import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
"""Verify the workflow-driven fixes: re-zero limit-shift, truncation guard,
run-launch atomicity, servo_pos robustness. Uses a temp config dir; never
touches the repo."""
import json
import tempfile
import threading
from pathlib import Path

from fastapi.testclient import TestClient
import server
from zbot_core.config import ConfigStore
from zbot_core.bus import ticks_to_rel_deg

tmp = Path(tempfile.mkdtemp())
server.CFG = ConfigStore(tmp)
server.ENGINE.cfg = server.CFG

ok = True
def check(name, cond):
    global ok; ok = ok and cond
    print(("PASS" if cond else "FAIL"), name)


class FakeBus:
    simulated = False
    port = "FAKE"
    def __init__(self, ticks): self.t = ticks
    def read_pos(self, sid): return self.t
    def move(self, *a): pass
    def torque_off(self, sid): pass
    def ping(self, sid): return 3215

client = TestClient(server.app)

# --- re-zero shifts existing limits by -delta (preserve physical stops) ---
server.CFG.offsets_path.write_text(json.dumps({"left_hip_pitch": 90.0}))
server.CFG.limits_path.write_text(json.dumps({
    "left_hip_pitch": {"min_deg": -30.0, "max_deg": 0.0,
                       "set": "direct", "updated": "2026-07-20"}}))
server.S.bus = FakeBus(3072 + 23)   # +2.02 deg past the old center
r = client.post("/api/zero", json={"servo_id": 31, "joint": "left_hip_pitch"}).json()
delta = r["offset"] - 90.0
lim = json.loads(server.CFG.limits_path.read_text())["left_hip_pitch"]
check(f"re-zero delta ~+2.02 (got {delta:+.2f})", abs(delta - 2.02) < 0.05)
check(f"limits shifted by -delta: min {lim['min_deg']:+.2f} (want ~-32.02)",
      abs(lim["min_deg"] - (-30.0 - delta)) < 0.05)
check(f"limits shifted by -delta: max {lim['max_deg']:+.2f} (want ~-2.02)",
      abs(lim["max_deg"] - (0.0 - delta)) < 0.05)
# physical stop invariance: old max phys tick == new max phys tick
old_max_tick = server._to_ticks(0.0, 90.0)
new_max_tick = server._to_ticks(lim["max_deg"], r["offset"])
check(f"forward physical stop preserved (old {old_max_tick} == new {new_max_tick})",
      abs(old_max_tick - new_max_tick) <= 1)

# --- /api/limits: response shape the GUI relies on + left/right mirroring ---
server.CFG.limits_path.write_text(json.dumps({}))
r = client.post("/api/limits", json={"joint": "left_knee_pitch",
                                     "min_deg": -80.0, "max_deg": 20.0}).json()
check("limits response carries the full table",
      r["limits"]["left_knee_pitch"]["max_deg"] == 20.0)
check(f"mirrored to the other side (got {r['mirrored']})",
      r["mirrored"] == "right_knee_pitch"
      and r["limits"]["right_knee_pitch"]["set"] == "mirrored")
rr = client.post("/api/limits", json={"joint": "left_knee_pitch",
                                      "min_deg": 20.0, "max_deg": 20.0})
check(f"empty range rejected (status {rr.status_code})", rr.status_code == 400)

# --- truncation guard: interval fully outside reachable band -> 400 ---
server.CFG.offsets_path.write_text(json.dumps({"j": 170.0}))   # huge offset
server.CFG.limits_path.write_text(json.dumps({}))
server.S.bus = FakeBus(2048)
# request +100..+120 with offset 170 -> both clamp to the seam max -> lo_t==hi_t
rr = client.post("/api/test", json={"servo_id": 5, "min_deg": 100,
                 "max_deg": 120, "simulate": True, "joint": "j"})
check(f"unreachable interval rejected (status {rr.status_code})",
      rr.status_code == 400)

# --- run-launch is atomic: 8 concurrent sim launches -> exactly one wins ---
server.S.live["running"] = False
server.S.bus = None
results = []
def fire():
    results.append(client.post("/api/test", json={"servo_id": 1, "min_deg": -10,
                   "max_deg": 10, "simulate": True}).status_code)
ts = [threading.Thread(target=fire) for _ in range(8)]
[t.start() for t in ts]; [t.join() for t in ts]
wins = results.count(200)
check(f"exactly one concurrent launch wins (got {wins} of 8, rest 400)",
      wins == 1 and results.count(400) == 7)
client.post("/api/stop")
import time; time.sleep(0.5)

# --- servo_pos soft-fails on a bus that raises a non-ServoBusError ---
class BrokenBus(FakeBus):
    def read_pos(self, sid): raise RuntimeError("port closed")
server.S.live["running"] = False
server.S.bus = BrokenBus(0)
d = client.get("/api/servo_pos", params={"servo_id": 1, "joint": "j"}).json()
check(f"servo_pos soft-fails on unexpected bus error (ok={d.get('ok')})",
      d["ok"] is False and d.get("reason") == "no_response")

print("\nALL PASS" if ok else "\nSOME FAILED")
