"""IMU balance assist: pure controller + a demo played on the SimBus with a
fake torso tilt."""
from test_service import logs, wait_idle

import pytest

import service
from zbot_core import balance as B

CFG = B.merged({})


@pytest.fixture
def legs():
    ids = {"left_knee_pitch": 31, "right_knee_pitch": 21,
           "left_ankle_pitch": 32, "right_ankle_pitch": 22}
    service.CFG.write_servo_ids(ids)
    service.CFG.write_limits({j: {"min_deg": -90.0, "max_deg": 90.0} for j in ids})


def feed(ctrl, pitch, roll, n=30, dt=0.04, t0=0.0):
    out = {}
    for k in range(n):
        out = ctrl.update(pitch, roll, 1000.0, t0 + k * dt)
    return out


def test_stance_auto():
    assert B.pick_stance(CFG, {"left_knee_pitch": 0, "right_knee_pitch": 60}) == "left"
    assert B.pick_stance(CFG, {"left_knee_pitch": -50, "right_knee_pitch": 2}) == "right"
    assert B.pick_stance(CFG, {"left_knee_pitch": 20, "right_knee_pitch": 25}) == "both"
    assert B.pick_stance({**CFG, "stance": "right"}, {}) == "right"


def test_no_correction_at_reference_and_in_deadband():
    c = B.TiltBalancer(CFG, "left")
    c.set_reference(5.0, 0.0)
    assert all(v == 0 for v in feed(c, 5.0, 0.0).values())
    assert all(v == 0 for v in feed(c, 5.4, 0.3).values())


def test_pitch_forward_drives_ankle_by_axis_sign_and_is_clamped():
    c = B.TiltBalancer(CFG, "left")
    c.set_reference(0.0, 0.0)
    off = feed(c, 10.0, 0.0, n=200)
    assert 0 < off["left_ankle_pitch"] <= CFG["max_deg"]
    assert off["right_ankle_pitch"] == 0          # not the stance leg
    c2 = B.TiltBalancer(CFG, "right")             # right ankle axis is mirrored
    c2.set_reference(0.0, 0.0)
    assert feed(c2, 10.0, 0.0, n=200)["right_ankle_pitch"] < 0


def test_roll_only_in_single_support_and_slew_limited():
    c = B.TiltBalancer(CFG, "left")
    c.set_reference(0.0, 0.0)
    off = feed(c, 0.0, 6.0, n=3)
    assert off["left_hip_yaw"] < 0 and abs(off["left_hip_yaw"]) <= CFG["slew_dps"] * 0.12 + 1e-9
    both = B.TiltBalancer(CFG, "both")
    both.set_reference(0.0, 0.0)
    assert feed(both, 0.0, 6.0)["left_hip_yaw"] == 0


def test_dynamic_sample_is_ignored():
    c = B.TiltBalancer(CFG, "left")
    c.set_reference(0.0, 0.0)
    assert all(v == 0 for v in c.update(30.0, 0.0, 2500.0, 0.0).values())


def test_demo_with_balance_on_simbus(client, legs):
    tilt = {"pitch": 0.0, "roll": 0.0, "g": 1000.0}
    service.ENGINE.tilt_source = lambda: dict(tilt)
    try:
        steps = [{"angles": {"left_knee_pitch": 0.0, "right_knee_pitch": 0.0,
                             "left_ankle_pitch": 0.0, "right_ankle_pitch": 0.0},
                  "speed": 3400, "pause_s": 0},
                 {"angles": {"left_knee_pitch": 0.0, "right_knee_pitch": 40.0,
                             "left_ankle_pitch": 0.0, "right_ankle_pitch": 20.0},
                  "speed": 1000, "pause_s": 0.4, "balance": True}]
        assert client.post("/demos", json={"name": "bal", "steps": steps}).status_code == 200
        tilt["pitch"] = 6.0                      # torso leans forward during the move
        assert client.post("/demo/bal").status_code == 200
        assert wait_idle(client)["phase"] == "done"
        text = logs(client)
        assert "balance assist ON" in text and "stance left" in text
        assert "synchronised joint arrival" in text
    finally:
        service.ENGINE.tilt_source = service._torso_tilt


def test_demo_balance_without_imu_just_plays(client, legs):
    service.ENGINE.tilt_source = lambda: None
    try:
        steps = [{"angles": {"left_ankle_pitch": 5.0}, "speed": 3400, "balance": True}]
        assert client.post("/demos", json={"name": "bal2", "steps": steps}).status_code == 200
        assert client.post("/demo/bal2").status_code == 200
        assert wait_idle(client)["phase"] == "done"
        assert "no fresh IMU" in logs(client)
    finally:
        service.ENGINE.tilt_source = service._torso_tilt
