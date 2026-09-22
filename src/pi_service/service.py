#!/usr/bin/env python3
"""Zeroth-01 Pi intent service.

Runs ON the robot (Raspberry Pi, adapter on USB) and executes motion
locally against the servo bus via the shared zbot_core engine. Clients —
the web GUI in wireless mode, later a teleoperation site — send only
high-level intents over HTTP; per-cycle setpoints never cross Wi-Fi
(jitter must not sit inside a servo control loop).

Endpoints (intents + the calibration the robot itself enforces; no static
files):
    GET  /status            engine live state + bus + battery + service info
    GET  /demos             taught-in demos available on this robot
    POST /demos             save a demo (wireless teach-in; repo stays canonical)
    POST /demos/delete      remove a demo from the robot
    GET  /limits            the joint ranges this robot enforces
    POST /limits            calibrate one joint's range (wireless calibration;
                            repo stays canonical)
    GET  /robot_pose        hand-posed pose in CAD deg (wireless teach-in)
    POST /demo/{name}       play a demo (limits/offsets enforced locally)
    POST /center            all configured servos to center (hold optional)
    POST /release           torque off (all or selected joints)
    POST /lock              freeze joints at their current position (teach-in)
    POST /shutdown          clean OS shutdown (protects the SD card; cut power
                            after the ACT LED stops — servos keep holding)
    POST /stop              E-stop: run aborted OR held pose released
    POST /connect           (re)open the serial bus
    POST /heartbeat         arms/feeds the streaming watchdog (future teleop)

Head peripherals (head.py — IMU display board + Camera Module 3):
    GET  /head              IMU sample (mg / dps / °C / V, head tilt) + camera state
    GET  /camera.mjpg       live MJPEG stream (multipart) — starts rpicam-vid on demand
    GET  /camera.jpg        one still from the same stream
    POST /head/cmd          one command line to the display firmware ("mood happy")

Safety is Pi-local and never trusted from clients: joint limits, mount
offsets and the corrupt-calibration guard run inside MotionEngine; the
watchdog soft-holds if a future streaming session stops heartbeating; the
battery monitor halts the OS cleanly before the hardware low-voltage cutoff
(XY-CD63) can pull the 5 V rail from under the Pi (SD-card protection).

Configuration:
    ZBOT_ROOT      config root (hardware/, demos/) — default ~/zbot
    ZBOT_SIMULATE  "1" -> SimBus (bench-first testing without hardware)
    ZBOT_PORT      HTTP port (default 8460)
    connection.json "battery" block (optional, see BatteryMonitor): thresholds
                   of the software shutdown — must stay ABOVE the XY-CD63 setting

Run:  uvicorn service:app --host 0.0.0.0 --port 8460
"""

import os
import subprocess
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from zbot_core.bus import ServoBusError, open_bus
from zbot_core.config import ConfigStore, Demo, limit_log_line
from zbot_core.motion import (GroupParams, MotionEngine, MotionError,
                              lock_joints, release_joints, to_rel)

from head import CameraStreamer, ImuReader, mjpeg_multipart

API_VERSION = 8

# Needs the matching NOPASSWD line in /etc/sudoers.d/zbot-deploy on the Pi.
# Kept as one exact command so the sudoers rule can stay maximally narrow.
SHUTDOWN_CMD = ["sudo", "-n", "/usr/sbin/shutdown", "-h", "now"]

ROOT = Path(os.environ.get("ZBOT_ROOT", Path.home() / "zbot"))
SIMULATE = os.environ.get("ZBOT_SIMULATE", "0") == "1"

CFG = ConfigStore(ROOT)
ENGINE = MotionEngine(CFG)
S = ENGINE.S


def _head_peripherals() -> tuple[ImuReader, CameraStreamer]:
    """connection.json keys (all optional, host-specific like "port"):
        imu_port   "auto" (default) | "none" | /dev/serial/by-id/...
        imu_axes   {"up": "+y", "forward": "-z"} — board axes in the head
        camera     {"width": 640, "height": 480, "fps": 15}"""
    c = CFG.connection()
    imu = ImuReader(port="none" if SIMULATE else c.get("imu_port", "auto"),
                    axes=c.get("imu_axes"), exclude_port=c.get("port"))
    cam = dict(c.get("camera") or {})
    return imu, CameraStreamer(width=int(cam.get("width", 640)),
                               height=int(cam.get("height", 480)),
                               fps=int(cam.get("fps", 15)),
                               binary=cam.get("binary", "rpicam-vid"))


IMU, CAMERA = _head_peripherals()

# ------------------------------------------------------------ bus lifecycle

def _connect_bus() -> str | None:
    """Open the bus per connection.json (or SimBus). Returns error or None."""
    with S.lock:
        if S.bus:
            return None
    try:
        port = CFG.connection().get("port", "auto")
        bus = open_bus(None if port == "auto" else port, simulate=SIMULATE)
    except (ServoBusError, ValueError) as e:
        # ValueError covers a malformed connection.json (JSONDecodeError):
        # never let a broken config file turn startup into a restart loop
        return f"{type(e).__name__}: {e}"
    with S.lock:
        S.bus = bus
    S.log(f"bus connected: {bus.port}"
          + (" (SIMULATED)" if getattr(bus, 'simulated', False) else ""))
    return None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    err = _connect_bus()
    if err:
        S.log(f"WARNING: bus not connected at startup: {err} "
              "— POST /connect to retry")
    IMU.start()
    BATTERY.start()
    FLIGHT.start()
    yield
    FLIGHT.stop()
    BATTERY.stop()
    ENGINE.stop()
    IMU.stop()
    CAMERA.stop()
    with S.lock:
        bus, S.bus = S.bus, None
    if bus:
        bus.close()


app = FastAPI(title="Zeroth-01 Pi intent service", lifespan=lifespan)

# The wireless web GUI is served from the laptop (different origin). Auth
# comes with the public teleop stack later — transport stays agnostic.
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])


# ------------------------------------------------------------ watchdog

class StreamWatchdog:
    """Scaffold for FUTURE streaming clients (teleop): while a streaming
    session is armed, missing heartbeats for `timeout_s` triggers a soft
    hold (stop the run; servos keep their last position goal). Demo intents
    are self-contained and do NOT arm it — execution is already Pi-local.
    """

    def __init__(self, engine: MotionEngine, timeout_s: float = 0.5):
        self.engine = engine
        self.timeout_s = timeout_s
        self.armed = False
        self.last_beat = 0.0
        self._thread: threading.Thread | None = None

    def beat(self):
        self.last_beat = time.monotonic()
        if self.armed and self._thread is None:
            self._thread = threading.Thread(target=self._watch, daemon=True)
            self._thread.start()

    def arm(self):
        self.armed = True
        self.beat()

    def disarm(self):
        self.armed = False

    def _watch(self):
        while self.armed:
            if time.monotonic() - self.last_beat > self.timeout_s:
                self.engine.S.log("WATCHDOG: heartbeat lost — soft hold")
                self.engine.stop()      # abort any run; servos hold last goal
                self.armed = False
                break
            time.sleep(self.timeout_s / 5)
        self._thread = None


WATCHDOG = StreamWatchdog(ENGINE)


# ------------------------------------------------------------ battery

def _do_shutdown() -> subprocess.CompletedProcess:
    """Isolated so tests can patch it — never run the real command in CI."""
    return subprocess.run(SHUTDOWN_CMD, capture_output=True, text=True,
                          timeout=10)


class BatteryMonitor:
    """Pack voltage through the servo bus, and the clean shutdown it triggers.

    The Pi has no ADC; the Feetech servos measure their supply rail (register
    62, 0.1 V steps) and that rail is the 3S pack behind fuse, switch and
    XY-CD63 relay. One configured servo is polled every `period_s` (the
    first that answers, remembered until it stops answering).

    Levels:   ok  |  warn (< warn_v)  |  low (< shutdown_v)  |  unknown
    Going back up needs `hysteresis_v` more, so the log does not flap.

    Shutdown: a reading below `shutdown_v` must persist for `hold_s` — servo
    inrush sags the rail for milliseconds, an empty pack for good. Then the
    run is aborted (the runner releases torque; an idle-held pose keeps
    holding, same as the GUI button) and SHUTDOWN_CMD halts the OS, once.
    A failed halt (sudoers rule missing) is retried every `retry_s`.

    The XY-CD63 must be set BELOW `shutdown_v` — with equal thresholds the
    relay wins the race and the card sees a hard power loss again.

    connection.json "battery": {"enabled": true, "servo_id": null,
        "warn_v": 11.1, "shutdown_v": 10.8, "hold_s": 10, "period_s": 2}
    """

    DEFAULTS = {"enabled": True, "servo_id": None, "warn_v": 11.1,
                "shutdown_v": 10.8, "hold_s": 10.0, "period_s": 2.0,
                "hysteresis_v": 0.2, "retry_s": 60.0}

    def __init__(self, engine: MotionEngine, cfg: ConfigStore,
                 do_shutdown, settings: dict | None = None, notify=None):
        self.engine = engine
        self.cfg = cfg
        self.do_shutdown = do_shutdown
        self.notify = notify or (lambda line: False)   # e.g. a line to the head display
        o = {**self.DEFAULTS, **(settings or {})}
        self.enabled = bool(o["enabled"])
        self.servo_id = o["servo_id"]
        self.warn_v = float(o["warn_v"])
        self.shutdown_v = float(o["shutdown_v"])
        self.hold_s = float(o["hold_s"])
        self.period_s = max(0.2, float(o["period_s"]))
        self.hysteresis_v = float(o["hysteresis_v"])
        self.retry_s = float(o["retry_s"])
        if self.shutdown_v >= self.warn_v:
            raise ValueError("battery: shutdown_v must be below warn_v")
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._good_id: int | None = None
        self.reset()

    def reset(self):
        """Fresh state (tests); the thresholds stay."""
        with self._lock:
            self.volts: float | None = None
            self.read_id: int | None = None
            self.min_v: float | None = None
            self.level = "unknown"
            self.error: str | None = None
            self.last_read: float | None = None      # monotonic
            self.low_since: float | None = None
            self.shutdown_at: float | None = None
            self.shutdown_ok = False
            self.last_attempt: float | None = None

    # -- thread

    def start(self):
        if not self.enabled or self._thread:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="battery")
        self._thread.start()

    def stop(self):
        self._stop.set()
        t, self._thread = self._thread, None
        if t and t is not threading.current_thread():
            t.join(timeout=2 * self.period_s)

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.tick(time.monotonic())
            except Exception as e:                    # never kill the thread
                with self._lock:
                    self.error = f"{type(e).__name__}: {e}"
            self._stop.wait(self.period_s)

    # -- one measurement

    def _read(self) -> tuple[float | None, int | None, str | None]:
        with self.engine.S.lock:
            bus = self.engine.S.bus
        if bus is None:
            return None, None, "bus not connected"
        if self.servo_id is not None:
            ids = [int(self.servo_id)]
        else:
            ids = sorted(self.cfg.servo_ids().values())
            if self._good_id in ids:                  # try the last one first
                ids.remove(self._good_id)
                ids.insert(0, self._good_id)
        if not ids:
            return None, None, "no servos configured"
        for sid in ids:
            try:
                v = bus.read_voltage(sid)
            except Exception as e:
                return None, None, f"{type(e).__name__}: {e}"
            if v is not None:
                self._good_id = sid
                return v, sid, None
        self._good_id = None
        return None, None, "no servo answers"

    def tick(self, now: float):
        v, sid, err = self._read()
        with self._lock:
            self.error = err
            if v is None:
                # No data: keep level/low timer as they are — the servos are
                # also silent right after the relay tripped, but then the Pi
                # is gone with them; a bus hiccup must not fake a recovery.
                if self.last_read is not None and \
                        now - self.last_read > 5 * self.period_s:
                    self.level = "unknown"
                return
            self.volts, self.read_id, self.last_read = v, sid, now
            self.min_v = v if self.min_v is None else min(self.min_v, v)
            prev = self.level
            hyst = self.hysteresis_v
            if v < self.shutdown_v or \
                    (prev == "low" and v < self.shutdown_v + hyst):
                level = "low"
            elif v < self.warn_v or \
                    (prev in ("warn", "low") and v < self.warn_v + hyst):
                level = "warn"
            else:
                level = "ok"
            self.level = level
            # hold timer: starts below shutdown_v, cleared only by a clear
            # recovery (hysteresis) — a pack hovering at the threshold must
            # not keep resetting it
            if v < self.shutdown_v:
                if self.low_since is None:
                    self.low_since = now
            elif v >= self.shutdown_v + hyst:
                self.low_since = None
            low_for = now - self.low_since if self.low_since is not None \
                else 0.0
            due = (self.low_since is not None and low_for >= self.hold_s
                   and not self.shutdown_ok
                   and (self.last_attempt is None
                        or now - self.last_attempt >= self.retry_s))
        log = self.engine.S.log
        if level != prev:
            if level == "warn":
                log(f"BATTERY: {v:.1f} V (ID {sid}) — low, charge soon; "
                    f"OS halts at {self.shutdown_v:.1f} V")
            elif level == "low":
                log(f"BATTERY: {v:.1f} V (ID {sid}) below "
                    f"{self.shutdown_v:.1f} V — OS halts in {self.hold_s:.0f} s "
                    "unless it recovers")
            elif prev in ("warn", "low"):
                log(f"BATTERY: {v:.1f} V — recovered")
        if due:
            self._shutdown(now, v, low_for)

    def _shutdown(self, now: float, v: float, low_for: float):
        S = self.engine.S
        with self._lock:
            self.last_attempt = now
            self.shutdown_at = now
        S.log(f"BATTERY: {v:.1f} V for {low_for:.0f} s — stopping the run "
              "and halting the OS before the hardware cutoff trips")
        # the head display keeps its 5 V after the Pi halts: its warning
        # screen is the one that stays visible on the robot
        self.notify("alert battery")
        self.engine.stop()
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            with S.lock:
                running = S.live["running"]
            if not running:
                break
            time.sleep(0.05)
        r = self.do_shutdown()
        with self._lock:
            self.shutdown_ok = r.returncode == 0
        if r.returncode == 0:
            S.log("SHUTDOWN: OS halting (battery) — cut power after the "
                  "ACT LED stops")
        else:
            S.log("BATTERY: shutdown FAILED — sudoers rule for "
                  f"'{' '.join(SHUTDOWN_CMD[1:])}' missing? "
                  f"({(r.stderr or '').strip()}); retry in "
                  f"{self.retry_s:.0f} s — CUT POWER MANUALLY after "
                  "sudo shutdown -h now")

    def snapshot(self) -> dict:
        now = time.monotonic()
        with self._lock:
            return {
                "enabled": self.enabled,
                "volts": self.volts, "servo_id": self.read_id,
                "min_v": self.min_v, "level": self.level,
                "age_s": None if self.last_read is None
                else round(now - self.last_read, 1),
                "low_for_s": None if self.low_since is None
                else round(now - self.low_since, 1),
                "warn_v": self.warn_v, "shutdown_v": self.shutdown_v,
                "hold_s": self.hold_s,
                "shutdown": None if self.shutdown_at is None
                else ("halting" if self.shutdown_ok else "failed"),
                "error": self.error,
            }


BATTERY = BatteryMonitor(ENGINE, CFG, lambda: _do_shutdown(),   # late-bound: tests patch it
                         CFG.connection().get("battery"),
                         notify=lambda line: IMU.send(line))


class FlightRecorder:
    """Crash-proof log on the Pi (2026-09-22: the Pi keeps dropping off the
    network mid-run and the journal of the dead boot is gone every time).

    Every line goes to ~/zbot/logs/flight-YYYYMMDD.log with flush + fsync, so
    a hard power cut loses at most the line being written. Content:
      boot    once at service start (boot id, uptime, throttled flags so far)
      engine  every engine log line (bus, runs, warnings) as it happens
      vitals  every `period_s`: pack voltage + level (servo reading),
              vcgencmd throttled flags (0x50000 = under-voltage now/since
              boot), CPU temperature, Wi-Fi link/level, load average
    After a crash: `tail -n 60 ~/zbot/logs/flight-*.log`, or GET /flight?n=60.
    Files older than `keep_days` are removed at startup."""

    def __init__(self, root: Path, battery: BatteryMonitor, state, period_s: float = 2.0, keep_days: int = 14):
        self.dir = root / "logs"
        self.battery, self.state = battery, state
        self.period_s, self.keep_days = period_s, keep_days
        self._fh = None; self._day = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._sink = lambda msg: self.write("engine", msg)

    # -- file handling
    def path(self) -> Path:
        return self.dir / f"flight-{time.strftime('%Y%m%d')}.log"

    def _open(self):
        day = time.strftime("%Y%m%d")
        if self._fh and self._day == day:
            return
        if self._fh:
            self._fh.close()
        self.dir.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.dir / f"flight-{day}.log", "a", encoding="utf-8")
        self._day = day

    def write(self, kind: str, msg: str):
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {kind:6s} {msg}\n"
        with self._lock:
            try:
                self._open()
                self._fh.write(line); self._fh.flush(); os.fsync(self._fh.fileno())
            except OSError:
                pass

    def tail(self, n: int = 60) -> list[str]:
        p = self.path()
        if not p.exists():
            return []
        with open(p, encoding="utf-8", errors="replace") as f:
            return [l.rstrip("\n") for l in f.readlines()[-max(1, n):]]

    # -- vitals
    @staticmethod
    def _read(cmd_or_path, timeout=1.0) -> str:
        try:
            if isinstance(cmd_or_path, list):
                return subprocess.run(cmd_or_path, capture_output=True, text=True, timeout=timeout).stdout.strip()
            return Path(cmd_or_path).read_text().strip()
        except Exception:
            return ""

    def vitals(self) -> str:
        b = self.battery.snapshot()
        thr = self._read(["vcgencmd", "get_throttled"])          # "throttled=0x50005"
        thr = thr.split("=")[-1] if thr else "n/a"
        flags = ""
        try:
            v = int(thr, 16)
            flags = "".join(f for f, bit in (("U", 0x1), ("F", 0x2), ("T", 0x4), ("S", 0x8),
                                             ("u", 0x10000), ("f", 0x20000), ("t", 0x40000), ("s", 0x80000)) if v & bit)
        except ValueError:
            pass
        temp = self._read("/sys/class/thermal/thermal_zone0/temp")
        temp = f"{int(temp) / 1000:.1f}C" if temp.isdigit() else "n/a"
        wl = ""
        for line in self._read("/proc/net/wireless").splitlines()[2:]:
            parts = line.split()
            if len(parts) >= 4:
                wl = f"{parts[0]} link {parts[2].rstrip('.')} level {parts[3].rstrip('.')}dBm"
        load = self._read("/proc/loadavg").split()[:1]
        return (f"pack {b['volts'] if b['volts'] is not None else 'n/a'}V ({b['level']}, min {b['min_v']}) "
                f"throttled {thr}{'[' + flags + ']' if flags else ''} cpu {temp} "
                f"{wl or 'wifi n/a'} load {load[0] if load else 'n/a'}")

    def _loop(self):
        while not self._stop.wait(self.period_s):
            self.write("vitals", self.vitals())

    def start(self):
        try:
            for f in self.dir.glob("flight-*.log"):
                if time.time() - f.stat().st_mtime > self.keep_days * 86400:
                    f.unlink()
        except OSError:
            pass
        boot_id = self._read("/proc/sys/kernel/random/boot_id") or "n/a"
        up = self._read("/proc/uptime").split()[:1]
        self.write("boot", f"service start, boot {boot_id[:8]}, uptime {up[0] if up else 'n/a'}s, "
                           f"api {API_VERSION}; {self.vitals()}")
        self.state.sinks.append(self._sink)
        self._thread = threading.Thread(target=self._loop, daemon=True); self._thread.start()

    def stop(self):
        self._stop.set()
        if self._sink in self.state.sinks:
            self.state.sinks.remove(self._sink)
        self.write("stop", "service stopping")
        with self._lock:
            if self._fh:
                self._fh.close(); self._fh = None


FLIGHT = FlightRecorder(ROOT, BATTERY, S)


def _engine(fn):
    try:
        return fn()
    except MotionError as e:
        raise HTTPException(400, str(e)) from e


# ------------------------------------------------------------ intents

@app.get("/flight")
def flight(n: int = 60):
    """Tail of today's flight-recorder file (see FlightRecorder)."""
    return {"file": str(FLIGHT.path()), "lines": FLIGHT.tail(n)}


@app.get("/status")
def status():
    with S.lock:
        bus = S.bus
    return {"api_version": API_VERSION, "root": str(ROOT),
            "simulate": SIMULATE,
            "bus": {"connected": bus is not None,
                    "port": getattr(bus, "port", None),
                    "simulated": getattr(bus, "simulated", False)},
            "watchdog": {"armed": WATCHDOG.armed,
                         "timeout_s": WATCHDOG.timeout_s},
            "battery": BATTERY.snapshot(),
            "head": _head_state(),
            "live": S.snapshot()}


# ------------------------------------------------------------ head

def _head_state() -> dict:
    return {"imu": IMU.snapshot(), "camera": CAMERA.status()}


@app.get("/head")
def head():
    return _head_state()


@app.get("/camera.mjpg")
def camera_stream():
    """Live view for <img src=...>: multipart MJPEG straight from rpicam-vid.
    The first viewer starts the camera process, it stops itself a few seconds
    after the last one is gone."""
    try:
        frames = CAMERA.frames()
        first = next(frames)            # fail here, as 503, not mid-stream
    except RuntimeError as e:
        raise HTTPException(503, f"camera: {e}") from e
    except StopIteration:
        raise HTTPException(503, "camera: no frame — "
                            + (CAMERA.error or "rpicam-vid produced nothing"))

    def gen():
        yield from mjpeg_multipart(iter([first]))
        yield from mjpeg_multipart(frames)
    return StreamingResponse(
        gen(), media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store"})


@app.get("/camera.jpg")
def camera_still():
    try:
        jpg = CAMERA.snapshot()
    except RuntimeError as e:
        raise HTTPException(503, f"camera: {e}") from e
    if jpg is None:
        raise HTTPException(503, "camera: no frame")
    return Response(jpg, media_type="image/jpeg",
                    headers={"Cache-Control": "no-store"})


class HeadCmd(BaseModel):
    line: str = Field(min_length=1, max_length=120, pattern=r"^[ -~]+$")


@app.post("/head/cmd")
def head_cmd(p: HeadCmd):
    """Forward one line to the display firmware (src/head_display/README.md
    lists them: mood, look, blink, rot, ...)."""
    if not IMU.send(p.line):
        raise HTTPException(503, "head board not connected: "
                            + (IMU.error or "?"))
    return {"ok": True}


def _demos_list():
    return CFG.load_demos(
        on_invalid=lambda n: S.log(f"WARNING: demo file {n} invalid"))


@app.get("/demos")
def demos():
    return {"demos": _demos_list()}


@app.post("/demos")
def save_demo(d: Demo):
    """Wireless teach-in: store a demo on the robot (the GUI also saves it
    to the repo — the repo stays canonical, this copy is what /demo/{name}
    plays without a redeploy)."""
    for i, step in enumerate(d.steps, 1):
        for j, deg in step.angles.items():
            if not -180 <= deg <= 180:
                raise HTTPException(400, f"Step {i}: angle {deg} for {j} "
                                         "out of range.")
    try:
        path = CFG.demo_path(d.name)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    CFG.save_demo(d)
    S.log(f"demo saved: '{d.name}' ({len(d.steps)} steps) -> "
          f"demos/{path.name}")
    return {"ok": True, "demos": _demos_list()}


class DemoName(BaseModel):
    name: str


@app.post("/demos/delete")
def delete_demo(p: DemoName):
    try:
        if CFG.delete_demo(p.name):
            S.log(f"demo deleted: '{p.name}'")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "demos": _demos_list()}


# ------------------------------------------------------------ joint limits
# The robot enforces ITS OWN copy of the ranges (MotionEngine re-reads them
# per run), so wireless calibration has to land here — not only in the repo.
# Everything else about calibration (zero/offsets) still comes from a deploy.

@app.get("/limits")
def get_limits():
    return CFG.limits()


class LimitEntry(BaseModel):
    joint: str
    min_deg: float = Field(ge=-180, le=180)
    max_deg: float = Field(ge=-180, le=180)
    symmetric: bool = True


@app.post("/limits")
def set_limits(e: LimitEntry):
    """Calibrate one joint's safe range on the robot. Takes effect on the
    next run without a redeploy; the GUI saves the same values into the repo,
    which stays canonical."""
    try:
        r = CFG.save_limit(e.joint, e.min_deg, e.max_deg, e.symmetric)
    except ValueError as ex:
        raise HTTPException(400, str(ex)) from ex
    S.log(limit_log_line(e.joint, e.min_deg, e.max_deg,
                         r["mirrored"], r["skipped"]))
    return {"ok": True, **r}


@app.get("/robot_pose")
def robot_pose():
    """Current pose of the PHYSICAL robot in CAD-frame degrees — wireless
    teach-in: release torque, hand-pose the robot, capture."""
    with S.lock:
        bus = S.bus
        if S.live["running"]:
            raise HTTPException(400, "Bus busy — a run is in progress.")
    if not bus:
        raise HTTPException(400, "Bus not connected.")
    ids = CFG.servo_ids()
    offs = CFG.offsets()
    pose, missing = {}, []
    for j, sid in ids.items():
        try:
            pose[j] = round(to_rel(bus.read_pos(sid),
                                   float(offs.get(j, 0.0))), 1)
        except ServoBusError:
            missing.append(j)
    if not pose:
        raise HTTPException(400, "No servo responds.")
    return {"pose": pose, "missing": missing}


@app.post("/connect")
def connect():
    err = _connect_bus()
    if err:
        raise HTTPException(400, err)
    return {"ok": True, "port": S.bus.port}


class PlayIntent(BaseModel):
    until: int | None = Field(None, ge=1)     # play only steps 1..until (inclusive)


@app.post("/demo/{name}")
def play_demo(name: str, p: PlayIntent = PlayIntent()):
    try:
        demo = CFG.load_demo(name)
    except (KeyError, ValueError) as e:
        raise HTTPException(404, f"Demo '{name}' not found.") from e
    if p.until is not None and p.until > len(demo.steps):
        raise HTTPException(400, f"Step {p.until} out of range (demo has {len(demo.steps)} steps).")
    _engine(lambda: ENGINE.play_demo(demo, simulate=False, until=p.until))
    return {"ok": True, "demo": demo.name, "steps": p.until or len(demo.steps)}


class CenterIntent(BaseModel):
    hold: bool = True
    speed: int = Field(300, ge=1, le=3400)


@app.post("/center")
def center(p: CenterIntent = CenterIntent()):
    joints = sorted(CFG.servo_ids(), key=lambda j: CFG.servo_ids()[j])
    if not joints:
        raise HTTPException(400, "No servos configured.")
    gp = GroupParams(joints=joints, mode="simultaneous", speed=p.speed,
                     acc=30, cycles=1, simulate=False, hold_center=p.hold)
    _engine(lambda: ENGINE.start_group(gp, "center"))
    return {"ok": True, "joints": len(joints)}


class ReleaseIntent(BaseModel):
    joints: list[str] | None = None    # None -> all configured


def _idle_bus_or_400():
    with S.lock:
        bus = S.bus
        if S.live["running"]:
            raise HTTPException(400, "Run in progress — POST /stop first.")
    if not bus:
        raise HTTPException(400, "Bus not connected.")
    return bus


@app.post("/release")
def release(p: ReleaseIntent = ReleaseIntent()):
    bus = _idle_bus_or_400()
    released = release_joints(bus, CFG.servo_ids(), p.joints)
    S.log(f"torque released: IDs {released}")
    return {"ok": True, "released": released}


@app.post("/lock")
def lock(p: ReleaseIntent = ReleaseIntent()):
    """Teach-in: freeze the given joints (or all) at their current physical
    position — hand-pose a limb, lock it, pose the next one."""
    bus = _idle_bus_or_400()
    locked = lock_joints(bus, CFG.servo_ids(), p.joints)
    S.log(f"torque locked at current position: IDs {locked}")
    return {"ok": True, "locked": locked}


@app.post("/stop")
def stop():
    """E-stop: always available, everything goes limp. During a run the
    aborted runner thread releases all torque; when idle-HOLDING (demos and
    centering park with torque on) there is no runner to do that, so the
    release happens right here — Stop must never be a silent no-op."""
    ENGINE.stop()
    WATCHDOG.disarm()
    with S.lock:
        bus = S.bus
        running = S.live["running"]
    released = []
    if bus and not running:
        ids = CFG.servo_ids()
        for j in sorted(ids, key=lambda k: ids[k]):
            try:
                bus.torque_off(ids[j])
                released.append(ids[j])
            except Exception:
                pass
        if released:
            S.log(f"E-STOP: torque released: IDs {released}")
    return {"ok": True, "released": released}


@app.post("/heartbeat")
def heartbeat():
    WATCHDOG.beat()
    return {"ok": True, "armed": WATCHDOG.armed}


@app.post("/shutdown")
def shutdown():
    """Clean OS shutdown (SD-card-safe power-off). Rejected during a run —
    stop first. Servos keep their last goal and torque (they are powered
    from the servo rail, not the Pi): the robot holds its pose until the
    main switch is cut. Cut power only after the green ACT LED stops."""
    with S.lock:
        if S.live["running"]:
            raise HTTPException(400, "Run in progress — POST /stop first.")
    r = _do_shutdown()
    if r.returncode != 0:
        raise HTTPException(500, "shutdown failed — sudoers rule for "
                                 f"'{' '.join(SHUTDOWN_CMD[1:])}' missing? "
                                 f"({(r.stderr or '').strip()})")
    S.log("SHUTDOWN: OS halting — cut power after the ACT LED stops")
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0",
                port=int(os.environ.get("ZBOT_PORT", "8460")))
