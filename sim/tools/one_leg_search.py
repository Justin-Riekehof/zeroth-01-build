"""Search kinematically-balanced poses for the one-leg-stance demo (stance foot = right).

Cost uses forward kinematics only (fast): with the stance sole flat on the floor the CoM must
project into the sole polygon with margin; the other foot must clear the floor and the legs
must not cross. Result poses are verified/refined in physics by one_leg_verify.py.
"""
import json
import sys

import numpy as np
from scipy.optimize import differential_evolution

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from stance_sim import *  # noqa

LIM = json.loads((ROOT / "hardware/joint_limits.json").read_text())
sim = Sim()
W_ROLL = 0.0
c0 = center_pose()
fk(sim, c0)
N0 = support_margin(sim, "Right")[3].copy()          # sole normal (base frame) in the centre pose

V = ["right_hip_pitch", "right_hip_yaw", "right_knee_pitch", "right_ankle_pitch",
     "left_hip_pitch", "left_hip_yaw", "left_hip_roll", "left_knee_pitch", "left_ankle_pitch",
     "right_shoulder_yaw", "left_shoulder_yaw"]


def bounds(m=4.0, fixed=None):
    b = []
    for v in V:
        lo, hi = LIM[v]["min_deg"] + m, LIM[v]["max_deg"] - m
        b.append((lo, hi))
    return b


def body_pt(name):
    return sim.d.xpos[sim.m.body(name).id].copy()


def seg_dist(p, a, b):
    ab = b - a
    t = np.clip(((p - a) @ ab) / (ab @ ab), 0, 1)
    return np.linalg.norm(p - (a + t * ab))


def evaluate(x, fixed=None, detail=False):
    ang = dict(zip(V, x))
    if fixed:
        ang.update(fixed)
    fk(sim, ang)
    mx, my, cc, n = support_margin(sim, "Right")
    P = sole_corners(sim, "Right")
    c = P.mean(0)
    L = sole_corners(sim, "Left")
    clear = ((L - c) @ n).min()
    # leg crossing: left knee/ankle/foot corners vs right thigh+shank segments
    rh, rk, ra = body_pt("right_hip_yaw_link"), body_pt("right_knee_pitch_link"), body_pt("right_ankle_pitch_link")
    pts = [body_pt("left_knee_pitch_link"), body_pt("left_ankle_pitch_link")] + list(L)
    dmin = min(min(seg_dist(p, rh, rk), seg_dist(p, rk, ra)) for p in pts)
    s = min(my / 0.0175, mx / 0.05)
    cost = -s
    cost += 6 * max(0, 0.03 - clear) / 0.03
    cost += 6 * max(0, 0.06 - dmin) / 0.06
    cost += 3 * (n[0] - N0[0]) ** 2 + W_ROLL * n[1] ** 2                      # keep the torso pitch of the centre pose
    cost += 0.02 * sum((ang[v] / 90.0) ** 2 for v in V)  # prefer small angles
    if detail:
        return dict(cost=cost, mx=mx, my=my, com=cc, clear=clear, dmin=dmin, n=n, ang=ang)
    return cost


def search(fixed=None, seed=0, x0=None, pop=25, iters=300):
    fixed = fixed or {}
    free = [v for v in V if v not in fixed]
    b = [bb for v, bb in zip(V, bounds()) if v not in fixed]

    def f(y):
        ang = dict(zip(free, y))
        ang.update(fixed)
        return evaluate([ang[v] for v in V], None)
    r = differential_evolution(f, b, seed=seed, popsize=pop, maxiter=iters, tol=1e-8, polish=True)
    ang = dict(zip(free, r.x)); ang.update(fixed)
    return ang, evaluate([ang[v] for v in V], detail=True)


if __name__ == "__main__":
    import ast
    knee = float(sys.argv[1]); W_ROLL = float(sys.argv[2])
    ang, info = search(fixed={"right_knee_pitch": knee}, seed=0, pop=20, iters=250)
    print("knee", knee, "wroll", W_ROLL)
    print({k: round(float(v), 1) for k, v in ang.items()})
    print({k: np.round(v, 4) for k, v in info.items() if k != "ang"})
