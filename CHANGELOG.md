# Changelog

Notable changes to the robot, its parts and the software, newest first. Details and the reasoning behind each training
run are in [docs/training-journal.md](docs/training-journal.md) (German).

## 2026-11-28 — first steps on a learned policy

- **Milestone:** `servo_comp6_step6115` walked several steps roughly forward on the real robot (run 14:37:05, 5.7 s
  before it tipped over), the first policy to do so. New hero GIF `media/first-steps.gif` (trimmed before the fall).
  Six live runs on parquet with a hand-held safety leash; Pi logs in
  `sim/policies/servo_comp6_step6115/hw_logs_2026-11-28/`, slow-motion videos in `media/hw_tests/2026-11-28/`.
- **Sim vs. robot:** hip-yaw use and the first second match the sim; the real yaw rate is 2–4× higher (p95 100–210 vs.
  52 °/s), and the policy ends 22° off course in the sim too (the gate did not check heading).
- **Gate:** new criterion `yaw_end_deg` ≤ 10° (median |base yaw| at the end of walking episodes,
  `sim/tools/hardware_gate.py`).
- **Training:** `servo_yaw1` from 6115 with `heading_penalty` −1 → −8, hip-yaw play up to 4° and springs 4–40 Nm/rad,
  foot torsion 0.003–0.05. `sim/tools/launch_continue.sh` takes `WINDOW` for the stagnation window.

## 2026-11-21 — neck, rubber soles, friction-trained policies

Merged into `main` as `d8f2f71` (with `baa98c0`, `61d10c8`, `c290330`).

### Hardware

**Reinforced neck piece, bolted through** — [hardware/neck_piece/](hardware/neck_piece/)

- **Problem (2026-11-07):** the two screw tabs that hold the neck piece on the torso broke the first time the head hit
  an obstacle. The head has leaned slightly backwards since then. The screw head pressed on a 2.5 mm wall (2 mm under the
  countersink), and a knock on the head levers against it with about 40 mm vs. 5–8 mm.
- **Fix (v2):** the torso front strip is now clamped between a **3.2 mm front claw** and **8 mm tab walls**, held by two
  **M3×35 ISO 10642 countersunk screws + DIN 985 lock nuts**. The screws no longer pull on a threaded insert in a thin
  wall. Nuts sit in hex pockets, so they cannot turn.
- **Cost:** 34.0 → 47.3 cm³ (about 46 g PETG instead of about 30 g). The centre of mass stays practically on the torso.
- **Print:** Bambu Lab P2S, PETG, claw face down, 5 walls, 40 % gyroid, normal "snug" supports. The first print with tree
  supports failed (the nozzle knocked the support over), see `print/PRINT.md`. Ready-to-slice project:
  `print/neck_piece_PETG_front_project.3mf`.
- **One-time torso change:** drill out the thread of the two heat-set inserts (3.2 mm drill from the front, using the
  claw holes as a template). Alternative: print the torso with through holes (`make_torso.py`).
- **Torso change (needed for the new neck):** the pinned torso has two Ø4 insert holes in its front strip (y −20 … −10)
  behind a closed 5.4 mm front wall, so the through screws cannot reach the nuts. Two ways to adapt it:
  1. **Modify the existing torso (once):** drill out the thread of the two heat-set inserts. Use a 3.2 mm drill from the
     front through the claw holes: first the 5.4 mm wall, then the insert. Drill slowly so the brass insert does not
     spin, then clean out the chips.
  2. **Print a new torso:** `make_torso.py` cuts two Ø3.3 through bores (x +32.44 / −32.54, z 379) from the front face
     (y −25.4) through the whole front strip, so no drilling and no heat-set inserts are needed at the neck. Output:
     `stl/torso_neck_through.stl` (robot frame, mm). The script checks that the bores go through and that the torso
     stays one watertight body.
  The neck and the torso share one constant set (`make_neck_piece.py`), so screw axes and bores always match. Removing the
  rucksack is needed to insert the nuts from behind. Clearance check: the claw stands 3.45 mm in front of the old torso
  front, which matters for arm poses directly in front of the chest. Everything else is clear (smallest gaps: Milk-V stack
  1.7 mm, head shell 1.2 mm, shoulder motors 3.8 mm).
- **WebUI:** new attachment set "Hals: verstärktes Halsstück" (`resources/cad/attachments/neck_piece.glb`), the original
  neck can be hidden.
- **Not yet verified:** no impact test, and the simulation mass of the heavier neck is still open. Next weakest point is
  the head itself (pin ↔ back plate), unchanged for now.

**Rubber foot soles** — [hardware/foot_sole/](hardware/foot_sole/)

- New variant `rubber`: the TPU sole is 1.8 mm thinner and has no bottom chamfer, so climbing-shoe rubber can be glued
  flush on the flat underside. The sole plane stays the same as the other variants, so the simulation geometry does
  not change, only the floor friction.
- `make_sole.py rubber` writes the STLs and a 1:1 A4 cutting template. `make_bambu_project.py --variant rubber` writes
  the Bambu project (about 64 g, 4 h 37 min for the pair).
- Glue with contact cement, not cyanoacrylate. Sand and degrease both sides first.

### Simulation and training

- **Fundamental bug fixed (`c290330`):** every policy up to `servo_tpu5` was trained on a single foot/floor friction.
  `FloorFrictionRandomizer` changed the floor geoms, but the feet touch the floor through explicit `<pair>` contacts that
  override the geoms. `FootFrictionRandomizer` in `sim/train/walking.py` now sets `pair_friction` per environment
  (μ 0.2–1.2, later 0.1–1.5 and 0.5–1.3 for the rubber soles). The range is written into `policy_meta.json`.
  Test: `sim/tests/test_foot_friction.py`.
- **Retrain from scratch** with the bootstrap rewards of `servo_tpu1` (`sim/tools/launch_servo_fric.sh`, `launch_servo_fric2.sh`).
  Continue a run from a snapshot with a changed setting: `sim/tools/launch_continue.sh`.
- **Exported policies** in `sim/policies/`: `servo_rubber2_step440`, `servo_rubber14_step1205`, `servo_rubber22_step3210`,
  `servo_rubber23_step3315` (ONNX, `action_filter_alpha` in `policy_meta.json`). `servo_rubber23_step3315` is the best
  candidate so far. It has no falls in the sim and its only open gate criterion is the high-frequency share
  (0.17–0.19, limit 0.15).
- **Training supervisor** (`train_supervisor.sh`, `install_supervisor.sh`, `train_supervisor_prompt.md`): a systemd timer
  checks every 10 min whether the GPU is idle. If so, it starts a headless analysis that launches the next run, with a
  no-analysis fallback that continues the last run. **Paused since 2026-11-11** at the owner's request.
- `train_chain.py`, `hardware_gate.py`, `export_policy.py` and the watchdog got matching updates.

### Robot software (Pi service)

- **Start-pose check (`baa98c0`):** the policy runner warns when a joint starts more than 1° off the centre pose (the run
  still starts). It stores each joint's deviation and the mean accelerometer reading in the step log, so standing
  postures can be compared between runs.
- **Friction bench test (`61d10c8`):** `test=friction` pushes the feet apart on the standing robot until the soles slide.
  `GET /bench/friction` converts the hip load into μ. It aborts on high hip load or body tilt. **The μ value is marked
  uncalibrated** until a force gauge confirms it.

### Hardware results

First real-robot run of a friction-trained policy (`servo_rubber23_step3315`, 2026-11-11): several unaided steps, best
runs 10.4 s and 14.8 s (E-stop). The runs got shorter, the robot drifted left, and the left leg has a lot of play.
Next: repair the play, then repeat with the same settings. Logs are in
`sim/policies/servo_rubber23_step3315/hw_logs_2026-11-11/`. Logs of three more runs from 2026-11-21 are in
`hw_logs_2026-11-21/` (not yet evaluated in the journal).
