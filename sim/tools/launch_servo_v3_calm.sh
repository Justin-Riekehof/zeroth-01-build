#!/usr/bin/env bash
# Calm-gait follow-up to servo_v1. servo_v1 (ckpt 1300) took 5.5 steps/s with 200 ms swing and 9 cm foot lift
# (target 1.5 cm) and rolled/pitched ~100 deg p2p over 30 s: too hectic to deploy. Same servo model / start pose,
# same slow target speed, but the rewards push towards slow, deliberate steps:
#   gait_swing_tmin/tmax 0.3/0.5   was 0.2/0.35 (longer swing -> fewer, slower steps)
#   foot_lift_penalty -1.0, foot_lift_max 0.03, clearance target 0.02   (was -0.5 / 0.025 / 0.015)
#   gait_smooth_penalty -1.5       was -0.5 (action rate was 0.36 rad/step)
#   joint_velocity_penalty -0.05   was -0.02
#   gait_single_support 0.2        was 0
#   target_speed 0.08-0.15         was 0.05-0.10 (servo_v1 only reached 0.036 m/s)
# Warm start: servo_v1 ckpt 1300 (already adapted to the servo model). max_steps is absolute: 2100 = 800 more
# updates (~7 h at ~115 updates/h).
set -euo pipefail
cd "$(dirname "$0")/../.."
GPU="${GPU:-0}" ASSETS=zbot-cad sim/tools/train_backpack.sh servo_v3_calm \
  servo_model=True servo_kp=32 dt=0.002 leg_servo_speed=2000 start_pose=center hip_yaw_range_deg=30 \
  velocity_tracking=True gait_shaping=True target_speed_min=0.08 target_speed_max=0.15 \
  track_reward_scale=4.0 track_error_scale=0.08 gait_step_reward=0.0 gait_single_support=0.2 feet_slip_penalty=-0.3 \
  gait_swing_reward=1.0 gait_flip_penalty=-0.1 gait_clearance_reward=0.5 gait_clearance_target=0.02 \
  heading_penalty=-1.0 lateral_position_penalty=-0.5 gait_swing_tmin=0.3 gait_swing_tmax=0.5 heading_obs=True \
  gait_smooth_penalty=-1.5 foot_lift_penalty=-1.0 foot_lift_max=0.03 joint_deviation_penalty=-0.5 \
  roll_penalty=-3.0 joint_velocity_penalty=-0.05 gait_lateral_penalty=-1.0 max_steps=2100 \
  load_from_ckpt_path="$PWD/sim/train/zbot_walking_task/servo_v1/snapshots/ckpt.1300.bin"
