"""Play and elasticity between servo output and link (sim/train/common.py, joint_compliance).

    ~/Documents/stash/ksim-zbot/.venv/bin/python -m pytest sim/tests/test_joint_compliance.py -q   (repo root)
"""
import sys
from pathlib import Path

import jax
import jax.numpy as jnp
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sim.train import common as C                          # noqa: E402

DT = 0.002
# STS3250 as in the training: kp 32 x error gain, kd 3, gain vin*kt/R
KP_DUTY, KD, GAIN, PWM = 32 * 0.16293639, 3.0, 12.1 * 1.0005874626213263 / 1.3890462492623645, 0.97
K_SERVO = KP_DUTY * GAIN                                   # ~45 Nm/rad, the bench sag test


def solve(p, q, b, k, prev=None, dz_prev=0.0, v=0.0):
    a = lambda x: jnp.array([float(x)])
    th, tau = C.solve_servo_output(a(p), a(v), a(q), a(q if prev is None else prev), a(dz_prev), a(b), a(k), 0.005,
                                   a(KP_DUTY), a(KD), a(GAIN), a(PWM), DT)
    return float(th[0]), float(tau[0])


def static(p, q, b, k, steps=4000):
    """link held at q, servo output settles. Setpoint speed 0: the servo's kd term then lets the output creep to its
    final angle with kd / kp_duty = 0.58 s (the old model does the same on the link), hence 8 s."""
    a = lambda x: jnp.array([float(x)])

    def step(carry, _):
        th, dz = carry
        th, tau = C.solve_servo_output(a(p), a(0.0), a(q), th, dz, a(b), a(k), 0.005, a(KP_DUTY), a(KD), a(GAIN),
                                       a(PWM), DT)
        return (th, C.dead_zone(th - q, a(b))), tau

    (th, _), tau = jax.lax.scan(step, (a(q), a(0.0)), None, length=steps)
    return float(th[0]), float(tau[-1, 0])


def test_stiff_spring_without_play_is_the_old_servo():
    for p in (0.01, 0.05, -0.2, 0.5):                       # 0.5 rad saturates the duty
        _, tau = static(p, 0.0, 0.0, 1e6)
        old = GAIN * np.clip(KP_DUTY * p, -PWM, PWM)
        assert tau == pytest.approx(old, rel=2e-3, abs=1e-4), p


def test_static_deflection_is_play_plus_series_springs():
    p, b, k = 0.10, np.radians(2.0), 10.0
    th, tau = static(p, 0.0, b, k)
    assert tau == pytest.approx((p - b) * K_SERVO * k / (K_SERVO + k), rel=1e-3)
    assert tau == pytest.approx(k * (th - b), rel=1e-3)     # the spring carries what the servo pushes


def test_inside_the_play_nothing_is_passed_on():
    th, tau = static(0.01, 0.0, np.radians(2.0), 30.0)
    assert abs(tau) < 1e-6 and th == pytest.approx(0.01, abs=1e-6)   # the servo reaches its setpoint, the link stays


def test_saturated_servo_cannot_push_harder_than_its_torque():
    th, tau = static(1.0, 0.0, 0.0, 20.0)
    assert tau == pytest.approx(GAIN * PWM, rel=1e-3)


def make_actuators(compliance):
    ones = jnp.ones(3)
    return C.ServoModelActuators(
        max_torque_j=ones * 8.7, kp_j=ones * 32.0, kd_j=ones * KD, max_velocity_j=ones * 9.0, max_pwm_j=ones * PWM,
        vin_j=ones * 12.1, kt_j=ones * 1.0005874626213263, r_j=ones * 1.3890462492623645, vmax_j=ones * 5.0,
        amax_j=ones * 39.0, error_gain_j=ones * 0.16293639, dt=DT, v_max_j=ones * 3.0, a_max_j=ones * 350.0,
        delay_steps_j=jnp.zeros(3, dtype=jnp.int32), compliance=compliance)


class Cfg:
    play_yaw_deg, play_roll_deg, play_pitch_deg = 2.0, 1.0, 0.5
    k_yaw, k_roll, k_pitch = "8,60", "60,400", "200,1000"
    compliance_damping_s, compliance_prob = 0.005, 1.0


NAMES = ["left_hip_yaw", "left_knee_pitch", "left_shoulder_pitch"]


class Data:
    def __init__(self, q, qd):
        self.qpos = jnp.concatenate([jnp.zeros(7), q])
        self.qvel = jnp.concatenate([jnp.zeros(6), qd])


def link_sim(act, target, inertia=0.06, seconds=1.0, seed=0):
    """three links of the given inertia (link + the 0.04 rotor armature the model puts on every joint), driven only by
    the actuator torque (no gravity), semi-implicit like MuJoCo"""
    q0 = jnp.zeros(3)

    def step(carry, key):
        q, qd, state = carry
        tau, state = act.get_stateful_ctrl(target, Data(q, qd), state, key)
        qd = qd + DT * (tau - 1.346 * qd) / inertia       # joint damping of the STS3250 sys-ID (mjcf)
        q = q + DT * qd
        return (q, qd, state), (q, state.theta_s, tau)

    keys = jax.random.split(jax.random.PRNGKey(seed), int(seconds / DT))
    (_, _, state), (q, th, tau) = jax.jit(lambda k: jax.lax.scan(step, (q0, q0, act.get_default_state(q0, q0)), k))(keys)
    return [(a, b, c) for a, b, c in zip(np.asarray(q), np.asarray(th), np.asarray(tau))], state


def test_ranges_per_joint_type():
    cr = C.compliance_ranges(Cfg, NAMES)
    assert np.allclose(np.degrees(cr.play_max), [2.0, 0.5, 0.0])
    assert np.allclose(cr.k_lo, [8, 200, 0]) and np.allclose(cr.k_hi, [60, 1000, 0])


def test_drawn_once_per_episode_within_the_ranges_and_arms_stay_direct():
    act = make_actuators(C.compliance_ranges(Cfg, NAMES))
    ks = []
    for seed in range(20):
        state = act.get_default_state(jnp.zeros(3), jnp.zeros(3))
        _, s1 = act.get_stateful_ctrl(jnp.zeros(3), Data(jnp.zeros(3), jnp.zeros(3)), state, jax.random.PRNGKey(seed))
        _, s2 = act.get_stateful_ctrl(jnp.zeros(3), Data(jnp.zeros(3), jnp.zeros(3)), s1, jax.random.PRNGKey(seed + 99))
        assert np.array_equal(s1.play_k, s2.play_k) and np.array_equal(s1.play_b, s2.play_b)
        k = np.asarray(s1.play_k)
        assert 8 <= k[0] <= 60 and 200 <= k[1] <= 1000 and k[2] == 0
        assert 0 <= float(s1.play_b[0]) <= np.radians(2.0) and float(s1.play_b[2]) == 0
        ks.append(k[0])
    assert np.ptp(ks) > 10                                   # it really varies between episodes


def test_without_compliance_the_torque_is_unchanged():
    target = jnp.array([0.2, -0.1, 0.3])
    a, _ = link_sim(make_actuators(None), target, seconds=0.3)
    cfg = Cfg(); cfg.compliance_prob = 0.0                    # compliance on, but this episode drew "stiff"
    b, _ = link_sim(make_actuators(C.compliance_ranges(cfg, NAMES)), target, seconds=0.3)
    assert np.allclose([x[2] for x in a], [x[2] for x in b], atol=1e-4)      # float32 rounding only


@pytest.mark.parametrize("seed", range(6))
def test_step_response_is_stable_and_settles(seed):
    act = make_actuators(C.compliance_ranges(Cfg, NAMES))
    target = jnp.array([0.3, -0.3, 0.3])
    out, state = link_sim(act, target, seconds=6.0, seed=seed)
    q, th, tau = (np.array([o[i] for o in out]) for i in range(3))
    assert np.isfinite(q).all() and np.abs(tau).max() <= GAIN * PWM + 1e-4
    # no load: link ends within the play of the target, servo output on it, nothing keeps swinging
    b = np.asarray(state.play_b)
    assert np.all(np.abs(q[-1] - np.asarray(target)) <= b + np.radians(0.3))
    assert np.allclose(th[-1], np.asarray(target), atol=np.radians(0.2))
    assert np.ptp(q[-100:], axis=0).max() < np.radians(0.2)


def test_the_policy_sees_the_servo_side():
    from sim.train.walking import encoder_side

    class PS:
        play_k = jnp.array([10.0, 0.0])
        theta_s = jnp.array([0.3, 0.3])

    class St:
        class physics_state:
            planner_state = PS

    assert np.allclose(encoder_side(St, jnp.array([0.1, 0.1]), "theta_s"), [0.3, 0.1])
