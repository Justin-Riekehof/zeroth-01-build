# Zwei-Finger-Greifer mit Handgelenk-Roll (2× STS3215, PLA/PETG)

v0.2, **nicht gedruckt und nicht am Roboter getestet**. Ein Filament, die TPU-Pads werden
nachträglich aufgesteckt. Erzeugt von [make_gripper.py](make_gripper.py) (Greifer) und
[make_wrist.py](make_wrist.py) (Joch + Roll-Servo-Fach), alle Maße Parameter, STLs in [stl/](stl/).

Druckvorbereitung für den Bambu Lab P2S (3 Platten für beide Greifer): [print/PRINT.md](print/PRINT.md).

```bash
.cad/bin/python hardware/gripper/make_gripper.py --check   # Greifer: Bewegungssweep + Servo-Passung
.cad/bin/python hardware/gripper/make_wrist.py --check     # Joch: Roll-Servo-Passung
```

## Aufbau (vom Ellbogen zur Fingerspitze)

1. **Joch** `wrist_yoke_x2` klemmt auf beide Ellbogen-Hörner (ersetzt den PETG-Stumpf, gleiches
   Lochbild: 4 × Ø3 auf R7, Mittelbohrung Ø6,8, Ohren 4,5 mm, die als gerundete Rampe über 26 mm auf die Kastenwand auslaufen, alle Außenkanten R6). Ein Kasten darin hält den
   **Roll-Servo** (STS3215, ID 14/24), Welle entlang des Unterarms.
2. **Deckplatte** `wrist_retainer_x2` hält den Roll-Servo von oben (4 × M3 Senkkopf in die Kastenwände).
3. Die **Rückwand des Greifer-Fachs** (die normale 4-mm-Fachwand, keine Extra-Platte) sitzt mit einem Zapfen
   (Ø22, 2,8 mm, gerundet, mit Auslauf in die Wand). Er sitzt bündig in einem runden Fenster (Ø23,2) der Roll-Deckplatte auf dem Horn des Roll-Servos. 4 Rundlöcher (Lochbild R7 wie am Ellbogen-Horn). Die Horn-Zahnung hat 25 Zähne, die
   Drehlage auf der Welle ändert nur die Roll-Nulllage (bis 7,2°, per Servo-Offset kalibrieren). Die Schraubenköpfe sitzen im Fach, M3×6 von innen mit dem Sechskantschlüssel, **vor**
   dem Einsetzen des Greifer-Servos.
4. **Greifer** (unten): Greifer-Servo (ID 15/25) liegt quer im Fach, mittig auf der Roll-Achse.

Ein Joch passt an beide Arme (es ist symmetrisch zur Hornachse), also 2 Stück drucken.

## Formgebung

Kurbeln und Lenker sind konisch (breit am Zahnrad, schmal am Zapfen), Fach, Platten, Joch und Finger sind
verrundet (Ecken 5–10 mm, Fingerknie 5 mm, Spitzen 3 mm). Alle Funktionsmaße (Bohrungen, Bewegungsraum)
blieben gleich, der Bewegungssweep ist weiter ohne Überlappung.

## G2-Achse (verstärkt)

Die Achse des Idlers G2 trägt den Zahndruck. Bei 50 % Servomoment (≈ 105 N, Hebel ≈ 11 mm) sind das mit Ø6 etwa
54 MPa Biegespannung, zu viel für gedrucktes PETG quer zu den Schichten. Deshalb: **Ø10**, konischer Fuß ohne
Absatz, und die Deckplatte ist **durchgehend 4,45 mm** dick (vorher 2,6 mm). Das ergibt rechnerisch etwa 12 MPa.

Die Platte hat kein rechteckiges Fenster mehr: Die erhabene Servo-Oberseite sitzt in einer **Tasche von unten**
(Restdicke 2,15 mm), nur um die Horn-Nabe von G1 gibt es ein Loch Ø19,6. Das Loch liegt ganz innerhalb der Tasche, die Lochwand ist deshalb überall gleich hoch und es gibt keine Stufe. So steht die Achse auf einer geschlossenen Fläche,
ohne Stufe zwischen Zapfen und Gehäuse. G2 hat eine Bohrung Ø10,3 und eine Senkung an der Unterseite für den Konus. G1 hat einen schmalen Abstandsring Ø18,4 zum Horn.

## Schrauben der Deckplatte und Rückwand

Das Fach ist **ein Teil** mit einer gemeinsamen, rundum verrundeten Außenhülle. Seine Rückwand ist 6,6 mm dick (4 mm Fachwand
plus 2,6 mm Verdickung über die ganze Breite und Höhe), ohne Naht und ohne aufgesetzten Block. Die Deckplatte folgt hinten
den Eckenradien des Fachs. Die Hand wird dadurch 3 mm länger als mit der 4-mm-Wand (174 mm).

- **Deckplatte:** vier Schrauben, **zwei hinten** in der verdickten Rückwand und **zwei vorn** in der auf 5,2 mm verbreiterten
  Vorderwand. Die Platte schließt hinten bündig mit der neuen Rückseite ab. Die dünnste Wand um eine Senkung Ø6,2 beträgt
  **1,2 mm** (hinten 4,3 mm von der Schraubenmitte bis zum Plattenrand, sonst mindestens 1,9 mm).
- **Gewinde der hinteren Schrauben:** 1,0 mm Wand zur Servo-Seite, 3,0 mm nach hinten.
- **Tasche** für die erhabene Servo-Oberseite: ein Streifen (x −9,3 … 9,9) plus ein Kreis um das G1-Loch, damit die Senkungen
  mindestens 2,1 mm Wand zur Tasche behalten.
- **Horn-Schrauben** des Roll-Servos: Senkung von der Servo-Seite, hinter jedem Kopf 0,8 mm Wand + 2,6 mm Verdickung + 2,8 mm
  Boss = 6,2 mm Material. Die Aussparung für die Horn-Mittelschraube ist Ø7,0 (1,8 mm Steg zu den vier Bohrungen).

**Montagereihenfolge:** erst das Fach mit den vier Horn-Schrauben (M3×6 von der Servo-Seite) an das Roll-Horn schrauben,
dann den Greifer-Servo von oben einsetzen und zuletzt die Deckplatte aufsetzen.

## Greifer-Mechanik

- Der Greifer-Servo dreht G1 um φ, G2 (Idler, gleich groß) dreht gegenläufig −φ. Modul 2, 14 Zähne.
- Je Seite Kurbel (am Zahnrad) und Lenker (an der Platte), je 34 mm, mit dem Finger als Koppel:
  Parallelogramm. Die Finger ändern ihre Orientierung nie, die Pads bleiben parallel.
- Der Lenker liegt unter der Platte (z −12,3…−5,3), die Kurbel darüber, sonst überdecken sie sich bei φ=0.
- **Hub:** φ −10,6° (Pads 0,5 mm auseinander) bis +50° → Öffnung **65 mm**.
- **Preis:** Die Spitzen laufen auf Kreisbögen und wandern beim Öffnen bis 12 mm zur Hand zurück.
- **Kraft:** bei vollem Servomoment (2,9 N·m) rund 90 N je Finger, mehr als PLA-Zähne dauerhaft halten.
  **Drehmomentgrenze des Servos auf etwa 50 % setzen.**

## Teile

Die Zahl `_xN` im Dateinamen ist die **Gesamtstückzahl für den linken und den rechten Greifer zusammen**
(beide Hände sind gleich, es gibt keine gespiegelten Teile). Je Arm ist es die Hälfte.

| Datei | zu drucken (L+R) | je Arm | Funktion | Druckrichtung |
| ----- | ---------------- | ------ | -------- | ------------- |
| `wrist_yoke_x2` | 2 | 1 | Joch + Fach für den Roll-Servo | auf der Seitenfläche (Ohren stehen) |
| `wrist_retainer_x2` | 2 | 1 | Deckplatte Roll-Servo | flach |
| `housing_tray_x2` | 2 | 1 | Greifer-Fach, Rückwand mit Roll-Interface | Boden auf dem Bett, Servo von oben einsetzen |
| `housing_top_plate_x2` | 2 | 1 | Deckplatte, durchgehend 4,45 mm, G2-Achse Ø10 angedruckt (kein Fenster, Servo-Oberseite in einer Tasche von unten) | flach, Achse oben, **PETG** |
| `link_post_x4` | 4 | 2 | hängender Drehpunkt der Lenker | Flansch unten |
| `drive_G1_x2` | 2 | 1 | Zahnrad G1 + Kurbel A | Zahnrad unten, Pin oben |
| `drive_G2_x2` | 2 | 1 | Zahnrad G2 + Kurbel B (Bohrung Ø10,3 für die dicke Achse) | Zahnrad unten, Pin oben |
| `link_A_x2` | 2 | 1 | Lenker A | Unterseite auf dem Bett, Pin oben |
| `link_B_x2` | 2 | 1 | Lenker B | Unterseite auf dem Bett, Pin oben |
| `finger_coupler_x4` | 4 | 2 | Koppelstange (Stab mit den zwei Zapfenbohrungen), gleich für A und B | auf der Oberseite, Passzapfen oben, Bohrungen mit 6,3 / 8,3 mm aufbohren |
| `finger_tip_A_x2` | 2 | 1 | Fingerstück A: Säule, Knie und Spitze | auf der Außenseite |
| `finger_tip_B_x2` | 2 | 1 | Fingerstück B (Spiegelbild von A) | wie A |
| `cap_d10_x4` | 4 | 2 | Sicherungskappe Ø10 (Kurbelzapfen) | flach |
| `cap_d12_x8` | 8 | 4 | Sicherungskappe Ø12 (Lenkerzapfen, Lenkerzapfen-Pins) | flach |
| `cap_d14_x2` | 2 | 1 | Sicherungskappe Ø14 (G2-Achse) | flach |
| `pad_tpu_x4` | 4 | 2 | TPU 95A | flach, 100 % Infill |

Zahnräder 0,15 mm Schicht, 5 Wände. Rest 0,2 mm, 4 Wände, 25 % Gyroid.
Das Joch ist mit 46 cm³ der schwerste Teil. Die Kraft läuft über die Ohren (4,5 mm, tragen das Drehmoment der
Hörner) in die Kastenwände (6,5 mm, halten nur Servo und Deckplattenschrauben). Ausdünnen ist noch offen.

## Zukaufteile (je Arm)

- **2× Feetech STS3215** (12 V, 30 kg·cm, wie die Arm-Servos): Greifer + Roll.
- **Schrauben, alle M3 mit Zylinderkopf (DIN 912).** Vorhanden sind M2, M3, M4 in 4, 6, 8, 12, 16, 20 mm.
  M2 und M4 werden nicht gebraucht. Alle Plattenköpfe sitzen 1 mm tief in der Platte.

| Zweck | Anzahl | Schraube |
| ----- | ------ | -------- |
| Greifer-Deckplatte auf das Fach (nur an der Vorderwand) | 4 | M3×16 |
| Roll-Deckplatte auf das Joch | 4 | M3×16 |
| Lenkerzapfen an die Deckplatte | 4 | M3×6 |
| Pin-Kappen (Kurbel-, Lenker-, Lenkerzapfen- und G2-Achse) | 7 | M3×8 |
| G1 auf das Greifer-Servo-Horn | 4 | M3×12 |
| Greifer-Rückwand auf das Roll-Horn (von innen) | 4 | M3×6 |
| Joch auf die Ellbogen-Hörner | 8 | M3×8 (4 je Horn, Ohr 4,5 mm) |
| Koppelstange auf das Fingerstück | 4 | M3×12 (2 je Finger) |

Zusammen 39 Schrauben je Arm. Beide Arme: 16× M3×16, 16× M3×12, 30× M3×8, 16× M3×6. Das Horn-Gewinde ist noch nicht bestätigt (M3 angenommen). Probiere an einem
freien Servo eine M3×6 von Hand in ein Horn-Loch. Wenn die Schraube nicht greift, sag Bescheid.
Prüfe beim Zusammenbau, dass die M3×12 am G1 und die M3×6 am Roll-Horn (greift ca. 2,4 mm ins 2,6 mm dicke Horn) nicht auf dem Servo aufsetzen.

## Was geprüft ist

- Alle Teile wasserdicht. Greifer-Sweep φ −12°…+50°, alle Paare: 0 mm³ Überlappung, kleinster Zahnabstand 0,18 mm.
- Beide Servo-Meshes (aus dem Roboter-CAD) sitzen in ihren Fächern ohne Berührung.
- **Schwenktest am Ellbogen gegen den ganzen Roboter** (Oberflächenabstand < 1 mm = Kontakt):
  alter Stumpf trifft das Bein bei **+30°** (zur Körpermitte), nach außen frei.
  Neue Hand mit geschlossenen Fingern: **+10°**, mit voll geöffneten Fingern schon bei 0°
  (Finger berühren das Hüftgelenk). Nach außen ist sie bis −100° frei.

## Probleme und Annahmen

- **Die Hand ist zu lang.** Spitze etwa 172 mm unter der Ellbogenachse, der Stumpf reichte 105 mm. Sie hängt auf
  Knie-/Oberschenkelhöhe. Nach innen schwenken geht kaum, nach außen und über die Schulter ist alles frei.
  Kürzen geht nur mit kleinerem Parallelogramm (C, S) oder kürzeren Fingern.
- Servo-Maße aus dem STS3215-Mesh (45,2 × 24,7 × 32,8 mm, Welle 9,85 mm vom Ende). Mit dem Messschieber nachprüfen,
  Luft je Seite 0,25 mm.
- Horn-Lochbild der Ellbogen-Hörner aus dem alten Finger gemessen (Winkel −7,5° + 90°·k, R7). Die Rückwand nutzt dasselbe
  Lochbild als Rundlöcher (Ø3,4, Winkel 0°/90°/…). Die Drehlage des Horns auf der Welle ist unbekannt und verschiebt
  nur die Roll-Nulllage.
- Servo-Kabel: Lage der Buchsen unbekannt, Kabelauslass im Roll-Fach und Greifer-Fach noch offen.
- Zahn- und Zapfenfestigkeit nur überschlagen. Das Drehmoment am Ellbogen/Schulter mit rund 220 g Hand ist nicht nachgerechnet.
- Der Schwenktest nutzt Punktproben auf dem Mesh (≈1 mm Raster), keine exakte Booleans.

## Offen

1. Hand kürzen (siehe oben). Der größte Hebel ist der Roll-Servo (52 mm lang) plus Greifer (≈122 mm).
2. Einbindung in WebUI/Sim (Visual + Masse), Servo-IDs 14/15 und 24/25 in `hardware/servo_ids.json`.
3. Joch ausdünnen, Kabelführung.
