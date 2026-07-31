"""Repo-config I/O for the Zeroth-01 build.

All calibration and motion data lives as JSON in the repo (see
docs/User_Manual.md §6). A ConfigStore binds those files to a *root*
directory: the repo checkout on the laptop, a synced copy on the Pi.
Writes are atomic (temp file + os.replace) so concurrent readers — e.g.
the GUI's 250 ms live poll — never see a half-written file.
"""

import json
import os
import re
from pathlib import Path

from pydantic import BaseModel, Field


def write_json_atomic(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path, default):
    if path.exists():
        # utf-8-sig: tolerate a UTF-8 BOM — Windows editors/redirects
        # (PowerShell!) routinely prepend one to hand-edited configs
        return json.loads(path.read_text(encoding="utf-8-sig"))
    return default


# ------------------------------------------------------------ demo format

class DemoStep(BaseModel):
    angles: dict[str, float]           # joint name -> target angle (CAD deg)
    speed: int = Field(500, ge=1, le=3400)
    acc: int = Field(50, ge=0, le=254)
    pause_s: float = Field(0.0, ge=0, le=10)


class Demo(BaseModel):
    name: str = Field(min_length=1, max_length=40,
                      pattern=r"^[A-Za-z0-9_\- ]+$")
    description: str = ""
    steps: list[DemoStep] = Field(min_length=1)


def demo_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "_", name.strip().lower()).strip("_")
    if not slug:
        raise ValueError("Invalid demo name.")
    return slug


# ------------------------------------------------------------ config store

# Connection defaults: how a host reaches the servo bus / the Pi service.
# "port": "auto" = pick the single USB serial adapter (works for COMx and
# /dev/tty*); an explicit value pins it (prefer /dev/serial/by-id/... on Pi).
DEFAULT_CONNECTION = {
    "mode": "usb",                          # "usb" (local) | "wireless" (Pi)
    "port": "auto",
    "pi_url": "http://pixel.local:8460",
}

class ConfigStore:
    """Paths + typed accessors for the build's JSON configs under one root."""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        hw = self.root / "hardware"
        self.servo_ids_path = hw / "servo_ids.json"
        self.limits_path = hw / "joint_limits.json"
        self.offsets_path = hw / "joint_offsets.json"
        self.model_zero_path = hw / "model_zero_offsets.json"
        self.model_invert_path = hw / "model_invert.json"
        self.connection_path = hw / "connection.json"
        self.demos_dir = self.root / "demos"
        hw.mkdir(parents=True, exist_ok=True)
        self.demos_dir.mkdir(parents=True, exist_ok=True)

    # -- reads (missing file -> empty dict, same semantics as before)
    def servo_ids(self) -> dict:
        return read_json(self.servo_ids_path, {})

    def limits(self) -> dict:
        return read_json(self.limits_path, {})

    def offsets(self) -> dict:
        return read_json(self.offsets_path, {})

    def model_zero(self) -> dict:
        return read_json(self.model_zero_path, {})

    def model_invert(self) -> dict:
        return read_json(self.model_invert_path, {})

    def connection(self) -> dict:
        return {**DEFAULT_CONNECTION, **read_json(self.connection_path, {})}

    # -- writes (atomic)
    def write_servo_ids(self, d: dict) -> None:
        write_json_atomic(self.servo_ids_path, d)

    def write_limits(self, d: dict) -> None:
        write_json_atomic(self.limits_path, d)

    def write_offsets(self, d: dict) -> None:
        write_json_atomic(self.offsets_path, d)

    def write_model_zero(self, d: dict) -> None:
        write_json_atomic(self.model_zero_path, d)

    def write_model_invert(self, d: dict) -> None:
        write_json_atomic(self.model_invert_path, d)

    # -- demos
    def demo_path(self, name: str) -> Path:
        return self.demos_dir / f"{demo_slug(name)}.json"

    def load_demo(self, name: str) -> Demo:
        path = self.demo_path(name)
        if not path.exists():
            raise KeyError(f"Demo '{name}' not found.")
        return Demo(**json.loads(path.read_text(encoding="utf-8")))

    def load_demos(self, on_invalid=None) -> list[dict]:
        out = []
        if self.demos_dir.exists():
            for f in sorted(self.demos_dir.glob("*.json")):
                try:
                    out.append(Demo(**json.loads(
                        f.read_text(encoding="utf-8"))).model_dump())
                except Exception:                    # skip broken files
                    if on_invalid:
                        on_invalid(f.name)
        return out

    def save_demo(self, d: Demo) -> Path:
        path = self.demo_path(d.name)
        write_json_atomic(path, d.model_dump())
        return path

    def delete_demo(self, name: str) -> bool:
        path = self.demo_path(name)
        if path.exists():
            path.unlink()
            return True
        return False
