"""Smoke test of the whole chain (task config -> model -> start pose -> servo-model actuator) in plain MuJoCo on the CPU.

    ~/Documents/stash/ksim-zbot/.venv/bin/python sim/tests/stand_check.py [legacy] dt=0.002   (ALWAYS give dt: the class default 0.005 is unstable)

The robot starts in the centre pose and the 'policy' just commands the centre pose. Prints base height and pitch over time."""
import os
import sys
from pathlib import Path

import jax
import jax.numpy as jnp
import mujoco
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from sim.train.walking import ZbotWalkingTask, ZbotWalkingTaskConfig   # noqa: E402

def main() -> None:
    legacy = "legacy" in sys.argv
    dt = next((float(a.split("=")[1]) for a in sys.argv if a.startswith("dt=")), None)
    assets = ROOT / "sim" / "assets" / os.environ.get("ASSETS", "zbot-cad")       # ASSETS=zbot-cad-tpu: TPU shoes
    # The task constructor starts xax's multiprocessing/logging machinery: build the object without it and give it
    # a plain namespace with the config defaults (only get_mujoco_model / get_actuators / get_resets are used).
    import dataclasses
    from types import SimpleNamespace

    fields = {f.name: f.default for f in dataclasses.fields(ZbotWalkingTaskConfig)
              if f.default is not dataclasses.MISSING}
    fields.update(robot_urdf_path=str(assets), actuator_params_path=str(assets / "actuators"),
                  servo_model=not legacy, start_pose="center", hip_yaw_range_deg=30.0, domain_randomize=False,
                  **({"dt": dt} if dt else {}))
    cfg = SimpleNamespace(**fields)
    task = object.__new__(ZbotWalkingTask)
    task.config = cfg
    m = task.get_mujoco_model()
    meta = task.get_mujoco_model_metadata(m)
    act = task.get_actuators(m, meta)
    print("actuator:", type(act).__name__)
    d = mujoco.MjData(m)
    d.qpos[:] = m.qpos0
    for r in task.get_resets(m)[:1]:
        d = r(d, 1.0, jax.random.PRNGKey(0))
    hold = np.array(d.qpos[7:])                      # command the centre pose
    mujoco.mj_forward(m, d)
    state = act.get_default_state(jnp.array(d.qpos[7:]), jnp.zeros(m.nq - 7))
    steps_per_ctrl = round(cfg.ctrl_dt / cfg.dt)
    print("dt %.4f ctrl_dt %.3f; hip_yaw ranges (deg):" % (cfg.dt, cfg.ctrl_dt),
          {mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, i): np.degrees(m.jnt_range[i]).round(0).tolist()
           for i in range(m.njnt) if (mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, i) or "").endswith("hip_yaw")})
    for k in range(int(3.0 / cfg.dt)):
        ctrl, state = act.get_stateful_ctrl(jnp.array(hold), d, state, jax.random.PRNGKey(k))
        d.ctrl[:] = np.array(ctrl)
        mujoco.mj_step(m, d)
        if k % int(0.5 / cfg.dt) == 0:
            R = d.xmat[1].reshape(3, 3)
            print("t=%.1f  base z %.3f  pitch %.1f deg  tilt %.1f deg" % (
                k * cfg.dt, d.qpos[2], np.degrees(np.arcsin(-R[2, 0])), np.degrees(np.arccos(np.clip(R[2, 2], -1, 1)))))


if __name__ == "__main__":
    main()
