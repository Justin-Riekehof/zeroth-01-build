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
