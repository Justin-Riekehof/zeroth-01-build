import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
"""USB-mode teleop endpoints + static delivery of the vendored MediaPipe files."""
import json, tempfile, time
from pathlib import Path
from fastapi.testclient import TestClient
import server
from zbot_core.config import ConfigStore

tmp = Path(tempfile.mkdtemp())
server.CFG = ConfigStore(tmp)
server.ENGINE.cfg = server.CFG
server.CFG.servo_ids_path.write_text(json.dumps({"left_shoulder_yaw": 12}))
server.CFG.limits_path.write_text(json.dumps({"left_shoulder_yaw": {
    "min_deg": -50.0, "max_deg": 20.0, "set": "direct", "updated": "x"}}))

ok = True
def check(name, cond):
    global ok; ok = ok and cond
    print(("PASS" if cond else "FAIL"), name)

client = TestClient(server.app)
lm = [[0.0, 0.0, 0.0, 0.0] for _ in range(33)]
lm[11] = [0.2, -0.5, 0, 1]; lm[12] = [-0.2, -0.5, 0, 1]
lm[23] = [0.1, 0, 0, 1]; lm[24] = [-0.1, 0, 0, 1]
lm[13] = [0.5, -0.5, 0, 1]; lm[15] = [0.5, -0.25, 0, 1]      # left arm straight out sideways

r = client.post("/api/teleop/pose", json={"landmarks": lm})
check("pose preview works without a run", r.status_code == 200 and r.json()["active"] is False)
check("preview clamped to the limit (20)", r.json()["angles"]["left_shoulder_yaw"] == 20.0)
check("target without teleop rejected", client.post("/api/teleop/target", json={"angles": {"left_shoulder_yaw": 1}}).status_code == 400)

r = client.post("/api/teleop/start", json={"joints": ["left_shoulder_yaw"], "simulate": True})
check("start (simulation)", r.status_code == 200 and r.json()["joints"] == ["left_shoulder_yaw"])
time.sleep(0.2)
for _ in range(10):
    j = client.post("/api/teleop/pose", json={"landmarks": lm}).json(); time.sleep(0.05)
check("pose is now active", j["active"] is True)
check("rig follows, clamped", server.S.snapshot()["multi"]["left_shoulder_yaw"] <= 20.0)
check("second start rejected while running", client.post("/api/teleop/start", json={}).status_code == 400)
client.post("/api/teleop/stop"); time.sleep(0.4)
check("stopped, slot free", server.S.snapshot()["running"] is False)

for f in ("vendor/mediapipe/vision_bundle.mjs", "vendor/mediapipe/wasm/vision_wasm_internal.wasm",
          "vendor/mediapipe/pose_landmarker_full.task"):
    r = client.get("/" + f)
    check(f"serves {f}", r.status_code == 200 and len(r.content) > 1000)
check("wasm mime", client.get("/vendor/mediapipe/wasm/vision_wasm_internal.wasm").headers["content-type"] == "application/wasm")
check("vendor files cacheable", "no-store" not in client.get("/vendor/mediapipe/vision_bundle.mjs").headers.get("cache-control", ""))
check("app files not cached", client.get("/mocap.js").headers.get("cache-control") == "no-store")
sys.exit(0 if ok else 1)
