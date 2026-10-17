#!/usr/bin/env python3
"""Fin-Ray finger for the Z001 forearm — replaces the PETG "stump" (FINGER_1).

Two printed parts, built in the FINGER_1 mesh frame (mm) so they drop into the
existing assembly at the same pose (right arm; `--left` mirrors y -> -y for FINGER_1_2):

  carrier_petg   rigid clevis: horn ears with the original hole pattern (centre bore
                 6.9 + 4x2.8 on R~7.1), pocketed neck, dovetail rail, stop plate
  pad_tpu        compliant Fin-Ray blade (95A TPU), slides onto the rail along z
  retainer_petg  2 mm plate + 1x M2 screw closing the dovetail at the +z end

Fin-Ray layout (pad profile, local s along the finger, t across it):
  t=0  contact wall F (straight, optional grip ridges)  -> faces the object
  t=T  back wall B, tapering to the tip
  ribs run from F towards the BASE on the B side (angle `rib_angle` from the wall
  normal). That is the orientation for which the linear beam model keeps the tip
  stationary while the load point yields; the real wrap-around is a large-
  deflection effect and has to be tuned on a print.

Usage: python3 make_finger.py [--left] [--contact -x|+x] [--rib-angle 25] ...
"""
import argparse
import math
import os

import cadquery as cq
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union
from shapely import affinity

# Ear/hub outline measured from FINGER_1 (section at z=-0.7), mm, finger frame.
EAR_OUTLINE = [
    (-15.62, -30.14), (-11.5, -30.14), (-9.89, -30.01), (-8.32, -29.62), (-6.83, -28.98),
    (-5.46, -28.11), (-4.26, -27.04), (-2.81, -25.09), (8.67, -4.94), (9.38, -3.4),
    (9.82, -1.76), (9.97, -0.07), (9.84, 1.62), (9.43, 3.26), (8.74, 4.81), (7.8, 6.22),
    (6.63, 7.45), (5.27, 8.47), (3.76, 9.24), (1.3, 9.89), (-0.39, 9.97), (-2.07, 9.76),
    (-3.69, 9.27), (-5.21, 8.51), (-6.58, 7.5), (-7.75, 6.28), (-8.7, 4.87), (-9.4, 3.33),
    (-13.67, -8.72), (-14.76, -9.98), (-15.74, -10.77),
]
HORN_BORE = ((0.1, 0.3), 6.9)  # centre, diameter
HORN_HOLES = [(-6.85, 2.15), (-2.4, -6.8), (2.15, 6.4), (6.35, -2.55)]  # dia 2.8
HORN_HOLE_D = 2.8
EAR_Z = [(-1.5, 0.0), (37.6, 39.1)]  # the two clevis ears (z0, z1)

X_MIN, X_MAX = -16.9, -6.6  # blade envelope in x = original FINGER_1 (back wall vertical at x=-6.6)
Y_BASE = -30.1  # where the pad starts (end of the original neck)
Y_TIP = -66.3  # original blade tip


def to_cq(poly, z0, z1):
    """Shapely polygon (with holes) -> extruded cadquery solid."""
    solid = cq.Workplane("XY").workplane(offset=z0).polyline(list(poly.exterior.coords)[:-1]).close().extrude(z1 - z0)
    for ring in poly.interiors:
        hole = cq.Workplane("XY").workplane(offset=z0 - 0.1).polyline(list(ring.coords)[:-1]).close().extrude(z1 - z0 + 0.2)
        solid = solid.cut(hole)
    return solid


def pad_profile(p):
    """Fin-Ray pad as shapely polygon in local (s, t)."""
    L, T0, T1, w, wr = p.length, p.thick, p.tip_thick, p.wall, p.rib
    tb = lambda s: T0 + (T1 - T0) * s / L  # outer position of back wall
    base = box(-2.0, 0, p.base_len, T0)
    f_wall = LineString([(0, w / 2), (L, w / 2)]).buffer(w / 2, cap_style=2)
    b_wall = LineString([(0, T0 - w / 2), (L, tb(L) - w / 2)]).buffer(w / 2, cap_style=2)
    tip = Polygon([(L - 2 * w, 0), (L, 0), (L, tb(L)), (L - 2 * w, tb(L - 2 * w))])
    parts = [base, f_wall, b_wall, tip]
    tan_a = math.tan(math.radians(p.rib_angle))
    s = p.base_len + p.pitch * 0.5
    while s < L - 2 * w - p.pitch * 0.3:
        tf = w / 2
        tbk = tb(s) - w / 2
        s_b = s - (tbk - tf) * tan_a  # back-wall end leans towards the base
        parts.append(LineString([(s, tf), (max(s_b, p.base_len), tbk)]).buffer(wr / 2, cap_style=2))
        s += p.pitch
    if p.ridges:
        r = 0.45
        sr = p.base_len + 1.5
        while sr < L - 4:
            parts.append(Polygon([(sr, 0), (sr + p.ridge_pitch * 0.5, 0), (sr + p.ridge_pitch * 0.25, -r)]))
            sr += p.ridge_pitch
    prof = unary_union(parts)
    # centre on the finger axis (t=0) and tilt by half the taper so the wedge is symmetric about it
    beta = math.degrees(math.atan((T0 - T1) / L))
    prof = affinity.translate(prof, 0, -T0 / 2)
    prof = affinity.rotate(prof, beta / 2, origin=(0, 0)).intersection(box(0, -T0 / 2 - 0.6, L + 10, T0 / 2))
    # dovetail slot (opening at s=0, widening inside), centred on the axis
    tc = 0.0
    slot = Polygon([(-0.1, tc - p.dt_open / 2), (0, tc - p.dt_open / 2), (p.dt_depth, tc - p.dt_wide / 2),
                    (p.dt_depth, tc + p.dt_wide / 2), (0, tc + p.dt_open / 2), (-0.1, tc + p.dt_open / 2)])
    return prof if p.single else prof.difference(slot)


def axis_frame(p):
    """Finger axis: unit direction d, normal n, base point P0 (finger frame, mm).
    --single: the axis runs through the hub centre (0,0), tilted `axis_angle` deg from -y towards -x,
    the blade starts `base_dist` along it. Legacy two-part layout: straight along -y."""
    if p.single:
        ph = math.radians(p.axis_angle)
        d = (-math.sin(ph), -math.cos(ph))
        n = (math.cos(ph), -math.sin(ph))
        return d, n, (p.base_dist * d[0], p.base_dist * d[1])
    return (0.0, -1.0), (1.0, 0.0), ((X_MIN + X_MAX) / 2, Y_BASE)


def local_to_frame(geom, p):
    """local (s along the axis, t across, 0 = axis) -> finger frame (x,y)."""
    d, n, P0 = axis_frame(p)
    sgn = 1 if p.contact == "-x" else -1
    return affinity.affine_transform(geom, [d[0], sgn * n[0], d[1], sgn * n[1], P0[0], P0[1]])


def neck_outline(p):
    """Smooth hull from the hub circle to the blade base, plus the solid-neck region (beyond the hub)."""
    from shapely.geometry import Point, MultiPoint
    d, n, P0 = axis_frame(p)
    h = p.thick / 2
    pts = [(P0[0] + d[0] * 2 + sg * h * n[0], P0[1] + d[1] * 2 + sg * h * n[1]) for sg in (-1, 1)]
    hull = unary_union([Point(0, 0).buffer(10.0, 64), MultiPoint(pts + [(P0[0] - d[0] * 3 + sg * h * n[0], P0[1] - d[1] * 3 + sg * h * n[1]) for sg in (-1, 1)]).convex_hull]).convex_hull
    far = Polygon([(13 * d[0] + sg * 60 * n[0], 13 * d[1] + sg * 60 * n[1]) for sg in (-1, 1)] +
                  [(120 * d[0] + sg * 60 * n[0], 120 * d[1] + sg * 60 * n[1]) for sg in (1, -1)])
    return hull, hull.intersection(far)


def build_single(p):
    """One-piece TPU finger: ears + solid neck (smooth hull) + Fin-Ray blade centred on the hub axis."""
    ex = p.ear_extra
    z0, z1 = 0.0, p.z_len
    body = to_cq(local_to_frame(pad_profile(p), p), z0, z1)
    hull, neck = neck_outline(p)
    for (a, b) in EAR_Z:
        a2, b2 = (a - ex, b) if a < 0 else (a, b + ex)
        body = body.union(to_cq(hull, a2, b2))
    for g in ([neck] if neck.geom_type == "Polygon" else list(neck.geoms)):
        body = body.union(to_cq(g, EAR_Z[0][0], EAR_Z[1][1]))
    for a, b in EAR_Z:
        a2, b2 = (a - ex, b) if a < 0 else (a, b + ex)
        body = body.cut(cq.Workplane("XY").workplane(offset=a2 - 0.1).center(*HORN_BORE[0]).circle(HORN_BORE[1] / 2).extrude(b2 - a2 + 0.2))
        for hx, hy in HORN_HOLES:
            body = body.cut(cq.Workplane("XY").workplane(offset=a2 - 0.1).center(hx, hy).circle(HORN_HOLE_D / 2).extrude(b2 - a2 + 0.2))
    parts = {"finger_tpu": body}
    return {k: v.mirror("XZ") for k, v in parts.items()} if p.left else parts


def build(p):
    if p.single:
        return build_single(p)
    T0 = p.thick
    z0, z1 = 0.0, p.z_len

    # ---- pad (TPU)
    pad_xy = local_to_frame(pad_profile(p), p)
    pad = to_cq(pad_xy, z0, z1)

    # ---- carrier (PETG)
    ear = Polygon(EAR_OUTLINE)
    carrier = None
    for (a, b) in EAR_Z:
        e = to_cq(ear, a, b)
        carrier = e if carrier is None else carrier.union(e)
    # neck block x X_MIN..X_MAX, y -30.1..-14 across both ears, pocketed from +x
    neck = cq.Workplane("XY").box(X_MAX - X_MIN, 18.0, 39.1 + 1.5, centered=False).translate((X_MIN, Y_BASE, -1.5))
    for y0, y1 in [(-27.4, -22.2), (-19.8, -14.6)]:
        pocket = cq.Workplane("XY").box(X_MAX - X_MIN - 2.0, y1 - y0, 39.1 - 3.0 - 3.0, centered=False).translate((X_MIN + 2.0, y0, 3.0))
        neck = neck.cut(pocket)
    carrier = carrier.union(neck)
    # horn holes through both ears
    for a, b in EAR_Z:
        bore = cq.Workplane("XY").workplane(offset=a - 0.1).center(*HORN_BORE[0]).circle(HORN_BORE[1] / 2).extrude(b - a + 0.2)
        carrier = carrier.cut(bore)
        for hx, hy in HORN_HOLES:
            carrier = carrier.cut(cq.Workplane("XY").workplane(offset=a - 0.1).center(hx, hy).circle(HORN_HOLE_D / 2).extrude(b - a + 0.2))
    # dovetail rail (y -30.1 .. -35.1), centred on pad base, slightly undersized for slide clearance
    xc = (X_MIN + X_MAX) / 2
    c = p.dt_clear
    rail_poly = Polygon([(xc - p.dt_open / 2 + c, Y_BASE + 0.2), (xc + p.dt_open / 2 - c, Y_BASE + 0.2),
                         (xc + p.dt_wide / 2 - c, Y_BASE - p.dt_depth + c), (xc - p.dt_wide / 2 + c, Y_BASE - p.dt_depth + c)])
    rail = to_cq(rail_poly, z0, z1)
    pilot = cq.Workplane("XY").workplane(offset=z1 - p.screw_depth).center(xc, Y_BASE - 2.4).circle(0.85).extrude(p.screw_depth + 0.1)
    carrier = carrier.union(rail).cut(pilot)
    # stop plate in front of the pad, behind z=0
    stop = cq.Workplane("XY").box(X_MAX - X_MIN, 8.5, 1.5, centered=False).translate((X_MIN, Y_BASE - 8.4, -1.5))
    carrier = carrier.union(stop)

    # ---- retainer (PETG)
    ret = cq.Workplane("XY").box(X_MAX - X_MIN, 8.5, 2.0, centered=False).translate((X_MIN, Y_BASE - 8.4, z1))
    ret = ret.cut(cq.Workplane("XY").workplane(offset=z1 - 0.1).center(xc, Y_BASE - 2.4).circle(1.15).extrude(2.2))
    ret = ret.cut(cq.Workplane("XY").workplane(offset=z1 + 1.0).center(xc, Y_BASE - 2.4).circle(2.0).extrude(1.1))  # head recess

    parts = {"carrier_petg": carrier, "pad_tpu": pad, "retainer_petg": ret}
    if p.left:
        parts = {k: v.mirror("XZ") for k, v in parts.items()}
    return parts


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--left", action="store_true", help="mirror y -> -y (FINGER_1_2 frame)")
    ap.add_argument("--contact", choices=["-x", "+x"], default="-x", help="which blade face grips (the finger sweeps about z)")
    ap.add_argument("--length", dest="length", type=float, default=38.0, help="pad length from the base (mm)")
    ap.add_argument("--thick", type=float, default=X_MAX - X_MIN, help="pad thickness at the base (mm)")
    ap.add_argument("--tip-thick", dest="tip_thick", type=float, default=7.0, help="blade thickness at the tip before alignment (original ~6.6)")
    ap.add_argument("--wall", type=float, default=1.6, help="contact/back wall thickness (mm, 4 perimeters @0.4)")
    ap.add_argument("--rib", type=float, default=1.2, help="rib thickness (mm, 3 perimeters @0.4)")
    ap.add_argument("--pitch", type=float, default=5.0, help="rib spacing along the finger (mm)")
    ap.add_argument("--rib-angle", dest="rib_angle", type=float, default=25.0, help="rib lean from wall normal, towards the base (deg)")
    ap.add_argument("--base-len", dest="base_len", type=float, default=8.0)
    ap.add_argument("--no-ridges", dest="ridges", action="store_false")
    ap.add_argument("--ridge-pitch", dest="ridge_pitch", type=float, default=2.2)
    ap.add_argument("--z-len", dest="z_len", type=float, default=37.0, help="pad width along the servo axis (mm)")
    ap.add_argument("--dt-open", dest="dt_open", type=float, default=4.0)
    ap.add_argument("--dt-wide", dest="dt_wide", type=float, default=7.0)
    ap.add_argument("--dt-depth", dest="dt_depth", type=float, default=5.0)
    ap.add_argument("--dt-clear", dest="dt_clear", type=float, default=0.0, help="rail undersize per side (mm); 0 = TPU press fit")
    ap.add_argument("--screw-depth", dest="screw_depth", type=float, default=8.0)
    ap.add_argument("--axis-angle", dest="axis_angle", type=float, default=27.0, help="--single: finger axis through the hub centre, deg from -y towards -x (hub/neck axis of the original ~27)")
    ap.add_argument("--base-dist", dest="base_dist", type=float, default=28.0, help="--single: distance hub centre -> blade base along the axis (mm)")
    ap.add_argument("--single", action="store_true", help="one-piece, one-material (TPU) finger for printers without multi-filament")
    ap.add_argument("--ear-extra", dest="ear_extra", type=float, default=1.5, help="--single: extra ear thickness added outward (mm); use screws that much longer + washers")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "stl"))
    p = ap.parse_args()
    os.makedirs(p.out, exist_ok=True)
    side = "L" if p.left else "R"
    for name, shape in build(p).items():
        path = os.path.join(p.out, f"finger_{side}_{name}.stl")
        cq.exporters.export(shape, path, tolerance=0.01, angularTolerance=0.1)
        print(path)


if __name__ == "__main__":
    main()
