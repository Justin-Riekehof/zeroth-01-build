import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
"""Verify /api/model_zero roundtrip and that the shipped demos validate."""
import json, tempfile
from pathlib import Path
from fastapi.testclient import TestClient
import server
from zbot_core.config import ConfigStore

tmp = Path(tempfile.mkdtemp())
server.CFG = ConfigStore(tmp)
client = TestClient(server.app)
ok = True
def check(n, c):
    global ok; ok = ok and c
    print(("PASS" if c else "FAIL"), n)

r = client.post("/api/model_zero", json={"joint": "left_knee_pitch",
                                         "deg": -9.3}).json()
check("set model zero", r["offsets"] == {"left_knee_pitch": -9.3})
check("persisted", json.loads(server.CFG.model_zero_path.read_text())
      == {"left_knee_pitch": -9.3})
r = client.post("/api/model_zero", json={"joint": "left_knee_pitch",
                                         "deg": 0}).json()
check("zero removes entry", r["offsets"] == {})
check("GET works", client.get("/api/model_zero").json() == {})

# real repo demos must validate against the Demo model (real DEMOS_DIR)
server.CFG.demos_dir = Path(__file__).resolve().parents[4] / "demos"
names = [d["name"] for d in server._load_demos()]
check(f"repo demos valid & listed: {names}", "careful_walk" in names)

print("\nALL PASS" if ok else "\nSOME FAILED")
