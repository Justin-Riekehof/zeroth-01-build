"""Write demos/one_leg_stand.json from a planned/verified pose set and re-verify the SAVED file in physics.

    python sim/tools/one_leg_demo.py <plan.json> [--write]
"""
import json
import sys
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from stance_sim import *  # noqa

Y_OUT = -0.0392
ALL = ["left_ankle_pitch", "left_elbow_yaw", "left_hip_pitch", "left_hip_roll", "left_hip_yaw", "left_knee_pitch",
       "left_shoulder_pitch", "left_shoulder_yaw", "right_ankle_pitch", "right_elbow_yaw", "right_hip_pitch",
       "right_hip_roll", "right_hip_yaw", "right_knee_pitch", "right_shoulder_pitch", "right_shoulder_yaw"]
SPEED, ACC = 150, 50


def step(title, ang=None, center=False, pause=1.0, speed=SPEED):
    angles = {j: 0.0 for j in ALL}
    if ang:
        angles.update({k: round(float(v), 1) for k, v in ang.items()})
    return dict(title=title, angles=angles, center=center, speed=speed, acc=ACC, pause_s=pause,
                boost=False, settle=False, stagger=None)


def build(plan):
    steps = [step("1 center", center=True, pause=1.5),
             step("2 right leg bent, lean right (both feet down)", plan["step2"]),
             step("3 all weight on the right leg, left foot up", plan["step3"], pause=2.0)]
    for i, a in enumerate(plan["ext"], 1):
        steps.append(step(f"4.{i} extend the right leg (still on one leg)", a, pause=1.0 if i < len(plan["ext"]) else 3.0, speed=100))
    desc = ("ONE-LEG STAND on the RIGHT leg. Only works with a wide flat right sole: "
            f"outer edge at the printed foot (+1.6 mm wall), inner edge {plan['y_inner_mm']:.0f} mm beyond the ankle axis towards the body centre "
            "(sim/tools/one_leg_plan.py). Planned and verified in simulation only (sim/tools/one_leg_demo.py); "
            "with the standard narrow foot the robot falls. Test with the robot held/hanging first.")
    return dict(description=desc, name="one_leg_stand", steps=steps)


def play_saved(args):
    demo, y_in, kp, mass = args
    sim = Sim(kp=kp, kd=kp / 50, mass_scale=mass, right_sole=(Y_OUT, y_in / 1000))
    pl = start_standing(sim)
    for st in demo["steps"]:
        ang = center_pose() if st.get("center") else st["angles"]
        if not pl.move(ang, st["speed"], st["acc"], hold_s=st["pause_s"]):
            return args[2:], False, st["title"]
    r = pl.log[-1]
    ok = abs(r[2]) < 0.06 and abs(r[3]) < 0.05 and r[4]["Left"] < 0.5
    return args[2:], ok, (round(r[2] * 1e3), round(r[3] * 1e3), round(r[1], 1))


if __name__ == "__main__":
    plan = json.load(open(sys.argv[1]))
    demo = build(plan)
    lim = json.loads((ROOT / "hardware/joint_limits.json").read_text())
    for st in demo["steps"]:
        for j, v in st["angles"].items():
            assert lim[j]["min_deg"] <= v <= lim[j]["max_deg"], (st["title"], j, v)
    if "--write" in sys.argv:
        (ROOT / "demos/one_leg_stand.json").write_text(json.dumps(demo, indent=1, sort_keys=True) + "\n")
        print("written demos/one_leg_stand.json")
    saved = json.load(open(ROOT / "demos/one_leg_stand.json")) if "--write" in sys.argv else demo
    with Pool(9) as p:
        res = p.map(play_saved, [(saved, plan["y_inner_mm"], kp, m) for kp in (30, 60, 120) for m in (0.9, 1.0, 1.1)])
    for r in res:
        print("kp,mass", r[0], "OK" if r[1] else "FAIL", r[2])
