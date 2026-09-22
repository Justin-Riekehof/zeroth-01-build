#!/usr/bin/env bash
# Summarise a run's reward / episode-length / throughput curves from its tensorboard events.
# Usage: sim/tools/progress.sh <exp_name> [more tag substrings]
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; EXP="${1:?exp}"; shift || true
"$HOME/Documents/stash/ksim-zbot/.venv/bin/python" "$ROOT/sim/tools/tb_read.py" "$ROOT/sim/train/zbot_walking_task/$EXP" \
  "reward/total" "naive_velocity" "linear_velocity_tracking" "episode_length" "steps/second" "curriculum" "termination/mean" "$@" 2>&1 | grep "^\["
