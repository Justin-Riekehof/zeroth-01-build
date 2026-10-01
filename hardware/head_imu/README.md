# Kopf, linkes Auge: IMU (Waveshare RP2040-LCD-1.28) + Steckadapter

Das linke Auge trägt das **Waveshare RP2040-LCD-1.28**: rundes 1,28"-Display, RP2040 und die 6-Achsen-IMU
**QMI8658**. Das Auge hat zwei Nuten für die beiden Buchsenleisten der Platine. Zwischen Platine und Nuten sitzen
zwei gedruckte **Steckadapter**.

**Stand 2026-09-19: Die IMU-Buchsen sind als zwei Stege fest an der Hinterplatte, lose Adapter entfallen.**

| Datei | Inhalt |
| --- | --- |
| `print/neck_mount_imu.stl` | **Druckdatei**: Hinterplatte („Neck Mount“) mit zwei IMU-Stegen und Senkungen Ø5,5 × 3,5 für die Plattenschrauben, Rückseite aufs Bett, Stege nach oben. Ersetzt die Original-Hinterplatte **und** die Adapter |
| `neck_mount_imu.py` | baut sie: Original-Netz aus dem GLB reparieren, Stege anbauen, alte Nuten ausfüllen |
| `imu_adapter.py` | Adapter (CadQuery) → `stl/imu_adapter.stl` / `.step`, Standardlänge 10 mm (Display 0,9 mm hinter der Frontwand) |
| `stl/imu_adapter_flush.stl` | Adapter 13,43 mm lang (bündiges Display) – **nicht mehr drucken**, die Stege der Hinterplatte ersetzen ihn |
| `rp2040_lcd_128.py` | Modell der Platine, Einbaulage im Kopf mit beiden Adaptern, Abstandsprüfung → `stl/` (Modulrahmen), `stl/robotframe/`, `stl/rp2040_lcd_128.step`, `imu_pose.json` |

Ausführen mit `.cad/bin/python` aus dem Repo-Wurzelverzeichnis, danach `hardware/backpack_v2/viewer/export_attachments.py`
für die WebUI. Dort erscheint das Set **„Kopf links: IMU RP2040-LCD-1.28 + 2 Adapter“**, jedes Bauteil einzeln
schaltbar, dazu die IMU-Achsen als Pfeile. Das Original im Auge (K-Scale „LCD IMU“ + „Eye Mount“) ist per Haken
ausgeblendet. Kopfschale („Head“), Hinterplatte („Neck Mount“) und Halsstück („Torso to Neck“) lassen sich im selben
Panel einzeln ausblenden, um an die Einbausituation heranzukommen.

## Stege an der Hinterplatte (statt Adapter)

Jeder Steg hat die Form des bündigen Adapters, fest mit der Platte verbunden: außen 15,43 × 5,27 mm, vorn ein Schacht
13,43 × 3,27 × 4 mm (Maß der Plattennuten) mit 0,3-mm-Einführfase, Vorderkante bei y −15,36, 8,43 mm vor der
Plattenfläche. Die alten Nuten (21,5 mm tief bis zur Rückwand) sind massiv ausgefüllt. Das Display sitzt damit bündig
in der Augenöffnung. Geprüft: Die Leisten liegen auf dem Schachtboden auf, keine Überschneidung. Abstand Steg ↔
Platine 0,5 mm, ↔ Taster BOOT/RESET 0,2 mm, ↔ Akkustecker 0,63 mm, ↔ L1 0,94 mm.

Reparatur der Hinterplatte: Das GLB-Netz hatte 384 offene Kanten, alle an T-Stößen (Kante auf einer Seite geteilt,
auf der anderen nicht). Die Randkanten werden an diesen Punkten geteilt: 0 offene Kanten, jede Kante gehört genau zwei
Flächen, keine neuen Punkte, keine gefüllten Flächen. Die Geometrie ist also unverändert. Volumen 38,65 cm³, mit
Stegen 41,56 cm³ (vor den Änderungen unten).

## Weitere Änderungen an der Hinterplatte (2026-09-19)

* **Milk-Kamerahalter entfernt:** Am rechten Auge des Roboters (von vorn gesehen links) sind der U-Rahmen und die
  zwei Schraubdome weg. Den rechten U-Schenkel habe ich bis knapp über den Halskragen gekappt (z 409,95), der Kragen
  selbst ist unverändert. Das Camera Module 3 braucht den Halter nicht, es sitzt an der Kopfschale.
* **Schlitz für das Kameraflachband:** 18 × 3 mm in der Rückwand direkt hinter der Kamera (x −36,5 … −18,5,
  z 406,2 … 409,2), zentriert auf dem Band, Höhe aus dem 4-mm-Biegeradius. Das Band läuft von dort gerade in den
  Rucksack (siehe `hardware/head_cam`). Die Halsaussparung ist wieder im Original. Die Zwischenlösung mit dem
  aufgeweiteten Halsschlitz vom Morgen entfällt.
* Volumen: repariert 38,65 cm³ → ohne Halter und mit Kameraschlitz 35,02 cm³ → mit IMU-Stegen **37,93 cm³**.

## Senkungen für die Plattenschrauben (2026-09-22)

* Die vier Schraublöcher der Hinterplatte (Ø2,95 durch, Mitten x ±18,8 / z 402,5 und 444,6) bekommen auf der
  Rückseite (y 19,64) **Senkungen Ø5,5 × 3,5 mm** für Zylinderkopfschrauben [Vorgabe]. Das Original hatte dort nur
  eine Ø4,35 × 2 mm tiefe Vertiefung. Unter dem Kopf bleiben 1,5 mm der 5 mm dicken Rückwand.
* Druck: Die Rückseite liegt auf dem Bett, die Senkungen sind Sacklöcher von der Bettseite aus; der Ring zwischen
  Ø2,95 und Ø5,5 überbrückt 1,3 mm, kein Support nötig.
* Volumen mit Stegen: 37,93 → **37,75 cm³**. Werte in `neck_mount_imu.py` (`SCREW_HOLES`, `CBORE`).

## Adapter (ersetzt durch die Stege, nur noch Referenz)

| Merkmal | Maß |
| --- | --- |
| Female-Seite: Schacht für die Buchsenleiste | **13,43 × 3,27 mm** (= Nuten der Hinterplatte im CAD), 4 mm tief |
| Wand rundum, Boden | 1,0 mm → außen **15,43 × 5,27 mm** |
| Male-Seite: Zapfen in die Nut der Hinterplatte | **13,43 × 3,27 mm** (Negativ der Nut), 5 mm lang |
| Gesamt | 15,43 × 5,27 × 10 mm (Standard) bzw. **15,43 × 5,27 × 13,43 mm (bündig)**: 3,43 mm Zwischenstück zwischen Boden und Zapfen |
| Einführfase | 0,3 mm an Schachtöffnung und Zapfenspitze (ändert die Passung nicht) |

Schacht und Zapfen haben exakt die Nutmaße der Hinterplatte. Mit 13 × 3 war der Schacht zu eng für die Leiste und der
Zapfen zu locker in der Nut. `POCKET_CLEAR` / `TONGUE_CLEAR` in `imu_adapter.py` ändern das Spiel pro Seite.

**Druck:** Schachtöffnung aufs Bett, Zapfen nach oben. Kein Überhang, nur der Boden überbrückt 3 mm.

## Platine (Waveshare RP2040-LCD-1.28)

Quellen: Maßzeichnung im Waveshare-Wiki und der offizielle „3D Drawing“
(`files.waveshare.com/upload/a/a2/RP2040-LCD-1.28-3D-Drawing.zip`). `[S]` = geschätzt, weil das offizielle Modell dort
nur Platzhalter hat. Bitte an der echten Platine nachmessen.

| Merkmal | Wert |
| --- | --- |
| Umriss | Kreis R 18,25 + trapezförmige USB-C-Lasche (oben 12,81 breit, bis 21,25 über der Mitte) |
| Platine + Display | **4,0 mm gemessen**: Platine 1,6 + Luftspalt 0,8 + Display 1,6 (Displayfront bis Platinenrückseite) |
| Display | Ø35,6 `[S]`, aktive Fläche Ø32,4 |
| Buchsenleisten H1/H2 | 2×10, Raster 1,27, SMD; Körper 3,0 × 13,1, Höhe 4,5 `[S]`; Mitten ±13,50 von der Platinenmitte (**27,00** auseinander), parallel zur USB-Richtung |
| Weitere Bauteile hinten | USB-C 3,25 hoch, Taster BOOT/RESET 2,5, Akkustecker MX1.25 ~3,4 `[S]`, D1, L1, RP2040, Quarz |
| IMU-Chip QMI8658 | fast unter der Displaymitte (−0,28 / +0,20 mm); Achsen laut Bestückungsdruck: X → USB, Y → H1, Z → aus der Rückseite |

## Einbaulage im Kopf

**Das Display sitzt bündig in der linken Augenöffnung** (`DISPLAY_FLUSH = True`): Displayfront auf der Gesichtsfläche
(y −19,86), Platinenrückseite y −15,86. Die USB-Lasche der Platine liegt in einer Aussparung der Kopfschale Richtung
Kopfmitte (siehe `hardware/head_cam`). Die Hinterplatte („Neck Mount“) hat zwei Nuten, im CAD 13,43 × 3,27 mm
(gedruckt gemessen 13 × 3), Öffnung bei y −6,93, mindestens 9,7 mm tief, Mitten x 27,67 / z 410,06 und 437,09. Damit
die Zapfen der Adapter trotzdem 5 mm in diesen Nuten stecken und die Schultern auf der Hinterplatte liegen, sind die
Adapter 3,43 mm länger. Der Wert gilt für 4,5 mm hohe Buchsenleisten: Ist die echte Leiste niedriger, sitzt das Display
um die Differenz weiter hinten, höchstens um 0,5 mm. Ausrichtung wie die „LCD IMU“ im CAD: USB-Lasche zur Kopfmitte,
H1 oben, H2 unten.

**IMU für die Simulation** (`imu_pose.json`, Assembly-Rahmen: +X links, +Y hinten, +Z oben):

| | Roboter-Rahmen |
| --- | --- |
| Chip-Mitte | (27,42 / −15,37 / 423,84) mm |
| X_imu | −X (zur Kopfmitte) |
| Y_imu | +Z (nach oben) |
| Z_imu | +Y (nach hinten) |

Der Kopf hat kein Gelenk. Die IMU ist damit starr mit dem Torso verbunden.

## Prüfung

| Prüfung | Ergebnis |
| --- | --- |
| Adapter ↔ Taster BOOT/RESET | **0,20 mm** (mit 15,43 mm Länge; bei 15 mm waren es 0,30, gegen das Original-STEP 0,35): die Stirnwand steht knapp neben den Tastern |
| Adapter ↔ Akkustecker / L1 | 0,61 / 0,93 mm |
| Adapterrand ↔ Platine | 0,5 mm Luft. Die 4,5 mm hohe Leiste liegt auf dem Schachtboden auf, der Rand bleibt über den SMD-Beinchen (0,25 mm) |
| Leiste ↔ Schacht | Leiste 13,1 × 3,0 laut STEP (Platzhalter), Schacht 13,43 × 3,27 |

**Achtung Leistenhöhe:** Ist die echte Buchsenleiste niedriger als etwa 4,3 mm, sitzt der Adapterrand auf den
Lötbeinchen der Leiste auf. Dann den Schacht flacher machen (`POCKET_D`) oder die Leiste nachmessen und `HDR_H`
anpassen.
