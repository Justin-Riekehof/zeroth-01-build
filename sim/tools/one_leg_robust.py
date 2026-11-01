"""Robustness sweep: play the one-leg sequence over servo stiffness x mass x speed for a given number of
interpolated sub-steps in the weight-transfer move (step 2 -> 3)."""
import itertools, json, sys
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from stance_sim import *  # noqa

Y_OUT = -0.0392


def lerp(a, b, t):
    return {k: a[k] + (b[k] - a[k]) * t for k in a}


def build_seq(plan, n_transfer):
    s2, s3 = plan["step2"], plan["step3"]
    seq = [("2", s2)]
    for i in range(1, n_transfer):
        seq.append((f"2>3 {i}/{n_transfer}", lerp(s2, s3, i / n_transfer)))
    seq.append(("3", s3))
    seq += [(f"4.{i+1}", a) for i, a in enumerate(plan["ext"])]
    return seq


def play(args):
    plan, n_transfer, kp, mass, speed, acc, hold = args
    sim = Sim(kp=kp, kd=kp / 50, mass_scale=mass, right_sole=(Y_OUT, plan["y_inner_mm"] / 1000))
    pl = start_standing(sim)
    for name, ang in build_seq(plan, n_transfer):
        if not pl.move(ang, speed, acc, hold_s=hold):
            return args[1:], False, name
    r = pl.log[-1]
    return args[1:], True, (round(r[2] * 1e3, 1), round(r[3] * 1e3, 1))


if __name__ == "__main__":
    plan = json.load(open(sys.argv[1]))
    ns = [int(x) for x in sys.argv[2].split(",")]
    speed = float(sys.argv[3]); acc = float(sys.argv[4])
    jobs = [(plan, n, kp, m, speed, acc, 1.0) for n in ns for kp in (30, 60, 120) for m in (0.9, 1.0, 1.1)]
    with Pool(6) as p:
        res = p.map(play, jobs)
    for n in ns:
        sub = [r for r in res if r[0][0] == n]
        print(f"n_transfer={n}: {sum(r[1] for r in sub)}/{len(sub)} ok; failures:", [(r[0][1], r[0][2], r[2]) for r in sub if not r[1]])
