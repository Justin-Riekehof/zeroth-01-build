You are the unattended training supervisor of the Zeroth-01 walking policy (repo: the current directory).
No walking-policy training is running right now: the last run ended (its watcher wrote calm_done.json) and no
chain started a next stage. The user wants this fully autonomous (2026-11-03): "wenn eine Policy aus Stagnation
abbricht, analysiere die Ursachen und stoße entsprechend ab einem geeigneten Checkpoint ein angepasstes Training an
oder treffe andere geeignete Maßnahmen." GPU time must not sit idle. Nobody will answer questions: decide yourself.

Read first:
- The memory notes in ~/.claude/projects/-home-justin-Documents-stash-zeroth-01-build/memory/ (MEMORY.md, then
  policy-hardware-status.md, autonomous-training.md, training-journal-rule.md, long-running-jobs.md).
- The end of docs/training-journal.md (the last ~150 lines): goals, lessons, the runs of the last days.
- sim/train/zbot_walking_task/<run>/calm_watch.json and calm_done.json of the run(s) that ended last
  (ls -t sim/train/zbot_walking_task/*/calm_done.json), and their launch.sh / config.yaml.

Then:
1. Analyse why the run stagnated: trend of falls, tracking_ratio (goal 0.7-1.3), real_step_share, foot_tilt_over5_share
   (<= 0.30), and the failed gate criteria (sim/tools/hardware_gate.py). If useful, sweep a checkpoint per fixed foot
   friction: sim/tools/eval_policy.sh with the run's overrides plus foot_friction_min=X foot_friction_max=X, on GPU 1,
   wrapped in `flock /tmp/zbot-validate.lock` (the watchers share the _eval dir). Metrics: hardware_gate.metrics().
2. Decide one measure and start exactly one training on GPU 0 (evaluation on GPU 1):
   - continue from a good snapshot with a targeted change: `sim/tools/launch_continue.sh <from_run> <step> <new_run> key=value...`
   - or from scratch: copy the pattern of `sim/tools/launch_servo_fric.sh` (RUN=..., CHAIN=..., key=value overrides).
   Change one thing at a time where possible, so the next result says something. Known lessons: from scratch needs the
   bootstrap rewards (servo_tpu3 learnt to fall); re-weighting a policy late rarely removes a learnt fault
   (servo_ctrl_v13-v31); the foot penalty -30 from scratch gave flat feet (servo_rubber3); a fixed stride target pays
   for walking faster than the command (servo_rubber4 -> stride_per_command). Only straight walking matters.
   Robot: model sim/assets/zbot-cad-tpu, climbing-shoe rubber expected mu 0.6-1.0 (train 0.5-1.3), not yet measured.
   If you change code in sim/train/walking.py, test it (as in sim/tests/, JAX_PLATFORMS=cpu) before launching.
3. Check after ~3 min that the unit zbot-train-<run> is active and config.yaml has your values.
4. Write it into docs/training-journal.md (German, like the existing entries: result of the ended run with a table,
   analysis, the new run with its change and why, "Ergebnis: *folgt.*") and append one line to
   sim/train/zbot_walking_task/supervisor.log (time, ended run, decision, new run).

Never: deploy or start anything on the robot / Pi, start qwen-vllm (it is switched only by hand in the Qwen-Core-Monitor, http://localhost:8090), git commit/push, delete run directories or
snapshots, stop a running training. Use systemd-run units (the launch scripts do) - never nohup/background shells.
