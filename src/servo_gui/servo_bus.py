"""Serial access to Feetech STS-series bus servos (STS3215 / STS3250).

Same protocol for both models (scservo_sdk sms_sts). Position scale 0..4095,
one tick = 360/4096 deg. Limits keep distance to the 0/4095 encoder seam —
see src/tests/servos/sts3250_test.py for the rationale.
"""

import threading
import time

from scservo_sdk import COMM_SUCCESS, PortHandler, sms_sts
from serial.tools import list_ports

BAUD = 1_000_000
ADDR_TORQUE_ENABLE = 40
ADDR_ID = 5                    # EPROM register holding the servo ID
TICKS_PER_REV = 4096
POS_MIN_SAFE = 40      # ~3.5 deg
POS_MAX_SAFE = 4055    # ~356.5 deg


CENTER_TICKS = 2048    # 180 deg absolute = mount/assembly position = 0 deg relative


def deg_to_ticks(deg: float) -> int:
    return max(POS_MIN_SAFE, min(POS_MAX_SAFE, round(deg * TICKS_PER_REV / 360.0)))


def ticks_to_deg(ticks: float) -> float:
    return ticks * 360.0 / TICKS_PER_REV


# Calibration convention of this build: servos are moved to CENTER_TICKS before
# the printed parts are mounted, so every joint has +/-180 deg of travel.
# All user-facing angles are relative to that center.

def rel_deg_to_ticks(rel: float) -> int:
    return deg_to_ticks(rel + 180.0)


def ticks_to_rel_deg(ticks: float) -> float:
    return ticks_to_deg(ticks) - 180.0


def serial_ports() -> list[dict]:
    return [{"device": p.device, "description": p.description}
            for p in list_ports.comports() if p.vid is not None]


class ServoBusError(RuntimeError):
    pass


class ServoBus:
    """Real hardware bus via the Waveshare USB adapter."""

    simulated = False

    def __init__(self, port: str):
        self.port = port
        self._lock = threading.Lock()
        self._ph = PortHandler(port)
        self._servo = sms_sts(self._ph)
        if not self._ph.openPort():
            raise ServoBusError(
                f"Could not open {port} (in use? permissions?).")
        self._ph.setBaudRate(BAUD)

    def close(self):
        with self._lock:
            try:
                self._ph.closePort()
            except Exception:
                pass

    def _check(self, res, err, action: str):
        if res != COMM_SUCCESS:
            raise ServoBusError(f"{action} failed: "
                                f"{self._servo.getTxRxResult(res).strip()}")
        if err != 0:
            raise ServoBusError(f"{action}: servo error "
                                f"{self._servo.getRxPacketError(err).strip()}")

    def ping(self, servo_id: int) -> int:
        with self._lock:
            model, res, err = self._servo.ping(servo_id)
        self._check(res, err, f"Ping ID {servo_id}")
        return model

    def read_pos(self, servo_id: int) -> int:
        with self._lock:
            pos, res, err = self._servo.ReadPos(servo_id)
        self._check(res, err, "Read position")
        return pos

    def move(self, servo_id: int, ticks: int, speed: int, acc: int):
        with self._lock:
            res, err = self._servo.WritePosEx(servo_id, ticks, speed, acc)
        self._check(res, err, f"Move to {ticks}")

    def torque_off(self, servo_id: int):
        with self._lock:
            self._servo.write1ByteTxRx(servo_id, ADDR_TORQUE_ENABLE, 0)

    def scan(self, id_from: int = 1, id_to: int = 30) -> list[dict]:
        """Ping every ID in the range; returns the servos that answered."""
        found = []
        with self._lock:
            for sid in range(id_from, id_to + 1):
                model, res, _err = self._servo.ping(sid)
                if res == COMM_SUCCESS:
                    found.append({"id": sid, "model": model})
        return found

    def set_id(self, old_id: int, new_id: int) -> int:
        """Persistently re-ID a servo (EPROM write). The bus must contain
        exactly one servo with old_id and none with new_id."""
        with self._lock:
            model, res, _ = self._servo.ping(old_id)
            if res != COMM_SUCCESS:
                raise ServoBusError(f"ID {old_id} does not respond.")
            if new_id != old_id:
                _, res2, _ = self._servo.ping(new_id)
                if res2 == COMM_SUCCESS:
                    raise ServoBusError(f"ID {new_id} is already in use "
                                        "on the bus.")
            self._servo.unLockEprom(old_id)
            res, err = self._servo.write1ByteTxRx(old_id, ADDR_ID, new_id)
            self._servo.LockEprom(new_id)
        self._check(res, err, f"Write ID {old_id} -> {new_id}")
        with self._lock:
            _, res3, _ = self._servo.ping(new_id)
        if res3 != COMM_SUCCESS:
            raise ServoBusError(f"Servo does not respond on new ID {new_id} "
                                "— check and rescan!")
        return model


class SimBus:
    """Drop-in simulation: linear motion at the commanded speed, any number
    of servo IDs. Lets the GUI (and the 3D visualization) be used without
    hardware.
    """

    simulated = True
    port = "simulator"

    def __init__(self, start_ticks: int = 2048):
        self._start = float(start_ticks)
        self._pos: dict[int, float] = {}
        self._target: dict[int, float] = {}
        self._speed: dict[int, float] = {}
        self._t = time.monotonic()

    def close(self):
        pass

    def _p(self, sid: int) -> float:
        return self._pos.setdefault(sid, self._start)

    def _advance(self):
        now = time.monotonic()
        dt, self._t = now - self._t, now
        for sid, target in self._target.items():
            step = self._speed.get(sid, 500.0) * dt
            delta = target - self._p(sid)
            self._pos[sid] = target if abs(delta) <= step else \
                self._pos[sid] + step * (1 if delta > 0 else -1)

    def ping(self, servo_id: int) -> int:
        self._p(servo_id)
        return 3250

    def read_pos(self, servo_id: int) -> int:
        self._advance()
        return round(self._p(servo_id))

    def move(self, servo_id: int, ticks: int, speed: int, acc: int):
        self._advance()
        self._p(servo_id)
        self._target[servo_id] = float(ticks)
        self._speed[servo_id] = max(1.0, float(speed))

    def torque_off(self, servo_id: int):
        pass

    def scan(self, id_from: int = 1, id_to: int = 30) -> list[dict]:
        return [{"id": sid, "model": 3250} for sid in sorted(self._pos)
                if id_from <= sid <= id_to]

    def set_id(self, old_id: int, new_id: int) -> int:
        return 3250
