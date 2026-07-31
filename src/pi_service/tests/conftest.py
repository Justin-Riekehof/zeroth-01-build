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
        yield c


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
    for f in cfg.demos_dir.glob("*.json"):
        f.unlink()
    yield
    service.ENGINE.stop()
