# Policies und ihre Reibungsbedingungen

Stand 24.11.2026. Die Übersicht zeigt für jeden Trainingslauf und jede exportierte Policy, mit welchem Fußmodell und
welcher Fuß-Boden-Reibung sie trainiert wurde und auf welchem Boden sie real getestet wurde. Die Daten stammen aus
den `config.yaml` der Läufe (`sim/train/zbot_walking_task/<lauf>/`), dem kompilierten MuJoCo-Modell, der Git-Historie
von `sim/train/walking.py` und `sim/assets/*/robot.mjcf` sowie dem [Trainingstagebuch](training-journal.md).

## Kurzfassung

| Zeitraum | Läufe | Fußmodell | Wirksame Fußreibung μ | Bohrreibung |
|---|---|---|---|---|
| 6.8.–8.9. | `run_0`, `backpack_v1`–`v10` | `zbot-pixel(-backpack)`, Quader | **fest 1,0** | keine |
| 8.9.–23.9. | `cad_v1`–`v13`, `cad2_*` | `zbot-cad`, Quader 10 × 5,8 cm | **fest 1,0** | keine |
| 26.10.–29.10. | `servo_v1`–`v3`, `servo_calm_*`, `servo_ctrl_v1`–`v10` | `zbot-cad`, Quader | **fest 1,0** | keine |
| 29.10.–31.10. | `servo_ctrl_v13`–`v31`, `servo_scratch2`–`4` | `zbot-cad`, flacher Streifen + Fasenkapseln | **fest 1,0** | keine |
| 31.10.–1.11. | `servo_tpu1`–`tpu5` | `zbot-cad-tpu(-leftold)`, flache TPU-Sohle 10,2 × 5,6 cm | **fest 1,1** | keine |
| 1.11.–2.11. | `servo_fric1`, `servo_fric2` | `zbot-cad-tpu` | **0,1–1,5** je Umgebung (fric2 log-verteilt) | keine |
| 2.11.–11.11. | `servo_rubber1`–`rubber24` | `zbot-cad-tpu` | **0,5–1,3** je Umgebung, gleichverteilt | keine |

**Für alle Policies gilt:**
- Bis einschließlich `servo_tpu5` gab es effektiv **nur einen Reibwert**. Die Randomisierung lief zwar, wirkte aber nicht auf die Füße (siehe unten).
- **Kein Lauf hatte Bohrreibung** (Reibmoment um die Hochachse in einem Kontaktpunkt). Alle Fußkontakte haben `condim 3`.

## Wie die Fußreibung im Sim entsteht

1. **Explizite Kontaktpaare.** Jedes `robot.mjcf` legt die Fuß-Boden-Kontakte als `<pair>` fest. Das kompilierte Modell
   erzeugt zwischen Fuß und Boden nur diese Paar-Kontakte, keine zusätzlichen automatischen. Ein `<pair>` hat eigene
   Reibung und eigenes `condim`. Die Werte der Geoms (Fuß `condim 6`, `friction 0.8 0.02 0.01`; Boden `1 0.005 0.0001`)
   gelten für die Füße also **nicht**.
2. **Werte der Paare** (kompiliert geprüft am 23.11.):

   | Modell | Paare | `condim` | Reibung (gleiten, gleiten, bohren, rollen, rollen) |
   |---|---|---|---|
   | `zbot-pixel`, `zbot-pixel-backpack` | 2 (Quader) | 3 | 1,0 1,0 0,005 0,0001 0,0001 (MuJoCo-Standard, nichts angegeben) |
   | `zbot-cad` bis 29.10. | 2 (Quader) | 3 | wie oben |
   | `zbot-cad` ab 29.10. | 6 (Quader + 2 Fasen je Fuß) | 3 | wie oben |
   | `zbot-cad-tpu`, `zbot-cad-tpu-leftold` | 2 (flache Sohle) | 3 | **1,1** 1,1 0,005 0,0001 0,0001 (explizit) |

   Mit `condim 3` rechnet MuJoCo nur die beiden Gleitrichtungen. Die Bohr- und Rollwerte stehen zwar im Paar, werden
   aber **nicht ausgewertet**.
3. **Solver:** pyramidaler Reibkegel (`cone 0`), `impratio 1`, kein No-Slip, `dt 0,002 s`, Regelschritt 0,02 s.
   Kontakte sind weich: Unterhalb der Rutschgrenze kriecht ein Fuß mit 0,01–8 mm/s. Ein starrer Block rutscht schon
   bei 50–95 % von μ·M·g, nicht erst bei μ·M·g (Tagebuch 1.11., `servo_fric1`).
4. **Randomisierung** bei `domain_randomize: true` (alle Läufe):
   - **Bis 1.11. 22:27** (`c290330`): `ksim.FloorFrictionRandomizer` skaliert `geom_friction` des Bodens ×0,1–2,0. Das
     erreicht die Füße nicht, weil die Paare die Geom-Werte überschreiben. In MuJoCo geprüft: Bei Skala 0,1, 1,0 und
     2,0 bleibt die Fußreibung 1,1. **Alle Läufe bis `servo_tpu5` kennen also nur einen μ.**
   - **Ab 1.11.**: `FootFrictionRandomizer` (`sim/train/walking.py`) setzt je Umgebung die Gleitreibung der Paare
     (`pair_friction[:, :2]`) auf einen Zufallswert aus `foot_friction_min`–`foot_friction_max` (gleich- oder
     log-verteilt). Bohr- und Rollwerte bleiben unverändert und mit `condim 3` ohnehin wirkungslos. In MJX bis in
     die Kontakte geprüft.
   - `ksim.StaticFrictionRandomizer` (×0,5–1,5) betrifft die **Gelenkreibung** der Servos, nicht den Boden.

## Fußgeometrie je Modell

| Modell | Kollisionsform der Sohle | Gilt für |
|---|---|---|
| `zbot-pixel`, `zbot-pixel-backpack` | ein flacher Quader | Phase 1 |
| `zbot-cad` bis 29.10. | ein flacher Quader 10 × 5,8 cm, also seitlich mehr als dreimal zu breit | `cad_*`, `cad2_*`, `servo_v*`, `servo_ctrl_v1`–`v10` |
| `zbot-cad` ab 29.10. | Quader + dünne Kapseln (r 1 mm) auf den äußeren Fasenkanten (14–16°, ~3,5 mm hoch) | `servo_ctrl_v13`–`v31`, `servo_scratch2`–`4` |
| `zbot-cad-tpu` | flache Sohle über die ganze Fußfläche (10,2 × 5,6 cm), 3,5 mm tiefer, +22 g je Fuß | `servo_tpu1`–`3`, `servo_fric*`, `servo_rubber*` |
| `zbot-cad-tpu-leftold` | wie `zbot-cad-tpu`, aber linke Hüft-Roll-Achse alt (Export mit `--flip-joints left_hip_roll`) | `servo_tpu4`, `servo_tpu5` |

Die `servo_rubber*`-Läufe nutzen das TPU-Sohlenmodell. Annahme dabei: Der Kletterschuhgummi wird flach unter die
PETG-Sohle geklebt, als 3–4 mm dicke Platte mit 20–30 g. Ein eigenes Gummimodell gibt es nicht.

## Alle Trainingsläufe

Datum = Anlage der `config.yaml`. „fest“ heißt: Die Randomisierung lief, erreichte die Füße aber nicht.

| Lauf | Datum | Modell | μ Fuß–Boden | Start aus |
|---|---|---|---|---|
| `run_0` | 6.8. | `zbot-pixel` | fest 1,0 | null |
| `backpack_v1` … `v6_swing`, `v8_clear`, `v9_clear_scratch` | 7./8.9. | `zbot-pixel-backpack` | fest 1,0 | null |
| `backpack_v7_swing_warm` | 7.9. | `zbot-pixel-backpack` | fest 1,0 | `backpack_v4_slip` 130 |
| `backpack_v10_heading` | 8.9. | `zbot-pixel-backpack` | fest 1,0 | `backpack_v8_clear` 350 |
| `cad_v1_mild` … `cad_v5_heading_fast`, `cad_v7`, `cad_v9`, `cad_v10`, `cad_v11` | 8.9. | `zbot-cad` (alte Massen) | fest 1,0 | null |
| `cad_v6_small_ft`, `cad_v8_calm_ft`, `cad_v12_tiny_ft`, `cad_v13_tiny_from_calm` | 8.9. | `zbot-cad` (alte Massen) | fest 1,0 | Fine-Tunes |
| `cad2_v4_heading`, `cad2_v9_calm`, `cad2_v10_calm2` | 23.9. | `zbot-cad` | fest 1,0 | null |
| `cad2_v6_small_ft` | 23.9. | `zbot-cad` | fest 1,0 | `cad2_v4` 320 |
| `cad2_v13_tiny` | 23.9. | `zbot-cad` | fest 1,0 | `cad2_v10` 850 |
| `servo_v1` | 27.10. | `zbot-cad` | fest 1,0 | `cad2_v13` 905 |
| `servo_v2_normal`, `servo_v3_calm`, `servo_calm_a`/`b` | 26./27.10. | `zbot-cad` | fest 1,0 | Fine-Tunes |
| `servo_ctrl_v1` | 26.10. | `zbot-cad` | fest 1,0 | `servo_v3_calm` 2100 |
| `servo_ctrl_v2`, `servo_ctrl_v4` | 26./28.10. | `zbot-cad` | fest 1,0 | null |
| `servo_ctrl_v3`, `v5`–`v10` | 27.–29.10. | `zbot-cad` | fest 1,0 | Kette ab v2/v4 |
| `servo_ctrl_v13`, `v16`, `v17`, `v20`, `v24`, `v27`, `v30`, `v31` | 29./30.10. | `zbot-cad` mit Fasen | fest 1,0 | Kette ab v10 1330 |
| `servo_scratch2_oldaxis`, `servo_scratch2`, `servo_scratch3`, `servo_scratch4` | 30./31.10. | `zbot-cad` mit Fasen | fest 1,0 | null |
| `servo_tpu1`, `servo_tpu3` | 31.10. | `zbot-cad-tpu` | fest 1,1 | null |
| `servo_tpu2` | 31.10. | `zbot-cad-tpu` | fest 1,1 | `servo_tpu1` 770 |
| `servo_tpu4` | 31.10. | `zbot-cad-tpu-leftold` | fest 1,1 | `servo_tpu2` 815 |
| `servo_tpu5` | 31.10. | `zbot-cad-tpu-leftold` | fest 1,1 | `servo_tpu1` 770 |
| `servo_fric1` | 1.11. | `zbot-cad-tpu` | 0,1–1,5 gleichverteilt | null |
| `servo_fric2` | 2.11. | `zbot-cad-tpu` | 0,1–1,5 log-verteilt | `servo_fric1` 750 |
| `servo_rubber1`, `servo_rubber3`, `servo_rubber8` | 2.–5.11. | `zbot-cad-tpu` | 0,5–1,3 gleichverteilt | null |
| `servo_rubber2`, `4`–`7`, `9`–`24` | 2.–11.11. | `zbot-cad-tpu` | 0,5–1,3 gleichverteilt | Kette (Vorgänger) |

Bewertungsläufe: `_eval` (11.11.) mit 0,5–1,3. `_eval_sw0`/`_eval_sw1` (21.11., Sim/Hardware-Vergleich) mit **fest
0,9**. Die μ-Sweeps `servo_fric1/mu_sweep_750/` und `servo_rubber2/mu_sweep_440/` nutzen je Durchgang einen festen Wert.

## Exportierte Policies (`sim/policies/`)

| Policy | Modell, Sohle im Sim | μ im Training | Real getestet |
|---|---|---|---|
| `cad2_v4_heading_step320` | `zbot-cad`, breiter Quader | fest 1,0 | 21./22.10., Isomatte: fällt nach 1–2 s |
| `cad2_v6_small_ft_step335` | `zbot-cad`, breiter Quader | fest 1,0 | 21./22.10., Isomatte: fällt nach 1–2 s |
| `cad2_v9_calm_step45` | `zbot-cad`, breiter Quader | fest 1,0 | 21./22.10., Isomatte: fällt nach 1–2 s |
| `cad2_v10_calm2_step850` | `zbot-cad`, breiter Quader | fest 1,0 | 21./22.10., Isomatte: fällt nach 1–2 s. 31.10. Boden: 8,1 s bis E-Stopp, kippt nach hinten |
| `cad2_v13_tiny_step905` | `zbot-cad`, breiter Quader | fest 1,0 | 21./22.10., Isomatte: fällt nach 1–2 s |
| `servo_ctrl_v2_step670_f02` | `zbot-cad`, breiter Quader | fest 1,0 | Hardwaretest nicht im Tagebuch |
| `servo_ctrl_v4_step550` | `zbot-cad`, breiter Quader | fest 1,0 | nein |
| `servo_ctrl_v8_step895` | `zbot-cad`, breiter Quader | fest 1,0 | nein |
| `servo_tpu1_step770` | `zbot-cad-tpu`, flache Sohle | fest 1,1 | 31.10. nur Trockenlauf |
| `servo_tpu5_step1150` | `zbot-cad-tpu-leftold`, flache Sohle | fest 1,1 | 31.10., TPU-Schuhe: Parkett ~2 Schritte, rutscht weg; Anti-Rutschmatte kein Schritt. 1.11., neue TPU-Schuhe, Laminat: rutscht, 0,9–4,8 s |
| `servo_rubber2_step440` | `zbot-cad-tpu`, flache Sohle | 0,5–1,3 | nein |
| `servo_rubber14_step1205` | `zbot-cad-tpu`, flache Sohle | 0,5–1,3 | nein |
| `servo_rubber22_step3210` | `zbot-cad-tpu`, flache Sohle | 0,5–1,3 | nein |
| `servo_rubber23_step3315` | `zbot-cad-tpu`, flache Sohle | 0,5–1,3 | Kletterschuhgummi: 11.11. (14 Läufe, bis 14,8 s), 21.11. und 22.11. Parkett, 1–5 s, dreht sich um die Hochachse |

Bei den vier `servo_rubber*`-Policies steht der μ-Bereich in `policy_meta.json` (`foot_friction_min/max/log`).
Bei allen älteren fehlt er. Dort lässt er sich nur über den Checkpoint-Pfad, die `config.yaml` des Laufs und das
Fußpaar im Modell nachvollziehen. Das `condim` der Fußpaare steht in keiner Metadatei.

## Reale Sohlen und Böden

| Sohle | Zeitraum | Reibwert |
|---|---|---|
| gedruckte PETG-Sohle mit Fasen | bis 30.10. | nicht gemessen |
| TPU-Überschuh (`hardware/foot_sole`) | 31.10.–1.11. | nicht gemessen. Bench-Test 1.11. (Füße auseinanderdrücken): Laminat 0,08–0,12 Nm Hüftlast, im Sim entspricht das grob μ ≈ 0,2 (**unkalibriert**) |
| Kletterschuhgummi, flach unter die Sohle geklebt | Tests ab 11.11. | Erwartung des Nutzers 0,6–1,0, **nicht gemessen** |

Böden in den Tests: Isomatte (21./22.10.), Parkett, Anti-Rutschmatte, Laminat und Zeitschrift (Bench 1.11.), Parkett (21.–23.11.).

## Befund 23.11.: Bohrreibung fehlt im Sim

Alle Policies wurden **ohne Bohrreibung** trainiert. In der Sim kann ein Fuß nur über die Hebelarme mehrerer
Kontaktpunkte gegen Verdrehen halten. Steht er auf einer Kante oder Ecke, dreht er sich frei.

Messung an `servo_rubber23_step3315` (16 Sim-Starts, μ 0,9, Vorwärtskinematik aus `qpos`):
- Zwischen 0,1 und 0,26 s trägt der linke Fuß allein (≈ 22 N).
- Die Sohle steht dabei 5–10° schräg (maximal 14°), meist mit nur **einem** Kontaktpunkt.
- Die Policy dreht die linke Hüftgierung auf −11°. Der Fuß dreht sich dabei um **−5°** auf dem Boden, der Rumpf nur um +0,5°.

Real haftet der Gummi, und der Fuß dreht sich nicht (Fotos `media/hw_tests/2026-11-23/`). Stattdessen dreht der
Körper: Das integrierte gyro_y zeigt nach 0,3 s +6 bis +10°, und dieser Winkel bleibt.

**Folgerung für künftige Läufe:**
- Fußpaare mit `condim 4` (oder 6) und einer realistischen Bohrreibung rechnen.
- Den Bohrwert mit der Gleitreibung mitrandomisieren.
- Die Reibung des Kletterschuhgummis messen.

**Sim-Test 24.11.** (`condim 4`, Bohrreibung 0,01–0,3 m, ohne Training, Tabelle im Tagebuch):
- Mit festerem Fuß dreht der Rumpf mehr mit, nach 0,4 s 7° statt 4°. Die Hardware liegt bei 9°.
- `servo_rubber23` stürzt dann häufiger (3–4/16 statt 1/16) und weicht stärker in der Richtung ab.
- Die reale Gierspitze von 85 °/s bei 0,2 s entsteht dabei nicht, im Sim bleibt es bei höchstens 24 °/s. Die fehlende Bohrreibung ist also nur ein Teil der Ursache.

## Offene Punkte

- Reibwert des Kletterschuhgummis auf Parkett messen (Kipptest oder Kraftmesser).
- `policy_meta.json` beim Export um das `condim` und die Reibwerte der Fußpaare ergänzen.
- Torsionsverhalten mit `condim 4` im Sim gegen die Hardware-Gierspitze (76–94 °/s bei 0,2 s) prüfen, ohne Training.
