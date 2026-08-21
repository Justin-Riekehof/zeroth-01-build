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

import json
import threading
import time
from types import SimpleNamespace

from pydantic import BaseModel, Field

from .bus import (CENTER_TICKS, POS_MAX_SAFE, POS_MIN_SAFE, ServoBusError,
                  SimBus, rel_deg_to_ticks, ticks_to_rel_deg)
from .config import ConfigStore, Demo

POLL_S = 0.04          # position poll interval during a test
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

    def log(self, msg: str):
        with self.lock:
            self.seq += 1
            self.live["log"].append({"seq": self.seq, "msg": msg})
            self.live["log"] = self.live["log"][-300:]

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
    speed: int = Field(500, ge=1, le=3400)
    acc: int = Field(50, ge=0, le=254)
    cycles: int = Field(1, ge=1, le=20)
    simulate: bool = False
    node: str | None = None            # clicked CAD node (for the log)
    joint: str | None = None           # CAD joint name (for limit enforcement)
    offset: float = Field(0, ge=-180, le=180)   # resolved engine-side


class CenterParams(BaseModel):
    servo_id: int = Field(1, ge=1, le=253)
    speed: int = Field(300, ge=1, le=3400)
    acc: int = Field(50, ge=0, le=254)
    simulate: bool = False
    joint: str | None = None
    offset: float = Field(0, ge=-180, le=180)   # resolved engine-side
    hold_center: bool = False                   # keep torque on after centering


class GroupParams(BaseModel):
    joints: list[str] = Field(min_length=1)
    mode: str = Field("sequential", pattern="^(sequential|simultaneous)$")
    speed: int = Field(500, ge=1, le=3400)
    acc: int = Field(50, ge=0, le=254)
    cycles: int = Field(1, ge=1, le=20)
    simulate: bool = False
    # demo mode: after each joint's test, return it to center and keep torque
    # ON so the robot holds a stable pose. Stop/abort still releases everything.
    hold_center: bool = False


# ---------------------------------------------------------------- engine

class MotionEngine:
    """Owns the (single) run lifecycle against one bus, plus the live state."""

    def __init__(self, cfg: ConfigStore):
        self.cfg = cfg
        self.S = State()

    # ------------------------------------------------------ single-servo

    def _move_and_wait(self, bus, p, target: int, label: str):
        S = self.S
        off = p.offset
        start = bus.read_pos(p.servo_id)
        bus.move(p.servo_id, target, p.speed, p.acc)
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
        target = to_ticks(0.0, p.offset)
        self._move_and_wait(bus, p, target, "to center (mount position)")
        if p.hold_center:
            ok = bus.torque_on(p.servo_id)
            S.log(f"center reached: +0.0 deg (tick {target}) — holding, torque "
                  + ("ON (verified)" if ok else "state UNVERIFIED, check servo!"))
            return True                  # tell _run to keep torque on
        S.log(f"center reached: +0.0 deg (tick {target}) — mount the part now")
        return False

    # ------------------------------------------------------ group helpers

    def _move_all_and_wait(self, bus, p, plan, targets: dict, label: str,
                           held: set | None = None, settle: bool = False):
        """Command several servos at once and poll until all reached (or
        timeout). Servos in `held` (parked, holding) are read too, so their
        live angle is streamed while OTHER joints test.

        settle=True adds a load-sag compensation pass: under load the servo's
        P-controller parks short of the goal (steady-state error); we measure
        the residual and over-command by it (clamped to the joint limits) so
        the ACTUAL pose matches the taught pose. Used for demo steps and
        centering, not for range sweeps."""
        S = self.S
        id2joint = {e["id"]: e["joint"] for e in plan}
        id2off = {e["id"]: e.get("offset", 0.0) for e in plan}
        by_id = {e["id"]: e for e in plan}
        watch = [sid for sid in (held or set())
                 if sid in id2joint and sid not in targets]
        starts = {sid: bus.read_pos(sid) for sid in targets}
        for sid, t in targets.items():
            bus.move(sid, t, p.speed, p.acc)
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
            for sid, t in targets.items():
                pos = bus.read_pos(sid)
                multi[id2joint[sid]] = to_rel(pos, id2off[sid])
                if abs(pos - t) > TOLERANCE:
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
                for sid, t in targets.items():
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
                    bus.move(sid, cmd, 150, 30)  # slow trim move
                t1 = time.monotonic() + 0.45
                while time.monotonic() < t1:
                    if S.abort.is_set():
                        raise ServoBusError("aborted by user")
                    time.sleep(POLL_S)
            resid = []
            multi = dict(S.snapshot().get("multi") or {})
            for sid, t in targets.items():
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
                bus.move(sid, center_t[sid], 300, 50)
                bus.torque_on(sid)
            except ServoBusError:
                S.log(f"WARNING: ID {sid} not responding during hold check")

    def _group_center_body(self, bus, p, plan, held: set):
        self._move_all_and_wait(bus, p, plan,
                                {e["id"]: to_ticks(0.0, e["offset"])
                                 for e in plan},
                                "group: to center", settle=True)
        if p.hold_center:
            for e in plan:
                self._hold(bus, e, held)
        self.S.log("all selected servos at center (+0.0 deg, mount offsets applied)")

    def _group_test_body(self, bus, p, plan, held: set):
        S = self.S
        center_t = {e["id"]: to_ticks(0.0, e["offset"]) for e in plan}
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
            plan.append({"joint": j, "id": ids[j], "lo": lo, "hi": hi,
                         "limited": bool(L),
                         "offset": float(offs.get(j, 0.0))})
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
            p = p.model_copy(
                update={"offset": float(self.cfg.offsets().get(p.joint, 0.0))})
        self._launch(p, self._center_body,
                     f"--- move to center: ID {p.servo_id}, speed {p.speed}, "
                     f"{'SIMULATION' if p.simulate else 'hardware'} ---")

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

    def play_demo(self, demo: Demo, simulate: bool):
        """Run a taught-in demo: per step, move all its joints simultaneously
        (clamped to limits, offsets applied, settle pass), honor pauses, and
        hold the final pose."""
        S = self.S
        ids = self.cfg.servo_ids()
        used = list(dict.fromkeys(
            j for s in demo.steps for j in s.angles if j in ids))
        unknown = sorted({j for s in demo.steps for j in s.angles} - set(used))
        if not used:
            raise MotionError("Demo uses no configured joints.")
        plan = self.build_plan(used)

        def body(bus, bp, plan, held):
            if unknown:
                S.log(f"NOTE: unknown joints skipped: {', '.join(unknown)}")
            by_joint = {e["joint"]: e for e in plan}
            moved: set[int] = set()
            n = len(demo.steps)
            for i, step in enumerate(demo.steps, 1):
                sp = SimpleNamespace(speed=step.speed, acc=step.acc)
                targets, clamped = {}, []
                for j, deg in step.angles.items():
                    e = by_joint.get(j)
                    if not e:
                        continue
                    d = max(e["lo"], min(e["hi"], deg))
                    if d != deg:
                        clamped.append(f"{j} {deg:+.1f}->{d:+.1f}")
                    targets[e["id"]] = to_ticks(d, e["offset"])
                if clamped:
                    S.log(f"step {i}: clamped to joint limits: "
                          + ", ".join(clamped))
                if not targets:
                    S.log(f"step {i}: no responding joints — skipped")
                    continue
                moved.update(targets)
                self._move_all_and_wait(bus, sp, plan, targets,
                                        f"demo '{demo.name}' step {i}/{n}",
                                        held, settle=True)
                if step.pause_s:
                    deadline = time.monotonic() + step.pause_s
                    while time.monotonic() < deadline:
                        if S.abort.is_set():
                            raise ServoBusError("aborted by user")
                        time.sleep(0.05)
            # demos end in a defined pose: hold it (release via release-torque)
            for e in plan:
                if e["id"] in moved:
                    self._hold(bus, e, held)
            S.log(f"demo '{demo.name}' finished — holding final pose")

        # warn_unlimited=False: the pre-refactor demo launch never warned
        # about limits-less joints (only group runs do) — log parity matters
        self._launch_group(
            p=SimpleNamespace(simulate=simulate),
            plan=plan, body=body,
            banner=f"--- demo '{demo.name}': {len(demo.steps)} steps, "
                   f"{len(plan)} joints, "
                   f"{'SIMULATION' if simulate else 'hardware'} ---",
            warn_unlimited=False)
        return plan
