#!/usr/bin/env bash
# Quantitative eval (16 argmax rollouts, 5 s, no video) of every checkpoint snapshot of a run that has no result
# yet -> <exp>/snapshots/eval_<step>/eval.txt and one summary line per step in <exp>/snapshots/summary.txt.
# Serialised with the hourly watcher through the validate lock (RAM). Usage: sim/tools/sweep_snapshots.sh <exp> "<overrides>"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"; EXP="${1:?exp}"; OV="${2:-}"
D="$ROOT/sim/train/zbot_walking_task/$EXP"; S="$D/snapshots"; V="$HOME/Documents/stash/ksim-zbot/.venv/bin/python"
for ck in $(ls "$S" 2>/dev/null | grep -o "ckpt\.[0-9]*\.bin" | sort -t. -k2 -n); do
  step=${ck#ckpt.}; step=${step%.bin}; out="$S/eval_$step"
  [ -f "$out/eval.txt" ] && grep -q "forward displacement" "$out/eval.txt" && continue
  mkdir -p "$out"
  if GPU="" JAX_PLATFORMS=cpu flock /tmp/zbot-validate.lock nice -n 10 sim/tools/eval_policy.sh "$S/$ck" "$out/rollouts.ds" "${ASSETS:-zbot-cad}" \
       batch_size=16 num_envs=16 dataset_num_batches=16 collect_dataset_argmax_action=True $OV > "$out/eval.txt" 2> "$out/eval.log"; then
    "$V" sim/tools/gait_analyze.py "$out/rollouts.ds" >> "$out/eval.txt" 2>/dev/null
    echo "$step | $(grep -h 'fall/termination\|without falls\|steps per foot\|swing duration' "$out/eval.txt" | sed 's/episodes with a fall\/termination within the horizon/falls/' | tr '\n' ' ')" >> "$S/summary.txt"
  else
    echo "$step | eval failed (see $out/eval.log)" >> "$S/summary.txt"
  fi
  rm -f "$out/rollouts.ds" "$out/rollouts.meta.json"
done
