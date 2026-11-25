#!/usr/bin/env python3
"""Hardware gate: does a policy respect what the real robot can take?  Reads a rollout dataset (eval_policy.sh).

    .cad/bin/python sim/tools/hardware_gate.py <rollouts.ds> [--json out.json]      exit code 0 = every limit respected

Every criterion is a measurement on the rollouts (16 argmax episodes with randomisation and pushes). The thresholds are
the project's choice, from what the hardware tests of 2026-10-22/25 showed - change them HERE, nowhere else:

  falls              no episode ends in a fall
  target_in_limits   the commanded targets stay inside the real joint limits (hardware/joint_limits.json): the Pi clamps
                     them there, so a target outside means the real robot would behave differently from the sim
  joint_margin       the joints themselves stay MARGIN_DEG away from those limits (no riding the hard stop; the
                     2026-10-22 failure was a hip-yaw bracket at its stop); at most half the distance from the zero pose
                     to the limit, since the hip-yaw limits sit only 3 / 5 deg from zero
  servo_speed        measured joint speed p99 <= the servo limit (legs: speed register 2000 = 3.07 rad/s, arms 1.8)
                     and at most 2 % of the steps with any joint more than 10 % over its limit
  speed_buffer       at most 20 % of the joint-steps above 85 % of the limit: the servos must not live at their limit
                     (a saturated servo stops following the target proportionally; sim and hardware part ways there)
  target_gap         the commanded target stays near the joint: mean |action - q| and its p99 (a far target drives the
                     servo at full speed / full duty)
  action_rate        calm commands: mean and p99 of |action(t) - action(t-1)| per 20 ms step
  saturation         share of |action| > 0.95 (tanh outputs pinned at +-1 = bang-bang)
  tracking           mean forward speed >= 75 % of the mean commanded speed
  jitter             p99 of the second difference of the SENT targets <= 0.04 rad/step^2 (the zig-zag a servo sees; 0.086 on the
                     first calm runs) and at most 15 % of the leg joint-angle spectrum above 5 Hz (0.35 there)
  limiter_share      runs trained with a command rate limiter (cmd_rate_fraction > 0): the gap/rate criteria are judged
                     on the targets that are actually SENT (clamped + rate limited, like the Pi does), and at most 20 %
                     of the joint-steps may ask for more than the limiter lets through

    --config <run>/config.yaml   (calm_watch.py passes it) enables the limiter-aware evaluation
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
MARGIN_DEG = 5.0
LEG_SPEED, ARM_SPEED, SPEED_TOL, OVER_TOL, BUFFER = 3.07, 1.8, 1.00, 1.10, 0.85
THRESH = {"falls": 0, "target_out_share": 0.01, "margin_share": 0.01, "speed_leg_p99": LEG_SPEED * SPEED_TOL,
          "speed_arm_p99": ARM_SPEED * SPEED_TOL, "gap_mean": 0.15, "gap_p99": 0.6, "rate_mean": 0.10,
          "rate_p99": 0.35, "saturation_share": 0.01, "tracking_ratio": 0.5, "speed_over_share": 0.02, "speed_buffer_share": 0.20, "limiter_share": 0.20,
          "jerk_p99": 0.04, "highfreq_share": 0.15, "tracking_ratio_max": 2.0, "zero_cmd_drift_abs": 0.02,
          "foot_tilt_over5_share": 0.30, "lateral_ratio": 0.25}
# lateral_ratio (25.11.2026): median over the episodes of |sideways| / forward base displacement. The goal is walking
# STRAIGHT; servo_rubber23 had 0.15 on the stiff sim model and 0.74 with joint play/elasticity (joint_compliance)
# tracking 0.5-2.0 (was 0.75-1.3): user 2026-11-06 "Soll und Ist-Tempo ist gar nicht die Prio. Wichtig ist, dass der
# Roboter vorwärts kommt, stabil, ohne Zittern und mit Sohlen parallel zum Boden" - forward, yes; the exact speed, no
LEGS = ("hip", "knee", "ankle")


def joint_order():
    return json.load(open(ROOT / "sim/policies/cad2_v13_tiny_step905/policy_meta.json"))["joint_order"]


def real_limits(J):
    d = json.load(open(ROOT / "hardware/joint_limits.json"))
    return (np.radians([d[j]["min_deg"] for j in J]), np.radians([d[j]["max_deg"] for j in J]))


def load(path):
    p = Path(path)
    m = json.load(open(p.with_suffix(".meta.json")))
    fp = np.memmap(p, dtype=np.float32, mode="r", shape=(m["num_samples"], m["total_size"]))
    cols, off = {}, 0
    for n, sh in zip(m["names"], m["shapes"]):
        s = int(np.prod(sh)); cols[n] = (off, s, tuple(sh)); off += s
    g = lambda n: np.asarray(fp[:, cols[n][0]:cols[n][0] + cols[n][1]]).reshape((m["num_samples"],) + cols[n][2])
    valid = np.abs(g("timestep")).sum(1) > 0
    keys = ("qpos", "qvel", "action", "done", "xpos", "command.linear_velocity_command")
    out = {k: g(k)[valid] for k in keys}
    if "obs.feet_contact_observation" in cols:
        out["contact"] = g("obs.feet_contact_observation")[valid]
    if "xquat" in cols:
        out["xquat"] = g("xquat")[valid]
    return out


def foot_bodies() -> tuple[int, int]:
    import mujoco
    from mujoco_scenes.mjcf import load_mjmodel                     # the contact pairs need the scene's floor
    mm = load_mjmodel(str(ROOT / "sim/assets/zbot-cad/robot.mjcf"), scene="smooth")
    return tuple(mujoco.mj_name2id(mm, mujoco.mjtObj.mjOBJ_BODY, f"{s}_ankle_pitch_link") for s in ("left", "right"))


def foot_tilt(xquat: np.ndarray, contact: np.ndarray) -> dict:
    """Tilt of the feet while on the floor (deg): median and share > 5 deg. servo_ctrl_v9: median 9 deg, 80 % > 5 deg -
    standing on the sole's edges, which the real robot cannot (its flat strip is 1.7 cm wide)."""
    try:
        bodies = foot_bodies()
    except Exception:
        return {}
    q = xquat[:, :, list(bodies), :]
    tilt = np.degrees(np.arccos(np.clip(1 - 2 * (q[..., 1] ** 2 + q[..., 2] ** 2), -1, 1)))
    on = contact > 0.5
    if not on.any():
        return {}
    return {"foot_tilt_median_deg": float(np.median(tilt[on])), "foot_tilt_over5_share": float((tilt[on] > 5).mean())}


def swing_stats(contact: np.ndarray, dt: float = 0.02, real: float = 0.2) -> dict:
    """Swings (foot off the ground) per foot: how many per second and which share lasts >= `real` s. Every policy up
    to servo_ctrl_v6 moved by micro-hops: 90-95 % of the swings < 0.1 s, none >= 0.2 s (2026-10-28)."""
    lens = []
    for ep in contact > 0.5:
        for foot in ep.T:
            run = 0
            for c in foot:
                if not c:
                    run += 1
                elif run:
                    lens.append(run); run = 0
    lens = np.asarray(lens, float) * dt
    secs = contact.shape[0] * contact.shape[1] * dt * 2
    return {"swings_per_s_foot": float(len(lens) / max(secs, 1e-9)),
            "real_step_share": float((lens >= real).mean()) if len(lens) else 0.0}


def run_config(path) -> dict:
    """scalar keys of a run's config.yaml"""
    out = {}
    for line in Path(path).read_text().splitlines():
        if ":" in line and not line.startswith((" ", "-")):
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def sent_targets(a, q0, lo, hi, step, alpha=0.0):
    """the targets the Pi sends: low-pass (alpha, 0 = off), clamp to the limits, then move at most `step` (rad per
    control step) per step"""
    s = np.empty_like(a)
    prev = q0.copy()
    filt = q0.copy()
    for t in range(a.shape[1]):
        filt = a[:, t] if alpha <= 0 else filt + alpha * (a[:, t] - filt)
        prev = prev + np.clip(np.clip(filt, lo, hi) - prev, -step, step)
        s[:, t] = prev
    return s


def metrics(path, cfg=None):
    J = joint_order()
    legs = [i for i, j in enumerate(J) if any(k in j for k in LEGS)]
    arms = [i for i in range(len(J)) if i not in legs]
    d = load(path)
    fell = d["done"].astype(bool).any(1)
    ok = ~fell
    a, q, qd = d["action"], d["qpos"][:, :, 7:], d["qvel"][:, :, 6:]
    lo, hi = real_limits(J)
    m = {"falls": int(fell.sum()), "episodes": int(len(fell))}
    if ok.sum() == 0:
        return m | {"error": "every episode fell"}
    a, q, qd = a[ok], q[ok], qd[ok]
    m["target_out_share"] = float(((a < lo - 1e-3) | (a > hi + 1e-3)).any(-1).mean())
    dist = np.minimum(q - lo, hi - q)
    # per joint MARGIN_DEG, but at most half the zero-pose distance to the limit (hip yaw: limits 3 / 5 deg from zero)
    to_zero = np.minimum(-lo, hi)
    margin = np.where(to_zero > 0, np.minimum(np.radians(MARGIN_DEG), 0.5 * to_zero), np.radians(MARGIN_DEG))
    m["margin_share"] = float((dist < margin).any(-1).mean())
    m["speed_leg_p99"] = float(np.percentile(np.abs(qd[:, :, legs]), 99))
    m["speed_arm_p99"] = float(np.percentile(np.abs(qd[:, :, arms]), 99))
    vlim = np.full(len(J), LEG_SPEED); vlim[arms] = ARM_SPEED
    m["speed_over_share"] = float((np.abs(qd) > vlim * OVER_TOL).any(-1).mean())
    m["speed_buffer_share"] = float((np.abs(qd) > vlim * BUFFER).mean())
    frac = float((cfg or {}).get("cmd_rate_fraction", 0) or 0)
    sent = a
    if frac > 0:
        vlim_cmd = np.full(len(J), float(cfg.get("leg_servo_speed", 2000)) * 2 * np.pi / 4096)
        vlim_cmd[arms] = float(cfg.get("arm_v_max", ARM_SPEED))
        step = frac * vlim_cmd * float(cfg.get("ctrl_dt", 0.02))
        alpha = float(cfg.get("action_filter_alpha", 0) or 0)
        sent = sent_targets(a, q[:, 0], lo, hi, step, alpha)
        prev = np.concatenate([q[:, :1], sent[:, :-1]], axis=1)
        m["limiter_share"] = float((np.abs(np.clip(a, lo, hi) - prev) > step + 1e-6).mean())
    m["jerk_p99"] = float(np.percentile(np.abs(np.diff(sent, n=2, axis=1)), 99))
    x = q[:, :, legs] - q[:, :, legs].mean(1, keepdims=True)
    sp = np.abs(np.fft.rfft(x, axis=1)).mean((0, 2))
    fr = np.fft.rfftfreq(x.shape[1], 0.02)
    m["highfreq_share"] = float(sp[fr > 5].sum() / max(sp[1:].sum(), 1e-9))
    gap = np.abs(sent - q)
    m["gap_mean"], m["gap_p99"] = float(gap.mean()), float(np.percentile(gap, 99))
    da = np.abs(np.diff(sent, axis=1))
    m["rate_mean"], m["rate_p99"] = float(da.mean()), float(np.percentile(da, 99))
    m["saturation_share"] = float((np.abs(a) > 0.95).mean())
    # forward speed over the steps that COMMAND forward motion only: with a share of zero commands (speed curriculum,
    # 2026-10-29) the old whole-episode ratio divided a few cm of drift by a tiny mean command and swung to +3 / -3.7
    cmd = d["command.linear_velocity_command"][ok][:, :, 0]
    if d["xpos"].ndim == 4:
        v = np.diff(d["xpos"][ok][:, :, 1, 0], axis=1) / 0.02
        c = cmd[:, 1:]; fwd = c > 1e-3
        m["tracking_ratio"] = float(v[fwd].mean() / c[fwd].mean()) if fwd.any() else float("nan")
        if (~fwd).any():
            m["zero_cmd_drift_mps"] = float(v[~fwd].mean())
        base = d["xpos"][ok][:, :, 1, :2]
        dx, dy = base[:, -1, 0] - base[:, 0, 0], base[:, -1, 1] - base[:, 0, 1]
        go = fwd.any(1) & (dx > 0.02)                  # episodes that were told to walk and did get somewhere
        if go.any():
            m["lateral_ratio"] = float(np.median(np.abs(dy[go]) / dx[go]))
    else:
        m["tracking_ratio"] = float("nan")
    if "contact" in d:
        m.update(swing_stats(d["contact"][ok]))     # reported, not (yet) a criterion
        if "xquat" in d:
            m.update(foot_tilt(d["xquat"][ok], d["contact"][ok]))
    m["hip_yaw_deg"] = {n: [float(np.degrees(q[:, :, J.index(n)].min())), float(np.degrees(q[:, :, J.index(n)].max()))]
                        for n in ("left_hip_yaw", "right_hip_yaw")}
    return m


def verdict(m):
    """list of (criterion, value, threshold, passed, 'lower is better' margin 0..1+) """
    if "error" in m:
        return [("falls", m["falls"], 0, False, 9.9)]
    rows = [("falls", m["falls"], THRESH["falls"], m["falls"] <= THRESH["falls"])]
    for k in ("target_out_share", "margin_share", "speed_leg_p99", "speed_arm_p99", "speed_over_share", "speed_buffer_share", "gap_mean", "gap_p99", "rate_mean",
              "rate_p99", "saturation_share", "jerk_p99", "highfreq_share"):
        rows.append((k, m[k], THRESH[k], m[k] <= THRESH[k]))
    if "limiter_share" in m:
        rows.append(("limiter_share", m["limiter_share"], THRESH["limiter_share"], m["limiter_share"] <= THRESH["limiter_share"]))
    t = m["tracking_ratio"]
    if np.isfinite(t):          # NaN = no forward command at all (stage 0: stepping on the spot) - nothing to track
        rows.append(("tracking_ratio", t, THRESH["tracking_ratio"], bool(t >= THRESH["tracking_ratio"])))
        rows.append(("tracking_ratio_max", t, THRESH["tracking_ratio_max"], bool(t <= THRESH["tracking_ratio_max"])))
    # both ignored the command before (servo_tpu1: 7 cm/s at every command, also at 0) and the score could not see it
    if "zero_cmd_drift_mps" in m:
        d0 = abs(m["zero_cmd_drift_mps"])
        rows.append(("zero_cmd_drift_abs", d0, THRESH["zero_cmd_drift_abs"], bool(d0 <= THRESH["zero_cmd_drift_abs"])))
    if "lateral_ratio" in m:
        lr = m["lateral_ratio"]
        rows.append(("lateral_ratio", lr, THRESH["lateral_ratio"], bool(lr <= THRESH["lateral_ratio"])))
    if "foot_tilt_over5_share" in m:
        ft = m["foot_tilt_over5_share"]
        rows.append(("foot_tilt_over5_share", ft, THRESH["foot_tilt_over5_share"], bool(ft <= THRESH["foot_tilt_over5_share"])))
    out = []
    for k, v, th, ok in rows:
        over = 0.0 if ok else (abs(v - th) / max(abs(th), 1e-6) if k != "falls" else float(v))
        out.append((k, v, th, ok, over))
    return out


def score(m):
    """0..1, higher = closer to passing everything (used for the stagnation check)"""
    v = verdict(m)
    return float(np.mean([1.0 / (1.0 + o) for *_, o in v]))


def main(path, json_out=None, cfg_path=None):
    m = metrics(path, run_config(cfg_path) if cfg_path else None)
    v = verdict(m)
    for k, val, th, ok, _ in v:
        print("%-18s %10.4f   limit %-7.3f  %s" % (k, val, th, "ok" if ok else "FAIL"))
    if "hip_yaw_deg" in m:
        print("hip yaw range seen (deg):", {k: [round(x) for x in r] for k, r in m["hip_yaw_deg"].items()})
    allok = all(ok for _, _, _, ok, _ in v)
    print("GATE:", "PASSED" if allok else "not passed", " score %.3f" % score(m))
    if json_out:
        json.dump({"metrics": m, "passed": allok, "score": score(m)}, open(json_out, "w"), indent=1)
    return 0 if allok else 1


if __name__ == "__main__":
    args = sys.argv[1:]
    out = args[args.index("--json") + 1] if "--json" in args else None
    cfgp = args[args.index("--config") + 1] if "--config" in args else None
    sys.exit(main(args[0], out, cfgp))
