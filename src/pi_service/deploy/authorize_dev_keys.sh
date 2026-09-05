#!/usr/bin/env bash
# Install hardware/dev_authorized_keys into a Raspberry Pi SD card's rootfs.
#
# For the case where NO machine can SSH into the robot any more (the accepted
# key lived on a machine that got wiped). The card goes into any Linux box with
# a card reader; this writes the keys with the ownership and modes sshd's
# StrictModes insists on — getting those wrong is why a hand-made attempt fails
# silently with "Permission denied (publickey)".
#
#   sudo ./src/pi_service/deploy/authorize_dev_keys.sh /media/$USER/rootfs
#
# Run WITHOUT an argument to list the mounted partitions that look like a Pi
# rootfs. Afterwards: sync, unmount cleanly, card back into the Pi.
#
# The usual mistake this replaces: writing the key onto `bootfs` (FAT32, the
# only partition Windows shows). sshd never looks there.

set -euo pipefail

PI_USER="${2:-justin}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
KEYS="$REPO_ROOT/hardware/dev_authorized_keys"

fail() { printf '\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }
step() { printf '\033[36m==> %s\033[0m\n' "$*"; }

looks_like_rootfs() { [[ -f "$1/etc/rpi-issue" && -d "$1/home" ]]; }

if [[ $# -lt 1 ]]; then
    echo "usage: sudo $0 <mounted-rootfs> [pi-user]" >&2
    echo >&2
    echo "candidates found on this machine:" >&2
    found=0
    while read -r mp; do
        if looks_like_rootfs "$mp"; then echo "  $mp" >&2; found=1; fi
    done < <(findmnt -rno TARGET -t ext4)
    [[ $found -eq 1 ]] || echo "  (none — is the card inserted and the ext4" \
        "partition 'rootfs' mounted?)" >&2
    exit 1
fi

R="${1%/}"
[[ -n "$R" && -d "$R" ]]        || fail "'$1' is not a directory."
[[ "$1" != "/" ]]               || fail "refusing to touch the running system."
looks_like_rootfs "$R"          || fail "'$R' is not a Raspberry Pi OS rootfs \
(no etc/rpi-issue). The FAT32 'bootfs' partition is NOT the right one."
[[ -d "$R/home/$PI_USER" ]]     || fail "no home directory for '$PI_USER' in '$R'."
[[ -w "$R" ]]                   || fail "'$R' is not writable — mounted read-only?"
[[ -r "$KEYS" ]]                || fail "key list not found: $KEYS"
[[ $EUID -eq 0 ]]               || fail "run me with sudo (ownership must be set)."

HOME_DIR="$R/home/$PI_USER"
SSH_DIR="$HOME_DIR/.ssh"
AUTH="$SSH_DIR/authorized_keys"
# take ownership from the card, not from this machine's user numbering
OWNER="$(stat -c '%u:%g' "$HOME_DIR")"

step "target: $AUTH (owner $OWNER)"
install -d -m 700 -o "${OWNER%:*}" -g "${OWNER#*:}" "$SSH_DIR"
touch "$AUTH"

added=0 kept=0
while IFS= read -r line; do
    line="${line%$'\r'}"                       # tolerate CRLF from Windows edits
    [[ -z "${line// }" || "$line" == \#* ]] && continue
    ssh-keygen -l -f /dev/stdin <<<"$line" >/dev/null 2>&1 \
        || fail "not a valid public key line (wrapped across lines?): ${line:0:40}…"
    if grep -qxF "$line" "$AUTH"; then
        kept=$((kept + 1))
    else
        printf '%s\n' "$line" >> "$AUTH"
        added=$((added + 1))
    fi
done < "$KEYS"

chown "$OWNER" "$AUTH"
chmod 600 "$AUTH"
chmod 700 "$SSH_DIR"

step "$added key(s) added, $kept already present — authorized now:"
while IFS= read -r line; do
    [[ -z "${line// }" || "$line" == \#* ]] && continue
    ssh-keygen -l -f /dev/stdin <<<"$line" 2>/dev/null | sed 's/^/    /'
done < "$AUTH"

sync
step "done — unmount cleanly, then put the card back into the Pi"
echo "    udisksctl unmount -b <device>     # e.g. /dev/mmcblk0p2"
