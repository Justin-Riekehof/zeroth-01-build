"""Search a motion profile for ONE hard demo transition (pose A -> pose B) in physics.

For a weight shift on one leg the end poses are fine statically; the problem is the way
between them: the CoM has to be accelerated across and brought to rest over the stance
sole, with servos that only know position + speed/acc ramps. This tool takes two steps of
a demo, plays candidate profiles on the MuJoCo model (servo-ramp player of stance_sim.py)
and ranks them by the smallest CoM margin over the stance sole during the whole move.

Profile = push to a waypoint W = A + f*(B-A) at (v1, a1) -> go on to B at (v2, a2).
 - sync: speeds scaled per joint so all arrive together (demo "sync" flag)
 - blend: leave phase 1 when every joint is within `blend` deg of W instead of waiting for it
   to stop, so the phase-1 velocity carries into phase 2 (the "push"). NEEDS a blend feature
   in the Pi player (not there yet) - candidates without blend are playable today.

    PY=~/Documents/stash/ksim-zbot/.venv/bin/python
    $PY sim/tools/transition_plan.py demos/one_leg_left.json --from 3 --to 4 --stance Left \
        --sole-inner-mm 60 [--demo-file path] [-n 300]
"""
import argparse
import json
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from stance_sim import *  # noqa
from stance_sim import TICK_DEG, Player, Sim, center_pose, sole_corners, start_standing

Y_OUT = 0.0392          # outer sole edge from the ankle frame centre line (metres)


def margin_world(sim, side):
    """Smallest distance (m) of the CoM to an edge of the stance sole box, on the floor plane
    (positive = inside). Uses the sole's horizontal long axis, so a tipping foot shows up."""
    P = sole_corners(sim, side)
    c = P.mean(0)
    xb = sim.d.geom_xmat[sim.feet[side][0]].reshape(3, 3)[:, 0].copy()
    ex = np.array([xb[0], xb[1], 0.0]); ex /= np.linalg.norm(ex)
    ey = np.array([-ex[1], ex[0], 0.0])
    Q = np.stack([(P - c) @ ex, (P - c) @ ey], 1)
    r = sim.com() - c
    cx, cy = r @ ex, r @ ey
    return min(cx - Q[:, 0].min(), Q[:, 0].max() - cx, cy - Q[:, 1].min(), Q[:, 1].max() - cy)


class Mover(Player):
    """Player with per-joint synchronised speeds, early hand-over (blend) and margin tracking."""

    def __init__(self, sim, stance):
        super().__init__(sim, stance)
        self.min_margin = 9.0
        self.max_tilt = 0.0

    def record(self, t):
        super().record(t)
        self.min_margin = min(self.min_margin, margin_world(self.s, self.stance))
        self.max_tilt = max(self.max_tilt, self.s.tilt_deg())

    def go(self, angles, speed, acc, sync=False, blend_deg=None, hold_s=0.0, max_s=20.0):
        s = self.s
        goal = s.target.copy()
        for i, n in enumerate(s.names):
            if n in angles:
                goal[i] = np.radians(angles[n])
        dist = np.abs(goal - s.target)
        vtop = np.radians(speed * TICK_DEG)
        vmax = np.full(s.m.nu, vtop)
        if sync and dist.max() > 1e-9:
            vmax = np.maximum(np.radians(20 * TICK_DEG), vtop * dist / dist.max())
        amax = np.radians(acc * 100 * TICK_DEG)
        dt = s.m.opt.timestep
        t, k = 0.0, 0
        while t < max_s:
            self._servo_step(goal, vmax, amax, dt)
            s.step(1); t += dt; k += 1
            if k % 20 == 0:
                self.record(t)
                if self.fell:
                    return False
            err = np.abs(goal - s.target)
            if blend_deg is not None and np.degrees(err.max()) < blend_deg:
                break
            if err.max() < 1e-6 and t > 0.05:
                break
        for _ in range(int(hold_s / dt)):
            s.step(1); t += dt; k += 1
            if k % 20 == 0:
                self.record(t)
                if self.fell:
                    return False
        return True


def pose_of(step):
    return center_pose() if step.get("center") else dict(step["angles"])


def lerp(a, b, f):
    return {j: a.get(j, 0.0) + f * (b.get(j, 0.0) - a.get(j, 0.0)) for j in set(a) | set(b)}


def run(args):
    A, B, prof, stance, soles, kp, mass = args
    sim = Sim(kp=kp, kd=kp / 50, mass_scale=mass, **soles)
    sim.reset(A, stance)
    sim.step(int(1.5 / sim.m.opt.timestep))
    mv = Mover(sim, stance)
    mv.min_margin = 9.0
    if sim.tilt_deg() > 10 or margin_world(sim, stance) < 0:
        return dict(ok=False, why="start pose not stable", margin=-9)
    ok = True
    if prof["f"] < 1.0:
        W = lerp(A, B, prof["f"])
        ok = mv.go(W, prof["v1"], prof["a1"], prof["sync"], prof["blend"])
    if ok:
        ok = mv.go(B, prof["v2"], prof["a2"], prof["sync"], None, hold_s=1.5)
    if not ok or mv.fell:
        return dict(ok=False, why=mv.fell or "fell", margin=mv.min_margin)
    final_ok = sim.tilt_deg() < 10 and margin_world(sim, stance) > 0.002
    return dict(ok=bool(final_ok), why="" if final_ok else "final pose not held",
                margin=float(mv.min_margin), tilt=float(mv.max_tilt))


def sample_profiles(n, rng, allow_blend):
    out = [dict(f=1.0, v1=0, a1=0, v2=v, a2=a, sync=sy, blend=None)       # direct moves
           for v in (100, 200, 400, 800, 1600, 3400) for a in (30, 100, 254) for sy in (False, True)]
    while len(out) < n:
        out.append(dict(f=float(rng.uniform(0.3, 0.95)),
                        v1=int(rng.choice([400, 800, 1600, 3400])), a1=int(rng.choice([60, 120, 254])),
                        v2=int(rng.choice([60, 100, 200, 400])), a2=int(rng.choice([20, 40, 80])),
                        sync=bool(rng.integers(2)),
                        blend=float(rng.choice([2, 4, 8, 15])) if allow_blend and rng.integers(2) else None))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("demo")
    ap.add_argument("--from", dest="a", type=int, required=True)
    ap.add_argument("--to", dest="b", type=int, required=True)
    ap.add_argument("--stance", default="Left", choices=["Left", "Right"])
    ap.add_argument("--sole-inner-mm", type=float, default=None,
                    help="widen the stance sole: inner edge this far beyond the ankle axis (none = stock foot)")
    ap.add_argument("-n", type=int, default=200)
    ap.add_argument("--no-blend", action="store_true")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    demo = json.load(open(a.demo))
    A, B = pose_of(demo["steps"][a.a - 1]), pose_of(demo["steps"][a.b - 1])
    soles = {}
    if a.sole_inner_mm:
        w = a.sole_inner_mm / 1000
        soles = {"left_sole": (Y_OUT, -w)} if a.stance == "Left" else {"right_sole": (-Y_OUT, w)}
    rng = np.random.default_rng(1)
    cands = sample_profiles(a.n, rng, not a.no_blend)
    with Pool(18) as pool:
        res = pool.map(run, [(A, B, p, a.stance, soles, 30, 1.0) for p in cands])
        good = sorted([(r["margin"], p) for p, r in zip(cands, res) if r["ok"]], key=lambda x: -x[0])
        print(f"{len(good)}/{len(cands)} candidates stay up with kp 30; reference: step {a.a} -> {a.b}, stance {a.stance}")
        top = [p for _, p in good[:8]]
        rob = []
        for p in top:                                       # robustness: servo stiffness x mass
            jobs = [(A, B, p, a.stance, soles, kp, m) for kp in (20, 30, 60) for m in (0.9, 1.0, 1.1)]
            rr = pool.map(run, jobs)
            rob.append((sum(r["ok"] for r in rr), min(r["margin"] for r in rr), p))
    rob.sort(key=lambda x: (-x[0], -x[1]))
    for okn, mm, p in rob:
        print(f"  robust {okn}/9  worst margin {mm * 1000:+.1f} mm  {p}")
    if not rob:
        r0 = run((A, B, cands[0], a.stance, soles, 30, 1.0))
        print("no candidate works. e.g. direct move:", r0)
    if a.out:
        json.dump([dict(robust_ok=o, worst_margin_mm=m * 1000, profile=p) for o, m, p in rob], open(a.out, "w"), indent=1)


if __name__ == "__main__":
    main()
