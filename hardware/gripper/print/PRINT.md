# Druckvorbereitung Bambu Lab P2S: Greifer + Handgelenk (links und rechts)

Fünf 3MF-Projekte, alle Teile für **beide Greifer** (die Zahl `_xN` im Dateinamen). **Alles in PETG**, nur die Greifpads
sind TPU. Jedes Teil liegt in seiner Druckrichtung, mittig auf der 256 × 256-mm-Platte. Vorschau: [plates.png](plates.png).
Erzeugt von [../make_print.py](../make_print.py), neu erzeugen nach jeder Änderung an den STLs.

| Datei | Material | Inhalt | Filament (ca.) |
| ----- | -------- | ------ | -------------- |
| `plate_01_PETG_Finger.3mf` | PETG | 4 Koppelstangen, 2 Fingerstücke A, 2 Fingerstücke B (8 Teile) | 37–54 g |
| `plate_02_PETG_Mechanik.3mf` | PETG | 2 Joche, 2 G1, 2 G2, 2 Lenker A, 2 Lenker B, 4 Lenkerzapfen (14 Teile) | 106–155 g |
| `plate_03_PETG_Gehaeuse.3mf` | PETG | 2 Fächer, 2 Deckplatten, 2 Roll-Deckplatten, 4 Kappen Ø10, 8 Kappen Ø12, 2 Kappen Ø14 (20 Teile) | 67–98 g |
| `plate_04_TPU.3mf` | TPU 95A | 4 Greifpads | ca. 3 g |
| `plate_05_PETG_Nachdruck.3mf` | PETG | **nur die Teile, die sich seit der Platte 5 vom 18.10. geändert haben:** 2 Joche, 2 Fächer, 2 Deckplatten, 2 Roll-Deckplatten, 2 G1, 2 Lenker A, 2 Lenker B (14 Teile) | 155–226 g |

Platte 5 ist eine Teilmenge der Platten 2 und 3, keine zusätzlichen Teile. Ihre Auswahl ergibt sich aus dem Vergleich von Volumen und
Maßen aller Teile gegen den Stand dieser Platte (Joch, Roll-Deckplatte, G1, Lenker, Fach und Deckplatte haben sich
geändert, G2, Kappen, Finger und Lenkerzapfen nicht). Wenn du Teile aus einem anderen Stand gedruckt hast, ändere die
Liste `NACHDRUCK` in `make_print.py`.

Der Finger besteht aus zwei Teilen: der **Koppelstange** (`finger_coupler_x4`, identisch für A und B) und dem
**L-Fingerstück** (`finger_tip_A_x2` / `finger_tip_B_x2`, Spiegelpaar). Sie werden mit 2× M3×12 verschraubt,
zwei Passzapfen Ø4 an der Koppelstange verhindern das Verdrehen.

Die Filamentmengen sind eine Schätzung (Volumen mit Wänden und Infill). Die Druckzeit habe ich nicht berechnet,
das macht Bambu Studio beim Slicen.

## So öffnest du sie

1. In Bambu Studio den Drucker **Bambu Lab P2S 0.4 nozzle** wählen, dann die 3MF-Datei öffnen. Die Datei enthält
   nur Geometrie und Position, keine Druckerprofile oder Einstellungen. Wenn Objekte nicht mittig auf der Platte
   liegen, mit **A** (Anordnen) neu verteilen.
2. Das Filament zuweisen: Platte 1, 2, 3 und 5 *Generic PETG* oder Bambu PETG, Platte 4 *Bambu TPU 95A HF*.
3. Einstellungen aus der Tabelle unten übernehmen.
4. Weil du kein AMS hast: **eine Platte pro Material, nie mehrere Filamente in einem Druck.**

**Erst testen:** Lösche aus Platte 3 alles außer **1× `housing_tray_x2` und 1× `housing_top_plate_x2`** und drucke
das zuerst (etwa 2 Stunden). Setze einen echten Servo ein. Passt er mit leichtem Spiel ins Fach und lässt sich die Platte
schließen, drucke den Rest. Die Servo-Maße stammen nur aus dem CAD-Mesh.

## Einstellungen

Allgemein: Düse 0,4 mm, Schichthöhe 0,20 mm, Elefantenfuß-Kompensation 0,15 mm, Bauplatte **Textured PEI**. Keine Skirts nötig, Brim 3–5 mm nur bei den schmalen Teilen (Finger, Lenker, Lenkerzapfen).

| Teil | Wände | Infill | Stützen | Hinweis |
| ---- | ----- | ------ | ------- | ------- |
| Joch (`wrist_yoke_x2`) | 4 | 40 % Gyroid | **Baum, organisch, überall** | liegt auf einem Ohr. Das Dach über der Servo-Tasche braucht Stützen, du entfernst sie durch die offene Seite. |
| Koppelstange | 4 | 40 % Gyroid | keine | liegt auf der Oberseite (Zapfen oben). Bohrungen nach dem Druck mit 6,3 mm (Ø6-Zapfen) und 8,3 mm aufbohren. |
| Fingerstück A/B | 4 | 40 % Gyroid | keine | liegt auf der Außenseite, Pad-Seite oben. Pilotlöcher Ø2,6 (Absatz) und Zapfentaschen Ø4,2 prüfen. |
| G1, G2 (Zahnräder) | 5 | 100 % | G1: Baum, nur auf Bauplatte | G1 hat unter dem Zahnkranz einen Absatz zum Abstandsring Ø18,4, dort kleine Stützen. G2: Bohrung Ø10,3 und Senkung unten. | Schichthöhe 0,12–0,16 für saubere Zähne. G1 hat einen kleinen Absatz unter dem Zahnkranz, der ohne Stütze gelingt. |
| Lenker A/B | 4 | 40 % | keine | Zapfen steht senkrecht, 33 mm hoch, langsam drucken. |
| Lenkerzapfen | 4 | 100 % | keine | Flansch unten, Schaft oben. |
| Fach | 4 | 25 % Gyroid | keine | Boden auf dem Bett, Servo-Tasche oben offen. |
| Deckplatte (PETG) | 5 | 40 % Gyroid | keine | flach, G2-Achse oben, Platte durchgehend 4,45 mm. Schichthöhe 0,16 mm gibt eine glattere Achse. |
| Roll-Deckplatte | 4 | 25 % | keine | flach |
| Kappen | 3 | 100 % | keine | flach, Senkung oben |
| Pads (TPU 95A) | 3 | 100 % | keine | Direktantrieb nutzen, langsam, Filament trocknen. Vorgabe-Fluss des Bambu-TPU-Profils nicht überschreiben. |

Nach dem Druck:
- Pilotlöcher Ø2,6 (in Pins und Wänden) prüfen, bei Bedarf mit einem 2,5-mm-Bohrer nachziehen.
- Koppelstange auf den Absatz des Fingerstücks legen (Passzapfen in die Taschen), mit 2× M3×12 verschrauben.
- Pads auf die zwei Zapfen im Fingerstück stecken, bei Bedarf mit Sekundenkleber sichern.
- Danach die Montage nach der Schraubenliste in der [README](../README.md).

## Druckrichtung je Teil

| Teil | liegt auf |
| ---- | --------- |
| Joch | äußerer Fläche eines Ohrs (Hornachse senkrecht) |
| Koppelstange | Oberseite (Passzapfen zeigen nach oben) |
| Fingerstück | Außenseite (die Seite ohne Pad), Fläche eben |
| Lenkerzapfen | Flanschfläche, Schaft oben |
| Zahnräder, Lenker, Fach, Deckplatte, Kappen | wie im Modell, Zapfen oben |
| Roll-Deckplatte | Unterseite (zum Servo) |
| Pads | Greiffläche, Zapfen oben |
