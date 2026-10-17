"""Demo step titles: optional, round-trip through the Pi's save endpoint, and
appear in the playback phase label."""
import time

from test_service import logs, wait_idle

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


def test_stagger_pairs_mirrors_and_only_on_the_first_move():
    """Mirrored joints share a wave, and the stagger applies to the first move
    of a run only (later demo steps must start together)."""
    from zbot_core.motion import MotionEngine
    plan = [{"id": i, "joint": j} for j, i in (
        ("left_hip_pitch", 31), ("left_knee_pitch", 34),
        ("right_hip_pitch", 41), ("right_knee_pitch", 44))]
    waves = MotionEngine._stagger_waves({31: 0, 34: 0, 41: 0, 44: 0}, plan)
    assert [sorted(w) for w in waves] == [[31, 41], [34, 44]]
    # a joint without its mirror in the move stays alone
    assert MotionEngine._stagger_waves({34: 0}, plan) == [[34]]


def test_demo_steps_after_the_first_are_not_staggered(client):
    service.CFG.write_motion_limits({"max_speed": 3400, "max_acc": 254, "stagger_ms": 300})
    steps = [{"angles": {"right_shoulder_pitch": 10.0, "right_elbow": 10.0}, "speed": 3400},
             {"angles": {"right_shoulder_pitch": 0.0, "right_elbow": 0.0}, "speed": 3400}]
    assert client.post("/demos", json={"name": "stag", "steps": steps}).status_code == 200
    t0 = time.monotonic()
    assert client.post("/demo/stag").status_code == 200
    assert wait_idle(client)["phase"] == "done"
    # 2 unmirrored joints -> 2 waves; only the first step waits once (300 ms)
    assert time.monotonic() - t0 < 1.2
    service.CFG.write_motion_limits({"max_speed": 3400, "max_acc": 254})


def test_boost_step_bypasses_the_power_limits(client):
    service.CFG.write_motion_limits({})                 # defaults 300 / 30
    steps = [{"angles": {"right_elbow": 10.0}, "speed": 3400, "acc": 254},
             {"title": "push off", "angles": {"right_elbow": 0.0}, "speed": 3400, "acc": 254, "boost": True}]
    assert client.post("/demos", json={"name": "boost", "steps": steps}).status_code == 200
    assert client.post("/demo/boost").status_code == 200
    assert wait_idle(client)["phase"] == "done"
    # only this run's lines: the live log keeps the last 300 entries of the session
    out = logs(client).split("--- demo 'boost'")[-1]
    assert "power limit: speed 3400 -> 300, acc 254 -> 30" in out        # step 1 clamped
    assert "step 2: POWER BOOST — speed 3400, acc 254" in out            # step 2 not
    service.CFG.write_motion_limits({"max_speed": 3400, "max_acc": 254})


def test_play_single_step_skips_the_earlier_ones(client):
    """start == until moves straight to that pose, with the step's own speed."""
    steps = [{"angles": {"right_elbow": 40.0}, "speed": 3400},
             {"title": "target", "angles": {"right_elbow": -20.0}, "speed": 3400},
             {"angles": {"right_elbow": 0.0}, "speed": 3400}]
    assert client.post("/demos", json={"name": "jump", "steps": steps}).status_code == 200
    r = client.post("/demo/jump", json={"start": 2, "until": 2})
    assert r.status_code == 200 and r.json()["steps"] == 1
    assert wait_idle(client)["phase"] == "done"
    # step 1 (+40) was skipped, the robot sits on step 2's angle
    assert abs(service.S.bus.read_pos(13) - (2048 - 20 * 4096 / 360)) <= 26
    out = logs(client).split("--- demo 'jump'")[-1]
    assert "direct move: starting at step 2" in out
    assert "step 2/3 (target)" in out and "step 1/3" not in out


def test_play_range_and_bad_range_rejected(client):
    steps = [{"angles": {"right_elbow": float(a)}, "speed": 3400} for a in (30, 15, 0)]
    assert client.post("/demos", json={"name": "rng", "steps": steps}).status_code == 200
    assert client.post("/demo/rng", json={"start": 2}).status_code == 200      # 2..end
    assert wait_idle(client)["phase"] == "done"
    assert abs(service.S.bus.read_pos(13) - 2048) <= 26
    assert client.post("/demo/rng", json={"start": 4}).status_code == 400
    assert client.post("/demo/rng", json={"start": 3, "until": 2}).status_code == 400
    assert client.post("/demo/rng", json={"start": 0}).status_code == 422
