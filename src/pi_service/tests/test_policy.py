"""Walking-policy runner: observation contract, ONNX round trip, safety refusals, 50 Hz loop
on the SimBus. Uses the real versioned policy files in sim/policies/."""
import math
import time
from pathlib import Path

import numpy as np
import pytest

import policy as P
import service

POLICIES = Path(__file__).resolve().parents[3] / "sim" / "policies"
NAME = "cad2_v13_tiny_step905"
IDS = {"right_shoulder_pitch": 21, "right_shoulder_yaw": 22, "right_elbow_yaw": 23,
       "left_shoulder_pitch": 11, "left_shoulder_yaw": 12, "left_elbow_yaw": 13,
       "right_hip_pitch": 41, "right_hip_yaw": 42, "right_hip_roll": 43,
       "right_knee_pitch": 44, "right_ankle_pitch": 45, "left_hip_pitch": 31,
       "left_hip_yaw": 32, "left_hip_roll": 33, "left_knee_pitch": 34, "left_ankle_pitch": 35}


class StubImu:
    """Standing robot: +1 g on the chip Y axis, as the real board reads it."""
    def __init__(self, ay=1000.0):
        self.ay, self.seq = ay, 0

    gy = 0.0

    def snapshot(self):
        self.seq += 1
        return {"age_s": 0.01, "sample": {"ax": 0.0, "ay": self.ay, "az": 0.0,
                                          "gx": 0.0, "gy": self.gy, "gz": 0.0, "seq": self.seq}}


@pytest.fixture
def runner(client, monkeypatch, tmp_path):
    monkeypatch.setattr(P, "GYRO_CAL_S", 0.15)
    cfg = service.CFG
    cfg.write_servo_ids(IDS)
    cfg.write_limits({j: {"min_deg": -80.0, "max_deg": 80.0} for j in IDS})
    cfg.write_offsets({})
    r = P.PolicyRunner(service.ENGINE, StubImu(), POLICIES)
    r.log_dir = tmp_path / "policy_logs"
    yield r
    r.stop()
    if r._thread:
        r._thread.join(2)
    service.S.set(running=False)
    service.S.abort.clear()
    bus = service.S.bus                      # the session-wide SimBus: back to the centre
    bus._pos.clear(); bus._target.clear(); bus._speed.clear()


def _wait_done(r, timeout=3.0):
    r._thread.join(timeout)
    assert not r._thread.is_alive()


def test_policy_loads_and_is_bounded():
    pol = P.LoadedPolicy(POLICIES / NAME)
    a = pol(np.zeros(P.N_IN, np.float32))
    assert a.shape == (16,) and np.all(np.abs(a) <= 1.0 + 1e-6)
    np.testing.assert_allclose(pol.up_in_imu, [0, 1, 0])      # body up = chip Y


def test_every_versioned_policy_matches_the_layout():
    names = [p["name"] for p in P.list_policies(POLICIES)]
    assert len(names) >= 5
    for n in names:
        P.LoadedPolicy(POLICIES / n)


def test_obs_layout_and_gait_clock():
    ob = P.ObsBuilder(16, 1.5, np.array([0.0, 1, 0]))
    z16 = np.zeros(16)
    o = ob.build(z16, z16, np.array([0, 9.81, 0]), np.zeros(3), np.array([.1, 0]), 0.2)
    assert o.shape == (64,)
    # [cos p0, cos p1, sin p0, sin p1] with phases (0, pi)
    np.testing.assert_allclose(o[:4], [1, -1, 0, 0], atol=1e-6)
    np.testing.assert_allclose(o[42:46], [.1, 0, .2, 1.5], atol=1e-6)   # lin, ang, gait cmd
    np.testing.assert_allclose(o[-2:], [1, 0])                          # heading at start
    ob.advance(np.full(16, .5))
    assert ob.phase[0] == pytest.approx(2 * math.pi * 1.5 * P.CTRL_DT)
    o = ob.build(z16, z16, np.zeros(3), np.zeros(3), np.zeros(2), 0.0)
    np.testing.assert_allclose(o[46:62], 0.5)                           # last action


def test_heading_integrates_once_per_new_imu_sample():
    ob = P.ObsBuilder(16, 1.5, np.array([0.0, 1, 0]))
    g = np.array([0.0, 0.5, 0.0])
    ob.integrate_yaw(g, 1, 10.0)
    ob.integrate_yaw(g, 1, 10.02)          # same sample again: must not integrate twice
    ob.integrate_yaw(g, 2, 10.05)
    assert ob.psi == pytest.approx(0.5 * 0.05)


def test_refuses_command_outside_trained_range(runner):
    with pytest.raises(P.PolicyError, match="trained range"):
        runner.start(NAME, vx=0.5, dry_run=True)
    with pytest.raises(P.PolicyError, match="gait_freq"):
        runner.start(NAME, gait_freq=5.0, dry_run=True)
    assert not service.S.live["running"]                  # slot not leaked


def test_refuses_when_not_standing(runner):
    runner.imu.ay = 0.0                                   # gravity not on chip Y
    with pytest.raises(P.PolicyError, match="not standing upright"):
        runner.start(NAME, dry_run=True)
    assert not service.S.live["running"]


def test_refuses_without_imu(runner):
    runner.imu = type("NoImu", (), {"snapshot": lambda s: {"age_s": None, "sample": None}})()
    with pytest.raises(P.PolicyError, match="no head-IMU"):
        runner.start(NAME, dry_run=True)


def test_unknown_policy_and_path_escape(runner):
    for bad in ("nope", "../policies", ".."):
        with pytest.raises(P.PolicyError):
            runner.start(bad, dry_run=True)


def test_closed_loop_on_simbus_holds_rate(runner):
    runner.start(NAME)
    time.sleep(0.6)
    st = runner.status()
    assert st["running"] and st["stats"]["steps"] >= 15
    runner.set_cmd(vx=0.08)
    assert runner.status()["cmd"]["vx"] == 0.08
    with pytest.raises(P.PolicyError):
        runner.set_cmd(vx=0.9)
    runner.stop()
    _wait_done(runner)
    st = runner.status()
    assert st["stats"]["stop_reason"] == "stopped"
    assert st["stats"]["max_step_ms"] < 20
    assert not service.S.live["running"]


def test_dry_run_never_commands_servos(runner, monkeypatch):
    bus = service.S.bus
    monkeypatch.setattr(bus, "sync_move", lambda *a, **k: pytest.fail("servo command in dry run"))
    monkeypatch.setattr(bus, "torque_on", lambda *a, **k: pytest.fail("torque in dry run"))
    runner.start(NAME, dry_run=True)
    time.sleep(0.3)
    runner.stop()
    _wait_done(runner)
    assert runner.status()["stats"]["steps"] > 5


def test_fall_aborts_and_goes_limp(runner, monkeypatch):
    released = []
    bus = service.S.bus
    orig = bus.torque_off
    monkeypatch.setattr(bus, "torque_off", lambda i: (released.append(i), orig(i))[1])
    runner.start(NAME)
    time.sleep(0.2)
    runner.imu.ay = 0.0                                   # robot tips over
    _wait_done(runner, 4.0)
    assert "tilt" in runner.status()["stats"]["stop_reason"]
    assert service.S.live["phase"] == "error"
    assert set(released) == set(IDS.values())             # every servo released, none held


def test_estop_releases_and_ends_run(client, runner):
    runner.start(NAME)
    time.sleep(0.2)
    service.ENGINE.stop()                                 # what POST /stop does
    _wait_done(runner)
    assert "E-stop" in runner.status()["stats"]["stop_reason"]


def test_endpoints(client):
    r = client.get("/policies")
    assert r.status_code == 200 and r.json()["policies"] == []     # tmp ROOT has no policies
    assert client.post("/policy/start", json={"name": "x"}).status_code == 400


def test_gyro_bias_is_removed_from_heading(runner):
    runner.imu.gy = -3.0                                  # the real chip's resting offset
    runner.start(NAME, dry_run=True)
    assert runner.status()["gyro_bias_dps"][1] == pytest.approx(-3.0)
    time.sleep(0.5)
    heading = runner.status()["last"]["heading_deg"]
    runner.stop()
    _wait_done(runner)
    assert abs(heading) < 1.0                             # without the fix: -3 dps -> drifts


def test_live_start_refused_while_robot_is_moved(runner):
    class Shaken(StubImu):
        def snapshot(self):
            self.gy = 40.0 * (-1) ** self.seq
            return super().snapshot()
    runner.imu = Shaken()
    with pytest.raises(P.PolicyError, match="moving during gyro calibration"):
        runner.start(NAME)
    assert not service.S.live["running"]


def test_dry_run_shows_the_policy_target_not_the_measured_pose(runner):
    runner.start(NAME, dry_run=True)
    time.sleep(0.4)
    shown = dict(service.S.live["multi"])
    runner.stop()
    _wait_done(runner)
    assert len(shown) == 16 and any(abs(v) > 0.05 for v in shown.values())   # SimBus pose is all 0


def test_run_writes_a_replayable_step_log(runner):
    import json
    runner.start(NAME, dry_run=True)
    time.sleep(0.5)
    runner.stop()
    _wait_done(runner)
    name = runner.status()["last_log"]
    assert name and name.endswith("_dry.npz")
    d = np.load(runner.log_path(name))
    meta = json.loads(str(d["meta"]))
    n = meta["steps"]
    assert n >= 10 and meta["joints"] and meta["dry_run"]
    assert d["obs"].shape == (n, P.N_IN) and d["action"].shape == (n, 16)
    assert d["pos_ticks"].shape == (n, 16) and d["imu_raw"].shape == (n, 6)
    # the logged obs really is what the net saw: re-running the policy reproduces the action
    pol = P.LoadedPolicy(POLICIES / NAME)
    np.testing.assert_allclose(pol(d["obs"][5]), d["action"][5], atol=1e-5)
    assert runner.logs()[0]["name"] == name
    with pytest.raises(P.PolicyError):
        runner.log_path("../x.npz")


def test_off_center_start_warns_but_still_runs_and_is_logged(runner):
    import json
    bus = service.S.bus
    sid = IDS["right_ankle_pitch"]
    bus._pos[sid] = 2048 + 30                # about +2.6°, above START_POSE_WARN_DEG
    runner.start(NAME, dry_run=True)
    assert any("start pose off center: right_ankle_pitch +2.6" in e["msg"] for e in service.S.snapshot()["log"])
    time.sleep(0.2)
    runner.stop()
    _wait_done(runner)
    meta = json.loads(str(np.load(runner.log_path(runner.status()["last_log"]))["meta"]))
    assert meta["start_pose_dev_deg"]["right_ankle_pitch"] == pytest.approx(2.64, abs=0.01)
    assert abs(meta["start_pose_dev_deg"]["left_ankle_pitch"]) < 0.1
    assert meta["start_acc_mg"] == [0.0, 1000.0, 0.0]


def test_servo_model_speed_and_rate_limit():
    assert P.resolve_speed(None, None) == 1000                    # old policies: the old default
    assert P.resolve_speed(2000, None) == 2000                    # servo-model policy: its own register
    assert P.resolve_speed(2000, 2000) == 2000
    with pytest.raises(P.PolicyError, match="2000"):
        P.resolve_speed(2000, 3000)
    prev = np.zeros(3)
    out = P.limit_rate(np.array([1.0, -1.0, 0.01]), prev, np.array([2.0, 2.0, 2.0]), 0.02)
    np.testing.assert_allclose(out, [0.04, -0.04, 0.01])
    np.testing.assert_allclose(P.limit_rate(np.array([1.0]), np.zeros(1), None, 0.02), [1.0])   # old policies: none


def test_action_filter_step():
    np.testing.assert_allclose(P.low_pass(np.array([1.0]), np.array([0.0]), 0.2), [0.2])
    np.testing.assert_allclose(P.low_pass(np.array([1.0]), np.array([0.0]), 0.0), [1.0])   # old policies: unfiltered


def test_first_last_action_is_the_start_pose_like_in_the_sim():
    ob = P.ObsBuilder(16, 1.5, np.array([0.0, 1, 0]), history=3)
    pose = np.linspace(-0.3, 0.3, 16)
    o = ob.build(pose, np.zeros(16), np.zeros(3), np.zeros(3), np.zeros(2), 0.0)
    np.testing.assert_allclose(o[46:62], pose, atol=1e-6)
    np.testing.assert_allclose(o[P.N_IN:].reshape(3, 16), np.tile(pose, (3, 1)), atol=1e-6)
    ob.advance(np.zeros(16))
    o = ob.build(np.ones(16), np.zeros(16), np.zeros(3), np.zeros(3), np.zeros(2), 0.0)
    np.testing.assert_allclose(o[46:62], 0.0)                                # from now on: the real actions


def test_action_history_matches_the_sim_order():
    ob = P.ObsBuilder(16, 1.5, np.array([0.0, 1, 0]), history=3)
    z16 = np.zeros(16)
    o = ob.build(z16, z16, np.zeros(3), np.zeros(3), np.zeros(2), 0.0)
    assert o.shape == (P.N_IN + 48,)
    np.testing.assert_allclose(o[P.N_IN:], 0.0)             # start: every older action = the first last action
    for k in (1, 2, 3, 4):                                  # a(t) = k
        ob.advance(np.full(16, float(k)))
    o = ob.build(z16, z16, np.zeros(3), np.zeros(3), np.zeros(2), 0.0)
    np.testing.assert_allclose(o[46:62], 4.0)                                 # last action a(t-1)
    np.testing.assert_allclose(o[P.N_IN:].reshape(3, 16)[:, 0], [3, 2, 1])   # then a(t-2), a(t-3), a(t-4)


def test_policy_with_action_history_loads(tmp_path):
    import json, shutil
    src = POLICIES / NAME
    dst = tmp_path / "hist"
    shutil.copytree(src, dst)
    m = json.loads((dst / "policy_meta.json").read_text())
    m["input"]["layout_in_order"].append({"name": "action_history", "size": 48, "meaning": "x"})
    m["input"]["size"] += 48
    (dst / "policy_meta.json").write_text(json.dumps(m))
    with pytest.raises(P.PolicyError, match="ONNX input"):                   # the 64-input network must be refused
        P.LoadedPolicy(dst)
    m["input"]["layout_in_order"][-1]["size"] = 40                           # not a multiple of 16 joints
    (dst / "policy_meta.json").write_text(json.dumps(m))
    with pytest.raises(P.PolicyError, match="action_history"):
        P.LoadedPolicy(dst)


def _policy_copy(tmp_path, flip):
    import json, shutil
    root = tmp_path / "policies"
    shutil.copytree(POLICIES / NAME, root / "flipped")
    f = root / "flipped" / "policy_meta.json"
    m = json.loads(f.read_text())
    m["joint_sign_flip"] = flip
    f.write_text(json.dumps(m))
    return root


def test_sign_flip_unknown_joint_is_refused(tmp_path):
    root = _policy_copy(tmp_path, ["left_hip_nonsense"])
    with pytest.raises(P.PolicyError, match="joint_sign_flip"):
        P.LoadedPolicy(root / "flipped")


def test_sign_flip_mirrors_measurement_and_command_of_that_joint_only(client, runner, tmp_path):
    import json
    root = _policy_copy(tmp_path, ["left_hip_roll", "right_hip_roll"])
    runner.root = root
    pol = P.LoadedPolicy(root / "flipped")
    runner.start("flipped")
    time.sleep(1.5)                                       # past a 1 s ramp, if any
    runner.stop()
    _wait_done(runner)
    d = np.load(runner.log_path(runner.status()["last_log"]))
    meta = json.loads(str(d["meta"]))
    assert meta["joint_sign_flip"] == ["left_hip_roll", "right_hip_roll"]
    J, off = meta["joints"], meta["offsets"]
    flip = [J.index("left_hip_roll"), J.index("right_hip_roll")]
    keep = J.index("left_knee_pitch")
    k = meta["steps"] - 1
    assert k > pol.ramp_steps
    servo = np.radians((d["pos_ticks"][k] - 2048) * 360 / 4096 - np.asarray(off))
    np.testing.assert_allclose(d["obs"][k, 4:20][flip], -servo[flip], atol=1e-5)    # policy sees the mirrored angle
    np.testing.assert_allclose(d["obs"][k, 4:20][keep], servo[keep], atol=1e-5)     # the others untouched
    lo, hi = np.radians(np.asarray(meta["limits_deg"])).T
    want = np.clip(pol.sign * d["action"][k] * pol.action_scale, lo, hi)
    np.testing.assert_allclose(d["target"][k], want, atol=1e-5)                     # and commands it mirrored
    np.testing.assert_allclose(pol(d["obs"][k]), d["action"][k], atol=1e-5)         # the log stays replayable


def test_start_ramp_follows_the_trained_start(tmp_path):
    """A policy trained from the centre pose acts at full authority from step 0 (as in the sim); older policies keep
    the 1 s blend; policy_meta start_ramp_steps overrides both."""
    import json
    root = _policy_copy(tmp_path, [])
    f = root / "flipped" / "policy_meta.json"
    m = json.loads(f.read_text())
    tc = m.get("task_config", {})
    assert P.LoadedPolicy(root / "flipped").ramp_steps == (0 if tc.get("start_pose") == "center" else P.RAMP_STEPS)
    m["task_config"] = {**tc, "start_pose": "center"}
    f.write_text(json.dumps(m))
    assert P.LoadedPolicy(root / "flipped").ramp_steps == 0
    m["task_config"] = {**tc, "start_pose": "zero"}
    f.write_text(json.dumps(m))
    assert P.LoadedPolicy(root / "flipped").ramp_steps == P.RAMP_STEPS
    m["start_ramp_steps"] = 5
    f.write_text(json.dumps(m))
    assert P.LoadedPolicy(root / "flipped").ramp_steps == 5
