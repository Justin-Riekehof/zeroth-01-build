# Fin-Ray-Finger für den Unterarm (Greif-Stumpen)

Ersatz für den PETG-Stumpen `FINGER_1` / `FINGER_1_2` (Onshape-Baugruppe "Opus").
PETG ist glatt und hart – Flaschen rutschen weg. Neu: **harter Träger + weicher
Fin-Ray-Pad aus TPU**, der sich unter Last um das Objekt legt.

Die Teile werden von [make_finger.py](make_finger.py) erzeugt (CadQuery, alle Maße
Parameter). Die STLs liegen in [stl/](stl/), im selben Koordinatensystem wie die
Original-Meshes `FINGER_1.stl` / `FINGER_1_2.stl`. Die Onshape-Datei selbst ist
unverändert (nicht von hier aus editierbar).

## Aufbau (3 Teile je Arm)

| Teil | Material | Funktion |
| ---- | -------- | -------- |
| `carrier` | PETG (oder PA-CF) | Starrer Bügel: zwei 1,5-mm-Ohren mit dem Original-Lochbild (Ø6,9 Mitte + 4×Ø2,8 auf R≈7,1), ausgesparter Hals, Schwalbenschwanz-Schiene, Anschlagplatte |
| `pad` | **TPU 95A** | Fin-Ray-Blatt, 36 mm lang, 12 mm dick an der Basis → 2,4 mm an der Spitze, 37 mm breit |
| `retainer` | PETG | 2-mm-Platte + 1× M2×8 Schraube, sichert den Pad gegen Herausrutschen in +z |

Warum nicht alles aus TPU? Die Ohren klemmen auf dem Servo-Horn (M2,5-/M3-Schrauben);
TPU kriecht und gibt dort nach → Spiel im Gelenk. Die Kraft geht deshalb durch hartes
Material, nur die Kontaktzone ist weich. Der Pad wird auf die Schiene geschoben
(Schwalbenschwanz trägt alle Lasten in der Greifebene), nur die z-Richtung hält die
M2-Schraube. Pad ist damit einzeln tauschbar (85A / 90A / 95A, andere Rippenwinkel).

## Fin-Ray-Geometrie

```
 Basis (fest)              Spitze
 ┌────────┐ ____----####
 │ Rail   │#============╲   t=0  Kontaktwand  (gerade, 1,6 mm, mit 0,45-mm-Rillen)
 │        │  ╲  ╲  ╲  ╲ ╲   Rippen 1,2 mm, 25° zur Wandnormalen,
 │        │#====================  Rückwand-Ende zur BASIS geneigt
 └────────┘                 Rückwand verjüngt zur Spitze
```

Kontaktwand und Rückwand treffen sich an der Spitze; dazwischen Querrippen. Drückt
das Objekt auf die Kontaktwand, kippen die Rippen und die Spitze krümmt sich zum
Objekt (Fin-Ray-Effekt).

**Was geprüft ist und was nicht:** Ein lineares Balkenmodell (nur Wände + Rippen,
E = 26 MPa) bestätigt die Rippenrichtung: Mit zur Basis geneigten Rippen weicht die
Spitze am wenigsten in Kraftrichtung aus, bei zur Spitze geneigten am stärksten.
Das eigentliche Umgreifen ist ein Effekt großer Verformung und ist **nicht
simuliert** – die Parameter (Rippenwinkel, Teilung, Wanddicken) sind Startwerte aus
der Literatur und müssen am Druckteil abgestimmt werden.

## Druck

**Pad (TPU 95A)** – 0,4-mm-Düse, 0,2 mm Schicht, Direct-Drive empfohlen
- Liegend drucken (z-Achse des Teils = Druckrichtung nach oben); die Rippenebene liegt dann in der Schichtebene – die Biegung läuft entlang der Schichten, nicht quer
- Filament trocknen (≥ 6 h bei 55 °C); 20–25 mm/s, Retraction aus oder ≤ 1 mm
- 4 Perimeter für die Wände, Rippen 3 Perimeter (1,2 mm), 100 % Infill (es gibt praktisch keins), kein Support nötig, keine Kühlung für die ersten 3 Schichten
- Stützrippen/Brim vermeiden – die Schwalbenschwanznut muss sauber sein; 0,1 mm Elefantenfuß-Kompensation

**Träger/Retainer (PETG)** – 0,2 mm, 4 Wände, 40 % Gyroid; Ohren liegen auf dem Bett. Löcher ggf. mit 2,8-mm-Bohrer nachziehen.

Masse (100 %-Rechnung): Pad 6,9 cm³ ≈ 8 g, Träger 6,9 cm³ ≈ 8 g – zusammen weniger als der alte Stumpen (14,2 cm³ Außenvolumen).

## Variante für nur ein Filament (ohne AMS): `--single`

```bash
python3 make_finger.py --single          # rechts -> stl/finger_R_finger_tpu.stl
python3 make_finger.py --single --left   # links
```

Ein einziges Teil komplett aus **TPU 95A** (Bambu TPU 95A HF läuft auf dem P2S), ohne Schiene, Retainer und Hals-Aussparungen. Der Hals ist massiv, damit die Biegung im weichen Blatt bleibt und nicht im Hals sitzt. Das Gesamtvolumen beträgt etwa 18,9 cm³ (rund 23 g bei 100 %).

**Achse:** Das Blatt liegt auf einer Geraden durch die Nabenmitte (Standard `--axis-angle 27`, entspricht der Hub-Hals-Achse des Originals) und ist ohne Knick mit dem Hals verbunden (glatte Hülle um Nabe und Blattansatz). Die Spitze liegt dadurch rund 20 mm weiter außen als beim alten Stumpen, mit `--axis-angle` (Grad von −y nach −x) und `--base-dist`/`--length` lässt sich das anpassen. Die Zwei-Material-Variante (Träger/Pad/Retainer) nutzt noch das alte gerade Layout und ist nicht angepasst.

Weil die Ohren jetzt ebenfalls weich sind, gelten drei Anpassungen:
- **Ohren 3 mm statt 1,5 mm:** Die Verdickung geht nur nach außen (`--ear-extra 1.5`), die Innenseite zum Servo bleibt gleich. Die Servo-Schrauben müssen dafür 1,5 mm länger sein.
- **Unterlegscheiben:** Lege große Scheiben (M2,5/M3, Außen-Ø 6–7) unter jeden Schraubenkopf, damit die Klemmkraft verteilt wird und nicht in das TPU einschneidet.
- **Schrauben nicht überdrehen:** Ziehe nur an, bis das TPU anliegt. Prüfe nach den ersten Läufen das Spiel am Horn nach. Wenn der Finger am Horn wandert, sind die Ohren der Schwachpunkt. Dann ist ein PETG-Träger mit TPU-Pad (Variante oben) oder nachträglich getauschtes Filament nötig.

Druck: wie beim Pad oben (langsam, trocken, Direct-Drive, 4 Perimeter für die Wände). Die Ohren brauchen 100 % Infill und mindestens 6 Perimeter. Bei einem so kleinen Teil bleibt dann kaum noch Infill übrig.
Hinweis: Die Rippen sind nur 1,2 mm dick (3 Perimeter bei 0,4 mm Düse). Bei Bambu Studio die Wanddicke nicht überschreiben lassen und "Dünne Wände erkennen" aktivieren.

## Montage (2-Material-Variante)

1. Träger wie bisher auf das Servo-Horn schrauben (Lochbild unverändert).
2. Pad von der +z-Seite auf die Schiene schieben, bis er an der Anschlagplatte anliegt (leicht schwergängig ist gewollt – `--dt-clear 0.1` macht ihn lockerer).
3. Retainer auflegen, M2×8 in die Schienenbohrung (Pilotloch Ø1,7).

## Anpassen

```bash
python3 make_finger.py                    # rechter Arm
python3 make_finger.py --left             # linker Arm (y gespiegelt, = FINGER_1_2-Frame)
python3 make_finger.py --contact +x       # greifende Fläche auf +x statt −x
python3 make_finger.py --rib-angle 35 --pitch 4 --wall 1.2   # weicher
python3 make_finger.py --thick 10.4       # exakt Originalhüllkurve (x −17 … −6,6)
```

Der Pad ist 12 mm dick (Original 10,4 mm: x −17 … −6,6) – 1,6 mm mehr nach +x für
bessere Verhältnisse (Länge:Dicke = 3:1). Wenn dort etwas kollidiert, `--thick 10.4`.

## Offene Punkte

- **Greifende Seite:** Der Finger schwenkt beim Ellbogen-Yaw um z, die Blattflächen zeigen ±x. Default `--contact -x` (glatte Rückseite des alten Blattes). Welche Fläche beim Schließen zum Objekt zeigt, hängt von der Einbaurichtung ab – bei Bedarf `--contact +x`.
- **Kollision / Sim:** Die neuen STLs sind noch nicht in `sim/assets` oder dem GUI-Modell eingebunden (Visual und Masse des alten Fingers bleiben dort).
- **Erster Test:** 85A, 90A, 95A mit je 15°/25°/35° Rippenwinkel auf einer Test-Leiste (nur Pad, in Schraubstock mit Flasche drücken) – günstiger als ganze Arme zu drucken.
