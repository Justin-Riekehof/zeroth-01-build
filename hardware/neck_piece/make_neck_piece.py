#!/usr/bin/env python3
"""Zeroth-01 neck piece ("Torso to Neck"), reinforced: the two screw lugs that hold it on the torso broke at the first
knock against the head.

Why they broke: the piece rests on the torso only on the 10 mm front shelf (y -20 ... -10) and hangs on two horizontal
M3 screws (x +-32.5, z 379) that go into dia 4 heat-set inserts in that shelf. The screw head bore on a 2.5 mm wall
(y -10 ... -7.5), the lug was 12.5 mm wide with 2 mm under the dia 6.5 counterbore. A push on the head (lever ~40 mm)
against a pivot 5 ... 8 mm from the screw axis loads each screw with 5-8 times that force -> the wall tears out.

Changes (v2, 2026-11-07: through-bolted; the screws keep their position):
  * lugs: solid blocks x -9 / +7.5 around the screw, y -10 ... 14.64 (flush with the plate back), down to z 371.5;
    bearing wall 8 mm (dia 3.3 through), behind it a hex shaft AF 5.8 open to the back that holds the lock nut
  * front claw: 3.2 mm over the rounded front edge and the whole torso front down to the lug foot (x +-42, z 371.5),
    with a countersunk dia 3.3 hole on each screw axis. Pushing the head back presses the claw against the outside of the
    torso front and the lug foot against its inside (pure compression)
  * bolt: M3x35 countersunk from the front, through the claw, the torso front shelf and the lug wall, lock nut DIN 985
    in the hex shaft. The torso front shelf is clamped between claw and lug. The torso needs one change for that: the
    heat-set inserts are drilled out with 3.2 mm (their thread would otherwise carry the screw and claw and lug would
    each only clamp against the insert) and the remaining 5.4 mm of the front wall drilled through to the front - with
    the neck piece in place, through the claw holes as a drill jig
  * tongue, cable channel dia 3.3 and everything above the plate are unchanged
Clearances to every part of the pinned CAD and to the head/backpack rebuilds are checked; the piece still drops onto the
torso from above.

Usage: .cad/bin/python hardware/neck_piece/make_neck_piece.py   (needs cadquery, trimesh, manifold3d)
"""
from __future__ import annotations
import json, os, sys
import numpy as np
import trimesh
import cadquery as cq

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "sim", "tools"))
from meshfix import stitch_t_junctions  # noqa: E402

GLB = os.path.join(REPO, "resources", "cad", "z001-opus-m-93de7567.glb")
RF = os.path.join(HERE, "stl", "robotframe"); PRINT = os.path.join(HERE, "print")
NODE = "Torso to Neck"
# existing torso geometry (measured on the stitched meshes)
SCREWS = [(32.44, 379.05), (-32.54, 379.02)]           # (x, z) of the torso inserts (dia 4.0, y -10 ... -20, cone to -21.5)
Y_TORSO_IN = -10.0                                     # inner face of the torso front shelf = front face of the lugs
Y_TORSO_OUT = -25.4                                    # outer front face of the torso
Z_SHELF = 386.6                                        # top of the shelf, the plate sits on it
Y_PLATE_BACK = 14.64
# new lug [mm]
LUG_IN, LUG_OUT = 9.0, 7.5                             # from the screw axis towards the middle / outwards (x 40 < shoulder motor 40.5)
LUG_Z0 = 371.5                                         # foot: >= 1.4 mm above Milk-V stack (369.8) and shoulder motors (370.6)
WALL = 8.0                                             # bearing wall in front of the nut (was 2.5 under the screw head)
HOLE_D = 3.3                                           # M3 clearance (drill 3.2 in the torso)
NUT = dict(name="DIN 985 M3", af=5.5, h=4.0)           # lock nut (nylon ring)
HEX_AF = NUT["af"] + 0.3                               # hex shaft: nut slides in from the back, cannot turn
# front claw
CLAW_X = 42.0; CLAW_T = 3.2; CLAW_Z0 = LUG_Z0; GAP = 0.25
CSK = dict(d=7.0, recess=0.2)                          # 90 deg countersink for ISO 10642 M3 (head dia <= 6.72), head 0.2 below the surface
SCREW = dict(name="M3x35 ISO 10642 (countersunk) + lock nut DIN 985", length=35.0)
Y_CLAW_FRONT = Y_TORSO_OUT - GAP - CLAW_T


def load(name):
    sc = trimesh.load(GLB, force="scene"); g = sc.graph
    for n in g.nodes_geometry:
        if n.split("_")[0] == name:
            T, gn = g.get(n); m = sc.geometry[gn].copy(); m.apply_transform(T)
            m.apply_scale(1000.0)
            return stitch_t_junctions(m, tol=2e-4)              # in mm here: only exact T-junctions, nothing moved
    raise KeyError(name)


def tm(wp):
    v, f = wp.val().tessellate(0.01, 0.1)
    return trimesh.Trimesh([(p.x, p.y, p.z) for p in v], f, process=True)


def lug(x, z):
    """solid block around one screw, from the lug foot up into the plate, back edges rounded"""
    s = np.sign(x); x0, x1 = sorted((x - s * LUG_IN, x + s * LUG_OUT))
    b = cq.Workplane("XY").box(x1 - x0, Y_PLATE_BACK - Y_TORSO_IN, Z_SHELF + 3.0 - LUG_Z0, centered=False).translate((x0, Y_TORSO_IN, LUG_Z0))
    return b.edges("|Z and >Y").fillet(2.0).faces("<Z").edges("not <Y").chamfer(1.0)


def bores(x, z):
    """lug: through hole in the bearing wall + hex shaft for the lock nut (flats top/bottom), open to the back"""
    y_nut = Y_TORSO_IN + WALL
    hole = cq.Workplane("XZ", origin=(x, Y_TORSO_IN + 1.0, z)).circle(HOLE_D / 2).extrude(-(WALL + 1.0))      # XZ extrudes -Y
    shaft = cq.Workplane("XZ", origin=(x, y_nut, z)).polygon(6, HEX_AF / np.cos(np.pi / 6)).extrude(-(Y_PLATE_BACK + 2.0 - y_nut))
    return hole.union(shaft)


def claw_holes(x, z):
    """claw: dia 3.3 through (= drill jig for the torso) + 90 deg countersink from the front"""
    y0 = Y_CLAW_FRONT - 1.0
    hole = cq.Workplane("XZ", origin=(x, Y_TORSO_OUT - 0.1, z)).circle(HOLE_D / 2).extrude(Y_TORSO_OUT - 0.1 - y0)  # +extrude = -Y
    depth = CSK["recess"] + (CSK["d"] - HOLE_D) / 2
    cone = cq.Solid.makeCone(CSK["d"] / 2 + 1.0, HOLE_D / 2, depth + 1.0, pnt=cq.Vector(x, Y_CLAW_FRONT - 1.0, z), dir=cq.Vector(0, 1, 0))
    rec = cq.Workplane("XZ", origin=(x, Y_CLAW_FRONT + CSK["recess"], z)).circle(CSK["d"] / 2).extrude(CSK["recess"] + 1.0)
    return hole.union(cq.Workplane().add(cone)).union(rec)


def claw():
    """lip over the rounded front edge of the torso; its inside is cut from the torso grown by GAP"""
    yo = Y_CLAW_FRONT
    # inner side stays inside the torso shell (it is cut away anyway) and clear of the insert holes (y > -21.5)
    prof = [(-19.5, 391.0), (-24.0, 391.0), (yo, 387.5), (yo, CLAW_Z0 + 0.8), (yo + 0.8, CLAW_Z0), (-23.5, CLAW_Z0), (-23.5, 384.0), (-19.5, 386.0)]
    w = cq.Workplane("YZ", origin=(-CLAW_X, 0, 0)).polyline(prof).close().extrude(2 * CLAW_X)
    return w.edges("|Y").chamfer(1.5)


def grown(m, d):
    """m grown by about d in every direction (union of shifted copies; exact enough for a print clearance)"""
    dirs = [(0, 0, 0)] + [tuple(v) for v in np.array(np.meshgrid([-1, 0, 1], [-1, 0, 1], [-1, 0, 1])).T.reshape(-1, 3) if any(v)]
    cps = []
    for v in dirs:
        v = np.array(v, float); v = v / np.linalg.norm(v) * d if v.any() else v
        c = m.copy(); c.apply_translation(v); cps.append(c)
    return trimesh.boolean.union(cps, engine="manifold")


def neighbours():
    """everything that must stay free: all other parts of the pinned CAD plus the head/backpack rebuilds"""
    sc = trimesh.load(GLB, force="scene"); g = sc.graph; out = {}
    lo, hi = np.array([-70, -45, 355]), np.array([70, 45, 412])
    for n in g.nodes_geometry:
        if n.split("_")[0] == NODE: continue
        T, gn = g.get(n); m = sc.geometry[gn].copy(); m.apply_transform(T); m.apply_scale(1000.0)
        if np.all(m.bounds[1] > lo) and np.all(m.bounds[0] < hi): out[n] = m
    for p in ("hardware/head_imu/stl/robotframe/neck_mount_imu.stl", "hardware/head_cam/stl/robotframe/head_shell_cam3.stl",
              "hardware/backpack_v2/stl_v3/backpack_v3_base_robotframe.stl"):
        f = os.path.join(REPO, p)
        if os.path.exists(f): out[os.path.basename(p)] = trimesh.load(f)
    return out


def near_surface(m, lo, hi, step=0.3):
    """points on m's surface inside the box lo..hi, about step apart (only the faces near the box are sampled)"""
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    t = m.triangles; sel = np.all(t.max(1) > lo, axis=1) & np.all(t.min(1) < hi, axis=1)
    if not sel.any(): return np.zeros((0, 3))
    sub = trimesh.Trimesh(t[sel].reshape(-1, 3), np.arange(sel.sum() * 3).reshape(-1, 3), process=False)
    p = np.vstack([sub.vertices, sub.sample(int(min(4e5, sub.area / step ** 2 + 100)))])
    return p[np.all((p > lo) & (p < hi), axis=1)]


def main():
    os.makedirs(RF, exist_ok=True); os.makedirs(PRINT, exist_ok=True)
    old = load(NODE); torso = load("Torso")
    assert old.is_watertight and torso.is_watertight
    print(f"{NODE}: {old.volume/1000:.2f} cm3 (stitched GLB)")
    claw_fit = trimesh.boolean.difference([tm(claw()), grown(torso, GAP)], engine="manifold")    # the lugs keep touching the shelf at y -10
    claw_fit = max(claw_fit.split(only_watertight=False), key=lambda b: b.volume)              # drop the bits left in the insert holes' tips
    new = trimesh.boolean.union([old] + [tm(lug(x, z)) for x, z in SCREWS] + [claw_fit], engine="manifold")
    new = trimesh.boolean.difference([new] + [tm(bores(x, z)) for x, z in SCREWS] + [tm(claw_holes(x, z)) for x, z in SCREWS], engine="manifold")
    assert new.is_watertight and new.body_count == 1, (new.is_watertight, new.body_count)
    print(f"  reinforced: {new.volume/1000:.2f} cm3 (+{(new.volume-old.volume)/1000:.2f}), watertight, 1 body")

    # ---- checks
    rep = dict(volume_old_cm3=round(old.volume / 1000, 2), volume_new_cm3=round(new.volume / 1000, 2), clearance_mm={}, points_inside={})
    nb = neighbours(); nb["Torso (stitched)"] = torso
    added = trimesh.boolean.difference([new, old], engine="manifold")          # only the new material can collide (watertight)
    lo, hi = added.bounds[0] - 6.0, added.bounds[1] + 6.0
    for n, m in nb.items():
        pts = near_surface(m, lo, hi)
        if not len(pts): continue
        inside = int(added.contains(pts).sum())                                # neighbour surface inside the new material
        d = float(trimesh.proximity.closest_point(added, pts)[1].min())
        if d < 5.0 or inside: rep["clearance_mm"][n] = round(d, 2); rep["points_inside"][n] = inside
        print(f"  {n:45s} min distance {d:6.2f} mm" + (f", {inside} surface points INSIDE" if inside else ""))
        if n != "Torso (stitched)": assert inside == 0, n
    # the torso shelf is touched on purpose (y -10 face, plate on the shelf): only its points deeper than 0.05 mm count
    tp = near_surface(torso, lo, hi); deep = tp[added.contains(tp)]
    deep = deep[trimesh.proximity.closest_point(added, deep)[1] > 0.05] if len(deep) else deep
    assert len(deep) == 0, f"{len(deep)} torso points inside the new material"
    # bolt: countersunk head 0.2 below the claw front, through claw + torso + lug wall, nylon ring fully engaged; the lock
    # nut is pushed in from behind through the hex shaft (path checked up to the backpack)
    y_head = Y_CLAW_FRONT + CSK["recess"]; tip = y_head + SCREW["length"]; y_nut = Y_TORSO_IN + WALL
    assert y_nut + NUT["h"] + 1.0 <= tip <= Y_PLATE_BACK - 1.0, tip              # >= 2 pitches past the nut, inside the shaft
    for x, z in SCREWS:
        r = HEX_AF / 2 - 0.3
        for n, m in nb.items():
            q = near_surface(m, (x - r, Y_PLATE_BACK + 0.5, z - r), (x + r, 37.5, z + r))
            hit = q[np.hypot(q[:, 0] - x, q[:, 2] - z) < r] if len(q) else q
            assert len(hit) == 0, f"nut path at x {x} blocked by {n}"
    print(f"  bolt: {SCREW['name']}, head y {y_head:.2f}, nut y {y_nut:.1f} ... {y_nut + NUT['h']:.1f}, tip y {tip:.2f} "
          f"({tip - y_nut - NUT['h']:.1f} past the nut), clamps claw {CLAW_T} + torso {Y_TORSO_IN - Y_TORSO_OUT:.1f} + lug wall {WALL}; nut path free to y 37.5")
    rep["screw"] = SCREW; rep["nut"] = NUT; rep["screw_head_y"] = round(y_head, 2); rep["screw_tip_y"] = round(tip, 2)

    new.export(os.path.join(RF, "neck_piece_reinforced.stl"))
    old.export(os.path.join(RF, "neck_piece_original.stl"))
    scr = []                                                                   # bolts for the WebUI: countersunk head, shank, lock nut
    for x, z in SCREWS:
        hd = tm(cq.Workplane().add(cq.Solid.makeCone(6.72 / 2, 3.0 / 2, 1.86, pnt=cq.Vector(x, y_head, z), dir=cq.Vector(0, 1, 0))))
        sh = trimesh.creation.cylinder(radius=1.5, segment=[[x, y_head + 1.0, z], [x, tip, z]], sections=48)
        nut = tm(cq.Workplane("XZ", origin=(x, y_nut, z)).polygon(6, NUT["af"] / np.cos(np.pi / 6)).extrude(-NUT["h"]))
        scr += [hd, sh, nut]
    trimesh.util.concatenate(scr).export(os.path.join(RF, "neck_screws.stl"))
    pr = new.copy(); pr.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))    # claw front (-Y) on the bed
    pr.apply_translation(-pr.bounds[0]); pr.export(os.path.join(PRINT, "neck_piece_reinforced.stl"))
    json.dump(rep, open(os.path.join(HERE, "neck_piece.json"), "w"), indent=1)
    print("done ->", os.path.join(PRINT, "neck_piece_reinforced.stl"))


if __name__ == "__main__":
    main()
