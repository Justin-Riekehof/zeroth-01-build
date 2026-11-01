"""Servo model of sim/train/common.py: setpoint planner, delay line, centre start pose.

    ~/Documents/stash/ksim-zbot/.venv/bin/python -m pytest sim/tests -q      (from the repo root)
"""
import sys
from pathlib import Path

import jax.numpy as jnp
import mujoco
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "sim" / "tools"))

import bench_fit                                           # noqa: E402
from sim.train import common as C                          # noqa: E402

DT = 0.004


def run(target, v_max, a_max, seconds, p0=0.0):
    p, v = jnp.array([p0]), jnp.array([0.0])
    tgt, vm, am = jnp.array([target]), jnp.array([v_max]), jnp.array([a_max])
    out = []
    for _ in range(int(seconds / DT)):
        p, v = C.servo_step(p, v, tgt, DT, vm, am)
        out.append((float(p[0]), float(v[0])))
    return np.array(out)


def test_planner_matches_the_trapezoid_of_the_fit():
    """the fit (sim/tools/bench_fit.py) and the training model must describe the same servo"""
    for v, a, d in ((3.07, 350.0, 0.52), (1.8, 8.0, 0.52), (3.07, 350.0, 0.09), (1.8, 8.0, 0.09)):
        traj = run(d, v, a, 1.5)
        t = (np.arange(len(traj)) + 1) * DT
        ref = bench_fit.trapezoid(t, d, v, a)
        assert np.abs(traj[:, 0] - ref).max() < np.radians(1.0), (v, a, d)


def test_speed_limit_and_no_overshoot_or_chatter():
    traj = run(0.5, 3.07, 350.0, 1.5)
    assert np.abs(traj[:, 1]).max() <= 3.07 + 1e-6
    assert traj[:, 0].max() <= 0.5 + np.radians(0.5)                   # discretisation: well under half a degree
    assert np.ptp(traj[-100:, 0]) < np.radians(0.01) and np.abs(traj[-100:, 1]).max() < 1e-3


def test_arm_is_slow_to_accelerate():
    """STS3215: ~8 rad/s^2 -> 0.22 s to reach its 1.8 rad/s"""
    traj = run(1.0, 1.8, 8.0, 0.2)
    assert traj[-1, 1] < 1.8 and traj[-1, 1] == pytest.approx(8.0 * 0.2, rel=0.05)


def make_actuators(delay_steps):
    n = len(delay_steps)
    ones = jnp.ones(n)
    return C.ServoModelActuators(
        max_torque_j=ones * 8.7, kp_j=ones * 16.0, kd_j=ones * 3.0, max_velocity_j=ones * 9.0, max_pwm_j=ones * 0.97,
        vin_j=ones * 12.0, kt_j=ones, r_j=ones * 1.4, vmax_j=ones * 5.0, amax_j=ones * 39.0, error_gain_j=ones * 0.16,
        dt=DT, v_max_j=ones * 3.0, a_max_j=ones * 350.0, delay_steps_j=jnp.array(delay_steps))


class Data:
    def __init__(self, n):
        self.qpos = jnp.zeros(7 + n)
        self.qvel = jnp.zeros(6 + n)


def test_command_delay_per_joint():
    import jax
    act = make_actuators([0, 5, 10])
    state = act.get_default_state(jnp.zeros(3), jnp.zeros(3))
    action = jnp.full(3, 0.3)
    first_move = [None, None, None]
    for k in range(1, 30):
        _, state = act.get_stateful_ctrl(action, Data(3), state, jax.random.PRNGKey(0))
        for j in range(3):
            if first_move[j] is None and float(state.position[j]) > 1e-6:
                first_move[j] = k
    assert first_move == [1, 6, 11]                          # joint j starts moving delay_steps[j] steps later


def test_random_delay_is_drawn_once_per_episode_and_shifts_every_joint():
    import jax
    shifts = set()
    for seed in range(40):
        act = make_actuators([5, 8])
        act.delay_rand_steps = 3
        act.buffer_len = 8 + 3 + 1
        state = act.get_default_state(jnp.zeros(2), jnp.zeros(2))
        first_move = [None, None]
        for k in range(1, 20):
            _, state = act.get_stateful_ctrl(jnp.full(2, 0.3), Data(2), state, jax.random.PRNGKey(seed * 100 + k))
            for j in range(2):
                if first_move[j] is None and float(state.position[j]) > 1e-6:
                    first_move[j] = k
        shift = first_move[0] - 6
        assert first_move[1] - 9 == shift                     # one shift for the whole bus, kept for the episode
        assert -3 <= shift <= 3
        shifts.add(shift)
    assert len(shifts) >= 5                                   # and it really varies between episodes


def test_no_random_delay_by_default():
    act = make_actuators([2, 4])
    assert act.delay_rand_steps == 0 and act.buffer_len == 5


def test_action_history_observation_keeps_the_older_actions_newest_first():
    import jax
    from types import SimpleNamespace
    from sim.train.walking import ActionHistoryObservation
    act = make_actuators([1, 1])
    act.action_history, act.phys_per_ctrl = 4, 3
    state = act.get_default_state(jnp.full(2, 0.5), jnp.zeros(2))         # episode starts in a pose: first action 0.5
    obs = ActionHistoryObservation(steps=3)
    seen = lambda st: np.asarray(obs.observe(SimpleNamespace(physics_state=SimpleNamespace(planner_state=st)),
                                             jax.random.PRNGKey(0))).reshape(3, 2)[:, 0]
    np.testing.assert_allclose(seen(state), [0.5, 0.5, 0.5])
    for k in range(1, 6):                                                 # control step k applies action k
        for _ in range(3):                                                # 3 physics steps per control step
            _, state = act.get_stateful_ctrl(jnp.full(2, float(k)), Data(2), state, jax.random.PRNGKey(k))
        if k == 1:
            np.testing.assert_allclose(seen(state), [0.5, 0.5, 0.5])      # a(t-1) = 1 is the last action, not here
    np.testing.assert_allclose(np.asarray(state.actions)[:, 0], [5, 4, 3, 2])
    np.testing.assert_allclose(seen(state), [4, 3, 2])                    # a(t-2), a(t-3), a(t-4)


def test_plain_planner_state_from_the_render_path_is_upgraded():
    import jax
    from ksim.types import PlannerState
    act = make_actuators([2, 2])
    ctrl, state = act.get_stateful_ctrl(jnp.zeros(2), Data(2), PlannerState(jnp.zeros(2), jnp.zeros(2)),
                                        jax.random.PRNGKey(0))
    assert isinstance(state, C.ServoState) and ctrl.shape == (2,)


def test_centre_start_pose_stands_on_both_feet():
    spec = mujoco.MjSpec.from_file(str(ROOT / "sim" / "assets" / "zbot-cad" / "robot.mjcf"))
    spec.worldbody.add_geom(name="floor", type=mujoco.mjtGeom.mjGEOM_PLANE, size=[1, 1, 0.1])
    m = spec.compile()
    zero_ref = m.qpos0[7:].copy()
    text = "left_hip_pitch=18.7,right_hip_pitch=-16.1"
    C.center_start_qpos(m, C.parse_center_pose(text))
    pitch = 2 * np.degrees(np.arcsin(m.qpos0[5]))
    assert pitch == pytest.approx(17.4, abs=1.0)                  # static analysis on 2026-10-22
    np.testing.assert_array_equal(m.qpos0[7:], zero_ref)          # joint zero untouched (qpos - qpos0 is the kinematics)
    reset = C.CenterPoseReset.from_model(m, text)
    d = mujoco.MjData(m)
    d.qpos[:] = m.qpos0
    d = reset(d, 1.0, None)
    assert d.qpos[m.joint("left_hip_pitch").qposadr[0]] == pytest.approx(np.radians(18.7))
    assert d.qpos[m.joint("right_hip_pitch").qposadr[0]] == pytest.approx(np.radians(-16.1))
    mujoco.mj_forward(m, d)
    low = [d.geom_xpos[g][2] - float(np.abs(d.geom_xmat[g].reshape(3, 3)[2]) @ m.geom_size[g])
           for g in range(m.ngeom) if "Foot_collision" in (mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, g) or "")]
    assert len(low) == 2 and all(abs(z - 0.001) < 2e-3 for z in low)     # both soles on the floor


def test_servo_state_survives_jit_and_scan():
    """training runs get_stateful_ctrl inside jax.lax.scan: the carry must keep its structure"""
    import jax
    act = make_actuators([2, 3])

    def body(carry, i):
        state = carry
        action = jnp.where(i < 40, 0.4, -0.4) * jnp.ones(2)
        ctrl, state = act.get_stateful_ctrl(action, Data(2), state, jax.random.PRNGKey(0))
        return state, state.position

    state0 = act.get_default_state(jnp.zeros(2), jnp.zeros(2))
    final, positions = jax.jit(lambda s: jax.lax.scan(body, s, jnp.arange(120)))(state0)
    assert isinstance(final, C.ServoState) and positions.shape == (120, 2)
    assert float(positions[:, 0].max()) <= 0.4 + 1e-2 and float(positions[-1, 0]) < 0.0       # moved out and came back


def test_centre_reset_builds_from_the_mjx_model_used_in_training():
    """get_resets() gets an mjx.Model in training: it has no names and no .joint()"""
    from mujoco import mjx
    spec = mujoco.MjSpec.from_file(str(ROOT / "sim" / "assets" / "zbot-cad" / "robot.mjcf"))
    spec.worldbody.add_geom(name="floor", type=mujoco.mjtGeom.mjGEOM_PLANE, size=[1, 1, 0.1])
    m = spec.compile()
    text = "left_hip_pitch=18.7,right_hip_pitch=-16.1"
    a = C.CenterPoseReset.from_model(m, text)
    b = C.CenterPoseReset.from_model(mjx.put_model(m), text)
    assert a.joint_qpos == b.joint_qpos and max(a.joint_qpos) == pytest.approx(np.radians(18.7))


# ---- reward terms for calm, hardware-safe walking (sim/train/walking.py) -------------------------------------------

def _traj(action, qpos_joints):
    from types import SimpleNamespace
    action = jnp.asarray(action, dtype=jnp.float32)
    q = jnp.concatenate([jnp.zeros(action.shape[:-1] + (7,)), jnp.asarray(qpos_joints, dtype=jnp.float32)], axis=-1)
    return SimpleNamespace(action=action, qpos=q, done=jnp.zeros(action.shape[:-1], dtype=bool))


def test_calm_penalties():
    from sim.train import walking as W
    n = 3
    a0 = np.zeros((4, n))
    gap = W.TargetGapPenalty(scale=-1.0)
    r, _ = gap(_traj(a0 + 0.5, a0), None)
    assert float(r[0]) == pytest.approx(0.5)                              # target 0.5 rad ahead of every joint
    r, _ = gap(_traj(a0, a0), None)
    assert float(r[0]) == 0.0
    sat = W.ActionSaturationPenalty(scale=-1.0)
    assert float(sat(_traj(a0 + 0.9, a0), None)[0][0]) == 0.0              # at the threshold
    assert float(sat(_traj(a0 + 1.0, a0), None)[0][0]) == pytest.approx(1.0)
    lim = W.JointLimitPenalty(lower=(-1.0,) * n, upper=(0.1,) * n, margin=0.1, scale=-1.0)
    assert float(lim(_traj(a0, a0 - 0.5), None)[0][0]) == 0.0              # far from both limits
    assert float(lim(_traj(a0, a0 + 0.1), None)[0][0]) == pytest.approx(1.0)  # on the upper limit
    assert float(lim(_traj(a0, a0 + 0.05), None)[0][0]) == pytest.approx(0.25)  # half-way into the band


def test_joint_limit_penalty_reads_mjx_ranges():
    from mujoco import mjx
    from sim.train import walking as W
    spec = mujoco.MjSpec.from_file(str(ROOT / "sim" / "assets" / "zbot-cad" / "robot.mjcf"))
    spec.worldbody.add_geom(name="floor", type=mujoco.mjtGeom.mjGEOM_PLANE, size=[1, 1, 0.1])
    pen = W.JointLimitPenalty.from_model(mjx.put_model(spec.compile()), 5.0, -1.0)
    assert len(pen.lower) == 16 and all(lo < hi for lo, hi in zip(pen.lower, pen.upper))


def test_real_limits_clamp_in_the_actuator_and_the_target_penalty():
    import jax
    from mujoco import mjx
    from sim.train import walking as W
    spec = mujoco.MjSpec.from_file(str(ROOT / "sim" / "assets" / "zbot-cad" / "robot.mjcf"))
    spec.worldbody.add_geom(name="floor", type=mujoco.mjtGeom.mjGEOM_PLANE, size=[1, 1, 0.1])
    m = spec.compile()
    lo, hi = C.real_joint_limits(m)
    lo2, hi2 = C.real_joint_limits(mjx.put_model(m))
    np.testing.assert_allclose(lo, lo2)
    names = [mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, i) for i in range(1, m.njnt)]
    j = names.index("left_hip_yaw")
    assert np.degrees(hi[j]) == pytest.approx(5.0, abs=0.01) and np.degrees(lo[j]) == pytest.approx(-90.0, abs=0.1)
    assert np.degrees(hi[names.index("right_hip_yaw")]) == pytest.approx(90.0, abs=0.1)
    pen = W.TargetLimitPenalty(lower=tuple(lo), upper=tuple(hi), scale=-1.0)
    a = np.zeros((2, 16)); a[:, j] = hi[j] + 0.3                          # 0.3 rad beyond the left hip-yaw limit
    r, _ = pen(_traj(a, np.zeros((2, 16))), None)
    assert float(r[0]) == pytest.approx(0.3 / 16, rel=1e-3)                # linear in the excess
    # the actuator: a target far beyond the limit is clamped before the servo sees it
    n = 16
    act = make_actuators([0] * n)
    act = C.ServoModelActuators(**{**act.__dict__, "max_torque_j": act.max_torque_j} ) if False else act
    act.lo_j, act.hi_j = jnp.array(lo), jnp.array(hi)
    state = act.get_default_state(jnp.zeros(n), jnp.zeros(n))
    action = jnp.zeros(n).at[j].set(1.0)                                 # 57 deg, the limit is +5 deg
    for _ in range(200):
        _, state = act.get_stateful_ctrl(action, Data(n), state, jax.random.PRNGKey(0))
    assert float(state.position[j]) == pytest.approx(float(hi[j]), abs=1e-3)


def test_speed_limit_penalty():
    from types import SimpleNamespace
    from mujoco import mjx
    from sim.train import walking as W
    spec = mujoco.MjSpec.from_file(str(ROOT / "sim" / "assets" / "zbot-cad" / "robot.mjcf"))
    spec.worldbody.add_geom(name="floor", type=mujoco.mjtGeom.mjGEOM_PLANE, size=[1, 1, 0.1])
    m = spec.compile()
    pen = W.JointSpeedLimitPenalty.from_model(mjx.put_model(m), 3.0, 1.8, -1.0)
    names = [mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, i) for i in range(1, m.njnt)]
    assert pen.v_limit[names.index("left_elbow_yaw")] == pytest.approx(1.8)
    assert pen.v_limit[names.index("left_knee_pitch")] == pytest.approx(3.0)
    qvel = jnp.zeros((2, 6 + 16))
    traj = SimpleNamespace(qvel=qvel, done=jnp.zeros(2, dtype=bool))
    assert float(pen(traj, None)[0][0]) == 0.0
    knee = names.index("left_knee_pitch")
    traj.qvel = qvel.at[:, 6 + knee].set(3.6)                           # 20 % over the leg limit, one joint of 16
    assert float(pen(traj, None)[0][0]) == pytest.approx(0.2 / 16, rel=1e-4)
    traj.qvel = qvel.at[:, 6 + knee].set(-2.5)                          # slower than the limit, either direction
    assert float(pen(traj, None)[0][0]) == 0.0


def test_speed_penalty_buffer():
    from types import SimpleNamespace
    from mujoco import mjx
    from sim.train import walking as W
    spec = mujoco.MjSpec.from_file(str(ROOT / "sim" / "assets" / "zbot-cad" / "robot.mjcf"))
    spec.worldbody.add_geom(name="floor", type=mujoco.mjtGeom.mjGEOM_PLANE, size=[1, 1, 0.1])
    m = spec.compile()
    names = [mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, i) for i in range(1, m.njnt)]
    knee = names.index("left_knee_pitch")
    pen = W.JointSpeedLimitPenalty.from_model(mjx.put_model(m), 3.0 * 0.7, 1.8 * 0.7, -1.0)     # buffer 70 %
    assert pen.v_limit[knee] == pytest.approx(2.1)
    traj = SimpleNamespace(qvel=jnp.zeros((2, 22)).at[:, 6 + knee].set(2.0), done=jnp.zeros(2, dtype=bool))
    assert float(pen(traj, None)[0][0]) == 0.0                  # 2.0 < 2.1: inside the buffer, free
    traj.qvel = jnp.zeros((2, 22)).at[:, 6 + knee].set(2.52)    # 20 % over the buffer edge
    assert float(pen(traj, None)[0][0]) == pytest.approx(0.2 / 16, rel=1e-4)


def test_command_rate_limiter_before_the_delay_line():
    import jax
    n = 2
    act = make_actuators([0, 0])
    act.cmd_rate_j = jnp.array([1.0, 2.0])                  # rad/s the target may move
    state = act.get_default_state(jnp.zeros(n), jnp.zeros(n))
    action = jnp.array([0.5, 0.5])                          # a jump the limiter must spread out
    for k in range(50):                                     # 50 x 4 ms = 0.2 s
        _, state = act.get_stateful_ctrl(action, Data(n), state, jax.random.PRNGKey(0))
    np.testing.assert_allclose(np.asarray(state.last_cmd), [0.2, 0.4], atol=1e-5)
    for k in range(200):
        _, state = act.get_stateful_ctrl(action, Data(n), state, jax.random.PRNGKey(0))
    np.testing.assert_allclose(np.asarray(state.last_cmd), [0.5, 0.5], atol=1e-6)   # then it arrives and stays


def test_limit_margins_never_forbid_the_zero_pose():
    from sim.train import walking as W
    m = W.limit_margins(np.radians([-3.0, -90.0, -45.0]), np.radians([90.0, 5.0, 90.0]), np.radians(5.0))
    np.testing.assert_allclose(np.degrees(m), [1.5, 2.5, 5.0])


def test_chatter_penalties():
    from sim.train import walking as W
    n = 2
    step = (0.04, 0.02)
    lim = W.ActionStepLimitPenalty(step=step, scale=-1.0)
    smooth = np.cumsum(np.full((6, n), 0.01), axis=0)                       # 0.01 per step: inside both steps
    assert float(lim(_traj(smooth[None], smooth[None] * 0), None)[0][0, 3]) == 0.0
    chatter = np.tile(np.array([[0.0, 0.0], [0.1, 0.1]]), (3, 1))           # +-0.1 every step: 2.5x / 5x the step
    r = lim(_traj(chatter[None], chatter[None] * 0), None)[0][0]
    assert float(r[3]) == pytest.approx(((0.1 - 0.04) / 0.04 + (0.1 - 0.02) / 0.02) / 2)
    jerk = W.ActionJerkPenalty(scale=-1.0)
    assert float(jerk(_traj(smooth[None], smooth[None] * 0), None)[0][0, 4]) == pytest.approx(0.0, abs=1e-9)   # constant slope
    assert float(jerk(_traj(chatter[None], chatter[None] * 0), None)[0][0, 4]) == pytest.approx((0.2 ** 2))    # a-2a'+a'' = 0.2


def test_action_filter_matches_one_pi_step_per_control_step():
    import jax
    n = 1
    act = make_actuators([0])
    alpha, substeps = 0.2, 10
    act.filter_alpha_phys = 1.0 - (1.0 - alpha) ** (1.0 / substeps)
    state = act.get_default_state(jnp.zeros(n), jnp.zeros(n))
    for _ in range(substeps):                                    # one control step with a constant action of 1.0
        _, state = act.get_stateful_ctrl(jnp.ones(n), Data(n), state, jax.random.PRNGKey(0))
    assert float(state.filt[0]) == pytest.approx(alpha, rel=1e-5)   # = what the Pi computes once: 0 + 0.2 * (1 - 0)
    zig = 0.0                                                    # a +-1 zig-zag every control step comes through damped
    peak = 0.0
    for k in range(40):
        for _ in range(substeps):
            _, state = act.get_stateful_ctrl(jnp.full(n, 1.0 if k % 2 else -1.0), Data(n), state, jax.random.PRNGKey(0))
        if k > 20:
            peak = max(peak, abs(float(state.filt[0])))
    assert peak < 0.15                                           # alpha/(2-alpha) = 0.11 for the per-step filter


def _gait_traj(contact, x=None, sin=None):
    from types import SimpleNamespace
    T = contact.shape[0]
    pos = np.zeros((T, 2, 3)) if x is None else np.stack([x, np.zeros_like(x), np.zeros_like(x)], axis=-1)
    ph = np.zeros((T, 4)) if sin is None else np.concatenate([np.zeros((T, 2)), sin], axis=-1)
    return SimpleNamespace(obs={"feet_position_observation": jnp.asarray(pos.reshape(T, 6), jnp.float32),
                                "feet_contact_observation": jnp.asarray(contact, jnp.float32),
                                "timestep_phase_observation": jnp.asarray(ph, jnp.float32)},
                           done=jnp.zeros(T, bool))


def test_stride_reward_counts_real_steps_only():
    from sim.train import walking as W
    T = 40
    c = np.ones((T, 2)); x = np.zeros((T, 2))
    c[5:20, 0] = 0                                     # left foot: 15 steps = 0.3 s swing, travels 0.06 m
    x[:, 0] = np.where(np.arange(T) >= 5, np.minimum((np.arange(T) - 5) * 0.004, 0.06), 0)
    c[25:27, 1] = 0                                    # right foot: 2-step flicker, travels 0.1 m (must not count)
    x[:, 1] = np.where(np.arange(T) >= 25, 0.1, 0)
    r = np.asarray(W.StrideLengthReward(target=0.08, min_swing=0.2, scale=1.0)(_gait_traj(c, x), None)[0])
    assert r[20] == pytest.approx(0.75) and r.sum() == pytest.approx(0.75)


def test_gait_clock_reward():
    from sim.train import walking as W
    T = 4
    sin = np.array([[0.9, -0.9]] * T)                  # left should swing, right should stand
    good = np.tile([0.0, 1.0], (T, 1)); bad = np.tile([1.0, 0.0], (T, 1))
    rew = W.GaitClockReward(scale=1.0)
    assert float(rew(_gait_traj(good, sin=sin), None)[0][0]) == pytest.approx(1.0)
    assert float(rew(_gait_traj(bad, sin=sin), None)[0][0]) == pytest.approx(0.0)
    assert float(rew(_gait_traj(good, sin=np.zeros((T, 2))), None)[0][0]) == pytest.approx(0.0)   # transition: no count


def test_joint_accel_penalty():
    from types import SimpleNamespace
    from sim.train import walking as W
    qv = np.zeros((5, 6 + 2)); qv[2, 6] = 1.0                         # one joint jumps 1 rad/s for one step
    r = np.asarray(W.JointAccelerationPenalty(scale=-1.0)(SimpleNamespace(qvel=jnp.asarray(qv), done=jnp.zeros(5, bool)), None)[0])
    np.testing.assert_allclose(r, [0, 0, 0.5, 0.5, 0], atol=1e-6)      # (+1)^2 and (-1)^2, mean over 2 joints


def test_dense_swing_reward_rises_with_the_swing_length():
    from types import SimpleNamespace
    from sim.train.walking import SwingDurationReward
    T = 40
    contact = np.ones((T, 2), np.float32)
    contact[5:7, 0] = 0          # 0.04 s hop of the left foot
    contact[20:30, 0] = 0        # 0.20 s swing
    traj = SimpleNamespace(obs={"feet_contact_observation": jnp.asarray(contact)}, done=jnp.zeros(T, bool))
    dense = np.asarray(SwingDurationReward(t_min=0.2, t_max=0.6, dense=True, scale=1.0)(traj, None)[0])
    step = np.asarray(SwingDurationReward(t_min=0.2, t_max=0.6, scale=1.0)(traj, None)[0])
    np.testing.assert_allclose(dense[5:7], -0.6, atol=1e-6)      # 2 * 0.04 / 0.2 - 1
    np.testing.assert_allclose(dense[20:30], 1.0, atol=1e-6)
    np.testing.assert_allclose(step[5:7], -1.0)                  # the old step: no difference between 0.04 and 0.18 s
    contact[5:14, 0] = 0                                         # the hop grows to 0.18 s: dense pays more, step does not
    traj = SimpleNamespace(obs={"feet_contact_observation": jnp.asarray(contact)}, done=jnp.zeros(T, bool))
    assert np.asarray(SwingDurationReward(t_min=0.2, t_max=0.6, dense=True, scale=1.0)(traj, None)[0])[5] > -0.6


def test_foot_flat_penalty_is_the_tilt_of_feet_on_the_floor():
    from types import SimpleNamespace
    from sim.train.walking import FootFlatPenalty
    a = np.radians(10.0)
    flat = [1.0, 0.0, 0.0, 0.0]
    rolled = [np.cos(a / 2), np.sin(a / 2), 0.0, 0.0]                 # 10 deg about x
    xquat = np.zeros((3, 4, 4)); xquat[..., 0] = 1.0
    xquat[0, 2], xquat[0, 3] = flat, rolled
    xquat[1, 2], xquat[1, 3] = rolled, rolled
    xquat[2, 2], xquat[2, 3] = rolled, rolled
    contact = np.array([[1, 1], [1, 1], [0, 0]], np.float32)           # last step: both feet in the air
    traj = SimpleNamespace(xquat=jnp.asarray(xquat), obs={"feet_contact_observation": jnp.asarray(contact)},
                           done=jnp.zeros(3, bool))
    r = np.asarray(FootFlatPenalty(left_body=2, right_body=3, scale=-1.0)(traj, None)[0])
    np.testing.assert_allclose(r, [a, 2 * a, 0.0], atol=1e-5)
    dz = np.asarray(FootFlatPenalty(left_body=2, right_body=3, deadzone=np.radians(5.0), scale=-1.0)(traj, None)[0])
    np.testing.assert_allclose(dz, [a - np.radians(5), 2 * (a - np.radians(5)), 0.0], atol=1e-5)


def test_new_model_has_chamfered_soles_on_the_floor():
    from mujoco_scenes.mjcf import load_mjmodel
    m = load_mjmodel(str(ROOT / "sim" / "assets" / "zbot-cad" / "robot.mjcf"), scene="smooth")   # adds the floor
    for side in ("Left", "Right"):
        names = [f"{side}_Foot_{s}" for s in ("collision_box", "chamfer_neg", "chamfer_pos")]
        ids = [mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, n) for n in names]
        assert min(ids) >= 0
        assert m.geom_size[ids[0]][1] < 0.012                         # flat strip ~1.2-1.7 cm wide, not 5.8 cm
        box_c, box_h = m.geom_pos[ids[0]], m.geom_size[ids[0]]
        sole = box_c[2] - box_h[2]
        for i in ids[1:]:                                               # capsules on the outer chamfer edges
            assert m.geom_type[i] == mujoco.mjtGeom.mjGEOM_CAPSULE
            out = abs(m.geom_pos[i][1] - box_c[1]) - box_h[1]           # how far beyond the flat strip
            rise = m.geom_pos[i][2] - m.geom_size[i][0] - sole
            assert 0.008 < out < 0.016 and 10 < np.degrees(np.arctan2(rise, out)) < 20, (out, rise)


def test_tracking_on_the_mean_velocity_ignores_the_sway():
    from types import SimpleNamespace
    from sim.train.walking import LinearVelocityTrackingReward, moving_average
    T = 200
    t = np.arange(T) * 0.02
    vel = np.stack([0.05 + 0.10 * np.sin(2 * np.pi * 1.25 * t), 0.15 * np.sin(2 * np.pi * 1.25 * t)], 1)   # +-sway at 1.25 Hz
    np.testing.assert_allclose(np.asarray(moving_average(jnp.asarray(vel), 40))[40:-40], [[0.05, 0.0]] * (T - 80), atol=1e-3)
    def traj(cmd):
        return SimpleNamespace(obs={"sensor_observation_base_link_vel": jnp.asarray(np.c_[vel, np.zeros(T)], jnp.float32)},
                               command={"linear_velocity_command": jnp.full((T, 2), 0.0).at[:, 0].set(cmd)})
    win = LinearVelocityTrackingReward(error_scale=0.03, norm="l1", window_steps=40, scale=1.0)
    inst = LinearVelocityTrackingReward(error_scale=0.03, norm="l1", scale=1.0)
    right, wrong = float(win(traj(0.05), None)[0][40:-40].mean()), float(win(traj(0.0), None)[0][40:-40].mean())
    assert right > 0.9 and wrong < 0.3                                    # the window tells the speeds apart
    assert float(inst(traj(0.05), None)[0].mean()) < 0.2                  # the instantaneous kernel reads ~0 even on target


def test_stride_reward_can_require_a_forward_command():
    from types import SimpleNamespace
    from sim.train.walking import StrideLengthReward
    T = 40
    contact = np.ones((T, 2), np.float32); contact[10:25, 0] = 0          # 0.3 s swing of the left foot
    pos = np.zeros((T, 6), np.float32); pos[15:, 0] = 0.05                # it lands 5 cm further
    for cmd, expected in ((0.05, 1.0), (0.0, 0.0)):
        tr = SimpleNamespace(obs={"feet_position_observation": jnp.asarray(pos), "feet_contact_observation": jnp.asarray(contact)},
                             command={"linear_velocity_command": jnp.full((T, 2), 0.0).at[:, 0].set(cmd)}, done=jnp.zeros(T, bool))
        r = np.asarray(StrideLengthReward(target=0.04, needs_command=True, scale=1.0)(tr, None)[0])
        assert r.sum() == expected


def test_forward_progress_pays_up_to_the_command_only():
    from types import SimpleNamespace
    from sim.train.walking import ForwardProgressReward
    T = 120
    def mean_r(v, cmd):
        tr = SimpleNamespace(obs={"sensor_observation_base_link_vel": jnp.full((T, 3), 0.0).at[:, 0].set(v)},
                             command={"linear_velocity_command": jnp.full((T, 2), 0.0).at[:, 0].set(cmd)}, done=jnp.zeros(T, bool))
        return float(ForwardProgressReward(window_steps=40, scale=1.0)(tr, None)[0].mean())
    assert mean_r(0.0, 0.04) == 0.0 and abs(mean_r(0.02, 0.04) - 0.5) < 1e-4
    assert abs(mean_r(0.04, 0.04) - 1.0) < 1e-4 and abs(mean_r(0.08, 0.04) - 1.0) < 1e-4       # no pay for overspeed
    assert abs(mean_r(-0.08, 0.04) + 1.0) < 1e-4 and mean_r(0.08, 0.0) == 0.0                   # backwards costs, command 0 pays nothing
