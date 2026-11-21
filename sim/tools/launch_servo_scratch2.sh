#!/usr/bin/env bash
# FROM SCRATCH with the lessons of servo_ctrl_v1-v30 (2026-10-27..30, docs/training-journal.md). User: "if that does not
# work, compute again completely from zero with sensible rewards and punishments".
#   model     chamfered soles (flat strip + edge capsules) - the old wide box let policies stand on its edges
#   observe   action_history=4 (commands in flight in the servo delay), delay_rand=0.02, no action filter (it is lag)
#   task      slow and steady: 0.03-0.06 m/s, 20 % zero commands (stop / step on the spot), gait 1.0-1.25 Hz
#   tracking  weight 30, l1 kernel exp(-|err|/0.03): sharp at the command and a slope everywhere (the strict l2 kernel
#             was flat beyond 2 cm/s and let v13-v27 walk backwards unnoticed)
#             over the velocity averaged across one step (0.8 s, the body sways +-15 cm/s per step), no naive forward reward:
#             servo_tpu1 walked 7 cm/s at every command, also at 0
#   steps     dense swing reward 2 (0.25 s), stride 15 for real steps under a forward command only (>= 0.2 s, full at 4 cm), contact flip -1,
#             gait clock 1 - small next to tracking (v24: swing at 40x tracking made the gait the goal, not walking)
#   feet      flat-foot penalty -8 beyond a 5 deg dead zone: heel/toe roll allowed, landing on an edge not
#   limits    servo model, rate limiter 70 %, real joint limits, speed limit penalty as in all servo runs
#   jitter    no extra penalties: the 5-6 Hz oscillation was the hopping gait, real steps removed it (v8/v9: 0.21)
# Watcher: no videos (user, 2026-10-30), stagnation only after 800 (scratch needs ~700 to walk), tracking collapse
# only after 800. Parameters: RUN, GPU (training), ASSETS (zbot-cad = printed soles, zbot-cad-tpu = TPU overshoes),
# EVAL_GPU (-1 = CPU: both GPUs train), VIDEO_EVERY, MAX_STEPS.
set -euo pipefail
cd "$(dirname "$0")/../.."
VENV="$HOME/Documents/stash/ksim-zbot/.venv"
RUN=${RUN:-servo_scratch2}
GPU=${GPU:-1} ASSETS=${ASSETS:-zbot-cad} sim/tools/train_backpack.sh "$RUN" \
  servo_model=True servo_kp=32 dt=0.002 leg_servo_speed=2000 start_pose=center hip_yaw_range_deg=30 \
  clamp_to_real_limits=True cmd_rate_fraction=0.7 export_for_inference=False \
  action_history=4 delay_rand=0.02 \
  velocity_tracking=True gait_shaping=True heading_obs=True \
  target_speed_min=0.03 target_speed_max=0.06 speed_zero_prob=0.2 \
  track_reward_scale=30.0 track_norm=l1 track_error_scale=0.03 track_window_s=0.8 naive_velocity_scale=0.0 \
  gait_freq_lower=1.0 gait_freq_upper=1.25 gait_swing_reward=2.0 gait_swing_tmin=0.25 gait_swing_tmax=0.6 gait_swing_dense=True \
  gait_step_reward=0.0 gait_single_support=0.1 gait_flip_penalty=-1.0 gait_clearance_reward=0.2 gait_clearance_target=0.02 \
  gait_clock_reward=1.0 stride_reward=15.0 stride_target=0.04 stride_min_swing=0.2 stride_needs_command=True \
  foot_flat_penalty=-8.0 foot_flat_deadzone_deg=5.0 \
  foot_lift_penalty=-1.0 foot_lift_max=0.03 feet_slip_penalty=-0.3 heading_penalty=-1.0 lateral_position_penalty=-0.5 \
  gait_lateral_penalty=-1.0 roll_penalty=-3.0 joint_deviation_penalty=-0.5 joint_velocity_penalty=-0.05 \
  gait_smooth_penalty=-1.0 target_gap_penalty=-0.25 action_saturation_penalty=-0.5 \
  action_step_limit_penalty=-0.025 action_jerk_penalty=-0.1 \
  joint_limit_penalty=-0.5 target_limit_penalty=-4.0 joint_speed_limit_penalty=-1.0 joint_speed_limit_fraction=0.7 \
  max_steps=${MAX_STEPS:-4000} "$@"
systemctl --user reset-failed "zbot-calmwatch-$RUN" 2>/dev/null || true
systemd-run --user --collect --quiet --unit="zbot-calmwatch-$RUN" -p Restart=on-failure -p RestartSec=60 \
  -p WorkingDirectory="$PWD" -E HOME="$HOME" -E PATH="$PATH" "$VENV/bin/python" sim/tools/calm_watch.py "$RUN" \
  --interval 40 --window 6 --min-iters 800 --collapse-after 800 --eval-gpu "${EVAL_GPU:-0}" --video-every "${VIDEO_EVERY:-0}"
echo "watcher zbot-calmwatch-$RUN started"
