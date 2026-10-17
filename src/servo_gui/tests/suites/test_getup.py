import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
"""Get-up assignment (hardware/getup.json) through the GUI backend: save and
read back, problems against the repo's demos, play one case in simulation
(segments concatenated into one run, origin step numbers in the log)."""
import json, tempfile, time
from pathlib import Path
from fastapi.testclient import TestClient
import server
from zbot_core.config import ConfigStore

tmp = Path(tempfile.mkdtemp())
server.CFG = ConfigStore(tmp)
server.CFG.write_motion_limits({"max_speed": 3400, "max_acc": 254})
server.ENGINE.cfg = server.CFG
server.CFG.servo_ids_path.write_text(json.dumps({"a": 11, "b": 12}))
server.CFG.limits_path.write_text(json.dumps({
    "a": {"min_deg": -90.0, "max_deg": 90.0, "set": "direct", "updated": "x"},
    "b": {"min_deg": -90.0, "max_deg": 90.0, "set": "direct", "updated": "x"}}))

ok = True
def check(name, cond):
    global ok; ok = ok and cond
    print(("PASS" if cond else "FAIL"), name)

client = TestClient(server.app)

# --- empty default
r = client.get("/api/getup").json()
check("empty default", r["config"]["front"] == "" and r["config"]["auto"] is False)

# --- assign + problems
client.post("/api/demos", json={"name": "getup_front", "steps": [
    {"angles": {"a": 20.0}, "speed": 3400, "acc": 254, "title": "push"},
    {"angles": {"a": 0.0, "b": 0.0}, "speed": 3400, "acc": 254, "title": "stand"}]})
r = client.post("/api/getup", json={"front": "getup_front", "back": "missing", "hold_s": 15})
check(f"save ({r.status_code})", r.status_code == 200)
check("problems reported", r.json()["problems"] == ["back: demo 'missing' not found"])
check("file written", json.loads(server.CFG.getup_path.read_text())["front"] == "getup_front")
r = client.post("/api/getup", json={"front": [{"demo": "push_ups", "start": 1, "until": 2}]})
check(f"old step-range format rejected ({r.status_code})", r.status_code == 422)

# --- play
r = client.post("/api/getup/play", json={"case": "back", "simulate": True})
check(f"missing demo rejected ({r.status_code})", r.status_code == 400
      and "not found" in r.json()["detail"])
r = client.post("/api/getup/play", json={"case": "front", "simulate": True})
check(f"play front ({r.status_code})", r.status_code == 200 and r.json()["steps"] == 2)
deadline = time.monotonic() + 10
while server.S.live["running"] and time.monotonic() < deadline:
    time.sleep(0.05)
log = "\n".join(e["msg"] for e in server.S.live["log"])
check("ran to the end", server.S.live["phase"] == "done")
check("log names the demo", "get-up 'front' (face down): getup_front" in log)
check("plain demo steps", "demo 'getup_front' step 2/2 (stand)" in log)

print("ALL OK" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
