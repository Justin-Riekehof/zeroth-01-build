#!/usr/bin/env python3
"""Two-finger parallel gripper for one Feetech STS3215 (bus servo), all PLA.

Mechanism: toothed parallelogram, no rods.
  * G1 sits on the servo horn, G2 (idler, same size) meshes with it -> opposite rotation +-phi.
  * Each gear carries a crank (length C). A second link (same length, pivot P2 on the plate)
    runs parallel to it. The finger is the coupler of that parallelogram, so its orientation
    never changes: the pad faces stay parallel to each other and to the roll axis.
  * Tip path is a circular arc: it moves in y by C*sin(phi) and back in x by C*(1-cos(phi)).

Frame (mm): +x towards the fingertips (= wrist roll axis), +y left, +z up (away from servo
bottom). z=0 is the servo top face. The roll axis is (y=0, z=ROLL_Z).

Usage (repo root, CAD env):  .cad/bin/python hardware/gripper/make_gripper.py [--check]
Writes stl/*.stl (print orientation noted in README.md).
"""
import argparse
import math
import os

import cadquery as cq
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "stl")

# ---- servo (STS3215, measured on the robot CAD mesh; see README) -----------------------
SV_L, SV_W, SV_H = 45.22, 24.72, 32.75  # body (z=0 = top face, below the horn plate), bump below not counted
SV_BUMP_D = 18.0                        # rear-shaft bump under the body (Ø16.5) -> hole in the tray floor
SV_SHAFT_FROM_FRONT = 9.85              # shaft centre to front end face (along x)
SV_CLR = 0.25                           # clearance per side in the tray

# ---- kinematics -------------------------------------------------------------------------
M, Z = 2.0, 14                          # gear module / teeth  -> pitch dia 28
A = M * Z / 2                           # gear axes at y=+-A
C = 34.0                                # crank / link length
S = 26.0                                # P1->P2 distance (coupler length between pins)
T = 12.0                                # finger width in y (= width of the pin ear, so both faces are flat)
PAD = 1.5                               # TPU pad thickness
PHI_MAX = 50.0                          # open stop (deg)
PHI_MIN = math.degrees(math.asin((PAD + T / 2 + 0.25 - A) / C))  # pads 0.5 mm apart
ROLL_Z = -16.0                          # servo body is centred on the roll axis
PHI_STEPS = 12

# ---- layers (z) --------------------------------------------------------------------------
PLATE_Z = (0.0, 4.45)                   # one thick plate everywhere (cap heads sit 2.9 mm deep, gear plane starts at 4.85)
Z_UP = 2.2                              # gear plane lifted so M3 cap-head screws (3 mm) fit under it
GEAR_Z = (2.65 + Z_UP, 15.0 + Z_UP)
ARM_Z = (2.65 + Z_UP, 10.0 + Z_UP)
PAD_TOP = PLATE_Z[1]                     # cranks (on the gears), above the plate
LINK_Z = (-12.3, -5.3)                  # parallel links, BELOW the plate (no collinear overlap with cranks)
CPL_Z = (10.4 + Z_UP, 18.4 + Z_UP)                    # coupler / finger bar
PIN_D, BORE_D = 6.0, 6.3                # crank pins
G2_PIN_D, G2_BORE_D = 10.0, 10.3        # idler axle: fat, on a thickened plate pad (it carries the tooth force)
PIN8_D, BORE8_D = 8.0, 8.3              # link pins (longer lever)
CAP_T = 4.5                             # M3 cap head sits in a 3.2 mm counterbore

HORN_R, HORN_HOLE_D, HORN_BORE_D = 7.1, 3.2, 7.4   # M3 clearance
HORN_ANG = [70, 160, 250, 340]

P1 = (0.0, A)
P1B = (0.0, -A)
P2A = (S, A)
P2B = (S, -A)


# ---- helpers -----------------------------------------------------------------------------
def cyl(x, y, d, z0, z1):
    return cq.Workplane("XY").workplane(offset=z0).center(x, y).circle(d / 2).extrude(z1 - z0)


def box(x0, x1, y0, y1, z0, z1):
    return cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0, centered=False).translate((x0, y0, z0))


def arm(x0, y0, x1, y1, w, z0, z1):
    """Straight bar with round ends between two points."""
    dx, dy = x1 - x0, y1 - y0
    L = math.hypot(dx, dy)
    bar = (cq.Workplane("XY").workplane(offset=z0).center(L / 2, 0).slot2D(L + w, w, 0).extrude(z1 - z0))
    return bar.rotate((0, 0, 0), (0, 0, 1), math.degrees(math.atan2(dy, dx))).translate((x0, y0, 0))


def soft(wp, sel, r):
    """Fillet the selected edges; fall back to smaller radii if the kernel refuses (never fails the build)."""
    for k in (1.0, 0.7, 0.5, 0.3):
        try:
            return (wp.edges(sel) if sel else wp.edges()).fillet(r * k)
        except Exception:
            continue
    print("  (fillet skipped:", sel, r, ")")
    return wp


def soft_c(wp, sel, c):
    """Chamfer fallback."""
    for k in (1.0, 0.6, 0.3):
        try:
            return (wp.edges(sel) if sel else wp.edges()).chamfer(c * k)
        except Exception:
            continue
    return wp


def soft_at(wp, x, z, r, y0, y1):
    """Fillet the single edge parallel to Y through (x, z) (profile corner of an XZ-profile solid)."""
    sel = cq.selectors.BoxSelector((x - 0.4, y0 - 1, z - 0.4), (x + 0.4, y1 + 1, z + 0.4))
    for k in (1.0, 0.7, 0.5, 0.3):
        try:
            return wp.edges(sel).fillet(r * k)
        except Exception:
            continue
    print("  (corner fillet skipped at", x, z, ")")
    return wp


def hull_poly(p0, r0, p1, r1, z0, z1):
    """Tapered arm: convex hull of two circles, extruded z0..z1."""
    from shapely.geometry import Point
    from shapely.ops import unary_union
    poly = unary_union([Point(*p0).buffer(r0, 40), Point(*p1).buffer(r1, 40)]).convex_hull
    sol = cq.Workplane("XY").workplane(offset=z0).polyline(list(poly.exterior.coords)[:-1]).close().extrude(z1 - z0)
    return soft(sol, "not |Z", min(1.4, (z1 - z0) / 4))


def inv(a):
    return math.tan(a) - a


def gear(cx, cy, phase_deg, z0, z1, backlash=0.2):
    """Involute spur gear (full circle), tooth centre at phase + k*360/Z. 20 deg pressure angle."""
    alpha = math.radians(20)
    r = M * Z / 2
    rb = r * math.cos(alpha)
    ra = r + M
    rr = r - 1.25 * M
    half = math.pi / (2 * Z)
    pts = []
    n = 8
    for k in range(Z):
        th = math.radians(phase_deg) + 2 * math.pi * k / Z
        r0 = max(rb, rr)
        rs = np.linspace(r0, ra, n)
        psi = [half + inv(alpha) - inv(math.acos(min(1.0, rb / x))) - backlash / (2 * x) for x in rs]
        left = [(x * math.cos(th - p), x * math.sin(th - p)) for x, p in zip(rs, psi)]
        right = [(x * math.cos(th + p), x * math.sin(th + p)) for x, p in zip(rs[::-1], psi[::-1])]
        # root: radial line from the root circle to the base-circle start, then the flank
        root_l = (rr * math.cos(th - psi[0]), rr * math.sin(th - psi[0]))
        root_r = (rr * math.cos(th + psi[0]), rr * math.sin(th + psi[0]))
        pts += [root_l] + left + right + [root_r]
        # root arc to the next tooth
        th2 = th + 2 * math.pi / Z
        p0 = half + inv(alpha) - inv(math.acos(min(1.0, rb / max(rb, rr)))) - backlash / (2 * max(rb, rr))
        a0, a1 = th + psi[0], th2 - psi[0]
        for a in np.linspace(a0, a1, 4)[1:-1]:
            pts.append((rr * math.cos(a), rr * math.sin(a)))
    pts = [(cx + x, cy + y) for x, y in pts]
    gw = cq.Workplane("XY").workplane(offset=z0).polyline(pts).close().extrude(z1 - z0)
    return soft_c(gw, "not |Z", 0.45)          # small chamfer on both faces (elephant foot, feels finished)


def pilot(x, y, z_top, depth, d=2.6):
    return cyl(x, y, d, z_top - depth, z_top + 0.01)


# ---- parts (all at phi = 0) ---------------------------------------------------------------
def drive(side):
    """G1 (side=+1, on the horn) or G2 (side=-1, idler on a plate post) with its crank."""
    cx, cy = (0.0, side * A)
    phase = 12.857 if side > 0 else 0.0   # opposite phase so the teeth interleave at y=0
    g = gear(cx, cy, phase, *GEAR_Z)
    g = g.union(hull_poly((cx, cy), 11.0, (cx + C, cy), 6.0, *ARM_Z))       # tapered crank, blends into the gear root
    g = g.union(cyl(cx + C, cy, PIN_D, ARM_Z[1] - 0.01, CPL_Z[1] + 0.2))
    g = g.cut(pilot(cx + C, cy, CPL_Z[1] + 0.2, 9))
    if side > 0:  # horn: 4 screw holes + centre relief, counterbored from the top
        g = g.union(cyl(cx, cy, 18.4, 2.65, GEAR_Z[0] + 0.01))       # hub spacer down to the horn top (2.65); it turns inside the Ø19.6 hole of the plate
        g = g.cut(cyl(cx, cy, HORN_BORE_D, 2.6, GEAR_Z[0] + 4.0))
        for a in HORN_ANG:
            x, y = cx + HORN_R * math.cos(math.radians(a)), cy + HORN_R * math.sin(math.radians(a))
            g = g.cut(cyl(x, y, HORN_HOLE_D, 2.6, GEAR_Z[1] + 0.01))
            g = g.cut(cyl(x, y, 5.9, GEAR_Z[1] - 5.4, GEAR_Z[1] + 0.01))   # M3x12 cap head, deep counterbore
    else:        # idler: bore for the plate post
        g = g.cut(cyl(cx, cy, G2_BORE_D, GEAR_Z[0] - 0.01, GEAR_Z[1] + 0.01))
        g = g.cut(cyl(cx, cy, 17.6, GEAR_Z[0] - 0.01, GEAR_Z[0] + 3.8))     # clears the conical foot of the axle
    return g


def link(side):
    """Parallel link below the plate: bore on the plate post at P2, Ø8 pin up through the finger at F2."""
    cy = side * A
    lk = hull_poly((S, cy), 7.2, (S + C, cy), 6.0, *LINK_Z)               # tapered link
    lk = lk.union(cyl(S + C, cy, PIN8_D, LINK_Z[1] - 0.01, CPL_Z[1] + 0.2))
    lk = lk.cut(pilot(S + C, cy, CPL_Z[1] + 0.2, 12))
    return lk.cut(cyl(S, cy, BORE8_D, LINK_Z[0] - 0.01, LINK_Z[1] + 0.01))


TIP_X0, TIP_LEN, TIP_Z = 16.0, 35.0, (-22.0, -10.0)   # column width, tip bar length/height
COL_GAP = 7.0                                         # column starts this far in front of F2


JOINT_SCREW_DX = (4.0, 12.0)            # M3x12 positions along x from the column start (on the finger centre line)
JOINT_PEG_DX, JOINT_PEG_DY = 8.0, 3.5   # two printed dowels Ø4 take the torque about the x axis
PEG_D, PEG_H = 4.0, 3.0


def _joint_x0():
    return C + S + COL_GAP              # column start (x)


def coupler(rim=1.2):
    """Koppelstange (same part for finger A and B, built at side +1): pin ears at F1/F2 and a tongue that lies on
    the column seat of the finger tip and is held by 2x M3x12 + 2 dowels."""
    side = +1
    fy = side * A
    f1, f2 = C, C + S
    zt, zb = CPL_Z[1], CPL_Z[0]
    x0 = _joint_x0()
    xe = x0 + TIP_X0
    y0, y1 = fy - T / 2, fy + T / 2
    ears = (cq.Workplane("XY").workplane(offset=zb).center((f1 + f2) / 2, fy)
            .slot2D((f2 - f1) + T, T, 0).extrude(zt - zb))             # exact stadium, R = T/2
    tongue = soft(box(f2, xe, y0, y1, zb, zt), "|Z and >X", 3.0)
    f = ears.union(tongue)
    if rim:
        for face in (">Z", "<Z"):
            try:
                f = f.faces(face).edges().fillet(rim)
            except Exception:
                pass
    f = f.cut(cyl(f1, fy, BORE_D, zb - 0.01, zt + 0.01))
    f = f.cut(cyl(f2, fy, BORE8_D, zb - 0.01, zt + 0.01))
    for dx in JOINT_SCREW_DX:                                         # M3 cap head, 3.4 mm counterbore
        f = f.cut(cyl(x0 + dx, fy, 3.4, zb - 0.01, zt + 0.01))
        f = f.cut(cyl(x0 + dx, fy, 6.2, zt - 3.4, zt + 0.01))
    for s_ in (+1, -1):                                               # alignment dowels on the underside
        f = f.union(cyl(x0 + JOINT_PEG_DX, fy + s_ * JOINT_PEG_DY, PEG_D, zb - PEG_H, zb + 0.01))
    return f


def tip(side, rim=1.2, seat=None):
    """Fingerstück: column with a flat seat for the coupler, elbow and tip bar (pad side faces y=0)."""
    fy = side * A
    y0, y1 = fy - T / 2, fy + T / 2
    zb = CPL_Z[0]
    x0 = _joint_x0()
    xe = x0 + TIP_X0
    prof = [(x0, zb), (xe, zb), (xe, TIP_Z[1]), (x0 + TIP_LEN, TIP_Z[1]), (x0 + TIP_LEN, TIP_Z[0]), (x0, TIP_Z[0])]
    f = cq.Workplane("XZ").workplane(offset=-y1).polyline(prof).close().extrude(T)
    f = soft_at(f, xe, TIP_Z[1], 5.0, y0, y1)                         # inner elbow
    f = soft_at(f, x0, TIP_Z[0], 4.0, y0, y1)                         # heel
    f = soft_at(f, x0 + TIP_LEN, TIP_Z[1], 3.0, y0, y1)               # tip corners
    f = soft_at(f, x0 + TIP_LEN, TIP_Z[0], 3.0, y0, y1)
    if seat:
        f = soft_at(f, x0, zb, seat, y0, y1)                          # soft edges of the seat
        f = soft_at(f, xe, zb, seat, y0, y1)
    if rim:
        for face in (">Y", "<Y"):
            try:
                f = f.faces(face).edges().fillet(rim)
            except Exception:
                pass
    for dx in JOINT_SCREW_DX:                                         # pilot holes for the M3x12
        f = f.cut(cyl(x0 + dx, fy, 2.6, zb - 8.0, zb + 0.01))
    for s_ in (+1, -1):                                               # pockets for the dowels
        f = f.cut(cyl(x0 + JOINT_PEG_DX, fy + s_ * JOINT_PEG_DY, PEG_D + 0.2, zb - PEG_H - 0.4, zb + 0.01))
    inner = -1 if side > 0 else 1                   # direction towards y=0
    yface = fy + inner * T / 2
    for dx in (10, 26):                             # pad seat: two 3.1 holes in the inner face of the tip bar
        h = cq.Workplane("XY").add(cq.Solid.makeCylinder(
            1.55, 4.0, cq.Vector(x0 + dx, yface, sum(TIP_Z) / 2), cq.Vector(0, -inner, 0)))
        f = f.cut(h)
    return f


def pad(side):
    """TPU pad 1.5 x 12 x 36 with two pegs; pegs point away from the contact face."""
    p = soft(box(0, 34, 0, PAD, -6, 6), "|Y", 3.0)
    for dx in (9, 25):
        p = p.union(cq.Workplane("XY").add(cq.Solid.makeCylinder(1.45, 3.6, cq.Vector(dx, PAD - 0.01, 0), cq.Vector(0, 1, 0))))
    return p


def cap(d=10.0):
    c = cyl(0, 0, d, 0, CAP_T).faces(">Z").edges().chamfer(0.7)
    c = c.cut(cyl(0, 0, 3.4, -0.01, CAP_T + 0.01))
    return c.cut(cyl(0, 0, 6.0, CAP_T - 3.2, CAP_T + 0.01))


# ---- housing ---------------------------------------------------------------------------------
# S2 lies across the gripper: long axis along y (shaft end at +y), width along x. The body then spans
# y = -21.4 .. +23.9 around both gear axes (y = +-14) and sits centred on the roll axis.
SV_XOFF = 0.32                          # body centre is 0.32 mm off the shaft axis (robot CAD mesh)
CAV_X0, CAV_X1 = SV_XOFF - SV_W / 2 - SV_CLR, SV_XOFF + SV_W / 2 + SV_CLR
CAV_Y0 = A - (SV_L - SV_SHAFT_FROM_FRONT) - SV_CLR
CAV_Y1 = A + SV_SHAFT_FROM_FRONT + SV_CLR
WALL, FLOOR = 4.0, 2.5
FRONT_WALL = 5.2                        # thicker front wall: it carries all four plate screws (the plate reaches far past it)
TRAY_X0, TRAY_X1 = CAV_X0 - WALL, CAV_X1 + FRONT_WALL
TRAY_Y0, TRAY_Y1 = CAV_Y0 - WALL, CAV_Y1 + WALL
CAV_Z0 = -(SV_H + 0.55)
TRAY_Z0 = CAV_Z0 - FLOOR


REAR_T = 2.6                            # the rear wall is thicker (4 + 2.6 = 6.6 mm) as one part with the tray: more material behind the roll-horn heads
                                        # and under the rear plate screws; the plate ends flush with the new rear face
ROLL_Y = 0.0                            # roll axis (y_g, z_g)
BOSS_D, BOSS_H = 22.0, 2.8              # boss on the rear face that sits on the horn: R11 backs all four counterbores (they reach R10); 0.8 wall + 2.8 boss = 3.6 mm under each head, M3x6 reaches ~2.4 into the 2.6 mm horn plate
BOSS_FLARE, BOSS_ROUND = 0.8, 0.8       # concave blend into the wall, convex round of the boss tip edge (no sharp edges); the retainer gets a round window for the boss
HORN_R_ROLL, HORN_HOLE_ROLL, HORN_CB_D = 7.0, 3.4, 6.0   # roll-horn screw circle (same horn as the elbow: 4 x R7), round holes; the spline phase only shifts the roll zero (<= 7.2 deg)
HORN_CB = 3.2                           # head counterbore depth from the cavity face (head 3 mm, sits 0.2 deep)
REAR_Y0 = TRAY_Y0
# plate screws: 2 in the rear wall (6.6 mm thick, the plate ends flush with its rear face, 4.3 mm from the screw centre to the
# edge: 1.2 mm of plate around the Ø6.2 counterbore) + 2 in the front wall (5.2 mm, the plate reaches far past it).
REAR_SCREW_X = TRAY_X0 + 1.7            # 0.3 mm behind the wall centre: 1.2 mm of plate around the counterbore, 1.0 mm of wall on the servo side
REAR_SCREW_Y = (-15.0, 20.0)
SCREWS = [(REAR_SCREW_X, REAR_SCREW_Y[0]), (REAR_SCREW_X, REAR_SCREW_Y[1]), (TRAY_X1 - 3.0, -19.5), (TRAY_X1 - 3.0, 19.5)]


def boss(xr):
    """Roll-horn boss as a revolved profile: concave blend into the wall, flat tip, rounded tip edge."""
    r, f, q, h = BOSS_D / 2, BOSS_FLARE, BOSS_ROUND, BOSS_H
    c = math.sqrt(0.5)
    prof = (cq.Workplane("XY").moveTo(xr + 0.01, 0).lineTo(xr + 0.01, r + f).lineTo(xr, r + f)
           .threePointArc((xr - f + f * c, r + f - f * c), (xr - f, r))
           .lineTo(xr - h + q, r)
           .threePointArc((xr - h + q - q * c, r - q + q * c), (xr - h, r - q))
           .lineTo(xr - h, 0).close())
    return prof.revolve(360, (0, 0, 0), (1, 0, 0)).translate((0, ROLL_Y, ROLL_Z))


def tray():
    """Servo tray, rear wall closed (carries the roll-horn pattern), servo drops in from the top."""
    # one outer shell including the thicker rear wall: the same rounding runs around the whole body, no seam, no add-on block
    t = box(TRAY_X0 - REAR_T, TRAY_X1, TRAY_Y0, TRAY_Y1, TRAY_Z0, 0)
    t = soft(t, "|Z", 5.0)
    t = soft(t, "<Z", 3.0)
    t = soft(t, ">Z", 1.2)
    t = t.cut(box(CAV_X0, CAV_X1, CAV_Y0, CAV_Y1, CAV_Z0, 0.1))
    t = t.cut(cyl(0, A, SV_BUMP_D, TRAY_Z0 - 0.1, CAV_Z0 + 0.1))
    for x, y in SCREWS:
        t = t.cut(pilot(x, y, 0, 15))          # M3x16
    # roll-horn boss on the rear face
    xr = TRAY_X0 - REAR_T
    t = t.union(boss(xr))
    t = t.cut(cq.Workplane("YZ").workplane(offset=xr - BOSS_H - 0.01).center(ROLL_Y, ROLL_Z).circle(3.5).extrude(1.6))   # centre-screw relief Ø7.0 (horn boss Ø6.45): 1.8 mm web to the four screw holes
    for k in range(4):                   # round holes through wall + boss, heads counterbored from the cavity (M3x6, hex key from above)
        ang = 90 * k
        yy, zz = ROLL_Y + HORN_R_ROLL * math.cos(math.radians(ang)), ROLL_Z + HORN_R_ROLL * math.sin(math.radians(ang))
        slot = (cq.Workplane("YZ").workplane(offset=xr - BOSS_H - 0.01).center(yy, zz)
                .circle(HORN_HOLE_ROLL / 2).extrude(WALL + REAR_T + BOSS_H + 0.02))
        cb = (cq.Workplane("YZ").workplane(offset=CAV_X0 - HORN_CB).center(yy, zz)
              .circle(HORN_CB_D / 2).extrude(HORN_CB + 0.1))
        t = t.cut(slot).cut(cb)
    return t


POST_SCREW = 5.0
PLATE_X0, PLATE_X1 = TRAY_X0 - REAR_T, S + 13      # flush with the rear face
PLATE_Y0, PLATE_Y1 = TRAY_Y0, TRAY_Y1


def top_plate():
    p = box(PLATE_X0, PLATE_X1, PLATE_Y0, PLATE_Y1, *PLATE_Z)
    p = soft(p, "|Z and <X", 5.0)                       # rear corners follow the tray outline
    p = soft(p, "|Z and >X", 8.0)
    for face in (">Z", "<Z"):
        try:
            p = p.faces(face).edges().fillet(1.0)
        except Exception:
            pass
    # the servo's raised top bar (38 x 18.5, 1.85 high) fits into a blind pocket from below: the plate stays closed
    # on top, so the idler axle sits on an unbroken 4.45 mm plate. Only the G1 hub (horn disc + spacer) gets a Ø19.6 hole.
    p = p.cut(box(-9.3, 9.9, A - 30.6, A + 8.6, PLATE_Z[0] - 0.01, 2.3))                # bar strip (bar x = -8.9 .. 9.6)
    p = p.cut(cyl(P1[0], P1[1], 20.6, PLATE_Z[0] - 0.01, 2.3))                           # round pocket around the G1 hole (r 10.3 vs hole r 9.8)
    p = p.cut(cyl(P1[0], P1[1], 19.6, PLATE_Z[0] - 0.01, PLATE_Z[1] + 0.01))      # lies completely inside the pocket: same wall height all around, no step
    for x, y in SCREWS:                                                           # M3 cap head, 2.9 mm counterbore
        p = p.cut(cyl(x, y, 3.4, PLATE_Z[0] - 0.01, PLATE_Z[1] + 0.01))
        p = p.cut(cyl(x, y, 6.2, PLATE_Z[1] - 2.9, PLATE_Z[1] + 0.01))
    # G2 idler axle (Ø10) grows out of the plate: conical foot instead of a step
    x, y = P1B
    top = GEAR_Z[1] + 0.3
    p = p.union(cq.Workplane("XY").add(cq.Solid.makeCone(8.0, G2_PIN_D / 2, 3.0, cq.Vector(x, y, PAD_TOP - 0.01), cq.Vector(0, 0, 1))))
    p = p.union(cyl(x, y, G2_PIN_D, PAD_TOP - 0.01, top))
    p = p.cut(pilot(x, y, top, 10))
    # the link posts are separate parts (flange screwed to the plate underside): 2 M3x6 per post
    for x, y in (P2A, P2B):
        for dx in (-POST_SCREW, POST_SCREW):
            p = p.cut(cyl(x + dx, y, 3.4, PLATE_Z[0] - 0.01, PLATE_Z[1] + 0.01))
            p = p.cut(cyl(x + dx, y, 6.2, PLATE_Z[1] - 2.9, PLATE_Z[1] + 0.01))
    return p


def link_post():
    """Hanging pivot for a link: Ø14 flange (screwed up into the plate) + Ø8 shaft down, M3 pilot at the tip."""
    bot = LINK_Z[0] - 0.3
    c = cyl(0, 0, 14, -5.0, PLATE_Z[0] - 0.01).faces("<Z").edges().chamfer(0.8)
    c = c.union(cyl(0, 0, PIN8_D, bot, -4.99))
    c = c.cut(cq.Workplane("XY").add(cq.Solid.makeCylinder(1.3, 12, cq.Vector(0, 0, bot - 0.01), cq.Vector(0, 0, 1))))
    for dx in (-POST_SCREW, POST_SCREW):
        c = c.cut(cq.Workplane("XY").add(cq.Solid.makeCylinder(1.3, 4.7, cq.Vector(dx, 0, -4.6), cq.Vector(0, 0, 1))))
    return c


PARTS = {
    "link_post_x4": link_post,
    "housing_tray_x2": tray, "housing_top_plate_x2": top_plate,
    "drive_G1_x2": lambda: drive(+1), "drive_G2_x2": lambda: drive(-1),
    "link_A_x2": lambda: link(+1), "link_B_x2": lambda: link(-1),
    "finger_coupler_x4": coupler, "finger_tip_A_x2": lambda: tip(+1), "finger_tip_B_x2": lambda: tip(-1),
    "cap_d10_x4": lambda: cap(10.0), "cap_d12_x8": lambda: cap(12.0), "cap_d14_x2": lambda: cap(14.0), "pad_tpu_x4": lambda: pad(+1),
}


def export():
    os.makedirs(OUT, exist_ok=True)
    for name, fn in PARTS.items():
        cq.exporters.export(fn(), os.path.join(OUT, f"{name}.stl"), tolerance=0.02, angularTolerance=0.1)
        print("wrote", name)


# ---- kinematic collision sweep -------------------------------------------------------------------
def load_servo(transverse=True):
    """STS3215 mesh from the robot CAD, placed with the shaft at P1 and the body top face at z=0."""
    import trimesh
    sc = trimesh.load(os.path.join(HERE, "..", "..", "resources", "cad", "z001-opus-m-93de7567.glb"))
    m = None
    for n in sc.graph.nodes_geometry:
        if n.startswith("left_elbow_yaw_motor"):
            T, g = sc.graph[n]
            mm = sc.geometry[g].copy()
            mm.apply_transform(T)
            mm.apply_scale(1000)
            if len(mm.faces) > 5000:
                m = mm
    m.apply_transform(np.linalg.inv(m.bounding_box_oriented.primitive.transform))   # axes: 0=width 1=height 2=length
    R = np.array([[0, 0, 1, 0], [1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1.0]])         # (ax0,ax1,ax2) -> (y,z,x)
    m.apply_transform(R)
    m.apply_translation([-12.75, -0.32, -16.25])
    if transverse:
        m.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2, [0, 0, 1]))   # long axis -> +y
    m.apply_translation([0, A, 0])
    return m


def check():
    import trimesh
    from trimesh.transformations import rotation_matrix as rm, translation_matrix as tm

    def load(n):
        return trimesh.load(os.path.join(OUT, n + ".stl"))

    base = {n: load(n) for n in PARTS}
    post_a = base["link_post_x4"].copy().apply_translation([*P2A, 0])
    post_b = base["link_post_x4"].copy().apply_translation([*P2B, 0])
    fixed = trimesh.util.concatenate([base["housing_tray_x2"], base["housing_top_plate_x2"], post_a, post_b])
    servo = load_servo()
    pts = servo.sample(30000)
    for n in ("housing_tray_x2", "housing_top_plate_x2", "drive_G1_x2", "drive_G2_x2"):
        k = sum(int(base[n].contains(pts[i:i + 3000]).sum()) for i in range(0, len(pts), 3000))
        print(f"servo surface points inside {n}: {k}")
    print(f"phi range {PHI_MIN:.1f} .. {PHI_MAX:.1f} deg; opening {2*(A + C*math.sin(math.radians(PHI_MAX)) - T/2 - PAD):.1f} mm")
    worst = {}
    for phi in np.linspace(PHI_MIN, PHI_MAX, PHI_STEPS):
        r = math.radians(phi)
        mv = {}
        mv["G1"] = base["drive_G1_x2"].copy().apply_transform(rm(r, [0, 0, 1], [*P1, 0]))
        mv["G2"] = base["drive_G2_x2"].copy().apply_transform(rm(-r, [0, 0, 1], [*P1B, 0]))
        mv["LA"] = base["link_A_x2"].copy().apply_transform(rm(r, [0, 0, 1], [*P2A, 0]))
        mv["LB"] = base["link_B_x2"].copy().apply_transform(rm(-r, [0, 0, 1], [*P2B, 0]))
        cA = base["finger_coupler_x4"].copy()
        cB = base["finger_coupler_x4"].copy().apply_translation([0, -2 * A, 0])        # identical part, mirrored position
        fA = trimesh.util.concatenate([cA, base["finger_tip_A_x2"]])
        fB = trimesh.util.concatenate([cB, base["finger_tip_B_x2"]])
        mv["FA"] = fA.apply_transform(tm([C * (math.cos(r) - 1), C * math.sin(r), 0]))
        mv["FB"] = fB.apply_transform(tm([C * (math.cos(r) - 1), -C * math.sin(r), 0]))
        names = list(mv)
        pairs = [(a, b) for i, a in enumerate(names) for b in names[i + 1:]] + [(a, "fixed") for a in names]
        mv["fixed"] = fixed
        for a, b in pairs:
            if a == "G1" and b == "G2":
                continue    # teeth mesh with clearance; checked separately below
            try:
                v = trimesh.boolean.intersection([mv[a], mv[b]], engine="manifold").volume
            except Exception as e:      # empty intersection
                v = 0.0
            if v > 0.5:
                worst[(a, b)] = max(worst.get((a, b), 0), v)
        # tooth mesh: min distance estimate via small intersection volume
        v = trimesh.boolean.intersection([mv["G1"], mv["G2"]], engine="manifold").volume
        worst[("G1", "G2")] = max(worst.get(("G1", "G2"), 0), v)
    print("max overlaps (mm^3):", {f"{a}-{b}": round(v, 1) for (a, b), v in worst.items()} or "none")
    return worst


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--no-export", action="store_true")
    a = ap.parse_args()
    if not a.no_export:
        export()
    if a.check:
        check()
