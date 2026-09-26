#!/usr/bin/env python3
"""Build hardware/mass_model.json -- where every non-printed gram of this robot sits.

Run with the CAD env (needs cadquery for the backpack placeholders):
    .cad/bin/python sim/tools/build_mass_model.py

Inputs
  hardware/electronics_masses.json      datasheet masses (one entry per component, with source + confidence)
  hardware/backpack_v2/backpack_v4.py   build_placeholders() -> the v4.2 component boxes (CAD frame, mm)
                                        CABLES -> cable centrelines, for the wiring mass
  hardware/head_imu/imu_pose.json       Waveshare RP2040-LCD-1.28 (IMU) pose in the head
  hardware/head_cam/cam3_pose.json      Pi Camera Module 3 pose in the head

Output: hardware/mass_model.json -- items with mass, centre and box extent in the CAD assembly frame
(+X robot left, +Y back, +Z up, mm), grouped by the link they are rigid to:
  group "backpack" -> the backpack body of the MJCF, "head"/"torso" -> merged into the base link.
sim/tools/build_model_cad.py consumes this file; it runs in the ksim venv and must not need cadquery.
"""
from __future__ import annotations
import json
import os
import sys

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "hardware", "backpack_v2"))
MASSES = os.path.join(ROOT, "hardware", "electronics_masses.json")
OUT = os.path.join(ROOT, "hardware", "mass_model.json")


def main() -> None:
    import backpack_v4 as B  # noqa: E402  (needs cadquery)

    table = json.load(open(MASSES))
    comp = table["components"]
    wire = table["wire"]
    used: set[str] = set()

    def entry(key: str) -> dict:
        used.add(key)
        return comp[key]

    ph = {}
    for k, v in B.build_placeholders().items():
        s = v.val(); bb = s.BoundingBox(); c = s.Center()
        ph[k] = (np.array([c.x, c.y, c.z]), np.array([bb.xlen, bb.ylen, bb.zlen]))

    items: list[dict] = []

    def add(name, group, key, centre, box, note=""):
        e = entry(key)
        items.append(dict(name=name, group=group, mass_g=float(e["mass_g"]),
                          com_cad_mm=[round(float(x), 2) for x in centre],
                          box_mm=[round(float(x), 2) for x in box],
                          confidence=e["confidence"], source=e["source"],
                          note=(note + (" " + e.get("note", "")).rstrip()).strip()))

    # ---- backpack: every component sits in its v4.2 placeholder box -------------------------------------------
    for name, key, phk in [
        ("LiPo 3S 2200 (Gens Ace)", "lipo_3s_2200", "lipo"),
        ("XY-CD63 cutoff", "cutoff_xycd63", "cutoff"),
        ("Raspberry Pi 4B", "raspberry_pi_4b", "pi"),
        ("Waveshare bus servo adapter", "waveshare_servo_adapter", "waveshare"),
        ("Pololu D24V50F5", "pololu_d24v50f5", "pololu"),
        ("anti-spark switch", "antispark_switch", "switch"),
        ("XT60 fuse holder + fuse", "fuse_holder_30a", "fuse_holder"),
        ("LiPo warner", "lipo_warner", "warner"),
        ("XT60 pair LiPo-fuse", "xt60_pair", "xt60_lipo_fuse"),
        ("XT60 pair fuse-switch", "xt60_pair", "xt60_fuse_switch"),
    ]:
        c, d = ph[phk]
        add(name, "backpack", key, c, d)

    # plug bodies that hang off the boards (USB-C to the Pi, DC + Molex on the Waveshare)
    for name, key, phk in [
        ("Pi port-side plugs", "plug_usb_bundle", "pi_plugs"),
        ("Pi USB-C power plug", "plug_usbc", "pi_usbc_plug"),
        ("Waveshare servo plugs", "plug_molex_pair", "waveshare_servo_plugs"),
        ("Waveshare DC plug", "plug_dc_barrel", "waveshare_plugs"),
        ("cutoff VIN terminals", "screw_terminal_pair", "cutoff_vin_wires"),
        ("cutoff OUT terminals", "screw_terminal_pair", "cutoff_out_wires"),
        ("warner balancer plug", "plug_jst_xh", "warner_plug"),
    ]:
        c, d = ph[phk]
        add(name, "backpack", key, c, d)

    # M2/M3 screws + heat-set inserts holding the boards (small, but they sit far from the torso)
    for name, key, phk in [("cutoff screws", "screws_m3_set4", "cutoff_screws"),
                           ("Pi screws", "screws_m25_set4", "pi_screws")]:
        c, d = ph[phk]
        add(name, "backpack", key, c, d)

    # ---- cables: length of each centreline x conductor count x wire mass per metre ------------------------------
    for cname, cab in B.CABLES.items():
        pts = np.array(cab["pts"], float)
        length_mm = float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum())
        spec = wire["cables"][cname]
        gauge = wire["gauge"][spec["gauge"]]
        mass_g = length_mm / 1000.0 * gauge["g_per_m"] * spec["conductors"]
        lo, hi = pts.min(0), pts.max(0)
        items.append(dict(name=f"cable {cname}", group="backpack", mass_g=round(mass_g, 2),
                          com_cad_mm=[round(float(x), 2) for x in pts.mean(0)],
                          box_mm=[round(float(max(h - l, 5.0)), 2) for l, h in zip(lo, hi)],
                          confidence=gauge["confidence"], source=gauge["source"],
                          note=f"{length_mm:.0f} mm x {spec['conductors']} x {spec['gauge']} "
                               f"({gauge['g_per_m']} g/m), centroid of the CAD centreline"))

    # ---- torso: the servo bus that the CAD does not model ------------------------------------------------------
    # It leaves the backpack through the torso passage and runs down into the legs and out into the arms; lumped
    # slightly below and behind the torso centre (CAD torso centre is about (-5, 6, 322) mm).
    add("servo harness (not in CAD)", "torso", "servo_harness", [0.0, 20.0, 300.0], [120.0, 60.0, 200.0])

    # ---- head: the two modules in the eyes ---------------------------------------------------------------------
    imu = json.load(open(os.path.join(ROOT, "hardware", "head_imu", "imu_pose.json")))
    t = np.array(imu["t_module_to_robot_mm"], float)          # PCB centre on the back face of the module
    # module spans 4 mm forward (PCB + air gap + display) and ~4.5 mm back (headers): mass centre ~1 mm forward
    add("head IMU module (RP2040-LCD-1.28)", "head", "waveshare_rp2040_lcd_128",
        t + np.array([0.0, -1.0, 0.0]), [39.5, 9.0, 39.5], note="left eye;")

    cam = json.load(open(os.path.join(ROOT, "hardware", "head_cam", "cam3_pose.json")))
    T = np.array(cam["camera_to_robot"], float)
    cam_centre = (T[:3, :3] @ np.array([12.5, 12.5, -3.0]) + T[:3, 3])   # board centre, lens barrel forward
    add("Pi Camera Module 3", "head", "pi_camera_module_3", cam_centre, [25.0, 12.4, 24.0], note="right eye;")

    # the two servo types are not placed here: build_model_cad.py puts them on their CAD meshes
    unused = sorted(set(comp) - used - {"feetech_sts3215_12v", "feetech_sts3250"})
    total = sum(i["mass_g"] for i in items)
    per_group: dict[str, float] = {}
    for i in items:
        per_group[i["group"]] = per_group.get(i["group"], 0.0) + i["mass_g"]
    com = np.array([0.0, 0.0, 0.0])
    for i in items:
        com += i["mass_g"] * np.array(i["com_cad_mm"])
    com /= total

    doc = dict(
        generated_by="sim/tools/build_mass_model.py",
        frame="CAD assembly frame of resources/cad/z001-opus-m-93de7567 (mm): +X robot left, +Y back, +Z up",
        note="Masses are datasheet/manufacturer values (see electronics_masses.json); positions come from the "
             "backpack v4.2 placeholders and the head poses. Printed parts are NOT here - build_model_cad.py "
             "derives those from mesh volume x PETG density.",
        petg_density_kg_m3=table["petg_density_kg_m3"],
        servo_mass_g={k: comp[k]["mass_g"] for k in ("feetech_sts3215_12v", "feetech_sts3250")},
        servo_source={k: comp[k]["source"] for k in ("feetech_sts3215_12v", "feetech_sts3250")},
        total_g=round(total, 1),
        group_g={k: round(v, 1) for k, v in sorted(per_group.items())},
        com_cad_mm=[round(float(x), 1) for x in com],
        unused_components=unused,
        items=items,
    )
    json.dump(doc, open(OUT, "w"), indent=1)
    print(f"-> {os.path.relpath(OUT, ROOT)}")
    print(f"{len(items)} items, {total:.0f} g total, CoM (CAD mm) {np.round(com, 1)}")
    for g, v in sorted(per_group.items()):
        print(f"  {g:10s} {v:7.1f} g")
    for i in sorted(items, key=lambda x: -x["mass_g"]):
        print(f"  {i['mass_g']:7.1f} g  [{i['confidence']}] {i['name']:36s} {i['com_cad_mm']}")
    if unused:
        print("components in the table not placed:", unused)


if __name__ == "__main__":
    main()
