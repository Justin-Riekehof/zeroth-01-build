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
| `demos/` (the repo is canonical) | SSH authorized keys — the *list* is in the repo ([hardware/dev_authorized_keys](../hardware/dev_authorized_keys)), but it has to be put on the Pi once (Imager, or `authorize_dev_keys.sh`) before a deploy can reach it |
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
- **SSH → public key only**, paste the **contents** of
  [hardware/dev_authorized_keys](../hardware/dev_authorized_keys) — every dev
  machine's public key, one per line, comments stripped. The Imager does not
  accept a path here, and it takes only one line at a time, so paste each key
  separately. Pasting just *one* machine's key is how you lock yourself out
  later: see *Recovering SSH access* below
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

## 6. Deploy from a dev machine

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

## 8. Smoke test from a dev machine

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

## Recovering SSH access from a new dev machine

`sshd` on the robot is **publickey-only** and there is deliberately no way in
through the intent service (demo saves are slug-restricted to `demos/*.json`)
or the serial console (it belongs to the servo UART). So when the machine
holding the accepted key is wiped or replaced, the robot becomes unreachable
for deploys, and nothing but physical access gets it back. That happened on
2026-09-05, when the dev laptop was reset.

**First, check whether you actually need the card.** Try every machine you
still have, including freshly set-up ones:

```bash
ssh justin@192.168.178.147 'echo OK; hostname'
```

Any machine that answers can authorize the others in one line, no disassembly:

```bash
ssh justin@192.168.178.147 'cat >> ~/.ssh/authorized_keys' < hardware/dev_authorized_keys
```

**Only a Windows machine has a card reader?** Windows cannot write the ext4
`rootfs`, so the steps below do not work there — re-flash the card instead:
[Runbook: re-flash from the Windows laptop](#runbook-re-flash-from-the-windows-laptop).

**If nothing answers, go through the SD card.** The keys live in the repo, so
any Linux box with a card reader can do it — the robot's own machine does not
have to be the one holding a key:

1. Shut the Pi down cleanly (GUI ⏻, wait for the ACT LED, then main switch).
   Pulling a card from a running Pi is how the last one died.
2. Card into a reader. Identify the partitions — you want the **ext4** one
   labelled `rootfs`, *not* the FAT32 `bootfs`:
   ```bash
   lsblk -o NAME,SIZE,FSTYPE,LABEL,MOUNTPOINT
   udisksctl mount -b /dev/mmcblk0p2       # if it did not auto-mount
   ```
   Writing the key onto `bootfs` is the classic failed attempt: it is the only
   partition Windows shows, and `sshd` never looks there.
3. Install every key from the repo, with the ownership and modes `StrictModes`
   demands (wrong ones fail silently as `Permission denied (publickey)`):
   ```bash
   sudo ./src/pi_service/deploy/authorize_dev_keys.sh /media/$USER/rootfs
   ```
   Run it without an argument and it lists the mounted partitions that look
   like a Pi rootfs. It refuses anything that is not one, validates each key
   line, and is safe to run twice.
4. `sync`, unmount cleanly, card back into the Pi, boot, then verify from the
   machine you want to deploy from — with `ssh-keygen -R 192.168.178.147`
   first if the card was re-flashed rather than edited.

**Adding a machine later** (a rebuilt laptop, a second workstation): append its
`~/.ssh/id_ed25519.pub` to
[hardware/dev_authorized_keys](../hardware/dev_authorized_keys), commit, and
install it over SSH from a machine that still has access. Doing it while access
exists is the whole point of keeping the list in the repo — it costs one
command instead of opening the robot.

## Runbook: re-flash from the Windows laptop

**The situation since 2026-09-05:** no machine can SSH into the robot, and the
only card reader is in the Windows 11 laptop. Windows sees just the FAT32
`bootfs` and cannot write the ext4 `rootfs` where `authorized_keys` lives, so
`authorize_dev_keys.sh` is not an option there. Instead the card is re-flashed
with Raspberry Pi Imager, which writes the keys itself — this time **all** of
them. The price is the Pi-local setup (venv, sudoers rule, journal cap,
`connection.json`), which steps 5–6 rebuild; demos, calibration and code all
come back from the repo. Budget about an hour.

> A Linux machine with a card reader (a cheap USB reader on the workstation
> will do) keeps the existing install via the section above and beats this
> route — use it if one is at hand.

`powershell` blocks run on the laptop, `bash` blocks inside an SSH session on
the Pi.

### 0. Prepare the laptop — robot not involved yet

1. Repo up to date: `git pull` — you need this runbook and the current
   [hardware/dev_authorized_keys](../hardware/dev_authorized_keys).
2. Install Raspberry Pi Imager from <https://www.raspberrypi.com/software/>
   (or `winget install RaspberryPiFoundation.RaspberryPiImager`).
3. `ssh -V` must print a version — the OpenSSH client ships with Windows 11.
4. ProtonVPN: **"Allow LAN connections"** on, or disconnect. Otherwise every
   step against `192.168.178.147` fails with a timeout.
5. A freshly reset Windows refuses to run `.ps1` files. Once, for your user:
   ```powershell
   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
   ```

### 1. Give the laptop a key and put it on the list

The reset took the laptop's old private key with it — that is the whole reason
for this runbook. If `Test-Path $HOME\.ssh\id_ed25519.pub` prints `True`, reuse
that key and skip the `ssh-keygen` line; never overwrite an existing key.

```powershell
ssh-keygen -t ed25519 -C "justin@laptop"      # Enter = default path; passphrase optional
Get-Content $HOME\.ssh\id_ed25519.pub | Add-Content -Encoding ascii hardware\dev_authorized_keys
Select-String '^ssh-' hardware\dev_authorized_keys    # expect TWO lines: workstation + laptop
git add hardware/dev_authorized_keys
git commit -m "dev keys: add the laptop"
git push
```

Both lines go onto the card in step 3. With two machines holding access,
resetting one of them can no longer lock the robot out.

### 2. Save what only the robot has, then shut it down

Robot on, still with its **old** card. One last check first: should
`ssh justin@192.168.178.147 'echo OK'` answer from the workstation against all
odds, the one-liner in the section above replaces this whole runbook.

SSH is locked, but the intent service on port 8460 answers over HTTP. Demos taught in wireless mode are stored on the
robot; the GUI writes them to the repo as well, but check before the card is
erased:

```powershell
curl.exe -s http://192.168.178.147:8460/demos -o $HOME\pi_backup_demos.json
(Get-Content $HOME\pi_backup_demos.json | ConvertFrom-Json).demos.name   # on the robot
Get-ChildItem demos\*.json | ForEach-Object BaseName                      # in the repo
```

A demo that exists only on the robot goes into the repo before you continue —
the deploy in step 6 fills the fresh card from `demos/`, so the repo is the
only copy that survives (replace `NAME` twice):

```powershell
$d = (Get-Content $HOME\pi_backup_demos.json | ConvertFrom-Json).demos | Where-Object name -eq "NAME"
[IO.File]::WriteAllText("$PWD\demos\NAME.json", ($d | ConvertTo-Json -Depth 10))
```

`WriteAllText` rather than `Set-Content -Encoding utf8`: Windows PowerShell
writes a BOM, and the loader then skips the file as invalid. Commit and push
whatever you restored.

Then shut down cleanly — GUI ⏻ in wireless mode, or:

```powershell
curl.exe -s -X POST http://192.168.178.147:8460/shutdown
```

Wait until the green ACT LED stays dark, then the main switch, and only then
pull the card. Pulling it from a running Pi is how the last one died. If the
service does not answer at all, skip the backup — the repo is canonical — and
wait for the ACT LED to stop flickering before cutting power.

### 3. Flash the card with Imager

1. Card into the laptop's reader. Windows will likely pop up *"You need to
   format the disk in drive X: before you can use it"* — that is the ext4
   partition it cannot read. **Cancel**, every time; Imager does the erasing.
2. In Imager: **Device** Raspberry Pi 4 · **OS** Raspberry Pi OS (other) →
   **Raspberry Pi OS Lite (64-bit)** · **Storage** the SD card. Check the size
   before you confirm — it must not be a USB stick or a backup drive.
3. OS customisation ("Edit settings" in Imager 1.x, the customisation steps of
   the wizard in Imager 2.x):

   | Setting | Value |
   |---|---|
   | Hostname | `pixel2` |
   | Username / password | `justin` / a password — **write it down**, step 5 needs it once for `sudo` |
   | Wireless LAN | SSID + password, country `DE` |
   | Locale | time zone `Europe/Berlin`, keyboard `de` |
   | SSH | **enabled, public-key authentication only** |
   | Authorized keys | **both** `ssh-ed25519 …` lines from `hardware/dev_authorized_keys`, each as its own entry, full line including the trailing comment — not the `#` lines |

   Imager may offer to pre-fill the laptop's own key. Keep it, but add the
   workstation line by hand: a card with a single key is exactly how the robot
   got locked out.
4. **Write** → confirm the erase → wait for writing **and** verifying to
   finish. Eject in Windows, pull the card.

### 4. First boot

Card into the Pi, power on — servo power can stay off for now. The first boot
applies the settings, grows the filesystem and reboots once: give it 2–3
minutes. The DHCP reservation is bound to the Pi's MAC, so it comes back at
`192.168.178.147`.

```powershell
ssh-keygen -R 192.168.178.147                    # re-flash = new host keys; expected
ssh justin@192.168.178.147 'echo OK; hostname'    # accept the fingerprint with "yes"
```

| Result | Meaning |
|---|---|
| `OK`, `pixel2` | access restored — continue |
| timeout / `No route to host` | still booting, VPN blocking LAN, or Wi-Fi settings wrong — look for `pixel2` in the FritzBox device list |
| `Permission denied (publickey)` | the keys did not make it onto the card as intended — back to step 3; Imager keeps the settings |

### 5. Rebuild the Pi-local setup

Copy the root-only script over, then open a shell on the Pi:

```powershell
scp src/pi_service/deploy/pi_setup.sh justin@192.168.178.147:~/
ssh -t justin@192.168.178.147
```

On the Pi — the background for each line is in [3. Virtualenv](#3-virtualenv)
to [5. Serial adapter](#5-serial-adapter) above:

```bash
sed -i 's/\r$//' ~/pi_setup.sh     # a Windows checkout has CRLF line endings; bash chokes on them
sudo bash ~/pi_setup.sh            # asks for the Imager password once
sudo -n systemctl daemon-reload && echo SUDO-OK    # sudoers rule is live
sudo -n -l /usr/sbin/shutdown -h now               # must echo the command back (GUI ⏻)
python3 -m venv ~/venv
id -nG                             # must contain dialout
cat /proc/swaps                    # must show /dev/zram0
```

Servo adapter: Waveshare jumper on **B**, USB into the Pi, servo power on. Then
pin the port:

```bash
ls /dev/serial/by-id/              # expect usb-1a86_USB_Single_Serial_5B8E112354-if00
mkdir -p ~/zbot/hardware
cat > ~/zbot/hardware/connection.json <<'EOF'
{
  "port": "/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B8E112354-if00"
}
EOF
exit
```

If `ls` shows a different name, write that one into the file — it carries the
adapter's serial number.

### 6. Deploy

```powershell
.\src\pi_service\deploy\deploy_pi.ps1
```

This ships Pi service **v6** (wireless joint-range calibration) and the ±95°
shoulder limits, neither of which the robot has had so far. The health check
at the end must print `"bus": {"connected": true, ...}` with the `by-id` path.

### 7. Verify

```powershell
ssh justin@192.168.178.147 'systemctl is-enabled zbot-pi; systemctl is-active zbot-pi'  # enabled, active
curl.exe -s http://192.168.178.147:8460/demos        # the repo's demos
curl.exe -s http://192.168.178.147:8460/limits       # shoulder pitch now ±95°
ssh justin@192.168.178.147 vcgencmd get_throttled    # baseline: throttled=0x0
```

Then run `push_ups` as usual — robot set up for it, E-stop at hand
(`curl.exe -s -X POST http://192.168.178.147:8460/stop`). The log in `/status`
must no longer show the shoulders clamped to ±60° (`left_shoulder_pitch +92.5
-> +60.0`). Read `get_throttled` once more afterwards; anything other than
`0x0` means [7. Power sanity check](#7-power-sanity-check--do-this-before-trusting-the-build)
comes first.

### 8. Back at the workstation

```bash
git pull                                  # picks up the laptop's key line
ssh-keygen -R 192.168.178.147
ssh justin@192.168.178.147 'echo OK'      # both dev machines have access again
```

Then tick the entry off in the README roadmap.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `REMOTE HOST IDENTIFICATION HAS CHANGED` | expected after a reinstall — `ssh-keygen -R 192.168.178.147` |
| `scp` / `ssh` fail, host unreachable | ProtonVPN blocking LAN; or Pi off |
| `Permission denied (publickey)` from every machine | the accepted key is gone with its machine — *Recovering SSH access* above |
| Windows: *"You need to format the disk"* when the card goes in | that is the ext4 `rootfs`, which Windows cannot read — Cancel |
| `pi_setup.sh`: `$'\r': command not found` | checked out on Windows with CRLF line endings — `sed -i 's/\r$//' ~/pi_setup.sh` |
| `.ps1`: "running scripts is disabled on this system" | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, once per user |
| key installed by hand, still `Permission denied` | written to `bootfs` instead of `rootfs`, or wrong owner/mode — `authorize_dev_keys.sh` sets both |
| ssh: `kex_exchange_identification: Connection closed` | TCP up but every fork dies — storage gone, kernel still running from RAM. Not recoverable remotely |
| deploy: "systemd step failed" | `/etc/sudoers.d/zbot-deploy` missing → step 4, or use `--skip-service` |
| `/status` shows `"connected": false` | adapter jumper not on **B**, servo power off, or `connection.json` points at a stale `by-id` path |
| GUI demo list empty in wireless mode | the Pi is the source there — service down or unreachable; check port 8460 |
| service dead after a reboot | `systemctl is-enabled zbot-pi` — the deploy's `enable --now` may have been skipped |
