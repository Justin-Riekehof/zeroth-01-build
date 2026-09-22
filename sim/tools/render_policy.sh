#!/usr/bin/env bash
# Render a video of a trained policy on the backpack model (offscreen, EGL).
# Usage: sim/tools/render_policy.sh <checkpoint.bin> <out.mp4|out.gif> [seconds=10] [assets=zbot-pixel-backpack] [extra overrides...]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"
CKPT="${1:?checkpoint}"; OUT="${2:?output video}"; SECS="${3:-10}"; ASSETS="${4:-${ASSETS:-zbot-cad}}"; shift 4 2>/dev/null || shift $#
VENV="$HOME/Documents/stash/ksim-zbot/.venv"
export CUDA_VISIBLE_DEVICES="${GPU:-0}" MUJOCO_GL=egl XLA_PYTHON_CLIENT_PREALLOCATE=false
"$VENV/bin/python" -m sim.train.walking run_environment=True \
  run_environment_save_path="$OUT" run_environment_num_seconds="$SECS" run_environment_argmax_action=True \
  load_from_ckpt_path="$CKPT" robot_urdf_path="$ROOT/sim/assets/$ASSETS" \
  exp_dir="$ROOT/sim/train/zbot_walking_task/_render" \
  render_distance=1.3 render_azimuth=150 render_elevation=-15 render_track_body_id=1 "$@"
