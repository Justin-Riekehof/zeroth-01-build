#!/usr/bin/env bash
# Stop a training run for good (unit + watchdog registration). Usage: sim/tools/stop_run.sh <exp_name>
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; EXP="${1:?exp name}"; T="$ROOT/sim/train/zbot_walking_task"
sed -i "/^$EXP\$/d" "$T/active_runs.txt" 2>/dev/null
systemctl --user stop "zbot-train-$EXP" 2>/dev/null; systemctl --user reset-failed "zbot-train-$EXP" 2>/dev/null
echo "$EXP stopped ($(systemctl --user is-active "zbot-train-$EXP" 2>/dev/null))"
