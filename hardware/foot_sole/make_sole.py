#!/usr/bin/env python3
"""TPU slip-on shoe ("Ueberschuh") for the printed foot (ankle_pitch link of sim/assets/zbot-cad).  v0.2

The cavity is the true negative of the foot: the signed distance field of the foot mesh (exact distances in a band
around the surface, voxel fill only for the sign far away), cut at the flat top face of the foot block and eroded by
UNDERSIZE for the stretch fit. No hull, no height-field: the curved underside, the flanks and the rounded corners
come out of the real mesh. The side walls therefore follow the foot all the way up to the top face, and a small lip
(LIP mm) snaps over the top edge so the shoe cannot slip off. The two ankle brackets that stand on the top face
pass through the opening.

Frame = link frame of the ankle mesh (m in the STL, mm here); +z up, sole down -> print as-is, open side up,
no supports (outside = vertical extrusion of the foot silhouette, the space under the curved flanks is solid).

Usage (repo root):  .cad/bin/python hardware/foot_sole/make_sole.py   (needs scikit-image)
Writes stl/foot_sole_{left,right}.stl and prints volume / mass.

Contact-surface profiles (all TPU, one print each; same outer plane and sole height at the contact tips, so one
sim model fits all - only the contact patch differs). Heights are measured from the old flat underside plane:
  smooth       flat underside (baseline)
  ribs         transverse grooves 2.0 mm wide, 1.0 mm deep, 5 mm pitch        (forward/backward grip)
  herringbone  chevron grooves 1.8 mm wide, 1.0 mm deep, 45 deg, apex to +x   (grip in x and y, channels water outwards)
  nubs         domed nubs d 3.4 -> 2.6 mm, 1.0 mm high, hex pitch 5.5 mm      (many small soft contacts)
  studs        conical studs d 3.6 -> 1.0 mm, 1.6 mm high, hex pitch 8 mm      (few hard-ish contacts that dig in)
Dry hard floors: grooves remove contact area and can slightly LOWER mu; they pay off on wet/dusty floors. Studs/nubs
act on carpet, rubber mats, soft surfaces. Which one wins here is a measurement (README: tilt test), not a given.
Files: stl/foot_sole_{side}[_profile].stl.

  rubber       for a glued-on rubber sole (climbing-shoe resole rubber, RUBBER_T thick): the TPU floor is RUBBER_T
               thinner and has no bottom chamfer (the rubber covers the whole flat underside, flush with the wall),
               so TPU + rubber end on the same sole plane as the other profiles. Also writes
               print/rubber_template_A4.pdf: the underside outline 1:1 for cutting the rubber.
"""
import os

import manifold3d as mf
import numpy as np
import trimesh
from scipy.ndimage import distance_transform_edt
from scipy.spatial import cKDTree
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union
from skimage import measure

HERE = os.path.dirname(os.path.abspath(__file__))
MESHES = os.path.join(HERE, "..", "..", "sim", "assets", "zbot-cad", "meshes")
OUT = os.path.join(HERE, "stl")

SOLE_T = 3.5      # TPU under the old sole plane
WALL = 1.8        # side wall, measured from the cavity
UNDERSIZE = 0.35  # cavity is the foot eroded by this much on every face (stretch fit)
LIP = 1.0         # overlap of the lip onto the top face of the foot block
LIP_T = 1.2       # lip height above the top face
BRACKET_CLR = 1.0  # opening clearance around the ankle brackets
CHAMFER = 1.2     # bottom edge
PITCH = 0.25      # voxel pitch of the distance field / marching cubes
BAND = 0.9        # mm, band around the surface with exact distances
SIMPLIFY = 0.02   # mm, merges coplanar triangles of the cavity only within this tolerance
RUBBER_T = 1.8   # glued-on rubber sheet (profile "rubber")
TPU_DENSITY = 1.21e-3  # g/mm3

RIB_W, RIB_PITCH, RIB_D, RIB_EDGE = 2.0, 5.0, 1.0, 4.0
HB_W, HB_PITCH, HB_D, HB_ANGLE = 1.8, 6.0, 1.0, 45.0
NUB = dict(h=1.0, r0=1.7, r1=1.3, pitch=5.5, edge=2.5)     # nub: base radius, tip radius (flat top, 0.4 mm rounded below)
STUD = dict(h=1.6, r0=1.8, r1=0.5, pitch=8.0, edge=3.0)
PROFILES = ("smooth", "ribs", "herringbone", "nubs", "studs", "rubber")


def prism(poly, z0, z1):
    parts = poly.geoms if isinstance(poly, MultiPolygon) else [poly]
    ms = [trimesh.creation.extrude_polygon(p, z1 - z0).apply_translation([0, 0, z0]) for p in parts if not p.is_empty]
    return ms[0] if len(ms) == 1 else trimesh.boolean.union(ms, engine="manifold")


def contour_polygon(img, x0, y0, level=0.0, below=True):
    """Polygon(s) of img<=level (below) or img>=level on the xy grid; img[ix, iy] at (x0+ix*P, y0+iy*P)."""
    a = np.pad(img, 1, constant_values=(level + 1.0) if below else (level - 1.0))
    polys = []
    for c in measure.find_contours(a, level):
        if len(c) < 4:
            continue
        xy = (c - 1) * PITCH + [x0, y0]
        p = Polygon(xy)
        if p.is_valid and p.area > 1.0:
            polys.append(p)
    # find_contours gives closed rings both for outer boundaries and holes: use symmetric difference
    out = Polygon()
    for p in sorted(polys, key=lambda q: -q.area):
        out = out.symmetric_difference(p)
    return out


def foot_sdf(m):
    """Signed distance of the foot mesh (negative inside) on a regular grid. Returns field, mask, (x0, y0, z0)."""
    vg = m.voxelized(PITCH).fill()
    mat = vg.matrix
    org = np.asarray(vg.transform[:3, 3])
    pad = int(round(3.0 / PITCH))
    mask = np.pad(mat, pad)
    o = org - pad * PITCH
    d_in = distance_transform_edt(mask)
    d_out = distance_transform_edt(~mask)
    bv = BAND / PITCH
    band = ((d_in <= bv) & mask) | ((d_out <= bv) & ~mask)
    idx = np.argwhere(band)
    pts = o + idx * PITCH
    sp, fi = trimesh.sample.sample_surface(m, 5_000_000, seed=0)
    d, j = cKDTree(sp).query(pts, workers=-1)
    # the voxel mask is dilated by up to a voxel diagonal: near the surface take the sign from the face normal
    s = np.where(mask[tuple(idx.T)], -1.0, 1.0)
    near = d < 0.6
    n = m.face_normals[fi[j[near]]]
    s[near] = np.where(np.einsum("ij,ij->i", pts[near] - sp[j[near]], n) >= 0, 1.0, -1.0)
    field = np.where(mask, -1.5, 1.5).astype(np.float32)
    field[tuple(idx.T)] = np.clip(s * d, -1.5, 1.5)
    return field, mask, o


def build(side, sole_t=SOLE_T, chamfer=CHAMFER):
    m = trimesh.load(os.path.join(MESHES, f"{side}_ankle_pitch_link_printed.stl"), force="mesh")
    m.vertices = m.vertices * 1000.0
    zmin = m.vertices[:, 2].min()

    field, mask, o = foot_sdf(m)
    nx, ny, nz = field.shape
    zs = o[2] + np.arange(nz) * PITCH

    # top face of the foot block: a (slightly tilted) plane z = a*x + b*y + c, fitted on ray hits in the middle strip
    # between the two ankle brackets
    yc = 0.5 * (m.bounds[0, 1] + m.bounds[1, 1])
    org = np.array([[x, y, zmin + 60] for x in np.arange(-35, 56, 3.0) for y in np.arange(yc - 14, yc + 14, 3.0)])
    hits, _, _ = m.ray.intersects_location(org, np.tile([0, 0, -1.0], (len(org), 1)), multiple_hits=False)
    A = np.c_[hits[:, 0], hits[:, 1], np.ones(len(hits))]
    pa, pb, pc = np.linalg.lstsq(A, hits[:, 2], rcond=None)[0]
    X, Y, Z = np.meshgrid(o[0] + np.arange(nx) * PITCH, o[1] + np.arange(ny) * PITCH, zs, indexing="ij")
    plane = ((Z - (pa * X + pb * Y + pc)) / np.sqrt(1 + pa**2 + pb**2)).astype(np.float32)
    corners = np.array([[x, y] for x in (m.bounds[0, 0], m.bounds[1, 0]) for y in (m.bounds[0, 1], m.bounds[1, 1])])
    ztop_c = pa * corners[:, 0] + pb * corners[:, 1] + pc
    ztop, ztop_hi = ztop_c.min(), ztop_c.max()

    # the foot block = foot below its top face
    block = np.maximum(field, plane)
    del X, Y, Z

    # outside: vertical extrusion of the silhouette (+wall), flat bottom SOLE_T below the old sole plane
    sil = contour_polygon(block.min(axis=2), o[0], o[1])
    outer_fp = sil.buffer(WALL - UNDERSIZE)
    z_floor = zmin - sole_t
    z_top_body = ztop_hi + LIP_T
    if chamfer > 0:
        lower = prism(outer_fp.buffer(-chamfer), z_floor, z_floor + chamfer * 0.5)
        mid = prism(outer_fp, z_floor + chamfer * 0.5, z_top_body)
        body = trimesh.boolean.union([lower, mid], engine="manifold")
    else:
        body = prism(outer_fp, z_floor, z_top_body)

    # cavity = true negative (foot eroded by UNDERSIZE)
    v, f, _, _ = measure.marching_cubes(block, level=-UNDERSIZE, spacing=(PITCH,) * 3)
    v = v + o
    cav = mf.Manifold(mf.Mesh(vert_properties=v.astype(np.float32), tri_verts=f.astype(np.uint32))).simplify(SIMPLIFY)
    cm = cav.to_mesh()
    cavity = trimesh.Trimesh(cm.vert_properties[:, :3].astype(float), cm.tri_verts, process=True)

    # opening: top-face outline shrunk by LIP (lip stays) + clearance around the brackets
    k0, k1 = int(round((ztop - 2.0 - o[2]) / PITCH)), int(round((ztop - 0.5 - o[2]) / PITCH))
    top_fp = contour_polygon(block[:, :, k0:k1].min(axis=2), o[0], o[1])
    kb = int(round((ztop_hi + 3.0 - o[2]) / PITCH))
    bracket_fp = contour_polygon(np.where(mask[:, :, kb], -1.0, 1.0).astype(float), o[0], o[1])
    opening_fp = unary_union([top_fp.buffer(-LIP), bracket_fp.buffer(BRACKET_CLR)])
    opening = prism(opening_fp, ztop - 2.0, z_top_body + 1.0)

    shoe = trimesh.boolean.difference([body, cavity, opening], engine="manifold")
    return shoe, m, outer_fp


def sole_outline(shoe, z_floor):
    """Outline of the shoe a little above the bottom chamfer (shapely polygon, link xy)."""
    sec = shoe.section(plane_origin=[0, 0, z_floor + 2.0], plane_normal=[0, 0, 1])
    path, to3d = sec.to_2D()
    polys = unary_union([Polygon(p.exterior) for p in path.polygons_full])
    pts = np.array(polys.exterior.coords if polys.geom_type == "Polygon" else max(polys.geoms, key=lambda g: g.area).exterior.coords)
    pts = trimesh.transform_points(np.c_[pts, np.zeros(len(pts)), ], to3d)[:, :2]
    return Polygon(pts)


def groove_cuts(shoe, z_floor, kind):
    yc = shoe.bounds.mean(axis=0)[1]; yw = shoe.extents[1] / 2 - 1.0
    cuts = []
    if kind == "ribs":
        for x in np.arange(shoe.bounds[0, 0] + RIB_EDGE + RIB_W / 2, shoe.bounds[1, 0] - RIB_EDGE, RIB_PITCH):
            cuts.append(trimesh.creation.box([RIB_W, shoe.extents[1] + 4.0, RIB_D + 1.0])
                        .apply_translation([x, yc, z_floor + (RIB_D - 1.0) / 2]))
    else:  # herringbone: two bars per chevron, apex on the centre line, opening towards -x
        ang = np.radians(HB_ANGLE); L = yw / np.sin(ang)
        for x in np.arange(shoe.bounds[0, 0] + yw / np.tan(ang) + 4.0, shoe.bounds[1, 0] - 3.0, HB_PITCH):
            for sg in (1, -1):
                bar = trimesh.creation.box([L + 1.0, HB_W, HB_D + 1.0])
                bar.apply_translation([-(L + 1.0) / 2 + 0.5, 0, 0])             # one end at the apex, running to -x
                bar.apply_transform(trimesh.transformations.rotation_matrix(sg * ang, [0, 0, 1]))
                bar.apply_translation([x, yc, z_floor + (HB_D - 1.0) / 2])
                cuts.append(bar)
    return cuts


def raised_contacts(shoe, z_floor, cfg, tip_round):
    """Cut the whole underside back by cfg['h'] and stand hex-gridded cones/nubs on it, tips on the old sole plane."""
    outline = sole_outline(shoe, z_floor)
    h = cfg["h"]
    base = trimesh.boolean.difference([shoe, prism(outline.buffer(1.0), z_floor - 1.0, z_floor + h)], engine="manifold")
    area = outline.buffer(-cfg["edge"])
    x0, y0, x1, y1 = area.bounds; P = cfg["pitch"]
    prof = [[0, -0.05], [cfg["r0"], -0.05], [cfg["r0"], 0], [cfg["r1"], h - tip_round], [cfg["r1"] - tip_round * 0.6, h], [0, h]]
    cone = trimesh.creation.revolve(np.array(prof), sections=28)       # z 0..h, base at the bottom: flip so the tip is down
    cone.apply_transform(trimesh.transformations.rotation_matrix(np.pi, [1, 0, 0]))
    parts = [base]; n = 0
    from shapely.geometry import Point
    for j, y in enumerate(np.arange(y0, y1 + P, P * np.sqrt(3) / 2)):
        for x in np.arange(x0 + (P / 2 if j % 2 else 0), x1 + P, P):
            if area.contains(Point(x, y)):
                parts.append(cone.copy().apply_translation([x, y, z_floor + h])); n += 1   # 0.05 mm overlap into the base is in the profile
    return trimesh.boolean.union(parts, engine="manifold"), n


def apply_profile(shoe, profile, z_floor):
    """Returns (shoe_variant, number_of_contacts or None)."""
    if profile == "smooth":
        return shoe, None
    if profile in ("ribs", "herringbone"):
        cuts = groove_cuts(shoe, z_floor, profile)
        return trimesh.boolean.difference([shoe] + cuts, engine="manifold"), len(cuts)
    cfg, rnd = (NUB, 0.4) if profile == "nubs" else (STUD, 0.0)
    return raised_contacts(shoe, z_floor, cfg, rnd)


def rubber_template(outlines, path, margin=2.0):
    """A4 PDF, 1:1: underside outline of both shoes seen from BELOW (= looking at the tread of the rubber), toe up.
    Solid line = cut line (flush with the TPU wall), dashed = +margin for cut-oversize-glue-trim."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    W, H = 210.0, 297.0
    fig = plt.figure(figsize=(W / 25.4, H / 25.4))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W); ax.set_ylim(0, H); ax.set_aspect("equal"); ax.axis("off")
    # seen from below with the toe (+x) up: page_x = +y (robot left is on the right of the page), page_y = x
    for (side, poly), cx in zip(outlines.items(), (W * 0.27, W * 0.73)):
        b = poly.bounds
        dx, dy = cx - 0.5 * (b[1] + b[3]), 175.0 - 0.5 * (b[0] + b[2])
        for p, ls, lw in ((poly, "-", 0.5), (poly.buffer(margin, join_style=2), (0, (3, 2)), 0.3)):
            x, y = np.asarray(p.exterior.coords).T
            ax.plot(y + dx, x + dy, color="k", ls=ls, lw=lw)
        ax.annotate("", xy=(cx, 175 + 0.5 * (b[2] - b[0]) + 14), xytext=(cx, 175 + 0.5 * (b[2] - b[0]) + 4),
                    arrowprops=dict(arrowstyle="->", lw=0.8))
        ax.text(cx, 175 + 0.5 * (b[2] - b[0]) + 16, "Spitze", ha="center", va="bottom", fontsize=8)
        name = {"left": "LINKS", "right": "RECHTS"}[side]
        ax.text(cx, 175 - 0.5 * (b[2] - b[0]) - 8, f"{name}\n{b[2] - b[0]:.1f} x {b[3] - b[1]:.1f} mm",
                ha="center", va="top", fontsize=9, weight="bold")
    for x0, y0, horiz in ((20, 60, True), (190, 20, False)):     # scale check: 100 mm each way
        x1, y1 = (x0 + 100, y0) if horiz else (x0, y0 + 100)
        ax.plot([x0, x1], [y0, y1], color="k", lw=0.8)
        for t in range(0, 101, 10):
            px, py = (x0 + t, y0) if horiz else (x0, y0 + t)
            k = 3 if t % 50 == 0 else 1.5
            ax.plot([px, px] if horiz else [px - k, px], [py, py + k] if horiz else [py, py], color="k", lw=0.5)
    ax.text(70, 55, "100 mm  (nachmessen!)", ha="center", va="top", fontsize=8)
    ax.text(186, 70, "100 mm", ha="right", va="center", fontsize=8, rotation=90)
    ax.text(20, 45, "Gummi-Schablone TPU-Überschuh (Profil rubber, Gummi %.1f mm)\n"
            "Drucken mit 100 %% / Tatsächliche Größe, nicht \"An Seite anpassen\". Maßstäbe prüfen.\n"
            "Ansicht von UNTEN: Lauffläche (glatte Seite) des Gummis nach oben, Schablone darauf.\n"
            "Raue Seite = Klebeseite zur TPU-Sohle.\n"
            "Durchgezogen: Schnittlinie (bündig mit der Wand).  Gestrichelt: +%.0f mm zum Übermaß-Schneiden,\n"
            "dann aufkleben und mit dem Cutter an der TPU-Kante bündig beschneiden (genauer)." % (RUBBER_T, margin),
            ha="left", va="top", fontsize=7.5, linespacing=1.5)
    fig.savefig(path)
    plt.close(fig)


def main():
    import sys
    os.makedirs(OUT, exist_ok=True)
    only = sys.argv[1:] or list(PROFILES)
    outlines = {}
    for side in ("left", "right"):
        if "rubber" in only:
            shoe, foot, fp = build(side, SOLE_T - RUBBER_T, 0.0)
            out = os.path.join(OUT, f"foot_sole_{side}_rubber.stl")
            shoe.export(out)
            outlines[side] = max(fp.geoms, key=lambda g: g.area) if isinstance(fp, MultiPolygon) else fp
            print(f"{side} rubber: watertight={shoe.is_watertight} vol={shoe.volume:.0f} mm3 "
                  f"mass~{shoe.volume * TPU_DENSITY:.1f} g (solid) bottom z={shoe.bounds[0, 2]:.2f} "
                  f"(+{RUBBER_T} mm rubber) -> {out}")
        if not [p for p in only if p != "rubber"]:
            continue
        shoe, foot, _ = build(side)
        z_floor = foot.vertices[:, 2].min() - SOLE_T
        for prof in [p for p in only if p != "rubber"]:
            var, n = apply_profile(shoe, prof, z_floor)
            out = os.path.join(OUT, f"foot_sole_{side}.stl" if prof == "smooth" else f"foot_sole_{side}_{prof}.stl")
            var.export(out)
            print(f"{side} {prof}: watertight={var.is_watertight} n={n} vol={var.volume:.0f} mm3 "
                  f"mass~{var.volume * TPU_DENSITY:.1f} g (solid) bottom z={var.bounds[0, 2]:.2f} -> {out}")
    if outlines:
        pdf = os.path.join(HERE, "print", "rubber_template_A4.pdf")
        rubber_template(outlines, pdf)
        print("wrote", pdf)


if __name__ == "__main__":
    main()
