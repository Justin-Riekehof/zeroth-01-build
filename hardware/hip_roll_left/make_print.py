#!/usr/bin/env python3
"""Reprint of the broken hip_roll_left bracket for the Bambu Lab P2S (single material, no AMS).

Takes the part from the pinned CAD (resources/cad/z001-opus-*.glb, node 'hip_roll_left'), stitches the T-junction
cracks of the OnShape export (sim/tools/meshfix.py), turns it onto its best print face and writes
  stl/hip_roll_left.stl             (CAD frame, mm, as designed)
  print/hip_roll_left_PETG.3mf      (print orientation, centred on the 256 x 256 mm bed)
  print/plate.png                   (three views of the print orientation)

Usage: .cad/bin/python hardware/hip_roll_left/make_print.py
"""
import os
import sys
import zipfile

import numpy as np
import trimesh

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "sim", "tools"))
from meshfix import is_closed, stitch_t_junctions  # noqa: E402

GLB = os.path.join(REPO, "resources", "cad", "z001-opus-m-93de7567.glb")
NODE = "hip_roll_left"
BED = 256.0
DOWN = (0, 1, 0)       # outward normal of the face that goes on the bed (largest flat face, 1217 mm2)


def load():
    sc = trimesh.load(GLB, force="scene")
    T, g = sc.graph[NODE]
    m = sc.geometry[g].copy()
    m.apply_transform(T)                               # metres, assembly frame
    m = stitch_t_junctions(m)
    assert is_closed(m), "stitched mesh is still open"
    m.apply_scale(1000.0)
    return m


def oriented(m):
    m = m.copy()
    sel = m.face_normals @ np.array(DOWN, float) > 0.95   # the part is ~6 deg off the axes: use the face's real normal
    n = (m.face_normals[sel] * m.area_faces[sel, None]).sum(0)
    m.apply_transform(trimesh.geometry.align_vectors(n / np.linalg.norm(n), [0, 0, -1]))
    m.apply_translation(-m.bounds[0])
    return m


def write_3mf(path, m):
    v = "".join(f'<vertex x="{a:.4f}" y="{b:.4f}" z="{c:.4f}"/>' for a, b, c in m.vertices)
    t = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in m.faces)
    x, y = (BED - m.extents[0]) / 2, (BED - m.extents[1]) / 2
    model = ('<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" '
             'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
             '<metadata name="Title">hip_roll_left (Nachdruck)</metadata><resources>'
             f'<object id="1" name="{NODE}" type="model"><mesh><vertices>{v}</vertices><triangles>{t}</triangles></mesh></object>'
             f'</resources><build><item objectid="1" transform="1 0 0 0 1 0 0 0 1 {x:.3f} {y:.3f} 0"/></build></model>')
    ct = ('<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", model)


def preview(m, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axs = plt.subplots(1, 3, figsize=(12, 4.4))
    for ax, (i, j, title) in zip(axs, [(0, 1, "Draufsicht (Bett)"), (0, 2, "Vorderansicht"), (1, 2, "Seitenansicht")]):
        ax.triplot(m.vertices[:, i], m.vertices[:, j], m.faces, lw=0.15, color="#4a82d6")
        ax.set_aspect("equal"); ax.set_title(title, fontsize=9)
        ax.set_xlabel("xyz"[i] + " mm"); ax.set_ylabel("xyz"[j] + " mm")
    plt.tight_layout(); plt.savefig(path, dpi=110)


def main():
    os.makedirs(os.path.join(HERE, "stl"), exist_ok=True)
    os.makedirs(os.path.join(HERE, "print"), exist_ok=True)
    m = load()
    m.export(os.path.join(HERE, "stl", "hip_roll_left.stl"))
    p = oriented(m)
    write_3mf(os.path.join(HERE, "print", "hip_roll_left_PETG.3mf"), p)
    preview(p, os.path.join(HERE, "print", "plate.png"))
    print(f"volume {m.volume / 1000:.2f} cm3 (~{m.volume / 1000 * 1.27:.0f} g solid, {m.volume / 1000 * 1.27 * 0.55:.0f}-{m.volume / 1000 * 1.27 * 0.8:.0f} g with walls/infill)")
    print("print extents (mm):", np.round(p.extents, 1), " watertight:", p.is_watertight)


if __name__ == "__main__":
    main()
