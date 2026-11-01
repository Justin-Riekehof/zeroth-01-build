#!/usr/bin/env python3
"""Fit the servo setpoint model to a bench 'step' log: per servo type  delay, a_max, v_cap.

Model (what sim/train/common.py FeetechActuators implements): the goal jumps at t0; after `delay` the servo
follows a trapezoidal profile with  v = min(speed register, v_cap)  and acceleration a_max.

    .cad/bin/python sim/tools/bench_fit.py step_log.npz
"""
import itertools
import json
import sys

import numpy as np

TICK = 2 * np.pi / 4096
ARMS = {"left_shoulder_pitch", "left_shoulder_yaw", "left_elbow_yaw",
        "right_shoulder_pitch", "right_shoulder_yaw", "right_elbow_yaw"}


def trapezoid(t, d, v, a):
    """distance travelled after time t of a move of length d (>0), cruise speed v, accel a."""
    t_acc = v / a
    d_acc = 0.5 * a * t_acc ** 2
    if 2 * d_acc >= d:                                   # triangular: never reaches v
        t_half = np.sqrt(d / a)
        return np.where(t < t_half, 0.5 * a * t ** 2,
                        np.where(t < 2 * t_half, d - 0.5 * a * (2 * t_half - t) ** 2, d))
    t_cruise = (d - 2 * d_acc) / v
    return np.where(t < t_acc, 0.5 * a * t ** 2,
                    np.where(t < t_acc + t_cruise, d_acc + v * (t - t_acc),
                             np.where(t < 2 * t_acc + t_cruise, d - 0.5 * a * (2 * t_acc + t_cruise - t) ** 2, d)))


def collect(z, m):
    J, mv, t, pos, move = m["joints"], m["moves"], z["t"], z["pos"], z["move"].astype(int)
    out = {"arm": [], "leg": []}
    for mi, mm in enumerate(mv):
        if not mm["label"].endswith("out"):
            continue
        j = J.index(mm["joint"])
        sel = np.where(move == mi)[0]
        if len(sel) < 10:
            continue
        p0 = pos[sel[0] - 1, j] if sel[0] else pos[sel[0], j]
        # time axis relative to the previous sample: the goal is written right after it was read
        tt = t[sel] - t[sel[0] - 1 if sel[0] else sel[0]]
        d = (pos[sel, j] - p0) * TICK
        sgn = np.sign(d[np.argmax(np.abs(d))]) or 1.0
        out["arm" if mm["joint"] in ARMS else "leg"].append((tt, sgn * d, mm["speed"] * TICK, abs(mm["amp"]) * np.pi / 180))
    return out


def fit(moves, kind):
    delays = np.arange(0.0, 0.15, 0.01)
    accs = np.geomspace(3, 400, 40)
    caps = [np.inf] if kind == "leg" else np.arange(1.2, 4.0, 0.1)
    best = None
    for dl, a, cap in itertools.product(delays, accs, caps):
        e = 0.0
        for tt, d, v, amp in moves:
            pred = trapezoid(np.maximum(tt - dl, 0.0), amp, min(v, cap), a)
            e += np.mean((pred - d) ** 2)
        if best is None or e < best[0]:
            best = (e, dl, a, cap)
    rms = np.sqrt(best[0] / len(moves)) * 180 / np.pi
    return best[1], best[2], best[3], rms


if __name__ == "__main__":
    z = np.load(sys.argv[1])
    m = json.loads(str(z["meta"]))
    data = collect(z, m)
    for kind in ("leg", "arm"):
        dl, a, cap, rms = fit(data[kind], kind)
        print(f"{kind}: delay {dl * 1000:.0f} ms ({dl / 0.02:.1f} steps)  a_max {a:.0f} rad/s^2  "
              f"v_cap {'none (follows register)' if np.isinf(cap) else f'{cap:.2f} rad/s'}  rms {rms:.2f} deg  n={len(data[kind])}")
