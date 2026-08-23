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
| `GET /status` | bus state, watchdog state, live engine snapshot (phase, poses, log) |
| `GET /demos` | demos available on the robot |
| `POST /demos` | save a demo onto the robot (wireless teach-in; the GUI also saves to the repo, which stays canonical) |
| `POST /demos/delete` | remove a demo from the robot (`{"name": "..."}`) |
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
   (`servo_ids/joint_limits/joint_offsets.json`) + `demos/` — teach-in
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
