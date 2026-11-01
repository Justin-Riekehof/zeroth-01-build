"""Motion/demo execution engine for the Zeroth-01 build.

One engine, two hosts: the local servo GUI (Windows, COM port) and the Pi
intent service (Linux). The engine owns the run lifecycle (one run at a
time, claimed atomically), the live state consumed by SSE/status endpoints,
and the safety semantics established during bring-up:

- every sweep/demo target is clamped to the configured joint limits
- mount offsets shift a joint's zero transparently (tick 2048 + offset)
- Stop/abort is an E-stop: everything goes limp, including held joints
- hold-center parks tested joints at center with verified torque; a
  watchdog re-parks joints that lose torque or drift
- settle passes compensate load sag so poses land where they were taught

Raises typed MotionError subclasses — hosts translate them to transport
errors (HTTP 400 etc.). Log strings are part of the observable behavior
(the regression suites assert on them); change them deliberately.
"""

import itertools
import json
import threading
import time
from types import SimpleNamespace

from pydantic import BaseModel, Field

from .bus import (CENTER_TICKS, POS_MAX_SAFE, POS_MIN_SAFE, ServoBusError,
                  SimBus, rel_deg_to_ticks, ticks_to_rel_deg)
from . import mocap
from .balance import TiltBalancer, pick_stance
from .config import ConfigStore, Demo, mirror_joint

POLL_S = 0.04          # position poll interval during a test
TELE_PERIOD_S = 0.05   # teleop control loop (20 Hz; the bus does 50-100 writes/s in total)
TELE_STALE_S = 1.0     # no fresh target for this long -> joints just hold
TELE_TIMEOUT_S = 10.0  # ... for this long -> teleop ends by itself (pose is held)
TELE_DEADBAND_DEG = 0.8  # below the servo's 10-count firmware deadband: do not re-command

ARM_JOINTS = ["left_shoulder_pitch", "left_shoulder_yaw", "left_elbow_yaw",
              "right_shoulder_pitch", "right_shoulder_yaw", "right_elbow_yaw"]
TOLERANCE = 25         # ticks (~2.2 deg), same as bench test

# reachable band in CAD degrees (seam-safe tick range), used to clamp limits
SEAM_MIN_DEG = round(ticks_to_rel_deg(POS_MIN_SAFE), 2)
SEAM_MAX_DEG = round(ticks_to_rel_deg(POS_MAX_SAFE), 2)


# Mount offsets: a servo mounted e.g. +90 deg off has its CAD zero at
# tick(180+90). All user-facing angles stay relative to the CAD zero; the
# offset only shifts the servo-tick mapping.

def to_ticks(rel_deg: float, offset: float = 0.0) -> int:
    return rel_deg_to_ticks(rel_deg + offset)


def to_rel(ticks: float, offset: float = 0.0) -> float:
    return ticks_to_rel_deg(ticks) - offset


def release_joints(bus, ids: dict[str, int],
                   joints: list[str] | None) -> list[int]:
    """Torque off for the given joints (None/empty -> all configured).
    Shared by the local GUI backend and the Pi intent service — one torque
    path for both modes. Returns the servo IDs actually released."""
    sel = joints or sorted(ids, key=lambda j: ids[j])
    released = []
    for j in sel:
        if j not in ids:
            continue
        try:
            bus.torque_off(ids[j])
            released.append(ids[j])
        except Exception:
            pass
    return released


def lock_joints(bus, ids: dict[str, int],
                joints: list[str] | None) -> list[int]:
    """Freeze joints at their CURRENT physical position (teach-in: fix an
    already hand-posed limb while posing the next one). The present position
    is re-commanded as the goal before enabling torque — enabling torque
    alone could snap the servo back to a stale goal from an earlier move.
    Returns the servo IDs actually locked (torque verified ON)."""
    sel = joints or sorted(ids, key=lambda j: ids[j])
    locked = []
    for j in sel:
        if j not in ids:
            continue
        sid = ids[j]
        try:
            bus.move(sid, bus.read_pos(sid), 200, 30)   # goal := here
            if bus.torque_on(sid):
                locked.append(sid)
        except Exception:
            pass
    return locked


class MotionError(Exception):
    """Engine-level rejection; hosts map it to a client error (HTTP 400)."""


class BusyError(MotionError):
    pass


class NotConnectedError(MotionError):
    pass


# ---------------------------------------------------------------- state

class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.bus = None                # Bus | None (real hardware)
        self.runner: threading.Thread | None = None
        self.abort = threading.Event()
        self.seq = 0
        self.live = {
            "running": False, "phase": "idle", "servo_id": None,
            "pos": None, "deg": None, "target": None, "error": None,
            "multi": None,           # {joint: deg} during group runs
            "log": [],
        }

    sinks: list = []                       # extra log consumers, e.g. the Pi's flight recorder

    def log(self, msg: str):
        with self.lock:
            self.seq += 1
            self.live["log"].append({"seq": self.seq, "msg": msg})
            self.live["log"] = self.live["log"][-300:]
        for sink in list(self.sinks):
            try:
                sink(msg)
            except Exception:
                pass

    def set(self, **kw):
        with self.lock:
            self.live.update(kw)

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.live))


# ---------------------------------------------------------------- params

class TestParams(BaseModel):
    servo_id: int = Field(1, ge=1, le=253)
    servo_model: str = "STS3250"
    # angles are relative to the center/mount position (0 deg = tick 2048)
    min_deg: float = Field(-90, ge=-180, le=180)
    max_deg: float = Field(90, ge=-180, le=180)
    speed: int = Field(300, ge=1, le=3400)
    acc: int = Field(30, ge=0, le=254)
    cycles: int = Field(1, ge=1, le=20)
    simulate: bool = False
    node: str | None = None            # clicked CAD node (for the log)
    joint: str | None = None           # CAD joint name (for limit enforcement)
    offset: float = Field(0, ge=-180, le=180)   # resolved engine-side


class CenterParams(BaseModel):
    servo_id: int = Field(1, ge=1, le=253)
    speed: int = Field(300, ge=1, le=3400)
    acc: int = Field(30, ge=0, le=254)
    simulate: bool = False
    joint: str | None = None
    offset: float = Field(0, ge=-180, le=180)   # resolved engine-side
    center_deg: float = Field(0, ge=-180, le=180)   # resolved engine-side (center pose override)
    hold_center: bool = False                   # keep torque on after centering


class GroupParams(BaseModel):
    joints: list[str] = Field(min_length=1)
    mode: str = Field("sequential", pattern="^(sequential|simultaneous)$")
    speed: int = Field(300, ge=1, le=3400)
    acc: int = Field(30, ge=0, le=254)
    cycles: int = Field(1, ge=1, le=20)
    simulate: bool = False
    # demo mode: after each joint's test, return it to center and keep torque
    # ON so the robot holds a stable pose. Stop/abort still releases everything.
    hold_center: bool = False


class TeleopParams(BaseModel):
    """Live teleoperation (motion capture): a client streams target angles,
    the engine follows them. Targets pass the same joint-limit clamp, mount
    offsets and power limits as every other move."""
    joints: list[str] = Field(default_factory=lambda: list(ARM_JOINTS), min_length=1)
    simulate: bool = False
    speed: int = Field(300, ge=1, le=3400)     # clamped by hardware/motion_limits.json
    acc: int = Field(30, ge=0, le=254)
    max_dps: float = Field(90, ge=5, le=360)   # slew limit of the commanded target
    smooth: float = Field(0.5, gt=0, le=1)     # EMA weight of the newest target (1 = none)


# ---------------------------------------------------------------- engine

class _BalanceSession:
    """IMU balance assist over a run of demo steps (see balance.py). Holds the
    controller across consecutive balanced steps, so its reference tilt and
    corrections carry over from one step to the next."""

    def __init__(self, eng, plan):
        self.eng, self.S = eng, eng.S
        self.by_joint = {e["joint"]: e for e in plan}
        self.cfg = eng.cfg.balance()
        self.ctrl: TiltBalancer | None = None
        self.base: dict[int, int] = {}       # sid -> uncorrected target ticks
        self.sent: dict[int, int] = {}       # sid -> last commanded ticks
        self.hold_ids: set[int] = set()
        self._warned = False
        self.t_last_log = 0.0

    def _tilt(self):
        src = self.eng.tilt_source
        try:
            return src() if src else None
        except Exception:
            return None

    def prepare(self, label: str, angles: dict, bus) -> bool:
        """Arm for one step. False = no assist (disabled / no IMU)."""
        if not self.cfg["enabled"]:
            return False
        t = self._tilt()
        if t is None:
            if not self._warned:
                self._warned = True
                self.S.log(f"{label}: balance assist skipped — no fresh IMU data")
            return False
        stance = pick_stance(self.cfg, {k: v for k, v in angles.items() if "knee" in k})
        if self.ctrl is None:
            ps, rs = [], []
            t_end = time.monotonic() + 0.3        # reference = tilt at rest, averaged
            while time.monotonic() < t_end:
                t = self._tilt() or t
                ps.append(t["pitch"]); rs.append(t["roll"])
                time.sleep(0.03)
            self.ctrl = TiltBalancer(self.cfg, stance)
            self.ctrl.set_reference(sum(ps) / len(ps), sum(rs) / len(rs))
            self.S.log(f"{label}: balance assist ON — reference pitch "
                       f"{self.ctrl.ref[0]:+.1f} deg, roll {self.ctrl.ref[1]:+.1f} deg"
                       + (" (DRY RUN: only logging)" if self.cfg["dry_run"] else ""))
        else:
            self.ctrl.set_stance(stance)
            self.ctrl.max_dev = (0.0, 0.0)
        self.S.log(f"{label}: balance stance {stance} -> "
                   + ", ".join(list(self.ctrl.pitch_joints) + list(self.ctrl.roll_joints)))
        return True

    def drop(self, label: str):
        if self.ctrl is not None:
            self.S.log(f"{label}: balance assist off (corrections released)")
        self.ctrl = None
        self.base.clear(); self.sent.clear()

    def begin(self, bus, targets: dict):
        """New move: remember the uncorrected targets of the balanced joints."""
        self.base = dict(targets)
        for j in self.ctrl.joints:
            e = self.by_joint.get(j)
            if e and e["id"] not in self.base:
                self.base[e["id"]] = bus.read_pos(e["id"])
        self.sent = dict(self.base)

    def step(self, bus, targets: dict | None = None) -> dict:
        """One control tick: read the tilt, command changed corrections.
        Returns {sid: corrected target ticks} for the balanced joints."""
        t = self._tilt()
        if t is None or self.ctrl is None:
            return {}
        off = self.ctrl.update(t["pitch"], t["roll"], t.get("g", 1000.0),
                               time.monotonic())
        out = {}
        for j, deg in off.items():
            e = self.by_joint.get(j)
            if not e or e["id"] not in self.base:
                continue
            sid = e["id"]
            if self.cfg["dry_run"]:
                deg = 0.0
            lo_t, hi_t = sorted((to_ticks(e["lo"], e["offset"]),
                                 to_ticks(e["hi"], e["offset"])))
            base_deg = to_rel(self.base[sid], e["offset"])
            tgt = max(lo_t, min(hi_t, to_ticks(base_deg + deg, e["offset"])))
            out[sid] = tgt
            if abs(tgt - self.sent.get(sid, tgt)) >= 3:
                self.eng._cmd(bus, sid, tgt, self.cfg["speed"], self.cfg["acc"])
                self.sent[sid] = tgt
        now = time.monotonic()
        if now - self.t_last_log > 0.5:
            self.t_last_log = now
            fp, fr = self.ctrl._f
            self.S.log(f"balance: pitch {fp - self.ctrl.ref[0]:+.1f} roll "
                       f"{fr - self.ctrl.ref[1]:+.1f} deg off ref; corrections "
                       + ", ".join(f"{j.replace('_pitch', '').replace('_', ' ')} {d:+.1f}"
                                   for j, d in off.items() if abs(d) >= 0.05 or
                                   j in {**self.ctrl.pitch_joints, **self.ctrl.roll_joints}))
        return out

    def summary(self, label: str):
        if self.ctrl:
            self.S.log(f"{label}: balance max deviation pitch "
                       f"{self.ctrl.max_dev[0]:.1f} deg, roll {self.ctrl.max_dev[1]:.1f} deg")


class MotionEngine:
    """Owns the (single) run lifecycle against one bus, plus the live state."""

    def __init__(self, cfg: ConfigStore):
        self.cfg = cfg
        self.S = State()
        self._clamped: set = set()          # (speed, acc) pairs already reported this run
        self._stagger_next = False          # stagger the FIRST group move of a run (see _stagger_waves)
        self._tele: SimpleNamespace | None = None   # active teleop session
        # () -> {"pitch","roll","g"} (deg, deg, mg) of the torso, or None: set
        # by the Pi service from the head IMU; None = no balance assist
        self.tilt_source = None
        self._mocap_state: dict = {}                # per-arm memory of the pose solver

    def _cmd(self, bus, sid: int, ticks: int, speed: int, acc: int,
             boost: bool = False) -> None:
        """The one place that commands a move: clamps speed/acc to the power
        limits (hardware/motion_limits.json) and logs each distinct clamp
        once per run. acc 0 (no ramp) is the hardest jolt and is clamped too.
        `boost` skips the clamp for a deliberate peak move (a demo step with
        "boost": true) — the pack sags accordingly, so use it sparingly."""
        if boost:
            bus.move(sid, ticks, int(speed), int(acc))
            return
        L = self.cfg.motion_limits()
        s2 = min(int(speed), L["max_speed"])
        a2 = L["max_acc"] if (acc == 0 or acc > L["max_acc"]) else int(acc)
        if (s2, a2) != (speed, acc) and (speed, acc) not in self._clamped:
            self._clamped.add((speed, acc))
            self.S.log(f"power limit: speed {speed} -> {s2}, acc {acc} -> {a2} "
                       "(hardware/motion_limits.json)")
        bus.move(sid, ticks, s2, a2)

    # ------------------------------------------------------ single-servo

    def _move_and_wait(self, bus, p, target: int, label: str):
        S = self.S
        off = p.offset
        start = bus.read_pos(p.servo_id)
        self._cmd(bus, p.servo_id, target, p.speed, p.acc)
        S.set(target=to_rel(target, off), phase=label)
        timeout = abs(target - start) / p.speed + 2.0
        t0 = time.monotonic()
        while True:
            if S.abort.is_set():
                raise ServoBusError("aborted by user")
            pos = bus.read_pos(p.servo_id)
            S.set(pos=pos, deg=to_rel(pos, off))
            if abs(pos - target) <= TOLERANCE:
                S.log(f"reached {to_rel(target, off):+.1f} deg "
                      f"(actual {to_rel(pos, off):+.1f} deg)")
                return
            if time.monotonic() - t0 > timeout:
                S.log(f"WARNING: target {to_rel(target, off):+.1f} deg not "
                      f"reached after {timeout:.1f} s "
                      f"(actual {to_rel(pos, off):+.1f} deg)")
                return
            time.sleep(POLL_S)

    def _start_and_ping(self, bus, p) -> None:
        S = self.S
        S.set(phase="ping")
        model = bus.ping(p.servo_id)
        S.log(f"servo ID {p.servo_id} responds (model {model}"
              f"{', simulated' if bus.simulated else ''})")
        if p.offset:
            S.log(f"mount offset {p.offset:+.1f} deg (zero = tick "
                  f"{to_ticks(0, p.offset)})")
        pos = bus.read_pos(p.servo_id)
        S.set(pos=pos, deg=to_rel(pos, p.offset))
        S.log(f"start position {to_rel(pos, p.offset):+.1f} deg")

    def _test_body(self, bus, p: TestParams):
        S = self.S
        lo, hi = to_ticks(p.min_deg, p.offset), to_ticks(p.max_deg, p.offset)
        self._move_and_wait(bus, p, lo, "to lower limit")
        for i in range(p.cycles):
            tag = f" (cycle {i + 1}/{p.cycles})" if p.cycles > 1 else ""
            self._move_and_wait(bus, p, hi, "sweep up" + tag)
            self._move_and_wait(bus, p, lo, "sweep down" + tag)
        S.log("test finished")

    def _center_body(self, bus, p):
        S = self.S
        target = to_ticks(p.center_deg, p.offset)
        label = ("to center (mount position)" if not p.center_deg
                 else f"to center pose ({p.center_deg:+.1f} deg)")
        self._move_and_wait(bus, p, target, label)
        if p.hold_center:
            ok = bus.torque_on(p.servo_id)
            S.log(f"center reached: {p.center_deg:+.1f} deg (tick {target}) — holding, torque "
                  + ("ON (verified)" if ok else "state UNVERIFIED, check servo!"))
            return True                  # tell _run to keep torque on
        S.log(f"center reached: {p.center_deg:+.1f} deg (tick {target}) — "
              + ("mount the part now" if not p.center_deg else "center pose override"))
        return False

    # ------------------------------------------------------ group helpers

    def _move_all_and_wait(self, bus, p, plan, targets: dict, label: str,
                           held: set | None = None, settle: bool = False,
                           stagger: bool | None = None,
                           balance=None, sync: bool = False):
        """Command several servos at once and poll until all reached (or
        timeout). Servos in `held` (parked, holding) are read too, so their
        live angle is streamed while OTHER joints test.

        settle=True adds a load-sag compensation pass: under load the servo's
        P-controller parks short of the goal (steady-state error); we measure
        the residual and over-command by it (clamped to the joint limits) so
        the ACTUAL pose matches the taught pose. Used for demo steps and
        centering, not for range sweeps.

        stagger controls the staggered start (see below): None keeps the
        per-run default (first move only), True/False force it for this move.

        sync=True scales each servo's speed by its distance, so all of them
        arrive together: the path between two stable poses is then a straight
        line in joint space instead of "short joints first". It replaces the
        staggered start.

        balance is a _Balance session (IMU assist): while waiting, its
        corrections are added to the stance joints' targets."""
        S = self.S
        id2joint = {e["id"]: e["joint"] for e in plan}
        id2off = {e["id"]: e.get("offset", 0.0) for e in plan}
        by_id = {e["id"]: e for e in plan}
        watch = [sid for sid in (held or set())
                 if sid in id2joint and sid not in targets]
        starts = {sid: bus.read_pos(sid) for sid in targets}
        # Staggered start: the servos leave in mirror-pair waves (stagger_ms
        # apart) instead of all at once. 16 servos leaving torque-off at the
        # same instant is the biggest current spike the pack sees (the Pi
        # dropped off the network on a plain "center" with the robot in the
        # air), and a simultaneous start is also the harder lunge — a demo step
        # that has to lift the body wants the spread, one that lowers it does
        # not. Default (stagger=None): the FIRST move of a run only, because
        # that is the one leaving torque-off. True/False override per move.
        want = self._stagger_next if stagger is None else bool(stagger)
        self._stagger_next = False
        stagger_s = (self.cfg.motion_limits().get("stagger_ms", 0) / 1000.0
                     if want else 0.0)
        speeds = {sid: p.speed for sid in targets}
        if sync:
            stagger_s = 0.0
            far = max(abs(t - starts[sid]) for sid, t in targets.items()) or 1
            speeds = {sid: max(20, min(p.speed, int(p.speed * abs(t - starts[sid]) / far)))
                      for sid, t in targets.items()}
        eff = dict(targets)                  # targets + balance corrections
        if balance:
            balance.begin(bus, targets)
        for k, wave in enumerate(self._stagger_waves(targets, plan)):
            if k and stagger_s > 0:
                time.sleep(stagger_s)
            for sid in wave:
                self._cmd(bus, sid, targets[sid], speeds[sid], p.acc,
                          boost=getattr(p, "boost", False))
        S.set(phase=label)
        timeout = max(abs(t - starts[sid]) for sid, t in targets.items()) \
            / p.speed + 2.0
        t0 = time.monotonic()
        reached = False
        while True:
            if S.abort.is_set():
                raise ServoBusError("aborted by user")
            done = True
            multi = dict(S.snapshot().get("multi") or {})
            if balance:
                eff.update(balance.step(bus, targets))
            for sid, t in targets.items():
                pos = bus.read_pos(sid)
                multi[id2joint[sid]] = to_rel(pos, id2off[sid])
                if abs(pos - eff[sid]) > TOLERANCE:
                    done = False
            for sid in watch:                    # live view of holding joints
                try:
                    multi[id2joint[sid]] = to_rel(bus.read_pos(sid),
                                                  id2off[sid])
                except ServoBusError:
                    pass
            S.set(multi=multi)
            if done:
                reached = True
                break
            if time.monotonic() - t0 > timeout:
                break
            time.sleep(POLL_S)

        if settle:
            corrected = False
            for _ in range(2):                   # at most two trim iterations
                trims = {}
                for sid, t in eff.items():
                    if sid not in targets:
                        continue
                    err = t - bus.read_pos(sid)
                    if 10 < abs(err) <= 300:     # sag-sized, not a blockage
                        e = by_id[sid]
                        lo_t, hi_t = sorted((to_ticks(e["lo"], e["offset"]),
                                             to_ticks(e["hi"], e["offset"])))
                        cmd = max(lo_t, min(hi_t, t + err))
                        if cmd != t:
                            trims[sid] = cmd
                if not trims:
                    break
                corrected = True
                for sid, cmd in trims.items():
                    self._cmd(bus, sid, cmd, 150, 30)  # slow trim move
                t1 = time.monotonic() + 0.45
                while time.monotonic() < t1:
                    if S.abort.is_set():
                        raise ServoBusError("aborted by user")
                    time.sleep(POLL_S)
            resid = []
            multi = dict(S.snapshot().get("multi") or {})
            for sid, t in targets.items():
                t = eff[sid]
                pos = bus.read_pos(sid)
                multi[id2joint[sid]] = to_rel(pos, id2off[sid])
                if abs(t - pos) > TOLERANCE:
                    resid.append(f"{id2joint[sid]} "
                                 f"{(pos - t) * 360 / 4096:+.1f} deg")
            S.set(multi=multi)
            if corrected:
                S.log(f"{label}: load sag compensated")
            if resid:
                S.log(f"WARNING: {label}: residual pose error: "
                      + ", ".join(resid))

        if reached:
            S.log(f"{label}: all targets reached")
        else:
            S.log(f"WARNING: {label}: not all targets reached "
                  f"after {timeout:.1f} s")

    @staticmethod
    def _stagger_waves(targets, plan) -> list[list[int]]:
        """Group the servo IDs of one move into waves for the staggered start.
        A joint and its mirror (left_knee_pitch / right_knee_pitch) share a
        wave, so a symmetric pose still starts symmetrically; everything else
        follows in ID order."""
        id2joint = {e["id"]: e["joint"] for e in plan}
        joint2id = {j: sid for sid, j in id2joint.items()}
        waves, seen = [], set()
        for sid in targets:
            if sid in seen:
                continue
            wave = [sid]
            m = mirror_joint(id2joint.get(sid, ""))
            partner = joint2id.get(m) if m else None
            if partner is not None and partner in targets and partner not in seen:
                wave.append(partner)
            seen.update(wave)
            waves.append(wave)
        return waves

    def _hold(self, bus, e, held: set):
        """Park confirmation: explicitly enable torque (verified by read-back)
        instead of trusting that the position command left it on."""
        ok = bus.torque_on(e["id"])
        held.add(e["id"])
        self.S.log(f"{e['joint']} holding center — torque "
                   + ("ON (verified)" if ok else "state UNVERIFIED, check servo!"))

    def _check_held(self, bus, plan, held: set, center_t: dict):
        """Hold watchdog, two failure modes:
        - torque bit dropped (servo reset / protection kicked in) -> re-park
        - torque ON but position drifted off center (controller not holding
          the load, or goal lost) -> log the deviation and re-command
        Self-healing plus diagnosis: the log tells WHICH mode occurred."""
        S = self.S
        for e in plan:
            sid = e["id"]
            if sid not in held:
                continue
            try:
                tq = bus.read_torque(sid)
                pos = bus.read_pos(sid)
                dev = abs(pos - center_t[sid])
                if tq == 1 and dev <= 3 * TOLERANCE:
                    continue
                if tq != 1:
                    S.log(f"WARNING: {e['joint']} (ID {sid}) LOST torque "
                          f"(reg={tq}; reset/protection?) — re-parking at center")
                else:
                    S.log(f"WARNING: {e['joint']} (ID {sid}) torque ON but "
                          f"drifted {dev * 360 / 4096:.1f} deg off center "
                          f"(holding too weak / goal lost?) — re-commanding")
                self._cmd(bus, sid, center_t[sid], 300, 30)
                bus.torque_on(sid)
            except ServoBusError:
                S.log(f"WARNING: ID {sid} not responding during hold check")

    def _center_note(self, plan):
        """Log which joints center away from 0 deg (center pose override)."""
        ov = [e for e in plan if e["center"]]
        if ov:
            self.S.log("center pose override: "
                       + ", ".join(f"{e['joint']} {e['center']:+.1f} deg"
                                   + (" (clamped to limits)" if e.get("center_clamped") else "")
                                   for e in ov))

    def _group_center_body(self, bus, p, plan, held: set):
        self._center_note(plan)
        self._move_all_and_wait(bus, p, plan,
                                {e["id"]: to_ticks(e["center"], e["offset"])
                                 for e in plan},
                                "group: to center", settle=True)
        if p.hold_center:
            for e in plan:
                self._hold(bus, e, held)
        self.S.log("all selected servos at center ("
                   + ("+0.0 deg" if not any(e["center"] for e in plan) else "center pose")
                   + ", mount offsets applied)")

    def _group_test_body(self, bus, p, plan, held: set):
        S = self.S
        center_t = {e["id"]: to_ticks(e["center"], e["offset"]) for e in plan}
        if p.hold_center:
            self._center_note(plan)
        if p.mode == "simultaneous":
            lo_t = {e["id"]: to_ticks(e["lo"], e["offset"]) for e in plan}
            hi_t = {e["id"]: to_ticks(e["hi"], e["offset"]) for e in plan}
            self._move_all_and_wait(bus, p, plan, lo_t, "group: to lower limits")
            for i in range(p.cycles):
                tag = f" (cycle {i + 1}/{p.cycles})" if p.cycles > 1 else ""
                self._move_all_and_wait(bus, p, plan, hi_t,
                                        "group: sweep up" + tag)
                self._move_all_and_wait(bus, p, plan, lo_t,
                                        "group: sweep down" + tag)
            if p.hold_center:
                self._move_all_and_wait(bus, p, plan, center_t,
                                        "group: back to center (hold)",
                                        settle=True)
                for e in plan:
                    self._hold(bus, e, held)
        else:                                    # sequential, ascending ID
            for e in plan:
                S.log(f"--- {e['joint']} (ID {e['id']}) "
                      f"[{e['lo']:+.1f}, {e['hi']:+.1f}] deg ---")
                lo = {e["id"]: to_ticks(e["lo"], e["offset"])}
                hi = {e["id"]: to_ticks(e["hi"], e["offset"])}
                self._move_all_and_wait(bus, p, plan, lo,
                                        f"{e['joint']}: to lower limit", held)
                self._check_held(bus, plan, held, center_t)
                for i in range(p.cycles):
                    tag = f" (cycle {i + 1}/{p.cycles})" if p.cycles > 1 else ""
                    self._move_all_and_wait(bus, p, plan, hi,
                                            f"{e['joint']}: sweep up" + tag,
                                            held)
                    self._move_all_and_wait(bus, p, plan, lo,
                                            f"{e['joint']}: sweep down" + tag,
                                            held)
                    self._check_held(bus, plan, held, center_t)
                if p.hold_center:
                    # demo mode: park this joint at center and keep torque ON
                    # so the already-tested chain stays stable
                    self._move_all_and_wait(bus, p, plan,
                                            {e["id"]: center_t[e["id"]]},
                                            f"{e['joint']}: back to center (hold)",
                                            held, settle=True)
                    self._hold(bus, e, held)
                else:
                    bus.torque_off(e["id"])
            self._check_held(bus, plan, held, center_t)   # final sanity pass
        S.log("group test finished")

    # ------------------------------------------------------ run wrappers

    def _run_group(self, bus, p, plan, body):
        S = self.S
        held: set[int] = set()      # ids parked at center that keep torque ON
        success = False
        try:
            S.set(phase="ping")
            responding = []
            for e in plan:
                try:
                    model = bus.ping(e["id"])
                except ServoBusError:
                    S.log(f"WARNING: ID {e['id']} ({e['joint']}) does not "
                          f"respond — skipped (not wired yet?)")
                    continue
                S.log(f"ID {e['id']} ({e['joint']}) responds (model {model}"
                      f"{', simulated' if bus.simulated else ''})")
                responding.append(e)
            if not responding:
                raise ServoBusError("none of the selected servos responds")
            plan = responding
            body(bus, p, plan, held)
            S.set(phase="done")
            success = True
        except ServoBusError as e:
            if S.abort.is_set():
                S.set(phase="aborted")
                S.log("group run aborted")
            else:
                S.set(phase="error", error=str(e))
                S.log(f"ERROR: {e}")
        except Exception as e:                                  # noqa: BLE001
            S.set(phase="error", error=repr(e))
            S.log(f"ERROR: {e!r}")
        finally:
            # on success, servos parked at center keep holding (demo mode);
            # on Stop/error everything goes limp — abort stays an E-stop
            keep = held if success else set()
            for e in plan:
                if e["id"] in keep:
                    continue
                try:
                    bus.torque_off(e["id"])
                except Exception:
                    pass
            if keep:
                S.log(f"holding center with torque ON: IDs {sorted(keep)} — "
                      "use 'release torque' to let go")
            else:
                S.log("torque disabled (all selected)")
            if bus.simulated:
                bus.close()
            S.set(running=False, target=None, multi=None, pos=None, deg=None)

    def _run(self, bus, p, body):
        S = self.S
        hold = False    # body returns True when the servo should keep holding
        success = False
        try:
            self._start_and_ping(bus, p)
            hold = bool(body(bus, p))
            S.set(phase="done")
            success = True
        except ServoBusError as e:
            if S.abort.is_set():
                S.set(phase="aborted")
                S.log("test aborted")
            else:
                S.set(phase="error", error=str(e))
                S.log(f"ERROR: {e}")
        except Exception as e:                                  # noqa: BLE001
            S.set(phase="error", error=repr(e))
            S.log(f"ERROR: {e!r}")
        finally:
            if success and hold:
                S.log(f"ID {p.servo_id} keeps holding — "
                      "'release torque' lets go")
            else:
                try:
                    bus.torque_off(p.servo_id)
                    S.log("torque disabled")
                except Exception:
                    S.log("WARNING: could not disable torque")
            if bus.simulated:
                bus.close()
            S.set(running=False, target=None, pos=None, deg=None)

    # ------------------------------------------------------ launchers

    def _claim_run_slot(self):
        """Atomically claim the single run slot (TOCTOU-safe)."""
        S = self.S
        with S.lock:
            if S.live["running"]:
                raise BusyError("A run is already in progress.")
            bus = S.bus
            S.live["running"] = True
        return bus

    def _resolve_bus(self, bus, simulate: bool):
        try:
            if simulate:
                return SimBus(start_ticks=CENTER_TICKS)
            if not bus:
                raise NotConnectedError(
                    "Not connected (or enable simulation).")
            return bus
        except Exception:
            self.S.set(running=False)    # release the slot on rejected launch
            raise

    def _launch(self, p, body, banner: str):
        S = self.S
        bus = self._resolve_bus(self._claim_run_slot(), p.simulate)
        S.abort.clear()
        self._clamped = set()
        self._stagger_next = True
        S.set(phase="starting", servo_id=p.servo_id, error=None)
        S.log(banner)
        t = threading.Thread(target=self._run, args=(bus, p, body),
                             daemon=True)
        with S.lock:
            S.runner = t
        t.start()

    def _launch_group(self, p, plan, body, banner: str,
                      warn_unlimited: bool = True):
        S = self.S
        bus = self._resolve_bus(self._claim_run_slot(), p.simulate)
        S.abort.clear()
        self._clamped = set()
        self._stagger_next = True
        S.set(phase="starting", servo_id=None, error=None, multi={})
        S.log(banner)
        if warn_unlimited:
            for e in plan:
                if not e["limited"]:
                    S.log(f"WARNING: no limits configured for {e['joint']} — "
                          f"using safe default [-30, +30] deg")
        t = threading.Thread(target=self._run_group,
                             args=(bus, p, plan, body), daemon=True)
        with S.lock:
            S.runner = t
        t.start()

    def build_plan(self, joints_sel: list[str]) -> list[dict]:
        ids = self.cfg.servo_ids()
        lims = self.cfg.limits()
        offs = self.cfg.offsets()
        cpose = self.cfg.center_pose()
        plan = []
        for j in joints_sel:
            if j not in ids:
                raise MotionError(f"No servo ID configured for '{j}' "
                                  "(hardware/servo_ids.json).")
            L = lims.get(j)
            lo, hi = (L["min_deg"], L["max_deg"]) if L else (-30.0, 30.0)
            # calibration sanity: the limit band must contain the joint's own
            # zero (= center/mount pose). A band like [+90, +176] is almost
            # certainly corrupt (e.g. a re-zero shifted the limits and a
            # manual offset edit didn't shift them back) — clamping a taught
            # ~0 deg pose against it would SLAM the joint to the band edge.
            if lo > hi:
                raise MotionError(f"Corrupt limits for {j}: min {lo:+.1f} > "
                                  f"max {hi:+.1f} — fix "
                                  "hardware/joint_limits.json first.")
            if lo > 0 or hi < 0:
                raise MotionError(
                    f"Limits of {j} [{lo:+.1f}, {hi:+.1f}] exclude its zero "
                    "position — calibration looks corrupt (re-zero vs manual "
                    "offset edit?). Re-measure and save limits before "
                    "running.")
            # center pose override (hardware/center_pose.json), kept inside the
            # joint's safe band so a stale override can never slam a limit
            c_raw = float(cpose.get(j, 0.0)) if isinstance(cpose.get(j, 0.0), (int, float)) else 0.0
            c = max(lo, min(hi, c_raw))
            plan.append({"joint": j, "id": ids[j], "lo": lo, "hi": hi,
                         "limited": bool(L),
                         "offset": float(offs.get(j, 0.0)),
                         "center": c, "center_clamped": c != c_raw})
        plan.sort(key=lambda e: e["id"])
        return plan

    # ------------------------------------------------------ public intents

    def stop(self):
        self.S.abort.set()

    def start_test(self, p: TestParams):
        S = self.S
        if p.min_deg >= p.max_deg:
            raise MotionError("min must be smaller than max.")
        # safety: never sweep beyond configured joint limits
        lims = self.cfg.limits().get(p.joint) if p.joint else None
        if lims:
            lo = max(p.min_deg, lims["min_deg"])
            hi = min(p.max_deg, lims["max_deg"])
            if lo >= hi:
                raise MotionError(f"Interval lies outside the configured "
                                  f"limits [{lims['min_deg']:+.1f}, "
                                  f"{lims['max_deg']:+.1f}] of {p.joint}.")
            if (lo, hi) != (p.min_deg, p.max_deg):
                S.log(f"interval clamped to configured limits "
                      f"[{lo:+.1f}, {hi:+.1f}] deg of {p.joint} "
                      f"(save new limits to widen)")
                p = p.model_copy(update={"min_deg": lo, "max_deg": hi})
        if p.joint:
            off = float(self.cfg.offsets().get(p.joint, 0.0))
            p = p.model_copy(update={"offset": off})
            # detect seam clamping of the offset-shifted endpoints (otherwise
            # a truncated / no-op sweep would still be reported as 'reached')
            lo_t, hi_t = to_ticks(p.min_deg, off), to_ticks(p.max_deg, off)
            if lo_t == hi_t:
                raise MotionError(f"Interval not reachable for {p.joint} "
                                  f"with mount offset {off:+.1f} deg — both "
                                  "ends fall outside the seam-safe range.")
            got_lo, got_hi = to_rel(lo_t, off), to_rel(hi_t, off)
            if abs(got_lo - p.min_deg) > 0.5 or abs(got_hi - p.max_deg) > 0.5:
                S.log(f"NOTE: sweep truncated to reachable band "
                      f"[{got_lo:+.1f}, {got_hi:+.1f}] deg "
                      f"(mount offset {off:+.1f} deg near the encoder seam)")
        self._launch(p, self._test_body,
                     f"--- test: ID {p.servo_id} ({p.servo_model}"
                     f"{', ' + p.node if p.node else ''}) "
                     f"{p.min_deg:+.1f}..{p.max_deg:+.1f} deg, "
                     f"speed {p.speed}, "
                     f"{'SIMULATION' if p.simulate else 'hardware'} ---")

    def start_center(self, p: CenterParams):
        if p.joint:
            c = self.cfg.center_pose().get(p.joint, 0.0)
            c = float(c) if isinstance(c, (int, float)) else 0.0
            L = self.cfg.limits().get(p.joint)
            if L:                                    # keep the override inside the safe band
                c = max(float(L["min_deg"]), min(float(L["max_deg"]), c))
            p = p.model_copy(
                update={"offset": float(self.cfg.offsets().get(p.joint, 0.0)),
                        "center_deg": c})
        self._launch(p, self._center_body,
                     f"--- move to center: ID {p.servo_id}, speed {p.speed}, "
                     + (f"center pose {p.center_deg:+.1f} deg, " if p.center_deg else "")
                     + f"{'SIMULATION' if p.simulate else 'hardware'} ---")

    def start_group(self, p: GroupParams, kind: str):
        plan = self.build_plan(p.joints)
        body = (self._group_center_body if kind == "center"
                else self._group_test_body)
        self._launch_group(
            p, plan, body,
            f"--- group {kind}: "
            + ", ".join(f"ID {e['id']} ({e['joint']})" for e in plan)
            + f", {p.mode}, {'SIMULATION' if p.simulate else 'hardware'} ---")
        return plan

    @staticmethod
    def settle_for(step, last: bool) -> bool:
        """Load-sag settling costs up to ~1 s per step (slow trim moves + waits).
        Transit steps (pause 0, not the last) skip it so a sequence flows;
        steps that are held (pause > 0) and the final pose get it. An explicit
        `settle` on the step overrides the rule."""
        s = getattr(step, "settle", None)
        if s is not None:
            return bool(s)
        return bool(step.pause_s) or last

    @staticmethod
    def stagger_for(step, first: bool) -> bool:
        """Whether this demo step starts its servos in waves instead of all at
        once. Default (no `stagger` on the step): only the FIRST move of a run,
        which is the one leaving torque-off. Steps that have to LIFT the body
        want it set True — the spread keeps the inrush off the pack and turns
        the lunge into a push. Steps that LOWER the body (sitting down, going
        to the knees) want it off, or the leading wave is already carrying
        weight before the rest arrives and the robot folds."""
        s = getattr(step, "stagger", None)
        if s is not None:
            return bool(s)
        return first

    def play_demo(self, demo: Demo, simulate: bool, until: int | None = None,
                  start: int | None = None, loops: int = 1):
        """Run a taught-in demo: per step, move all its joints simultaneously
        (clamped to limits, offsets applied, settle pass), honor pauses, and
        hold the final pose.

        `start` and `until` (both 1-based and inclusive) select a range of
        steps. `until` alone stops after that step, `start == until` moves
        straight to that one pose without running the steps before it — each
        step keeps its own speed/acc either way. Step numbers in the log stay
        the ones from the editor.

        `loops` repeats the selected range: n >= 1 times, -1 = until stopped
        (stop/abort ends it between or during moves; the last pose is held)."""
        if loops != -1 and loops < 1:
            raise MotionError("loops must be >= 1, or -1 for endless.")
        n_all = len(demo.steps)
        lo = 1 if start is None else start
        hi = n_all if until is None else until
        if not 1 <= lo <= n_all or not 1 <= hi <= n_all:
            raise MotionError(f"Step out of range (demo has {n_all} steps).")
        if lo > hi:
            raise MotionError(f"Step {lo} lies after step {hi} — empty range.")
        numbered = list(enumerate(demo.steps, 1))[lo - 1:hi]
        S = self.S
        ids = self.cfg.servo_ids()
        used = list(dict.fromkeys(
            j for _, s in numbered for j in s.angles if j in ids))
        unknown = sorted({j for _, s in numbered for j in s.angles} - set(used))
        if not used:
            raise MotionError("Demo uses no configured joints.")
        plan = self.build_plan(used)

        def body(bus, bp, plan, held):
            if unknown:
                S.log(f"NOTE: unknown joints skipped: {', '.join(unknown)}")
            by_joint = {e["joint"]: e for e in plan}
            moved: set[int] = set()
            n = n_all
            stagger_ms = self.cfg.motion_limits().get("stagger_ms", 0)
            if lo > 1:
                S.log(f"direct move: starting at step {lo}"
                      + (f" of {n}" if hi == n else f", stopping after {hi}")
                      + " — the earlier steps are skipped")
            bal = _BalanceSession(self, plan)
            reps = itertools.count(1) if loops == -1 else range(1, loops + 1)
            for rep in reps:
                last_rep = loops != -1 and rep == loops
                if loops != 1:
                    S.log(f"demo '{demo.name}': loop {rep}" + ("" if loops == -1 else f"/{loops}"))
                for i, step in numbered:
                    sp = SimpleNamespace(speed=step.speed, acc=step.acc)
                    targets, clamped, deg_of = {}, [], {}
                    # a center step ("center": true, or every angle exactly 0 = the
                    # old "+ center" steps) follows the center pose override
                    is_center = bool(getattr(step, "center", False)) or (
                        bool(step.angles) and all(abs(v) < 1e-6 for v in step.angles.values()))
                    if is_center:
                        ov = [f"{e['joint']} {e['center']:+.1f}" for e in plan if e["center"]]
                        S.log(f"step {i}: center step -> "
                              + (f"center pose override ({', '.join(ov)} deg), 0 deg elsewhere"
                                 if ov else "mount pose (all 0 deg, no override set)"))
                    for j, deg in step.angles.items():
                        e = by_joint.get(j)
                        if not e:
                            continue
                        if is_center:
                            deg = e["center"]
                        d = max(e["lo"], min(e["hi"], deg))
                        if d != deg:
                            clamped.append(f"{j} {deg:+.1f}->{d:+.1f}")
                        targets[e["id"]] = to_ticks(d, e["offset"])
                        deg_of[e["id"]] = d
                    if clamped:
                        S.log(f"step {i}: clamped to joint limits: "
                              + ", ".join(clamped))
                    if not targets:
                        S.log(f"step {i}: no responding joints — skipped")
                        continue
                    moved.update(targets)
                    title = getattr(step, "title", "") or ""
                    if getattr(step, "boost", False):
                        sp.boost = True
                        S.log(f"step {i}: POWER BOOST — speed {step.speed}, acc "
                              f"{step.acc}, power limits bypassed (peak current!)")
                    stag = self.stagger_for(step, i == lo and rep == 1)
                    use_bal = False
                    if getattr(step, "balance", False):
                        knees = {j: deg_of[e["id"]] for j, e in by_joint.items()
                                 if "knee" in j and e["id"] in deg_of}
                        use_bal = bal.prepare(f"step {i}", knees, bus)
                    elif bal.ctrl is not None:
                        bal.drop(f"step {i}")
                    sync = getattr(step, "sync", None)
                    sync = use_bal if sync is None else bool(sync)
                    if sync:
                        S.log(f"step {i}: synchronised joint arrival")
                    if stag and not (i == lo and rep == 1):
                        S.log(f"step {i}: staggered start (waves {stagger_ms} ms apart)")
                    self._move_all_and_wait(bus, sp, plan, targets,
                                            f"demo '{demo.name}' step {i}/{n}"
                                            + (f" ({title})" if title else ""),
                                            held, settle=self.settle_for(step, i == hi and last_rep),
                                            stagger=stag, sync=sync,
                                            balance=bal if use_bal else None)
                    if step.pause_s:
                        deadline = time.monotonic() + step.pause_s
                        while time.monotonic() < deadline:
                            if S.abort.is_set():
                                raise ServoBusError("aborted by user")
                            if use_bal:
                                bal.step(bus)    # keep balancing while it waits
                            time.sleep(0.05 if not use_bal else POLL_S)
                    if use_bal:
                        bal.summary(f"step {i}")
            # demos end in a defined pose: hold it (release via release-torque)
            for e in plan:
                if e["id"] in moved:
                    self._hold(bus, e, held)
            S.log(f"demo '{demo.name}' finished — holding final pose"
                  + (f" (steps {lo}..{hi} of {n_all})" if (lo, hi) != (1, n_all) else ""))

        # warn_unlimited=False: the pre-refactor demo launch never warned
        # about limits-less joints (only group runs do) — log parity matters
        self._launch_group(
            p=SimpleNamespace(simulate=simulate),
            plan=plan, body=body,
            banner=f"--- demo '{demo.name}': "
                   + (f"{len(numbered)} steps" if (lo, hi) == (1, n_all)
                      else f"step{'s' if lo != hi else ''} {lo}..{hi} of {n_all}") + ", "
                   f"{len(plan)} joints, "
                   f"{'SIMULATION' if simulate else 'hardware'} ---",
            warn_unlimited=False)
        return plan

    # ------------------------------------------------------ teleoperation

    def _teleop_body(self, bus, p, plan, held):
        """Follow the streamed targets until stopped. Starts from the CURRENT
        physical pose (goal := here, then torque on), so enabling it never
        makes the arms jump; the first targets are approached at max_dps."""
        S, tl = self.S, self._tele
        cmd, sent = {}, {}
        for e in plan:
            pos = bus.read_pos(e["id"])
            bus.move(e["id"], pos, 200, 30)
            if not bus.torque_on(e["id"]):
                S.log(f"WARNING: {e['joint']} torque state UNVERIFIED, check servo!")
            held.add(e["id"])
            cmd[e["joint"]] = sent[e["joint"]] = to_rel(pos, e["offset"])
        S.set(multi=dict(cmd), phase="teleop")
        S.log(f"teleop active: {', '.join(e['joint'] for e in plan)} "
              f"(slew {p.max_dps:.0f} deg/s) — targets clamped to the joint limits")
        by_joint = {e["joint"]: e for e in plan}
        ema = dict(cmd)
        prev = time.monotonic()
        stale = False
        try:
            while not tl.stop.is_set():
                if S.abort.is_set():
                    raise ServoBusError("aborted by user")
                now = time.monotonic()
                dt, prev = now - prev, now
                with tl.lock:
                    targets, age = dict(tl.targets), now - tl.stamp
                if age > TELE_TIMEOUT_S:
                    S.log(f"teleop: no input for {TELE_TIMEOUT_S:.0f} s — ended, holding pose")
                    break
                if age > TELE_STALE_S:
                    if not stale:
                        S.log("teleop: input lost — holding the last pose")
                    stale = True
                else:
                    if stale:
                        S.log("teleop: input back")
                    stale = False
                    step = p.max_dps * max(dt, 1e-3)
                    for j, deg in targets.items():
                        e = by_joint.get(j)
                        if e is None:           # not responding on the bus
                            continue
                        d = max(e["lo"], min(e["hi"], deg))
                        ema[j] += p.smooth * (d - ema[j])
                        cmd[j] += max(-step, min(step, ema[j] - cmd[j]))
                for j, e in by_joint.items():
                    if abs(cmd[j] - sent[j]) >= TELE_DEADBAND_DEG:
                        self._cmd(bus, e["id"], to_ticks(cmd[j], e["offset"]),
                                  p.speed, p.acc)
                        sent[j] = cmd[j]
                S.set(multi=dict(cmd))
                time.sleep(max(0.0, TELE_PERIOD_S - (time.monotonic() - now)))
            else:
                S.log("teleop stopped — holding the current pose")
        finally:
            tl.active = False

    def start_teleop(self, p: TeleopParams):
        plan = self.build_plan(p.joints)
        self._mocap_state.clear()
        prev = self._tele
        self._tele = SimpleNamespace(lock=threading.Lock(), targets={}, stamp=time.monotonic(),
                                     stop=threading.Event(), active=True,
                                     joints={e["joint"] for e in plan})
        try:
            self._launch_group(
                p, plan, self._teleop_body,
                f"--- teleop: {len(plan)} joints, "
                f"{'SIMULATION' if p.simulate else 'hardware'} ---")
        except Exception:
            self._tele = prev
            raise
        return plan

    def teleop_target(self, angles: dict[str, float]) -> int:
        """Latest target angles (CAD-frame deg). Unknown joints are ignored;
        clamping to the limits happens in the loop. Returns how many were taken."""
        tl = self._tele
        if tl is None or not tl.active:
            raise MotionError("Teleop is not active.")
        take = {j: float(d) for j, d in angles.items()
                if j in tl.joints and isinstance(d, (int, float)) and abs(d) <= 360}
        with tl.lock:
            tl.targets.update(take)
            tl.stamp = time.monotonic()
        return len(take)

    def mocap_pose(self, landmarks, mirror: bool = False,
                   flip_forward: bool = False) -> tuple[dict, dict]:
        """One camera frame: world landmarks -> arm angles (clamped to the
        joint limits). While teleop is active they are also the new targets;
        otherwise this is a pure preview (nothing moves)."""
        angles, info = mocap.arm_angles(landmarks, self.cfg.limits(),
                                        self._mocap_state, mirror, flip_forward)
        tl = self._tele
        info["active"] = bool(tl and tl.active)
        if info["active"] and angles:
            self.teleop_target(angles)
        return angles, info

    def stop_teleop(self):
        """Orderly end: the arms keep holding their pose (E-stop is `stop`)."""
        tl = self._tele
        if tl is not None:
            tl.stop.set()
