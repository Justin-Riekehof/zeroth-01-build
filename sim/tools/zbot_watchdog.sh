#!/usr/bin/env bash
# Every 10 min (systemd user timer zbot-watchdog.timer, see sim/README.md): keep the registered training runs
# (active_runs.txt) and the validation watcher alive, and keep step-numbered checkpoint snapshots — xax only keeps
# the most recent ckpt — in <exp>/snapshots/ plus a copy outside the repo (~/zbot-ckpt-backup/<exp>/).
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; T="$ROOT/sim/train/zbot_walking_task"; LOG="$T/watchdog.log"; BK="$HOME/zbot-ckpt-backup"
log() { echo "$(date '+%F %T') $*" >> "$LOG"; }
[ -f "$T/active_runs.txt" ] || exit 0
while read -r exp; do
  [ -z "$exp" ] && continue; d="$T/$exp"; u="zbot-train-$exp"
  if ! systemctl --user is-active --quiet "$u"; then
    log "$exp: unit $u not active -> relaunch"; bash "$d/launch.sh" >> "$LOG" 2>&1 || log "$exp: relaunch failed"
  fi
  latest=$(ls "$d/checkpoints" 2>/dev/null | grep -o "ckpt\.[0-9]*\.bin" | sort -t. -k2 -n | tail -1)
  if [ -n "$latest" ] && [ ! -f "$d/snapshots/$latest" ]; then
    mkdir -p "$d/snapshots" "$BK/$exp"
    cp "$d/checkpoints/$latest" "$d/snapshots/$latest.tmp" && mv "$d/snapshots/$latest.tmp" "$d/snapshots/$latest" \
      && cp "$d/snapshots/$latest" "$BK/$exp/" && log "$exp: snapshot $latest"
  fi
done < "$T/active_runs.txt"
if [ -f "$T/autoval_cmd.sh" ] && ! systemctl --user is-active --quiet zbot-autoval; then
  log "validation watcher not active -> restart"; bash "$T/autoval_cmd.sh" >> "$LOG" 2>&1
fi
