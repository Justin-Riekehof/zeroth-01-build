#!/usr/bin/env python3
"""Ends a training run only when the hardware limits are respected or progress has stagnated.

    ~/Documents/stash/ksim-zbot/.venv/bin/python sim/tools/calm_watch.py <run> [--interval 40] [--window 4]
        [--min-iters 600] [--eval-gpu 0]

Every `interval` training iterations the newest checkpoint is rolled out (CPU, 16 argmax episodes, the run's own task
flags from its launch.sh) and judged by sim/tools/hardware_gate.py:
  * gate passed on two consecutive evaluations           -> stop the run, reason "hardware limits respected"
  * score (0..1, distance to passing) not improved by `min_gain` over the last `window` evaluations
                                                          -> stop the run, reason "stagnation"
  * the run ends by itself (max_steps)                    -> last checkpoint is evaluated, reason "max_steps"
State: <run>/calm_watch.json (history, best checkpoint), <run>/calm_done.json when finished. Stop it by hand with
`systemctl --user stop zbot-calmwatch-<run>`; the training keeps running.
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


def is_stagnant(scores: list[float], window: int = 4, min_gain: float = 0.03) -> bool:
    """True when the best of the last `window` scores is not at least `min_gain` (relative) above the best before."""
    if len(scores) < window + 1:
        return False
    before, recent = max(scores[:-window]), max(scores[-window:])
    return recent < before * (1.0 + min_gain)


TRACKING_FLOOR = 0.3            # forward speed / commanded speed below which the policy no longer walks


def tracking_collapsed(history: list[dict], floor: float = TRACKING_FLOOR, evals: int = 2) -> bool:
    """True when a run that once walked (tracking >= floor) has stayed below `floor` for the last `evals` evaluations.
    The averaged score cannot see this: servo_ctrl_v3 (2026-10-27) traded walking for standing still at a flat 0.73."""
    tr = [h.get("metrics", {}).get("tracking_ratio") for h in history]
    tr = [t if isinstance(t, (int, float)) and t == t else None for t in tr]
    if len(tr) <= evals or not any(t is not None and t >= floor for t in tr[:-evals]):
        return False
    return all(t is not None and t < floor for t in tr[-evals:])


def decide(history: list[dict], window: int = 4, min_gain: float = 0.03, min_iters: int = 0,
           collapse_after: int = 0) -> str | None:
    """None = keep training, else the reason to stop. Stagnation only counts after `min_iters` iterations since the first
    evaluation: a run from scratch sits at a flat score for hours before it walks at all. A collapse of the forward
    tracking stops the run regardless of min_iters, but only `collapse_after` iterations after the first evaluation (a run
    that restructures its gait may dip on purpose)."""
    if len(history) >= 2 and history[-1]["passed"] and history[-2]["passed"]:
        return "hardware limits respected (gate passed twice in a row)"
    recent = history[-6:]
    if len(recent) == 6 and recent[-1].get("step", 0) - history[0].get("step", 0) >= 240 and all(
            h.get("metrics", {}).get("error") == "every episode fell" for h in recent):
        return "never stands (every episode of the last 6 evaluations fell)"    # servo_tpu3: 3 h of learning to fall
    if tracking_collapsed(history) and history[-1].get("step", 0) - history[0].get("step", 0) >= collapse_after:
        return f"tracking collapsed (below {TRACKING_FLOOR:.0%} of the commanded speed after it had walked)"
    if history and history[-1].get("step", 0) - history[0].get("step", 0) < min_iters:
        return None
    if is_stagnant([h["score"] for h in history], window, min_gain):
        return f"stagnation (score not improved by {min_gain:.0%} over the last {window} evaluations)"
    return None


def snapshots(run: str) -> list[int]:
    d = T / run / "snapshots"
    return sorted(int(f.name.split(".")[1]) for f in d.glob("ckpt.*.bin")) if d.is_dir() else []


def overrides(run: str) -> list[str]:
    toks = shlex.split((T / run / "launch.sh").read_text())
    i = [k for k, t in enumerate(toks) if t.endswith("train_backpack.sh")][0]
    return [t for t in toks[i + 2:] if "=" in t and not t.startswith(("max_steps=", "load_from_ckpt_path="))]


def assets(run: str) -> str:
    """the model the run trains on, from its launch.sh ("GPU=1 ASSETS=zbot-cad-tpu .../train_backpack.sh ...")"""
    toks = shlex.split((T / run / "launch.sh").read_text())
    return next((t.split("=", 1)[1] for t in toks if t.startswith("ASSETS=")), "zbot-cad")


def evaluate(run: str, step: int) -> dict:
    import hardware_gate as G
    out = T / run / "calm_eval"
    out.mkdir(exist_ok=True)
    ds = out / f"rollouts_{step}.ds"
    cmd = [str(ROOT / "sim/tools/eval_policy.sh"), str(T / run / "snapshots" / f"ckpt.{step}.bin"), str(ds), assets(run),
           "batch_size=16", "num_envs=16", "dataset_num_batches=16", "collect_dataset_argmax_action=True"] + overrides(run)
    # eval_policy.sh does `CUDA_VISIBLE_DEVICES=${GPU:-0}`: an EMPTY GPU still means GPU 0 and the "CPU" evaluation
    # grabbed ~1.5 GB of a training GPU (which then died with cuSolver/OOM errors). -1 hides every GPU.
    env = {**os.environ, "GPU": "-1", "JAX_PLATFORMS": "cpu"} if EVAL_GPU == "-1" else \
        {**os.environ, "GPU": EVAL_GPU, "XLA_PYTHON_CLIENT_MEM_FRACTION": "0.3"}
    # one CPU evaluation at a time machine-wide (two at once next to two trainings exhausted the RAM before)
    r = subprocess.run(["flock", "/tmp/zbot-validate.lock"] + cmd, capture_output=True, text=True, env=env)
    if not ds.exists():
        return {"step": step, "error": (r.stdout + r.stderr)[-300:], "score": 0.0, "passed": False}
    m = G.metrics(ds, G.run_config(T / run / "config.yaml"))
    verdict = G.verdict(m)
    res = {"step": step, "score": G.score(m), "passed": all(ok for _, _, _, ok, _ in verdict), "metrics": m,
           "failed": [k for k, _, _, ok, _ in verdict if not ok]}
    for f in out.glob("rollouts_*.ds*"):                           # keep disk small: only the newest dataset
        if f.name.split(".")[0] != ds.name.split(".")[0]:
            f.unlink()
    return res


COLLAPSE_AFTER = 0              # --collapse-after N: the tracking-collapse rule only N iterations after the first evaluation
VIDEO_EVERY = 100               # --video-every N: render the evaluated checkpoint every N iterations (0 = never)


def render(run: str, step: int) -> str | None:
    """15 s video of a checkpoint, always the same camera (render_policy.sh defaults), named <run>_step<NNNNN>.mp4 in
    <run>/videos/ - the archive for the training film. Same flags as the run, so the clip shows what it trained."""
    out = T / run / "videos" / f"{run}_step{step:05d}.mp4"
    out.parent.mkdir(exist_ok=True)
    cmd = [str(ROOT / "sim/tools/render_policy.sh"), str(T / run / "snapshots" / f"ckpt.{step}.bin"), str(out), "15",
           assets(run)] + overrides(run)
    env = {**os.environ, "GPU": "-1", "JAX_PLATFORMS": "cpu"} if EVAL_GPU == "-1" else {**os.environ, "GPU": EVAL_GPU}
    script = "rm -rf " + shlex.quote(str(T / "_render" / "checkpoints")) + " && " + " ".join(shlex.quote(c) for c in cmd)
    subprocess.run(["flock", "/tmp/zbot-validate.lock", "bash", "-c", script], capture_output=True, text=True, env=env)
    return str(out) if out.exists() else None


def stop_training(run: str):
    subprocess.run([str(ROOT / "sim/tools/stop_run.sh"), run], capture_output=True)


EVAL_GPU = "-1"                  # --eval-gpu N: roll out on GPU N instead of the CPU. A CPU evaluation needs > 8.6 GB of RAM
                                # (measured 2026-10-26) and was OOM-killed next to two trainings; only use a GPU that
                                # no training is running on
REVIVE_GRACE_S = 20 * 60        # the watchdog (zbot_watchdog.sh) / systemd restart a crashed run: only a run that stays
                                # down this long counts as finished


def main(run: str, interval: int, window: int, min_iters: int = 0):
    state_f = T / run / "calm_watch.json"
    saved = json.loads(state_f.read_text()) if state_f.exists() else {}
    history, videos = saved.get("history", []), saved.get("videos", [])
    import hardware_gate as G
    for h in history:           # the gate's criteria change between restarts: every entry scored by the current ones
        if "metrics" in h:
            v = G.verdict(h["metrics"])
            h["score"], h["passed"], h["failed"] = G.score(h["metrics"]), all(x[3] for x in v), [x[0] for x in v if not x[3]]
    last = history[-1]["step"] if history else 0
    unit = f"zbot-train-{run}"
    log = lambda *a: print(time.strftime("%H:%M:%S"), *a, flush=True)
    down_since = None
    log(f"watching {run}: eval every {interval} iterations, stagnation window {window}")
    while True:
        steps = snapshots(run)
        active = subprocess.run(["systemctl", "--user", "is-active", unit], capture_output=True, text=True).stdout.strip()
        latest = steps[-1] if steps else 0
        down_since = (down_since or time.time()) if active in ("inactive", "failed") else None
        finished = down_since is not None and time.time() - down_since > REVIVE_GRACE_S
        if latest and (latest >= last + interval or (finished and latest > last)):
            log(f"evaluating checkpoint {latest}")
            res = evaluate(run, latest)
            if "error" in res:
                # the evaluation itself failed (2026-10-31: OOM-killed next to two trainings) - not a result of the
                # policy; a score-0 entry would distort the stagnation check. Retry with the next loop.
                log(f"evaluation of {latest} failed, retrying later: {res['error'][-120:]}")
                time.sleep(300)
                continue
            history.append(res)
            last = latest
            best = max(history, key=lambda h: h["score"])
            log(f"step {latest}: score {res['score']:.3f} passed={res['passed']} failed={res.get('failed')}")
            last_video = max([v["step"] for v in videos], default=-10 ** 9)
            if VIDEO_EVERY and latest - last_video >= VIDEO_EVERY:
                v = render(run, latest)
                log(f"video: {v}")
                if v:
                    videos.append({"step": latest, "file": v, "score": res["score"]})
            state_f.write_text(json.dumps({"history": history, "best_step": best["step"], "best_score": best["score"],
                                           "videos": videos}, indent=1))
            why = decide(history, window, min_iters=min_iters, collapse_after=COLLAPSE_AFTER)
            if why or finished:
                why = why or "max_steps reached"
                if active != "inactive":
                    stop_training(run)
                (T / run / "calm_done.json").write_text(json.dumps(
                    {"reason": why, "last_step": latest, "best_step": best["step"], "best_score": best["score"],
                     "passed": history[-1]["passed"], "failed_at_last": history[-1].get("failed")}, indent=1))
                log("DONE:", why, "| best checkpoint", best["step"])
                return
        elif finished and latest <= last:
            best = max(history, key=lambda h: h["score"]) if history else {"step": None, "score": 0}
            (T / run / "calm_done.json").write_text(json.dumps({"reason": "training ended", "last_step": last,
                                                                 "best_step": best["step"], "best_score": best["score"]}))
            log("training ended, nothing new to evaluate")
            return
        time.sleep(60)


if __name__ == "__main__":
    a = sys.argv[1:]
    get = lambda k, d: int(a[a.index(k) + 1]) if k in a else d
    EVAL_GPU = a[a.index("--eval-gpu") + 1] if "--eval-gpu" in a else "-1"
    VIDEO_EVERY = get("--video-every", 100)
    COLLAPSE_AFTER = get("--collapse-after", 0)
    main(a[0], get("--interval", 40), get("--window", 4), get("--min-iters", 0))
