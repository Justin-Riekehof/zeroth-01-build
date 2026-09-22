#!/usr/bin/env bash
# Flash the head display board (Waveshare RP2040-LCD-1.28) — over SSH, on the
# Pi it is plugged into. See README.md. Needs `picotool` on the Pi (apt).
#
#   ./src/head_display/deploy_head.sh                 # backup, MicroPython, our files
#   ./src/head_display/deploy_head.sh --restore       # stock Waveshare firmware back
#   ./src/head_display/deploy_head.sh --files-only    # just re-copy the .py files
#   ./src/head_display/deploy_head.sh --host justin@10.0.0.5

set -euo pipefail

PI_HOST="justin@192.168.178.147"
MODE=full
UF2_URL="https://micropython.org/resources/firmware/RPI_PICO-20260824-v1.29.0.uf2"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --host) PI_HOST="$2"; shift 2 ;;
        --restore) MODE=restore; shift ;;
        --files-only) MODE=files; shift ;;
        *) echo "unknown argument: $1" >&2; exit 1 ;;
    esac
done

step() { printf '\033[36m==> %s\033[0m\n' "$*"; }
fail() { printf '\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

step "copying firmware sources to $PI_HOST:~/head_display"
ssh "$PI_HOST" 'mkdir -p ~/head_display' || fail "ssh failed — robot off, VPN?"
scp -q "$HERE"/gc9a01.py "$HERE"/qmi8658.py "$HERE"/main.py "$PI_HOST:~/head_display/"

# Everything below runs on the Pi. sudo lines are covered by
# /etc/sudoers.d/zbot-deploy (stop/start zbot-pi).
ssh "$PI_HOST" MODE="$MODE" UF2_URL="$UF2_URL" 'bash -s' <<'REMOTE'
set -euo pipefail
step() { printf '\033[36m    %s\033[0m\n' "$*"; }
fail() { printf '\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }
cd ~/head_display
export PATH="$HOME/.local/bin:$PATH"      # prebuilt picotool lives there (no apt needed)
command -v picotool >/dev/null || fail "picotool missing: apt install picotool, or the
    prebuilt aarch64 tarball from github.com/raspberrypi/pico-sdk-tools into ~/.local/bin"

port_of() { ls /dev/serial/by-id/ 2>/dev/null | grep -E "$1" | head -1 | sed 's|^|/dev/serial/by-id/|'; }
wait_port() {   # pattern, seconds
    for _ in $(seq 1 "$2"); do p=$(port_of "$1"); [[ -n "$p" ]] && { echo "$p"; return; }; sleep 1; done
    return 1
}

step "stopping zbot-pi (it holds the serial port)"
sudo -n systemctl stop zbot-pi
trap 'sudo -n systemctl start zbot-pi' EXIT

if [[ "$MODE" == "restore" ]]; then
    bak=$(ls -1 backup-*.bin 2>/dev/null | head -1)
    [[ -n "$bak" ]] || fail "no backup-*.bin here — nothing to restore"
    step "restoring stock firmware from $bak"
    picotool load -x "$bak" -t bin -o 0x10000000 -f
    wait_port "Pico" 20 >/dev/null || fail "board did not come back as a Pico"
    step "restored — stock demo running"
    exit 0
fi

if [[ "$MODE" == "full" ]]; then
    if ! ls backup-*.bin >/dev/null 2>&1; then
        step "saving the board's flash (stock firmware) -> backup-$(date +%F).bin"
        picotool save -a "backup-$(date +%F).bin" -f
        # picotool reboots it back into the app afterwards — wait for USB
        wait_port "Pico|MicroPython" 20 >/dev/null || fail "board did not re-enumerate after the backup"
        sleep 1
    fi
    if ! port_of MicroPython >/dev/null; then
        uf2=$(basename "$UF2_URL")
        [[ -f "$uf2" ]] || { step "downloading $uf2"; curl -fsSL -o "$uf2" "$UF2_URL"; }
        step "flashing MicroPython ($uf2)"
        picotool load -x "$uf2" -f
        wait_port "MicroPython" 25 >/dev/null || fail "no MicroPython serial port after flashing"
        sleep 2
    fi
fi

port=$(wait_port "MicroPython" 10) || fail "MicroPython board not found on USB"
~/venv/bin/python -c 'import mpremote' 2>/dev/null || {
    step "installing mpremote into ~/venv"; ~/venv/bin/pip install -q mpremote; }
step "copying gc9a01.py qmi8658.py main.py -> $port"
~/venv/bin/mpremote connect "$port" cp gc9a01.py qmi8658.py main.py : >/dev/null
# mpremote leaves the board stopped at the REPL — a hard reset runs main.py
# again (the USB connection drops with it, hence the ignored error)
~/venv/bin/mpremote connect "$port" exec "import machine; machine.reset()" >/dev/null 2>&1 || true
sleep 2
port=$(wait_port "MicroPython" 15) || fail "board did not come back after the reset"
sleep 2
step "first lines from the board:"
lines=$(timeout 3 cat "$port" | head -3 | cut -c1-140 || true)
[[ -n "$lines" ]] || fail "board is silent — main.py crashed? try: mpremote connect $port"
echo "$lines"
REMOTE

sleep 2
step "Pi service view of the head"
ssh "$PI_HOST" 'curl -s http://localhost:8460/head' | python3 -c '
import sys, json
h = json.load(sys.stdin)["imu"]; s = h.get("sample") or {}
print("   ", "connected" if h["connected"] else "NOT connected", h.get("port"),
      "| source:", s.get("source"), "| mood:", s.get("mood"), "| fps:", s.get("fps"))'
step "done — the eye should be looking at you. Orientation: README.md"
