#!/usr/bin/env python3
"""Export the backpack designs as GLB attachments for the servo GUI and write the manifest.

resources/cad/attachments/manifest.json is GENERATED here — edit the tables below, not the JSON.
Frame: the pinned assembly frame (X left, Y back, Z up), metres — like the pinned GLB, so the
GUI adds the nodes as children of the model root without any transform.
Needs trimesh + numpy.  Usage: python export_attachments.py
(run hardware/backpack_v2/check_cables.py first: it writes the per-cable STLs)
"""
import glob, json, os, trimesh
HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
OUT = os.path.join(REPO, "resources", "cad", "attachments"); os.makedirs(OUT, exist_ok=True)
BP = os.path.join(REPO, "hardware", "backpack_v2")

# printed parts: key -> (label, colour)
PARTS = {
    "v3": {"base": ("base frame: Pi-Lage + LiPo-Schublade (Druck 1)", "#3070d6"), "lid": ("rear lid: Cutoff, Schalter, Sicherung, Warner (Druck 2)", "#80b35a")},
    "v2": {"base": ("base frame (print 1)", "#3070d6"), "deck": ("electronics deck (print 2)", "#e08a2e"), "lid": ("rear lid (print 3)", "#80b35a")},
}
# component envelopes: placeholder key -> (label, colour, opacity)
COMPONENTS = {
    "lipo": ("LiPo Gens Ace 3S 2200 mAh (106 x 34 x 25)", "#d4c33a", 0.55),
    "cutoff": ("XY-CD63 low-voltage cutoff (62 x 56 x 28), Display nach innen", "#d94545", 0.55),
    "cutoff_screws": ("XY-CD63: 4x M3 Zylinderkopf, von aussen durch den Deckel", "#9aa0a6", 1.0),
    "cutoff_vin_wires": ("XY-CD63 VIN-Klemmen (Oberkante, -X): Kabelzone nach oben", "#d94545", 0.25),
    "cutoff_out_wires": ("XY-CD63 OUT-Klemmen (Oberkante, +X): Kabelzone nach oben", "#d94545", 0.25),
    "waveshare": ("Waveshare Bus Servo Adapter (A) (42 x 33), am Deckel", "#2bb0c9", 0.55),
    "waveshare_servo_plugs": ("Waveshare: Servostecker + Biegeradien (42 mm, obere Kante)", "#2bb0c9", 0.25),
    "waveshare_plugs": ("Waveshare: DC / USB-C plug zone (-X)", "#2bb0c9", 0.25),
    "cam_ribbon": ("Kamera-Flachband: Schlitz -> CSI-Buchse", "#d9a441", 0.3),
    "switch": ("anti-spark XT60 switch body (45 x 22 x 15)", "#f08a24", 0.55),
    "fuse_holder": ("30 A fuse holder", "#9a5fd1", 0.55),
    "xt60_lipo_fuse": ("XT60 pair: LiPo <-> fuse", "#b8433a", 0.55),
    "xt60_fuse_switch": ("XT60 pair: fuse <-> switch", "#b8433a", 0.55),
    "warner": ("LiPo low-voltage warner (35 x 22)", "#2ca58d", 0.55),
    "warner_plug": ("balancer plug JST-XH at the warner", "#2ca58d", 0.35),
    "pololu": ("Pololu D24V50F5 5 V buck", "#4f8fe6", 0.55),
    "pololu_wires": ("Pololu: soldered wires zone", "#4f8fe6", 0.25),
    "pi": ("Raspberry Pi 4B quer, USB/Ethernet zur Mitte", "#c51a4a", 0.55),
    "pi_screws": ("Pi: 4x M2x8 Zylinderkopf von der Torsoseite + Mutter", "#9aa0a6", 1.0),
    "pi_plugs": ("Pi: Ethernet + USB-A mit Steckern (28 mm, nach +X)", "#c51a4a", 0.35),
    "pi_usbc_plug": ("Pi: USB-C Netzteil, 90-Grad-Stecker", "#c51a4a", 0.35),
}
CABLES = {
    "lipo_xt60_lead": ("LiPo XT60 lead, 14 AWG", "#8b1a1a"), "lipo_balancer": ("LiPo balancer lead", "#c9a227"),
    "fuse_leg_1": ("fuse cable leg -> LiPo XT60", "#8b1a1a"), "fuse_leg_2": ("fuse cable leg -> switch XT60", "#8b1a1a"),
    "switch_in_lead": ("switch input lead", "#8b1a1a"), "switch_out_pigtail": ("switch output pigtail -> VIN, 14 AWG", "#8b1a1a"),
    "out_to_waveshare": ("12 V OUT -> Waveshare", "#e07020"), "out_to_pololu": ("12 V OUT -> Pololu", "#e07020"),
    "servo_bus_a": ("servo bus A (Molex) from the torso", "#3aa655"), "servo_bus_b": ("servo bus B (Molex) from the torso", "#3aa655"),
    "pi_usb_to_waveshare": ("Pi USB-A -> Waveshare USB-C", "#3b6fd2"), "pololu_5v_usbc": ("Pololu 5 V -> Pi USB-C", "#22b3c7"),
    "test_leads_5v": ("5 V test leads -> lid pins", "#c9a227"),
}
# head, right eye: Raspberry Pi Camera Module 3 + modified head shell (hardware/head_cam/head_cam3.py)
CAM_DIR = os.path.join(REPO, "hardware", "head_cam", "stl", "robotframe")
CAM_PARTS = {"head_shell_cam3": ("Kopfschale mit Kamera-Blende rechts (Druck)", "#caa21a", 1.0)}
CAM_COMPONENTS = {"cam3_board": ("Camera Module 3: Platine 25 x 23,9", "#2e7d32", 1.0), "cam3_module": ("Camera Module 3: Sensor + Objektiv (75°)", "#1c1c1c", 1.0),
                  "cam3_j1": ("Camera Module 3: Kabelstecker J1", "#d0d0d0", 1.0), "cam3_fpc": ("Flachbandkabel 16 mm (nach unten)", "#d9a441", 1.0),
                  "cam3_fov": ("Sichtfeld 66° x 41° (35 mm)", "#3060e0", 0.18)}
# head, left eye: IMU board + plug adapters (hardware/head_imu/rp2040_lcd_128.py writes the robot-frame STLs)
HEAD_DIR = os.path.join(REPO, "hardware", "head_imu", "stl", "robotframe")
HEAD_PARTS = {"neck_mount_imu": ("Hinterplatte mit IMU-Stegen (Druck, ersetzt Neck Mount + Adapter)", "#caa21a")}
HEAD_COMPONENTS = {   # key -> (label, colour, opacity)
    "pcb": ("RP2040-LCD-1.28: Platine (R 18,25 + USB-Lasche)", "#1d3f7a", 1.0), "lcd_panel": ("1,28\" LCD Ø35,6", "#15171a", 1.0),
    "lcd_viewarea": ("LCD aktive Fläche Ø32,4", "#0e4a5c", 1.0), "hdr_h1": ("Buchsenleiste H1 2x10 1,27 mm", "#2a2a2a", 1.0),
    "hdr_h2": ("Buchsenleiste H2 2x10 1,27 mm", "#2a2a2a", 1.0), "usbc": ("USB-C", "#b0b4b8", 1.0),
    "sw_boot": ("Taster BOOT", "#e6e6e6", 1.0), "sw_reset": ("Taster RESET", "#e6e6e6", 1.0), "batt": ("Akkustecker MX1.25", "#f2efe6", 1.0),
    "rp2040": ("RP2040", "#333333", 1.0), "xtal": ("Quarz", "#9aa0a6", 1.0), "d1": ("D1", "#333333", 1.0), "l1": ("L1", "#555555", 1.0),
    "qmi8658": ("QMI8658 IMU-Chip", "#f0c020", 1.0),
    "axis_x": ("IMU-Achse X (rot)", "#e03030", 1.0), "axis_y": ("IMU-Achse Y (grün)", "#30b040", 1.0), "axis_z": ("IMU-Achse Z (blau)", "#3060e0", 1.0),
}
def hexrgb(h): h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
def colored(mesh, rgb, alpha=1.0):
    mesh.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
        baseColorFactor=list(rgb) + [int(255 * alpha)], metallicFactor=0.05, roughness=0.6))
    return mesh
def add(sc, path, name, color, alpha=1.0):
    m = trimesh.load(path); m.apply_scale(0.001); sc.add_geometry(colored(m, hexrgb(color), alpha), node_name=name, geom_name=name)

manifest = {"_comment": "GENERATED by hardware/backpack_v2/viewer/export_attachments.py - edit the tables there. Frame = assembly frame of the pinned GLB (Z-up, metres).", "sets": [], "hide": [
    {"id": "orig_back", "label": "hide original BackPack + Waveshare", "patterns": ["BackPack", "Bus Servo Adaptor"], "default": True},
    {"id": "orig_torso", "label": "hide original torso electronics (battery, Electronics Mount, MilkV, speaker)", "patterns": ["Battery", "Electronics Mount", "MilkV", "[Draft] Speaker Mount"], "default": True},
    {"id": "orig_eye", "label": "hide original left-eye LCD IMU + Eye Mount", "patterns": ["LCD IMU", "Eye Mount"], "default": True},
    {"id": "head_shell", "label": "hide original head shell (Head) - replaced by the camera version", "patterns": ["Head"], "default": True},
    {"id": "orig_cam", "label": "hide original Milk camera", "patterns": ["Milk Camera"], "default": True},
    {"id": "head_back", "label": "hide original head back plate (Neck Mount) - replaced by the IMU version", "patterns": ["Neck Mount"], "default": True},
    {"id": "head_neck", "label": "hide neck piece on the torso (Torso to Neck)", "patterns": ["Torso to Neck"], "default": False}]}
for ver, stl_dir, label, visible in (("v3", "stl_v3", "Backpack v4.2 — Pi quer, Waveshare am Deckel, Kameraschlitz", True),
                                      ("v2", "stl", "Backpack v2 — two layers (fallback)", False)):
    sc = trimesh.Scene(); prefix = f"bp{ver[1]}"
    entry = {"id": f"backpack_{ver}", "label": label, "file": f"backpack_{ver}.glb", "visible": visible, "parts": [], "groups": []}
    for key, (lab, col) in PARTS[ver].items():
        name = f"{prefix}_{key}"; add(sc, os.path.join(BP, stl_dir, f"backpack_{ver}_{key}_robotframe.stl"), name, col)
        entry["parts"].append({"node": name, "label": lab, "color": col, "opacity": 0.85 if key == "lid" else 1.0})
    comps = []
    for f in sorted(glob.glob(os.path.join(BP, stl_dir, "placeholder_*.stl"))):
        key = os.path.basename(f)[12:-4]
        if key == "cables": continue
        lab, col, op = COMPONENTS.get(key, (key, "#cf4b4b", 0.45))
        name = f"{prefix}_c_{key}"; add(sc, f, name, col, op)
        comps.append({"node": name, "label": lab, "color": col, "opacity": op, "visible": False})
    if comps: entry["groups"].append({"id": f"{prefix}_components", "label": "components (envelopes incl. connectors & wire zones)", "items": comps})
    cabs = []
    for f in sorted(glob.glob(os.path.join(BP, stl_dir, "cables", "*.stl"))):
        key = os.path.basename(f)[:-4]; lab, col = CABLES.get(key, (key, "#2a2a2a"))
        name = f"{prefix}_w_{key}"; add(sc, f, name, col, 1.0)
        cabs.append({"node": name, "label": lab, "color": col, "opacity": 1.0, "visible": False})
    if cabs: entry["groups"].append({"id": f"{prefix}_cables", "label": "cables (tubes at minimum bend radius)", "items": cabs})
    path = os.path.join(OUT, entry["file"]); sc.export(path)
    print(f"{entry['id']}: {len(sc.geometry)} nodes -> {path} ({os.path.getsize(path)/1e6:.2f} MB)")
    manifest["sets"].append(entry)
if os.path.isdir(HEAD_DIR):
    sc = trimesh.Scene()
    entry = {"id": "head_imu", "label": "Kopf links: IMU RP2040-LCD-1.28 + Hinterplatte mit Stegen", "file": "head_imu.glb", "visible": True, "parts": [], "groups": []}
    for key, (lab, col) in HEAD_PARTS.items():
        name = f"imu_a_{key}"; add(sc, os.path.join(HEAD_DIR, f"{key}.stl"), name, col)
        entry["parts"].append({"node": name, "label": lab, "color": col, "opacity": 1.0})
    comps = []
    for key, (lab, col, op) in HEAD_COMPONENTS.items():
        name = f"imu_c_{key}"; add(sc, os.path.join(HEAD_DIR, f"imu_{key}.stl"), name, col, op)
        comps.append({"node": name, "label": lab, "color": col, "opacity": op, "visible": True})
    entry["groups"].append({"id": "imu_components", "label": "Waveshare RP2040-LCD-1.28 (Bauteile + IMU-Achsen)", "items": comps})
    path = os.path.join(OUT, entry["file"]); sc.export(path)
    print(f"{entry['id']}: {len(sc.geometry)} nodes -> {path} ({os.path.getsize(path)/1e6:.2f} MB)")
    manifest["sets"].append(entry)
if os.path.isdir(CAM_DIR):
    sc = trimesh.Scene()
    entry = {"id": "head_cam", "label": "Kopf rechts: Camera Module 3 + angepasste Kopfschale", "file": "head_cam.glb", "visible": True, "parts": [], "groups": []}
    for key, (lab, col, op) in CAM_PARTS.items():
        name = f"cam_p_{key}"; add(sc, os.path.join(CAM_DIR, f"{key}.stl"), name, col, op)
        entry["parts"].append({"node": name, "label": lab, "color": col, "opacity": op})
    comps = []
    for key, (lab, col, op) in CAM_COMPONENTS.items():
        name = f"cam_c_{key}"; add(sc, os.path.join(CAM_DIR, f"{key}.stl"), name, col, op)
        comps.append({"node": name, "label": lab, "color": col, "opacity": op, "visible": True})
    entry["groups"].append({"id": "cam_components", "label": "Raspberry Pi Camera Module 3 (+ Kabel, Sichtfeld)", "items": comps})
    path = os.path.join(OUT, entry["file"]); sc.export(path)
    print(f"{entry['id']}: {len(sc.geometry)} nodes -> {path} ({os.path.getsize(path)/1e6:.2f} MB)")
    manifest["sets"].append(entry)
json.dump(manifest, open(os.path.join(OUT, "manifest.json"), "w"), indent=1)
print("manifest written:", os.path.join(OUT, "manifest.json"))
