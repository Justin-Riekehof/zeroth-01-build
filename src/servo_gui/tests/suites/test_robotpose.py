import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
"""Verify /api/robot_pose: offset-aware capture, missing servos reported."""
import json, tempfile
from pathlib import Path
from fastapi.testclient import TestClient
import server

tmp = Path(tempfile.mkdtemp())
server.SERVO_IDS_PATH = tmp / "servo_ids.json"
server.OFFSETS_PATH = tmp / "joint_offsets.json"
server.SERVO_IDS_PATH.write_text(json.dumps({"a": 11, "b": 12, "c": 13}))
server.OFFSETS_PATH.write_text(json.dumps({"a": 90.0}))


class Bus:
    simulated = False
    port = "FAKE"
    # a at 3300 (with offset 90 -> +20.0 deg), b at 1820 (-20.0), c dead
    def read_pos(self, sid):
        if sid == 13:
            raise server.ServoBusError("dead")
        return {11: 3300, 12: 1820}[sid]


server.S.bus = Bus()
server.S.live["running"] = False
r = TestClient(server.app).get("/api/robot_pose").json()
ok = (abs(r["pose"]["a"] - 20.0) < 0.1 and abs(r["pose"]["b"] + 20.0) < 0.1
      and r["missing"] == ["c"] and "c" not in r["pose"])
print("pose:", r["pose"], "| missing:", r["missing"], "=>",
      "PASS" if ok else "FAIL")
