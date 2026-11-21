#!/usr/bin/env python3
"""Print plate of the reinforced neck piece for the Bambu Lab P2S (PETG, single material, no AMS).

Takes stl/robotframe/neck_piece_reinforced.stl (written by make_neck_piece.py, already watertight and manifold), puts
the front face of the claw (-Y, y -28.85) on the bed and centres it on the 256 x 256 mm plate:
  print/neck_piece_PETG_front.3mf    (geometry only; settings come from make_bambu_project.py)
  print/plate.png                    (three views)
Screw axes stand vertical in this pose: round holes, and the pull-out surface of the 8 mm lug wall cuts across the layers
instead of running between them. Front rather than back on the bed: the rounded inside of the claw (0.25 mm to the torso)
is printed without support; the support goes under the flat front faces of lugs and skirt (y -10), which are easy to
file flat. Back on the bed would put 1019 mm2 of support on the claw's inside (bed 595 vs 1202 mm2, overhang 2870 vs 2018).

Usage: .cad/bin/python hardware/neck_piece/make_print.py
"""
import os
import sys
import zipfile

import numpy as np
import trimesh

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "hardware", "hip_yaw_left"))
from make_print import preview  # noqa: E402

SRC = os.path.join(HERE, "stl", "robotframe", "neck_piece_reinforced.stl")
NAME = "neck_piece_reinforced"
BED = 256.0


def on_front(m):
    """exact +90 deg about X: -Y (claw front, axis-aligned in the CAD) -> -Z. A normal-weighted fit would also count
    other -Y faces (lug fronts, skirt) and tilt the part."""
    m = m.copy(); m.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))
    m.apply_translation(-m.bounds[0])
    return m


def write_3mf(path, m):
    v = "".join(f'<vertex x="{a:.4f}" y="{b:.4f}" z="{c:.4f}"/>' for a, b, c in m.vertices)
    t = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in m.faces)
    x, y = (BED - m.extents[0]) / 2, (BED - m.extents[1]) / 2
    model = ('<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" '
             'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
             '<metadata name="Title">Halsstueck verstaerkt (Torso to Neck)</metadata><resources>'
             f'<object id="1" name="{NAME}" type="model"><mesh><vertices>{v}</vertices><triangles>{t}</triangles></mesh></object>'
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


def main():
    m = trimesh.load(SRC)
    assert m.is_watertight and m.is_winding_consistent, "neck piece mesh is not closed - run make_neck_piece.py"
    print(f"volume {m.volume / 1000:.2f} cm3 (~{m.volume / 1000 * 1.27:.0f} g solid PETG)")
    p = on_front(m)
    write_3mf(os.path.join(HERE, "print", "neck_piece_PETG_front.3mf"), p)
    fn, ar, z = p.face_normals, p.area_faces, p.vertices[p.faces].mean(1)[:, 2]
    print(f"front on bed: extents {np.round(p.extents, 1)} mm, bed contact {ar[(fn[:, 2] < -0.95) & (z < 0.3)].sum():.0f} mm2, "
          f"overhang >45deg {ar[(fn[:, 2] < -0.707) & (z > 0.3)].sum():.0f} mm2")
    preview(p, os.path.join(HERE, "print", "plate.png"))


if __name__ == "__main__":
    main()
