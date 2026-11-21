# TPU-Überschuh für den Fuß (v0.2, Prototyp)

Gummischuh zum Überziehen über den bestehenden gedruckten Fuß (`*_ankle_pitch_link_printed`).
Der Fuß wird nicht verändert. Erzeugt von `make_sole.py` aus den Netzen in `sim/assets/zbot-cad/meshes`.

- **Echtes Negativ** (v0.2): Die Tasche ist das Abstandsfeld (SDF) des Fußnetzes, an der (leicht geneigten) Oberseite
  des Fußblocks abgeschnitten und überall um 0,35 mm erodiert (Pressung). Keine Hülle, kein Höhenfeld: gekrümmte
  Unterseite, 45°-Flanken, senkrechte Seiten und Eckenradien stammen aus dem echten Netz (Voxel 0,25 mm; nur
  koplanare Dreiecke im Toleranzband 0,02 mm zusammengefasst).
- Die Wand folgt dem Fuß bis zur Oberseite; eine Lippe (1,0 mm Überdeckung, 1,2 mm hoch) rastet über die Oberkante.
  Die zwei Knöchel-Böcke auf der Oberseite ragen durch die Öffnung (1 mm Luft).
- Außen: senkrechte Extrusion der Fuß-Silhouette + 1,8 mm Wand, flache Unterseite 3,5 mm unter der alten Sohlenebene,
  1,2 mm Fase an der Unterkante. Unter den Flanken ist Vollmaterial → kein Überhang, keine Stützen.
- Druck: TPU 95A, Sohle nach unten, offene Seite oben. Wände 3, ~20 % Gyroid. Projekt: `print/Robot_Shoes_TPU_project.3mf`
  (aus `make_bambu_project.py --slice`, ordnet die STLs selbst an). Laut Slicer ~69 g für das Paar, ~5 h.
- Noch nicht am echten Fuß geprüft (Einsetzen über die Lippe; ggf. `LIP` auf 0,6–0,8 mm senken, wenn zu stramm).
  Die frühere Messung (22 g je Schuh) und die Sim-Werte in `zbot-cad-tpu` gelten für v0.1 – Silhouette ist jetzt
  bis ~1 mm größer, Höhe 23–24 mm statt 15,5 mm.

Befehl (Repo-Root): `.cad/bin/python hardware/foot_sole/make_sole.py` (braucht scikit-image) → `stl/foot_sole_{left,right}.stl`

## Profile der Kontaktfläche (2026-10-31)

Alles TPU, je ein Druck, kein Kleben. Gleiche Sohlenebene (Spitzen der Noppen/Stollen liegen auf der alten
Sohlenebene, Unterkante z = −39,15 mm links), also passt ein Sim-Modell für alle; nur die Kontaktfläche ist anders.
`.cad/bin/python hardware/foot_sole/make_sole.py [smooth ribs herringbone nubs studs]` baut alle (~2 min).

| Profil | Aufbau | Auflagefläche bei 0,3 mm | Wirkung / Einsatz |
|---|---|---|---|
| `smooth` | glatt (Basis) | 100 % (54 cm²) | Referenz |
| `ribs` | Querrillen 2,0 mm breit, 1,0 tief, 5 mm Raster | 60 % | Vor-/Rückwärtsgrip, quer zur Laufrichtung |
| `herringbone` | Fischgräte 45°, Rillen 1,8 mm breit, 1,0 tief, Spitze nach +x | 69 % | Grip in x und y, Wasser läuft nach außen ab |
| `nubs` | 191 Noppen (Ø 3,4→2,6 mm, 1,0 hoch, Sechseckraster 5,5 mm) | 17 % | viele kleine weiche Kontakte |
| `studs` | 84 Kegelstollen (Ø 3,6→1,0 mm, 1,6 hoch, Raster 8 mm) | 3 % | wenige Spitzen, die sich in weiche Böden krallen |

Dateien: `stl/foot_sole_{left,right}[_ribs|_herringbone|_nubs|_studs].stl`.

- **Erwartung, aus Recherche:** Auf trockenen, harten Böden *senken* Rillen die Reibung eher leicht (weniger Fläche); sie helfen
  bei Nässe/Staub (Gap-Breite ist dort der dominante Parameter). Gegen Öl bringt das Profil nichts. Noppen/Stollen wirken
  vor allem auf Teppich, Gummimatten und weichen Böden; auf Fliesen/Laminat sind sie mit 3–17 % Fläche eher rutschig, weil
  die Spitzen nachgeben, und die Flächenpressung ist hoch. Direkte Vergleiche an Roboterfüßen oder gedrucktem TPU habe ich
  nicht gefunden – das ist also eine Messfrage.
- **Messen:** pro Profil und pro Boden μ = tan(Abrutschwinkel) auf der Kipp-Ebene (3 Messungen mitteln, Schuh mit
  Fußgewicht belasten). Diese Werte in die Sim-Randomisierung (Bodenreibung) übernehmen; der Trainingsbereich muss das
  kleinste gemessene μ einschließen.
- Druck: Sohle unten, Spitzen direkt auf dem Bett (keine Stützen). Stollen-/Noppenspitzen mit Brim oder 0,2-mm-Schicht,
  Elefantenfuß-Kompensation aus. Stollen sind die empfindlichste Variante (Wand 1,9 mm Boden darüber).

## Variante `rubber`: aufgeklebtes Kletterschuh-Gummi (2026-11-06)

TPU-Boden um die Gummistärke (1,8 mm, `RUBBER_T`) dünner und **ohne Unterkanten-Fase**, damit das Gummi die ganze
flache Unterseite bündig mit der Wand bedeckt. TPU + Gummi enden auf derselben Sohlenebene wie die anderen Profile
(links −37,35 + 1,8 = −39,15 mm) → Sim-Geometrie bleibt gleich, nur die Bodenreibung ändert sich.
TPU-Boden unter dem Fuß min. 2,1 mm (Median ~4,3 mm, die Fußunterseite ist gewölbt).

- `.cad/bin/python hardware/foot_sole/make_sole.py rubber` → `stl/foot_sole_{left,right}_rubber.stl` +
  `print/rubber_template_A4.pdf` (Unterseiten-Kontur 1:1, Ansicht von unten = auf die Lauffläche geschaut, Spitze oben;
  durchgezogen = Schnittlinie, gestrichelt = +2 mm Übermaß). Mit 100 % drucken, 100-mm-Maßstäbe nachmessen.
- `.cad/bin/python hardware/foot_sole/make_bambu_project.py --slice --variant rubber` →
  `print/Robot_Shoes_TPU_rubber_project.3mf` (Slicer: ~64 g, ~4 h 37 min für das Paar).
- Gummi: glatte Seite = Lauffläche (mehr Kontaktfläche auf hartem Boden), raue/angeschliffene Seite = Klebeseite.
- Kleben: Kontaktkleber (Neopren/PU, Schuhreparatur), beide Seiten anschleifen + mit Isopropanol entfetten, beidseitig
  dünn auftragen, ablüften, kurz warm aktivieren (Föhn), einmal kräftig pressen. Kein Sekundenkleber (spröde, löst sich
  bei Biegung/Schälung an den Kanten). Am genauesten: mit Übermaß schneiden, aufkleben, bündig an der TPU-Kante beschneiden.
