# Zeroth-01 — User Manual (development & programming reference)

Living reference for everything needed to program and operate this build.
The narrative build log lives in the dated entries next to this file; the
public overview is the repo [README](../README.md).

---

## 1. Angle & position conventions

| Concept | Value |
| --- | --- |
| Encoder scale | 0 – 4095 ticks = 360° (4096 ticks/rev, 0.088°/tick) |
| **Center / zero** | tick **2048** = 180° absolute = **0° in all tooling** ("CAD pose") |
| Angle frame | All GUI/API/demo angles are **relative to zero**: −…+ around the mount pose |
| Seam-safe travel | **±176.5°** (ticks 40 – 4055) — endpoints keep distance to the 0/4095 encoder seam ([why](../src/tests/servos/sts3250_test.py)) |
| Mount offsets | Servo mounted off-center? Offset in [hardware/joint_offsets.json](../hardware/joint_offsets.json) shifts that joint's zero (e.g. `left_hip_pitch` +90° → zero at tick 3072). Applied transparently everywhere. Usable travel becomes asymmetric. |
| Model zero | Display-only corrections ([hardware/model_zero_offsets.json](../hardware/model_zero_offsets.json)) mapping the CAD scene pose onto the real standing zero pose. Never affects servo commands. |

Conversions: `deg = ticks × 360/4096` · `rel = deg − 180 − mount_offset`.

## 2. Speed

Unit: **ticks/second**; °/s ≈ speed × 0.088. Valid range in GUI/API: **1 – 3400**.

| speed | °/s | feel |
| --- | --- | --- |
| 200 | ~18 | very gentle (careful_walk range) |
| 300 | ~26 | demo/pose changes |
| 500 | ~44 | default test speed |
| 1000 | ~88 | brisk |
| 3400 | ~299 | register max ≈ physical no-load max (STS3215 @ 12 V: ~270°/s; less under load) |

Commanding more than the servo can deliver just means "as fast as possible".

## 3. Acceleration

Unit: **1 ≈ 100 ticks/s² ≈ 8.8°/s²** (1-byte Feetech ramp register). Range: **0 – 254**.

| acc | °/s² | feel |
| --- | --- | --- |
| 10 – 30 | 90 – 260 | butter-smooth (demos, holds) |
| 50 | ~440 | default |
| 150+ | 1300+ | aggressive — torque spikes, mechanical stress |
| **0** | ∞ | **special case: no ramp at all** — hard jolt, avoid |

High accel = torque spikes = the thing that tears printed brackets and dips
undersized power supplies. Prefer low accel for pose sequences.

## 4. Servos & electronics

| | Arms | Legs/torso |
| --- | --- | --- |
| Servo | Feetech **STS3215 C018** (12 V variant!) | Feetech **STS3250** |
| Ping model number | **777** | **2825** |
| Stall torque | 30 kg·cm @ 12 V | ~50 kg·cm |
| Stall current | 2.7 A | ≥3 A |

- Bus: half-duplex TTL daisy chain, **1 Mbit/s**, Waveshare Bus Servo Adapter (A),
  supply **12 V** (both types).
- **PSU current limit:** ≥1 A for bench pings, **2.5–3 A** for single-servo sweeps,
  more headroom for group/demo runs (multiple servos + holding torque).
- After a servo `Overload error`: power-cycle the servo supply to clear it.
- STS3215 exists as C001 (7.4 V) — this build uses the C018; check labels when
  buying spares. Details: [hardware/servos.md](../hardware/servos.md).

## 5. Servo IDs

Tens digit = limb, ones digit = joint counted from the torso outward.
**ID 1 stays reserved** for factory-fresh servos (never >1 × ID 1 on the bus).

| ID | Joint | ID | Joint |
| --- | --- | --- | --- |
| 11 | left_shoulder_pitch | 21 | right_shoulder_pitch |
| 12 | left_shoulder_yaw | 22 | right_shoulder_yaw |
| 13 | left_elbow_yaw | 23 | right_elbow_yaw |
| 31 | left_hip_pitch | 41 | right_hip_pitch |
| 32 | left_hip_yaw | 42 | right_hip_yaw |
| 33 | left_hip_roll | 43 | right_hip_roll |
| 34 | left_knee_pitch | 44 | right_knee_pitch |
| 35 | left_ankle_pitch | 45 | right_ankle_pitch |

## 6. Configuration files (all in the repo, all GUI-managed)

| File | Content / frame |
| --- | --- |
| [hardware/servo_ids.json](../hardware/servo_ids.json) | joint → bus ID (canonical; drives group/demo runs) |
| [hardware/joint_limits.json](../hardware/joint_limits.json) | per-joint safe range, CAD-frame deg; **enforced server-side** (sweeps/demos clamped); left↔right mirroring, `direct` beats `mirrored` |
| [hardware/joint_offsets.json](../hardware/joint_offsets.json) | per-joint mount offset (zero ≠ tick 2048) |
| [hardware/model_zero_offsets.json](../hardware/model_zero_offsets.json) | display-only model pose corrections |
| [src/servo_gui/servo_map.json](../src/servo_gui/servo_map.json) | CAD part → ID/model/axis (3D click prefill) |
| [demos/*.json](../demos/) | teach-in sequences: steps of `{angles, speed, acc, pause_s}` ([format](../demos/README.md)) |

## 7. CAD reference

All tooling is pinned to an **immutable OnShape microversion** — geometry (GLB) and
joint data (axes, centers, kinematic tree from the assembly mates) are snapshotted
in [resources/cad/](../resources/cad/VERSION.md). Joint axes, gauge orientation,
zero lines and the posable 3D rig are **derived from CAD data, not guessed**.

## 8. Servo GUI

### Starting the web UI

The GUI is a local web app: a small FastAPI server serves the page and (in
USB mode) drives the servo adapter. It runs on **any machine with this repo**
— the Windows laptop and the Linux workstation both work; the robot needs
nothing extra (in wireless mode the browser talks to the Pi service that is
already running as a systemd unit).

Prerequisite (once per machine): [uv](https://docs.astral.sh/uv/) —
`winget install astral-sh.uv` (Windows) / `curl -LsSf https://astral.sh/uv/install.sh | sh` (Linux).

```bash
cd src/servo_gui
uv run server.py        # first run resolves deps automatically
```

Then open **<http://127.0.0.1:8451>** in the browser. Stop with `Ctrl+C`.
The port is fixed (8451); a second instance on the same machine will fail
with "address already in use" — there is probably already one running.

- **USB mode**: plug the adapter into *this* computer first, then *Connect*.
- **Wireless mode**: robot main switch on, ~30 s Pi boot — the GUI finds the
  service on its own (status line shows `bus connected`), and the 3D model
  syncs to the robot's real pose on first contact.

- **Version badge** in the header (`GUI vN · backend vN`): mismatch = red banner →
  restart the server (`Ctrl+C`, `uv run server.py`). GUI files are served with
  `no-store`, so a plain F5 always gets the current frontend.
- **Torque rules:** every run releases torque at the end — except *hold center*
  (group checkbox) and demo playback, which hold the final pose. **Stop is always
  an E-stop** (everything goes limp). *✋ release torque* lets go after a hold.
  A watchdog re-parks held joints if they lose torque (logged).
- **Simulation checkbox:** full GUI without hardware; group/demo runs animate the
  3D model.

### Operating modes: USB (local) ↔ Wireless (Pi)

Switch at the top of the *Connection* section; the choice persists in
[hardware/connection.json](../hardware/connection.json) and is restored on reload.

| | **USB (local)** — default | **Wireless (Pi)** |
| --- | --- | --- |
| Servo adapter | laptop USB (`COMx`) | Raspberry Pi USB (`pixel2`, 192.168.178.147) |
| Execution | on the laptop | **on the Pi** — the browser only sends intents (never per-cycle setpoints; Wi-Fi jitter stays out of the control loop) |
| Available | everything below | demo list/▶ play with **waypoint preview**, **■ STOP**, ⌂ center, per-servo **✋ release / 🔒 lock** (Servos list or clicked joint), live position + **idle digital twin** (hand-moved joints mirror onto the model), live log/phase, **full teach-in**, **⏻ shutdown Pi** (banner confirms when it is safe to cut power) |
| Hidden | — | bus/bench tooling (scan/IDs, mapping, limits, offsets, sweep tests, group runs, model-zero calibration) |

- Both modes run the same `zbot_core` engine — limits, offsets, sag
  compensation and hold behave identically; in wireless mode they are enforced
  **on the Pi** and never trusted from the browser.
- **Stop is an E-stop in both modes** (USB: *■ Stop*; wireless: *■ STOP* in the
  Demos section).
- **Teach-in works in both modes.** Demos always save to the repo (canonical,
  git-tracked); in wireless mode the robot additionally gets its own copy, so
  *▶ play* works immediately without a deploy. *+ robot pose* reads the
  hand-posed robot through the Pi (release torque first via *✋ release*).
  Calibration (zero/offsets/limits/model zero) stays a USB-mode feature.
- Deploying to the robot syncs demos + calibration:
  `.\src\pi_service\deploy\deploy_pi.ps1` (Windows) /
  `./src/pi_service/deploy/deploy_pi.sh` (Linux) —
  details/troubleshooting: [pi-service.md](pi-service.md).
- Robot unreachable in wireless mode? ProtonVPN blocks LAN by default —
  enable *"Allow LAN connections"*.

### Standard workflows

| Task | Steps |
| --- | --- |
| New servo bring-up | chain it in alone → *scan bus* → *set ID* (auto-selects the joint) → *save mapping* → probe range → *save limits* |
| Mount & calibrate | *⌂ Move to center* → mount part → hand-trim → *⊙ set current position as zero* (shifts existing limits automatically) |
| Teach-in demo | *— new demo —* → pose model (sliders) or robot (*release torque*, hand-pose) → *+ step* → per-step or global spd/acc → *save demo* → play in **simulation first** |
| Run on the robot (wireless) | `deploy_pi.ps1` once → switch to *Wireless (Pi)* → select demo → *▶ play* (*■ STOP* aborts instantly) |
| Teach-in via Wi-Fi | wireless mode → *✋ release* (all, or selected servos) → hand-pose the robot (the model mirrors live) → *🔒 lock* a posed limb to keep it while posing the next → *+ robot pose* (or pose the model with the slider → *+ model pose*) → *save demo* (lands in the repo **and** on the robot) → *▶ play* |

## 9. Pose accuracy under load

Two effects make the ACTUAL pose deviate from the taught pose:

1. **Steady-state sag:** the servo's P-controller parks short of the goal under
   load (several degrees when lifting body weight, e.g. standing up from a
   squat). Demo playback and centering runs compensate automatically: after each
   step the residual error is measured and the goal is over-commanded by it
   (clamped to the joint limits, max 2 trim iterations — log line
   `load sag compensated`; uncorrectable rest is logged as
   `residual pose error`). Range sweeps are not settled on purpose.
2. **Teach-in capture bias:** *+ robot pose* records the hand-posed robot with
   torque released — "roughly center by hand" is easily ±10° off true zero.
   For an exact neutral step use **+ center** (writes true 0.0° for all
   joints) instead of hand-posing it.

## 10. Safety checklist

1. Output shafts free / limbs clear before sweeps.
2. Limits before speed: measure & save per-joint limits early — the server clamps
   every sweep/demo to them.
3. Keep amplitudes and accel small for whole-body demos (no balance policy).
4. Don't leave servos holding under load unattended (heat/current).
5. PSU current limit generous enough — brown-outs reset servos mid-motion.

## 11. Pi camera (Camera Module 3, IMX708)

SSH to the Pi is passwordless since 2026-07-31 (laptop key in `~/.ssh/authorized_keys`).

```bash
# on the Pi — quick checks
rpicam-hello --list-cameras    # must list imx708 (autodetected)
rpicam-still -n -o ~/test.jpg  # still capture (-n = headless, no preview)
vcgencmd get_throttled         # 0x0 = power supply OK

# on the Pi — live stream (waits for one viewer)
rpicam-vid -t 0 -n --width 1280 --height 720 --framerate 30 --inline --listen -o tcp://0.0.0.0:8888
```

```powershell
# on the laptop — viewer (ffplay via `winget install Gyan.FFmpeg`)
ffplay -fflags nobuffer -flags low_delay -framedrop tcp://192.168.178.147:8888
```

`--listen` serves exactly one client: closing the viewer window ends the Pi-side
process too (`failed to send data on socket` is the normal teardown) — restart
both commands for a new session.
