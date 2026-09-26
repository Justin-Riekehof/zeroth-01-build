# Simulation & RL-Training

RL-Trainings-Stack für diesen Z-Bot-Build ("Pixel"): **ksim (JAX + MuJoCo MJX)** mit einem
an die reale Hardware angepassten Modell. Aufgesetzt am 2026-08-06; Kontext und
Hardware-Ground-Truth in [docs/sim-context.md](../docs/sim-context.md) und
[docs/robot-context.md](../docs/robot-context.md).

## Stack-Entscheidung (Stand August 2026)

**Gewählt: ksim + ksim-zbot (JAX + MuJoCo MJX)** — der offizielle Nachfolge-Stack des
Zeroth-01-Teams und die einzige Pipeline mit sys-identifizierten Feetech-Aktuatormodellen
für genau unsere Servos.

Rechercheergebnis in Kürze:

- **K-Scale Labs hat am 4./5. Nov 2025 den Betrieb eingestellt** (Finanzierung gescheitert,
  IP komplett open-sourced, Software MIT). Sämtliche Web-Infrastruktur (`api.kscale.dev`,
  `docs.kscale.dev`, `docs.zeroth.bot`, Asset-Store) ist **auf DNS-Ebene tot** — die
  `kscale`-CLI/API liefert keine Assets mehr (offener Punkt §8 in sim-context.md: damit
  geklärt). Die GitHub-Repos sind aber **nicht archiviert und vollständig nutzbar**;
  die Community (Zeroth Bot Discord, ~1.500 Mitglieder) existiert weiter.
- **[kscalelabs/ksim-zbot](https://github.com/kscalelabs/ksim-zbot)** ist der richtige
  Einstieg: bündelt `kscale-assets` als Git-Submodule (MJCF/URDF + Meshes + Aktuator-Sys-ID),
  funktioniert komplett offline. `ksim-gym-zbot` dagegen ruft die tote K-Scale-API auf →
  ungeeignet.
- Die **alte Isaac-Gym/humanoid-gym-Pipeline** (`kscalelabs/sim`, `zeroth-robotics/sim`,
  Modell "stompymicro") ist archiviert/deprecated — nicht verwenden.
- **Fallback**, falls das eingefrorene ksim-Ökosystem bricht:
  [MuJoCo Playground](https://github.com/google-deepmind/mujoco_playground) (gleiches
  MJX-Physik-Backend, aktiv gepflegt; unser `robot.mjcf` + Aktuator-JSONs wären portierbar,
  OP3/Berkeley-Humanoid als Task-Vorlagen). Isaac Lab: für diese Plattform Overkill, kein
  Z-Bot-Modell.

Das Ökosystem ist eingefroren (letzte ksim-Commits Okt 2025) → **Versionen bleiben gepinnt**
(`ksim==0.0.31`, `xax[exportable]==0.2.6`, siehe ksim-zbot `requirements.txt`).

## Installation (dieser Rechner)

Liegt **außerhalb** dieses Repos unter `~/Documents/stash/ksim-zbot`:

```bash
# einmalig erledigt am 2026-08-06:
git clone https://github.com/kscalelabs/ksim-zbot ~/Documents/stash/ksim-zbot
cd ~/Documents/stash/ksim-zbot
git config submodule."ksim_zbot/kscale-assets".url https://github.com/kscalelabs/kscale-assets
git submodule update --init          # braucht git-lfs (liegt in ~/.local/bin)
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r ksim_zbot/requirements.txt -e . 'jax[cuda12]' kinfer
```

Aktivieren: `source ~/Documents/stash/ksim-zbot/.venv/bin/activate`

GPU-Hinweis: Training belegt standardmäßig ~75 % VRAM einer 3090 (JAX-Preallocation).
Wenn vLLM/ComfyUI laufen, vorher stoppen oder mit
`XLA_PYTHON_CLIENT_PREALLOCATE=false` bzw. `CUDA_VISIBLE_DEVICES=0|1` arbeiten.

## Was liegt wo

```
sim/
  assets/zbot-pixel/     # GENERIERT — das an diesen Build angepasste Modell
    robot.mjcf           #   16 Joints, kanonische Namen, Fuß-Sites/-Sensoren
    metadata.json        #   Joint → Servo-ID (aus hardware/servo_ids.json!),
                         #   Aktuator-Typ (Beine STS3250, Arme STS3215), kp/kd, 50 Hz
    actuators/*.json     #   K-Scale-Sys-ID beider Servotypen (Torque, armature, damping, …)
    meshes/*.stl         #   Geometrie aus kscale-assets
  tools/build_model.py   # erzeugt assets/zbot-pixel aus kscale-assets + hardware/*.json
  train/
    common.py            # vendored aus ksim-zbot (Task-Basis, Feetech-Aktuatormodell)
    walking.py           # vendored, auf 16 DoF angepasst — der Trainings-Task
```

### Warum ein generiertes eigenes Modell?

Basis ist die Upstream-Variante **`zbot-feet`** (5-DoF-Beine wie unser Roboter; Kollision
nur an den Füßen = schnelles MJX). `zbot-6dof-feet` — worauf ksim-zbot ab Werk trainiert —
hat ein zusätzliches `ankle_roll` pro Bein, das unsere Hardware nicht hat.
`sim/tools/build_model.py` transformiert das Upstream-MJCF:

1. **Joint-Namen kanonisiert** (`left_knee` → `left_knee_pitch`, `left_elbow` →
   `left_elbow_yaw`, …) — ein Namensschema für GUI, Hardware-Configs und Sim (§7.6 sim-context).
2. **Gripper entfernt** (Joints + Aktuatoren; Finger-Massen bleiben angeschweißt erhalten)
   → 16 aktuierte Joints = 16 reale Servos.
3. **Servo-IDs aus `hardware/servo_ids.json`** — Achtung: Upstream-Metadaten haben eine
   ANDERE ID-Zuordnung (z. B. dort 31=hip_yaw, bei uns 31=hip_pitch). Unsere IDs sind
   Ground Truth (§8-Punkt "Bein-Servo-IDs → Gelenk-Zuordnung": geklärt).
4. **Aktuator-Split** Beine/Arme (§2 sim-context): Beingelenke → `feetech_sts3250`,
   Armgelenke → `feetech_sts3215_12v`. Damit bekommen die Beine 8,7 N·m Forcerange,
   8,94 rad/s max. Geschwindigkeit statt der 3215-Werte (5,5 N·m / 4,86 rad/s).
   Der §8-Punkt "STS3250-Leerlaufgeschwindigkeit" ist damit durch **Sys-ID-Messwerte**
   geschlossen (besser als Datenblatt).
5. **±2-N·m-Klemmen entfernt**: `zbot-feet` clampt ab Werk `ctrlrange`/`actuatorfrcrange`
   auf ±2 N·m — das würde die STS3250-Beine stillschweigend kastrieren. Forcerange etc.
   setzt `common.py` beim Laden pro Joint aus den Sys-ID-JSONs.
6. **IMU-Sensoren/Fuß-Geoms umbenannt + Fuß-Sites & Kraftsensoren ergänzt**, damit der
   Walking-Task (Feet-Contact-/Position-Observations) sie findet.

Neu generieren (nach Änderung von Servo-IDs o. Ä.): `python3 sim/tools/build_model.py`

### Bewusste Abweichung vom Upstream-Code

`common.py::get_actuators` ordnet die Aktuator-Parameter jetzt in **MuJoCo-Joint-Reihenfolge**
statt (wie Upstream) nach Servo-ID sortiert. Der ctrl-Vektor der Physik läuft in
MuJoCo-Reihenfolge; mit unseren realen IDs (hip_pitch=x1, aber drittes Gelenk der Kette)
würden Upstream-sortierte Parameter auf den falschen Gelenken landen. Die Servo-IDs in
`metadata.json` sind ausschließlich das Deployment-Mapping (kinfer → eigener Pi-Loop).

## Benutzung

Immer vom Repo-Root, mit aktivem venv:

```bash
# Environment-Rollout ohne Training (Viewer):
python -m sim.train.walking run_environment=True

# Training (Defaults: 4096 Envs, PPO):
python -m sim.train.walking

# Kleiner GPU-Smoke-Test neben laufendem vLLM:
XLA_PYTHON_CLIENT_PREALLOCATE=false python -m sim.train.walking num_envs=64 batch_size=32
```

Logs/Checkpoints landen in `sim/train/zbot_walking_task/run_N/` (xax-Konvention,
gitignored). TensorBoard manuell starten (der Auto-Start von xax sucht ein nacktes
`python` im PATH und scheitert still — harmlos, die Event-Files sind vollständig):

```bash
~/Documents/stash/ksim-zbot/.venv/bin/tensorboard --logdir sim/train/zbot_walking_task
```

Export nach jedem Checkpoint-Save: TF-SavedModel (`.../checkpoints/tf_model/`,
`export_for_inference=True`), daraus später `.kinfer`/ONNX für den Pi.

Verifiziert am 2026-08-06 (Smoke-Test): Modell lädt in MuJoCo 3.3.3, PPO-Training läuft
auf der GPU (JAX 0.6.2/CUDA, 94 % Util neben laufendem vLLM), Checkpoint + TF-Export
funktionieren. Ein Logger-Bug der gepinnten xax-Version ist in `sim/train/common.py`
umschifft (JSON-Shim, siehe Kommentar dort).


## Modell `assets/zbot-cad` — der gebaute Roboter aus dem WebUI-CAD (Stand 2026-09-23)

**Die bisherigen Modelle `zbot-pixel`/`zbot-pixel-backpack` sind der falsche Roboter**: sie stammen aus den
K-Scale-Assets des *Z-Bot 2* (Greifer-Hände, andere Beinkette). Der gebaute Roboter ist der Zeroth-01
(`resources/cad/z001-opus-m-93de7567.glb`, genau das Modell der Servo-WebUI, Stummel-Arme). Alle
Trainingsläufe v1–v10 unten liefen auf dem falschen Modell und dienen nur noch als Pipeline-Nachweis.

`sim/tools/build_model_cad.py` erzeugt `assets/zbot-cad/` direkt aus dem CAD:

* **Kinematik** aus `z001-joints-m-93de7567.json` (16 Revolute-Mates: Achse, Zentrum) und den FASTENED-Mates
  (starre Links, gleiche Union-Find-Logik wie das Pose-Rig der WebUI). Beinkette hip_pitch → hip_yaw →
  hip_roll → knee → ankle; Achsen so, wie das CAD sie definiert (das Gelenk `hip_yaw` dreht physisch um die
  Längsachse, `hip_roll` um die Hochachse — Namen bleiben die der Hardware-Configs).
* **Nullpose = reale Servo-Null (stehend)**: die CAD-Szenenpose ist verdreht; `hardware/model_zero_offsets.json`
  (die Anzeige-Korrektur der WebUI) wird als Vorwärtskinematik angewandt, `hardware/model_invert.json` dreht
  die Achse um, wo der reale Servo andersherum zählt → Sim-Gelenkwinkel = Servo-Gelenkwinkel.
* **Gelenkgrenzen** aus `hardware/joint_limits.json` (Repo-Stand ist maßgeblich, auch wenn die neuen
  Schultergrenzen noch nicht auf den Roboter gespielt sind).
* **Geometrie**: je Link ein STL für gedruckte Teile und eines für die Servos (aus dem GLB, in Standpose,
  Link-Frame). Nicht verbaute Originalelektronik (MilkV + Hat, Akku, alter BackPack + Waveshare, Speaker,
  Milk-Kamera, Mikro, LCD-IMU-Display) und Schrauben sind entfernt; Kopf/Hals bleiben. Kollision nur
  Fußsohlen-Boxen (unterste 12 mm der Fußnetze) gegen den Boden, Sites `left_foot`/`right_foot`.
* **Massen aus Datenblättern** (Stand 2026-09-23, `hardware/electronics_masses.json` → `mass_model.json`):
  Alles, was nicht gedruckt ist, steht mit Datenblattmasse, Quelle und Vertrauensgrad (`V` Hersteller /
  `D` Distributor / `S` hergeleitet) in `hardware/electronics_masses.json`;
  `sim/tools/build_mass_model.py` (braucht `.cad/bin/python`) setzt jeden Posten an die Stelle, die das CAD
  ihm gibt — Rucksackbauteile auf ihre v4.2-Platzhalterboxen, Kabel über die Länge ihrer Mittellinien
  (14 AWG Silikon ≈ 27 g/m je Ader), Kopfmodule auf ihre Einbaulage — und schreibt `hardware/mass_model.json`.
  Gedruckte Teile aus ihrem **echten** Netzvolumen × 0,75 g/cm³ — auch die Rucksackschalen (vorher pauschal
  240 + 71 g geraten, real 189 + 53 cm³ → 142 + 40 g).
* **Gedruckte Teile: Risse im GLB zunähen statt Hüllvolumen raten.** Die GLB-Netze sind nicht wasserdicht,
  aber nicht wegen echter Löcher: an T-Stößen ist eine Kante auf einer Seite geteilt, auf der anderen nicht
  (Torso 907 offene Kanten, Kopf 76). Der alte Fallback „halbes Hüllvolumen" überschätzt hohle Schalen damit
  um das 2–3-fache. `sim/tools/meshfix.py` (aus `hardware/head_imu/neck_mount_imu.py` übernommen) teilt die
  ungeteilte Kante an diesen Punkten — **keine neue Geometrie, nichts verschoben** — danach ist die Fläche
  geschlossen und Volumen/Schwerpunkt/Trägheit sind integrierbar. Gegenprobe: der so geflickte Kopf ergibt
  30,4 g, die separat modellierte reale Kopfschale (`hardware/head_cam`) 31,2 g; Hinterplatte 29,0 vs. 28,4 g.
  Strenge 2-Mannigfaltigkeit wird **nicht** verlangt (die Netze haben 10–20 Kanten mit >2 Flächen und
  Null-Volumen-Splitter, die die Integrale nicht stören), und bis zu 2 mm Restkante bleiben erlaubt — sonst
  fiele die linke Hand auf das Hüllvolumen zurück (37,7 g) und wäre asymmetrisch zur rechten (beide 46,9 g).
  Korrekturen u. a.: Kopf 88 → 30 g, Torso 430 → 377 g, Hüft-Roll 41 → 21 g.
  Wichtigste Massenkorrektur: **STS3250 wiegt 74,5 g** (Datenblatt), nicht die bisher angenommenen 62 g —
  10 Beinservos, also +125 g tief unten. Ergebnis **2,627 kg** (Roboter 2,053 + Rucksack 0,574), also 290 g
  weniger als die alte Schätzung, Schwerpunkt **10 mm tiefer**. Offen bleibt nur noch das Wiegen (Gesamt,
  je ein Servo, bestückter Rucksack) — die dicksten `S`-Posten sind XY-CD63 (±10 g) und Anti-Spark (±8 g),
  und die effektive PETG-Dichte von 0,75 g/cm³ ist weiter geschätzt.
* **IMU: reale Einbaulage und Achslage.** Site `imu` sitzt auf dem QMI8658 des Waveshare RP2040-LCD-1.28 im
  **linken Auge** (`hardware/head_imu/imu_pose.json`, CAD 27,4 / −15,4 / 423,8 mm → im Körperframe 2,2 cm vorn,
  2,7 cm links, 11,4 cm über der Torsomitte). Der Kopf hat kein Gelenk, die IMU ist also starr an `base`.
  Die Site ist auf die **echten Chipachsen gedreht** (x_imu nach rechts, y_imu nach oben, z_imu nach hinten,
  Quaternion 0,5 / 0,5 / −0,5 / −0,5) — `imu_acc`/`imu_gyro` im Sim sind damit genau das, was der reale Sensor
  ausgibt, der Pi-Loop reicht die Rohwerte ohne Drehung durch. Prüfwert: stehender Roboter → Beschleunigung
  **+9,81 auf der Chip-Y-Achse**; Gierrate +1 rad/s → Gyro `[0, +1, 0]` (im Sim verifiziert).
  `metadata.json` enthält Position, Quaternion und `R_body_from_imu`. Wer lieber in Körperachsen beobachtet:
  `build_model_cad.py --imu-frame body`, dann muss der Pi die Rohwerte mit `R_body_from_imu` drehen.
  `base`-Site (Torsomitte) liefert wie bisher `base_link_*` für die Belohnungen.
* Metadaten wie bisher (`metadata.json`: Servo-IDs aus `hardware/servo_ids.json`, Aktuatortypen, kp/kd),
  Sys-ID-JSONs kopiert. `walking.py`: `torso_body_name` (Massen-Randomisierung) jetzt konfigurierbar,
  Default `base`.

Ansehen ohne Policy: `python sim/tools/show_model.py sim/assets/zbot-cad --out sheet.png` (4 Ansichten) oder
`--viewer` (interaktiv, statisch in der Nullpose; `--physics` simuliert mit Haltefeder).

**Statik der Nullpose:** mit Rucksack liegt der Schwerpunkt 8 mm hinter der Torsomitte und nur 17 mm vor der
Fersenkante der Sohlenbox (−24…+79 mm); mit servoähnlichem PD (kp 16) kippt der Roboter aus der reinen Nullpose
nach hinten. Die Nullpose bleibt trotzdem exakt Servo-Null (Aktion 0 = Servo-Null fürs Deployment); die
Policy muss die Vorneigung lernen. Die Massenarbeit vom 2026-09-23 hat die Reserve kaum verändert (16,6 → 16,7 mm),
wohl aber die Verteilung: 164 g weniger im Rucksack, 290 g weniger insgesamt, Schwerpunkt 10 mm tiefer.

**Modell neu bauen** nach Änderungen an Hardware-JSONs, Rucksack-CAD, Kopfmodulen oder Massen:

```bash
.cad/bin/python sim/tools/build_mass_model.py            # hardware/mass_model.json (braucht cadquery)
~/Documents/stash/ksim-zbot/.venv/bin/python sim/tools/build_model_cad.py
```

## Modell-Variante mit Backpack v3.1 (`assets/zbot-pixel-backpack`)

Erzeugt von `sim/tools/add_backpack.py` aus `zbot-pixel` (Aufruf: `python sim/tools/add_backpack.py`,
braucht nur numpy):

* **Rucksack als eigener Körper** `backpack` am Torso-Link, Frame = OnShape-Assembly-Frame des
  Rucksack-CAD (`hardware/backpack_v2`), abgeleitet über die Schultergelenk-Anker und die
  Torso-Rückwand: `lokal = CAD + (0, 8,2, −372,6) mm` im Frame von `Z_BOT2_MASTER_BODY_SKELETON`
  (Rückwand im Sim bei x −46,3 ↔ Torso-Netz endet bei −45,6). Sichtbar als drei Meshes
  (Grundrahmen, Deckel, Träger), keine Kollisionsgeometrie (Kollision bleibt Füße↔Boden).
* **Massenmodell (Educated Guess, `backpack_mass_model.json`)**: 738 g aus 12 Posten (PETG-Teile
  198/68/31 g, LiPo 200, XY-CD63 60, Pi 46, Kabel 60, …), Schwerpunkt im CAD-Frame
  (−9, 56, 314) mm = 18 mm hinter der Rückwand; Trägheitstensor als Summe von Quadern.
* **Torso-Link −0,40 kg** (1,546 → 1,146 kg, Trägheit proportional): Original-Akku 5,2 Ah,
  MilkV + Hat, Speaker und alter BackPack/Waveshare sind im Build nicht vorhanden.
* Ergebnis: Gesamtmasse 3,756 → **4,094 kg**, Roboter-Schwerpunkt verschiebt sich um
  **10 mm nach hinten (−x im Sim) und 4 mm nach oben** (Stand qpos0, CAD-schwere Links).
* Training/Rendern: `sim/tools/train_backpack.sh <exp>` (GPU 0, `GPU=1` für die zweite),
  `sim/tools/render_policy.sh <ckpt.bin> <out.mp4> [s]` (offscreen/EGL, `imageio[ffmpeg]` liegt im venv).

### Neu trainierte Policies `cad2_*` (Stand 2026-09-23/24) — gültig für das aktuelle Modell

**Die `cad_*`-Policies weiter unten sind überholt.** Sie liefen auf dem alten Massenmodell (Kopf 88 statt
30 g, STS3250 62 statt 74,5 g, Rucksack v3.1) und auf einer IMU, die als Körperachsen-Site im Torso saß.
Ihre Beobachtungen passen nicht mehr zum Modell — nicht wiederverwenden, nur als Vergleichszahlen lesen.

Alle fünf Rezepte neu trainiert, Auswahl per `sim/tools/pick_best.py` über den Snapshot-Sweep
(16 Argmax-Rollouts × 5 s mit Randomisierung und Stößen):

| Run | Schritt | Tempo | Stürze | Gier | Torso-Rollen p2p | Charakter |
| --- | --- | --- | --- | --- | --- | --- |
| `cad2_v4_heading` | 320 | 0,31 m/s | 0/16 | 1,9° | 51° | kräftig, große Schritte |
| `cad2_v6_small_ft` | 335 | 0,19 m/s | 0/16 | 1,4° | 44° | kleine Schritte (Fine-Tune aus v4) |
| `cad2_v9_calm` | 45 | 0,11 m/s | 0/16 | 2,0° | 30° | ruhig |
| `cad2_v10_calm2` | 850 | 0,13 m/s | 0/16 | 2,2° | 27° | ruhigster Geher |
| `cad2_v13_tiny` | 905 | 0,07 m/s | 0/16 | 2,5° | **25°** | kleinste Schritte (Fine-Tune aus v10) |

Bestätigt sich: **das Torso-Rollen bleibt bei ~25° hängen**, auch mit korrigierten Massen. Die 5,7-cm-Sohle
ist der begrenzende Faktor, nicht die Massenverteilung.

**Vorsicht bei `cad2_v9_calm`:** der Sweep krönt Schritt 45, einen sehr frühen Checkpoint. Er bewertet Tempo
und Ruhe über 5 s, nicht Robustheit. Vor einem Einsatz gegen einen späteren Checkpoint über 30 s mit Stößen
gegenprüfen. Für die Fine-Tune-Eltern setzt `train_queue.sh` deshalb `--min-step` auf die Hälfte des Budgets.

### Trainings-Queue (`sim/tools/train_queue.sh`)

Fährt mehrere Varianten nacheinander auf **einer** GPU, unbeaufsichtigt, als systemd-User-Unit `zbot-queue`:

```bash
GPU=1 sim/tools/train_queue.sh start      # Definition: sim/train/zbot_walking_task/queue/queue.txt
sim/tools/train_queue.sh status
sim/tools/train_queue.sh stop
```

Je Stage: `train_backpack.sh` starten, auf `max_steps` warten, aus `active_runs.txt` austragen (sonst
belebt der Watchdog einen fertigen Lauf wieder), dann den Snapshot-Sweep **im Hintergrund** auf der CPU
anwerfen, während die nächste Stage schon die GPU nutzt. Ein Fine-Tune wartet nur auf den Sweep seines
eigenen Elternlaufs und holt sich dessen Checkpoint über `pick_best.py`.

Zwei Fallen, die dabei Zeit gekostet haben und jetzt im Skript kommentiert sind:

* **Die Overrides des Laufs müssen in den Sweep.** Das Eval baut das Netz aus der Task-Config; mit
  `heading_obs=True` ist der Actor 64 statt 62 Eingänge breit, und ohne die Overrides scheitert *jeder*
  Checkpoint beim Deserialisieren (`changed shape from (256, 62) to (256, 64)`) — der Sweep produziert
  dann stillschweigend nichts, und die abhängige Fine-Tune-Stage fällt aus.
* **Fine-Tunes zählen den Schrittzähler weiter**, weil xax den State mit den Gewichten lädt. `max_steps`
  ist also absolut: Elternschritt + Budget.

### Gespeicherte Policies (`sim/train/zbot_walking_task/best/`, je Checkpoint + ONNX/SavedModel/Metadaten + Messungen + Videos)

| Ordner | Charakter | 5 s mit Stößen (16 Läufe) | Unruhe (Torso-Rollen p2p / Hüfte / Arme) |
| --- | --- | --- | --- |
| `cad_v4_heading_step380` | kräftig, 12 cm Schritte, 0,35 m/s, Hub 9 cm | 0 Stürze, 1,81 m, 1,8° Gier | 53° / 15° / 23° |
| `cad_v6_small_ft_step585` | kleine Schritte (5 cm), 0,17 m/s, Hub 6 cm | 0 Stürze, 0,86 m, 2,3° Gier | 43° / 11° / 24° |
| `cad_v9_calm_step185` | ruhig, 4 cm Schritte, 0,16 m/s; **30 s: 4,85 m nominal / 3,65 m mit Stößen, 0 Stürze** | 0 Stürze, 0,79 m, 2,4° Gier | 35° / 7° / 4° |
| `cad_v10_calm2_step910` | ruhigste gehende, 3 cm Schritte, 0,12 m/s, Hub 4 cm; **30 s nominal: 5,03 m, 0 Stürze** | 0 Stürze, 0,63 m, 2,1° Gier | 26° / 5° / 3° |
| `cad_v13_tiny_step690` | kleinste Schritte, 1,3 cm, 0,05 m/s, Hub 4 cm | 0 Stürze, 0,25 m, 2,5° Gier | 25° / 6° / 4° |

Die Torso-Rollbewegung bleibt bei ≈ 25° Spitze-Spitze hängen (cad_v10/v13, auch mit dreifacher Rollstrafe): bei der
schmalen Sohle (5,7 cm) muss das Gewicht für jeden Schritt seitlich über den Standfuß; weniger ginge nur mit
Doppelstütz-Gang (Einbeinstand-Anteil < 90 %) oder breiterer Spur — offen.

### Ergebnis (Stand 2026-09-08 11:30): der Roboter läuft geradeaus

`sim/train/zbot_walking_task/best/cad_v4_heading_step380/` enthält den gewählten Checkpoint, die Task-Optionen,
Messwerte und Videos (randomisiert 8 s, nominal 15 s). 16 Argmax-Rollouts × 5 s **mit** Randomisierung und Stößen:
0/16 Stürze, 1,81 m Median (min 1,44), 12 cm seitlich, Gier 1,8° (max 7°), 3 Schritte/s, Schwung 320 ms,
Fußhub 9 cm; nominal 2,0 m/5 s (0,41 m/s). Der Snapshot-Sweep (`snapshots/summary.txt`) zeigt ab Schritt 40 jeden
10-Minuten-Checkpoint sturzfrei und ≤ 4° Gier — die Wahl ist also nicht vom Zufall eines Checkpoints abhängig.

**Export für den Roboter:** `JAX_PLATFORMS=cpu python sim/tools/export_policy.py <ckpt.bin> <outdir>` schreibt
`policy.onnx` (direkt aus den MLP-Gewichten gebaut, gegen JAX geprüft), das xax-SavedModel `tf_model/` und
`policy_meta.json` (Eingangslayout, Gelenk-/Servo-Reihenfolge, Aktionssemantik) — für Schritt 380 liegt das unter
`best/cad_v4_heading_step380/export/`. (`tf2onnx` 1.16 ist mit NumPy 2 kaputt und wurde deshalb nicht benutzt.)

**Ruhiger Gang (ab 14:19):** `gait_analyze.py` misst jetzt auch die Unruhe: Torso-Rollwinkel Spitze-Spitze
53° (cad_v4) bzw. 44° (cad_v6), Hüft-Yaw/-Roll im Mittel 11–15° ausgelenkt, Arme 23°. Gegenmittel in `walking.py`:
`JointDeviationPenalty` (Summe |q| über `joint_deviation_joints`, Default Hüft-Yaw/-Roll + Arme), `BaseRollPenalty`
(|Roll| des Torsos), `MeanJointSpeedPenalty` (mittlere |Gelenkgeschwindigkeit|), dazu stärkere Aktionsglättung und
Seitenstrafe (Läufe cad_v8/cad_v9).

**Mehrere Meter am Stück:** `sim/tools/long_walk.sh <ckpt> <outdir> [s=30] [overrides]` (GPU=<n> optional) misst 16
Argmax-Rollouts über 30 s (Strecke, Stürze, Gangbild) und rendert ein 30-s-Video — Nachweis, dass die Policy nicht nur
5 s hält. Ergebnisse in `<exp>/longwalk_step<N>/{nominal,randomized}/eval.txt`.

**Kleine Schritte für Sim-to-Real (ab 12:00):** `cad_v6_small_ft` (GPU 0, Feintuning ab Schritt 380) und
`cad_v7_small_scratch` (GPU 1, von Null) mit konservativem Setup: Ziel 0,12–0,25 m/s, Schwungband 0,2–0,4 s,
Fußhub-Ziel 2 cm plus `FootLiftPenalty` ab 4 cm (`foot_lift_penalty=-0.5 foot_lift_max=0.04`), Aktionsglättung −0,1
statt −0,02. Ziel: kürzere, flachere Schritte und ruhigere Servobefehle bei gleicher Kursstabilität.

### Trainingsläufe mit dem Backpack-Modell (Stand 2026-09-07)

Alle in `sim/train/zbot_walking_task/<exp>/` (gitignored), gestartet mit `sim/tools/train_backpack.sh` (Modell per
`ASSETS=`, Default `zbot-cad`; v1–v10 liefen mit `zbot-pixel-backpack`)
(startet eine transiente **systemd-User-Unit** `zbot-train-<exp>`, denn alles, was aus einer
Editor-/Claude-Shell heraus läuft — auch mit `setsid nohup` — hängt in der cgroup des VS-Code-Fensters
und stirbt mit ihr; stoppen mit `systemctl --user stop zbot-train-<exp>`; ein Neustart mit demselben
`exp_dir` setzt vom letzten `checkpoints/ckpt.bin` fort):

| Lauf | Task-Optionen | Beobachtung |
| --- | --- | --- |
| `backpack_v1` | Vendored-Defaults (NaiveVelocityReward) | 1,1 m/s, aber Schlittern, starke Kurven, Stürze — gestoppt |
| `backpack_v2_track` | `velocity_tracking=True` (Vorwärts-Kommando 0,15–0,35 m/s, Kurshalten) | geradeaus, sturzfrei, ~0,16 m/s, eher Rutschen |
| `backpack_v3_gait` | `velocity_tracking=True gait_shaping=True target_speed_min=0.2 target_speed_max=0.4` | Fuß-Abhebe-Belohnung, Drift-/Gier-/Ruck-Strafen; Schritt 295: 0,44 m/5 s, 1,2 m seitlich, 35° Gier, 1/16 Stürze — gestoppt |
| `backpack_v4_slip` | v3 + `target_speed 0.25–0.45 track_reward_scale=3.0 track_error_scale=0.15 gait_step_reward=0.0 gait_single_support=0.3 feet_slip_penalty=-0.3` | Schritt 80: 1,26 m/5 s (min 1,12), 0,25 m/s, 0/16 Stürze, 11° Gier — geradeaus, aber **Trippeln** (11 Fußhebungen/s, 70 ms Schwung, 2 cm Hub); Snapshot Schritt 130 |
| `backpack_v5_fast` | v4 mit 0,3–0,5 m/s, `gait_single_support=0.5 feet_slip_penalty=-0.4` | nach 8 min zugunsten v6/v7 abgebrochen |
| `backpack_v6_swing` | v4 + `gait_swing_reward=1.0 gait_flip_penalty=-0.1` (Schwungdauer-Band 0,15–0,45 s) | von Null; nach 80 Schritten zugunsten v8 gestoppt |
| `backpack_v7_swing_warm` | wie v6, `load_from_ckpt_path=` v4-Snapshot Schritt 130 | Schritt 285: echte Schritte (5,1/s, Schwung 220 ms, Hub 3,8 cm), aber 6/16 Stürze, 0,6 m seitlich, 26° Gier; Schwung-Reward sättigt am unteren Bandrand — gestoppt zugunsten v9 |
| `backpack_v8_clear` | v7 + `gait_swing_tmin=0.25 gait_swing_tmax=0.6 gait_clearance_reward=0.5 gait_clearance_target=0.03`, Warmstart v7-Snapshot Schritt 180 | Schritt 325: **Gehen** (3,5 Schritte/s, Schwung 340 ms, Hub 5–6 cm, 95 % Einbeinstand), aber 1,1 m seitlich, 26° Gier, 3/16 Stürze. **Schritt 355: 0/16 Stürze, 1,58 m in 5 s (0,32 m/s), 0,30 m seitlich, 13° Gier, 3,3 Schritte/s, Schwung 360 ms** — Checkpoint in `validation_step355/` und `snapshots/`; nominal (ohne Randomisierung, `validation_step355_nominal/`, 15-s-Video): 0/16 Stürze, 1,62 m/5 s, seitlich 0,23 m, Gier 9° (Median); läuft weiter (GPU 0) |
| `backpack_v9_clear_scratch` | Optionen wie v8, von Null | nach 15 min zugunsten v10 gestoppt |
| `backpack_v10_heading` | v8 + `heading_penalty=-1.0 lateral_position_penalty=-0.5`, Warmstart v8-Snapshot Schritt 350 | läuft (GPU 1; erster Start 21:10 starb mit der Editor-Sitzung, Neustart 02:28 als systemd-Unit) |
| **`cad_v1_mild`** | **Modell `zbot-cad`**, von Null: v8-Rewards + Critic-Driftstrafen, Schwungband 0,15–0,45 s | Schritt 110: 1,14 m/5 s, 3/16 Stürze, 27° Gier; Schritt 270: 6/16 Stürze, 41° Gier — 06:28 gestoppt |
| **`cad_v2_strict`** | wie cad_v1, Schwungband 0,25–0,6 s | **Schritt 80: 0/16 Stürze, 1,18 m/5 s, 7 cm seitlich, 8° Gier, 2,7 Schritte/s, Schwung 340 ms, Hub 8 cm; Schritt 195: 0/16, 1,35 m, 19 cm seitlich, 10° Gier**; ab Schritt 235 wieder 25–36° Gier — 09:50 gestoppt (Snapshots 95/140/195 gesichert) |
| `cad_v3_strict_fast` | wie cad_v2, `target_speed 0.3–0.5 heading_penalty=-2.0` | Snapshot 65: 1,44 m, aber 34° Gier — 08:01 zugunsten cad_v4 gestoppt |
| **`cad_v4_heading`** | wie cad_v2 + `heading_obs=True` (Actor sieht [cos, sin] des Gierwinkels relativ zum Start) | **geradeaus ab Snapshot 15, sturzfrei ab 40**; Schritt 180: 1,92 m/5 s, 2° Gier; **Schritt 380: 0/16 Stürze, 1,81 m/5 s (0,35 m/s), 12 cm seitlich, 1,8° Gier (max 7°)** → `best/cad_v4_heading_step380/` (+ ONNX-Export); 11:45 pausiert bei Schritt 455 |
| `cad_v5_heading_fast` | wie cad_v4, `target_speed 0.3–0.5` | Schritt 120: 1,84 m, 2,7° Gier, 1/16 Stürze — 11:45 pausiert |
| `cad_v6_small_ft` | cad_v4 + kleine Schritte (s. o.), Feintuning ab `best/cad_v4_heading_step380` | jeder Snapshot 380–585 sturzfrei; Schritt 470: 0,84 m/5 s, ~5 cm Schritte, Hub 6 cm, 1,3° Gier → **`best/cad_v6_small_ft_step585/`** (+ Export); 14:19 gestoppt |
| `cad_v7_small_scratch` | wie cad_v6, von Null | Snapshots 15–110: 0/16 Stürze, ~3 cm Schritte, Hub 5 cm, 3–4° Gier — 14:19 gestoppt |
| `cad_v8_calm_ft` | cad_v6 + ruhiger Gang: `joint_deviation_penalty=-0.3` (Hüft-Yaw/-Roll, Arme nahe Null), `roll_penalty=-1.0`, `joint_velocity_penalty=-0.02`, Glättung −0,2, Seitenstrafe −1,0; Feintuning ab `best/cad_v6_small_ft_step585` | Schritt 675: Arme 24→10°, Hüfte 11→8°, Rollen nur 43→40° p2p (bleibt im Rocking-Muster der Ausgangspolicy) — 15:45 zugunsten cad_v10 gestoppt |
| `cad_v9_calm_scratch` | wie cad_v8, von Null | Schritt 85: 0/16 Stürze, 0,51 m/5 s, Hub 4,3 cm, **Torso-Rollen 30° p2p, Hüfte 5,7°, Arme 3°**, 1,2° Gier; Snapshots 55–150 stabil (0 Stürze, ~30° Rollen) → **`best/cad_v9_calm_step185/`** (+ Export); **Langstrecke 30 s nominal: 4,85 m Median (4,6–5,3), 0/16 Stürze, 3° Gier** — 16:45 gestoppt |
| `cad_v10_calm2_scratch` | wie cad_v9, `roll_penalty=-3.0 gait_single_support=0.0 joint_deviation_penalty=-0.5` (Doppelstütz erlaubt, Rollen stärker bestraft) | Schritt 105: 0/16 Stürze, 0,61 m/5 s, **Rollen 26° p2p, Hüfte 4,9°, Arme 2,5°, Hub 3,7 cm**, 1,7° Gier; Schritte 210–910 gleich (Rollen 24–26°, 0 Stürze, ~0,12 m/s, Plateau) → **`best/cad_v10_calm2_step910/`** — 23:38 gestoppt |
| `cad_v11_tiny_scratch` | wie cad_v10, **2-cm-Schritte**: `target_speed 0.05–0.10 gait_swing 0.15–0.3 s gait_clearance_target=0.015 foot_lift_max=0.025 joint_velocity_penalty=-0.03` | Schritt 130: ruhig (Rollen 20°, Hüfte 4°, Arme 2°, Hub 3 cm), **aber tritt auf der Stelle** (0,10 m/5 s): bei Zielen ≤ 0,1 m/s ist `track_error_scale=0.15` zu lasch — 19:00 gestoppt |
| `cad_v12_tiny_ft` | wie cad_v11 mit `track_error_scale=0.05`, Feintuning ab cad_v11-Snapshot | Schritt 250: kriecht mit 0,04 m/s (0,8 cm Schritte bei 4,9/s), ruhig (Rollen 22°) — 20:40 gestoppt |
| `cad_v13_tiny_from_calm` | **Warmstart aus cad_v10** (läuft 0,12 m/s, 3,3 cm Schritte) mit `target_speed 0.05–0.10 track_reward_scale=5 track_error_scale=0.05 gait_swing 0.2–0.35 clearance 0.015 foot_lift_max 0.025` → Ziel 2-cm-Schritte | Schritt 690: 0/16 Stürze, 0,05 m/s, **1,3 cm Schritte** bei 3,9/s, Hub 4 cm, Rollen 25°, 2,5° Gier; Schritt 800 gleich (Plateau) → **`best/cad_v13_tiny_step690/`** — 23:38 gestoppt |

Die Optionen `velocity_tracking`, `gait_shaping`, `target_speed_*`, `gait_*` sind lokale
Ergänzungen in `walking.py` (Defaults reproduzieren den vendored Task). Werkzeuge:
`progress.sh <exp>` (Reward-/Episodenkurven aus TensorBoard), `validate_policy.sh <ckpt> <out>`
(16 Argmax-Rollouts → Weg/Geschwindigkeit/Stürze, Gangbild via `gait_analyze.py`: Schritte/s,
Schwungdauer, Stützphasen, Fußhub, Video, Kontaktbogen), `start_autoval.sh` → `autoval.sh` (stündliche
Validierung als losgelöster Watcher, Unit `zbot-autoval`, hebt dabei stündlich einen Checkpoint auf), `stop_run.sh <exp>`
(einziger sauberer Weg, einen Lauf zu beenden), `zbot_watchdog.sh` (systemd-User-Timer `zbot-watchdog.timer`, alle
10 min, `~/.config/systemd/user/`: belebt in `active_runs.txt` eingetragene Läufe und den Watcher nach Absturz,
Logout oder Reboot per `<exp>/launch.sh` wieder — die Units haben zusätzlich `Restart=on-failure` — und kopiert den
neuesten Checkpoint nach `<exp>/snapshots/` und `~/zbot-ckpt-backup/<exp>/`, weil xax nur den letzten behält;
Protokoll `watchdog.log`; der Watcher wird nur wiederbelebt, solange `autoval_cmd.sh` existiert (löschen = aus); `validate_policy.sh` serialisiert sich über `flock /tmp/zbot-validate.lock`, weil zwei parallele CPU-Validierungen neben
zwei Trainings den RAM sprengen (OOM-Kill des Watchers am 08.09.) → `<exp>/validation_step<N>/`). Reward-Werte in TensorBoard
sind Mittel je Zeitschritt geteilt durch die Rollout-Länge (250): `dhhealthy 0,002` = volle 0,5.

**Gelernte Lektion:** Weg/Geschwindigkeit/Stürze allein reichen als Metrik nicht — v4 „lief“ sauber
geradeaus, hob die Füße aber nur 2 cm für je 70 ms (Kontakt-Chattering, im Video ein Zittern statt
Schritte). `gait_analyze.py` deckt das auf (Fußkontakt- und Fußpositions-Observations aus dem
Rollout-Datensatz). Gegenmittel in `walking.py`: `SwingDurationReward` (+1 je Zeitschritt einer
Schwungphase von `gait_swing_tmin..tmax` s, −1 bei kürzeren, 0 bei längeren/Flugphasen; die Dauer
ist bekannt, weil der Reward auf dem ganzen Rollout rechnet) und `ContactFlipPenalty` (Kontaktwechsel
je Schritt). Weil die Policy den Schwung-Reward mit Schwüngen knapp über `tmin` sättigt, gibt es
zusätzlich `FootClearanceReward` (Hub des Schwungfußes über seiner Standhöhe, gesättigt bei
`gait_clearance_target`) und ein strengeres Band 0,25–0,6 s (v8).
Der Actor sieht keine absolute Orientierung (nur IMU/Gelenke/Kommandos), der Critic schon; deshalb
sind `HeadingPenalty` (|Gier| aus `qpos`) und `LateralPositionPenalty` (|y|) als Critic-sichtbare
Driftstrafen ergänzt (v10) — sie bestrafen die akkumulierte Abweichung statt der Gierrate, die beim
Gehen ohnehin oszilliert.
Auf dem CAD-Modell zeigt der Snapshot-Sweep von `cad_v2_strict`, dass diese Critic-Strafen die Drift nicht
stetig senken: der Gierwinkel nach 5 s pendelt von Checkpoint zu Checkpoint zwischen 5° und 36° (Schritte
95/140/155/195 gut, 125/180/235/315 schlecht). Deshalb `heading_obs=True` (cad_v4): `BaseHeadingObservation`
liefert dem Actor [cos ψ, sin ψ] des Gierwinkels relativ zur Startrichtung (+2 Eingänge, Rauschen 0,05 bei
Randomisierung). **Deployment:** der Pi-Loop muss dafür den beim Policy-Start genullten IMU-Gierwinkel
(Gyro-Integration bzw. Fusion mit Magnetometer) liefern; ohne `heading_obs` bleibt der Eingangsvektor wie bisher.

## Offene Punkte vor dem ersten ernsthaften Training

Aus [docs/sim-context.md](../docs/sim-context.md) §8, aktualisiert:

- [x] ~~K-Scale-Asset-Pipeline~~ → API tot, GitHub-Assets lokal gesichert (git-lfs)
- [x] ~~STS3250-Geschwindigkeit~~ → Sys-ID: 8,94 rad/s (`actuators/feetech_sts3250.json`)
- [x] ~~Bein-Servo-IDs → Gelenk-Zuordnung~~ → aus `hardware/servo_ids.json` in metadata.json
- [x] ~~Hip-Roll-Limits in Radiant~~ → MJCF: links −0,175…+1,571 rad (−10°…+90°),
      rechts gespiegelt — deckt sich mit dem mechanischen Anschlag (Abduktion frei,
      Adduktion blockiert). Gegen das gedruckte Teil verifizieren, dann ggf. enger ziehen.
- [ ] Servos + Gesamtroboter **wiegen**, Link-Inertials normieren (CAD nimmt Vollmaterial
      an; real PETG 4 Wände/40 % Gyroid). Bis dahin trainiert die Sim mit zu schweren Links.
- [ ] **IMU-Entscheidung** (Typ, Einbaulage, Rate) — Modell-IMU sitzt im Torso
      (`IMU_2_site`); reale Orientierung muss exakt gespiegelt werden.
- [ ] Gemessene `hardware/joint_limits.json` in die MJCF-Ranges übernehmen — erst nachdem
      Vorzeichen-/Nullpunkt-Konventionen Sim ↔ GUI verifiziert sind (GUI-Grade ≠
      zwangsläufig MJCF-Radianten-Vorzeichen; nicht blind übertragen).
- [ ] kp/kd in `metadata.json` stehen auf zbot2-Defaults (16/3, passend zum
      Sys-ID-Duty-Modell). Vor Sim-to-Real: reale Servo-P/D-Register auslesen und
      angleichen (§5.4). Legacy-Referenz (per-Joint getunt, alte Pipeline):
      Hüfte 80–90, Knie 80, Knöchel 100.
- [ ] Latenz-/Backlash-/Deadband-Modell (§5.1–5.3) ins Training einbauen — der Task hat
      `min/max_action_latency`, Backlash/Deadband noch nicht.

## Upstream-Referenzen

- [kscalelabs/ksim](https://github.com/kscalelabs/ksim) · [ksim-zbot](https://github.com/kscalelabs/ksim-zbot) · [kscale-assets](https://github.com/kscalelabs/kscale-assets) (archiviert — bei Bedarf forken)
- [kscalelabs/kinfer](https://github.com/kscalelabs/kinfer) (Policy-Export), [kos-zbot](https://github.com/kscalelabs/kos-zbot) (Referenz für Feetech-Deployment, wird hier nicht 1:1 genutzt)
- Deploy-Referenzcode: `~/Documents/stash/ksim-zbot/ksim_zbot/zbot2/deploy/`
