"""Battery monitor against the SimBus: voltage in /status, level
hysteresis, and the clean OS halt that must come BEFORE the XY-CD63
hardware cutoff — driven by hand-fed monotonic timestamps."""
import subprocess as sp
import time

import pytest

import service
from service import BatteryMonitor

from test_service import logs, save_pause_demo, wait_idle


def ok_halt(calls):
    def f():
        calls.append(1)
        return sp.CompletedProcess(service.SHUTDOWN_CMD, 0, "", "")
    return f


def test_status_reports_voltage(client, battery):
    battery.tick(100.0)
    b = client.get("/status").json()["battery"]
    assert b["volts"] == 12.3 and b["level"] == "ok"
    assert b["servo_id"] == 11              # lowest configured ID answered
    assert b["shutdown"] is None and b["error"] is None
    assert b["warn_v"] == 11.1 and b["shutdown_v"] == 10.8


def test_defaults_are_ordered():
    d = BatteryMonitor.DEFAULTS
    assert d["shutdown_v"] < d["warn_v"]
    with pytest.raises(ValueError):
        BatteryMonitor(service.ENGINE, service.CFG, lambda: None,
                       {"warn_v": 10.5, "shutdown_v": 10.8})


def test_warn_level_logs_once_with_hysteresis(client, battery):
    bus = service.S.bus
    bus.voltage = 11.0
    battery.tick(100.0)
    assert battery.level == "warn"
    assert "BATTERY: 11.0 V (ID 11) — low, charge soon" in logs(client)
    n = logs(client).count("BATTERY:")
    bus.voltage = 11.2                       # inside the 0.2 V hysteresis
    battery.tick(102.0)
    assert battery.level == "warn" and logs(client).count("BATTERY:") == n
    bus.voltage = 11.4
    battery.tick(104.0)
    assert battery.level == "ok"
    assert "BATTERY: 11.4 V — recovered" in logs(client)


def test_short_sag_does_not_halt(client, battery, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "_do_shutdown", ok_halt(calls))
    bus = service.S.bus
    bus.voltage = 10.5
    battery.tick(100.0)
    battery.tick(104.0)                      # 4 s < hold_s (10 s)
    assert battery.level == "low" and not calls
    bus.voltage = 12.0                       # servo inrush over
    battery.tick(106.0)
    battery.tick(120.0)
    assert battery.level == "ok" and not calls
    assert client.get("/status").json()["battery"]["low_for_s"] is None


def test_sustained_low_voltage_halts_once(client, battery, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "_do_shutdown", ok_halt(calls))
    bus = service.S.bus
    bus.voltage = 10.7
    battery.tick(100.0)
    battery.tick(109.9)
    assert not calls
    battery.tick(110.0)                      # hold_s reached
    assert calls == [1]
    l = logs(client)
    assert "BATTERY: 10.7 V for 10 s — stopping the run" in l
    assert "SHUTDOWN: OS halting (battery)" in l
    battery.tick(112.0)
    battery.tick(500.0)                      # never twice
    assert calls == [1]
    assert client.get("/status").json()["battery"]["shutdown"] == "halting"


def test_hovering_at_threshold_keeps_the_timer(client, battery, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "_do_shutdown", ok_halt(calls))
    bus = service.S.bus
    for t, v in ((100.0, 10.7), (102.0, 10.9), (104.0, 10.7), (106.0, 10.85),
                 (108.0, 10.7)):
        bus.voltage = v
        battery.tick(t)
    assert not calls
    battery.tick(110.0)
    assert calls == [1]


def test_low_voltage_aborts_a_running_demo_first(client, battery,
                                                 monkeypatch):
    order = []

    def halt():
        order.append(("halt", service.S.live["running"]))
        return sp.CompletedProcess(service.SHUTDOWN_CMD, 0, "", "")
    monkeypatch.setattr(service, "_do_shutdown", halt)
    save_pause_demo()
    assert client.post("/demo/slow").status_code == 200
    time.sleep(0.15)
    assert service.S.live["running"]
    bus = service.S.bus
    bus.voltage = 10.0
    battery.tick(100.0)
    battery.tick(111.0)
    assert order == [("halt", False)]        # run aborted before the halt
    wait_idle(client, timeout=3.0)


def test_failed_halt_is_logged_and_retried(client, battery, monkeypatch):
    calls = []

    def fail():
        calls.append(1)
        return sp.CompletedProcess(service.SHUTDOWN_CMD, 1, "",
                                   "sudo: a password is required")
    monkeypatch.setattr(service, "_do_shutdown", fail)
    bus = service.S.bus
    bus.voltage = 10.0
    battery.tick(100.0)
    battery.tick(110.0)
    assert calls == [1]
    assert "BATTERY: shutdown FAILED — sudoers rule" in logs(client)
    assert client.get("/status").json()["battery"]["shutdown"] == "failed"
    battery.tick(150.0)                      # < retry_s (60 s)
    assert calls == [1]
    battery.tick(171.0)
    assert calls == [1, 1]


def test_no_reading_keeps_state_and_never_halts(client, battery, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "_do_shutdown", ok_halt(calls))
    bus = service.S.bus
    bus.voltage = 10.0
    battery.tick(100.0)
    bus.voltage = None                       # servo silent
    battery.tick(120.0)
    b = client.get("/status").json()["battery"]
    assert b["error"] == "no servo answers" and b["volts"] == 10.0
    assert b["level"] == "unknown"           # stale for > 5 periods
    assert not calls                         # no data -> no decision


def test_disconnected_bus_reports_error(client, battery):
    with service.S.lock:
        bus, service.S.bus = service.S.bus, None
    try:
        battery.tick(100.0)
        assert battery.error == "bus not connected" and battery.volts is None
    finally:
        with service.S.lock:
            service.S.bus = bus


def test_halt_warns_the_head_display_first(client, battery, monkeypatch):
    order = []
    monkeypatch.setattr(service.IMU, "send", lambda line: (order.append(line), True)[1])
    monkeypatch.setattr(service, "_do_shutdown", lambda: (
        order.append("halt"), sp.CompletedProcess(service.SHUTDOWN_CMD, 0, "", ""))[1])
    bus = service.S.bus
    bus.voltage = 10.0
    battery.tick(100.0)
    battery.tick(110.0)
    assert order == ["alert battery", "halt"]      # warning on the robot BEFORE the halt
