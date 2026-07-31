#!/usr/bin/env python3
"""Zeroth-01 Pi intent service.

Runs ON the robot (Raspberry Pi, adapter on USB) and executes motion
locally against the servo bus via the shared zbot_core engine. Clients —
the web GUI in wireless mode, later a teleoperation site — send only
high-level intents over HTTP; per-cycle setpoints never cross Wi-Fi
(jitter must not sit inside a servo control loop).

Endpoints (intents only, no static files, no calibration editing):
    GET  /status            engine live state + bus + service info
    GET  /demos             taught-in demos available on this robot
    POST /demo/{name}       play a demo (limits/offsets enforced locally)
    POST /center            all configured servos to center (hold optional)
    POST /release           torque off (all or selected joints)
    POST /stop              E-stop: abort run, everything goes limp
    POST /connect           (re)open the serial bus
    POST /heartbeat         arms/feeds the streaming watchdog (future teleop)

Safety is Pi-local and never trusted from clients: joint limits, mount
offsets and the corrupt-calibration guard run inside MotionEngine; the
watchdog soft-holds if a future streaming session stops heartbeating.

Configuration:
    ZBOT_ROOT      config root (hardware/, demos/) — default ~/zbot
    ZBOT_SIMULATE  "1" -> SimBus (bench-first testing without hardware)
    ZBOT_PORT      HTTP port (default 8460)

Run:  uvicorn service:app --host 0.0.0.0 --port 8460
"""

import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from zbot_core.bus import ServoBusError, open_bus
from zbot_core.config import ConfigStore
from zbot_core.motion import GroupParams, MotionEngine, MotionError

API_VERSION = 2

ROOT = Path(os.environ.get("ZBOT_ROOT", Path.home() / "zbot"))
SIMULATE = os.environ.get("ZBOT_SIMULATE", "0") == "1"

CFG = ConfigStore(ROOT)
ENGINE = MotionEngine(CFG)
S = ENGINE.S

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
    yield
    ENGINE.stop()
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


def _engine(fn):
    try:
        return fn()
    except MotionError as e:
        raise HTTPException(400, str(e)) from e


# ------------------------------------------------------------ intents

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
            "live": S.snapshot()}


@app.get("/demos")
def demos():
    return {"demos": CFG.load_demos(
        on_invalid=lambda n: S.log(f"WARNING: demo file {n} invalid"))}


@app.post("/connect")
def connect():
    err = _connect_bus()
    if err:
        raise HTTPException(400, err)
    return {"ok": True, "port": S.bus.port}


@app.post("/demo/{name}")
def play_demo(name: str):
    try:
        demo = CFG.load_demo(name)
    except (KeyError, ValueError) as e:
        raise HTTPException(404, f"Demo '{name}' not found.") from e
    _engine(lambda: ENGINE.play_demo(demo, simulate=False))
    return {"ok": True, "demo": demo.name, "steps": len(demo.steps)}


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


@app.post("/release")
def release(p: ReleaseIntent = ReleaseIntent()):
    with S.lock:
        bus = S.bus
        if S.live["running"]:
            raise HTTPException(400, "Run in progress — POST /stop first.")
    if not bus:
        raise HTTPException(400, "Bus not connected.")
    ids = CFG.servo_ids()
    sel = p.joints or sorted(ids, key=lambda j: ids[j])
    released = []
    for j in sel:
        if j not in ids:
            continue
        try:
            bus.torque_off(ids[j])
            released.append(ids[j])
        except Exception:
            pass
    S.log(f"torque released: IDs {released}")
    return {"ok": True, "released": released}


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0",
                port=int(os.environ.get("ZBOT_PORT", "8460")))
