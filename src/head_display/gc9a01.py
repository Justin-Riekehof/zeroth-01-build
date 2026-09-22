# GC9A01 round 1.28" 240x240 LCD on the Waveshare RP2040-LCD-1.28 (and the
# -Touch- variant: same LCD pins except RST, both are pulsed).
# Init sequence as in Waveshare's demo; orientation via MADCTL so the eye can
# be turned to match how the board sits in the head — no per-pixel rotation.
#
# framebuf.RGB565 stores little-endian, the panel wants the high byte first:
# every colour goes through rgb() which swaps the bytes once.

from machine import Pin, SPI, PWM
import framebuf
import time

DC, CS, SCK, MOSI, BL = 8, 9, 10, 11, 25
RST_PINS = (12, 13)          # 12 = RP2040-LCD-1.28, 13 = RP2040-Touch-LCD-1.28

# MADCTL: MY=0x80 MX=0x40 MV=0x20, base ML|BGR = 0x18 (Waveshare uses 0x98)
_MADCTL = {0: 0x80, 90: 0xE0, 180: 0x40, 270: 0x20}

_INIT = (
    (0xEF, b""), (0xEB, b"\x14"), (0xFE, b""), (0xEF, b""), (0xEB, b"\x14"),
    (0x84, b"\x40"), (0x85, b"\xFF"), (0x86, b"\xFF"), (0x87, b"\xFF"),
    (0x88, b"\x0A"), (0x89, b"\x21"), (0x8A, b"\x00"), (0x8B, b"\x80"),
    (0x8C, b"\x01"), (0x8D, b"\x01"), (0x8E, b"\xFF"), (0x8F, b"\xFF"),
    (0xB6, b"\x00\x20"), (0x3A, b"\x05"), (0x90, b"\x08\x08\x08\x08"),
    (0xBD, b"\x06"), (0xBC, b"\x00"), (0xFF, b"\x60\x01\x04"),
    (0xC3, b"\x13"), (0xC4, b"\x13"), (0xC9, b"\x22"), (0xBE, b"\x11"),
    (0xE1, b"\x10\x0E"), (0xDF, b"\x21\x0c\x02"),
    (0xF0, b"\x45\x09\x08\x08\x26\x2A"), (0xF1, b"\x43\x70\x72\x36\x37\x6F"),
    (0xF2, b"\x45\x09\x08\x08\x26\x2A"), (0xF3, b"\x43\x70\x72\x36\x37\x6F"),
    (0xED, b"\x1B\x0B"), (0xAE, b"\x77"), (0xCD, b"\x63"),
    (0x70, b"\x07\x07\x04\x0E\x0F\x09\x07\x08\x03"), (0xE8, b"\x34"),
    (0x62, b"\x18\x0D\x71\xED\x70\x70\x18\x0F\x71\xEF\x70\x70"),
    (0x63, b"\x18\x11\x71\xF1\x70\x70\x18\x13\x71\xF3\x70\x70"),
    (0x64, b"\x28\x29\xF1\x01\xF1\x00\x07"),
    (0x66, b"\x3C\x00\xCD\x67\x45\x45\x10\x00\x00\x00"),
    (0x67, b"\x00\x3C\x00\x00\x00\x01\x54\x10\x32\x98"),
    (0x74, b"\x10\x85\x80\x00\x00\x4E\x00"), (0x98, b"\x3e\x07"),
    (0x35, b""), (0x21, b""), (0x11, b""), (0x29, b""),
)


def rgb(r, g, b):
    c = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
    return ((c & 0xFF) << 8) | (c >> 8)


class GC9A01(framebuf.FrameBuffer):
    W = H = 240

    def __init__(self, rotation=0):
        self.cs = Pin(CS, Pin.OUT, value=1)
        self.dc = Pin(DC, Pin.OUT, value=1)
        self.rsts = [Pin(p, Pin.OUT, value=1) for p in RST_PINS]
        self.spi = SPI(1, 100_000_000, polarity=0, phase=0, bits=8,
                       sck=Pin(SCK), mosi=Pin(MOSI), miso=None)
        self.buf = bytearray(self.W * self.H * 2)
        super().__init__(self.buf, self.W, self.H, framebuf.RGB565)
        self._init()
        self.rotation(rotation)
        self.bl = PWM(Pin(BL))
        self.bl.freq(5000)
        self.brightness(100)

    def _cmd(self, cmd, data=b""):
        self.dc(0); self.cs(0)
        self.spi.write(bytes([cmd]))
        self.cs(1)
        if data:
            self.dc(1); self.cs(0)
            self.spi.write(data)
            self.cs(1)

    def _init(self):
        for r in self.rsts:
            r(1)
        time.sleep_ms(10)
        for r in self.rsts:
            r(0)
        time.sleep_ms(10)
        for r in self.rsts:
            r(1)
        time.sleep_ms(50)
        for cmd, data in _INIT:
            self._cmd(cmd, data)
        time.sleep_ms(120)

    def rotation(self, deg):
        self.rot = deg if deg in _MADCTL else 0
        self._cmd(0x36, bytes([_MADCTL[self.rot] | 0x18]))

    def brightness(self, pct):
        pct = min(100, max(0, int(pct)))
        self.bl.duty_u16(pct * 65535 // 100)

    def show(self):
        self._cmd(0x2A, b"\x00\x00\x00\xEF")
        self._cmd(0x2B, b"\x00\x00\x00\xEF")
        self._cmd(0x2C)
        self.dc(1); self.cs(0)
        self.spi.write(self.buf)
        self.cs(1)
