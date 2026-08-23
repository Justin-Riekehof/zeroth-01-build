# Pi bring-up — from a blank card to a green `/status`

What to do when the robot's Raspberry Pi needs a fresh OS: SD card died, card
replaced, or a move to USB-SSD boot. [pi-service.md](pi-service.md) starts at
"run the deploy script" and assumes the venv, the sudoers rule and the pinned
serial port already exist — **this document creates them.**

Written after the 2026-08-23 card failure, where the SD card's controller lost
its flash translation layer mid-run: the kernel kept answering pings from RAM
while every `fork()` from disk died, so `sshd` never got to its banner and
`zbot-pi` could not restart. Nothing was lost — `demos/`, calibration and code
all live in this repo — but the Pi-local setup had to be rebuilt from four
different documents. Hence this list.

**Every step below was executed and verified on 2026-08-23** against a fresh
Raspberry Pi OS Lite (Debian 13 Trixie, Python 3.13.5) on a Pi 4 Model B Rev 1.5.

## What the repo restores for you, and what it does not

| Restored by `deploy_pi.*` | Must be rebuilt by hand |
|---|---|
| `zbot_core` + `pi_service` source | Raspberry Pi OS itself, hostname, user |
| `demos/` (the repo is canonical) | SSH authorized key |
| `servo_ids` / `joint_limits` / `joint_offsets` | `~/venv` |
| the `zbot-pi` systemd unit | `/etc/sudoers.d/zbot-deploy` (→ `pi_setup.sh`) |
| | `~/zbot/hardware/connection.json` (pinned serial port) |
| | journal cap (→ `pi_setup.sh`) |

The DHCP reservation survives: it is bound to the Pi's MAC, not to the card.
Same Pi, same reservation, same `192.168.178.147`.

## 1. Flash the card

Raspberry Pi Imager → **Raspberry Pi OS Lite (64-bit)**. Before writing, open
the settings gear and set:

- hostname `pixel2`
- username `justin` + a password (needed once, for step 4 and local console)
- **SSH → public key only**, paste the **contents** of the dev laptop's
  `~/.ssh/id_ed25519.pub` (the whole `ssh-ed25519 AAAA... justin-laptop` line), or
  click DURCHSUCHEN and pick the file. The Imager does not accept a path here
- WLAN SSID + password, country `DE`
- locale/timezone `Europe/Berlin`

Setting these here saves the whole headless-first-boot dance. On a card that was
bought online, run **H2testw** (Windows) or **f3write/f3read** (Linux) against it
*before* flashing — counterfeit and dead-on-arrival cards are common, and both
fail silently until they eat data.

## 2. First boot and reachability

A reinstall means new SSH host keys, so the laptop will refuse to connect with
`REMOTE HOST IDENTIFICATION HAS CHANGED`. That is expected here, not an attack —
drop the stale entry first:

```bash
ssh-keygen -R 192.168.178.147
ssh justin@192.168.178.147
```

If the IP is not there yet, check the DHCP reservation in the FritzBox. Do not
use `pixel2.local` or `pixel2.fritz.box` in any config — mDNS has served a stale
ghost entry before, and the `.fritz.box` name resolves IPv6-only while the
service binds IPv4.

> **Pitfall:** ProtonVPN on the dev laptop blocks LAN access. Enable "Allow LAN
> connections" or disconnect, otherwise SSH and HTTP to the robot both fail.

## 3. Virtualenv

```bash
python3 -m venv ~/venv
```

That is the whole step. Both packages declare `requires-python >=3.12` and
Trixie ships 3.13; `python3-venv` is already present on the Lite image, and the
deploy's `pip install -e` pulls fastapi, uvicorn, pydantic, ftservo-python-sdk
and pyserial automatically.

Two things the stock image already gets right — **verify, do not "fix"**:

- **`dialout` membership.** The Imager-created user is already in it. Check with
  `id -nG`; only run `sudo usermod -aG dialout justin` if it is genuinely absent.
- **Swap.** Trixie swaps to **`/dev/zram0`** via `systemd-zram-generator` —
  compressed RAM, *zero* SD-card writes. `dphys-swapfile` is not installed and
  must not be. Older Pi guides tell you to disable swap to save the card; that
  advice does not apply to this image and would only cost you RAM headroom.
  Confirm with `cat /proc/swaps` — if it says `zram0`, you are done.
- **`noatime`** is already set on `/` by the stock image (`grep " / " /proc/mounts`).

## 4. Root-only setup — one script

Journal cap and the sudoers rule need root, and `sudo` on a fresh image still
asks for a password. Both live in [`pi_setup.sh`](../src/pi_service/deploy/pi_setup.sh):

```bash
scp src/pi_service/deploy/pi_setup.sh justin@192.168.178.147:~/
ssh -t justin@192.168.178.147 "sudo bash ~/pi_setup.sh"
```

It does exactly two things:

1. **Caps the systemd journal** at `SystemMaxUse=50M`. An uncapped journal is the
   largest continuous write source on the card. Deliberately *not*
   `Storage=volatile`, even though that saves more — a volatile journal is gone
   after a crash, and the post-mortem journal is precisely what the 2026-08-23
   failure cost us. Capped-but-persistent is the right trade.
2. **Installs `/etc/sudoers.d/zbot-deploy`**, validated with `visudo -c` *before*
   it goes live — a syntax error in `sudoers.d` breaks `sudo` outright and would
   lock the account out of root.

The rule it installs, for reference:

```
justin ALL=(root) NOPASSWD: /usr/bin/install -m 644 /home/justin/zbot/src/pi_service/deploy/zbot-pi.service /etc/systemd/system/zbot-pi.service
justin ALL=(root) NOPASSWD: /usr/bin/systemctl daemon-reload
justin ALL=(root) NOPASSWD: /usr/bin/systemctl enable --now zbot-pi
justin ALL=(root) NOPASSWD: /usr/bin/systemctl disable zbot-pi
justin ALL=(root) NOPASSWD: /usr/bin/systemctl start zbot-pi
justin ALL=(root) NOPASSWD: /usr/bin/systemctl stop zbot-pi
justin ALL=(root) NOPASSWD: /usr/bin/systemctl restart zbot-pi
justin ALL=(root) NOPASSWD: /usr/sbin/shutdown -h now
```

Verify it before trusting the deploy — `sudo -n -l <cmd>` checks permission
without executing:

```bash
sudo -n systemctl daemon-reload                    # must succeed silently
sudo -n -l /usr/sbin/shutdown -h now               # must echo the command back
```

The `shutdown` line is what makes the GUI's "shutdown Pi" button work. Note that
under usr-merge `/usr/sbin/shutdown` is a symlink to `systemctl` — sudo still
matches on the literal path `service.py` invokes, so the rule is correct as
written (verified 2026-08-23).

## 5. Serial adapter

Waveshare Bus Servo Adapter (A) V1.1, board jumper in position **B** (USB mode),
into a Pi USB port. Servo power on. Then pin the port so it survives
re-enumeration:

```bash
ls /dev/serial/by-id/     # -> usb-1a86_USB_Single_Serial_5B8E112354-if00
mkdir -p ~/zbot/hardware
nano ~/zbot/hardware/connection.json
```

```json
{
  "port": "/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B8E112354-if00"
}
```

Substitute the real `by-id` name — it carries the adapter's serial number, so it
differs per adapter. Only `port` is needed here: `mode` and `pi_url` are
client-side settings and `ConfigStore.connection()` fills them from its defaults.
This file is host-specific and deliberately never shipped by the deploy — later
deploys preserve it.

## 6. Deploy from the dev laptop

```powershell
.\src\pi_service\deploy\deploy_pi.ps1          # Windows
```
```bash
./src/pi_service/deploy/deploy_pi.sh           # Linux / macOS
```

The health check should print JSON containing `"bus": {"connected": true, ...}`
with the pinned `by-id` path. Then confirm the unit survives a reboot:

```bash
ssh justin@192.168.178.147 'systemctl is-enabled zbot-pi; systemctl is-active zbot-pi'
```

## 7. Power sanity check — do this before trusting the build

The Pi's PMIC latches undervoltage events that a multimeter averages away, so
this is a *better* brownout detector than a meter on the buck converter.

```bash
vcgencmd get_throttled     # idle, as a baseline
```

Then drive the robot — a demo, not just idle hold; the inrush at servo start is
the critical moment, not the holding current — and read it again.

| Value | Meaning |
|---|---|
| `0x0` | supply is fine |
| bit 0 set (`0x1`) | under-voltage **right now** |
| bit 16 set (`0x10000`) | under-voltage **has occurred** since boot |
| bit 1 / bit 17 | ARM frequency capped — usually thermal, worth checking too |

Anything other than `0x0` after a run means the 5 V rail sags under servo load.
Fix that before anything else: it corrupts storage regardless of how cleanly you
shut down, it resets the Pi mid-demo (leaving the servos holding torque with no
stop control), and it rules out the USB-SSD upgrade, which adds 2–3 W to the same
rail.

Only if this shows a problem is it worth putting a scope on the buck converter —
and it must be a scope or a min/max-capturing meter, because the dips are
milliseconds long.

## 8. Smoke test from the laptop

```powershell
curl.exe -s http://192.168.178.147:8460/status
curl.exe -s http://192.168.178.147:8460/demos     # expect the repo's demos
curl.exe -s -X POST http://192.168.178.147:8460/demo/wave
curl.exe -s -X POST http://192.168.178.147:8460/stop      # mid-run: E-stop
curl.exe -s -X POST http://192.168.178.147:8460/release
```

Then switch the GUI to wireless mode and confirm the demo dropdown fills — in
that mode the list comes from the robot, not the repo.

## 9. Operating rules that keep the card alive

- **Always shut down cleanly.** GUI "shutdown Pi" button, or `sudo shutdown -h
  now`. Cut the main switch only after the ACT LED stops; the servos keep
  holding through the shutdown.
- Re-check `vcgencmd get_throttled` after any change to the power wiring.
- Prefer High Endurance cards (Samsung PRO Endurance, SanDisk Max Endurance),
  64 GB rather than 32 — endurance scales with capacity. Avoid Extreme / Evo /
  Ultra: high sequential speed, low write endurance.
- SD cards have no SMART, so you get no warning. A USB SSD does — if you move to
  one, add `sudo smartctl -a -d sat /dev/sda` to a monthly check.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `REMOTE HOST IDENTIFICATION HAS CHANGED` | expected after a reinstall — `ssh-keygen -R 192.168.178.147` |
| `scp` / `ssh` fail, host unreachable | ProtonVPN blocking LAN; or Pi off |
| ssh: `kex_exchange_identification: Connection closed` | TCP up but every fork dies — storage gone, kernel still running from RAM. Not recoverable remotely |
| deploy: "systemd step failed" | `/etc/sudoers.d/zbot-deploy` missing → step 4, or use `--skip-service` |
| `/status` shows `"connected": false` | adapter jumper not on **B**, servo power off, or `connection.json` points at a stale `by-id` path |
| GUI demo list empty in wireless mode | the Pi is the source there — service down or unreachable; check port 8460 |
| service dead after a reboot | `systemctl is-enabled zbot-pi` — the deploy's `enable --now` may have been skipped |
