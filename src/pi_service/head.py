"""Head peripherals of the Zeroth-01: IMU display and camera.

Both live on the Raspberry Pi but are NOT part of the servo bus:

* **IMU display** — a Waveshare RP2040-LCD-1.28 (round 1.28" LCD + QMI8658
  IMU) on USB serial. It runs its own firmware (src/head_display/) that draws
  the eye and streams one JSON line per frame; the stock Waveshare demo
  (`acc_x = 295.166mg , ...` lines) is understood as well, so the values show
  up in the GUI even before the board is re-flashed. Units are the sensor's
  native ones everywhere: acceleration in **mg**, rate in **dps** (deg/s),
  temperature in **°C**, supply voltage in **V**.
* **Camera Module 3** — read through `rpicam-vid` as MJPEG on demand: the
  first HTTP client starts the process, the last one leaving stops it a few
  seconds later. Nothing runs while nobody is watching.

Neither may ever stall the servo side: everything here runs in its own
daemon thread with its own lock, and a missing device is a status field,
not an exception.
"""

import glob
import json
import math
import re
import shutil
import subprocess
import threading
import time
from collections import deque

# --------------------------------------------------------------- IMU parsing

# Waveshare demo firmware, one sample = three lines:
#   acc_x   = 295.166mg , acc_y  = 1065.186mg , acc_z  = 158.203mg
#   gyro_x  = -0.125dps, gyro_y = -7.328dps, gyro_z = -0.219dps
#   Raw value: 0xa43, voltage: 4.232959 V
_DEMO_PAIR = re.compile(r"(acc|gyro)_([xyz])\s*=\s*([-+]?\d+(?:\.\d+)?)")
_DEMO_VOLT = re.compile(r"voltage:\s*([-+]?\d+(?:\.\d+)?)")
_DEMO_KEY = {"acc": "a", "gyro": "g"}

SAMPLE_KEYS = ("ax", "ay", "az", "gx", "gy", "gz")


class ImuParser:
    """Turns serial lines into samples. Feed lines, collect finished samples.

    JSON lines (our firmware) are one sample each. Demo lines are merged:
    the gyro line closes a sample that the acc line opened; the voltage line
    is remembered and attached to the next samples.
    """

    def __init__(self):
        self._partial: dict = {}
        self._vsys: float | None = None

    def feed(self, line: str) -> dict | None:
        line = line.strip()
        if not line:
            return None
        if line[0] == "{":
            try:
                d = json.loads(line)
            except ValueError:
                return None
            if not all(k in d for k in SAMPLE_KEYS):
                return None
            s = {k: float(d[k]) for k in SAMPLE_KEYS}
            if "t" in d:
                s["temp_c"] = float(d["t"])
            if "v" in d:
                s["vsys"] = float(d["v"])
            for k in ("mood", "rot", "fps", "lid"):
                if k in d:
                    s[k] = d[k]
            s["source"] = "json"
            return s
        m = _DEMO_VOLT.search(line)
        if m:
            self._vsys = float(m.group(1))
            return None
        pairs = _DEMO_PAIR.findall(line)
        if not pairs:
            return None
        for kind, axis, val in pairs:
            self._partial[_DEMO_KEY[kind] + axis] = float(val)
        if all(k in self._partial for k in SAMPLE_KEYS):
            s, self._partial = self._partial, {}
            if self._vsys is not None:
                s["vsys"] = self._vsys
            s["source"] = "demo"
            return s
        return None


# ------------------------------------------------------------ head-frame tilt
# The board sits in the head at some orientation; which board axis points
# up/forward is a mount property, so it is configuration (connection.json
# "imu_axes"), not code. Values: "+x" "-x" "+y" "-y" "+z" "-z".

DEFAULT_AXES = {"up": "+y", "forward": "-z"}


def _unit(spec: str) -> tuple[float, float, float]:
    sign = -1.0 if spec.startswith("-") else 1.0
    i = "xyz".index(spec[-1])
    return tuple(sign if k == i else 0.0 for k in range(3))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def head_tilt(sample: dict, axes: dict | None = None) -> dict:
    """Gravity-based tilt of the head in degrees.

    pitch: nose down positive; roll: right ear down positive; tilt: total
    angle from upright. Only valid while the head is not accelerating
    (gravity ≈ the only acceleration) — good enough for a status readout.
    """
    axes = {**DEFAULT_AXES, **(axes or {})}
    up_v, fwd_v = _unit(axes["up"]), _unit(axes["forward"])
    right_v = _cross(fwd_v, up_v)          # right-handed head frame
    if not any(right_v):                   # up == forward: unusable config
        return {"pitch_deg": None, "roll_deg": None, "tilt_deg": None}
    acc = (sample["ax"], sample["ay"], sample["az"])
    dot = lambda v: sum(a * b for a, b in zip(acc, v))
    up, fwd, right = dot(up_v), dot(fwd_v), dot(right_v)
    g = math.sqrt(up * up + fwd * fwd + right * right) or 1.0
    up_c = max(-1.0, min(1.0, up / g))
    # an accelerometer axis that points DOWN reads negative (reaction force):
    # nose down -> forward axis dips -> fwd < 0 -> pitch positive
    return {"pitch_deg": round(math.degrees(math.atan2(-fwd, up)), 1),
            "roll_deg": round(math.degrees(math.atan2(-right, up)), 1),
            "tilt_deg": round(math.degrees(math.acos(up_c)), 1)}


# ---------------------------------------------------------------- IMU reader

SERVO_ADAPTER_HINT = "1a86"          # QinHeng CH343 — never the IMU board


def find_imu_port(exclude: str | None = None) -> str | None:
    """Pick the head board among /dev/serial/by-id — a Pico under the stock
    firmware, a 'MicroPython Board in FS mode' under ours."""
    cands = sorted(glob.glob("/dev/serial/by-id/*"))
    cands = [c for c in cands if SERVO_ADAPTER_HINT not in c
             and c != exclude]
    for pat in ("MicroPython", "Pico"):
        for c in cands:
            if pat in c:
                return c
    return None


class ImuReader:
    """Daemon thread: keeps the serial link to the head board open, parses
    what it sends, holds the latest sample. Reconnects on its own."""

    HISTORY = 50                       # ~2.5 s at the firmware's 20 Hz

    def __init__(self, port: str = "auto", axes: dict | None = None,
                 exclude_port: str | None = None, baud: int = 115200):
        self.port_cfg = port
        self.exclude_port = exclude_port
        self.axes = {**DEFAULT_AXES, **(axes or {})}
        self.baud = baud
        self.lock = threading.Lock()
        self.sample: dict | None = None
        self.sample_t = 0.0
        self.seq = 0
        self.port: str | None = None
        self.error: str | None = None
        self.history: deque = deque(maxlen=self.HISTORY)
        self._ser = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- lifecycle
    def start(self):
        if self.port_cfg == "none":
            self.error = "disabled (imu_port: none)"
            return
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="imu-reader")
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._close()

    def _close(self):
        ser, self._ser = self._ser, None
        if ser:
            try:
                ser.close()
            except Exception:
                pass
        with self.lock:
            self.port = None

    def _open(self) -> bool:
        import serial
        port = self.port_cfg
        if port == "auto":
            port = find_imu_port(self.exclude_port)
            if not port:
                self.error = "no head board on USB (Pico / MicroPython)"
                return False
        try:
            self._ser = serial.Serial(port, self.baud, timeout=1.0)
        except (serial.SerialException, OSError) as e:
            self.error = f"{type(e).__name__}: {e}"
            return False
        with self.lock:
            self.port = port
            self.error = None
        return True

    def _run(self):
        parser = ImuParser()
        while not self._stop.is_set():
            if self._ser is None:
                if not self._open():
                    self._stop.wait(2.0)
                    continue
                parser = ImuParser()
            try:
                raw = self._ser.readline()
            except Exception as e:           # unplugged mid-read
                self.error = f"{type(e).__name__}: {e}"
                self._close()
                continue
            if not raw:
                continue
            s = parser.feed(raw.decode("ascii", "replace"))
            if s is None:
                continue
            s.update(head_tilt(s, self.axes))
            with self.lock:
                self.seq += 1
                s["seq"] = self.seq
                self.sample = s
                self.sample_t = time.monotonic()
                self.history.append(s)

    # -- API
    def send(self, line: str) -> bool:
        """One command line to the firmware (see src/head_display/README)."""
        ser = self._ser
        if ser is None:
            return False
        try:
            ser.write((line.strip() + "\n").encode("ascii"))
            return True
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
            return False

    def snapshot(self) -> dict:
        with self.lock:
            s = dict(self.sample) if self.sample else None
            age = (time.monotonic() - self.sample_t) if s else None
            return {"connected": self.port is not None,
                    "port": self.port, "error": self.error,
                    "age_s": round(age, 2) if age is not None else None,
                    "sample": s}


# ------------------------------------------------------------------ camera

SOI = b"\xff\xd8\xff"
EOI = b"\xff\xd9"


def split_jpegs(buf: bytearray) -> list[bytes]:
    """Cut complete JPEG frames off the front of `buf` (mutated in place).
    rpicam-vid --codec mjpeg writes them back to back with no framing."""
    frames = []
    while True:
        start = buf.find(SOI)
        if start < 0:
            del buf[:-2]                 # a marker may straddle two reads
            return frames
        end = buf.find(EOI, start + 3)
        if end < 0:
            if start:
                del buf[:start]
            return frames
        frames.append(bytes(buf[start:end + 2]))
        del buf[:end + 2]


class CameraStreamer:
    """`rpicam-vid` MJPEG on demand, one process shared by every client."""

    IDLE_STOP_S = 4.0                  # keep running this long after the last client

    def __init__(self, width=640, height=480, fps=15, binary="rpicam-vid"):
        self.width, self.height, self.fps = width, height, fps
        self.binary = binary
        self.lock = threading.Lock()
        self.cond = threading.Condition(self.lock)
        self.frame: bytes | None = None
        self.frame_no = 0
        self.frame_t = 0.0
        self.clients = 0
        self.error: str | None = None
        self._proc: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None
        self._last_client_t = 0.0
        self._measured_fps = 0.0

    @property
    def available(self) -> bool:
        return shutil.which(self.binary) is not None

    def _cmd(self) -> list[str]:
        return [self.binary, "-n", "-t", "0", "--codec", "mjpeg",
                "--width", str(self.width), "--height", str(self.height),
                "--framerate", str(self.fps), "-o", "-"]

    def _ensure_running(self):
        with self.lock:
            if self._proc and self._proc.poll() is None:
                return
            if not self.available:
                self.error = f"{self.binary} not installed"
                raise RuntimeError(self.error)
            try:
                self._proc = subprocess.Popen(
                    self._cmd(), stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, bufsize=0)
            except OSError as e:
                self.error = f"{type(e).__name__}: {e}"
                raise RuntimeError(self.error) from e
            self.error = None
            self._reader = threading.Thread(target=self._pump,
                                            args=(self._proc,), daemon=True,
                                            name="camera-pump")
            self._reader.start()

    def _pump(self, proc: subprocess.Popen):
        buf = bytearray()
        t_win, n_win = time.monotonic(), 0
        try:
            while True:
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                buf += chunk
                for jpg in split_jpegs(buf):
                    with self.cond:
                        self.frame = jpg
                        self.frame_no += 1
                        self.frame_t = time.monotonic()
                        self.cond.notify_all()
                    n_win += 1
                    if self.frame_t - t_win >= 2.0:
                        self._measured_fps = n_win / (self.frame_t - t_win)
                        t_win, n_win = self.frame_t, 0
                # stop when nobody has been watching for a while
                if (self.clients == 0
                        and time.monotonic() - self._last_client_t
                        > self.IDLE_STOP_S):
                    break
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(3)
                except subprocess.TimeoutExpired:
                    proc.kill()
            rc = proc.returncode
            with self.cond:
                if rc not in (0, None, -15) and self.clients:
                    self.error = f"{self.binary} exited with {rc}"
                if self._proc is proc:
                    self._proc = None
                self._measured_fps = 0.0
                self.cond.notify_all()

    def stop(self):
        with self.lock:
            proc = self._proc
        if proc and proc.poll() is None:
            proc.terminate()

    def frames(self, timeout: float = 5.0):
        """Generator of JPEG bytes for one client; registers/unregisters it."""
        # register BEFORE starting the process: the pump's idle check must
        # never see "no clients" while the first one is still on its way in
        with self.lock:
            self.clients += 1
            self._last_client_t = time.monotonic()
        try:
            self._ensure_running()
        except RuntimeError:
            with self.lock:
                self.clients -= 1
            raise
        with self.lock:
            last = self.frame_no             # only frames newer than "now"
        try:
            while True:
                with self.cond:
                    ok = self.cond.wait_for(
                        lambda: self.frame_no != last or self._proc is None,
                        timeout=timeout)
                    if self._proc is None or not ok:
                        return
                    last, frame = self.frame_no, self.frame
                yield frame
        finally:
            with self.lock:
                self.clients -= 1
                self._last_client_t = time.monotonic()

    def snapshot(self, timeout: float = 3.0) -> bytes | None:
        for jpg in self.frames(timeout=timeout):
            return jpg
        return None

    def status(self) -> dict:
        with self.lock:
            running = self._proc is not None and self._proc.poll() is None
            return {"available": self.available, "streaming": running,
                    "clients": self.clients, "error": self.error,
                    "width": self.width, "height": self.height,
                    "fps": round(self._measured_fps, 1) if running else 0.0}


def mjpeg_multipart(frames, boundary: bytes = b"frame"):
    """Wrap raw JPEGs as multipart/x-mixed-replace parts for <img> tags."""
    for jpg in frames:
        yield (b"--" + boundary + b"\r\nContent-Type: image/jpeg\r\n"
               b"Content-Length: " + str(len(jpg)).encode() + b"\r\n\r\n"
               + jpg + b"\r\n")
