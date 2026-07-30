import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
"""Verify the mount-offset + zero-here math through the real endpoints,
with a fake bus and a temp offsets file (never touches the repo config)."""
import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

import server
from servo_bus import ticks_to_rel_deg

# redirect the offsets file to a temp path
tmp = Path(tempfile.mkdtemp()) / "joint_offsets.json"
server.OFFSETS_PATH = tmp


class FakeBus:
    simulated = False
    port = "FAKE"

    def __init__(self, ticks):
        self._ticks = ticks

    def read_pos(self, sid):
        return self._ticks


client = TestClient(server.app)
ok = True


def check(name, cond):
    global ok
    ok = ok and cond
    print(("PASS" if cond else "FAIL"), name)


# --- pure math round-trips ---
for t in (2048, 3072, 3095, 40, 4055):
    off = round(ticks_to_rel_deg(t), 6)
    rel = server._to_rel(t, off)
    check(f"zero round-trip tick {t}: _to_rel == 0 (got {rel:+.4f})",
          abs(rel) < 0.1)

# --- realistic hip scenario: offset 90, hand-turned +2 deg (23 ticks) ---
server.S.bus = FakeBus(3072 + 23)          # 3095
# before re-zero, with saved offset 90, live readout should show ~+2 deg
tmp.write_text(json.dumps({"left_hip_pitch": 90.0}))
r = client.get("/api/servo_pos", params={"servo_id": 31,
                                         "joint": "left_hip_pitch"})
d = r.json()
check(f"live readout with offset 90 shows ~+2 deg (got {d.get('deg'):+.2f})",
      d["ok"] and abs(d["deg"] - 2.02) < 0.2)

# --- zero here: capture current position as new zero ---
r = client.post("/api/zero", json={"servo_id": 31, "joint": "left_hip_pitch"})
z = r.json()
check(f"zero returns offset ~+92.02 (got {z.get('offset'):+.2f})",
      z["ok"] and abs(z["offset"] - 92.02) < 0.1)
check("offsets file updated with new offset",
      abs(json.loads(tmp.read_text())["left_hip_pitch"] - 92.02) < 0.1)

# after re-zero, the same physical position must read ~0 deg
r = client.get("/api/servo_pos", params={"servo_id": 31,
                                         "joint": "left_hip_pitch"})
d = r.json()
check(f"after zero, same position reads ~0 deg (got {d.get('deg'):+.3f})",
      abs(d["deg"]) < 0.1)

# --- zero at exact center clears the offset ---
server.S.bus = FakeBus(2048)
r = client.post("/api/zero", json={"servo_id": 31, "joint": "left_hip_pitch"})
z = r.json()
check(f"zero at tick 2048 clears offset to 0 (got {z.get('offset')})",
      z["offset"] == 0.0 and "left_hip_pitch" not in json.loads(tmp.read_text()))

# --- zero refused during a run ---
server.S.live["running"] = True
r = client.post("/api/zero", json={"servo_id": 31, "joint": "left_hip_pitch"})
check(f"zero refused during run (status {r.status_code})", r.status_code == 400)
server.S.live["running"] = False

print("\nALL PASS" if ok else "\nSOME FAILED")
