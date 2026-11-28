#!/usr/bin/env bash
# Continue a run from one of its snapshots under a new name, with its launch overrides plus changes, and a watcher.
# Usage: sim/tools/launch_continue.sh <from_run> <from_step> <new_run> [key=value changes...]
#        (GPU=0 training, EVAL_GPU=1, ITERS=2500, MIN_ITERS=200 before the stagnation rule, WINDOW=6 evaluations
#        for it, VIDEO_EVERY=100)
# Same model as the source run (its launch.sh). Used for the autonomous follow-up stages from 2026-11-04 on.
set -euo pipefail
cd "$(dirname "$0")/../.."
VENV="$HOME/Documents/stash/ksim-zbot/.venv"
T=sim/train/zbot_walking_task
FROM=${1:?from_run} STEP=${2:?from_step} RUN=${3:?new_run}; shift 3
CK="$PWD/$T/$FROM/snapshots/ckpt.$STEP.bin"; [ -f "$CK" ] || { echo "no snapshot $CK"; exit 1; }
[ -e "$T/$RUN" ] && { echo "$T/$RUN exists"; exit 1; }
mapfile -t OV < <("$VENV/bin/python" -c 'import sys; sys.path.insert(0, "sim/tools"); import calm_watch as W; print("\n".join(W.overrides(sys.argv[1])))' "$FROM")
ASSETS=$("$VENV/bin/python" -c 'import sys; sys.path.insert(0, "sim/tools"); import calm_watch as W; print(W.assets(sys.argv[1]))' "$FROM")
GPU=${GPU:-0} ASSETS=$ASSETS sim/tools/train_backpack.sh "$RUN" "${OV[@]}" "$@" \
  load_from_ckpt_path="$CK" max_steps=$((STEP + ${ITERS:-2500}))
systemctl --user reset-failed "zbot-calmwatch-$RUN" 2>/dev/null || true
systemd-run --user --collect --quiet --unit="zbot-calmwatch-$RUN" -p Restart=on-failure -p RestartSec=60 \
  -p WorkingDirectory="$PWD" -E HOME="$HOME" -E PATH="$PATH" "$VENV/bin/python" sim/tools/calm_watch.py "$RUN" \
  --interval 40 --window "${WINDOW:-6}" --min-iters "${MIN_ITERS:-200}" --collapse-after 200 --eval-gpu "${EVAL_GPU:-1}" \
  --video-every "${VIDEO_EVERY:-100}"
echo "watcher zbot-calmwatch-$RUN started ($ASSETS, from $FROM step $STEP)"
