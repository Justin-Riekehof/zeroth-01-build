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
- `stagger` — optional `true`/`false`: start this step's servos in mirror-pair waves
  (`stagger_ms` apart, see [hardware/motion_limits.json](../hardware/motion_limits.json))
  instead of all at once. Without the field only the **first** step of a run staggers, because
  that is the one leaving torque-off. Set it `true` on steps that have to **lift** the body:
  the spread keeps the inrush off the pack and turns a simultaneous lunge into a push. Leave it
  off where the body is **lowered** (sitting down, going to the knees), or the leading wave
  carries weight before the rest arrives. The editor has a *stagger* box per step, and the box
  always shows what will actually happen.
- `boost` — `true` runs this one step **without** the power limits, i.e. at the `speed`/`acc`
  written in the step (up to 3400 / 254). For a peak move such as pushing off the floor at
  the end of `push_ups`. It draws the largest current the pack ever sees, so use it for
  single steps only and watch `pack`/`throttled` in the Pi's flight recorder afterwards.
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
step plays the saved demo up to that step only, *⇥ go to* moves straight to that one pose
without the steps before it (`until` and `start` in the play request, both 1-based and
inclusive; each step keeps its own speed/acc either way).
