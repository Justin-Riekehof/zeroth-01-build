"""Step 2 of the one-leg demo: both feet stay flat where the centre pose put them, the CoM is moved
over the RIGHT sole as far as the joints allow (hip_roll/hip_pitch swing the right foot under the body)."""
import sys, json
import numpy as np
from scipy.optimize import differential_evolution
sys.path.insert(0, "sim/tools")
from stance_sim import *

LIM = json.loads((ROOT / "hardware/joint_limits.json").read_text())
sim = Sim()
ARMS = ["right_shoulder_yaw", "left_shoulder_yaw", "right_shoulder_pitch", "left_shoulder_pitch"]
J = ["right_hip_pitch", "right_hip_yaw", "right_hip_roll", "right_knee_pitch", "right_ankle_pitch",
     "left_hip_pitch", "left_hip_yaw", "left_hip_roll", "left_knee_pitch", "left_ankle_pitch"]


def frame(side):
    P = sole_corners(sim, side); c = P.mean(0)
    mx, my, cc, n = support_margin(sim, side)
    ex = P[1] - P[0]; ex = ex - n * (ex @ n); ex /= np.linalg.norm(ex)
    xb = sim.d.geom_xmat[sim.feet[side][0]].reshape(3, 3)[:, 0]
    if ex @ xb < 0: ex = -ex
    return c, ex, np.cross(n, ex), n, cc


def rel_left():
    cR, exR, eyR, nR, _ = frame("Right")
    cL, exL, eyL, nL, _ = frame("Left")
    d = cL - cR
    return np.array([d @ exR, d @ eyR, d @ nR]), np.array([nL @ exR, nL @ eyR, exL @ eyR])


fk(sim, center_pose())
POS0, ROT0 = rel_left()
CX0 = frame("Right")[4]
print("centre pose: left foot rel. to right (mm)", (POS0 * 1e3).round(1), "rot", ROT0.round(3), "CoM in right sole (mm)", (np.array(CX0) * 1e3).round(1))


def evaluate(x, knee, detail=False):
    ang = dict(zip(J, x)); ang["right_knee_pitch"] = knee
    ang["right_hip_pitch"] = x[0]
    fk(sim, ang)
    pos, rot = rel_left()
    ep = np.linalg.norm(pos - POS0) * 1e3          # mm
    er = np.linalg.norm(rot - ROT0) * 57.3          # ~deg
    cc = frame("Right")[4]
    cost = (ep / 1.0) ** 2 * 3 + (er / 0.7) ** 2 * 3
    cost += (cc[1] * 1e3) ** 2 * 0.05 + max(0, abs(cc[0]) * 1e3 - 12) ** 2 * 0.02
    cost += 0.002 * sum((a / 90) ** 2 for a in x)
    if detail:
        return dict(ep=ep, er=er, cx=cc[0] * 1e3, cy=cc[1] * 1e3, ang=ang)
    return cost


def run_free(seed=0, w_cy=0.05, tol_mm=1.0, tol_deg=0.7):
    """all leg joints AND the arms free; how far can the CoM go with both feet flat and unmoved?"""
    names = J + ARMS
    b = [(LIM[j]["min_deg"] + 3, LIM[j]["max_deg"] - 3) for j in names]
    def f(y):
        ang = dict(zip(names, y)); fk(sim, ang)
        pos, rot = rel_left()
        ep = np.linalg.norm(pos - POS0) * 1e3; er = np.linalg.norm(rot - ROT0) * 57.3
        cc = frame("Right")[4]
        return (ep / tol_mm) ** 2 * 3 + (er / tol_deg) ** 2 * 3 + (cc[1] * 1e3) ** 2 * w_cy + max(0, abs(cc[0]) * 1e3 - 15) ** 2 * 0.05
    r = differential_evolution(f, b, seed=seed, popsize=30, maxiter=600, tol=1e-10, polish=True)
    ang = dict(zip(names, r.x)); fk(sim, ang)
    pos, rot = rel_left(); cc = frame("Right")[4]
    return dict(ep=np.linalg.norm(pos - POS0) * 1e3, er=np.linalg.norm(rot - ROT0) * 57.3, cx=cc[0] * 1e3, cy=cc[1] * 1e3, ang=ang)


def run(knee, seed=0):
    names = [j for j in J if j != "right_knee_pitch"]
    b = [(LIM[j]["min_deg"] + 3, LIM[j]["max_deg"] - 3) for j in J]
    keep = [i for i, j in enumerate(J) if j != "right_knee_pitch"]
    def f(y):
        x = np.zeros(len(J)); x[keep] = y
        return evaluate(x, knee)
    r = differential_evolution(f, [b[i] for i in keep], seed=seed, popsize=30, maxiter=500, tol=1e-9, polish=True)
    x = np.zeros(len(J)); x[keep] = r.x
    return evaluate(x, knee, detail=True)


if __name__ == "__main__":
    if sys.argv[1] == "free":
        for w in (0.5, 5.0):
            d = run_free(w_cy=w)
            print("free w_cy", w, {k: round(float(v), 2) for k, v in d.items() if k != "ang"})
            print("  ", {k: round(float(v), 1) for k, v in d["ang"].items()})
        sys.exit()
    for knee in [float(a) for a in sys.argv[1:]]:
        d = run(knee)
        print("knee", knee, {k: round(float(v), 2) for k, v in d.items() if k != "ang"})
        print("  ", {k: round(float(v), 1) for k, v in d["ang"].items()})
