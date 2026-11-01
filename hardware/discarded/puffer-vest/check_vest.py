#!/usr/bin/env python3
"""Passungs-Check der Puffer-Weste im getragenen Zustand (Roboter-Frame): Rucksack-Kollision (Boolean), Abstand zu allen
Roboter-Bauteilen des gepinnten Assemblys, Druckbett, Masse. Exit 1 bei einem Befund.
Usage: .cad/bin/python hardware/vest/check_vest.py   (vorher make_vest.py)"""
import json, os, sys
import numpy as np, trimesh
HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
W = os.path.join(HERE, "stl", "robotframe"); BP = os.path.join(REPO, "hardware", "backpack_v2", "stl_v3")
RHO = 1.22e-3; MIN_CLEAR = {"arm": 4.0, "head": 4.0, "default": 1.0}; bad = []
def warn(msg): print("  !!", msg); bad.append(msg)
vest = {k: trimesh.load(os.path.join(W, f"vest_{k}.stl")) for k in ("pads", "flaps", "belt", "rear_A", "rear_B")}
print("Weste, getragener Zustand:")
for k, m in vest.items(): print(f"  {k:7s} {m.volume * RHO:6.1f} g  bbox {m.bounds[0].round(1)} .. {m.bounds[1].round(1)}  watertight={m.is_watertight}")
# ---- 1. Rucksack: Boolean-Schnitt (watertight)
print("Rucksack (Boolean, manifold):")
bp = {n: trimesh.load(os.path.join(BP, f"backpack_v3_{n}_robotframe.stl")) for n in ("base", "lid")}
for k, m in vest.items():
    for n, b in bp.items():
        if not (m.bounds[1] > b.bounds[0]).all() or not (m.bounds[0] < b.bounds[1]).all(): continue
        try: v = trimesh.boolean.intersection([m, b], engine="manifold").volume
        except Exception as e: v = float("nan"); print("   boolean failed:", e)
        print(f"  {k:7s} x {n:4s}: {v:8.3f} mm3")
        if not v < 5.0:   # Tessellation der Biegung, < 0,03 mm tief warn(f"{k} durchdringt Rucksack {n} ({v:.1f} mm3)")
# ---- 2. Abstand zu allen Roboter-Bauteilen (ungesigned, Oberflaechenpunkte der Weste)
s = trimesh.load(os.path.join(REPO, "resources", "cad", "z001-opus-m-93de7567.glb"))
rng = np.random.default_rng(0); lo = np.min([m.bounds[0] for m in vest.values()], 0) - 30; hi = np.max([m.bounds[1] for m in vest.values()], 0) + 30
parts = []
for n in s.graph.nodes_geometry:
    T, g = s.graph[n]; m = s.geometry[g].copy(); m.apply_transform(T); m.apply_scale(1000)
    if (m.bounds[1] < lo).any() or (m.bounds[0] > hi).any() or n.startswith(("BackPack", "Bus Servo", "Battery", "Electronics", "MilkV", "[Draft]")): continue
    parts.append((n, m))
parts += [(f"backpack_{n}", b) for n, b in bp.items()]
print("Mindestabstand Weste -> Roboter (mm), 6 engste Teile je Weste-Teil:")
for k, m in vest.items():
    pts = m.sample(1500) if len(m.faces) > 1500 else m.vertices
    res = []
    for n, p in parts:
        if (p.bounds[1] < m.bounds[0] - 30).any() or (p.bounds[0] > m.bounds[1] + 30).any(): continue
        d = np.linalg.norm(trimesh.proximity.closest_point(p, pts)[0] - pts, axis=1).min(); res.append((d, n))
    res.sort()
    print(f"  {k:7s} " + "; ".join(f"{n[:26]} {d:.1f}" for d, n in res[:6]))
    for d, n in res:
        kind = "arm" if any(t in n for t in ("shoulder", "elbow", "hand")) else ("head" if any(t in n for t in ("Head", "Neck", "Eye", "MIC", "LCD")) else "default")
        if kind != "default" and d < MIN_CLEAR[kind]: warn(f"{k}: nur {d:.1f} mm zu {n}")
        if kind == "default" and not n.startswith(("Torso", "backpack")) and d < MIN_CLEAR["default"]: warn(f"{k}: nur {d:.1f} mm zu {n}")
# ---- 3. Druckdaten
print("Druckdaten:")
for f in sorted(os.listdir(os.path.join(HERE, "stl"))):
    if not f.endswith(".stl"): continue
    m = trimesh.load(os.path.join(HERE, "stl", f)); sz = m.extents
    print(f"  {f:34s} {sz.round(1)} mm  {m.volume * RHO:5.1f} g  watertight={m.is_watertight}")
    if max(sz[0], sz[1]) > 250 or not m.is_watertight: warn(f"{f}: Bettgroesse/Wasserdichtigkeit")
tot = sum(m.volume for m in vest.values()) * RHO; print(f"Gesamt: {tot:.0f} g TPU (Roboter laut mass_model nur Elektronik 430 g, Rest Servos/Druckteile)")
print("OK" if not bad else f"{len(bad)} Befund(e)"); sys.exit(1 if bad else 0)
