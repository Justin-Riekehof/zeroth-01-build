#!/usr/bin/env python3
"""Look at a sim model without any policy: render a 2x2 sheet (front/left/back/iso) of the standing pose, or open the
interactive MuJoCo viewer STATICALLY in the zero pose (orbit, inspect; joint sliders in the right panel move it);
--physics steps the simulation instead, with a holding spring on every joint.
Usage: python sim/tools/show_model.py <assets dir> [--out sheet.png] [--viewer] [--stiffness 15]"""
import argparse, os, time
import numpy as np, mujoco
from mujoco_scenes.mjcf import load_mjmodel

ap = argparse.ArgumentParser(); ap.add_argument("assets"); ap.add_argument("--out", default=None); ap.add_argument("--viewer", action="store_true")
ap.add_argument("--stiffness", type=float, default=15.0); ap.add_argument("--physics", action="store_true"); a = ap.parse_args()
m = load_mjmodel(os.path.join(a.assets, "robot.mjcf"), scene="smooth"); d = mujoco.MjData(m); mujoco.mj_forward(m, d)
if a.out:
    r = mujoco.Renderer(m, 480, 640); cam = mujoco.MjvCamera(); cam.type = mujoco.mjtCamera.mjCAMERA_FREE
    cam.lookat[:] = [0.0, 0.0, 0.22]; cam.distance = 0.95; imgs = []
    for az, el in ((180, -10), (90, -10), (0, -10), (135, -25)):   # front (looking at +x face), left side, back, iso
        cam.azimuth, cam.elevation = az, el; r.update_scene(d, cam); imgs.append(r.render().copy())
    sheet = np.vstack([np.hstack(imgs[:2]), np.hstack(imgs[2:])]); import imageio.v2 as iio; iio.imwrite(a.out, sheet); print("wrote", a.out)
if a.viewer:
    import mujoco.viewer
    # static by default: no physics, the model just sits in its zero pose (orbit with the mouse, joints via the
    # right-hand panel's "Joint" sliders). --physics steps the simulation with a holding spring on every joint.
    if a.physics:
        hinge = m.jnt_type == mujoco.mjtJoint.mjJNT_HINGE
        m.jnt_stiffness[hinge] = a.stiffness; m.dof_damping[m.jnt_dofadr[hinge]] = 0.03 * a.stiffness
    with mujoco.viewer.launch_passive(m, d) as v:
        v.cam.lookat[:] = [0, 0, 0.22]; v.cam.distance = 1.1; v.cam.azimuth = 150; v.cam.elevation = -15
        while v.is_running():
            t0 = time.time()
            if a.physics: mujoco.mj_step(m, d)
            else: mujoco.mj_forward(m, d)
            v.sync(); time.sleep(max(0.0, m.opt.timestep - (time.time() - t0)))
