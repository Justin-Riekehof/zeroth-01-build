import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
"""Verify: hold watchdog re-parks a servo that lost torque; single-servo
center hold; regressions of the hold suite. Temp configs only."""
import json, tempfile, time
from pathlib import Path
from fastapi.testclient import TestClient
import server
from zbot_core.config import ConfigStore

tmp = Path(tempfile.mkdtemp())
server.CFG = ConfigStore(tmp)
server.CFG.servo_ids_path.write_text(json.dumps({"a": 11, "b": 12}))
server.CFG.limits_path.write_text(json.dumps({
    "a": {"min_deg": -20.0, "max_deg": 20.0, "set": "direct", "updated": "x"},
    "b": {"min_deg": -20.0, "max_deg": 20.0, "set": "direct", "updated": "x"}}))
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
        self.torque = {}          # sid -> reported TORQUE_ENABLE
        self.dropped = False
    def ping(self, sid): return 3215
    def read_pos(self, sid): return self.pos.get(sid, 2048)
    def move(self, sid, ticks, speed, acc):
        self.pos[sid] = ticks; self.moves.append((sid, ticks))
    def torque_off(self, sid): self.offs.append(sid); self.torque[sid] = 0
    def torque_on(self, sid):
        self.ons.append(sid); self.torque[sid] = 1; return True
    def read_torque(self, sid): return self.torque.get(sid, 1)


class BrownoutBus(RecBus):
    """Servo 11 'browns out' (torque drops) right after being parked once."""
    def read_torque(self, sid):
        if sid == 11 and not self.dropped and 11 in self.torque:
            self.dropped = True
            self.torque[11] = 0
        return self.torque.get(sid, 1)


client = TestClient(server.app)

def wait_done():
    for _ in range(200):
        if not server.S.live["running"]: return
        time.sleep(0.05)

# --- 1) watchdog: A browns out while B tests -> re-parked + torque back on ---
bus = BrownoutBus()
server.S.bus = bus; server.S.live["running"] = False
r = client.post("/api/group/test", json={"joints": ["a", "b"],
    "mode": "sequential", "speed": 3000, "hold_center": True})
assert r.status_code == 200, r.text
wait_done()
a_parks = [i for i, (s, t) in enumerate(bus.moves) if s == 11 and t == 3072]
check(f"A parked at center TWICE (initial + watchdog re-park): {len(a_parks)}x",
      len(a_parks) >= 2)
check(f"A torque re-enabled (torque_on calls for 11: "
      f"{bus.ons.count(11)})", bus.ons.count(11) >= 2)
check("A ends holding (torque=1, no final torque_off)",
      bus.torque.get(11) == 1 and 11 not in bus.offs)
log = " | ".join(e["msg"] for e in server.S.live["log"])
check("watchdog warning logged", "LOST torque" in log)

# --- 2) single-servo center with hold: keeps torque ---
bus = RecBus()
server.S.bus = bus; server.S.live["running"] = False
client.post("/api/center", json={"servo_id": 11, "joint": "a", "speed": 3000,
                                 "hold_center": True})
wait_done()
check(f"single center+hold: parked at 3072 (got {bus.pos.get(11)})",
      bus.pos.get(11) == 3072)
check(f"single center+hold: torque_on, no torque_off (ons={bus.ons}, offs={bus.offs})",
      11 in bus.ons and 11 not in bus.offs)

# --- 3) single center WITHOUT hold: old behavior (torque released) ---
bus = RecBus()
server.S.bus = bus; server.S.live["running"] = False
client.post("/api/center", json={"servo_id": 11, "joint": "a", "speed": 3000,
                                 "hold_center": False})
wait_done()
check(f"single center no-hold: torque_off fired (offs={bus.offs})",
      11 in bus.offs)

# --- 4) single TEST still releases torque (unchanged) ---
bus = RecBus()
server.S.bus = bus; server.S.live["running"] = False
client.post("/api/test", json={"servo_id": 11, "joint": "a", "min_deg": -10,
                               "max_deg": 10, "speed": 3000})
wait_done()
check(f"single test: torque released as before (offs={bus.offs})",
      11 in bus.offs)

print("\nALL PASS" if ok else "\nSOME FAILED")
