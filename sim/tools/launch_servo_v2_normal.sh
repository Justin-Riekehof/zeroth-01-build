#!/usr/bin/env bash
# "Normal steps" run with the measured servo model: same servo/start-pose setup as servo_v1, but the gait targets of
# cad2_v4_heading (0.31 m/s, large steps) instead of the tiny 0.05-0.10 m/s shuffle of servo_v1/v13_tiny.
#
# Differences to servo_v1:
#   target_speed 0.20-0.35        was 0.05-0.10 (v4 used 0.25-0.45; lower upper end because the servos are speed-limited)
#   gait_swing_tmin/tmax 0.25/0.6 swing 250-600 ms like v4 (servo_v1: 0.2-0.35)
#   gait_clearance_target 0.03    3 cm foot lift (servo_v1: 1.5 cm); foot_lift_penalty and joint_deviation_penalty off,
#                                 they are what kept servo_v1 small
#   gait_single_support 0.3       reward single support like v4
#   track_error_scale 0.10        looser than servo_v1 (0.05), tighter than v4 (0.15)
#   gait_smooth_penalty -0.3      still penalise bang-bang, less than servo_v1 (-0.5)
# Warm start: cad2_v4_heading (strong, large steps; same observation layout incl. heading_obs).
# max_steps counts from the warm start (servo_v1: 1300 steps ~ 87 min).
set -euo pipefail
cd "$(dirname "$0")/../.."
GPU="${GPU:-1}" ASSETS=zbot-cad sim/tools/train_backpack.sh servo_v2_normal \
  servo_model=True servo_kp=32 dt=0.002 leg_servo_speed=2000 start_pose=center hip_yaw_range_deg=30 \
  velocity_tracking=True gait_shaping=True target_speed_min=0.20 target_speed_max=0.35 \
  track_reward_scale=3.0 track_error_scale=0.10 gait_step_reward=0.0 gait_single_support=0.3 feet_slip_penalty=-0.3 \
  gait_swing_reward=1.0 gait_flip_penalty=-0.1 gait_clearance_reward=0.5 gait_clearance_target=0.03 \
  heading_penalty=-1.0 lateral_position_penalty=-0.5 gait_swing_tmin=0.25 gait_swing_tmax=0.6 heading_obs=True \
  gait_smooth_penalty=-0.3 roll_penalty=-3.0 joint_velocity_penalty=-0.02 max_steps=1200 \
  load_from_ckpt_path="$PWD/sim/policies/cad2_v4_heading_step320/ckpt.bin"
