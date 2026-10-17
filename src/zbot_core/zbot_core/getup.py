"""Get-up after a fall: which demo stands the robot back up.

hardware/getup.json assigns one ordinary demo to each of the two ways the
robot can come to rest on the floor:

    front   lying face down (it fell forwards)
    back    lying on its back (it fell backwards)

The demos are normal teach-in demos (demos/*.json) — edited, saved and played
like any other. The GUI can seed one by copying a range of steps out of an
existing demo (e.g. the stand-up tail of push_ups) into a new demo, but after
that the copy is independent. A robot that lies on its side is sent down the
case it is closer to (see pi_service/posture.py).

The same file holds the fall detector's thresholds and the opt-in switch for
the automatic get-up on the Pi:

    {"front": "getup_front", "back": "getup_back",
     "auto": false, "fallen_deg": 45, "upright_deg": 35,
     "hold_s": 15, "still_dps": 30, "max_attempts": 2}
"""

from pydantic import BaseModel, Field, model_validator

from .config import ConfigStore, Demo

CASES = ("front", "back")
CASE_LABEL = {"front": "face down", "back": "on its back"}


class GetupConfig(BaseModel):
    front: str = Field("", max_length=40)     # demo name, "" = none assigned
    back: str = Field("", max_length=40)
    # automatic get-up on the Pi (opt-in: a robot that stands up on its own
    # while somebody holds it horizontal is a hazard)
    auto: bool = False
    # fall detector, torso tilt from gravity (0 deg = upright)
    fallen_deg: float = Field(60.0, ge=30, le=85)
    upright_deg: float = Field(35.0, ge=5, le=60)
    hold_s: float = Field(1.5, ge=0.2, le=60)       # lying still this long before acting
    still_dps: float = Field(30.0, ge=5, le=200)    # "still" = every gyro axis below this
    max_attempts: int = Field(2, ge=1, le=5)        # automatic tries per fall

    @model_validator(mode="after")
    def _thresholds(self):
        if self.upright_deg >= self.fallen_deg:
            raise ValueError("upright_deg must be below fallen_deg")
        return self

    def demo_name(self, case: str) -> str:
        if case not in CASES:
            raise ValueError(f"unknown get-up case '{case}' (front | back)")
        return getattr(self, case)


def load_getup(cfg: ConfigStore) -> GetupConfig:
    """The stored config; a missing file is the empty default. A broken file
    (including the old step-range format) raises ValueError (pydantic's
    ValidationError is one)."""
    return GetupConfig(**cfg.getup_raw())


def save_getup(cfg: ConfigStore, gc: GetupConfig) -> None:
    cfg.write_getup(gc.model_dump())


def validate_getup(cfg: ConfigStore, gc: GetupConfig) -> list[str]:
    """Problems of the assignment against the demos under this root (empty =
    fine). Not a hard error on save: the demo may land on the robot later."""
    out = []
    for case in CASES:
        name = gc.demo_name(case)
        if not name:
            continue
        try:
            cfg.load_demo(name)
        except (KeyError, ValueError):
            out.append(f"{case}: demo '{name}' not found")
    return out


def describe(gc: GetupConfig, case: str) -> str:
    return gc.demo_name(case) or "–"


def load_getup_demo(cfg: ConfigStore, gc: GetupConfig, case: str) -> Demo:
    """The demo assigned to one case, ready for play_demo(). Raises
    ValueError when nothing is assigned or the demo is gone."""
    name = gc.demo_name(case)
    if not name:
        raise ValueError(f"no get-up demo assigned for '{case}' "
                         f"({CASE_LABEL[case]}) — assign one in the GUI")
    try:
        return cfg.load_demo(name)
    except (KeyError, ValueError) as e:
        raise ValueError(f"get-up '{case}': demo '{name}' not found") from e
