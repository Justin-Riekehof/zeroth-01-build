"""Test env must be pinned BEFORE service.py is imported (module-level
ConfigStore/engine): config root -> tmp dir, bus -> SimBus."""
import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="zbot_pi_test_"))
os.environ["ZBOT_ROOT"] = str(TMP)
os.environ["ZBOT_SIMULATE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient

import service


@pytest.fixture(scope="session")
def client():
    # context manager runs the startup hook (connects the SimBus)
    with TestClient(service.app) as c:
        # the battery thread would race the tests' hand-driven tick()s
        # (and could halt the CI box with a low SimBus voltage): stop it
        service.BATTERY.stop()
        yield c


@pytest.fixture
def battery(client):
    """Battery monitor with fresh state; SimBus voltage restored afterwards."""
    b = service.BATTERY
    b.reset()
    bus = service.S.bus
    bus.voltage = 12.3
    yield b
    bus.voltage = 12.3
    b.reset()


@pytest.fixture(autouse=True)
def base_config():
    """Fresh known-good config per test; no run left in progress."""
    cfg = service.CFG
    cfg.write_servo_ids({"right_shoulder_pitch": 11, "right_elbow": 13})
    cfg.write_limits({
        "right_shoulder_pitch": {"min_deg": -90.0, "max_deg": 90.0},
        "right_elbow": {"min_deg": -90.0, "max_deg": 90.0},
    })
    cfg.write_offsets({})
    # engine tests run at register-max speed so the SimBus settles instantly;
    # the power-limit test writes its own (default) limits
    cfg.write_motion_limits({"max_speed": 3400, "max_acc": 254})
    for f in cfg.demos_dir.glob("*.json"):
        f.unlink()
    yield
    service.ENGINE.stop()
