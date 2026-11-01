#!/usr/bin/env python3
"""Print preparation for the Bambu Lab P2S (256 x 256 x 256 mm, single material, no AMS).

Reads stl/*.stl, turns every part into its print orientation, packs the copies for BOTH grippers
(count = the _xN suffix of the file name) onto plates per material and writes
  print/plate_<nn>_<material>.3mf   (plain 3MF, mm, every copy a separate object, centred on the bed)
  print/plates.png                  (top view of every plate)
  print/PRINT.md                    (what is on which plate + slicer settings)
Open a 3MF in Bambu Studio, pick "Bambu Lab P2S 0.4 nozzle" and the filament, then apply PRINT.md.

Usage: .cad/bin/python hardware/gripper/make_print.py
"""
import os
import re
import zipfile

import numpy as np
import trimesh

HERE = os.path.dirname(os.path.abspath(__file__))
STL = os.path.join(HERE, "stl")
OUT = os.path.join(HERE, "print")
BED = 256.0
USE = 238.0          # usable edge length (margin for brim/skirt)
GAP = 6.0

# file, material, outward normal of the face that goes on the bed (None = as exported), settings key
PARTS = [
    # file, material, outward normal of the face on the bed, key, plate group
    ("finger_coupler_x4", "PETG", (0, 0, 1), "coupler", "Finger"),
    ("finger_tip_A_x2", "PETG", (0, 1, 0), "tip", "Finger"),
    ("finger_tip_B_x2", "PETG", (0, -1, 0), "tip", "Finger"),
    ("wrist_yoke_x2", "PETG", None, "yoke", "Mechanik"),
    ("link_post_x4", "PETG", (0, 0, 1), "pin", "Mechanik"),
    ("drive_G1_x2", "PETG", None, "gear", "Mechanik"),
    ("drive_G2_x2", "PETG", None, "gear", "Mechanik"),
    ("link_A_x2", "PETG", None, "pin", "Mechanik"),
    ("link_B_x2", "PETG", None, "pin", "Mechanik"),
    ("housing_tray_x2", "PETG", None, "housing", "Gehaeuse"),
    ("housing_top_plate_x2", "PETG", None, "plate", "Gehaeuse"),
    ("wrist_retainer_x2", "PETG", (-1, 0, 0), "housing", "Gehaeuse"),
    ("cap_d10_x4", "PETG", None, "cap", "Gehaeuse"),
    ("cap_d12_x8", "PETG", None, "cap", "Gehaeuse"),
    ("cap_d14_x2", "PETG", None, "cap", "Gehaeuse"),
    ("pad_tpu_x4", "TPU", (0, -1, 0), "pad", "TPU"),
]
DENSITY = {"PLA": 1.24, "PETG": 1.27, "TPU": 1.21}


def oriented(name, down):
    m = trimesh.load(os.path.join(STL, name + ".stl"))
    if down is not None:
        R = trimesh.geometry.align_vectors(np.array(down, float), [0, 0, -1])
        m.apply_transform(R)
    m.apply_translation(-m.bounds[0])           # min corner to the origin, z min = 0
    return m


def count_of(name):
    return int(re.search(r"_x(\d+)$", name).group(1))


# Parts whose geometry changed since the plate the user last opened (compared by volume and size against the published
# viewer data of that state). Everything is PETG now. Edit this list when the geometry changes again.
NACHDRUCK = ["wrist_yoke_x2", "drive_G1_x2", "link_A_x2", "link_B_x2", "housing_tray_x2", "housing_top_plate_x2", "wrist_retainer_x2"]


def _fill(plates, grp, mat, todo):
    todo = sorted(todo, key=lambda it: -it["mesh"].extents[1])
    state = {"cur": None, "x": 0.0, "y": 0.0, "row_h": 0.0}

    def new_plate():
        state.update(cur={"mat": mat, "grp": grp, "items": []}, x=0.0, y=0.0, row_h=0.0)
        plates.append(state["cur"])
    new_plate()
    for it in todo:
        w, d = it["mesh"].extents[0], it["mesh"].extents[1]
        if state["x"] + w > USE:                         # next row
            state.update(x=0.0, y=state["y"] + state["row_h"] + GAP, row_h=0.0)
        if state["y"] + d > USE:                         # next plate
            new_plate()
        it["pos"] = (state["x"], state["y"])
        state["cur"]["items"].append(it)
        state["x"] += w + GAP
        state["row_h"] = max(state["row_h"], d)


def pack():
    items = []
    for name, mat, down, key, grp in PARTS:
        m = oriented(name, down)
        for i in range(count_of(name)):
            items.append({"name": name, "mat": mat, "mesh": m, "key": key, "idx": i + 1, "grp": grp})
    plates = []
    for grp in ("Finger", "Mechanik", "Gehaeuse", "TPU"):
        todo = [it for it in items if it["grp"] == grp]
        _fill(plates, grp, todo[0]["mat"], todo)
    extra = []                                           # reprint plate: only what the G2 axle change touched
    for name in NACHDRUCK:
        spec = next(sp for sp in PARTS if sp[0] == name)
        m = oriented(name, spec[2])
        for i in range(count_of(name)):
            extra.append({"name": name, "mat": "PETG", "mesh": m, "key": spec[3], "idx": i + 1, "grp": "Nachdruck"})
    _fill(plates, "Nachdruck", "PETG", extra)
    return plates


def center(plate):
    xs = [it["pos"][0] for it in plate["items"]] + [it["pos"][0] + it["mesh"].extents[0] for it in plate["items"]]
    ys = [it["pos"][1] for it in plate["items"]] + [it["pos"][1] + it["mesh"].extents[1] for it in plate["items"]]
    ox = BED / 2 - (min(xs) + max(xs)) / 2
    oy = BED / 2 - (min(ys) + max(ys)) / 2
    for it in plate["items"]:
        it["place"] = (it["pos"][0] + ox, it["pos"][1] + oy)


def write_3mf(path, plate):
    names = []
    for it in plate["items"]:
        if it["name"] not in names:
            names.append(it["name"])
    res, build = [], []
    for oid, n in enumerate(names, 1):
        m = next(it["mesh"] for it in plate["items"] if it["name"] == n)
        v = "".join(f'<vertex x="{a:.4f}" y="{b:.4f}" z="{c:.4f}"/>' for a, b, c in m.vertices)
        t = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in m.faces)
        res.append(f'<object id="{oid}" name="{n}" type="model"><mesh><vertices>{v}</vertices><triangles>{t}</triangles></mesh></object>')
    for it in plate["items"]:
        oid = names.index(it["name"]) + 1
        x, y = it["place"]
        build.append(f'<item objectid="{oid}" transform="1 0 0 0 1 0 0 0 1 {x:.3f} {y:.3f} 0"/>')
    model = ('<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" '
             'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
             '<metadata name="Title">Zwei-Finger-Greifer mit Handgelenk</metadata>'
             f'<resources>{"".join(res)}</resources><build>{"".join(build)}</build></model>')
    ct = ('<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", model)


def preview(plates, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    col = {"PETG": "#4a82d6", "PLA": "#8794a3", "TPU": "#d9a441"}
    n = len(plates)
    fig, axs = plt.subplots(1, n, figsize=(4.2 * n, 4.6))
    axs = np.atleast_1d(axs)
    for ax, (i, p) in zip(axs, enumerate(plates, 1)):
        ax.add_patch(Rectangle((0, 0), BED, BED, fill=False, lw=1.5, ec="#555"))
        for it in p["items"]:
            x, y = it["place"]
            w, d = it["mesh"].extents[0], it["mesh"].extents[1]
            ax.add_patch(Rectangle((x, y), w, d, fc=col[p["mat"]], ec="#222", lw=0.6, alpha=0.85))
            if w > 22 and d > 12:
                ax.text(x + w / 2, y + d / 2, re.sub(r"_x\d+$", "", it["name"]).replace("housing_", "").replace("wrist_", "")[:16], ha="center", va="center", fontsize=5)
        ax.set_xlim(-4, BED + 4); ax.set_ylim(-4, BED + 4); ax.set_aspect("equal")
        ax.set_title(f"Platte {i}: {p['mat']} {p['grp'] if p['grp'] != 'TPU' else ''} ({len(p['items'])} Teile)", fontsize=9)
        ax.set_xticks([]); ax.set_yticks([])
    plt.tight_layout()
    plt.savefig(path, dpi=110)


def main():
    os.makedirs(OUT, exist_ok=True)
    for f in os.listdir(OUT):
        if f.startswith("plate_") and f.endswith(".3mf"):
            os.remove(os.path.join(OUT, f))
    plates = pack()
    for p in plates:
        center(p)
    lines = []
    for i, p in enumerate(plates, 1):
        fn = f"plate_{i:02d}_{p['mat']}_{p['grp']}.3mf" if p["grp"] != "TPU" else f"plate_{i:02d}_{p['mat']}.3mf"
        write_3mf(os.path.join(OUT, fn), p)
        counts = {}
        for it in p["items"]:
            counts[it["name"]] = counts.get(it["name"], 0) + 1
        grams = sum(it["mesh"].volume / 1000 * DENSITY[p["mat"]] for it in p["items"])
        hmax = max(it["mesh"].extents[2] for it in p["items"])
        lines.append((i, p["mat"], fn, counts, grams, hmax))
        print(fn, counts, f"~{grams * 0.55:.0f}-{grams * 0.8:.0f} g, h<={hmax:.0f} mm")
    preview(plates, os.path.join(OUT, "plates.png"))
    import json
    json.dump([{"plate": i, "material": m, "file": f, "parts": c, "mass_100_g": round(g, 1), "max_height_mm": round(h, 1)} for i, m, f, c, g, h in lines],
              open(os.path.join(OUT, "plates.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
