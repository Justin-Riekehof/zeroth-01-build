#!/usr/bin/env python3
"""Zeroth-01 head back plate ("Neck Mount") with the IMU sockets built in: instead of two loose plug adapters, the
plate gets two ridges ("Stege") on its front face at the header slots. Each ridge is the flush adapter of
imu_adapter.py / rp2040_lcd_128.py (15.43 x 5.27 outside, pocket 13.43 x 3.27 x 4 for the header, 8.43 long so the
display sits flush in the eye opening), fused with the plate; the old slot (21.5 mm deep) is filled solid.

Source: "Neck Mount" of resources/cad/z001-opus-m-93de7567.glb. That mesh is not closed (GLB export): 94 zero-area
cracks at T-junctions and 12 holes where planar faces are missing (mostly the plate faces at y 14.6 / 19.6). Repair
without new vertices: T-junctions are stitched by splitting the boundary edges, the remaining holes are filled per
plane as polygons with their inner loops (earcut), so pockets and holes stay open.
Usage: .cad/bin/python hardware/head_imu/neck_mount_imu.py   (needs trimesh, manifold3d, shapely, networkx, mapbox-earcut)
       ridge geometry and position come from imu_adapter.py / rp2040_lcd_128.py (DISPLAY_FLUSH)
"""
from __future__ import annotations
import json, os
from collections import defaultdict
import numpy as np
import trimesh, mapbox_earcut
from scipy.spatial import cKDTree
from shapely.geometry import Polygon
import cadquery as cq
import imu_adapter as ad
import rp2040_lcd_128 as imu

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
GLB = os.path.join(REPO, "resources", "cad", "z001-opus-m-93de7567.glb")
RF = os.path.join(HERE, "stl", "robotframe"); PRINT = os.path.join(HERE, "print")
SLOT_END_Y = 14.6                                   # the header slots end at the back wall of the plate
Y_PLATE_FRONT = 14.6                                # front face of the plate's back wall
# old Milk-camera bracket (robot right eye): U-frame + 2 screw bosses in front of the back wall - not needed any more.
# Cut from z 413.8 up: below, the right leg of the U merges into the neck collar, which stays.
MILK_BRACKET = dict(x=(-45.2, -10.6), y=(-0.1, Y_PLATE_FRONT), z=(413.8, 436.0))
MILK_LEG_STUB = dict(x=(-14.2, -10.6), y=(-0.1, Y_PLATE_FRONT), z=(409.95, 414.0))   # rest of the U's right leg down to the collar (top 409.9)
# camera ribbon slot (2026-09-19): straight behind the camera through the back wall, centred on the ribbon, at the height
# given by its bend radius - position from hardware/head_cam/cam3_pose.json (written by head_cam3.py). The earlier widened
# neck notch is back to the original (the ribbon no longer goes through the neck).
_cs = json.load(open(os.path.join(REPO, "hardware", "head_cam", "cam3_pose.json")))["cable_slot"]
CAM_SLOT = dict(x=tuple(_cs["x"]), y=(Y_PLATE_FRONT - 0.2, 19.9), z=tuple(_cs["z"]))


def load_neck_mount():
    sc = trimesh.load(GLB, force="scene"); g = sc.graph
    for n in g.nodes_geometry:
        if n.split("_")[0] == "Neck Mount":
            T, gn = g.get(n); m = sc.geometry[gn].copy(); m.apply_transform(T); m.apply_scale(1000.0); break
    V = m.vertices.copy()
    for i, j in sorted(cKDTree(V).query_pairs(1e-3)): V[j] = V[i]        # weld vertices < 1 um apart
    m = trimesh.Trimesh(V, m.faces, process=True); m.merge_vertices(digits_vertex=6)
    return m


def boundary_edges(m):
    e = m.edges_sorted; u, c = np.unique(e, axis=0, return_counts=True)
    return u[c == 1]


def stitch_t_junctions(m, tol=2e-3, rounds=20):
    """close cracks: a boundary vertex lying on another boundary edge splits that edge (and its face)"""
    F = m.faces.copy(); V = m.vertices
    for _ in range(rounds):
        mm = trimesh.Trimesh(V, F, process=False); b = boundary_edges(mm)
        if len(b) == 0: break
        bverts = np.unique(b); tree = cKDTree(V[bverts])
        edge_face = {}
        for fi, f in enumerate(F):
            for k in range(3):
                a, c = f[k], f[(k + 1) % 3]; edge_face[(min(a, c), max(a, c))] = (fi, k)
        splits = {}
        for a, c in b:
            pa, pc = V[a], V[c]; L = np.linalg.norm(pc - pa)
            if L < 1e-9: continue
            cand = tree.query_ball_point((pa + pc) / 2, L / 2 + tol)
            hits = []
            for ci in cand:
                v = bverts[ci]
                if v in (a, c): continue
                t = np.dot(V[v] - pa, pc - pa) / L ** 2
                if 1e-6 < t < 1 - 1e-6 and np.linalg.norm(pa + t * (pc - pa) - V[v]) < tol: hits.append((t, v))
            if hits: splits[(a, c)] = sorted(hits)
        if not splits: break
        newF, drop = [], set()
        for (a, c), hits in splits.items():
            fi, k = edge_face[(min(a, c), max(a, c))]
            if fi in drop: continue
            f = F[fi]; p, q, r = f[k], f[(k + 1) % 3], f[(k + 2) % 3]        # edge p->q in face order, r opposite
            chain = [p] + [v for t, v in (hits if p == a else hits[::-1])] + [q]
            for s in range(len(chain) - 1): newF.append([chain[s], chain[s + 1], r])
            drop.add(fi)
        F = np.vstack([np.delete(F, sorted(drop), axis=0), np.array(newF)])
    return trimesh.Trimesh(V, F, process=True)


def boundary_loops(m):
    b = boundary_edges(m); adj = defaultdict(list)
    for a, c in b: adj[a].append(c); adj[c].append(a)
    seen, loops = set(), []
    for s in adj:
        if s in seen: continue
        L = [s]; seen.add(s); prev, cur = None, s
        while True:
            nxt = [n for n in adj[cur] if n != prev and n not in seen]
            if not nxt: break
            prev, cur = cur, nxt[0]; L.append(cur); seen.add(cur)
        loops.append(L)
    return loops


def fill_planar_holes(m):
    """fill every hole plane by plane: loops in one plane become polygons with holes (nesting by containment)"""
    V = m.vertices; groups = defaultdict(list)
    for L in boundary_loops(m):
        if len(L) < 3: continue
        P = V[L]; c0 = P.mean(0); _, sv, vt = np.linalg.svd(P - c0); n = vt[-1]
        n = n * np.sign(n[np.argmax(np.abs(n))])
        key = (tuple(np.round(n, 2)), round(float(np.dot(c0, n)), 1))
        groups[key].append(L)
    new_faces = []
    for (n, d), loops in groups.items():
        n = np.array(n); n /= np.linalg.norm(n); u = np.cross(n, [1, 0, 0] if abs(n[0]) < 0.9 else [0, 1, 0]); u /= np.linalg.norm(u); w = np.cross(n, u)
        polys = [Polygon(np.c_[V[L] @ u, V[L] @ w]) for L in loops]
        depth = [sum(1 for j, q in enumerate(polys) if j != i and q.buffer(1e-6).contains(p.representative_point())) for i, p in enumerate(polys)]
        for i, L in enumerate(loops):
            if depth[i] % 2: continue                                      # holes are handled with their outer loop
            rings = [L] + [loops[j] for j in range(len(loops)) if depth[j] == depth[i] + 1 and polys[i].buffer(1e-6).contains(polys[j].representative_point())]
            ids = np.concatenate(rings); pts = np.c_[V[ids] @ u, V[ids] @ w]
            ends = np.cumsum([len(r) for r in rings]).astype(np.uint32)
            tri = mapbox_earcut.triangulate_float64(pts, ends).reshape(-1, 3)
            new_faces.extend(ids[tri].tolist())
    out = trimesh.Trimesh(V, np.vstack([m.faces] + ([np.array(new_faces)] if new_faces else [])), process=True)
    trimesh.repair.fix_winding(out); trimesh.repair.fix_inversion(out)
    return out, len(new_faces)


def ridges():
    """the two IMU sockets as solids in the assembly frame: body 15.43 x 5.27 from the pocket rim (0.5 mm in front of the
    PCB back face) to 0.3 mm into the plate, pocket 13.43 x 3.27 x 4 with lead-in, slot filled completely (+0.05/side overlap)"""
    y_rim = imu.Y_PCB_BACK + imu.Z_ADAPTER; y_face = imu.SLOT_FACE_Y; out = []   # rim 0.5 mm behind the PCB back face
    for zc in imu.SLOT_Z:
        xc = imu.SLOT_X
        body = cq.Workplane("XZ", origin=(xc, y_face + 0.3, zc)).rect(ad.OUT_W, ad.OUT_H).extrude(y_face + 0.3 - y_rim)   # XZ extrudes -Y
        pocket = cq.Workplane("XZ", origin=(xc, y_rim + ad.POCKET_D, zc)).rect(ad.SLOT_W + 2 * ad.POCKET_CLEAR, ad.SLOT_H + 2 * ad.POCKET_CLEAR).extrude(ad.POCKET_D + 1.0)
        body = body.cut(pocket)
        if ad.C_ENTRY:
            body = body.faces("<Y").edges(cq.selectors.BoxSelector((xc - ad.SLOT_W / 2 - 0.1, y_rim - 0.01, zc - ad.SLOT_H / 2 - 0.1),
                                                                (xc + ad.SLOT_W / 2 + 0.1, y_rim + 0.01, zc + ad.SLOT_H / 2 + 0.1))).chamfer(ad.C_ENTRY)
        # fill the whole slot (it is 21.5 mm deep, down to the back wall at y 14.6), otherwise a closed void stays behind
        plug = cq.Workplane("XZ", origin=(xc, SLOT_END_Y + 0.3, zc)).rect(ad.SLOT_W + 0.1, ad.SLOT_H + 0.1).extrude(SLOT_END_Y + 0.6 - y_face)
        out.append(body.union(plug))
    return out


def tm(wp):
    v, f = wp.val().tessellate(0.005, 0.05)
    return trimesh.Trimesh([(p.x, p.y, p.z) for p in v], f, process=True)


def main():
    os.makedirs(PRINT, exist_ok=True)
    raw = load_neck_mount()
    st = stitch_t_junctions(raw)
    print(f"neck mount: {len(boundary_edges(raw))} open edges -> {len(boundary_edges(st))} after T-junction stitching")
    fixed, nfill = fill_planar_holes(st)
    e = fixed.edges_sorted; _, cnt = np.unique(e, axis=0, return_counts=True)
    print(f"  edge use: {np.bincount(cnt).tolist()} (index = faces per edge; only 2 allowed), winding {fixed.is_winding_consistent}")
    print(f"  filled {nfill} triangles -> watertight {fixed.is_watertight}, bodies {fixed.body_count}, volume {fixed.volume/1000:.2f} cm3")
    assert fixed.is_watertight and fixed.volume > 0
    # every original vertex kept, no new ones: the repair only adds faces
    assert len(fixed.vertices) <= len(raw.vertices) + 0
    cut = [trimesh.creation.box(bounds=np.array([[b["x"][0], b["y"][0], b["z"][0]], [b["x"][1], b["y"][1], b["z"][1]]])) for b in (MILK_BRACKET, MILK_LEG_STUB, CAM_SLOT)]
    trimmed = trimesh.boolean.difference([fixed] + cut, engine="manifold")
    print(f"  - Milk bracket, camera ribbon slot {CAM_SLOT['x'][1]-CAM_SLOT['x'][0]:.0f} x {CAM_SLOT['z'][1]-CAM_SLOT['z'][0]:.0f} mm: {fixed.volume/1000:.2f} -> {trimmed.volume/1000:.2f} cm3")
    rg = [tm(r) for r in ridges()]
    new = trimesh.boolean.union([trimmed] + rg, engine="manifold")
    assert new.is_watertight and new.body_count == 1, (new.is_watertight, new.body_count)
    print(f"  + 2 IMU ridges -> {new.volume/1000:.2f} cm3, watertight, 1 body")
    new.export(os.path.join(RF, "neck_mount_imu.stl"))
    pr = new.copy(); pr.apply_transform(trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0]))   # back face (+Y) on the bed, ridges up
    pr.apply_translation(-pr.bounds[0]); pr.export(os.path.join(PRINT, "neck_mount_imu.stl"))
    json.dump(dict(open_edges_raw=int(len(boundary_edges(raw))), open_edges_after_stitch=int(len(boundary_edges(st))),
                   fill_triangles=nfill, volume_repaired_cm3=round(fixed.volume / 1000, 3), volume_with_ridges_cm3=round(new.volume / 1000, 3)),
              open(os.path.join(HERE, "neck_mount_imu.json"), "w"), indent=1)
    print("done ->", os.path.join(PRINT, "neck_mount_imu.stl"))


if __name__ == "__main__":
    main()
