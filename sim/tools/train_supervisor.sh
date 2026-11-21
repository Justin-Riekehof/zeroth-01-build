#!/usr/bin/env bash
# Keeps the GPU training without a person (user, 2026-11-03/04: "agiere komplett autonom"; twice hours were lost because
# the follow-up stage waited for an interactive Claude session). Run by the systemd user timer zbot-supervisor.timer
# every 10 min:
#   - a training unit or a chain is active -> nothing to do
#   - otherwise a headless Claude (claude -p, sim/tools/train_supervisor_prompt.md) analyses the ended run and starts the
#     next one; at most one attempt per 45 min
#   - still idle 45 min after an attempt -> fallback without analysis: continue the last ended run from its best
#     snapshot with unchanged settings, so the GPU never sits idle
# Log: sim/train/zbot_walking_task/supervisor.log (+ supervisor_claude_<time>.log). Install: sim/tools/install_supervisor.sh
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"
T="$ROOT/sim/train/zbot_walking_task"; LOG="$T/supervisor.log"; STAMP="$T/.supervisor_attempt"
export PATH="$HOME/.local/node/bin:$HOME/.local/bin:$PATH"
log() { echo "$(date '+%Y-%m-%d %H:%M') $*" >> "$LOG"; }
exec 9>/tmp/zbot-supervisor.lock; flock -n 9 || exit 0

systemctl --user list-units 'zbot-train-*' 'zbot-chain-*' --state=active,activating --no-legend | grep -q . && { rm -f "$STAMP"; exit 0; }

last_done=$(ls -t "$T"/*/calm_done.json 2>/dev/null | head -1)
[ -n "$last_done" ] || exit 0
now=$(date +%s)
if [ ! -f "$STAMP" ]; then
  echo "$now" > "$STAMP"
  out="$T/supervisor_claude_$(date +%Y%m%d_%H%M).log"
  log "idle after $(basename "$(dirname "$last_done")"): headless Claude analyses and starts the next run ($out)"
  timeout 2700 claude -p "$(cat sim/tools/train_supervisor_prompt.md)" \
    --allowedTools "Bash Read Edit Write Glob Grep" --permission-mode acceptEdits \
    --add-dir "$HOME/.claude/projects/-home-justin-Documents-stash-zeroth-01-build/memory" > "$out" 2>&1
  log "headless Claude exited ($?)"
  exit 0
fi
[ $((now - $(cat "$STAMP"))) -lt 2700 ] && exit 0

# fallback: same settings, from the best snapshot of the last ended run
run=$(basename "$(dirname "$last_done")")
step=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("best_step", ""))' "$last_done")
[ -n "$step" ] && [ -f "$T/$run/snapshots/ckpt.$step.bin" ] || { log "fallback impossible: no best snapshot in $run"; echo "$now" > "$STAMP"; exit 0; }
n=1; while [ -e "$T/${run}_c$n" ]; do n=$((n + 1)); done
log "still idle 45 min after the Claude attempt: fallback continues $run from $step as ${run}_c$n, settings unchanged"
GPU=0 EVAL_GPU=1 sim/tools/launch_continue.sh "$run" "$step" "${run}_c$n" >> "$LOG" 2>&1
rm -f "$STAMP"
