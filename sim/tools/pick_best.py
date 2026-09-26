#!/usr/bin/env python3
"""Rank the evaluated snapshots of a run and print the best checkpoint.

Checkpoint quality swings a lot between consecutive checkpoints, so a run is never judged by its last
checkpoint: sim/tools/sweep_snapshots.sh evaluates every 10-minute snapshot into
<exp>/snapshots/eval_<step>/eval.txt, and this script scores those evals and prints the winner.

  python sim/tools/pick_best.py <exp> [--target-speed 0.35] [--profile strong|calm|tiny] [--path]

--path prints only the checkpoint path (that is what sim/tools/train_queue.sh consumes), otherwise a table.
Scoring (all terms are penalties, 0 is perfect):
  falls          heaviest -- a policy that falls is not a candidate, whatever else it does
  speed          relative error against the run's commanded speed
  heading        |yaw| at the end of the rollout + lateral/forward ratio
  calmness       torso roll peak-to-peak and lateral base velocity (weighted up for --profile calm/tiny)
  gait           swing duration outside 0.2-0.6 s and near-zero single-support share (shuffling, not stepping)
"""
from __future__ import annotations
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "sim/train/zbot_walking_task"

W = {  # profile -> (w_speed, w_heading, w_calm, w_gait)
    "strong": (6.0, 1.0, 0.4, 1.0),
    "calm":   (5.0, 1.0, 1.6, 1.0),
    "tiny":   (7.0, 1.0, 1.6, 1.2),
}


def num(pattern: str, text: str, group: int = 1) -> float | None:
    m = re.search(pattern, text)
    return float(m.group(group)) if m else None


def parse(path: Path) -> dict | None:
    t = path.read_text(errors="replace")
    falls = re.search(r"fall/termination within the horizon:\s*(\d+)\s*/\s*(\d+)", t)
    speed = num(r"mean forward speed\s+([\d.]+)", t)
    if falls is None or speed is None:
        return None
    d = dict(
        falls=int(falls.group(1)) / max(int(falls.group(2)), 1),
        speed=speed,
        fwd=num(r"forward displacement x: mean\s+([\d.]+)", t),
        yaw=num(r"\|yaw\| end mean\s+([\d.]+)", t),
        lat_ratio=num(r"lateral/forward ratio median\s+([\d.]+)", t),
        roll=num(r"torso roll p2p\s+([\d.]+)", t),
        pitch=num(r"pitch p2p\s+([\d.]+)", t),
        lat_vel=num(r"lateral base vel RMS\s+([\d.]+)", t),
        swing=num(r"swing duration: median\s+([\d.]+)", t),
        single=num(r"support phases: single\s+([\d.]+)", t),
        clearance=num(r"foot clearance \(max lift\): L\s+([\d.]+)", t),
        action_rate=num(r"action rate mean\s+([\d.]+)", t),
    )
    return d


def score(d: dict, target: float, profile: str) -> float:
    w_speed, w_head, w_calm, w_gait = W[profile]
    s = 20.0 * d["falls"]
    s += w_speed * abs(d["speed"] - target) / max(target, 1e-3)
    s += w_head * ((d["yaw"] or 0.0) / 20.0 + (d["lat_ratio"] or 0.0))
    s += w_calm * ((d["roll"] or 0.0) / 25.0 + (d["lat_vel"] or 0.0) / 0.1) / 2.0
    swing = (d["swing"] or 0.0) / 1000.0
    s += w_gait * (max(0.0, 0.2 - swing) + max(0.0, swing - 0.6)) / 0.2
    s += w_gait * max(0.0, 0.5 - (d["single"] or 0.0) / 100.0)      # no real single support = shuffling
    return s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("exp")
    ap.add_argument("--target-speed", type=float, default=0.35)
    ap.add_argument("--profile", default="strong", choices=sorted(W))
    ap.add_argument("--path", action="store_true", help="print only the winning checkpoint path")
    ap.add_argument("--min-step", type=int, default=0, help="ignore snapshots below this step")
    a = ap.parse_args()

    snaps = RUNS / a.exp / "snapshots"
    rows = []
    for ev in sorted(snaps.glob("eval_*/eval.txt")):
        step = int(ev.parent.name.removeprefix("eval_"))
        if step < a.min_step:
            continue
        d = parse(ev)
        if d is None:
            continue
        ck = snaps / f"ckpt.{step}.bin"
        if not ck.exists():
            continue
        rows.append((score(d, a.target_speed, a.profile), step, ck, d))
    if not rows:
        print(f"no evaluated snapshots in {snaps}", file=sys.stderr)
        return 1
    rows.sort(key=lambda r: r[0])

    if a.path:
        print(rows[0][2])
        return 0
    print(f"{a.exp}: {len(rows)} evaluated snapshots, profile {a.profile}, target {a.target_speed} m/s")
    print(f"{'step':>6} {'score':>6} {'falls':>6} {'m/s':>6} {'fwd m':>6} {'yaw':>5} {'roll':>6} {'swing':>6} {'single':>6}")
    for s, step, _, d in rows[:15]:
        print(f"{step:6d} {s:6.2f} {d['falls']*100:5.0f}% {d['speed']:6.3f} {d['fwd'] or 0:6.2f} "
              f"{d['yaw'] or 0:5.1f} {d['roll'] or 0:6.1f} {d['swing'] or 0:6.0f} {d['single'] or 0:5.0f}%")
    print("best:", rows[0][2])
    return 0


if __name__ == "__main__":
    sys.exit(main())
