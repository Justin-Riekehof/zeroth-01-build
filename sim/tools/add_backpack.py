#!/usr/bin/env python3
"""Derive sim/assets/zbot-pixel-backpack from sim/assets/zbot-pixel: adds the printed backpack v3.1
(hardware/backpack_v2) as a torso-fixed body with an educated-guess mass model, and removes the
original electronics mass (battery, MilkV, old backpack) from the torso link.

Frame mapping (derived from joint anchors + the torso mesh, see hardware/backpack_v2/README.md):
the OnShape assembly frame used for the backpack (X left, Y back, Z up, mm) maps onto the
Z_BOT2_MASTER_BODY_SKELETON body frame as  local = CAD + (0, 8.2, -372.6) mm  (axes coincide).

Usage: python sim/tools/add_backpack.py   (needs numpy; mujoco optional for the self-check)
"""
import json, os, re, shutil, sys
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC = os.path.join(ROOT, "sim", "assets", "zbot-pixel")
DST = os.path.join(ROOT, "sim", "assets", "zbot-pixel-backpack")
STL = os.path.join(ROOT, "hardware", "backpack_v2", "stl_v3")
CAD_TO_BODY_MM = np.array([0.0, 8.2, -372.6])

# educated-guess mass model of the mounted backpack v3.1 (grams, CAD frame mm, box dims mm) -----------------------
ITEMS = [  # name, mass g, centre (x,y,z), box (dx,dy,dz)
    ("base frame PETG",     240, (-2.7, 59.5, 332.7), (160, 67, 162)),   # v4: zwei Lagen, 69 mm tief
    ("lid PETG",             71, (-4.6, 104.5, 333.2), (160, 19, 162)),
        ("LiPo 3S 2200",        200, (-23.5, 57.6, 275.5), (106, 25, 34)),
    ("XY-CD63 cutoff",       60, (0.0, 58.0, 368.0), (62, 28, 56)),
    ("Waveshare adapter",    15, (-6.0, 53.0, 320.5), (42, 20, 33)),
    ("anti-spark switch",    20, (-61.0, 80.6, 358.5), (22, 15, 45)),
    ("fuse cable",           25, (-27.0, 80.0, 266.5), (40, 15, 15)),
    ("LiPo warner",          10, (59.5, 80.0, 310.0), (35, 14, 22)),
    ("Pololu buck",           5, (66.0, 47.0, 362.0), (18, 9, 20)),
    ("Raspberry Pi 4B",      46, (-18.0, 52.0, 342.5), (56, 20, 85)),   # v4: im Rucksack, vordere Lage
    ("cables + connectors",  60, (0.0, 60.0, 330.0), (150, 40, 140)),
]
TORSO_MASS_REMOVED_KG = 0.40   # original 5.2 Ah pack (~0.33), MilkV + hat, speaker, old backpack + Waveshare

def mass_model():
    m = np.array([i[1] for i in ITEMS]) / 1000.0
    c = np.array([i[2] for i in ITEMS]) / 1000.0
    d = np.array([i[3] for i in ITEMS]) / 1000.0
    M = m.sum(); com = (m[:, None] * c).sum(0) / M
    I = np.zeros((3, 3))
    for mi, ci, di in zip(m, c, d):
        Ib = mi / 12.0 * np.diag([di[1]**2 + di[2]**2, di[0]**2 + di[2]**2, di[0]**2 + di[1]**2])
        r = ci - com; I += Ib + mi * (np.dot(r, r) * np.eye(3) - np.outer(r, r))
    return M, com, I

def main():
    M, com, I = mass_model()
    print(f"backpack mass {M*1000:.0f} g, CoM (CAD mm) {np.round(com*1000,1)}, inertia diag {np.round(np.diag(I)*1e6,0)} g mm2")
    if os.path.exists(DST): shutil.rmtree(DST)
    os.makedirs(os.path.join(DST, "meshes"))
    for f in os.listdir(os.path.join(SRC, "meshes")): shutil.copy(os.path.join(SRC, "meshes", f), os.path.join(DST, "meshes", f))
    shutil.copytree(os.path.join(SRC, "actuators"), os.path.join(DST, "actuators"))
    shutil.copy(os.path.join(SRC, "metadata.json"), os.path.join(DST, "metadata.json"))
    for part in ("base", "lid", "insert"):
        shutil.copy(os.path.join(STL, f"backpack_v3_{part}_robotframe.stl"), os.path.join(DST, "meshes", f"backpack_{part}.stl"))
    mj = open(os.path.join(SRC, "robot.mjcf")).read()
    # 1) assets
    assets = ''.join(f'    <mesh name="backpack_{p}.stl" file="meshes/backpack_{p}.stl" scale="0.001 0.001 0.001" />\n' for p in ("base", "lid", "insert"))
    mats = ('    <material name="backpack_base_material" rgba="0.19 0.44 0.84 1" />\n'
            '    <material name="backpack_lid_material" rgba="0.50 0.70 0.35 1" />\n'
            '    <material name="backpack_insert_material" rgba="0.78 0.63 0.23 1" />\n')
    mj = mj.replace("  </asset>", mats + assets + "  </asset>", 1)
    # 2) torso link: remove the original electronics mass (scale inertia with it)
    m_old = re.search(r'<body name="Z_BOT2_MASTER_BODY_SKELETON"[^>]*>\s*<inertial pos="([^"]+)" mass="([^"]+)" diaginertia="([^"]+)" />', mj)
    pos_s, mass_s, di_s = m_old.groups(); mass_old = float(mass_s); mass_new = mass_old - TORSO_MASS_REMOVED_KG
    di_new = " ".join(f"{float(v) * mass_new / mass_old:.6f}" for v in di_s.split())
    mj = mj.replace(f'<inertial pos="{pos_s}" mass="{mass_s}" diaginertia="{di_s}" />',
                    f'<inertial pos="{pos_s}" mass="{mass_new:.6f}" diaginertia="{di_new}" />', 1)
    # 3) backpack body as first child of the torso link (frame = CAD frame in metres)
    off = CAD_TO_BODY_MM / 1000.0
    Ixx, Iyy, Izz, Ixy, Ixz, Iyz = I[0, 0], I[1, 1], I[2, 2], I[0, 1], I[0, 2], I[1, 2]
    body = (f'        <body name="backpack" pos="{off[0]:.4f} {off[1]:.4f} {off[2]:.4f}">\n'
            f'          <!-- backpack v3.1 (hardware/backpack_v2): {M*1000:.0f} g educated guess, CoM/inertia from sim/tools/add_backpack.py -->\n'
            f'          <inertial pos="{com[0]:.5f} {com[1]:.5f} {com[2]:.5f}" mass="{M:.4f}" fullinertia="{Ixx:.3e} {Iyy:.3e} {Izz:.3e} {Ixy:.3e} {Ixz:.3e} {Iyz:.3e}" />\n'
            f'          <geom name="backpack_base_visual" material="backpack_base_material" type="mesh" mesh="backpack_base.stl" class="visual" />\n'
            f'          <geom name="backpack_lid_visual" material="backpack_lid_material" type="mesh" mesh="backpack_lid.stl" class="visual" />\n'
            f'          <geom name="backpack_insert_visual" material="backpack_insert_material" type="mesh" mesh="backpack_insert.stl" class="visual" />\n'
            f'        </body>\n')
    anchor = '        <body name="IMU_2"'
    assert anchor in mj; mj = mj.replace(anchor, body + anchor, 1)
    mj = mj.replace('<mujoco model="z-bot2_fe_urdf">', '<mujoco model="z-bot2_pixel_backpack">', 1)
    mj = mj.replace("<!-- GENERATED FILE - do not hand-edit.", "<!-- GENERATED FILE - do not hand-edit (sim/tools/add_backpack.py on top of zbot-pixel).", 1)
    open(os.path.join(DST, "robot.mjcf"), "w").write(mj)
    json.dump(dict(items=[dict(name=n, mass_g=m, com_cad_mm=list(c), box_mm=list(d)) for n, m, c, d in ITEMS],
                   total_mass_kg=round(M, 4), com_cad_mm=[round(v * 1000, 1) for v in com], torso_mass_removed_kg=TORSO_MASS_REMOVED_KG,
                   cad_to_body_mm=list(CAD_TO_BODY_MM)), open(os.path.join(DST, "backpack_mass_model.json"), "w"), indent=1)
    print("written", DST, f"torso link mass {mass_old:.3f} -> {mass_new:.3f} kg")

if __name__ == "__main__":
    main()
