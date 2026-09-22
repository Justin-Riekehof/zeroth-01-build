#!/usr/bin/env python3
"""Z-Bot "Pixel" — Backpack v2 (CadQuery source).

Three printed parts that replace the K-Scale BackPack on the pinned CAD state
(OnShape "[0]th Z001", assembly Opus, microversion 93de7567):

  1. base   — mounting frame on the torso (4x M3 into the existing heat-set inserts),
              LiPo drawer (side-loading), Waveshare bay over the torso window,
              anti-spark switch pocket, fuse trough, cable bays.
  2. deck   — electronics deck screwed onto the base rim: XY-CD63 cutoff, Pi 4B,
              Pololu bay, LiPo-warner pocket (balancer plug reachable from below).
  3. lid    — rear cover with display window, button window, vents, 5 V probe slot.

All geometry is modelled in the ROBOT frame of the pinned assembly (mm):
  +X = robot left, +Y = robot back, +Z = up.  Torso back wall = plane Y 38.1.
STLs are exported in print orientation (bed = the face that touches the previous
layer, i.e. -Y in the robot frame). No mirroring anywhere.

Run:  python backpack_v2.py        (needs cadquery >= 2.4)
"""
from __future__ import annotations
import json, math, os, sys
import cadquery as cq

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "stl")

# ----------------------------------------------------------------------------
# Interface to the torso — derived from resources/cad/z001-opus-m-93de7567.glb
# ----------------------------------------------------------------------------
Y0 = 38.1                                   # torso back wall / mounting plane
TORSO_HOLES = [(-35.01, 261.56), (35.01, 261.56),      # lower pair, 70.0 apart
               (-47.24, 330.34), (47.24, 330.34)]      # upper pair, 94.5 apart
TORSO_WINDOW = dict(x=(-27.0, 27.0), z=(251.6, 337.0)) # opening into the torso

# ----------------------------------------------------------------------------
# Envelope & wall stack
# ----------------------------------------------------------------------------
XW = 73.0                     # half width (torso wall is +-73 at shoulder height)
Z_BOT, Z_TOP = 254.0, 377.0   # legs (95 deg hip extension) stay > Y 128 below Z 252
T_PLATE, T_BOSS = 3.0, 3.0    # base plate; screw-head bosses above it
T_OW, T_IW = 2.5, 2.0         # outer walls / inner dividers
D1 = 28.0                     # clear depth of layer 1 (LiPo thickness + puffing)
D2 = 28.0                     # clear depth of layer 2 (XY-CD63 incl. standoffs)
T_FLOOR2, T_LID = 2.5, 2.0

Y_PL1 = Y0 + T_PLATE          # 41.1 top of base plate
Y_FL1 = Y_PL1 + T_BOSS        # 44.1 effective floor of layer 1 (rails / boss tops)
Y_RIM = Y_FL1 + D1            # 72.1 base rim = deck floor underside
Y_FL2 = Y_RIM + T_FLOOR2      # 74.6 deck floor top
Y_IN2 = Y_FL2 + D2            # 102.6 deck interior end = lid underside
Y_LID = Y_IN2 + T_LID         # 104.6 rear face

XI = XW - T_OW                # 70.5 inner half width
ZI0, ZI1 = Z_BOT + T_OW, Z_TOP - T_OW     # 256.5 .. 374.5 inner Z

# layer-1 bands (Z)
Z_TRAY0, Z_TRAY1 = ZI0, ZI0 + 38.0        # LiPo tray 256.5..294.5
Z_DIV1 = Z_TRAY1 + T_IW                   # 296.5  bays start
Z_ROOF0 = 349.0; Z_ROOF1 = Z_ROOF0 + T_IW # centre-bay roof 349..351, fuse strip above
X_CB = 38.0                               # centre bay half width (inner); walls to 40
TRAY_STOP_X = -60.0                       # end-stop rib (pack rests against it)
PACK_L = 106.0

# layer-2 bands
Z_BAND = 314.5                            # cutoff band below, Pi band above
Z_BAND1 = Z_BAND + T_IW

# fasteners
D_M3_CLEAR, D_M3_HEAD, H_M3_HEAD = 3.4, 6.6, 3.2
D_M3_INSERT, H_M3_INSERT = 4.0, 6.0       # heat-set M3 (OD ~4.6, L 5.7)
D_M25_TAP, D_M2_TAP = 2.2, 1.7            # self-tapping pilots in PETG

# component placement (robot frame) — see README for the [V]/[S] status of each
DECK_SCREWS = [(-67.0, 260.0), (67.0, 260.0), (-67.0, 371.0), (67.0, 371.0)]   # in 7x8 corner blocks
WS_C = (0.0, 322.5); WS_HOLES_DX, WS_HOLES_DZ = 37.0, 28.0      # Waveshare (A), 42x33
PI_X0, PI_Z0 = -22.0, 317.5                                     # Pi 4B, SD edge at +X
CUT_X1, CUT_Z0 = -1.0, 257.5                                    # XY-CD63 left edge (+X), bottom
POL_BAY = dict(x=(3.0, 34.0), z=(ZI0, 286.0))                   # Pololu bay (walls incl.)
WARN_POCKET = dict(x=(37.5, 63.5), z=(ZI0, 304.0))              # warner pocket (walls incl.)
BAL_SLOT = dict(x=(44.0, 58.0), z=(258.0, 270.0))               # balancer lead pass-through
SW_POCKET = dict(x=(-XI, -43.5), z=(Z_DIV1, Z_DIV1 + 50.0))     # anti-spark switch pocket
SW_SLIDER = dict(z=(314.0, 332.0), y=(47.6, 55.6))              # slider slot, adjust on print

# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
def box(x0, x1, y0, y1, z0, z1):
    assert x1 > x0 and y1 > y0 and z1 > z0, (x0, x1, y0, y1, z0, z1)
    return cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0, centered=False).translate((x0, y0, z0))

def cyl_y(x, z, y0, y1, d):
    return cq.Workplane("XY").add(cq.Solid.makeCylinder(d / 2, y1 - y0, cq.Vector(x, y0, z), cq.Vector(0, 1, 0)))

def cyl_x(y, z, x0, x1, d):
    return cq.Workplane("XY").add(cq.Solid.makeCylinder(d / 2, x1 - x0, cq.Vector(x0, y, z), cq.Vector(1, 0, 0)))

def slot_y(x, z, y0, y1, w, lx):
    """slot along X (length lx incl. round ends, width w), axis along Y"""
    s = box(x - lx / 2 + w / 2, x + lx / 2 - w / 2, y0, y1, z - w / 2, z + w / 2)
    return s.union(cyl_y(x - lx / 2 + w / 2, z, y0, y1, w)).union(cyl_y(x + lx / 2 - w / 2, z, y0, y1, w))

def corner_block(x, z, y0, y1):
    """7 x 8 mm block fused into the nearest inner corner (robust alternative to a round boss)"""
    xa, xb = (XI - 7.0, XI) if x > 0 else (-XI, -XI + 7.0)
    za, zb = (ZI0, ZI0 + 8.0) if z < (ZI0 + ZI1) / 2 else (ZI1 - 8.0, ZI1)
    return box(xa, xb, y0, y1, za, zb)

def union_all(parts):
    r = parts[0]
    for p in parts[1:]:
        r = r.union(p)
    return r

def cut_all(base, tools):
    for t in tools:
        base = base.cut(t)
    return base

def text_cut(target, txt, size, plane_origin, xdir, normal, depth=0.6):
    """Deboss text into a face; reading direction = xdir, viewed from +normal."""
    try:
        pl = cq.Plane(origin=cq.Vector(*plane_origin), xDir=cq.Vector(*xdir), normal=cq.Vector(*normal))
        t = cq.Workplane(pl).text(txt, size, -depth, combine=False, halign="center", valign="center")
        return target.cut(t)
    except Exception as e:  # no font in the environment etc. — never fail the build on a label
        print(f"  [warn] label '{txt}' skipped: {e}")
        return target

# ----------------------------------------------------------------------------
# PART 1 — base frame
# ----------------------------------------------------------------------------
def build_base():
    shell = box(-XW, XW, Y0, Y_RIM, Z_BOT, Z_TOP)
    shell = shell.cut(box(-XI, XI, Y_PL1, Y_RIM + 1, ZI0, ZI1))          # open towards +Y (deck side)

    adds = []
    # tray / bay divider and centre-bay walls + roof
    adds.append(box(-XI, XI, Y_PL1, Y_RIM, Z_TRAY1, Z_DIV1))
    adds.append(box(-X_CB - T_IW, -X_CB, Y_PL1, Y_RIM, Z_DIV1, Z_ROOF1))
    adds.append(box(X_CB, X_CB + T_IW, Y_PL1, Y_RIM, Z_DIV1, Z_ROOF1))
    adds.append(box(-X_CB - T_IW, X_CB + T_IW, Y_PL1, Y_RIM, Z_ROOF0, Z_ROOF1))
    # torso-screw bosses + LiPo rails (pack rides on the rails, clears the screw heads)
    for (x, z) in TORSO_HOLES:
        adds.append(cyl_y(x, z, Y_PL1, Y_FL1, 10.0))
    adds.append(box(-XI, XI, Y_PL1, Y_FL1, Z_TRAY0, Z_TRAY0 + 4.0))
    adds.append(box(-XI, XI, Y_PL1, Y_FL1, Z_TRAY1 - 4.0, Z_TRAY1))
    # tray end stop (pack rests against it; dead corner behind it hosts a deck-screw boss)
    adds.append(box(TRAY_STOP_X - T_IW, TRAY_STOP_X, Y_PL1, Y_RIM, Z_TRAY0, Z_TRAY1))
    # Waveshare standoffs (37 x 28 pattern, docs.waveshare.com) — 4 mm tall
    for sx in (-1, 1):
        for sz in (-1, 1):
            adds.append(cyl_y(WS_C[0] + sx * WS_HOLES_DX / 2, WS_C[1] + sz * WS_HOLES_DZ / 2, Y_PL1, Y_PL1 + 4.0, 5.5))
    # switch pocket ribs (partial height 19 mm — the body is ~15 mm)
    sx0, sx1 = SW_POCKET["x"]; sz0, sz1 = SW_POCKET["z"]
    adds.append(box(sx1, sx1 + T_IW, Y_PL1, Y_PL1 + 19.0, sz0, sz1 + T_IW))
    adds.append(box(sx0, sx1 + T_IW, Y_PL1, Y_PL1 + 19.0, sz1, sz1 + T_IW))
    # fuse-holder guide ribs at the apex of the fuse strip
    adds.append(box(-22.0 - T_IW, -22.0, Y_PL1, Y_PL1 + 9.0, Z_ROOF1, ZI1))
    adds.append(box(22.0, 22.0 + T_IW, Y_PL1, Y_PL1 + 9.0, Z_ROOF1, ZI1))
    # deck-screw bosses (heat-set inserts) in the four corners, fused into the walls
    for (x, z) in DECK_SCREWS:
        adds.append(corner_block(x, z, Y_RIM - H_M3_INSERT - 1.0, Y_RIM))
    base = union_all([shell] + adds)

    cuts = []
    # torso screws: through hole + counterbore (head flush with boss top at Y 44.1)
    for (x, z) in TORSO_HOLES:
        cuts.append(cyl_y(x, z, Y0 - 1, Y_FL1 + 1, D_M3_CLEAR))
        cuts.append(cyl_y(x, z, Y_FL1 - H_M3_HEAD, Y_FL1 + 1, D_M3_HEAD))
    # deck-screw inserts
    for (x, z) in DECK_SCREWS:
        cuts.append(cyl_y(x, z, Y_RIM - H_M3_INSERT, Y_RIM + 1, D_M3_INSERT))
    # plate window over the torso opening (servo bus from inside the torso -> Waveshare)
    cuts.append(box(-20.0, 20.0, Y0 - 1, Y_PL1 + 1, 300.0, 336.0))
    # Waveshare pilot holes
    for sx in (-1, 1):
        for sz in (-1, 1):
            cuts.append(cyl_y(WS_C[0] + sx * WS_HOLES_DX / 2, WS_C[1] + sz * WS_HOLES_DZ / 2, Y_PL1 + 0.8, Y_PL1 + 5.0, D_M25_TAP))
    # LiPo drawer: open +X end (full band, from plate top to rim)
    cuts.append(box(XI - 1, XW + 1, Y_PL1, Y_RIM + 1, Z_TRAY0, Z_TRAY1))
    # end strap slots (bottom wall + divider), strap 20 mm wide, at the pack's open end
    strap_x = (TRAY_STOP_X + PACK_L + 2.0, TRAY_STOP_X + PACK_L + 6.0)     # 48..52
    cuts.append(box(strap_x[0], strap_x[1], 46.0, 68.0, Z_BOT - 1, Z_TRAY0 + 1))
    cuts.append(box(strap_x[0], strap_x[1], 46.0, 68.0, Z_TRAY1 - 1, Z_DIV1 + 1))
    # divider notch: LiPo XT60 lead goes up into the left cable bay
    cuts.append(box(54.0, 68.0, Y_FL1, Y_RIM + 1, Z_TRAY1 - 1, Z_DIV1 + 1))
    # switch: slider slot through the right wall + 1.2 mm recess collar on the outside
    cuts.append(box(-XW - 1, -XI + 1, SW_SLIDER["y"][0], SW_SLIDER["y"][1], SW_SLIDER["z"][0], SW_SLIDER["z"][1]))
    cuts.append(box(-XW - 1, -XW + 1.2, SW_SLIDER["y"][0] - 4.0, SW_SLIDER["y"][1] + 4.0, SW_SLIDER["z"][0] - 5.0, SW_SLIDER["z"][1] + 5.0))
    # switch strap slots through the rib and the outer wall (velcro/cable tie around the body)
    for z in (311.0, 334.0):
        cuts.append(box(-XW - 1, -XI + 1, 46.0, 66.0, z, z + 4.0))
        cuts.append(box(sx1 - 1, sx1 + T_IW + 1, 46.0, 66.0, z, z + 4.0))
    # fuse holder: top-face notch for the flip lid (open to the rim -> support-free)
    cuts.append(box(-20.0, 20.0, 46.0, Y_RIM + 1, ZI1 - 1, Z_TOP + 1))
    # cable-tie slots through the centre-bay roof (holder body tie-down)
    for x in (-12.0, 12.0):
        cuts.append(box(x - 1.5, x + 1.5, 46.0, 54.0, Z_ROOF0 - 1, Z_ROOF1 + 1))
    # convection slots in the top wall over the fuse strip / left bay (heat from Waveshare)
    for x in (30.0, 36.0, 42.0, 48.0, 54.0):
        cuts.append(box(x, x + 2.5, 50.0, 66.0, ZI1 - 1, Z_TOP + 1))
    base = cut_all(base, cuts)
    # labels: fuse rating next to the lid notch (top face, read from behind/above)
    base = text_cut(base, "30A", 6.0, (30.0, 58.0, Z_TOP), (-1, 0, 0), (0, 0, 1))
    return base

# ----------------------------------------------------------------------------
# PART 2 — electronics deck
# ----------------------------------------------------------------------------
def build_deck():
    shell = box(-XW, XW, Y_RIM, Y_IN2, Z_BOT, Z_TOP)
    shell = shell.cut(box(-XI, XI, Y_FL2, Y_IN2 + 1, ZI0, ZI1))

    adds = []
    adds.append(box(-XI, XI, Y_FL2, Y_IN2 - 0.3, Z_BAND, Z_BAND1))            # band divider
    adds.append(box(CUT_X1 + 2.0, CUT_X1 + 2.0 + T_IW, Y_FL2, Y_IN2 - 0.3, ZI0, Z_BAND))  # cutoff | left zone
    # Pololu bay walls (bottom-left of the lower band, vented through the bottom wall)
    px0, px1 = POL_BAY["x"]; pz0, pz1 = POL_BAY["z"]
    adds.append(box(px1 - T_IW, px1, Y_FL2, Y_IN2 - 0.3, pz0, pz1))
    adds.append(box(px0, px1, Y_FL2, Y_IN2 - 0.3, pz1 - T_IW, pz1))
    # Pololu bosses (2x, 13.5 mm apart, M2 self-tap), 3 mm tall
    pol_cx, pol_cz = (px0 + px1) / 2 + 1.0, 277.0
    for dx in (-6.75, 6.75):
        adds.append(cyl_y(pol_cx + dx, pol_cz, Y_FL2, Y_FL2 + 3.0, 5.0))
    # warner pocket: two side walls, top wall, two ledges (header slot between them)
    wx0, wx1 = WARN_POCKET["x"]; wz0, wz1 = WARN_POCKET["z"]
    adds.append(box(wx0, wx0 + T_IW, Y_FL2, Y_IN2 - 0.3, wz0, wz1))
    adds.append(box(wx1 - T_IW, wx1, Y_FL2, Y_IN2 - 0.3, wz0, wz1))
    adds.append(box(wx0, wx1, Y_FL2, Y_IN2 - 0.3, wz1 - T_IW, wz1))
    bx0, bx1 = BAL_SLOT["x"]
    adds.append(box(wx0 + T_IW, bx0, Y_FL2, Y_FL2 + 20.0, 276.0, 278.0))
    adds.append(box(bx1, wx1 - T_IW, Y_FL2, Y_FL2 + 20.0, 276.0, 278.0))
    # XY-CD63 bosses (module 62 x 56, holes (2|60, 3.5|41.5) from its lower-left corner; left = +X)
    cut_holes = [(CUT_X1 - 2.0, CUT_Z0 + 3.5), (CUT_X1 - 60.0, CUT_Z0 + 3.5),
                 (CUT_X1 - 2.0, CUT_Z0 + 41.5), (CUT_X1 - 60.0, CUT_Z0 + 41.5)]
    for (x, z) in cut_holes:
        adds.append(cyl_y(x, z, Y_FL2, Y_FL2 + 3.0, 7.5))
    # Pi 4B bosses (holes 3.5 from the edges, 58 x 49), 5 mm standoff height
    pi_holes = [(PI_X0 + 85.0 - 3.5, PI_Z0 + 3.5), (PI_X0 + 85.0 - 61.5, PI_Z0 + 3.5),
                (PI_X0 + 85.0 - 3.5, PI_Z0 + 52.5), (PI_X0 + 85.0 - 61.5, PI_Z0 + 52.5)]
    for (x, z) in pi_holes:
        adds.append(cyl_y(x, z, Y_FL2, Y_FL2 + 5.0, 6.0))
    # lid-screw bosses (heat-set) in the corners
    for (x, z) in DECK_SCREWS:
        adds.append(corner_block(x, z, Y_IN2 - H_M3_INSERT - 1.0, Y_IN2))
    deck = union_all([shell] + adds)

    cuts = []
    for (x, z) in DECK_SCREWS:                                   # screws into the base
        cuts.append(cyl_y(x, z, Y_RIM - 1, Y_FL2 + 1, D_M3_CLEAR))
        cuts.append(cyl_y(x, z, Y_IN2 - H_M3_INSERT, Y_IN2 + 1, D_M3_INSERT))   # lid inserts
    for (x, z) in cut_holes:                                     # XY-CD63: right pair slotted in X
        if abs(x - (CUT_X1 - 60.0)) < 1e-6:
            cuts.append(slot_y(x, z, Y_FL2 + 0.8, Y_FL2 + 4.0, 2.6, 4.6))
        else:
            cuts.append(cyl_y(x, z, Y_FL2 + 0.8, Y_FL2 + 4.0, 2.6))
    for (x, z) in pi_holes:
        cuts.append(cyl_y(x, z, Y_FL2 + 0.8, Y_FL2 + 6.0, D_M25_TAP))
    for dx in (-6.75, 6.75):
        cuts.append(cyl_y(pol_cx + dx, pol_cz, Y_FL2 + 0.8, Y_FL2 + 4.0, D_M2_TAP))
    # pass-throughs in the deck floor (matching openings are free space in the base bays)
    cuts.append(box(-36.0, -24.0, Y_RIM - 1, Y_FL2 + 1, 336.0, 348.0))      # USB Pi -> Waveshare
    cuts.append(box(-36.0, -24.0, Y_RIM - 1, Y_FL2 + 1, 314.0 - 8.0, 314.0 - 2.0))  # 12 V -> Waveshare jack (below band divider)
    cuts.append(box(-12.0, 0.0, Y_RIM - 1, Y_FL2 + 1, 297.0, 304.0))        # switch out -> cutoff VIN
    cuts.append(box(bx0, bx1, Y_RIM - 1, Y_FL2 + 1, BAL_SLOT["z"][0], BAL_SLOT["z"][1]))  # balancer lead
    # warner: plug pull-out through the bottom wall (always open, no tool, no lid)
    cuts.append(box(bx0, bx1, Y_FL2, Y_FL2 + 20.0, Z_BOT - 1, ZI0 + 1))
    # SD card slot in the +X wall (card sits under the board, Y 74.6..~81)
    cuts.append(box(XI - 1, XW + 1, Y_FL2, Y_FL2 + 7.0, PI_Z0 + 17.0, PI_Z0 + 39.0))
    # ventilation: bottom wall under Pololu bay and cutoff relay, top wall over the Pi
    for x in (8.0, 13.0, 18.0, 23.0, 28.0):
        cuts.append(box(x, x + 2.0, Y_FL2 + 3.0, Y_IN2 - 3.0, Z_BOT - 1, ZI0 + 1))
    for x in range(-58, -10, 8):
        cuts.append(box(x, x + 2.5, Y_FL2 + 3.0, Y_IN2 - 3.0, Z_BOT - 1, ZI0 + 1))
    for x in range(-10, 56, 7):
        cuts.append(box(x, x + 2.5, Y_FL2 + 3.0, Y_IN2 - 3.0, ZI1 - 1, Z_TOP + 1))
    deck = cut_all(deck, cuts)
    return deck

# ----------------------------------------------------------------------------
# PART 3 — lid
# ----------------------------------------------------------------------------
def build_lid():
    lid = box(-XW, XW, Y_IN2, Y_LID, Z_BOT, Z_TOP)
    cuts = []
    for (x, z) in DECK_SCREWS:
        cuts.append(cyl_y(x, z, Y_IN2 - 1, Y_LID + 1, D_M3_CLEAR))
        cuts.append(cyl_y(x, z, Y_LID - 1.0, Y_LID + 1, D_M3_HEAD))       # shallow counterbore
    # XY-CD63: display window (bottom edge, centred) and button window (right edge = -X)
    cuts.append(box(-49.0, -15.0, Y_IN2 - 1, Y_LID + 1, CUT_Z0 - 0.5, CUT_Z0 + 15.5))
    cuts.append(box(-65.0, -51.0, Y_IN2 - 1, Y_LID + 1, CUT_Z0 + 2.5, CUT_Z0 + 34.5))
    # Pi SoC vent grid (SoC ~ 25 mm from the SD edge / 25 mm from the USB-C edge)
    for k in range(6):
        z = PI_Z0 + 9.0 + 6.0 * k
        cuts.append(box(PI_X0 + 85.0 - 42.0, PI_X0 + 85.0 - 8.0, Y_IN2 - 1, Y_LID + 1, z, z + 2.5))
    # warner grille (piezo faces the lid)
    for k in range(4):
        z = 281.0 + 5.5 * k
        cuts.append(box(WARN_POCKET["x"][0] + 4.0, WARN_POCKET["x"][1] - 4.0, Y_IN2 - 1, Y_LID + 1, z, z + 2.0))
    # Pololu: probe slot over the pad row (5 V rail measurable without opening) + 2 vents
    cuts.append(box(10.0, 27.0, Y_IN2 - 1, Y_LID + 1, 259.5, 263.0))
    for z in (267.0, 271.0):
        cuts.append(box(10.0, 27.0, Y_IN2 - 1, Y_LID + 1, z, z + 2.0))
    lid = cut_all(lid, cuts)
    lid = text_cut(lid, "5V GND", 3.5, (18.5, Y_LID, 281.0), (-1, 0, 0), (0, 1, 0))
    lid = text_cut(lid, "BAL", 3.5, (51.0, Y_LID, 308.0), (-1, 0, 0), (0, 1, 0))
    return lid

# ----------------------------------------------------------------------------
# component placeholders (NOT for printing — clearance/preview only)
# ----------------------------------------------------------------------------
def build_placeholders():
    p = {}
    p["lipo"] = box(TRAY_STOP_X + 1, TRAY_STOP_X + 1 + PACK_L, Y_FL1 + 1, Y_FL1 + 26, Z_TRAY0 + 2, Z_TRAY0 + 36)
    p["waveshare"] = box(WS_C[0] - 21, WS_C[0] + 21, Y_PL1 + 4, Y_PL1 + 4 + 16, WS_C[1] - 16.5, WS_C[1] + 16.5)
    p["switch"] = box(-XI, -XI + 22, Y_FL1, Y_FL1 + 15, SW_POCKET["z"][0] + 2.5, SW_POCKET["z"][0] + 47.5)
    p["fuse_holder"] = box(-20, 20, Y_PL1 + 2, Y_PL1 + 17, Z_ROOF1 + 2, Z_ROOF1 + 17)
    p["cutoff"] = box(CUT_X1 - 62, CUT_X1, Y_FL2, Y_FL2 + 28, CUT_Z0, CUT_Z0 + 56)
    p["pi"] = box(PI_X0, PI_X0 + 85, Y_FL2 + 5, Y_FL2 + 5 + 17, PI_Z0, PI_Z0 + 56)
    p["pi_usb_plugs"] = box(PI_X0 - 20, PI_X0, Y_FL2 + 5, Y_FL2 + 22, PI_Z0 + 3, PI_Z0 + 40)
    p["pololu"] = box(POL_BAY["x"][0] + 5.6, POL_BAY["x"][0] + 5.6 + 17.8, Y_FL2 + 3, Y_FL2 + 3 + 8.8, 258.0, 278.3)
    p["warner"] = box(WARN_POCKET["x"][0] + 4, WARN_POCKET["x"][1] - 4, Y_FL2 + 1, Y_FL2 + 15, 278.0, 300.0)
    return p

# ----------------------------------------------------------------------------
def to_print(shape, y_bed):
    """robot frame -> print frame: X_p = X, Y_p = -Z, Z_p = Y - y_bed  (proper rotation, no mirror)"""
    s = shape.rotate((0, 0, 0), (1, 0, 0), 90)          # (x,y,z) -> (x, -z, y)
    return s.translate((0, 0, -y_bed))

def main():
    os.makedirs(OUT, exist_ok=True)
    parts = {}
    for name, fn, ybed in (("base", build_base, Y0), ("deck", build_deck, Y_RIM), ("lid", build_lid, Y_IN2)):
        print(f"building {name} ...")
        s = fn()
        parts[name] = s
        vol = s.val().Volume()
        bb = s.val().BoundingBox()
        c = s.val().Center()
        print(f"  volume {vol/1000:.1f} cm3, bbox X[{bb.xmin:.1f},{bb.xmax:.1f}] Y[{bb.ymin:.1f},{bb.ymax:.1f}] Z[{bb.zmin:.1f},{bb.zmax:.1f}], centroid ({c.x:.1f},{c.y:.1f},{c.z:.1f})")
        cq.exporters.export(s, os.path.join(OUT, f"backpack_v2_{name}_robotframe.stl"), tolerance=0.02, angularTolerance=0.1)
        cq.exporters.export(to_print(s, ybed), os.path.join(OUT, f"backpack_v2_{name}.stl"), tolerance=0.02, angularTolerance=0.1)
    ph = build_placeholders()
    for k, v in ph.items():
        cq.exporters.export(v, os.path.join(OUT, f"placeholder_{k}.stl"), tolerance=0.05)
    meta = {name: dict(volume_cm3=round(s.val().Volume() / 1000, 2),
                       centroid_robot_mm=[round(s.val().Center().x, 2), round(s.val().Center().y, 2), round(s.val().Center().z, 2)])
            for name, s in parts.items()}
    meta["frame"] = "robot frame of the pinned assembly (mm): +X left, +Y back, +Z up; torso back wall Y=38.1"
    meta["depth_mm"] = dict(base=[Y0, Y_RIM], deck=[Y_RIM, Y_IN2], lid=[Y_IN2, Y_LID], total=Y_LID - Y0)
    with open(os.path.join(OUT, "parts.json"), "w") as f:
        json.dump(meta, f, indent=2)
    print("done ->", OUT)

if __name__ == "__main__":
    main()
