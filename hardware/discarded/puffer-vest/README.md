> **VERWORFEN (2026-10-20).** Dieses Konzept wird nicht weiterverfolgt und ist nur noch Referenz. Es wurde nie gedruckt
> oder getestet; Pfade in den Befehlen unten zeigen noch auf `hardware/vest/` und müssen auf `hardware/discarded/puffer-vest/`
> angepasst werden. Siehe [../README.md](../README.md).

# Puffer-Weste (TPU 95A) — Aufprallschutz für Brust und Schultern

v0.1, **nicht gedruckt und nicht am Roboter getestet**. Zwei Wabenpuffer vorn auf Brust/Schulter (dort schlägt der
Roboter beim Vornüberfallen zuerst auf) und ein Netzgurt, der **Torso und Rucksack zusammen** umspannt. Alles ist
Parameter in [make_vest.py](make_vest.py); die Maße stammen aus dem gepinnten CAD und dem Rucksack v4.6.

```bash
.cad/bin/python hardware/vest/make_vest.py      # Druckdaten stl/ + getragener Zustand stl/robotframe/ + vest.json
.cad/bin/python hardware/vest/check_vest.py     # Rucksack-Kollision, Abstände zu allen Bauteilen, Bettgröße
.cad/bin/python hardware/vest/render_preview.py # preview.png (4 Ansichten am Roboter)
.cad/bin/python hardware/backpack_v2/viewer/export_attachments.py   # Weste erscheint in der Servo-WebUI (Attachments)
```

## Teile (alle TPU 95A, flach gedruckt, kein Support)

| Datei | Inhalt | Größe (mm) | Masse |
| --- | --- | --- | --- |
| `puffervest_1-front_tpu.stl` | 2 Puffer (Wabe + Haut), Netzgurt Vorderseite + Ecken, 2 Haltelaschen | 232 × 109 × 22 | ≈ 95 g |
| `puffervest_2-rear-A_tpu.stl` | Rückgurt −X-Seite mit **Spannschnalle** (Rahmen, 3 Stege) | 230 × 28 × 3,2 | ≈ 10 g |
| `puffervest_3-rear-B_tpu.stl` | Rückgurt +X-Seite, loses Ende (60 mm) | 230 × 20 × 2,4 | ≈ 10 g |

Zusammen ≈ 115 g TPU (Roboter laut `mass_model.json`: nur Elektronik 430 g, dazu Servos und Druckteile). Der
Schwerpunkt wandert etwas nach vorn/oben; falls die Weste im Dauerbetrieb bleibt, die Masse im Sim-Modell nachtragen.

Hardware: **4× M3×10 + Mutter + große Unterlegscheibe** (zwei Überlappungsverbindungen vorn-seitlich).

## Aufbau am Roboter

* **Gurt** 20 mm hoch auf z 300…320: unter den Schulter-Yaw-Bügeln (ab z 327, x ≥ 75) und über der LiPo-Schublade
  (+X-Wand, bis z 294). Er läuft vorn am Torso entlang, über die Torsoecken, auf einer geraden Flanke zu den
  vorderen Rucksackkanten, an den Rucksackseiten und über den Deckel. An den Flanken steht er frei (Torso ist dort
  schmaler als der Rucksack) — gehalten wird er vorn am Torso, an den Rucksackkanten und über die Puffer.
* **Puffer** (je 69 × 58 × 22 mm, z 323…382, x 2…71): Rückplatte 2,4 mm mit Entlüftungslöchern, Rautenwabe
  (Wand 1,4, Zelle 15), 1,2 mm Haut, Rand gerundet. Vorderkante bei y = −47,8, also deutlich vor den Schulterbügeln
  (y = −28). Sie enden bei x = 71, damit die Bügel (x ≥ 75) frei schwenken.
* **Haltelasche** (12 mm breit, x 54,5…65,5): geht von der Pufferoberkante über die 5-mm-Fase der Torso-Vorderwand,
  über die Wandoberseite und hinter die Wand in die Schulterwanne (Wulst 6 mm). Sie trägt das Gewicht — ohne sie
  rutscht der Gurt auf dem nach unten schmaler werdenden Torso ab. Freiräume: Hals-Bügel 4,5 mm, Schulter-Pitch-Motor
  (z ≤ 371) 7 mm.
* **Lap-Verbindung** (2×, Flanke vor den Rucksack-Vorderkanten): Rückgurt liegt 26 mm über dem Vorderteil, 2× M3.
* **Spannschnalle** auf dem Deckel bei x = 30 (dort hat der Deckel auf z 296…324 keine Öffnung):
  Rückgurt B von der +X-Seite kommend **über Steg 1, durch Schlitz 2 nach unten, unter dem Mittelsteg, durch Schlitz 1
  nach oben, über Steg 3** und als Ende auf dem Gurt A zurück. Zug am Hauptteil klemmt (Leiterschloss-Prinzip);
  zum Lösen das Ende anheben und nachlassen. Reicht die Reibung auf TPU nicht, eine handelsübliche
  20-mm-Leiterschnalle ersetzt den Rahmen (Gurt A am Ende mit M3 an die Schnalle klemmen).

## Druckhinweise (Bambu P2S, Direct-Drive, 0,4 mm Düse, Bambu TPU 95A HF)

* 0,2 mm Schicht, 20–25 mm/s, Trocknen nicht vergessen, Rückplatte/Gurt auf dem Bett (glatte Platte, Kleber).
* **Wände 4, Boden/Deckel 5 Schichten**, Infill 15 % Gyroid; die Wabenwände (1,4 mm) werden reine Perimeter —
  „Dünne Wände erkennen“ an. Die Haut (1,2 mm) überbrückt 15-mm-Zellen: sieht sie schlecht aus, `SKIN` auf 0 setzen
  (offene Wabe, druckt sicher).
* Netz-Stege sind ≈ 3 mm breit; Gurt-Netz auf Wunsch mit `NET_H`/`NET_PITCH` verkleinern.

## Bekannte Grenzen / offen

* Lüftungsschlitze des Rucksacks (z 300…318, x −40…4) liegen unter dem Netzgurt (≈ 36 % offen) — Luft kommt durch,
  aber schlechter. Bei Wärmeproblemen Gurt nach oben/unten verschieben (`BELT_Z`, Pufferunterkante `PAD_Z`).
* Die Pufferdicke (22 mm) schränkt Armbewegungen vor der Brust ein (Greifer zur Brust, lift_bottle-Demo): im Sim/Pose
  prüfen, ggf. `PAD_T` reduzieren.
* Dämpfung ist nicht gemessen. Wabenwand/Zellgröße/Haut sind die Stellschrauben; Fallversuch auf Matte und Wand
  1,2 ↔ 1,8 mm vergleichen.
* Die Reibung der Schnalle und der Haltewulst sind ungetestet.
