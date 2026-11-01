#!/usr/bin/env python3
"""Bambu Studio project (.3mf with ALL print settings) for the TPU 95A foot soles (Robot_Shoes layout).

Takes stl/foot_sole_{left,right}.stl (sole down, open side up, no supports), arranges both on the plate, flattens the P2S machine /
0.20 mm process / Bambu TPU 95A chains itself (the CLI does not resolve `inherits`) and writes the project:

    .cad/bin/python hardware/foot_sole/make_bambu_project.py [--slice]

Output: print/Robot_Shoes_TPU_project.3mf. Open in Bambu Studio and press "Slice plate".
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
FILAMENT = "Bambu TPU 95A @BBL P2S"
BED = "Textured PEI Plate"

# Only what changes the printed structure (final strength) plus the support the part cannot be printed without.
# Everything else (temperatures, fan, layer height, brim, skirt, ...) stays at the P2S standard for PETG Basic.
PROCESS_OVERRIDES = {
    "wall_loops": "3", "sparse_infill_density": "20%", "sparse_infill_pattern": "gyroid",
    "enable_support": "0", "brim_type": "outer_only", "enable_prime_tower": "0",
}
# GUI-side project values of the reference project (single TPU filament, no AMS; the CLI writes defaults)
PROJECT_VALUES = {
    "filament_colour": ["#00000000"], "filament_colour_type": ["2"], "filament_multi_colour": ["#00000000"],
    "flush_volumes_matrix": ["0"], "flush_volumes_vector": ["140", "140"],
    "extruder_ams_count": ["1#0|4#0", "1#0|4#0"], "extruder_nozzle_stats": ["Standard#1"],
    "extruder_nozzle_stats_new": ["Standard#1"],
    "filament_dev_ams_drying_temperature": ["65", "75", "45", "45"],
    "filament_dev_ams_drying_time": ["12", "18", "12", "18"],
    "wipe_tower_x": ["165"], "wipe_tower_y": ["206.296"],
    "host_type": "octoprint", "printhost_authorization_type": "key", "printhost_ssl_ignore_revoke": "0",
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
                cfg.update(PROJECT_VALUES)
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
    shutil.copy(HERE / "stl" / "foot_sole_left.stl", tmp / "foot_sole_left.stl")
    shutil.copy(HERE / "stl" / "foot_sole_right.stl", tmp / "foot_sole_right.stl")
    out = tmp / "out"
    out.mkdir(exist_ok=True)
    cmd = ["flatpak", "run", "com.bambulab.BambuStudio",
           "--load-settings", "machine.json;process.json", "--load-filaments", "filament.json",
           "--arrange", "1", "--orient", "0", "--curr-bed-type", BED] + (["--slice", "0"] if a.slice else []) + [
           "--outputdir", "out", "--export-3mf", "project.3mf", "foot_sole_left.stl", "foot_sole_right.stl"]
    r = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True)
    proj = out / "project.3mf"
    if not proj.is_file():
        print(r.stdout[-1500:], r.stderr[-1500:])
        sys.exit("CLI produced no project")
    PRINT.mkdir(exist_ok=True)
    dst = PRINT / "Robot_Shoes_TPU_project.3mf"
    shutil.copy(proj, dst)
    mark_changes(dst)
    print("wrote", dst.relative_to(HERE.parent.parent))
    if not a.slice:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
