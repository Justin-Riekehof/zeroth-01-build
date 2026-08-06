# Z-Bot — Hardware & Deployment Context

Distilled from hardware bring-up sessions (last updated 2026-07-30). The facts below are
**not discoverable from the code** — treat them as ground truth and do not re-derive or guess.

## Operating modes (decided — both are first-class, never remove either)

- **USB / local mode (current state, must keep working):** Waveshare servo adapter plugged
  directly into the Windows laptop via USB; the web interface drives the local COM port and
  trajectory execution runs on the laptop. This is how everything works today.
- **Wireless mode (to be added):** the same adapter plugged into the Raspberry Pi via USB;
  laptop/web clients send **high-level intents only** (HTTP/WebSocket) to a Pi-side
  **FastAPI** service (e.g. `POST /demo/wave`, `POST /demo/squat`, `POST /stop`,
  `GET /status`) which executes locally against the servo bus.
- Rationale for the intent split in wireless mode: Wi-Fi jitter (2–20 ms, spikes >100 ms)
  must never sit inside a servo control loop. Never stream per-cycle setpoints over Wi-Fi.
- **Shared core requirement:** trajectory/demo logic and the serial layer must be one
  shared library used by both the local runner (Windows, `COMx`) and the Pi service
  (Linux, `/dev/tty*`). No forked per-platform copies.
- The wireless API will later front a public teleoperation website (VPS + TURN relay,
  booking system). Keep it transport-agnostic and auth-ready, but do **not** build the
  public stack now.
- Safety in wireless mode is Pi-local and never trusted from clients: watchdog (~500 ms
  without a command → soft hold position), joint limits + velocity clamps validated on
  the Pi, stop endpoint always available. A working stop control is required in **both**
  modes.

## Robot computer

- Raspberry Pi 4B 4 GB, Raspberry Pi OS Lite 64-bit (Debian Trixie), `aarch64`
- Reachable as `justin@pixel.local` (mDNS works; FritzBox network `192.168.178.0/24`,
  DHCP reservation recommended so the IP stays stable)
- Python venv at `~/venv` (feetech-servo-sdk / scservo_sdk and pyserial installed)
- Pitfall: **ProtonVPN on the dev laptop blocks LAN access** — enable "Allow LAN
  connections" or disconnect the VPN, otherwise SSH/HTTP to the robot fail with
  unresolvable hostnames / unreachable IPs.

## Servo bus (ground truth — do not guess)

- **Waveshare Bus Servo Adapter (A) V1.1**, board jumper in position **B** (USB mode).
  Connects via USB either to the Windows laptop (enumerates as `COMx` — current setup)
  or to the Pi (enumerates as `/dev/ttyUSB0` or `/dev/ttyACM0`). On the Pi, prefer a
  stable `/dev/serial/by-id/...` path or a udev rule over the raw index.
- Native-UART alternative is configured and verified on the Pi: PL011 enabled via
  `dtoverlay=disable-bt`, `/dev/serial0 → ttyAMA0`, serial console removed. If ever
  switching: jumper to **A**, wiring is **RX-RX / TX-TX (NOT crossed)**, Pi pins
  8 (TXD) / 10 (RXD) / 6 (GND).
- Bus settings: **1,000,000 baud**, scservo_sdk **protocol 0**.
- Servos: Feetech **STS3215** arms — IDs **11/12/13 left**, **21/22/23 right**;
  Feetech **STS3250** legs (10x, K-Scale ID scheme).
- Hardware ceiling (design around it, don't fight it): position-only control, ~1.3°
  backlash, 10-count firmware deadband, realistic bus rate 50–100 Hz. Smoothing levers:
  EMA on targets, velocity/acceleration ramps, consistent loop timing.

## Existing assets & refactor rules

- Working demos (squat without falling, hand wave) and per-joint zero-offset calibration
  exist in this repo and currently run on the Windows laptop against the local COM port —
  **this must not regress**.
- Regression gate: the first milestone of any refactor is that the existing USB/local
  mode runs unchanged through the new serial/backend abstraction. Only then add the
  Pi-side service.
- Abstract the serial port behind a small interface (`COMx` ↔ `/dev/tty*`), port chosen
  via configuration — no hardcoded ports, no forked scripts.
- Provide a hardware mock for the serial layer so trajectory/API/client code is testable
  without the robot (bench-first workflow).

## Deployment

- Laptop (Windows 11) → Pi via ssh/scp/rsync to `justin@pixel.local`.
- Target: one-command deploy; later a systemd unit so the Pi service starts on boot.
