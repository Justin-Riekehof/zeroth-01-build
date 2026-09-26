#!/usr/bin/env python3
"""Engine-independent NumPy port of the Feetech actuator model that ksim trains with.

The point of this file is the sim-to-sim comparison: a policy trained in MuJoCo/MJX is only worth
re-testing in another physics engine if that engine drives the joints the same way. A plain PD position
controller is NOT the same thing -- these servos are modelled down to the duty cycle and the winding:

    planner  : a trapezoidal velocity profile (v_max 5 rad/s, a_max 39 rad/s^2) turns the commanded
               position into a reachable (position, velocity) pair
    duty     : raw = kp * error_gain * pos_error + kd * vel_error, clipped to +-max_pwm
    torque   : volts = duty * vin, torque = volts * kt / R, clamped to +-max_torque

Verbatim port of `FeetechActuators.get_stateful_ctrl` and `trapezoidal_step` in sim/train/common.py
(vendored from ksim-zbot). sim/tools/check_feetech_port.py verifies this against the JAX original.

IMPORTANT: it is stepped at the PHYSICS rate (dt = 0.002 s in our config, i.e. 500 Hz), not at the 50 Hz
control rate -- the action is held constant across the ten physics steps of one policy step, but the
planner advances every one of them.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

V_MAX = 5.0
A_MAX = 39.0


def trapezoidal_step(position, velocity, target_position, dt):
    """One planner step. Returns (new_position, new_velocity)."""
    position_error = target_position - position
    direction = np.sign(position_error)
    stopping_distance = (velocity ** 2) / (2 * A_MAX)
    should_accelerate = np.abs(position_error) > stopping_distance
    acceleration = np.where(should_accelerate, direction * A_MAX, -direction * A_MAX)
    new_velocity = velocity + acceleration * dt
    new_velocity = np.clip(new_velocity, -V_MAX, V_MAX)
    new_velocity = np.where(direction * new_velocity < 0, 0.0, new_velocity)
    new_position = position + new_velocity * dt
    return new_position, new_velocity


class FeetechActuators:
    """Per-joint arrays, all in MuJoCo joint order (which is also the policy's action order)."""

    def __init__(self, max_torque, kp, kd, max_pwm, vin, kt, r, error_gain, dt):
        self.max_torque = np.asarray(max_torque, float)
        self.kp = np.asarray(kp, float)
        self.kd = np.asarray(kd, float)
        self.max_pwm = np.asarray(max_pwm, float)
        self.vin = np.asarray(vin, float)
        self.kt = np.asarray(kt, float)
        self.r = np.asarray(r, float)
        self.error_gain = np.asarray(error_gain, float)
        self.dt = float(dt)
        self.position = np.zeros_like(self.kp)
        self.velocity = np.zeros_like(self.kp)

    def reset(self, position, velocity=None):
        self.position = np.array(position, float)
        self.velocity = np.zeros_like(self.position) if velocity is None else np.array(velocity, float)

    def step(self, action, qpos, qvel):
        """action: commanded joint positions (rad). qpos/qvel: current joint state. -> torque per joint."""
        self.position, self.velocity = trapezoidal_step(self.position, self.velocity, np.asarray(action, float), self.dt)
        pos_error = self.position - np.asarray(qpos, float)
        vel_error = self.velocity - np.asarray(qvel, float)
        raw_duty = self.kp * self.error_gain * pos_error + self.kd * vel_error
        duty = np.clip(raw_duty, -self.max_pwm, self.max_pwm)
        torque = duty * self.vin * self.kt / self.r
        return np.clip(torque, -self.max_torque, self.max_torque)

    @classmethod
    def from_assets(cls, assets_dir, joint_order, dt=0.002):
        """Build from sim/assets/<model>/{metadata.json,actuators/*.json} for the given joint order."""
        assets = Path(assets_dir)
        meta = json.load(open(assets / "metadata.json"))["joint_name_to_metadata"]
        cache, cols = {}, {k: [] for k in
                            ("max_torque", "kp", "kd", "max_pwm", "vin", "kt", "r", "error_gain")}
        for name in joint_order:
            jm = meta[name]
            atype = jm["actuator_type"]
            if atype not in cache:
                cache[atype] = json.load(open(assets / "actuators" / f"{atype}.json"))
            p = cache[atype]
            cols["max_torque"].append(p["max_torque"])
            cols["max_pwm"].append(p["max_pwm"])
            cols["vin"].append(p["vin"])
            cols["kt"].append(p["kt"])
            cols["r"].append(p["R"])
            cols["error_gain"].append(p["error_gain"])
            cols["kp"].append(float(jm["kp"]))
            cols["kd"].append(float(jm["kd"]))
        return cls(dt=dt, **{k: np.array(v) for k, v in cols.items()})
