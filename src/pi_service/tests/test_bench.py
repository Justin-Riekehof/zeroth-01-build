"""Servo bench runner: program building, safety refusals, run + log on the SimBus."""
import json
import time

import numpy as np
import pytest

import bench as B
import service

IDS = {"right_shoulder_pitch": 21, "right_shoulder_yaw": 22, "right_elbow_yaw": 23,
       "left_shoulder_pitch": 11, "left_shoulder_yaw": 12, "left_elbow_yaw": 13,
       "right_hip_pitch": 41, "right_hip_yaw": 42, "right_hip_roll": 43,
       "right_knee_pitch": 44, "right_ankle_pitch": 45, "left_hip_pitch": 31,
       "left_hip_yaw": 32, "left_hip_roll": 33, "left_knee_pitch": 34, "left_ankle_pitch": 35}


@pytest.fixture
def bench(client, tmp_path):
    cfg = service.CFG
    cfg.write_servo_ids(IDS)
    cfg.write_limits({j: {"min_deg": -80.0, "max_deg": 80.0} for j in IDS})
    cfg.write_offsets({})
    r = B.BenchRunner(service.ENGINE, tmp_path)
    yield r
    r.stop()
    if r._thread:
        r._thread.join(5)
    service.S.set(running=False)
    service.S.abort.clear()
    bus = service.S.bus
    bus._pos.clear(); bus._target.clear(); bus._speed.clear()
    bus.voltage = 12.3


def _plan(lo=-80.0, hi=80.0, n=3):
    return [{"joint": f"j{k}", "id": k, "offset": 0.0, "lo": lo, "hi": hi} for k in range(n)]


def test_program_stays_inside_the_limits():
    plan = _plan()
    moves, skipped = B.build_program("step", plan, [0.0, 70.0, -75.0], [1000, 3400], [5.0, 30.0, 45.0])
    for m in moves:
        for e, g in zip(plan, m["goal"]):
            assert e["lo"] + B.MARGIN_DEG - 1e-6 <= g <= e["hi"] - B.MARGIN_DEG + 1e-6 or g in (70.0, -75.0)
    # j1 starts at +70: 10 deg margin to 80 leaves none upward, the room is downward (150 - 10)
    j1 = [m for m in moves if m["joint"] == "j1" and m["label"].endswith("out")]
    assert j1 and all(m["goal"][1] < 70.0 for m in j1)
    assert B.build_program("step", _plan(-12.0, 12.0, 1), [0.0], [1000], [5.0])[0] == []   # 2 deg of room: skipped
    assert B.build_program("step", _plan(-12.0, 12.0, 1), [0.0], [1000], [5.0])[1]


def test_rect_program_moves_all_joints_together():
    moves, _ = B.build_program("rect", _plan(), [0.0, 0.0, 0.0], [1000, 2000], [5.0], cycles=2, rect_amp=10.0)
    outs = [m for m in moves if m["label"].endswith("out")]
    assert len(outs) == 4 and all(all(abs(g) == 10.0 for g in m["goal"]) for m in outs)


def test_refuses_without_suspension_confirmation(bench):
    with pytest.raises(B.BenchError, match="hang free"):
        bench.start("step", [1000])
    assert not service.S.live["running"]


def test_refuses_a_flat_pack(bench):
    service.S.bus.voltage = 11.2
    with pytest.raises(B.BenchError, match="charge"):
        bench.start("rect", [1000], confirm_suspended=True)
    assert not service.S.live["running"]


def test_refuses_bad_speed(bench):
    with pytest.raises(B.BenchError, match="speeds"):
        bench.start("rect", [50], confirm_suspended=True)
    with pytest.raises(B.BenchError, match="speeds"):
        bench.start("rect", [9000], confirm_suspended=True)


def test_rect_run_logs_every_servo(bench):
    bench.start("rect", [3400], cycles=1, confirm_suspended=True)
    bench._thread.join(30)
    assert not bench._thread.is_alive()
    st = bench.status()
    assert st["stop_reason"] == "finished" and st["last_log"]
    z = np.load(bench.log_path(st["last_log"]))
    meta = json.loads(str(z["meta"]))
    assert z["pos"].shape == (len(z["t"]), 16) and z["volt"].shape == z["pos"].shape
    assert len(meta["ids"]) == 16 and meta["test"] == "rect" and not meta["fault"]
    assert float(z["volt"].min()) == pytest.approx(12.3, abs=0.01)
    assert np.all(np.diff(z["t"]) > 0)


def test_low_voltage_aborts_and_holds(bench):
    bench.start("rect", [1000], cycles=3, confirm_suspended=True)
    time.sleep(0.4)
    service.S.bus.voltage = 10.5                          # the pack sags under load
    bench._thread.join(10)
    st = bench.status()
    assert "pack voltage" in st["stop_reason"]
    assert service.S.live["phase"] == "error"
    assert st["last_log"]


def test_estop_releases_and_ends_run(bench, monkeypatch):
    released = []
    bus = service.S.bus
    orig = bus.torque_off
    monkeypatch.setattr(bus, "torque_off", lambda i: (released.append(i), orig(i))[1])
    bench.start("rect", [1000], cycles=3, confirm_suspended=True)
    time.sleep(0.3)
    service.ENGINE.stop()                                 # what POST /stop does
    bench._thread.join(10)
    assert "E-stop" in bench.status()["stop_reason"]
    assert set(released) >= set(IDS.values())


def test_endpoints(client):
    assert client.get("/bench/status").status_code == 200
    assert client.get("/bench/logs").json() == {"logs": []} or "logs" in client.get("/bench/logs").json()
    r = client.post("/bench/start", json={"test": "rect"})
    assert r.status_code == 400 and "hang free" in r.json()["detail"]


def test_a_single_bad_sample_does_not_abort(bench, monkeypatch):
    bus = service.S.bus
    orig = bus.sync_read_ext
    n = {"k": 0}

    def flaky(ids):
        n["k"] += 1
        out = orig(ids)
        if n["k"] == 10:                                   # one corrupted status block, as on the real bus
            i = ids[0]
            out[i] = (out[i][0], out[i][1], out[i][2], 3.0, 137)
        return out

    monkeypatch.setattr(bus, "sync_read_ext", flaky)
    bench.start("rect", [3400], cycles=1, confirm_suspended=True)
    bench._thread.join(30)
    assert bench.status()["stop_reason"] == "finished"


def test_sag_program_holds_growing_angles_then_returns():
    plan = _plan()
    moves, skipped = B.build_program("sag", plan, [0.0, 0.0, 0.0], [300], [30.0, 60.0, 90.0])
    j0 = [m for m in moves if m["joint"] == "j0"]
    assert [m["label"] for m in j0] == ["sag j0 30deg", "sag j0 60deg", "sag j0 70deg", "sag j0 back"]   # room 80 - 10
    assert [round(m["goal"][0]) for m in j0] == [30, 60, 70, 0]
    assert all(m["dwell"] >= B.SAG_SETTLE_S for m in j0[:3])


def test_sag_run_records_the_imu_at_each_move(bench):
    class Imu:
        def snapshot(self):
            return {"age_s": 0.01, "sample": {"ax": 1.0, "ay": 1000.0, "az": 0.0, "gx": 0.0, "gy": 0.0, "gz": 0.0}}
    bench.imu = Imu()
    bench.start("sag", [3400], amps=[10.0], joints=["left_knee_pitch"], confirm_suspended=True)
    bench._thread.join(30)
    z = np.load(bench.log_path(bench.status()["last_log"]))
    meta = json.loads(str(z["meta"]))
    assert meta["test"] == "sag" and len(meta["imu_at_move_end"]) == len(meta["moves"]) == 2


def test_hold_needs_its_own_confirmation_and_does_not_move(bench):
    with pytest.raises(B.BenchError, match="STANDING"):
        bench.start("hold", [300], confirm_suspended=True)               # the hanging confirmation is not enough
    moves, _ = B.build_program("hold", _plan(), [5.0, -3.0, 0.0], [300], [30.0], cycles=6)
    assert len(moves) == 1 and moves[0]["goal"] == [5.0, -3.0, 0.0] and moves[0]["dwell"] == 6.0
    bench.start("hold", [300], confirm_standing=True, hold_s=2.0)
    bench._thread.join(30)
    z = np.load(bench.log_path(bench.status()["last_log"]))
    assert json.loads(str(z["meta"]))["test"] == "hold" and np.ptp(z["goal"], axis=0).max() == 0


class _StandingImu:
    ay = 1000.0
    az = 0.0

    def snapshot(self):
        return {"age_s": 0.01, "sample": {"ax": 0.0, "ay": self.ay, "az": self.az, "gx": 0.0, "gy": 0.0, "gz": 0.0}}


def _leg_plan():
    return [{"joint": j, "id": i, "offset": 0.0, "lo": -80.0, "hi": 80.0} for j, i in IDS.items()]


def test_friction_program_splits_the_feet_and_keeps_the_soles_flat():
    plan = _leg_plan()
    names = [e["joint"] for e in plan]
    moves, skipped = B.build_program("friction", plan, [0.0] * 16, [100], [5.0], cycles=1)
    assert not skipped and len(moves) == 4 * round(B.FRICTION_STROKE_DEG / B.FRICTION_STEP_DEG)
    top = max(moves, key=lambda m: m["amp"])
    assert top["amp"] == B.FRICTION_STROKE_DEG
    for j, g in zip(names, top["goal"]):                 # only hips and ankles move, all by the same servo angle
        assert g == (B.FRICTION_STROKE_DEG if j in B.FRICTION_JOINTS else 0.0)
    steps = np.diff([m["amp"] for m in moves])
    assert np.abs(steps).max() == B.FRICTION_STEP_DEG    # no jump anywhere, back to zero at the end
    assert moves[-1]["amp"] == 0.0 and min(m["amp"] for m in moves) == -B.FRICTION_STROKE_DEG


def test_friction_program_refuses_without_room_on_both_sides():
    plan = [{**e, "hi": 12.0} if e["joint"] == "right_hip_pitch" else e for e in _leg_plan()]
    moves, skipped = B.build_program("friction", plan, [0.0] * 16, [100], [5.0], cycles=1)
    assert moves == [] and skipped[0]["joint"] == "right_hip_pitch"


def test_friction_refusals(bench):
    bench.imu = _StandingImu()
    for kw in ({}, {"confirm_standing": True, "confirm_suspended": True}):      # exactly one phase
        with pytest.raises(B.BenchError, match="runs twice"):
            bench.start("friction", [100], **kw)
    with pytest.raises(B.BenchError, match="cycles"):
        bench.start("friction", [100], cycles=9, confirm_standing=True)
    bench.imu = None
    with pytest.raises(B.BenchError, match="IMU"):
        bench.start("friction", [100], cycles=1, confirm_standing=True)
    bench.imu = _StandingImu()
    service.S.bus._pos[IDS["left_knee_pitch"]] = 2048 + 60                      # about 5 deg off centre
    with pytest.raises(B.BenchError, match="centre pose.*left_knee_pitch"):
        bench.start("friction", [100], cycles=1, confirm_standing=True)
    assert not service.S.live["running"]


def test_friction_run_logs_phase_and_imu(bench):
    bench.imu = _StandingImu()
    bench.start("friction", [100], cycles=1, confirm_suspended=True)
    bench.stop()
    bench._thread.join(10)
    z = np.load(bench.log_path(bench.status()["last_log"]))
    meta = json.loads(str(z["meta"]))
    assert meta["phase"] == "air" and z["imu"].shape == (len(z["t"]), 6)


def test_friction_high_load_eases_back_without_a_fault(bench, monkeypatch):
    bus = service.S.bus
    orig = bus.sync_read_ext
    monkeypatch.setattr(bus, "sync_read_ext", lambda ids: {i: (*orig(ids)[i][:2], 500, *orig(ids)[i][3:]) for i in ids})
    bench.imu = _StandingImu()
    bench.start("friction", [100], cycles=1, confirm_standing=True)
    bench._thread.join(10)
    assert "hip load 50 %" in bench.status()["stop_reason"]
    assert service.S.live["phase"] == "done"


def test_friction_tilt_aborts_and_holds(bench):
    imu = _StandingImu()
    bench.imu = imu
    bench.start("friction", [100], cycles=1, confirm_standing=True)
    time.sleep(0.2)
    imu.ay, imu.az = 700.0, 700.0                         # 45 deg
    bench._thread.join(10)
    assert "tilted" in bench.status()["stop_reason"] and service.S.live["phase"] == "error"


def _friction_log(tmp_path, phase, plus, minus):
    """A log whose hip load is `plus` during the positive stroke and `minus` during the negative one."""
    joints = list(B.FRICTION_HIPS)
    moves, move, load = [], [], []
    for sign, val in ((1.0, plus), (-1.0, minus)):
        for k in range(1, 25):
            moves.append({"label": f"friction 1 {sign:+.0f} out", "amp": sign * k * 0.25})
            move.append(len(moves) - 1)
            load.append([val, val])
    f = tmp_path / f"{phase}.npz"
    np.savez(f, move=np.array(move, float), load=np.array(load, float), meta=np.array(json.dumps(
        {"test": "friction", "phase": phase, "joints": joints, "moves": moves, "stop_reason": "finished"})))
    return np.load(f)


def test_friction_result_uses_the_stroke_difference_and_the_air_reference(tmp_path):
    # 0.562 Nm = 62.4 load units net, on top of a static offset (30) and a gearbox share (20) to be cancelled
    g = _friction_log(tmp_path, "ground", 30 + 20 + 62.4, 30 - 20 - 62.4)
    a = _friction_log(tmp_path, "air", 20, -20)
    r = B.friction_result(g, a)
    assert r["mu_sim_curve"] == pytest.approx(0.6, abs=0.01) and r["hips_agree"] and not r["calibrated"]
    assert not r["at_upper_limit"] and not r["at_lower_limit"]
    r = B.friction_result(_friction_log(tmp_path, "ground", 300, -300), a)
    assert r["at_upper_limit"] and r["mu_sim_curve"] == 1.1
    with pytest.raises(B.BenchError, match="phase 'ground'"):
        B.friction_result(a, a)
