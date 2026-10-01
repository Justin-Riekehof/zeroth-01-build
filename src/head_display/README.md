# Head display — the eye

Firmware for the **Waveshare RP2040-LCD-1.28** in the robot's head (round
1.28" GC9A01 LCD, QMI8658 IMU, USB-serial to the Pi). It replaces the stock
Waveshare demo (which showed raw IMU numbers) with one friendly eye that looks
around, blinks, drifts with gravity like a googly eye and gets startled by fast
head movements — and it streams the IMU as JSON so the Pi service
([src/pi_service/head.py](../pi_service/head.py)) and the GUI's head card can
show it.

MicroPython, three files: [gc9a01.py](gc9a01.py) (LCD), [qmi8658.py](qmi8658.py)
(IMU), [main.py](main.py) (eye + telemetry + commands). ~25–30 fps.

On boot the display shows **"ROBOT PROJECT / PIXEL"** for about three seconds
— a stroke font drawn with `framebuf.line()` (4 × 6 grid, 45° chamfers instead
of corners), the letters of PIXEL drop in one by one with a small bounce, a
light sweep runs across, then the lids close and the eye opens. The font lives
in `GLYPHS` in main.py (only the letters the two words need); `splash` replays it.

## Flash it — from the workstation, over SSH, no card reader

Everything happens on the Pi, where the board is plugged in. One-time
prerequisite on the Pi (needs a sudo password, so not scripted):

```bash
ssh -t justin@192.168.178.147 'sudo apt install -y picotool'
```

Then:

```bash
./src/head_display/deploy_head.sh            # backup → MicroPython → our files
./src/head_display/deploy_head.sh --restore  # back to the stock Waveshare demo
```

What the script does, in order: stops `zbot-pi` (it holds the serial port),
**saves the board's whole flash** to `~/head_display/backup-*.bin` on the Pi
the first time (that is the stock firmware — `--restore` writes it back),
reboots the board into BOOTSEL via `picotool` (the stock firmware exposes the
pico-sdk reset interface, so no BOOT button), loads the MicroPython UF2 for the
Pico (downloaded once to `~/head_display/`), copies the three `.py` files with
`mpremote`, resets the board and starts `zbot-pi` again. Total: ~1 minute.

`picotool` runs unprivileged: Raspberry Pi OS ships udev rules for RP2040
boards (`60-picotool.rules`, group `plugdev`).

## Telemetry

One JSON line per ~50 ms, native sensor units (same as the stock demo showed):

| key | unit | |
|---|---|---|
| `ax ay az` | **mg** | acceleration incl. gravity (1000 mg ≈ 9.81 m/s²) |
| `gx gy gz` | **dps** | rate, degrees per second |
| `t` | °C | IMU die temperature |
| `v` | V | board supply (VSYS via the board's 1:2 divider on GPIO 29; ≈4.2 V on USB) |
| `mood rot fps` | | eye state, display rotation, render rate |

## Commands

Lines on the same serial port; from the GUI/HTTP: `POST /head/cmd {"line": "..."}`.

| command | effect |
|---|---|
| `mood neutral` / `happy` / `sleepy` / `surprised` [`SECONDS`] | expression; with a duration it reverts to neutral |
| `blink` | blink now |
| `splash` | replay the boot splash ("ROBOT PROJECT / PIXEL", ~3 s), then the eye opens |
| `alert battery` / `alert WORD [WORD [WORD]]` / `alert off` | full-screen pulsing red warning instead of the eye (preset `battery` = "BATTERY / EMPTY / PI OFF - CHARGE"). The Pi service sends `alert battery` right before it halts the OS on an empty pack — the board keeps its 5 V, so the warning stays on the robot until the main switch is cut |
| `look X Y [SECONDS]` | gaze to (−1…1, −1…1) for a while (default 2 s) |
| `rot 0` / `90` / `180` / `270` | display rotation — **persisted** |
| `axes fwd=-z right=+x` | which board axes point out of the face / to the right — **persisted** |
| `bl PCT` | backlight 0–100 — persisted |
| `color R G B` | iris colour — persisted |
| `info` | prints the config as JSON |

## Orientation — calibrating once

The board sits rotated in the head, so both the picture and the gravity
reaction have to be told where "up" is. Two facts, both stored in
`config.json` on the board:

1. **`rot`** — turn until the eye is upright (the lids close top-down).
2. **`axes`** — which accelerometer axis points forward out of the face and
   which to the right. Read them off the GUI's head card: tilt the head nose-
   down and watch which of `acc x/y/z` grows; same for the right ear.

The Pi service has the matching mount setting in `~/zbot/hardware/connection.json`
(`"imu_axes": {"up": "+y", "forward": "-z"}`) for the pitch/roll it reports.
