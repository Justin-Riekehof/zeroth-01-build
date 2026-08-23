# Sim-Kontext — Z-Bot ("Pixel"), Zeroth-01-Derivat

**Zweck:** Kontextdatei für Claude Code beim Aufsetzen des Sim-/RL-Stacks (ksim → MJX → kinfer → Pi).
**Stand:** 2026-08-06
**Gilt zusammen mit:** `robot-context.md`, `zbot-gesamt-bom.md`

**Legende Verifikationsstatus:**
`[OK]` belegt/gemessen · `[V]` zu verifizieren gegen Repo/Datenblatt · `[?]` offen, Entscheidung/Messung fehlt

---

## 1. Zielbild

Locomotion-Policy (Stand → Balance → Walking) per RL in Simulation trainieren, Sim-to-Real-Transfer auf die reale 16-DOF-Plattform. Trainings-Hardware: Ubuntu-Workstation, 2× RTX 3090 (48 GB VRAM), 32 GB System-RAM. Zielhardware: Raspberry Pi 4B **2 GB** (Rev 1.5), 50 Hz Regelschleife.

---

## 2. Die zentralen Abweichungen vom Referenz-Design

Das ist der Teil, der beim Sim-Aufbau schiefgeht, wenn man das Default-Modell ungeprüft übernimmt.

| Bereich | Referenz Zeroth-01 | Dieser Aufbau | Sim-Konsequenz |
|---|---|---|---|
| Bein-Aktoren | ursprüngliche Revisionen: STS3215 in allen 16 Gelenken | **10× STS3250** (12 V, C002, 1:345) `[OK]` | Aktuator-Blöcke im MJCF/URDF für Beingelenke **müssen** andere `forcerange`/`gear`/Geschwindigkeitsgrenzen tragen als die Arme. Wenn das Repo einen einzigen Aktuator-Typ für alle 16 Joints definiert → aufsplitten. |
| Arm-Aktoren | STS3215 | 6× STS3215 (12 V, C018, 1:345) `[OK]` | unverändert |
| Compute | Milk-V Duo S + kos-zbot-Image | **Raspberry Pi 4B 2 GB**, eigener Inferenz-Loop (Python/onnxruntime ARM64, FastAPI-Intent-API) `[OK]` | kos-zbot-Runtime wird **nicht** 1:1 genutzt → Joint-Order- und Action-Scaling-Metadaten aus dem kinfer-Export müssen im eigenen Loop explizit gelesen und angewandt werden. Häufigste Sim-to-Real-Fehlerquelle. |
| Servo-Bus | UART/GPIO | Waveshare Bus Servo Adapter (A) V1.1 via USB, `/dev/ttyUSB0`, 1 Mbit/s, Y-Splitter-Topologie an der Hüfte `[OK]` | Bus-Roundtrip-Latenz gehört ins Latenzmodell (s. §5) |
| Material | — | Bambu PETG, 4 Wände, 40 % Gyroid `[OK]` | Link-Massen der CAD-Inertials sind **zu hoch** (Vollmaterial-Annahme) → skalieren, s. §4 |

> **Wenn mit „Wechsel der Bein-Servos" etwas anderes gemeint ist als STS3215→STS3250 (z. B. ein späterer Tausch einzelner Einheiten), muss dieser Abschnitt korrigiert werden, bevor Aktuator-Parameter gesetzt werden.**

---

## 3. Aktuator-Daten für das Sim-Modell

Beide Typen: **1:345 Getriebe, 12 V, Position-Control-only** (interner PD-Regler, kein externer Torque-/Stromzugriff). In MuJoCo also `position`-Aktuator mit `kp`, **nicht** `motor`.

| Parameter | STS3215 (Arme) | STS3250 (Beine) | Status |
|---|---|---|---|
| Stall-Torque @12 V | 30 kg·cm ≈ **2,94 N·m** | 50 kg·cm ≈ **4,90 N·m** | `[OK]` Herstellerangabe |
| Nenn-/Dauertorque | 10 kg·cm ≈ **0,98 N·m** | ~25 kg·cm ≈ **2,45 N·m** (≈50 % Peak vor Schutzabschaltung) | `[OK]` Datenblatt bzw. robonine-Messung |
| Stall-Strom @12 V | 2,7 A | — | `[V]` STS3250-Wert fehlt |
| Leerlaufgeschwindigkeit | 0,222 s/60° → **≈ 4,7 rad/s** | — | `[V]` **kritisch**: STS3250-Geschwindigkeit ist der eigentliche Grund für den Typ in den Beinen; Wert aus Feetech-Datenblatt holen, bevor `velocity`-Limits gesetzt werden |
| Encoderauflösung | 4096 Counts / 360° = **0,088°/Count** | identisch | `[OK]` |
| Firmware-Deadband | 10 Counts ≈ **0,88°** | identisch | `[OK]` |
| Ausgangs-Backlash | ~15 Counts ≈ **1,3°** | identisch (anzunehmen) | `[OK]` / `[V]` für 3250 |
| Thermische Abschaltung | 70 °C | 70 °C; Anstieg ~3,75 °C/min bei 40 % Last → Trip nach ~8 min | `[OK]` |
| Überspannungsschutz | >14 V / <4 V | identisch | `[OK]` |
| Masse | — | — | `[?]` **beide wiegen** (Küchenwaage reicht), dann Link-Inertials korrigieren |

**Bus-Feedback (real verfügbar, für Reward-Design und Telemetrie relevant):** Position, Geschwindigkeit, Spannung (Reg 62, 0,1-V-Einheiten), Strom (1 = 6,5 mA), Temperatur (°C direkt), Last (Skala 1000 = 100 % Torque-Duty). `[OK]`

**Konsequenz fürs Reward-Shaping:** Der Dauertorque, nicht der Stall-Torque, ist die reale Grenze. Torque-Penalty so kalibrieren, dass die Beinservos im stationären Gang unter ~2,45 N·m bleiben — sonst trainierst du eine Policy, die auf der Hardware nach 8 Minuten thermisch abschaltet.

---

## 4. Kinematik, Massen, Gelenkgrenzen

- **16 DOF:** Arme 3 pro Seite, Beine 5 pro Seite.
- **Servo-IDs real:** Arme links 11/12/13, rechts 21/22/23 `[OK]`. Beine: 30er/40er-Schema nach K-Scale `[V]` — die exakte ID→Gelenk-Zuordnung gegen die tatsächlichen Metadaten prüfen, nicht raten.
- **Neutralstellung:** Servo-Mitte = Count 2048 = 180°. Nullwinkel-Kalibrierung der Gelenke ist real bereits durchgeführt `[OK]`. Der Sim-Nullpunkt muss mit dieser realen Referenzpose übereinstimmen.
- **Hüft-Roll-Anschlag:** mechanischer Anschlag im gedruckten Teil, erlaubt Abduktion ~90°, blockiert Adduktion. Ist **Absicht** (Selbstkollisionsschutz). URDF-`lower`/`upper` des Hip-Roll-Joints müssen exakt darauf liegen. `[V]` konkrete Radiant-Werte aus dem URDF ziehen und gegen das gedruckte Teil gegenprüfen.
- **Link-Massen:** CAD-Inertials gehen von Vollmaterial aus. Real: PETG (~1,27 g/cm³) mit 4 Wänden + 40 % Gyroid → effektive Dichte deutlich niedriger. **Vorgehen:** Gesamtroboter wiegen, Summe der URDF-Link-Massen dagegen normieren, Servo-Massen (gemessen, s. §3) als separate, korrekte Punktmassen einsetzen. `[?]`
- **Gesamtmasse Roboter:** `[?]` noch nicht gemessen — blockiert eine saubere Inertial-Kalibrierung.

---

## 5. Sim-to-Real-Gap: was explizit modelliert werden muss

Diese Punkte sind bei dieser Hardware nicht optional, sie sind der Unterschied zwischen einer Policy, die in Sim läuft, und einer, die real läuft.

1. **Regelrate 50 Hz** → `ctrl_dt = 0.02 s`. Physikschritt feiner (z. B. 0,004 s, 5 Substeps).
2. **Aktions-Latenz:** Bus-Roundtrip bei 1 Mbit/s mit 16 Servos ergibt real ~50–100 Hz Kommandorate. Action-Delay von **1–2 Regelschritten (20–40 ms)** einbauen und randomisieren. Ohne das lernt die Policy eine Reaktionsschnelligkeit, die die Hardware nicht hat.
3. **Backlash ~1,3°** und **Deadband ~0,88°** auf die Gelenkkommandos legen (oder mindestens als Positionsrauschen approximieren).
4. **Interner PD statt Torque-Control:** Die Servos regeln selbst. Der `kp` im Sim-Aktuator ist ein Ersatzmodell für diesen internen Regler, kein freier Designparameter — real veränderst du ihn über die Servo-Register (PID-Gains, Ramps), nicht über die Policy.
5. **Spannungsabfall:** 3S LiPo läuft von 12,6 V auf 10,8 V herunter, Torque skaliert mit. Effektiven Torque über die Episode randomisieren (z. B. ±15 %).
6. **PETG-Flex:** Der Sim-Körper ist starr, der reale nicht. Gegenmaßnahme: Joint-Damping, `armature` und Kontaktreibung breit randomisieren, statt Steifigkeit vorzutäuschen.
7. **Action-Filter:** EMA auf die Policy-Ausgabe gehört **in beide Seiten** — Sim und reale Deployment-Loop, mit identischem Koeffizienten. Sonst verschiebt der Filter das Verhalten nur real.
8. **IMU:** Observation-Space braucht Projected Gravity + Winkelgeschwindigkeit. **Einbaulage, Achsorientierung und Datenrate der realen IMU müssen im Sim-Observation exakt gespiegelt werden.** `[?]` IMU-Wahl (RP2040-LCD-1.28/QMI8658 via USB vs. I²C-Breakout) und Montageorientierung sind noch nicht final — das blockiert einen sauberen Observation-Space und sollte **vor** dem ersten Trainingslauf entschieden werden.

---

## 6. Software-Stack

| Werkzeug | Rolle | Ort |
|---|---|---|
| **ksim** (+ xax, mujoco-scenes) | RL-Training, MuJoCo MJX + JAX | Workstation (CUDA) |
| **ksim-zbot / ksim-gym-zbot** | Task-Template mit MJCF/URDF | Workstation |
| **kscale CLI** | Asset-Download (`ks robots urdf download zbot`) | `[V]` s. Warnung unten |
| **kinfer** | Export Checkpoint → `.kinfer` (trägt Joint-Order + Action-Scaling als Metadaten) | Workstation |
| **kinfer-sim** | Policy-Validierung/Visualisierung vor Deployment | Workstation |
| **kos-sim** | Sim-Backend mit derselben gRPC-Schnittstelle wie die echte Hardware | Workstation |
| **onnxruntime (ARM64)** | Inferenz on-robot, ~1 ms/Forward-Pass | Pi 4B |

**Aufteilung:** Training GPU-gebunden auf einer 3090 (MJX skaliert über parallele Envs; Multi-GPU via `pmap` optional, aber 32 GB System-RAM sind eher der Engpass als VRAM). Ausführung ausschließlich auf dem Pi — Off-Board-Inferenz über WLAN ist für den 50-Hz-Balance-Loop keine Option (variable Latenz kippt genau den Regelkreis, den die Sim mit festem Timing trainiert hat).

**Warnung Asset-Beschaffung:** `docs.kscale.dev` ist auf DNS-Ebene tot. K-Scale hatte Ende 2025 erhebliche operative Probleme. **Vor dem ersten Schritt prüfen, ob die `kscale`-CLI/API überhaupt noch Assets liefert.** Fallbacks: URDF/Mesh-Pack aus GitHub Release V0.3.1, oder Export aus dem aktuellen OnShape-Dokument (Workspace „Opus", ID `b4672a7f…` — **nicht** das eingefrorene „OpenLCH"/V84-Dokument `cacc96f8…`). BOM-Referenz liegt im Repo `kscalelabs/docs`, Branch `master`, Pfad `docs-master/docs/robots/zeroth-01/bom.md`.

---

## 7. Konkrete Reihenfolge für den Sim-Aufbau

1. Asset-Verfügbarkeit klären (§6-Warnung), URDF/MJCF lokal ziehen.
2. **Aktuator-Blöcke prüfen:** Trägt das Modell einen einheitlichen Servo-Typ? Falls ja → Beingelenke auf STS3250-Parameter aufsplitten (§3). Vorher STS3250-Geschwindigkeit aus dem Datenblatt holen.
3. Joint-Limits gegen die reale Mechanik prüfen, insbesondere Hip-Roll (§4).
4. Servos wiegen, Roboter wiegen, Link-Inertials normieren (§4).
5. IMU-Entscheidung treffen und Observation-Space danach definieren (§5.8).
6. Joint-Order-Mapping schriftlich fixieren: MJCF-Joint-Reihenfolge ↔ Servo-IDs ↔ kinfer-Metadaten. Ein Mapping, eine Quelle, in beiden Loops referenziert.
7. Latenz-/Backlash-/Deadband-Modell einbauen (§5.1–5.3), **dann erst** trainieren.
8. Validierung: `kinfer-sim` → `kos-sim` (gRPC-Pfad identisch zur Hardware) → Pi mit `--dry-run` (Loop-Latenz messen, Ziel < 20 ms) → erst danach mit Torque auf die reale Plattform, hängend/gesichert.

---

## 8. Offene Punkte, die vor dem ersten Trainingslauf geschlossen sein sollten

- `[?]` STS3250-Leerlaufgeschwindigkeit (Datenblatt)
- `[?]` Massen STS3215 / STS3250 / Gesamtroboter (wiegen)
- `[?]` IMU-Typ, Einbaulage, Datenrate
- `[V]` Bein-Servo-IDs → Gelenk-Zuordnung
- `[V]` Hip-Roll-Limits in Radiant aus URDF
- `[V]` Ob die K-Scale-Asset-Pipeline noch funktioniert
- `[V]` Ob der Bedeutung von „Wechsel der Bein-Servos" in §2 korrekt getroffen ist
