#!/usr/bin/env bash
# Controlled walking, concept v4 (2026-10-27). Continues servo_ctrl_v2 at step 670 (walks, no falls, but the user saw
# "the strongest jitter so far" and tiny tripping steps). Measured on its rollouts: 7.2 touchdowns per foot and second
# against a 1.0-1.5 Hz gait command, median stride 5 mm, 33-57 % of the leg motion above 5 Hz. The chatter penalties on
# the raw action (v2) did not reach the joints because the limiter and the servo model smoothed the chatter away
# before it cost anything. So:
#   * action_filter_alpha=0.2  low-pass on the action, in the sim AND in the Pi runner (policy_meta.json): a zig-zag at
#                              half the control rate passes at 11 %, 10 Hz at ~19 %, the gait at ~83 %
#   * joint_accel_penalty      punishes what a video shows: (qvel(t) - qvel(t-1))^2 of the joints
#   * gait_clock_reward        feet swing / stand with the commanded gait clock (they ignored it: 7 Hz vibration)
#   * stride_reward            forward foot travel per real step (>= 0.2 s swing), full at 8 cm
#   * gait_flip_penalty -0.5   (was -0.1) contact flicker
# Everything else as servo_ctrl_v2. Watcher: video every 100 iterations into <run>/videos for the training film.
set -euo pipefail
cd "$(dirname "$0")/../.."
VENV="$HOME/Documents/stash/ksim-zbot/.venv"
RUN=servo_ctrl_v3
GPU=1 ASSETS=zbot-cad sim/tools/train_backpack.sh "$RUN" \
  servo_model=True servo_kp=32 dt=0.002 leg_servo_speed=2000 start_pose=center hip_yaw_range_deg=30 \
  clamp_to_real_limits=True cmd_rate_fraction=0.7 action_filter_alpha=0.2 export_for_inference=False \
  velocity_tracking=True gait_shaping=True heading_obs=True \
  target_speed_min=0.08 target_speed_max=0.14 track_reward_scale=6.0 track_error_scale=0.12 naive_velocity_scale=1.5 \
  gait_freq_lower=1.0 gait_freq_upper=1.5 gait_swing_reward=0.3 gait_swing_tmin=0.3 gait_swing_tmax=0.6 \
  gait_step_reward=0.0 gait_single_support=0.1 gait_flip_penalty=-0.5 gait_clearance_reward=0.2 gait_clearance_target=0.02 \
  gait_clock_reward=1.0 stride_reward=15.0 stride_target=0.08 stride_min_swing=0.2 joint_accel_penalty=-0.1 \
  foot_lift_penalty=-1.0 foot_lift_max=0.03 feet_slip_penalty=-0.3 heading_penalty=-1.0 lateral_position_penalty=-0.5 \
  gait_lateral_penalty=-1.0 roll_penalty=-3.0 joint_deviation_penalty=-0.5 joint_velocity_penalty=-0.05 \
  gait_smooth_penalty=-1.0 target_gap_penalty=-0.25 action_saturation_penalty=-0.5 \
  action_step_limit_penalty=-0.025 action_jerk_penalty=-0.5 \
  joint_limit_penalty=-0.5 target_limit_penalty=-4.0 joint_speed_limit_penalty=-1.0 joint_speed_limit_fraction=0.7 \
  max_steps=3670 load_from_ckpt_path="$PWD/sim/train/zbot_walking_task/servo_ctrl_v2/snapshots/ckpt.670.bin"
systemctl --user reset-failed "zbot-calmwatch-$RUN" 2>/dev/null || true
systemd-run --user --collect --quiet --unit="zbot-calmwatch-$RUN" -p Restart=on-failure -p RestartSec=60 \
  -p WorkingDirectory="$PWD" -E HOME="$HOME" -E PATH="$PATH" "$VENV/bin/python" sim/tools/calm_watch.py "$RUN" \
  --interval 40 --window 6 --min-iters 400 --eval-gpu 0 --video-every 100
echo "watcher zbot-calmwatch-$RUN started"
