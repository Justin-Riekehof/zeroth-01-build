# Pi intent service — deploy & bring-up

The wireless-mode backend: a FastAPI service on the Raspberry Pi
(`justin@192.168.178.147`) that executes demos **locally** against the servo bus
through the same `zbot_core` engine the desktop GUI uses. Clients send
high-level intents only — per-cycle setpoints never cross Wi-Fi
(see [robot-context.md](robot-context.md)). Limits, mount offsets and the
corrupt-calibration guard are enforced on the Pi, never trusted from clients.

## API (port 8460)

| Endpoint | Effect |
|---|---|
| `GET /status` | bus state, watchdog state, **battery** (pack voltage via the servo bus, level, halt state), live engine snapshot (phase, poses, log) |
| `GET /demos` | demos available on the robot |
| `POST /demos` | save a demo onto the robot (wireless teach-in; the GUI also saves to the repo, which stays canonical) |
| `POST /demos/delete` | remove a demo from the robot (`{"name": "..."}`) |
| `GET /limits` | the joint ranges this robot enforces |
| `POST /limits` | calibrate one joint's range (`{"joint": "...", "min_deg": -90, "max_deg": 45, "symmetric": true}`) — wireless calibration; takes effect on the next run without a redeploy, the GUI writes the same values into the repo, which stays canonical |
| `GET /robot_pose` | hand-posed robot pose in CAD-frame degrees (wireless teach-in capture) |
| `POST /demo/{name}` | play a taught-in demo, hold the final pose |
| `POST /center` | all configured servos to center (`{"hold": true, "speed": 300}`) |
| `POST /release` | torque off — all, or `{"joints": ["right_elbow_yaw"]}` |
| `POST /lock` | freeze joints at their **current** position (torque on) — all, or `{"joints": [...]}`; teach-in: pose a limb, lock it, pose the next |
| `POST /shutdown` | clean OS shutdown (SD-card-safe) — servos keep holding; cut the main switch after the ACT LED stops. Needs the shutdown line in `/etc/sudoers.d/zbot-deploy` |
| `POST /stop` | **E-stop**: aborts a run; when idle-holding a pose it releases all torque directly |
| `POST /connect` | (re)open the serial bus after an error |
| `POST /heartbeat` | feeds the streaming watchdog (future teleop; demos don't need it) |

Environment: `ZBOT_ROOT` (config root, default `~/zbot`), `ZBOT_SIMULATE=1`
(SimBus, no hardware), `ZBOT_PORT` (default 8460).

## Battery monitor — the software shutdown before the hardware cutoff

The Pi has no ADC, so the service reads the pack voltage the way the servos
see it: register 62 (0.1 V steps) of the first configured servo that answers,
every 2 s. That rail is the 3S LiPo behind fuse, anti-spark switch and XY-CD63
relay, so it reads a little below the pack. `/status.battery` carries
`volts`, `level` (`ok` / `warn` / `low` / `unknown`), `min_v`, `low_for_s` and
`shutdown` (`null` / `halting` / `failed`); the GUI shows it next to the
⏻ button.

Below `shutdown_v` for `hold_s` the service aborts a running demo (its runner
releases torque; an idle-held pose keeps holding, like the ⏻ button) and runs
the same `shutdown -h now` as `POST /shutdown` — once. Servo inrush sags the
rail for milliseconds, so the 10 s hold ignores it; an empty pack does not
recover. A failed halt (sudoers rule missing) is logged loudly and retried
every 60 s.

**How the halt is announced:** right before the halt the service sends
`alert battery` to the head display, which switches from the eye to a pulsing
red "BATTERY / EMPTY / PI OFF" screen and keeps it — the board stays powered
after the Pi is gone. The GUI shows a red full-screen banner ("BATTERY EMPTY —
the Pi shut itself down") that stays until acknowledged and updates to "Pi is
DOWN — cut the main switch" once the Pi stops answering.

| Event | Default | Where |
|---|---|---|
| warning in log + GUI | **11.1 V** (3.7 V/cell) | `warn_v` |
| software shutdown after `hold_s` | **10.8 V** (3.6 V/cell), default hold **10 s**; the robot `pixel2` runs with **30 s** since 2026-09-22 so that load peaks (push-ups) do not trigger it | `shutdown_v`, `hold_s` |
| XY-CD63 hardware cutoff | **≤ 10.5 V** | set on the module — **must stay below `shutdown_v`**, otherwise the relay wins and the card sees a hard power loss again |

`hold_s` is safe to raise: the Pi's 5 V comes from the Pololu buck, which regulates
down to ~6 V of pack voltage, so a sagging pack never reaches the Pi. The only hazard is
the XY-CD63 relay cutting power hard — that depends on the module's own threshold and
delay, not on `hold_s`. Set the module's delay to a few seconds as well, so short sags
do not trip it. A longer hold only delays the *clean* shutdown of a genuinely empty
pack (3.6 V/cell) by that many seconds, which the LiPo tolerates.

Override per robot in `~/zbot/hardware/connection.json` (host-specific, never
shipped by the deploy):

```json
{"battery": {"enabled": true, "servo_id": null, "warn_v": 11.1,
             "shutdown_v": 10.8, "hold_s": 10, "period_s": 2}}
```

`servo_id: null` = the lowest configured ID that answers. The monitor is
started with the service and stops with it; `enabled: false` turns it off (bench
supply without a pack, or an external monitor).

## Flight recorder — crash analysis (since 2026-09-22)

The Pi kept dropping off the network mid-run and the journal of the dead boot was
gone every time (a hard power cut loses everything journald has not synced yet —
by default up to 5 minutes). The service therefore writes its own **flight
recorder**: `~/zbot/logs/flight-YYYYMMDD.log`, every line flushed + fsynced, so a
power cut loses at most the line being written. Files older than 14 days are removed.

| Line | Content |
|---|---|
| `boot` | once per service start: boot id, uptime, API version, first vitals |
| `engine` | every engine log line as it happens (bus, runs, clamps, warnings) |
| `vitals` | every 2 s: pack voltage + level (servo reading), `vcgencmd get_throttled` flags — `U` = under-voltage on the 5 V rail **now**, `u` = since boot, `T`/`t` throttled, `F`/`f` frequency capped, `S`/`s` soft temperature limit — CPU temperature, Wi-Fi link/level, load |

Reading it after a crash (the file survives the reboot):

```bash
ssh justin@192.168.178.147 'tail -n 80 ~/zbot/logs/flight-$(date +%Y%m%d).log'
curl -s http://192.168.178.147:8460/flight?n=80 | jq -r '.lines[]'   # while it runs
```

What to look for in the last lines before the gap: a `pack` voltage diving towards
10.5 V (XY-CD63 relay), a `U`/`u` flag (the Pi's own 5 V rail sagged — Pololu, cable,
USB-C plug), or nothing unusual (Wi-Fi/power switch). `vcgencmd get_throttled`
keeps the *since boot* bits until the next reboot, so `u` in the first `boot` line of
a new boot is not the crash, only the `vitals` lines before the gap are.

Optional, needs sudo on the Pi — make journald keep the last seconds too:

```bash
sudo mkdir -p /etc/systemd/journald.conf.d
printf '[Journal]\nStorage=persistent\nSyncIntervalSec=2s\n' | sudo tee /etc/systemd/journald.conf.d/zbot.conf
sudo systemctl restart systemd-journald
```

Related mitigation in the engine: group starts are **staggered** (`stagger_ms` in
`hardware/motion_limits.json`, default 40 ms → 16 servos spread over 0.6 s) so the
inrush currents of servos leaving torque-off do not add up — a plain *center* with the
robot held in the air was enough to drop the Pi.

## Deploy (one command, from the repo root)

```powershell
.\src\pi_service\deploy\deploy_pi.ps1          # Windows laptop
```
```bash
./src/pi_service/deploy/deploy_pi.sh           # Linux workstation / macOS
```

Both scripts do the same thing; `--host justin@<ip>` / `-PiHost` overrides the
target. The systemd step runs sudo **non-interactively** on the Pi: it relies on
the scoped rule `/etc/sudoers.d/zbot-deploy` (installed 2026-08-21), which allows
exactly the six unit-install/start/stop/restart commands and nothing else. If
that rule is ever missing, deploy with `--skip-service` / `-SkipService` and run
the systemd commands manually over `ssh -t`.

What it does:

1. Stages `zbot_core` + `pi_service` + calibration
   (`servo_ids/joint_limits/joint_offsets/center_pose/motion_limits.json`) + `demos/` — teach-in
   happens on the laptop in USB mode; every deploy syncs the results to the
   robot. `connection.json` is host-specific and never shipped.
2. Copies the bundle to `~/zbot` on the Pi and installs both packages
   editable into the existing `~/venv`.
3. Installs/refreshes the systemd unit `zbot-pi` (the only step that needs
   sudo; `-SkipService` deploys code only) and health-checks `/status`.

## First bring-up on the real bus

> Starting from a **blank card** — fresh OS, no `~/venv`, no sudoers rule — the
> steps before this one are in [pi-bringup.md](pi-bringup.md).

1. Plug the Waveshare adapter (jumper **B**) into the Pi's USB, servo power on.
2. On the laptop: ProtonVPN → **"Allow LAN connections"** (or disconnect),
   otherwise `192.168.178.147` is unreachable.
3. Run the deploy script. The health check should print JSON with
   `"bus": {"connected": true, ...}`.
4. Pin the serial port (recommended — survives re-enumeration):
   ```bash
   ssh justin@192.168.178.147
   ls /dev/serial/by-id/          # -> usb-1a86_USB_Single_Serial-...
   nano ~/zbot/hardware/connection.json   # {"port": "/dev/serial/by-id/usb-..."}
   sudo systemctl restart zbot-pi
   ```
   Later deploys preserve this file.
5. Smoke test from the laptop (PowerShell):
   ```powershell
   curl.exe -s http://192.168.178.147:8460/status
   curl.exe -s http://192.168.178.147:8460/demos
   curl.exe -s -X POST http://192.168.178.147:8460/demo/wave
   curl.exe -s -X POST http://192.168.178.147:8460/stop      # mid-run: E-stop
   curl.exe -s -X POST http://192.168.178.147:8460/release
   ```
   Expected: wave plays exactly as in USB mode; stop aborts instantly and
   releases all torque; release lets the held pose go limp.

## Troubleshooting

- **Host unreachable** → ProtonVPN LAN setting (see above), or use the
  FritzBox IP directly instead of `192.168.178.147`.
- **Service logs** → `ssh justin@192.168.178.147 journalctl -u zbot-pi -f`
- **`Permission denied: /dev/ttyUSB0`** → `sudo usermod -aG dialout justin`,
  then re-login (default Pi user already has it).
- **Bus not connected at startup** (adapter plugged in later) →
  `curl -X POST http://192.168.178.147:8460/connect`
- The serial port is exclusive: stop the service
  (`sudo systemctl stop zbot-pi`) before running any manual bus script on
  the Pi, and vice versa.
