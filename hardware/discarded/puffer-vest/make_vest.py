#!/usr/bin/env python3
"""Z-Bot "Pixel" - Puffer-Weste (TPU 95A): zwei Wabenpuffer auf Brust/Schulter + Netzgurt um Torso UND Rucksack.

Alles ist Parameter (unten). Maße = Roboter-Frame des gepinnten Assemblys (mm, +X links, +Y hinten, +Z oben,
Torso-Vorderflaeche y = -25,4, Rucksack y 38,1 .. 107,1). Aufbau:

  1. front   - Brustteil, flach gedruckt: 2 Puffer (Wabe + Haut), Netzgurt (Vorderseite + Ecken), 2 Haltelaschen
               ueber die Torso-Oberkante (Wulst haengt hinter der Vorderwand)
  2. rear_A  - Rueckgurt (Netz) von der -X-Seite ueber den Deckel, endet in der Spannschnalle (Rahmen, 3 Stege)
  3. rear_B  - Rueckgurt von der +X-Seite, loses Ende wird durch die Schnalle gefaedelt
Gurt: 20 mm hoch auf z 300..320 -> unter den Schulter-Gelenken (>= 327) und ueber der LiPo-Schublade (<= 294).

Ausgabe: stl/ (Druckdaten, flach) und stl/robotframe/ (getragener Zustand, fuer WebUI + check_vest.py).
Usage: .cad/bin/python hardware/vest/make_vest.py
"""
from __future__ import annotations
import json, math, os, sys
import numpy as np
import cadquery as cq
import trimesh

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "stl"); OUT_W = os.path.join(OUT, "robotframe")

# ------------------------------------------------------------------ Roboter (gemessen am gepinnten GLB + backpack_v4.py)
Y_FRONT = -25.4                          # Torso-Vorderflaeche (flach fuer |x| < 70, z 322..382)
WALL_TOP = 386.6                         # Oberkante der Torso-Vorderwand, flach fuer |x| <= 62
WALL_Y = (-20.4, -10.4)                  # flache Oberseite der Vorderwand; davor 5 x 5 mm Fase, dahinter die offene Schulterwanne
WALL_CH = 5.0
POCKET_FREE_Z = 372.0                    # Schulter-Pitch-Motor endet bei z 371
TORSO_HW = {300: 53.9, 310: 60.1, 320: 66.4}   # Torso-Halbbreite (Schnitte) im Gurtband
BP_X, BP_Y, BP_Z = 80.0, (38.1, 107.1), (254.0, 416.0)   # Rucksack v4.6 (Deckelflaeche y = 107,1)
ARM_Z_MIN = 327.0                        # Unterkante der Schulter-Yaw-Buegel (x >= 75)

# ------------------------------------------------------------------ Parameter
GAP = 0.4                                # Luft zwischen Weste und Roboter
T_PLATE = 2.4                            # Rueckplatte der Puffer = Gurtstaerke
BELT_Z = (300.0, 320.0); BELT_W = BELT_Z[1] - BELT_Z[0]; BELT_MID = sum(BELT_Z) / 2
PAD_Z = (323.0, 381.6)                   # Puffer: 3 mm ueber dem Gurt bis zur Fase der Vorderwand
PAD_X = (2.0, 71.0)                      # 4 mm Spalt in der Mitte; Buegel beginnen bei x 75
PAD_T = 22.0                             # Gesamttiefe Platte + Wabe + Haut (Vorderkante bei y = -25,8 - 22)
SKIN, WALL, CELL, R_V, R_TOP = 1.2, 1.4, 15.0, 5.0, 3.0   # Haut, Wabenwand, Zellkante (Raute), Ecken, Randrundung
RIM = WALL + 0.2 - SKIN                  # Aussenwand = Wabenwand (+0,2): der Rand ist keine massive Schiene
HOLE_D = 4.5                             # Entlueftung in der Rueckplatte je Zelle
FLAP_X = (54.5, 65.5)                    # Haltelasche (Wandoberkante ist hier flach, Halsmotor-Buegel ab x 75, Hals bis x 50)
FLAP_BEAD = (14.0, 5.0, 6.0)             # Wulst (Breite ignoriert -> FLAP_X), Laenge, Hoehe ueber der Lasche
OV = 26.0                                # Ueberlappung Vorderteil <-> Rueckgurt
LAP_HOLE = 3.4                           # M3 durch beide Lagen, 2 Schrauben je Seite
LOCK_X = 30.0                            # Schnalle auf dem Deckel (frei: Deckel hat bei x 8..80, z 296..324 keine Oeffnung)
FR_L, FR_W, FR_T = 26.0, BELT_W + 8.0, 3.2   # Schnallenrahmen
TAIL = 60.0                              # loses Ende von rear_B hinter der Schnalle
NET_PITCH, NET_H, NET_ROWS, RAIL = 14.0, 5.2, 4.0, 2.5   # Netzgurt: Rauten
BED = 250.0                              # P2S: 256 x 256
RHO_TPU = 1.22e-3                        # g/mm3

# ------------------------------------------------------------------ Gurtpfad (Hülle Torso + Rucksack, Innenflaeche des Gurts)
def round_polygon(verts, radii, n_arc=20):
    V = [np.asarray(v, float) for v in verts]; N = len(V); pts, apex = [], []
    for i in range(N):
        p0, p1, p2 = V[i - 1], V[i], V[(i + 1) % N]; r = radii[i]
        if r == 0: pts.append(p1); apex.append(len(pts) - 1); continue
        d1 = (p1 - p0) / np.linalg.norm(p1 - p0); d2 = (p2 - p1) / np.linalg.norm(p2 - p1)
        cr = d1[0] * d2[1] - d1[1] * d2[0]; th = math.atan2(abs(cr), float(d1 @ d2)); t = r * math.tan(th / 2)
        a, b = p1 - d1 * t, p1 + d2 * t; sg = 1 if cr > 0 else -1
        c = a + np.array([-d1[1], d1[0]]) * sg * r
        a0, a1 = math.atan2(*(a - c)[::-1]), math.atan2(*(b - c)[::-1])
        da = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
        arc = [c + r * np.array([math.cos(a0 + da * k / n_arc), math.sin(a0 + da * k / n_arc)]) for k in range(n_arc + 1)]
        apex.append(len(pts) + n_arc // 2); pts.extend(arc)
    return np.array(pts), apex

class BeltPath:
    """Geschlossener Pfad (x, y); s = 0 in der Mitte der Vorderseite, +s Richtung +X (Roboter links)."""
    def __init__(self):
        xc = TORSO_HW[320] + GAP; yf = Y_FRONT - GAP; xb = BP_X + GAP; yb0 = BP_Y[0]; yb1 = BP_Y[1] + GAP
        verts = [(0, yf), (xc, yf), (xb, yb0), (xb, yb1), (-xb, yb1), (-xb, yb0), (-xc, yf)]
        radii = [0, 8.5, 12.0, 2.5, 2.5, 12.0, 8.5]
        pts, apex = round_polygon(verts, radii); pts = np.vstack([pts, pts[:1]])
        seg = np.linalg.norm(np.diff(pts, axis=0), axis=1); self.s = np.concatenate([[0], np.cumsum(seg)]); self.pts = pts
        self.L = float(self.s[-1]); self.s_apex = [float(self.s[i]) for i in apex]
        self.yf, self.xc, self.xb, self.yb1 = yf, xc, xb, yb1
    def at(self, s):
        s = np.mod(np.asarray(s, float), self.L)
        x = np.interp(s, self.s, self.pts[:, 0]); y = np.interp(s, self.s, self.pts[:, 1])
        e = 0.05; xa = np.interp(np.mod(s + e, self.L), self.s, self.pts[:, 0]); ya = np.interp(np.mod(s + e, self.L), self.s, self.pts[:, 1])
        xb_ = np.interp(np.mod(s - e, self.L), self.s, self.pts[:, 0]); yb_ = np.interp(np.mod(s - e, self.L), self.s, self.pts[:, 1])
        t = np.stack([xa - xb_, ya - yb_], -1); t /= np.linalg.norm(t, axis=-1, keepdims=True)
        return np.stack([x, y], -1), np.stack([t[..., 1], -t[..., 0]], -1)   # Punkt, Aussennormale (rechts der Fahrtrichtung)
    def s_lid(self, x):                      # s eines Deckelpunkts (gerade Strecke y = yb1, x von +xb nach -xb)
        m = np.isclose(self.pts[:, 1], self.yb1) & (np.abs(self.pts[:, 0]) <= self.xb - 2.4)
        return float(np.interp(-x, -self.pts[m, 0], self.s[m]))
PATH = BeltPath()
S_APEX_V2 = PATH.s_apex[2]                  # Backpack-Vorderkante (+X)
S_F = round(S_APEX_V2 - 14.0, 1)            # Vorderteil reicht bis +-S_F, Lap-Verbindung auf der geraden Flanke
S_LID_B0 = PATH.s_lid(PATH.xb - 2.5)         # Deckelanfang (+X-Ecke endet hier)

# ------------------------------------------------------------------ 2D/CadQuery-Helfer (flaches Koordinatensystem: u = Gurtlaenge/x, v = z, w = Dicke)
def prism(pts, w0, w1):
    return cq.Workplane("XY").workplane(offset=w0).polyline([tuple(p) for p in pts]).close().extrude(w1 - w0)
def box(u0, u1, v0, v1, w0, w1):
    return cq.Workplane("XY").box(u1 - u0, v1 - v0, w1 - w0, centered=False).translate((u0, v0, w0))
def cyl(u, v, d, w0, w1):
    return cq.Workplane("XY").workplane(offset=w0).center(u, v).circle(d / 2).extrude(w1 - w0)
def union_all(parts):
    r = parts[0]
    for p in parts[1:]: r = r.union(p)
    return r
def cut_all(solid, cutters):
    if not cutters: return solid
    return solid.cut(cq.Workplane("XY").add(cq.Compound.makeCompound([c.val() for c in cutters])))
def clip_poly(poly, vmin, vmax):
    out = list(poly)
    for axis, lim, keep_ge in ((1, vmin, True), (1, vmax, False)):
        pts, res = out, []
        for i in range(len(pts)):
            a, b = pts[i], pts[(i + 1) % len(pts)]
            ina = (a[axis] >= lim) if keep_ge else (a[axis] <= lim); inb = (b[axis] >= lim) if keep_ge else (b[axis] <= lim)
            if ina: res.append(a)
            if ina != inb:
                t = (lim - a[axis]) / (b[axis] - a[axis]); res.append((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])))
        out = res
    return out

def net_strip(u0, u1, v0, v1, t, solid0=0.0, solid1=0.0, holes=()):
    """Flachband mit Rautennetz (zwei versetzte Reihen), Enden solid_ massiv; holes = [(u, v, d)] durch alles."""
    s = box(u0, u1, v0, v1, 0, t); vm = (v0 + v1) / 2; cut = []
    k0 = math.floor((u0 + solid0) / NET_PITCH) - 1
    for row, dv in enumerate((-NET_ROWS, NET_ROWS)):
        for k in range(k0, int((u1 - solid1) / NET_PITCH) + 2):
            uc = k * NET_PITCH + (NET_PITCH / 2 if row else 0.0)
            if uc - NET_H < u0 + solid0 or uc + NET_H > u1 - solid1: continue
            poly = clip_poly([(uc + NET_H, vm + dv), (uc, vm + dv + NET_H), (uc - NET_H, vm + dv), (uc, vm + dv - NET_H)], v0 + RAIL, v1 - RAIL)
            cut.append(prism(poly, -0.1, t + 0.1))
    cut += [cyl(u, v, d, -0.1, t + 0.1) for (u, v, d) in holes]
    return cut_all(s, cut)

# ------------------------------------------------------------------ Puffer (flach: Rueckplatte w = 0 auf dem Bett, Wabe nach oben)
def pad(mirror=False):
    x0, x1 = PAD_X; z0, z1 = PAD_Z
    pts = [(x0, z0), (x1 - 9, z0), (x1, z0 + 9), (x1, z1 - 5.6), (x1 - 4.5, z1), (x0, z1)]
    d_in = SKIN + RIM
    base = prism(pts, 0, PAD_T).edges("|Z").fillet(R_V).faces(">Z").edges().fillet(R_TOP)
    region = cq.Workplane("XY").polyline(pts).close().offset2D(-d_in).extrude(PAD_T - SKIN - T_PLATE).translate((0, 0, T_PLATE))
    cx, cz = (x0 + x1) / 2, (z0 + z1) / 2; sc = CELL / math.sqrt(2); h = (CELL - WALL) / math.sqrt(2)
    cut, holes, n_full = [], [], 0
    for m in range(-12, 13):
        for n in range(-12, 13):
            u, v = cx + (m + n) * sc, cz + (m - n) * sc
            if not (x0 - 2 < u < x1 + 2 and z0 - 2 < v < z1 + 2): continue
            dia = prism([(u + h, v), (u, v + h), (u - h, v), (u, v - h)], T_PLATE, PAD_T - SKIN)
            c = region.intersect(dia); vol = c.val().Volume() if c.vals() else 0.0
            full = 2 * h * h * (PAD_T - SKIN - T_PLATE)
            if vol < 0.45 * full: continue
            cut.append(c)
            if vol > 0.97 * full: holes.append(cyl(u, v, HOLE_D, -0.1, T_PLATE + 0.1)); n_full += 1
    p = cut_all(base, cut + holes)
    return p.mirror("YZ") if mirror else p, n_full, len(cut)

# ------------------------------------------------------------------ Haltelasche ueber die Torso-Oberkante
def flap_path():
    """Innenflaeche der Lasche (y, z): Platte -> Fase -> Oberseite -> hinter die Vorderwand; q = Bogenlaenge ab Plattenoberkante."""
    wall = np.array([(Y_FRONT, PAD_Z[1]), (WALL_Y[0], WALL_TOP), (WALL_Y[1], WALL_TOP), (WALL_Y[1], POCKET_FREE_Z + 6.0)], float)   # Wandkontur (rechts der Fahrtrichtung = Wand)
    d = np.diff(wall, axis=0); d /= np.linalg.norm(d, axis=1, keepdims=True); left = np.stack([-d[:, 1], d[:, 0]], -1)
    pts = [wall[0] + left[0] * GAP]
    for i in range(1, len(wall) - 1):                      # Gehrung an den Ecken
        a, b = wall[i] + left[i - 1] * GAP, wall[i] + left[i] * GAP
        n = left[i - 1] + left[i]; n /= np.linalg.norm(n); k = GAP / (n @ left[i]); pts.append(wall[i] + n * k)
    pts.append(wall[-1] + left[-1] * GAP)
    pts = np.array([(Y_FRONT - GAP, PAD_Z[1] - 0.5)] + [tuple(p) for p in pts])
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1); return pts, np.concatenate([[0], np.cumsum(seg)])
FLAP_PTS, FLAP_Q = flap_path(); FLAP_LEN = float(FLAP_Q[-1]) - 0.5
def flap(mirror=False):
    u0, u1 = FLAP_X; v0, v1 = PAD_Z[1] - 1.0, PAD_Z[1] + FLAP_LEN
    f = box(u0, u1, v0, v1, 0, T_PLATE)
    f = f.union(box(u0, u1, v1 - FLAP_BEAD[1], v1, 0, T_PLATE + FLAP_BEAD[2]).edges("|Z").fillet(1.0))
    return f.mirror("YZ") if mirror else f

# ------------------------------------------------------------------ Teile
def front_piece():
    pl, n_full, n_cells = pad(False); pr, _, _ = pad(True)
    holes = [(sg * (S_F - OV / 2 + d), BELT_MID, LAP_HOLE) for sg in (1, -1) for d in (-5.0, 5.0)]
    belt = net_strip(-S_F, S_F, BELT_Z[0], BELT_Z[1], T_PLATE, solid0=OV + 2, solid1=OV + 2, holes=holes)
    ties = [box(sg * u - 4.0, sg * u + 4.0, BELT_Z[1] - 2.0, PAD_Z[0] + 2.0, 0, T_PLATE) for u in (12.0, 40.0) for sg in (1, -1)]   # Pufferplatte haengt am Gurt
    ties = [t for t in ties]
    parts = {"pads": union_all([pl, pr]), "flaps": union_all([flap(False), flap(True)]), "belt": union_all([belt] + ties)}
    return parts, n_full, n_cells

def rear_parts(P=PATH):
    s_b0 = S_F - OV                               # Rueckgurt beginnt im Lap
    s_f0 = P.s_lid(LOCK_X + FR_L / 2)             # Rahmen: niedrige s (+X) = Steg A1 ... hohe s = Steg A0 (Gurt A)
    s_a1 = P.L - (S_F - OV)                       # Gurt A endet im -X-Lap
    # --- rear_B: Lap (massiv, 2 Loecher) + Netz + loses Ende
    len_b = (s_f0 - s_b0) + FR_L + TAIL
    holes_b = [(OV / 2 + d, BELT_MID, LAP_HOLE) for d in (-5.0, 5.0)]
    B = net_strip(0, len_b, BELT_Z[0], BELT_Z[1], T_PLATE, solid0=OV + 2, solid1=10.0, holes=holes_b)
    for sv in (1, -1):                            # Spitze: 45-Grad-Ecken zum Einfaedeln
        tri = prism([(len_b + 0.1, BELT_Z[0] + (0 if sv < 0 else BELT_W)), (len_b - 3.5, BELT_Z[0] + (0 if sv < 0 else BELT_W)),
                     (len_b + 0.1, BELT_Z[0] + (3.5 if sv < 0 else BELT_W - 3.5))], -0.1, T_PLATE + 0.1); B = B.cut(tri)
    # --- rear_A: Rahmen + Netz bis zum -X-Lap (u = 0 am Rahmenanfang)
    len_a = s_a1 - s_f0
    frame = box(0, FR_L, BELT_MID - FR_W / 2, BELT_MID + FR_W / 2, 0, FR_T).edges("|Z").fillet(2.5)
    slots = [box(a, b, BELT_MID - (BELT_W + 2.0) / 2, BELT_MID + (BELT_W + 2.0) / 2, -0.1, FR_T + 0.1).edges("|Z").fillet(1.0) for a, b in ((5.0, 10.5), (15.5, 21.0))]
    frame = cut_all(frame, slots)
    holes_a = [(len_a - OV / 2 + d, BELT_MID, LAP_HOLE) for d in (-5.0, 5.0)]
    strap = net_strip(FR_L - 2.0, len_a, BELT_Z[0], BELT_Z[1], T_PLATE, solid0=4.0, solid1=OV + 2, holes=holes_a)
    A = frame.union(strap)
    return {"A": A, "B": B}, dict(s_b0=s_b0, s_f0=s_f0, s_a1=s_a1, len_a=len_a, len_b=len_b)

# ------------------------------------------------------------------ Export
def to_mesh(shape, tol=0.04):  # Druckdaten fein; getragener Zustand (Viewer/Check) mit tol=0.1
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as f: tmp = f.name
    cq.exporters.export(shape, tmp, tolerance=tol, angularTolerance=0.15)
    m = trimesh.load(tmp); os.unlink(tmp); m.merge_vertices(); return m
def dense(m, edge=3.0):
    v, f = trimesh.remesh.subdivide_to_size(m.vertices, m.faces, max_edge=edge); return trimesh.Trimesh(v, f, process=False)

def worn_belt(m, s0, off=lambda s: 0.0):
    """Flachband (u, v, w) -> auf den Gurtpfad gelegt: s = s0 + u, z = v, Dicke nach aussen."""
    m = dense(m); u, v, w = m.vertices.T; s = s0 + u
    P, N = PATH.at(s); o = w + np.vectorize(off)(s)
    X = np.stack([P[:, 0] + N[:, 0] * o, P[:, 1] + N[:, 1] * o, v], -1); return trimesh.Trimesh(X, m.faces, process=False)
def worn_pads(m):
    u, v, w = m.vertices.T
    return trimesh.Trimesh(np.stack([u, Y_FRONT - GAP - w, v], -1), m.faces, process=False)
def worn_flaps(m):
    m = dense(m); u, v, w = m.vertices.T; q = v - PAD_Z[1] + 0.5      # q = 0 ab FLAP_PTS[0]
    pts, Q = FLAP_PTS, FLAP_Q; qc = np.clip(q, 0, Q[-1])
    y = np.interp(qc, Q, pts[:, 0]); z = np.interp(qc, Q, pts[:, 1])
    e = 0.05; ya = np.interp(np.clip(qc + e, 0, Q[-1]), Q, pts[:, 0]); za = np.interp(np.clip(qc + e, 0, Q[-1]), Q, pts[:, 1])
    yb = np.interp(np.clip(qc - e, 0, Q[-1]), Q, pts[:, 0]); zb = np.interp(np.clip(qc - e, 0, Q[-1]), Q, pts[:, 1])
    t = np.stack([ya - yb, za - zb], -1); t /= np.linalg.norm(t, axis=-1, keepdims=True); nl = np.stack([-t[:, 1], t[:, 0]], -1)
    y = y + nl[:, 0] * w + t[:, 0] * (q - qc); z = z + nl[:, 1] * w + t[:, 1] * (q - qc)
    return trimesh.Trimesh(np.stack([u, y, z], -1), m.faces, process=False)

def ramp(s_a, s_b, h0, h1):
    return lambda s: float(np.interp(s, [s_a, s_b], [h0, h1]))

def main():
    os.makedirs(OUT_W, exist_ok=True)
    print(f"Gurtpfad: Umfang {PATH.L:.1f} mm, Vorderteil +-{S_F} mm, Deckel s {S_LID_B0:.1f}..{PATH.s_lid(-(PATH.xb - 2.5)):.1f}")
    fr, n_full, n_cells = front_piece(); rr, info = rear_parts()
    print(f"Puffer: {n_cells} Zellen ({n_full} voll), Lasche {FLAP_LEN:.1f} mm; rear: {info}")
    flat = {}
    front_all = union_all([fr["pads"], fr["flaps"], fr["belt"]])
    flat["front"] = front_all; flat["rear_A"] = rr["A"]; flat["rear_B"] = rr["B"]
    names = {"front": "puffervest_1-front_tpu", "rear_A": "puffervest_2-rear-A_tpu", "rear_B": "puffervest_3-rear-B_tpu"}
    stats = {}
    for k, shp in flat.items():
        m = to_mesh(shp); b = m.bounds; size = (b[1] - b[0]).round(1)
        m.apply_translation(-np.array([b[0][0], b[0][1], b[0][2]]))
        m.export(os.path.join(OUT, names[k] + ".stl"))
        stats[k] = dict(size=size.tolist(), volume_cm3=round(m.volume / 1000, 1), mass_g=round(m.volume * RHO_TPU, 0), watertight=bool(m.is_watertight))
        assert max(size[0], size[1]) <= BED, f"{k} passt nicht aufs Bett: {size}"
        print(f"  {names[k]}.stl  {size} mm  {stats[k]['volume_cm3']} cm3  {stats[k]['mass_g']:.0f} g  watertight={m.is_watertight}")
    # ---- getragener Zustand (Roboter-Frame)
    w = {}
    w["pads"] = worn_pads(to_mesh(fr["pads"], 0.1))
    w["flaps"] = worn_flaps(to_mesh(fr["flaps"], 0.1))
    w["belt"] = worn_belt(to_mesh(fr["belt"], 0.1), 0.0)
    L = PATH.L
    offB = lambda s: float(np.interp(s, [info["s_b0"], info["s_b0"] + 2, S_F, S_F + 4, info["s_f0"] - 4, info["s_f0"]], [T_PLATE, T_PLATE, T_PLATE, 0, 0, FR_T + T_PLATE * 0]))
    w["rear_B"] = worn_belt(to_mesh(rr["B"], 0.1), info["s_b0"], lambda s: offB(s) if s < info["s_f0"] else FR_T)
    offA = lambda s: float(np.interp(s, [L - S_F - 4, L - S_F], [0, T_PLATE]))
    w["rear_A"] = worn_belt(to_mesh(rr["A"], 0.1), info["s_f0"], offA)
    for k, m in w.items(): m.export(os.path.join(OUT_W, f"vest_{k}.stl"))
    json.dump(dict(path_length=PATH.L, S_F=S_F, info=info, flap_len=FLAP_LEN, stats=stats, params=dict(PAD_T=PAD_T, BELT_Z=BELT_Z, PAD_Z=PAD_Z)), open(os.path.join(HERE, "vest.json"), "w"), indent=1)
    print("total:", sum(s["mass_g"] for s in stats.values()), "g TPU")

if __name__ == "__main__":
    main()
