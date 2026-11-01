"""Servo bench tests: drive the joints through scripted moves WITHOUT a policy and log what the servos do.

Purpose (2026-10-22): the sim assumes a soft PD actuator with 8.9 rad/s; the real servos follow a goal at the
`speed` register (1000 ticks/s = 1.53 rad/s) and brown the pack out when many of them move at once. The logs give
the numbers for the actuator model (dead time, time constant, real top speed per servo type) and the pack voltage
versus speed.

    POST /bench/start {"test": "step"|"rect", "speeds": [1000, 2000, 3400], "confirm_suspended": true}

ROBOT MUST HANG FREE (feet off the ground, no contact). Every move stays `MARGIN_DEG` inside the joint limits.
The run aborts below `v_min` volts, on a bus loss, a joint outside its limits or a hot servo, and /stop (E-stop)
releases all torque. Log: ~/zbot/bench_logs/<time>_<test>.npz, one row per 20 ms step, all 16 servos.

  step  one joint at a time: out-and-back moves of several amplitudes at several speeds  (servo dynamics)
  rect  all joints together: out-and-back square wave at several speeds                   (pack voltage, load)
  sag   chosen joints held at growing angles, slowly, with a 2.5 s settle each            (static stiffness: the
        sag of a held limb under its own weight vs. the load register; compare with the model's gravity torque)
  hold  NO motion: the robot STANDS (on the mat, centre pose) and the servos just hold; logs the load of every joint
        (mass / centre-of-mass check against the model's holding torques)
"""
import json
import math
import threading
import time
from pathlib import Path

import numpy as np

from zbot_core.bus import ServoBusError
from zbot_core.motion import MotionError, to_rel, to_ticks

DT = 0.02
TICK_DEG = 360.0 / 4096.0
MARGIN_DEG = 10.0           # every move stays this far inside the joint limits
MIN_AMP_DEG = 3.0           # smaller moves are skipped (joint too close to its limit)
V_START_MIN = 11.8          # refuse to start on a flat pack
V_START_MIN_TEST = {"sag": 11.4, "hold": 11.4}   # the sag test moves slowly and draws almost nothing
V_MIN_DEFAULT = 11.0        # abort below this (the battery guard halts the Pi at 10.8)
TEMP_MAX = 65               # deg C
BUS_FAIL_STEPS = 3
LOG_MAX_STEPS = 45000       # 15 min at 50 Hz
LIMIT_SLACK_DEG = 3.0       # measured position beyond a limit by more than this = fault
# The status block of the STS servos has isolated bad samples (2026-10-25: temperature 55/56/137 C between
# readings of ~30 C), so every guard needs consecutive bad samples before it aborts.
HOLD_DEFAULT_S = 10.0
SAG_SETTLE_S = 2.5          # hold time at every angle of the sag test
DEBOUNCE = {"volt": 2, "temp": 5, "limit": 3}
FIELDS = ("t", "move", "goal", "pos", "speed", "load", "volt", "temp")


class BenchError(MotionError):
    pass


def build_program(test: str, plan: list[dict], start_deg: list[float], speeds: list[int],
                  amps: list[float], cycles: int = 4, rect_amp: float = 10.0,
                  margin: float = MARGIN_DEG) -> tuple[list[dict], list[dict]]:
    """Moves for the whole test: (moves, skipped). A move sets the goal of every joint (the idle ones to their
    start pose) at one speed and waits `dwell` s. Each joint goes toward the side with more room."""
    n = len(plan)
    start = list(start_deg)
    dirs, rooms = [], []
    for e, d0 in zip(plan, start):
        up, dn = e["hi"] - d0, d0 - e["lo"]
        dirs.append(1.0 if up >= dn else -1.0)
        rooms.append(max(up, dn) - margin)

    def goal(amp_by_joint: dict[int, float]) -> list[float]:
        g = list(start)
        for j, a in amp_by_joint.items():
            g[j] = start[j] + dirs[j] * a
        return g

    def dwell(amp: float, speed: int) -> float:
        return max(0.6, 1.5 * amp / (speed * TICK_DEG) + 0.4)

    moves, skipped = [], []
    if test == "step":
        for j, e in enumerate(plan):
            for speed in speeds:
                for amp in amps:
                    a = min(amp, rooms[j])
                    if a < MIN_AMP_DEG:
                        skipped.append({"joint": e["joint"], "speed": speed, "amp": amp,
                                        "reason": f"only {rooms[j]:.1f} deg of room"})
                        continue
                    dw = dwell(a, speed)
                    moves.append({"label": f"step {e['joint']} {a:.0f}deg @{speed} out", "joint": e["joint"],
                                  "speed": speed, "amp": a, "dwell": dw, "goal": goal({j: a})})
                    moves.append({"label": f"step {e['joint']} {a:.0f}deg @{speed} back", "joint": e["joint"],
                                  "speed": speed, "amp": a, "dwell": dw, "goal": goal({})})
    elif test == "rect":
        amps_all = {j: min(rect_amp, rooms[j]) for j in range(n) if min(rect_amp, rooms[j]) >= MIN_AMP_DEG}
        for j in range(n):
            if j not in amps_all:
                skipped.append({"joint": plan[j]["joint"], "reason": f"only {rooms[j]:.1f} deg of room"})
        top = max(amps_all.values()) if amps_all else 0.0
        for speed in speeds:
            moves.append({"label": f"rect @{speed} rest", "joint": None, "speed": speed, "amp": 0.0,
                          "dwell": 1.5, "goal": goal({})})
            for c in range(cycles):
                moves.append({"label": f"rect @{speed} cycle {c + 1} out", "joint": None, "speed": speed,
                              "amp": top, "dwell": dwell(top, speed), "goal": goal(amps_all)})
                moves.append({"label": f"rect @{speed} cycle {c + 1} back", "joint": None, "speed": speed,
                              "amp": top, "dwell": dwell(top, speed), "goal": goal({})})
    elif test == "hold":
        moves.append({"label": "hold", "joint": None, "speed": speeds[0], "amp": 0.0,
                      "dwell": float(max(cycles, 1)), "goal": goal({})})      # `cycles` doubles as the hold time in s
    elif test == "sag":
        for j, e in enumerate(plan):
            for a_req in sorted(amps):
                a = min(a_req, rooms[j])
                if a < MIN_AMP_DEG:
                    skipped.append({"joint": e["joint"], "speed": speeds[0], "amp": a_req,
                                    "reason": f"only {rooms[j]:.1f} deg of room"})
                    continue
                prev = moves[-1]["amp"] if moves and moves[-1]["joint"] == e["joint"] else 0.0
                moves.append({"label": f"sag {e['joint']} {a:.0f}deg", "joint": e["joint"], "speed": speeds[0],
                              "amp": a, "dwell": abs(a - prev) / (speeds[0] * TICK_DEG) + SAG_SETTLE_S,
                              "goal": goal({j: a})})
            if moves and moves[-1]["joint"] == e["joint"]:
                a = moves[-1]["amp"]
                moves.append({"label": f"sag {e['joint']} back", "joint": e["joint"], "speed": speeds[0], "amp": a,
                              "dwell": a / (speeds[0] * TICK_DEG) + 1.0, "goal": goal({})})
    else:
        raise BenchError(f"unknown test '{test}' (step | rect | sag | hold)")
    return moves, skipped


class BenchRunner:
    def __init__(self, engine, root: Path, imu=None):
        self.imu = imu                  # anything with .snapshot(): the head IMU gives the body attitude per move
        self.engine = engine
        self.S = engine.S
        self.cfg = engine.cfg
        self.log_dir = Path(root) / "bench_logs"
        self.last_log: str | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._st = self._fresh()

    @staticmethod
    def _fresh():
        return {"test": None, "move": 0, "moves": 0, "label": None, "min_volt": None, "max_temp": None,
                "steps": 0, "stop_reason": None}

    # -- public
    def start(self, test: str, speeds: list[int], amps: list[float] | None = None, acc: int = 0,
              v_min: float = V_MIN_DEFAULT, cycles: int = 4, rect_amp: float = 10.0,
              joints: list[str] | None = None, confirm_suspended: bool = False, confirm_standing: bool = False,
              hold_s: float = HOLD_DEFAULT_S) -> dict:
        if test == "hold":
            if not confirm_standing:
                raise BenchError("The hold test needs the robot STANDING upright on the mat, centre pose, "
                                 "someone at the E-stop: send confirm_standing=true once it does.")
            cycles = int(hold_s)
        elif not confirm_suspended:
            raise BenchError("The robot must hang free with its feet off the ground: "
                             "send confirm_suspended=true once it does.")
        if not speeds or any(not (100 <= s <= 3400) for s in speeds):
            raise BenchError("speeds must be 100..3400 ticks/s")
        amps = amps or ([30.0, 60.0, 90.0] if test == "sag" else [5.0, 15.0, 30.0])
        if any(not (1.0 <= a <= (90.0 if test == "sag" else 45.0)) for a in amps) or not (1.0 <= rect_amp <= 30.0):
            raise BenchError("amps must be 1..45 deg (sag: 1..90), rect_amp 1..30 deg")
        sel = joints or sorted(self.cfg.servo_ids(), key=lambda j: self.cfg.servo_ids()[j])
        plan = self.engine.build_plan(sel)
        bus = self.engine._claim_run_slot()
        try:
            if bus is None:
                raise BenchError("Not connected to the servo bus.")
            ids = [e["id"] for e in plan]
            try:
                raw = bus.sync_read_ext(ids)
            except ServoBusError as e:
                raise BenchError(f"servo check failed: {e}") from e
            volts = min(r[3] for r in raw.values())
            v_need = V_START_MIN_TEST.get(test, V_START_MIN)
            if volts < v_need:
                raise BenchError(f"pack is at {volts:.1f} V, charge it to >= {v_need} V first")
            hot = [i for i, r in raw.items() if r[4] >= TEMP_MAX - 10]
            if hot:
                raise BenchError(f"servo(s) {hot} are warm (>= {TEMP_MAX - 10} C): let them cool down")
            start_deg = [to_rel(raw[e["id"]][0], e["offset"]) for e in plan]
            far = [f"{e['joint']} {d:+.1f} deg outside [{e['lo']:+.0f}, {e['hi']:+.0f}]"
                   for e, d in zip(plan, start_deg) if not (e["lo"] <= d <= e["hi"])]
            if far:
                raise BenchError("joint(s) outside their limits: " + "; ".join(far))
            program, skipped = build_program(test, plan, start_deg, list(speeds), list(amps), cycles, rect_amp)
            if not program:
                raise BenchError("nothing to do: every joint is too close to its limit")
        except Exception:
            self.S.set(running=False)
            raise
        self._stop.clear()
        self.S.abort.clear()
        with self._lock:
            self._st = self._fresh()
            self._st.update(test=test, moves=len(program))
        total = sum(m["dwell"] for m in program)
        self.S.set(phase="bench", error=None, multi={})
        self.S.log(f"bench '{test}' starting: {len(program)} moves, ~{total:.0f} s, speeds {speeds}, "
                   f"abort below {v_min:.1f} V, pack {volts:.1f} V")
        t = threading.Thread(target=self._run, daemon=True, name="bench-runner",
                             args=(test, plan, bus, program, skipped, [raw[e["id"]][0] for e in plan],
                                   acc, v_min))
        with self.S.lock:
            self.S.runner = t
        self._thread = t
        t.start()
        return self.status()

    def stop(self):
        self._stop.set()

    def status(self) -> dict:
        alive = self._thread is not None and self._thread.is_alive()
        with self._lock:
            return {"running": alive, **self._st, "last_log": self.last_log}

    def logs(self) -> list[dict]:
        return [{"name": f.name, "bytes": f.stat().st_size, "mtime": f.stat().st_mtime}
                for f in sorted(self.log_dir.glob("*.npz"))] if self.log_dir.is_dir() else []

    def log_path(self, name: str) -> Path:
        f = (self.log_dir / name).resolve()
        if f.parent != self.log_dir.resolve() or f.suffix != ".npz" or not f.is_file():
            raise BenchError(f"unknown log '{name}'")
        return f

    # -- the loop
    def _run(self, test, plan, bus, program, skipped, start_ticks, acc, v_min):
        S = self.S
        ids = [e["id"] for e in plan]
        offs = [e["offset"] for e in plan]
        lo = np.array([e["lo"] for e in plan])
        hi = np.array([e["hi"] for e in plan])
        rows = {f: [] for f in FIELDS}
        imu_at = []                                                     # head IMU at the end of every move
        reason, fault, held, estop, truncated = "finished", False, False, False, False
        t_start = time.monotonic()
        try:
            bus.sync_move(dict(zip(ids, start_ticks)), 200, 30)          # goal := here, then torque on
            for i in ids:
                if not bus.torque_on(i):
                    S.log(f"WARNING: servo {i} torque state UNVERIFIED")
            held = True
            fails = 0
            bad = {"volt": 0, "temp": 0, "limit": 0}
            nxt = time.monotonic()
            done = False
            for mi, mv in enumerate(program):
                goal = [to_ticks(d, o) for d, o in zip(mv["goal"], offs)]
                bus.sync_move(dict(zip(ids, goal)), mv["speed"], acc)
                with self._lock:
                    self._st.update(move=mi + 1, label=mv["label"])
                t_end = time.monotonic() + mv["dwell"]
                while time.monotonic() < t_end:
                    if S.abort.is_set():
                        reason, estop, done = "aborted by user (E-stop)", True, True
                        break
                    if self._stop.is_set():
                        reason, done = "stopped", True
                        break
                    try:
                        raw = bus.sync_read_ext(ids)
                        fails = 0
                    except ServoBusError as e:
                        fails += 1
                        S.log(f"bench: bus read failed ({fails}/{BUS_FAIL_STEPS}): {e}")
                        if fails >= BUS_FAIL_STEPS:
                            reason, fault, done = f"bus lost: {e}", True, True
                            break
                        nxt += DT
                        time.sleep(max(0.0, nxt - time.monotonic()))
                        continue
                    pos = np.array([raw[i][0] for i in ids], float)
                    volt = np.array([raw[i][3] for i in ids], float)
                    temp = np.array([raw[i][4] for i in ids], float)
                    deg = np.array([to_rel(p, o) for p, o in zip(pos, offs)])
                    if len(rows["t"]) < LOG_MAX_STEPS:
                        rows["t"].append(time.monotonic() - t_start)
                        rows["move"].append(mi)
                        rows["goal"].append(goal)
                        rows["pos"].append(pos)
                        rows["speed"].append([raw[i][1] for i in ids])
                        rows["load"].append([raw[i][2] for i in ids])
                        rows["volt"].append(volt)
                        rows["temp"].append(temp)
                    else:
                        truncated = True
                    with self._lock:
                        self._st["steps"] = len(rows["t"])
                        self._st["min_volt"] = round(float(min(volt.min(), self._st["min_volt"] or 99)), 2)
                        self._st["max_temp"] = int(max(temp.max(), self._st["max_temp"] or 0))
                    out = np.where((deg < lo - LIMIT_SLACK_DEG) | (deg > hi + LIMIT_SLACK_DEG))[0]
                    bad["volt"] = bad["volt"] + 1 if volt.min() < v_min else 0
                    bad["temp"] = bad["temp"] + 1 if temp.max() >= TEMP_MAX else 0
                    bad["limit"] = bad["limit"] + 1 if len(out) else 0
                    if bad["volt"] >= DEBOUNCE["volt"]:
                        reason, fault, done = f"pack voltage {volt.min():.1f} V < {v_min:.1f} V", True, True
                        break
                    if bad["temp"] >= DEBOUNCE["temp"]:
                        reason, fault, done = f"servo at {temp.max():.0f} C", True, True
                        break
                    if bad["limit"] >= DEBOUNCE["limit"]:
                        j = out[0]
                        reason, fault, done = (f"{plan[j]['joint']} at {deg[j]:+.1f} deg, outside "
                                               f"[{lo[j]:+.0f}, {hi[j]:+.0f}]"), True, True
                        break
                    nxt += DT
                    slack = nxt - time.monotonic()
                    if slack < 0:
                        nxt = time.monotonic()
                    else:
                        time.sleep(slack)
                if done:
                    break
                imu_at.append(self._imu_sample(mi))
        except Exception as e:                                          # noqa: BLE001
            reason, fault = f"{type(e).__name__}: {e}", True
        finally:
            if estop:
                for i in ids:
                    try:
                        bus.torque_off(i)
                    except Exception:                                   # noqa: BLE001
                        pass
            elif held:
                try:
                    if fault:                                           # hold where it is: the rig is hanging
                        cur = bus.sync_read(ids)
                        bus.sync_move({i: cur[i][0] for i in ids}, 200, 30)
                    else:                                               # back to the start pose, slowly
                        bus.sync_move(dict(zip(ids, start_ticks)), 300, 30)
                        time.sleep(1.5)
                except Exception:                                       # noqa: BLE001
                    S.log("WARNING: bench end: could not park the servos")
            with self._lock:
                self._st["stop_reason"] = reason
            self._save(test, plan, rows, program, skipped, start_ticks, acc, v_min, reason, fault, truncated, imu_at)
            S.log(f"bench '{test}' ended: {reason}" + (" - torque held" if fault and not estop else ""))
            S.set(running=False, phase="error" if fault else "done", error=reason if fault else None, multi=None)

    def _imu_sample(self, move: int) -> dict | None:
        try:
            snap = self.imu.snapshot() if self.imu else None
            smp = snap and snap.get("sample")
            if not smp or snap.get("age_s", 9) > 0.5:
                return None
            return {"move": move, **{k: smp[k] for k in ("ax", "ay", "az", "gx", "gy", "gz")}}
        except Exception:                                               # noqa: BLE001
            return None

    def _save(self, test, plan, rows, program, skipped, start_ticks, acc, v_min, reason, fault, truncated, imu_at):
        if not rows["t"]:
            return
        path = self.log_dir / f"{time.strftime('%Y%m%d-%H%M%S')}_bench_{test}.npz"
        meta = {"test": test, "stop_reason": reason, "fault": fault, "steps": len(rows["t"]),
                "truncated": truncated, "dt": DT, "acc": acc, "v_min": v_min,
                "joints": [e["joint"] for e in plan], "ids": [e["id"] for e in plan],
                "offsets": [e["offset"] for e in plan], "limits_deg": [[e["lo"], e["hi"]] for e in plan],
                "start_ticks": [int(t) for t in start_ticks],
                "moves": [{k: m[k] for k in ("label", "joint", "speed", "amp", "dwell")} for m in program],
                "skipped": skipped, "imu_at_move_end": [x for x in imu_at if x],
                "units": "ticks 4096/turn; speed ticks/s; load -1000..1000 (1000 = 100 % torque limit); volt V; temp C"}
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            arrs = {f: np.asarray(v, dtype=np.float64) for f, v in rows.items()}
            arrs["meta"] = np.array(json.dumps(meta))
            tmp = path.with_suffix(".tmp.npz")
            np.savez_compressed(tmp, **arrs)
            tmp.replace(path)
            self.last_log = path.name
            self.S.log(f"bench: {len(rows['t'])} steps logged to {path}")
        except Exception as e:                                          # noqa: BLE001
            self.S.log(f"WARNING: bench log could not be written: {e}")
