#!/usr/bin/env python3
"""Wrist-roll yoke for the gripper: replaces the PETG stump (FINGER_1) on the elbow-yaw servo.

Hub frame H (mm), origin on the elbow servo's horn axis:
  a = along the forearm (hand direction, +),  b = sideways (the old blade sat at b ~ -12),
  c = along the horn axis (the two horn plates at c = +-18.85, the old clevis ears at |c| 19.8..21.3).
The yoke clamps both horns (same 4-hole pattern as the old finger), then a box holds the roll servo S1
(ID 14/24) with its shaft along +a at (b = B_R, c = 0). The gripper's rear wall (roll interface plate of
make_gripper.py) sits on the S1 horn. One part serves both arms: it is symmetric in c.

Usage: .cad/bin/python hardware/gripper/make_wrist.py [--check]
"""
import argparse
import math
import os
import sys

import cadquery as cq
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_gripper as G  # noqa: E402

OUT = os.path.join(HERE, "stl")

# horn clamp (measured on the left_hand mesh in the robot CAD)
EAR_IN, EAR_T = 19.8, 4.5           # ear inner face |c|, thickness (the ears carry the whole roll/grip torque from the horns)
HUB_R = 11.0
HOLE_R, HOLE_D, BORE_D = 7.0, 3.2, 6.8
HOLE_ANG0 = -7.5                    # angle (deg) of the first hole in the (a, b) plane, step 90
# roll-servo cradle
B_R = -12.0                         # roll axis b (= old blade offset)
A_F = 14.0                          # cradle floor (outer face) distance from the horn axis
WALL, FLOOR, PLATE_T = 4.0, 2.5, 2.6
C_OUT = EAR_IN + EAR_T              # 24.3 outer face of the ears
SIDE_WALL = 6.5                     # cradle side walls: only locate the servo and hold the retainer screws

CAV_DEPTH = G.SV_H + 0.55
A_TOP = A_F + FLOOR + CAV_DEPTH     # servo top face = cavity roof (retainer plate bottom)
A_HORN = A_TOP + PLATE_T            # horn top = retainer top = gripper boss tip
B_FRONT = B_R + (G.SV_SHAFT_FROM_FRONT + G.SV_CLR)                    # cavity edges along b (shaft end points inward, +b;
B_REAR = B_R - (G.SV_L - G.SV_SHAFT_FROM_FRONT + G.SV_CLR)            # the body then reaches outward, away from the torso)
C_OFF = -0.32                  # body centre offset in c (y_l = -c)
CAV_C = G.SV_W / 2 + G.SV_CLR + 0.1
SIDE_OUT = CAV_C + SIDE_WALL        # outer face of the thin cradle walls |c|
CORNER_R = 6.0                      # radius of the long outer edges of the cradle and the ramp
RAMP_A = 26.0                       # the ear thickness ramps down onto the wall over this length (a = A_F .. A_F + RAMP_A)
BOX_B0, BOX_B1 = B_REAR - WALL, B_FRONT + WALL
OFFA = A_HORN - (G.TRAY_X0 - G.REAR_T - G.BOSS_H)   # gripper x_g -> a
SCREW_C = (CAV_C + SIDE_OUT) / 2
SCREW_B = (B_REAR + 6.0, B_FRONT - 6.0)


def to_h(x_g=0.0, y_g=0.0, z_g=0.0):
    """Gripper coordinates -> hub frame."""
    return (x_g + OFFA, y_g + B_R, z_g - G.ROLL_Z)


def yoke():
    """Built with cadquery axes (X,Y,Z) = (a, b, c)."""
    bm, bl = (BOX_B0 + BOX_B1) / 2, BOX_B1 - BOX_B0
    # outer body in two grown pieces that share the rounded-rectangle section at a = A_F + RAMP_A:
    # the cradle (thin walls) and a ruled loft from the ear width down to that section (the ramp)
    a_r = A_F + RAMP_A
    box = cq.Workplane("YZ").workplane(offset=a_r).center(bm, 0).rect(bl, 2 * SIDE_OUT).extrude(A_TOP - a_r)
    box = G.soft(box, "|X", CORNER_R)
    box = G.soft(box, ">X", 3.0)                              # rim of the walls at the open end
    # cosine ease: the ramp leaves the flat ear face and meets the wall tangentially, so no crease line is left
    secs = []
    for k in range(9):
        t = k / 8
        hc = SIDE_OUT + (C_OUT - SIDE_OUT) * (0.5 + 0.5 * math.cos(math.pi * t))
        secs.append(cq.Sketch().rect(bl, 2 * hc).vertices().fillet(CORNER_R).moved(cq.Location(cq.Vector(0, 0, RAMP_A * t))))
    ramp = cq.Workplane("YZ").workplane(offset=A_F).center(bm, 0).placeSketch(*secs).loft()
    body = box.union(ramp)
    # ear plates: hub circle + web that ends on the flat part of the ramp start face
    pts = [(HUB_R * math.cos(2 * math.pi * k / 48), HUB_R * math.sin(2 * math.pi * k / 48)) for k in range(48)]
    pts += [(A_F + 0.05, BOX_B0 + CORNER_R), (A_F + 0.05, BOX_B1 - CORNER_R)]
    from shapely.geometry import MultiPoint
    poly = MultiPoint(pts).convex_hull
    for s in (+1, -1):
        c0 = EAR_IN if s > 0 else -EAR_IN - EAR_T
        e = cq.Workplane("XY").workplane(offset=c0).polyline(list(poly.exterior.coords)[:-1]).close().extrude(EAR_T)
        # round the ear rim, but not the edge that sits on the ramp start
        rim = [ed for ed in e.edges("not |Z").vals() if ed.Center().x < A_F]
        try:
            e = e.newObject(rim).fillet(1.2)
        except Exception:
            print("  (ear rim fillet skipped)")
        body = body.union(e)
    cav = G.box(A_F + FLOOR, A_TOP + 0.1, B_REAR, B_FRONT, C_OFF - CAV_C, C_OFF + CAV_C)
    body = body.cut(cav)
    # rear-bump hole in the floor (shaft end of S1 is at the +a side, bump at the floor)
    body = body.cut(cq.Workplane("YZ").workplane(offset=A_F - 0.1).center(B_R, C_OFF).circle(G.SV_BUMP_D / 2).extrude(FLOOR + 0.2))
    # horn screw holes + centre bore through both ears
    for s in (+1, -1):
        c_out = s * C_OUT
        body = body.cut(G.cyl(0, 0, BORE_D, min(s * EAR_IN, c_out) - 0.1, max(s * EAR_IN, c_out) + 0.1))
        for k in range(4):
            ang = math.radians(HOLE_ANG0 + 90 * k)
            x, y = HOLE_R * math.cos(ang), HOLE_R * math.sin(ang)
            z0, z1 = sorted((s * EAR_IN - 0.1 * s, c_out))
            body = body.cut(G.cyl(x, y, HOLE_D, z0 - 0.2, z1 + 0.2))
    # pilots for the retainer screws
    for sc in (+1, -1):
        for bb in SCREW_B:
            body = body.cut(cq.Workplane("XY").add(cq.Solid.makeCylinder(1.3, 15, cq.Vector(A_TOP - 14.99, bb, sc * SCREW_C), cq.Vector(1, 0, 0))))
    return body


def retainer():
    p = G.soft(G.box(A_TOP, A_HORN, BOX_B0, BOX_B1, -SIDE_OUT, SIDE_OUT), "|X", 6.0)
    p = G.soft(p, "not |X", 1.2)
    p = p.cut(G.box(A_TOP - 0.1, A_HORN + 0.1, B_R - 30.6, B_R + 8.6, C_OFF - 9.8, C_OFF + 9.8))   # raised servo top + horn
    p = p.cut(cq.Workplane("XY").add(cq.Solid.makeCylinder(G.BOSS_D / 2 + 0.6, PLATE_T + 0.2, cq.Vector(A_TOP - 0.1, B_R, 0), cq.Vector(1, 0, 0))))   # round window: the gripper boss sits in it, flush with the plate top
    for sc in (+1, -1):
        for bb in SCREW_B:
            p = p.cut(cq.Workplane("XY").add(cq.Solid.makeCylinder(1.7, PLATE_T + 0.2, cq.Vector(A_TOP - 0.1, bb, sc * SCREW_C), cq.Vector(1, 0, 0))))
            p = p.cut(cq.Workplane("XY").add(cq.Solid.makeCylinder(3.1, 1.1, cq.Vector(A_HORN - 1.0, bb, sc * SCREW_C), cq.Vector(1, 0, 0))))   # 1 mm cap-head counterbore
    return p


PARTS = {"wrist_yoke_x2": yoke, "wrist_retainer_x2": retainer}


def export():
    os.makedirs(OUT, exist_ok=True)
    for n, f in PARTS.items():
        cq.exporters.export(f(), os.path.join(OUT, n + ".stl"), tolerance=0.02, angularTolerance=0.1)
        print("wrote", n)


def check():
    import trimesh
    from trimesh.transformations import rotation_matrix as rm, translation_matrix as tm

    def load(n):
        return trimesh.load(os.path.join(OUT, n + ".stl"))

    yk, rt = load("wrist_yoke_x2"), load("wrist_retainer_x2")
    print("yoke volume %.1f cm3, retainer %.1f cm3" % (yk.volume / 1e3, rt.volume / 1e3))
    # S1 servo mesh: servo-local (x_l long, y_l width, z_l height) -> hub (a, b, c) = (z_l + A_TOP, B_R + x_l, +y_l)
    sv = G.load_servo(transverse=False)
    sv.apply_translation([0, -G.A, 0])                      # shaft to the local origin; z=0 = body top
    v = sv.vertices.copy()
    sv.vertices = np.c_[v[:, 2] + A_TOP, B_R + v[:, 0], v[:, 1]]
    pts = sv.sample(20000)
    for n, m in (("yoke", yk), ("retainer", rt)):
        k = sum(int(m.contains(pts[i:i + 2500]).sum()) for i in range(0, len(pts), 2500))
        print(f"S1 servo surface points inside {n}: {k}")
    print("S1 servo extents a [%.1f, %.1f]  b [%.1f, %.1f]  c [%.1f, %.1f]" % tuple(np.r_[sv.bounds[:, 0], sv.bounds[:, 1], sv.bounds[:, 2]][[0, 3, 1, 4, 2, 5]]))
    return yk, rt, sv


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--no-export", action="store_true")
    a = ap.parse_args()
    print(f"A_TOP {A_TOP:.1f}  horn plane {A_HORN:.1f}  gripper offset {OFFA:.1f}  hand tip a ~ {OFFA + 100:.0f}")
    if not a.no_export:
        export()
    if a.check:
        check()
