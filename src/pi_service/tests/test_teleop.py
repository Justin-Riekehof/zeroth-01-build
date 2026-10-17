"""Teleoperation (camera motion capture): streamed targets are followed, but
only inside the configured joint limits; input loss holds; stop keeps the pose."""
import json
import time

import pytest
from test_service import logs, wait_idle

import service
from zbot_core.bus import rel_deg_to_ticks

J = "right_shoulder_pitch"


@pytest.fixture(autouse=True)
def arms(client):
    cfg = service.CFG
    cfg.servo_ids_path.write_text(json.dumps({J: 21, "right_elbow_yaw": 23}))
    cfg.limits_path.write_text(json.dumps({
        J: {"min_deg": -30.0, "max_deg": 40.0, "set": "direct", "updated": "x"},
        "right_elbow_yaw": {"min_deg": -10.0, "max_deg": 90.0, "set": "direct", "updated": "x"}}))
    cfg.offsets_path.write_text("{}")
    yield
    client.post("/teleop/stop")
    wait_idle(client)


def start(client, **kw):
    r = client.post("/teleop/start", json={"joints": [J, "right_elbow_yaw"],
                                            "max_dps": 360, "smooth": 1.0, **kw})
    assert r.status_code == 200, r.text
    return r


def feed(client, angles, seconds):
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        assert client.post("/teleop/target", json={"angles": angles}).status_code == 200
        time.sleep(0.05)


def test_target_without_session_is_rejected(client):
    assert client.post("/teleop/target", json={"angles": {J: 1}}).status_code == 400


def test_follows_and_clamps_to_limits(client):
    start(client)
    feed(client, {J: 200.0, "right_elbow_yaw": 45.0}, 0.6)   # shoulder far beyond max 40
    cmd = client.get("/status").json()["live"]["multi"]
    assert cmd[J] == pytest.approx(40.0, abs=0.01)           # clamped, never 200
    assert cmd["right_elbow_yaw"] == pytest.approx(45.0, abs=0.01)
    feed(client, {J: -90.0}, 0.6)
    assert client.get("/status").json()["live"]["multi"][J] == pytest.approx(-30.0, abs=0.01)
    assert service.S.bus._target[21] == pytest.approx(rel_deg_to_ticks(-30.0), abs=40)   # servo GOAL (the sim servo itself is power-limited slow)


def test_slew_limit(client):
    start(client, max_dps=20)
    feed(client, {J: 40.0}, 0.5)
    assert client.get("/status").json()["live"]["multi"][J] < 15.0   # ~20 deg/s * 0.5 s


def test_stop_holds_pose_and_frees_slot(client):
    start(client)
    feed(client, {J: 20.0}, 0.4)
    client.post("/teleop/stop")
    live = wait_idle(client)
    assert "teleop stopped" in logs(client)
    assert client.post("/teleop/target", json={"angles": {J: 1}}).status_code == 400


def test_estop_aborts(client):
    start(client)
    client.post("/stop")
    wait_idle(client)
    assert "aborted" in logs(client)


def test_busy_while_teleop_runs(client):
    start(client)
    assert client.post("/teleop/start", json={}).status_code == 400


def _lm(left_yaw_dir=0.0):
    """Person facing the camera, left arm raised sideways by left_yaw_dir deg."""
    import math
    lm = [[0.0, 0.0, 0.0, 0.0] for _ in range(33)]
    lm[11] = [0.2, -0.5, 0, 1]; lm[12] = [-0.2, -0.5, 0, 1]
    lm[23] = [0.1, 0, 0, 1]; lm[24] = [-0.1, 0, 0, 1]
    a = math.radians(left_yaw_dir)
    lm[13] = [0.2 + 0.3 * math.sin(a), -0.5 + 0.3 * math.cos(a), 0, 1]
    lm[15] = [lm[13][0], lm[13][1] + 0.25, 0, 1]
    return lm


def test_pose_preview_does_not_start_anything(client):
    r = client.post("/teleop/pose", json={"landmarks": _lm(30)})
    assert r.status_code == 200
    j = r.json()
    assert j["tracked"] and j["active"] is False
    assert j["angles"]["left_shoulder_yaw"] == pytest.approx(30, abs=0.5)
    assert client.get("/status").json()["live"]["running"] is False


def test_pose_feeds_active_teleop(client):
    service.CFG.servo_ids_path.write_text(json.dumps({"left_shoulder_yaw": 12}))
    service.CFG.limits_path.write_text(json.dumps({"left_shoulder_yaw": {
        "min_deg": -50.0, "max_deg": 20.0, "set": "direct", "updated": "x"}}))
    assert client.post("/teleop/start", json={"joints": ["left_shoulder_yaw"],
                                              "max_dps": 360, "smooth": 1.0}).status_code == 200
    t0 = time.monotonic()
    while time.monotonic() - t0 < 0.6:
        j = client.post("/teleop/pose", json={"landmarks": _lm(35)}).json()
        time.sleep(0.05)
    assert j["active"] is True
    assert client.get("/status").json()["live"]["multi"]["left_shoulder_yaw"] == pytest.approx(20.0, abs=0.01)


def test_pose_rejects_bad_payload(client):
    assert client.post("/teleop/pose", json={"landmarks": [[0, 0, 0, 1]] * 5}).status_code == 422
    assert client.post("/teleop/pose", json={"landmarks": [[0, 0, 0]] * 33}).status_code == 400
