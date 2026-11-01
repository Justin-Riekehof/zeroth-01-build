"""Calibrate the IMU direction on the two-foot reading, re-project the one-leg readings."""
import re, sys, ast, numpy as np, mujoco
from mujoco_scenes.mjcf import load_mjmodel
S = sys.argv[1]
m = load_mjmodel("sim/assets/zbot-cad-tpu/robot.mjcf", scene="smooth"); d = mujoco.MjData(m)
names = [m.joint(i).name for i in range(1, m.njnt)]
def reading(n):
    t = open(f"{S}/com_reading_{n}.txt").read()
    ang = ast.literal_eval(re.findall(r"^\{.*\}$", t, re.M)[-1])
    r = {}
    for side in ("Right", "Left"):
        mm = re.search(side + r": .*pitch ([+-][\d.]+), roll ([+-][\d.]+)", t)
        r[side] = np.radians([float(mm[1]), float(mm[2])])
    return ang, r
def fk(ang):
    d.qpos[:] = 0; d.qpos[3] = 1
    for j, v in ang.items():
        d.qpos[7 + names.index(j)] = np.radians(v)
    mujoco.mj_forward(m, d)
def foot(side):
    g = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, f"{side}_Foot_collision_box"); return g, m.geom_bodyid[g], d.xmat[m.geom_bodyid[g]].reshape(3, 3)
def up_world(side, pr):
    _, _, R = foot(side); u = np.array([np.tan(pr[0]), np.tan(pr[1]), 1.0]); return R @ (u / np.linalg.norm(u))
def rot(a, b):                 # minimal rotation taking a to b
    v, c = np.cross(a, b), a @ b; K = np.array([[0,-v[2],v[1]],[v[2],0,-v[0]],[-v[1],v[0],0]])
    return np.eye(3) + K + K @ K / (1 + c)
ang1, r1 = reading(1); fk(ang1)
meas = up_world("Right", r1["Right"])      # same vector whichever foot it is computed from
zr, zl = foot("Right")[2][:, 2], foot("Left")[2][:, 2]
print("center pose: angle between the two soles in FK %.1f deg" % np.degrees(np.arccos(np.clip(zr @ zl, -1, 1))))
ideal = (zr + zl) / np.linalg.norm(zr + zl)
C = rot(meas, ideal)
print("IMU correction from the two-foot stance: %.1f deg" % np.degrees(np.arccos(meas @ ideal)))
for n, side, lab in ((2, "Right", "one_leg_right (alt)"), (4, "Right", "one_leg_right (neu)"), (3, "Left", "one_leg_left")):
    ang, r = reading(n); fk(ang)
    u0 = up_world(side, r[side]); up_w = C @ u0
    g, b, R = foot(side); up = R.T @ up_w
    c = R.T @ (d.subtree_com[0] - d.xpos[b]); z0 = m.geom_pos[g][2] - m.geom_size[g][2]
    p = c - up * (c[2] - z0) / up[2]
    lo, hi = (m.geom_pos[g] - m.geom_size[g])[:2] * 1e3, (m.geom_pos[g] + m.geom_size[g])[:2] * 1e3
    pr = np.degrees([np.arctan2(up[0], up[2]), np.arctan2(up[1], up[2])])
    f = lambda v, a, b: "inside" if a <= v <= b else f"{min(abs(v-a), abs(v-b)):.0f} mm outside"
    print(f"{lab}: calibrated foot tilt pitch {pr[0]:+.1f} roll {pr[1]:+.1f} deg | CoM on sole x {p[0]*1e3:6.1f} ({f(p[0]*1e3, lo[0], hi[0])}, {lo[0]:.0f}..{hi[0]:.0f}), y {p[1]*1e3:6.1f} ({f(p[1]*1e3, lo[1], hi[1])}, {lo[1]:.0f}..{hi[1]:.0f}) | if foot flat: x {c[0]*1e3:.1f} y {c[1]*1e3:.1f}")
