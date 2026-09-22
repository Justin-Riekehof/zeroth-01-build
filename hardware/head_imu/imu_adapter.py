#!/usr/bin/env python3
"""Zeroth-01 head, left eye: plug adapter between the IMU's pin headers and the header slots of the eye (CadQuery).

One adapter per header (print 2x). Slot of the head back plate (CAD): 13.43 x 3.27 mm.
  female side: pocket 13.43 x 3.27 mm, 4 mm deep, 1 mm wall all round (outer 15.43 x 5.27) -> takes the IMU header
  floor:       1 mm (the same wall thickness)
  male side:   tongue 13.43 x 3.27 mm (negative of the slot), 5 mm long, on top of the floor -> into the slot
Overall 15.43 x 5.27 x 10 mm (flush variant with spacer: see rp2040_lcd_128.py).

Frame = print orientation: pocket opening on the bed (Z 0), tongue up (Z 10). Printed this way there is no overhang,
only the floor bridging the 3 mm pocket width. STL -> stl/imu_adapter.stl
Usage: .cad/bin/python hardware/head_imu/imu_adapter.py
"""
from __future__ import annotations
import json, os
import cadquery as cq

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "stl")

SLOT_W, SLOT_H = 13.43, 3.27        # = the header slots of the head back plate (Neck Mount, CAD) = pocket = tongue [Vorgabe]
                                    # (was 13.0 x 3.0 measured on the print: pocket too tight for the header, tongue too loose)
POCKET_D = 4.0                      # pocket depth [Vorgabe]
WALL = 1.0                          # wall on all sides of the pocket, also the floor [Vorgabe]
TONGUE_L = 5.0                      # tongue length [Vorgabe]
POCKET_CLEAR = 0.0                  # extra per side in the pocket (+ = looser); 0 = exactly the measured slot
TONGUE_CLEAR = 0.0                  # taken off per side of the tongue (+ = looser in the eye slot)
C_ENTRY = 0.3                       # 45-degree lead-in at the pocket mouth and on the tongue tip (does not change the fit)

OUT_W, OUT_H = SLOT_W + 2 * POCKET_CLEAR + 2 * WALL, SLOT_H + 2 * POCKET_CLEAR + 2 * WALL   # 15 x 5
Z_FLOOR = POCKET_D                  # 4: pocket ceiling = underside of the floor
Z_BODY = POCKET_D + WALL            # 5: top of the body = root of the tongue
Z_TOP = Z_BODY + TONGUE_L           # 10


def build(spacer: float = 0.0) -> cq.Workplane:
    """spacer: extra solid length between floor and tongue (longer adapter, e.g. for a display sitting in the eye opening)"""
    body = cq.Workplane("XY").box(OUT_W, OUT_H, Z_BODY + spacer, centered=(True, True, False))
    pw, ph = SLOT_W + 2 * POCKET_CLEAR, SLOT_H + 2 * POCKET_CLEAR
    body = body.cut(cq.Workplane("XY").box(pw, ph, Z_FLOOR, centered=(True, True, False)))
    if C_ENTRY:   # lead-in: chamfer the four edges of the pocket mouth on the bed face
        body = body.faces("<Z").edges(cq.selectors.BoxSelector((-pw / 2 - 0.01, -ph / 2 - 0.01, -0.01), (pw / 2 + 0.01, ph / 2 + 0.01, 0.01))).chamfer(C_ENTRY)
    tw, th = SLOT_W - 2 * TONGUE_CLEAR, SLOT_H - 2 * TONGUE_CLEAR
    tongue = cq.Workplane("XY", origin=(0, 0, Z_BODY + spacer)).box(tw, th, TONGUE_L, centered=(True, True, False))
    if C_ENTRY: tongue = tongue.faces(">Z").edges().chamfer(C_ENTRY)
    return body.union(tongue)


def main():
    os.makedirs(OUT, exist_ok=True)
    s = build(); v = s.val(); bb = v.BoundingBox()
    assert v.isValid() and len(s.solids().vals()) == 1
    print(f"imu_adapter: volume {v.Volume():.1f} mm3, bbox {bb.xlen:.2f} x {bb.ylen:.2f} x {bb.zlen:.2f} mm")
    cq.exporters.export(s, os.path.join(OUT, "imu_adapter.stl"), tolerance=0.005, angularTolerance=0.05)
    cq.exporters.export(s, os.path.join(OUT, "imu_adapter.step"))
    json.dump(dict(outer_mm=[OUT_W, OUT_H, Z_TOP], pocket_mm=[SLOT_W + 2 * POCKET_CLEAR, SLOT_H + 2 * POCKET_CLEAR, POCKET_D],
                   floor_mm=WALL, tongue_mm=[SLOT_W - 2 * TONGUE_CLEAR, SLOT_H - 2 * TONGUE_CLEAR, TONGUE_L], lead_in_mm=C_ENTRY,
                   volume_mm3=round(v.Volume(), 1)), open(os.path.join(OUT, "imu_adapter.json"), "w"), indent=1)
    print("done ->", OUT)


if __name__ == "__main__":
    main()
