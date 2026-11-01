#!/usr/bin/env bash
# Controlled walking, reward concept v3 (2026-10-26), FROM SCRATCH. What servo_ctrl_v1 taught us (demo: stepping on the
# spot, jittery legs; gate: tracking 0.4, 35 % of the leg spectrum above 5 Hz):
#   * the raw policy chattered (action jerk 0.34 rad/step^2, 88 % of the joint-steps asked for more than the command
#     rate limiter's step) and the limiter turned that into a 25 Hz zig-zag for the servos
#       -> action_step_limit_penalty (asking for more than the limiter lets through) + action_jerk_penalty (2nd difference)
#   * swing / clearance / single-support rewards pay for marching on the spot, tracking alone hardly punishes it
#       -> those rewards lowered, tracking stronger and wider (gradient from standing still), naive forward reward x6
#   * speed 0.08-0.14 m/s (a real stride, still inside the 70 % servo budget), gait 1.0-1.5 Hz
# Penalty scales are half of what would match the tracking reward on the jittery policy: a random policy at the start
# would otherwise learn that standing still is cheapest. Hard limits stay structural (rate limiter, joint-limit clamp).
# From scratch: the warm-started runs kept their bang-bang habits under every penalty.
set -euo pipefail
cd "$(dirname "$0")/../.."
VENV="$HOME/Documents/stash/ksim-zbot/.venv"
RUN=servo_ctrl_v2
GPU=1 ASSETS=zbot-cad sim/tools/train_backpack.sh "$RUN" \
  servo_model=True servo_kp=32 dt=0.002 leg_servo_speed=2000 start_pose=center hip_yaw_range_deg=30 \
  clamp_to_real_limits=True cmd_rate_fraction=0.7 export_for_inference=False \
  velocity_tracking=True gait_shaping=True heading_obs=True \
  target_speed_min=0.08 target_speed_max=0.14 track_reward_scale=6.0 track_error_scale=0.12 naive_velocity_scale=1.5 \
  gait_freq_lower=1.0 gait_freq_upper=1.5 gait_swing_reward=0.3 gait_swing_tmin=0.3 gait_swing_tmax=0.6 \
  gait_step_reward=0.0 gait_single_support=0.1 gait_flip_penalty=-0.1 gait_clearance_reward=0.2 gait_clearance_target=0.02 \
  foot_lift_penalty=-1.0 foot_lift_max=0.03 feet_slip_penalty=-0.3 heading_penalty=-1.0 lateral_position_penalty=-0.5 \
  gait_lateral_penalty=-1.0 roll_penalty=-3.0 joint_deviation_penalty=-0.5 joint_velocity_penalty=-0.05 \
  gait_smooth_penalty=-1.0 target_gap_penalty=-0.25 action_saturation_penalty=-0.5 \
  action_step_limit_penalty=-0.025 action_jerk_penalty=-0.5 \
  joint_limit_penalty=-0.5 target_limit_penalty=-4.0 joint_speed_limit_penalty=-1.0 joint_speed_limit_fraction=0.7 \
  max_steps=3000
systemctl --user reset-failed "zbot-calmwatch-$RUN" 2>/dev/null || true
systemd-run --user --collect --quiet --unit="zbot-calmwatch-$RUN" -p Restart=on-failure -p RestartSec=60 \
  -p WorkingDirectory="$PWD" -E HOME="$HOME" -E PATH="$PATH" "$VENV/bin/python" sim/tools/calm_watch.py "$RUN" \
  --interval 40 --window 6 --min-iters 600 --eval-gpu 0
echo "watcher zbot-calmwatch-$RUN started"
