"""Center pose override (hardware/center_pose.json) against the SimBus.

Every "center" action targets the override angles instead of 0 deg; joints
not listed stay at 0 deg; the override is clamped to the joint's limits and
composes with mount offsets; an empty file restores the mount pose."""
import pytest
from test_service import CENTER, TOL, logs, wait_idle

import service


@pytest.fixture(autouse=True)
def no_center_pose():
    """These tests write hardware/center_pose.json — never leak it into other tests."""
    service.CFG.write_center_pose({})
    yield
    service.CFG.write_center_pose({})

TPD = 4096 / 360.0   # ticks per degree


def _center(client):
    r = client.post("/center", json={"hold": True, "speed": 3400})
    assert r.status_code == 200
    assert wait_idle(client)["phase"] == "done"


def test_center_pose_override_targets_angles(client):
    service.CFG.write_center_pose({"right_elbow": 20.0})
    _center(client)
    assert abs(service.S.bus.read_pos(11) - CENTER) <= TOL          # not listed -> 0 deg
    assert abs(service.S.bus.read_pos(13) - (CENTER + 20 * TPD)) <= TOL
    assert "center pose override: right_elbow +20.0 deg" in logs(client)


def test_center_pose_composes_with_offset_and_clamps(client):
    service.CFG.write_offsets({"right_elbow": 90.0})
    service.CFG.write_center_pose({"right_elbow": -30.0, "right_shoulder_pitch": 150.0})
    _center(client)
    # mount offset +90 and center pose -30 -> tick(180 + 90 - 30)
    assert abs(service.S.bus.read_pos(13) - (CENTER + 60 * TPD)) <= TOL
    # 150 deg lies outside the +-90 limits -> clamped to +90
    assert abs(service.S.bus.read_pos(11) - (CENTER + 90 * TPD)) <= TOL
    assert "right_shoulder_pitch +90.0 deg (clamped to limits)" in logs(client)


def test_center_pose_cleared_is_mount_pose(client):
    service.CFG.write_center_pose({"right_elbow": 45.0})
    _center(client)
    service.CFG.write_center_pose({})
    _center(client)
    assert abs(service.S.bus.read_pos(13) - CENTER) <= TOL
    assert "center pose override" not in logs(client).split("--- group center")[-1]


def test_demo_center_step_follows_override(client):
    """A flagged center step and an all-zero step both resolve to the override."""
    service.CFG.write_center_pose({"right_elbow": 25.0})
    steps = [{"center": True, "angles": {"right_shoulder_pitch": 0.0, "right_elbow": 0.0}, "speed": 3400},
             {"angles": {"right_elbow": 60.0}, "speed": 3400},
             {"angles": {"right_shoulder_pitch": 0.0, "right_elbow": 0.0}, "speed": 3400}]   # old-style center
    assert client.post("/demos", json={"name": "c", "steps": steps}).status_code == 200
    assert client.post("/demo/c").status_code == 200
    live = wait_idle(client)
    assert live["phase"] == "done"
    assert abs(service.S.bus.read_pos(13) - (CENTER + 25 * TPD)) <= TOL     # ended on the all-zero step -> override
    assert abs(service.S.bus.read_pos(11) - CENTER) <= TOL
    assert logs(client).count("center step -> center pose override (right_elbow +25.0 deg)") == 2


def test_power_limits_clamp_speed_and_acc(client):
    service.CFG.write_motion_limits({})            # defaults: 300 / 30
    steps = [{"angles": {"right_elbow": 20.0}, "speed": 3400, "acc": 254},
             {"angles": {"right_elbow": 0.0}, "speed": 3400, "acc": 0}]     # acc 0 = no ramp -> clamped too
    assert client.post("/demos", json={"name": "fast", "steps": steps}).status_code == 200
    assert client.post("/demo/fast").status_code == 200
    assert wait_idle(client)["phase"] == "done"
    out = logs(client)
    assert "power limit: speed 3400 -> 300, acc 254 -> 30" in out
    assert "power limit: speed 3400 -> 300, acc 0 -> 30" in out
    assert out.count("power limit: speed 3400 -> 300, acc 254 -> 30") == 1   # once per run
