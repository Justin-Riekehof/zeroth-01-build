# Druck: Halsstück verstärkt, durchgeschraubt (Bambu Lab P2S, PETG)

| Datei | Inhalt |
| --- | --- |
| `neck_piece_PETG_front_project.3mf` | **Bambu-Studio-Projekt** mit allen Einstellungen: öffnen, „Slice plate“, drucken |
| `neck_piece_PETG_front.3mf` | nur Geometrie, Lage wie unten, mittig auf der 256-mm-Platte |
| `neck_piece_reinforced.stl` | dieselbe Lage als STL |
| `plate.png` | Draufsicht, Vorder- und Seitenansicht der Lage |

Erzeugt mit `.cad/bin/python hardware/neck_piece/make_print.py` (Geometrie) und `make_bambu_project.py` (Projekt,
`--slice` slict zur Kontrolle mit).

## Lage

**Krallenfront aufs Bett** (y −28,85, 1202 mm² Auflage). Maße 100 × 35 × 43,5 mm. Die Schraubachsen stehen senkrecht:
Löcher und Sechskantschächte werden maßhaltig, und die Ausreißfläche der 8-mm-Laschenwand läuft quer durch die Lagen statt
zwischen ihnen. Die Senkungen öffnen zum Bett (45°-Kegel, druckbar), die Sechskantschächte nach oben.

Warum nicht die Rückseite aufs Bett (wie in v1): Dann läge die Kralle oben, und ihre gerundete Innenseite, die mit
0,25 mm Spiel am Torso sitzt, müsste auf 1019 mm² Stützen gedruckt werden. So werden stattdessen die **ebenen**
Frontflächen von Laschen und Schürze (y −10) gestützt. Die liegen innen an der Torsoleiste an und lassen sich leicht plan
feilen. Kennzahlen: Rücken 595 mm² Auflage und 2870 mm² Überhang, Front 1202 mm² Auflage und 2018 mm² Überhang.

## Einstellungen

Basis: `Bambu Lab P2S 0.4 nozzle`, `0.20mm Standard @BBL P2S`, `Bambu PETG Basic @BBL P2S 0.4 nozzle`, Textured PEI
Plate. Düse 250 °C, Bett 70 °C (PETG-Standard).

| Einstellung | Standard | hier | Grund |
| --- | --- | --- | --- |
| Wände | 2 | **5** | Laschen um den Sechskantschacht fast massiv |
| Füllung | 15 % Gitter | **40 % Gyroid** | Festigkeit in alle Richtungen (Stöße auf den Kopf) |
| Stützen | aus | **an, normal (auto), Stil „snug“** | unter Laschen-/Schürzenfront und Zapfen, siehe unten |

Alles andere bleibt P2S-Standard. In der GUI sind die geänderten Werte als Abweichung markiert.

**Stützen (2026-11-07):** Erster Druck mit Baumstützen (Standardstil): Die Düse hat den freistehenden Baum vor dem
Teil umgestoßen, der unter dem Zapfen 21 mm hoch steht und nur etwa 3 mm Taille hatte. Danach hing der Zapfen in der Luft,
oben entstand Spaghetti. Dickere Bäume (Tree Strong, 8-mm-Äste) wurden zu hohlen Röhren mit 2 Wänden, die am Teilrand
als offene Ringe enden. Deshalb jetzt **normale Stützen „snug“**: vorn ein geschlossener Gitterblock mit etwa 20 × 10 mm
Grundfläche auf dem Bett, im Spalt zwischen Kralle und Laschen ein Block, der sich von der offenen Rückseite heraushebeln lässt.

**Slice-Kontrolle (Bambu Studio 2.9.1, CLI):** 1 h 56 min, 47,8 g PETG inkl. Stützen, nichts außerhalb der Platte.

## Nach dem Druck

* Stützen zwischen Kralle und Laschen entfernen. In diesen 15,4 mm breiten Spalt kommt die Torsoleiste. Die
  Frontflächen der Laschen und der Schürze (y −10) plan feilen, bis das Teil ohne Druck auf die Leiste rutscht.
  Die Stützen im Spalt stehen auf der Krallen-Innenseite: Abdrücke dort glätten.
* Sechskantschächte prüfen: Eine M3-Mutter (SW 5,5) muss bis zum Grund durchrutschen.
* Torso aufbohren und montieren: siehe `../README.md` („Umbau am Torso“, „Montage“).
