#!/usr/bin/env bash
# Train a list of walking variants one after another on ONE GPU, unattended.
#
#   sim/tools/train_queue.sh start [queue-file]     launch the queue as the systemd user unit zbot-queue
#   sim/tools/train_queue.sh run   <queue-file>     run it in the foreground (what the unit does)
#   sim/tools/train_queue.sh status                 what is done / running / pending
#   sim/tools/train_queue.sh stop                   stop the queue and the training it started
#
# Queue file: one stage per line, `#` comments and blank lines ignored
#   exp | profile | target_speed | steps | parent | overrides
#     exp           run name under sim/train/zbot_walking_task/
#     profile       strong|calm|tiny -- how sim/tools/pick_best.py scores this run's snapshots
#     target_speed  m/s the run is commanded to walk, for the same scoring
#     steps         training steps for THIS stage (for a fine-tune, on top of the parent's step count --
#                   xax restores the step counter together with the weights, so max_steps is absolute)
#     parent        `-` for a run from scratch, else the stage whose best snapshot this one fine-tunes
#     overrides     key=value pairs passed to sim/train/walking.py
#
# Per stage: launch through train_backpack.sh (systemd unit zbot-train-<exp>, survives a session restart and
# is revived by the watchdog), wait for max_steps, deregister it from active_runs.txt so the watchdog does not
# restart a finished run, then sweep its snapshots (foreground if a later stage needs its best checkpoint,
# otherwise in the background on the CPU while the next stage already trains on the GPU).
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"
T="$ROOT/sim/train/zbot_walking_task"; Q="$T/queue"; GPU="${GPU:-1}"; ASSETS="${ASSETS:-zbot-cad}"
LOG="$Q/queue.log"; POLL="${POLL:-30}"

log() { mkdir -p "$Q"; echo "$(date '+%F %T') $*" | tee -a "$LOG"; }

stages() { grep -vE '^\s*(#|$)' "$1"; }
field() { echo "$1" | awk -F'|' -v n="$2" '{gsub(/^[ \t]+|[ \t]+$/,"",$n); print $n}'; }

ckpt_step() {   # highest snapshot/checkpoint step of a run
  local d="$T/$1"
  { ls "$d/snapshots" "$d/checkpoints" 2>/dev/null | grep -o 'ckpt\.[0-9]*\.bin'; } \
    | sed 's/ckpt\.//;s/\.bin//' | sort -n | tail -1
}

sweep() {       # evaluate every snapshot of a run that has no result yet
  # The run's own overrides MUST go through: the eval rebuilds the network from the task config, and e.g.
  # heading_obs=True makes the actor 64 inputs wide instead of 62 -- without it every checkpoint fails to
  # deserialise ("changed shape from (256, 62) to (256, 64)") and the sweep silently produces nothing.
  local exp="$1" ov="${2:-}"
  log "$exp: sweeping snapshots"
  ASSETS="$ASSETS" bash sim/tools/sweep_snapshots.sh "$exp" "$ov ${SWEEP_OVERRIDES:-}" >> "$Q/$exp.sweep.log" 2>&1
  log "$exp: sweep done ($(ls -d "$T/$exp"/snapshots/eval_* 2>/dev/null | wc -l) evaluated)"
}

# Sweeps are CPU-only and take hours, so they always run alongside the next stage's GPU training; a
# fine-tune stage waits for its own parent's sweep right before it needs the checkpoint, and nothing else
# ever blocks the GPU.
sweep_bg() { ( sweep "$1" "$2" ) & echo $! > "$Q/$1.sweep.pid"; }
wait_sweep() {
  local pid; pid=$(cat "$Q/$1.sweep.pid" 2>/dev/null) || return 0
  [ -z "$pid" ] && return 0
  kill -0 "$pid" 2>/dev/null && log "$2: waiting for the $1 sweep (pid $pid) to finish"
  while kill -0 "$pid" 2>/dev/null; do sleep 30; done
}

run_queue() {
  local qf="$1"; mkdir -p "$Q"
  log "queue start: $qf (GPU=$GPU ASSETS=$ASSETS, $(stages "$qf" | wc -l) stages)"
  while IFS= read -r line; do
    local exp profile target steps parent ov
    exp=$(field "$line" 1); profile=$(field "$line" 2); target=$(field "$line" 3)
    steps=$(field "$line" 4); parent=$(field "$line" 5); ov=$(field "$line" 6)
    [ -z "$exp" ] && continue
    if [ -f "$Q/$exp.done" ]; then log "$exp: already done, skipping"; continue; fi

    # fine-tune: take the parent's best evaluated snapshot, and make max_steps absolute
    local extra="" max_steps="$steps"
    if [ "$parent" != "-" ] && [ -n "$parent" ]; then
      local pck pstep pline pmin
      wait_sweep "$parent" "$exp"
      pline=$(stages "$qf" | grep -m1 "^\s*$parent\s*|")
      # only consider the parent's later half: the 5 s sweep happily ranks a barely-trained checkpoint first
      # (it scores speed/calmness, not robustness), and fine-tuning from one of those wastes the stage
      pmin=$(( $(field "$pline" 4) / 2 ))
      pck=$(python3 sim/tools/pick_best.py "$parent" --path --min-step "$pmin" \
              --target-speed "$(field "$pline" 3)" --profile "$(field "$pline" 2)" 2>>"$LOG")
      if [ -z "$pck" ] || [ ! -f "$pck" ]; then   # nothing evaluated that late -> fall back to any snapshot
        log "$exp: no parent snapshot at/after step $pmin, retrying without the minimum"
        pck=$(python3 sim/tools/pick_best.py "$parent" --path \
                --target-speed "$(field "$pline" 3)" --profile "$(field "$pline" 2)" 2>>"$LOG")
      fi
      if [ -z "$pck" ] || [ ! -f "$pck" ]; then log "$exp: FAILED, no usable parent checkpoint from $parent"; continue; fi
      pstep=$(basename "$pck" | sed 's/ckpt\.//;s/\.bin//')
      max_steps=$((pstep + steps))
      extra="load_from_ckpt_path=$pck"
      log "$exp: fine-tuning $parent step $pstep -> max_steps $max_steps"
    fi

    log "$exp: launching (max_steps=$max_steps) $ov $extra"
    GPU="$GPU" ASSETS="$ASSETS" bash sim/tools/train_backpack.sh "$exp" $ov max_steps="$max_steps" $extra >> "$LOG" 2>&1
    sleep 10
    # "activating" = systemd is restarting the unit after a crash (Restart=on-failure), so it is NOT finished
    while true; do
      local st; st=$(systemctl --user show -p ActiveState --value "zbot-train-$exp" 2>/dev/null)
      case "$st" in active|activating|deactivating|reloading) ;; *) break ;; esac
      sleep "$POLL"
      local s; s=$(ckpt_step "$exp")
      echo "$(date '+%F %T') $exp step ${s:-0}/$max_steps ($st)" > "$Q/$exp.progress"
    done
    systemctl --user stop "zbot-train-$exp" 2>/dev/null   # make sure nothing lingers on the GPU
    # finished (max_steps reached or crashed): take it off the watchdog's revive list
    grep -vx "$exp" "$T/active_runs.txt" > "$T/active_runs.tmp" 2>/dev/null; mv "$T/active_runs.tmp" "$T/active_runs.txt"
    local s; s=$(ckpt_step "$exp")
    if [ -z "$s" ] || [ "$s" -lt "$((max_steps - 20))" ]; then
      log "$exp: stopped at step ${s:-0} of $max_steps -- check $T/$exp/train.log"
    else
      log "$exp: reached step $s"; touch "$Q/$exp.done"
    fi

    sweep_bg "$exp" "$ov"
  done < <(stages "$qf")
  wait
  log "queue finished"
  for f in "$Q"/*.done; do [ -e "$f" ] && echo "  done: $(basename "${f%.done}")" | tee -a "$LOG"; done
}

case "${1:-status}" in
  start)
    qf="${2:-$Q/queue.txt}"; mkdir -p "$Q"
    systemctl --user reset-failed zbot-queue 2>/dev/null
    systemd-run --user --collect --quiet --unit=zbot-queue \
      -p WorkingDirectory="$ROOT" -p KillSignal=SIGKILL -p TimeoutStopSec=15 \
      -p StandardOutput=append:"$Q/unit.log" -p StandardError=append:"$Q/unit.log" \
      -E HOME="$HOME" -E PATH="$PATH" -E GPU="$GPU" -E ASSETS="$ASSETS" \
      bash "$ROOT/sim/tools/train_queue.sh" run "$qf"
    echo "queue running as unit zbot-queue -> $LOG"
    ;;
  run) run_queue "${2:-$Q/queue.txt}" ;;
  status)
    systemctl --user is-active zbot-queue >/dev/null && echo "queue: running" || echo "queue: not running"
    for f in "$Q"/*.progress; do [ -e "$f" ] && cat "$f"; done
    for f in "$Q"/*.done; do [ -e "$f" ] && echo "done: $(basename "${f%.done}")"; done
    tail -n 12 "$LOG" 2>/dev/null
    ;;
  stop)
    systemctl --user stop zbot-queue 2>/dev/null
    for u in $(systemctl --user list-units --plain --no-legend 'zbot-train-*' | awk '{print $1}'); do
      echo "stopping $u"; systemctl --user stop "$u"
    done
    ;;
  *) sed -n '2,25p' "$0"; exit 1 ;;
esac
