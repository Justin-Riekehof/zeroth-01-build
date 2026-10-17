"""Fall detection from the head IMU, and the get-up it can trigger.

The head is rigidly fixed to the torso (no neck servo), so gravity in the
head board's frame IS the torso's orientation. Board axes -> body axes come
from connection.json "imu_axes" (same mapping as head.head_tilt).

Gravity in body axes (accelerometer at rest reads +1 g along the axis that
points UP):

    tilt     angle between the body's up axis and vertical (0 = upright)
    azimuth  which way the body lies, seen from above along the body:
             0 = face down (fell forwards), ±180 = on its back,
             +90 = on its right side, -90 = on its left side

States (with 5 deg hysteresis on each threshold of hardware/getup.json):
    upright  tilt <= upright_deg
    tilted   in between (kneeling forward, mid-fall, mid-get-up)
    fallen   tilt >= fallen_deg
    unknown  no fresh IMU sample
Samples whose magnitude is far from 1 g (an impact, a swing) do not change
the state — gravity is not the only acceleration then.

A fallen robot is assigned to the get-up case it is closer to: |azimuth| <
90 -> "front", otherwise "back". Lying (partly) on a side is reported with
the side and how far it is rolled from face down / back.

Automatic get-up (opt-in, getup.json "auto"): only for a fall that happens
while NO run is active — demos such as push_ups go to the floor on purpose,
and a fall inside a run cannot be told apart from that. Once the robot lies
still for hold_s it plays the case's sequence, up to max_attempts times per
fall; reaching "upright" ends the episode, /stop cancels it.
"""

import math
import threading
import time

from zbot_core.getup import CASE_LABEL, GetupConfig

from head import DEFAULT_AXES, _cross, _unit

STALE_S = 1.0          # IMU sample older than this -> state "unknown"
HYST_DEG = 5.0
G_BAND = (700.0, 1300.0)   # mg: outside, the sample is dynamic -> keep state
RUN_GRACE_S = 1.0      # a fall this soon after a run counts as part of the run


def gravity_body(sample: dict, axes: dict | None = None):
    """Accelerometer reading as (up, forward, right) in body axes, in mg."""
    axes = {**DEFAULT_AXES, **(axes or {})}
    up_v, fwd_v = _unit(axes["up"]), _unit(axes["forward"])
    right_v = _cross(fwd_v, up_v)
    if not any(right_v):
        raise ValueError("imu_axes: up and forward must be different axes")
    acc = (sample["ax"], sample["ay"], sample["az"])
    dot = lambda v: sum(a * b for a, b in zip(acc, v))
    return dot(up_v), dot(fwd_v), dot(right_v)


def classify(sample: dict, axes: dict | None = None) -> dict:
    """Orientation of the body from one IMU sample (pure; no state)."""
    up, fwd, right = gravity_body(sample, axes)
    g = math.sqrt(up * up + fwd * fwd + right * right) or 1.0
    u, f, r = up / g, fwd / g, right / g
    tilt = math.degrees(math.acos(max(-1.0, min(1.0, u))))
    # the axis that points DOWN reads negative: face down -> f < 0
    az = math.degrees(math.atan2(-r, -f))
    case = "front" if abs(az) < 90 else "back"
    if u < -0.5 and math.hypot(f, r) < 0.5:
        facing = "inverted"
    elif abs(az) <= 45:
        facing = "front"
    elif abs(az) >= 135:
        facing = "back"
    else:
        facing = "right" if az > 0 else "left"
    # roll away from the case's plane: + = toward the right side
    side = az if case == "front" else math.copysign(180.0 - abs(az), az)
    return {"tilt_deg": round(tilt, 1), "azimuth_deg": round(az, 1),
            "side_deg": round(side, 1), "facing": facing, "case": case,
            "g_mg": round(g)}


def lying_label(c: dict) -> str:
    """'face down, rolled 25° to the left' / 'on its right side — closer to
    on its back' — for the log and the GUI."""
    side = c["side_deg"]
    toward = "right" if side > 0 else "left"
    if c["facing"] == "inverted":
        return f"upside down — closer to {CASE_LABEL[c['case']]}"
    if c["facing"] in ("left", "right"):
        return (f"on its {c['facing']} side — closer to "
                f"{CASE_LABEL[c['case']]} ({abs(side):.0f}° rolled)")
    base = CASE_LABEL[c["case"]]
    return base + (f", rolled {abs(side):.0f}° to the {toward}"
                   if abs(side) >= 15 else "")


def next_state(prev: str, c: dict, gc: GetupConfig) -> str:
    t = c["tilt_deg"]
    if not G_BAND[0] <= c["g_mg"] <= G_BAND[1] and prev != "unknown":
        return prev
    if t >= gc.fallen_deg or (prev == "fallen" and t >= gc.fallen_deg - HYST_DEG):
        return "fallen"
    if t <= gc.upright_deg or (prev == "upright" and t <= gc.upright_deg + HYST_DEG):
        return "upright"
    return "tilted"


class PostureMonitor:
    """Daemon thread at ~10 Hz over the IMU reader's latest sample.

    imu       head.ImuReader (snapshot(), axes)
    engine    MotionEngine (S.live["running"], S.log)
    load_cfg  () -> GetupConfig — re-read every few seconds, so a GUI save
              takes effect without a restart
    play      (case) -> None — starts the get-up run (raises on failure)
    """

    CFG_TTL_S = 2.0

    def __init__(self, imu, engine, load_cfg, play, period_s: float = 0.1):
        self.imu, self.engine = imu, engine
        self.load_cfg, self.play = load_cfg, play
        self.period_s = period_s
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._gc: GetupConfig | None = None
        self._gc_t = -1e9
        self.reset()

    def reset(self):
        with self._lock:
            self.state = "unknown"
            self.c: dict | None = None
            self.state_since: float | None = None
            self.still_since: float | None = None
            self.last_run_t = -1e9
            self.was_fallen = False
            self.episode: dict | None = None
            self.cfg_error: str | None = None
            self.settled = False

    # -- thread
    def start(self):
        if self._thread:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="posture")
        self._thread.start()

    def stop(self):
        self._stop.set()
        t, self._thread = self._thread, None
        if t and t is not threading.current_thread():
            t.join(timeout=1.0)

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.tick(time.monotonic())
            except Exception as e:                  # never kill the thread
                with self._lock:
                    self.cfg_error = f"{type(e).__name__}: {e}"
            self._stop.wait(self.period_s)

    # -- config
    def config(self, now: float | None = None) -> GetupConfig:
        now = time.monotonic() if now is None else now
        if self._gc is None or now - self._gc_t > self.CFG_TTL_S:
            try:
                self._gc = self.load_cfg()
                self.cfg_error = None
            except Exception as e:                  # broken file: defaults, auto off
                self._gc = GetupConfig()
                self.cfg_error = f"getup.json invalid: {e}"
            self._gc_t = now
        return self._gc

    def invalidate(self):
        self._gc = None

    # -- one step
    def tick(self, now: float):
        log = self.engine.S.log
        snap = self.imu.snapshot()
        s, age = snap.get("sample"), snap.get("age_s")
        with self.engine.S.lock:
            running = bool(self.engine.S.live["running"])
        gc = self.config(now)
        with self._lock:
            if running:
                self.last_run_t = now
            if not s or age is None or age > STALE_S:
                if self.state not in ("unknown",):
                    log("POSTURE: no fresh IMU data — fall detection paused")
                self.state, self.c, self.state_since = "unknown", None, None
                self.still_since, self.settled = None, False
                return
            c = classify(s, self.imu.axes)
            prev = self.state
            state = next_state(prev, c, gc)
            self.c = c
            if state != prev:
                self.state, self.state_since = state, now
            still = all(abs(s.get(k, 0.0)) < gc.still_dps
                        for k in ("gx", "gy", "gz"))
            if not still:
                self.still_since = None
            elif self.still_since is None:
                self.still_since = now
            quiet_from = max(self.still_since or now, self.state_since or now,
                             self.last_run_t + RUN_GRACE_S)
            self.settled = (state == "fallen" and self.still_since is not None
                            and now - quiet_from >= gc.hold_s)
            settled = self.settled
            msgs, trigger = [], None
            if state == "fallen" and prev != "fallen" and not self.was_fallen:
                self.was_fallen = True
                in_run = running or now - self.last_run_t < RUN_GRACE_S
                msgs.append(f"POSTURE: FALLEN — {lying_label(c)} "
                            f"(tilt {c['tilt_deg']:.0f}°, azimuth "
                            f"{c['azimuth_deg']:+.0f}°)"
                            + (" during a run" if in_run else ""))
                if gc.auto and not in_run and prev != "unknown":
                    self.episode = {"attempts": 0, "gave_up": False,
                                    "case": c["case"]}
                    msgs.append(f"auto get-up armed: starts once the robot "
                                f"lies still for {gc.hold_s:.1f} s")
            elif state == "upright" and self.was_fallen:
                self.was_fallen = False
                ep = self.episode
                msgs.append("POSTURE: upright again"
                            + (f" — get-up succeeded (attempt "
                               f"{ep['attempts']})" if ep and ep["attempts"]
                               else ""))
                self.episode = None
            ep = self.episode
            if (ep and not ep["gave_up"] and settled and not running
                    and gc.auto):
                if ep["attempts"] >= gc.max_attempts:
                    ep["gave_up"] = True
                    msgs.append(f"auto get-up: still down after "
                                f"{ep['attempts']} attempt(s) — giving up "
                                "(stand it up by hand or use ▶ get up)")
                else:
                    ep["attempts"] += 1
                    ep["case"] = c["case"]
                    # counts as a run from now on: the next attempt needs a
                    # fresh quiet phase even if this one never got going
                    self.last_run_t = now
                    self.settled = False
                    trigger = (c["case"], ep["attempts"], lying_label(c))
        for m in msgs:
            log(m)
        if trigger:
            case, n, label = trigger
            log(f"auto get-up: attempt {n}/{gc.max_attempts} — {label} "
                f"-> '{case}' sequence")
            try:
                self.play(case)
            except Exception as e:
                with self._lock:
                    if self.episode:
                        self.episode["gave_up"] = True
                log(f"auto get-up FAILED to start: {e}")

    def cancel(self, why: str = "stop"):
        """E-stop: never restart a get-up the user just aborted."""
        with self._lock:
            ep, self.episode = self.episode, None
        if ep and not ep["gave_up"]:
            self.engine.S.log(f"auto get-up cancelled ({why})")

    def snapshot(self) -> dict:
        gc = self.config()
        with self._lock:
            c = self.c or {}
            now = time.monotonic()
            label = None
            if self.state == "fallen":
                label = lying_label(c)
            elif self.state == "tilted":
                toward = {"front": "forward", "back": "backward",
                          "left": "to the left", "right": "to the right",
                          "inverted": "head down"}[c["facing"]]
                label = f"tilted {c['tilt_deg']:.0f}° {toward}"
            elif self.state == "upright":
                label = "upright"
            return {
                "state": self.state, "label": label,
                "tilt_deg": c.get("tilt_deg"),
                "azimuth_deg": c.get("azimuth_deg"),
                "side_deg": c.get("side_deg"),
                "facing": c.get("facing"), "case": c.get("case"),
                "for_s": None if self.state_since is None
                else round(now - self.state_since, 1),
                "settled": self.settled,
                "auto": gc.auto,
                "episode": dict(self.episode) if self.episode else None,
                "error": self.cfg_error,
            }
