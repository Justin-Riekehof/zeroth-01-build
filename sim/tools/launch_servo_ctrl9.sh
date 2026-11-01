#!/usr/bin/env bash
# Slow and steady, concept v7 (2026-10-28 evening). User: "langsam gehen ist nicht schlimm, hauptsache wir kommen
# kontrolliert und stetig vorwärts". servo_ctrl_v8 built real steps (0 -> 36 % swings >= 0.2 s, 3.2 hops/s, 0.24 above
# 5 Hz) but tracked only 0.30 of 0.08-0.14 m/s (~0.03 m/s) and stood < 4 s on the floor. So the task gets slower
# instead of the speed reward stronger: 0.03-0.06 m/s, full stride reward at 4 cm, gait 1.0-1.25 Hz (longer swings).
# track_error_scale 0.002 (was 0.12): the tracking reward is exp(-err^2 / scale) with the SQUARED error - at 0.12 standing
# still earned 0.90 of it at 0.11 m/s and would earn 0.98 at 0.045 m/s. At 0.002: standing ~0.37, half speed ~0.78.
# From servo_ctrl_v8 step 935, dense swing reward kept, back on GPU 1.
#
# servo_ctrl_v8: Real steps, concept v6b (2026-10-28): as servo_ctrl_v7 below, but the swing reward is DENSE (gait_swing_dense=True:
# 2 min(d / 0.25 s, 1) - 1 per swing step). v7 never made a single 0.25 s swing in 225 iterations - the +1 never
# fired, only the -1 for short swings: it hopped faster (7.3-7.8/s per foot), tracking fell to 0.41. Runs on GPU 0
# next to v7 (memory capped at 60 %; the watchers' evaluations also use GPU 0 with 30 %).
#
# servo_ctrl_v7: Real steps, concept v6 (2026-10-28). Measured on the gate rollouts of every walking policy since servo_ctrl_v2: not a
# single swing >= 0.2 s; 90-95 % of the swings < 0.1 s, 7-12 per foot and second. They move by micro-hops at 5-6 Hz:
# the "jitter" IS the gait, which is why penalising it (servo_ctrl_v5/v6: x10, x30) only cost tracking (0.84 -> 0.46)
# while the share above 5 Hz stayed at 0.40-0.43. So reward the step structure instead of fighting the oscillation:
#   * gait_swing_reward 6.0 (was 0.3)  per swing step +1 for 0.25-0.6 s swings, -1 for shorter ones: ~1/3 of tracking
#   * gait_flip_penalty -1.0 (was -0.1)  every contact change costs
#   * stride_reward 15 (min swing 0.2 s, full at 8 cm)  forward foot travel only counts for real steps
#   * gait_clock_reward 1.0  feet follow the commanded 1.0-1.5 Hz clock
# From servo_ctrl_v4 step 610 (action history, random delay; walks: tracking 0.84, no fall), jitter penalties at v4 level.
# Watcher: tracking-collapse rule only after 300 iterations (the gait has to be rebuilt), stagnation after 400.
set -euo pipefail
cd "$(dirname "$0")/../.."
VENV="$HOME/Documents/stash/ksim-zbot/.venv"
RUN=${RUN:-servo_ctrl_v9}
FROM=sim/train/zbot_walking_task/servo_ctrl_v8/snapshots/ckpt.935.bin
GPU=1 ASSETS=zbot-cad sim/tools/train_backpack.sh "$RUN" \
  servo_model=True servo_kp=32 dt=0.002 leg_servo_speed=2000 start_pose=center hip_yaw_range_deg=30 \
  clamp_to_real_limits=True cmd_rate_fraction=0.7 export_for_inference=False \
  action_history=4 delay_rand=0.02 \
  velocity_tracking=True gait_shaping=True heading_obs=True \
  target_speed_min=0.03 target_speed_max=0.06 track_reward_scale=10.0 track_error_scale=0.002 naive_velocity_scale=1.5 \
  gait_freq_lower=1.0 gait_freq_upper=1.25 gait_swing_reward=6.0 gait_swing_tmin=0.25 gait_swing_tmax=0.6 gait_swing_dense=True \
  gait_step_reward=0.0 gait_single_support=0.1 gait_flip_penalty=-1.0 gait_clearance_reward=0.2 gait_clearance_target=0.02 \
  gait_clock_reward=1.0 stride_reward=15.0 stride_target=0.04 stride_min_swing=0.2 \
  foot_lift_penalty=-1.0 foot_lift_max=0.03 feet_slip_penalty=-0.3 heading_penalty=-1.0 lateral_position_penalty=-0.5 \
  gait_lateral_penalty=-1.0 roll_penalty=-3.0 joint_deviation_penalty=-0.5 joint_velocity_penalty=-0.05 \
  gait_smooth_penalty=-1.0 target_gap_penalty=-0.25 action_saturation_penalty=-0.5 \
  action_step_limit_penalty=-0.025 action_jerk_penalty=-0.1 \
  joint_limit_penalty=-0.5 target_limit_penalty=-4.0 joint_speed_limit_penalty=-1.0 joint_speed_limit_fraction=0.7 \
  load_from_ckpt_path="$PWD/$FROM" max_steps=${MAX_STEPS:-2935}
systemctl --user reset-failed "zbot-calmwatch-$RUN" 2>/dev/null || true
systemd-run --user --collect --quiet --unit="zbot-calmwatch-$RUN" -p Restart=on-failure -p RestartSec=60 \
  -p WorkingDirectory="$PWD" -E HOME="$HOME" -E PATH="$PATH" "$VENV/bin/python" sim/tools/calm_watch.py "$RUN" \
  --interval 40 --window 6 --min-iters 400 --collapse-after 300 --eval-gpu 0 --video-every 100
echo "watcher zbot-calmwatch-$RUN started"
