"""Contact sheet from a rendered policy video: python contact_sheet.py <video.mp4> <out.png> [n_frames=8]"""
import sys, numpy as np, imageio.v3 as iio, PIL.Image as Im
src, out = sys.argv[1], sys.argv[2]; n = int(sys.argv[3]) if len(sys.argv) > 3 else 8
frames = iio.imread(src, plugin="pyav") if False else list(iio.imiter(src))
idx = np.linspace(0, len(frames) - 1, n).astype(int)
tiles = [Im.fromarray(frames[i]) for i in idx]
w, h = tiles[0].size; cols = 4; rows = (n + cols - 1) // cols
sheet = Im.new("RGB", (cols * w, rows * h), "white")
for k, t in enumerate(tiles): sheet.paste(t, ((k % cols) * w, (k // cols) * h))
sheet.save(out); print(f"{len(frames)} frames, {w}x{h}, sheet -> {out}")
