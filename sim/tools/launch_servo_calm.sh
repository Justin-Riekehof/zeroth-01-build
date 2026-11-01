#!/usr/bin/env bash
# Calm, hardware-safe walking: continue servo_v2_normal (the only candidate that walked) with penalties for everything
# the first hardware tests showed to be a problem, until the hardware gate (sim/tools/hardware_gate.py) passes or the
# progress stagnates (sim/tools/calm_watch.py decides; max_steps is only the safety cap).
#
#   calm_a  (GPU 1)  gentle penalties        calm_b  (GPU 0)  twice as strong
#
# Scales are calibrated on the rollouts of servo_v2_normal (per-step reward = scale * raw * ctrl_dt, tracking ~0.44):
#   term                           raw in v2        calm_a   calm_b
#   gait_smooth_penalty (l2)       ~0.05 per unit   -1.5     -3       (was -0.3: 3 % of the tracking reward = no effect)
#   target_gap_penalty             0.50 rad         -0.1     -0.2     |action - q|: targets 29 deg ahead of the joints
#   action_saturation_penalty      0.044            -1       -2
#   joint_limit_penalty            0.199            -0.5     -1       hip yaw within 5 deg of its limit half the time
#   target_limit_penalty           0.025            -4       -8       hip-yaw targets 0.2-0.4 rad beyond the real limits
#   joint_speed_limit_penalty      0.05 / 0.15      -1.5     -0.8     relative excess over a BUFFER below the servo limit:
#                                                   (raw at 85 % / 70 % of the limit in v2; legs average 2.3 of 3.07 rad/s = 73 %)
#   joint_speed_limit_fraction                      0.85     0.70     calm_a keeps the servos below 85 %, calm_b below 70 % of their limit
# together ~50 % (calm_a) / ~70 % (calm_b) of the tracking reward at the start: strong, but a standing robot must not
# beat a walking one. clamp_to_real_limits=True makes the sim clamp targets exactly like the Pi runner.
set -euo pipefail
cd "$(dirname "$0")/.."/..
VENV="$HOME/Documents/stash/ksim-zbot/.venv"
T=sim/train/zbot_walking_task
BASE=$(python3 - <<'PY'
import shlex
toks = shlex.split(open("sim/train/zbot_walking_task/servo_v2_normal/launch.sh").read())
i = [k for k, t in enumerate(toks) if t.endswith("train_backpack.sh")][0]
drop = ("max_steps=", "load_from_ckpt_path=", "gait_smooth_penalty=")
print(" ".join(shlex.quote(t) for t in toks[i + 2:] if not t.startswith(drop)))
PY
)
CKPT="$PWD/$T/servo_v2_normal/snapshots/ckpt.1200.bin"
start() {  # name gpu smooth gap sat limit tlimit speed fraction
  GPU=$2 ASSETS=zbot-cad eval sim/tools/train_backpack.sh "$1" $BASE clamp_to_real_limits=True \
    gait_smooth_penalty=$3 target_gap_penalty=$4 action_saturation_penalty=$5 joint_limit_penalty=$6 \
    target_limit_penalty=$7 joint_speed_limit_penalty=$8 joint_speed_limit_fraction=$9 max_steps=3200 load_from_ckpt_path="$CKPT"
  systemctl --user reset-failed "zbot-calmwatch-$1" 2>/dev/null || true
  systemd-run --user --collect --quiet --unit="zbot-calmwatch-$1" -p Restart=on-failure -p RestartSec=60 -p WorkingDirectory="$PWD" \
    -E HOME="$HOME" -E PATH="$PATH" "$VENV/bin/python" sim/tools/calm_watch.py "$1" --interval 40 --window 4
  echo "watcher zbot-calmwatch-$1 started"
}
start servo_calm_a 1 -1.5 -0.1 -1 -0.5 -4 -1.5 0.85
start servo_calm_b 0 -3 -0.2 -2 -1 -8 -0.8 0.70
