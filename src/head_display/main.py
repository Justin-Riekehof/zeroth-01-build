# Zeroth-01 head display: one friendly eye + IMU telemetry.
#
# Runs under MicroPython on the Waveshare RP2040-LCD-1.28 in the robot's
# head (USB-serial to the Pi). Every frame it draws the eye, reads the IMU
# and — at ~20 Hz — prints one JSON line the Pi service parses:
#   {"ax":..,"ay":..,"az":..,"gx":..,"gy":..,"gz":..,"t":..,"v":..,
#    "mood":"neutral","rot":90,"fps":28}
# Units stay the sensor's: mg, dps, °C, V — the same numbers the stock
# Waveshare demo showed, just machine-readable.
#
# Commands arrive as lines on the same serial port (see README.md):
#   mood neutral|happy|sleepy|surprised   blink   look X Y   rot DEG
#   axes fwd=-z right=+x   bl PCT   color R G B   info
# rot/axes/bl/color persist in config.json on the board's flash.

import json
import math
import random
import select
import sys
import time

from machine import ADC, Pin
from gc9a01 import GC9A01, rgb
from qmi8658 import QMI8658

CONFIG_FILE = "config.json"
CONFIG = {
    # defaults = the Zeroth-01 head as measured 2026-09-22 (config.json on
    # the board overrides; `rot`/`axes`/`color` commands write it)
    "rot": 270,           # display rotation so the eye is upright in the head
    "fwd": "-z",          # board accel axis that points out of the robot's face
    "right": "+x",        # board accel axis toward the robot's right
    "up": "+y",           # board axis pointing up — yaw rate is the gyro about it
    "bl": 100,            # backlight %
    "iris": [118, 122, 62],   # hazel — brown with a green tint
}

try:
    CONFIG.update(json.load(open(CONFIG_FILE)))
except (OSError, ValueError):
    pass


def save_config():
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(CONFIG, f)
    except OSError:
        pass


# ------------------------------------------------------------------ colours
BG = rgb(8, 10, 16)
SCLERA = rgb(246, 247, 250)
PUPIL = rgb(10, 10, 14)
GLINT = rgb(255, 255, 255)
LID = BG


def iris_color():
    r, g, b = CONFIG["iris"]
    return rgb(r, g, b)


# ------------------------------------------------------------------ geometry
CX, CY = 120, 122
SCL_RX, SCL_RY = 88, 80              # sclera ellipse
IRIS_R = 46
PUPIL_R = 24
MAX_DX = SCL_RX - IRIS_R - 5          # keep the iris inside the sclera
MAX_DY = SCL_RY - IRIS_R - 5


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def ease(t):                          # smoothstep
    t = clamp(t, 0.0, 1.0)
    return t * t * (3 - 2 * t)


# ------------------------------------------------------------------ eye state
MOODS = {
    #            upper lid rest, lower lid rest, pupil radius, saccade rate
    "neutral":   (0.06, 0.00, PUPIL_R, 1.0),
    "happy":     (0.14, 0.42, PUPIL_R, 1.2),
    "sleepy":    (0.50, 0.12, PUPIL_R + 4, 0.35),
    "surprised": (0.00, 0.00, PUPIL_R - 9, 1.6),
}


class Eye:
    def __init__(self):
        self.mood = "neutral"
        self.mood_until = None        # auto-revert time for a triggered mood
        self.px = self.py = 0.0       # current gaze (-1..1)
        self.tx = self.ty = 0.0       # saccade target
        now = time.ticks_ms()         # ticks_* want ints, never floats
        self.next_saccade = now
        self.look_until = now         # external "look X Y" holds the gaze
        self.upper = 0.06
        self.lower = 0.0
        self.blink_t0 = None
        self.next_blink = time.ticks_add(time.ticks_ms(), 1500)
        self.g_dx = self.g_dy = 0.0   # gravity-driven gaze offset
        self.alert = None             # (line, line, line) -> warning screen instead of the eye

    def set_mood(self, mood, hold_s=None):
        if mood not in MOODS:
            return False
        self.mood = mood
        self.mood_until = (time.ticks_add(time.ticks_ms(), int(hold_s * 1000))
                           if hold_s else None)
        return True

    def blink(self):
        self.blink_t0 = time.ticks_ms()

    def look(self, x, y, hold_s=2.0):
        self.tx, self.ty = clamp(x, -1, 1), clamp(y, -1, 1)
        self.look_until = time.ticks_add(time.ticks_ms(), int(hold_s * 1000))

    def update(self, dt, now):
        up_rest, low_rest, _, rate = MOODS[self.mood]
        if self.mood_until and time.ticks_diff(now, self.mood_until) > 0:
            self.mood, self.mood_until = "neutral", None
        # saccades: a new target every 0.7–3 s, biased toward the centre
        if time.ticks_diff(now, self.look_until) > 0 \
                and time.ticks_diff(now, self.next_saccade) > 0:
            k = 0.85 if random.random() < 0.35 else 0.4
            self.tx = random.uniform(-k, k)
            self.ty = random.uniform(-k * 0.7, k * 0.7)
            self.next_saccade = time.ticks_add(
                now, int(random.uniform(700, 3000) / rate))
        a = 1 - math.exp(-dt * 16)
        self.px += (self.tx - self.px) * a
        self.py += (self.ty - self.py) * a
        # blink: 80 ms close, 40 ms hold, 120 ms open; sleepy blinks slower
        lid = 0.0
        if self.blink_t0 is not None:
            t = time.ticks_diff(now, self.blink_t0)
            slow = 2.2 if self.mood == "sleepy" else 1.0
            if t < 80 * slow:
                lid = ease(t / (80 * slow))
            elif t < 120 * slow:
                lid = 1.0
            elif t < 240 * slow:
                lid = 1 - ease((t - 120 * slow) / (120 * slow))
            else:
                self.blink_t0 = None
                double = random.random() < 0.12
                self.next_blink = time.ticks_add(
                    now, 250 if double else int(random.uniform(2500, 6500)))
        elif time.ticks_diff(now, self.next_blink) > 0:
            self.blink_t0 = now
        b = 1 - math.exp(-dt * 10)
        self.upper += (max(up_rest, lid) - self.upper) * b
        self.lower += (low_rest - self.lower) * b

    def draw(self, fb):
        fb.fill(BG)
        fb.ellipse(CX, CY, SCL_RX, SCL_RY, SCLERA, True)
        dx = clamp(self.px * MAX_DX + self.g_dx, -MAX_DX, MAX_DX)
        dy = clamp(self.py * MAX_DY + self.g_dy, -MAX_DY, MAX_DY)
        ix, iy = int(CX + dx), int(CY + dy)
        fb.ellipse(ix, iy, IRIS_R, IRIS_R, iris_color(), True)
        pr = MOODS[self.mood][2]
        fb.ellipse(ix, iy, pr, pr, PUPIL, True)
        fb.ellipse(ix - 15, iy - 15, 10, 10, GLINT, True)
        fb.ellipse(ix + 13, iy + 11, 5, 5, GLINT, True)
        # upper lid: a big background-coloured ellipse whose lower edge is
        # the (convex) lid line, plus a rect to cover everything above it
        top = CY - SCL_RY - 4
        span = 2 * SCL_RY + 8
        if self.upper > 0.005:
            y = top + int(self.upper * span)
            fb.ellipse(CX, y - 70, SCL_RX + 30, 70, LID, True)
            fb.fill_rect(0, 0, 240, max(0, y - 70), LID)
        if self.lower > 0.005:
            y = top + span - int(self.lower * span)
            fb.ellipse(CX, y + 70, SCL_RX + 30, 70, LID, True)
            fb.fill_rect(0, min(240, y + 70), 240, 240, LID)



# ------------------------------------------------------------------ boot splash
# "ROBOT PROJECT / PIXEL" before the eye opens. A stroke font drawn with
# framebuf.line(): glyphs on a 4 x 6 grid with 45-degree chamfers instead of
# corners (the futuristic part), rendered with a per-letter bounce and a
# sweep that lights the letters one by one (the playful part). No bitmap
# font is needed on the board.
GLYPHS = {   # polylines, grid x 0..4 (right), y 0..6 (down)
    "R": [[(0, 6), (0, 0), (3, 0), (4, 1), (4, 2), (3, 3), (0, 3)], [(2, 3), (4, 6)]],
    "O": [[(1, 0), (3, 0), (4, 1), (4, 5), (3, 6), (1, 6), (0, 5), (0, 1), (1, 0)]],
    "B": [[(0, 6), (0, 0), (3, 0), (4, 1), (4, 2), (3, 3), (0, 3)], [(3, 3), (4, 4), (4, 5), (3, 6), (0, 6)]],
    "T": [[(0, 0), (4, 0)], [(2, 0), (2, 6)]],
    "P": [[(0, 6), (0, 0), (3, 0), (4, 1), (4, 2), (3, 3), (0, 3)]],
    "J": [[(1, 0), (4, 0)], [(3, 0), (3, 5), (2, 6), (1, 6), (0, 5)]],
    "E": [[(4, 0), (0, 0), (0, 6), (4, 6)], [(0, 3), (3, 3)]],
    "C": [[(4, 1), (3, 0), (1, 0), (0, 1), (0, 5), (1, 6), (3, 6), (4, 5)]],
    "I": [[(2, 0), (2, 6)], [(1, 0), (3, 0)], [(1, 6), (3, 6)]],
    "X": [[(0, 0), (4, 6)], [(4, 0), (0, 6)]],
    "L": [[(0, 0), (0, 6), (4, 6)]],
    "A": [[(0, 6), (0, 2), (2, 0), (4, 2), (4, 6)], [(0, 4), (4, 4)]],
    "D": [[(0, 6), (0, 0), (2, 0), (4, 2), (4, 4), (2, 6), (0, 6)]],
    "F": [[(4, 0), (0, 0), (0, 6)], [(0, 3), (3, 3)]],
    "G": [[(4, 1), (3, 0), (1, 0), (0, 1), (0, 5), (1, 6), (3, 6), (4, 5), (4, 3), (2, 3)]],
    "H": [[(0, 0), (0, 6)], [(4, 0), (4, 6)], [(0, 3), (4, 3)]],
    "K": [[(0, 0), (0, 6)], [(4, 0), (0, 4)], [(1, 3), (4, 6)]],
    "M": [[(0, 6), (0, 0), (2, 3), (4, 0), (4, 6)]],
    "N": [[(0, 6), (0, 0), (4, 6), (4, 0)]],
    "Q": [[(1, 0), (3, 0), (4, 1), (4, 5), (3, 6), (1, 6), (0, 5), (0, 1), (1, 0)], [(2, 4), (4, 6)]],
    "S": [[(4, 1), (3, 0), (1, 0), (0, 1), (0, 2), (1, 3), (3, 3), (4, 4), (4, 5), (3, 6), (1, 6), (0, 5)]],
    "U": [[(0, 0), (0, 5), (1, 6), (3, 6), (4, 5), (4, 0)]],
    "V": [[(0, 0), (0, 3), (2, 6), (4, 3), (4, 0)]],
    "W": [[(0, 0), (0, 6), (2, 3), (4, 6), (4, 0)]],
    "Y": [[(0, 0), (0, 2), (2, 4), (4, 2), (4, 0)], [(2, 4), (2, 6)]],
    "Z": [[(0, 0), (4, 0), (0, 6), (4, 6)]],
    "!": [[(2, 0), (2, 4)], [(2, 5), (2, 6)]],
    "-": [[(1, 3), (3, 3)]],
    " ": [],
}
ALERT_RED = rgb(200, 20, 24)
ALERT_DARK = rgb(70, 6, 8)
ALERTS = {          # preset alert screens: up to three lines (big, big, small)
    "battery": ("BATTERY", "EMPTY", "PI OFF - CHARGE"),
}


def draw_alert(fb, lines, t):
    """Full-screen warning: pulsing red ground, a ring, a big '!' and the
    text. Shown instead of the eye while an alert is active — e.g. after the
    Pi service halted the OS on an empty pack: the board keeps its 5 V, so
    this is the warning that stays visible on the robot."""
    hot = 0.5 + 0.5 * math.sin(t * 5.0)
    fb.fill(ALERT_RED if hot > 0.5 else ALERT_DARK)
    ring = SPLASH_WHITE if hot > 0.5 else ALERT_RED
    fb.ellipse(120, 120, 116, 116, ring, False)
    fb.ellipse(120, 120, 115, 115, ring, False)
    l1, l2, l3 = (list(lines) + ["", "", ""])[:3]
    fg = SPLASH_WHITE
    draw_glyph(fb, "!", 110, 22, 5, fg, 3)
    if l1:
        w = text_width(l1, 5, 6)
        draw_text(fb, l1, (240 - w) // 2, 74, 5, fg, 6, 3)
    if l2:
        w = text_width(l2, 5, 6)
        draw_text(fb, l2, (240 - w) // 2, 118, 5, fg, 6, 3)
    if l3:
        w = text_width(l3, 3, 3)
        draw_text(fb, l3, (240 - w) // 2, 168, 3, fg, 3, 1)

SPLASH_BG = rgb(6, 8, 14)
SPLASH_DIM = rgb(40, 70, 90)
SPLASH_CYAN = rgb(60, 220, 255)
SPLASH_AMBER = rgb(255, 150, 30)
SPLASH_WHITE = rgb(235, 245, 255)


def draw_glyph(fb, ch, x, y, s, color, thick=1):
    """Glyph `ch` with its top-left at (x, y), `s` px per grid unit."""
    for line in GLYPHS.get(ch, ()):
        for (x0, y0), (x1, y1) in zip(line, line[1:]):
            for d in range(thick):
                for e in range(thick):
                    fb.line(int(x + x0 * s) + d, int(y + y0 * s) + e,
                            int(x + x1 * s) + d, int(y + y1 * s) + e, color)


def text_width(txt, s, gap):
    return len(txt) * (4 * s + gap) - gap


def draw_text(fb, txt, x, y, s, color, gap, thick=1, bounce=None):
    for i, ch in enumerate(txt):
        dy = bounce(i) if bounce else 0
        draw_glyph(fb, ch, x + i * (4 * s + gap), y + dy, s, color, thick)


def splash(lcd, seconds=3.2):
    t0 = time.ticks_ms()
    title, name = "ROBOT PROJECT", "PIXEL"
    s1, g1, s2, g2 = 3, 4, 8, 9              # px per unit, letter gap
    w1, w2 = text_width(title, s1, g1), text_width(name, s2, g2)
    x1, y1 = (240 - w1) // 2, 68
    x2, y2 = (240 - w2) // 2, 108
    while True:
        t = time.ticks_diff(time.ticks_ms(), t0) / 1000.0
        if t > seconds:
            break
        lcd.fill(SPLASH_BG)
        # rotating orbit ring: three arcs that spin, a nod to the round face
        a0 = t * 2.2
        for k in range(3):
            base = a0 + k * 2.094
            for i in range(28):
                a = base + i * 0.03
                lcd.pixel(int(120 + 112 * math.cos(a)), int(120 + 112 * math.sin(a)), SPLASH_DIM)
                lcd.pixel(int(120 + 111 * math.cos(a)), int(120 + 111 * math.sin(a)), SPLASH_DIM)
        # title fades in over the first 0.6 s (dim -> cyan)
        col = SPLASH_DIM if t < 0.3 else SPLASH_CYAN
        if t > 0.15:
            draw_text(lcd, title, x1, y1, s1, col, g1)
        # PIXEL: letters land one by one with a small bounce, a bright sweep
        # follows; after 2.2 s everything settles
        for i, ch in enumerate(name):
            born = 0.5 + i * 0.22
            if t < born:
                continue
            age = t - born
            drop = int((1 - ease(age / 0.35)) * 26) if age < 0.35 else 0
            hop = int(4 * math.sin(t * 5 + i)) if t < 2.4 else 0
            hot = age < 0.18
            c = SPLASH_WHITE if hot else (SPLASH_AMBER if i == 2 else SPLASH_CYAN)
            draw_glyph(lcd, ch, x2 + i * (4 * s2 + g2), y2 - drop + hop, s2, c, 3)
        # sweep line runs across the name once
        if 1.6 < t < 2.3:
            sx = int(x2 - 10 + (w2 + 20) * (t - 1.6) / 0.7)
            lcd.vline(sx, y2 - 6, 6 * s2 + 12, SPLASH_WHITE)
        # underline grows, then the word dims out at the very end
        if t > 2.0:
            uw = int(w2 * ease((t - 2.0) / 0.4))
            lcd.hline(x2 + (w2 - uw) // 2, y2 + 6 * s2 + 10, uw, SPLASH_AMBER)
        if t > seconds - 0.4:            # closing iris: eye lids come from top and bottom
            k = int(120 * ease((t - (seconds - 0.4)) / 0.4))
            lcd.fill_rect(0, 0, 240, k, SPLASH_BG)
            lcd.fill_rect(0, 240 - k, 240, k, SPLASH_BG)
        lcd.show()

# ------------------------------------------------------------------ IMU mapping
def axis_get(v, spec):
    """Component of the accel triple along a board axis like "-z"."""
    i = "xyz".index(spec[-1])
    return -v[i] if spec[0] == "-" else v[i]


def gravity_offsets(acc):
    """Where the head leans -> where the eye drifts (like a googly eye):
    nose down = look down, right ear down = look right. ±45° ≈ full deflection.
    An axis that dips reads negative (reaction force), hence the minus."""
    fwd = axis_get(acc, CONFIG["fwd"])
    right = axis_get(acc, CONFIG["right"])
    return (clamp(-right / 700.0, -1, 1) * MAX_DX * 0.8,
            clamp(-fwd / 700.0, -1, 1) * MAX_DY * 0.8)


class YawFollow:
    """Gravity cannot show yaw, so the eye follows the TURN RATE instead:
    while the head turns, the gaze leads into the turn and settles back
    when the turn stops. Gyro bias (a few dps at rest) is learned whenever
    the head is still, otherwise it would read as a slow permanent turn."""

    def __init__(self):
        self.bias = [0.0, 0.0, 0.0]
        self.out = 0.0

    def update(self, gyro, dt):
        mag = math.sqrt(gyro[0] ** 2 + gyro[1] ** 2 + gyro[2] ** 2)
        if mag < 8.0:                                  # still -> learn bias
            k = min(1.0, dt * 0.5)
            for i in range(3):
                self.bias[i] += (gyro[i] - self.bias[i]) * k
        g = [gyro[i] - self.bias[i] for i in range(3)]
        # sign verified on the robot 2026-09-22: a right turn reads positive
        # about the board's up axis (the QMI8658's gyro convention here)
        yaw_right = axis_get(g, CONFIG["up"])
        if abs(yaw_right) < 4.0:                       # deadband
            yaw_right = 0.0
        target = clamp(yaw_right / 90.0, -1, 1)        # 90 dps = full deflection
        a = 1 - math.exp(-dt * (12 if abs(target) > abs(self.out) else 4))
        self.out += (target - self.out) * a
        return self.out * MAX_DX * 0.9


# ------------------------------------------------------------------ commands
def handle(line, eye, lcd):
    parts = line.strip().split()
    if not parts:
        return
    cmd, args = parts[0].lower(), parts[1:]
    try:
        if cmd == "mood" and args:
            eye.set_mood(args[0].lower(),
                         float(args[1]) if len(args) > 1 else None)
        elif cmd == "blink":
            eye.blink()
        elif cmd == "splash":
            splash(lcd)
            eye.upper, eye.lower = 1.0, 0.6      # the eye opens afterwards
        elif cmd == "alert":
            # "alert off" | "alert battery" | "alert WORD [WORD [WORD]]"
            if not args or args[0].lower() == "off":
                eye.alert = None
            elif args[0].lower() in ALERTS:
                eye.alert = ALERTS[args[0].lower()]
            else:
                eye.alert = tuple(a.upper()[:12] for a in args[:3])
        elif cmd == "look" and len(args) >= 2:
            eye.look(float(args[0]), float(args[1]),
                     float(args[2]) if len(args) > 2 else 2.0)
        elif cmd == "rot" and args:
            CONFIG["rot"] = int(args[0]) % 360
            lcd.rotation(CONFIG["rot"])
            save_config()
        elif cmd == "axes":
            for a in args:
                k, _, v = a.partition("=")
                if k in ("fwd", "right", "up") and v[-1] in "xyz" and v[0] in "+-":
                    CONFIG[k] = v
            save_config()
        elif cmd == "bl" and args:
            CONFIG["bl"] = int(args[0])
            lcd.brightness(CONFIG["bl"])
            save_config()
        elif cmd == "color" and len(args) >= 3:
            CONFIG["iris"] = [clamp(int(a), 0, 255) for a in args[:3]]
            save_config()
        elif cmd == "info":
            print(json.dumps({"config": CONFIG, "mood": eye.mood}))
    except ValueError:
        pass


# ------------------------------------------------------------------ main loop
def main():
    lcd = GC9A01(rotation=CONFIG["rot"])
    lcd.brightness(CONFIG["bl"])
    imu = QMI8658()
    vsys = ADC(Pin(29))
    eye = Eye()
    splash(lcd)
    eye.upper, eye.lower = 1.0, 0.6              # lids closed -> the eye opens
    eye.next_blink = time.ticks_add(time.ticks_ms(), 2500)
    yaw = YawFollow()
    poll = select.poll()
    poll.register(sys.stdin, select.POLLIN)

    last = time.ticks_ms()
    last_tx = last
    frames, fps, fps_t0 = 0, 0.0, last
    surprise_cooldown = last
    cmd_buf = ""
    while True:
        now = time.ticks_ms()
        dt = time.ticks_diff(now, last) / 1000.0
        last = now

        # commands — strictly non-blocking: readline() would hang the eye
        # when the host reopens the port and poll() reports an event that
        # is not a full line (seen when the Pi service takes over from cat)
        for _ in range(64):
            ev = poll.poll(0)
            if not ev or not (ev[0][1] & select.POLLIN):
                break
            ch = sys.stdin.read(1)
            if ch == "\n":
                handle(cmd_buf, eye, lcd)
                cmd_buf = ""
            elif ch and ch != "\r":
                cmd_buf = (cmd_buf + ch)[-120:]

        acc = imu.read()
        ax, ay, az, gx, gy, gz = acc
        eye.g_dx, eye.g_dy = gravity_offsets(acc)
        eye.g_dx += yaw.update(acc[3:], dt)
        # a fast head movement gets a startled look, once per second at most
        if eye.mood == "neutral" and time.ticks_diff(now, surprise_cooldown) > 0 \
                and (gx * gx + gy * gy + gz * gz) > 150 ** 2:
            eye.set_mood("surprised", 1.2)
            surprise_cooldown = time.ticks_add(now, 2500)

        eye.update(dt, now)
        if eye.alert:
            draw_alert(lcd, eye.alert, now / 1000.0)
            lcd.brightness(100)               # a warning is never dimmed
        else:
            eye.draw(lcd)
        lcd.show()

        frames += 1
        if time.ticks_diff(now, fps_t0) >= 1000:
            fps = frames * 1000.0 / time.ticks_diff(now, fps_t0)
            frames, fps_t0 = 0, now
        if time.ticks_diff(now, last_tx) >= 50:        # ~20 Hz telemetry
            last_tx = now
            print(json.dumps({
                "ax": round(ax, 1), "ay": round(ay, 1), "az": round(az, 1),
                "gx": round(gx, 2), "gy": round(gy, 2), "gz": round(gz, 2),
                "t": round(imu.temperature(), 1),
                "v": round(vsys.read_u16() * 3.3 / 65535 * 2, 3),   # board divider 1:2
                "mood": eye.mood, "rot": CONFIG["rot"], "fps": round(fps, 1),
            }))


# A crash must leave a trace (crash.txt on the board's flash — read it with
# `mpremote cat crash.txt`) and the eye must come back, not sit in the REPL.
# Ctrl-C from mpremote still stops it, that is how files get updated.
while True:
    try:
        main()
    except KeyboardInterrupt:
        raise
    except Exception as e:
        try:
            with open("crash.txt", "w") as f:
                sys.print_exception(e, f)
        except OSError:
            pass
        sys.print_exception(e)
        time.sleep(2)
