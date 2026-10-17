"""Fall detection (posture.py) and get-up sequences (hardware/getup.json).

Default imu_axes {"up": "+y", "forward": "-z"} -> body right = +x. At rest
the accelerometer reads +1000 mg along the axis that points UP, so:
upright ay=+1000 · face down az=+1000 · on its back az=-1000 ·
right side down ax=-1000 · left side down ax=+1000."""
import math

import pytest
from test_service import logs, wait_idle

import service
from posture import PostureMonitor, classify, lying_label
from zbot_core.config import Demo
from zbot_core.getup import GetupConfig, load_getup_demo, validate_getup


def sample(up=0.0, fwd=0.0, right=0.0, gyro=0.0):
    """Body-frame gravity (mg) -> board-frame sample for the default axes."""
    return {"ax": right, "ay": up, "az": -fwd, "gx": gyro, "gy": 0.0, "gz": 0.0}


def lying(az_deg, tilt_deg=90.0, gyro=0.0):
    """Sample of a body tilted by tilt_deg toward azimuth az_deg
    (0 = face down, 180 = back, +90 = right side)."""
    t, a = math.radians(tilt_deg), math.radians(az_deg)
    h = 1000 * math.sin(t)
    # the DOWN-pointing body direction reads negative
    return sample(up=1000 * math.cos(t), fwd=-h * math.cos(a),
                  right=-h * math.sin(a), gyro=gyro)


# ------------------------------------------------------------ classification

@pytest.mark.parametrize("s, facing, case", [
    (sample(fwd=-1000), "front", "front"),           # face down
    (sample(fwd=1000), "back", "back"),              # on its back
    (sample(right=-1000), "right", "back"),          # exactly sideways: tie -> back
    (sample(right=1000), "left", "back"),
    (lying(60), "right", "front"),                   # mostly sideways, closer to face down
    (lying(-120), "left", "back"),                   # mostly sideways, closer to the back
    (lying(20), "front", "front"),
    (lying(-170), "back", "back"),
    (sample(up=-1000), "inverted", None),
])
def test_classify_directions(s, facing, case):
    c = classify(s)
    assert c["facing"] == facing
    if case:
        assert c["case"] == case


def test_classify_upright_and_tilt():
    assert classify(sample(up=1000))["tilt_deg"] == 0.0
    c = classify(lying(0, tilt_deg=30))
    assert c["tilt_deg"] == pytest.approx(30, abs=0.2)
    assert c["azimuth_deg"] == pytest.approx(0, abs=0.2)


def test_side_roll_reported():
    c = classify(lying(25))
    assert c["side_deg"] == pytest.approx(25, abs=0.2)
    assert lying_label(c) == "face down, rolled 25° to the right"
    c = classify(lying(-150))                       # back, rolled 30° to the left
    assert c["side_deg"] == pytest.approx(-30, abs=0.2)
    assert lying_label(c) == "on its back, rolled 30° to the left"
    assert "closer to face down" in lying_label(classify(lying(70)))


def test_axes_mapping_is_honoured():
    # board mounted with +z up and +x forward
    axes = {"up": "+z", "forward": "+x"}
    assert classify({"ax": -1000, "ay": 0, "az": 0}, axes)["facing"] == "front"
    assert classify({"ax": 1000, "ay": 0, "az": 0}, axes)["facing"] == "back"


# ------------------------------------------------------------ monitor

class FakeImu:
    axes = {"up": "+y", "forward": "-z"}

    def __init__(self):
        self.s = None

    def snapshot(self):
        return {"sample": self.s, "age_s": 0.05 if self.s else None}


class Mon:
    """PostureMonitor on a fake IMU with a controllable clock."""

    def __init__(self, **cfg):
        self.imu = FakeImu()
        self.played = []
        self.gc = GetupConfig(**cfg)
        self.m = PostureMonitor(self.imu, service.ENGINE, lambda: self.gc,
                                self.played.append)
        self.t = 1000.0

    def run(self, s, seconds, dt=0.1):
        self.imu.s = s
        for _ in range(int(round(seconds / dt))):
            self.t += dt
            self.m.tick(self.t)
        return self.m.snapshot()


@pytest.fixture(autouse=True)
def quiet_posture(client):
    """The service's own posture thread must not race the hand-driven ticks."""
    service.POSTURE.stop()
    service.CFG.write_getup({})
    yield
    service.CFG.write_getup({})
    service.POSTURE.invalidate()


def test_states_with_hysteresis(client):
    m = Mon()
    assert m.run(sample(up=1000), 0.3)["state"] == "upright"
    assert m.run(lying(0, 38), 0.3)["state"] == "upright"      # 35 + 5 hysteresis
    assert m.run(lying(0, 45), 0.3)["state"] == "tilted"
    assert m.run(lying(0, 70), 0.3)["state"] == "fallen"
    assert m.run(lying(0, 57), 0.3)["state"] == "fallen"       # 60 - 5 hysteresis
    assert m.run(lying(0, 50), 0.3)["state"] == "tilted"
    m.imu.s = None
    m.t += 0.1
    m.m.tick(m.t)
    assert m.m.snapshot()["state"] == "unknown"


def test_impact_sample_does_not_flip_state(client):
    m = Mon()
    m.run(sample(up=1000), 0.3)
    assert m.run(sample(up=300, fwd=-2500), 0.1)["state"] == "upright"


def test_fall_logged_without_auto(client):
    m = Mon()
    m.run(sample(up=1000), 0.3)
    p = m.run(lying(-160), 3.0)
    assert p["state"] == "fallen" and p["case"] == "back"
    assert p["settled"] and m.played == []
    assert "POSTURE: FALLEN — on its back, rolled 20° to the left" in logs(client)
    m.run(sample(up=1000), 0.3)
    assert "POSTURE: upright again" in logs(client)


def test_auto_getup_after_settling(client):
    m = Mon(auto=True, hold_s=1.0, front="x")
    m.run(sample(up=1000), 0.3)
    m.run(lying(10, gyro=120), 0.5)          # still tumbling
    assert m.played == []
    m.run(lying(10), 0.6)                    # still, but not long enough
    assert m.played == []
    m.run(lying(10), 0.6)
    assert m.played == ["front"]
    assert m.m.snapshot()["episode"]["attempts"] == 1
    m.run(sample(up=1000), 0.3)              # get-up worked
    assert m.m.snapshot()["episode"] is None
    assert "get-up succeeded (attempt 1)" in logs(client)


def test_auto_retries_then_gives_up(client):
    m = Mon(auto=True, hold_s=0.5, max_attempts=2)
    m.run(sample(up=1000), 0.3)
    m.run(lying(180), 2.0)
    m.run(lying(180), 2.0)
    m.run(lying(180), 2.0)
    assert m.played == ["back", "back"]
    assert m.m.snapshot()["episode"]["gave_up"]
    assert "giving up" in logs(client)


def test_no_auto_for_a_fall_during_a_run(client):
    """push_ups lies down on purpose — a run that ends on the floor must not
    look like a fall."""
    m = Mon(auto=True, hold_s=0.5)
    m.run(sample(up=1000), 0.3)
    service.S.set(running=True)
    try:
        m.run(lying(0), 1.0)
    finally:
        service.S.set(running=False)
    m.run(lying(0), 3.0)
    assert m.played == [] and m.m.snapshot()["episode"] is None
    assert "POSTURE: FALLEN — face down (tilt 90°" in logs(client)
    assert logs(client).rstrip().endswith("during a run")


def test_no_auto_when_already_lying_at_start(client):
    m = Mon(auto=True, hold_s=0.5)
    m.run(lying(0), 3.0)                       # first sample: already down
    assert m.played == []


def test_stop_cancels_auto(client):
    m = Mon(auto=True, hold_s=1.0)
    m.run(sample(up=1000), 0.3)
    m.run(lying(0), 0.5)
    m.m.cancel()
    m.run(lying(0), 3.0)
    assert m.played == []


# ------------------------------------------------------------ sequences + API

def save_floor_demo(name="floor"):
    service.CFG.save_demo(Demo(name=name, steps=[
        {"angles": {"right_shoulder_pitch": 20.0}, "speed": 3400, "acc": 150, "title": "b"},
        {"angles": {"right_shoulder_pitch": 30.0}, "speed": 3400, "acc": 150},
        {"angles": {"right_elbow": 15.0}, "speed": 3400, "acc": 150, "title": "d"},
    ]))


def test_assignment_validated_and_loaded(client):
    save_floor_demo()
    gc = GetupConfig(front="floor", back="gone")
    assert validate_getup(service.CFG, gc) == ["back: demo 'gone' not found"]
    assert load_getup_demo(service.CFG, gc, "front").name == "floor"
    with pytest.raises(ValueError, match="no get-up demo assigned"):
        load_getup_demo(service.CFG, GetupConfig(), "back")
    with pytest.raises(ValueError, match="not found"):
        load_getup_demo(service.CFG, gc, "back")


def test_threshold_validation():
    with pytest.raises(ValueError):
        GetupConfig(upright_deg=50, fallen_deg=45)
    assert GetupConfig(hold_s=15).hold_s == 15
    with pytest.raises(ValueError):                 # the old step-range format
        GetupConfig(front=[{"demo": "x", "start": 1, "until": 2}])


def test_config_roundtrip_and_play(client):
    save_floor_demo("getup_front")
    r = client.post("/getup/config", json={"front": "getup_front", "auto": True})
    assert r.status_code == 200 and r.json()["problems"] == []
    g = client.get("/getup").json()
    assert g["config"]["front"] == "getup_front" and g["config"]["auto"]
    assert "posture" in client.get("/status").json()
    r = client.post("/getup", json={"case": "front"})
    assert r.status_code == 200 and r.json()["steps"] == 3
    live = wait_idle(client)
    assert live["phase"] == "done", live
    TPD = 4096 / 360.0
    assert abs(service.S.bus.read_pos(11) - (2048 + 30 * TPD)) <= 26
    assert abs(service.S.bus.read_pos(13) - (2048 + 15 * TPD)) <= 26
    out = logs(client)
    assert "get-up 'front' (face down): getup_front" in out
    assert "demo 'getup_front'" in out


def test_edited_demo_is_what_plays(client):
    """The get-up demo is an ordinary demo: saving it again changes the get-up."""
    save_floor_demo("getup_front")
    client.post("/getup/config", json={"front": "getup_front"})
    service.CFG.save_demo(Demo(name="getup_front", steps=[
        {"angles": {"right_elbow": -40.0}, "speed": 3400, "acc": 150}]))
    assert client.post("/getup", json={"case": "front"}).json()["steps"] == 1
    wait_idle(client)
    assert abs(service.S.bus.read_pos(13) - (2048 - 40 * 4096 / 360.0)) <= 26


def test_getup_rejections(client):
    r = client.post("/getup", json={"case": "back"})
    assert r.status_code == 400 and "no get-up demo assigned" in r.json()["detail"]
    service.POSTURE.reset()                       # no IMU in the test service
    r = client.post("/getup", json={"case": "auto"})
    assert r.status_code == 400 and "No IMU data" in r.json()["detail"]
    assert client.post("/getup", json={"case": "sideways"}).status_code == 422
