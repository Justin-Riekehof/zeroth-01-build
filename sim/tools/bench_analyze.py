#!/usr/bin/env python3
"""Evaluate servo bench logs (src/pi_service/bench.py, GET /bench/logs/<name>).

    .cad/bin/python sim/tools/bench_analyze.py step_log.npz     # one joint at a time: servo dynamics
    .cad/bin/python sim/tools/bench_analyze.py rect_log.npz     # all joints together: pack voltage vs speed

Notes: the status block of the servos has isolated bad samples (temperature 54..137 C between ~30 C readings),
so voltage uses the median over the servos of each step, temperature a median filter.
"""
import json
import sys

import numpy as np

TICK_DEG = 360 / 4096
ARMS = {"left_shoulder_pitch", "left_shoulder_yaw", "left_elbow_yaw",
        "right_shoulder_pitch", "right_shoulder_yaw", "right_elbow_yaw"}      # STS3215; the rest STS3250


def load(path):
    z = np.load(path)
    return z, json.loads(str(z["meta"]))


def step(z, m):
    J, mv, t, pos, load_, move = m["joints"], m["moves"], z["t"], z["pos"], z["load"], z["move"].astype(int)
    rows = []
    for mi, mm in enumerate(mv):
        if not mm["label"].endswith("out"):
            continue
        j = J.index(mm["joint"])
        sel = np.where(move == mi)[0]
        if len(sel) < 10:
            continue
        p, tt = pos[sel, j], t[sel] - t[sel][0]
        p0 = pos[sel[0] - 1, j] if sel[0] else p[0]
        amp = mm["amp"] / TICK_DEG
        d = np.abs(p - p0)
        td = tt[np.argmax(d > 3)] if (d > 3).any() else np.nan
        v = np.abs(p[4:] - p[:-4]) / (tt[4:] - tt[:-4] + 1e-9)
        t10 = tt[np.argmax(d > 0.1 * amp)] if (d > 0.1 * amp).any() else np.nan
        t90 = tt[np.argmax(d > 0.9 * amp)] if (d > 0.9 * amp).any() else np.nan
        rows.append((mm["joint"] in ARMS, mm["speed"], round(mm["amp"]), td, np.percentile(v, 95), t90 - t10,
                     np.median(d[-5:]) / amp, np.abs(load_[sel, j]).max(), z["volt"][sel].min()))
    r = np.array(rows, float)
    print("type  speed amp | dead[ms] vpeak[ticks/s] vpeak/cmd  t10-90[ms] reached% max|load|")
    for arm in (1, 0):
        for sp in sorted(set(r[:, 1])):
            for am in sorted(set(r[:, 2])):
                q = r[(r[:, 0] == arm) & (r[:, 1] == sp) & (r[:, 2] == am)]
                if len(q):
                    md = np.nanmedian(q, axis=0)
                    print("%-4s %5d %3d | %6.0f %9.0f %9.2f %9.0f %8.0f %7.0f" % (
                        "arm" if arm else "leg", sp, am, md[3] * 1000, md[4], md[4] / sp, md[5] * 1000,
                        md[6] * 100, md[7]))


def rect(z, m):
    J, mv, move = m["joints"], m["moves"], z["move"].astype(int)
    vm = np.median(z["volt"], axis=1)
    speeds = sorted({x["speed"] for x in mv})
    print("speed | rest V | min V | sag from rest")
    for sp in speeds:
        idx = [i for i, x in enumerate(mv) if f"@{sp} " in x["label"]]
        rest = [i for i in idx if mv[i]["label"].endswith("rest")][0]
        base = np.median(vm[move == rest][-25:])
        cyc = np.isin(move, [i for i in idx if "cycle" in mv[i]["label"]])
        print("%5d | %5.2f  | %5.2f | %4.2f V" % (sp, base, vm[cyc].min(), base - vm[cyc].min()))


if __name__ == "__main__":
    z, m = load(sys.argv[1])
    print(m["test"], "steps", len(z["t"]), "stop:", m["stop_reason"])
    (step if m["test"] == "step" else rect)(z, m)
