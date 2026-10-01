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

# ---------------- envelope & stack (v4: zwei Lagen, Pi im Rucksack) ----------------
XW = 80.0; Z_BOT, Z_TOP = 254.0, 416.0
T_PLATE, T_BOSS, T_OW, T_IW, D1, T_LID = 3.0, 3.0, 2.5, 2.0, 61.0, 2.0   # D1 61 = Pi-Lage 20 + Elektronikebene 41
Y_PL1 = Y0 + T_PLATE; Y_FL1 = Y_PL1 + T_BOSS; Y_RIM = Y_FL1 + D1; Y_LID = Y_RIM + T_LID   # 41.1 / 44.1 / 105.1 / 107.1
Y_PI = Y_PL1 + 2.0                                      # 43.1 Unterseite der Pi-Platine (2 mm Standoffs)
Y_DECK = Y_PL1 + 20.0                                   # 61.1 Oberkante der Pi-Lage
Y_CAB = Y_RIM - 15.1                                    # 90.0 Kabelebene (Deckel-Cradles)
XI = XW - T_OW; ZI0, ZI1 = Z_BOT + T_OW, Z_TOP - T_OW   # +-77.5, 256.5..413.5
Z_TRAY1 = ZI0 + 38.0; Z_DIV1 = Z_TRAY1 + T_IW           # 294.5 / 296.5
PACK_X = (-76.5, 29.5); STRAP_X = (31.0, 35.0)

# --- vordere Lage: Pi quer (v4.2), Waveshare am Deckel ------------------------------------------------------------------
# v4.3 (2026-09-22): SD_GAP 6,5 mm zwischen SD-Kante und Seitenwand + microSD-Fenster in der Seitenwand [Vorgabe].
# v4.4 (2026-09-22): Netzteilstecker braucht >= 35 mm gerade vor der USB-C-Kante [Vorgabe] (v4.3: 15 mm fuer einen 90-Grad-Stecker).
# In der Lage v4.3 (SD-Kante -X, USB-C-Kante oben) ist das nicht erfuellbar: 35 mm unter der Decke (413,5) zwingt die Platine auf
# z <= 378,5, dann liegt sie auf dem Schraubdom der Torsoschraube (-47,2 / 330,3), der frei bleiben muss (Rucksack laesst sich
# sonst nicht mehr vom Torso loesen). Loesung: Pi um 180 Grad in der Ebene gedreht - SD-Kante an +X (Fenster in der +X-Wand),
# USB-C-Kante unten mit 40 mm bis zum Zwischenboden, Ethernet/USB-A nach -X (50 mm Steckerzone, von hinten erreichbar), Platine
# knapp ueber dem +X-Schraubdom (z 337 > 335,3). Aussenmasse unveraendert. Der Pololu weicht nach links unten aus.
SD_GAP = 6.5                                            # Platinenkante (SD-Seite) -> Innenflaeche der Seitenwand
SD_SIDE = +1                                            # Seitenwand mit dem microSD-Fenster: +1 = +X-Wand (Roboter links), -1 = -X-Wand
PI_X = (XI - SD_GAP - 85.0, XI - SD_GAP)                # -14 .. 71: SD-Kante bei x 71, Ethernet/USB-A-Kante bei x -14
PI_Z = (337.0, 393.0)                                   # USB-C-Kante unten (337 -> 40,5 mm bis zum Zwischenboden 296,5), ueber dem Dom (47,2/330,3)
Z_USBC_FREE = PI_Z[0] - Z_DIV1                          # 40,5 >= 35 [Vorgabe]
assert Z_USBC_FREE >= 35.0 and PI_Z[0] > TORSO_HOLES[3][1] + 5.0
# microSD (Pi 4B: Unterseite, mittig auf der 56-mm-Kante, Karte 11 x 15 x 1, ~3 mm Ueberstand) -> Fenster in der Seitenwand zum
# Stecken/Ziehen [Vorgabe]: 24 mm breit (z), ab Plattenoberkante 6,4 mm gerade, dann 45-Grad-Dach auf 4 mm Steg (Druck ohne Support,
# Platte liegt auf dem Bett), Eintrittskante aussen 1 mm angefast, Ecken R 1.
SD_Z = (PI_Z[0] + PI_Z[1]) / 2                          # 365 Kartenmitte
SD_CARD = dict(x=(PI_X[1] - 12.0, PI_X[1] + 3.0), z=(SD_Z - 5.5, SD_Z + 5.5))   # Karte gesteckt: 12 mm im Halter, 3 mm frei
SD_WIN = dict(hw=12.0, y0=Y_PL1, y_str=Y_PL1 + 6.4, hw_top=2.0, y_top=Y_PL1 + 6.4 + 10.0)   # z-Halbbreite, Unter-/Knick-/Firsthoehe
PI_HOLES = [(PI_X[1] - 3.5, PI_Z[0] + 3.5), (PI_X[1] - 61.5, PI_Z[0] + 3.5),
            (PI_X[1] - 3.5, PI_Z[1] - 3.5), (PI_X[1] - 61.5, PI_Z[1] - 3.5)]   # Lochbild 58 x 49, 3,5 mm von der SD-Kante
D_PI_SHAFT, D_PI_CB, H_PI_CB = 2.4, 4.5, 2.4          # Pi von der Torsoseite verschraubt: M2 Durchgang, Senkung fuer Zylinderkopf 4 x 2 (Aufmass 0,5 / 0,4) [Vorgabe]
PI_PLUGS = dict(x=(PI_X[0] - 50.0, PI_X[0]), z=PI_Z)    # Ethernet + USB-A mit Steckern: 50 mm nach -X [Vorgabe] (bis zur Wand 63,5 mm frei)
assert PI_PLUGS["x"][0] >= -XI and PI_PLUGS["z"][0] > TORSO_HOLES[2][1] + 5.0   # Steckerzone in der Wanne, ueber dem -X-Schraubdom
PI_USBC = dict(x=(PI_X[1] - 11.2 - 7.0, PI_X[1] - 11.2 + 7.0), z=(PI_Z[0] - 35.0, PI_Z[0]))   # USB-C 11,2 mm von der SD-Kante, gerader Stecker + Kabel 35 mm nach unten [Vorgabe]
PI_CSI = (PI_X[1] - 45.0, PI_Z[0] + 11.5)               # Kamerabuchse (CSI) zwischen HDMI und Klinke, 11,5 mm von der USB-C-Kante
_cs = json.load(open(os.path.join(HERE, "..", "head_cam", "cam3_pose.json")))["cable_slot"]
CAM_SLOT = dict(x=tuple(_cs["x"]), z=tuple(_cs["z"]))   # Kamera-Flachband: gleiche Achse + Hoehe wie der Schlitz in der Kopfplatte [Vorgabe]
# Waveshare am Deckel: Bauteilseite zum Torso, Servostecker an der oberen Kante (42 mm Zone), DC/USB-C-Seite dadurch bei -X;
# vier Kunststoffsockel am Deckel fuer M2 (Metallsockel entfernt) [Vorgabe]
WS_X, WS_Z = (34.5, 76.5), (298.0, 331.0)               # 42 x 33, 1,5 mm ueber dem Zwischenboden, 1 mm zur Seitenwand
WS_PLUG_Z = (WS_Z[1], WS_Z[1] + 42.0)                   # 42 mm fuer Servostecker + Biegeradien
WS_DC = dict(x=(WS_X[0] - 13.0, WS_X[0] - 1.0), z=(WS_Z[0] + 2.0, WS_Z[0] + 30.0))   # DC / USB-C des Adapters
WS_DX, WS_DZ = 37.0, 28.0                               # Lochbild
WS_HOLES = [((WS_X[0] + WS_X[1]) / 2 + sx * WS_DX / 2, (WS_Z[0] + WS_Z[1]) / 2 + sz * WS_DZ / 2) for sx in (-1, 1) for sz in (-1, 1)]
H_WS_BOSS, D_WS_BOSS = 4.0, 5.5                         # Sockel am Deckel
D_M2_BORE = 1.9                                         # M2 in Kunststoffsockeln (wie die Kameradome) [Vorgabe]
D_WS_BORE = D_M2_BORE + 0.3                             # v4.5: Waveshare-Sockel 0,3 mm weiter (2,2) [Vorgabe]
POL_C = (-63.0, 308.0)                                  # Pololu in der vorderen Lage links unten (v4.4: Platz des Pi-Steckerraums), Loetpads oben
POL_HOLES = [(POL_C[0] - 6.75, POL_C[1] + 8.0), (POL_C[0] + 6.75, POL_C[1] - 8.0)]   # diagonal 13,5 x 16,0 (Pololu-Zeichnung) [Vorgabe]
PASS_A = dict(x=(11.0, 22.0), z=(300.0, 335.0))         # Durchfuehrung ins Torso-Fenster (Servobus)
TEST_PINS = [(-60.0, 325.0), (-54.0, 325.0)]            # 5V / GND im Deckel: zwischen XT60-Cradle (z <= 318) und Schalterpad (z >= 336)

# --- Elektronikebene / Kabelebene (am Deckel) ----------------------------------------------------
CUT_X1, CUT_Z0 = 31.0, 340.0                            # XY-CD63 62 x 56, mittig, am DECKEL verschraubt
CUT_Z1 = CUT_Z0 + 56.0                                  # 396 Oberkante des Moduls
CUT_TERM_Z = CUT_Z1 - 2.0                               # 394 Klemmen an der OBEREN Kante, Leitungen kommen senkrecht von oben [Vorgabe]
CUT_TERM_H = 16.0                                       # Kabelzone ueber dem Modul bis z 412 (Decke innen 413,5)
# 2026-09-19: Modul mit dem Display nach INNEN montiert [Vorgabe] (Relais zu hoch fuer die andere Richtung), Klemmen oben ->
# um die Hochachse gedreht: VIN (Blick aufs Display links) liegt jetzt bei -X zum Schalter, OUT bei +X zu Pololu/Waveshare
CUT_VIN_X, CUT_OUT_X = (CUT_X1 - 62.0, CUT_X1 - 31.0), (CUT_X1 - 31.0, CUT_X1)
CUT_DX = 56.5                                           # v4.5: Lochabstand auf der langen Seite 58 -> 56,5 (am Modul gemessen 1,5 mm enger) [Vorgabe]
CUT_HOLES = [(CUT_X1 - 31.0 + CUT_DX / 2, CUT_Z0 + 3.5), (CUT_X1 - 31.0 - CUT_DX / 2, CUT_Z0 + 3.5),
             (CUT_X1 - 31.0 + CUT_DX / 2, CUT_Z0 + 41.5), (CUT_X1 - 31.0 - CUT_DX / 2, CUT_Z0 + 41.5)]   # +-28,25 / z 343,5 + 381,5, mittig zum Modul
D_CUT_SHAFT, D_CUT_CB, H_CUT_CB, D_CUT_PAD = 3.3, 6.0, 3.4, 12.0   # Durchgang, Senkung, Tiefe, Verdickung im Deckel
Y_CUT_TOP = Y_RIM - 3.0                                 # 102.1 Auflage des Moduls an den Deckelpads
Y_WS_BOARD = Y_RIM - H_WS_BOSS                          # 101.1 Rueckseite der Waveshare-Platine
# Anti-Spark-Hauptschalter (2026-09-19): von aussen durch den Deckel eingesetzt [Vorgabe] - Einsatz 15 x 34 hochkant, zwei
# Schrauben Ø2 auf der senkrechten Mittelachse, 40 mm Mittenabstand. Deckel: Ausschnitt mit SW_CLEAR Spiel je Seite,
# Bohrungen Ø1,9 fuer M2 (wie die Kameradome) durch Deckel + 3 mm Verstaerkung innen. Die alte Innenhalterung entfaellt.
SW_C = (-64.0, 358.5)                                  # an der bisherigen Stelle
SW_INSERT, SW_CLEAR = (15.0, 34.0), 0.25
# v4.5 (2026-09-22): Der Einsatz hat an den Schrauben eigene Sockel (Ø5 x 3 mm hoch, wie die Deckelpads) [Vorgabe]. Sie werden von
# aussen in Ø5,5 x 3 mm tiefe Aussparungen eingelassen (0,25 mm Spiel je Seite); die Innenpads sind dafuer auf 6 mm Hoehe und Ø7,5
# gewachsen, so bleiben unter der Aussparung wieder 5 mm Gewindelaenge (2 mm Deckel + 6 mm Pad - 3 mm Aussparung).
SW_SCREW_DZ, D_SW_PAD, H_SW_PAD = 40.0, 7.5, 6.0
SW_BOSS = dict(d=5.0, h=3.0)                           # Sockel am Einsatz
D_SW_RECESS, H_SW_RECESS = SW_BOSS["d"] + 2 * SW_CLEAR, SW_BOSS["h"]   # 5,5 x 3,0 von aussen
assert T_LID + H_SW_PAD - H_SW_RECESS >= 5.0
SW_SCREWS = [(SW_C[0], SW_C[1] - SW_SCREW_DZ / 2), (SW_C[0], SW_C[1] + SW_SCREW_DZ / 2)]
SW_BODY = dict(x=(SW_C[0] - SW_INSERT[0] / 2, SW_C[0] + SW_INSERT[0] / 2), z=(SW_C[1] - SW_INSERT[1] / 2, SW_C[1] + SW_INSERT[1] / 2),
               y=(Y_CAB + 0.1, Y_RIM))                 # Schalterkoerper hinter dem Deckel, Tiefe 15 [S]
FUSE_HOLDER = dict(x=(-47.0, -7.0), z=(259.0, 274.0), y=(Y_CAB + 0.1, Y_RIM))
FUSE_RIBS = ((-49.0, -47.0), (-7.0, -5.0))
XT_LIPO = dict(x=(-4.0, 36.0), z=(259.0, 274.0), y=(Y_CAB, Y_CAB + 8.0))
XT_LIPO_RIBS = ((-6.0, -4.0), (36.0, 38.0))
XT_SW = dict(x=(-69.0, -53.0), z=(276.0, 316.0), y=(Y_CAB, Y_CAB + 8.0))
XT_SW_RIBS = ((-71.0, -69.0), (-53.0, -51.0))
WARN = dict(x=(38.0, 73.0), z=(269.0, 291.0), y=(Y_CAB, Y_CAB + 14.0))   # v4.2: +3 mm, sein Balancer-Stecker lag 2 mm im XT60-Paar LiPo/Sicherung
WARN_RIBS = ((36.0, 38.0), (73.0, 75.0))
CORNER_SCREWS = [(-74.0, 260.0), (74.0, 260.0), (-74.0, 410.0), (74.0, 410.0)]
D_M3_CLEAR, D_M3_HEAD, H_M3_HEAD = 3.4, 6.6, 3.2
D_TORSO_HOLE = 4.0                                      # v4.6: Durchgang der vier Torsoschrauben Ø4,0 [Vorgabe] (Deckel-Eckschrauben bleiben 3,4)
D_TORSO_CB, H_TORSO_CB = 7.0, 4.0                       # v4.6: Senkung der Torsoschrauben Ø7,0 x 4,0 [Vorgabe]: 3 mm Dom + 1 mm in die Platte, Restwand im Dom 1,5, unter dem Kopf 2 mm
assert T_BOSS + T_PLATE - H_TORSO_CB >= 2.0
D_M3_INS, H_M3_INS, D_M25_TAP, D_M2_TAP = 4.0, 6.0, 2.2, 1.7

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
def sd_window_tool(r=1.0, c=1.0, side=None):
    """Cut tool for the microSD window in the side wall SD_SIDE (v4.3: -X, v4.4: +X): a 'house' profile in the YZ plane (flat bottom on the
    plate, vertical flanks, 45-degree roof to a short ridge -> prints support-free with the plate on the bed), corners
    rounded with r, and a 45-degree chamfer c of the entry edge on the outer face (x = -XW). One ruled loft, one solid."""
    w = SD_WIN; base_pts = [(w["y0"] - 3.0 + r, -w["hw"] + r), (w["y0"] - 3.0 + r, w["hw"] - r), (w["y_str"] - r * 0.41, w["hw"] - r),
                            (w["y_top"] - r, w["hw_top"] - r * 0.41), (w["y_top"] - r, -w["hw_top"] + r * 0.41), (w["y_str"] - r * 0.41, -w["hw"] + r)]
    # (y, z) polygon shrunk by ~r; offset2D(r) gives the nominal outline with rounded corners, offset2D(r + c) the chamfer outline.
    # The bottom edge runs 3 mm below the plate top so the window's floor is the plate itself (no lip to lift the card over).
    pts = [(y, z + SD_Z) for (y, z) in base_pts]
    sd = SD_SIDE if side is None else side
    def wire(x, d): return cq.Workplane("YZ", origin=(x, 0, 0)).polyline(pts).close().offset2D(d).val()
    secs = [wire(sd * (XW + 1.3), r + c), wire(sd * XW, r + c), wire(sd * (XW - c), r), wire(sd * (XI - 1.0), r)]   # outside -> chamfer -> straight through the wall
    t = cq.Workplane("XY").add(cq.Solid.makeLoft(secs, True))
    assert t.val().Volume() > 0, "sd window tool inverted"
    xa, xb = sorted((sd * (XW + 2.0), sd * (XI - 1.0)))
    return t.intersect(box(xa, xb, Y_PL1, Y_RIM, Z_BOT, Z_TOP))   # never below the plate top

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
def build_base():
    shell = soften(box(-XW, XW, Y0, Y_RIM, Z_BOT, Z_TOP)).cut(box(-XI, XI, Y_PL1, Y_RIM + 1, ZI0, ZI1).edges("|Y").fillet(R_POCKET))
    a = []
    a.append(chamfer_free(box(-XI, XI, Y_PL1, Y_RIM, Z_TRAY1, Z_DIV1), ">Y", 0.8))          # Zwischenboden
    for (x, z) in TORSO_HOLES: a.append(chamfer_free(cyl_y(x, z, Y_PL1, Y_FL1, 10.0), ">Y"))
    a.append(chamfer_free(box(-XI, PACK_X[1] + 6.0, Y_PL1, Y_FL1, ZI0, ZI0 + 4.0), ">Y"))   # LiPo-Schienen
    a.append(chamfer_free(box(-XI, PACK_X[1] + 6.0, Y_PL1, Y_FL1, Z_TRAY1 - 4.0, Z_TRAY1), ">Y"))
    for (x, z) in PI_HOLES: a.append(chamfer_free(cyl_y(x, z, Y_PL1, Y_PI, 6.0), ">Y"))     # Pi-Standoffs 2 mm
    for (x, z) in POL_HOLES: a.append(chamfer_free(cyl_y(x, z, Y_PL1, Y_PL1 + 3.0, 5.0), ">Y"))                          # Pololu, diagonal
    for (x, z) in CORNER_SCREWS: a.append(corner_block(x, z, Y_RIM - H_M3_INS - 1.0, Y_RIM))
    base = union_all([shell] + a)

    PL = ((Y0, 1), (Y_PL1, -1)); FLOOR = ((Z_BOT, 1), (ZI0, -1)); TRAY = ((Z_TRAY1, 1), (Z_DIV1, -1))
    TOP = ((ZI1, 1), (Z_TOP, -1)); XWALL = ((XI, 1), (XW, -1))
    c = []
    for (x, z) in TORSO_HOLES:
        c.append(soft_cyl(x, z, Y0 - 1, Y_FL1 + 1, D_TORSO_HOLE, ((Y0, 1),))); c.append(soft_cyl(x, z, Y_FL1 - H_TORSO_CB, Y_FL1 + 1, D_TORSO_CB, ((Y_FL1, -1),)))
    for (x, z) in CORNER_SCREWS: c.append(soft_cyl(x, z, Y_RIM - H_M3_INS, Y_RIM + 1, D_M3_INS, ((Y_RIM, -1),)))
    for (x, z) in PI_HOLES:                                                # Pi: M2 von der Torsoseite durch Platte + Standoff, Kopf versenkt
        c.append(soft_cyl(x, z, Y0 - 1, Y_PI + 1.0, D_PI_SHAFT, ((Y_PI, -1),), c=0.4))
        c.append(soft_cyl(x, z, Y0 - 1, Y0 + H_PI_CB, D_PI_CB, ((Y0, 1),), c=0.4))
    for (x, z) in POL_HOLES: c.append(soft_cyl(x, z, Y_PL1 - 1.0, Y_PL1 + 4.0, D_M2_BORE, ((Y_PL1 + 3.0, -1),), c=0.3))
    c.append(soft_tool(PASS_A["x"][0], PASS_A["x"][1], Y0 - 1, Y_PL1 + 1, PASS_A["z"][0], PASS_A["z"][1], "y", PL, c=0.8, r=3.0))
    for z in range(346, 381, 8): c.append(soft_tool(15.0, 62.0, Y0 - 1, Y_PL1 + 1, z, z + 3.0, "y", PL, c=0.6, r=1.2))     # Lueftung unter dem Pi (frei von Standoffs/Senkungen, v4.4 mitgewandert)
    c.append(soft_tool(CAM_SLOT["x"][0], CAM_SLOT["x"][1], Y0 - 1, Y_PL1 + 1, CAM_SLOT["z"][0], CAM_SLOT["z"][1], "y", PL, c=0.6, r=1.0))   # Kamera-Flachband
    c.append(soft_tool(XI - 1, XW + 1, Y_PL1, Y_RIM + 1, ZI0, Z_TRAY1, "x", XWALL, c=1.0, r=2.0))                            # LiPo-Schublade
    c.append(sd_window_tool())                                                                                                 # v4.3/4.4: microSD-Fenster in der Seitenwand SD_SIDE
    c.append(soft_tool(STRAP_X[0], STRAP_X[1], 46.0, 70.0, Z_BOT - 1, ZI0 + 1, "z", FLOOR, c=0.6, r=1.5))
    c.append(soft_tool(STRAP_X[0], STRAP_X[1], 46.0, 70.0, Z_TRAY1 - 1, Z_DIV1 + 1, "z", TRAY, c=0.6, r=1.5))
    c.append(soft_tool(XT_SW["x"][0] - 2.0, XT_SW["x"][1] + 2.0, Y_CAB - 2.0, Y_RIM + 1, Z_TRAY1 - 1, Z_DIV1 + 1, "z", TRAY, c=0.8, r=2.0))
    c.append(soft_tool(-18.0, 6.0, Y_DECK, Y_RIM + 1, Z_TRAY1 - 1, Z_DIV1 + 1, "z", TRAY, c=0.8, r=2.0))                     # Kabel aus dem unteren Fach nach oben
    for x in range(-24, 30, 7): c.append(soft_tool(x, x + 2.5, 50.0, 70.0, ZI1 - 1, Z_TOP + 1, "z", TOP, c=0.6, r=1.0))
    return cut_all(base, c)

# ============================================================== lid
def build_lid():
    lid = soften(box(-XW, XW, Y_RIM, Y_LID, Z_BOT, Z_TOP), chamfer_faces=(">Y",))
    a = [chamfer_free(cyl_y(x, z, Y_RIM - 3.0, Y_RIM, D_CUT_PAD), "<Y", 0.6) for (x, z) in CUT_HOLES]   # Verdickung fuer die Senkungen
    a += [chamfer_free(cyl_y(x, z, Y_WS_BOARD, Y_RIM, D_WS_BOSS), "<Y", 0.4) for (x, z) in WS_HOLES]     # Waveshare-Sockel (M2)
    def lid_cradle(ribs, z0, z1, lips=(True, True)):
        for (x0, x1), lip in zip(ribs, lips):
            a.append(chamfer_free(box(x0, x1, Y_CAB, Y_RIM, z0, z1), "<Y"))
            if lip:
                inward = 1.0 if x0 < (ribs[0][0] + ribs[1][1]) / 2 else -1.0
                x_in, x_out, x_far = (x1, x1 + 2.0, x0) if inward > 0 else (x0, x0 - 2.0, x1)
                a.append(cq.Workplane("XY", origin=(0, 0, z0)).polyline([(x_far, Y_CAB), (x_in, Y_CAB), (x_out, Y_CAB - 2.0), (x_far, Y_CAB - 2.0)]).close().extrude(z1 - z0))
    a += [chamfer_free(cyl_y(x, z, Y_RIM - H_SW_PAD, Y_RIM, D_SW_PAD), "<Y", 0.4) for (x, z) in SW_SCREWS]   # Verstaerkung der Schalterschrauben
    lid_cradle(FUSE_RIBS, FUSE_HOLDER["z"][0] - 2.0, FUSE_HOLDER["z"][1] + 2.0)
    lid_cradle(XT_LIPO_RIBS, XT_LIPO["z"][0] - 2.0, XT_LIPO["z"][1] + 2.0)
    lid_cradle(XT_SW_RIBS, XT_SW["z"][0] - 2.0, XT_SW["z"][1] + 2.0)
    lid_cradle(WARN_RIBS, WARN["z"][0] - 1.0, WARN["z"][1] + 2.0)
    lid = union_all([lid] + a)

    LP = ((Y_RIM - 3.0, 1), (Y_LID, -1))
    c = []
    for (x, z) in CORNER_SCREWS: c.append(soft_cyl(x, z, Y_RIM - 1, Y_LID + 1, D_M3_CLEAR, ((Y_RIM, 1),))); c.append(soft_cyl(x, z, Y_LID - 1.0, Y_LID + 1, D_M3_HEAD, ((Y_LID, -1),)))
    for (x, z) in CUT_HOLES:                                                   # Cutoff von aussen verschraubt
        c.append(soft_cyl(x, z, Y_RIM - 4.0, Y_LID + 1, D_CUT_SHAFT, ((Y_RIM - 3.0, 1),), c=0.4))
        c.append(soft_cyl(x, z, Y_LID - H_CUT_CB, Y_LID + 1, D_CUT_CB, ((Y_LID, -1),), c=0.5))
    for z in range(343, 376, 5): c.append(soft_tool(-20.0, 20.0, Y_RIM - 1, Y_LID + 1, z, z + 2.0, "y", LP, c=0.5, r=0.9))        # Lueftung ueber dem Cutoff (Display/Taster zeigen nach innen)
    c.append(soft_tool(FUSE_HOLDER["x"][0] + 1.0, FUSE_HOLDER["x"][1] - 1.0, Y_RIM - 1, Y_LID + 1, FUSE_HOLDER["z"][0] + 1.0, FUSE_HOLDER["z"][1] - 1.0, "y", LP, c=0.8, r=2.0))
    hx, hz = SW_INSERT[0] / 2 + SW_CLEAR, SW_INSERT[1] / 2 + SW_CLEAR                                                          # Hauptschalter von aussen
    c.append(soft_tool(SW_C[0] - hx, SW_C[0] + hx, Y_RIM - H_SW_PAD - 0.1, Y_LID + 1, SW_C[1] - hz, SW_C[1] + hz, "y", LP, c=0.4, r=0.5))   # v4.5: durch die ganze Padhoehe (Pads enden am Ausschnitt)
    for (x, z) in SW_SCREWS:
        c.append(soft_cyl(x, z, Y_RIM - H_SW_PAD - 0.1, Y_LID + 1, D_M2_BORE, ((Y_LID, -1),), c=0.3))                          # M2 durch Pad + Deckel
        c.append(soft_cyl(x, z, Y_LID - H_SW_RECESS, Y_LID + 1, D_SW_RECESS, ((Y_LID, -1),), c=0.3))                          # v4.5: Aussparung fuer den Einsatz-Sockel
        zc = SW_C[1] - hz - 0.5 if z > SW_C[1] else SW_C[1] + hz + 0.5                                                          # ... zum Ausschnitt hin offen (0,5 mm Ueberlappung statt
        c.append(soft_tool(x - D_SW_RECESS / 2, x + D_SW_RECESS / 2, Y_LID - H_SW_RECESS, Y_LID + 1, min(z, zc), max(z, zc), "y", ((Y_LID, -1),), c=0.3, r=0.5))   # tangentialer Beruehrung)
    for k in range(4): z = WARN["z"][0] + 4.0 + 4.0 * k; c.append(soft_tool(WARN["x"][0] + 5.0, WARN["x"][1] - 5.0, Y_RIM - 1, Y_LID + 1, z, z + 2.0, "y", LP, c=0.5, r=0.9))
    for k in range(3): z = CUT_Z0 + 40.0 + 5.0 * k; c.append(soft_tool(CUT_X1 - 45.0, CUT_X1 - 21.0, Y_RIM - 1, Y_LID + 1, z, z + 2.0, "y", LP, c=0.5, r=0.9))   # Relais
    for k in range(3): z = 300.0 + 8.0 * k; c.append(soft_tool(-40.0, 4.0, Y_RIM - 1, Y_LID + 1, z, z + 2.5, "y", LP, c=0.6, r=1.1))                             # Lueftung Pi/Waveshare
    for (x, z) in TEST_PINS: c.append(soft_cyl(x, z, Y_RIM - 1, Y_LID + 1, 2.2, ((Y_RIM, 1), (Y_LID, -1)), c=0.4))                                              # 5-V-Messpunkte
    for (x, z) in WS_HOLES: c.append(soft_cyl(x, z, Y_WS_BOARD - 0.1, Y_RIM + 1.0, D_WS_BORE, ((Y_WS_BOARD, 1),), c=0.3))                                      # M2 in die Sockel (Ø2,2), 1 mm Deckel bleibt
    lid = cut_all(lid, c)
    c2 = []
    for (x0, x1) in FUSE_RIBS + XT_LIPO_RIBS:
        c2.append(soft_tool(x0 - 1, x1 + 1, Y_CAB - 3.0, Y_RIM, 261.0, 272.0, "x", ((x0, 1), (x1, -1)), c=0.8, r=2.0))
    for (x0, x1) in XT_LIPO_RIBS: c2.append(soft_tool(x0 - 1, x1 + 1, Y_CAB + 1.0, Y_CAB + 11.0, 275.0, 279.0, "x", ((x0, 1), (x1, -1)), c=0.6, r=1.5))
    c2.append(soft_tool(WARN["x"][0] - 16.0, WARN["x"][0] - 2.0, Y_RIM - 1, Y_LID + 1, WARN["z"][0] + 5.0, WARN["z"][1] - 5.0, "y", LP, c=0.8, r=2.5))
    lid = cut_all(lid, c2)
    lid = text_cut(lid, "5V", 3.0, (TEST_PINS[0][0] - 5.0, Y_LID, TEST_PINS[0][1]), (-1, 0, 0), (0, 1, 0))
    lid = text_cut(lid, "GND", 3.0, (TEST_PINS[1][0] + 6.5, Y_LID, TEST_PINS[1][1]), (-1, 0, 0), (0, 1, 0))
    lid = text_cut(lid, "30A", 5.0, (-27.0, Y_LID, 279.5), (-1, 0, 0), (0, 1, 0))
    return text_cut(lid, "BAL", 3.5, (WARN["x"][0] - 9.0, Y_LID, WARN["z"][0] - 1.0), (-1, 0, 0), (0, 1, 0))

# ============================================================== Platzhalter (verkabelte Huellen)
def build_placeholders():
    p = {}
    p["lipo"] = box(PACK_X[0], PACK_X[1], Y_FL1 + 1, Y_FL1 + 26, ZI0 + 2, ZI0 + 36)
    p["warner"] = box(WARN["x"][0], WARN["x"][1], WARN["y"][0], WARN["y"][1], WARN["z"][0], WARN["z"][1])
    p["warner_plug"] = box(WARN["x"][0] - 16.0, WARN["x"][0] - 2.0, WARN["y"][0] + 2.0, WARN["y"][0] + 9.0, WARN["z"][0] + 6.0, WARN["z"][0] + 16.0)
    p["cutoff"] = box(CUT_X1 - 62, CUT_X1, Y_CUT_TOP - 28.0, Y_CUT_TOP, CUT_Z0, CUT_Z0 + 56)
    p["cutoff_vin_wires"] = box(CUT_VIN_X[0], CUT_VIN_X[1], Y_CUT_TOP - 22.0, Y_CUT_TOP - 8.0, CUT_Z1, CUT_Z1 + CUT_TERM_H)
    p["cutoff_out_wires"] = box(CUT_OUT_X[0], CUT_OUT_X[1], Y_CUT_TOP - 22.0, Y_CUT_TOP - 8.0, CUT_Z1, CUT_Z1 + CUT_TERM_H)
    y_head = Y_LID - H_CUT_CB
    p["cutoff_screws"] = union_all([cyl_y(x, z, y_head, y_head + 3.0, 5.5).union(cyl_y(x, z, y_head - 10.0, y_head, 3.0)) for (x, z) in CUT_HOLES])
    y_pi_head = Y0 + H_PI_CB - 2.0                                         # Kopf 2 mm hoch, 0,4 mm versenkt
    p["pi_screws"] = union_all([cyl_y(x, z, y_pi_head, y_pi_head + 2.0, 4.0).union(cyl_y(x, z, y_pi_head + 2.0, y_pi_head + 10.0, 2.0))
                                .union(cyl_y(x, z, Y_PI + 1.5, Y_PI + 3.1, 4.6)) for (x, z) in PI_HOLES])   # 4x M2x8 + Mutter auf der Platine
    p["pi"] = box(PI_X[0], PI_X[1], Y_PI, Y_PI + 17.5, PI_Z[0], PI_Z[1])
    p["pi_sd"] = box(SD_CARD["x"][0], SD_CARD["x"][1], Y_PI - 1.7, Y_PI - 0.7, SD_CARD["z"][0], SD_CARD["z"][1])   # microSD gesteckt, 3 mm Ueberstand
    p["pi_plugs"] = box(PI_PLUGS["x"][0], PI_PLUGS["x"][1], Y_PI, Y_PI + 16.0, PI_PLUGS["z"][0], PI_PLUGS["z"][1])
    p["pi_usbc_plug"] = box(PI_USBC["x"][0], PI_USBC["x"][1], Y_PI, Y_PI + 12.0, PI_USBC["z"][0], PI_USBC["z"][1])   # gerader Stecker + Kabel, 35 mm nach unten
    p["waveshare"] = box(WS_X[0], WS_X[1], Y_WS_BOARD - 16, Y_WS_BOARD, WS_Z[0], WS_Z[1])                 # am Deckel, Bauteile Richtung Torso
    p["waveshare_servo_plugs"] = box(WS_X[0], WS_X[1], Y_WS_BOARD - 15, Y_WS_BOARD, WS_PLUG_Z[0], WS_PLUG_Z[1])
    p["waveshare_plugs"] = box(WS_DC["x"][0], WS_DC["x"][1], Y_WS_BOARD - 14, Y_WS_BOARD, WS_DC["z"][0], WS_DC["z"][1])
    # Kamera-Flachband (16 mm breit): aus dem Schlitz auf der Platte nach unten, ueber der Pi-Oberkante (z 395..411) nach +X, dort
    # einmal gefaltet und ueber die Platine (ueber der GPIO-Leiste) hinunter zur CSI-Buchse
    z_band = (PI_Z[1] + 2.0, PI_Z[1] + 18.0)
    p["cam_ribbon"] = (box(CAM_SLOT["x"][0], CAM_SLOT["x"][1], Y_PL1, Y_PL1 + 3.0, z_band[0], CAM_SLOT["z"][1])
                       .union(box(CAM_SLOT["x"][0], PI_CSI[0] + 8.0, Y_PL1, Y_PL1 + 2.0, z_band[0], z_band[1]))
                       .union(box(PI_CSI[0] - 8.0, PI_CSI[0] + 8.0, Y_PL1, Y_PI + 13.0, z_band[0], z_band[1]))
                       .union(box(PI_CSI[0] - 8.0, PI_CSI[0] + 8.0, Y_PI + 11.0, Y_PI + 13.0, PI_CSI[1] - 3.0, z_band[1])))
    p["switch"] = box(SW_BODY["x"][0], SW_BODY["x"][1], SW_BODY["y"][0], SW_BODY["y"][1], SW_BODY["z"][0], SW_BODY["z"][1])
    p["switch_bosses"] = union_all([cyl_y(x, z, Y_LID - SW_BOSS["h"], Y_LID, SW_BOSS["d"]) for (x, z) in SW_SCREWS])   # v4.5: Sockel des Einsatzes, in den Deckel eingelassen
    p["fuse_holder"] = box(FUSE_HOLDER["x"][0], FUSE_HOLDER["x"][1], FUSE_HOLDER["y"][0], FUSE_HOLDER["y"][1], FUSE_HOLDER["z"][0], FUSE_HOLDER["z"][1])
    p["xt60_lipo_fuse"] = box(XT_LIPO["x"][0], XT_LIPO["x"][1], XT_LIPO["y"][0], XT_LIPO["y"][1], XT_LIPO["z"][0], XT_LIPO["z"][1])
    p["xt60_fuse_switch"] = box(XT_SW["x"][0], XT_SW["x"][1], XT_SW["y"][0], XT_SW["y"][1], XT_SW["z"][0], XT_SW["z"][1])
    p["pololu"] = box(POL_C[0] - 8.9, POL_C[0] + 8.9, Y_PL1 + 3.0, Y_PL1 + 3.0 + 8.8, POL_C[1] - 10.15, POL_C[1] + 10.15)
    p["pololu_wires"] = box(POL_C[0] - 10.0, POL_C[0] + 10.0, Y_PL1 + 2.0, Y_PL1 + 16.0, POL_C[1] + 10.15, POL_C[1] + 26.0)
    return p

def to_print(shape, y_bed): return shape.rotate((0, 0, 0), (1, 0, 0), 90).translate((0, 0, -y_bed))

CABLES = {
    "lipo_xt60_lead":  dict(d=4.0, r=14.0, pts=[(PACK_X[1], 52.0, 272.0), (31.0, 60.0, 269.0), (31.0, 84.0, 264.0), (20.0, 94.0, 265.0)]),
    "lipo_balancer":   dict(d=2.5, r=5.0,  pts=[(PACK_X[1], 62.0, 270.0), (28.0, 78.0, 272.0), (28.0, 94.0, 277.0)]),
    "fuse_leg_1":      dict(d=4.0, r=14.0, pts=[(FUSE_HOLDER["x"][1], 94.0, 266.5), (XT_LIPO["x"][0] + 6.0, 94.0, 266.5)]),
    "fuse_leg_2":      dict(d=4.0, r=14.0, pts=[(-61.0, 94.0, XT_SW["z"][0] + 6.0), (-61.0, 94.0, 266.5), (FUSE_HOLDER["x"][0], 94.0, 266.5)]),
    "switch_in_lead":  dict(d=3.5, r=10.0, pts=[(-61.0, 94.0, XT_SW["z"][1] - 6.0), (-64.0, 96.0, SW_BODY["z"][0])]),
    "switch_out_pigtail": dict(d=4.0, r=12.0, pts=[(-64.0, 96.0, SW_BODY["z"][1]), (-64.0, 96.0, 410.0), (-26.0, 88.0, 410.0), (-26.0, 88.0, CUT_TERM_Z)]),   # VIN jetzt bei -X; v4.5: y 96 (Pads jetzt 6 mm hoch)
    "out_to_pololu":   dict(d=2.5, r=6.0,  pts=[(22.0, 86.0, CUT_TERM_Z), (22.0, 86.0, 405.0), (10.0, 66.0, 405.0), (-68.0, 66.0, 405.0), (-74.0, 58.0, 396.0), (-74.0, 50.0, 340.0), (POL_C[0], 50.0, POL_C[1] + 14.0)]),   # v4.4: an der Decke nach -X, an der -X-Wand hinunter zum Pololu (neben der 50-mm-Steckerzone)
    "out_to_waveshare": dict(d=3.0, r=8.0, pts=[(12.0, 84.0, CUT_TERM_Z), (12.0, 84.0, 404.0), (16.0, 66.0, 402.0), (16.0, 66.0, 338.0), (28.0, 90.0, 322.0)]),   # vor dem Cutoff abwaerts
    "servo_bus_a":     dict(d=3.0, r=8.0,  pts=[(42.0, 93.0, 335.0), (42.0, 93.0, 352.0), (42.0, 76.0, 352.0), (21.0, 52.0, 328.0), (14.5, 45.0, 318.0), (14.5, 36.0, 314.0)]),   # Deckel -> Durchfuehrung
    "servo_bus_b":     dict(d=3.0, r=8.0,  pts=[(52.0, 93.0, 335.0), (52.0, 93.0, 360.0), (50.0, 72.0, 360.0), (27.0, 57.0, 322.0), (19.5, 46.0, 310.0), (19.5, 36.0, 306.0)]),
    "pi_usb_to_waveshare": dict(d=3.0, r=8.0, pts=[(-62.0, 52.0, 360.0), (-64.0, 62.0, 342.0), (-30.0, 70.0, 320.0), (10.0, 80.0, 312.0), (28.0, 90.0, 312.0)]),   # v4.4: Stecker bei -X (50 mm), vor dem Cutoff hinunter zum Waveshare
    "pololu_5v_usbc":  dict(d=3.5, r=8.0,  pts=[(POL_C[0], 50.0, POL_C[1] + 14.0), (-58.0, 54.0, 313.0), (48.0, 54.0, 313.0), (59.8, 50.0, 320.0), (59.8, 47.0, 330.0)]),   # v4.4: unten quer ueber die Domen zum USB-C-Stecker
    "test_leads_5v":   dict(d=2.0, r=6.0,  pts=[(POL_C[0], 50.0, POL_C[1] + 14.0), (-57.0, 70.0, TEST_PINS[0][1]), (-57.0, 100.0, TEST_PINS[0][1])]),
}

def main():
    os.makedirs(OUT, exist_ok=True); meta = {}
    for name, fn, ybed in (("base", build_base, Y0), ("lid", build_lid, Y_RIM)):
        print(f"building {name} ..."); s = fn(); v = s.val(); bb = v.BoundingBox(); c = v.Center()
        print(f"  volume {v.Volume()/1000:.1f} cm3, bbox X[{bb.xmin:.1f},{bb.xmax:.1f}] Y[{bb.ymin:.1f},{bb.ymax:.1f}] Z[{bb.zmin:.1f},{bb.zmax:.1f}], centroid ({c.x:.1f},{c.y:.1f},{c.z:.1f})")
        cq.exporters.export(s, os.path.join(OUT, f"backpack_v3_{name}_robotframe.stl"), tolerance=0.02, angularTolerance=0.1)
        ps = s.rotate((0, 0, 0), (1, 0, 0), -90).translate((0, 0, Y_LID)) if name == "lid" else to_print(s, ybed)
        cq.exporters.export(ps, os.path.join(OUT, f"backpack_v3_{name}.stl"), tolerance=0.02, angularTolerance=0.1)
        meta[name] = dict(volume_cm3=round(v.Volume() / 1000, 2), centroid_robot_mm=[round(c.x, 2), round(c.y, 2), round(c.z, 2)])
    for k, v in build_placeholders().items():
        cq.exporters.export(v, os.path.join(OUT, f"placeholder_{k}.stl"), tolerance=0.05)
    meta["depth_mm"] = dict(plate=[Y0, Y_PL1], pi_layer=[Y_PL1, Y_DECK], deck=[Y_DECK, Y_RIM], lid=[Y_RIM, Y_LID], total=Y_LID - Y0)
    meta["envelope_mm"] = dict(x=[-XW, XW], y=[Y0, Y_LID], z=[Z_BOT, Z_TOP])
    json.dump(CABLES, open(os.path.join(OUT, "cables.json"), "w"), indent=1)
    json.dump(meta, open(os.path.join(OUT, "parts.json"), "w"), indent=2)
    print("done ->", OUT)

if __name__ == "__main__":
    main()
