#!/usr/bin/env python3
"""Generate sim/assets/zbot-cad/ -- the MuJoCo model of THIS robot, built from the pinned OnShape CAD
(resources/cad/z001-opus-m-93de7567.glb + z001-joints-m-93de7567.json: exactly what the servo WebUI shows)
instead of the upstream K-Scale Z-Bot 2 assets (a different robot: gripper hands, other leg chain).

* Links: FASTENED mates merge parts into rigid links, REVOLUTE mates connect them (the WebUI's pose-rig
  union-find). Original electronics this build does not have (MilkV, hat, battery, old backpack, speaker,
  camera, mic, LCD-IMU display) and screws are dropped.
* Zero pose: the CAD scene pose is not the standing pose. hardware/model_zero_offsets.json (the WebUI's
  display correction that puts the CAD model onto the real robot's servo zero) is applied as forward
  kinematics, so qpos = 0 is the real robot standing straight; hardware/model_invert.json flips the joint
  axis where the real servo turns the other way -> sim joint angle == servo joint angle (in rad).
* Ranges: hardware/joint_limits.json (calibrated per servo; the repo state is the ground truth, even if
  not yet uploaded to the robot).
* Frame: sim x forward, y left, z up (the CAD assembly frame is X left, Y back, Z up); base body at the
  torso centre, feet on the floor.
* Masses: everything that is not printed comes from hardware/mass_model.json (datasheet masses at the
  position the CAD puts them: servos by type, the backpack v4.2 components, cables, the two head modules;
  built by sim/tools/build_mass_model.py). Printed parts from their real mesh volume x 750 kg/m3 (PETG,
  4 walls, 40 % gyroid): the GLB exports are full of T-junction cracks, so sim/tools/meshfix.py stitches
  them closed first -- without that the old half-convex-hull fallback over-estimated hollow shells by 2-3x
  (the head came out 88 g against 30 g of real volume). The robot has still not been weighed -- the
  effective PETG density is the remaining guess.
* IMU: site `imu` at the QMI8658 chip of the head module (hardware/head_imu/imu_pose.json), with the site
  axes rotated onto the real chip axes, so `imu_acc`/`imu_gyro` in the sim are what the real sensor puts on
  the wire. `--imu-frame body` instead aligns the site with the body axes (x forward, y left, z up) -- then
  the Pi has to rotate the raw readings by R_body_from_imu from metadata.json before feeding the policy.
Sensor / site / geom names are the ones sim/train/walking.py expects.
Usage: python sim/tools/build_model_cad.py [--out sim/assets/zbot-cad] [--imu x,y,z] [--imu-frame imu|body]
       [--no-backpack]
"""
from __future__ import annotations
import argparse, collections, json, os, re, shutil, sys
from pathlib import Path
import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parents[2]
GLB = ROOT / "resources/cad/z001-opus-m-93de7567.glb"
JOINTS = ROOT / "resources/cad/z001-joints-m-93de7567.json"
HW = ROOT / "hardware"
SRC_ASSETS = ROOT / "sim/assets/zbot-pixel"           # sys-ID actuator JSONs
BACKPACK_STL = ROOT / "hardware/backpack_v2/stl_v3"   # *_robotframe.stl = CAD assembly frame, mm
BACKPACK_PARTS = ("base", "lid")                      # v4.2 prints; the v3.1 torso insert is gone
MASS_MODEL = HW / "mass_model.json"                   # datasheet masses, built by sim/tools/build_mass_model.py
sys.path.insert(0, str(ROOT))
from sim.tools.meshfix import solid_props  # noqa: E402

EXCLUDE = [r"^milkv", r"^bus_servo_adaptor", r"^backpack", r"^battery", r"^electronics_mount", r"^\[draft\]_speaker",
           r"^milk_camera", r"^mic$", r"^mic_", r"^lcd_imu", r"^hex_socket", r"^chamfered",
           r"^eye_mount"]   # the K-Scale eye mount is not in this build either: the head module sits on the ridges
                            # of the reworked neck mount (hardware/head_imu), the right eye carries the camera
MASS = json.load(open(MASS_MODEL))
SERVO_MASS = {k: v / 1000.0 for k, v in MASS["servo_mass_g"].items()}
PETG_DENSITY = float(MASS["petg_density_kg_m3"])
R_SIM = np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])   # CAD -> sim
LEG_JOINTS = ("hip_pitch", "hip_yaw", "hip_roll", "knee_pitch", "ankle_pitch")
ACT_ORDER = ["left_shoulder_yaw", "left_shoulder_pitch", "left_elbow_yaw", "right_shoulder_yaw", "right_shoulder_pitch",
             "right_elbow_yaw", "left_hip_yaw", "left_hip_roll", "left_hip_pitch", "left_knee_pitch", "left_ankle_pitch",
             "right_hip_yaw", "right_hip_roll", "right_hip_pitch", "right_knee_pitch", "right_ankle_pitch"]


def norm(s: str) -> str:
    s = re.sub(r"\s*<\d+>\s*$", "", s.strip().lower())
    s = re.sub(r"_[0-9a-f]{6}$", "", s)          # GLB hash suffix of split occurrences
    return re.sub(r"[\s_]+", "_", s).strip("_")


def actuator_type(joint: str) -> str:
    return "feetech_sts3250" if any(joint.endswith(k) for k in LEG_JOINTS) else "feetech_sts3215_12v"


def rot(axis, theta):
    a = np.asarray(axis, float); a = a / np.linalg.norm(a); K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + np.sin(theta) * K + (1 - np.cos(theta)) * K @ K


def mass_items(group):
    """Datasheet components of one group: (mass kg, centre in CAD m, box in CAD m, name)."""
    return [(i["mass_g"] / 1000.0, np.array(i["com_cad_mm"]) / 1000.0, np.array(i["box_mm"]) / 1000.0, i["name"])
            for i in MASS["items"] if i["group"] == group]


def quat_of(R):
    """MuJoCo quaternion (w x y z) of a rotation matrix whose columns are the frame's axes in the parent frame."""
    t = np.trace(R)
    if t > 0:
        w = np.sqrt(1.0 + t) / 2.0
        q = np.array([w, (R[2, 1] - R[1, 2]) / (4 * w), (R[0, 2] - R[2, 0]) / (4 * w), (R[1, 0] - R[0, 1]) / (4 * w)])
    else:
        i = int(np.argmax(np.diag(R))); j, k = (i + 1) % 3, (i + 2) % 3
        s = np.sqrt(1.0 + R[i, i] - R[j, j] - R[k, k]) * 2.0
        q = np.zeros(4); q[0] = (R[k, j] - R[j, k]) / s
        q[1 + i], q[1 + j], q[1 + k] = 0.25 * s, (R[j, i] + R[i, j]) / s, (R[k, i] + R[i, k]) / s
    return q / np.linalg.norm(q)


def box_inertia(m, d):
    return m / 12.0 * np.diag([d[1] ** 2 + d[2] ** 2, d[0] ** 2 + d[2] ** 2, d[0] ** 2 + d[1] ** 2])


def combine(parts):
    """parts: list of (mass, com, I_about_com) -> (M, com, I_about_com)."""
    M = sum(p[0] for p in parts); com = sum(p[0] * p[1] for p in parts) / M; I = np.zeros((3, 3))
    for m, c, Ii in parts:
        r = c - com; I += Ii + m * (r @ r * np.eye(3) - np.outer(r, r))
    return M, com, I


def part_props(name: str, mesh: trimesh.Trimesh, motor_type: str | None):
    """(mass kg, com, inertia about com) in the frame of `mesh`."""
    lo, hi = mesh.bounds; d = hi - lo
    if motor_type:
        m = SERVO_MASS[motor_type]; return m, (lo + hi) / 2, box_inertia(m, d), "servo"
    return solid_props(mesh, PETG_DENSITY)   # stitches the GLB's T-junction cracks, then real volume/inertia


def fmt(v, n=6):
    return " ".join(f"{float(x):.{n}f}" for x in np.atleast_1d(v))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "sim/assets/zbot-cad"))
    ap.add_argument("--imu", default=None, help="IMU position in CAD mm (default: the QMI8658 chip centre from hardware/head_imu/imu_pose.json)")
    ap.add_argument("--imu-frame", default="imu", choices=("imu", "body"),
                    help="'imu' (default): site axes = the real chip axes, the sim sensors output raw QMI8658 readings. "
                         "'body': site axes = body axes (x fwd, y left, z up), the Pi must rotate the raw readings first.")
    ap.add_argument("--no-backpack", action="store_true")
    args = ap.parse_args(); out = Path(args.out)

    # ---- IMU pose: chip position + chip axes, from the head module's CAD pose ----------------------------------
    imu_pose = json.load(open(HW / "head_imu/imu_pose.json"))
    imu_cad_mm = np.array([float(x) for x in args.imu.split(",")]) if args.imu else np.array(imu_pose["imu_chip_centre_mm"], float)
    ax_cad = imu_pose["imu_axes_in_robot_frame"]
    # columns = the chip's x/y/z axes expressed in the sim body frame
    R_imu = np.column_stack([R_SIM @ np.array(ax_cad[k], float) for k in ("x_imu", "y_imu", "z_imu")])
    assert abs(np.linalg.det(R_imu) - 1.0) < 1e-9 and np.allclose(R_imu.T @ R_imu, np.eye(3), atol=1e-9), R_imu
    R_site = R_imu if args.imu_frame == "imu" else np.eye(3)

    J = json.load(open(JOINTS)); joints = {j["name"]: j for j in J["joints"]}
    limits = json.load(open(HW / "joint_limits.json")); servo_ids = json.load(open(HW / "servo_ids.json"))
    model_zero = json.load(open(HW / "model_zero_offsets.json")); invert = json.load(open(HW / "model_invert.json"))

    # ---- GLB: meshes per occurrence (CAD metres, assembly frame) ------------------------------------------------
    scene = trimesh.load(str(GLB), force="scene"); g = scene.graph; parents = g.transforms.parents
    generic = re.compile(r"^(mesh_\d+(_\d+)?|node_\d+|)$")
    def occ(n):
        while n is not None and (generic.match(n) or n == "world"): n = parents.get(n)
        return n
    occ_meshes: dict[str, list] = collections.defaultdict(list)
    for n in g.nodes_geometry:
        T, geom = g.get(n); m = scene.geometry[geom].copy(); m.apply_transform(T); occ_meshes[norm(occ(n))].append(m)
    excluded = sorted(k for k in occ_meshes if any(re.search(p, k) for p in EXCLUDE))
    occ_meshes = {k: trimesh.util.concatenate(v) for k, v in occ_meshes.items() if k not in excluded}

    # ---- links: union-find over fastened pairs + joint occurrences ----------------------------------------------
    uf: dict[str, str] = {}
    def rep(k):
        uf.setdefault(k, k)
        while uf[k] != k: uf[k] = uf[uf[k]]; k = uf[k]
        return k
    # union-find keys keep the "<n>" instance suffix (two screws of the same type must not fuse links);
    # excluded hardware (screws, washers, absent electronics) never joins anything
    def mkey(s): return re.sub(r"[\s_]+", "_", s.strip().lower())
    def is_excluded(s): return any(re.search(p, norm(s)) for p in EXCLUDE)
    for a, b in J["fastened"]:
        if a != "?" and b != "?" and not is_excluded(a) and not is_excluded(b): uf[rep(mkey(a))] = rep(mkey(b))
    for j in joints.values():
        for o in j["occurrences"]: rep(mkey(o))
    members = collections.defaultdict(list)
    for k in list(uf): members[rep(k)].append(norm(k))
    root = next(rep(k) for k in uf if "torso" in k)
    # orphans (GLB occurrences without any mate) go to the torso link
    mated_norm = {norm(k) for k in uf}
    orphans = [k for k in occ_meshes if k not in mated_norm]
    for k in orphans: members[root].append(k)
    # tree
    link_of_joint = {}; parent_link = {root: None}; joint_of_link = {}; order = []; visited = {root}; progress = True
    while progress:
        progress = False
        for name, j in joints.items():
            if name in link_of_joint: continue
            ra, rb = rep(mkey(j["occurrences"][0])), rep(mkey(j["occurrences"][1]))
            if ra in visited and rb not in visited: p, c = ra, rb
            elif rb in visited and ra not in visited: p, c = rb, ra
            else: continue
            link_of_joint[name] = c; parent_link[c] = p; joint_of_link[c] = name; visited.add(c); order.append(name); progress = True
    assert len(order) == 16, order

    # ---- forward kinematics to the standing pose (model_zero_offsets), CAD frame --------------------------------
    T = {root: np.eye(4)}; jw = {}
    for name in order:
        j = joints[name]; c = link_of_joint[name]; p = parent_link[c]; Tp = T[p]
        o = Tp[:3, :3] @ np.array(j["origin"]) + Tp[:3, 3]; a = Tp[:3, :3] @ np.array(j["axis"]); a /= np.linalg.norm(a)
        R = rot(a, np.radians(model_zero.get(name, 0.0))); Tj = np.eye(4); Tj[:3, :3] = R; Tj[:3, 3] = o - R @ o
        T[c] = Tj @ Tp; jw[name] = (o, a)
    # standing-pose meshes per link, CAD frame
    link_mesh: dict[str, dict] = {}
    for L, mem in members.items():
        printed, servos = [], []
        for k in mem:
            if k not in occ_meshes: continue
            m = occ_meshes[k].copy(); m.apply_transform(T[L]); (servos if k.endswith("_motor") else printed).append((k, m))
        link_mesh[L] = {"printed": printed, "servos": servos}
    allv = np.vstack([m.vertices for d in link_mesh.values() for grp in d.values() for _, m in grp])
    z_floor = allv[:, 2].min()
    torso = occ_meshes[next(k for k in members[root] if k == "torso")]
    base_cad = (torso.bounds[0] + torso.bounds[1]) / 2
    def to_sim(p): return R_SIM @ (np.asarray(p) - base_cad)
    origin = {root: base_cad}; origin.update({link_of_joint[n]: jw[n][0] for n in order})

    # ---- output dir, meshes, inertials ----------------------------------------------------------------------------
    if out.exists(): shutil.rmtree(out)
    (out / "meshes").mkdir(parents=True); shutil.copytree(SRC_ASSETS / "actuators", out / "actuators")
    link_names = {root: "base"}; link_names.update({link_of_joint[n]: f"{n}_link" for n in order})
    inertial, geoms, report = {}, {}, []
    for L, d in link_mesh.items():
        lname = link_names[L]; parts = []; gl = []
        for kind, grp in d.items():
            if not grp: continue
            meshes = []
            for k, m in grp:
                mt = actuator_type(k[: -len("_motor")]) if kind == "servos" else None
                mass, com, I, how = part_props(k, m, mt); parts.append((mass, com, I)); report.append((lname, k, mass, how))
                mm = m.copy(); mm.vertices = (R_SIM @ (m.vertices - origin[L]).T).T
                meshes.append(mm)
            merged = trimesh.util.concatenate(meshes); fn = f"{lname}_{kind}.stl"; merged.export(out / "meshes" / fn); gl.append((fn, kind))
        if L == root:   # electronics rigid to the torso: the two modules in the head (no neck joint)
            for m, c, dd, n in mass_items("head") + mass_items("torso"):
                parts.append((m, c, box_inertia(m, dd))); report.append((lname, n, m, "datasheet"))
        M, com, I = combine(parts); com_s = R_SIM @ (com - origin[L]); I_s = R_SIM @ I @ R_SIM.T
        inertial[L] = (M, com_s, I_s); geoms[L] = gl
    # backpack (rigid on the base): datasheet components + the printed shells from their mesh volume
    bp = None
    if not args.no_backpack:
        parts = []
        for m, c, dd, n in mass_items("backpack"):
            parts.append((m, c, box_inertia(m, dd))); report.append(("backpack", n, m, "datasheet"))
        for part in BACKPACK_PARTS:
            m = trimesh.load(str(BACKPACK_STL / f"backpack_v3_{part}_robotframe.stl"), force="mesh")
            m.vertices = m.vertices / 1000.0
            mass, com_p, I_p, how = solid_props(m, PETG_DENSITY)
            parts.append((mass, com_p, I_p)); report.append(("backpack", f"{part} PETG", mass, how))
            m.vertices = (R_SIM @ (m.vertices - base_cad).T).T; m.export(out / "meshes" / f"backpack_{part}.stl")
        M, com, I = combine(parts); bp = (M, R_SIM @ (com - base_cad), R_SIM @ I @ R_SIM.T)

    # ---- feet: collision box = bottom 12 mm slab of the foot link mesh (link frame) ----------------------------
    feet = {}
    for side in ("left", "right"):
        L = link_of_joint[f"{side}_ankle_pitch"]; m = trimesh.load(str(out / "meshes" / f"{link_names[L]}_printed.stl"), force="mesh")
        v = m.vertices; zmin = v[:, 2].min(); sl = v[v[:, 2] < zmin + 0.012]; lo, hi = sl.min(0), sl.max(0)
        feet[side] = ((lo + hi) / 2, (hi - lo) / 2, zmin)
    imu_sim = to_sim(imu_cad_mm / 1000.0); imu_quat = quat_of(R_site)
    base_z = base_cad[2] - z_floor + 0.001

    # ---- MJCF ---------------------------------------------------------------------------------------------------
    o = []; w = o.append
    w('<mujoco model="zeroth01_cad">')
    w('  <!-- GENERATED FILE - do not hand-edit. Source: resources/cad/z001-opus-m-93de7567 (OnShape microversion 93de7567)')
    w('       + hardware/{joint_limits,model_zero_offsets,model_invert,servo_ids}.json, built by sim/tools/build_model_cad.py -->')
    w('  <default>\n    <default class="robot">\n      <default class="motor">\n        <joint />\n        <motor />\n      </default>')
    w('      <default class="visual">\n        <geom contype="0" conaffinity="0" group="2" />\n      </default>')
    w('      <default class="collision">\n        <geom condim="6" friction="0.8 0.02 0.01" group="3" />\n      </default>\n    </default>')
    w('    <mesh maxhullvert="32" />\n  </default>\n  <compiler angle="radian" />')
    w('  <asset>\n    <material name="printed_material" rgba="0.80 0.85 0.90 1" />\n    <material name="servo_material" rgba="0.20 0.20 0.22 1" />')
    w('    <material name="backpack_base_material" rgba="0.19 0.44 0.84 1" />\n    <material name="backpack_lid_material" rgba="0.50 0.70 0.35 1" />')
    w('    <material name="backpack_insert_material" rgba="0.78 0.63 0.23 1" />\n    <material name="imu_material" rgba="0 1 0 1" />')
    for L in link_mesh:
        for fn, kind in geoms[L]: w(f'    <mesh name="{fn}" file="meshes/{fn}" />')
    if bp:
        for part in BACKPACK_PARTS: w(f'    <mesh name="backpack_{part}.stl" file="meshes/backpack_{part}.stl" />')
    w('  </asset>\n  <worldbody>')
    w(f'    <body name="base" pos="0 0 {base_z:.6f}" childclass="robot">\n      <freejoint name="floating_base" />')
    def emit(L, ind):
        sp = " " * ind; lname = link_names[L]; M, com, I = inertial[L]
        w(f'{sp}<inertial pos="{fmt(com)}" mass="{M:.6f}" fullinertia="{I[0,0]:.3e} {I[1,1]:.3e} {I[2,2]:.3e} {I[0,1]:.3e} {I[0,2]:.3e} {I[1,2]:.3e}" />')
        for fn, kind in geoms[L]:
            w(f'{sp}<geom name="{lname}_{kind}_visual" material="{"servo" if kind == "servos" else "printed"}_material" type="mesh" mesh="{fn}" class="visual" />')
        if L == root:
            w(f'{sp}<site name="base" pos="0 0 0" size="0.005" />')
            w(f'{sp}<!-- IMU: QMI8658 of the Waveshare RP2040-LCD-1.28 in the left eye (hardware/head_imu/imu_pose.json).')
            w(f'{sp}     The head has no joint, so the chip is rigid to the base. Site axes = {"the real chip axes: x_imu to the robot right, y_imu up, z_imu backwards" if args.imu_frame == "imu" else "the body axes (x fwd, y left, z up)"}. -->')
            w(f'{sp}<site name="imu" pos="{fmt(imu_sim)}" quat="{fmt(imu_quat)}" size="0.006" rgba="0 1 0 1" />')
            if bp:
                w(f'{sp}<body name="backpack" pos="0 0 0">\n{sp}  <!-- backpack v4.2 (hardware/backpack_v2), {bp[0]*1000:.0f} g: components from hardware/mass_model.json (datasheets), printed shells from mesh volume -->')
                w(f'{sp}  <inertial pos="{fmt(bp[1])}" mass="{bp[0]:.4f}" fullinertia="{bp[2][0,0]:.3e} {bp[2][1,1]:.3e} {bp[2][2,2]:.3e} {bp[2][0,1]:.3e} {bp[2][0,2]:.3e} {bp[2][1,2]:.3e}" />')
                for part in BACKPACK_PARTS: w(f'{sp}  <geom name="backpack_{part}_visual" material="backpack_{part}_material" type="mesh" mesh="backpack_{part}.stl" class="visual" />')
                w(f'{sp}</body>')
        for side in ("left", "right"):
            if L == link_of_joint[f"{side}_ankle_pitch"]:
                c, h, zmin = feet[side]; S = side.capitalize()
                w(f'{sp}<geom name="{S}_Foot_collision_box" type="box" pos="{fmt(c)}" size="{fmt(h)}" class="collision" />')
                w(f'{sp}<site name="{side}_foot" pos="{c[0]:.6f} {c[1]:.6f} {zmin - 0.002:.6f}" size="0.005" />')
        for name in order:
            c = link_of_joint[name]
            if parent_link[c] != L: continue
            pos = R_SIM @ (origin[c] - origin[L]); ax = R_SIM @ jw[name][1]; ax = -ax if invert.get(name) else ax
            lim = limits[name]; lo, hi = np.radians(lim["min_deg"]), np.radians(lim["max_deg"])
            w(f'{sp}<body name="{link_names[c]}" pos="{fmt(pos)}">')
            w(f'{sp}  <joint name="{name}" type="hinge" ref="0.0" class="motor" range="{lo:.6f} {hi:.6f}" axis="{fmt(ax)}" />')
            emit(c, ind + 2); w(f'{sp}</body>')
    emit(root, 6)
    w('    </body>\n  </worldbody>\n  <actuator>')
    tree_order = [ln.split('name="')[1].split('"')[0] for ln in o if ln.lstrip().startswith("<joint ")]
    assert len(tree_order) == 16
    for name in tree_order: w(f'    <motor name="{name}_ctrl" joint="{name}" class="motor" />')   # ctrl index == joint order
    w('  </actuator>\n  <contact>\n    <pair geom1="Left_Foot_collision_box" geom2="floor" />\n    <pair geom1="Right_Foot_collision_box" geom2="floor" />\n  </contact>')
    w('  <sensor>\n    <accelerometer name="imu_acc" site="imu" noise="0.01" />\n    <gyro name="imu_gyro" site="imu" noise="0.01" />\n    <magnetometer name="imu_mag" site="imu" noise="0.05" />')
    w('    <framepos name="base_link_pos" objtype="site" objname="base" />\n    <framequat name="base_link_quat" objtype="site" objname="base" />')
    w('    <framelinvel name="base_link_vel" objtype="site" objname="base" />\n    <frameangvel name="base_link_ang_vel" objtype="site" objname="base" />')
    w('    <force name="left_foot_force" site="left_foot" />\n    <force name="right_foot_force" site="right_foot" />\n  </sensor>\n</mujoco>')
    (out / "robot.mjcf").write_text("\n".join(o) + "\n")
    total_mass = sum(v[0] for v in inertial.values()) + (bp[0] if bp else 0)
    meta = {"joint_name_to_metadata": {n: {"id": servo_ids[n], "actuator_type": actuator_type(n), "kp": "16.0", "kd": "3.0"} for n in tree_order},
            "control_frequency": 50, "source": "resources/cad/z001-opus-m-93de7567 via sim/tools/build_model_cad.py",
            "imu": {"cad_mm": [round(float(x), 3) for x in imu_cad_mm],
                    "pos_body_m": [round(float(x), 5) for x in imu_sim],
                    "site_quat_wxyz": [round(float(x), 6) for x in imu_quat],
                    "frame": args.imu_frame,
                    "R_body_from_imu": [[round(float(v), 6) for v in row] for row in R_imu],
                    "axes_in_body": {"x_imu": [round(float(v), 3) for v in R_imu[:, 0]],
                                     "y_imu": [round(float(v), 3) for v in R_imu[:, 1]],
                                     "z_imu": [round(float(v), 3) for v in R_imu[:, 2]]},
                    "note": ("sim imu_acc/imu_gyro are the raw QMI8658 axes -- the Pi feeds the sensor readings "
                             "straight to the policy" if args.imu_frame == "imu" else
                             "sim imu_acc/imu_gyro are in body axes -- the Pi must map raw readings with R_body_from_imu "
                             "before feeding the policy"),
                    "source": "hardware/head_imu/imu_pose.json (Waveshare RP2040-LCD-1.28, QMI8658, left eye)"},
            "mass_model": {"source": "hardware/mass_model.json", "total_mass_kg": round(total_mass, 4)}}
    json.dump(meta, open(out / "metadata.json", "w"), indent=2)

    # ---- report ---------------------------------------------------------------------------------------------------
    total = total_mass
    print(f"model -> {out}\nlinks: {len(link_mesh)}  joints: {len(order)}  excluded occurrences: {len(excluded)}  orphans->torso: {orphans}")
    print(f"total mass {total:.3f} kg (robot {total - (bp[0] if bp else 0):.3f} + backpack {bp[0] if bp else 0:.3f}); base at z={base_z:.3f} m; floor at CAD z={z_floor*1000:.1f} mm")
    for L in link_mesh:
        M, com, I = inertial[L]; print(f"  {link_names[L]:26s} {M*1000:7.1f} g  com(sim) {np.round(com*1000,1)}")
    print("joints (sim axis at standing pose, range deg, zero offset applied):")
    for name in order:
        ax = R_SIM @ jw[name][1]; ax = -ax if invert.get(name) else ax; lim = limits[name]
        print(f"  {name:22s} axis {np.round(ax,3)}  range [{lim['min_deg']:.1f}, {lim['max_deg']:.1f}]  zero {model_zero.get(name,0):+.1f}  inv {bool(invert.get(name))}")
    print("part mass estimates:"); [print(f"  {l:26s} {k:28s} {m*1000:6.1f} g  ({how})") for l, k, m, how in report]
    print("excluded:", excluded)
    json.dump({"links": {link_names[L]: [k for k in members[L] if k in occ_meshes] for L in link_mesh}, "excluded": excluded,
               "part_masses_g": {k: round(m * 1000, 1) for _, k, m, _ in report}, "total_mass_kg": round(total, 4)},
              open(out / "build_report.json", "w"), indent=1)


if __name__ == "__main__":
    main()
