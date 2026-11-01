#!/usr/bin/env python3
"""Static stiffness from a bench 'sag' log (src/pi_service/bench.py): a limb held at a growing angle sags under its own
weight; the model says how much torque that weight is, the servo's load register says how hard it works.

    ~/Documents/stash/ksim-zbot/.venv/bin/python sim/tools/sag_analyze.py sag_log.npz   (needs mujoco; .cad has none)

Per hold (joint, angle): measured sag (ticks, deg), load register (-1000..1000 = +-100 % of the torque limit) and the
gravity torque the model (sim/assets/zbot-cad, datasheet masses) predicts at the MEASURED pose, with the gravity
direction taken from the head IMU. Fit per servo type:
    K_est  = tau_model / sag            [Nm/rad]  static stiffness of the servo (if the model masses are right)
    T_full = tau_model / (load / 1000)  [Nm]      torque that 100 % load stands for
A wrong mass/CoM shows up as a joint that does not fit the other joints of its type.
"""
import json
import sys
from pathlib import Path

import mujoco
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
TICK_DEG = 360 / 4096
ARMS = {"left_shoulder_pitch", "left_shoulder_yaw", "left_elbow_yaw",
        "right_shoulder_pitch", "right_shoulder_yaw", "right_elbow_yaw"}


def imu_rotation():
    meta = json.loads((ROOT / "sim/policies/cad2_v13_tiny_step905/policy_meta.json").read_text())
    return np.array(meta["imu"]["R_body_from_imu"], float)


def main(path):
    z = np.load(path)
    m = json.loads(str(z["meta"]))
    J, offs, mv = m["joints"], np.array(m["offsets"], float), m["moves"]
    pos, load, goal, move = z["pos"], z["load"], z["goal"], z["move"].astype(int)
    imu = {x["move"]: x for x in m.get("imu_at_move_end", [])}
    R = imu_rotation()
    spec = mujoco.MjSpec.from_file(str(ROOT / "sim/assets/zbot-cad/robot.mjcf"))
    spec.worldbody.add_geom(name="floor", type=mujoco.mjtGeom.mjGEOM_PLANE, size=[1, 1, 0.1])   # the MJCF names it
    model = spec.compile()
    data = mujoco.MjData(model)
    adr = {n: (model.joint(n).qposadr[0], model.joint(n).dofadr[0]) for n in J}
    rows = []
    for mi, mv_ in enumerate(mv):
        if not mv_["label"].endswith("deg") or mi not in imu:
            continue
        sel = np.where(move == mi)[0]
        if len(sel) < 30:
            continue
        end = sel[-30:]                                           # the last 0.6 s of the hold
        ticks = np.median(pos[end], axis=0)
        q = (ticks - 2048) * TICK_DEG - offs
        a = np.array([imu[mi][k] for k in ("ax", "ay", "az")], float)
        up_body = R @ (a / np.linalg.norm(a))                     # body-frame direction of "up"
        model.opt.gravity[:] = -9.81 * up_body
        mujoco.mj_resetData(model, data)
        for i, n in enumerate(J):
            data.qpos[adr[n][0]] = np.radians(q[i])
        mujoco.mj_forward(model, data)
        j = J.index(mv_["joint"])
        tau = float(data.qfrc_bias[adr[mv_["joint"]][1]])         # gravity torque on the joint, Nm
        sag_ticks = float(np.median(pos[end, j]) - np.median(goal[end, j]))
        rows.append((mv_["joint"], float(mv_["amp"]), tau, sag_ticks, float(np.median(load[end, j])),
                     float(np.degrees(np.arccos(np.clip(up_body[2], -1, 1))))))
    if not rows:
        sys.exit("no sag holds with IMU data in this log")
    print("joint                  angle  tau_model[Nm]  sag[ticks]  sag[deg]  load[/1000]  tilt[deg]")
    for r in rows:
        print("%-22s %5.0f  %12.2f  %9.1f  %8.2f  %10.0f  %8.0f" % (r[0], r[1], r[2], r[3], r[3] * TICK_DEG, r[4], r[5]))
    for kind, sel in (("arms (STS3215)", lambda n: n in ARMS), ("legs (STS3250)", lambda n: n not in ARMS)):
        rr = np.array([(r[2], r[3], r[4]) for r in rows if sel(r[0])], float).reshape(-1, 3)
        rr = rr[np.abs(rr[:, 0]) > 0.05]
        if len(rr) < 1:
            continue
        tau, sag, ld = rr[:, 0], np.radians(rr[:, 1] * TICK_DEG), rr[:, 2]
        # signs: only the magnitudes are compared (the sign convention of sag / load differs per servo)
        k = np.sum(np.abs(tau) * np.abs(sag)) / max(np.sum(sag ** 2), 1e-12)
        t_full = np.sum(np.abs(tau)) / max(np.sum(np.abs(ld)) / 1000.0, 1e-9)
        print("\n%s: n=%d  K_est %.1f Nm/rad (%.2f Nm/deg)  |  100 %% load = %.1f Nm  |  sim soft PD: 22.7 Nm/rad" % (
            kind, len(rr), k, k * np.pi / 180, t_full))


if __name__ == "__main__":
    main(sys.argv[1])
