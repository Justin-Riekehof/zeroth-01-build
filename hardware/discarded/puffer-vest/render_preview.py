#!/usr/bin/env python3
"""Orthografische Vorschau der Weste am Roboter (Painter's Algorithm, matplotlib) -> preview.png.
Usage: .cad/bin/python hardware/vest/render_preview.py [out.png]"""
import os, sys, numpy as np, trimesh, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection
HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
W = os.path.join(HERE, "stl", "robotframe"); BP = os.path.join(REPO, "hardware", "backpack_v2", "stl_v3")
COL = {"pads": "#e8742a", "flaps": "#c9501a", "belt": "#f0a050", "rear_A": "#f0a050", "rear_B": "#f5c080"}
def load_glb_parts(names):
    s = trimesh.load(os.path.join(REPO, "resources", "cad", "z001-opus-m-93de7567.glb")); out = []
    for n in s.graph.nodes_geometry:
        if any(n.startswith(k) for k in names):
            T, g = s.graph[n]; m = s.geometry[g].copy(); m.apply_transform(T); m.apply_scale(1000); out.append(m)
    return out
ctx = [(m, "#9aa4b0") for m in load_glb_parts(["Torso", "left_shoulder", "right_shoulder", "elbow_bracket", "left_elbow", "right_elbow", "Head", "Torso to Neck", "left_hand", "right_hand"])]
ctx += [(trimesh.load(os.path.join(BP, f)), c) for f, c in (("backpack_v3_base_robotframe.stl", "#7d93b8"), ("backpack_v3_lid_robotframe.stl", "#7fae6c"))]
vest = [(trimesh.load(os.path.join(W, f"vest_{k}.stl")), c) for k, c in COL.items() if os.path.exists(os.path.join(W, f"vest_{k}.stl"))]
VIEWS = {"front (von vorn)": (np.array([[1, 0, 0], [0, 0, 1], [0, 1, 0]]), (-150, 150, 230, 440)),   # Zeilen: x2d, y2d, Tiefe (gross = weit weg)
         "side (von links)": (np.array([[0, 1, 0], [0, 0, 1], [-1, 0, 0]]), (-90, 140, 230, 440)),
         "back (von hinten)": (np.array([[-1, 0, 0], [0, 0, 1], [0, -1, 0]]), (-150, 150, 230, 440)),
         "top (von oben)": (np.array([[1, 0, 0], [0, 1, 0], [0, 0, -1]]), (-150, 150, -90, 140))}
def tris(m, R, shade, color, light=np.array([0.3, -0.5, 0.8])):
    f = m.faces; v = m.vertices @ R.T                       # x2d, y2d, tiefe (grosse Tiefe = weit weg)
    n = m.face_normals @ R.T; lam = np.clip(np.abs(n @ (light / np.linalg.norm(light))), 0, 1) * 0.55 + 0.45
    base = np.array(matplotlib.colors.to_rgb(color)); cols = np.clip(base[None] * lam[:, None], 0, 1)
    return v[f][:, :, :2], v[f][:, :, 2].mean(1), cols
fig, axs = plt.subplots(2, 2, figsize=(16, 15))
for ax, (title, (R, lim)) in zip(axs.ravel(), VIEWS.items()):
    P, D, C = [], [], []
    for m, c in ctx + vest:
        p, d, col = tris(m, R, True, c); P.append(p); D.append(d); C.append(col)
    P = np.concatenate(P); D = np.concatenate(D); C = np.concatenate(C); o = np.argsort(-D)
    ax.add_collection(PolyCollection(P[o], facecolors=C[o], edgecolors="none", linewidths=0))
    ax.set_xlim(lim[0], lim[1]); ax.set_ylim(lim[2], lim[3]); ax.set_aspect("equal"); ax.set_title(title); ax.grid(True, alpha=.3)
plt.tight_layout(); out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "preview.png"); plt.savefig(out, dpi=70); print(out)
