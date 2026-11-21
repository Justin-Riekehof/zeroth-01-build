# Halsstück („Torso to Neck“), verstärkt und durchgeschraubt

**Problem (2026-11-07):** Die beiden Schraublaschen, mit denen das Halsstück am Torso hängt, sind beim ersten Kontakt
des Kopfes mit einem Hindernis gebrochen. Seitdem ist der Kopf leicht nach hinten geneigt.

**Ursache:** Das Halsstück liegt nur auf der 10 mm schmalen Leiste vorn am Torso auf (y −20 … −10, z 386,6). Dahinter
ist der Torso offen. Gehalten wurde es von zwei waagerechten M3-Schrauben (x ±32,5, z 379) in Ø4-Einschmelzmuttern
dieser Leiste. Der Schraubenkopf drückte auf eine **2,5 mm** dicke Wand. Unter der Ø6,5-Senkung blieben **2 mm**, die
Lasche war 12,5 mm breit. Ein Stoß gegen den Kopf hebelt mit etwa 40 mm gegen nur 5 … 8 mm zwischen Schraube und
Drehpunkt. Jede Schraube zieht dann mit dem 5- bis 8-fachen der Kraft am Kopf an der dünnen Wand.

| Datei | Inhalt |
| --- | --- |
| `print/neck_piece_PETG_front_project.3mf` | **Bambu-Studio-Projekt** für den P2S in PETG, siehe `print/PRINT.md` |
| `print/neck_piece_PETG_front.3mf`, `print/neck_piece_reinforced.stl` | nur Geometrie, Krallenfront aufs Bett |
| `make_neck_piece.py` | baut das Teil aus dem Original im gepinnten GLB, prüft Abstände, Schrauben und Mutternweg |
| `make_print.py`, `make_bambu_project.py` | Druckplatte bzw. Projekt mit allen Einstellungen |
| `stl/robotframe/` | neues und originales Halsstück, Schrauben + Muttern (Assembly-Rahmen, für die WebUI) |
| `neck_piece.json` | Volumen, Abstände zu den Nachbarteilen, Schraubenlage |

Ausführen mit `.cad/bin/python hardware/neck_piece/make_neck_piece.py`, danach `make_print.py`,
`make_bambu_project.py` und `hardware/backpack_v2/viewer/export_attachments.py`. In der WebUI heißt das Set
**„Hals: verstärktes Halsstück“**, das Original ist per Haken ausgeblendet.

## Aufbau (v2: durchgeschraubt)

Die Torso-Frontleiste (15,4 mm) wird zwischen Kralle und Laschen eingeklemmt:

```
 vorn                                                                   hinten
 Senkkopf M3x35 | Kralle 3,2 | Torsoleiste 15,4 (Einschmelzmutter aufgebohrt) | Laschenwand 8 | Sicherungsmutter
```

| Merkmal | alt | neu |
| --- | --- | --- |
| Lasche | 12,5 breit, hohl, Fuß z 374 | massiver Block x −9 / +7,5 um die Schraube, y −10 … 14,64, Fuß z 371,5 |
| Wand hinter der Torsoleiste | 2,5 mm | **8 mm** (Ø3,3 durch) |
| hinter der Wand | Senkung Ø6,5 für den Schraubenkopf | **Sechskantschacht SW 5,8** bis zur Rückseite, hält die Mutter verdrehsicher |
| Material unter dem Schacht | 2 mm | 4,6 mm, seitlich 4,1 / 5,6 mm |
| Frontkralle | – | **3,2 mm** über die Rundung und die ganze Torsofront bis z 371,5, x ±42, 0,25 mm Spiel; Ø3,3 + 90°-Senkung Ø7 je Schraube |

**Wirkung:** Ein Stoß nach hinten drückt die Kralle außen gegen die Torsofront und den Laschenfuß innen gegen die
Leiste, also Druck auf große Flächen. Stöße nach vorn oder zur Seite gehen über die Schrauben. Diese ziehen jetzt aber
nicht mehr an einer Gewindebuchse, sondern spannen Kralle, Leiste und Laschenwand zu einem Paket zusammen. Ausreißen
kann nur noch ein Schraubenkopf durch 3,2 mm Kralle, die dabei aber direkt auf dem Torso aufliegt, oder die Mutter
durch 8 mm Laschenwand. Die nächste Schwachstelle ist der Kopf selbst (Zapfen ↔ Hinterplatte), der bleibt vorerst so.

Volumen 34,0 → 47,3 cm³, gedruckt etwa 46 g PETG statt rund 30 g. Der Schwerpunkt bleibt praktisch auf dem Torso.

## Teile

* 2 × **M3×35 ISO 10642** (Senkkopf, Innensechskant)
* 2 × **Sicherungsmutter DIN 985 M3** (Nylonring, SW 5,5, 4 mm hoch)

Der Kopf sitzt 0,2 mm unter der Krallenfläche (y −28,65). Die Spitze endet bei y +6,35, also 4,4 mm hinter der Mutter
(y −2 … +2), damit der Nylonring voll greift. M3×30 wäre zu kurz.

## Umbau am Torso (einmalig)

Die Einschmelzmuttern bleiben im Torso, ihr **Gewinde muss aber weg**. Läuft die Schraube im Gewinde der Buchse,
klemmen Kralle und Lasche jeweils nur gegen die Buchse und nicht gegeneinander, dann bringt das Durchschrauben kaum
etwas. Ab y −20 endet das Buchsenloch, bis zur Torsofront (y −25,4) bleiben 5,4 mm Wand.

1. Altes Halsstück abnehmen.
2. Neues Halsstück aufsetzen (Kralle vorn über die Kante, Laschen innen an die Leiste) und von Hand andrücken.
3. Mit einem **3,2-mm-Bohrer von vorn durch die Krallenlöcher** bohren: erst durch die 5,4 mm Torsowand, dann durch die
   Einschmelzmutter. Die Ø3,3-Löcher der Kralle dienen als Bohrschablone, so treffen die Bohrungen die Buchsenachse.
   Langsam bohren, damit sich die Messingbuchse nicht im Torso mitdreht.
4. Halsstück abnehmen und die Späne aus Torso, Buchse und Laschen entfernen.

### Alternativ: Torso mit Durchgangsbohrungen drucken

`make_torso.py` schneidet in den Torso zwei Ø3,3-Bohrungen (x +32,44 / −32,54, z 379) von der Front (y −25,4) durch das
ganze Frontleisten-Paket bis y −10. Ergebnis: `stl/torso_neck_through.stl` (Roboterrahmen, mm). Beim neu gedruckten Torso
entfallen Aufbohren und Einschmelzmuttern am Hals. Ausführen mit `.cad/bin/python hardware/neck_piece/make_torso.py`.

## Montage

1. Bei abgenommenem Rucksack je eine Mutter von hinten in den Sechskantschacht der Lasche schieben, bis zum Grund
   (y −2). Mit einem Stift oder Inbusschlüssel nachdrücken. Der Weg bis y 37,5 ist frei geprüft.
2. Halsstück von oben aufsetzen.
3. Schrauben von vorn durch Kralle und Torso eindrehen. Die Mutter kann sich im Schacht nicht mitdrehen. Anziehen, bis
   der Senkkopf bündig sitzt. Nicht überdrehen, PETG gibt unter dem Senkkopf nach.

Zum Lösen später reicht es, die Schrauben von vorn herauszudrehen. Die Muttern bleiben im Schacht, können bei
abgenommenem Rucksack aber nach hinten herausfallen.

## Prüfung

Das neue Material wurde gegen alle Teile des gepinnten CAD im Umkreis geprüft, dazu Hinterplatte mit IMU-Stegen,
Kopfschale mit Kamera und Rucksack. Ergebnis: keine Überschneidung. Kleinste Abstände: Torso 0 (Anlage an der Leiste,
gewollt), Milk-V-Stapel 1,7 mm, Kopfschale 1,2 mm, Schultermotoren 3,8 mm. Vor der Torsofront liegt in der Grundstellung
nichts. Bei Armhaltungen direkt vor der Brust (Greifen vor dem Körper) steht die Kralle 3,45 mm vor der alten
Torsofront. Das Teil lässt sich weiterhin senkrecht von oben aufsetzen.

## Druck

Krallenfront aufs Bett, siehe `print/PRINT.md`. PETG, 5 Wände, 40 % Gyroid, normale Stützen (snug), etwa 1 h 56 min und 48 g.
