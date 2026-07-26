# Demos — teach-in motion sequences

One JSON file per demo, created/edited/played via the [servo GUI](../src/servo_gui/)
(*Demos* section) — or by hand:

```json
{
  "name": "example_wave",
  "description": "optional",
  "steps": [
    { "angles": { "left_elbow_yaw": 40.0 }, "speed": 900, "acc": 60, "pause_s": 0.5 }
  ]
}
```

- `angles` — target angles in **CAD-frame degrees** (0° = mount/center pose; mount
  offsets from [hardware/joint_offsets.json](../hardware/joint_offsets.json) are
  applied automatically). Joints omitted in a step simply stay where they are.
- `speed` / `acc` — per step (ticks/s, Feetech accel units).
- `pause_s` — dwell after the step's pose is reached.

Playback moves all joints of a step **simultaneously**, waits until every target is
reached, honors the safety limits from
[hardware/joint_limits.json](../hardware/joint_limits.json) (targets are clamped,
clamping is logged), skips servos not present on the bus, and **holds the final
pose** (release via *✋ release torque*; *Stop* is the E-stop).

Teach-in workflow in the GUI: pose the 3D model with the per-joint sliders →
*+ add step (current pose)* → adjust speed/acc/pause per step → *save demo*.
