# Demos — teach-in motion sequences

One JSON file per demo, created/edited/played via the [servo GUI](../src/servo_gui/)
(*Demos* section) — or by hand:

```json
{
  "name": "example_wave",
  "description": "optional",
  "steps": [
    { "title": "arm up", "angles": { "left_elbow_yaw": 40.0 }, "speed": 900, "acc": 60, "pause_s": 0.5 }
  ]
}
```

- `angles` — target angles in **CAD-frame degrees** (0° = mount/center pose; mount
  offsets from [hardware/joint_offsets.json](../hardware/joint_offsets.json) are
  applied automatically). Joints omitted in a step simply stay where they are.
- `speed` / `acc` — per step (ticks/s, Feetech accel units). Both are clamped at playback to
  the power limits in [hardware/motion_limits.json](../hardware/motion_limits.json)
  (default 300 / 30; the clamp is logged) so that all servos starting at once cannot sag the
  pack into the low-voltage cutoff.
- `pause_s` — dwell after the step's pose is reached. A step with pause 0 is a **transit
  step**: it is not load-sag settled (that pass costs up to ~1 s), so the sequence flows;
  steps with a pause and the final step are settled to the exact pose.
- `settle` — optional `true`/`false` to force or skip the settle pass for one step.
- `title` — optional label (max. 60 chars) shown in the editor and in the playback log.
- `center` — `true` marks a **center step**: at playback its joints go to the center pose
  override from [hardware/center_pose.json](../hardware/center_pose.json) (0° where no
  override is set). A step whose angles are all exactly 0 counts as a center step too, so
  older "+ center" steps follow the override as well.

Playback moves all joints of a step **simultaneously**, waits until every target is
reached, honors the safety limits from
[hardware/joint_limits.json](../hardware/joint_limits.json) (targets are clamped,
clamping is logged), skips servos not present on the bus, and **holds the final
pose** (release via *✋ release torque*; *Stop* is the E-stop).

Teach-in workflow in the GUI: pose the 3D model with the per-joint sliders →
*+ model pose* / *+ robot pose* / *+ center* → adjust speed/acc/pause and give steps a
title → reorder with ▲ ▼ or drag the ⠿ handle, copy with ⧉ dup → *save demo*; *▶ to here* on a
step plays the saved demo up to that step only (`until` in the play request).
