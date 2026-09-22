#!/usr/bin/env bash
# Start (or restart) the hourly validation watcher as a systemd user unit (revived by zbot_watchdog.sh if it dies).
# Usage: sim/tools/start_autoval.sh <interval_s> <run> "<overrides>" [<run> "<overrides>" ...]
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; T="$ROOT/sim/train/zbot_walking_task"; LOG="$T/autoval.log"
{ printf '%q' "$ROOT/sim/tools/start_autoval.sh"; for a in "$@"; do printf ' %q' "$a"; done; echo; } > "$T/autoval_cmd.sh"
systemctl --user stop zbot-autoval 2>/dev/null; systemctl --user reset-failed zbot-autoval 2>/dev/null
systemd-run --user --collect --quiet --unit=zbot-autoval -p WorkingDirectory="$ROOT" -p KillMode=control-group \
  -p StandardOutput=append:"$LOG" -p StandardError=append:"$LOG" -E HOME="$HOME" -E PATH="$PATH" -E MUJOCO_GL=egl -E ASSETS="${ASSETS:-zbot-cad}" \
  bash "$ROOT/sim/tools/autoval.sh" "$@"
sleep 1; echo "watcher unit zbot-autoval: $(systemctl --user is-active zbot-autoval) (pid $(systemctl --user show -p MainPID --value zbot-autoval))"
