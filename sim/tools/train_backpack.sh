#!/usr/bin/env bash
# Train the walking policy on the backpack model (zbot-pixel-backpack) on one GPU, detached.
# Usage: sim/tools/train_backpack.sh <exp_name> [extra key=value overrides...]      (GPU=1 for the second card,
#        ASSETS=zbot-pixel-backpack for the old Z-Bot-2-based model; default zbot-cad = this robot from the WebUI CAD)
# Runs as a transient systemd *user* service (unit zbot-train-<exp>, Restart=on-failure) so it survives VS Code /
# Claude session restarts and crashes: a Bash-tool shell lives in the editor's snap.code.*.scope cgroup and
# everything in it — even setsid/nohup'd processes — is killed when that scope stops. The run is registered in
# active_runs.txt for zbot_watchdog.sh (revive after reboot, checkpoint snapshots). Stop: sim/tools/stop_run.sh <exp>
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"
EXP="${1:?exp name}"; shift || true
VENV="$HOME/Documents/stash/ksim-zbot/.venv"; GPU="${GPU:-0}"; ASSETS="${ASSETS:-zbot-cad}"
T="$ROOT/sim/train/zbot_walking_task"; DIR="$T/$EXP"; mkdir -p "$DIR"; UNIT="zbot-train-$EXP"
{ printf 'GPU=%q ASSETS=%q %q %q' "$GPU" "$ASSETS" "$ROOT/sim/tools/train_backpack.sh" "$EXP"; for a in "$@"; do printf ' %q' "$a"; done; echo; } > "$DIR/launch.sh"
grep -qx "$EXP" "$T/active_runs.txt" 2>/dev/null || echo "$EXP" >> "$T/active_runs.txt"
systemctl --user reset-failed "$UNIT" 2>/dev/null || true
systemd-run --user --collect --quiet --unit="$UNIT" \
  -p WorkingDirectory="$ROOT" -p KillSignal=SIGKILL -p TimeoutStopSec=15 -p Restart=on-failure -p RestartSec=30 \
  -p StandardOutput=append:"$DIR/train.log" -p StandardError=append:"$DIR/train.log" \
  -E CUDA_VISIBLE_DEVICES="$GPU" -E MUJOCO_GL=egl -E ASSETS="$ASSETS" -E HOME="$HOME" -E PATH="$PATH" \
  "$VENV/bin/python" -m sim.train.walking \
  robot_urdf_path="$ROOT/sim/assets/$ASSETS" exp_dir="$DIR" "$@"
sleep 1; systemctl --user show -p MainPID --value "$UNIT" > "$DIR/train.pid"
echo "started unit $UNIT pid $(cat "$DIR/train.pid") -> sim/train/zbot_walking_task/$EXP/train.log"
