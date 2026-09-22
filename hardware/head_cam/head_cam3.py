#!/usr/bin/env python3
"""Zeroth-01 head, right eye: Raspberry Pi Camera Module 3 (standard lens, 75 deg) instead of the Milk camera.

Head shell ("Head" in the pinned CAD): the round right eye opening (dia ~36) in the 2.5 mm face wall is closed by a
plug in wall thickness with a dia 9 lens aperture (chamfered at the front) and four M2 bosses on its inner side in the
camera's hole pattern. The camera sits between face wall and back plate; the back plate ("Neck Mount") stays as it is
(the camera ends ~8 mm in front of the old Milk-camera bracket). The ribbon leaves the camera downwards directly behind
the board, runs along the head floor in front of the back plate and exits through the neck opening (x -8..8).

Source of the head shell: the "Head" of resources/cad/z001-opus-m-93de7567.glb (the printed version; the IMU slots in
the back plate match exactly): shell + front face primitive merged into one closed solid, unchanged geometry.
Camera: parametric from Raspberry Pi's STEP / drawings (datasheets.raspberrypi.com/camera/camera-module-3-step.zip),
lens housing position as measured by the user (housing 4.5 mm from the ribbon edge; the STEP has 4.06).

Camera frame (= Raspberry Pi STEP frame, mm): X along the 23.862 edge (0 = top edge, 23.862 = ribbon edge),
Y along the 25 edge, lens towards -Z, back side (ribbon connector J1) +Z; PCB front face z -0.744, back +0.013.
Mounted: ribbon edge down, lens forward (-Y), 66 deg horizontal FOV horizontal.
Usage: .cad/bin/python hardware/head_cam/head_cam3.py   (needs cadquery, trimesh, manifold3d)
"""
from __future__ import annotations
import json, os, re
import numpy as np
import cadquery as cq
import trimesh
from scipy.spatial import cKDTree

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
GLB = os.path.join(REPO, "resources", "cad", "z001-opus-m-93de7567.glb")
OUT = os.path.join(HERE, "stl"); OUT_RF = os.path.join(OUT, "robotframe"); OUT_PRINT = os.path.join(HERE, "print")

# ---------------- camera (Raspberry Pi STEP + drawing; [M] = measured by the user) ----------------
BRD_X, BRD_Y, BRD_R = 23.862, 25.0, 2.0
Z_PCB_FRONT, Z_PCB_BACK = -0.744, 0.013            # STEP; the drawing says 1.12 thick - irrelevant, the board sits on its front face
HOLES = [(2.0, 2.0), (2.0, 23.0), (14.5, 2.0), (14.5, 23.0)]; D_HOLE = 2.2
HOUSING = 10.8
HOUSING_TO_EDGE = 4.5                              # [M] lens housing to the ribbon edge (STEP: 4.06)
AX_X, AX_Y = BRD_X - HOUSING_TO_EDGE - HOUSING / 2, BRD_Y / 2   # optical axis 13.96 / 12.5
Z_MODULE, Z_HOUSING_FRONT = -1.73, -5.55           # sensor module on J2 (0.98 above the PCB), housing front
Z_COLLAR, Z_CONE, Z_LENS = -5.75, -6.55, -7.65     # collar dia 8.15, cone to 5.8, lens front (focus infinity)
AF_TRAVEL = 0.24                                   # autofocus: barrel moves out by 0.24 at 10 cm
J1 = dict(x=(17.58, 23.49), y=(1.04, 23.96), z=(Z_PCB_BACK, 2.595))   # ribbon connector (back side)
FPC_W, FPC_T, FPC_Z = 16.0, 0.3, 1.3               # ribbon: 16 wide, leaves across the X = 23.862 edge ~1.3 behind the board
FOV_H, FOV_V = 66.0, 41.0                          # deg: horizontal along Y, vertical along X
CLEAR_AP = 3.77

# ---------------- head (pinned CAD, assembly frame mm: +X robot left, +Y back, +Z up) ----------------
Y_FACE_FRONT, Y_FACE_BACK = -19.86, -17.36         # face wall of the head shell
EYE_R_FILL = 18.8                                  # plug radius (the 10-gon opening has circumradius ~18.3)
LENS_BEHIND_FACE = 1.0                             # lens front 1 mm behind the face front
D_APERTURE, C_APERTURE = 9.0, 0.8                  # lens aperture in the plug + 45 deg chamfer at the front
D_BOSS, D_PILOT, PILOT_INTO_WALL = 4.5, 1.9, 1.2   # M2 bosses, bore 1.9 [Vorgabe] (pad keep-out on the board is dia 4.75)
# left eye (IMU display): the GLB has the round opening only as a 12-gon (35.35 across flats) -> re-cut it round, plus a
# recess for the USB tab of the RP2040-LCD-1.28 so the display can sit in the opening (tab points to the head centre, -X)
IMU_POSE = os.path.join(REPO, "hardware", "head_imu", "imu_pose.json")   # written by hardware/head_imu/rp2040_lcd_128.py
_t = json.load(open(IMU_POSE))["t_module_to_robot_mm"]
EYE_L = (_t[0], _t[2])                                   # opening centred on the IMU board (0.1 mm from the CAD eye centre)
R_OPEN, R_OPEN_FRONT, C_OPEN = 18.5, 18.9, 0.5         # dia 37.0 (CAD 36.6; board dia 36.5, display 35.6), front chamfer as in the CAD
TAB_TRAPEZ = [(-9.19, 15.77), (9.19, 15.77), (6.40, 21.25), (-6.40, 21.25)]   # Waveshare drawing: (across, radial) from the board centre
TAB_W_M, TAB_DEPTH_M, R_DISPLAY = 16.0, 4.0, 17.8      # [M] tab 16 wide, 4 beyond the display edge; display radius ~17.6-17.8
TAB_CLEAR = 0.5
# camera ribbon route (2026-09-19): straight back instead of through the neck. It leaves J1 downwards, runs FPC_LEAD straight,
# bends with FPC_BEND_R to horizontal (+Y) and goes through an 18 mm slot in the head back plate (neck_mount_imu.py) and the
# same slot, projected, in the backpack base plate (backpack_v4.py) - the backpack top (z 416) overlaps the head in height.
FPC_LEAD, FPC_BEND_R, CABLE_SLOT_W, CABLE_SLOT_H = 2.0, 4.0, 18.0, 3.0
FPC_END_Y = 50.0                                     # ribbon drawn up into the backpack front layer
R_CAM = np.array([[0.0, -1.0, 0.0],               # camera X -> -Z (ribbon edge down), Y -> -X, Z -> +Y (lens forward = -Y)
                  [0.0, 0.0, 1.0],
                  [-1.0, 0.0, 0.0]])


def head_shell():
    """the 'Head' of the pinned GLB = two primitives: the shell (open at the front) and the flat front face of the face
    wall (y -19.86, with both eye holes). Together they form a closed solid - no mesh repair needed."""
    sc = trimesh.load(GLB, force="scene"); g = sc.graph; prims = []
    for n in g.nodes_geometry:
        if n.split("_")[0] != "Head": continue
        T, gn = g.get(n); m = sc.geometry[gn].copy(); m.apply_transform(T); m.apply_scale(1000.0); prims.append(m)
    head = trimesh.util.concatenate(prims)
    V = head.vertices.copy()                                       # weld the two primitives: snap vertices < 1 um apart
    for i, j in sorted(cKDTree(V).query_pairs(1e-3)): V[j] = V[i]
    head = trimesh.Trimesh(V, head.faces, process=True); head.merge_vertices(digits_vertex=6)
    trimesh.repair.fix_winding(head); trimesh.repair.fix_inversion(head)
    assert len(prims) == 2 and head.is_watertight and head.body_count == 1 and head.volume > 0, (len(prims), head.is_watertight)
    return head


def eye_centre(head):
    """centre of the right eye opening: mean of the opening's section points in the middle of the face wall"""
    seg = trimesh.intersections.mesh_plane(head, [0, 1, 0], [0, (Y_FACE_FRONT + Y_FACE_BACK) / 2, 0]).reshape(-1, 3)
    near = seg[(seg[:, 0] < -5) & (seg[:, 0] > -50) & (seg[:, 2] > 402) & (seg[:, 2] < 446)]
    r = np.hypot(near[:, 0] + 27.5, near[:, 2] - 424.0); ring = near[r < 22]
    return np.array([(ring[:, 0].min() + ring[:, 0].max()) / 2, (ring[:, 2].min() + ring[:, 2].max()) / 2])


def placement(eye):
    """camera frame -> robot frame: optical axis on the eye centre, lens front 1 mm behind the face front"""
    t = np.array([eye[0] + AX_Y, (Y_FACE_FRONT + LENS_BEHIND_FACE) - Z_LENS, eye[1] + AX_X])
    T = np.eye(4); T[:3, :3] = R_CAM; T[:3, 3] = t
    return T


def to_rf(T, p):
    return np.asarray(p) @ T[:3, :3].T + T[:3, 3]


def cyl_y(x, z, y0, y1, d):
    return cq.Workplane("XY").add(cq.Solid.makeCylinder(d / 2, y1 - y0, cq.Vector(x, y0, z), cq.Vector(0, 1, 0)))


def tm(wp):
    v, f = wp.val().tessellate(0.01, 0.1)
    return trimesh.Trimesh([(p.x, p.y, p.z) for p in v], f, process=True)


def camera_parts():
    """parametric Camera Module 3 in its own frame"""
    def box(x0, x1, y0, y1, z0, z1): return cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0, centered=False).translate((x0, y0, z0))
    board = box(0, BRD_X, 0, BRD_Y, Z_PCB_FRONT, Z_PCB_BACK).edges("|Z").fillet(BRD_R)
    for (x, y) in HOLES: board = board.cut(cq.Workplane("XY").add(cq.Solid.makeCylinder(D_HOLE / 2, 2, cq.Vector(x, y, -1.5), cq.Vector(0, 0, 1))))
    hx0 = AX_X - HOUSING / 2
    module = (box(1.7, hx0 + 0.5, 9.35, 18.25, Z_MODULE, Z_PCB_FRONT)                               # flex tail + J2
              .union(box(hx0, hx0 + HOUSING, AX_Y - HOUSING / 2, AX_Y + HOUSING / 2, Z_HOUSING_FRONT, Z_PCB_FRONT)))
    ax = cq.Vector(AX_X, AX_Y, 0)
    barrel = (cq.Workplane("XY").add(cq.Solid.makeCylinder(8.15 / 2, Z_HOUSING_FRONT - Z_COLLAR, ax + cq.Vector(0, 0, Z_COLLAR), cq.Vector(0, 0, 1)))
              .union(cq.Workplane("XY").add(cq.Solid.makeCone(5.8 / 2, 8.15 / 2, Z_COLLAR - Z_CONE, ax + cq.Vector(0, 0, Z_CONE), cq.Vector(0, 0, 1))))
              .union(cq.Workplane("XY").add(cq.Solid.makeCylinder(5.75 / 2, Z_CONE - Z_LENS, ax + cq.Vector(0, 0, Z_LENS), cq.Vector(0, 0, 1)))))
    j1 = box(J1["x"][0], J1["x"][1], J1["y"][0], J1["y"][1], J1["z"][0], J1["z"][1])
    return {"cam3_board": board, "cam3_module": module.union(barrel), "cam3_j1": j1}


def head_features(T):
    """plug, aperture and bosses in the robot frame (cadquery)"""
    ax = to_rf(T, [AX_X, AX_Y, 0.0]); ex, ez = ax[0], ax[2]
    y_pcb = to_rf(T, [0, 0, Z_PCB_FRONT])[1]
    plug = cyl_y(ex, ez, Y_FACE_FRONT, Y_FACE_BACK, 2 * EYE_R_FILL)
    bosses, pilots, hole_rf = [], [], []
    for (hx, hy) in HOLES:
        p = to_rf(T, [hx, hy, 0.0]); hole_rf.append([round(p[0], 3), round(p[2], 3)])
        bosses.append(cyl_y(p[0], p[2], Y_FACE_BACK - 0.5, y_pcb, D_BOSS))
        pilots.append(cyl_y(p[0], p[2], Y_FACE_BACK - PILOT_INTO_WALL, y_pcb + 0.5, D_PILOT))
    aperture = cyl_y(ex, ez, Y_FACE_FRONT - 1.0, Y_FACE_BACK + 1.0, D_APERTURE).union(
        cq.Workplane("XY").add(cq.Solid.makeCone(D_APERTURE / 2 + C_APERTURE + 0.5, D_APERTURE / 2, C_APERTURE + 0.5,
                                                 cq.Vector(ex, Y_FACE_FRONT - 0.5, ez), cq.Vector(0, 1, 0))))
    return plug, bosses, pilots, aperture, hole_rf, float(y_pcb)


def left_eye_tool():
    """cut tool for the left eye: round opening + front chamfer + USB-tab recess (drawing trapezoid and measured 16 x 4, +0.5)"""
    cx, cz = EYE_L; y0, y1 = Y_FACE_FRONT - 1.0, Y_FACE_BACK + 1.0
    tool = cyl_y(cx, cz, y0, y1, 2 * R_OPEN)
    k = (R_OPEN_FRONT - R_OPEN) / C_OPEN                   # chamfer slope, cone extended 1 mm in front of the face
    tool = tool.union(cq.Workplane("XY").add(cq.Solid.makeCone(R_OPEN_FRONT + k * 1.0, R_OPEN, C_OPEN + 1.0,
                                                             cq.Vector(cx, Y_FACE_FRONT - 1.0, cz), cq.Vector(0, 1, 0))))
    tip = max(TAB_TRAPEZ[2][1], R_DISPLAY + TAB_DEPTH_M) + TAB_CLEAR
    pl = cq.Plane(origin=(cx, y0, cz), xDir=(0, 0, -1), normal=(0, 1, 0))  # local x = robot -Z (across), local y = robot -X (radial)
    trap = cq.Workplane(pl).polyline(TAB_TRAPEZ).close().offset2D(TAB_CLEAR).extrude(y1 - y0)
    rect = cq.Workplane(pl).center(0, (15.0 + tip) / 2).rect(TAB_W_M + 2 * TAB_CLEAR, tip - 15.0).extrude(y1 - y0)
    return tool.union(trap).union(rect), tip


def ribbon(T):
    """camera ribbon (16 x 0.3) in the robot frame: J1 -> down FPC_LEAD -> bend R -> straight back (+Y); returns mesh + slot data"""
    xc = float(to_rf(T, [AX_X, AX_Y, 0.0])[0]); y0 = float(to_rf(T, [0, 0, FPC_Z])[1]); z0 = float(to_rf(T, [BRD_X, 0, 0])[2])
    z1 = z0 - FPC_LEAD; R = FPC_BEND_R; zh = z1 - R
    path = [(y0, z0), (y0, z1)] + [(y0 + R - R * np.cos(a), z1 - R * np.sin(a)) for a in np.linspace(0, np.pi / 2, 10)[1:]] + [(FPC_END_Y, zh)]
    parts = []
    for (ya, za), (yb, zb) in zip(path[:-1], path[1:]):
        L = np.hypot(yb - ya, zb - za)
        if L < 1e-6: continue
        b = trimesh.creation.box(extents=[FPC_W, FPC_T, L + 0.05])
        ang = np.arctan2(-(yb - ya), zb - za)                     # rotation about x taking the box axis (0,0,1) to (0, dy, dz)/L
        Rm = trimesh.transformations.rotation_matrix(ang, [1, 0, 0]); b.apply_transform(Rm)
        b.apply_translation([xc, (ya + yb) / 2, (za + zb) / 2]); parts.append(b)
    slot = dict(x=[round(xc - CABLE_SLOT_W / 2, 3), round(xc + CABLE_SLOT_W / 2, 3)], z=[round(zh - CABLE_SLOT_H / 2, 3), round(zh + CABLE_SLOT_H / 2, 3)],
                ribbon_z=round(zh, 3), bend_radius=R, lead=FPC_LEAD)
    return trimesh.util.concatenate(parts), slot


def fov_frustum(T, depth=35.0):
    """view frustum from the lens front (clear aperture) forward, in the camera frame -> robot frame"""
    h, v = np.tan(np.radians(FOV_H / 2)), np.tan(np.radians(FOV_V / 2)); a = CLEAR_AP / 2
    z0 = Z_LENS - AF_TRAVEL; pts = []
    for d in (0.0, depth):
        for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            pts.append([AX_X + sx * (a + d * v), AX_Y + sy * (a + d * h), z0 - d])
    return trimesh.convex.convex_hull(to_rf(T, pts))


def main():
    for d in (OUT_RF, OUT_PRINT): os.makedirs(d, exist_ok=True)
    head = head_shell()
    eye = eye_centre(head); T = placement(eye)
    plug, bosses, pilots, aperture, hole_rf, y_pcb = head_features(T)
    add = trimesh.boolean.union([head, tm(plug)] + [tm(b) for b in bosses], engine="manifold")
    ltool, tab_tip = left_eye_tool()
    new = trimesh.boolean.difference([add, tm(aperture), tm(ltool)] + [tm(p) for p in pilots], engine="manifold")
    assert new.is_watertight and new.body_count == 1, (new.is_watertight, new.body_count)
    print(f"head shell: {head.volume/1000:.2f} -> {new.volume/1000:.2f} cm3, watertight, 1 body")
    new.export(os.path.join(OUT_RF, "head_shell_cam3.stl"))
    pr = new.copy(); pr.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))   # face (-Y) down on the bed
    pr.apply_translation(-pr.bounds[0]); pr.export(os.path.join(OUT_PRINT, "head_shell_cam3.stl"))

    parts = {k: tm(v) for k, v in camera_parts().items()}
    for k, m in parts.items(): m.apply_transform(T)
    parts["cam3_fpc"], cable_slot = ribbon(T)
    parts["cam3_fov"] = fov_frustum(T)
    for k, m in parts.items(): m.export(os.path.join(OUT_RF, f"{k}.stl"))

    # checks: camera vs new head (only the screws may touch: the bosses end on the PCB front face), FOV vs head
    clear = {k: float(trimesh.proximity.closest_point(new, m.sample(3000))[1].min()) for k, m in parts.items() if k in ("cam3_module", "cam3_j1", "cam3_fpc")}
    inter = {k: float(trimesh.boolean.intersection([new, m], engine="manifold").volume) for k, m in parts.items() if k not in ("cam3_fov", "cam3_fpc")}
    fov_hit = float(trimesh.boolean.intersection([new, parts["cam3_fov"]], engine="manifold").volume)
    print("overlap with the head shell (mm3):", {k: round(v, 3) for k, v in inter.items()}, "| FOV frustum vs head:", round(fov_hit, 3), "mm3")
    print("min. distance to the head shell (mm):", {k: round(v, 2) for k, v in clear.items()})
    imu_dir = os.path.join(REPO, "hardware", "head_imu", "stl", "robotframe"); imu_chk = {}
    for k in ("lcd_panel", "pcb", "usbc", "hdr_h1", "hdr_h2", "batt", "sw_boot", "sw_reset", "adapter_h1", "adapter_h2"):
        m = trimesh.load(os.path.join(imu_dir, f"imu_{k}.stl"))
        imu_chk[k] = (round(float(trimesh.boolean.intersection([new, m], engine="manifold").volume), 3),
                      round(float(trimesh.proximity.closest_point(new, m.sample(3000))[1].min()), 2))
    print("IMU vs head shell (overlap mm3, min distance mm):", imu_chk)
    info = dict(frame="assembly frame of the pinned CAD (mm): +X robot left, +Y back, +Z up",
                eye_centre_xz=np.round(eye, 3).tolist(), optical_axis_xz=np.round(to_rf(T, [AX_X, AX_Y, 0])[[0, 2]], 3).tolist(),
                lens_front_y=round(Y_FACE_FRONT + LENS_BEHIND_FACE, 3), pcb_front_y=round(y_pcb, 3), boss_holes_xz=hole_rf,
                boss_length_mm=round(y_pcb - Y_FACE_BACK, 2), camera_to_robot=T.round(4).tolist(),
                cable_slot=cable_slot, fov_frustum_vs_head_mm3=round(fov_hit, 3), left_eye=dict(centre_xz=list(EYE_L), opening_dia=2 * R_OPEN,
                front_chamfer_dia=2 * R_OPEN_FRONT, tab_recess_to_radius=round(tab_tip, 2), tab_direction="-X (head centre)",
                imu_vs_head=imu_chk),
                overlap_mm3={k: round(v, 3) for k, v in inter.items()})
    json.dump(info, open(os.path.join(HERE, "cam3_pose.json"), "w"), indent=1)
    print("eye centre", info["eye_centre_xz"], "| PCB front y", info["pcb_front_y"], "| boss length", info["boss_length_mm"], "| holes", hole_rf)
    print("done ->", OUT_RF, OUT_PRINT)


if __name__ == "__main__":
    main()
