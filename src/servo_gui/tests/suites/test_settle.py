import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
"""Verify the load-sag settle pass: a bus with constant steady-state error
(40 ticks short of every goal) must end each demo step ON target; sweeps
(settle off) keep the raw behavior. Temp configs."""
import json, tempfile, time
from pathlib import Path
from fastapi.testclient import TestClient
import server

tmp = Path(tempfile.mkdtemp())
server.SERVO_IDS_PATH = tmp / "servo_ids.json"
server.LIMITS_PATH = tmp / "joint_limits.json"
server.OFFSETS_PATH = tmp / "joint_offsets.json"
server.DEMOS_DIR = tmp / "demos"
server.SERVO_IDS_PATH.write_text(json.dumps({"a": 11, "b": 12}))
server.LIMITS_PATH.write_text(json.dumps({
    "a": {"min_deg": -90.0, "max_deg": 90.0, "set": "direct", "updated": "x"},
    "b": {"min_deg": -90.0, "max_deg": 90.0, "set": "direct", "updated": "x"}}))
server.OFFSETS_PATH.write_text(json.dumps({}))

ok = True
def check(n, c):
    global ok; ok = ok and c
    print(("PASS" if c else "FAIL"), n)


class SagBus:
    """Position controller parks SAG ticks short of the goal (gravity load)."""
    SAG = 40
    simulated = False
    port = "FAKE"
    def __init__(self):
        self.goal = {}; self.ons = []; self.offs = []
    def ping(self, sid): return 2825
    def read_pos(self, sid):
        g = self.goal.get(sid, 2048)
        return g - self.SAG if sid in self.goal else 2048
    def move(self, sid, ticks, speed, acc): self.goal[sid] = ticks
    def torque_off(self, sid): self.offs.append(sid)
    def torque_on(self, sid): self.ons.append(sid); return True
    def read_torque(self, sid): return 1


client = TestClient(server.app)
demo = {"name": "sag_demo", "steps": [
    {"angles": {"a": 45.0, "b": -30.0}, "speed": 2000, "acc": 50, "pause_s": 0},
    {"angles": {"a": 0.0, "b": 0.0}, "speed": 2000, "acc": 50, "pause_s": 0}]}
client.post("/api/demos", json=demo)

bus = SagBus()
server.S.bus = bus
server.S.live["running"] = False
r = client.post("/api/demo/play", json={"name": "sag_demo"})
assert r.status_code == 200, r.text
for _ in range(400):
    if not server.S.live["running"]: break
    time.sleep(0.05)

# final step target: center ticks 2048; with settle the ACTUAL pos must be ~2048
final_a, final_b = bus.read_pos(11), bus.read_pos(12)
check(f"settle: actual final pos a={final_a} (target 2048, sag 40)",
      abs(final_a - 2048) <= server.TOLERANCE)
check(f"settle: actual final pos b={final_b}", abs(final_b - 2048) <= server.TOLERANCE)
log = " | ".join(e["msg"] for e in server.S.live["log"])
check("compensation logged", "load sag compensated" in log)
check("no residual warning", "residual pose error" not in log)
check("phase done + holding", server.S.live["phase"] == "done"
      and 11 not in bus.offs and 12 not in bus.offs)

# sweeps keep raw behavior (settle off): final pos stays SAG short
bus2 = SagBus()
server.S.bus = bus2
server.S.live["running"] = False
client.post("/api/group/test", json={"joints": ["a"], "mode": "sequential",
    "speed": 3000, "hold_center": False, "cycles": 1})
for _ in range(400):
    if not server.S.live["running"]: break
    time.sleep(0.05)
check(f"sweep unchanged: pos stays {bus2.SAG} short (got {bus2.goal[11] - bus2.read_pos(11)})",
      bus2.goal[11] - bus2.read_pos(11) == bus2.SAG)

print("\nALL PASS" if ok else "\nSOME FAILED")
