#!/usr/bin/env python3
# STS3250 Erst-Test am Waveshare Bus Servo Adapter (A) V1.1
# Laeuft unter Windows 11 und Ubuntu (und macOS)
#
# Aufbau:
#   - NUR EINEN Servo anschliessen (Werks-ID = 1)
#   - Servokabel in weisse Buchse (D V G)
#   - Gelber Jumper auf B (USB -> SERVO)
#   - Labornetzteil 12.0 V, Strombegrenzung ~1 A, an gruene Schraubklemme
#   - USB-C zum Laptop
#
# Installation (einmalig, im Ordner src/tests):
#   uv sync
#
# Start (im Ordner src/tests):
#   uv run servos/sts3250_test.py                -> Port-Autosuche
#   uv run servos/sts3250_test.py COM5           -> Port manuell (Windows)
#   uv run servos/sts3250_test.py /dev/ttyUSB0   -> Port manuell (Ubuntu, spaeter)
#
# Ablauf:
#   1) Ping
#   2) Startposition lesen (Kommunikationsstatus wird geprueft)
#   3) Nach Bestaetigung: Fahrt zur unteren Endposition, dann eine volle
#      Fahrt zur oberen Endposition (+353 Grad) und wieder zurueck.
#      Jede Fahrt wartet, bis das Ziel tatsaechlich erreicht ist.
#
# Warum nicht exakt 0 und 4095? Position 0 und 4095 liegen direkt an der
# Encoder-Naht (0/4095 = derselbe physische Punkt). Schiesst der Servo dort
# minimal ueber, landet er auf der anderen Seite der Naht und die Fahrt zur
# gegenueberliegenden Endposition wird zum No-Op (Regler sieht nur noch
# wenige Schritte Fehler). Deshalb halten die Endpositionen einen kleinen
# Sicherheitsabstand zur Naht.

import sys
import time

from scservo_sdk import *          # PortHandler, sms_sts, COMM_SUCCESS
from serial.tools import list_ports

BAUD = 1_000_000                   # Werkseinstellung STS-Serie
SERVO_ID = 1                       # Werkseinstellung
ADDR_TORQUE_ENABLE = 40

POS_MIN = 40                       # untere Endposition (~3.5 Grad, Abstand zur Naht)
POS_MAX = 4055                     # obere Endposition (~356.5 Grad, Abstand zur Naht)
SPEED = 500                        # Schritte/s -> volle Umdrehung in ~8 s
ACC = 50                           # sanfte Rampe
TOLERANZ = 25                      # Zieltoleranz in Schritten (~2.2 Grad)


def grad(pos):
    return pos * 360.0 / 4096.0


def find_port():
    if len(sys.argv) > 1:
        return sys.argv[1]
    ports = [p for p in list_ports.comports() if p.vid is not None]
    if not ports:
        sys.exit('Kein USB-Serial-Port gefunden.\n'
                 '-> Adapter angesteckt? CH343-Treiber installiert (Geraete-Manager)?\n'
                 '-> Sonst Port manuell angeben, z.B.: uv run servos/sts3250_test.py COM5')
    if len(ports) == 1:
        return ports[0].device
    print('Mehrere Ports gefunden:')
    for p in ports:
        print(f'  {p.device}  ({p.description})')
    sys.exit('Bitte Port als Argument angeben, z.B.: uv run servos/sts3250_test.py COM5')


def check(res, err, aktion):
    if res != COMM_SUCCESS:
        sys.exit(f'{aktion} fehlgeschlagen: {servo.getTxRxResult(res)}')
    if err != 0:
        print(f'Warnung bei "{aktion}": {servo.getRxPacketError(err)}')


def lese_position():
    pos, res, err = servo.ReadPos(SERVO_ID)
    check(res, err, 'Position lesen')
    return pos


def fahre_zu(ziel):
    start = lese_position()
    res, err = servo.WritePosEx(SERVO_ID, ziel, SPEED, ACC)
    check(res, err, f'Fahrbefehl auf {ziel}')
    timeout = abs(ziel - start) / SPEED + 2.0
    t0 = time.monotonic()
    while True:
        pos = lese_position()
        # Ziele halten Abstand zur 0/4095-Naht, daher reicht die einfache
        # Differenz (kein Umrechnen ueber die Naht noetig).
        if abs(pos - ziel) <= TOLERANZ:
            print(f'  Ziel {ziel:4d} ({grad(ziel):5.1f} Grad) erreicht, '
                  f'Ist {pos:4d} ({grad(pos):5.1f} Grad)')
            return
        if time.monotonic() - t0 > timeout:
            print(f'  WARNUNG: Ziel {ziel:4d} nach {timeout:.1f} s nicht erreicht, '
                  f'Ist {pos:4d} ({grad(pos):5.1f} Grad)')
            return
        time.sleep(0.05)


port = find_port()
print(f'Port: {port}')

ph = PortHandler(port)
servo = sms_sts(ph)

if not ph.openPort():
    sys.exit('Port liess sich nicht oeffnen (belegt? Berechtigung?).')
ph.setBaudRate(BAUD)

# --- 1) Ping: antwortet der Servo? ---
model, res, err = servo.ping(SERVO_ID)
if res != COMM_SUCCESS:
    sys.exit(f'Kein Ping: {servo.getTxRxResult(res)}\n'
             '-> 12 V an? Jumper auf B? Kabel eingerastet?')
print(f'OK: Servo ID {SERVO_ID} antwortet (Modellnummer {model})')

# --- 2) Startposition lesen ---
start_pos = lese_position()
print(f'Startposition: {start_pos} ({grad(start_pos):.1f} Grad; '
      f'Skala 0-4095, Mitte = 2048)')

# --- 3) Volle Fahrt: zur unteren Endposition, hoch, wieder zurueck ---
antwort = input('Volle 360-Grad-Fahrt starten? Abtrieb muss frei sein! [j/N] ')
if antwort.strip().lower() == 'j':
    try:
        print(f'Fahre zur unteren Endposition {POS_MIN} ...')
        fahre_zu(POS_MIN)
        print(f'Hin:     {POS_MIN} -> {POS_MAX} (+{grad(POS_MAX - POS_MIN):.0f} Grad) ...')
        fahre_zu(POS_MAX)
        print(f'Zurueck: {POS_MAX} -> {POS_MIN} (-{grad(POS_MAX - POS_MIN):.0f} Grad) ...')
        fahre_zu(POS_MIN)
        print('Fahrt ok.')
    finally:
        # Torque immer deaktivieren, auch wenn ein Fahrbefehl abbricht
        try:
            servo.write1ByteTxRx(SERVO_ID, ADDR_TORQUE_ENABLE, 0)
            print('Torque deaktiviert.')
        except Exception:
            print('WARNUNG: Torque konnte nicht deaktiviert werden.')

ph.closePort()
print('Test abgeschlossen.')
