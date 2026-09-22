"""Analyse a ksim TrajectoryDataset (memmap + .meta.json): forward displacement, speed, height, falls.
Usage: python eval_analyze.py <dataset file>"""
import sys, json, numpy as np
from pathlib import Path
p = Path(sys.argv[1]); meta = json.load(open(p.with_suffix(".meta.json")))
fp = np.memmap(p, dtype=np.float32, mode="r", shape=(meta["num_samples"], meta["total_size"]))
cols = {}; off = 0
for name, shape in zip(meta["names"], meta["shapes"]):
    size = int(np.prod(shape)); cols[name] = (off, size, tuple(shape)); off += size
def get(name):
    o, s, sh = cols[name]; return np.asarray(fp[:, o:o + s]).reshape((meta["num_samples"],) + sh)
qpos, qvel, done, ts = get("qpos"), get("qvel"), get("done"), get("timestep")
valid = np.abs(ts).sum(1) > 0            # the writer may leave unused rows zero-filled
qpos, qvel, done, ts = qpos[valid], qvel[valid], done[valid], ts[valid]
n, T = qpos.shape[0], qpos.shape[1]; dt = float(ts[0, 1] - ts[0, 0]) if T > 1 else 0.02
# forward = +x in the sim world; robot spawns facing +x
dx = qpos[:, -1, 0] - qpos[:, 0, 0]; dy = qpos[:, -1, 1] - qpos[:, 0, 1]
vx = qvel[:, :, 0].mean(1); z = qpos[:, :, 2]; fell = done.astype(bool).any(1)
# heading drift: yaw from the base quaternion (w,x,y,z) at the end
q = qpos[:, -1, 3:7]; yaw = np.arctan2(2 * (q[:, 0] * q[:, 3] + q[:, 1] * q[:, 2]), 1 - 2 * (q[:, 2] ** 2 + q[:, 3] ** 2))
print(f"envs {n}, horizon {T} steps = {T*dt:.1f} s")
print(f"forward displacement x: mean {dx.mean():.3f} m  (min {dx.min():.2f}, max {dx.max():.2f});  lateral |y| mean {np.abs(dy).mean():.3f} m;  |yaw| end mean {np.degrees(np.abs(yaw)).mean():.1f} deg")
print(f"mean forward speed {vx.mean():.3f} m/s;  base height mean {z.mean():.3f} m, min-over-time mean {z.min(1).mean():.3f} m")
print(f"episodes with a fall/termination within the horizon: {int(fell.sum())}/{n}")
ok = ~fell
if ok.any():
    print(f"without falls ({int(ok.sum())} episodes): forward x median {np.median(dx[ok]):.3f} m (min {dx[ok].min():.2f}, max {dx[ok].max():.2f});  lateral |y| median {np.median(np.abs(dy[ok])):.3f} m (max {np.abs(dy[ok]).max():.2f});  |yaw| end median {np.degrees(np.median(np.abs(yaw[ok]))):.1f} deg (max {np.degrees(np.abs(yaw[ok]).max()):.0f})")
    print(f"  path straightness: lateral/forward ratio median {np.median(np.abs(dy[ok]) / np.maximum(dx[ok], 0.05)):.2f}")
