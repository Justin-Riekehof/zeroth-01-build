"""Gait check on a ksim TrajectoryDataset: does the robot actually step (alternating swing phases),
or does it shuffle/skate? Uses feet_contact_observation (2) and feet_position_observation (6: L xyz, R xyz).
Usage: python gait_analyze.py <dataset file>"""
import sys, json, numpy as np
from pathlib import Path
p = Path(sys.argv[1]); meta = json.load(open(p.with_suffix(".meta.json")))
fp = np.memmap(p, dtype=np.float32, mode="r", shape=(meta["num_samples"], meta["total_size"]))
cols = {}; off = 0
for name, shape in zip(meta["names"], meta["shapes"]):
    size = int(np.prod(shape)); cols[name] = (off, size, tuple(shape)); off += size
def get(name):
    o, s, sh = cols[name]; return np.asarray(fp[:, o:o + s]).reshape((meta["num_samples"],) + sh)
ts = get("timestep"); valid = np.abs(ts).sum(1) > 0
c = get("obs.feet_contact_observation")[valid] > 0.5          # (n, T, 2)
fpz = get("obs.feet_position_observation")[valid].reshape(c.shape[0], c.shape[1], 2, 3)[..., 2]
n, T = c.shape[:2]; dt = float(ts[valid][0, 1] - ts[valid][0, 0])
single = (c.sum(2) == 1).mean(1); double = (c.sum(2) == 2).mean(1); flight = (c.sum(2) == 0).mean(1)
lift = (~c[:, 1:] & c[:, :-1]).sum(1)                         # contact -> swing transitions per foot
swing_len = []
for i in range(n):
    for f in range(2):
        s = ~c[i, :, f]; runs = np.diff(np.flatnonzero(np.diff(np.r_[0, s.astype(int), 0])))[::2]
        swing_len += list(runs * dt)
swing_len = np.array(swing_len) if swing_len else np.zeros(1)
clear = (fpz - fpz.min(1, keepdims=True)).max(1)              # max foot lift above its lowest z per episode
print(f"envs {n}, horizon {T*dt:.1f} s")
print(f"steps per foot per episode: L {lift[:,0].mean():.1f}  R {lift[:,1].mean():.1f}  (cadence {(lift.sum(1).mean()/(T*dt)):.2f} steps/s)")
print(f"support phases: single {single.mean()*100:.0f} %  double {double.mean()*100:.0f} %  flight {flight.mean()*100:.0f} %")
print(f"swing duration: median {np.median(swing_len)*1000:.0f} ms, p90 {np.percentile(swing_len,90)*1000:.0f} ms")
print(f"foot clearance (max lift): L {clear[:,0].mean()*100:.1f} cm  R {clear[:,1].mean()*100:.1f} cm")
# calmness: torso roll/pitch swing, lateral base velocity, joint excursions (zbot-cad joint order: 0-5 arms, 6-10 right leg
# [hip_pitch, hip_yaw, hip_roll, knee, ankle], 11-15 left leg) and action rate
qpos = get("qpos")[valid]; qvel = get("qvel")[valid]; act = get("action")[valid]
q = qpos[:, :, 3:7]
roll = np.degrees(np.arctan2(2 * (q[..., 0] * q[..., 1] + q[..., 2] * q[..., 3]), 1 - 2 * (q[..., 1] ** 2 + q[..., 2] ** 2)))
pitch = np.degrees(np.arcsin(np.clip(2 * (q[..., 0] * q[..., 2] - q[..., 3] * q[..., 1]), -1, 1)))
jq = np.degrees(qpos[:, :, 7:]); jv = qvel[:, :, 6:]
hip_ab = jq[:, :, [7, 8, 12, 13]]; arms = jq[:, :, 0:6]
print(f"calmness: torso roll p2p {np.percentile(roll.max(1)-roll.min(1),50):.1f} deg, pitch p2p {np.percentile(pitch.max(1)-pitch.min(1),50):.1f} deg;  lateral base vel RMS {np.sqrt((qvel[:,:,1]**2).mean()):.3f} m/s")
print(f"          hip yaw/roll |q| mean {np.abs(hip_ab).mean():.1f} deg (p2p {np.percentile(hip_ab.max(1)-hip_ab.min(1),50):.1f});  arms |q| mean {np.abs(arms).mean():.1f} deg;  joint speed mean {np.abs(jv).mean():.2f} rad/s;  action rate mean {np.abs(np.diff(act,axis=1)).mean():.3f} rad/step")
