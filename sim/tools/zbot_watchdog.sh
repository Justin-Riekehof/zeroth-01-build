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
  # its calm watcher too (2026-11-07: after a reboot the run came back, the watcher did not - no evaluation, no stop)
  w="zbot-calmwatch-$exp"
  if [ -f "$d/calm_watch.json" ] && [ ! -f "$d/calm_done.json" ] && ! systemctl --user is-active --quiet "$w"; then
    log "$exp: watcher $w not active -> restart"
    systemctl --user reset-failed "$w" 2>/dev/null
    systemd-run --user --collect --quiet --unit="$w" -p Restart=on-failure -p RestartSec=60 -p WorkingDirectory="$ROOT" \
      -E HOME="$HOME" -E PATH="$PATH" "$HOME/Documents/stash/ksim-zbot/.venv/bin/python" sim/tools/calm_watch.py "$exp" \
      --interval 40 --window 6 --min-iters 200 --collapse-after 200 --eval-gpu 1 --video-every 100 >> "$LOG" 2>&1 \
      || log "$exp: watcher restart failed"
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
