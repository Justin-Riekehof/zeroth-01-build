"""Generate the build-specific MuJoCo model (sim/assets/zbot-pixel/) from upstream kscale-assets.

Source of truth:
  * Geometry/kinematics:  kscale-assets `zbot-feet` (5-DoF legs, collision only on the feet
    -- the variant that matches this robot; `zbot-6dof-feet` has an extra ankle_roll joint
    that this build does not have)
  * Servo-bus IDs:        hardware/servo_ids.json (this repo -- ground truth, the upstream
    metadata uses a DIFFERENT id->joint assignment!)
  * Actuator dynamics:    kscale-assets sys-ID JSONs (STS3215@12V arms, STS3250 legs)

Transformations applied to upstream robot.mjcf:
  1. Joint names normalized to this repo's canonical names (left_knee -> left_knee_pitch,
     left_elbow -> left_elbow_yaw, ...) so hardware/*.json, the servo GUI and the sim all
     speak the same language.
  2. Gripper joints + actuators removed (no gripper servos in this build); the finger
     bodies stay welded to the forearms so their mass is preserved. Result: 16 actuated
     joints == 16 real servos.
  3. IMU sensor names normalized (IMU_2_acc -> imu_acc, ...) to what the training task expects.
  4. Foot collision boxes renamed to Left_/Right_Foot_collision_box; `left_foot`/`right_foot`
     sites added at the sole centers plus force sensors on them (needed by the walking task's
     feet observations).
  5. The restrictive defaults of the zbot-feet variant (ctrlrange/actuatorfrcrange +-2 Nm,
     fixed armature/frictionloss) are stripped: forcerange, damping, armature and frictionloss
     are set at load time from the sys-ID actuator JSONs per joint (see sim/train/common.py);
     a +-2 Nm clamp would silently cripple the 8.7 Nm STS3250 legs.
  6. Root body renamed floating_base_link -> "base" (K-Scale kbot convention): the
     mujoco-scenes "smooth" training scene aims its spotlights at a body named "base"
     and refuses to load models without one.

Usage:
  python sim/tools/build_model.py [--assets /path/to/kscale-assets] [--out sim/assets/zbot-pixel]

Re-run whenever servo IDs or the upstream assets change. Do not hand-edit the output.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

JOINT_RENAMES = {
    "left_elbow": "left_elbow_yaw",
    "right_elbow": "right_elbow_yaw",
    "left_knee": "left_knee_pitch",
    "right_knee": "right_knee_pitch",
    "left_ankle": "left_ankle_pitch",
    "right_ankle": "right_ankle_pitch",
}
GRIPPER_JOINTS = {"left_gripper", "right_gripper"}
SENSOR_RENAMES = {"IMU_2_acc": "imu_acc", "IMU_2_gyro": "imu_gyro", "IMU_2_mag": "imu_mag"}
GEOM_RENAMES = {
    "FOOT_collision_box": "Left_Foot_collision_box",
    "FOOT_2_collision_box": "Right_Foot_collision_box",
}
# body name -> (site name, force sensor name)
FOOT_BODIES = {"FOOT": ("left_foot", "left_foot_force"), "FOOT_2": ("right_foot", "right_foot_force")}

LEG_KEYWORDS = ("hip", "knee", "ankle")
ACTUATOR_TYPE_LEGS = "feetech_sts3250"
ACTUATOR_TYPE_ARMS = "feetech_sts3215_12v"

# zbot2-era defaults, matched to the sys-ID duty-cycle model (duty = kp*error_gain*err + kd*velerr).
# NOTE: before sim-to-real, read the real servos' P/D registers and make them consistent.
DEFAULT_KP = "16.0"
DEFAULT_KD = "3.0"
CONTROL_FREQUENCY = 50  # Hz, this build's target loop rate


def classify_actuator(joint_name: str) -> str:
    if any(k in joint_name for k in LEG_KEYWORDS):
        return ACTUATOR_TYPE_LEGS
    return ACTUATOR_TYPE_ARMS


def transform_mjcf(src: Path, provenance: str) -> ET.ElementTree:
    tree = ET.parse(src)
    root = tree.getroot()

    # 6. root body: kbot naming convention expected by the mujoco-scenes templates
    for body in root.iter("body"):
        if body.get("name") == "floating_base_link":
            body.set("name", "base")

    # 1+2. joints: rename / drop grippers
    for body in root.iter("body"):
        for joint in list(body.findall("joint")):
            name = joint.get("name", "")
            if name in GRIPPER_JOINTS:
                body.remove(joint)  # body becomes welded to parent, mass preserved
            elif name in JOINT_RENAMES:
                joint.set("name", JOINT_RENAMES[name])

    # actuators: rename to match joints, drop grippers
    actuator_sec = root.find("actuator")
    assert actuator_sec is not None, "no <actuator> section found"
    for motor in list(actuator_sec):
        jname = motor.get("joint", "")
        if jname in GRIPPER_JOINTS:
            actuator_sec.remove(motor)
        elif jname in JOINT_RENAMES:
            motor.set("joint", JOINT_RENAMES[jname])
            motor.set("name", f"{JOINT_RENAMES[jname]}_ctrl")

    # 3. sensors: rename IMU sensors
    sensor_sec = root.find("sensor")
    assert sensor_sec is not None, "no <sensor> section found"
    for sensor in sensor_sec:
        name = sensor.get("name", "")
        if name in SENSOR_RENAMES:
            sensor.set("name", SENSOR_RENAMES[name])

    # 4a. rename foot geoms everywhere they are referenced
    for geom in root.iter("geom"):
        name = geom.get("name", "")
        if name in GEOM_RENAMES:
            geom.set("name", GEOM_RENAMES[name])
    contact_sec = root.find("contact")
    if contact_sec is not None:
        for pair in contact_sec:
            for attr in ("geom1", "geom2"):
                v = pair.get(attr, "")
                if v in GEOM_RENAMES:
                    pair.set(attr, GEOM_RENAMES[v])

    # 4b. foot sites at the sole center (bottom face of the collision box) + force sensors
    for body in root.iter("body"):
        bname = body.get("name", "")
        if bname not in FOOT_BODIES:
            continue
        site_name, force_name = FOOT_BODIES[bname]
        box = next(g for g in body.findall("geom") if g.get("name", "").endswith("_Foot_collision_box"))
        px, py, pz = (float(v) for v in box.get("pos").split())
        sz = float(box.get("size").split()[2])
        site = ET.SubElement(body, "site")
        site.set("name", site_name)
        site.set("pos", f"{px:.6f} {py:.6f} {pz - sz:.6f}")
        site.set("size", "0.005")
        force = ET.SubElement(sensor_sec, "force")
        force.set("name", force_name)
        force.set("site", site_name)

    # 5. strip the restrictive default-class clamps (see module docstring)
    for default in root.iter("default"):
        for joint in default.findall("joint"):
            for attr in ("actuatorfrcrange", "armature", "frictionloss"):
                joint.attrib.pop(attr, None)
        for motor in default.findall("motor"):
            motor.attrib.pop("ctrlrange", None)

    root.insert(0, ET.Comment(f" GENERATED FILE - do not hand-edit. {provenance} "))
    ET.indent(tree, space="  ")
    return tree


def build_metadata(mjcf_root: ET.Element, servo_ids: dict[str, int]) -> dict:
    joint_names = [j.get("name") for j in mjcf_root.iter("joint") if j.get("name")]
    missing = set(joint_names) ^ set(servo_ids)
    assert not missing, f"joint sets differ between model and hardware/servo_ids.json: {missing}"
    return {
        "joint_name_to_metadata": {
            name: {
                "id": servo_ids[name],
                "actuator_type": classify_actuator(name),
                "kp": DEFAULT_KP,
                "kd": DEFAULT_KD,
            }
            for name in joint_names
        },
        "control_frequency": CONTROL_FREQUENCY,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--assets",
        type=Path,
        default=REPO_ROOT.parent / "ksim-zbot" / "ksim_zbot" / "kscale-assets",
        help="Path to a kscale-assets checkout",
    )
    parser.add_argument("--variant", default="zbot-feet", help="Upstream model variant to base on")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "sim" / "assets" / "zbot-pixel")
    args = parser.parse_args()

    src_dir = args.assets / args.variant
    assert (src_dir / "robot.mjcf").exists(), f"{src_dir}/robot.mjcf not found -- clone kscale-assets first"

    try:
        commit = subprocess.run(
            ["git", "-C", str(args.assets), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        commit = "unknown"
    provenance = f"Source: kscale-assets/{args.variant}@{commit}, built by sim/tools/build_model.py"

    servo_ids = json.loads((REPO_ROOT / "hardware" / "servo_ids.json").read_text())

    tree = transform_mjcf(src_dir / "robot.mjcf", provenance)
    metadata = build_metadata(tree.getroot(), servo_ids)

    n_joints = len(metadata["joint_name_to_metadata"])
    n_actuators = len(tree.getroot().find("actuator"))
    assert n_joints == n_actuators == 16, f"expected 16 joints/actuators, got {n_joints}/{n_actuators}"

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    tree.write(out / "robot.mjcf")
    (out / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    shutil.copytree(src_dir / "meshes", out / "meshes", dirs_exist_ok=True)
    (out / "actuators").mkdir(exist_ok=True)
    for f in (args.assets / "actuators").glob("feetech_*.json"):
        shutil.copy(f, out / "actuators" / f.name)

    print(f"OK: {out} ({n_joints} joints, provenance: {provenance})")
    for name, meta in metadata["joint_name_to_metadata"].items():
        print(f"  {name:22s} id={meta['id']:3d} {meta['actuator_type']}")


if __name__ == "__main__":
    main()
