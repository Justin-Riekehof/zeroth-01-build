#!/usr/bin/env python3
"""Interactive 3D assembly viewer for the gripper + wrist: collects every part in hub coordinates,
groups them into an assembly tree with joints, and writes viewer/gripper_assembly.html (single file).

Hub frame H (see make_wrist.py): a = along the forearm, b = sideways, c = elbow horn axis.
Joints: roll (about the a-axis through the S1 shaft), phi (G1/G2/links rotate about z_g=c), fingers translate.

Usage: .cad/bin/python hardware/gripper/export_viewer.py
"""
import base64
import json
import math
import os
import re
import sys

import numpy as np
import trimesh

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_gripper as G  # noqa: E402
import make_wrist as W  # noqa: E402

STL = os.path.join(HERE, "stl")
OFF = np.array(W.to_h())          # gripper frame -> hub frame (pure translation)
PHI_MIN, PHI_MAX = G.PHI_MIN, G.PHI_MAX


def stl(n):
    return trimesh.load(os.path.join(STL, n + ".stl"))


def to_hub(m):
    m = m.copy()
    m.apply_translation(OFF)
    return m


def elbow_servo():
    """The existing elbow-yaw STS3215 in hub coordinates (reference part, from the robot CAD)."""
    sc = trimesh.load(os.path.join(HERE, "..", "..", "resources", "cad", "z001-opus-m-93de7567.glb"))
    best = None
    for n in sc.graph.nodes_geometry:
        if n.startswith("left_elbow_yaw_motor"):
            T, g = sc.graph[n]
            m = sc.geometry[g].copy()
            m.apply_transform(T)
            m.apply_scale(1000)
            if len(m.faces) > 5000:
                best = m
    T = best.bounding_box_oriented.primitive.transform
    best.apply_transform(np.linalg.inv(T))
    v = best.vertices.copy()
    best.vertices = np.c_[v[:, 2] - 12.52, v[:, 0] - 0.13, v[:, 1]]
    return best


def roll_servo():
    sv = G.load_servo(transverse=False)
    sv.apply_translation([0, -G.A, 0])
    v = sv.vertices.copy()
    sv.vertices = np.c_[v[:, 2] + W.A_TOP, W.B_R + v[:, 0], v[:, 1]]
    return sv


def cap_mesh(d, x, y, z0, flip=False):
    c = trimesh.load(os.path.join(STL, {10: "cap_d10_x4.stl", 12: "cap_d12_x8.stl", 14: "cap_d14_x2.stl"}[d]))
    if flip:
        c.apply_transform(trimesh.transformations.rotation_matrix(math.pi, [1, 0, 0]))
        c.apply_translation([x, y, z0 + G.CAP_T])
    else:
        c.apply_translation([x, y, z0])
    return c


def pad_mesh(side):
    """TPU pad placed on finger A (side +1) or mirrored for B, gripper frame, phi = 0 pose."""
    p = stl("pad_tpu_x4")
    col_x0 = G.C + G.S + G.COL_GAP
    fy = G.A
    p.apply_translation([col_x0 + 1.0, fy - G.T / 2 - G.PAD, sum(G.TIP_Z) / 2])
    if side < 0:
        p.vertices = p.vertices * np.array([1, -1, 1])
        p.invert()
    return p


def enc(m, pivot):
    """Indexed geometry relative to the pivot, little base64 blobs."""
    v = (np.asarray(m.vertices) - np.asarray(pivot)).astype(np.float32)
    f = np.asarray(m.faces).astype(np.uint32)
    return {"v": base64.b64encode(v.tobytes()).decode(), "f": base64.b64encode(f.tobytes()).decode(), "nv": len(v), "nf": len(f)}


def bbox(m):
    e = m.extents
    return [round(float(x), 1) for x in e]


def vol(m):
    try:
        return round(float(m.volume) / 1000, 1) if m.is_watertight else None
    except Exception:
        return None


def part(pid, name, mesh, pivot, mat, qty, fname, cat, note=""):
    return {"id": pid, "name": name, "type": "part", "cat": cat, "material": mat, "qty": qty, "file": fname,
            "volume_cm3": vol(mesh), "size_mm": bbox(mesh), "note": note, "geom": enc(mesh, pivot)}


def group(gid, name, children, pivot=(0, 0, 0), motion=None, note=""):
    return {"id": gid, "name": name, "type": "group", "pivot": [float(x) for x in pivot], "motion": motion or "none",
            "note": note, "children": children}


def build():
    C, A, S = G.C, G.A, G.S
    p1 = OFF + np.array([*G.P1, 0])
    p1b = OFF + np.array([*G.P1B, 0])
    p2a = OFF + np.array([*G.P2A, 0])
    p2b = OFF + np.array([*G.P2B, 0])
    z0 = np.array([0, 0, 0.0])
    roll_pivot = np.array([0.0, W.B_R, 0.0])
    cap_top = G.CPL_Z[1] + 0.2

    # ---- finger groups (translate with phi) ----
    def finger(side, name, fid):
        s = "A" if side > 0 else "B"
        fy = side * A
        tip = to_hub(stl(f"finger_tip_{s}_x2"))
        cp = stl("finger_coupler_x4")
        if side < 0:
            cp.apply_translation([0, -2 * A, 0])          # same part as for finger A, mirrored position
        cp = to_hub(cp)
        pad = to_hub(pad_mesh(side))
        cap10 = to_hub(cap_mesh(10, C, fy, cap_top))
        cap12 = to_hub(cap_mesh(12, C + S, fy, cap_top))
        pv = OFF + np.array([C, fy, 0])
        kids = [
            part(fid + "_tip", f"Fingerstück {s} (L-Winkel mit Spitze)", tip, pv, "PETG (oder PLA)", 1, f"finger_tip_{s}_x2.stl", "finger", "Absatz trägt die Koppelstange"),
            part(fid + "_cpl", f"Koppelstange {s}", cp, pv, "PETG (oder PLA)", 1, "finger_coupler_x4.stl", "finger", "auf das Fingerstück: 2× M3×12 + 2 Passzapfen"),
            part(fid + "_pad", f"Greifpad {s}", pad, pv, "TPU 95A", 1, "pad_tpu_x4.stl", "pad", "aufgesteckt, 2 Zapfen"),
            part(fid + "_cap1", f"Kappe Ø10 (Kurbelzapfen {s})", cap10, pv, "PLA", 1, "cap_d10_x4.stl", "cap", "M3×8"),
            part(fid + "_cap2", f"Kappe Ø12 (Lenkerzapfen {s})", cap12, pv, "PLA", 1, "cap_d12_x8.stl", "cap", "M3×8"),
        ]
        return group(fid, name, kids, pv, "finger_pos" if side > 0 else "finger_neg",
                     "Koppel des Parallelogramms, bleibt parallel zur Rollachse")

    # ---- housing ----
    posts = []
    for i, (pp, nm) in enumerate(((G.P2A, "A"), (G.P2B, "B"))):
        pm = stl("link_post_x4")
        pm.apply_translation([*pp, 0])
        cap = cap_mesh(12, pp[0], pp[1], G.LINK_Z[0] - 0.3 - G.CAP_T, flip=False)
        posts.append(part(f"post{nm}", f"Lenkerzapfen {nm}", to_hub(pm), z0, "PLA", 1, "link_post_x4.stl", "housing", "2 Stück je Arm, von unten an die Platte geschraubt"))
        posts.append(part(f"post{nm}_cap", f"Kappe Ø12 (Lenkerzapfen {nm})", to_hub(cap), z0, "PLA", 1, "cap_d12_x8.stl", "cap", "M3×8"))
    g2cap = cap_mesh(14, 0, -A, G.GEAR_Z[1] + 0.3)

    housing = group("housing", "Gehäuse", [
        part("tray", "Fach (Rückwand = Roll-Interface)", to_hub(stl("housing_tray_x2")), z0, "PLA", 1, "housing_tray_x2.stl", "housing", "Roll-Horn: 4× M3×6 von innen, dann Servo von oben einsetzen"),
        part("plate", "Deckplatte (mit angedruckter G2-Achse Ø10)", to_hub(stl("housing_top_plate_x2")), z0, "PETG", 1, "housing_top_plate_x2.stl", "housing", "verdickter Sockel unter G2, 4× M3 Zylinderkopf"),
        part("sv2", "Greifer-Servo STS3215 (ID 15/25)", to_hub(G.load_servo()), z0, "Feetech STS3215 12 V", 1, "(Zukaufteil)", "servo", "liegt quer im Fach"),
        *posts,
        part("g2cap", "Kappe Ø14 (G2-Achse)", to_hub(g2cap), z0, "PLA", 1, "cap_d14_x2.stl", "cap", "M3×8"),
    ])

    drive = group("drive", "Antrieb (Zahnräder + Kurbeln)", [
        group("g1", "Zahnrad G1 + Kurbel A", [part("g1p", "G1 (auf dem Servo-Horn)", to_hub(stl("drive_G1_x2")), p1, "PLA", 1, "drive_G1_x2.stl", "drive", "4× M2,5 ins Horn")], p1, "phi_pos", "dreht +φ"),
        group("g2", "Zahnrad G2 + Kurbel B", [part("g2p", "G2 (Idler auf Plattenpin)", to_hub(stl("drive_G2_x2")), p1b, "PLA", 1, "drive_G2_x2.stl", "drive")], p1b, "phi_neg", "dreht −φ"),
    ])
    links = group("links", "Lenker (unter der Platte)", [
        group("la", "Lenker A", [part("lap", "Lenker A", to_hub(stl("link_A_x2")), p2a, "PLA", 1, "link_A_x2.stl", "link")], p2a, "phi_pos"),
        group("lb", "Lenker B", [part("lbp", "Lenker B", to_hub(stl("link_B_x2")), p2b, "PLA", 1, "link_B_x2.stl", "link")], p2b, "phi_neg"),
    ])
    fingers = group("fingers", "Finger (Parallelogramm-Koppeln)", [finger(+1, "Finger A", "fa"), finger(-1, "Finger B", "fb")])
    gripper = group("gripper", "Greifer-Baugruppe (rollt)", [housing, drive, links, fingers], roll_pivot, "roll",
                    "dreht mit dem Roll-Servo um die Unterarmachse")

    wrist = group("wrist", "Handgelenk-Baugruppe", [
        part("yoke", "Joch (klemmt auf beide Ellbogen-Hörner)", stl("wrist_yoke_x2"), z0, "PETG", 1, "wrist_yoke_x2.stl", "wrist", "für beide Arme je 1×"),
        part("ret", "Deckplatte Roll-Servo", stl("wrist_retainer_x2"), z0, "PLA", 1, "wrist_retainer_x2.stl", "wrist", "4× M3 Senkkopf"),
        part("sv1", "Roll-Servo STS3215 (ID 14/24)", roll_servo(), z0, "Feetech STS3215 12 V", 1, "(Zukaufteil)", "servo", "Welle entlang des Unterarms"),
        gripper,
    ])
    root = group("root", "Hand mit Greifer und Handgelenk", [
        part("elbow", "Ellbogen-Servo (vorhanden, nur Referenz)", elbow_servo(), z0, "Feetech STS3215", 1, "(im Roboter)", "ref", "ID 13/23"),
        wrist,
    ])
    meta = {
        "phi": [round(PHI_MIN, 1), PHI_MAX], "C": C, "A": A, "S": S,
        "tp": G.T / 2 + G.PAD, "roll_pivot": [0, W.B_R, 0], "opening_mm": round(2 * (A + C * math.sin(math.radians(PHI_MAX)) - G.T / 2 - G.PAD), 1),
        "hand_tip_a": round(float(OFF[0] + 100), 0),
    }
    return {"meta": meta, "tree": root}


def main():
    data = build()
    tpl = open(os.path.join(HERE, "viewer", "viewer_template.html"), encoding="utf-8").read()
    out = tpl.replace("/*__DATA__*/null", json.dumps(data, separators=(",", ":")))
    path = os.path.join(HERE, "viewer", "gripper_assembly.html")
    open(path, "w", encoding="utf-8").write(out)
    print("wrote", path, f"{len(out) / 1e6:.2f} MB")
    write_standalone(out)


def write_standalone(page):
    """Offline single file (also for iPhone/Safari): three.js inlined, no web font, own <html> shell."""
    vend = os.path.join(HERE, "viewer", "vendor")
    libs = {}
    for fn in ("three.min.js", "OrbitControls.js"):
        libs[fn] = open(os.path.join(vend, fn), encoding="utf-8").read().replace("</script", "<\\/script")
    page = re.sub(r'<link rel="stylesheet" href="https://fonts[^>]*>\n', "", page)
    page = re.sub(r'<meta name="claude:viewport-fit-sides"[^>]*>\n', "", page)
    for fn, src in libs.items():
        page = re.sub(r'<script src="[^"]*/%s"></script>' % re.escape(fn), lambda m: "<script>" + src + "</script>", page)
    assert "https://" not in re.sub(r"/\*[\s\S]*?\*/", "", page.split("</style>")[0]), "external CSS left"
    head = ('<!doctype html>\n<html lang="de">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            '<meta name="apple-mobile-web-app-capable" content="yes">\n')
    page = head + page.replace("<title>", "<title>", 1)
    page = page.replace("<header>", "</head>\n<body>\n<header>", 1) + "\n</body>\n</html>\n"
    path = os.path.join(HERE, "viewer", "gripper_assembly_standalone.html")
    open(path, "w", encoding="utf-8").write(page)
    print("wrote", path, f"{len(page) / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
