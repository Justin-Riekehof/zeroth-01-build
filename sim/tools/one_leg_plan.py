"""Plan the 4 poses of the one-leg-stance demo (stance = right) for a given right-sole width.

    python sim/tools/one_leg_plan.py <y_inner_mm> [knee_bend] [knee_ext]

y_inner: where the flat right sole ends on the inside, in mm from the ankle axis towards the body
centre (outer edge fixed at the printed foot outline + 1.6 mm wall). Poses: 1 centre, 2 right knee bent +
leaned (both feet flat, feet NOT moved), 3 left foot lifted (weight fully on the right leg), 4 right knee extended.
Kinematic search (flat stance sole, CoM over the sole polygon), verified afterwards by one_leg_verify.py.
"""
import json
import sys

import numpy as np
from scipy.optimize import differential_evolution

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from stance_sim import *  # noqa

LIM = json.loads((ROOT / "hardware/joint_limits.json").read_text())
Y_OUT = -0.0392
J = ["right_hip_pitch", "right_hip_yaw", "right_hip_roll", "right_knee_pitch", "right_ankle_pitch",
     "left_hip_pitch", "left_hip_yaw", "left_hip_roll", "left_knee_pitch", "left_ankle_pitch"]
BOUND_MARGIN = 3.0
CAP_Y, CAP_X = 0.012, 0.02


def setup(y_in_mm):
    global sim, N0, POS0, ROT0
    sim = Sim(right_sole=(Y_OUT, y_in_mm / 1000.0))
    fk(sim, center_pose())
    N0 = support_margin(sim, "Right")[3].copy()
    POS0, ROT0 = rel_left()


def frame(side):
    P = sole_corners(sim, side); c = P.mean(0)
    mx, my, cc, n = support_margin(sim, side)
    ex = P[1] - P[0]; ex = ex - n * (ex @ n); ex /= np.linalg.norm(ex)
    return c, ex, np.cross(n, ex), n, cc


def rel_left():
    cR, exR, eyR, nR, _ = frame("Right")
    cL, exL, eyL, nL, _ = frame("Left")
    d = cL - cR
    return np.array([d @ exR, d @ eyR, d @ nR]), np.array([nL @ exR, nL @ eyR, exL @ eyR])


def body_pt(name):
    return sim.d.xpos[sim.m.body(name).id].copy()


def seg_dist(p, a, b):
    ab = b - a
    t = np.clip(((p - a) @ ab) / (ab @ ab), 0, 1)
    return np.linalg.norm(p - (a + t * ab))


def geometry(ang):
    fk(sim, ang)
    mx, my, cc, n = support_margin(sim, "Right")
    Pr = sole_corners(sim, "Right"); c = Pr.mean(0)
    L = sole_corners(sim, "Left")
    clear = ((L - c) @ n).min()
    rh, rk, ra = body_pt("right_hip_yaw_link"), body_pt("right_knee_pitch_link"), body_pt("right_ankle_pitch_link")
    pts = [body_pt("left_knee_pitch_link"), body_pt("left_ankle_pitch_link")] + list(L)
    dmin = min(min(seg_dist(p, rh, rk), seg_dist(p, rk, ra)) for p in pts)
    return dict(mx=mx, my=my, cc=cc, n=n, clear=clear, dmin=dmin)


def reg(ang, ref=None, w=0.002):
    r = sum((ang[j] / 90.0) ** 2 for j in J) * w
    if ref:
        r += sum(((ang[j] - ref[j]) / 90.0) ** 2 for j in J) * 0.05
    return r


NATURAL = {   # keep the poses human-readable: no twisted/over-extended legs
    "right_hip_pitch": (-45, 45), "left_hip_pitch": (-30, 45),
    "right_hip_yaw": (-3, 45), "left_hip_yaw": (-15, 5),
    "right_hip_roll": (-12, 12), "left_hip_roll": (-12, 12),
    "right_ankle_pitch": (-45, 45), "left_ankle_pitch": (-45, 45),
    "left_knee_pitch": (-90, 20),
}


def solve(kind, knee, ref=None, seed=0):
    free = [j for j in J if j != "right_knee_pitch"]
    b = [NATURAL[j] for j in free]

    def full(y):
        a = dict(zip(free, y)); a["right_knee_pitch"] = knee
        return a

    def f(y):
        ang = full(y)
        g = geometry(ang)
        cost = reg(ang, ref) + 3 * (g["n"][0] - N0[0]) ** 2
        cost += -min(g["my"], CAP_Y) / CAP_Y - 0.5 * min(g["mx"], CAP_X) / CAP_X
        cost += 20 * max(0, 0.006 - g["my"]) / 0.006 + 20 * max(0, 0.015 - g["mx"]) / 0.015
        cost += 3 * g["n"][1] ** 2
        if kind == "double":                      # both feet stay where the centre pose put them
            cost += 8 * (g["cc"][0] / 0.02) ** 2 * 0.1
            pos, rot = rel_left()
            ep = np.linalg.norm(pos - POS0) * 1e3; er = np.linalg.norm(rot - ROT0) * 57.3
            cost += 3 * (ep / 1.0) ** 2 + 3 * (er / 0.7) ** 2
        else:                                     # left foot in the air, legs apart
            cost += 6 * max(0, 0.03 - g["clear"]) / 0.03 + 6 * max(0, 0.06 - g["dmin"]) / 0.06
        return cost

    init = "latinhypercube"
    if ref:                              # seed half of the population around the previous step
        rng = np.random.default_rng(seed)
        lo, hi = np.array([x[0] for x in b], float), np.array([x[1] for x in b], float)
        x0 = np.array([ref[j] for j in free], float)
        n = len(free); N = 15 * n
        init = np.vstack([rng.uniform(lo, hi, (N, n)), np.clip(x0 + rng.normal(0, 4.0, (N, n)), lo, hi)])
    r = differential_evolution(f, b, seed=seed, popsize=30, maxiter=500, tol=1e-9, polish=True, init=init)
    ang = full(r.x)
    return ang, geometry(ang)


def foot_err(ang):
    fk(sim, ang)
    pos, rot = rel_left()
    return np.linalg.norm(pos - POS0) * 1e3, np.linalg.norm(rot - ROT0) * 57.3


def show(tag, ang, g):
    ep, er = foot_err(ang)
    print(tag, "left-foot err vs centre pose: %.1f mm %.1f deg" % (ep, er))
    print(tag, "my %.1f mx %.1f mm" % (g["my"] * 1e3, g["mx"] * 1e3), "CoM in sole (mm)", np.round(np.array(g["cc"][:2]) * 1e3, 1),
          "clear %.0f dmin %.0f mm" % (g["clear"] * 1e3, g["dmin"] * 1e3), "torso n", np.round(g["n"], 2))
    print("   ", {k: round(float(v), 1) for k, v in ang.items()})


if __name__ == "__main__":
    y_in = float(sys.argv[1]); kb = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0
    ke = float(sys.argv[3]) if len(sys.argv) > 3 else 4.0
    setup(y_in)
    out = {"y_inner_mm": y_in}
    a2, g2 = solve("double", kb); show("step2", a2, g2); out["step2"] = a2
    a3, g3 = solve("single", kb, ref=a2); show("step3", a3, g3); out["step3"] = a3
    a4, g4 = solve("single", ke, ref=a3); show("step4", a4, g4); out["step4"] = a4
    json.dump(out, open(f"/tmp/claude-1000/-home-justin-Documents-stash-zeroth-01-build/2fae1a81-4022-4edf-8866-65029aa5af89/scratchpad/plan_{int(y_in)}.json", "w"), indent=1)
