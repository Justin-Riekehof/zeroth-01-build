"""On-robot inference loop for the walking policies trained in sim/ (ONNX, 50 Hz).

One policy directory (sim/policies/<name>/) = policy.onnx + policy_meta.json.
policy_meta.json is the contract: this module refuses to run when the input
layout, output size or joint list differ from what it implements, instead of
feeding a network a vector it was not trained on.

Per control step (ctrl_dt = 20 ms):

    servos --sync read--> joint pos/vel ┐
    head IMU (raw chip axes) -----------┼-> 64-vector -> ONNX -> 16 target angles
    gait clock, heading, last action(s) ┘                          │
    (+ 16 per older action for policies trained with action_history > 1)
    velocity/gait commands                       clamp to joint limits, sync write

Angle convention (policy_meta.json): action = target joint angle in rad, MuJoCo
joint order, 0 = servo zero. The sim joint angle IS the servo "relative degree"
(model_invert is baked into the sim axes), so ticks = to_ticks(deg(angle), mount
offset) exactly like every demo — no extra sign handling here.

The runner takes the engine's single run slot, so it can never overlap a demo,
a get-up or teleop, and /stop (S.abort) ends it like any other run.
"""

import json
import math
import threading
import time
from pathlib import Path

import numpy as np

from zbot_core.bus import ServoBusError
from zbot_core.motion import MotionError, to_rel, to_ticks

CTRL_DT = 0.02
MG_TO_MS2 = 9.80665e-3
DPS_TO_RAD = math.pi / 180.0
TICKS_TO_RAD = 2.0 * math.pi / 4096.0

# What this module builds, in this order. Anything else in policy_meta.json is
# a different training setup and must be implemented here before it may run.
EXPECTED_LAYOUT = [("timestep_phase", 4), ("joint_pos", 16), ("joint_vel", 16),
                   ("imu_acc", 3), ("imu_gyro", 3), ("lin_vel_cmd", 2),
                   ("ang_vel_cmd", 1), ("gait_freq_cmd", 1), ("last_action", 16),
                   ("heading", 2)]
N_IN = sum(n for _, n in EXPECTED_LAYOUT)
MAX_ACTION_HISTORY = 8      # optional ("action_history", 16 * (k - 1)) after the heading: the k - 1 actions before the last

# Abort thresholds
IMU_STALE_S = 0.25          # firmware streams ~20 Hz; older than this = link dead
TILT_ABORT_DEG = 55.0       # body up-axis vs. gravity, low-passed
TILT_ABORT_STEPS = 5        # consecutive steps above the threshold
BUS_FAIL_STEPS = 3          # consecutive failed bus transactions
RAMP_STEPS = 50             # 1 s: blend from the current pose into the policy (default for policies without a trained start)
GYRO_CAL_S = 1.0            # standing still at start: measure the gyro zero offset
GYRO_STILL_DPS = 8.0        # per-axis std-dev above this = robot is being moved -> no calibration
STANDING_G_TOL = 1.5        # |chip-Y reading - 9.81| allowed at start (m/s²)
START_POSE_WARN_DEG = 1.0   # joint further than this from the center pose at start: warn, the run still starts
MAX_WZ = 0.5                # rad/s, clamp for the yaw-rate command
LOG_MAX_STEPS = 30000       # 10 min at 50 Hz; recording stops there, the run goes on


class PolicyError(MotionError):
    pass


class StepLog:
    """In-memory per-step record of one run, written once at the end (no disk I/O inside the
    50 Hz loop). Everything needed to replay a run offline against the sim: the raw servo
    ticks/speeds and raw IMU as read, the exact 64-vector fed to the network, the raw action,
    the clamped/ramped target and the ticks that were sent."""

    FIELDS = ("t", "step_ms", "read_ms", "infer_ms", "imu_seq", "imu_age_ms", "imu_raw", "pos_ticks",
              "speed_ticks", "obs", "action", "target", "sent_ticks", "tilt_deg", "heading", "cmd")

    def __init__(self):
        self.rows = {f: [] for f in self.FIELDS}
        self.full = False

    def add(self, **kw):
        if len(self.rows["t"]) >= LOG_MAX_STEPS:
            self.full = True
            return
        for f in self.FIELDS:
            self.rows[f].append(kw[f])

    def __len__(self):
        return len(self.rows["t"])

    def save(self, path: Path, meta: dict):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        arrs = {f: np.asarray(v, dtype=np.float64) for f, v in self.rows.items() if v}
        arrs["meta"] = np.array(json.dumps(meta))
        tmp = path.with_suffix(".tmp.npz")
        np.savez_compressed(tmp, **arrs)
        tmp.replace(path)


# ------------------------------------------------------------------ loading

def list_policies(root: Path) -> list[dict]:
    out = []
    for d in sorted(Path(root).glob("*/policy_meta.json")):
        try:
            m = json.loads(d.read_text())
            tc = m.get("task_config", {})
            out.append({"name": d.parent.name,
                        "has_onnx": (d.parent / "policy.onnx").is_file(),
                        "speed_range": [tc.get("target_speed_min"), tc.get("target_speed_max")],
                        "gait_freq_range": [tc.get("gait_freq_lower"), tc.get("gait_freq_upper")],
                        "heading_obs": tc.get("heading_obs"),
                        "joint_sign_flip": m.get("joint_sign_flip") or [],
                        "assets": m.get("assets")})
        except (ValueError, OSError):
            continue
    return out


class LoadedPolicy:
    """policy.onnx + validated policy_meta.json."""

    def __init__(self, directory: Path):
        self.dir = Path(directory)
        try:
            self.meta = json.loads((self.dir / "policy_meta.json").read_text())
        except (OSError, ValueError) as e:
            raise PolicyError(f"{self.dir.name}: policy_meta.json unreadable ({e})")
        m = self.meta
        layout = [(e["name"], e["size"]) for e in m["input"]["layout_in_order"]]
        self.joints: list[str] = list(m["joint_order"])
        self.history = 0                     # older actions beyond the last one
        if layout[len(EXPECTED_LAYOUT):] and layout[len(EXPECTED_LAYOUT)][0] == "action_history":
            size = layout[len(EXPECTED_LAYOUT)][1]
            self.history = size // len(self.joints)
            if size % len(self.joints) or not 0 < self.history < MAX_ACTION_HISTORY:
                raise PolicyError(f"{self.dir.name}: action_history size {size} is not 1..{MAX_ACTION_HISTORY - 1} "
                                  f"x {len(self.joints)} joints")
        expected = EXPECTED_LAYOUT + ([("action_history", len(self.joints) * self.history)] if self.history else [])
        self.n_in = sum(n for _, n in expected)
        if layout != expected or m["input"]["size"] != self.n_in:
            raise PolicyError(f"{self.dir.name}: input layout {layout} differs from what "
                              f"policy.py builds {expected} — retrained with other "
                              "observations? implement them first")
        if m["output"]["size"] != len(self.joints):
            raise PolicyError(f"{self.dir.name}: output size {m['output']['size']} != "
                              f"{len(self.joints)} joints")
        # joints whose axis was mirrored in the sim model the policy was trained on (hardware/model_invert.json corrected
        # 2026-10-31): policy angle = -servo angle, so the robot makes the motion the policy learnt
        self.flip: list[str] = list(m.get("joint_sign_flip") or [])
        unknown = sorted(set(self.flip) - set(self.joints))
        if unknown:
            raise PolicyError(f"{self.dir.name}: joint_sign_flip names unknown joints {unknown}")
        self.sign = np.array([-1.0 if j in self.flip else 1.0 for j in self.joints])
        tc = m.get("task_config", {})
        if tc.get("ctrl_dt", CTRL_DT) != CTRL_DT:
            raise PolicyError(f"{self.dir.name}: ctrl_dt {tc.get('ctrl_dt')} != {CTRL_DT}")
        self.action_scale = float(tc.get("action_scale", 1.0))
        # policies trained with the servo model: the speed register the sim assumed, and how fast the commanded target
        # may move per joint (the sim limits it before its delay line; we must do the same). None for older policies.
        self.servo_speed = m.get("servo_speed_register")
        self.action_filter = float(m.get("action_filter_alpha") or 0.0)
        rate = m.get("command_rate_limit_rad_s")
        self.cmd_rate = np.asarray(rate, float) if rate else None
        if self.cmd_rate is not None and len(self.cmd_rate) != len(m["joint_order"]):
            raise PolicyError(f"{self.dir.name}: command_rate_limit_rad_s has {len(self.cmd_rate)} entries, "
                              f"expected {len(m['joint_order'])}")
        # start blend: a policy trained from the centre pose (start_pose=center) acts at full authority from step 0 in
        # the sim -- a 1 s blend holds it back while its gait clock runs on, and it hits the floor at the blend's end
        # (servo_rubber23, 21.11.2026). policy_meta "start_ramp_steps" overrides; older policies keep the 1 s blend.
        ramp = m.get("start_ramp_steps")
        self.ramp_steps = int(ramp) if ramp is not None else (0 if tc.get("start_pose") == "center" else RAMP_STEPS)
        self.zero_speed_trained = float(tc.get("speed_zero_prob") or 0.0) > 0   # stepping on the spot was trained too
        self.speed_range = (float(tc.get("target_speed_min", 0.0)),
                            float(tc.get("target_speed_max", 0.0)))
        self.gait_range = (float(tc.get("gait_freq_lower", 1.25)),
                           float(tc.get("gait_freq_upper", 1.5)))
        # IMU: the sim feeds the RAW chip axes; the body-up direction in chip
        # axes is what the yaw integration and the start check need.
        axes = m["imu"]["axes_in_body"]
        self.up_in_imu = np.array([axes["x_imu"][2], axes["y_imu"][2], axes["z_imu"][2]])
        try:
            import onnxruntime as ort
        except ImportError as e:
            raise PolicyError("onnxruntime is not installed (pip install onnxruntime)") from e
        so = ort.SessionOptions()
        so.intra_op_num_threads = 1          # tiny MLP: threading only adds jitter
        so.inter_op_num_threads = 1
        self.sess = ort.InferenceSession(str(self.dir / "policy.onnx"), so,
                                         providers=["CPUExecutionProvider"])
        self._in = self.sess.get_inputs()[0].name
        if self.sess.get_inputs()[0].shape[-1] != self.n_in:
            raise PolicyError(f"{self.dir.name}: ONNX input is {self.sess.get_inputs()[0].shape}")

    def __call__(self, obs: np.ndarray) -> np.ndarray:
        return self.sess.run(None, {self._in: obs.reshape(1, self.n_in).astype(np.float32)})[0].reshape(-1)


# --------------------------------------------------------------- observation

def resolve_speed(trained: int | None, requested: int | None) -> int:
    """Servo speed register for a run: the policy's own (servo-model training) unless the caller asks for exactly that;
    a different register would change the joint dynamics the policy was trained on."""
    if trained is not None and requested is not None and int(requested) != int(trained):
        raise PolicyError(f"this policy was trained with servo speed {trained} ticks/s, refusing {requested}")
    return int(requested or trained or 1000)


def low_pass(x: np.ndarray, prev: np.ndarray, alpha: float) -> np.ndarray:
    """One control step of the action filter the sim's servo model applies (alpha 0 = off)."""
    return x if alpha <= 0 else prev + alpha * (x - prev)


def limit_rate(target: np.ndarray, prev: np.ndarray, rate: np.ndarray | None, dt: float) -> np.ndarray:
    """Move each joint's commanded target at most rate*dt from the previous one (rad), as the sim's servo model does."""
    if rate is None:
        return target
    return prev + np.clip(target - prev, -rate * dt, rate * dt)


class ObsBuilder:
    """Everything that is stateful between steps: gait phase, heading, last action and (history > 0) the `history`
    actions before it, newest first - like the sim's ActionHistoryObservation. Before the first action every one of
    them is the measured start pose, as in the sim (ksim's first "last action" is the reset pose)."""

    def __init__(self, n_joints: int, gait_freq: float, up_in_imu: np.ndarray, history: int = 0):
        self.gait_freq = gait_freq
        self.up_in_imu = up_in_imu
        self.phase = np.array([0.0, math.pi])          # trotting start, as in training
        self.psi = 0.0                                  # yaw relative to start
        self.last_action = np.zeros(n_joints)
        self.older = np.tile(self.last_action, (history, 1))
        self._fresh = True
        self._imu_seq = None
        self._imu_t = None

    def integrate_yaw(self, gyro_rad: np.ndarray, seq, t: float):
        """Heading = integral of the body-up component of the gyro, once per NEW IMU sample
        (the IMU streams slower than the loop; integrating a stale sample twice would drift)."""
        if seq != self._imu_seq:
            if self._imu_t is not None:
                self.psi += float(gyro_rad @ self.up_in_imu) * min(t - self._imu_t, 0.2)
            self._imu_seq, self._imu_t = seq, t

    def build(self, pos, vel, acc, gyro, lin_cmd, wz, last_action=None) -> np.ndarray:
        if self._fresh:
            self.last_action = np.asarray(pos, float).copy()
            self.older = np.tile(self.last_action, (len(self.older), 1))
        ph = np.mod(self.phase + math.pi, 2 * math.pi) - math.pi
        clock = np.concatenate([np.cos(ph), np.sin(ph)])        # [cos0, cos1, sin0, sin1]
        obs = np.concatenate([clock, pos, vel, acc, gyro, lin_cmd, [wz], [self.gait_freq],
                              self.last_action if last_action is None else last_action,
                              [math.cos(self.psi), math.sin(self.psi)], self.older.reshape(-1)]).astype(np.float32)
        assert obs.shape == (N_IN + self.older.size,), obs.shape
        return obs

    def advance(self, action: np.ndarray):
        self._fresh = False
        if len(self.older):
            self.older = np.concatenate([self.last_action[None, :], self.older[:-1]])
        self.last_action = action.copy()
        self.phase = self.phase + 2 * math.pi * self.gait_freq * CTRL_DT


# --------------------------------------------------------------------- runner

class PolicyRunner:
    """Owns the 50 Hz thread. `engine` supplies the run slot, config and bus; `imu` is an
    ImuReader (anything with .snapshot()). `dry_run` reads, infers and logs but never
    commands or energises a servo — the first test on the robot (limp, moved by hand)."""

    def __init__(self, engine, imu, policies_dir: Path):
        self.engine, self.imu, self.root = engine, imu, Path(policies_dir)
        self.S = engine.S
        self.cfg = engine.cfg
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._cmd = {"vx": 0.0, "vy": 0.0, "wz": 0.0, "gait_freq": 1.5}
        self._stats = self._fresh_stats()
        self.name: str | None = None
        self._pol: LoadedPolicy | None = None
        self.gyro_bias = np.zeros(3)
        self._start_dev: dict[str, float] = {}
        self._start_acc_mg: list[float] = []
        self.dry_run = False
        self.last: dict = {}
        self.log_dir = self.root.parent / "policy_logs"
        self.last_log: str | None = None

    @staticmethod
    def _fresh_stats():
        return {"steps": 0, "overruns": 0, "max_step_ms": 0.0, "mean_step_ms": 0.0,
                "max_imu_age_ms": 0.0, "stop_reason": None}

    # -- public
    def available(self):
        return list_policies(self.root)

    def start(self, name: str, vx: float | None = None, vy: float = 0.0, wz: float = 0.0,
              gait_freq: float | None = None, speed: int | None = None, acc: int = 0,
              dry_run: bool = False) -> dict:
        d = (self.root / name).resolve()
        if d.parent != self.root.resolve() or not d.is_dir():
            raise PolicyError(f"unknown policy '{name}'")
        pol = LoadedPolicy(d)
        speed = resolve_speed(pol.servo_speed, speed)
        lo_v, hi_v = pol.speed_range
        vx = (lo_v + hi_v) / 2 if vx is None else vx
        gf = sum(pol.gait_range) / 2 if gait_freq is None else gait_freq
        self._check_cmd(pol, vx, vy, wz, gf)

        plan = self.engine.build_plan(pol.joints)
        by_joint = {e["joint"]: e for e in plan}
        bus = self.engine._claim_run_slot()
        try:
            if bus is None:
                raise PolicyError("Not connected to the servo bus.")
            self._preflight(pol, plan, bus)
            gyro_bias = self._calibrate_gyro(dry_run)
        except Exception:
            self.S.set(running=False)
            raise
        self._stop.clear()
        self.S.abort.clear()
        with self._lock:
            self._cmd = {"vx": vx, "vy": vy, "wz": wz, "gait_freq": gf}
            self._stats = self._fresh_stats()
        self.name, self._pol, self.dry_run, self.last = name, pol, dry_run, {}
        self.gyro_bias = gyro_bias
        self.S.set(phase="policy", error=None, multi={})
        self.S.log(f"policy '{name}' starting{' (DRY RUN: no servo commands)' if dry_run else ''}: "
                   f"vx {vx:.2f} vy {vy:.2f} wz {wz:.2f} gait {gf:.2f} Hz, "
                   f"servo speed {speed} acc {acc}")
        t = threading.Thread(target=self._run, daemon=True, name="policy-runner",
                             args=(pol, [by_joint[j] for j in pol.joints], bus, speed, acc, dry_run,
                                   gyro_bias))
        with self.S.lock:
            self.S.runner = t
        self._thread = t
        t.start()
        return self.status()

    def stop(self):
        self._stop.set()

    def set_cmd(self, **kw):
        if self._thread is None or not self._thread.is_alive():
            raise PolicyError("no policy running")
        with self._lock:
            new = {**self._cmd, **{k: v for k, v in kw.items() if v is not None}}
        self._check_cmd(self._pol, new["vx"], new["vy"], new["wz"], new["gait_freq"])
        with self._lock:
            self._cmd = new
        return new

    def status(self) -> dict:
        alive = self._thread is not None and self._thread.is_alive()
        with self._lock:
            return {"running": alive, "policy": self.name if alive else None,
                    "dry_run": self.dry_run,
                    "gyro_bias_dps": [round(float(x), 2) for x in self.gyro_bias], "cmd": dict(self._cmd),
                    "stats": dict(self._stats), "last": dict(self.last),
                    "last_log": self.last_log}

    def logs(self) -> list[dict]:
        return [{"name": f.name, "bytes": f.stat().st_size, "mtime": f.stat().st_mtime}
                for f in sorted(self.log_dir.glob("*.npz"))] if self.log_dir.is_dir() else []

    def log_path(self, name: str) -> Path:
        f = (self.log_dir / name).resolve()
        if f.parent != self.log_dir.resolve() or f.suffix != ".npz" or not f.is_file():
            raise PolicyError(f"unknown log '{name}'")
        return f

    # -- checks
    def _check_cmd(self, pol: LoadedPolicy, vx, vy, wz, gf):
        lo, hi = pol.speed_range
        glo, ghi = pol.gait_range
        # the policy only ever saw forward speeds inside its training range (plus 0 handled
        # by stopping the run) — outside that range its behaviour is undefined
        if not (lo - 1e-9 <= vx <= hi + 1e-9) and not (pol.zero_speed_trained and abs(vx) < 1e-9):
            raise PolicyError(f"vx {vx} outside the trained range [{lo}, {hi}] m/s")
        if abs(vy) > 1e-9:
            raise PolicyError("vy must be 0: the policies were trained for forward walking")
        if abs(wz) > MAX_WZ:
            raise PolicyError(f"|wz| above {MAX_WZ} rad/s")
        if not (glo <= gf <= ghi):
            raise PolicyError(f"gait_freq {gf} outside the trained range [{glo}, {ghi}] Hz")

    def _imu_sample(self):
        snap = self.imu.snapshot()
        s = snap.get("sample")
        if s is None or snap.get("age_s") is None:
            raise PolicyError("no head-IMU data (is the head board connected?)")
        if snap["age_s"] > IMU_STALE_S:
            raise PolicyError(f"head-IMU data is {snap['age_s']:.2f} s old")
        return s, snap["age_s"]

    def _calibrate_gyro(self, dry: bool) -> np.ndarray:
        """Gyro zero offset in dps, measured over GYRO_CAL_S with the robot standing still.
        The QMI8658 sits a few dps off zero (seen: -3 dps = 24° of fake heading in 8 s); the sim
        gyro has no such offset and the heading input integrates it, so the policy would steer
        against a turn that never happened."""
        samples, accs, seen = [], [], None
        t_end = time.monotonic() + GYRO_CAL_S
        while time.monotonic() < t_end:
            s, _ = self._imu_sample()
            if s.get("seq") != seen:
                seen = s.get("seq")
                samples.append([s["gx"], s["gy"], s["gz"]])
                accs.append([s["ax"], s["ay"], s["az"]])
            time.sleep(0.01)
        a = np.array(samples)
        self._start_acc_mg = np.mean(accs, axis=0).tolist() if accs else []
        if len(a) < 5:
            raise PolicyError(f"gyro calibration got only {len(a)} IMU samples in {GYRO_CAL_S} s")
        sd = a.std(axis=0)
        if sd.max() > GYRO_STILL_DPS:
            msg = (f"robot is moving during gyro calibration (std {np.round(sd, 1).tolist()} dps) — "
                   "hold it still for a second after pressing start")
            if not dry:
                raise PolicyError(msg)
            self.S.log("WARNING: " + msg + " (dry run: bias estimate unreliable)")
        bias = a.mean(axis=0)
        self.S.log(f"policy: gyro bias {np.round(bias, 2).tolist()} dps over {len(a)} samples")
        return bias

    def _preflight(self, pol: LoadedPolicy, plan: list[dict], bus):
        s, _ = self._imu_sample()
        acc = np.array([s["ax"], s["ay"], s["az"]]) * MG_TO_MS2
        up = float(acc @ pol.up_in_imu)
        if abs(up - 9.81) > STANDING_G_TOL:
            raise PolicyError(
                f"robot is not standing upright: accelerometer reads {up:+.2f} m/s² along body-up "
                f"(chip axes {np.round(acc, 2).tolist()}, expected +9.81 on the chip Y axis). "
                "Wrong IMU mounting, or the robot is not standing.")
        ids = [e["id"] for e in plan]
        try:
            pos = bus.sync_read(ids)
        except ServoBusError as e:
            raise PolicyError(f"servo check failed: {e}") from e
        far = []
        for e in plan:
            deg = to_rel(pos[e["id"]][0], e["offset"])
            if not (e["lo"] - 1.0 <= deg <= e["hi"] + 1.0):
                far.append(f"{e['joint']} {deg:+.1f}° outside [{e['lo']:+.0f}, {e['hi']:+.0f}]")
        if far:
            raise PolicyError("joint(s) outside their limits: " + "; ".join(far))
        # the run blends in from wherever the robot stands, so an off-center joint would go unnoticed
        center = self.cfg.center_pose()
        self._start_dev = {e["joint"]: round(to_rel(pos[e["id"]][0], e["offset"]) - center.get(e["joint"], 0.0), 2)
                           for e in plan}
        off = [f"{j} {d:+.1f}°" for j, d in self._start_dev.items() if abs(d) > START_POSE_WARN_DEG]
        if off:
            self.S.log("WARNING: start pose off center: " + ", ".join(off))

    # -- the loop
    def _run(self, pol: LoadedPolicy, plan: list[dict], bus, speed: int, acc: int, dry: bool,
             gyro_bias: np.ndarray):
        S = self.S
        ids = [e["id"] for e in plan]
        lo = np.array([math.radians(e["lo"]) for e in plan])
        hi = np.array([math.radians(e["hi"]) for e in plan])
        offs = [e["offset"] for e in plan]
        held = False
        reason = "stopped"
        fault = False
        slog = StepLog()
        t_start = time.monotonic()
        try:
            raw = bus.sync_read(ids)
            start_pos = np.array([math.radians(to_rel(raw[i][0], o)) for i, o in zip(ids, offs)])
            prev_target = start_pos.copy()
            filt = start_pos.copy()                      # action filter state (servo-model policies)
            if not dry:
                # goal := here, then torque on — enabling never makes a joint jump
                bus.sync_move({i: raw[i][0] for i in ids}, 200, 30)
                for i in ids:
                    if not bus.torque_on(i):
                        S.log(f"WARNING: servo {i} torque state UNVERIFIED")
                held = True
            with self._lock:
                gf = self._cmd["gait_freq"]
            ob = ObsBuilder(len(ids), gf, pol.up_in_imu, pol.history)
            tilt_bad = fails = 0
            tilt_lp = 0.0
            step_ms_sum = 0.0
            nxt = time.monotonic()
            k = 0
            while not self._stop.is_set():
                if S.abort.is_set():
                    reason = "aborted by user (E-stop)"
                    self._release(bus, ids, dry)
                    break
                t0 = time.monotonic()
                try:
                    raw = bus.sync_read(ids)
                    fails = 0
                    t_read = time.monotonic()
                except ServoBusError as e:
                    fails += 1
                    S.log(f"policy: bus read failed ({fails}/{BUS_FAIL_STEPS}): {e}")
                    if fails >= BUS_FAIL_STEPS:
                        reason, fault = f"bus lost: {e}", True
                        break
                    nxt += CTRL_DT
                    time.sleep(max(0.0, nxt - time.monotonic()))
                    continue
                try:
                    s, age = self._imu_sample()
                except PolicyError as e:
                    reason, fault = str(e), True
                    break
                seq = s.get("seq")
                accv = np.array([s["ax"], s["ay"], s["az"]]) * MG_TO_MS2
                gyro = (np.array([s["gx"], s["gy"], s["gz"]]) - gyro_bias) * DPS_TO_RAD
                ob.integrate_yaw(gyro, seq, time.monotonic() - age)

                # tilt guard: low-passed angle between body-up and gravity
                g = np.linalg.norm(accv) or 1.0
                cos_t = float(np.clip(accv @ pol.up_in_imu / g, -1, 1))
                tilt = math.degrees(math.acos(cos_t))
                tilt_lp = tilt if k == 0 else 0.7 * tilt_lp + 0.3 * tilt
                tilt_bad = tilt_bad + 1 if tilt_lp > TILT_ABORT_DEG else 0
                if tilt_bad >= TILT_ABORT_STEPS:
                    reason, fault = f"tilt {tilt_lp:.0f}° > {TILT_ABORT_DEG:.0f}° — fall", True
                    break

                servo_pos = np.array([math.radians(to_rel(raw[i][0], o)) for i, o in zip(ids, offs)])
                pos = pol.sign * servo_pos                # what the policy sees (filter, limits, ramp: servo angles)
                vel = pol.sign * np.array([raw[i][1] * TICKS_TO_RAD for i in ids])
                with self._lock:
                    c = dict(self._cmd)
                ob.gait_freq = c["gait_freq"]
                obs = ob.build(pos, vel, accv, gyro, np.array([c["vx"], c["vy"]]), c["wz"])
                t_inf0 = time.monotonic()
                action = pol(obs)
                t_inf1 = time.monotonic()
                if not np.all(np.isfinite(action)):
                    reason, fault = "policy returned NaN/inf", True
                    break
                ob.advance(action)
                filt = low_pass(pol.sign * action * pol.action_scale, filt, pol.action_filter)
                target = np.clip(filt, lo, hi)
                if k < pol.ramp_steps:                  # blend in from where the robot stands
                    a = (k + 1) / pol.ramp_steps
                    target = start_pos + a * (target - start_pos)
                target = limit_rate(target, prev_target, pol.cmd_rate, CTRL_DT)
                prev_target = target
                sent = {i: to_ticks(math.degrees(t), o) for i, t, o in zip(ids, target, offs)}
                if not dry:
                    try:
                        bus.sync_move(sent, speed, acc)
                    except ServoBusError as e:
                        reason, fault = f"bus write failed: {e}", True
                        break

                dt_ms = (time.monotonic() - t0) * 1000
                step_ms_sum += dt_ms
                slog.add(t=t0 - t_start, step_ms=dt_ms, read_ms=(t_read - t0) * 1000,
                         infer_ms=(t_inf1 - t_inf0) * 1000, imu_seq=seq if seq is not None else -1,
                         imu_age_ms=age * 1000,
                         imu_raw=[s["ax"], s["ay"], s["az"], s["gx"], s["gy"], s["gz"]],
                         pos_ticks=[raw[i][0] for i in ids], speed_ticks=[raw[i][1] for i in ids],
                         obs=obs, action=action, target=target, sent_ticks=[sent[i] for i in ids],
                         tilt_deg=tilt, heading=ob.psi, cmd=[c["vx"], c["vy"], c["wz"], c["gait_freq"]])
                k += 1
                with self._lock:
                    st = self._stats
                    st["steps"] = k
                    st["max_step_ms"] = round(max(st["max_step_ms"], dt_ms), 2)
                    st["mean_step_ms"] = round(step_ms_sum / k, 2)
                    st["max_imu_age_ms"] = round(max(st["max_imu_age_ms"], age * 1000), 1)
                    self.last = {"tilt_deg": round(tilt_lp, 1), "heading_deg": round(math.degrees(ob.psi), 1),
                                 "action_max_abs": round(float(np.abs(action).max()), 3),
                                 "pos_deg": [round(math.degrees(x), 1) for x in servo_pos]}
                # live rig in the GUI: where the robot IS — in a dry run (servos untouched) where the
                # policy WOULD send it, otherwise the twin would sit still and show nothing
                shown = target if dry else servo_pos
                S.set(multi={j: round(math.degrees(x), 1) for j, x in zip(pol.joints, shown)})
                nxt += CTRL_DT
                slack = nxt - time.monotonic()
                if slack < 0:
                    with self._lock:
                        self._stats["overruns"] += 1
                    nxt = time.monotonic()               # do not try to catch up in a burst
                else:
                    time.sleep(slack)
        except Exception as e:                                          # noqa: BLE001
            reason, fault = f"{type(e).__name__}: {e}", True
        finally:
            if fault and not dry:
                # go limp: a servo that holds its pose against a falling body takes the whole
                # impact in the printed brackets (2026-10-22: left hip yaw bracket torn open
                # at the hard stop while the pose was held after a fall). _release() tries
                # every servo even if one fails.
                self._release(bus, ids, dry)
            elif held and self._stop.is_set() and not S.abort.is_set():
                try:                                                    # freeze, torque stays on
                    raw = bus.sync_read(ids)
                    bus.sync_move({i: raw[i][0] for i in ids}, 200, 30)
                except Exception:                                       # noqa: BLE001
                    pass
            with self._lock:
                self._stats["stop_reason"] = reason
            self._save_log(slog, pol, plan, speed, acc, dry, gyro_bias, reason, fault)
            S.log(f"policy '{self.name}' ended: {reason}"
                  + (" — torque released" if fault and not dry else ""))
            S.set(running=False, phase="error" if fault else "done",
                  error=reason if fault else None, multi=None)

    def _save_log(self, slog: StepLog, pol, plan, speed, acc, dry, gyro_bias, reason, fault):
        if len(slog) == 0:
            return
        stamp = time.strftime("%Y%m%d-%H%M%S")
        path = self.log_dir / f"{stamp}_{self.name}{'_dry' if dry else ''}.npz"
        with self._lock:
            cmd = dict(self._cmd)
        meta = {"policy": self.name, "dry_run": dry, "stop_reason": reason, "fault": fault,
                "steps": len(slog), "truncated": slog.full, "ctrl_dt": CTRL_DT,
                "joints": pol.joints, "joint_sign_flip": pol.flip, "ids": [e["id"] for e in plan],
                "offsets": [e["offset"] for e in plan], "limits_deg": [[e["lo"], e["hi"]] for e in plan],
                "action_scale": pol.action_scale, "servo_speed": speed, "servo_acc": acc, "start_ramp_steps": pol.ramp_steps,
                "gyro_bias_dps": [float(x) for x in gyro_bias], "cmd": cmd,
                "start_pose_dev_deg": self._start_dev, "start_acc_mg": self._start_acc_mg,
                "obs_layout": [[n, k] for n, k in EXPECTED_LAYOUT],
                "imu_raw_units": "ax ay az [mg], gx gy gz [dps], raw chip axes",
                "speed_units": "servo ticks/s as read from the bus",
                "up_in_imu": [float(x) for x in pol.up_in_imu]}
        try:
            slog.save(path, meta)
            self.last_log = path.name
            self.S.log(f"policy: {len(slog)} steps logged to {path}")
        except Exception as e:                                          # noqa: BLE001
            self.S.log(f"WARNING: policy log could not be written: {e}")

    @staticmethod
    def _release(bus, ids, dry):
        if dry:
            return
        for i in ids:
            try:
                bus.torque_off(i)
            except Exception:                                           # noqa: BLE001
                pass
