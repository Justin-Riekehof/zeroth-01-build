#!/usr/bin/env bash
# FROM SCRATCH with random foot friction (2026-11-01, user: "fundamental policy error"). Up to servo_tpu5 every policy
# knew only mu 1.1: the randomizer changed the floor geom, the foot <pair>s ignore that. Now foot_friction_min/max.
# TPU soles, correct hip-roll axes (zbot-cad-tpu, so no --flip-joints at export).
#
# Starts with the rewards of servo_tpu1 (read from its checkpoint): instantaneous tracking, naive_velocity 1.5, stride
# also without a command. The windowed rewards of launch_servo_scratch2.sh alone teach falling from scratch (servo_tpu3,
# servo_scratch3). The chain unit started here moves to servo_fric2 with those rewards once fric1 survives and steps.
# Straight walking only (user, 2026-11-01): no zero commands, so no stop-versus-walk conflict and no drift criterion.
# Friction 0.1-1.5 (user). In the contact model sliding starts at 80-95 % of mu*M*g (at mu 1.5 already 50-80 %), so the
# effective upper end is lower. IMU tilt +-8 deg: the real IMU differs from the model by 4-8 deg.
# Parameters: RUN, GPU, EVAL_GPU (-1 = CPU), VIDEO_EVERY, MAX_STEPS, CHAIN (train_chain.py chain, default friction).
# Later key=value arguments override the ones here (servo_rubber1: foot_friction_min=0.5 foot_friction_max=1.3).
set -euo pipefail
cd "$(dirname "$0")/../.."
VENV="$HOME/Documents/stash/ksim-zbot/.venv"
export RUN=${RUN:-servo_fric1} ASSETS=zbot-cad-tpu VIDEO_EVERY=${VIDEO_EVERY:-100}
sim/tools/launch_servo_scratch2.sh naive_velocity_scale=1.5 track_window_s=0.0 stride_needs_command=False \
  domain_randomize=True foot_friction_min=0.1 foot_friction_max=1.5 imu_tilt_deg=8.0 speed_zero_prob=0.0 "$@"
CHAIN=${CHAIN:-friction}
systemctl --user reset-failed "zbot-chain-$CHAIN" 2>/dev/null || true
systemd-run --user --collect --quiet --unit="zbot-chain-$CHAIN" -p WorkingDirectory="$PWD" -E HOME="$HOME" -E PATH="$PATH" \
  "$VENV/bin/python" sim/tools/train_chain.py "$CHAIN"
echo "chain zbot-chain-$CHAIN started"
