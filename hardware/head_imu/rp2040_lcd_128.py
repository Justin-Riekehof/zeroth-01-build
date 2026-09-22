#!/usr/bin/env python3
"""Waveshare RP2040-LCD-1.28 (1.28" round LCD, RP2040, QMI8658 6-axis IMU): CadQuery model, plus its placement in the
left eye of the Zeroth-01 head together with the two plug adapters (imu_adapter.py).

Source: Waveshare dimension drawing (wiki RP2040-LCD-1.28, "Spec02") and the official 3D drawing
files.waveshare.com/upload/a/a2/RP2040-LCD-1.28-3D-Drawing.zip (measured 2026-09-18). Values marked [S] are
estimates where the official model only has placeholders; measure them on the real board.

Module frame (mm): origin = centre of the round PCB on its BACK face (the side with the headers), +Z out of the back,
the display faces -Z, +Y points to the USB-C tab. Seen from the back (+Z) with USB up: H1 left (-X), H2 right (+X).
QMI8658 axes per its silkscreen: X_imu = +Y (towards USB), Y_imu = -X (towards H1), Z_imu = +Z (out of the back).

Head placement (assembly frame of resources/cad/z001-opus-m-93de7567.glb: +X robot left, +Y back, +Z up): orientation
as the "LCD IMU" there (USB tab towards the head centre (-X), H1 on top, H2 below); position from the two header
slots in the head back plate: the adapters sit on the headers, their tongues in the slots, shoulders on the plate.
Usage: .cad/bin/python hardware/head_imu/rp2040_lcd_128.py  ->  stl/ (module frame), stl/robotframe/, imu_pose.json
"""
from __future__ import annotations
import json, os
import numpy as np
import cadquery as cq
import trimesh
import imu_adapter as ad

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "stl"); OUT_RF = os.path.join(OUT, "robotframe")

# ---------------- board (Waveshare drawing + 3D drawing) ----------------
R_PCB = 18.25                                   # round PCB
TAB_TOP_Y, TAB_TOP_HX = 21.25, 6.40             # USB tab: flat top 12.81 wide ...
TAB_BASE_Y, TAB_BASE_HX = 15.77, 9.19           # ... slanted sides meet the circle here
T_STACK = 4.0                                   # [V] measured: display front to PCB back face (board + display)
T_PCB, LCD_T = 1.6, 1.6                         # [V] measured: PCB 1.6, display 1.6
GAP_LCD = T_STACK - T_PCB - LCD_T                # 0.8 air gap between PCB and display (rest of the measured stack)
LCD_D, LCD_VIEW_D = 35.6, 32.4                   # panel diameter [S] (touch variant), active area 32.4 [V]

HDR_W, HDR_L, HDR_H = 3.0, 13.1, 4.5            # 2x10 female header 1.27 mm, SMD; height [S] (3D drawing 4.5, K-Scale CAD ~5)
HDR_X, HDR_Y = 13.50, -0.05                     # H1 at -HDR_X, H2 at +HDR_X (27.00 apart [V])
PITCH = 1.27
LEG_W, LEG_H = 1.1, 0.25                        # gull-wing SMD legs on both long sides (footprint ~5.2 wide)

# other parts on the back face: (x0, x1, y0, y1, z0, z1), relative to the PCB centre
BACK_PARTS = {
    "usbc":     (-4.80, 4.78, 13.36, 21.07, 0.0, 3.25),     # USB-C, mouth towards +Y
    "batt":     (-10.25, -4.65, 6.85, 11.35, 0.0, 3.4),     # MX1.25 battery plug, height [S] (3D drawing 2.0, touch variant 3.4)
    "d1":       (5.18, 7.19, 13.80, 17.70, 0.2, 2.49),
    "l1":       (7.07, 9.94, 5.89, 8.17, 0.0, 1.6),
    "rp2040":   (-6.52, 0.52, -11.82, -4.78, 0.0, 0.85),
    "xtal":     (-5.24, -1.29, -16.35, -13.25, 0.0, 1.0),
    "qmi8658":  (-1.60, 1.05, -1.40, 1.80, 0.1, 0.88),      # the IMU chip
}

# ---------------- placement in the head (assembly frame, mm) ----------------
R_HEAD = np.array([[0.0, -1.0, 0.0],             # module X -> -Z (H1 on top), module Y -> -X (USB to the head centre),
                   [0.0, 0.0, 1.0],              # module Z -> +Y (back of the board towards the back of the head)
                   [-1.0, 0.0, 0.0]])
# anchor = the two header slots in the head back plate ("Neck Mount", pinned CAD): 13.43 x 3.27, mouth in its front
# face at y -6.93, centres x 27.665 / z 410.055 and 437.085. The adapter shoulders rest on that face.
SLOT_X, SLOT_Z, SLOT_FACE_Y = 27.665, (410.055, 437.085), -6.93
# adapter seat: the header bottoms out on the adapter floor if it is taller than the pocket; else the rim sits on the PCB
Z_ADAPTER = max(HDR_H - ad.POCKET_D, 0.0)
# DISPLAY_FLUSH: the display sits in the eye opening (front flush with the face, y -19.86; the USB tab goes into a recess
# of the head shell, see hardware/head_cam) and the adapters get a spacer so their tongues still reach the slots.
# False: standard adapters (10 mm), the display then sits 0.9 mm behind the face wall.
DISPLAY_FLUSH, Y_FACE_FRONT, DISPLAY_SETBACK = True, -19.86, 0.0
Y_PCB_BACK = (Y_FACE_FRONT + DISPLAY_SETBACK + T_STACK) if DISPLAY_FLUSH else SLOT_FACE_Y - (Z_ADAPTER + ad.Z_BODY)
SPACER = round(SLOT_FACE_Y - Y_PCB_BACK - (Z_ADAPTER + ad.Z_BODY), 2)   # 3.43 flush / 0 standard
T_HEAD = np.array([SLOT_X + HDR_Y, Y_PCB_BACK, sum(SLOT_Z) / 2])   # PCB centre on its back face


def box(x0, x1, y0, y1, z0, z1):
    return cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0, centered=False).translate((x0, y0, z0))


def pcb():
    disc = cq.Workplane("XY").circle(R_PCB).extrude(T_PCB)
    tab = cq.Workplane("XY").polyline([(-TAB_BASE_HX, TAB_BASE_Y), (TAB_BASE_HX, TAB_BASE_Y), (TAB_TOP_HX, TAB_TOP_Y), (-TAB_TOP_HX, TAB_TOP_Y)]).close().extrude(T_PCB)
    return disc.union(tab).translate((0, 0, -T_PCB))


def header(xc):
    h = box(xc - HDR_W / 2, xc + HDR_W / 2, HDR_Y - HDR_L / 2, HDR_Y + HDR_L / 2, 0.0, HDR_H)
    for col in (-0.5, 0.5):                                     # 2 x 10 socket openings, 1.27 mm pitch
        for k in range(10):
            x, y = xc + col * PITCH, HDR_Y + 4.5 * PITCH - k * PITCH
            h = h.cut(box(x - 0.3, x + 0.3, y - 0.3, y + 0.3, HDR_H - 2.5, HDR_H + 0.1))
    for s in (-1, 1):                                           # SMD legs
        x0 = xc + s * HDR_W / 2
        h = h.union(box(min(x0, x0 + s * LEG_W), max(x0, x0 + s * LEG_W), HDR_Y - 5 * PITCH, HDR_Y + 5 * PITCH, 0.0, LEG_H))
    return h


SW_C = (10.78, -9.795)                          # BOOT at (-x, y), RESET at (+x, y); 3.0 x 4.65 over the legs


def tact_switch(xc, yc):
    """SMD tact switch as in the 3D drawing: legs 3.0 x 4.65 x 0.2, body 3.0 x 3.65 up to 1.35, plunger 1.66 x 1.68 up to 2.5"""
    return (box(xc - 1.5, xc + 1.5, yc - 2.325, yc + 2.325, 0.0, 0.2)
            .union(box(xc - 1.5, xc + 1.5, yc - 1.825, yc + 1.825, 0.0, 1.35))
            .union(box(xc - 0.83, xc + 0.83, yc - 0.84, yc + 0.84, 1.35, 2.5)))


def build_parts():
    p = {"pcb": pcb()}
    z_lcd = -T_PCB - GAP_LCD
    p["lcd_panel"] = cq.Workplane("XY").circle(LCD_D / 2).extrude(LCD_T).translate((0, 0, z_lcd - LCD_T))
    p["lcd_viewarea"] = cq.Workplane("XY").circle(LCD_VIEW_D / 2).extrude(0.05).translate((0, 0, z_lcd - LCD_T - 0.05))
    p["hdr_h1"], p["hdr_h2"] = header(-HDR_X), header(HDR_X)
    for k, b in BACK_PARTS.items(): p[k] = box(*b)
    p["sw_boot"], p["sw_reset"] = tact_switch(-SW_C[0], SW_C[1]), tact_switch(SW_C[0], SW_C[1])
    p["usbc"] = p["usbc"].cut(box(-4.15, 4.15, 18.0, 21.2, 0.35, 2.9).edges("|Y").fillet(1.1))   # socket mouth
    return p


IMU_AXES = {"x": (0, 1, 0), "y": (-1, 0, 0), "z": (0, 0, 1)}   # QMI8658 axes in the module frame (silkscreen)


def imu_axes(length=9.0):
    """arrows from the QMI8658 centre along its X/Y/Z axes (for checking the mounting orientation against the sim)"""
    b = BACK_PARTS["qmi8658"]; c = cq.Vector((b[0] + b[1]) / 2, (b[2] + b[3]) / 2, b[5])
    out = {}
    for k, d in IMU_AXES.items():
        d = cq.Vector(*d)
        shaft = cq.Solid.makeCylinder(0.25, length - 1.6, c, d)
        tip = cq.Solid.makeCone(0.7, 0.0, 1.6, c + d * (length - 1.6), d)
        out[f"axis_{k}"] = cq.Workplane("XY").add(shaft.fuse(tip))
    return out


def adapters():
    """both adapters in the module frame: adapter +Z -> module +Z, adapter X (15 long) -> module Y, adapter Y -> module -X"""
    a = ad.build(SPACER)
    out = {}
    for name, xc in (("adapter_h1", -HDR_X), ("adapter_h2", HDR_X)):
        out[name] = a.rotate((0, 0, 0), (0, 0, 1), 90).translate((xc, HDR_Y, Z_ADAPTER))
    return out


def to_head(pts):
    return np.asarray(pts) @ R_HEAD.T + T_HEAD


def main():
    os.makedirs(OUT_RF, exist_ok=True)
    parts, adps, axes = build_parts(), adapters(), imu_axes()
    T = np.eye(4); T[:3, :3] = R_HEAD; T[:3, 3] = T_HEAD
    asm = cq.Assembly(name="RP2040-LCD-1.28")
    for k, s in {**parts, **adps, **axes}.items():
        f = os.path.join(OUT, f"imu_{k}.stl")
        cq.exporters.export(s, f, tolerance=0.01, angularTolerance=0.1)
        m = trimesh.load(f); m.apply_transform(T); m.export(os.path.join(OUT_RF, f"imu_{k}.stl"))
        if k in parts: asm.add(s, name=k)
    asm.save(os.path.join(OUT, "rp2040_lcd_128.step"))
    if SPACER > 0:   # print file of the longer adapter (same print orientation as imu_adapter.stl)
        cq.exporters.export(ad.build(SPACER), os.path.join(OUT, "imu_adapter_flush.stl"), tolerance=0.005, angularTolerance=0.05)
        print(f"flush adapters: spacer {SPACER} mm -> {ad.OUT_W:.2f} x {ad.OUT_H:.2f} x {ad.Z_TOP + SPACER:.2f} mm (stl/imu_adapter_flush.stl)")

    # clearance of the adapters to every part on the back (the header they sit on excluded)
    clear = {}
    for an, a in adps.items():
        own = "hdr_h1" if an.endswith("h1") else "hdr_h2"
        clear[an] = {k: round(a.val().distance(s.val()), 3) for k, s in parts.items() if k not in (own, "pcb", "lcd_panel", "lcd_viewarea")}
        worst = sorted(clear[an].items(), key=lambda kv: kv[1])[:3]
        print(f"{an}: nearest parts " + ", ".join(f"{k} {d:.2f} mm" for k, d in worst))
    rim = Z_ADAPTER
    print(f"adapter rim {rim:.2f} mm above the PCB back face (SMD legs {LEG_H} mm) -> {'clear' if rim > LEG_H else 'SITS ON THE HEADER LEGS'}")

    imu_c = np.array([(BACK_PARTS['qmi8658'][0] + BACK_PARTS['qmi8658'][1]) / 2, (BACK_PARTS['qmi8658'][2] + BACK_PARTS['qmi8658'][3]) / 2,
                      (BACK_PARTS['qmi8658'][4] + BACK_PARTS['qmi8658'][5]) / 2])
    axes_mod = {f"{k}_imu": list(v) for k, v in IMU_AXES.items()}
    pose = dict(
        frame="assembly frame of the pinned CAD (mm): +X robot left, +Y back, +Z up; rigid to the head/torso",
        imu_chip_centre_mm=np.round(to_head(imu_c), 2).tolist(),
        imu_axes_in_robot_frame={k: (R_HEAD @ np.array(v)).round(3).tolist() for k, v in axes_mod.items()},
        module_frame="origin PCB centre on the back face, +Z out of the back, display -Z, +Y to the USB-C tab",
        R_module_to_robot=R_HEAD.tolist(), t_module_to_robot_mm=np.round(T_HEAD, 3).tolist(),
        adapter_seat_above_pcb_mm=Z_ADAPTER, adapter_clearance_mm=clear, display_flush=DISPLAY_FLUSH,
        adapter_spacer_mm=SPACER, adapter_total_length_mm=round(ad.Z_TOP + SPACER, 2),
        measured=["T_STACK 4.0 = PCB 1.6 + air gap 0.8 + display 1.6"], estimated=["HDR_H", "batt height", "LCD_D"])
    json.dump(pose, open(os.path.join(HERE, "imu_pose.json"), "w"), indent=1)
    print("IMU chip centre (robot frame, mm):", pose["imu_chip_centre_mm"], " axes:", pose["imu_axes_in_robot_frame"])
    print("done ->", OUT)


if __name__ == "__main__":
    main()
