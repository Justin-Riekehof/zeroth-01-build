#!/usr/bin/env bash
# Long-horizon check: 16 argmax rollouts of SECS seconds (distance / falls / gait) + a SECS-second video.
# Usage: sim/tools/long_walk.sh <ckpt.bin> <outdir> [seconds=30] [task overrides...]   (GPU=<n> to use a GPU, default CPU)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"
CKPT="${1:?ckpt}"; OUT="${2:?outdir}"; SECS="${3:-30}"; shift 3 2>/dev/null || shift $#
mkdir -p "$OUT"; VENV="$HOME/Documents/stash/ksim-zbot/.venv"; ASSETS="${ASSETS:-zbot-cad}"
export MUJOCO_GL=egl XLA_PYTHON_CLIENT_PREALLOCATE=false; export CUDA_VISIBLE_DEVICES="${GPU:-}"; [ -z "${GPU:-}" ] && export JAX_PLATFORMS=cpu
if [ -z "${ZBOT_VALIDATE_LOCKED:-}" ]; then ZBOT_VALIDATE_LOCKED=1 exec flock /tmp/zbot-validate.lock "$0" "$CKPT" "$OUT" "$SECS" "$@"; fi
echo "== $SECS s x 16 argmax rollouts"; sim/tools/eval_policy.sh "$CKPT" "$OUT/rollouts.ds" "$ASSETS" batch_size=16 num_envs=16 dataset_num_batches=16 collect_dataset_argmax_action=True rollout_length_seconds="$SECS" "$@" | tee "$OUT/eval.txt"
"$VENV/bin/python" sim/tools/gait_analyze.py "$OUT/rollouts.ds" | tee -a "$OUT/eval.txt"
echo "== video"; sim/tools/render_policy.sh "$CKPT" "$OUT/walk.mp4" "$SECS" "$ASSETS" render_distance=1.2 render_azimuth=150 render_elevation=-15 "$@" > "$OUT/render.log" 2>&1
"$VENV/bin/python" sim/tools/contact_sheet.py "$OUT/walk.mp4" "$OUT/contact_sheet.png" 12 | tee -a "$OUT/eval.txt"; echo "done -> $OUT"
