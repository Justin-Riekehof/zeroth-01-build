# Kopf, rechtes Auge: Raspberry Pi Camera Module 3 (Standard, 75°)

Die Milk-Kamera im rechten Auge wird durch ein **Raspberry Pi Camera Module 3** mit Standardobjektiv ersetzt.
Angepasst wird dafür nur die **Kopfschale**. Die **Hinterplatte** („Neck Mount“) bleibt unverändert: Die Kamera sitzt
komplett zwischen Frontwand und Hinterplatte und endet etwa 8 mm vor dem alten Milk-Halter.

| Datei | Inhalt |
| --- | --- |
| `head_cam3.py` | Kopfschale umbauen, Kameramodell, Prüfungen → `stl/robotframe/`, `print/`, `cam3_pose.json` |
| `print/head_shell_cam3.stl` | **Druckdatei** Kopfschale (Gesicht nach unten; Ausrichtung im Slicer frei wählbar) |
| `stl/robotframe/*.stl` | Kopfschale, Kamera, Kabel, Sichtfeld im Assembly-Rahmen (für die WebUI) |

Ausführen mit `.cad/bin/python hardware/head_cam/head_cam3.py` (braucht cadquery, trimesh, manifold3d), danach
`hardware/backpack_v2/viewer/export_attachments.py`. In der WebUI heißt das Set **„Kopf rechts: Camera Module 3 +
angepasste Kopfschale“**. Die Original-Kopfschale und die Milk-Kamera sind per Haken ausgeblendet.

## Änderung an der Kopfschale

| Merkmal | Maß |
| --- | --- |
| Rechte Augenöffnung (vorn Ø37,4 mit Fase, dahinter Ø14,6) | mit einer Blende in Wanddicke geschlossen (y −19,86 … −17,36, 2,5 mm) |
| Objektivöffnung | Ø9, vorn 0,8 mm × 45° angefast, mittig auf dem Auge (x −27,5 / z 423,56) |
| Schraubdome | 4 × Ø4,5, 5,4 mm lang, innen auf der Blende; **Bohrung Ø1,9** für M2 (Wand 1,3 mm), 1,2 mm in die Wand (vorn bleiben 1,3 mm geschlossen) |
| Lochbild | 21 × 12,5 mm, bei x −17,0 / −38,0 und z 435,52 / 423,02 |
| Volumen | 40,58 → 41,56 cm³ (inkl. linkes Auge) |

**Kamera montieren:** Platine mit der Objektivseite auf die Dome, 4 × **M2×6** von hinten durch die Platine in die
Dome. Das Flachbandkabel zeigt nach unten. Die Köpfe an den beiden unteren Löchern dürfen höchstens Ø4,9 haben, denn
dort beginnt nach 2,45 mm der Kabelstecker. Ein M2-Zylinderkopf (Ø3,8) passt.

## Linkes Auge (IMU-Display)

Im GLB ist die runde Augenöffnung nur ein grobes Zwölfeck: 35,35 mm über die Flächen, da ginge das Display nicht
hinein. Die Öffnung ist deshalb **rund nachgeschnitten, Ø37,0**, mit der Originalfase vorn (Ø37,8). Sie ist auf die
IMU-Platine zentriert, die 0,1 mm neben der CAD-Augenmitte liegt. Richtung Kopfmitte gibt es eine **Aussparung für die
USB-Lasche** durch die ganze Wand. Sie deckt das Trapez aus der Waveshare-Zeichnung ab und das gemessene Maß
16 × 4 mm, jeweils mit 0,5 mm Spiel. Das Display sitzt damit bündig in der Öffnung. Prüfung mit dem IMU-Modell:
keine Überschneidung, Display 0,69 mm, Platine mit Lasche 0,25 mm, alles andere ≥ 1,9 mm von der Schale entfernt.

## Lage und Prüfung

| | Wert |
| --- | --- |
| Optische Achse | auf der Augenmitte, horizontales Sichtfeld (66°) waagerecht |
| Objektivfront | 1,0 mm hinter der Gesichtsfläche (Autofokus fährt bis 0,24 mm heraus) |
| Platinenvorderseite | y −11,95 |
| Objektivgehäuse ↔ Frontwand | 0,58 mm |
| Kabelstecker J1 ↔ Kopfschale | 1,15 mm |
| Sichtkegel 66° × 41° (35 mm tief) ↔ Kopfschale | frei (0 mm³ Überschneidung) |

Kameramaße aus dem offiziellen STEP-Modell und den Zeichnungen von Raspberry Pi
(`datasheets.raspberrypi.com/camera/camera-module-3-step.zip`). Der Abstand Objektivgehäuse → Kabelkante ist
**4,5 mm gemessen**, das STEP hat 4,06. Die Platinendicke ist unkritisch (Auflage auf der Vorderseite, STEP 0,76,
Zeichnung 1,12).

## Kabelweg (2026-09-19)

Das 16 mm breite Band kommt unten aus dem Stecker J1 (z 413,7), läuft 2 mm senkrecht und biegt dann mit **4 mm
Radius** waagerecht nach hinten (z 407,7). So geht es gerade durch den **18 × 3 mm großen Schlitz in der
Kopf-Rückplatte** (x −36,5 … −18,5, z 406,2 … 409,2, direkt hinter der Kamera), über den Luftspalt zum Rucksack
und durch den gleichen Schlitz in der Rucksack-Grundplatte zur CSI-Buchse des quer liegenden Pi, rund 20 mm tiefer.
Weg rund 60 mm plus Biegungen, **das 200-mm-Kabel reicht.** Geprüft: 1,0 mm Abstand zur Kopfplatte, 1,3 mm zur
Kopfschale, Halsstück und Torso weit weg. Die Schlitzlage steht in `cam3_pose.json` (`cable_slot`), Kopfplatte und
Rucksack lesen sie von dort. Kopfboden und Halsaussparung sind wieder im Original.

## Quelle der Kopfschale

Die Kopfschale ist das Bauteil „Head“ aus `resources/cad/z001-opus-m-93de7567.glb`, also der gedruckte Stand: Die
IMU-Nuten der Hinterplatte stimmen exakt. Im GLB besteht „Head“ aus zwei Netzen, der Schale und der ebenen
Gesichtsfläche. Zusammengeschweißt ergeben sie einen geschlossenen Körper **ohne Reparatur**, Geometrie unverändert.
Die Hinterplatte wird in `hardware/head_imu/neck_mount_imu.py` repariert (T-Stöße vernäht) und umgebaut.
