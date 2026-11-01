# Nachdruck hip_roll_left (Bambu Lab P2S, PETG)

Ein Teil, eine Platte: `hip_roll_left_PETG.3mf`. Vorschau: [plate.png](plate.png). Erzeugt von [../make_print.py](../make_print.py)
aus dem festgelegten CAD (`resources/cad/z001-opus-m-93de7567.glb`, Knoten `hip_roll_left`), mit zugenähten T-Stoß-Rissen.
Wenn du das Teil im CAD änderst, das Skript neu laufen lassen.

| Angabe | Wert |
| ------ | ---- |
| Maße im Druck | 83,5 × 31,6 × 59,9 mm (x · y · z) |
| Volumen | 28,2 cm³ (Vollmaterial 36 g, mit Wänden und Infill etwa 20–29 g) |
| Lage | auf der großen ebenen Seitenfläche (ca. 1200 mm² Auflage), Z-Form mit senkrechtem Steg |

## Einstellungen

Drucker **Bambu Lab P2S 0.4 nozzle**, Bauplatte Textured PEI, Düse 0,4 mm, Schichthöhe 0,20 mm, Elefantenfuß-Kompensation 0,15 mm.

| Wände | Infill | Stützen | Brim |
| ----- | ------ | ------- | ---- |
| 5 | 40 % Gyroid | **Baum, organisch, überall** | 4 mm |

> **Hinweis 22.10.2026:** Dieses Teil (`hip_roll_left`) ist beim Policy-Test **nicht** gerissen. Gerissen ist
> `hip_yaw_left`, dessen Layout liegt in [../../hip_yaw_left/print/PRINT.md](../../hip_yaw_left/print/PRINT.md).
> Bambu Studio meldet für die Platte hier 68 Non-Manifold-Kanten; `hip_yaw_left` wird mit pymeshfix repariert,
> dieses Skript noch nicht.

- Das Teil ist gebrochen, also trägt es die Last des Hüftgelenks: lieber 5 Wände und die Schichtlinien nicht quer zur
  Zugrichtung legen. Die Lage hier hat die Schichten parallel zur Plattenfläche, die Biegung zwischen Steg und Fuß liegt
  dadurch in der Schichtebene. Falls die alte Bruchstelle dort war, drehe das Teil in Bambu Studio um 90° und prüfe,
  ob die Stützen dann noch vertretbar sind.
- Beide Laschen (oben bei z 51–60 mm und die kleine bei z 10–16 mm) hängen frei, dort brauchen sie Stützen. Entferne sie
  nach dem Druck und ziehe die Bohrungen mit einem Bohrer nach.
- Das Material kommt aus dem Netz der CAD-Datei. Toleranzen der Servo-Aufnahmen vorher an der Stelle prüfen, an der der
  Servo sitzt, und das alte Teil als Maßvergleich nehmen.
