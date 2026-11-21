#!/usr/bin/env python3
"""Torso with through holes for the through-bolted neck piece (v2, claw + M3x35).

The pinned torso has two dia 4 insert holes (y -20 ... -10, cone to -21.5) and a closed 5.4 mm front wall behind them.
This cuts a dia 3.3 clearance bore along each screw axis from the front face (y -25.4) through the whole front shelf
(to y -10), so the printed torso needs no drilling and no heat-set inserts at the neck.

Usage: .cad/bin/python hardware/neck_piece/make_torso.py   -> stl/torso_neck_through.stl (robot frame, mm)
"""
import os, sys, json
import trimesh
import cadquery as cq
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_neck_piece as nk

OUT = os.path.join(nk.HERE, "stl", "torso_neck_through.stl")


def bore(x, z):
    return cq.Workplane("XZ", origin=(x, nk.Y_TORSO_IN + 1.0, z)).circle(nk.HOLE_D / 2).extrude(nk.Y_TORSO_IN + 1.0 - (nk.Y_TORSO_OUT - 1.0))


def main():
    torso = nk.load("Torso"); assert torso.is_watertight
    new = trimesh.boolean.difference([torso] + [nk.tm(bore(x, z)) for x, z in nk.SCREWS], engine="manifold")
    assert new.is_watertight and new.body_count == 1
    # check: the bore really goes through (ray along +y from in front of the screw axis hits nothing up to y -9)
    for x, z in nk.SCREWS:
        hits = new.ray.intersects_location([[x, -40, z]], [[0, 1, 0]])[0]
        assert not len(hits) or hits[:, 1].min() > -9.5, (x, z, hits)
    new.export(OUT)
    d = (torso.volume - new.volume) / 1000
    print(f"torso: {torso.volume/1000:.2f} -> {new.volume/1000:.2f} cm3 ({-d:+.3f}), bores at {nk.SCREWS}, wrote {OUT}")


if __name__ == "__main__":
    main()
