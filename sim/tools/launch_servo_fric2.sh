#!/usr/bin/env bash
# servo_fric2: servo_fric1 step 750 on, with log-uniform foot friction (user, 2026-11-02). servo_fric1 walked at mu 0.8-1.5
# (3 of 16 falls, 59-80 % real steps) and fell 15-16 of 16 at mu 0.1-0.2, with only 21 % of the environments below mu 0.4.
# Log-uniform 0.1-1.5 puts 51 % there. Everything else unchanged, so a change in the falls comes from the distribution.
# The chain unit moves to servo_fric3 with the follow-the-command rewards once it survives and steps.
# Parameters: RUN, GPU, EVAL_GPU, VIDEO_EVERY, FROM_STEP, ITERS.
set -euo pipefail
cd "$(dirname "$0")/../.."
VENV="$HOME/Documents/stash/ksim-zbot/.venv"
T=sim/train/zbot_walking_task
RUN=${RUN:-servo_fric2} GPU=${GPU:-0} FROM_STEP=${FROM_STEP:-750} ITERS=${ITERS:-2500}
mapfile -t OV < <("$VENV/bin/python" -c 'import sys; sys.path.insert(0, "sim/tools"); import calm_watch as W; print("\n".join(W.overrides("servo_fric1")))')
GPU=$GPU ASSETS=zbot-cad-tpu sim/tools/train_backpack.sh "$RUN" "${OV[@]}" foot_friction_log=True \
  load_from_ckpt_path="$PWD/$T/servo_fric1/snapshots/ckpt.$FROM_STEP.bin" max_steps=$((FROM_STEP + ITERS)) "$@"
systemctl --user reset-failed "zbot-calmwatch-$RUN" zbot-chain-friction2 2>/dev/null || true
systemd-run --user --collect --quiet --unit="zbot-calmwatch-$RUN" -p Restart=on-failure -p RestartSec=60 \
  -p WorkingDirectory="$PWD" -E HOME="$HOME" -E PATH="$PATH" "$VENV/bin/python" sim/tools/calm_watch.py "$RUN" \
  --interval 40 --window 6 --min-iters 800 --collapse-after 800 --eval-gpu "${EVAL_GPU:-1}" --video-every "${VIDEO_EVERY:-100}"
systemd-run --user --collect --quiet --unit=zbot-chain-friction2 -p WorkingDirectory="$PWD" -E HOME="$HOME" -E PATH="$PATH" \
  "$VENV/bin/python" sim/tools/train_chain.py friction2
echo "watcher and chain zbot-chain-friction2 started"
