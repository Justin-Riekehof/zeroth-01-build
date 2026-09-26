#!/usr/bin/env python3
"""Close the cracks in the pinned-CAD GLB meshes so their volume can be trusted.

The GLB exports are not watertight: neighbouring faces meet at T-junctions (an edge is split on one side
but not on the other), which leaves hundreds of open edges per part without any hole in the surface.
`stitch_t_junctions` splits the unsplit edge at those points -- it adds no vertices and moves nothing, so
the geometry is unchanged; it only makes the mesh consistent.

Lifted from hardware/head_imu/neck_mount_imu.py (which repaired the head's back plate this way and is the
reference implementation -- it additionally fills real planar holes, which needs shapely/mapbox_earcut;
this module deliberately stays on numpy/scipy/trimesh so the ksim venv can use it).

`solid_props` is what the model builder wants: after stitching, a part is usable as a solid as soon as its
surface is CLOSED and consistently wound. Strict two-manifoldness is not required -- a handful of edges
shared by more than two faces (the GLB has 10-20 per part, plus zero-volume slivers) does not affect the
divergence-theorem integrals trimesh uses for volume, centroid and inertia.
"""
from __future__ import annotations

import numpy as np
import trimesh
from scipy.spatial import cKDTree


def boundary_edges(m: trimesh.Trimesh) -> np.ndarray:
    e = m.edges_sorted
    u, c = np.unique(e, axis=0, return_counts=True)
    return u[c == 1]


def stitch_t_junctions(m: trimesh.Trimesh, tol: float = 2e-4, rounds: int = 20) -> trimesh.Trimesh:
    """close cracks: a boundary vertex lying on another boundary edge splits that edge (and its face).

    tol is in the mesh's own units -- the CAD meshes are in metres, so the default is 0.2 mm."""
    F = m.faces.copy()
    V = m.vertices
    for _ in range(rounds):
        mm = trimesh.Trimesh(V, F, process=False)
        b = boundary_edges(mm)
        if len(b) == 0:
            break
        bverts = np.unique(b)
        tree = cKDTree(V[bverts])
        edge_face = {}
        for fi, f in enumerate(F):
            for k in range(3):
                a, c = f[k], f[(k + 1) % 3]
                edge_face[(min(a, c), max(a, c))] = (fi, k)
        splits = {}
        for a, c in b:
            pa, pc = V[a], V[c]
            L = np.linalg.norm(pc - pa)
            if L < 1e-9:
                continue
            hits = []
            for ci in tree.query_ball_point((pa + pc) / 2, L / 2 + tol):
                v = bverts[ci]
                if v in (a, c):
                    continue
                t = np.dot(V[v] - pa, pc - pa) / L ** 2
                if 1e-6 < t < 1 - 1e-6 and np.linalg.norm(pa + t * (pc - pa) - V[v]) < tol:
                    hits.append((t, v))
            if hits:
                splits[(a, c)] = sorted(hits)
        if not splits:
            break
        newF, drop = [], set()
        for (a, c), hits in splits.items():
            fi, k = edge_face[(min(a, c), max(a, c))]
            if fi in drop:
                continue
            f = F[fi]
            p, q, r = f[k], f[(k + 1) % 3], f[(k + 2) % 3]     # edge p->q in face order, r opposite
            chain = [p] + [v for t, v in (hits if p == a else hits[::-1])] + [q]
            for s in range(len(chain) - 1):
                newF.append([chain[s], chain[s + 1], r])
            drop.add(fi)
        F = np.vstack([np.delete(F, sorted(drop), axis=0), np.array(newF)])
    return trimesh.Trimesh(V, F, process=True)


def open_length(m: trimesh.Trimesh) -> float:
    """Total length of the surface's open edges (0 for a closed surface)."""
    b = boundary_edges(m)
    if len(b) == 0:
        return 0.0
    V = m.vertices
    return float(np.linalg.norm(V[b[:, 0]] - V[b[:, 1]], axis=1).sum())


def is_closed(m: trimesh.Trimesh, max_open: float = 2e-3) -> bool:
    """Closed enough for volume/centroid/inertia: consistent winding, positive volume, and at most a
    sub-millimetre of leftover boundary.

    `max_open` (metres, default 2 mm of TOTAL edge length) exists because stitching sometimes leaves one or
    two crack edges a few tenths of a mm long. Those contribute nothing to the divergence-theorem integrals
    -- the left hand keeps two such edges (0.47 mm together) and integrates to 46.9 g, exactly the volume of
    its mirrored twin, while the convex-hull fallback would have put it at 37.7 g and made the arms
    asymmetric. A genuinely open shell has orders of magnitude more boundary than this."""
    return open_length(m) <= max_open and bool(m.is_winding_consistent) and m.volume > 1e-12


def solid_props(mesh: trimesh.Trimesh, density: float):
    """(mass, centre of mass, inertia about the com, how) for a printed part.

    Tries the mesh as given, then stitched; falls back to half the convex hull (the old heuristic, which
    over-estimates hollow shells by 2-3x -- the head came out 88 g that way against 30 g of real volume)."""
    m = mesh.copy()
    m.merge_vertices()
    how = "volume"
    for tol in (2e-4, 5e-4):        # a few parts keep 1-2 cracks wider than 0.2 mm
        if is_closed(m):
            break
        m = stitch_t_junctions(m, tol=tol)
        how = "stitched"
    if is_closed(m):
        m.density = density
        return m.volume * density, m.center_mass, m.moment_inertia, how
    hull = mesh.convex_hull
    lo, hi = mesh.bounds
    d = hi - lo
    mass = 0.5 * hull.volume * density
    I = mass / 12.0 * np.diag([d[1] ** 2 + d[2] ** 2, d[0] ** 2 + d[2] ** 2, d[0] ** 2 + d[1] ** 2])
    return mass, hull.centroid, I, "hull/2"
