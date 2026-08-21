#!/usr/bin/env bash
# One-command deploy of the Pi intent service — Linux/macOS counterpart of deploy_pi.ps1.
#
#   ./src/pi_service/deploy/deploy_pi.sh                       # full deploy (needs sudo on the Pi)
#   ./src/pi_service/deploy/deploy_pi.sh --skip-service        # code only, no sudo
#   ./src/pi_service/deploy/deploy_pi.sh --host justin@10.0.0.5
#
# Ships zbot_core + pi_service + calibration (servo_ids/joint_limits/joint_offsets)
# + demos to $PI_HOST:~/zbot, installs both packages editable into ~/venv,
# refreshes the systemd unit and health-checks /status.
# connection.json is deliberately NOT shipped: it is host-specific — the Pi falls
# back to port "auto" until you pin /dev/serial/by-id/... there.
#
# The systemd step runs sudo non-interactively; it needs either a sudo password
# prompt (interactive terminal) or the scoped NOPASSWD rules from
# /etc/sudoers.d/zbot-deploy on the Pi (see docs/pi-service.md).

set -euo pipefail

PI_HOST="justin@192.168.178.147"
SKIP_SERVICE=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --host) PI_HOST="$2"; shift 2 ;;
        --skip-service) SKIP_SERVICE=1; shift ;;
        *) echo "unknown argument: $1" >&2; exit 1 ;;
    esac
done

step() { printf '\033[36m==> %s\033[0m\n' "$*"; }
fail() { printf '\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

step "staging (source + calibration + demos, no venvs)"
STAGE="$(mktemp -d /tmp/zbot_deploy_stage.XXXXXX)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/src" "$STAGE/hardware"
cp -r "$REPO_ROOT/src/zbot_core" "$STAGE/src/zbot_core"
cp -r "$REPO_ROOT/src/pi_service" "$STAGE/src/pi_service"
find "$STAGE" -depth -type d \( -name .venv -o -name __pycache__ -o -name .pytest_cache \) -exec rm -rf {} +
for f in servo_ids.json joint_limits.json joint_offsets.json; do
    [[ -f "$REPO_ROOT/hardware/$f" ]] && cp "$REPO_ROOT/hardware/$f" "$STAGE/hardware/$f"
done
cp -r "$REPO_ROOT/demos" "$STAGE/demos"

TGZ="$STAGE/zbot_deploy.tgz"
tar -czf "$TGZ" -C "$STAGE" src hardware demos

step "copying to $PI_HOST:/tmp"
scp -q "$TGZ" "$PI_HOST:/tmp/zbot_deploy.tgz" \
    || fail "scp failed - robot off, or VPN blocking LAN?"

step "unpacking to ~/zbot + installing into ~/venv"
ssh "$PI_HOST" 'mkdir -p ~/zbot && tar -xzf /tmp/zbot_deploy.tgz -C ~/zbot &&
    rm /tmp/zbot_deploy.tgz &&
    ~/venv/bin/pip install -q -e ~/zbot/src/zbot_core -e ~/zbot/src/pi_service' \
    || fail "remote install failed"

if [[ $SKIP_SERVICE -eq 1 ]]; then
    step "done (systemd step skipped)"
    exit 0
fi

step "systemd unit install/restart"
ssh "$PI_HOST" 'sudo -n install -m 644 ~/zbot/src/pi_service/deploy/zbot-pi.service \
        /etc/systemd/system/zbot-pi.service &&
    sudo -n systemctl daemon-reload && sudo -n systemctl enable --now zbot-pi &&
    sudo -n systemctl restart zbot-pi' \
    || fail "systemd step failed (sudoers rule missing? use --skip-service for code-only)"

sleep 2
step "health check"
ssh "$PI_HOST" 'curl -s http://localhost:8460/status' \
    || fail "service not answering - inspect: ssh $PI_HOST journalctl -u zbot-pi -n 50"
echo
step "done - service reachable at http://$PI_HOST (port 8460, GET /status)"
