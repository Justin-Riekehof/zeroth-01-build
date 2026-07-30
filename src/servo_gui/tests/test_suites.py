"""Regression net: runs every verification suite in a FRESH interpreter.

Each suite in tests/suites/ is a self-contained script (imports the server
module, patches its config paths to temp dirs, drives the API with fake
buses and prints PASS/FAIL lines). Subprocess isolation keeps the server's
global state clean between suites — exactly how they were verified during
bring-up. A suite passes iff it exits 0 and printed no FAIL.
"""

import subprocess
import sys
from pathlib import Path

import pytest

SUITES = sorted((Path(__file__).parent / "suites").glob("test_*.py"))
SERVO_GUI_DIR = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("suite", SUITES, ids=lambda p: p.stem)
def test_suite(suite: Path):
    r = subprocess.run([sys.executable, str(suite)], capture_output=True,
                       text=True, timeout=300, cwd=SERVO_GUI_DIR)
    out = r.stdout + "\n" + r.stderr
    assert r.returncode == 0, out
    assert "FAIL" not in out, out
    assert "PASS" in out, out
