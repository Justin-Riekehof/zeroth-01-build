# Trainierte Walking-Policies (versioniert)

Die fünf Varianten vom 2026-09-23/24, trainiert auf `sim/assets/zbot-cad` **nach** der Massen- und
IMU-Korrektur. Je Ordner das Minimum, um die Policy zu deployen oder weiterzutrainieren:

| Datei | Zweck |
| --- | --- |
| `policy.onnx` | das Netz für den Roboter (onnxruntime ARM64 auf dem Pi), 64 → 16, 288 k Parameter |
| `policy_meta.json` | **der Vertrag**: Eingangslayout in Reihenfolge, Gelenkreihenfolge, Servo-IDs, Aktuatortypen, IMU-Achsen, Aktionssemantik |
| `ckpt.bin` | xax-Checkpoint — zum Fortsetzen, Fine-Tunen oder Neuexportieren |
| `eval.txt` | die Messwerte dieses Checkpoints (16 Argmax-Rollouts × 5 s, mit Randomisierung und Stößen) |

## Die fünf Varianten

| Ordner | Tempo | Stürze | Gier | Torso-Rollen p2p | Charakter |
| --- | --- | --- | --- | --- | --- |
| `cad2_v4_heading_step320` | 0,31 m/s | 0/16 | 1,9° | 51° | kräftig, große Schritte |
| `cad2_v6_small_ft_step335` | 0,19 m/s | 0/16 | 1,4° | 44° | kleine Schritte (Fine-Tune aus v4) |
| `cad2_v9_calm_step45` | 0,11 m/s | 0/16 | 2,0° | 30° | ruhig — **siehe Warnung unten** |
| `cad2_v10_calm2_step850` | 0,13 m/s | 0/16 | 2,2° | 27° | ruhigster Geher |
| `cad2_v13_tiny_step905` | 0,07 m/s | 0/16 | 2,5° | **25°** | kleinste Schritte, für erste Hardwaretests |

**Warnung zu `cad2_v9_calm_step45`:** Schritt 45 ist ein sehr früher Checkpoint. Der Sweep, der ihn gewählt
hat, bewertet Tempo und Ruhe über 5 s — **nicht Robustheit**. Vor einem Einsatz gegen einen späteren
Checkpoint über 30 s mit Stößen gegenprüfen. Die anderen vier stammen aus der zweiten Trainingshälfte.

## Vor dem Deployment unbedingt lesen

`policy_meta.json` ist nicht Dokumentation, sondern Schnittstellenbeschreibung. Die häufigste
Sim-to-Real-Fehlerquelle in diesem Projekt ist, Gelenkreihenfolge, Aktionsskalierung oder Achsen zu raten
statt sie dort auszulesen. Insbesondere:

* **IMU-Achsen sind die ROHEN Chipachsen** des QMI8658 im linken Auge (`x_imu` nach rechts, `y_imu` nach
  oben, `z_imu` nach hinten). Die Rohwerte werden **ungedreht** eingespeist. Prüfwert auf der Hardware:
  stehender Roboter → ca. **+9,81 auf der Chip-Y-Achse**. Stimmt das nicht, ist die Einbaulage anders als
  im CAD, und die Policy fällt sofort.
* **Aktion = Zielwinkel in rad** in MuJoCo-Gelenkreihenfolge, 0 = reale Servo-Null. Die Servos regeln selbst
  (Sim: kp 16 / kd 3) — die realen P/D-Register müssen vor dem ersten Lauf angeglichen werden.
* **Heading** (2 Eingänge) ist der auf 0 gesetzte Gierwinkel beim Policy-Start, also integriertes Gyro.

Die `cad_*`-Policies (ohne `2`) aus der Vorgängerserie liegen nur lokal unter
`sim/train/zbot_walking_task/best/` und sind **nicht übertragbar**: sie liefen auf dem alten Massenmodell
und einer IMU, die als Körperachsen-Site im Torso saß.

## Nicht hier drin

Videos, Rollout-Daten und die xax-SavedModels (`tf_model/`) bleiben außerhalb der Versionierung — sie
machen den Großteil der 177 MB im lokalen `best/` aus und sind aus Checkpoint bzw. ONNX reproduzierbar.

## Neu erzeugen

```bash
JAX_PLATFORMS=cpu ~/Documents/stash/ksim-zbot/.venv/bin/python \
    sim/tools/export_policy.py <ckpt.bin> <outdir>
```

Der Export prüft das ONNX gegen JAX und bricht bei einer Abweichung > 1e-4 ab (erreicht: 0,0 bei vier
Policies, 1,2e-07 bei v10). Welcher Checkpoint der beste ist, entscheidet
`sim/tools/pick_best.py <run> --target-speed <m/s> --profile strong|calm|tiny`.
