"""Serial access to Feetech STS-series bus servos (STS3215 / STS3250).

Same protocol for both models (scservo_sdk sms_sts, protocol 0, 1 Mbaud).
Position scale 0..4095, one tick = 360/4096 deg. Limits keep distance to the
0/4095 encoder seam — see src/tests/servos/sts3250_test.py for the rationale.

Platform-neutral: the port string may be a Windows ``COM4`` or a Linux
``/dev/ttyUSB0`` / ``/dev/serial/by-id/...`` — pyserial handles both.
``SimBus`` is the hardware mock (same interface, linear motion model) used by
the test suites and the GUI's simulation mode.
"""

import threading
import time
from typing import Protocol, runtime_checkable

from scservo_sdk import COMM_SUCCESS, GroupSyncRead, PortHandler, sms_sts
from serial.tools import list_ports

BAUD = 1_000_000
ADDR_TORQUE_ENABLE = 40
ADDR_ID = 5                    # EPROM register holding the servo ID
ADDR_PRESENT_POSITION = 56     # 2 B position + 2 B speed (sign-magnitude, bit 15) in one block
ADDR_PRESENT_VOLTAGE = 62      # supply rail in 0.1 V units (SMS_STS_PRESENT_VOLTAGE); 60 = load (2 B), 63 = temperature
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

    def sync_read(self, ids: list[int]) -> dict[int, tuple[int, int]]:
        """Position (ticks) and speed (ticks/s, signed) of every ID in ONE bus
        transaction — the 50 Hz policy loop cannot afford 16 round trips.
        Raises if any servo is missing from the answer."""
        with self._lock:
            grp = GroupSyncRead(self._servo, ADDR_PRESENT_POSITION, 4)
            for i in ids:
                grp.addParam(i)
            res = grp.txRxPacket()
            out = {}
            if res == COMM_SUCCESS:
                for i in ids:
                    ok, _ = grp.isAvailable(i, ADDR_PRESENT_POSITION, 4)
                    if ok:
                        d = grp.getData(i, ADDR_PRESENT_POSITION, 4)
                        out[i] = (self._servo.scs_tohost(self._servo.scs_loword(d), 15),
                                  self._servo.scs_tohost(self._servo.scs_hiword(d), 15))
        missing = [i for i in ids if i not in out]
        if res != COMM_SUCCESS or missing:
            raise ServoBusError(f"Sync read failed (IDs {missing or ids}): "
                                f"{self._servo.getTxRxResult(res).strip()}")
        return out

    def sync_read_ext(self, ids: list[int]) -> dict[int, tuple[int, int, int, float, int]]:
        """Position, speed, load, voltage and temperature of every ID in ONE bus transaction
        (registers 56..63 are contiguous): (ticks, ticks/s signed, load -1000..1000 = +-100 % of the
        torque limit, volts, deg C). For the bench tests; the 50 Hz policy loop uses sync_read."""
        with self._lock:
            grp = GroupSyncRead(self._servo, ADDR_PRESENT_POSITION, 8)
            for i in ids:
                grp.addParam(i)
            res = grp.txRxPacket()
            out = {}
            if res == COMM_SUCCESS:
                for i in ids:
                    ok, _ = grp.isAvailable(i, ADDR_PRESENT_POSITION, 8)
                    if ok:
                        a = ADDR_PRESENT_POSITION
                        out[i] = (self._servo.scs_tohost(grp.getData(i, a, 2), 15),
                                  self._servo.scs_tohost(grp.getData(i, a + 2, 2), 15),
                                  self._servo.scs_tohost(grp.getData(i, a + 4, 2), 10),
                                  grp.getData(i, a + 6, 1) / 10.0,
                                  grp.getData(i, a + 7, 1))
        missing = [i for i in ids if i not in out]
        if res != COMM_SUCCESS or missing:
            raise ServoBusError(f"Extended sync read failed (IDs {missing or ids}): "
                                f"{self._servo.getTxRxResult(res).strip()}")
        return out

    def sync_move(self, targets: dict[int, int], speed: int, acc: int):
        """Goal position of many servos in ONE broadcast packet (no reply)."""
        with self._lock:
            for i, ticks in targets.items():
                self._servo.SyncWritePosEx(i, ticks, speed, acc)
            res = self._servo.groupSyncWrite.txPacket()
            self._servo.groupSyncWrite.clearParam()
        if res != COMM_SUCCESS:
            raise ServoBusError(f"Sync move failed: "
                                f"{self._servo.getTxRxResult(res).strip()}")

    def read_regs(self, servo_id: int, addr: int, length: int) -> list[int]:
        """Raw bytes of `length` registers starting at `addr` (read only; the servo's own EEPROM/SRAM table)."""
        with self._lock:
            data, res, err = self._servo.readTxRx(servo_id, addr, length)
        self._check(res, err, f"Read registers {addr}..{addr + length - 1}")
        return list(data)

    def torque_off(self, servo_id: int):
        with self._lock:
            self._servo.write1ByteTxRx(servo_id, ADDR_TORQUE_ENABLE, 0)

    def torque_on(self, servo_id: int) -> bool:
        """Explicitly enable torque and read it back — used when parking a
        joint that must actively HOLD its position (demo mode). Returns the
        verified state instead of trusting the write."""
        with self._lock:
            self._servo.write1ByteTxRx(servo_id, ADDR_TORQUE_ENABLE, 1)
            val, res, _err = self._servo.read1ByteTxRx(servo_id,
                                                       ADDR_TORQUE_ENABLE)
        return res == COMM_SUCCESS and val == 1

    def read_torque(self, servo_id: int) -> int | None:
        """Current TORQUE_ENABLE state (1/0), or None if no response —
        watchdog for held joints (a brown-out reset silently drops torque)."""
        with self._lock:
            val, res, _err = self._servo.read1ByteTxRx(servo_id,
                                                       ADDR_TORQUE_ENABLE)
        return val if res == COMM_SUCCESS else None

    def read_voltage(self, servo_id: int) -> float | None:
        """Servo rail voltage in V as the servo measures it (register 62,
        0.1 V steps), or None if it does not answer. The rail sits behind the
        low-voltage cutoff, so this is the battery pack voltage minus the
        drop over fuse, switch and relay — the Pi has no ADC of its own."""
        with self._lock:
            val, res, _err = self._servo.read1ByteTxRx(servo_id,
                                                       ADDR_PRESENT_VOLTAGE)
        return val / 10.0 if res == COMM_SUCCESS else None

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

    voltage: float | None = 12.3    # a healthy 3S pack; tests lower it

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

    def sync_read(self, ids: list[int]) -> dict[int, tuple[int, int]]:
        self._advance()
        return {i: (round(self._p(i)), 0) for i in ids}

    def sync_read_ext(self, ids: list[int]) -> dict[int, tuple[int, int, int, float, int]]:
        self._advance()
        return {i: (round(self._p(i)), 0, 0, self.voltage if self.voltage is not None else 0.0, 30)
                for i in ids}

    def sync_move(self, targets: dict[int, int], speed: int, acc: int):
        for i, ticks in targets.items():
            self.move(i, ticks, speed, acc)

    def read_regs(self, servo_id: int, addr: int, length: int) -> list[int]:
        return [0] * length

    def torque_off(self, servo_id: int):
        pass

    def torque_on(self, servo_id: int) -> bool:
        return True

    def read_torque(self, servo_id: int) -> int | None:
        return 1

    def read_voltage(self, servo_id: int) -> float | None:
        return self.voltage

    def scan(self, id_from: int = 1, id_to: int = 30) -> list[dict]:
        return [{"id": sid, "model": 3250} for sid in sorted(self._pos)
                if id_from <= sid <= id_to]

    def set_id(self, old_id: int, new_id: int) -> int:
        return 3250


@runtime_checkable
class Bus(Protocol):
    """The interface both runners program against — implemented by ServoBus
    (real hardware, any platform) and SimBus (mock)."""

    simulated: bool
    port: str

    def close(self) -> None: ...
    def ping(self, servo_id: int) -> int: ...
    def read_pos(self, servo_id: int) -> int: ...
    def move(self, servo_id: int, ticks: int, speed: int, acc: int) -> None: ...
    def sync_read(self, ids: list[int]) -> dict[int, tuple[int, int]]: ...
    def sync_read_ext(self, ids: list[int]) -> dict[int, tuple[int, int, int, float, int]]: ...
    def sync_move(self, targets: dict[int, int], speed: int, acc: int) -> None: ...
    def read_regs(self, servo_id: int, addr: int, length: int) -> list[int]: ...
    def torque_off(self, servo_id: int) -> None: ...
    def torque_on(self, servo_id: int) -> bool: ...
    def read_torque(self, servo_id: int) -> int | None: ...
    def read_voltage(self, servo_id: int) -> float | None: ...
    def scan(self, id_from: int = ..., id_to: int = ...) -> list[dict]: ...
    def set_id(self, old_id: int, new_id: int) -> int: ...


def open_bus(port: str | None = None, simulate: bool = False,
             start_ticks: int = CENTER_TICKS) -> "Bus":
    """Factory: a SimBus (mock), or a ServoBus on an explicit port, or on the
    single auto-detected USB serial port."""
    if simulate:
        return SimBus(start_ticks=start_ticks)
    if not port:
        found = serial_ports()
        if len(found) != 1:
            raise ServoBusError(f"Cannot auto-select a serial port "
                                f"({len(found)} candidates found).")
        port = found[0]["device"]
    return ServoBus(port)
