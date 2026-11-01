#!/usr/bin/env bash
# FROM SCRATCH with random foot friction (2026-11-01, user: "fundamental policy error"). Up to servo_tpu5 every policy
# knew only mu 1.1: the randomizer changed the floor geom, the foot <pair>s ignore that. Now foot_friction_min/max.
# TPU soles, correct hip-roll axes (zbot-cad-tpu, so no --flip-joints at export).
#
# Starts with the rewards of servo_tpu1 (read from its checkpoint): instantaneous tracking, naive_velocity 1.5, stride
# also without a command. The windowed rewards of launch_servo_scratch2.sh alone teach falling from scratch (servo_tpu3,
# servo_scratch3). The chain unit started here moves to servo_fric2 with those rewards once fric1 survives and steps.
# Parameters: RUN, GPU, EVAL_GPU (-1 = CPU), MAX_STEPS.
set -euo pipefail
cd "$(dirname "$0")/../.."
VENV="$HOME/Documents/stash/ksim-zbot/.venv"
export RUN=${RUN:-servo_fric1} ASSETS=zbot-cad-tpu
sim/tools/launch_servo_scratch2.sh naive_velocity_scale=1.5 track_window_s=0.0 stride_needs_command=False \
  domain_randomize=True "$@"
systemctl --user reset-failed zbot-chain-friction 2>/dev/null || true
systemd-run --user --collect --quiet --unit=zbot-chain-friction -p WorkingDirectory="$PWD" -E HOME="$HOME" -E PATH="$PATH" \
  "$VENV/bin/python" sim/tools/train_chain.py friction
echo "chain zbot-chain-friction started"
