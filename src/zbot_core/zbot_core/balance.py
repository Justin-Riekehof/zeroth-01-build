"""IMU balance assist for demo steps: keeps the torso orientation while the
legs move between two (statically stable) poses.

The head IMU is rigid with the torso, so its gravity tilt IS the torso
attitude. When a step moves a leg (crouch, lift), the centre of mass shifts
over the support foot and the torso starts to pitch/roll. The controller
reads that tilt and adds a small correction on top of the step's own targets:

    pitch (nose down +)  -> ankle_pitch of the stance leg(s)   (ankle strategy)
    roll  (right ear +)  -> hip_yaw of the stance leg          (hip_yaw is the
                            lateral lean joint of this build; single support only)

The reference is the tilt when the series of balanced steps started (the
pose before was stable by assumption); the correction is a PD law on the
deviation from it, clamped and slew-limited, never an integrator — so it
cannot wind up and always falls back to zero when the tilt is right.

Signs: with the foot fixed on the floor, ankle +d turns the torso by -d about
the ankle's joint axis; the signs below follow the MJCF axes (left ankle
+y, right ankle -y, both hip_yaw -x). hardware/balance.json can override them
("pitch_sign", "roll_sign") — verify with "dry_run" before trusting them.
"""

import math

DEFAULTS = {
    "kp_pitch": 0.6,         # joint deg per deg of pitch deviation
    "kd_pitch": 0.08,        # joint deg per deg/s of pitch rate
    "kp_roll": 0.4,
    "kd_roll": 0.05,
    "deadband_deg": 0.7,     # deviations below this are ignored
    "max_deg": 8.0,          # clamp of each joint's correction
    "slew_dps": 40.0,        # max change of a correction [deg/s]
    "tau_s": 0.12,           # low-pass of the (accelerometer) tilt
    "speed": 400,            # servo speed [ticks/s] for correction commands
    "acc": 40,
    "stance": "auto",        # auto | left | right | both
    "stance_gap_deg": 15.0,  # auto: knee-bend difference that marks a stance leg
    "pitch_sign": {"left": 1.0, "right": -1.0},
    "roll_sign": {"left": -1.0, "right": -1.0},
    "dry_run": False,        # compute + log, command nothing
    "enabled": True,         # global kill switch for steps that ask for balance
}

G_BAND = (700.0, 1300.0)     # mg: outside, the tilt reading is dynamic -> hold


def merged(raw: dict | None) -> dict:
    out = {**DEFAULTS}
    for k, v in (raw or {}).items():
        if k not in out:
            continue
        if isinstance(DEFAULTS[k], dict) and isinstance(v, dict):
            out[k] = {**DEFAULTS[k], **v}
        elif isinstance(DEFAULTS[k], type(v)) or (
                isinstance(DEFAULTS[k], float) and isinstance(v, int)):
            out[k] = v
    return out


def pick_stance(cfg: dict, knee_deg: dict[str, float]) -> str:
    """'left' | 'right' | 'both' for a step whose target knee angles are given."""
    s = cfg["stance"]
    if s in ("left", "right", "both"):
        return s
    l = abs(knee_deg.get("left_knee_pitch", 0.0))
    r = abs(knee_deg.get("right_knee_pitch", 0.0))
    if abs(l - r) < cfg["stance_gap_deg"]:
        return "both"
    return "left" if l < r else "right"     # the straighter leg carries


class TiltBalancer:
    ALL = ("left_ankle_pitch", "right_ankle_pitch",
           "left_hip_yaw", "right_hip_yaw")

    def __init__(self, cfg: dict, stance: str):
        self.cfg = cfg
        self.ref: tuple[float, float] | None = None
        self._f: tuple[float, float] | None = None      # filtered pitch, roll
        self._rate = (0.0, 0.0)
        self._t: float | None = None
        self.off = {j: 0.0 for j in self.ALL}
        self.max_dev = (0.0, 0.0)
        self.set_stance(stance)

    def set_stance(self, stance: str):
        """Which joints work for the coming step; the others' corrections
        slew back to zero."""
        c = self.cfg
        self.stance = stance
        sides = ("left", "right") if stance == "both" else (stance,)
        self.pitch_joints = {f"{s}_ankle_pitch": c["pitch_sign"][s] for s in sides}
        # lateral lean only makes sense with ONE foot carrying: two feet down
        # would fight each other
        self.roll_joints = ({f"{s}_hip_yaw": c["roll_sign"][s] for s in sides}
                            if stance != "both" else {})

    @property
    def joints(self) -> list[str]:
        return list(self.ALL)

    def set_reference(self, pitch: float, roll: float):
        self.ref = (pitch, roll)
        self._f, self._t, self._rate = (pitch, roll), None, (0.0, 0.0)

    def update(self, pitch: float, roll: float, g_mg: float, now: float) -> dict:
        """Feed one tilt sample, get the corrections {joint: deg}. A sample
        taken while the body accelerates (|g| off 1 g) leaves them unchanged."""
        if self.ref is None:
            self.set_reference(pitch, roll)
        c = self.cfg
        if not (G_BAND[0] <= g_mg <= G_BAND[1]):
            self._t = now
            return dict(self.off)
        dt = 0.0 if self._t is None else max(0.0, now - self._t)
        self._t = now
        a = 1.0 if dt <= 0 else dt / (c["tau_s"] + dt)
        fp = self._f[0] + a * (pitch - self._f[0])
        fr = self._f[1] + a * (roll - self._f[1])
        rp = (fp - self._f[0]) / dt if dt > 0 else 0.0
        rr = (fr - self._f[1]) / dt if dt > 0 else 0.0
        self._f, self._rate = (fp, fr), (rp, rr)
        ep, er = fp - self.ref[0], fr - self.ref[1]
        self.max_dev = (max(self.max_dev[0], abs(ep)), max(self.max_dev[1], abs(er)))
        db = c["deadband_deg"]
        ep = math.copysign(max(0.0, abs(ep) - db), ep)
        er = math.copysign(max(0.0, abs(er) - db), er)
        step = c["slew_dps"] * dt
        for j in self.ALL:
            if j in self.pitch_joints:
                want = self.pitch_joints[j] * (c["kp_pitch"] * ep + c["kd_pitch"] * rp)
            elif j in self.roll_joints:
                want = self.roll_joints[j] * (c["kp_roll"] * er + c["kd_roll"] * rr)
            else:
                want = 0.0
            self.off[j] = self._slew(self.off[j], want, step)
        return dict(self.off)

    def _slew(self, cur: float, want: float, step: float) -> float:
        m = self.cfg["max_deg"]
        want = max(-m, min(m, want))
        return cur + max(-step, min(step, want - cur))
