"""Live CoM check: gravity from the head IMU + measured joint angles -> where the model CoM falls on the stance sole."""
import json, sys, time, urllib.request, mujoco, numpy as np
from mujoco_scenes.mjcf import load_mjmodel
H = "http://192.168.43.20:8460"
get = lambda p: json.load(urllib.request.urlopen(H + p, timeout=4))
A, P = [], []
for _ in range(25):
    s = get("/status")["head"]["imu"]["sample"]; A.append([s["ax"], s["ay"], s["az"]]); P.append(get("/robot_pose")["pose"]); time.sleep(0.2)
A = np.array(A); ang = {k: float(np.mean([p[k] for p in P])) for k in P[0]}
print("IMU |a| mg %.0f, std per axis %s | pose spread (max joint std) %.2f deg" % (np.linalg.norm(A.mean(0)), A.std(0).round(1), max(np.std([p[k] for p in P]) for k in P[0])))
m = load_mjmodel("sim/assets/zbot-cad-tpu/robot.mjcf", scene="smooth"); d = mujoco.MjData(m)
names = [m.joint(i).name for i in range(1, m.njnt)]
d.qpos[:] = 0; d.qpos[3] = 1
for j, v in ang.items():
    if j in names: d.qpos[7 + names.index(j)] = np.radians(v)
mujoco.mj_forward(m, d)
site = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_SITE, "imu")
up_w = d.site_xmat[site].reshape(3, 3) @ (A.mean(0) / np.linalg.norm(A.mean(0)))   # model-world direction of real "up"
for Sn in ("Right", "Left"):
    g = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, f"{Sn}_Foot_collision_box"); b = m.geom_bodyid[g]
    R = d.xmat[b].reshape(3, 3); up = R.T @ up_w
    c = R.T @ (d.subtree_com[0] - d.xpos[b]); z0 = m.geom_pos[g][2] - m.geom_size[g][2]
    t = (c[2] - z0) / up[2]; p = c - up * t
    lo, hi = (m.geom_pos[g] - m.geom_size[g])[:2], (m.geom_pos[g] + m.geom_size[g])[:2]
    pitch = np.degrees(np.arctan2(up[0], up[2])); roll = np.degrees(np.arctan2(up[1], up[2]))
    print(f"{Sn}: foot tilt vs gravity {np.degrees(np.arccos(up[2])):5.1f} deg (pitch {pitch:+.1f}, roll {roll:+.1f}) | CoM projected on sole x {p[0]*1e3:6.1f} y {p[1]*1e3:6.1f} mm | sole x {lo[0]*1e3:.0f}..{hi[0]*1e3:.0f} y {lo[1]*1e3:.0f}..{hi[1]*1e3:.0f} | height above sole {t*1e3:.0f} mm")
print({k: round(v, 1) for k, v in ang.items() if "hip" in k or "ankle" in k or "knee" in k})
