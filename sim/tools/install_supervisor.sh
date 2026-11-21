#!/usr/bin/env bash
# Installs the systemd user timer that runs sim/tools/train_supervisor.sh every 10 min (also after a reboot, with linger).
# Disable: systemctl --user disable --now zbot-supervisor.timer
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; D="$HOME/.config/systemd/user"; mkdir -p "$D"
cat > "$D/zbot-supervisor.service" <<EOF
[Unit]
Description=Zbot training supervisor (start the next run when the GPU is idle)
[Service]
Type=oneshot
WorkingDirectory=$ROOT
Environment=HOME=$HOME
Environment=PATH=$HOME/.local/node/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=$ROOT/sim/tools/train_supervisor.sh
TimeoutStartSec=3600
EOF
cat > "$D/zbot-supervisor.timer" <<EOF
[Unit]
Description=Run the zbot training supervisor every 10 minutes
[Timer]
OnBootSec=5min
OnUnitActiveSec=10min
Persistent=true
[Install]
WantedBy=timers.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now zbot-supervisor.timer
echo "zbot-supervisor.timer enabled"
