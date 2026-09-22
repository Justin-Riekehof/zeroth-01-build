#!/usr/bin/env bash
# Detached watcher: every INTERVAL seconds, validate the latest checkpoint of each run (CPU) into
# <run>/validation_step<N>/ (rollout stats, video, contact sheet). Survives Claude/VS Code sessions.
# Start it as a systemd user unit (survives editor/session restarts, see train_backpack.sh):
#   systemctl --user reset-failed zbot-autoval 2>/dev/null; systemd-run --user --collect --unit=zbot-autoval -p WorkingDirectory=$PWD \
#     -p StandardOutput=append:$PWD/sim/train/zbot_walking_task/autoval.log -p StandardError=append:$PWD/sim/train/zbot_walking_task/autoval.log \
#     -E HOME=$HOME -E PATH=$PATH bash sim/tools/autoval.sh 3600 <run> "<overrides>" [<run> "<overrides>" ...]
# Old form: setsid nohup sim/tools/autoval.sh 3600 backpack_v2_track "velocity_tracking=True" backpack_v3_gait "velocity_tracking=True gait_shaping=True target_speed_min=0.2 target_speed_max=0.4" > sim/train/zbot_walking_task/autoval.log 2>&1 &
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"
INTERVAL="${1:-3600}"; shift
while true; do
  set -- "$@"; args=("$@")
  for ((i = 0; i < ${#args[@]}; i += 2)); do
    run="${args[i]}"; extra="${args[i+1]}"
    ck="$ROOT/sim/train/zbot_walking_task/$run/checkpoints"
    step=$(ls "$ck" 2>/dev/null | grep -o "ckpt\.[0-9]*\.bin" | sed 's/ckpt\.//;s/\.bin//' | sort -n | tail -1)
    [ -z "$step" ] && continue
    out="$ROOT/sim/train/zbot_walking_task/$run/validation_step$step"
    [ -f "$out/eval.txt" ] && grep -q "forward displacement" "$out/eval.txt" && continue
    mkdir -p "$out"; cp "$ck/ckpt.bin" "$out/ckpt.bin"
    echo "$(date) validating $run step $step"
    ZBOT_VALIDATE_LOCKED=1 GPU="" JAX_PLATFORMS=cpu flock /tmp/zbot-validate.lock timeout 3600 sim/tools/validate_policy.sh "$out/ckpt.bin" "$out" 8 $extra > "$out/validate.log" 2>&1   # lock first, then the timeout || echo "$(date) $run step $step: validation failed (see $out/validate.log)"
    echo "$(date) $run step $step: $(grep -h 'forward displacement\|mean forward speed\|fall\|steps per foot\|support phases\|swing duration\|clearance' "$out/eval.txt" | tr '\n' ' | ')"
  done
  sleep "$INTERVAL"
done
