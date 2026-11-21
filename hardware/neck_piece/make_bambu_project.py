#!/usr/bin/env python3
"""Bambu Studio project (.3mf with ALL print settings) for the reinforced neck piece (PETG).

Bambu Studio's CLI does not resolve `inherits` of the system presets, so this script flattens the P2S machine /
0.20 mm process / PETG Basic filament chains itself, applies the few OVERRIDES below and lets the CLI write the project:

    .cad/bin/python hardware/neck_piece/make_bambu_project.py            # the plate
    .cad/bin/python hardware/neck_piece/make_bambu_project.py --slice    # also slice (checks support, prints time)

Needs the Bambu Studio flatpak (com.bambulab.BambuStudio) and the geometry plates from make_print.py.
Output: print/neck_piece_PETG_front_project.3mf, open it in Bambu Studio and press "Slice plate".
"""
import argparse
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRINT = HERE / "print"
SYS = Path.home() / ".var/app/com.bambulab.BambuStudio/config/BambuStudio/system/BBL"
MACHINE = "Bambu Lab P2S 0.4 nozzle"
PROCESS = "0.20mm Standard @BBL P2S"
FILAMENT = "Bambu PETG Basic @BBL P2S 0.4 nozzle"
BED = "Textured PEI Plate"

# Only what changes the printed structure (final strength) plus the support the part cannot be printed without
# (claw front on the bed: under the flat front faces of lugs and skirt and under the tongue). 5 walls + 40 % gyroid
# make the screw lugs (16.5 x 24.6 mm around the hex shaft) nearly solid. Everything else stays at the P2S standard for PETG Basic.
# Support: normal(auto), snug. History (2026-11-07): with the default tree style the free-standing tree in front of the
# part (under the tongue, 21 mm high) had a ~3 mm waist and was knocked over in the first print -> spaghetti above.
# tree_strong + 8 mm branches made it thicker, but the branches became hollow 2-wall tubes ending in open rings at the
# part edge. Normal snug support is a closed grid block on the full footprint (front ~20 x 10 mm on the bed), the
# block in the claw/lug gap is pried out from the open back. 47.8 g, 1 h 56 min.
PROCESS_OVERRIDES = {
    "wall_loops": "5", "sparse_infill_density": "40%", "sparse_infill_pattern": "gyroid",
    "enable_support": "1", "support_type": "normal(auto)", "support_style": "snug",
}
FILAMENT_OVERRIDES = {}


def find(kind, name):
    p = SYS / kind / f"{name}.json"
    if not p.is_file():
        sys.exit(f"preset not found: {p}")
    return json.loads(p.read_text())


def flatten(kind, name, seen=()):
    """parent first, then `include` templates, then the file's own keys."""
    d = find(kind, name)
    out = {}
    if d.get("inherits"):
        out.update(flatten(kind, d["inherits"]))
    for inc in d.get("include", []):
        out.update(flatten(kind, inc))
    out.update({k: v for k, v in d.items() if k not in ("inherits", "include")})
    return out


def mark_changes(proj: Path):
    """The GUI loads the named system presets and applies only the keys listed in `different_settings_to_system`
    (process; each filament; printer). The CLI leaves it empty, so without this every override is ignored."""
    cfg_name = "Metadata/project_settings.config"
    tmp = proj.with_suffix(".tmp")
    with zipfile.ZipFile(proj) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == cfg_name:
                cfg = json.loads(data)
                cfg["different_settings_to_system"] = [";".join(PROCESS_OVERRIDES), ";".join(FILAMENT_OVERRIDES), ""]
                data = json.dumps(cfg, indent=4).encode()
            zout.writestr(item, data)
    tmp.replace(proj)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", action="store_true", help="also slice (project then contains G-code)")
    a = ap.parse_args()
    tmp = HERE / "_cli"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    m, p, f = flatten("machine", MACHINE), flatten("process", PROCESS), flatten("filament", FILAMENT)
    p.update(PROCESS_OVERRIDES)
    f.update(FILAMENT_OVERRIDES)
    for d, n, t in ((m, "machine", "machine"), (p, "process", "process"), (f, "filament", "filament")):
        d.update({"type": t, "name": {"machine": MACHINE, "process": PROCESS, "filament": FILAMENT}[t], "from": "system"})
        (tmp / f"{n}.json").write_text(json.dumps(d, indent=1))
    for plate in sorted(PRINT.glob("neck_piece_PETG_*.3mf")):
        if plate.stem.endswith("_project"):
            continue
        shutil.copy(plate, tmp / "in.3mf")
        out = tmp / "out"
        out.mkdir(exist_ok=True)
        cmd = ["flatpak", "run", "com.bambulab.BambuStudio",
               "--load-settings", "machine.json;process.json", "--load-filaments", "filament.json",
               "--arrange", "0", "--orient", "0", "--curr-bed-type", BED] + (["--slice", "0"] if a.slice else []) + [
               "--outputdir", "out", "--export-3mf", "project.3mf", "in.3mf"]
        r = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True)
        proj = out / "project.3mf"
        if not proj.is_file():
            print(r.stdout[-1500:], r.stderr[-1500:])
            sys.exit(f"CLI produced no project for {plate.name}")
        dst = plate.with_name(plate.stem + "_project.3mf")
        shutil.copy(proj, dst)
        mark_changes(dst)
        print("wrote", dst.relative_to(HERE.parent.parent))
    if not a.slice:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
