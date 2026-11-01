#!/usr/bin/env bash
# First training run with the servo model measured on the robot (bench tests 2026-10-25). NOT STARTED YET.
#
# Differences to cad2_v13_tiny (same rewards, same observation layout, so the Pi runner needs no change):
#   servo_model=True        per-joint speed limit, acceleration limit and command delay (sim/train/common.py)
#   leg_servo_speed=2000    legs follow the speed register the Pi sends: use "speed": 2000 in /policy/start
#   dt=0.002                same physics step as every earlier run (config.yaml of cad2_*). NOTE: the config class
#                           default is 0.005, and at 5 ms the joint damping (kd 3) is numerically unstable - never
#                           leave dt at its default for this robot
#   servo_kp=32             the P register of the real servos (sag test: ~45 Nm/rad on the legs, 2x the old kp 16)
#   start_pose=center       episodes start in the real centre pose (hips +18.7 / -16.1), not upright at zero
#   hip_yaw_range_deg=30    hip yaw limited to +-30 deg in the sim (the real joint: [-90, 5] / [-3, 90])
#   gait_smooth_penalty=-0.5  action smoothness, was -0.2 (a guess: the old policies were bang-bang)
#
# Before starting: the local LLM (vLLM) holds both GPUs (~22 GB each) -> stop it first (sim/tools/text-modus.sh /
# bild-modus.sh switch it; see the memory note on GPU exclusivity). Warm start from the best old policy; for a
# from-scratch run drop load_from_ckpt_path and raise max_steps.   max_steps is an absolute step count (guess).
set -euo pipefail
cd "$(dirname "$0")/../.."
GPU=1 ASSETS=zbot-cad sim/tools/train_backpack.sh servo_v1 \
  servo_model=True servo_kp=32 dt=0.002 leg_servo_speed=2000 start_pose=center hip_yaw_range_deg=30 \
  velocity_tracking=True gait_shaping=True target_speed_min=0.05 target_speed_max=0.10 \
  track_reward_scale=5.0 track_error_scale=0.05 gait_step_reward=0.0 gait_single_support=0.0 feet_slip_penalty=-0.3 \
  gait_swing_reward=1.0 gait_flip_penalty=-0.1 gait_clearance_reward=0.5 gait_clearance_target=0.015 \
  heading_penalty=-1.0 lateral_position_penalty=-0.5 gait_swing_tmin=0.2 gait_swing_tmax=0.35 heading_obs=True \
  gait_smooth_penalty=-0.5 foot_lift_penalty=-0.5 foot_lift_max=0.025 joint_deviation_penalty=-0.5 \
  roll_penalty=-3.0 joint_velocity_penalty=-0.02 gait_lateral_penalty=-1.0 max_steps=1300 \
  load_from_ckpt_path="$PWD/sim/train/zbot_walking_task/cad2_v13_tiny/snapshots/ckpt.905.bin"
