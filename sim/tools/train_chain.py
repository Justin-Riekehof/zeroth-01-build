#!/usr/bin/env python3
"""Unattended training curriculum: hands a walking run over to the next stage when it is ready.

    ~/Documents/stash/ksim-zbot/.venv/bin/python sim/tools/train_chain.py        (as systemd user unit zbot-chain)

Concept v5 (2026-10-28, docs/training-journal.md): servo_ctrl_v4 (action history + random delay, from scratch) learns to
walk but keeps the 5-6 Hz oscillation - with the jitter penalties at ~3 % of the tracking reward it costs nothing.
Now that the policy has the information to regulate calmly, the stages raise the price of the oscillation step by step
from a walking checkpoint. Each stage is judged by calm_watch.py (gate, stagnation, tracking collapse) like any run.

  stage          starts when                                             from checkpoint (of the previous run)
  servo_ctrl_v5  v4 walks: 2 evals in a row tracking >= 0.7, no fall;   falls 0, highest tracking
                 or v4's watcher ended
  servo_ctrl_v6  v5's watcher ended, not by a tracking collapse, and    falls 0, tracking >= 0.6, lowest share > 5 Hz
                 the jitter criteria still fail

A tracking collapse ends the chain: the penalty was too strong, a person decides. State and decisions:
sim/train/zbot_walking_task/train_chain.json (+ the unit's journal).

    train_chain.py speed       (unit zbot-chain-speed, state train_chain_speed.json)

Speed curriculum (2026-10-29): servo_ctrl_v9 learnt real steps (91 % swings >= 0.2 s) but steps on the spot. Raise the
commanded speed in stages from a stepping checkpoint, a share of zero commands keeps the stepping:

  stage           speed m/s     zero  stride  track scale  starts when                       from
  servo_ctrl_v10  0.01-0.03     30 %  2 cm    0.0004       at once                           servo_ctrl_v9 step 1250
  servo_ctrl_v11  0.02-0.045    20 %  3 cm    0.001        v10 walks (2 evals: no fall,      no fall, >= 50 % real
  servo_ctrl_v12  0.03-0.06     10 %  4 cm    0.002          tracking >= 0.6, >= 50 % real     steps, best tracking
                                                             steps) or v10's watcher ended
"""
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
T = ROOT / "sim/train/zbot_walking_task"
sys.path.insert(0, str(ROOT / "sim/tools"))
import calm_watch as W                                                   # noqa: E402

VENV = Path.home() / "Documents/stash/ksim-zbot/.venv"
STATE = T / "train_chain.json"
JITTER = ("jerk_p99", "highfreq_share", "limiter_share")
# servo_ctrl_v4 values: action_jerk_penalty -0.1, action_step_limit_penalty -0.025, gait_smooth_penalty -1.0
STAGES = [
    {"run": "servo_ctrl_v5", "after": "servo_ctrl_v4", "iters": 1500, "pick": "walking",
     "set": {"action_jerk_penalty": -1.0, "action_step_limit_penalty": -0.25, "gait_smooth_penalty": -3.0}},
    {"run": "servo_ctrl_v6", "after": "servo_ctrl_v5", "iters": 1500, "pick": "calm",
     "set": {"action_jerk_penalty": -3.0, "action_step_limit_penalty": -0.75, "gait_smooth_penalty": -6.0}},
]
WALKS = 0.7
SPEED = [
    {"run": "servo_ctrl_v10", "after": "servo_ctrl_v9", "from_step": 1250, "iters": 1500, "pick": "steps",
     "set": {"target_speed_min": 0.01, "target_speed_max": 0.03, "speed_zero_prob": 0.3, "stride_target": 0.02,
             "track_error_scale": 0.0004}},
    {"run": "servo_ctrl_v11", "after": "servo_ctrl_v10", "iters": 1500, "pick": "steps",
     "set": {"target_speed_min": 0.02, "target_speed_max": 0.045, "speed_zero_prob": 0.2, "stride_target": 0.03,
             "track_error_scale": 0.001}},
    {"run": "servo_ctrl_v12", "after": "servo_ctrl_v11", "iters": 1500, "pick": "steps",
     "set": {"target_speed_min": 0.03, "target_speed_max": 0.06, "speed_zero_prob": 0.1, "stride_target": 0.04,
             "track_error_scale": 0.002}},
]
# the same curriculum with the chamfered soles (model rebuilt 2026-10-29) and a penalty on feet landing tilted,
# continuing from servo_ctrl_v10 (the old-foot first stage: forward with 91 % real steps, 1-3 falls in 16)
FLAT = -8.0
SPEED2 = [
    {"run": "servo_ctrl_v13", "after": "servo_ctrl_v10", "from_step": 1330, "iters": 1500, "pick": "steps",
     "set": {**SPEED[0]["set"], "foot_flat_penalty": FLAT}},
    {"run": "servo_ctrl_v14", "after": "servo_ctrl_v13", "iters": 1500, "pick": "steps",
     "set": {**SPEED[1]["set"], "foot_flat_penalty": FLAT}},
    {"run": "servo_ctrl_v15", "after": "servo_ctrl_v14", "iters": 1500, "pick": "steps",
     "set": {**SPEED[2]["set"], "foot_flat_penalty": FLAT}},
]
# stage 0 first (2026-10-30): servo_ctrl_v13 on the real sole walked BACKWARDS (~3 cm/s against a forward command) and
# fell 2-11 of 16 - balance and forward progress at once was too much. So: step on the spot until no fall, then the speeds.
STAND = {"target_speed_min": 0.0, "target_speed_max": 0.0, "speed_zero_prob": 1.0, "stride_reward": 0.0,
         "track_error_scale": 0.0004, "foot_flat_penalty": FLAT}
SPEED3 = [
    {"run": "servo_ctrl_v16", "after": "servo_ctrl_v13", "from_step": 1455, "iters": 1500, "pick": "stand", "set": STAND},
    {"run": "servo_ctrl_v17", "after": "servo_ctrl_v16", "iters": 1500, "pick": "steps",
     "set": {**SPEED2[0]["set"], "stride_reward": 15.0}},
    {"run": "servo_ctrl_v18", "after": "servo_ctrl_v17", "iters": 1500, "pick": "steps",
     "set": {**SPEED2[1]["set"], "stride_reward": 15.0}},
    {"run": "servo_ctrl_v19", "after": "servo_ctrl_v18", "iters": 1500, "pick": "steps",
     "set": {**SPEED2[2]["set"], "stride_reward": 15.0}},
]
# 2026-10-30: the strict squared tracking kernel (scale 0.0004) was flat beyond ~2 cm/s - v13/v16 walked backwards at
# 5-8 cm/s and the tracking reward simply read ~0, no gradient. l1 kernel exp(-|err|/scale): sharp at the command and a
# slope everywhere. Restart from servo_ctrl_v13 step 1375, the last checkpoint on the real sole that went forward.
L1 = {"track_norm": "l1"}
SPEED4 = [
    {"run": "servo_ctrl_v20", "after": "servo_ctrl_v13", "from_step": 1375, "iters": 1500, "pick": "stand",
     "set": {**STAND, **L1, "track_error_scale": 0.02}},
    {"run": "servo_ctrl_v21", "after": "servo_ctrl_v20", "iters": 1500, "pick": "steps",
     "set": {**SPEED3[1]["set"], **L1, "track_error_scale": 0.02}},
    {"run": "servo_ctrl_v22", "after": "servo_ctrl_v21", "iters": 1500, "pick": "steps",
     "set": {**SPEED3[2]["set"], **L1, "track_error_scale": 0.03}},
    {"run": "servo_ctrl_v23", "after": "servo_ctrl_v22", "iters": 1500, "pick": "steps",
     "set": {**SPEED3[3]["set"], **L1, "track_error_scale": 0.045}},
]
# user (2026-10-30): why stand still first when v13 1375 still walks forward? - stage 0 skipped
SPEED5 = [{**SPEED4[1], "run": "servo_ctrl_v24", "after": "servo_ctrl_v13", "from_step": 1375},
          {**SPEED4[2], "run": "servo_ctrl_v25", "after": "servo_ctrl_v24"},
          {**SPEED4[3], "run": "servo_ctrl_v26", "after": "servo_ctrl_v25"}]
CHAINS = {"jitter": (STAGES, T / "train_chain.json"), "speed": (SPEED, T / "train_chain_speed.json"),
          "speed2": (SPEED2, T / "train_chain_speed2.json"), "speed3": (SPEED3, T / "train_chain_speed3.json"),
          "speed4": (SPEED4, T / "train_chain_speed4.json"), "speed5": (SPEED5, T / "train_chain_speed5.json"),
          "speed6": None}
# 2026-10-30: v24 still walked backwards - the swing reward (+0.020/step) was 40x the tracking reward (+0.0005). The real
# steps are there (86 %), so: tracking 10 -> 30, swing 6 -> 2, and (user: "the feet must land flat") flat-foot -8 -> -16.
REBAL = {"track_reward_scale": 30.0, "gait_swing_reward": 2.0, "foot_flat_penalty": -16.0}
SPEED6 = [{**SPEED5[0], "run": "servo_ctrl_v27", "after": "servo_ctrl_v24", "from_step": 1540, "set": {**SPEED5[0]["set"], **REBAL}},
          {**SPEED5[1], "run": "servo_ctrl_v28", "after": "servo_ctrl_v27", "set": {**SPEED5[1]["set"], **REBAL}},
          {**SPEED5[2], "run": "servo_ctrl_v29", "after": "servo_ctrl_v28", "set": {**SPEED5[2]["set"], **REBAL}}]
CHAINS["speed6"] = (SPEED6, T / "train_chain_speed6.json")
# 2026-10-31: from scratch the windowed tracking without naive_velocity teaches falling fast (servo_tpu3/scratch3: episodes
# 0.45 s, reward per step still rising) - it only works on a policy that already walks. So bootstrap with the rewards of
# servo_tpu1, then switch as soon as it survives and steps.
FOLLOW = {"track_window_s": 0.8, "stride_needs_command": True, "naive_velocity_scale": 0.0, "forward_progress_reward": 10.0}
BOOT = [{"run": "servo_scratch5", "after": "servo_scratch4", "iters": 2500, "pick": "boot", "set": FOLLOW}]
CHAINS["boot"] = (BOOT, T / "train_chain_boot.json")
# 2026-11-01: the same bootstrap from scratch, now with random foot friction (FootFrictionRandomizer)
FRICTION = [{"run": "servo_fric2", "after": "servo_fric1", "iters": 2500, "pick": "boot", "set": FOLLOW}]
CHAINS["friction"] = (FRICTION, T / "train_chain_friction.json")
# 2026-11-02: servo_fric1 never reached 50 % real steps (low friction drags the mean), servo_fric2 goes on from its step 750
FRICTION2 = [{"run": "servo_fric3", "after": "servo_fric2", "iters": 2500, "pick": "boot", "set": FOLLOW}]
CHAINS["friction2"] = (FRICTION2, T / "train_chain_friction2.json")
# 2026-11-02: climbing-shoe rubber under the soles (user expects mu 0.6-1.0), from scratch like servo_fric1
RUBBER = [{"run": "servo_rubber2", "after": "servo_rubber1", "iters": 2500, "pick": "boot", "set": FOLLOW}]
CHAINS["rubber"] = (RUBBER, T / "train_chain_rubber.json")
# 2026-11-03: the same from scratch with the flat-foot penalty at -30 instead of -8 (servo_rubber2: 43 % of contact > 5 deg)
RUBBER3 = [{"run": "servo_rubber4", "after": "servo_rubber3", "iters": 2500, "pick": "boot", "set": FOLLOW}]
CHAINS["rubber3"] = (RUBBER3, T / "train_chain_rubber3.json")
# 2026-11-05: from scratch with the naive bootstrap speed capped at 1.2 x command (servo_rubber3-7 learnt one fixed
# ~8 cm/s gait from the uncapped one) and the stride target tied to the command from the start
RUBBER8 = [{"run": "servo_rubber9", "after": "servo_rubber8", "iters": 2500, "pick": "boot", "set": FOLLOW}]
CHAINS["rubber8"] = (RUBBER8, T / "train_chain_rubber8.json")
STEPS_WALK, STEPS_REAL = 0.6, 0.5


def log(*a):
    print(time.strftime("%d.%m. %H:%M:%S"), *a, flush=True)


def history(run: str) -> list[dict]:
    f = T / run / "calm_watch.json"
    return json.loads(f.read_text()).get("history", []) if f.exists() else []


def done(run: str) -> dict | None:
    f = T / run / "calm_done.json"
    return json.loads(f.read_text()) if f.exists() else None


def ok(h: dict) -> bool:
    return "metrics" in h and h["metrics"].get("falls", 1) == 0


def walks(hist: list[dict]) -> bool:
    return len(hist) >= 2 and all(ok(h) and h["metrics"]["tracking_ratio"] >= WALKS for h in hist[-2:])


def stands(hist: list[dict]) -> bool:
    """stage 0: two evaluations in a row without a fall while stepping (>= 50 % real steps)"""
    return len(hist) >= 2 and all(ok(h) and h["metrics"].get("real_step_share", 0) >= STEPS_REAL for h in hist[-2:])


def boots(hist: list[dict]) -> bool:
    """bootstrap done: two evaluations in a row with at most 4 falls of 16 and >= 50 % real steps"""
    return len(hist) >= 2 and all("metrics" in h and h["metrics"].get("falls", 16) <= 4
                                  and h["metrics"].get("real_step_share", 0) >= STEPS_REAL for h in hist[-2:])


def steps_walk(hist: list[dict]) -> bool:
    """speed curriculum: two evaluations in a row without a fall, tracking >= 0.6 and >= 50 % real steps"""
    return len(hist) >= 2 and all(ok(h) and h["metrics"]["tracking_ratio"] >= STEPS_WALK
                                  and h["metrics"].get("real_step_share", 0) >= STEPS_REAL for h in hist[-2:])


def pick(hist: list[dict], how: str) -> dict | None:
    """the checkpoint the next stage starts from"""
    cands = [h for h in hist if ok(h)]
    if how in ("steps", "stand", "boot"):
        # stepping checkpoints with the fewest falls (0 if any), then the best tracking. servo_ctrl_v10 never had a
        # fall-free evaluation (1-3 of 16) while it walked forward with 91 % real steps - the chain stopped there.
        stepping = [h for h in hist if "metrics" in h and h["metrics"].get("real_step_share", 0) >= STEPS_REAL]
        if not stepping:
            return None
        fewest = min(h["metrics"]["falls"] for h in stepping)
        return max((h for h in stepping if h["metrics"]["falls"] == fewest), key=lambda h: h["metrics"]["tracking_ratio"])
    if how == "calm":
        calm = [h for h in cands if h["metrics"]["tracking_ratio"] >= 0.6]
        return min(calm, key=lambda h: h["metrics"]["highfreq_share"]) if calm else None
    return max(cands, key=lambda h: h["metrics"]["tracking_ratio"]) if cands else None


def overrides(run: str, changes: dict) -> list[str]:
    out, seen = [], set()
    for tok in W.overrides(run):
        k = tok.split("=", 1)[0]
        seen.add(k)
        out.append(f"{k}={changes[k]}" if k in changes else tok)
    return out + [f"{k}={v}" for k, v in changes.items() if k not in seen]


def ready(stage: dict) -> tuple[bool, str]:
    prev = stage["after"]
    hist, fin = history(prev), done(prev)
    if "from_step" in stage:
        return True, f"fixed start: {prev} step {stage['from_step']}"
    if stage["pick"] == "boot":
        if boots(hist):
            return True, "bootstrap done (<= 4 falls, >= 50 % real steps, twice in a row)"
        return (True, f"watcher ended: {fin['reason']}") if fin else (False, "")
    if stage["pick"] == "steps" and STAGE_PICK.get(prev) == "stand":
        if stands(hist):
            return True, f"stands (no fall, >= {STEPS_REAL:.0%} real steps, twice in a row)"
        if not fin:
            return False, ""
        return True, f"watcher ended: {fin['reason']}"
    if stage["pick"] == "steps":
        if steps_walk(hist):
            return True, f"walks (no fall, tracking >= {STEPS_WALK}, >= {STEPS_REAL:.0%} real steps, twice in a row)"
        if not fin:
            return False, ""
        if "tracking collapsed" in fin["reason"]:
            return False, "STOP: tracking collapsed in " + prev
        return True, f"watcher ended: {fin['reason']}"
    if stage["pick"] == "walking":
        if walks(hist):
            return True, "walks (tracking >= %.1f, no fall, twice in a row)" % WALKS
        return (True, f"watcher ended: {fin['reason']}") if fin else (False, "")
    if not fin:
        return False, ""
    if "tracking collapsed" in fin["reason"]:
        return False, "STOP: tracking collapsed in " + prev
    last = hist[-1] if hist else {}
    if last.get("passed"):
        return False, "STOP: gate passed in " + prev
    if not set(JITTER) & set(last.get("failed", [])):
        return False, "STOP: jitter criteria met in " + prev
    return True, f"watcher ended ({fin['reason']}), jitter still failing"


def launch(stage: dict, src: dict, why: str, state: dict):
    prev, run = stage["after"], stage["run"]
    step = src["step"]
    ckpt = T / prev / "snapshots" / f"ckpt.{step}.bin"
    if subprocess.run(["systemctl", "--user", "is-active", f"zbot-train-{prev}"], capture_output=True,
                      text=True).stdout.strip() == "active":
        subprocess.run([str(ROOT / "sim/tools/stop_run.sh"), prev], capture_output=True)
    subprocess.run(["systemctl", "--user", "stop", f"zbot-calmwatch-{prev}"], capture_output=True)
    if not done(prev) and "from_step" not in stage:
        (T / prev / "calm_done.json").write_text(json.dumps(
            {"reason": f"handed over to {run} by train_chain.py: {why}", "last_step": history(prev)[-1]["step"],
             "best_step": step}, indent=1))
    args = overrides(prev, stage["set"]) + [f"load_from_ckpt_path={ckpt}", f"max_steps={step + stage['iters']}"]
    # the full environment: without XDG_RUNTIME_DIR / DBUS_SESSION_BUS_ADDRESS systemd-run cannot reach the user manager
    # ("Failed to connect to bus") and the stage silently never starts (servo_ctrl_v10, 2026-10-29)
    # the same model and GPU as the previous stage (fixed to zbot-cad on GPU 1 until 2026-11-01), evaluation on the other GPU
    gpu = next((t.split("=", 1)[1] for t in shlex.split((T / prev / "launch.sh").read_text()) if t.startswith("GPU=")), "1")
    env = {**os.environ, "GPU": gpu, "ASSETS": W.assets(prev)}
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    r = subprocess.run([str(ROOT / "sim/tools/train_backpack.sh"), run] + args, capture_output=True, text=True,
                       env=env, cwd=ROOT)
    log(r.stdout.strip(), r.stderr.strip()[-300:])
    subprocess.run(["systemctl", "--user", "reset-failed", f"zbot-calmwatch-{run}"], capture_output=True)
    subprocess.run(["systemd-run", "--user", "--collect", "--quiet", f"--unit=zbot-calmwatch-{run}",
                    "-p", "Restart=on-failure", "-p", "RestartSec=60", "-p", f"WorkingDirectory={ROOT}",
                    "-E", f"HOME={Path.home()}", "-E", f"PATH={os.environ.get('PATH', '/usr/bin:/bin')}", str(VENV / "bin/python"),
                    "sim/tools/calm_watch.py", run, "--interval", "40", "--window", "6", "--min-iters", "200",
                    "--eval-gpu", "0" if gpu == "1" else "1", "--video-every", "100", "--collapse-after", "200"], capture_output=True)
    m = src["metrics"]
    state["events"].append({"time": time.strftime("%Y-%m-%d %H:%M"), "started": run, "from": f"{prev} step {step}",
                            "why": why, "from_metrics": {k: m.get(k) for k in ("falls", "tracking_ratio",
                                                                                "highfreq_share", "jerk_p99")},
                            "set": stage["set"]})
    log(f"started {run} from {prev} step {step} ({why}) with {stage['set']}")


STAGE_PICK: dict[str, str] = {}


def main(chain: str = "jitter"):
    global STATE
    STAGES, STATE = CHAINS[chain]
    STAGE_PICK.update({st["run"]: st["pick"] for st in STAGES})
    state = json.loads(STATE.read_text()) if STATE.exists() else {"events": []}
    started = {e["started"] for e in state["events"] if "started" in e}
    log("chain:", [s["run"] for s in STAGES], "already started:", sorted(started))
    while True:
        stage = next((s for s in STAGES if s["run"] not in started), None)
        if stage is None:
            log("all stages started; chain ends")
            return
        go, why = ready(stage)
        if why.startswith("STOP"):
            state["events"].append({"time": time.strftime("%Y-%m-%d %H:%M"), "stopped": why})
            STATE.write_text(json.dumps(state, indent=1))
            log(why)
            return
        if go:
            src = ({"step": stage["from_step"], "metrics": next((h["metrics"] for h in history(stage["after"])
                                                                  if h["step"] == stage["from_step"]), {})}
                   if "from_step" in stage else pick(history(stage["after"]), stage["pick"]))
            if src is None:
                state["events"].append({"time": time.strftime("%Y-%m-%d %H:%M"),
                                        "stopped": f"STOP: no usable checkpoint in {stage['after']} ({why})"})
                STATE.write_text(json.dumps(state, indent=1))
                log(state["events"][-1]["stopped"])
                return
            launch(stage, src, why, state)
            started.add(stage["run"])
            STATE.write_text(json.dumps(state, indent=1))
        time.sleep(120)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "jitter")
