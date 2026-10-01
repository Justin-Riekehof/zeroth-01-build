#!/usr/bin/env python3
"""Zeroth-01 single-servo test GUI — backend.

Serves the three.js frontend, the pinned CAD model (GLB) and a small API to
run a one-servo-at-a-time movement test with live position streaming (SSE).

Run (in src/servo_gui):
    uv sync
    uv run server.py          -> http://127.0.0.1:8451
"""

import json
from datetime import date
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from zbot_core.bus import (POS_MAX_SAFE, POS_MIN_SAFE, ServoBus,
                           ServoBusError, rel_deg_to_ticks,
                           serial_ports, ticks_to_rel_deg)
from zbot_core.config import (ConfigStore, Demo, limit_log_line,
                              read_json)
from zbot_core.motion import (CenterParams, GroupParams, MotionEngine,
                              MotionError, TestParams, lock_joints,
                              release_joints)

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
GLB_PATH = REPO_ROOT / "resources" / "cad" / "z001-opus-m-93de7567.glb"
JOINTS_PATH = REPO_ROOT / "resources" / "cad" / "z001-joints-m-93de7567.json"
# printed add-on parts (own designs) shown on top of the pinned model, see resources/cad/attachments/
ATTACH_DIR = REPO_ROOT / "resources" / "cad" / "attachments"
MAP_PATH = HERE / "servo_map.json"

# all calibration/motion configs go through the shared store (repo root here;
# the Pi service later points it at its synced copy)
CFG = ConfigStore(REPO_ROOT)

TOLERANCE = 25         # ticks (~2.2 deg), same as bench test

# bumped on every backend behavior change; the frontend warns when its own
# build expects a newer backend (guards against running a stale server)
API_VERSION = 20


def _read_offsets() -> dict:
    return CFG.offsets()


# Mount offsets: a servo mounted e.g. +90 deg off has its CAD zero at
# tick(180+90). All user-facing angles stay relative to the CAD zero; the
# offset only shifts the servo-tick mapping.

def _to_ticks(rel_deg: float, offset: float = 0.0) -> int:
    return rel_deg_to_ticks(rel_deg + offset)


def _to_rel(ticks: float, offset: float = 0.0) -> float:
    return ticks_to_rel_deg(ticks) - offset


# reachable band in CAD degrees (seam-safe tick range), used to clamp limits
SEAM_MIN_DEG = round(ticks_to_rel_deg(POS_MIN_SAFE), 2)
SEAM_MAX_DEG = round(ticks_to_rel_deg(POS_MAX_SAFE), 2)


# ---------------------------------------------------------------- engine

ENGINE = MotionEngine(CFG)
S = ENGINE.S     # shared live state (SSE stream, bus-utility endpoints)


def _engine(fn):
    """Translate engine rejections into HTTP client errors."""
    try:
        return fn()
    except MotionError as e:
        raise HTTPException(400, str(e)) from e


app = FastAPI(title="Zeroth-01 servo test GUI")


@app.middleware("http")
async def no_cache_static(request, call_next):
    """The GUI files (index.html/app.js/style.css) must never be served from
    the browser cache — a stale frontend silently misses features. The big
    GLB stays cacheable."""
    resp = await call_next(request)
    if request.url.path != "/model":
        resp.headers["Cache-Control"] = "no-store"
    return resp


# ---------------------------------------------------------------- api

@app.get("/api/status")
def status():
    with S.lock:
        connected = S.bus is not None
        port = S.bus.port if S.bus else None
    return {"model_present": GLB_PATH.exists(), "connected": connected,
            "port": port, "live": S.snapshot(), "api_version": API_VERSION,
            "connection": CFG.connection(),
            "limits": {"min_deg": ticks_to_rel_deg(POS_MIN_SAFE),
                       "max_deg": ticks_to_rel_deg(POS_MAX_SAFE)}}


@app.get("/api/ports")
def ports():
    return serial_ports()


class ConnectParams(BaseModel):
    port: str | None = None


@app.post("/api/connect")
def connect(p: ConnectParams):
    port = p.port                     # explicit UI choice always wins
    if not port:
        configured = CFG.connection().get("port", "auto")
        if configured and configured != "auto":
            port = configured         # pinned in hardware/connection.json
        else:
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


class ConnectionParams(BaseModel):
    mode: str | None = Field(None, pattern="^(usb|wireless)$")
    pi_url: str | None = None
    port: str | None = None


@app.post("/api/connection")
def set_connection(p: ConnectionParams):
    """Persist connection settings (hardware/connection.json) — the GUI's
    mode switch. Only the provided fields are updated. Switching modes
    mid-run would swap the visible STOP away from the machine that is
    still moving, so it is refused like /api/disconnect."""
    with S.lock:
        if p.mode is not None and S.live["running"]:
            raise HTTPException(400, "Run in progress — stop it first.")
    stored = read_json(CFG.connection_path, {})
    for k in ("mode", "pi_url", "port"):
        v = getattr(p, k)
        if v is not None:
            stored[k] = v
    CFG.write_connection(stored)
    merged = CFG.connection()
    S.log(f"connection mode: {merged['mode']}"
          + (f" (Pi: {merged['pi_url']})" if merged["mode"] == "wireless"
             else ""))
    return {"ok": True, "connection": merged}


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
def scan(id_from: int = 1, id_to: int = 60):
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


@app.get("/api/present")
def present():
    """Ping every configured servo ID (servo_ids.json) and report which ones
    respond — the group list grays out the servos not on the bus."""
    with S.lock:
        bus = S.bus
        if S.live["running"]:
            raise HTTPException(400, "Bus busy — a run is in progress.")
    if not bus:
        raise HTTPException(400, "Not connected.")
    ids = sorted(set(_read_servo_ids().values()))
    found = []
    for sid in ids:
        try:
            bus.ping(sid)
            found.append(sid)
        except ServoBusError:
            pass
    missing = [i for i in ids if i not in found]
    S.log(f"presence check: {len(found)}/{len(ids)} configured servos respond"
          + (f" — missing {missing}" if missing else ""))
    return {"present": found, "configured": ids}


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


@app.get("/api/servo_pos")
def servo_pos(servo_id: int, joint: str | None = None):
    """Live position of one servo (for the idle readout). Never raises — the
    frontend polls this a few times a second; soft failures just show '–'.
    During a run the SSE stream already carries the position, so we don't
    touch the bus (avoids extra concurrent traffic)."""
    with S.lock:
        bus = S.bus
        running = S.live["running"]
    if running:
        return {"ok": False, "running": True}
    if not bus:
        return {"ok": False, "reason": "disconnected"}
    try:
        off = float(_read_offsets().get(joint, 0.0)) if joint else 0.0
        ticks = bus.read_pos(servo_id)
    except Exception:      # closed port mid-read, partial config file, etc.
        return {"ok": False, "reason": "no_response"}
    return {"ok": True, "ticks": ticks, "deg": _to_rel(ticks, off),
            "offset": off}


@app.post("/api/test")
def start_test(p: TestParams):
    _engine(lambda: ENGINE.start_test(p))
    return {"ok": True}


@app.post("/api/center")
def move_center(p: CenterParams):
    _engine(lambda: ENGINE.start_center(p))
    return {"ok": True}



def _read_servo_ids() -> dict:
    return CFG.servo_ids()


@app.post("/api/group/center")
def group_center(p: GroupParams):
    plan = _engine(lambda: ENGINE.start_group(p, "center"))
    return {"ok": True, "plan": plan}


@app.post("/api/group/test")
def group_test(p: GroupParams):
    plan = _engine(lambda: ENGINE.start_group(p, "test"))
    return {"ok": True, "plan": plan}


@app.get("/api/servo_ids")
def servo_ids():
    return _read_servo_ids()


class ReleaseParams(BaseModel):
    joints: list[str] | None = None    # None/empty -> all configured servos


def _idle_bus_or_400():
    with S.lock:
        bus = S.bus
        if S.live["running"]:
            raise HTTPException(400, "Bus busy — a run is in progress.")
    if not bus:
        raise HTTPException(400, "Not connected.")
    return bus


@app.post("/api/release")
def release_torque(p: ReleaseParams):
    """Let go after a hold-center demo: disable torque on the given joints
    (or all configured ones)."""
    bus = _idle_bus_or_400()
    released = release_joints(bus, _read_servo_ids(), p.joints)
    S.log(f"torque released: IDs {released}" if released
          else "torque release: nothing to do")
    return {"ok": True, "released": released}


@app.post("/api/lock")
def lock_torque(p: ReleaseParams):
    """Teach-in: freeze the given joints (or all) at their current physical
    position — hand-pose a limb, lock it, pose the next one."""
    bus = _idle_bus_or_400()
    locked = lock_joints(bus, _read_servo_ids(), p.joints)
    S.log(f"torque locked at current position: IDs {locked}" if locked
          else "torque lock: nothing to do")
    return {"ok": True, "locked": locked}


# ------------------------------------------------------------ demos (teach-in)

def _demo_path(name: str) -> Path:
    try:
        return CFG.demo_path(name)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


def _load_demos() -> list[dict]:
    return CFG.load_demos(
        on_invalid=lambda n: S.log(f"WARNING: demo file {n} is invalid — skipped"))


@app.get("/api/demos")
def demos():
    return {"demos": _load_demos()}


@app.post("/api/demos")
def save_demo(d: Demo):
    for i, step in enumerate(d.steps, 1):
        for j, deg in step.angles.items():
            if not -180 <= deg <= 180:
                raise HTTPException(400, f"Step {i}: angle {deg} for {j} "
                                         "out of range.")
    _demo_path(d.name)                 # 400 on unusable name
    CFG.save_demo(d)
    S.log(f"demo saved: '{d.name}' ({len(d.steps)} steps) -> "
          f"demos/{_demo_path(d.name).name}")
    return {"ok": True, "demos": _load_demos()}


class DemoNameParams(BaseModel):
    name: str


@app.post("/api/demos/delete")
def delete_demo(p: DemoNameParams):
    path = _demo_path(p.name)
    if path.exists():
        path.unlink()
        S.log(f"demo deleted: '{p.name}'")
    return {"ok": True, "demos": _load_demos()}


_BATT = {"t": 0.0, "volts": None, "servo_id": None, "error": None}


@app.get("/api/battery")
def battery():
    """Pack voltage as the servos see their rail (register 62, 0.1 V steps):
    the first configured servo that answers. Cached for 2 s so the GUI's
    poll does not load the bus; during a run the read interleaves with the
    runner (the bus is locked per transaction)."""
    import time as _t
    now = _t.monotonic()
    if now - _BATT["t"] < 2.0:
        return {**_BATT, "age_s": round(now - _BATT["t"], 1)}
    with S.lock:
        bus = S.bus
    volts, sid, err = None, None, None
    if not bus:
        err = "not connected"
    else:
        ids = sorted(set(_read_servo_ids().values()))
        if not ids:
            err = "no servos configured"
        for cand in ids:
            try:
                v = bus.read_voltage(cand)
            except Exception as e:                 # bus error: report, keep going
                err = f"{type(e).__name__}: {e}"
                break
            if v is not None:
                volts, sid, err = v, cand, None
                break
        else:
            if ids and err is None:
                err = "no servo answers"
    _BATT.update(t=now, volts=volts, servo_id=sid, error=err)
    return {**_BATT, "age_s": 0.0}


@app.get("/api/robot_pose")
def robot_pose():
    """Current pose of the PHYSICAL robot (all responding configured servos)
    in CAD-frame degrees — physical teach-in: release torque, hand-pose the
    robot, capture."""
    with S.lock:
        bus = S.bus
        if S.live["running"]:
            raise HTTPException(400, "Bus busy — a run is in progress.")
    if not bus:
        raise HTTPException(400, "Not connected.")
    ids = _read_servo_ids()
    offs = _read_offsets()
    pose, missing = {}, []
    for j, sid in ids.items():
        try:
            pose[j] = round(_to_rel(bus.read_pos(sid),
                                    float(offs.get(j, 0.0))), 1)
        except ServoBusError:
            missing.append(j)
    if not pose:
        raise HTTPException(400, "No servo responds.")
    return {"pose": pose, "missing": missing}


class PlayParams(BaseModel):
    name: str
    simulate: bool = False
    until: int | None = Field(None, ge=1)     # play only steps 1..until (inclusive)


@app.post("/api/demo/play")
def demo_play(p: PlayParams):
    _demo_path(p.name)                 # 400 on unusable name
    try:
        demo = CFG.load_demo(p.name)
    except KeyError as e:
        raise HTTPException(404, f"Demo '{p.name}' not found.") from e
    if p.until is not None and p.until > len(demo.steps):
        raise HTTPException(400, f"Step {p.until} out of range (demo has {len(demo.steps)} steps).")
    _engine(lambda: ENGINE.play_demo(demo, p.simulate, until=p.until))
    return {"ok": True, "steps": p.until or len(demo.steps)}


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
    return CFG.limits()


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
    """Repo copy of the joint's safe range — canonical and git-tracked. In
    wireless mode the GUI additionally writes the robot's own copy (the one
    the Pi enforces), exactly like a taught-in demo."""
    try:
        r = CFG.save_limit(e.joint, e.min_deg, e.max_deg, e.symmetric)
    except ValueError as ex:
        raise HTTPException(400, str(ex)) from ex
    S.log(limit_log_line(e.joint, e.min_deg, e.max_deg,
                         r["mirrored"], r["skipped"]))
    return {"ok": True, **r}


@app.get("/api/offsets")
def get_offsets():
    return _read_offsets()


class OffsetEntry(BaseModel):
    joint: str
    offset_deg: float = Field(ge=-180, le=180)


def _write_offsets(offs: dict) -> None:
    CFG.write_offsets(offs)


@app.post("/api/offsets")
def set_offset(e: OffsetEntry):
    offs = _read_offsets()
    old = offs.get(e.joint)
    if e.offset_deg == 0.0:
        offs.pop(e.joint, None)
    else:
        offs[e.joint] = e.offset_deg
    _write_offsets(offs)
    S.log(f"mount offset: {e.joint} -> {e.offset_deg:+.1f} deg "
          f"(zero = tick {_to_ticks(0, e.offset_deg)})"
          + (f" (was {old:+.1f})" if old not in (None, e.offset_deg) else ""))
    return {"ok": True, "offsets": offs}


class ZeroParams(BaseModel):
    servo_id: int = Field(ge=1, le=253)
    joint: str


@app.post("/api/zero")
def zero_here(p: ZeroParams):
    """Capture the servo's CURRENT physical position as this joint's zero
    (CAD pose). Used after mounting: move to center, hand-correct the last
    couple of degrees, then re-zero here. The mount offset absorbs the shift
    so that the current position now reads 0 deg — offset = the position (in
    the un-offset frame) the servo sits at right now."""
    with S.lock:
        bus = S.bus
        if S.live["running"]:
            raise HTTPException(400, "Bus busy — a run is in progress.")
    if not bus:
        raise HTTPException(400, "Not connected.")
    try:
        ticks = bus.read_pos(p.servo_id)
    except ServoBusError as ex:
        raise HTTPException(400, str(ex)) from ex
    offs = _read_offsets()
    old = offs.get(p.joint)
    old_offset = float(old) if isinstance(old, (int, float)) else 0.0
    new_offset = round(ticks_to_rel_deg(ticks), 2)
    delta = round(new_offset - old_offset, 2)
    if abs(new_offset) < 0.05:
        offs.pop(p.joint, None)
        new_offset = 0.0
    else:
        offs[p.joint] = new_offset
    _write_offsets(offs)
    S.log(f"zeroed {p.joint} at current position (tick {ticks}) -> "
          f"offset {new_offset:+.2f} deg"
          + (f" (was {old_offset:+.2f}, shifted {delta:+.2f})" if delta else ""))

    # keep safety limits pinned to the SAME physical stops: when the zero moves
    # by +delta, a CAD-frame limit moves by -delta to stay physically put.
    lim_note = None
    if delta:
        lims = _read_limits()
        L = lims.get(p.joint)
        if L:
            lo = round(max(SEAM_MIN_DEG, min(SEAM_MAX_DEG,
                                             L["min_deg"] - delta)), 2)
            hi = round(max(SEAM_MIN_DEG, min(SEAM_MAX_DEG,
                                             L["max_deg"] - delta)), 2)
            if lo < hi:
                L.update(min_deg=lo, max_deg=hi,
                         updated=date.today().isoformat())
                CFG.write_limits(lims)
                lim_note = {"min_deg": lo, "max_deg": hi}
                S.log(f"limits for {p.joint} shifted to [{lo:+.1f}, {hi:+.1f}] "
                      "deg (same physical range after re-zero)")
            else:
                S.log(f"WARNING: re-zero would collapse {p.joint} limits — "
                      "left unchanged, please re-check them")

    # commanded moves to 0 clamp to the seam-safe band — warn if zeroed so near
    # the encoder seam that CAD 0 can't actually be commanded to this position
    if abs(ticks - _to_ticks(0.0, new_offset)) > TOLERANCE:
        S.log(f"WARNING: {p.joint} zeroed near the encoder seam — commanded "
              "moves to 0 deg will be limited by the seam-safe range")

    return {"ok": True, "offset": new_offset, "ticks": ticks, "offsets": offs,
            "limits_shifted": lim_note}


# Display-only per-joint corrections so the 3D model's zero pose matches the
# REAL robot's calibrated zero (the CAD scene pose has bent knees / a raised
# arm). Servo angles are unaffected — this only rotates the preview rig.

def _read_model_zero() -> dict:
    return CFG.model_zero()


@app.get("/api/model_zero")
def get_model_zero():
    return _read_model_zero()


class ModelZeroEntry(BaseModel):
    joint: str
    deg: float = Field(ge=-180, le=180)


@app.post("/api/model_zero")
def set_model_zero(e: ModelZeroEntry):
    mz = _read_model_zero()
    if abs(e.deg) < 0.05:
        mz.pop(e.joint, None)
    else:
        mz[e.joint] = round(e.deg, 1)
    CFG.write_model_zero(mz)
    S.log(f"model zero (display only): {e.joint} -> {e.deg:+.1f} deg")
    return {"ok": True, "offsets": mz}


def _read_model_invert() -> dict:
    return CFG.model_invert()


@app.get("/api/model_invert")
def get_model_invert():
    return _read_model_invert()


class ModelInvertEntry(BaseModel):
    joint: str
    invert: bool


@app.post("/api/model_invert")
def set_model_invert(e: ModelInvertEntry):
    """Display-only: flip the model rig's rotation direction for a joint whose
    real servo turns the other way (e.g. the knees). Servo commands, limits
    and demos are unaffected."""
    inv = _read_model_invert()
    if e.invert:
        inv[e.joint] = True
    else:
        inv.pop(e.joint, None)
    CFG.write_model_invert(inv)
    S.log(f"model direction (display only): {e.joint} -> "
          + ("inverted" if e.invert else "normal"))
    return {"ok": True, "invert": inv}


class ModelZeroBulk(BaseModel):
    offsets: dict[str, float]


@app.post("/api/model_zero_bulk")
def set_model_zero_bulk(e: ModelZeroBulk):
    """Calibrate ALL joints at once: pose the model to match the real robot's
    zero, then fold every joint's current pose angle into its correction."""
    mz = _read_model_zero()
    changed = 0
    for j, v in e.offsets.items():
        if not -180 <= v <= 180:
            raise HTTPException(400, f"Offset {v} for {j} out of range.")
        if abs(v) < 0.05:
            changed += 1 if mz.pop(j, None) is not None else 0
        elif mz.get(j) != round(v, 1):
            mz[j] = round(v, 1)
            changed += 1
    CFG.write_model_zero(mz)
    S.log(f"model zero calibrated from posed model ({changed} joints changed)")
    return {"ok": True, "offsets": mz}


# Center pose override: the pose every "center" action moves to (single
# servo, group, Pi, hold-center re-parks). Joint -> CAD deg; an empty dict
# restores the plain mount pose (all 0 deg). Deployed to the Pi with the
# other calibration files.

@app.get("/api/center_pose")
def get_center_pose():
    return CFG.center_pose()


class CenterPoseBody(BaseModel):
    angles: dict[str, float]


@app.post("/api/center_pose")
def set_center_pose(b: CenterPoseBody):
    ids = _read_servo_ids()
    cp = {}
    for j, v in b.angles.items():
        if j not in ids:
            raise HTTPException(400, f"Unknown joint '{j}' (no servo ID configured).")
        if not -180 <= v <= 180:
            raise HTTPException(400, f"Angle {v} for {j} out of range.")
        if abs(v) >= 0.5:            # below that it is idle-twin jitter, not a posed joint
            cp[j] = round(v, 1)
    CFG.write_center_pose(cp)
    if cp:
        S.log("center pose override saved: "
              + ", ".join(f"{j} {v:+.1f}" for j, v in sorted(cp.items()))
              + " deg (deploy to apply on the Pi)")
    else:
        S.log("center pose override cleared — center = mount pose (all 0 deg)")
    return {"ok": True, "angles": cp}


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
        CFG.write_servo_ids(ids)
        S.log(f"servo ID config: {e.joint} -> ID {e.servo_id}"
              + (f" (was {old})" if old not in (None, e.servo_id) else ""))
    return {"ok": True, "servo_ids": ids}


# ---------------------------------------------------------------- model file

@app.get("/model")
def model():
    if not GLB_PATH.exists():
        raise HTTPException(404, "GLB snapshot missing — see resources/cad/VERSION.md")
    return FileResponse(GLB_PATH, media_type="model/gltf-binary")


@app.get("/api/attachments")
def attachments():
    """Manifest of printed add-on parts (e.g. the backpack) rendered torso-fixed on the model.

    Optional: an empty list keeps the GUI exactly as before. The GLBs live in the same
    frame as the pinned model (assembly frame, Z-up, metres)."""
    mf = ATTACH_DIR / "manifest.json"
    if not mf.exists():
        return {"sets": [], "hide": []}
    return read_json(mf, {"sets": [], "hide": []})


@app.get("/attachments/{name}")
def attachment_file(name: str):
    if "/" in name or "\\" in name or not name.endswith(".glb"):
        raise HTTPException(400, "attachment name must be a plain .glb file name")
    path = ATTACH_DIR / name
    if not path.exists():
        raise HTTPException(404, f"attachment {name} missing — run hardware/backpack_v2/viewer/export_attachments.py")
    return FileResponse(path, media_type="model/gltf-binary")


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
