"""Head peripherals without hardware: IMU line parsing (both firmware
formats), head-frame tilt, MJPEG frame splitting, and the HTTP surface
under simulation (no board, no camera binary)."""
from unittest import mock

import head
import service

DEMO_LINES = [
    "acc_x   = 295.166mg , acc_y  = 1065.186mg , acc_z  = 158.203mg\r\n",
    "gyro_x  = -0.125dps, gyro_y = -7.328dps, gyro_z = -0.219dps\r\n",
    "tim_count = 353052\r\n",
    "Raw value: 0xa43, voltage: 4.232959 V\r\n",
]


# ------------------------------------------------------------ parsing

def test_demo_format_merges_three_lines():
    p = head.ImuParser()
    out = [p.feed(l) for l in DEMO_LINES]
    samples = [s for s in out if s]
    assert len(samples) == 1
    s = samples[0]
    assert s["source"] == "demo"
    assert s["ax"] == 295.166 and s["gy"] == -7.328
    assert "vsys" not in s                  # voltage line comes AFTER
    # second sample picks up the remembered voltage
    out = [p.feed(l) for l in DEMO_LINES[:2]]
    assert [s for s in out if s][0]["vsys"] == 4.232959


def test_json_format_one_line_per_sample():
    p = head.ImuParser()
    s = p.feed('{"ax":1,"ay":2,"az":3,"gx":4,"gy":5,"gz":6,"t":31.5,'
               '"v":4.2,"mood":"happy"}\n')
    assert s["source"] == "json" and s["temp_c"] == 31.5
    assert s["vsys"] == 4.2 and s["mood"] == "happy"
    assert p.feed("{not json") is None
    assert p.feed('{"ax": 1}') is None       # incomplete
    assert p.feed("") is None


def test_tilt_upright_and_nose_down():
    axes = {"up": "+y", "forward": "-z"}
    up = {"ax": 0, "ay": 1000, "az": 0}
    t = head.head_tilt(up, axes)
    assert t == {"pitch_deg": 0.0, "roll_deg": 0.0, "tilt_deg": 0.0}
    # nose 30° down: the forward axis (-z) dips, so it reads NEGATIVE, i.e.
    # +z goes positive (measured on the robot 2026-09-22: z -7 -> +760 mg)
    import math
    nose = {"ax": 0, "ay": 1000 * math.cos(math.radians(30)),
            "az": +1000 * math.sin(math.radians(30))}
    t = head.head_tilt(nose, axes)
    assert t["pitch_deg"] == 30.0 and t["roll_deg"] == 0.0
    assert t["tilt_deg"] == 30.0
    # right ear down: right = forward x up = (-z) x (+y) = +x, which dips
    # (measured: x +55 -> -750 mg)
    ear = {"ax": -1000 * math.sin(math.radians(20)),
           "ay": 1000 * math.cos(math.radians(20)), "az": 0}
    assert head.head_tilt(ear, axes)["roll_deg"] == 20.0


def test_tilt_degenerate_axes():
    t = head.head_tilt({"ax": 0, "ay": 1, "az": 0},
                       {"up": "+y", "forward": "-y"})
    assert t["pitch_deg"] is None


def test_split_jpegs_handles_partial_frames():
    a = b"\xff\xd8\xff\xe0AAAA\xff\xd9"
    b = b"\xff\xd8\xff\xdbBBBBBB\xff\xd9"
    buf = bytearray(b"junk" + a + b[:5])
    assert head.split_jpegs(buf) == [a]
    assert bytes(buf) == b[:5]              # partial frame kept, junk dropped
    buf += b[5:] + b"\xff\xd8"
    assert head.split_jpegs(buf) == [b]
    assert bytes(buf) == b"\xff\xd8"        # lone SOI prefix waits for more
    buf = bytearray(b"no markers at all")
    assert head.split_jpegs(buf) == [] and buf == b"ll"   # 2-byte tail kept


def test_find_imu_port_skips_servo_adapter(tmp_path):
    names = ["/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B8E-if00",
             "/dev/serial/by-id/usb-Raspberry_Pi_Pico_E663-if00"]
    with mock.patch("glob.glob", return_value=names):
        assert head.find_imu_port() == names[1]
        assert head.find_imu_port(exclude=names[1]) is None
    names.append("/dev/serial/by-id/usb-MicroPython_Board_in_FS_mode_e663-if00")
    with mock.patch("glob.glob", return_value=names):
        assert head.find_imu_port().endswith("FS_mode_e663-if00")


# ------------------------------------------------------------ HTTP surface

def test_status_carries_head_state(client):
    j = client.get("/status").json()
    assert j["api_version"] == service.API_VERSION == 8
    assert j["head"]["imu"]["connected"] is False       # simulate: disabled
    assert j["head"]["imu"]["sample"] is None
    assert "streaming" in j["head"]["camera"]
    assert client.get("/head").json()["imu"]["error"].startswith("disabled")


def test_camera_503_without_binary(client):
    with mock.patch.object(head.shutil, "which", return_value=None):
        r = client.get("/camera.mjpg")
        assert r.status_code == 503 and "not installed" in r.json()["detail"]
        assert client.get("/camera.jpg").status_code == 503


def test_camera_stream_from_fake_process(client, tmp_path):
    """A stand-in for rpicam-vid: emits two JPEG-like frames, then exits."""
    fake = tmp_path / "fakecam.py"
    fake.write_text(
        "import sys, time\n"
        "for i in range(2):\n"
        "    sys.stdout.buffer.write(b'\\xff\\xd8\\xff\\xe0' + bytes([65+i])*8"
        " + b'\\xff\\xd9'); sys.stdout.flush(); time.sleep(0.05)\n"
        "time.sleep(0.5)\n")
    import sys
    cam = head.CameraStreamer(binary=sys.executable)
    cam._cmd = lambda: [sys.executable, str(fake)]
    with mock.patch.object(service, "CAMERA", cam):
        r = client.get("/camera.jpg")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/jpeg"
        assert r.content.startswith(b"\xff\xd8") and r.content.endswith(b"\xff\xd9")
        st = client.get("/head").json()["camera"]
        assert st["clients"] == 0
    cam.stop()


def test_head_cmd_without_board_is_503(client):
    r = client.post("/head/cmd", json={"line": "mood happy"})
    assert r.status_code == 503
    assert client.post("/head/cmd", json={"line": ""}).status_code == 422
    assert client.post("/head/cmd", json={"line": "bad\nline"}).status_code == 422
