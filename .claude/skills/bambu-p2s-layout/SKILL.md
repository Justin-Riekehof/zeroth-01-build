---
name: bambu-p2s-layout
description: Druckplatten (Layouts) für den Bambu Lab P2S aus CAD-Teilen erzeugen – Geometrie-3MF plus Bambu-Studio-Projekt mit allen Einstellungen per Flatpak-CLI. Nutzen, wenn ein Teil nachgedruckt, eine Platte angeordnet oder ein fertig konfiguriertes .3mf/Projekt für Bambu Studio gebraucht wird.
---

# Bambu P2S: Layout und Projekt-3MF erzeugen

Erprobt an `hardware/hip_yaw_left/` (Torso-Traverse, PETG) und `hardware/hip_roll_left/`; `hardware/gripper/` hat mehrere Platten (`plates.json`). Vorlagen: `hardware/hip_yaw_left/make_print.py` (Geometrie) und `make_bambu_project.py` (Einstellungen). Neue Teile = diese beiden Skripte kopieren und anpassen.

## Zwei Stufen (nicht vermischen)

1. **Geometrie-3MF** (`make_print.py`, reines Python, `.cad/bin/python`): Teil aus dem CAD holen, reparieren, auf die Druckfläche drehen, auf dem 256 × 256 mm Bett zentrieren. Enthält keine Druckeinstellungen. Das ist der Repo-Standard (gripper, hip_roll_left).
2. **Projekt-3MF** (`make_bambu_project.py`): schickt die Geometrie durch die Bambu-Studio-CLI und schreibt Prozess/Filament/Drucker hinein. Nur nötig, wenn der Nutzer nichts von Hand einstellen soll. Ergebnis `*_project.3mf` neben der Geometrie-Datei; die Glob-Schleife muss `_project`-Dateien überspringen.

## Stufe 1: Geometrie

- Teil aus `resources/cad/z001-opus-m-93de7567.glb` (Knotenname), `sim/tools/meshfix.py::stitch_t_junctions` zunähen (GLB-Netze sind nur an T-Stößen offen), Maßstab ×1000 (Meter → mm).
- Reicht Zunähen nicht (Bambu meldet Non-Manifold), danach `merge_vertices`, `unique_faces`, `nondegenerate_faces`, dann `pymeshfix`. Mit `assert is_watertight` und Volumenabweichung < 2 % absichern.
- Auflagefläche: **echte Flächennormale** verwenden (flächengewichtete Summe der Normalen mit `dot > 0.95`), nicht die Achse – das Teil liegt im CAD ein paar Grad schief. `align_vectors(n, [0,0,-1])`, dann `apply_translation(-bounds[0])`.
- Zentrieren per `transform` im `<item>`: `x = (256 - extents[0]) / 2`, analog y. Mehrere Teile: gleiche Logik pro Item, Abstand und Gesamthöhe prüfen (`max_height_mm`, Masse in `plates.json`).
- Lagevarianten (liegend/stehend) als eigene Dateien; Schichten laufen entlang der Platte, also lange, belastete Teile flach legen. Kennzahlen (Auflage mm², Überhang >45° mm²) ausgeben und in `PRINT.md` dokumentieren.
- Vorschau `plate.png` mit matplotlib (Agg), drei Ansichten.

## Stufe 2: Projekt per Flatpak-CLI

`flatpak run com.bambulab.BambuStudio` (Version 2.8.2). Systemprofile liegen unter
`~/.var/app/com.bambulab.BambuStudio/config/BambuStudio/system/BBL/{machine,process,filament}/<Name>.json`.

Verwendete Profile (P2S):

| Art | Name |
| --- | ---- |
| machine | `Bambu Lab P2S 0.4 nozzle` |
| process | `0.20mm Standard @BBL P2S` |
| filament | `Bambu PETG Basic @BBL P2S 0.4 nozzle` (TPU/PLA: passenden `@BBL P2S`-Namen im Ordner suchen) |

### Die Fallen (jede hat eine Iteration gekostet)

1. **`inherits`/`include` löst die CLI nicht auf.** Ohne Flatten kam das Filament als PLA, Bett 45 °C. Eigene `flatten()`-Funktion: erst `inherits` (rekursiv), dann jedes `include`, dann die eigenen Schlüssel der Datei. Danach Overrides drüberlegen, `type`/`name`/`from: "system"` setzen und als `machine.json`, `process.json`, `filament.json` in ein Arbeitsverzeichnis schreiben.
2. **`different_settings_to_system` muss gefüllt sein.** In `Metadata/project_settings.config` (JSON im ZIP) die geänderten Schlüssel eintragen: `[ "<Prozess-Keys ;-getrennt>", "<Filament-Keys je Filament>", "<Drucker-Keys>" ]`. Sonst lädt die GUI die Systemprofile und ignoriert alle Werte, obwohl die Datei sie enthält. Nachträglich per ZIP-Umschreiben setzen (CLI-Ergebnis → `mark_changes()`).
3. **Anordnen dreht das Teil:** `--arrange 0 --orient 0`, damit die Lage aus Stufe 1 bleibt.
4. **Bauplatte** nur per `--curr-bed-type "Textured PEI Plate"`, nicht im Profil.
5. **Pfade:** Arbeitsdateien im Home (Flatpak sieht `/tmp` nicht zuverlässig), `cwd` auf das Arbeitsverzeichnis, `--outputdir out` und `out/` vorher anlegen. Dateinamen relativ übergeben.

Aufruf:

```
flatpak run com.bambulab.BambuStudio \
  --load-settings "machine.json;process.json" --load-filaments filament.json \
  --arrange 0 --orient 0 --curr-bed-type "Textured PEI Plate" \
  [--slice 0] --outputdir out --export-3mf project.3mf in.3mf
```

`--slice 0` slict zusätzlich (prüft Stützen, gibt Zeit/Material aus, Projekt enthält dann G-Code). Danach in der GUI öffnen und „Slice plate“ drücken.

### Overrides: nur das, was nötig ist

Nur Festigkeitsstruktur und zwingende Stützen ändern, alles andere (Temperaturen, Lüfter, Schichthöhe, Brim, Skirt) bleibt P2S-Standard. Beispiel hip_yaw_left (PETG, hochbelastet): `wall_loops=6`, `top_shell_layers=6`, `bottom_shell_layers=6`, `sparse_infill_density=50%`, `sparse_infill_pattern=gyroid`, `enable_support=1`, `support_type=tree(auto)`. Die Override-Keys dienen gleichzeitig als Liste für `different_settings_to_system` (Falle 2) – ein Dict, zwei Verwendungen.

## Prüfen

- `unzip -p <projekt>.3mf Metadata/project_settings.config | python3 -c ...`: `different_settings_to_system`, `curr_bed_type`, `filament_type`, `nozzle_temperature`, `wall_loops` kontrollieren (nicht nur die GUI vertrauen).
- Bambu-Fehler „non-manifold“ → Stufe 1 reparieren, nicht in der GUI „reparieren“ lassen.
- `PRINT.md` neben die Dateien: Lagevarianten mit Kennzahlen, Tabelle der Einstellungen gegen Standard, offene Punkte vor dem Druck.
