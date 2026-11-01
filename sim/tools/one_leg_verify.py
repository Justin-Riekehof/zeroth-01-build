"""Play the planned one-leg poses in physics (torque-limited PD servos, rate-limited like the Pi) and report."""
import json
import sys

import numpy as np

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from stance_sim import *  # noqa

Y_OUT = -0.0392


def run(plan, speeds=(300, 300, 150), hold=(1.0, 1.0, 2.0, 3.0), acc=254, kp=KP, mass=1.0, quiet=False):
    sim = Sim(mass_scale=mass, kp=kp, right_sole=(Y_OUT, plan["y_inner_mm"] / 1000.0))
    pl = start_standing(sim)
    seq = [("step2", plan["step2"]), ("step3", plan["step3"]), ("step4", plan["step4"])]
    ok = True
    for (name, ang), sp, h in zip(seq, speeds, hold[1:]):
        ok = pl.move(ang, sp, acc, hold_s=h)
        last = pl.log[-1]
        if not quiet:
            print(f"{name}: ok={ok} {pl.fell or ''} tilt {last[1]:.1f} CoM(x,y) rel. sole {last[2]*1e3:.1f},{last[3]*1e3:.1f} mm "
                  f"load L/R {last[4]['Left']:.1f}/{last[4]['Right']:.1f} N")
        if not ok:
            break
    return ok, pl


if __name__ == "__main__":
    plan = json.load(open(sys.argv[1]))
    run(plan)
