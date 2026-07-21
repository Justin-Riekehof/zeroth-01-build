# Servos — this build

| Joint group        | Servo            | Variant | Voltage | Stall torque | Stall current |
| ------------------ | ---------------- | ------- | ------- | ------------ | ------------- |
| Arms               | Feetech STS3215  | **C018**| 12 V    | 30 kg·cm     | 2.7 A         |
| Legs/torso (plan)  | Feetech STS3250  | —       | 12 V    | ~50 kg·cm    | —             |

Both run the same STS-series serial-bus protocol (1 Mbps, 0–4095 ticks/360°),
driven via the Waveshare Bus Servo Adapter (A).

## Bench findings (2026-07-19)

- The STS3215 exists in two variants: **C001 (6–7.4 V)** and **C018 (4–14 V)**.
  This build uses the C018 — 12 V supply is correct for both servo types.
- Ping model number reported by the STS3215: **777**.
- **Power supply current limit:** ~1 A is fine for ping/first contact, but sweeps
  under load trip an `Overload error` — set the bench supply to **2.5–3 A**
  (C018 stall current is 2.7 A).
- After an overload the error state persists — **power-cycle the servo supply**
  to clear it.

## Bus IDs (daisy chain)

Factory default is ID 1 — with more than one factory servo on the chain, replies
collide. Rule: **never more than one ID-1 servo on the bus.** IDs are written
persistently (servo EPROM) via the servo GUI (*Bus IDs* section).

ID scheme (tens digit = limb, ones digit = joint, counted from the torso outward;
ID 1 stays reserved for "factory-fresh, unconfigured"):

| ID | Joint                | ID | Joint                 |
| -- | -------------------- | -- | --------------------- |
| 11 | left_shoulder_pitch  | 21 | right_shoulder_pitch  |
| 12 | left_shoulder_yaw    | 22 | right_shoulder_yaw    |
| 13 | left_elbow_yaw       | 23 | right_elbow_yaw       |

Legs (planned — order follows the kinematic chain from the CAD mates,
hip → foot, which is also the daisy-chain wiring order):

| ID | Joint                | ID | Joint                 |
| -- | -------------------- | -- | --------------------- |
| 31 | left_hip_pitch       | 41 | right_hip_pitch       |
| 32 | left_hip_yaw         | 42 | right_hip_yaw         |
| 33 | left_hip_roll        | 43 | right_hip_roll        |
| 34 | left_knee_pitch      | 44 | right_knee_pitch      |
| 35 | left_ankle_pitch     | 45 | right_ankle_pitch     |

Canonical joint → ID assignment (used by the GUI backend for group runs):
[servo_ids.json](servo_ids.json). The CAD-part ↔ ID mapping used by the 3D viewer
lives in [src/servo_gui/servo_map.json](../src/servo_gui/servo_map.json).
All six upper-body IDs were flashed on 2026-07-19.

In the GUI, clicking a joint retrieves its configured ID from `servo_ids.json`, and
setting an ID (via *set ID* or the field) auto-selects the matching joint in the 3D
model — so the selection always tracks the servo you are operating on.

When connected, the GUI pings every configured ID and **grays out the servos not on
the bus** in the group list (*All* / *run group* skip them). Servos come online as the
daisy chain is wired up; *scan bus* re-checks.

## Joint limits

Mechanically safe angle ranges per joint live in [joint_limits.json](joint_limits.json)
(relative to the center convention below). They are edited via the servo GUI
(*save limits*, with automatic left ↔ right mirroring unless a side has its own
direct entry) and **enforced by the GUI backend**: test sweeps are clamped to the
configured range. First entry: `shoulder_yaw` ±[-45°, +60°] — found on the bench
on 2026-07-19 after a ±90° sweep tore off an elbow bracket.

## Calibration convention

Servos are moved to **tick 2048 (= 180° absolute)** before mounting printed parts
(→ *Move to center* button in [src/servo_gui](../src/servo_gui/)). All angles in
tooling are relative to this center: 0° = mount position, travel ±176.5°
(seam-safe). Rationale for the seam margin: see header comment in
[src/tests/servos/sts3250_test.py](../src/tests/servos/sts3250_test.py).

**Mount offsets:** if a servo could not be mounted at center (e.g. `left_hip_pitch`
sits **+90°** off), the offset is stored in [joint_offsets.json](joint_offsets.json).
All tooling shifts that joint's zero accordingly — 0° keeps meaning "CAD pose", the
servo just parks at tick 2048 + offset. Note the usable travel becomes asymmetric
(e.g. +90° offset → about −180°…+86° remain).

Two ways to set it in the GUI (per selected joint):

- **⊙ set current position as zero** — the practical one. *Move to center*, hand-turn
  the output to exactly where zero should be (torque is off after the move), then
  click. The servo's current encoder position becomes the joint's 0°; the offset is
  computed and stored automatically. Use this to trim the last couple of degrees that
  the gear spline can't resolve.
- **save offset** — enter a known offset in degrees manually.

The **live position** readout (shown while connected) reflects the current angle in
the CAD frame with the offset applied, and drives the gauge needle — so you can watch
the value as you hand-turn.

Re-zeroing a joint that already has limits **shifts those limits by the same amount**
so they keep protecting the exact same physical stops (the range in
[joint_limits.json](joint_limits.json) moves, the physical endpoints do not).
