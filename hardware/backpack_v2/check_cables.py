#!/usr/bin/env python3
"""Cable & envelope check for backpack v3 (needs trimesh + numpy).

* builds every cable of stl_v3/cables.json as a tube along its filleted centreline
  (corners rounded with the cable's minimum bend radius; complains if a corner is too tight),
* checks tubes against the printed parts and against the wired component envelopes,
* checks the envelopes against the parts and each other,
* writes stl_v3/placeholder_cables.stl for the GUI / previews.
Usage: python check_cables.py
"""
import glob, json, os, sys, numpy as np, trimesh
HERE = os.path.dirname(os.path.abspath(__file__)); STL = os.path.join(HERE, "stl_v3")
parts = {k: trimesh.load(os.path.join(STL, f"backpack_v3_{k}_robotframe.stl")) for k in ("base", "lid")}
env = {os.path.basename(f)[12:-4]: trimesh.load(f) for f in glob.glob(os.path.join(STL, "placeholder_*.stl")) if "cables" not in f}
cables = json.load(open(os.path.join(STL, "cables.json")))

def fillet_path(pts, r, step=1.0):
    """3D polyline -> densified path with circular arcs of radius r at the corners."""
    P = [np.asarray(p, float) for p in pts]
    P = [q for i, q in enumerate(P) if i == 0 or np.linalg.norm(q - P[i - 1]) > 1e-6]   # drop duplicate points
    out = [P[0]]; notes = []
    for i in range(1, len(P) - 1):
        a, b, c = P[i - 1], P[i], P[i + 1]
        u = (a - b) / np.linalg.norm(a - b); v = (c - b) / np.linalg.norm(c - b)
        cosang = np.clip(np.dot(u, v), -1, 1); ang = np.arccos(cosang)          # angle between the legs
        if ang > np.pi - 1e-3:   # straight
            out.append(b); continue
        t = r / np.tan(ang / 2)                                                  # tangent length from the corner
        la, lc = np.linalg.norm(a - b), np.linalg.norm(c - b)
        lmax = min(la if i == 1 else la / 2.0, lc if i == len(P) - 2 else lc / 2.0)   # shared legs are split between neighbours
        rr = r
        if t > lmax:
            rr = lmax * np.tan(ang / 2); t = lmax
            if rr < r - 0.05:
                notes.append(f"corner {i} at {np.round(b,1).tolist()}: radius limited to {rr:.1f} mm (wanted {r})")
        p1, p2 = b + u * t, b + v * t
        n = u + v; n /= np.linalg.norm(n); centre = b + n * (rr / np.sin(ang / 2))
        # arc from p1 to p2 around centre
        w1, w2 = p1 - centre, p2 - centre
        if np.linalg.norm(w1) < 1e-9 or np.linalg.norm(w2) < 1e-9 or not np.isfinite(rr) or rr < 1e-6:
            out.append(b); continue
        sweep = np.arccos(np.clip(np.dot(w1, w2) / (np.linalg.norm(w1) * np.linalg.norm(w2)), -1, 1))
        k = max(3, int(sweep * rr / step) + 1)
        axis = np.cross(w1, w2); axis /= (np.linalg.norm(axis) + 1e-12)
        for j in range(k + 1):
            th = sweep * j / k
            w = w1 * np.cos(th) + np.cross(axis, w1) * np.sin(th) + axis * np.dot(axis, w1) * (1 - np.cos(th))
            out.append(centre + w)
    out.append(P[-1])
    # densify straight pieces
    dense = [out[0]]
    for q in out[1:]:
        seg = q - dense[-1]; L = float(np.linalg.norm(seg))
        if L < 1e-9: continue
        n = max(1, int(L / step)); start = dense[-1].copy()
        for j in range(1, n + 1): dense.append(start + seg * j / n)
    return np.array(dense), notes

def tube(path, d):
    r = d / 2; segs = []
    for i in range(len(path) - 1):
        a, b = path[i], path[i + 1]; L = np.linalg.norm(b - a)
        if L < 1e-6: continue
        cyl = trimesh.creation.cylinder(radius=r, height=L, sections=12)
        T = trimesh.geometry.align_vectors([0, 0, 1], (b - a) / L); T[:3, 3] = (a + b) / 2
        cyl.apply_transform(T); segs.append(cyl)
    segs.append(trimesh.creation.icosphere(subdivisions=1, radius=r).apply_translation(path[0]))
    segs.append(trimesh.creation.icosphere(subdivisions=1, radius=r).apply_translation(path[-1]))
    return trimesh.util.concatenate(segs)

own = {  # envelopes a cable is allowed to touch (its own connectors)
    "lipo_xt60_lead": ("lipo", "xt60_lipo_fuse"), "lipo_balancer": ("lipo", "warner_plug", "warner"),
    "fuse_leg_1": ("xt60_lipo_fuse", "fuse_holder"), "fuse_leg_2": ("fuse_holder", "xt60_fuse_switch"),
    "switch_in_lead": ("xt60_fuse_switch", "switch"), "switch_out_pigtail": ("switch", "cutoff_vin_wires", "cutoff"),
    "out_to_waveshare": ("cutoff_out_wires", "cutoff", "waveshare_plugs"), "out_to_pololu": ("cutoff_out_wires", "cutoff", "pololu", "pololu_wires"),
    "servo_bus_a": ("waveshare_servo_plugs", "waveshare"), "servo_bus_b": ("waveshare_servo_plugs", "waveshare"),
    "pi_usb_to_waveshare": ("pi_plugs", "pi", "waveshare_plugs"), "pololu_5v_usbc": ("pololu", "pololu_wires", "pi_usbc_plug", "pi"),
    "test_leads_5v": ("pololu", "pololu_wires", "lid"),
}
tubes = []; problems = 0
print("== cables ==")
for name, spec in cables.items():
    path, notes = fillet_path(spec["pts"], spec["r"])
    for n in notes: print(f"  [{name}] {n}"); 
    problems += len(notes)
    L = np.sum(np.linalg.norm(np.diff(path, axis=0), axis=1))
    tubes.append(tube(path, spec["d"]))
    msgs = []
    for pk, pm in parts.items():
        if pk in own.get(name, ()): continue
        dist = trimesh.proximity.signed_distance(pm, path) if pm.is_watertight else -trimesh.proximity.closest_point(pm, path)[1]
        # signed_distance: positive INSIDE the mesh (trimesh convention) -> clearance = -dist
        clearance = -dist
        mn = clearance.min()
        if mn < spec["d"] / 2 - 0.05:
            i = int(np.argmin(clearance)); msgs.append(f"{pk}: clearance {mn:.1f} < r {spec['d']/2:.1f} at {np.round(path[i],1).tolist()}")
    for ek, em in env.items():
        if ek in own.get(name, ()): continue
        inside = em.contains(path)
        if inside.any():
            i = int(np.argmax(inside)); msgs.append(f"enters envelope {ek} at {np.round(path[i],1).tolist()} ({int(inside.sum())} pts)")
    status = "ok" if not msgs else "PROBLEM"
    problems += len(msgs)
    print(f"  {name:22s} L={L:5.0f} mm  {status}" + ("".join("\n      - " + m for m in msgs)))
print("\n== envelopes vs parts (intersection volume mm3; own bosses give small values) ==")
def iv(a, b):
    try:
        r = trimesh.boolean.intersection([a, b], engine="manifold"); return 0.0 if r.is_empty else round(float(r.volume), 1)
    except Exception as e: sys.exit(f"boolean check failed ({type(e).__name__}: {e}) - is manifold3d installed?")
for ek, em in sorted(env.items()):
    row = {pk: iv(em, pm) for pk, pm in parts.items()}
    if any(v > 60 for v in row.values()): print(f"  {ek:20s} {row}")
print("\n== envelopes vs envelopes (overlaps > 20 mm3) ==")
keys = sorted(env); allowed = {("warner", "warner_plug"), ("pi", "pi_plugs"), ("pi", "pi_usbc_plug"), ("pi", "cam_ribbon"), ("pololu", "pololu_wires"), ("waveshare", "waveshare_servo_plugs"), ("waveshare", "waveshare_plugs"), ("cutoff", "cutoff_vin_wires"), ("cutoff", "cutoff_out_wires"), ("pi", "pi_screws"), ("pi", "pi_sd"), ("switch", "switch_bosses"), ("cutoff", "cutoff_screws")}
for i, a in enumerate(keys):
    for b in keys[i + 1:]:
        if (a, b) in allowed or (b, a) in allowed: continue
        v = iv(env[a], env[b])
        if v > 20: print(f"  {a} x {b}: {v}"); problems += 1
allc = trimesh.util.concatenate(tubes); allc.export(os.path.join(STL, "placeholder_cables.stl"))
os.makedirs(os.path.join(STL, "cables"), exist_ok=True)
for (name, spec), t in zip(cables.items(), tubes): t.export(os.path.join(STL, "cables", f"{name}.stl"))
print(f"\ncables -> {os.path.join(STL, 'placeholder_cables.stl')}   problems: {problems}")
sys.exit(1 if problems else 0)
