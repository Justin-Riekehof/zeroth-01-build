#!/usr/bin/env bash
# Quantitative walking check: roll out a checkpoint in batch_size envs, save the trajectories and
# report forward displacement / speed / falls.  Usage: sim/tools/eval_policy.sh <ckpt.bin> <out.npz> [assets] [overrides...]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"
CKPT="${1:?ckpt}"; OUT="${2:?out.npz}"; ASSETS="${3:-${ASSETS:-zbot-cad}}"; shift 3 2>/dev/null || shift $#
VENV="$HOME/Documents/stash/ksim-zbot/.venv"
export CUDA_VISIBLE_DEVICES="${GPU:-0}" MUJOCO_GL=egl XLA_PYTHON_CLIENT_PREALLOCATE=false
"$VENV/bin/python" -m sim.train.walking collect_dataset=True dataset_num_batches=1 dataset_save_path="$OUT" \
  load_from_ckpt_path="$CKPT" robot_urdf_path="$ROOT/sim/assets/$ASSETS" exp_dir="$ROOT/sim/train/zbot_walking_task/_eval" \
  batch_size=64 num_envs=64 "$@" > "$OUT.log" 2>&1 || { echo "collect failed, see $OUT.log"; exit 1; }
"$VENV/bin/python" "$ROOT/sim/tools/eval_analyze.py" "$OUT"
