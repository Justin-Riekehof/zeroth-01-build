"""Does the sim robot stand in the real centre pose when its joints are stiff enough?  (soft joints vs. wrong masses)

    ~/Documents/stash/ksim-zbot/.venv/bin/python sim/tests/static_check.py

Plain MuJoCo, CPU. Holds the centre pose with a joint PD of stiffness K (Nm/rad), torque-limited as the real servos,
and reports the body tilt over time, the centre of pressure of the soles and the holding torques."""
import dataclasses
import sys
from pathlib import Path
from types import SimpleNamespace

import jax
import mujoco
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from sim.train.walking import CenterPoseReset, ZbotWalkingTask, ZbotWalkingTaskConfig   # noqa: E402


def build(dt):
    assets = ROOT / "sim" / "assets" / "zbot-cad"
    fields = {f.name: f.default for f in dataclasses.fields(ZbotWalkingTaskConfig) if f.default is not dataclasses.MISSING}
    fields.update(robot_urdf_path=str(assets), actuator_params_path=str(assets / "actuators"), start_pose="center",
                  domain_randomize=False, dt=dt)
    task = object.__new__(ZbotWalkingTask)
    task.config = SimpleNamespace(**fields)
    m = task.get_mujoco_model()
    m.opt.timestep = dt
    return task, m


def cop_and_forward(m, d):
    """centre of pressure of all floor contacts (world x) and the world direction the toes point to"""
    fz = 0.0
    mx = 0.0
    for i in range(d.ncon):
        c = d.contact[i]
        f = np.zeros(6)
        mujoco.mj_contactForce(m, d, i, f)
        normal_force = f[0]
        fz += normal_force
        mx += normal_force * c.pos[0]
    return (mx / fz if fz > 1e-6 else float("nan")), fz


def main():
    torque_cap = 8.7
    print("K [Nm/rad] | dt  | after 3 s: tilt deg, base z | CoP x - CoM x (mm) | leg joint holding torque (Nm: hipP kneeP ankleP)")
    for K, D, dt in ((22.7, 26.0, 0.005), (200.0, 8.0, 0.001), (1000.0, 20.0, 0.001), (3000.0, 40.0, 0.001)):
        task, m = build(dt)
        d = mujoco.MjData(m)
        d.qpos[:] = m.qpos0
        d = CenterPoseReset.from_model(m, task.config.center_pose_deg)(d, 1.0, jax.random.PRNGKey(0))
        target = np.array(d.qpos[7:])
        mujoco.mj_forward(m, d)
        info = []
        for k in range(int(3.0 / dt)):
            tau = K * (target - d.qpos[7:]) - D * d.qvel[6:]
            d.ctrl[:] = np.clip(tau, -torque_cap, torque_cap)
            mujoco.mj_step(m, d)
        R = d.xmat[1].reshape(3, 3)
        tilt = np.degrees(np.arccos(np.clip(R[2, 2], -1, 1)))
        cop, fz = cop_and_forward(m, d)
        com = d.subtree_com[0][0]
        names = [mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, i) for i in range(1, m.njnt)]
        t = {n: float(d.ctrl[i]) for i, n in enumerate(names)}
        print("%9.0f  | %.3f | tilt %5.1f, z %.3f              | %+6.1f (Fz %.1f N)     | L %+.2f %+.2f %+.2f   R %+.2f %+.2f %+.2f" % (
            K, dt, tilt, d.qpos[2], 1000 * (cop - com) if np.isfinite(cop) else float("nan"), fz,
            t["left_hip_pitch"], t["left_knee_pitch"], t["left_ankle_pitch"],
            t["right_hip_pitch"], t["right_knee_pitch"], t["right_ankle_pitch"]))


if __name__ == "__main__":
    main()
