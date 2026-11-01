#!/usr/bin/env python3
"""Mass / centre-of-mass check from a bench 'hold' log (the robot STANDS, the servos hold the pose).

    ~/Documents/stash/ksim-zbot/.venv/bin/python sim/tools/hold_analyze.py hold_log.npz [T_full_legs]

The model is put into the measured pose with both soles flat on the floor and held there with a stiff joint PD; the
torques it needs are what the servos must deliver. They are compared with the load register of the real servos
(100 % load ~ 9 Nm on the legs, from the sag test). Wrong masses or a wrong centre of mass show up as joints (mostly
the ankles and hips) whose real load differs from the model; the sign pattern tells the direction.
"""
import json
import sys
from pathlib import Path

import mujoco
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "sim" / "tests"))
from sim.train.common import center_start_qpos   # noqa: E402
import static_check                               # noqa: E402  (builds the model like the training: sys-ID armature/damping)

TICK_DEG = 360 / 4096
K, D, DT = 1000.0, 20.0, 0.001


def main(path, t_full=9.2):
    z = np.load(path)
    m = json.loads(str(z["meta"]))
    J, offs = m["joints"], np.array(m["offsets"], float)
    n = len(z["t"])
    sel = slice(n // 3, n)                                              # skip the first third: servos settling
    ticks = np.median(z["pos"][sel], axis=0)
    load = np.median(z["load"][sel], axis=0)
    q_deg = (ticks - 2048) * TICK_DEG - offs
    imu = m.get("imu_at_move_end", [])
    R = np.array(json.loads((ROOT / "sim/policies/cad2_v13_tiny_step905/policy_meta.json").read_text())
                 ["imu"]["R_body_from_imu"], float)
    measured_tilt = None
    if imu:
        a = np.array([imu[0][k] for k in ("ax", "ay", "az")], float)
        up = R @ (a / np.linalg.norm(a))
        measured_tilt = float(np.degrees(np.arccos(np.clip(up[2], -1, 1))))

    _, model = static_check.build(DT)
    center_start_qpos(model, dict(zip(J, q_deg)))                      # base pose with the soles flat
    pitch = 2 * np.degrees(np.arcsin(model.qpos0[5]))
    data = mujoco.MjData(model)
    data.qpos[:] = model.qpos0
    for i, name in enumerate(J):
        data.qpos[model.joint(name).qposadr[0]] = np.radians(q_deg[i])
    target = np.array([data.qpos[model.joint(n_).qposadr[0]] for n_ in J])
    adr = np.array([model.joint(n_).qposadr[0] for n_ in J])
    dof = np.array([model.joint(n_).dofadr[0] for n_ in J])
    act = [mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, f"{n_}_ctrl") for n_ in J]
    for _ in range(int(2.0 / DT)):
        tau = K * (target - data.qpos[adr]) - D * data.qvel[dof]
        data.ctrl[act] = np.clip(tau, -8.7, 8.7)
        mujoco.mj_step(model, data)
    pred = data.ctrl[act].copy()
    up_sim = data.xmat[1].reshape(3, 3)[2, 2]
    print("pose: base pitch with flat soles (model) %.1f deg%s; model settled at tilt %.1f deg, height %.3f m" % (
        pitch, "" if measured_tilt is None else f"; head IMU measured tilt {measured_tilt:.1f} deg",
        np.degrees(np.arccos(np.clip(up_sim, -1, 1))), data.qpos[2]))
    print("hold time %.1f s, pack %.1f V" % (z["t"][-1] - z["t"][0], float(np.median(z["volt"]))))
    print("\njoint                 q[deg]  load[/1000]  real[Nm]  model[Nm]  real/model")
    for i, n_ in enumerate(J):
        real = load[i] / 1000.0 * t_full
        print("%-22s %6.1f  %10.0f  %8.2f  %9.2f  %9s" % (
            n_, q_deg[i], load[i], real, pred[i], "%.1f" % (real / pred[i]) if abs(pred[i]) > 0.05 else "-"))
    legs = [i for i, n_ in enumerate(J) if any(k in n_ for k in ("hip_pitch", "knee", "ankle"))]
    a_real = sum(abs(load[i]) for i in legs) / 1000.0 * t_full
    a_pred = float(np.abs(pred[legs]).sum())
    print("\nsum |torque| over the leg pitch joints: real %.2f Nm, model %.2f Nm" % (a_real, a_pred))


if __name__ == "__main__":
    main(sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 9.2)
