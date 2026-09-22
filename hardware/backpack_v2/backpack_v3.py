#!/usr/bin/env python3
"""Z-Bot "Pixel" — Backpack v3: single-layer backpack + torso insert (CadQuery source).

v3 uses the torso interior (the original battery / Electronics-Mount / MilkV bay is empty
in this build): the Raspberry Pi 4B and the Pololu buck sit on a printed carrier INSIDE
the torso, so the backpack shrinks to ONE 28 mm layer (36 mm total depth instead of 66.5).

Parts (robot frame of the pinned assembly, mm: +X left, +Y back, +Z up, torso back wall Y 38.1):
  1. base    — mounting frame (4x M3 into the torso inserts), LiPo drawer (side-loading, -X),
               XY-CD63 centred, Waveshare + warner on the right (-X), anti-spark switch on
               the left (+X), fuse trough across the top.
  2. lid     — rear cover: display + button windows, warner grille, vents, 5 V test pins.
  3. insert  — torso carrier for Pi 4B (vertical, SD edge up towards the neck gap) and
               Pololu; fixed through the torso window to the base with 2x M3.
STLs are exported in print orientation (bed = -Y face), no mirroring.
"""
from __future__ import annotations
import json, os
import cadquery as cq

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "stl_v3")

# ---------------- torso interface (from the pinned GLB, see README) ----------------
Y0 = 38.1
TORSO_HOLES = [(-35.01, 261.56), (35.01, 261.56), (-47.24, 330.34), (47.24, 330.34)]
WIN_X, WIN_Z = (-27.0, 27.0), (251.6, 337.0)          # torso back window
Y_WALL_IN = 29.6                                        # inner face of the 8.5 mm back wall
CAVITY = dict(x=(-36.0, 36.0), y=(-10.4, Y_WALL_IN), z=(251.6, 373.0))   # conservative interior

# ---------------- envelope & stack ----------------
XW = 80.0; Z_BOT, Z_TOP = 254.0, 416.0        # v3.5: obere Kante 10 mm hoeher -> mehr Raum ueber dem XY-CD63 (Klemmen/Relais)
T_PLATE, T_BOSS, T_OW, T_IW, D1, T_LID = 3.0, 3.0, 2.5, 2.0, 44.0, 2.0        # D1 44: 28 mm parts + 16 mm cable layer
Y_PL1 = Y0 + T_PLATE; Y_FL1 = Y_PL1 + T_BOSS; Y_RIM = Y_FL1 + D1; Y_LID = Y_RIM + T_LID   # 41.1 / 44.1 / 88.1 / 90.1
Y_CAB = 73.0                                            # cable layer starts here (above the 28 mm XY-CD63)
XI = XW - T_OW; ZI0, ZI1 = Z_BOT + T_OW, Z_TOP - T_OW    # ±77.5, 256.5..400.5
Z_TRAY1 = ZI0 + 38.0; Z_DIV1 = Z_TRAY1 + T_IW            # 294.5 / 296.5
PACK_X = (-76.5, 29.5)                                  # LiPo rests against the -X wall, drawer opens +X
STRAP_X = (31.0, 35.0)
WARN = dict(x=(38.0, 73.0), z=(266.0, 288.0), y=(Y_CAB, Y_CAB + 14.0))       # v3.6: warner im unteren Fach, hinteres Band, +X neben dem Akku (kurze Leitung zum Balancer); Stecker -> -X
WARN_RIBS = ((36.0, 38.0), (73.0, 75.0))                                     # Cradle-Rippen am Deckel, z 265..290 (unter z 265 sitzt der Eckklotz)
CUT_X1, CUT_Z0 = 31.0, 340.0                            # XY-CD63 62x56, VIN edge +X, moved up: window stays free
CUT_TERM_Z = 385.0                                      # assumed terminal height (upper region of the module) [S]
WS_C = (-6.0, 320.5); WS_DX, WS_DZ = 37.0, 28.0         # Waveshare unrotated 42x33 over the window, connectors on its -X edge [S]
WS_PLUG_X = (-57.0, -27.0)                              # DC / USB-C plug zone
PASS_A = dict(x=(15.0, 27.0), z=(300.0, 334.0))          # window pass-through: servo bus, Pi USB, Pololu 12 V, test leads
SW_BODY = dict(x=(-72.0, -50.0), z=(336.0, 381.0), y=(73.1, 88.1))           # switch vertical, cradled on the LID, slider -> lid; XT60 pair hangs below it
SW_RIBS = ((-74.0, -72.0), (-50.0, -48.0))
FUSE_HOLDER = dict(x=(-47.0, -7.0), z=(259.0, 274.0), y=(73.1, 88.1))        # holder in the cable layer above the LiPo, cradled on the LID, cap through the lid
FUSE_RIBS = ((-49.0, -47.0), (-7.0, -5.0))
XT_LIPO = dict(x=(-4.0, 36.0), z=(259.0, 274.0), y=(73.0, 81.0))             # v3.6: XT60-Paar LiPo <-> Sicherung 19 mm nach -X gerueckt, damit der Warner neben den Akku passt
XT_LIPO_RIBS = ((-6.0, -4.0), (36.0, 38.0))                                  # +X-Rippe ist zugleich die -X-Rippe des Warners
XT_SW = dict(x=(-69.0, -53.0), z=(276.0, 316.0), y=(73.0, 81.0))             # switch <-> fuse XT60 pair, vertical below the switch (dips through a divider notch)
XT_SW_RIBS = ((-71.0, -69.0), (-53.0, -51.0))
CORNER_SCREWS = [(-74.0, 260.0), (74.0, 260.0), (-74.0, 410.0), (74.0, 410.0)]
INSERT_SCREWS = [(-12.0, 262.0), (12.0, 262.0)]
PI_X, PI_Z = (-33.0, 23.0), (280.0, 365.0)              # Pi shifted 5 mm to -X: room for a right-angle USB-C plug on the +X edge
PI_Y_BOARD = 16.2
POL_C = (66.0, 362.0)                                   # Pololu in the backpack (+X column, near the 5 V test pins); pads at its top edge
D_M3_CLEAR, D_M3_HEAD, H_M3_HEAD = 3.4, 6.6, 3.2
D_M3_INS, H_M3_INS, D_M25_TAP, D_M2_TAP = 4.0, 6.0, 2.2, 1.7
# XY-CD63 wird von hinten (Torso-Seite) verschraubt: M3 durch Platte + Boss, Zylinderkopf 5.5 x 3 in einer Senkung
D_CUT_SHAFT, D_CUT_CB, H_CUT_CB, D_CUT_BOSS = 3.3, 6.0, 3.4, 9.0
CUT_HOLES = [(CUT_X1 - 2.0, CUT_Z0 + 3.5), (CUT_X1 - 60.0, CUT_Z0 + 3.5),
             (CUT_X1 - 2.0, CUT_Z0 + 41.5), (CUT_X1 - 60.0, CUT_Z0 + 41.5)]   # Lochbild des Moduls (2|60, 3.5|41.5 ab Ecke)

def box(x0, x1, y0, y1, z0, z1):
    assert x1 > x0 and y1 > y0 and z1 > z0, (x0, x1, y0, y1, z0, z1)
    return cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0, centered=False).translate((x0, y0, z0))
def cyl_y(x, z, y0, y1, d):
    return cq.Workplane("XY").add(cq.Solid.makeCylinder(d / 2, y1 - y0, cq.Vector(x, y0, z), cq.Vector(0, 1, 0)))
def slot_y(x, z, y0, y1, w, lx):
    s = box(x - lx / 2 + w / 2, x + lx / 2 - w / 2, y0, y1, z - w / 2, z + w / 2)
    return s.union(cyl_y(x - lx / 2 + w / 2, z, y0, y1, w)).union(cyl_y(x + lx / 2 - w / 2, z, y0, y1, w))
def teardrop_y(x, z, y0, y1, w):
    """support-free standoff for a part printed standing up (robot Z = print Z): flat top, 45 deg roof below"""
    h = w / 2
    pts = [(x - h, z + h), (x + h, z + h), (x + h, z), (x, z - h), (x - h, z)]
    return cq.Workplane("XZ", origin=(0, y0, 0)).polyline(pts).close().extrude(-(y1 - y0))
R_CORNER, R_POCKET, C_EDGE = 4.0, 1.6, 0.8   # pocket radius 1.6: not tangent to the M3 insert holes at the corner blocks (x = XI - 1.5)   # v3.2: outer corner radius, inner pocket radius, perimeter chamfer (mm)

def soften(shape, r_corner=R_CORNER, chamfer_faces=(">Y", "<Y"), c=C_EDGE):
    """Round the four edges parallel to Y (the box corners seen from the back) and chamfer the outer perimeter of
    the given faces. Used on the plain outer boxes before the booleans, so the cuts/bosses never touch the fillets."""
    if r_corner: shape = shape.edges("|Y").fillet(r_corner)
    for f in chamfer_faces:
        if c: shape = shape.faces(f).edges().chamfer(c)
    return shape

C_FLARE, R_HOLE = 1.0, 2.0   # v3.3: round-over of every opening's entry edge (mm), corner radius of openings

def rrect(w, h, r):
    r = min(r, 0.45 * min(w, h)); return cq.Sketch().rect(w, h).vertices().fillet(r)

def flare(axis, cu, cv, w, h, r, s, mat, c):
    """Round-over of an opening's entry edge: a loft that widens the w x h opening (cross-section u x v) by c at the
    material surface s (coordinate along `axis`; mat = +1 if the material lies toward +axis) following a quarter
    circle of radius c, plus a straight prism outside the surface so the boolean cut is clean. Built directly on a
    workplane whose normal points out of the material (no rotations -> no inverted solids)."""
    import math
    n = -mat                                          # outward normal along the axis
    if axis == "y":   pl = cq.Plane(origin=cq.Vector(cu, s, cv), xDir=cq.Vector(1, 0, 0), normal=cq.Vector(0, n, 0))
    elif axis == "x": pl = cq.Plane(origin=cq.Vector(s, cu, cv), xDir=cq.Vector(0, 1, 0), normal=cq.Vector(n, 0, 0))
    else:             pl = cq.Plane(origin=cq.Vector(cu, cv, s), xDir=cq.Vector(1, 0, 0), normal=cq.Vector(0, 0, n))
    secs = [rrect(w + 2 * c, h + 2 * c, r + c).moved(cq.Location(cq.Vector(0, 0, 1.3)))]     # straight part outside the surface (1.3: no tangency with the corner-screw holes at x = 76)
    for th in (90.0, 60.0, 30.0, 0.0):              # (offset, depth) on a quarter circle centred c inside the corner
        o, d = c - c * math.cos(math.radians(th)), c - c * math.sin(math.radians(th))
        secs.append(rrect(w + 2 * o, h + 2 * o, r + o).moved(cq.Location(cq.Vector(0, 0, -d))))
    f = cq.Workplane(pl).placeSketch(*secs).loft(ruled=True, combine=True)   # one solid (no union of coincident faces)
    assert f.val().Volume() > 0, "flare inverted"
    return f

def soft_tool(x0, x1, y0, y1, z0, z1, axis, surfaces, c=C_FLARE, r=R_HOLE):
    """Cut tool for an opening a cable may run through: a box with rounded corners (edges parallel to `axis`) and a
    round-over (radius c) of the entry edge at every material surface listed in `surfaces` = [(coord, mat), ...]."""
    dims = {"x": (x0, x1), "y": (y0, y1), "z": (z0, z1)}
    ua, va = {"y": ("x", "z"), "x": ("y", "z"), "z": ("x", "y")}[axis]   # cross-section axes (match the planes in flare())
    (u0, u1), (v0, v1) = dims[ua], dims[va]
    w, h = u1 - u0, v1 - v0; rr = min(r, 0.45 * min(w, h)); cu, cv = (u0 + u1) / 2, (v0 + v1) / 2
    tool = box(x0, x1, y0, y1, z0, z1).edges("|" + axis.upper()).fillet(rr)
    for s_, mat in surfaces:
        tool = tool.union(flare(axis, cu, cv, w, h, rr, s_, mat, c))
    assert tool.val().Volume() > 0, "tool inverted"
    return tool

def soft_cyl(x, z, y0, y1, d, surfaces, c=0.5):
    """Cylindrical hole along Y with a 45-degree countersink of size c at each material surface [(y, mat), ...]."""
    t = cyl_y(x, z, y0, y1, d)
    for s_, mat in surfaces:
        cone = cq.Solid.makeCone(d / 2 + c + 0.6, d / 2, c + 0.6, cq.Vector(x, s_ - mat * 0.6, z), cq.Vector(0, mat, 0))   # starts 0.6 outside the surface
        t = t.union(cq.Workplane("XY").add(cone))
    return t

def chamfer_free(shape, sel, c=0.5):
    """Chamfer the edges of the face(s) selected by `sel` (free edges of ribs, rails, lips); skipped if OCC refuses."""
    try: return (shape.edges(sel) if sel.startswith("|") else shape.faces(sel).edges()).chamfer(c)
    except Exception as e:
        print(f"  [warn] chamfer {sel} {c} skipped: {type(e).__name__}"); return shape

def corner_block(x, z, y0, y1):
    """Lid-screw block in an inner corner of the rim, with two 45-degree wedges underneath so it prints support-free
    (plate-down print: +Y is up; without the wedges the 7 x 8 mm underside floats 40 mm above the plate)."""
    xa, xb = (XI - 7.0, XI) if x > 0 else (-XI, -XI + 7.0)
    za, zb = (ZI0, ZI0 + 8.0) if z < (ZI0 + ZI1) / 2 else (ZI1 - 8.0, ZI1)
    blk = box(xa, xb, y0, y1, za, zb)
    xw, xi = (xb, xa) if x > 0 else (xa, xb)                  # wall side / inner side in X
    zw, zi = (za, zb) if z < (ZI0 + ZI1) / 2 else (zb, za)    # wall side / inner side in Z
    wedge_x = cq.Workplane("XY", origin=(0, 0, za)).polyline([(xw, y0), (xi, y0), (xw, y0 - abs(xi - xw))]).close().extrude(zb - za)
    wedge_z = cq.Workplane("YZ", origin=(xa, 0, 0)).polyline([(y0, zw), (y0, zi), (y0 - abs(zi - zw), zw)]).close().extrude(xb - xa)
    return blk.union(wedge_x).union(wedge_z)
def union_all(parts):
    r = parts[0]
    for p in parts[1:]: r = r.union(p)
    return r
def cut_all(base, tools):
    for t in tools: base = base.cut(t)
    return base
def text_cut(target, txt, size, origin, xdir, normal, depth=0.6):
    try:
        pl = cq.Plane(origin=cq.Vector(*origin), xDir=cq.Vector(*xdir), normal=cq.Vector(*normal))
        return target.cut(cq.Workplane(pl).text(txt, size, -depth, combine=False, halign="center", valign="center"))
    except Exception as e:
        print(f"  [warn] label '{txt}' skipped: {e}"); return target

# ============================================================== base
def ledge_pair(ribs, z0, z1, y_top, lip=2.0):
    """two vertical ribs (plate -> y_top) with 2 mm lips at their top: a support-free cradle for a body lying at y_top"""
    out = []
    for (x0, x1) in ribs:
        out.append(box(x0, x1, Y_PL1, y_top, z0, z1))
        inward = 1.0 if x0 < (ribs[0][0] + ribs[1][1]) / 2 else -1.0
        lx0, lx1 = (x0, x1 + lip) if inward > 0 else (x0 - lip, x1)
        out.append(box(lx0, lx1, y_top - 2.0, y_top, z0, z1))
    return out

def build_base():
    shell = soften(box(-XW, XW, Y0, Y_RIM, Z_BOT, Z_TOP)).cut(box(-XI, XI, Y_PL1, Y_RIM + 1, ZI0, ZI1).edges("|Y").fillet(R_POCKET))
    a = []
    a.append(chamfer_free(box(-XI, XI, Y_PL1, Y_RIM, Z_TRAY1, Z_DIV1), ">Y", 0.8))          # tray / middle divider, rounded free edge
    for (x, z) in TORSO_HOLES: a.append(chamfer_free(cyl_y(x, z, Y_PL1, Y_FL1, 10.0), ">Y"))
    a.append(chamfer_free(box(-XI, PACK_X[1] + 6.0, Y_PL1, Y_FL1, ZI0, ZI0 + 4.0), ">Y"))           # LiPo rails
    a.append(chamfer_free(box(-XI, PACK_X[1] + 6.0, Y_PL1, Y_FL1, Z_TRAY1 - 4.0, Z_TRAY1), ">Y"))
    # Waveshare standoffs 4 mm (37 x 28 pattern)
    for sx in (-1, 1):
        for sz in (-1, 1):
            a.append(chamfer_free(cyl_y(WS_C[0] + sx * WS_DX / 2, WS_C[1] + sz * WS_DZ / 2, Y_PL1, Y_PL1 + 4.0, 5.5), ">Y"))
    # XY-CD63 bosses (holes (2|60, 3.5|41.5) from its lower-left corner, left = +X)
    cut_holes = CUT_HOLES
    for (x, z) in cut_holes: a.append(chamfer_free(cyl_y(x, z, Y_PL1, Y_PL1 + 3.0, D_CUT_BOSS), ">Y"))   # Boss 9 mm: Wand um die Senkung
    # Pololu bosses (2x M2, 13.5 apart) in the +X column
    for dx in (-6.75, 6.75): a.append(chamfer_free(cyl_y(POL_C[0] + dx, POL_C[1] - 6.0, Y_PL1, Y_PL1 + 3.0, 5.0), ">Y"))
    for (x, z) in CORNER_SCREWS: a.append(corner_block(x, z, Y_RIM - H_M3_INS - 1.0, Y_RIM))
    base = union_all([shell] + a)

    PL = ((Y0, 1), (Y_PL1, -1))                     # back plate: material between Y0 and Y_PL1
    FLOOR = ((Z_BOT, 1), (ZI0, -1)); TRAY = ((Z_TRAY1, 1), (Z_DIV1, -1)); TOP = ((ZI1, 1), (Z_TOP, -1)); XWALL = ((XI, 1), (XW, -1))
    c = []
    for (x, z) in TORSO_HOLES:
        c.append(soft_cyl(x, z, Y0 - 1, Y_FL1 + 1, D_M3_CLEAR, ((Y0, 1),))); c.append(soft_cyl(x, z, Y_FL1 - H_M3_HEAD, Y_FL1 + 1, D_M3_HEAD, ((Y_FL1, -1),)))
    for (x, z) in CORNER_SCREWS: c.append(soft_cyl(x, z, Y_RIM - H_M3_INS, Y_RIM + 1, D_M3_INS, ((Y_RIM, -1),)))
    for (x, z) in INSERT_SCREWS: c.append(soft_cyl(x, z, Y0 - 1, Y_PL1 + 1, D_M3_CLEAR, ((Y0, 1), (Y_PL1, -1))))
    for sx in (-1, 1):
        for sz in (-1, 1):
            c.append(soft_cyl(WS_C[0] + sx * WS_DX / 2, WS_C[1] + sz * WS_DZ / 2, Y_PL1 + 0.8, Y_PL1 + 5.0, D_M25_TAP, ((Y_PL1 + 4.0, -1),), c=0.4))
    for (x, z) in cut_holes:                                          # von hinten verschraubt: Durchgang + Senkung an der Torso-Seite
        c.append(soft_cyl(x, z, Y0 - 1.0, Y_PL1 + 4.0, D_CUT_SHAFT, ((Y_PL1 + 3.0, -1),), c=0.4))
        c.append(soft_cyl(x, z, Y0 - 1.0, Y0 + H_CUT_CB, D_CUT_CB, ((Y0, 1),), c=0.5))
    # plate: pass-through into the torso (rounded, both entry edges rounded over) + vents under the Waveshare plug zone
    c.append(soft_tool(PASS_A["x"][0], PASS_A["x"][1], Y0 - 1, Y_PL1 + 1, PASS_A["z"][0], PASS_A["z"][1], "y", PL, c=0.8, r=3.0))
    for z in range(302, 330, 7): c.append(soft_tool(-25.0, -11.0, Y0 - 1, Y_PL1 + 1, z, z + 3.0, "y", PL, c=0.6, r=1.2))
    # LiPo drawer: open +X end (also the warner plug / lead exit) with rounded-over wall edges, end strap slots, lead notch
    c.append(soft_tool(XI - 1, XW + 1, Y_PL1, Y_RIM + 1, ZI0, Z_TRAY1, "x", XWALL, c=1.0, r=2.0))
    c.append(soft_tool(STRAP_X[0], STRAP_X[1], 46.0, 70.0, Z_BOT - 1, ZI0 + 1, "z", FLOOR, c=0.6, r=1.5))
    c.append(soft_tool(STRAP_X[0], STRAP_X[1], 46.0, 70.0, Z_TRAY1 - 1, Z_DIV1 + 1, "z", TRAY, c=0.6, r=1.5))
    c.append(soft_tool(XT_SW["x"][0] - 2.0, XT_SW["x"][1] + 2.0, Y_CAB - 2.0, Y_RIM + 1, Z_TRAY1 - 1, Z_DIV1 + 1, "z", TRAY, c=0.8, r=2.0))   # switch XT60 pair dips through the divider
    for dx in (-6.75, 6.75): c.append(soft_cyl(POL_C[0] + dx, POL_C[1] - 6.0, Y_PL1 + 0.8, Y_PL1 + 4.0, D_M2_TAP, ((Y_PL1 + 3.0, -1),), c=0.3))

    # convection slots in the top wall over the relay
    for x in range(-24, 30, 7): c.append(soft_tool(x, x + 2.5, 50.0, 70.0, ZI1 - 1, Z_TOP + 1, "z", TOP, c=0.6, r=1.0))
    return cut_all(base, c)

# ============================================================== lid
def build_lid():
    lid = soften(box(-XW, XW, Y_RIM, Y_LID, Z_BOT, Z_TOP), chamfer_faces=(">Y",))
    LP = ((Y_RIM, 1), (Y_LID, -1))                  # lid plate: material between Y_RIM and Y_LID
    c = []
    for (x, z) in CORNER_SCREWS: c.append(soft_cyl(x, z, Y_RIM - 1, Y_LID + 1, D_M3_CLEAR, ((Y_RIM, 1),))); c.append(soft_cyl(x, z, Y_LID - 1.0, Y_LID + 1, D_M3_HEAD, ((Y_LID, -1),)))
    c.append(soft_tool(-17.0, 17.0, Y_RIM - 1, Y_LID + 1, CUT_Z0 + 1.5, CUT_Z0 + 17.5, "y", LP, c=0.8, r=2.0))      # display (bottom edge, centred)
    c.append(soft_tool(-31.0, -17.0, Y_RIM - 1, Y_LID + 1, CUT_Z0 + 4.0, CUT_Z0 + 36.0, "y", LP, c=0.8, r=2.0))     # buttons (right edge = -X)
    c.append(soft_tool(FUSE_HOLDER["x"][0] + 1.0, FUSE_HOLDER["x"][1] - 1.0, Y_RIM - 1, Y_LID + 1, FUSE_HOLDER["z"][0] + 1.0, FUSE_HOLDER["z"][1] - 1.0, "y", LP, c=0.8, r=2.0))   # fuse cap (1 mm inside the rib faces)
    sx = (SW_BODY["x"][0] + SW_BODY["x"][1]) / 2; sz = (SW_BODY["z"][0] + SW_BODY["z"][1]) / 2
    c.append(soft_tool(sx - 4.0, sx + 4.0, Y_RIM - 1, Y_LID + 1, sz - 10.0, sz + 10.0, "y", ((Y_RIM, 1),), c=0.8, r=2.0))   # slider slot (adjust on print); outer edge sits in the recess
    c.append(box(sx - 8.0, sx + 8.0, Y_LID - 1.0, Y_LID + 1, sz - 15.0, sz + 15.0).edges("|Y").fillet(2.0))                    # recess collar
    for k in range(4): z = WARN["z"][0] + 4.0 + 4.0 * k; c.append(soft_tool(WARN["x"][0] + 5.0, WARN["x"][1] - 5.0, Y_RIM - 1, Y_LID + 1, z, z + 2.0, "y", LP, c=0.5, r=0.9))   # Warner-Display/Signalgeber
    for k in range(3): z = 380.0 + 5.0 * k; c.append(soft_tool(-14.0, 10.0, Y_RIM - 1, Y_LID + 1, z, z + 2.0, "y", LP, c=0.5, r=0.9))   # relay vents
    for k in range(3): z = 302.0 + 8.0 * k; c.append(soft_tool(-24.0, 12.0, Y_RIM - 1, Y_LID + 1, z, z + 2.5, "y", LP, c=0.6, r=1.1))  # Waveshare vents
    for z in (388.0, 393.08): c.append(soft_cyl(66.0, z, Y_RIM - 1, Y_LID + 1, 2.2, ((Y_RIM, 1), (Y_LID, -1)), c=0.4))   # 5 V test pins
    lid = cut_all(lid, c)
    a = []
    def lid_cradle(ribs, z0, z1, lips=(True, True)):
        for (x0, x1), lip in zip(ribs, lips):
            a.append(chamfer_free(box(x0, x1, Y_CAB, Y_RIM, z0, z1), "<Y"))                 # rib, free edge rounded
            if lip:   # wedge-shaped foot: 2 mm inward at Y_CAB-2, 45-degree slope back to the rib at Y_CAB (support-free, one body with the rib)
                inward = 1.0 if x0 < (ribs[0][0] + ribs[1][1]) / 2 else -1.0
                x_in, x_out, x_far = (x1, x1 + 2.0, x0) if inward > 0 else (x0, x0 - 2.0, x1)   # trapezoid over the rib end + 45-degree foot
                a.append(cq.Workplane("XY", origin=(0, 0, z0)).polyline([(x_far, Y_CAB), (x_in, Y_CAB), (x_out, Y_CAB - 2.0), (x_far, Y_CAB - 2.0)]).close().extrude(z1 - z0))
    lid_cradle(SW_RIBS, SW_BODY["z"][0] - 2.0, SW_BODY["z"][1] + 2.0)
    lid_cradle(FUSE_RIBS, FUSE_HOLDER["z"][0] - 2.0, FUSE_HOLDER["z"][1] + 2.0)
    lid_cradle(XT_LIPO_RIBS, XT_LIPO["z"][0] - 2.0, XT_LIPO["z"][1] + 2.0)
    lid_cradle(XT_SW_RIBS, XT_SW["z"][0] - 2.0, XT_SW["z"][1] + 2.0)
    lid_cradle(WARN_RIBS, WARN["z"][0] - 1.0, WARN["z"][1] + 2.0)              # Warner zwischen zwei X-Rippen (z-Bereich frei vom Eckklotz)
    lid = union_all([lid] + a)
    c2 = []
    for (x0, x1) in SW_RIBS:
        for z in (350.0, 372.0): c2.append(soft_tool(x0 - 1, x1 + 1, Y_CAB + 1.0, Y_CAB + 11.0, z, z + 4.0, "x", ((x0, 1), (x1, -1)), c=0.6, r=1.5))   # strap slots through the rib
    for (x0, x1) in FUSE_RIBS + XT_LIPO_RIBS:                                                            # cable notches (cables run along X), through the whole rib height
        c2.append(soft_tool(x0 - 1, x1 + 1, Y_CAB - 3.0, Y_RIM, 261.0, 272.0, "x", ((x0, 1), (x1, -1)), c=0.8, r=2.0))
    for (x0, x1) in XT_LIPO_RIBS: c2.append(soft_tool(x0 - 1, x1 + 1, Y_CAB + 1.0, Y_CAB + 11.0, 275.0, 279.0, "x", ((x0, 1), (x1, -1)), c=0.6, r=1.5))
    c2.append(soft_tool(WARN["x"][0] - 16.0, WARN["x"][0] - 2.0, Y_RIM - 1, Y_LID + 1, WARN["z"][0] + 5.0, WARN["z"][1] - 5.0, "y", LP, c=0.8, r=2.5))   # Fingeroeffnung ueber dem Balancer-Stecker
    lid = cut_all(lid, c2)
    lid = text_cut(lid, "5V", 3.0, (71.5, Y_LID, 388.0), (-1, 0, 0), (0, 1, 0))
    lid = text_cut(lid, "GND", 3.0, (58.5, Y_LID, 393.0), (-1, 0, 0), (0, 1, 0))
    lid = text_cut(lid, "30A", 5.0, (-27.0, Y_LID, 279.5), (-1, 0, 0), (0, 1, 0))
    return text_cut(lid, "BAL", 3.5, (35.0, Y_LID, 325.0), (-1, 0, 0), (0, 1, 0))

# ============================================================== torso insert
def build_insert():
    yb0, yb1 = Y_WALL_IN - 3.0, Y_WALL_IN                 # carrier plate against the inner face of the back wall
    plate = box(-36.0, 36.0, yb0, yb1, 255.0, 372.0).edges("|Y and >Z").fillet(3.0)      # bottom edge = bed (printed standing up); upper corners rounded
    a = [plate]
    for x in (-20.0, 4.0): a.append(chamfer_free(box(x, x + 16.0, yb1, Y0, 255.0, 269.0).edges("|Y").fillet(1.0), ">Y"))   # tabs through the window (8.5 mm), rounded
    a.append(chamfer_free(box(-27.0, -25.0, yb0 - 6.0, yb0, 270.0, 372.0), "<Y")); a.append(chamfer_free(box(33.0, 35.0, yb0 - 6.0, yb0, 270.0, 372.0), "<Y"))   # stiffening ribs
    pi_holes = [(PI_X[0] + 3.5, PI_Z[1] - 3.5), (PI_X[1] - 3.5, PI_Z[1] - 3.5), (PI_X[0] + 3.5, PI_Z[1] - 61.5), (PI_X[1] - 3.5, PI_Z[1] - 61.5)]
    for (x, z) in pi_holes: a.append(chamfer_free(chamfer_free(teardrop_y(x, z, PI_Y_BOARD, yb0, 6.0), "<Y", 0.4), "|Y", 0.4))   # 12 mm standoffs, support-free, edges broken
    ins = union_all(a)
    IP = ((yb0, 1), (yb1, -1))                      # carrier plate: material between yb0 and yb1
    c = []
    for (x, z) in INSERT_SCREWS: c.append(soft_cyl(x, z, yb1 + 2.5, Y0 + 1, D_M3_INS, ((Y0, -1),)))       # heat-set inserts from the back
    for (x, z) in pi_holes: c.append(soft_cyl(x, z, PI_Y_BOARD - 1, yb0 - 0.8, D_M25_TAP, ((PI_Y_BOARD, 1),), c=0.4))
    c.append(soft_tool(-8.0, 8.0, yb0 - 1, yb1 + 1, 340.0, 373.0, "y", IP, c=0.8, r=2.0))                            # SD card window (card sits under the board)
    c.append(soft_tool(PASS_A["x"][0] + 9.0, PASS_A["x"][1] + 7.0, yb0 - 1, yb1 + 1, PASS_A["z"][0] - 1.0, PASS_A["z"][1] + 1.0, "y", IP, c=0.8, r=3.0))   # cable pass-through, shifted +X: clears the Pi standoff
    for sx in (-1, 1):                                                                 # clearance for the torso's inner ribs / bosses
        c.append(soft_tool(min(sx * 27.0, sx * 40.0), max(sx * 27.0, sx * 40.0), yb0 - 10, yb1 + 1, 306.0, 344.0, "y", IP, c=0.8, r=2.0))
        c.append(soft_tool(min(sx * 31.0, sx * 40.0), max(sx * 31.0, sx * 40.0), yb0 - 10, yb1 + 1, 254.0, 268.0, "y", IP, c=0.8, r=2.0))
    for z in range(286, 338, 8):                                                       # airflow behind the board: 3 x 12 mm per row (12 mm bridges instead of 48 mm)
        for x in (-28.0, -10.0, 8.0): c.append(soft_tool(x, x + 12.0, yb0 - 1, yb1 + 1, z, z + 3.0, "y", IP, c=0.6, r=1.2))
    return cut_all(ins, c)

# ============================================================== placeholders (wired envelopes, not for printing)
def build_placeholders():
    p = {}
    p["lipo"] = box(PACK_X[0], PACK_X[1], Y_FL1 + 1, Y_FL1 + 26, ZI0 + 2, ZI0 + 36)
    p["warner"] = box(WARN["x"][0], WARN["x"][1], WARN["y"][0], WARN["y"][1], WARN["z"][0], WARN["z"][1])
    p["warner_plug"] = box(WARN["x"][0] - 16.0, WARN["x"][0] - 2.0, WARN["y"][0] + 2.0, WARN["y"][0] + 9.0, WARN["z"][0] + 6.0, WARN["z"][0] + 16.0)   # JST-XH zum Balancer des Akkus
    p["cutoff"] = box(CUT_X1 - 62, CUT_X1, Y_PL1 + 3, Y_PL1 + 31, CUT_Z0, CUT_Z0 + 56)
    # terminal wire-entry zones: 10 mm straight clamp entry + bend start, both edges
    p["cutoff_vin_wires"] = box(CUT_X1, CUT_X1 + 12.0, 46.0, 60.0, CUT_TERM_Z - 8.0, CUT_TERM_Z + 8.0)
    p["cutoff_out_wires"] = box(CUT_X1 - 74.0, CUT_X1 - 62.0, 46.0, 60.0, CUT_TERM_Z - 8.0, CUT_TERM_Z + 8.0)
    p["waveshare"] = box(WS_C[0] - 21, WS_C[0] + 21, Y_PL1 + 4, Y_PL1 + 20, WS_C[1] - 16.5, WS_C[1] + 16.5)
    p["waveshare_molex"] = box(WS_C[0] - 16, WS_C[0] + 16, Y_PL1 + 20, Y_PL1 + 31, WS_C[1] - 12, WS_C[1] + 12)       # plugs on top, cables bend above
    p["waveshare_plugs"] = box(WS_PLUG_X[0], WS_PLUG_X[1], 48.0, 62.0, WS_C[1] - 14, WS_C[1] + 14)                    # DC + USB-C plugs with boots
    p["switch"] = box(SW_BODY["x"][0], SW_BODY["x"][1], SW_BODY["y"][0], SW_BODY["y"][1], SW_BODY["z"][0], SW_BODY["z"][1])
    p["fuse_holder"] = box(FUSE_HOLDER["x"][0], FUSE_HOLDER["x"][1], FUSE_HOLDER["y"][0], FUSE_HOLDER["y"][1], FUSE_HOLDER["z"][0], FUSE_HOLDER["z"][1])
    p["xt60_lipo_fuse"] = box(XT_LIPO["x"][0], XT_LIPO["x"][1], XT_LIPO["y"][0], XT_LIPO["y"][1], XT_LIPO["z"][0], XT_LIPO["z"][1])
    p["xt60_fuse_switch"] = box(XT_SW["x"][0], XT_SW["x"][1], XT_SW["y"][0], XT_SW["y"][1], XT_SW["z"][0], XT_SW["z"][1])
    p["pi"] = box(PI_X[0], PI_X[1], PI_Y_BOARD - 17.0, PI_Y_BOARD, PI_Z[0], PI_Z[1])
    p["pi_usb_plugs"] = box(PI_X[0] + 10, PI_X[1] - 10, PI_Y_BOARD - 17.0, PI_Y_BOARD, PI_Z[0] - 14.0, PI_Z[0])      # down-angled USB-A plugs
    p["pi_usbc_plug"] = box(PI_X[1], PI_X[1] + 12.0, PI_Y_BOARD - 14.0, PI_Y_BOARD - 3.0, PI_Z[1] - 17.0, PI_Z[1] - 5.0)   # right-angle USB-C, power
    p["pololu"] = box(POL_C[0] - 8.9, POL_C[0] + 8.9, Y_PL1 + 3.0, Y_PL1 + 3.0 + 8.8, POL_C[1] - 10.15, POL_C[1] + 10.15)
    p["pololu_wires"] = box(POL_C[0] - 10.0, POL_C[0] + 10.0, Y_PL1 + 2.0, Y_PL1 + 16.0, POL_C[1] + 10.15, POL_C[1] + 26.0)
    y_head = Y0 + H_CUT_CB - 3.0                                        # Kopf sitzt im Senkgrund (0.4 mm versenkt)
    screws = [cyl_y(x, z, y_head, y_head + 3.0, 5.5).union(cyl_y(x, z, y_head + 3.0, y_head + 13.0, 3.0)) for (x, z) in CUT_HOLES]
    p["cutoff_screws"] = union_all(screws)                              # 4x M3 x 10 Zylinderkopf (DIN 912), von der Torso-Seite eingesetzt
    return p

# ---------------------------------------------------------------- cables (centrelines, robot frame; checked/rendered by check_cables.py)
# each: polyline waypoints, outer diameter, minimum bend radius (inner), what it is
CABLES = {
    "lipo_xt60_lead":  dict(d=4.0, r=14.0, pts=[(PACK_X[1], 52.0, 272.0), (31.0, 58.0, 269.0), (31.0, 72.0, 264.0), (20.0, 77.0, 265.0)]),
    "lipo_balancer":   dict(d=2.5, r=5.0,  pts=[(PACK_X[1], 62.0, 270.0), (28.0, 70.0, 272.0), (28.0, 78.0, 277.0)]),
    "fuse_leg_1":      dict(d=4.0, r=14.0, pts=[(FUSE_HOLDER["x"][1], 77.0, 266.5), (XT_LIPO["x"][0] + 6.0, 77.0, 266.5)]),
    "fuse_leg_2":      dict(d=4.0, r=14.0, pts=[(-61.0, 77.0, XT_SW["z"][0] + 6.0), (-61.0, 77.0, 266.5), (FUSE_HOLDER["x"][0], 77.0, 266.5)]),
    "switch_in_lead":  dict(d=3.5, r=10.0, pts=[(-61.0, 77.0, XT_SW["z"][1] - 6.0), (-61.0, 79.0, SW_BODY["z"][0])]),
    "switch_out_pigtail": dict(d=4.0, r=12.0, pts=[(-61.0, 80.0, SW_BODY["z"][1]), (-61.0, 80.0, 399.5), (49.0, 80.0, 399.5), (49.0, 52.0, 388.0), (CUT_X1 + 2.0, 52.0, CUT_TERM_Z)]),
    "out_to_waveshare": dict(d=3.0, r=10.0, pts=[(CUT_X1 - 64.0, 52.0, CUT_TERM_Z), (-45.0, 52.0, CUT_TERM_Z), (-45.0, 54.0, 324.0), (-50.0, 55.0, 318.0)]),
    "out_to_pololu":   dict(d=2.5, r=5.0,  pts=[(CUT_X1 - 64.0, 47.0, CUT_TERM_Z + 6.0), (-44.0, 46.0, 401.5), (50.0, 46.0, 401.5), (POL_C[0], 47.0, 394.0), (POL_C[0], 47.0, POL_C[1] + 16.0)]),
    "servo_bus_a":     dict(d=3.0, r=8.0,  pts=[(19.0, 34.0, 322.0), (19.0, 60.0, 322.0), (10.0, 74.0, 320.0), (0.0, 72.0, 320.0)]),
    "servo_bus_b":     dict(d=3.0, r=8.0,  pts=[(24.0, 34.0, 310.0), (24.0, 60.0, 310.0), (12.0, 74.0, 314.0), (-8.0, 72.0, 314.0)]),
    "pi_usb_to_waveshare": dict(d=3.0, r=8.0,  pts=[(0.0, 4.0, 262.0), (29.0, 6.0, 262.0), (29.0, 10.0, 300.0), (29.0, 20.0, 316.0), (24.0, 34.0, 318.0), (21.0, 44.0, 310.0), (17.0, 46.0, 300.0), (-35.0, 46.0, 300.0), (-45.0, 52.0, 310.0), (-50.0, 56.0, 318.0)]),
    "pololu_5v_usbc":  dict(d=3.5, r=6.0,  pts=[(POL_C[0] - 6.0, 47.0, POL_C[1] + 16.0), (52.0, 47.0, 350.0), (40.0, 47.0, 340.0), (40.0, 47.0, 316.0), (30.0, 46.0, 310.0), (22.0, 42.0, 312.0), (28.5, 32.0, 320.0), (30.0, 20.0, 330.0), (30.0, 10.0, 346.0), (PI_X[1] + 6.0, 8.0, 354.0)]),
    "test_leads_5v":   dict(d=2.0, r=6.0,  pts=[(POL_C[0], 47.0, POL_C[1] + 16.0), (66.0, 62.0, 384.0), (66.0, 86.0, 388.0)]),
}

def to_print(shape, y_bed): return shape.rotate((0, 0, 0), (1, 0, 0), 90).translate((0, 0, -y_bed))

def main():
    os.makedirs(OUT, exist_ok=True)
    meta = {}
    for name, fn, ybed in (("base", build_base, Y0), ("lid", build_lid, Y_RIM), ("insert", build_insert, None)):
        print(f"building {name} ..."); s = fn(); v = s.val()
        bb = v.BoundingBox(); c = v.Center()
        print(f"  volume {v.Volume()/1000:.1f} cm3, bbox X[{bb.xmin:.1f},{bb.xmax:.1f}] Y[{bb.ymin:.1f},{bb.ymax:.1f}] Z[{bb.zmin:.1f},{bb.zmax:.1f}], centroid ({c.x:.1f},{c.y:.1f},{c.z:.1f})")
        cq.exporters.export(s, os.path.join(OUT, f"backpack_v3_{name}_robotframe.stl"), tolerance=0.02, angularTolerance=0.1)
        if ybed is None:   # insert: printed standing on its bottom edge (tabs + plate edge on the bed), robot Z = print Z
            ps = s.translate((0, 0, -255.0))
        elif name == "lid":   # lid carries the cradle ribs on its inner face -> print OUTER face down, ribs grow upwards
            ps = s.rotate((0, 0, 0), (1, 0, 0), -90).translate((0, 0, Y_LID))
        else:
            ps = to_print(s, ybed)
        cq.exporters.export(ps, os.path.join(OUT, f"backpack_v3_{name}.stl"), tolerance=0.02, angularTolerance=0.1)
        meta[name] = dict(volume_cm3=round(v.Volume() / 1000, 2), centroid_robot_mm=[round(c.x, 2), round(c.y, 2), round(c.z, 2)])
    for k, v in build_placeholders().items():
        cq.exporters.export(v, os.path.join(OUT, f"placeholder_{k}.stl"), tolerance=0.05)
    meta["depth_mm"] = dict(base=[Y0, Y_RIM], lid=[Y_RIM, Y_LID], total=Y_LID - Y0, insert=[Y_WALL_IN - 9.0, Y0])
    meta["envelope_mm"] = dict(x=[-XW, XW], y=[Y0, Y_LID], z=[Z_BOT, Z_TOP])
    json.dump(CABLES, open(os.path.join(OUT, "cables.json"), "w"), indent=1)
    json.dump(meta, open(os.path.join(OUT, "parts.json"), "w"), indent=2)
    print("done ->", OUT)

if __name__ == "__main__":
    main()
