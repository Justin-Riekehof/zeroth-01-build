"""Demo step titles: optional, round-trip through the Pi's save endpoint, and
appear in the playback phase label."""
from test_service import wait_idle

import service


def test_step_title_roundtrip_and_phase(client):
    steps = [{"title": "arm up", "angles": {"right_elbow": 20.0}, "speed": 3400, "acc": 50, "pause_s": 0},
             {"angles": {"right_elbow": 0.0}, "speed": 3400, "acc": 50, "pause_s": 0}]
    r = client.post("/demos", json={"name": "titled", "steps": steps})
    assert r.status_code == 200
    saved = next(d for d in r.json()["demos"] if d["name"] == "titled")
    assert saved["steps"][0]["title"] == "arm up" and saved["steps"][1]["title"] == ""
    r = client.post("/demo/titled")
    assert r.status_code == 200 and r.json()["steps"] == 2
    assert wait_idle(client)["phase"] == "done"


def test_step_title_too_long_rejected(client):
    r = client.post("/demos", json={"name": "t2", "steps": [{"title": "x" * 61, "angles": {"right_elbow": 0.0}}]})
    assert r.status_code == 422


def test_play_until_stops_after_step(client):
    steps = [{"angles": {"right_elbow": 30.0}, "speed": 3400},
             {"angles": {"right_elbow": -30.0}, "speed": 3400},
             {"angles": {"right_elbow": 0.0}, "speed": 3400}]
    assert client.post("/demos", json={"name": "u", "steps": steps}).status_code == 200
    r = client.post("/demo/u", json={"until": 1})
    assert r.status_code == 200 and r.json()["steps"] == 1
    live = wait_idle(client)
    assert live["phase"] == "done"
    assert abs(service.S.bus.read_pos(13) - (2048 + 30 * 4096 / 360)) <= 26
    assert client.post("/demo/u", json={"until": 4}).status_code == 400
    assert client.post("/demo/u", json={"until": 0}).status_code == 422


def test_settle_only_on_held_and_last_steps():
    from types import SimpleNamespace
    from zbot_core.motion import MotionEngine
    st = lambda pause, settle=None: SimpleNamespace(pause_s=pause, settle=settle)
    assert MotionEngine.settle_for(st(0), last=False) is False      # transit step
    assert MotionEngine.settle_for(st(0.5), last=False) is True     # held pose
    assert MotionEngine.settle_for(st(0), last=True) is True        # final pose
    assert MotionEngine.settle_for(st(0, settle=False), last=True) is False
    assert MotionEngine.settle_for(st(0, settle=True), last=False) is True
