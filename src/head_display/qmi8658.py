# QMI8658 6-axis IMU on the Waveshare RP2040-LCD-1.28 (I2C1, SDA 6 / SCL 7).
# Same configuration as Waveshare's demo (±8 g, ±512 dps, 1 kHz ODR, LPF on),
# so the numbers match what the stock firmware showed:
#   accel in mg, gyro in dps (deg/s), temperature in °C.

from machine import Pin, I2C
import struct

ADDR = 0x6B


class QMI8658:
    ACC_LSB_PER_G = 4096.0       # ±8 g
    GYR_LSB_PER_DPS = 64.0       # ±512 dps

    def __init__(self, sda=6, scl=7, freq=400_000):
        self.i2c = I2C(1, sda=Pin(sda), scl=Pin(scl), freq=freq)
        self.ok = self._read(0x00, 1)[0] == 0x05          # WHO_AM_I
        if not self.ok:
            return
        for reg, val in ((0x02, 0x60), (0x03, 0x23), (0x04, 0x53),
                         (0x05, 0x00), (0x06, 0x11), (0x07, 0x00),
                         (0x08, 0x03)):
            self.i2c.writeto_mem(ADDR, reg, bytes([val]))

    def _read(self, reg, n):
        try:
            return self.i2c.readfrom_mem(ADDR, reg, n)
        except OSError:
            return bytes(n)

    def read(self):
        """(ax, ay, az, gx, gy, gz) in mg / dps — zeros if the chip is absent."""
        if not self.ok:
            return (0.0,) * 6
        raw = self._read(0x35, 12)
        ax, ay, az, gx, gy, gz = struct.unpack("<hhhhhh", raw)
        ka = 1000.0 / self.ACC_LSB_PER_G
        kg = 1.0 / self.GYR_LSB_PER_DPS
        return (ax * ka, ay * ka, az * ka, gx * kg, gy * kg, gz * kg)

    def temperature(self):
        if not self.ok:
            return 0.0
        lo, hi = self._read(0x33, 2)
        t = struct.unpack("<h", bytes((lo, hi)))[0]
        return t / 256.0
