import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
"""Verify the teach-in demo system end-to-end: save/list/delete, playback
order, per-step speed, limit clamping, offset math, final hold, abort.
Temp configs + temp demos dir; recording bus."""
import json, tempfile, time
from pathlib import Path
from fastapi.testclient import TestClient
import server
from zbot_core.config import ConfigStore

tmp = Path(tempfile.mkdtemp())
server.CFG = ConfigStore(tmp)
server.ENGINE.cfg = server.CFG
server.CFG.servo_ids_path.write_text(json.dumps({"a": 11, "b": 12}))
server.CFG.limits_path.write_text(json.dumps({
    "a": {"min_deg": -50.0, "max_deg": 50.0, "set": "direct", "updated": "x"},
    "b": {"min_deg": -90.0, "max_deg": 90.0, "set": "direct", "updated": "x"}}))
server.CFG.offsets_path.write_text(json.dumps({"a": 90.0}))

ok = True
def check(name, cond):
    global ok; ok = ok and cond
    print(("PASS" if cond else "FAIL"), name)


class RecBus:
    simulated = False
    port = "FAKE"
    def __init__(self):
        self.pos = {}; self.moves = []; self.offs = []; self.ons = []
        self.torque = {}
    def ping(self, sid): return 3215
    def read_pos(self, sid): return self.pos.get(sid, 2048)
    def move(self, sid, ticks, speed, acc):
        self.pos[sid] = ticks; self.moves.append((sid, ticks, speed, acc))
    def torque_off(self, sid): self.offs.append(sid); self.torque[sid] = 0
    def torque_on(self, sid):
        self.ons.append(sid); self.torque[sid] = 1; return True
    def read_torque(self, sid): return self.torque.get(sid, 1)


client = TestClient(server.app)

# --- 1) save + list ---
demo = {"name": "test_demo", "steps": [
    {"angles": {"a": 30.0, "b": -45.0}, "speed": 800, "acc": 60, "pause_s": 0},
    {"angles": {"a": 80.0, "ghost_joint": 10.0}, "speed": 300, "acc": 20,
     "pause_s": 0.2},
    {"angles": {"a": 0.0, "b": 0.0}, "speed": 500, "acc": 50, "pause_s": 0}]}
r = client.post("/api/demos", json=demo)
check(f"save demo ({r.status_code})", r.status_code == 200)
lst = client.get("/api/demos").json()["demos"]
check("demo listed", len(lst) == 1 and lst[0]["name"] == "test_demo"
      and len(lst[0]["steps"]) == 3)

# --- 2) play on recording bus ---
bus = RecBus()
server.S.bus = bus
server.S.live["running"] = False
r = client.post("/api/demo/play", json={"name": "test_demo"})
check(f"play accepted ({r.status_code})", r.status_code == 200)
for _ in range(200):
    if not server.S.live["running"]: break
    time.sleep(0.05)
check("phase done", server.S.live["phase"] == "done")

# step 1: a=+30 with offset 90 -> ticks(120+180 deg)=3413; b=-45 -> 1536
mv = bus.moves
check(f"step1 a: tick 3413 @speed 800 (got {mv[0] if mv else None})",
      (11, 3413, 800, 60) in mv[:2])
check(f"step1 b: tick 1536 @speed 800", (12, 1536, 800, 60) in mv[:2])
# step 2: a=80 clamped to limit 50 -> ticks(50+90+180=320 deg)... seam-clamped
exp_a2 = server._to_ticks(50.0, 90.0)
check(f"step2 a clamped to +50 -> tick {exp_a2}",
      any(m[0] == 11 and m[1] == exp_a2 and m[2] == 300 for m in mv))
log = " | ".join(e["msg"] for e in server.S.live["log"])
check("clamp logged", "clamped to joint limits" in log)
check("ghost joint noted", "unknown joints skipped" in log)
# step 3 end: both back to their centers (a: 3072, b: 2048)
last = {}
for sid, t, *_ in mv: last[sid] = t
check(f"final pose: a at 3072 / b at 2048 (got {last.get(11)}/{last.get(12)})",
      last.get(11) == 3072 and last.get(12) == 2048)
# final hold: torque_on both, no torque_off
check(f"final hold: torque_on {sorted(set(bus.ons))}, offs {bus.offs}",
      sorted(set(bus.ons)) == [11, 12] and bus.offs == [])
check("log says holding final pose", "holding final pose" in log)

# --- 3) abort mid-demo -> E-stop ---
class SlowBus(RecBus):
    def read_pos(self, sid): return 0
bus = SlowBus()
server.S.bus = bus
server.S.live["running"] = False
client.post("/api/demo/play", json={"name": "test_demo"})
time.sleep(0.3)
client.post("/api/stop")
for _ in range(100):
    if not server.S.live["running"]: break
    time.sleep(0.05)
check(f"abort -> all torque off (got {sorted(set(bus.offs))})",
      sorted(set(bus.offs)) == [11, 12])

# --- 4) delete ---
r = client.post("/api/demos/delete", json={"name": "test_demo"}).json()
check("deleted", r["demos"] == [])

# --- 5) invalid demos rejected ---
bad = client.post("/api/demos", json={"name": "x", "steps": []})
check(f"empty steps rejected ({bad.status_code})", bad.status_code == 422)
bad = client.post("/api/demos", json={"name": "x",
    "steps": [{"angles": {"a": 999}, "speed": 500, "acc": 50, "pause_s": 0}]})
check(f"angle 999 rejected ({bad.status_code})", bad.status_code == 400)
bad = client.post("/api/demos", json={"name": "../evil",
    "steps": [{"angles": {"a": 0}, "speed": 500, "acc": 50, "pause_s": 0}]})
check(f"path-traversal name rejected ({bad.status_code})",
      bad.status_code == 422)

print("\nALL PASS" if ok else "\nSOME FAILED")
