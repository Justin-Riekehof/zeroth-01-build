"""Pi intent service against the SimBus — no hardware required.

Covers the full intent surface: status, demo listing/playback (with hold),
E-stop, busy rejection, center (offset-aware), release, the corrupt-limits
guard, and the heartbeat-watchdog scaffold."""
import time

from zbot_core.config import Demo

import service

CENTER = 2048
TOL = 26        # engine TOLERANCE (25) + rounding


def wait_idle(client, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        live = client.get("/status").json()["live"]
        if not live["running"]:
            return live
        time.sleep(0.03)
    raise AssertionError("run did not finish in time")


def logs(client):
    # log entries are {"seq": n, "msg": text} dicts
    return "\n".join(
        e["msg"] for e in client.get("/status").json()["live"]["log"])


def save_wave():
    service.CFG.save_demo(Demo(name="wave", steps=[
        {"angles": {"right_shoulder_pitch": 45.0}, "speed": 3400, "acc": 150},
        {"angles": {"right_shoulder_pitch": 0.0}, "speed": 3400, "acc": 150},
    ]))


def save_pause_demo():
    service.CFG.save_demo(Demo(name="slow", steps=[
        {"angles": {"right_elbow": 20.0}, "speed": 3400, "acc": 150,
         "pause_s": 8.0},
    ]))


# ------------------------------------------------------------ status / demos

def test_status_shape(client):
    r = client.get("/status")
    assert r.status_code == 200
    j = r.json()
    assert j["api_version"] == service.API_VERSION
    assert j["simulate"] is True
    assert j["bus"] == {"connected": True, "port": "simulator",
                        "simulated": True}
    assert j["watchdog"]["armed"] is False
    assert "running" in j["live"] and "log" in j["live"]


def test_connect_idempotent(client):
    r = client.post("/connect")
    assert r.status_code == 200 and r.json()["port"] == "simulator"


def test_demos_lists_saved(client):
    assert client.get("/demos").json()["demos"] == []
    save_wave()
    demos = client.get("/demos").json()["demos"]
    assert [d["name"] for d in demos] == ["wave"]
    assert len(demos[0]["steps"]) == 2


def test_unknown_demo_404(client):
    assert client.post("/demo/nope").status_code == 404
    assert client.post("/demo/%20").status_code == 404   # invalid slug


# ------------------------------------------------------------ demo playback

def test_demo_plays_and_holds(client):
    save_wave()
    r = client.post("/demo/wave")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "demo": "wave", "steps": 2}
    live = wait_idle(client)
    assert live["phase"] == "done" and live["error"] is None
    out = logs(client)
    assert "demo 'wave' finished — holding final pose" in out
    assert "holding center with torque ON: IDs [11]" in out
    # final step returns the joint to 0 deg -> center ticks
    assert abs(service.S.bus.read_pos(11) - CENTER) <= TOL


def test_stop_is_estop(client):
    save_pause_demo()
    assert client.post("/demo/slow").status_code == 200
    time.sleep(0.15)                      # let the run start
    r = client.post("/stop")
    assert r.status_code == 200
    assert r.json()["released"] == []     # the aborted runner does the release
    live = wait_idle(client, timeout=3.0)  # must NOT wait out the 8 s pause
    assert live["phase"] == "aborted"
    out = logs(client)
    assert "group run aborted" in out
    assert "torque disabled (all selected)" in out


def test_stop_releases_held_pose(client):
    # after a demo the robot HOLDS the final pose with torque on and
    # running=False — Stop must still be an E-stop, not a silent no-op
    save_wave()
    assert client.post("/demo/wave").status_code == 200
    wait_idle(client)
    r = client.post("/stop")
    assert r.status_code == 200
    assert r.json()["released"] == [11, 13]
    assert "E-STOP: torque released: IDs [11, 13]" in logs(client)


def test_second_run_rejected_while_busy(client):
    save_pause_demo()
    assert client.post("/demo/slow").status_code == 200
    r = client.post("/demo/slow")
    assert r.status_code == 400
    assert "already in progress" in r.json()["detail"]
    client.post("/stop")
    wait_idle(client, timeout=3.0)


# ------------------------------------------------------------ center / release

def test_center_applies_offsets_and_holds(client):
    service.CFG.write_offsets({"right_elbow": 90.0})
    r = client.post("/center", json={"hold": True, "speed": 3400})
    assert r.status_code == 200 and r.json()["joints"] == 2
    live = wait_idle(client)
    assert live["phase"] == "done"
    assert "holding center with torque ON: IDs [11, 13]" in logs(client)
    assert abs(service.S.bus.read_pos(11) - CENTER) <= TOL
    # mounted 90 deg off -> center sits at tick 3072, not 2048
    assert abs(service.S.bus.read_pos(13) - 3072) <= TOL


def test_release_all_and_subset(client):
    r = client.post("/release")
    assert r.status_code == 200 and r.json()["released"] == [11, 13]
    assert "torque released: IDs [11, 13]" in logs(client)
    r = client.post("/release", json={"joints": ["right_elbow"]})
    assert r.json()["released"] == [13]


def test_release_rejected_during_run(client):
    save_pause_demo()
    assert client.post("/demo/slow").status_code == 200
    time.sleep(0.15)
    r = client.post("/release")
    assert r.status_code == 400 and "stop" in r.json()["detail"].lower()
    client.post("/stop")
    wait_idle(client, timeout=3.0)


# ------------------------------------------------------------ safety guards

def test_corrupt_limits_rejected(client):
    save_wave()
    service.CFG.write_limits(
        {"right_shoulder_pitch": {"min_deg": 90.0, "max_deg": 176.4}})
    r = client.post("/demo/wave")
    assert r.status_code == 400
    assert "exclude its zero position" in r.json()["detail"]
    r = client.post("/center")
    assert r.status_code == 400


def test_bom_config_tolerated(client):
    # PowerShell redirects prepend a UTF-8 BOM; configs must still parse
    # (this took the service down on the very first real deploy)
    service.CFG.connection_path.write_bytes(
        b'\xef\xbb\xbf{"port": "/dev/serial/by-id/usb-test"}')
    try:
        assert service.CFG.connection()["port"] == "/dev/serial/by-id/usb-test"
    finally:
        service.CFG.connection_path.unlink()


def test_malformed_config_degrades_to_warning():
    # a broken connection.json must not brick startup (systemd restart loop):
    # _connect_bus reports instead of raising
    service.CFG.connection_path.write_text("{not json", encoding="utf-8")
    saved = service.S.bus
    try:
        with service.S.lock:
            service.S.bus = None
        err = service._connect_bus()
        assert err is not None and "JSONDecodeError" in err
    finally:
        with service.S.lock:
            service.S.bus = saved
        service.CFG.connection_path.unlink()


def test_watchdog_soft_hold(client):
    save_pause_demo()
    service.WATCHDOG.timeout_s = 0.12
    try:
        # heartbeat alone never arms — demos don't need the watchdog
        assert client.post("/heartbeat").json()["armed"] is False
        service.WATCHDOG.arm()             # future streaming session starts
        assert client.post("/demo/slow").status_code == 200
        time.sleep(0.5)                    # ... and stops heartbeating
        live = wait_idle(client, timeout=3.0)
        assert live["phase"] == "aborted"
        assert "WATCHDOG: heartbeat lost — soft hold" in logs(client)
        assert service.WATCHDOG.armed is False
        # /stop must also disarm
        service.WATCHDOG.arm()
        client.post("/stop")
        assert client.get("/status").json()["watchdog"]["armed"] is False
    finally:
        service.WATCHDOG.disarm()
        service.WATCHDOG.timeout_s = 0.5
