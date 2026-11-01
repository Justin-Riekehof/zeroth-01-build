#!/usr/bin/env bash
# Controlled walking, concept v5 (2026-10-28), FROM SCRATCH. The diagnosis of 2026-10-28 (docs/training-journal.md):
# the 5-6 Hz jitter of servo_ctrl_v1-v3 is a feedback oscillation through the servo delay. The raw action already
# oscillates, and its frequency follows the delay (0 ms: 10.5 Hz, 40 ms: 6.2 Hz, 80 ms: 4.0 Hz; period ~ 2 x total lag).
# The low-pass filter and the jerk/acceleration penalties only added lag or forbade the correction (v3 stopped walking).
#   * action_history=4   the actor sees a(t-1) ... a(t-4): the commands still in flight in the ~85 ms of delay + lag
#                        (+48 inputs; the Pi builds the same vector, policy_meta.json "action_history")
#   * delay_rand=0.02    per episode every servo delay shifts by the same random +-20 ms (legs 20-60 ms): no feedback
#                        gain tuned to one exact delay
#   * no action filter   (it is lag), no joint-accel / stride / gait-clock terms of v4
#   * tracking 10 (was 6), action jerk penalty -0.1 (was -0.5): walking must stay the cheapest thing to do
# Otherwise the reward set of servo_ctrl_v2 (walked from scratch: no falls, tracking 0.63 at step 670).
# Watcher: tracking-collapse rule, video every 100 iterations into <run>/videos for the training film.
set -euo pipefail
cd "$(dirname "$0")/../.."
VENV="$HOME/Documents/stash/ksim-zbot/.venv"
RUN=${RUN:-servo_ctrl_v4}
GPU=1 ASSETS=zbot-cad sim/tools/train_backpack.sh "$RUN" \
  servo_model=True servo_kp=32 dt=0.002 leg_servo_speed=2000 start_pose=center hip_yaw_range_deg=30 \
  clamp_to_real_limits=True cmd_rate_fraction=0.7 export_for_inference=False \
  action_history=4 delay_rand=0.02 \
  velocity_tracking=True gait_shaping=True heading_obs=True \
  target_speed_min=0.08 target_speed_max=0.14 track_reward_scale=10.0 track_error_scale=0.12 naive_velocity_scale=1.5 \
  gait_freq_lower=1.0 gait_freq_upper=1.5 gait_swing_reward=0.3 gait_swing_tmin=0.3 gait_swing_tmax=0.6 \
  gait_step_reward=0.0 gait_single_support=0.1 gait_flip_penalty=-0.1 gait_clearance_reward=0.2 gait_clearance_target=0.02 \
  foot_lift_penalty=-1.0 foot_lift_max=0.03 feet_slip_penalty=-0.3 heading_penalty=-1.0 lateral_position_penalty=-0.5 \
  gait_lateral_penalty=-1.0 roll_penalty=-3.0 joint_deviation_penalty=-0.5 joint_velocity_penalty=-0.05 \
  gait_smooth_penalty=-1.0 target_gap_penalty=-0.25 action_saturation_penalty=-0.5 \
  action_step_limit_penalty=-0.025 action_jerk_penalty=-0.1 \
  joint_limit_penalty=-0.5 target_limit_penalty=-4.0 joint_speed_limit_penalty=-1.0 joint_speed_limit_fraction=0.7 \
  max_steps=${MAX_STEPS:-3000} "$@"
[ "${NO_WATCH:-}" = 1 ] && exit 0
systemctl --user reset-failed "zbot-calmwatch-$RUN" 2>/dev/null || true
systemd-run --user --collect --quiet --unit="zbot-calmwatch-$RUN" -p Restart=on-failure -p RestartSec=60 \
  -p WorkingDirectory="$PWD" -E HOME="$HOME" -E PATH="$PATH" "$VENV/bin/python" sim/tools/calm_watch.py "$RUN" \
  --interval 40 --window 6 --min-iters 600 --eval-gpu 0 --video-every 100
echo "watcher zbot-calmwatch-$RUN started"
