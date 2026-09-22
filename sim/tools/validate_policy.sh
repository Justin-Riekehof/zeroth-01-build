#!/usr/bin/env bash
# Full validation of one checkpoint: quantitative rollouts + video + contact sheet into <outdir>.
# Usage: sim/tools/validate_policy.sh <ckpt.bin> <outdir> [seconds=10] [task overrides...]   (CPU by default: GPU="" JAX_PLATFORMS=cpu)
set -euo pipefail
# serialise validations machine-wide: two CPU evals next to two trainings exhausted RAM (OOM-killed the watcher 2026-09-08)
if [ -z "${ZBOT_VALIDATE_LOCKED:-}" ]; then ZBOT_VALIDATE_LOCKED=1 exec flock /tmp/zbot-validate.lock "$0" "$@"; fi
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"
CKPT="${1:?ckpt}"; OUT="${2:?outdir}"; SECS="${3:-10}"; shift 3 2>/dev/null || shift $#
mkdir -p "$OUT"; VENV="$HOME/Documents/stash/ksim-zbot/.venv"; ASSETS="${ASSETS:-zbot-cad}"
export MUJOCO_GL=egl XLA_PYTHON_CLIENT_PREALLOCATE=false; export JAX_PLATFORMS="${JAX_PLATFORMS:-cpu}"; export CUDA_VISIBLE_DEVICES="${GPU:-}"
echo "== quantitative (16 argmax rollouts x 5 s)"; sim/tools/eval_policy.sh "$CKPT" "$OUT/rollouts.ds" "$ASSETS" batch_size=16 num_envs=16 dataset_num_batches=16 collect_dataset_argmax_action=True "$@" | tee "$OUT/eval.txt"
echo "== video"; sim/tools/render_policy.sh "$CKPT" "$OUT/walk.mp4" "$SECS" "$ASSETS" render_distance=1.1 render_azimuth=135 render_elevation=-12 "$@" > "$OUT/render.log" 2>&1
"$VENV/bin/python" sim/tools/gait_analyze.py "$OUT/rollouts.ds" | tee -a "$OUT/eval.txt"
"$VENV/bin/python" sim/tools/contact_sheet.py "$OUT/walk.mp4" "$OUT/contact_sheet.png" 12 | tee -a "$OUT/eval.txt"
echo "done -> $OUT"
