"""Render demos/one_leg_stand.json from the physics playback: contact sheet (PNG) + video (MP4)."""
import json
import os
import sys

os.environ.setdefault("MUJOCO_GL", "egl")
import mujoco
import numpy as np

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from stance_sim import *  # noqa

Y_OUT, Y_IN = -0.0392, 0.060


def main(out_png, out_mp4):
    demo = json.load(open(ROOT / "demos/one_leg_stand.json"))
    sim = Sim(kp=60, kd=1.2, right_sole=(Y_OUT, Y_IN))
    # make the wide right sole visible
    g = sim.feet["Right"][0]
    sim.m.geom_rgba[g] = [0.95, 0.55, 0.1, 1]
    sim.m.geom_group[g] = 0
    for gg in range(sim.m.ngeom):
        if sim.m.geom_group[gg] == 3 and gg != g:
            sim.m.geom_rgba[gg] = [0, 0, 0, 0]
    ren = mujoco.Renderer(sim.m, 480, 600)
    cam = mujoco.MjvCamera(); cam.type = mujoco.mjtCamera.mjCAMERA_FREE
    cam.distance, cam.azimuth, cam.elevation = 1.1, 150, -12
    opt = mujoco.MjvOption(); opt.geomgroup[:] = [1, 1, 1, 1, 0, 0]
    frames, sheet = [], []
    pl = start_standing(sim)
    orig_step = sim.step
    t = [0]

    def grab():
        cam.lookat[:] = [sim.d.qpos[0], sim.d.qpos[1] - 0.0, 0.2]
        ren.update_scene(sim.d, cam, opt)
        return ren.render().copy()

    def step(n=1):
        orig_step(n); t[0] += n
        if t[0] % 40 == 0:
            frames.append(grab())
    sim.step = step
    for st in demo["steps"]:
        ang = center_pose() if st.get("center") else st["angles"]
        pl.move(ang, st["speed"], st["acc"], hold_s=st["pause_s"])
        sheet.append((st["title"], grab()))
    import imageio.v2 as imageio
    imageio.mimsave(out_mp4, frames, fps=25)
    from PIL import Image, ImageDraw
    w, h = sheet[0][1].shape[1], sheet[0][1].shape[0]
    cols = 4; rows = (len(sheet) + cols - 1) // cols
    img = Image.new("RGB", (w * cols, h * rows), "white")
    for i, (title, fr) in enumerate(sheet):
        im = Image.fromarray(fr); ImageDraw.Draw(im).text((8, 8), title[:60], fill=(255, 255, 255))
        img.paste(im, ((i % cols) * w, (i // cols) * h))
    img.save(out_png)
    print("frames", len(frames))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
