"""Mirror the right-leg one-leg demo onto the LEFT leg and verify it (wide LEFT sole) in physics.

    python sim/tools/one_leg_mirror.py [--write] [dry_deg dra_deg]
"""
import json
import sys
from multiprocessing import Pool

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from stance_sim import *  # noqa

Y_OUT_L, Y_IN_L = 0.0403, -0.060          # mirror of the right sole (outer = foot + wall, inner 60 mm past the ankle axis)


def mirror(angles):
    out = {}
    for j, v in angles.items():
        if j.startswith("right_"):
            out["left_" + j[6:]] = -v if any(k in j for k in ("hip", "knee", "ankle")) else v
        elif j.startswith("left_"):
            out["right_" + j[5:]] = -v if any(k in j for k in ("hip", "knee", "ankle")) else v
    return out


def mirrored_demo(src, dry=0.0, dra=0.0):
    d = json.loads(json.dumps(src))
    d["name"] = "one_leg_left"
    d["description"] = src["description"].replace("RIGHT leg", "LEFT leg").replace("right sole", "LEFT sole") \
        + " (mirror of one_leg_stand; wide sole under the LEFT foot)."
    lim = json.loads((ROOT / "hardware/joint_limits.json").read_text())
    for st in d["steps"]:
        st["angles"] = {k: round(min(lim[k]["max_deg"], max(lim[k]["min_deg"], v)), 1) for k, v in mirror(st["angles"]).items()}
        st["title"] = st["title"].replace("right", "@R").replace("left", "right").replace("@R", "left")
        if st["title"][0] in "345" and not st.get("center"):
            st["angles"]["left_hip_yaw"] = round(st["angles"]["left_hip_yaw"] - dry, 1)
            st["angles"]["left_ankle_pitch"] = round(st["angles"]["left_ankle_pitch"] - dra, 1)
    return d


def play(a):
    demo, kp, m, sp_scale = a
    sim = Sim(kp=kp, kd=kp / 50, mass_scale=m, left_sole=(Y_OUT_L, Y_IN_L))
    pl = start_standing(sim, stance="Left")
    for st in demo["steps"]:
        ang = center_pose() if st.get("center") else st["angles"]
        if not pl.move(ang, st["speed"], st["acc"], hold_s=st["pause_s"]):
            return a[1:], False, st["title"]
    r = pl.log[-1]
    c = sole_xy_world(sim, "Left")
    ok = abs(c[0]) < 0.06 and abs(c[1]) < 0.05 and r[4]["Right"] < 0.5
    return a[1:], ok, (round(c[0] * 1e3), round(c[1] * 1e3), round(r[1], 1))


if __name__ == "__main__":
    src = json.load(open(ROOT / "demos/one_leg_stand.json"))
    dry = float(sys.argv[-2]) if len(sys.argv) > 2 and sys.argv[-2].lstrip("-").replace(".", "").isdigit() else 0.0
    dra = float(sys.argv[-1]) if dry or sys.argv[-1].lstrip("-").replace(".", "").isdigit() else 0.0
    demo = mirrored_demo(src, dry, dra)
    lim = json.loads((ROOT / "hardware/joint_limits.json").read_text())
    for st in demo["steps"]:
        for j, v in st["angles"].items():
            assert lim[j]["min_deg"] <= v <= lim[j]["max_deg"], (st["title"], j, v)
    with Pool(9) as p:
        res = p.map(play, [(demo, kp, m, 1) for kp in (30, 60, 120) for m in (0.9, 1.0, 1.1)])
    for r in res:
        print("kp,mass", r[0][:2], "OK" if r[1] else "FAIL", r[2])
    if "--write" in sys.argv and all(r[1] for r in res):
        (ROOT / "demos/one_leg_left.json").write_text(json.dumps(demo, indent=1, sort_keys=True) + "\n")
        print("written demos/one_leg_left.json")
