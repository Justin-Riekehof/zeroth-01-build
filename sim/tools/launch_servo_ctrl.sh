#!/usr/bin/env bash
# Controlled walking, reward concept v2 (2026-10-26). The first calm runs (servo_calm_a/b) asked for 0.20-0.35 m/s and
# punished fast joints at the same time; the policy settled on running the servos at full speed a bit less often.
# This run removes the contradiction:
#   1. hard guarantees instead of penalties: the commanded target may move at most 70 % of the servo speed
#      (cmd_rate_fraction=0.7: legs 2.15 rad/s, arms 1.26 rad/s) and is clamped to the real joint limits - the sim does
#      it before its delay line, the Pi runner does the same from policy_meta.json, so the servos never run faster
#   2. a task that fits that budget: 0.06-0.12 m/s, gait 1.0-1.5 Hz, swing 0.3-0.6 s (was up to 0.35 m/s, 2 Hz)
#   3. penalties only shape the style (moderate, calibrated on the earlier rollouts): smoothness, target-joint gap,
#      joint/target limits, joint speed above 70 %, hip yaw/roll + arms near zero, torso roll
# export_for_inference=False: the TF SavedModel export at every checkpoint needs extra GPU memory next to XLA and
# crashed the run each time (CUDA_ERROR_OUT_OF_MEMORY, 2026-10-26); sim/tools/export_policy.py exports separately.
# Evaluations run on GPU 0 (keep it free of trainings): on the CPU they need > 8.6 GB RAM and got OOM-killed.
# Starts from servo_v3_calm (already walks slowly with the servo model). Ends via sim/tools/calm_watch.py when the
# hardware gate passes twice or progress stagnates; max_steps is only the safety cap.
set -euo pipefail
cd "$(dirname "$0")/../.."
VENV="$HOME/Documents/stash/ksim-zbot/.venv"
RUN=servo_ctrl_v1
GPU=1 ASSETS=zbot-cad sim/tools/train_backpack.sh "$RUN" \
  servo_model=True servo_kp=32 dt=0.002 leg_servo_speed=2000 start_pose=center hip_yaw_range_deg=30 \
  clamp_to_real_limits=True cmd_rate_fraction=0.7 \
  velocity_tracking=True gait_shaping=True heading_obs=True \
  target_speed_min=0.06 target_speed_max=0.12 track_reward_scale=4.0 track_error_scale=0.06 \
  gait_freq_lower=1.0 gait_freq_upper=1.5 gait_swing_reward=1.0 gait_swing_tmin=0.3 gait_swing_tmax=0.6 \
  gait_step_reward=0.0 gait_single_support=0.2 gait_flip_penalty=-0.1 gait_clearance_reward=0.5 gait_clearance_target=0.02 \
  foot_lift_penalty=-1.0 foot_lift_max=0.03 feet_slip_penalty=-0.3 heading_penalty=-1.0 lateral_position_penalty=-0.5 \
  gait_lateral_penalty=-1.0 roll_penalty=-3.0 joint_deviation_penalty=-0.5 joint_velocity_penalty=-0.05 \
  gait_smooth_penalty=-2.0 target_gap_penalty=-0.5 action_saturation_penalty=-1.0 \
  joint_limit_penalty=-1.0 target_limit_penalty=-8.0 joint_speed_limit_penalty=-1.0 joint_speed_limit_fraction=0.7 \
  export_for_inference=False max_steps=4100 load_from_ckpt_path="$PWD/sim/train/zbot_walking_task/servo_v3_calm/snapshots/ckpt.2100.bin"
systemctl --user reset-failed "zbot-calmwatch-$RUN" 2>/dev/null || true
systemd-run --user --collect --quiet --unit="zbot-calmwatch-$RUN" -p Restart=on-failure -p RestartSec=60 \
  -p WorkingDirectory="$PWD" -E HOME="$HOME" -E PATH="$PATH" "$VENV/bin/python" sim/tools/calm_watch.py "$RUN" --interval 40 --window 4 --eval-gpu 0
echo "watcher zbot-calmwatch-$RUN started"
