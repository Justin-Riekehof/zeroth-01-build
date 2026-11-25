"""Walking task for this Z-Bot build ("Pixel", 16 DoF, 5-DoF legs).

Vendored from ksim-zbot (kscalelabs/ksim-zbot, MIT) `ksim_zbot/zbot2/walking/walking.py`.
Local changes:
  * Network/observation sizes for 16 actuated joints (upstream: 20, zbot-6dof-feet).
  * Mass randomization body renamed to this model's torso (Z_BOT2_MASTER_BODY_SKELETON).
  * Imports the vendored common module (asset paths -> sim/assets/zbot-pixel).

Run from the repo root with the ksim venv active:
  python -m sim.train.walking                      # train
  python -m sim.train.walking run_environment=True # visualize/rollout without training
"""

import logging
from dataclasses import dataclass
from typing import Collection, Self

import os
import attrs
import math
import distrax
import equinox as eqx
import jax
import jax.numpy as jnp
import numpy as np
import ksim
from ksim.utils.mujoco import get_site_data_idx_from_name
import optax
import xax
from jax.scipy.spatial.transform import Rotation
from jaxtyping import Array, PRNGKeyArray, PyTree
from ksim import Reward
from ksim.curriculum import Curriculum
from ksim.observation import ContactObservation, ObservationInput
from ksim.types import PhysicsState, Trajectory
from ksim.utils.mujoco import (
    get_qpos_data_idxs_by_name,
    get_site_data_idx_from_name,
    slice_update,
    update_data_field,
)
from xax.utils.types.frozen_dict import FrozenDict

try:
    from .common import CenterPoseReset, ZbotTask, ZbotTaskConfig, real_joint_limits
except ImportError:  # allow `python sim/train/walking.py` as well as `python -m sim.train.walking`
    import sys
    from pathlib import Path

    sys.path.append(str(Path(__file__).resolve().parent))
    from common import CenterPoseReset, ZbotTask, ZbotTaskConfig, real_joint_limits  # type: ignore[no-redef]

logger = logging.getLogger(__name__)


def _fix_collect_dataset() -> None:
    """ksim 0.0.31 RLTask.collect_dataset writes trajectories[0::batch_size]: only env 0 of every batch, and env 0 keeps
    running across batches. Every "16 episodes x 5 s" evaluation with dataset_num_batches=16 was ONE environment over
    80 s with a single start (found 21.11.2026). Patched to write every environment; evaluations use one batch of 16."""
    import inspect
    import textwrap

    import ksim.task.rl as rl

    if getattr(rl.RLTask.collect_dataset, "_zbot_fixed", False):
        return
    src = textwrap.dedent(inspect.getsource(rl.RLTask.collect_dataset))
    bad = "range(0, len(trajectories.done), self.batch_size)"
    if bad not in src:
        raise RuntimeError("ksim collect_dataset changed: check whether the env-0-only bug is still there")
    ns: dict = {}
    exec(compile(src.replace(bad, "range(len(trajectories.done))"), rl.__file__, "exec"), rl.__dict__, ns)
    ns["collect_dataset"]._zbot_fixed = True
    rl.RLTask.collect_dataset = ns["collect_dataset"]


_fix_collect_dataset()

# Constants for history handling
HISTORY_LENGTH = 0
SINGLE_STEP_HISTORY_SIZE = 0

# 16 actuated joints: 2x(3 arm) + 2x(5 leg), no grippers -- matches the real servo count.
# Observation components:
# timestep_phase_4: 4
# joint_pos_n: 16
# joint_vel_n: 16
# imu_acc_3: 3
# imu_gyro_3: 3
# last_action_n: 16
OBS_SIZE = 4 + 16 + 16 + 3 + 3 + 16  # = 58
# Command size: lin_vel_cmd_2 + ang_vel_cmd_1 + gait_freq_cmd_1
CMD_SIZE = 2 + 1 + 1
NUM_INPUTS = OBS_SIZE + CMD_SIZE  # 58 + 4 = 62
NUM_CRITIC_INPUTS = NUM_INPUTS + 2 + 2 + 6 + 3 + 3 + 4 + 3 + 3 + 16 + 1  # = 105
NUM_OUTPUTS = 16


@attrs.define(frozen=True, kw_only=True)
class FootFrictionRandomizer(ksim.PhysicsRandomizer):
    """Random sliding friction of the foot contacts. Those are explicit <pair>s in robot.mjcf, and a pair's friction
    overrides the geoms': ksim.FloorFrictionRandomizer (geom_friction) never reached the feet, so every policy up to
    servo_tpu5 trained on one value (1.1 with the TPU soles)."""

    mu_lower: float = attrs.field()
    mu_upper: float = attrs.field()
    log_uniform: bool = attrs.field(default=False)
    # torsional friction (m) of the pairs, uniform per environment; only acts with foot_condim >= 4. None = keep the model's
    torsion_lower: float | None = attrs.field(default=None)
    torsion_upper: float | None = attrs.field(default=None)

    def __call__(self, model: ksim.PhysicsModel, rng: jax.Array) -> dict[str, jax.Array]:
        if model.npair == 0:
            raise ValueError("The model has no contact pairs: nothing to randomize.")
        mu_rng, tor_rng = jax.random.split(rng)
        if self.log_uniform:
            mu = jnp.exp(jax.random.uniform(mu_rng, minval=jnp.log(self.mu_lower), maxval=jnp.log(self.mu_upper)))
        else:
            mu = jax.random.uniform(mu_rng, minval=self.mu_lower, maxval=self.mu_upper)
        fr = jnp.asarray(model.pair_friction).at[:, :2].set(mu)                          # both tangential directions
        if self.torsion_lower is not None and self.torsion_upper is not None:
            fr = fr.at[:, 2].set(jax.random.uniform(tor_rng, minval=self.torsion_lower, maxval=self.torsion_upper))
        return {"pair_friction": fr}


@attrs.define(frozen=True, kw_only=True)
class ImuTiltRandomizer(ksim.PhysicsRandomizer):
    """Constant tilt of the IMU site per environment, up to max_deg about a random axis in the chip's x/z plane (level
    when the head is upright). On the robot the IMU stands at 9-13 deg forward where the model says 17.2 (2026-10-31/11-01,
    head mount and leg compliance not separated): the policy must not rely on the absolute angle."""

    site_id: int = attrs.field()
    max_deg: float = attrs.field()

    @classmethod
    def from_site_name(cls, model: ksim.PhysicsModel, name: str, max_deg: float) -> "ImuTiltRandomizer":
        return cls(site_id=get_site_data_idx_from_name(model, name), max_deg=max_deg)

    def __call__(self, model: ksim.PhysicsModel, rng: jax.Array) -> dict[str, jax.Array]:
        rng_axis, rng_angle = jax.random.split(rng)
        heading = jax.random.uniform(rng_axis, minval=0.0, maxval=2 * jnp.pi)
        half = 0.5 * jnp.radians(self.max_deg) * jax.random.uniform(rng_angle, minval=-1.0, maxval=1.0)
        w2, x2, y2, z2 = jnp.cos(half), jnp.sin(half) * jnp.cos(heading), 0.0, jnp.sin(half) * jnp.sin(heading)
        site_quat = jnp.asarray(model.site_quat)
        w1, x1, y1, z1 = site_quat[self.site_id]
        tilted = jnp.stack([w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2, w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
                            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2, w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2])
        return {"site_quat": site_quat.at[self.site_id].set(tilted)}


@attrs.define(frozen=True)
class LinearVelocityCommand(ksim.Command):
    """Command to move the robot in a straight line.

    By convention, X is forward and Y is left. The switching probability is the
    probability of resampling the command at each step. The zero probability is
    the probability of the command being zero - this can be used to turn off
    any command.
    """

    x_range: tuple[float, float] = attrs.field()
    y_range: tuple[float, float] = attrs.field()
    x_zero_prob: float = attrs.field(default=0.0)
    y_zero_prob: float = attrs.field(default=0.0)
    switch_prob: float = attrs.field(default=0.0)
    vis_height: float = attrs.field(default=1.0)
    vis_scale: float = attrs.field(default=0.05)

    def initial_command(self, physics_data: ksim.PhysicsData, curriculum_level: Array, rng: PRNGKeyArray) -> Array:
        rng_x, rng_y, rng_zero_x, rng_zero_y = jax.random.split(rng, 4)
        (xmin, xmax), (ymin, ymax) = self.x_range, self.y_range
        x = jax.random.uniform(rng_x, (1,), minval=xmin, maxval=xmax)
        y = jax.random.uniform(rng_y, (1,), minval=ymin, maxval=ymax)
        x_zero_mask = jax.random.bernoulli(rng_zero_x, self.x_zero_prob)
        y_zero_mask = jax.random.bernoulli(rng_zero_y, self.y_zero_prob)
        return jnp.concatenate(
            [
                jnp.where(x_zero_mask, 0.0, x),
                jnp.where(y_zero_mask, 0.0, y),
            ]
        )

    def __call__(
        self, prev_command: Array, physics_data: ksim.PhysicsData, curriculum_level: Array, rng: PRNGKeyArray
    ) -> Array:
        rng_a, rng_b = jax.random.split(rng)
        switch_mask = jax.random.bernoulli(rng_a, self.switch_prob)
        new_commands = self.initial_command(physics_data, curriculum_level, rng_b)
        return jnp.where(switch_mask, new_commands, prev_command)

    def get_markers(self) -> Collection[ksim.vis.Marker]:
        return []


@attrs.define(frozen=True)
class AngularVelocityCommand(ksim.Command):
    """Command to turn the robot."""

    scale: float = attrs.field()
    index: int | str | None = attrs.field(default=None)
    zero_prob: float = attrs.field(default=0.0)
    switch_prob: float = attrs.field(default=0.0)

    def initial_command(
        self,
        physics_data: ksim.PhysicsData,
        curriculum_level: Array,
        rng: PRNGKeyArray,
    ) -> Array:
        """Returns (1,) array with angular velocity."""
        rng_a, rng_b = jax.random.split(rng)
        zero_mask = jax.random.bernoulli(rng_a, self.zero_prob)
        cmd = jax.random.uniform(rng_b, (1,), minval=-self.scale, maxval=self.scale)
        return jnp.where(zero_mask, jnp.zeros_like(cmd), cmd)

    def __call__(
        self,
        prev_command: Array,
        physics_data: ksim.PhysicsData,
        curriculum_level: Array,
        rng: PRNGKeyArray,
    ) -> Array:
        rng_a, rng_b = jax.random.split(rng)
        switch_mask = jax.random.bernoulli(rng_a, self.switch_prob)
        new_commands = self.initial_command(physics_data, curriculum_level, rng_b)
        return jnp.where(switch_mask, new_commands, prev_command)

    def get_name(self) -> str:
        return f"{super().get_name()}{'' if self.index is None else f'_{self.index}'}"


@attrs.define(frozen=True)
class GaitFrequencyCommand(ksim.Command):
    """Command to set the gait frequency of the robot."""

    gait_freq_lower: float = attrs.field(default=1.2)
    gait_freq_upper: float = attrs.field(default=1.5)

    def initial_command(
        self,
        physics_data: ksim.PhysicsData,
        curriculum_level: Array,
        rng: PRNGKeyArray,
    ) -> Array:
        """Returns (1,) array with gait frequency."""
        return jax.random.uniform(rng, (1,), minval=self.gait_freq_lower, maxval=self.gait_freq_upper)

    def __call__(
        self,
        prev_command: Array,
        physics_data: ksim.PhysicsData,
        curriculum_level: Array,
        rng: PRNGKeyArray,
    ) -> Array:
        return prev_command


@attrs.define(frozen=True)
class JointPositionObservation(ksim.Observation):
    default_targets: tuple[float, ...] = attrs.field(default=(0.0,) * NUM_OUTPUTS)
    noise: float = attrs.field(default=0.0)

    def observe(self, state: ksim.ObservationInput, rng: PRNGKeyArray) -> Array:
        qpos = encoder_side(state, state.physics_state.data.qpos[7:], "theta_s")  # (N,)
        diff = qpos - jnp.array(self.default_targets)
        return diff


def encoder_side(state: ksim.ObservationInput, link: Array, field: str) -> Array:
    """What the servo encoders read: with joint_compliance the servo output (planner state), else the link itself."""
    ps = state.physics_state.planner_state
    if not hasattr(ps, "play_k"):
        return link
    return jnp.where(ps.play_k > 0, getattr(ps, field), link)


@attrs.define(frozen=True, kw_only=True)
class JointVelocityObservation(ksim.Observation):
    """ksim.JointVelocityObservation, but from the servo side when the servo model has play/elasticity."""

    def observe(self, state: ksim.ObservationInput, rng: PRNGKeyArray) -> Array:
        return encoder_side(state, state.physics_state.data.qvel[6:], "omega_s")


@attrs.define(frozen=True)
class ProjectedGravityObservation(ksim.Observation):
    noise: float = attrs.field(default=0.0)

    def observe(self, state: ksim.ObservationInput, rng: PRNGKeyArray) -> Array:
        gvec = xax.get_projected_gravity_vector_from_quat(state.physics_state.data.qpos[3:7])
        return gvec


@attrs.define(frozen=True)
class TrueHeightObservation(ksim.Observation):
    """Observation of the true height of the body."""

    def observe(self, state: ksim.ObservationInput, rng: PRNGKeyArray) -> Array:
        return jnp.atleast_1d(state.physics_state.data.qpos[2])


@attrs.define(frozen=True)
class HistoryObservation(ksim.Observation):
    def observe(self, state: ObservationInput, rng: PRNGKeyArray) -> Array:
        return jnp.zeros(0, dtype=jnp.float32)


@attrs.define(frozen=True)
class LastActionObservation(ksim.Observation):
    noise: float = attrs.field(default=0.0)

    def observe(self, state: ObservationInput, rng: PRNGKeyArray) -> Array:
        return state.physics_state.most_recent_action

    def add_noise(self, observation: Array, curriculum_level: Array, rng: PRNGKeyArray) -> Array:
        return observation + jax.random.normal(rng, observation.shape) * self.noise


@attrs.define(frozen=True, kw_only=True)
class ActionHistoryObservation(ksim.Observation):
    """The actions BEFORE the last one: [a(t-2), ..., a(t-1-steps)], flattened (last_action_observation is a(t-1)).

    With the servo delay plus the servo's own lag (~85 ms = 4 control steps) these commands are still on their way
    when the policy decides; without them it cannot tell "already commanded, still arriving" from "not commanded"
    and keeps pushing (the 5-6 Hz jitter). Kept in the servo model's planner state (ServoState.actions: this ksim's
    observation carry is not batched per env); at an episode start they all equal the first last action. The Pi
    builds the same vector (ObsBuilder, action_history in policy_meta.json)."""

    steps: int = attrs.field(default=3)

    def observe(self, state: ObservationInput, rng: PRNGKeyArray) -> Array:
        ps = state.physics_state.planner_state
        if not hasattr(ps, "actions"):         # plain-MuJoCo render path, before the servo model upgraded its state
            return jnp.tile(state.physics_state.most_recent_action, self.steps)
        return ps.actions[1:self.steps + 1].reshape(-1)


@attrs.define(frozen=True, kw_only=True)
class TimestepPhaseObservation(ksim.TimestepObservation):
    """Observation of the phase of the timestep."""

    ctrl_dt: float = attrs.field(default=0.02)

    def observe(self, state: ksim.ObservationInput, rng: PRNGKeyArray) -> Array:
        gait_freq = state.commands["gait_frequency_command"]
        timestep = super().observe(state, rng)
        steps = timestep / self.ctrl_dt
        phase_dt = 2 * jnp.pi * gait_freq * self.ctrl_dt
        start_phase = jnp.array([0, jnp.pi])  # trotting gait
        phase = start_phase + steps * phase_dt
        phase = jnp.fmod(phase + jnp.pi, 2 * jnp.pi) - jnp.pi

        return jnp.array([jnp.cos(phase), jnp.sin(phase)]).flatten()


@attrs.define(frozen=True, kw_only=True)
class NaiveVelocityReward(ksim.Reward):
    """Raw forward speed. Uncapped it pays for any overspeed, and the bootstrap stage then bakes in one fixed fast gait
    (servo_rubber3-7: ~8 cm/s at every command of 3-5 cm/s, later re-weighting never removed it). cap > 0 clips the
    speed at cap x command."""

    cap: float = attrs.field(default=0.0)

    def __call__(self, trajectory: ksim.Trajectory, reward_carry: PyTree) -> tuple[Array, PyTree]:
        vx = trajectory.qvel[..., 0]
        if self.cap > 0:
            return jnp.minimum(vx, self.cap * trajectory.command["linear_velocity_command"][..., 0]), None
        return vx.clip(max=5.0), None


@attrs.define(frozen=True, kw_only=True)
class OrientationPenalty(ksim.Reward):
    """Penalizes deviation from upright orientation using the upvector approach.

    Rotates a unit up vector [0,0,1] by the current quaternion
    and penalizes any x,y components, which should be zero if perfectly upright.
    """

    scale: float = attrs.field()

    def __call__(self, trajectory: ksim.Trajectory, reward_carry: xax.FrozenDict[str, PyTree]) -> tuple[Array, None]:
        quat = trajectory.qpos[..., 3:7]
        up = jnp.array([0.0, 0.0, 1.0])
        rot_up = Rotation(quat).apply(up)
        orientation_penalty = jnp.sum(jnp.square(rot_up[..., :2]), axis=-1)
        return orientation_penalty, None


@attrs.define(frozen=True, kw_only=True)
class TargetedJointDeviationPenalty(ksim.Reward):
    """Penalty for joint deviations."""

    norm: xax.NormType = attrs.field(default="l2")
    joint_targets: tuple[float, ...] = attrs.field()

    def __call__(self, trajectory: ksim.Trajectory, reward_carry: PyTree) -> tuple[Array, PyTree]:
        diff = trajectory.qpos[..., 7:] - jnp.array(self.joint_targets)
        return xax.get_norm(diff, self.norm).sum(axis=-1), None


@attrs.define(frozen=True, kw_only=True)
class HeightReward(ksim.Reward):
    """Reward for how high the robot is."""

    height_target: float = attrs.field(default=1.4)

    def __call__(self, trajectory: ksim.Trajectory, reward_carry: PyTree) -> tuple[Array, PyTree]:
        if trajectory.qpos.ndim > 1:
            height = trajectory.qpos[:, 2]
        else:
            # 1D case for run_environment mode
            height = trajectory.qpos[2]
        reward = jnp.exp(-jnp.abs(height - self.height_target) * 10)
        return reward, None


@attrs.define(frozen=True)
class DHJointVelocityObservation(ksim.Observation):
    noise: float = attrs.field(default=0.0)

    def observe(self, state: ObservationInput, rng: PRNGKeyArray) -> Array:
        qvel = state.physics_state.data.qvel[6:]  # (N,)
        return qvel

    def add_noise(self, observation: Array, curriculum_level: Array, rng: PRNGKeyArray) -> Array:
        return observation + jax.random.normal(rng, observation.shape) * self.noise


@attrs.define(frozen=True)
class DHJointPositionObservation(ksim.Observation):
    noise: float = attrs.field(default=0.0)

    def observe(self, state: ObservationInput, rng: PRNGKeyArray) -> Array:
        qpos = state.physics_state.data.qpos[7:]  # (N,)
        return qpos

    def add_noise(self, observation: Array, curriculum_level: Array, rng: PRNGKeyArray) -> Array:
        return observation + jax.random.normal(rng, observation.shape) * self.noise


@attrs.define(frozen=True, kw_only=True)
class DHForwardReward(ksim.Reward):
    """Incentives forward movement."""

    def __call__(self, trajectory: ksim.Trajectory, reward_carry: PyTree) -> tuple[Array, PyTree]:
        # Take just the x velocity component
        if trajectory.qvel.ndim > 1:
            x_delta = -jnp.clip(trajectory.qvel[..., 1], -1.0, 1.0)
        else:
            x_delta = -jnp.clip(trajectory.qvel[1], -1.0, 1.0)
        return x_delta, None


@attrs.define(frozen=True, kw_only=True)
class DHControlPenalty(ksim.Reward):
    """Legacy default humanoid control cost that penalizes squared action magnitude."""

    def __call__(self, trajectory: ksim.Trajectory, reward_carry: PyTree) -> tuple[Array, PyTree]:
        return jnp.sum(jnp.square(trajectory.action), axis=-1), None


@attrs.define(frozen=True, kw_only=True)
class DHHealthyReward(ksim.Reward):
    """Legacy default humanoid healthy reward that gives binary reward based on height."""

    healthy_z_lower: float = attrs.field(default=0.2)
    healthy_z_upper: float = attrs.field(default=0.5)

    def __call__(self, trajectory: ksim.Trajectory, reward_carry: PyTree) -> tuple[Array, PyTree]:
        height = trajectory.qpos[..., 2]
        is_healthy = jnp.where(height < self.healthy_z_lower, 0.0, 1.0)
        is_healthy = jnp.where(height > self.healthy_z_upper, 0.0, is_healthy)
        return is_healthy, None


def moving_average(x: Array, n: int) -> Array:
    """Centred mean over n steps along the time axis of (T, d) data; shorter windows at the ends of the rollout.
    With real steps the body sways: instantaneous vx +-10, vy +-15 cm/s around a mean of 7 and 0.4 cm/s (servo_tpu1), so
    a tracking kernel on the instantaneous velocity reads ~0 whatever the mean speed is."""
    kernel = jnp.ones(n)
    sums = jax.vmap(lambda c: jnp.convolve(c, kernel, mode="same"), in_axes=1, out_axes=1)(x)
    counts = jnp.convolve(jnp.ones(x.shape[0]), kernel, mode="same")
    return sums / counts[:, None]


@attrs.define(frozen=True, kw_only=True)
class ForwardProgressReward(ksim.Reward):
    """Forward speed (mean over one step) as a share of the command, -1..1, 0 at command 0: more speed pays up to the
    command and no further. The tracking kernel cannot tell walking from stepping on the spot (0.14 vs 0.15, the body
    sways); this does (+0.82 vs +0.03), without paying for overspeed or walking on at command 0 like naive_velocity."""

    window_steps: int = attrs.field(default=40)
    linvel_obs_name: str = attrs.field(default="sensor_observation_base_link_vel")
    # Capped at the command, overspeed still pays in full and keeps every window safely at 1 (servo_rubber7/10: a sharp
    # tracking kernel left this as the only speed signal, the policy went to 2x command). peak: falls again above it.
    # servo_rubber11: a sharp peak (zero at 2x) made it shuffle at 0.3-0.7x; peak_tol keeps the full reward up to (1 + tol)x
    peak: bool = attrs.field(default=False)
    peak_tol: float = attrs.field(default=0.0)

    def __call__(self, trajectory: ksim.Trajectory, reward_carry: PyTree) -> tuple[Array, PyTree]:
        vx = moving_average(trajectory.obs[self.linvel_obs_name][..., :2], self.window_steps)[..., 0]
        cmd = trajectory.command["linear_velocity_command"][..., 0]
        ratio = vx / jnp.maximum(cmd, 1e-3)
        progress = jnp.clip(jnp.minimum(ratio, 2.0 + self.peak_tol - ratio) if self.peak else ratio, -1.0, 1.0)
        return jnp.where((cmd > 1e-3) & ~trajectory.done, progress, 0.0), None


@attrs.define(frozen=True, kw_only=True)
class LinearVelocityTrackingReward(ksim.Reward):
    """Reward for tracking the linear velocity."""

    error_scale: float = attrs.field(default=0.25)
    linvel_obs_name: str = attrs.field(default="sensor_observation_base_link_vel")
    command_name_x: str = attrs.field(default="linear_velocity_command_x")
    command_name_y: str = attrs.field(default="linear_velocity_command_y")
    norm: xax.NormType = attrs.field(default="l2")
    window_steps: int = attrs.field(default=1)

    def __call__(self, trajectory: ksim.Trajectory, reward_carry: PyTree) -> tuple[Array, PyTree]:
        if self.linvel_obs_name not in trajectory.obs:
            raise ValueError(f"Observation {self.linvel_obs_name} not found; add it as an observation in your task.")
        cmd = trajectory.command
        if self.command_name_x in cmd:
            command = jnp.concatenate([cmd[self.command_name_x], cmd[self.command_name_y]], axis=-1)
        else:  # LinearVelocityCommand emits one 2-vector named after the class
            command = cmd["linear_velocity_command"][..., :2]
        vel = trajectory.obs[self.linvel_obs_name][..., :2]
        if self.window_steps > 1:
            vel = moving_average(vel, self.window_steps)
        lin_vel_error = xax.get_norm(command - vel, self.norm).sum(axis=-1)
        return jnp.exp(-lin_vel_error / self.error_scale), None


@attrs.define(frozen=True, kw_only=True)
class HipDeviationPenalty(ksim.Reward):
    """Penalty for hip joint deviations."""

    norm: xax.NormType = attrs.field(default="l2")
    hip_indices: tuple[int, ...] = attrs.field()
    joint_targets: tuple[float, ...] = attrs.field()

    def __call__(self, trajectory: ksim.Trajectory, reward_carry: PyTree) -> tuple[Array, PyTree]:
        # NOTE - fix that
        diff = (
            trajectory.qpos[..., jnp.array(self.hip_indices) + 7]
            - jnp.array(self.joint_targets)[jnp.array(self.hip_indices)]
        )
        return xax.get_norm(diff, self.norm).sum(axis=-1), None

    @classmethod
    def create(
        cls,
        physics_model: ksim.PhysicsModel,
        hip_names: tuple[str, ...],
        joint_targets: tuple[float, ...],
        scale: float = -1.0,
    ) -> Self:
        """Create a sensor observation from a physics model."""
        mappings = get_qpos_data_idxs_by_name(physics_model)
        hip_indices = tuple([int(mappings[name][0]) - 7 for name in hip_names])
        return cls(
            hip_indices=hip_indices,
            joint_targets=joint_targets,
            scale=scale,
        )


@attrs.define(frozen=True, kw_only=True)
class JointDeviationPenalty(ksim.Reward):
    """Penalty for joint deviations."""

    norm: xax.NormType = attrs.field(default="l2")
    joint_targets: tuple[float, ...] = attrs.field(default=(0.0,) * NUM_OUTPUTS)
    joint_weights: tuple[float, ...] = attrs.field(default=(1.0,) * NUM_OUTPUTS)

    def __call__(self, trajectory: ksim.Trajectory, reward_carry: xax.FrozenDict[str, PyTree]) -> tuple[Array, None]:
        diff = trajectory.qpos[..., 7:] - jnp.array(self.joint_targets)
        cost = jnp.square(diff) * jnp.array(self.joint_weights)
        reward_value = jnp.sum(cost, axis=-1)
        return reward_value, None

    @classmethod
    def create(
        cls,
        physics_model: ksim.PhysicsModel,
        scale: float = -1.0,
        *,
        joint_targets: tuple[float, ...],
        joint_weights: tuple[float, ...] | None = None,
    ) -> Self:
        if joint_weights is None:
            joint_weights = tuple([1.0] * len(joint_targets))

        return cls(
            scale=scale,
            joint_targets=joint_targets,
            joint_weights=joint_weights,
        )


@attrs.define(frozen=True, kw_only=True)
class FeetContactPenalty(Reward):
    """Penalizes the robot when foot contact is detected.

    This reward reads the precomputed contact observation from the trajectory. The
    observation is expected to be a boolean array of shape (2,) in a single-environment
    rollout or (num_envs, 2) in batched training mode. The reward reduces along the
    last axis to yield a scalar per environment.
    """

    # The key under which the contact observation is stored.
    contact_obs_key: str = attrs.field(default="contact_observation_feet")
    # Use the reward object's scale field to set the penalty magnitude.
    scale: float = attrs.field(default=-1.0)

    def __call__(self, trajectory: Trajectory, reward_carry: PyTree) -> tuple[jnp.ndarray, PyTree]:
        target_shape = trajectory.done.shape  # Expected shape: () for a single env or (num_envs,) in batched mode.
        contact_flag = trajectory.obs[self.contact_obs_key]

        # If running in batched mode, ensure contact_flag has one extra dimension at the end.
        if target_shape and contact_flag.ndim < (len(target_shape) + 1):
            contact_flag = jnp.broadcast_to(contact_flag, target_shape + (contact_flag.shape[-1],))

        # For single-environment mode (target_shape == ()), simply reduce the (2,) vector.
        if not target_shape:
            is_contact = jnp.any(contact_flag)
        else:
            # Now contact_flag is (batch, 2). Reduce along the last axis.
            is_contact = jnp.any(contact_flag, axis=-1)

        # Convert the Boolean to float: 1.0 if any contact, 0.0 otherwise.
        contact_value = jnp.where(is_contact, 1.0, 0.0)
        return contact_value, None

    @property
    def reward_name(self) -> str:
        return "feet_contact_penalty"


@attrs.define(frozen=True, kw_only=True)
class FeetSlipPenalty(ksim.Reward):
    """Penalises horizontal foot velocity while that foot is in contact (skating / sliding gaits)."""

    ctrl_dt: float = attrs.field(default=0.02)
    pos_obs: str = attrs.field(default="feet_position_observation")
    contact_obs: str = attrs.field(default="feet_contact_observation")

    def __call__(self, trajectory: ksim.Trajectory, reward_carry: PyTree) -> tuple[Array, PyTree]:
        pos = trajectory.obs[self.pos_obs]                       # (..., 6) = left xyz, right xyz
        pos = pos.reshape(pos.shape[:-1] + (2, 3))
        contact = trajectory.obs[self.contact_obs].reshape(pos.shape[:-1])   # (..., 2)
        vel = (pos[1:] - pos[:-1]) / self.ctrl_dt
        vel = jnp.concatenate([vel, vel[-1:]], axis=0)
        slip = jnp.linalg.norm(vel[..., :2], axis=-1) * contact  # (..., 2)  m/s while touching the floor
        penalty = jnp.clip(slip, max=2.0).sum(axis=-1)
        return jnp.where(trajectory.done, 0.0, penalty), None


@attrs.define(frozen=True, kw_only=True)
class SingleSupportReward(ksim.Reward):
    """+1 while exactly one foot touches the floor: rewards a stepping gait over shuffling/hopping."""

    contact_obs: str = attrs.field(default="feet_contact_observation")

    def __call__(self, trajectory: ksim.Trajectory, reward_carry: PyTree) -> tuple[Array, PyTree]:
        contact = trajectory.obs[self.contact_obs]
        n = contact.reshape(contact.shape[:-1] + (-1,)).sum(axis=-1)
        return jnp.where(n == 1, 1.0, 0.0), None


@attrs.define(frozen=True, kw_only=True)
class SwingDurationReward(ksim.Reward):
    """Per-step reward for a foot that is in a swing phase of a proper length (stepping instead of shuffling).

    Every step of a swing (foot not in contact) receives +1 if that swing lasts t_min..t_max seconds,
    -1 if it is shorter (chattering / shuffling), 0 if longer (foot held up, hopping) or when the other
    foot is off the ground too (flight). The duration is known because the whole rollout is available.
    """

    ctrl_dt: float = attrs.field(default=0.02)
    t_min: float = attrs.field(default=0.15)
    t_max: float = attrs.field(default=0.45)
    dense: bool = attrs.field(default=False)
    contact_obs: str = attrs.field(default="feet_contact_observation")

    def __call__(self, trajectory: ksim.Trajectory, reward_carry: PyTree) -> tuple[Array, PyTree]:
        """dense=True: every swing step earns 2 * min(duration / t_min, 1) - 1 (0.04 s: -0.7, half of t_min: 0, t_min
        and longer: +1) instead of the step at t_min. servo_ctrl_v7 (2026-10-28) never made a 0.25 s swing, so the
        +1 never fired and only the -1 for short swings was felt: it hopped faster (7.8/s) and walked slower."""
        contact = trajectory.obs[self.contact_obs] > 0.5       # (T, 2)
        swing = ~contact

        def fwd(carry: Array, s: Array) -> tuple[Array, Array]:  # run length of the swing so far
            carry = jnp.where(s, carry + 1, 0)
            return carry, carry

        _, up = jax.lax.scan(fwd, jnp.zeros(contact.shape[-1], dtype=jnp.int32), swing)

        def bwd(carry: Array, x: tuple[Array, Array]) -> tuple[Array, Array]:  # total run length
            up_t, s_t = x
            carry = jnp.where(s_t, jnp.where(carry == 0, up_t, carry), 0)
            return carry, carry

        _, total = jax.lax.scan(bwd, jnp.zeros(contact.shape[-1], dtype=jnp.int32), (up, swing), reverse=True)
        dur = total.astype(jnp.float32) * self.ctrl_dt
        good = swing & (dur >= self.t_min) & (dur <= self.t_max)
        short = swing & (dur < self.t_min)
        other_down = contact[..., ::-1]
        if self.dense:
            ramp = 2.0 * jnp.clip(dur / self.t_min, 0.0, 1.0) - 1.0
            r = (jnp.where(good | short, ramp, 0.0) * other_down).sum(axis=-1)
            return jnp.where(trajectory.done, 0.0, r), None
        r = ((good.astype(jnp.float32) - short.astype(jnp.float32)) * other_down).sum(axis=-1)
        return jnp.where(trajectory.done, 0.0, r), None


@attrs.define(frozen=True, kw_only=True)
class ContactFlipPenalty(ksim.Reward):
    """Number of foot contact changes per step (chattering feet)."""

    contact_obs: str = attrs.field(default="feet_contact_observation")

    def __call__(self, trajectory: ksim.Trajectory, reward_carry: PyTree) -> tuple[Array, PyTree]:
        c = trajectory.obs[self.contact_obs]
        flips = jnp.abs(c[1:] - c[:-1]).sum(axis=-1)
        flips = jnp.concatenate([jnp.zeros_like(flips[:1]), flips], axis=0)
        return jnp.where(trajectory.done, 0.0, flips), None


@attrs.define(frozen=True, kw_only=True)
class FootFlatPenalty(ksim.Reward):
    """Tilt (rad) of each foot that touches the floor, summed over the feet: the sole should land flat. The real sole is
    flat only on a ~1.7 cm strip with 15 deg chamfers beside it; in the sim the policies stood on the foot's edges
    (> 5 deg tilt in 80 % of the contact time, servo_ctrl_v9) - the real robot tips over from there."""

    left_body: int = attrs.field()
    right_body: int = attrs.field()
    deadzone: float = attrs.field(default=0.0)          # rad of tilt that cost nothing (heel/toe roll while walking)
    contact_obs: str = attrs.field(default="feet_contact_observation")

    def __call__(self, trajectory: ksim.Trajectory, reward_carry: PyTree) -> tuple[Array, PyTree]:
        q = trajectory.xquat[..., jnp.array([self.left_body, self.right_body]), :]       # (T, 2, 4) wxyz
        x, y = q[..., 1], q[..., 2]
        cos_tilt = jnp.clip(1.0 - 2.0 * (x * x + y * y), -1.0, 1.0)                     # world z of the foot's z axis
        contact = trajectory.obs[self.contact_obs] > 0.5
        r = (jnp.maximum(jnp.arccos(cos_tilt) - self.deadzone, 0.0) * contact).sum(axis=-1)
        return jnp.where(trajectory.done, 0.0, r), None


@attrs.define(frozen=True, kw_only=True)
class FootClearanceReward(ksim.Reward):
    """Rewards lifting the swing foot: clip((z - z_stance) / target, 0, 1) for a foot off the ground while the
    other foot is in contact. z_stance is that foot's mean height while in contact over the rollout, so
    the reward is independent of the foot site's rest height."""

    target: float = attrs.field(default=0.03)
    pos_obs: str = attrs.field(default="feet_position_observation")
    contact_obs: str = attrs.field(default="feet_contact_observation")

    def __call__(self, trajectory: ksim.Trajectory, reward_carry: PyTree) -> tuple[Array, PyTree]:
        pos = trajectory.obs[self.pos_obs]
        z = pos.reshape(pos.shape[:-1] + (2, 3))[..., 2]                    # (T, 2)
        contact = trajectory.obs[self.contact_obs] > 0.5
        c = contact.astype(jnp.float32)
        z_stance = (z * c).sum(axis=0) / jnp.maximum(c.sum(axis=0), 1.0)      # (2,)
        lift = jnp.clip((z - z_stance) / self.target, 0.0, 1.0)
        r = (lift * (~contact) * contact[..., ::-1]).sum(axis=-1)
        return jnp.where(trajectory.done, 0.0, r), None


@attrs.define(frozen=True, kw_only=True)
class HeadingPenalty(ksim.Reward):
    """|yaw| of the base (rad, clipped) — the robot spawns facing +x, so this punishes accumulated heading drift
    instead of the per-step yaw rate (which a stepping gait oscillates anyway)."""

    clip: float = attrs.field(default=1.0)

    def __call__(self, trajectory: ksim.Trajectory, reward_carry: PyTree) -> tuple[Array, PyTree]:
        q = trajectory.qpos[..., 3:7]
        yaw = jnp.arctan2(2 * (q[..., 0] * q[..., 3] + q[..., 1] * q[..., 2]), 1 - 2 * (q[..., 2] ** 2 + q[..., 3] ** 2))
        return jnp.where(trajectory.done, 0.0, jnp.clip(jnp.abs(yaw), max=self.clip)), None


@attrs.define(frozen=True, kw_only=True)
class LateralPositionPenalty(ksim.Reward):
    """|y| of the base (m, clipped): stay on the x axis it started on."""

    clip: float = attrs.field(default=1.0)

    def __call__(self, trajectory: ksim.Trajectory, reward_carry: PyTree) -> tuple[Array, PyTree]:
        y = trajectory.qpos[..., 1]
        return jnp.where(trajectory.done, 0.0, jnp.clip(jnp.abs(y), max=self.clip)), None


@attrs.define(frozen=True, kw_only=True)
class BaseHeadingObservation(ksim.Observation):
    """Heading of the base relative to the start heading (the robot always spawns facing +x): [cos yaw, sin yaw].
    On the real robot this is the IMU's fused/gyro-integrated yaw, zeroed when the policy starts."""

    def observe(self, state: ksim.ObservationInput, rng: PRNGKeyArray) -> Array:
        q = state.physics_state.data.qpos[3:7]
        yaw = jnp.arctan2(2 * (q[0] * q[3] + q[1] * q[2]), 1 - 2 * (q[2] ** 2 + q[3] ** 2))
        return jnp.stack([jnp.cos(yaw), jnp.sin(yaw)], axis=-1)


@attrs.define(frozen=True, kw_only=True)
class FootLiftPenalty(ksim.Reward):
    """Penalises lifting a swing foot higher than `max_lift` above its stance height (small, real-robot-friendly
    steps): clip((z - z_stance - max_lift) / 0.02, 0, 1) per foot in the air while the other foot is down."""

    max_lift: float = attrs.field(default=0.04)
    pos_obs: str = attrs.field(default="feet_position_observation")
    contact_obs: str = attrs.field(default="feet_contact_observation")

    def __call__(self, trajectory: ksim.Trajectory, reward_carry: PyTree) -> tuple[Array, PyTree]:
        pos = trajectory.obs[self.pos_obs]
        z = pos.reshape(pos.shape[:-1] + (2, 3))[..., 2]
        contact = trajectory.obs[self.contact_obs] > 0.5
        c = contact.astype(jnp.float32)
        z_stance = (z * c).sum(axis=0) / jnp.maximum(c.sum(axis=0), 1.0)
        over = jnp.clip((z - z_stance - self.max_lift) / 0.02, 0.0, 1.0)
        r = (over * (~contact) * contact[..., ::-1]).sum(axis=-1)
        return jnp.where(trajectory.done, 0.0, r), None


@attrs.define(frozen=True, kw_only=True)
class JointDeviationPenalty(ksim.Reward):
    """Sum of |q| (rad) over selected joints: keeps e.g. hip abduction/rotation and the arms near the zero pose
    (minimal joint movement for a calm, real-robot-friendly gait)."""

    joint_indices: tuple[int, ...] = attrs.field()
    obs_name: str = attrs.field(default="joint_position_observation")

    def __call__(self, trajectory: ksim.Trajectory, reward_carry: PyTree) -> tuple[Array, PyTree]:
        q = trajectory.obs[self.obs_name][..., jnp.array(self.joint_indices)]
        return jnp.where(trajectory.done, 0.0, jnp.abs(q).sum(axis=-1)), None


@attrs.define(frozen=True, kw_only=True)
class BaseRollPenalty(ksim.Reward):
    """|roll| of the base (rad, clipped): left-right leaning of the torso."""

    clip: float = attrs.field(default=0.5)

    def __call__(self, trajectory: ksim.Trajectory, reward_carry: PyTree) -> tuple[Array, PyTree]:
        q = trajectory.qpos[..., 3:7]
        roll = jnp.arctan2(2 * (q[..., 0] * q[..., 1] + q[..., 2] * q[..., 3]), 1 - 2 * (q[..., 1] ** 2 + q[..., 2] ** 2))
        return jnp.where(trajectory.done, 0.0, jnp.clip(jnp.abs(roll), max=self.clip)), None


@attrs.define(frozen=True, kw_only=True)
class MeanJointSpeedPenalty(ksim.Reward):
    """Mean |joint velocity| (rad/s) over all actuated joints: slower, calmer motion."""

    obs_name: str = attrs.field(default="joint_velocity_observation")

    def __call__(self, trajectory: ksim.Trajectory, reward_carry: PyTree) -> tuple[Array, PyTree]:
        v = trajectory.obs[self.obs_name]
        return jnp.where(trajectory.done, 0.0, jnp.abs(v).mean(axis=-1)), None


@attrs.define(frozen=True, kw_only=True)
class AngularVelocityTrackingReward(ksim.Reward):
    """Reward for tracking the angular velocity."""

    error_scale: float = attrs.field(default=0.25)
    angvel_obs_name: str = attrs.field(default="sensor_observation_base_link_ang_vel")
    command_name: str = attrs.field(default="angular_velocity_command_z")
    norm: xax.NormType = attrs.field(default="l2")

    def __call__(self, trajectory: ksim.Trajectory, reward_carry: PyTree) -> tuple[Array, PyTree]:
        if self.angvel_obs_name not in trajectory.obs:
            raise ValueError(f"Observation {self.angvel_obs_name} not found; add it as an observation in your task.")
        cmd = trajectory.command
        ang_cmd = cmd[self.command_name] if self.command_name in cmd else cmd["angular_velocity_command"]
        ang_vel = trajectory.obs[self.angvel_obs_name][..., 2]
        ang_vel_error = jnp.square(jnp.reshape(ang_cmd, ang_vel.shape) - ang_vel)
        return jnp.exp(-ang_vel_error / self.error_scale), None


@attrs.define(frozen=True, kw_only=True)
class TerminationPenalty(ksim.Reward):
    """Penalty for termination."""

    scale: float = attrs.field(default=-1.0)

    def __call__(self, trajectory: ksim.Trajectory, reward_carry: PyTree) -> tuple[Array, PyTree]:
        return trajectory.done, None


@attrs.define(frozen=True, kw_only=True)
class XYPushEvent(ksim.Event):
    """Randomly push the robot after some interval."""

    interval_range: tuple[float, float] = attrs.field()
    force_range: tuple[float, float] = attrs.field()
    curriculum_scale: float = attrs.field(default=1.0)

    def __call__(
        self,
        model: ksim.PhysicsModel,
        data: ksim.PhysicsData,
        event_state: Array,
        curriculum_level: Array,
        rng: PRNGKeyArray,
    ) -> tuple[ksim.PhysicsData, Array]:
        # Decrement by physics timestep.
        dt = jnp.float32(model.opt.timestep)
        time_remaining = event_state - dt

        # Update the data if the time remaining is less than 0.
        updated_data, time_remaining = jax.lax.cond(
            time_remaining <= 0.0,
            lambda: self._apply_random_force(data, curriculum_level, rng),
            lambda: (data, time_remaining),
        )

        return updated_data, time_remaining

    def _apply_random_force(
        self, data: ksim.PhysicsData, curriculum_level: Array, rng: PRNGKeyArray
    ) -> tuple[ksim.PhysicsData, Array]:
        push_theta = jax.random.uniform(rng, maxval=2 * jnp.pi)
        push_magnitude = (
            jax.random.uniform(
                rng,
                minval=self.force_range[0],
                maxval=self.force_range[1],
            )
            * curriculum_level
            * self.curriculum_scale
        )
        push = jnp.array([jnp.cos(push_theta), jnp.sin(push_theta)])
        random_forces = push * push_magnitude + data.qvel[:2]
        new_qvel = slice_update(data, "qvel", slice(0, 2), random_forces)
        updated_data = update_data_field(data, "qvel", new_qvel)

        # Chooses a new remaining interval.
        minval, maxval = self.interval_range
        time_remaining = jax.random.uniform(rng, (), minval=minval, maxval=maxval)

        return updated_data, time_remaining

    def get_initial_event_state(self, rng: PRNGKeyArray) -> Array:
        minval, maxval = self.interval_range
        return jax.random.uniform(rng, (), minval=minval, maxval=maxval)


@attrs.define(frozen=True, kw_only=True)
class TorquePushEvent(ksim.Event):
    """Randomly push the robot with torque (angular velocity) after some interval."""

    interval_range: tuple[float, float] = attrs.field()
    ang_vel_range: tuple[float, float] = attrs.field()  # Min/max push angular velocity per axis
    curriculum_scale: float = attrs.field(default=1.0)

    def __call__(
        self,
        model: ksim.PhysicsModel,
        data: ksim.PhysicsData,
        event_state: Array,
        curriculum_level: Array,
        rng: PRNGKeyArray,
    ) -> tuple[ksim.PhysicsData, Array]:
        dt = jnp.float32(model.opt.timestep)
        time_remaining = event_state - dt

        # Update the data if the time remaining is less than 0.
        updated_data, time_remaining = jax.lax.cond(
            time_remaining <= 0.0,
            lambda: self._apply_random_angular_velocity_push(data, curriculum_level, rng),
            lambda: (data, time_remaining),
        )

        return updated_data, time_remaining

    def _apply_random_angular_velocity_push(
        self, data: ksim.PhysicsData, curriculum_level: Array, rng: PRNGKeyArray
    ) -> tuple[ksim.PhysicsData, Array]:
        """Applies a random angular velocity push to the root body."""
        rng_push, rng_interval = jax.random.split(rng)

        # Sample angular velocity push components
        min_ang_vel, max_ang_vel = self.ang_vel_range
        push_ang_vel = jax.random.uniform(
            rng_push,
            shape=(3,),  # Angular velocity is 3D (wx, wy, wz)
            minval=min_ang_vel,
            maxval=max_ang_vel,
        )
        scaled_push_ang_vel = push_ang_vel * curriculum_level * self.curriculum_scale

        # Apply the push to angular velocity (qvel indices 3:6 for free joint)
        ang_vel_indices = slice(3, 6)

        # Add the push to the current angular velocity
        current_ang_vel = data.qvel[ang_vel_indices]
        new_ang_vel_val = current_ang_vel + scaled_push_ang_vel
        new_qvel = slice_update(data, "qvel", ang_vel_indices, new_ang_vel_val)
        updated_data = update_data_field(data, "qvel", new_qvel)

        minval_interval, maxval_interval = self.interval_range
        time_remaining = jax.random.uniform(rng_interval, (), minval=minval_interval, maxval=maxval_interval)

        return updated_data, time_remaining

    def get_initial_event_state(self, rng: PRNGKeyArray) -> Array:
        minval, maxval = self.interval_range
        return jax.random.uniform(rng, (), minval=minval, maxval=maxval)


@attrs.define(frozen=True)
class FeetPositionObservation(ksim.Observation):
    foot_left: int = attrs.field()
    foot_right: int = attrs.field()
    floor_threshold: float = attrs.field(default=0.0)

    @classmethod
    def create(
        cls,
        *,
        physics_model: ksim.PhysicsModel,
        foot_left_site_name: str,
        foot_right_site_name: str,
        floor_threshold: float = 0.0,
    ) -> Self:
        foot_left_idx = get_site_data_idx_from_name(physics_model, foot_left_site_name)
        foot_right_idx = get_site_data_idx_from_name(physics_model, foot_right_site_name)
        return cls(
            foot_left=foot_left_idx,
            foot_right=foot_right_idx,
            floor_threshold=floor_threshold,
        )

    def observe(self, state: ksim.ObservationInput, rng: PRNGKeyArray) -> Array:
        foot_left_pos = state.physics_state.data.site_xpos[self.foot_left] + jnp.array([0.0, 0.0, self.floor_threshold])
        foot_right_pos = state.physics_state.data.site_xpos[self.foot_right] + jnp.array(
            [0.0, 0.0, self.floor_threshold]
        )
        return jnp.concatenate([foot_left_pos, foot_right_pos], axis=-1)


def sole_geoms(physics_model: ksim.PhysicsModel, side: str) -> list[str]:
    """The floor-contact geoms of one foot: the flat strip and, in models built since 2026-10-29, the two chamfers."""
    from ksim.utils.mujoco import get_geom_data_idx_from_name
    names = [f"{side}_Foot_collision_box"]
    for suffix in ("chamfer_neg", "chamfer_pos"):
        try:
            get_geom_data_idx_from_name(physics_model, f"{side}_Foot_{suffix}")
            names.append(f"{side}_Foot_{suffix}")
        except Exception:
            pass
    return names


@attrs.define(frozen=True, kw_only=True)
class FeetContactObservation(ksim.FeetContactObservation):
    """Observation of the feet contact: [left, right], each True when ANY of that foot's sole geoms touches the floor
    (flat strip + two chamfer boxes since 2026-10-29; a foot rolled onto its chamfer is still in contact)."""

    def observe(self, state: ksim.ObservationInput, rng: PRNGKeyArray) -> Array:
        from ksim.utils.mujoco import geoms_colliding
        data, floor = state.physics_state.data, jnp.array(self.floor_geom)
        left = geoms_colliding(data, jnp.array(self.foot_left), floor).any()
        right = geoms_colliding(data, jnp.array(self.foot_right), floor).any()
        return jnp.stack([left, right])


@attrs.define(frozen=True, kw_only=True)
class TargetGapPenalty(ksim.Reward):
    """Mean |commanded target - joint angle| (rad). A target that sits far ahead of the joint means the servo runs
    at full speed (or full duty) towards it: the bang-bang driving the first hardware tests had."""

    def __call__(self, trajectory: ksim.Trajectory, reward_carry: PyTree) -> tuple[Array, PyTree]:
        gap = jnp.abs(trajectory.action - trajectory.qpos[..., 7:])
        return jnp.where(trajectory.done, 0.0, gap.mean(axis=-1)), None


@attrs.define(frozen=True, kw_only=True)
class ActionSaturationPenalty(ksim.Reward):
    """Mean of ((|action| - threshold) / (1 - threshold))^2 over the part of |action| above `threshold`: the tanh
    outputs of a bang-bang policy sit at +-1."""

    threshold: float = attrs.field(default=0.9)

    def __call__(self, trajectory: ksim.Trajectory, reward_carry: PyTree) -> tuple[Array, PyTree]:
        over = jnp.maximum(jnp.abs(trajectory.action) - self.threshold, 0.0) / (1.0 - self.threshold)
        return jnp.where(trajectory.done, 0.0, jnp.square(over).mean(axis=-1)), None


@attrs.define(frozen=True, kw_only=True)
class JointLimitPenalty(ksim.Reward):
    """Mean over the joints of ((margin - distance to the nearer joint limit) / margin)^2 inside the margin band.
    The real joints end at hard stops; a policy that rides the limit presses a printed bracket against it."""

    lower: tuple[float, ...] = attrs.field()
    upper: tuple[float, ...] = attrs.field()
    margin: tuple[float, ...] | float = attrs.field(default=0.087)
    # "sum" over the joints instead of the mean: servo_rubber17 - only the two hip yaws ride their stop, the mean over
    # 20 joints made that 10x cheaper than intended and the policy kept leaning on the stop (margin_share 0.94)
    reduce_sum: bool = attrs.field(default=False)

    def __call__(self, trajectory: ksim.Trajectory, reward_carry: PyTree) -> tuple[Array, PyTree]:
        q = trajectory.qpos[..., 7:]
        margin = jnp.asarray(self.margin)
        dist = jnp.minimum(q - jnp.array(self.lower), jnp.array(self.upper) - q)
        inside = jnp.clip(jnp.maximum(margin - dist, 0.0) / margin, max=2.0) if self.reduce_sum else jnp.maximum(margin - dist, 0.0) / margin
        pen = jnp.square(inside).sum(axis=-1) if self.reduce_sum else jnp.square(inside).mean(axis=-1)
        return jnp.where(trajectory.done, 0.0, pen), None

    @classmethod
    def from_model(cls, physics_model: ksim.PhysicsModel, margin_deg: float, scale: float,
                   reduce_sum: bool = False) -> "JointLimitPenalty":
        lo, hi = real_joint_limits(physics_model)                    # real limits intersected with the sim range
        return cls(lower=tuple(float(x) for x in lo), upper=tuple(float(x) for x in hi),
                   margin=tuple(float(x) for x in limit_margins(lo, hi, np.radians(margin_deg))), scale=scale,
                   reduce_sum=reduce_sum)


def action_clip_bounds(mj_model, margin_deg: float, reserve_deg: float = 0.0) -> dict:
    """ZbotModel kwargs for action_clip_margin_deg > 0: per joint the real range (real_joint_limits) shrunk by
    limit_margins (= the hardware gate's margin, hip yaw 1.5 / 2.5 deg). servo_rubber16/17: penalties did not stop the
    policy from aiming the hip yaw 15-20 deg beyond its 3/5 deg limits and using the Pi clamp as an end stop."""
    if margin_deg <= 0:
        return {}
    lo, hi = real_joint_limits(mj_model)
    # + reserve_deg (action_clip_reserve_deg): servo_rubber19 parked the right hip-yaw target on the clip half the time
    # and the load bent the joint the last 1-1.5 deg into the gate margin -> keep the target that much further inside
    m = limit_margins(lo, hi, np.radians(margin_deg)) + np.radians(reserve_deg)
    m = np.minimum(m, np.where(lo < 0, -lo, m)); m = np.minimum(m, np.where(hi > 0, hi, m))   # never past the zero pose
    return {"clip_lo": tuple(float(x) for x in lo + m), "clip_hi": tuple(float(x) for x in hi - m)}


def limit_margins(lo: np.ndarray, hi: np.ndarray, margin: float) -> np.ndarray:
    """Per joint: `margin`, but at most half the distance from the zero pose to the nearer limit. The real hip-yaw limits
    sit 3 deg (right) and 5 deg (left) from zero: a fixed 5 deg band would forbid the neutral stance itself."""
    to_zero = np.minimum(-np.asarray(lo), np.asarray(hi))
    return np.where(to_zero > 0, np.minimum(margin, 0.5 * to_zero), margin)


@attrs.define(frozen=True, kw_only=True)
class JointSpeedLimitPenalty(ksim.Reward):
    """Mean over the joints of the relative excess of |joint speed| over the servo's speed limit:
    relu(|qvel| - v_limit) / v_limit. Legs follow the speed register the Pi sends (v = ticks/s * 2pi/4096), the arms
    top out at ~1.8 rad/s whatever the register says."""

    v_limit: tuple[float, ...] = attrs.field()

    def __call__(self, trajectory: ksim.Trajectory, reward_carry: PyTree) -> tuple[Array, PyTree]:
        v = jnp.array(self.v_limit)
        over = jnp.maximum(jnp.abs(trajectory.qvel[..., 6:]) - v, 0.0) / v
        return jnp.where(trajectory.done, 0.0, over.mean(axis=-1)), None

    @classmethod
    def from_model(cls, physics_model: ksim.PhysicsModel, leg_v: float, arm_v: float,
                   scale: float) -> "JointSpeedLimitPenalty":
        limits = np.full(int(physics_model.nq) - 7, leg_v)
        for name, idx in get_qpos_data_idxs_by_name(physics_model).items():
            if "shoulder" in name or "elbow" in name:
                limits[int(idx[0]) - 7] = arm_v
        return cls(v_limit=tuple(float(x) for x in limits), scale=scale)


def _shift_back(x: Array, n: int = 1) -> Array:
    """x(t-n) along the time axis (-2), padded with the first value."""
    return jnp.concatenate([jnp.repeat(x[..., :1, :], n, axis=-2), x[..., :-n, :]], axis=-2)


@attrs.define(frozen=True, kw_only=True)
class ActionStepLimitPenalty(ksim.Reward):
    """Mean over the joints of the relative excess of |action(t) - action(t-1)| over the step the command rate limiter
    lets through (relu(|da| - step) / step). A policy that asks for more than the limiter allows relies on it to cut
    its chatter: the servos then see a zig-zag at half the control rate (visible jitter on the first calm runs: the raw
    action jerk was 0.34 rad/step^2, 88 % of the joint-steps asked for more than the limiter's step)."""

    step: tuple[float, ...] = attrs.field()

    def __call__(self, trajectory: ksim.Trajectory, reward_carry: PyTree) -> tuple[Array, PyTree]:
        step = jnp.array(self.step)
        da = jnp.abs(trajectory.action - _shift_back(trajectory.action))
        return jnp.where(trajectory.done, 0.0, (jnp.maximum(da - step, 0.0) / step).mean(axis=-1)), None

    @classmethod
    def from_model(cls, physics_model: ksim.PhysicsModel, fraction: float, leg_v: float, arm_v: float, ctrl_dt: float,
                   scale: float) -> "ActionStepLimitPenalty":
        v = np.full(int(physics_model.nq) - 7, leg_v)
        for name, idx in get_qpos_data_idxs_by_name(physics_model).items():
            if "shoulder" in name or "elbow" in name:
                v[int(idx[0]) - 7] = arm_v
        return cls(step=tuple(float(x) for x in fraction * v * ctrl_dt), scale=scale)


@attrs.define(frozen=True, kw_only=True)
class ActionJerkPenalty(ksim.Reward):
    """Mean over the joints of (action(t) - 2 action(t-1) + action(t-2))^2: the change of the change. Chatter with the
    period of two control steps (the worst jitter for a servo) costs 16x more than a smooth swing of the same size."""

    def __call__(self, trajectory: ksim.Trajectory, reward_carry: PyTree) -> tuple[Array, PyTree]:
        a = trajectory.action
        jerk = a - 2.0 * _shift_back(a) + _shift_back(a, 2)
        return jnp.where(trajectory.done, 0.0, jnp.square(jerk).mean(axis=-1)), None


@attrs.define(frozen=True, kw_only=True)
class JointAccelerationPenalty(ksim.Reward):
    """Mean over the joints of (qvel(t) - qvel(t-1))^2: the jitter of the joints themselves, what a video shows. The
    penalties on the raw action did not reach it (servo_ctrl_v2: 33-57 % of the leg motion above 5 Hz)."""

    def __call__(self, trajectory: ksim.Trajectory, reward_carry: PyTree) -> tuple[Array, PyTree]:
        qv = trajectory.qvel[..., 6:]
        return jnp.where(trajectory.done, 0.0, jnp.square(qv - _shift_back(qv)).mean(axis=-1)), None


@attrs.define(frozen=True, kw_only=True)
class StrideLengthReward(ksim.Reward):
    """At every touchdown of a foot after a real swing (>= min_swing s in the air) and while the other foot stands:
    clip(forward travel of that foot since its liftoff / target, 0, 1). Contact flicker and shuffling earn nothing
    (servo_ctrl_v2: 7 touchdowns per foot and second, median stride 5 mm)."""

    target: float = attrs.field(default=0.08)
    min_swing: float = attrs.field(default=0.2)
    ctrl_dt: float = attrs.field(default=0.02)
    needs_command: bool = attrs.field(default=False)   # pay only while a forward speed is commanded
    per_command: bool = attrs.field(default=False)     # target = commanded speed x gait period, at most `target`
    pos_obs: str = attrs.field(default="feet_position_observation")
    contact_obs: str = attrs.field(default="feet_contact_observation")

    def __call__(self, trajectory: ksim.Trajectory, reward_carry: PyTree) -> tuple[Array, PyTree]:
        pos = trajectory.obs[self.pos_obs]
        x = pos.reshape(pos.shape[:-1] + (2, 3))[..., 0]                   # (T, 2) world x = forward
        contact = trajectory.obs[self.contact_obs] > 0.5
        prev = jnp.concatenate([contact[:1], contact[:-1]], axis=0)
        liftoff, touchdown = prev & ~contact, ~prev & contact

        def fwd(carry: tuple[Array, Array], inp: tuple[Array, Array, Array]) -> tuple[tuple[Array, Array], tuple[Array, Array]]:
            x_lift, run = carry
            x_t, lift_t, swing_t = inp
            x_lift = jnp.where(lift_t, x_t, x_lift)
            run = jnp.where(swing_t, run + 1, 0)
            return (x_lift, run), (x_lift, run)

        _, (x_lift, run) = jax.lax.scan(fwd, (x[0], jnp.zeros(2, dtype=jnp.int32)), (x, liftoff, ~contact))
        run_before = jnp.concatenate([jnp.zeros_like(run[:1]), run[:-1]], axis=0)   # swing length up to touchdown
        real = run_before.astype(jnp.float32) * self.ctrl_dt >= self.min_swing
        target = self.target
        if self.per_command:
            # a foot travels speed x gait period per swing: a fixed 4 cm at 1.0-1.25 Hz means 4-5 cm/s at every command,
            # servo_rubber4 walked 1.2-1.6x the command of 3-6 cm/s (2026-11-04)
            v = trajectory.command["linear_velocity_command"][..., :1]
            f = trajectory.command["gait_frequency_command"][..., :1]
            target = jnp.clip(v / jnp.maximum(f, 0.1), 0.01, self.target)
        stride = jnp.clip((x - x_lift) / target, 0.0, 1.0)
        r = (stride * touchdown * real * contact[..., ::-1]).sum(axis=-1)
        if self.needs_command:
            r = jnp.where(trajectory.command["linear_velocity_command"][..., 0] > 1e-3, r, 0.0)
        return jnp.where(trajectory.done, 0.0, r), None


@attrs.define(frozen=True, kw_only=True)
class GaitClockReward(ksim.Reward):
    """Feet follow the commanded gait clock (timestep_phase observation [cos0, cos1, sin0, sin1], one phase per foot,
    half a cycle apart): swing while sin(phase) > threshold, stand while sin(phase) < -threshold, transitions are not
    counted. Per step the mean over the feet of the matches: 0..~0.87. The policy ignored the clock before and
    vibrated its feet at 7 Hz against a 1.0-1.5 Hz command."""

    threshold: float = attrs.field(default=0.2)
    phase_obs: str = attrs.field(default="timestep_phase_observation")
    contact_obs: str = attrs.field(default="feet_contact_observation")

    def __call__(self, trajectory: ksim.Trajectory, reward_carry: PyTree) -> tuple[Array, PyTree]:
        sin = trajectory.obs[self.phase_obs][..., 2:4]
        contact = trajectory.obs[self.contact_obs] > 0.5
        want_swing, want_stance = sin > self.threshold, sin < -self.threshold
        match = (want_swing & ~contact) | (want_stance & contact)
        return jnp.where(trajectory.done, 0.0, match.astype(jnp.float32).mean(axis=-1)), None


@attrs.define(frozen=True, kw_only=True)
class TargetLimitPenalty(ksim.Reward):
    """Mean over the joints of how far the commanded target lies beyond the real joint limit (rad, linear: the hip-yaw
    excess is only hundredths of a radian, squared it vanished). The Pi clamps such a target to the limit; the policy
    should not need the clamp - it means pressing the joint onto its limit."""

    lower: tuple[float, ...] = attrs.field()
    upper: tuple[float, ...] = attrs.field()

    def __call__(self, trajectory: ksim.Trajectory, reward_carry: PyTree) -> tuple[Array, PyTree]:
        a = trajectory.action
        excess = jnp.maximum(a - jnp.array(self.upper), 0.0) + jnp.maximum(jnp.array(self.lower) - a, 0.0)
        return jnp.where(trajectory.done, 0.0, excess.mean(axis=-1)), None

    @classmethod
    def from_model(cls, physics_model: ksim.PhysicsModel, scale: float) -> "TargetLimitPenalty":
        lo, hi = real_joint_limits(physics_model)
        return cls(lower=tuple(float(x) for x in lo), upper=tuple(float(x) for x in hi), scale=scale)


class ZbotActor(eqx.Module):
    """Actor for the walking task."""

    mlp: eqx.nn.MLP
    min_std: float = eqx.static_field()
    max_std: float = eqx.static_field()
    var_scale: float = eqx.static_field()
    mean_scale: float = eqx.static_field()
    clip_lo: tuple[float, ...] | None = eqx.static_field()
    clip_hi: tuple[float, ...] | None = eqx.static_field()

    def __init__(
        self,
        key: PRNGKeyArray,
        *,
        min_std: float,
        max_std: float,
        var_scale: float,
        mean_scale: float,
        num_inputs: int = NUM_INPUTS,
        clip_lo: tuple[float, ...] | None = None,
        clip_hi: tuple[float, ...] | None = None,
    ) -> None:
        self.mlp = eqx.nn.MLP(
            in_size=num_inputs,
            out_size=NUM_OUTPUTS * 2,
            width_size=256,
            depth=5,
            key=key,
            activation=jax.nn.relu,
        )
        self.min_std = min_std
        self.max_std = max_std
        self.var_scale = var_scale
        self.mean_scale = mean_scale
        self.clip_lo = clip_lo
        self.clip_hi = clip_hi

    def forward(
        self,
        timestep_phase_4: Array,
        joint_pos_n: Array,
        joint_vel_n: Array,
        imu_acc_3: Array,
        imu_gyro_3: Array,
        lin_vel_cmd_2: Array,
        ang_vel_cmd_1: Array,
        gait_freq_cmd_1: Array,
        last_action_n: Array,
        heading_2: Array | None = None,
        action_history_m: Array | None = None,
    ) -> distrax.Normal:
        parts = [
            timestep_phase_4,
            joint_pos_n,
            joint_vel_n,
            imu_acc_3,
            imu_gyro_3,
            lin_vel_cmd_2,
            ang_vel_cmd_1,
            gait_freq_cmd_1,
            last_action_n,
        ]
        if heading_2 is not None:
            parts.append(heading_2)  # heading_obs=True: +2 inputs
        if action_history_m is not None:
            parts.append(action_history_m)  # action_history=k: +16 * (k - 1) inputs
        x_n = jnp.concatenate(parts, axis=-1)  # (NUM_INPUTS [+2] [+16 (k - 1)])

        return self.call_flat_obs(x_n)

    def call_flat_obs(
        self,
        flat_obs_n: Array,
    ) -> distrax.Normal:
        # Split the output into mean and standard deviation.
        prediction_n = self.mlp(flat_obs_n)

        mean_n = prediction_n[..., :NUM_OUTPUTS]
        std_n = prediction_n[..., NUM_OUTPUTS:]

        # Scale the mean.
        mean_n = jnp.tanh(mean_n) * self.mean_scale
        if self.clip_lo is not None:   # action_clip_margin_deg: the target never leaves the real range minus the margin
            mean_n = jnp.clip(mean_n, jnp.array(self.clip_lo), jnp.array(self.clip_hi))

        # Softplus and clip to ensure positive standard deviations.
        std_n = jnp.clip((jax.nn.softplus(std_n) + self.min_std) * self.var_scale, max=self.max_std)

        # Return position-only distribution
        return distrax.Normal(mean_n, std_n)


class ZbotCritic(eqx.Module):
    """Critic for the walking task."""

    mlp: eqx.nn.MLP

    def __init__(self, key: PRNGKeyArray) -> None:
        self.mlp = eqx.nn.MLP(
            in_size=NUM_CRITIC_INPUTS,
            out_size=1,  # Always output a single critic value.
            width_size=256,
            depth=5,
            key=key,
            activation=jax.nn.relu,
        )

    def forward(
        self,
        timestep_phase_4: Array,
        joint_pos_n: Array,
        joint_vel_n: Array,
        imu_acc_3: Array,
        imu_gyro_3: Array,
        lin_vel_cmd_2: Array,
        ang_vel_cmd_1: Array,
        gait_freq_cmd_1: Array,
        last_action_n: Array,
        feet_colliding_2: Array,
        feet_contact_2: Array,
        feet_position_6: Array,
        projected_gravity_3: Array,
        base_position_3: Array,
        base_orientation_4: Array,
        base_linear_velocity_3: Array,
        base_angular_velocity_3: Array,
        actuator_force_n: Array,
        true_height_1: Array,
    ) -> Array:
        # print("timestep_phase_4 shape:", timestep_phase_4.shape)
        # print("joint_pos_n shape:", joint_pos_n.shape)
        # print("joint_vel_n shape:", joint_vel_n.shape)
        # print("imu_acc_3 shape:", imu_acc_3.shape)
        # print("imu_gyro_3 shape:", imu_gyro_3.shape)
        # print("lin_vel_cmd_2 shape:", lin_vel_cmd_2.shape)
        # print("ang_vel_cmd shape:", ang_vel_cmd_1.shape)
        # print("gait_freq_cmd shape:", gait_freq_cmd_1.shape)
        # print("last_action_n shape:", last_action_n.shape)
        # print("feet_colliding_1 shape:", feet_colliding_2.shape)
        # print("feet_contact_2 shape:", feet_contact_2.shape)
        # print("feet_position_6 shape:", feet_position_6.shape)
        # print("projected_gravity_3 shape:", projected_gravity_3.shape)
        # print("base_position_3 shape:", base_position_3.shape)
        # print("base_orientation_4 shape:", base_orientation_4.shape)
        # print("base_linear_velocity_3 shape:", base_linear_velocity_3.shape)
        # print("base_angular_velocity_3 shape:", base_angular_velocity_3.shape)
        # print("actuator_force_n shape:", actuator_force_n.shape)
        # print("true_height_1 shape:", true_height_1.shape)
        x_n = jnp.concatenate(
            [
                timestep_phase_4,
                joint_pos_n,
                joint_vel_n,
                imu_acc_3,
                imu_gyro_3,
                lin_vel_cmd_2,
                ang_vel_cmd_1,
                gait_freq_cmd_1,
                last_action_n,
                feet_colliding_2,
                feet_contact_2,
                feet_position_6,
                projected_gravity_3,
                base_position_3,
                base_orientation_4,
                base_linear_velocity_3,
                base_angular_velocity_3,
                actuator_force_n,
                true_height_1,
            ],
            axis=-1,
        )
        return self.mlp(x_n)


class ZbotModel(eqx.Module):
    actor: ZbotActor
    critic: ZbotCritic

    def __init__(self, key: PRNGKeyArray, num_inputs: int = NUM_INPUTS,
                 clip_lo: tuple[float, ...] | None = None, clip_hi: tuple[float, ...] | None = None) -> None:
        self.actor = ZbotActor(
            key,
            min_std=0.01,
            max_std=1.0,
            var_scale=1.0,
            mean_scale=1.0,
            num_inputs=num_inputs,
            clip_lo=clip_lo,
            clip_hi=clip_hi,
        )
        self.critic = ZbotCritic(key)


@dataclass
class ZbotWalkingTaskConfig(ZbotTaskConfig):
    """Config for the ZBot walking task."""

    action_scale: float = xax.field(
        value=1.0,
        help="The scale to apply to the actions.",
    )

    gait_freq_lower: float = xax.field(value=1.25)
    gait_freq_upper: float = xax.field(value=2.0)

    # Optimizer parameters.
    learning_rate: float = xax.field(
        value=1e-4,
        help="Learning rate for PPO.",
    )
    max_grad_norm: float = xax.field(
        value=0.5,
        help="Maximum gradient norm for clipping.",
    )
    adam_weight_decay: float = xax.field(
        value=0.0,
        help="Weight decay for the Adam optimizer.",
    )

    # Local addition: "walk straight" variant. Tracks a forward velocity command instead of
    # rewarding raw forward speed; heading is held by the angular-velocity tracking term.
    velocity_tracking: bool = xax.field(
        value=False,
        help="Use velocity/heading tracking rewards with forward-only commands (walk straight).",
    )
    target_speed_min: float = xax.field(value=0.15, help="Forward command lower bound [m/s] (velocity_tracking).")
    target_speed_max: float = xax.field(value=0.35, help="Forward command upper bound [m/s] (velocity_tracking).")
    speed_zero_prob: float = xax.field(value=0.0, help="Share of forward commands that are exactly 0 (step on the spot) - keeps the stepping a speed curriculum builds on (velocity_tracking).")
    gait_shaping: bool = xax.field(
        value=False,
        help="Add gait-shaping terms: reward feet leaving the ground, penalise lateral drift, yaw rate and jerky actions.",
    )
    gait_step_reward: float = xax.field(value=0.2, help="Scale of the feet-no-contact (stepping) reward (gait_shaping).")
    gait_lateral_penalty: float = xax.field(value=-0.5, help="Scale of the lateral (y) velocity penalty (gait_shaping).")
    gait_yaw_penalty: float = xax.field(value=-0.3, help="Scale of the yaw-rate penalty (gait_shaping).")
    gait_smooth_penalty: float = xax.field(value=-0.02, help="Scale of the action-smoothness penalty (gait_shaping).")
    gait_single_support: float = xax.field(value=0.0, help="Scale of the single-support (stepping) reward (gait_shaping).")
    feet_slip_penalty: float = xax.field(value=0.0, help="Scale of the foot-slip-while-in-contact penalty (gait_shaping), e.g. -0.3.")
    heading_obs: bool = xax.field(value=False, help="Give the actor the base heading relative to the start ([cos yaw, sin yaw], +2 inputs; real robot: IMU yaw zeroed at start) so it can hold a straight course.")
    action_history: int = xax.field(value=1, help="How many past actions the actor sees: 1 = only the last one (as before); k > 1 appends a(t-2) ... a(t-k) after the heading (+16 (k - 1) inputs; needs servo_model). 4 covers the ~85 ms the servo delay and lag keep a command in flight.")
    torso_body_name: str = xax.field(value="base", help="Body that gets the mass randomisation (zbot-cad: base; old zbot-pixel models: Z_BOT2_MASTER_BODY_SKELETON).")
    gait_swing_reward: float = xax.field(value=0.0, help="Scale of the swing-duration-band reward (gait_shaping), e.g. 1.0: +1 per step of a swing lasting gait_swing_tmin..tmax, -1 for shorter swings.")
    gait_swing_tmin: float = xax.field(value=0.15, help="Shortest swing phase (s) counted as a real step.")
    gait_swing_tmax: float = xax.field(value=0.45, help="Longest swing phase (s) still rewarded.")
    foot_flat_penalty: float = xax.field(value=0.0, help="Scale of the foot-tilt-in-contact penalty (rad per foot on the floor), e.g. -8: the soles should land flat.")
    foot_flat_deadzone_deg: float = xax.field(value=0.0, help="Foot tilt (deg) that is not penalised - a little heel/toe roll is needed to walk forward; standing on an edge (10-15 deg) is not.")
    gait_swing_dense: bool = xax.field(value=False, help="Swing reward rises with the swing duration (2 min(d / tmin, 1) - 1 per swing step) instead of a step at tmin: a gradient for a policy that never makes a long swing.")
    gait_flip_penalty: float = xax.field(value=0.0, help="Scale of the foot-contact-change (chattering) penalty (gait_shaping), e.g. -0.1.")
    gait_clearance_reward: float = xax.field(value=0.0, help="Scale of the swing-foot clearance reward (gait_shaping), e.g. 0.5.")
    gait_clearance_target: float = xax.field(value=0.03, help="Foot lift (m) above stance height that earns the full clearance reward.")
    foot_lift_penalty: float = xax.field(value=0.0, help="Scale of the penalty for lifting a swing foot above foot_lift_max (gait_shaping), e.g. -0.5.")
    foot_lift_max: float = xax.field(value=0.04, help="Foot lift (m) above stance height from which foot_lift_penalty applies.")
    joint_deviation_penalty: float = xax.field(value=0.0, help="Scale of the sum-|q| penalty on joint_deviation_joints (gait_shaping), e.g. -0.3.")
    joint_deviation_joints: str = xax.field(value="hip_yaw,hip_roll,shoulder,elbow", help="Comma-separated name substrings of the joints held near zero by joint_deviation_penalty.")
    roll_penalty: float = xax.field(value=0.0, help="Scale of the |base roll| penalty (gait_shaping), e.g. -1.0.")
    joint_velocity_penalty: float = xax.field(value=0.0, help="Scale of the mean-|joint velocity| penalty (gait_shaping), e.g. -0.02.")
    heading_penalty: float = xax.field(value=0.0, help="Scale of the |yaw| heading-drift penalty (gait_shaping), e.g. -1.0.")
    lateral_position_penalty: float = xax.field(value=0.0, help="Scale of the |y| lateral-drift penalty (gait_shaping), e.g. -0.5.")
    target_gap_penalty: float = xax.field(value=0.0, help="Scale of the mean |action - joint angle| penalty (gait_shaping), e.g. -0.2: targets far ahead of the joints drive the servos at full speed.")
    action_saturation_penalty: float = xax.field(value=0.0, help="Scale of the |action| > 0.9 saturation penalty (gait_shaping), e.g. -2.")
    joint_limit_penalty: float = xax.field(value=0.0, help="Scale of the penalty for joints inside joint_limit_margin_deg of their range limit (gait_shaping), e.g. -1.")
    target_limit_penalty: float = xax.field(value=0.0, help="Scale of the penalty for commanded targets beyond the real joint limits (gait_shaping), e.g. -8: hip yaw targets are 0.2-0.4 rad beyond them in the first hardware candidates.")
    joint_speed_limit_fraction: float = xax.field(value=1.0, help="Buffer for joint_speed_limit_penalty: the penalty starts at this fraction of the servo speed limit (0.7 = the servos should stay below 70 % of what they can do, so they never saturate and follow the targets proportionally).")
    joint_speed_limit_penalty: float = xax.field(value=0.0, help="Scale of the penalty for joint speeds above the servo limits (gait_shaping; legs: leg_servo_speed register, arms: arm_v_max), e.g. -30: legs reached 3.7 rad/s against 3.07 in the first hardware candidates.")
    action_step_limit_penalty: float = xax.field(value=0.0, help="Scale of the penalty for action changes beyond the command rate limiter's step (needs cmd_rate_fraction), e.g. -0.05: raw excess was 5.0 on the first calm runs.")
    action_jerk_penalty: float = xax.field(value=0.0, help="Scale of the squared second difference of the action (gait_shaping), e.g. -1: kills chatter at half the control rate.")
    joint_accel_penalty: float = xax.field(value=0.0, help="Scale of the mean (qvel(t)-qvel(t-1))^2 penalty on the joints (gait_shaping), e.g. -0.1: physical jitter (raw 2.3 on servo_ctrl_v2).")
    stride_reward: float = xax.field(value=0.0, help="Scale of the stride-length reward per real step (gait_shaping), e.g. 20.")
    stride_target: float = xax.field(value=0.08, help="Forward foot travel per swing (m) that earns the full stride reward.")
    stride_min_swing: float = xax.field(value=0.2, help="Shortest swing (s) that counts as a step for the stride reward.")
    gait_clock_reward: float = xax.field(value=0.0, help="Scale of the reward for feet following the gait clock (gait_shaping), e.g. 2.")
    naive_velocity_scale: float = xax.field(value=0.25, help="Scale of the raw forward-speed reward (velocity_tracking). Raise it (1-2) when the policy marches on the spot: tracking alone is satisfied by a standing gait with small oscillation.")
    naive_velocity_cap: float = xax.field(value=0.0, help="If > 0, the raw forward-speed reward stops growing at this multiple of the commanded speed (e.g. 1.2), so the bootstrap does not teach overspeed. 0 = up to 5 m/s.")
    joint_limit_sum: bool = xax.field(value=False, help="joint_limit_penalty sums over the joints (depth clipped at 2) instead of averaging: one joint riding its stop then costs the full scale.")
    action_clip_margin_deg: float = xax.field(value=0.0, help="> 0: clip the policy's action mean (also in the ONNX export) to the real joint range shrunk by this margin (at most half the zero-pose distance, hip yaw 1.5/2.5 deg). 0 = off.")
    action_clip_reserve_deg: float = xax.field(value=0.0, help="Extra distance (deg) the action clip keeps on top of action_clip_margin_deg, for the deflection under load; never past the zero pose.")
    joint_limit_margin_deg: float = xax.field(value=5.0, help="Width of the band in front of the joint limits that joint_limit_penalty punishes.")
    track_reward_scale: float = xax.field(value=2.0, help="Scale of the linear velocity tracking reward (velocity_tracking).")
    track_error_scale: float = xax.field(value=0.25, help="Error scale of the velocity tracking reward; smaller = stricter.")
    track_window_s: float = xax.field(value=0.0, help="Track the velocity averaged over this window (s), ~one step (0.8): the body sways with every real step, the instantaneous velocity says little about the speed. 0 = instantaneous.")
    stride_per_command: bool = xax.field(value=False, help="Stride target = commanded speed / gait frequency (at most stride_target) instead of a fixed stride_target, which pays for walking faster than the command.")
    stride_needs_command: bool = xax.field(value=False, help="Stride reward only while a forward speed is commanded: otherwise it pays for walking on at command 0.")
    foot_friction_min: float = xax.field(value=0.2, help="Foot/floor friction, lower bound per environment (domain_randomize). Laminate measured ~0.2 on 2026-11-01, uncalibrated.")
    foot_friction_max: float = xax.field(value=1.2, help="Foot/floor friction, upper bound per environment (domain_randomize).")
    foot_friction_log: bool = xax.field(value=False, help="Draw the foot friction log-uniformly: half the environments below the geometric mean. servo_fric1 (uniform 0.1-1.5, 21 % below 0.4) fell 15-16 of 16 at mu 0.1-0.2, 3 of 16 at mu 0.8-1.5.")
    foot_condim: int = xax.field(value=3, help="condim of the foot-floor <pair>s. 3 (all policies up to servo_rubber24): sliding friction only, a foot on one edge spins freely. 4: plus torsional friction (the real rubber sole holds against twisting, 23.11.2026).")
    foot_torsion: str = xax.field(value="", help="'min,max' torsional friction of the foot pairs in m, uniform per environment (domain_randomize, needs foot_condim >= 4). Empty = the model's 0.005.")
    imu_tilt_deg: float = xax.field(value=0.0, help="Constant IMU tilt per environment, up to this angle (domain_randomize). The real IMU differs from the model by 4-8 deg. 0 = off.")
    forward_progress_reward: float = xax.field(value=0.0, help="Scale of the forward speed as a share of the command (-1..1, 0 at command 0), e.g. 10: makes walking pay more than stepping on the spot.")
    forward_progress_peak: bool = xax.field(value=False, help="Forward progress peaks at the command and falls again above it (2 - v/cmd), so overspeed stops paying.")
    caps_temporal: float = xax.field(value=0.0, help="CAPS-style loss term (not a reward): weight on the squared second difference of the MEAN action over consecutive steps. Hits the 5-6 Hz zig-zag ~1000x harder than a 1 Hz gait. e.g. 1.0")
    caps_spatial: float = xax.field(value=0.0, help="CAPS-style loss term: weight on the squared change of the mean action when the sensor inputs (joint pos/vel, IMU) get small noise; lowers the loop gain that drives the dead-time oscillation. e.g. 1.0")
    forward_progress_peak_tol: float = xax.field(value=0.0, help="With forward_progress_peak: full reward from 1x up to (1 + tol)x the command, then falling, 0 at (2 + tol)x.")
    track_norm: str = xax.field(value="l2", help="Tracking error norm: 'l2' exp(-err^2/scale) (flat far from the command: with a strict scale a 5 cm/s drift earned 0 and no gradient - servo_ctrl_v13/v16 walked backwards unnoticed), 'l1' exp(-|err|/scale) (sharp at the command, a slope everywhere).")


class ZbotWalkingTask(ZbotTask[ZbotWalkingTaskConfig, ZbotModel]):
    @property
    def get_input_shapes(self) -> list[tuple[int, ...]]:
        return [(self.num_actor_inputs,)]

    @property
    def num_actor_inputs(self) -> int:
        return NUM_INPUTS + (2 if self.config.heading_obs else 0) + NUM_OUTPUTS * (self.config.action_history - 1)

    def get_optimizer(self) -> optax.GradientTransformation:
        """Builds the optimizer.

        This provides a reasonable default optimizer for training PPO models,
        but can be overridden by subclasses who want to do something different.
        """
        optimizer = optax.chain(
            optax.clip_by_global_norm(self.config.max_grad_norm),
            (
                optax.adam(self.config.learning_rate)
                if self.config.adam_weight_decay == 0.0
                else optax.adamw(self.config.learning_rate, weight_decay=self.config.adam_weight_decay)
            ),
        )

        return optimizer

    def get_physics_randomizers(self, physics_model: ksim.PhysicsModel) -> list[ksim.PhysicsRandomizer]:
        if self.config.domain_randomize:
            return [
                FootFrictionRandomizer(mu_lower=self.config.foot_friction_min, mu_upper=self.config.foot_friction_max,
                                       log_uniform=self.config.foot_friction_log,
                                       **({"torsion_lower": float(self.config.foot_torsion.split(",")[0]),
                                           "torsion_upper": float(self.config.foot_torsion.split(",")[1])}
                                          if self.config.foot_torsion else {})),
                ksim.StaticFrictionRandomizer(scale_lower=0.5, scale_upper=1.5),
                ksim.ArmatureRandomizer(),
                ksim.MassAdditionRandomizer.from_body_name(
                    physics_model, self.config.torso_body_name, scale_lower=-0.5, scale_upper=0.5
                ),
                ksim.JointDampingRandomizer(scale_lower=0.95, scale_upper=1.05),
                ksim.JointZeroPositionRandomizer(scale_lower=-0.05, scale_upper=0.05),
                *([ImuTiltRandomizer.from_site_name(physics_model, "imu", self.config.imu_tilt_deg)]
                  if self.config.imu_tilt_deg > 0 else []),
            ]
        else:
            return []

    def get_resets(self, physics_model: ksim.PhysicsModel) -> list[ksim.Reset]:
        scale = 0.01 if self.config.domain_randomize else 0.0
        start = [CenterPoseReset.from_model(physics_model, self.config.center_pose_deg)] \
            if self.config.start_pose == "center" else []
        return start + [
            ksim.RandomBaseVelocityXYReset(scale=scale),
            ksim.RandomJointPositionReset(scale=scale),
            ksim.RandomJointVelocityReset(scale=scale),
        ]

    def get_events(self, physics_model: ksim.PhysicsModel) -> list[ksim.Event]:
        if self.config.domain_randomize:
            return [
                XYPushEvent(
                    interval_range=(2.0, 4.0),
                    force_range=(0.0, 0.5),
                ),
                TorquePushEvent(
                    interval_range=(2.0, 4.0),
                    ang_vel_range=(0.0, 0.5),
                ),
            ]
        else:
            return []

    def get_curriculum(self, physics_model: ksim.PhysicsModel) -> Curriculum:
        return ksim.EpisodeLengthCurriculum(
            num_levels=10,
            increase_threshold=20.0,
            decrease_threshold=10.0,
            min_level_steps=5,
            dt=self.config.ctrl_dt,  # not sure what this is for
        )

    def get_observations(self, physics_model: ksim.PhysicsModel) -> list[ksim.Observation]:
        if self.config.action_history > 1 and not self.config.servo_model:
            raise ValueError("action_history > 1 keeps the actions in the servo model's state: needs servo_model=True")
        if self.config.domain_randomize:
            joint_pos_noise = 0.1
            vel_obs_noise = 2.5
            imu_acc_noise = 0.5
            imu_gyro_noise = 0.5
            gvec_noise = 0.08
            base_position_noise = 0.0
            base_orientation_noise = 0.0
            base_linear_velocity_noise = 0.0
            base_angular_velocity_noise = 0.0
            base_angular_velocity_noise = 0.0
        else:
            joint_pos_noise = 0.0
            vel_obs_noise = 0.0
            imu_acc_noise = 0.0
            imu_gyro_noise = 0.0
            gvec_noise = 0.0
            base_position_noise = 0.0
            base_orientation_noise = 0.0
            base_linear_velocity_noise = 0.0
            base_angular_velocity_noise = 0.0
            base_angular_velocity_noise = 0.0
        return [
            TimestepPhaseObservation(),
            JointPositionObservation(noise=joint_pos_noise),
            JointVelocityObservation(noise=vel_obs_noise),
            ksim.ActuatorForceObservation(),
            ksim.SensorObservation.create(physics_model=physics_model, sensor_name="imu_acc", noise=imu_acc_noise),
            ksim.SensorObservation.create(physics_model=physics_model, sensor_name="imu_gyro", noise=imu_gyro_noise),
            ProjectedGravityObservation(noise=gvec_noise),
            LastActionObservation(noise=0.0),
            ksim.BasePositionObservation(noise=base_position_noise),
            ksim.BaseOrientationObservation(noise=base_orientation_noise),
            ksim.BaseLinearVelocityObservation(noise=base_linear_velocity_noise),
            ksim.BaseAngularVelocityObservation(noise=base_angular_velocity_noise),
            ksim.CenterOfMassVelocityObservation(),
            ksim.SensorObservation.create(physics_model=physics_model, sensor_name="left_foot_force", noise=0.0),
            ksim.SensorObservation.create(physics_model=physics_model, sensor_name="right_foot_force", noise=0.0),
            FeetContactObservation.create(
                physics_model=physics_model,
                foot_left_geom_names=sole_geoms(physics_model, "Left"),
                foot_right_geom_names=sole_geoms(physics_model, "Right"),
                floor_geom_names="floor",
            ),
            FeetPositionObservation.create(
                physics_model=physics_model,
                foot_left_site_name="left_foot",
                foot_right_site_name="right_foot",
                floor_threshold=0.00,
            ),
            ContactObservation.create(
                physics_model=physics_model,
                geom_names=["Left_Foot_collision_box", "Right_Foot_collision_box"],
                contact_group="feet",
                noise=0.0,
            ),
            TrueHeightObservation(),
            # world-frame base velocities from the IMU-site sensors (used by the tracking rewards only)
            ksim.SensorObservation.create(physics_model=physics_model, sensor_name="base_link_vel", noise=0.0),
            ksim.SensorObservation.create(physics_model=physics_model, sensor_name="base_link_ang_vel", noise=0.0),
            *([BaseHeadingObservation(noise=0.05 if self.config.domain_randomize else 0.0)] if self.config.heading_obs else []),
            *([ActionHistoryObservation(steps=self.config.action_history - 1)] if self.config.action_history > 1 else []),
        ]

    def get_commands(self, physics_model: ksim.PhysicsModel) -> list[ksim.Command]:
        if self.config.velocity_tracking:
            return [
                LinearVelocityCommand(
                    x_range=(self.config.target_speed_min, self.config.target_speed_max),
                    y_range=(0.0, 0.0),
                    x_zero_prob=self.config.speed_zero_prob,
                    y_zero_prob=1.0,
                    switch_prob=self.config.ctrl_dt / 5,
                ),
                AngularVelocityCommand(scale=0.0, zero_prob=1.0, switch_prob=self.config.ctrl_dt / 5),
                GaitFrequencyCommand(
                    gait_freq_lower=self.config.gait_freq_lower,
                    gait_freq_upper=self.config.gait_freq_upper,
                ),
            ]
        # NOTE: increase to 360
        return [
            LinearVelocityCommand(
                x_range=(-0.2, 0.2),
                y_range=(-0.1, 0.1),
                x_zero_prob=0.1,
                y_zero_prob=0.2,
                switch_prob=self.config.ctrl_dt / 3,
            ),
            AngularVelocityCommand(
                scale=0.1,
                zero_prob=0.9,
                switch_prob=self.config.ctrl_dt / 3,
            ),
            GaitFrequencyCommand(
                gait_freq_lower=self.config.gait_freq_lower,
                gait_freq_upper=self.config.gait_freq_upper,
            ),
        ]

    def get_rewards(self, physics_model: ksim.PhysicsModel) -> list[ksim.Reward]:
        shaping: list[ksim.Reward] = []
        if self.config.gait_shaping:
            shaping = [
                ksim.LinearVelocityPenalty(index="y", scale=self.config.gait_lateral_penalty),
                ksim.AngularVelocityPenalty(index="z", scale=self.config.gait_yaw_penalty),
                ksim.ActionSmoothnessPenalty(scale=self.config.gait_smooth_penalty),
            ]
            if self.config.gait_step_reward:
                shaping.append(ksim.FeetNoContactReward(window_size=5, scale=self.config.gait_step_reward))
            if self.config.gait_single_support:
                shaping.append(SingleSupportReward(scale=self.config.gait_single_support))
            if self.config.feet_slip_penalty:
                shaping.append(FeetSlipPenalty(ctrl_dt=self.config.ctrl_dt, scale=self.config.feet_slip_penalty))
            if self.config.foot_flat_penalty:
                from ksim.utils.mujoco import get_body_data_idx_from_name
                shaping.append(FootFlatPenalty(left_body=get_body_data_idx_from_name(physics_model, "left_ankle_pitch_link"),
                                               right_body=get_body_data_idx_from_name(physics_model, "right_ankle_pitch_link"),
                                               deadzone=float(np.radians(self.config.foot_flat_deadzone_deg)),
                                               scale=self.config.foot_flat_penalty))
            if self.config.gait_swing_reward:
                shaping.append(SwingDurationReward(ctrl_dt=self.config.ctrl_dt, t_min=self.config.gait_swing_tmin,
                                                   t_max=self.config.gait_swing_tmax, dense=self.config.gait_swing_dense,
                                                   scale=self.config.gait_swing_reward))
            if self.config.gait_flip_penalty:
                shaping.append(ContactFlipPenalty(scale=self.config.gait_flip_penalty))
            if self.config.gait_clearance_reward:
                shaping.append(FootClearanceReward(target=self.config.gait_clearance_target, scale=self.config.gait_clearance_reward))
            if self.config.foot_lift_penalty:
                shaping.append(FootLiftPenalty(max_lift=self.config.foot_lift_max, scale=self.config.foot_lift_penalty))
            if self.config.joint_deviation_penalty:
                from mujoco_scenes.mjcf import load_mjmodel
                mj = load_mjmodel(os.path.join(self.config.robot_urdf_path, "robot.mjcf"), scene="smooth")
                names = [mj.joint(i).name for i in range(1, mj.njnt)]
                subs = [t.strip() for t in self.config.joint_deviation_joints.split(",") if t.strip()]
                idx = tuple(i for i, n in enumerate(names) if any(t in n for t in subs))
                shaping.append(JointDeviationPenalty(joint_indices=idx, scale=self.config.joint_deviation_penalty))
            if self.config.roll_penalty:
                shaping.append(BaseRollPenalty(scale=self.config.roll_penalty))
            if self.config.joint_velocity_penalty:
                shaping.append(MeanJointSpeedPenalty(scale=self.config.joint_velocity_penalty))
            if self.config.heading_penalty:
                shaping.append(HeadingPenalty(scale=self.config.heading_penalty))
            if self.config.lateral_position_penalty:
                shaping.append(LateralPositionPenalty(scale=self.config.lateral_position_penalty))
            if self.config.target_gap_penalty:
                shaping.append(TargetGapPenalty(scale=self.config.target_gap_penalty))
            if self.config.action_saturation_penalty:
                shaping.append(ActionSaturationPenalty(scale=self.config.action_saturation_penalty))
            if self.config.action_step_limit_penalty:
                shaping.append(ActionStepLimitPenalty.from_model(
                    physics_model, self.config.cmd_rate_fraction,
                    self.config.leg_servo_speed * 2.0 * math.pi / 4096.0, self.config.arm_v_max, self.config.ctrl_dt,
                    self.config.action_step_limit_penalty))
            if self.config.joint_accel_penalty:
                shaping.append(JointAccelerationPenalty(scale=self.config.joint_accel_penalty))
            if self.config.stride_reward:
                shaping.append(StrideLengthReward(target=self.config.stride_target, min_swing=self.config.stride_min_swing,
                                                  ctrl_dt=self.config.ctrl_dt, needs_command=self.config.stride_needs_command,
                                                  per_command=self.config.stride_per_command,
                                                  scale=self.config.stride_reward))
            if self.config.gait_clock_reward:
                shaping.append(GaitClockReward(scale=self.config.gait_clock_reward))
            if self.config.action_jerk_penalty:
                shaping.append(ActionJerkPenalty(scale=self.config.action_jerk_penalty))
            if self.config.joint_speed_limit_penalty:
                shaping.append(JointSpeedLimitPenalty.from_model(
                    physics_model, self.config.leg_servo_speed * 2.0 * math.pi / 4096.0 * self.config.joint_speed_limit_fraction,
                    self.config.arm_v_max * self.config.joint_speed_limit_fraction, self.config.joint_speed_limit_penalty))
            if self.config.target_limit_penalty:
                shaping.append(TargetLimitPenalty.from_model(physics_model, self.config.target_limit_penalty))
            if self.config.joint_limit_penalty:
                shaping.append(JointLimitPenalty.from_model(physics_model, self.config.joint_limit_margin_deg,
                                                            self.config.joint_limit_penalty, self.config.joint_limit_sum))
        if self.config.velocity_tracking:
            return [
                DHHealthyReward(scale=0.5),
                TerminationPenalty(scale=-5.0),
                LinearVelocityTrackingReward(scale=self.config.track_reward_scale, error_scale=self.config.track_error_scale,
                                             norm=self.config.track_norm,
                                             window_steps=max(1, round(self.config.track_window_s / self.config.ctrl_dt))),
                AngularVelocityTrackingReward(scale=0.75),
                OrientationPenalty(scale=-2.0),
                FeetContactPenalty(contact_obs_key="contact_observation_feet", scale=-2.0),
                *([NaiveVelocityReward(scale=self.config.naive_velocity_scale, cap=self.config.naive_velocity_cap)]
                  if self.config.naive_velocity_scale else []),
                *([ForwardProgressReward(window_steps=max(1, round((self.config.track_window_s or 0.8) / self.config.ctrl_dt)),
                                         scale=self.config.forward_progress_reward,
                                         peak=self.config.forward_progress_peak,
                                         peak_tol=self.config.forward_progress_peak_tol)]
                  if self.config.forward_progress_reward else []),
            ] + shaping
        return shaping + [
            # JointDeviationPenalty(scale=-1.0),
            # JointDeviationPenalty(scale=-1.0),
            # DHControlPenalty(scale=-0.05),
            DHHealthyReward(scale=0.5),
            # DHControlPenalty(scale=-0.01),
            TerminationPenalty(scale=-5.0),
            # LinearVelocityTrackingReward(scale=2.0),
            # AngularVelocityTrackingReward(scale=0.75),
            OrientationPenalty(scale=-2.0),
            FeetContactPenalty(
                contact_obs_key="contact_observation_feet",
                scale=-2.0,
            ),
            NaiveVelocityReward(scale=1.0),
        ]

    def get_terminations(self, physics_model: ksim.PhysicsModel) -> list[ksim.Termination]:
        return [
            ksim.RollTooGreatTermination(max_roll=1.04),
            ksim.PitchTooGreatTermination(max_pitch=1.04),
        ]

    def get_model(self, key: PRNGKeyArray) -> ZbotModel:
        clip = {}
        if self.config.action_clip_margin_deg > 0:   # raw MJCF, like export_policy.py (get_mujoco_model is not traceable here)
            from mujoco_scenes.mjcf import load_mjmodel
            clip = action_clip_bounds(load_mjmodel(os.path.join(self.config.robot_urdf_path, "robot.mjcf"), scene="smooth"),
                                      self.config.action_clip_margin_deg, self.config.action_clip_reserve_deg)
        return ZbotModel(key, num_inputs=self.num_actor_inputs, **clip)

    def get_initial_model_carry(self, rng: PRNGKeyArray) -> Array:
        return jnp.zeros(0)

    def _run_actor(
        self,
        model: ZbotModel,
        observations: FrozenDict[str, Array],
        commands: FrozenDict[str, Array],
    ) -> distrax.Normal:
        timestep_phase_4 = observations["timestep_phase_observation"]
        joint_pos_n = observations["joint_position_observation"]
        joint_vel_n = observations["joint_velocity_observation"]
        imu_acc_3 = observations["sensor_observation_imu_acc"]
        imu_gyro_3 = observations["sensor_observation_imu_gyro"]
        lin_vel_cmd_2 = commands["linear_velocity_command"]
        ang_vel_cmd_1 = commands["angular_velocity_command"]
        gait_freq_cmd_1 = commands["gait_frequency_command"]
        last_action_n = observations["last_action_observation"]
        heading_2 = observations["base_heading_observation"] if self.config.heading_obs else None
        action_history_m = (observations["action_history_observation"] if self.config.action_history > 1 else None)
        return model.actor.forward(
            timestep_phase_4=timestep_phase_4,
            joint_pos_n=joint_pos_n,
            joint_vel_n=joint_vel_n,
            imu_acc_3=imu_acc_3,
            imu_gyro_3=imu_gyro_3,
            lin_vel_cmd_2=lin_vel_cmd_2,
            ang_vel_cmd_1=ang_vel_cmd_1,
            gait_freq_cmd_1=gait_freq_cmd_1,
            last_action_n=last_action_n,
            heading_2=heading_2,
            action_history_m=action_history_m,
        )

    def _run_critic(
        self,
        model: ZbotModel,
        observations: FrozenDict[str, Array],
        commands: FrozenDict[str, Array],
    ) -> Array:
        timestep_phase_4 = observations["timestep_phase_observation"]
        joint_pos_n = observations["joint_position_observation"]
        joint_vel_n = observations["joint_velocity_observation"]
        imu_acc_3 = observations["sensor_observation_imu_acc"]
        imu_gyro_3 = observations["sensor_observation_imu_gyro"]
        lin_vel_cmd_2 = commands["linear_velocity_command"]
        ang_vel_cmd_1 = commands["angular_velocity_command"]
        gait_freq_cmd = commands["gait_frequency_command"]
        last_action_n = observations["last_action_observation"]
        # Critic obs
        feet_colliding_2 = observations["contact_observation_feet"]
        feet_contact_2 = observations["feet_contact_observation"]
        feet_position_6 = observations["feet_position_observation"]
        projected_gravity_3 = observations["projected_gravity_observation"]
        base_position_3 = observations["base_position_observation"]
        base_orientation_4 = observations["base_orientation_observation"]
        base_linear_velocity_3 = observations["base_linear_velocity_observation"]
        base_angular_velocity_3 = observations["base_angular_velocity_observation"]
        actuator_force_n = observations["actuator_force_observation"]
        true_height_1 = observations["true_height_observation"]

        return model.critic.forward(
            timestep_phase_4=timestep_phase_4,
            joint_pos_n=joint_pos_n,
            joint_vel_n=joint_vel_n,
            imu_acc_3=imu_acc_3,
            imu_gyro_3=imu_gyro_3,
            lin_vel_cmd_2=lin_vel_cmd_2,
            ang_vel_cmd_1=ang_vel_cmd_1,
            gait_freq_cmd_1=gait_freq_cmd,
            last_action_n=last_action_n,
            # critic observations
            feet_colliding_2=feet_colliding_2,
            feet_contact_2=feet_contact_2,
            feet_position_6=feet_position_6,
            projected_gravity_3=projected_gravity_3,
            base_position_3=base_position_3,
            base_orientation_4=base_orientation_4,
            base_linear_velocity_3=base_linear_velocity_3,
            base_angular_velocity_3=base_angular_velocity_3,
            actuator_force_n=actuator_force_n,
            true_height_1=true_height_1,
        )

    def get_ppo_variables(
        self,
        model: ZbotModel,
        trajectories: ksim.Trajectory,
        carry: None,
        rng: PRNGKeyArray,
    ) -> tuple[ksim.PPOVariables, Array]:
        # Vectorize over the time dimensions.

        def get_log_prob(transition: ksim.Trajectory) -> Array:
            action_dist_n = self._run_actor(model, transition.obs, transition.command)
            log_probs_n = action_dist_n.log_prob(transition.action / model.actor.mean_scale)
            return log_probs_n

        log_probs_tn = jax.vmap(get_log_prob)(trajectories)

        values_tn = jax.vmap(self._run_critic, in_axes=(None, 0, 0))(model, trajectories.obs, trajectories.command)

        ppo_variables = ksim.PPOVariables(
            log_probs=log_probs_tn,
            values=values_tn.squeeze(-1),
        )

        return ppo_variables, jnp.zeros(0)

    def get_loss_and_metrics(self, model_arr, model_static, trajectories, rewards, init_carry, on_policy_variables, rng):
        """PPO loss plus CAPS smoothness terms on the mean action (Mysore et al. 2021). As rewards the jitter penalties
        cost PPO almost nothing (servo_ctrl_v4: ~3 % of the return) and stronger ones made it stop walking
        (servo_ctrl_v5/v6); as a loss term the gradient goes straight into the actor, no credit assignment needed."""
        rng, rng_s = jax.random.split(rng)
        loss, aux = super().get_loss_and_metrics(model_arr, model_static, trajectories, rewards, init_carry,
                                                 on_policy_variables, rng)
        if not (self.config.caps_temporal or self.config.caps_spatial):
            return loss, aux
        model = eqx.combine(model_arr, model_static)
        mean_fn = lambda obs, cmd: self._run_actor(model, obs, cmd).mode()
        mean_fn = jax.vmap(jax.vmap(mean_fn))                            # over batch and time
        mu = mean_fn(trajectories.obs, trajectories.command)            # (B, T, n)
        valid = ~trajectories.done
        extra = jnp.zeros(())
        if self.config.caps_temporal:
            jerk = mu[:, 2:] - 2 * mu[:, 1:-1] + mu[:, :-2]
            ok = valid[:, 2:] & valid[:, 1:-1] & valid[:, :-2]
            extra += self.config.caps_temporal * ((jerk ** 2).mean(-1) * ok).sum() / (ok.sum() + 1e-6)
        if self.config.caps_spatial:
            sigma = {"joint_position_observation": 0.01, "joint_velocity_observation": 0.1,
                     "sensor_observation_imu_gyro": 0.05, "sensor_observation_imu_acc": 0.1}
            obs = dict(trajectories.obs)
            for k, (name, sd) in zip(jax.random.split(rng_s, len(sigma)), sigma.items()):
                obs[name] = obs[name] + sd * jax.random.normal(k, obs[name].shape)
            mu_n = mean_fn(FrozenDict(obs), trajectories.command)
            extra += self.config.caps_spatial * (((mu_n - mu) ** 2).mean(-1) * valid).sum() / (valid.sum() + 1e-6)
        return loss + extra, aux

    def sample_action(
        self,
        model: ZbotModel,
        model_carry: Array,
        physics_model: ksim.PhysicsModel,
        physics_state: PhysicsState,
        observations: FrozenDict[str, Array],
        commands: FrozenDict[str, Array],
        rng: PRNGKeyArray,
        argmax: bool = False,
    ) -> ksim.Action:
        action_dist_n = self._run_actor(model, observations, commands)
        action_n = action_dist_n.sample(seed=rng) if not argmax else action_dist_n.mode()
        action_n = action_n * self.config.action_scale
        return ksim.Action(action=action_n, carry=jnp.zeros(0), aux_outputs=None)


def default_config(**overrides: object) -> ZbotWalkingTaskConfig:
    """The training configuration (also used by sim/tools/export_policy.py to rebuild the task for a checkpoint)."""
    kwargs: dict[str, object] = dict(
        num_envs=4096,
        batch_size=256,
        num_passes=10,
        epochs_per_log_step=1,
        # Simulation parameters.
        dt=0.002,
        ctrl_dt=0.02,
        max_action_latency=0.005,
        min_action_latency=0.0,
        valid_every_n_steps=5,
        save_every_n_steps=5,
        rollout_length_seconds=5.0,
        # PPO parameters
        gamma=0.97,
        lam=0.95,
        entropy_coef=0.001,
        learning_rate=3e-4,
        clip_param=0.3,
        max_grad_norm=1.0,
        export_for_inference=True,
    )
    kwargs.update(overrides)
    return ZbotWalkingTaskConfig(**kwargs)  # type: ignore[arg-type]


if __name__ == "__main__":
    # python -m sim.train.walking run_environment=True
    ZbotWalkingTask.launch(default_config())
