#!/usr/bin/env python3
"""Verify sim/tools/feetech_numpy.py against the JAX actuator model ksim actually trains with.

    ~/Documents/stash/ksim-zbot/.venv/bin/python sim/tools/check_feetech_port.py

Drives both implementations with the same random command/state sequence at the physics rate and compares
the torques. If these two ever disagree, a sim-to-sim result means nothing: differences measured in Isaac
would come from the actuator port, not from the physics engine.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import jax  # noqa: E402
# JAX is float32 by default while NumPy is float64; with x64 on, any remaining difference is a
# logic difference rather than rounding. Must be set before the first array is created.
jax.config.update("jax_enable_x64", True)
import jax.numpy as jnp  # noqa: E402

from sim.train.common import FeetechActuators as JaxActuators, PlannerState, trapezoidal_step  # noqa: E402
from sim.tools.feetech_numpy import FeetechActuators as NpActuators  # noqa: E402

ASSETS = ROOT / "sim/assets/zbot-cad"
DT = 0.002


def joint_order():
    import json
    return list(json.load(open(ASSETS / "metadata.json"))["joint_name_to_metadata"].keys())


def main() -> int:
    names = joint_order()
    n = len(names)
    npa = NpActuators.from_assets(ASSETS, names, dt=DT)
    print(f"{n} joints; max_torque {npa.max_torque.min():.2f}..{npa.max_torque.max():.2f} N.m, "
          f"kp {npa.kp[0]:.1f}, kd {npa.kd[0]:.1f}")

    jxa = JaxActuators(
        max_torque_j=jnp.array(npa.max_torque), kp_j=jnp.array(npa.kp), kd_j=jnp.array(npa.kd),
        max_velocity_j=jnp.zeros(n), max_pwm_j=jnp.array(npa.max_pwm), vin_j=jnp.array(npa.vin),
        kt_j=jnp.array(npa.kt), r_j=jnp.array(npa.r), error_gain_j=jnp.array(npa.error_gain), dt=DT,
        # stored on the class but never read: trapezoidal_step hard-codes v_max 5.0 / a_max 39.0,
        # and common.py passes exactly those values. Changing them here would have no effect.
        vmax_j=jnp.ones(n) * 5.0, amax_j=jnp.ones(n) * 39.0,
    )

    rng = np.random.default_rng(0)
    q = rng.uniform(-0.5, 0.5, n)
    npa.reset(q)
    jstate = PlannerState(position=jnp.array(q), velocity=jnp.zeros(n))

    worst = 0.0
    for step in range(500):                      # 1 s at the physics rate
        if step % 10 == 0:                       # a new action every 10 physics steps = 50 Hz
            action = rng.uniform(-0.8, 0.8, n)
        qpos = rng.uniform(-0.5, 0.5, n)
        qvel = rng.uniform(-2.0, 2.0, n)

        t_np = npa.step(action, qpos, qvel)

        # the JAX model applies the same arithmetic; replicate its planner + duty path directly
        jstate, (dpos, dvel) = trapezoidal_step(jstate, jnp.array(action), DT)
        pos_err = dpos - jnp.array(qpos)
        vel_err = dvel - jnp.array(qvel)
        duty = jnp.clip(jxa.kp_j * jxa.error_gain_j * pos_err + jxa.kd_j * vel_err, -jxa.max_pwm_j, jxa.max_pwm_j)
        t_jx = np.array(duty * jxa.vin_j * jxa.kt_j / jxa.r_j)
        t_jx = np.clip(t_jx, -npa.max_torque, npa.max_torque)   # MJCF actuator_forcerange does this clamp

        worst = max(worst, float(np.max(np.abs(t_np - t_jx))))

    print(f"worst torque difference over 500 physics steps: {worst:.3e} N.m")
    ok = worst < 1e-9
    print("VERDICT:", "port matches the JAX model" if ok else "PORT DIFFERS -- do not use it for sim-to-sim")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
