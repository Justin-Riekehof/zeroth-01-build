# Nachdruck hip_yaw_left (Bambu Lab P2S, PETG)

Das Teil ist beim Policy-Test am 22.10.2026 gerissen (linkes Bein drehte sich im Sturz bei vollem Torque nach innen
über den Anschlag, siehe README, Abschnitt Roadmap). Im Digital Twin ist es die lange Traverse neben dem Torso mit der
Servo-Aufnahme und der Platte mit dem Aluminium-Horn-Muster am linken Bein. Erzeugt von
[../make_print.py](../make_print.py) aus dem festgelegten CAD (`resources/cad/z001-opus-m-93de7567.glb`, Knoten
`hip_yaw_left`). Das CAD-Netz hatte nach dem Zunähen der T-Stöße noch rund 70 Non-Manifold-Kanten (Bambu Studio meldet
dafür einen Fehler); das Skript repariert sie mit pymeshfix. Danach ist das Netz wasserdicht, das Volumen ändert sich um
−0,1 %.

| Angabe | Wert |
| ------ | ---- |
| Volumen | 21,6 cm³ (Vollmaterial etwa 27 g, mit Wänden und Infill etwa 15–22 g) |
| Maße im CAD | 77,6 × 45,2 × 48,9 mm |

## Zwei Platten

| Datei | Lage | Maße im Druck | Auflage | Überhang >45° |
| ----- | ---- | ------------- | ------- | ------------- |
| `hip_yaw_left_PETG_A_lying.3mf` (**empfohlen**) | Traverse liegt | 46,0 × 80,6 × 41,5 mm | 294 mm² | 2185 mm² |
| `hip_yaw_left_PETG_B_standing.3mf` | steht auf dem Ende | 48,9 × 45,3 × 77,9 mm | 604 mm² | 2098 mm² |

- **A** legt die dünne Traverse flach in die Schichtebene. Zug und Biegung entlang der Traverse laufen dann *entlang*
  der Schichten. Bei **B** steht die Traverse senkrecht, die Schichten laufen quer dazu. Das ist die schwächere
  Richtung, B ist nur ein Ausweg, falls die Stützen bei A nicht funktionieren (Auflage klein, Brim nötig).
- Beide Lagen haben viel Überhang: Stützen überall (Baum, organisch), nach dem Druck entfernen und die Bohrungen
  nachziehen.
- Die Lage hat noch keiner gegen die Last geprüft. Wo genau der Riss verlief, steht nicht fest (siehe unten).

## Fertige Bambu-Studio-Projekte (alle Einstellungen enthalten)

`hip_yaw_left_PETG_A_lying_project.3mf` und `hip_yaw_left_PETG_B_standing_project.3mf`: in Bambu Studio öffnen und
"Slice plate" drücken, nichts von Hand einstellen. Erzeugt von [../make_bambu_project.py](../make_bambu_project.py)
(löst die P2S-Systemprofile selbst auf, die CLI tut das nicht). Das Skript braucht das Flatpak
`com.bambulab.BambuStudio`; `--slice` slict zusätzlich, um die Datei zu prüfen.

Eingebaut ist **nur die Druckstruktur für die Festigkeit**. Alles andere bleibt auf dem Standard des Bambu Lab P2S
für PETG Basic (Prozess 0.20mm Standard @BBL P2S, Filament Bambu PETG Basic @BBL P2S 0.4 nozzle: Düse, Bett, Lüfter,
Schichthöhe, Brim, Skirt usw.), Bauplatte **Textured PEI**:

| Einstellung | Wert | Standard |
| ----------- | ---- | -------- |
| Wände | 6 | 2 |
| Top / Bottom shell layers | 6 / 6 | 4 / 3 |
| Infill | 50 % Gyroid | 20 % Cubic |
| Stützen | an, Tree (auto) | aus |

Die Stützen sind keine Festigkeitseinstellung, aber das Teil ist ohne sie nicht druckbar (Traverse schwebt 6 mm über dem
Bett). Alles Weitere (Style, Winkel, Brim) stellst du bei Bedarf in Bambu Studio selbst ein. Zum Zurückdrehen: die
Werte stehen in `PROCESS_OVERRIDES` in [../make_bambu_project.py](../make_bambu_project.py).

Der frühere CLI-Probelauf (mit anderen Einstellungen) meldete "Floating vertical shell" bei z ≈ 2–3 mm und 9–10 mm:
in der Preview ansehen.

## Was die Struktur bringt

- Das Teil reißt entlang der Schichten, nicht durch die Füllung: Wände und Schalen bringen mehr als 100 % Infill.
  Vollmaterial kostet nur Masse (das Sim-Massenmodell stimmt dann nicht mehr).
- Das Material kommt aus dem Netz der CAD-Datei. Toleranzen der Servo-Aufnahmen vorher am alten Teil prüfen.

## Offen vor dem Druck

1. Wo verlief der Riss genau (Übergang Traverse/Platte, Servo-Aufnahme, Lasche mit dem Anschlag)? Danach richtet sich,
   ob Lage A reicht oder ob die Geometrie im CAD einen Radius oder eine Rippe braucht.
2. Das Teil trägt den mechanischen Anschlag des Hüft-Yaw-Gelenks: Anschlagfläche und Abstand zum Aluminium-Horn am
   alten Teil messen, bevor man nachdruckt.
3. Keine Policy auf den Roboter, bis die Punkte in der Roadmap (README) erledigt sind.
