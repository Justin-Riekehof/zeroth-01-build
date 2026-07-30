import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
"""Verify hold-center demo mode: per-joint return to center, selective torque
hold, release endpoint, and E-stop semantics. Temp configs; recording bus."""
import json, tempfile, time, threading
from pathlib import Path
from fastapi.testclient import TestClient
import server
from zbot_core.config import ConfigStore

tmp = Path(tempfile.mkdtemp())
server.CFG = ConfigStore(tmp)
server.ENGINE.cfg = server.CFG
server.CFG.servo_ids_path.write_text(json.dumps({"a": 11, "b": 12}))
server.CFG.limits_path.write_text(json.dumps({
    "a": {"min_deg": -20.0, "max_deg": 20.0, "set": "direct", "updated": "x"},
    "b": {"min_deg": -20.0, "max_deg": 20.0, "set": "direct", "updated": "x"}}))
server.CFG.offsets_path.write_text(json.dumps({"a": 90.0}))   # a's center = tick 3072

ok = True
def check(name, cond):
    global ok; ok = ok and cond
    print(("PASS" if cond else "FAIL"), name)


class RecBus:
    """Instant-reach bus that records every command."""
    simulated = False
    port = "FAKE"
    def __init__(self):
        self.pos = {}; self.moves = []; self.offs = []; self.ons = []
    def ping(self, sid): return 3215
    def read_pos(self, sid): return self.pos.get(sid, 2048)
    def move(self, sid, ticks, speed, acc):
        self.pos[sid] = ticks; self.moves.append((sid, ticks))
    def torque_off(self, sid): self.offs.append(sid)
    def torque_on(self, sid):
        self.ons.append(sid); return True
    def read_torque(self, sid): return 1


client = TestClient(server.app)

def run_group(payload):
    bus = RecBus()
    server.S.bus = bus
    server.S.live["running"] = False
    r = client.post("/api/group/test", json=payload)
    assert r.status_code == 200, r.text
    for _ in range(200):
        if not server.S.live["running"]: break
        time.sleep(0.05)
    return bus

# --- 1) sequential + hold: each joint ends at ITS center, no torque_off ---
bus = run_group({"joints": ["a", "b"], "mode": "sequential", "speed": 3000,
                 "hold_center": True})
last = {}
for sid, t in bus.moves: last[sid] = t
check(f"a (offset +90) parked at tick 3072 (got {last.get(11)})", last.get(11) == 3072)
check(f"b parked at tick 2048 (got {last.get(12)})", last.get(12) == 2048)
check(f"no torque_off on held servos (got {bus.offs})", bus.offs == [])
check("phase done", server.S.live["phase"] == "done")
# order: a must be back at center BEFORE b's first move (stability while testing b)
a_center_idx = max(i for i, (s, t) in enumerate(bus.moves) if s == 11)
b_first_idx = min(i for i, (s, t) in enumerate(bus.moves) if s == 12)
check("a holds center before b starts", a_center_idx < b_first_idx)
check(f"explicit torque_on for held servos (got {sorted(set(bus.ons))})",
      sorted(set(bus.ons)) == [11, 12])

# --- 2) release endpoint lets go ---
r = client.post("/api/release", json={"joints": None}).json()
check(f"release all -> IDs {r['released']}", sorted(r["released"]) == [11, 12])

# --- 3) sequential without hold: old behavior (torque_off per joint, ends at min) ---
bus = run_group({"joints": ["a", "b"], "mode": "sequential", "speed": 3000,
                 "hold_center": False})
last = {}
for sid, t in bus.moves: last[sid] = t
check(f"no-hold: ends at lower limit, not center (a: {last.get(11)})",
      last.get(11) != 3072)
check(f"no-hold: torque_off for both (got {sorted(set(bus.offs))})",
      sorted(set(bus.offs)) == [11, 12])

# --- 4) simultaneous + hold: both parked at their centers, torque on ---
bus = run_group({"joints": ["a", "b"], "mode": "simultaneous", "speed": 3000,
                 "hold_center": True})
last = {}
for sid, t in bus.moves: last[sid] = t
check(f"simultaneous hold: a at 3072 / b at 2048 (got {last.get(11)}/{last.get(12)})",
      last.get(11) == 3072 and last.get(12) == 2048)
check(f"simultaneous hold: no torque_off (got {bus.offs})", bus.offs == [])
check(f"simultaneous: torque_on both (got {sorted(set(bus.ons))})",
      sorted(set(bus.ons)) == [11, 12])

# --- 5) E-stop: abort during hold run still torque-offs EVERYTHING ---
class SlowBus(RecBus):
    def read_pos(self, sid):            # never reaches -> run loops until abort
        return 0
bus = SlowBus()
server.S.bus = bus
server.S.live["running"] = False
client.post("/api/group/test", json={"joints": ["a", "b"], "mode": "sequential",
                                     "speed": 10, "hold_center": True})
time.sleep(0.3)
client.post("/api/stop")
for _ in range(100):
    if not server.S.live["running"]: break
    time.sleep(0.05)
check(f"abort -> all torque off despite hold (got {sorted(set(bus.offs))})",
      sorted(set(bus.offs)) == [11, 12])
check("phase aborted", server.S.live["phase"] == "aborted")

print("\nALL PASS" if ok else "\nSOME FAILED")
