# 2026-07-19 — Upper body: assembly, bring-up & calibration

Video: [media/raw/upper_body.MOV](../media/raw/upper_body.MOV) (local only, `raw/` is
untracked) — hero GIF in [media/](../media/).

## What happened

**Servo test GUI built** ([src/servo_gui/](../src/servo_gui/)) — FastAPI + three.js.
All bring-up below was done with it (no PyKOS yet, contrary to the original plan —
own tooling first). Key design decisions:

- **Pinned CAD reference:** all tooling refers to an immutable OnShape state
  (microversion pin, see [resources/cad/VERSION.md](../resources/cad/VERSION.md) —
  document "[0]th Z001", assembly "Opus"). Geometry (GLB) and joint data (revolute
  mates: axis, center, mate frames; fastened mates for the kinematic tree) are
  snapshotted locally via the OnShape API.
- **Calibration convention:** tick 2048 = 180° absolute = **0° relative** = assembly
  pose. Every servo is moved to center before its bracket is mounted → ±180° travel.
  All angles in tooling/configs are relative to this center.
- **Joint axes are data, not guesses:** the GUI's test-interval gauge (ring, zero
  line along the mounted part, live needle) and the posable 3D rig are derived from
  the CAD mates.

**Assembly & bring-up:**

1. Both arms assembled onto the torso (shoulder pitch/yaw + elbow yaw per side).
2. Daisy chain: servos re-ID'd one at a time (never >1 factory-ID-1 on the bus):
   left 11/12/13, right 21/22/23 → [hardware/servo_ids.json](../hardware/servo_ids.json).
3. Center calibration for all six, then per-joint sweep tests.
4. **Safe joint limits measured** — the hard way: a ±90° shoulder-yaw sweep tore off
   an elbow bracket. Limits now live in
   [hardware/joint_limits.json](../hardware/joint_limits.json) (GUI-editable, left ↔
   right mirroring, server-side clamping of every sweep).
5. Group runs verified: all six to center, sequential and simultaneous sweeps within
   per-joint limits.

## Bench findings

- STS3215 comes in two variants; ours is the **C018 (12 V)** — see
  [hardware/servos.md](../hardware/servos.md).
- Power-supply current limit of ~1 A trips `Overload error` under load → 2.5–3 A for
  single-servo sweeps; simultaneous 6-servo runs need more headroom (stall is 2.7 A
  *per servo*).
- After an overload, power-cycle the servo supply to clear the error state.

## Next

- C++ serial tooling (packet parser, tick ↔ rad, RAII port) against the bench setup
- First manipulation demos with the assembled arms
