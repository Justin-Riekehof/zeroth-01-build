# Pixel Backpack v4 — Druckdateien

v4.6 (2026-09-22): **Grundrahmen**: Durchgangsbohrungen der vier Torsoschrauben Ø4,0 (vorher 3,4), Senkung Ø7,0 × 4,0
(vorher 6,6 × 3,2). Deckel unverändert.

v4.5 (2026-09-22): **Deckel**: Cutoff-Bohrungen auf der langen Seite 1,5 mm enger (56,5 mm), Waveshare-Sockelbohrungen Ø2,2,
Aussparungen Ø5,5 × 3 mm für die Sockel des Schaltereinsatzes mit höheren Innenpads (5 mm Gewinde bleiben). Nur der Deckel ist neu.

v4.4 (2026-09-22): **Pi um 180° gedreht** — SD-Kante rechts (+X) mit microSD-Fenster in der +X-Wand, USB-C-Kante unten mit
**40 mm** Platz für Netzteilstecker und Kabel, Ethernet/USB-A nach −X mit **50 mm** Steckerzone; Pololu links unten. Beide
Druckteile neu (Deckel: nur die 5-V-Messpins und ihre Beschriftung sind gewandert).

v4.3 (2026-09-22): **Pi 6 mm nach +X** (Platinenkante → Seitenwand 6,5 mm statt 0,5 mm, die gesteckte microSD-Karte
passt jetzt) und **microSD-Fenster in der rechten Seitenwand** (−X, gegenüber der LiPo-Schublade): 24 mm breit, 45°-Dach,
ohne Support. Außenmaße unverändert, nur der Grundrahmen ist neu, der Deckel ist identisch mit v4.2.

v4.2 (2026-09-19): **Pi quer** (USB/Ethernet zur Mitte, von hinten steckbar), **Waveshare am Deckel** auf vier
Kunststoffsockeln (M2, Bohrung Ø1,9), **Kameraschlitz** 18 × 3 mm oben links in der Grundplatte, Pololu-Dome diagonal
(13,5 × 16,0, M2), 5-V-Messpins im Deckel verlegt, Warner 3 mm höher. Für den Pi einen **USB-C-Stecker mit 90°-Abgang**
verwenden (Kabel nach hinten).

v4.1 (2026-09-18): **Pi von der Torsoseite verschraubt** (4× M2, Senkungen in der Grundplatte); XY-CD63-Klemmen an
der Oberkante, Kabel von oben (nur Kabelwege/Hüllen, Deckel unverändert). Details im README.

v4 (2026-09-16): **zwei Lagen, Pi im Rucksack.** Der Raspberry Pi passt nicht in den Torso (dort sind zwischen den
Seitenrippen nur 57 mm frei, die Platine ist 56 mm breit und die Ethernet-Buchse 16 mm hoch). Er sitzt jetzt in einer
eigenen vorderen Lage direkt an der Torsoplatte, die Elektronik hängt darüber am Deckel. Innentiefe 44 → 61 mm,
Gesamttiefe ab Torsowand **69 mm** (vorher 52). Der Torso-Einsatz entfällt, es sind nur noch **zwei** Druckteile.

| Datei | Teil | Bett-Auflage | Größe (mm) | Support |
| --- | --- | --- | --- | --- |
| `pixel-backpack-v4_1-base.stl` | Grundrahmen: Pi-Standoffs (M2 von der Torsoseite, gesenkt), microSD-Fenster, Pololu, LiPo-Schublade | Grundplatte (Torsoseite) unten | 160 × 162 × 67 | keiner |
| `pixel-backpack-v4_2-lid.stl` | Rückdeckel: XY-CD63 (von außen verschraubt), Schalter, Sicherung, XT60-Paare, Warner | **Außenseite unten** | 160 × 162 × 19 | keiner |

## Lagenaufbau (y ab Torso-Rückwand 38,1 mm)

| y [mm] | Inhalt |
| --- | --- |
| 38,1 – 41,1 | Grundplatte, Torsoschrauben |
| 41,1 – 61,1 | **vordere Lage:** Pi 4B auf 2-mm-Standoffs, Waveshare auf 4-mm-Standoffs, Pololu; Steckerzonen und Biegeradien |
| 61,1 – 90,0 | Elektronikebene: XY-CD63 hängt am Deckel (Auflage bei 102,1) |
| 90,0 – 105,1 | Kabelebene mit den Deckel-Cradles (Schalter, Sicherung, XT60, Warner) |
| 105,1 – 107,1 | Deckel |

## XY-CD63

Wird jetzt **von außen durch den Deckel** verschraubt: 4× Ø3,3 Durchgang, Senkung Ø6,0 × 3,4 mm für Zylinderkopf
5,5 × 3 mm, dafür ist der Deckel an den vier Stellen auf 5 mm verdickt. Grund: bei zwei Lagen müssten Säulen von der
Torsoplatte genau durch die Pi-Lage laufen — die Schraubenabstände (58 mm) und die Platinenbreite (56 mm) lassen das
nicht zu.

## Bambu PETG (wie in der Spezifikation)

Düse 240–250 °C, Bett 70–80 °C, 4 Wandlinien, 40 % Gyroid, Support-Z-Abstand 0,2 mm
(nur falls der Slicer doch etwas vorschlägt). Beim Deckel liegen die Beschriftungen („30A“, „BAL“, „5V/GND“) auf der Bett-Seite — 0,6 mm tiefe Vertiefungen in
der ersten Lage, kein Problem.

## Nach dem Druck

* Gewindeeinsätze: 4× M3 im Grundrahmen (Ecken, für den Deckel); Torso-Schrauben gehen in die vorhandenen
  Hülsen des Torsos (4× M3×8).
* **XY-CD63:** 4× M3×10 Zylinderkopf von außen durch den Deckel, Köpfe 0,4 mm versenkt.
* **Raspberry Pi:** 4× M2×8 Zylinderkopf (Ø4 × 2) von der Torsoseite durch Grundplatte und Standoffs, M2-Mutter auf
  der Platine. Senkung Ø4,5 × 2,4 mm, Köpfe 0,4 mm versenkt, die Platte liegt plan am Torso. Der Pi lässt sich nur
  bei abgenommenem Rucksack lösen. Die **microSD-Karte** wird durch das Fenster in der Seitenwand (+X, Seite der
  LiPo-Schublade) gesteckt und gezogen; sie steht 3 mm über die Platine und endet 3,5 mm vor der Wand. Netzteil mit
  geradem USB-C-Stecker von unten, USB-A/Ethernet-Stecker nach −X.
* **XY-CD63** mit dem Display nach innen einsetzen (Klemmen oben, VIN zum Schalter hin). Im Deckel sitzen an Stelle der
  früheren Display-/Tasterfenster Lüftungsschlitze.
* **Waveshare:** 4× M2×6 von der Bauteilseite in die Deckelsockel (Bohrung Ø2,2; Metallsockel vorher entfernen).
* **Pololu:** 2× M2×6 in die diagonalen Dome.
* **Hauptschalter:** von außen in den Ausschnitt (15 × 34) einsetzen, seine zwei Sockel Ø5 × 3 sitzen in den Aussparungen
  Ø5,5 × 3 des Deckels; 2× M2 durch seine Befestigungslöcher in den Deckel. Gewinde im Deckel 5 mm tief (unter der
  Aussparung 2 mm Deckel + 6 mm Pad − 3 mm); Schraubenlänge = Flanschdicke + ca. 5 mm.
* Reihenfolge: Pi (von der Torsoseite) und Pololu in den Grundrahmen schrauben, Waveshare an den Deckel → Grundrahmen an den Torso →
  Servobus und Pi-Kabel durch die Durchführung legen → Deckel mit Cutoff, Schalter, Sicherung, XT60 und
  Warner bestücken → verkabeln → Deckel aufsetzen → LiPo von links einschieben.

Quelle: `../backpack_v3.py` (CadQuery), Kabelprüfung `../check_cables.py`, Details `../README.md`.
