"""Flight recorder: a fsync'ed log file on the Pi with boot, engine and vitals lines."""
import time

import service


def test_flight_recorder_writes_boot_engine_and_vitals(client):
    p = service.FLIGHT.path()
    assert p.exists(), p
    service.S.log("flight test marker")
    r = client.get("/flight", params={"n": 500})
    assert r.status_code == 200
    lines = r.json()["lines"]
    assert any(l.split(None, 2)[2].startswith("boot") for l in lines if len(l.split(None, 2)) > 2) or any(" boot " in l for l in lines)
    assert any("engine flight test marker" in l for l in lines)
    v = service.FLIGHT.vitals()
    assert "pack " in v and "throttled" in v and "load" in v
