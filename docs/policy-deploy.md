# Running a walking policy on the robot

The policies from [sim/policies/](../sim/policies/README.md) run **on the Pi** (onnxruntime, CPU,
~1 ms per forward pass) inside the intent service: [src/pi_service/policy.py](../src/pi_service/policy.py).
Training stays on the GPU machine; the Pi only does inference.

## What happens every 20 ms (50 Hz, same as `ctrl_dt` in training)

1. one bus transaction reads position + speed of all 16 servos (`Bus.sync_read`)
2. the latest head-IMU sample (raw chip axes, mg → m/s², dps → rad/s)
3. 64-vector in the order of `policy_meta.json` (the runner refuses any other layout):
   gait clock 4 · joint pos 16 · joint vel 16 · acc 3 · gyro 3 · lin-vel cmd 2 · yaw-rate cmd 1 ·
   gait-freq cmd 1 · last action 16 · heading 2
4. ONNX → 16 target angles (rad) → clamped to `joint_limits.json` → ticks (mount offsets applied,
   same path as demos) → one broadcast packet (`Bus.sync_move`)

The gait clock, heading (integrated gyro, zeroed at start) and last action live in the runner, not in
the network. Every run starts with a 1 s blend from the pose the robot stands in into the policy output.

## Deploy

```bash
./src/pi_service/deploy/deploy_pi.sh        # or deploy_pi.ps1
```

Ships the ONNX + `policy_meta.json` of every policy to `~/zbot/policies/<name>/` and installs
`numpy` + `onnxruntime` into `~/venv` (the Pi needs internet for that once). Without them the rest of
the service runs normally and `/policy/*` answers 501.

## First run — in this order

```bash
PI=http://<pi>:8460
curl $PI/policies                                    # installed, with trained speed range
# 1. DRY RUN: robot limp / held in your hands; reads servos + IMU, runs the net, commands NOTHING
curl -X POST $PI/policy/start -H 'content-type: application/json' \
     -d '{"name":"cad2_v13_tiny_step905","dry_run":true}'
curl $PI/policy/status        # steps, mean/max step ms, overruns, imu age, tilt, heading
curl -X POST $PI/policy/stop
# 2. live, robot standing, suspended or caught by a rope
curl -X POST $PI/policy/start -H 'content-type: application/json' -d '{"name":"cad2_v13_tiny_step905"}'
curl -X POST $PI/stop                                # E-stop: releases all torque
```

`/policy/stop` is the soft stop (ends the loop, the robot holds its pose). `/stop` is the E-stop.

Refused at start: no / stale IMU data; accelerometer not reading ≈ +9.81 m/s² on the chip **Y** axis
(wrong mounting or robot not upright); a joint outside its limits; a command outside the trained range.
Aborted while running (**torque is released**: holding the pose against a falling body tore a hip-yaw
bracket on 2026-10-22, so the robot goes limp instead): IMU older than 250 ms, body tilt > 55°,
3 failed bus transactions in a row, NaN output.

## Step logs (every run, dry runs included)

When a run ends (stop, fault or E-stop) the runner writes `~/zbot/policy_logs/<time>_<policy>[_dry].npz`:
per 20 ms step the raw servo ticks and speeds, raw IMU (mg / dps, chip axes), the exact 64-vector fed to
the net, the raw action, the clamped + ramped target, the ticks sent, tilt, heading, command and the
timing (step / bus read / inference ms), plus a `meta` JSON (joints, ids, offsets, limits, gyro bias, stop
reason). Recording is in memory inside the loop and capped at 10 min.

```bash
curl $PI/policy/logs                                  # list
curl -O $PI/policy/logs/<name>.npz                    # download
```

## Open points — verify on the bench, nothing here has run on hardware yet

* **IMU rate.** The head firmware now streams at 50 Hz (`rate HZ` command), also *between* the strips of
  the SPI frame transfer, so the render loop no longer sets the pace. The eye drawing itself (~10-15 ms,
  not sliceable) still blocks, so the occasional interval is 30 ms instead of 20: the firmware reports the
  longest interval of the last second as `gap` (in `GET /head`), the runner as `max_imu_age_ms`. Not
  measured on the board yet; **flash first** (`./src/head_display/deploy_head.sh --files-only`). If `gap`
  stays above ~35 ms, lower the eye's frame rate while a policy runs or move the draw off the critical path.
* **Step time.** Target: `max_step_ms` well below 20 and `overruns` ≈ 0. If the bus read+write does not
  fit into 20 ms the policy runs at the wrong speed (the clock assumes 50 Hz). Measure with the dry run.
* **Servo P/D and speed.** The sim tracks the target with kp 16 / kd 3. The real servos use their own
  registers; `speed` (default 1000 ticks/s) and `acc` (default 0 = no ramp) of `/policy/start` are
  *not* the demo limits (300 / 30 in `motion_limits.json` are far too slow for 50 Hz tracking and are
  deliberately not applied here). Tune P/D and speed against the sim; watch the battery voltage — 16
  servos stepping at once is the brown-out case `motion_limits.json` guards against.
* **Zero mapping.** The policy assumes angle 0 = standing straight = servo zero including
  `joint_offsets.json`, and sim sign = servo sign (`model_invert` baked into the model). Dry-run with the
  robot standing in its reference pose: the reported `pos_deg` must be ≈ 0 for every joint.
* **Command range.** Only forward walking within each policy's trained speed range (`vx`), `vy = 0`,
  gait frequency within its trained range. The "tiny" policy is 0.05–0.10 m/s.
