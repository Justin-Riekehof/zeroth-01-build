#!/usr/bin/env bash
# Zeroth-01 Pi bring-up — the steps that need root. Run once:
#     sudo bash ~/zbot_setup.sh
#
# Everything else (venv, connection.json, deploy) is done from the dev laptop
# over the SSH key and needs no password.
set -euo pipefail

log() { printf '\033[36m==> %s\033[0m\n' "$*"; }
[[ $EUID -eq 0 ]] || { echo "must run as root: sudo bash $0" >&2; exit 1; }

# ---------------------------------------------------------------- journal cap
# An SD card dies from writes; an uncapped journal is the largest continuous
# source. NOT Storage=volatile: the post-mortem journal is what the 2026-08-23
# card failure cost us, so keep it persistent, just bounded.
log "capping the systemd journal at 50M"
if grep -qE '^#?SystemMaxUse=' /etc/systemd/journald.conf; then
    sed -i 's|^#\?SystemMaxUse=.*|SystemMaxUse=50M|' /etc/systemd/journald.conf
else
    printf '\nSystemMaxUse=50M\n' >>/etc/systemd/journald.conf
fi
systemctl restart systemd-journald
echo "    now: $(grep -E '^SystemMaxUse' /etc/systemd/journald.conf)"

# ------------------------------------------------------------------- sudoers
# Scoped NOPASSWD rule so deploy_pi.* can install/restart the unit without a
# password, and so the service can trigger a clean shutdown (GUI button).
# Validated with `visudo -c` BEFORE installing: a broken file in sudoers.d
# breaks sudo entirely and would lock this account out of root.
log "installing /etc/sudoers.d/zbot-deploy"
tmp="$(mktemp)"
cat >"$tmp" <<'RULES'
# Zeroth-01 deploy + service rights for justin. See docs/pi-bringup.md.
# Deploy (deploy_pi.sh / deploy_pi.ps1) — unit install and lifecycle:
justin ALL=(root) NOPASSWD: /usr/bin/install -m 644 /home/justin/zbot/src/pi_service/deploy/zbot-pi.service /etc/systemd/system/zbot-pi.service
justin ALL=(root) NOPASSWD: /usr/bin/systemctl daemon-reload
justin ALL=(root) NOPASSWD: /usr/bin/systemctl enable --now zbot-pi
justin ALL=(root) NOPASSWD: /usr/bin/systemctl disable zbot-pi
justin ALL=(root) NOPASSWD: /usr/bin/systemctl start zbot-pi
justin ALL=(root) NOPASSWD: /usr/bin/systemctl stop zbot-pi
justin ALL=(root) NOPASSWD: /usr/bin/systemctl restart zbot-pi
# Service SHUTDOWN_CMD — clean OS halt, protects the SD card:
justin ALL=(root) NOPASSWD: /usr/sbin/shutdown -h now
RULES

if visudo -c -q -f "$tmp"; then
    install -m 440 -o root -g root "$tmp" /etc/sudoers.d/zbot-deploy
    rm -f "$tmp"
    echo "    syntax OK, installed"
else
    rm -f "$tmp"
    echo "ERROR: sudoers syntax invalid — nothing was installed" >&2
    exit 1
fi

# ---------------------------------------------------------------------- notes
# Deliberately NOT done here:
#   swap      — this image swaps to zram0 (RAM-backed, no SD writes). Correct
#               as-is; dphys-swapfile is not installed and must not be.
#   noatime   — already set on / by the stock image.
#   dialout   — justin is already a member.
log "done — run the deploy from the laptop next"
