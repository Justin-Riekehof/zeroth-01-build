#!/usr/bin/env python3
"""Zeroth-01 single-servo test GUI — backend.

Serves the three.js frontend, the pinned CAD model (GLB) and a small API to
run a one-servo-at-a-time movement test with live position streaming (SSE).

Run (in src/servo_gui):
    uv sync
    uv run server.py          -> http://127.0.0.1:8451
"""

import json
import threading
import time
from datetime import date
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from servo_bus import (CENTER_TICKS, POS_MAX_SAFE, POS_MIN_SAFE, ServoBus,
                       ServoBusError, SimBus, rel_deg_to_ticks, serial_ports,
                       ticks_to_rel_deg)

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
GLB_PATH = REPO_ROOT / "resources" / "cad" / "z001-opus-m-93de7567.glb"
JOINTS_PATH = REPO_ROOT / "resources" / "cad" / "z001-joints-m-93de7567.json"
MAP_PATH = HERE / "servo_map.json"
LIMITS_PATH = REPO_ROOT / "hardware" / "joint_limits.json"
SERVO_IDS_PATH = REPO_ROOT / "hardware" / "servo_ids.json"

POLL_S = 0.04          # position poll interval during a test
TOLERANCE = 25         # ticks (~2.2 deg), same as bench test


# ---------------------------------------------------------------- state

class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.bus = None                # ServoBus | None (real hardware)
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
            self.live["log"] = self.live["log"][-80:]

    def set(self, **kw):
        with self.lock:
            self.live.update(kw)

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.live))


S = State()
app = FastAPI(title="Zeroth-01 servo test GUI")


# ---------------------------------------------------------------- test run

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


def _move_and_wait(bus, p, target: int, label: str):
    start = bus.read_pos(p.servo_id)
    bus.move(p.servo_id, target, p.speed, p.acc)
    S.set(target=ticks_to_rel_deg(target), phase=label)
    timeout = abs(target - start) / p.speed + 2.0
    t0 = time.monotonic()
    while True:
        if S.abort.is_set():
            raise ServoBusError("aborted by user")
        pos = bus.read_pos(p.servo_id)
        S.set(pos=pos, deg=ticks_to_rel_deg(pos))
        if abs(pos - target) <= TOLERANCE:
            S.log(f"reached {ticks_to_rel_deg(target):+.1f} deg "
                  f"(actual {ticks_to_rel_deg(pos):+.1f} deg)")
            return
        if time.monotonic() - t0 > timeout:
            S.log(f"WARNING: target {ticks_to_rel_deg(target):+.1f} deg not "
                  f"reached after {timeout:.1f} s "
                  f"(actual {ticks_to_rel_deg(pos):+.1f} deg)")
            return
        time.sleep(POLL_S)


def _start_and_ping(bus, p) -> None:
    S.set(phase="ping")
    model = bus.ping(p.servo_id)
    S.log(f"servo ID {p.servo_id} responds (model {model}"
          f"{', simulated' if bus.simulated else ''})")
    pos = bus.read_pos(p.servo_id)
    S.set(pos=pos, deg=ticks_to_rel_deg(pos))
    S.log(f"start position {ticks_to_rel_deg(pos):+.1f} deg")


def _test_body(bus, p: "TestParams"):
    lo, hi = rel_deg_to_ticks(p.min_deg), rel_deg_to_ticks(p.max_deg)
    _move_and_wait(bus, p, lo, "to lower limit")
    for i in range(p.cycles):
        tag = f" (cycle {i + 1}/{p.cycles})" if p.cycles > 1 else ""
        _move_and_wait(bus, p, hi, "sweep up" + tag)
        _move_and_wait(bus, p, lo, "sweep down" + tag)
    S.log("test finished")


def _center_body(bus, p):
    _move_and_wait(bus, p, CENTER_TICKS, "to center (mount position)")
    S.log("center reached: +0.0 deg (tick 2048) — mount the part now")


# ------------------------------------------------------------ group runs

def _move_all_and_wait(bus, p, plan, targets: dict, label: str):
    """Command several servos at once and poll until all reached (or timeout)."""
    id2joint = {e["id"]: e["joint"] for e in plan}
    starts = {sid: bus.read_pos(sid) for sid in targets}
    for sid, t in targets.items():
        bus.move(sid, t, p.speed, p.acc)
    S.set(phase=label)
    timeout = max(abs(t - starts[sid]) for sid, t in targets.items()) \
        / p.speed + 2.0
    t0 = time.monotonic()
    while True:
        if S.abort.is_set():
            raise ServoBusError("aborted by user")
        done = True
        multi = dict(S.snapshot().get("multi") or {})
        for sid, t in targets.items():
            pos = bus.read_pos(sid)
            multi[id2joint[sid]] = ticks_to_rel_deg(pos)
            if abs(pos - t) > TOLERANCE:
                done = False
        S.set(multi=multi)
        if done:
            S.log(f"{label}: all targets reached")
            return
        if time.monotonic() - t0 > timeout:
            S.log(f"WARNING: {label}: not all targets reached "
                  f"after {timeout:.1f} s")
            return
        time.sleep(POLL_S)


def _group_center_body(bus, p, plan):
    _move_all_and_wait(bus, p, plan,
                       {e["id"]: CENTER_TICKS for e in plan},
                       "group: to center")
    S.log("all selected servos at center (+0.0 deg / tick 2048)")


def _group_test_body(bus, p, plan):
    if p.mode == "simultaneous":
        lo_t = {e["id"]: rel_deg_to_ticks(e["lo"]) for e in plan}
        hi_t = {e["id"]: rel_deg_to_ticks(e["hi"]) for e in plan}
        _move_all_and_wait(bus, p, plan, lo_t, "group: to lower limits")
        for i in range(p.cycles):
            tag = f" (cycle {i + 1}/{p.cycles})" if p.cycles > 1 else ""
            _move_all_and_wait(bus, p, plan, hi_t, "group: sweep up" + tag)
            _move_all_and_wait(bus, p, plan, lo_t, "group: sweep down" + tag)
    else:                                    # sequential, ascending ID
        for e in plan:
            S.log(f"--- {e['joint']} (ID {e['id']}) "
                  f"[{e['lo']:+.1f}, {e['hi']:+.1f}] deg ---")
            lo = {e["id"]: rel_deg_to_ticks(e["lo"])}
            hi = {e["id"]: rel_deg_to_ticks(e["hi"])}
            _move_all_and_wait(bus, p, plan, lo,
                               f"{e['joint']}: to lower limit")
            for i in range(p.cycles):
                tag = f" (cycle {i + 1}/{p.cycles})" if p.cycles > 1 else ""
                _move_all_and_wait(bus, p, plan, hi,
                                   f"{e['joint']}: sweep up" + tag)
                _move_all_and_wait(bus, p, plan, lo,
                                   f"{e['joint']}: sweep down" + tag)
            bus.torque_off(e["id"])
    S.log("group test finished")


def _run_group(bus, p, plan, body):
    try:
        S.set(phase="ping")
        for e in plan:
            model = bus.ping(e["id"])
            S.log(f"ID {e['id']} ({e['joint']}) responds (model {model}"
                  f"{', simulated' if bus.simulated else ''})")
        body(bus, p, plan)
        S.set(phase="done")
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
        for e in plan:
            try:
                bus.torque_off(e["id"])
            except Exception:
                pass
        S.log("torque disabled (all selected)")
        if bus.simulated:
            bus.close()
        S.set(running=False, target=None, multi=None)


def _run(bus, p, body):
    try:
        _start_and_ping(bus, p)
        body(bus, p)
        S.set(phase="done")
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
        try:
            bus.torque_off(p.servo_id)
            S.log("torque disabled")
        except Exception:
            S.log("WARNING: could not disable torque")
        if bus.simulated:
            bus.close()
        S.set(running=False, target=None)


# ---------------------------------------------------------------- api

@app.get("/api/status")
def status():
    with S.lock:
        connected = S.bus is not None
        port = S.bus.port if S.bus else None
    return {"model_present": GLB_PATH.exists(), "connected": connected,
            "port": port, "live": S.snapshot(),
            "limits": {"min_deg": ticks_to_rel_deg(POS_MIN_SAFE),
                       "max_deg": ticks_to_rel_deg(POS_MAX_SAFE)}}


@app.get("/api/ports")
def ports():
    return serial_ports()


class ConnectParams(BaseModel):
    port: str | None = None


@app.post("/api/connect")
def connect(p: ConnectParams):
    port = p.port
    if not port:
        found = serial_ports()
        if len(found) != 1:
            raise HTTPException(400, "Select a port "
                                     f"({len(found)} candidates found).")
        port = found[0]["device"]
    with S.lock:
        if S.bus:
            raise HTTPException(400, "Already connected.")
    try:
        bus = ServoBus(port)
    except ServoBusError as e:
        raise HTTPException(400, str(e)) from e
    with S.lock:
        S.bus = bus
    S.log(f"connected to {port}")
    return {"ok": True, "port": port}


@app.post("/api/disconnect")
def disconnect():
    with S.lock:
        if S.live["running"]:
            raise HTTPException(400, "Test running — stop it first.")
        bus, S.bus = S.bus, None
    if bus:
        bus.close()
        S.log("disconnected")
    return {"ok": True}


class PingParams(BaseModel):
    servo_id: int = Field(1, ge=1, le=253)


@app.get("/api/scan")
def scan(id_from: int = 1, id_to: int = 30):
    with S.lock:
        bus = S.bus
        if S.live["running"]:
            raise HTTPException(400, "Bus busy — a run is in progress.")
    if not bus:
        raise HTTPException(400, "Not connected.")
    found = bus.scan(id_from, id_to)
    S.log(f"bus scan {id_from}-{id_to}: "
          + (", ".join(f"ID {f['id']} (model {f['model']})" for f in found)
             if found else "no servos found"))
    return {"found": found}


class SetIdParams(BaseModel):
    old_id: int = Field(ge=1, le=253)
    new_id: int = Field(ge=1, le=253)


@app.post("/api/set_id")
def set_id(p: SetIdParams):
    with S.lock:
        bus = S.bus
        if S.live["running"]:
            raise HTTPException(400, "Bus busy — a run is in progress.")
    if not bus:
        raise HTTPException(400, "Not connected.")
    try:
        model = bus.set_id(p.old_id, p.new_id)
    except ServoBusError as e:
        raise HTTPException(400, str(e)) from e
    S.log(f"servo ID changed: {p.old_id} -> {p.new_id} "
          f"(model {model}, persistent)")
    return {"ok": True, "model": model}


@app.post("/api/ping")
def ping(p: PingParams):
    with S.lock:
        bus = S.bus
    if not bus:
        raise HTTPException(400, "Not connected.")
    try:
        model = bus.ping(p.servo_id)
    except ServoBusError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "model": model}


def _launch(p, body, banner: str):
    with S.lock:
        if S.live["running"]:
            raise HTTPException(400, "A run is already in progress.")
        bus = S.bus
    if p.simulate:
        bus = SimBus(start_ticks=CENTER_TICKS)
    elif not bus:
        raise HTTPException(400, "Not connected (or enable simulation).")
    S.abort.clear()
    S.set(running=True, phase="starting", servo_id=p.servo_id, error=None)
    S.log(banner)
    t = threading.Thread(target=_run, args=(bus, p, body), daemon=True)
    with S.lock:
        S.runner = t
    t.start()
    return {"ok": True}


@app.post("/api/test")
def start_test(p: TestParams):
    if p.min_deg >= p.max_deg:
        raise HTTPException(400, "min must be smaller than max.")
    # safety: never sweep beyond configured joint limits (hardware/joint_limits.json)
    lims = _read_limits().get(p.joint) if p.joint else None
    if lims:
        lo = max(p.min_deg, lims["min_deg"])
        hi = min(p.max_deg, lims["max_deg"])
        if lo >= hi:
            raise HTTPException(400, f"Interval lies outside the configured "
                                     f"limits [{lims['min_deg']:+.1f}, "
                                     f"{lims['max_deg']:+.1f}] of {p.joint}.")
        if (lo, hi) != (p.min_deg, p.max_deg):
            S.log(f"interval clamped to configured limits "
                  f"[{lo:+.1f}, {hi:+.1f}] deg of {p.joint} "
                  f"(save new limits to widen)")
            p = p.model_copy(update={"min_deg": lo, "max_deg": hi})
    return _launch(p, _test_body,
                   f"--- test: ID {p.servo_id} ({p.servo_model}"
                   f"{', ' + p.node if p.node else ''}) "
                   f"{p.min_deg:+.1f}..{p.max_deg:+.1f} deg, speed {p.speed}, "
                   f"{'SIMULATION' if p.simulate else 'hardware'} ---")


class CenterParams(BaseModel):
    servo_id: int = Field(1, ge=1, le=253)
    speed: int = Field(300, ge=1, le=3400)
    acc: int = Field(50, ge=0, le=254)
    simulate: bool = False


@app.post("/api/center")
def move_center(p: CenterParams):
    return _launch(p, _center_body,
                   f"--- move to center: ID {p.servo_id}, speed {p.speed}, "
                   f"{'SIMULATION' if p.simulate else 'hardware'} ---")


class GroupParams(BaseModel):
    joints: list[str] = Field(min_length=1)
    mode: str = Field("sequential", pattern="^(sequential|simultaneous)$")
    speed: int = Field(500, ge=1, le=3400)
    acc: int = Field(50, ge=0, le=254)
    cycles: int = Field(1, ge=1, le=20)
    simulate: bool = False


def _read_servo_ids() -> dict:
    if SERVO_IDS_PATH.exists():
        return json.loads(SERVO_IDS_PATH.read_text(encoding="utf-8"))
    return {}


def _build_plan(joints_sel: list[str]) -> list[dict]:
    ids = _read_servo_ids()
    lims = _read_limits()
    plan = []
    for j in joints_sel:
        if j not in ids:
            raise HTTPException(400, f"No servo ID configured for '{j}' "
                                     "(hardware/servo_ids.json).")
        L = lims.get(j)
        lo, hi = (L["min_deg"], L["max_deg"]) if L else (-30.0, 30.0)
        plan.append({"joint": j, "id": ids[j], "lo": lo, "hi": hi,
                     "limited": bool(L)})
    plan.sort(key=lambda e: e["id"])
    return plan


def _launch_group(p: GroupParams, body, kind: str):
    plan = _build_plan(p.joints)
    with S.lock:
        if S.live["running"]:
            raise HTTPException(400, "A run is already in progress.")
        bus = S.bus
    if p.simulate:
        bus = SimBus(start_ticks=CENTER_TICKS)
    elif not bus:
        raise HTTPException(400, "Not connected (or enable simulation).")
    S.abort.clear()
    S.set(running=True, phase="starting", servo_id=None, error=None, multi={})
    S.log(f"--- group {kind}: "
          + ", ".join(f"ID {e['id']} ({e['joint']})" for e in plan)
          + f", {p.mode}, {'SIMULATION' if p.simulate else 'hardware'} ---")
    for e in plan:
        if not e["limited"]:
            S.log(f"WARNING: no limits configured for {e['joint']} — "
                  f"using safe default [-30, +30] deg")
    t = threading.Thread(target=_run_group, args=(bus, p, plan, body),
                         daemon=True)
    with S.lock:
        S.runner = t
    t.start()
    return {"ok": True, "plan": plan}


@app.post("/api/group/center")
def group_center(p: GroupParams):
    return _launch_group(p, _group_center_body, "center")


@app.post("/api/group/test")
def group_test(p: GroupParams):
    return _launch_group(p, _group_test_body, "test")


@app.get("/api/servo_ids")
def servo_ids():
    return _read_servo_ids()


@app.post("/api/stop")
def stop():
    S.abort.set()
    return {"ok": True}


@app.get("/api/stream")
async def stream():
    import asyncio

    async def gen():
        while True:
            yield f"data: {json.dumps(S.snapshot())}\n\n"
            await asyncio.sleep(0.05)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# ------------------------------------------------------------ joint limits

def _read_limits() -> dict:
    if LIMITS_PATH.exists():
        return json.loads(LIMITS_PATH.read_text(encoding="utf-8"))
    return {}


def _mirror_name(joint: str) -> str | None:
    if "left" in joint:
        return joint.replace("left", "right", 1)
    if "right" in joint:
        return joint.replace("right", "left", 1)
    return None


@app.get("/api/limits")
def get_limits():
    return _read_limits()


class LimitEntry(BaseModel):
    joint: str
    min_deg: float = Field(ge=-180, le=180)
    max_deg: float = Field(ge=-180, le=180)
    symmetric: bool = True


@app.post("/api/limits")
def set_limits(e: LimitEntry):
    if e.min_deg >= e.max_deg:
        raise HTTPException(400, "min must be smaller than max.")
    limits = _read_limits()
    entry = {"min_deg": e.min_deg, "max_deg": e.max_deg,
             "set": "direct", "updated": date.today().isoformat()}
    limits[e.joint] = entry
    mirrored = skipped = None
    m = _mirror_name(e.joint)
    if e.symmetric and m and m != e.joint:
        # never silently overwrite limits someone set directly on the mirror
        if limits.get(m, {}).get("set") == "direct":
            skipped = m
        else:
            limits[m] = {**entry, "set": "mirrored"}
            mirrored = m
    LIMITS_PATH.parent.mkdir(parents=True, exist_ok=True)
    LIMITS_PATH.write_text(json.dumps(limits, indent=2, sort_keys=True),
                           encoding="utf-8")
    S.log(f"joint limits saved: {e.joint} [{e.min_deg:+.1f}, {e.max_deg:+.1f}]"
          + (f" + mirrored to {mirrored}" if mirrored else "")
          + (f" ({skipped} kept its own direct values)" if skipped else ""))
    return {"ok": True, "mirrored": mirrored, "skipped": skipped,
            "limits": limits}


@app.get("/api/joints")
def joints():
    if JOINTS_PATH.exists():
        return json.loads(JOINTS_PATH.read_text(encoding="utf-8"))
    return {"joints": []}


# ---------------------------------------------------------------- mapping

@app.get("/api/mapping")
def get_mapping():
    if MAP_PATH.exists():
        return json.loads(MAP_PATH.read_text(encoding="utf-8"))
    return {}


class MapEntry(BaseModel):
    node: str
    servo_id: int = Field(ge=1, le=253)
    servo_model: str = "STS3250"
    axis: str = Field("Z", pattern="^[XYZ]$")
    joint: str | None = None       # CAD joint -> also update servo_ids.json


@app.post("/api/mapping")
def set_mapping(e: MapEntry):
    mapping = get_mapping()
    mapping[e.node] = {"servo_id": e.servo_id, "servo_model": e.servo_model,
                       "axis": e.axis}
    MAP_PATH.write_text(json.dumps(mapping, indent=2), encoding="utf-8")
    # keep the canonical joint -> ID config (group runs) in sync
    ids = _read_servo_ids()
    if e.joint:
        old = ids.get(e.joint)
        ids[e.joint] = e.servo_id
        SERVO_IDS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SERVO_IDS_PATH.write_text(
            json.dumps(ids, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        S.log(f"servo ID config: {e.joint} -> ID {e.servo_id}"
              + (f" (was {old})" if old not in (None, e.servo_id) else ""))
    return {"ok": True, "servo_ids": ids}


# ---------------------------------------------------------------- model file

@app.get("/model")
def model():
    if not GLB_PATH.exists():
        raise HTTPException(404, "GLB snapshot missing — see resources/cad/VERSION.md")
    return FileResponse(GLB_PATH, media_type="model/gltf-binary")


@app.put("/api/model")
async def upload_model(request: Request):
    data = await request.body()
    if data[:4] != b"glTF":
        raise HTTPException(400, "Not a binary glTF (.glb) file.")
    GLB_PATH.parent.mkdir(parents=True, exist_ok=True)
    GLB_PATH.write_bytes(data)
    S.log(f"CAD model stored ({len(data) / 1e6:.1f} MB) -> {GLB_PATH.name}")
    return {"ok": True, "size": len(data)}


app.mount("/", StaticFiles(directory=HERE / "static", html=True), name="static")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8451)
