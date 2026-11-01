# Trainingstagebuch: Der Zeroth-01 lernt laufen

Jeder Trainingslauf mit Ziel, Ausgangspunkt, Änderungen gegenüber dem Vorgänger, Ergebnis, Beobachtung und Lehre —
die Fehlschläge eingeschlossen. Grundlage für den Film über den Trainingsprozess. **Wird bei jedem Lauf fortgeschrieben.**

Konventionen:
- Läufe liegen in `sim/train/zbot_walking_task/<lauf>/` (Konfiguration `config.yaml`, Startbefehl `launch.sh`,
  Checkpoints `snapshots/ckpt.<schritt>.bin`, Kurven `tensorboard/`).
- Ab der Servo-Ära wertet `sim/tools/calm_watch.py` jeden Lauf alle 40 Iterationen mit dem Hardware-Prüfer
  (`sim/tools/hardware_gate.py`) aus: Verlauf in `<lauf>/calm_watch.json`, Ende und Grund in `<lauf>/calm_done.json`.
- Videos ab `servo_ctrl_v3` automatisch alle 100 Iterationen: `<lauf>/videos/<lauf>_step<NNNNN>.mp4`, immer dieselbe
  Kamera (15 s, `sim/tools/render_policy.sh`), damit die Clips direkt vergleichbar und schneidbar sind.
- "Score" ist der Hardware-Prüfer-Score (0..1, 1 = alle Grenzen eingehalten), "Tracking" das erreichte Vorwärtstempo
  relativ zum befohlenen.

---

## Zeitleiste

| Phase | Zeitraum | Läufe | Ergebnis | Mehr dazu |
| --- | --- | --- | --- | --- |
| 1 Rucksack-Modell | Anfang Sept. 2026 | `backpack_v1` … `backpack_v10_heading` | Der Roboter läuft in der Sim geradeaus (8.9.) | `sim/README.md`, Abschnitte "Ergebnis (Stand 2026-09-08)" und "Trainingsläufe mit dem Backpack-Modell" |
| 2 Erstes CAD-Modell | Mitte Sept. | `cad_v1_mild` … `cad_v13_tiny_from_calm` | überholt: falsche Massen (Kopf 88 statt 30 g), IMU im Torso statt im Kopf | `sim/README.md` |
| 3 Korrigiertes CAD-Modell | 23./24.9. | `cad2_v4_heading`, `cad2_v6_small_ft`, `cad2_v9_calm`, `cad2_v10_calm2`, `cad2_v13_tiny` | fünf versionierte Policies, alle 0/16 Stürze in der Sim | `sim/policies/README.md`, Videos in `best/` |
| 4 Erster Hardwaretest | 21./22.10. | die fünf `cad2_*` | **alle fallen nach ~1 s**; Test mit `speed=3000` zerreißt das Teil `hip_yaw_left` | Abschnitt [Hardwaretests](#hardwaretests-2122-10) |
| 5 Messen statt raten | 25.10. | Bench-Tests am Roboter (keine Policy) | Servo-Dynamik, Steifigkeit, Spannung, Massen gemessen | Abschnitt [Bench-Tests](#bench-tests-25-10) |
| 6 Servo-Modell | ab 25.10. | `servo_v1` … `servo_ctrl_v3` | Sim bildet das reale Scheitern nach; Weg zu kontrolliertem Laufen | Abschnitt [Servo-Ära](#servo-ara-ab-25-10) |

---

## Hardwaretests (21./22.10.)

**Ziel:** die fünf `cad2_*`-Policies erstmals auf dem echten Roboter (Isomatte, Speed-Register 1000).

**Ergebnis:** alle fünf fallen nach 1–2 s um (Tilt > 55°). Step-Logs ab dem 22.10. (`/policy/logs` auf dem Pi).

**Diagnose:**
- Inferenz korrekt: ONNX-Replay der geloggten Beobachtungen ergibt exakt die geloggten Aktionen.
- Die Policies sind **bang-bang** (Aktionen nahe ±1, Sprünge von Schritt zu Schritt). In der Sim glättete ein weicher
  PD-Regler (kp 16, kd 3) das, der echte Servo folgt fast direkt.
- Speed-Register 1000 ticks/s = 1,53 rad/s gegen 8,9 rad/s (bzw. hart verdrahtet 5 rad/s) in der Sim.

**Tiefpunkt (22.10. 18:33):** Test mit `speed=3000`. Der Roboter fällt, das linke Bein dreht sich ganz nach innen, das
Teil `hip_yaw_left` (Traverse mit Servo-Aufnahme und Horn-Platte) reißt am mechanischen Anschlag auf. Vermutliche
Ursache: Nach dem Sturz hielt der Pi die Pose mit vollem Torque, der Aufprall drückte das Gelenk gegen den Anschlag
(Spannungseinbruch auf 9,3 V in diesem Fenster). **Korrekturen:** Fault gibt jetzt den Torque frei (`policy.py`);
Neudruck `hardware/hip_yaw_left/` mit Bambu-Studio-Projekt (6 Wände, 50 % Gyroid); keine Policy mehr auf die Hardware
bis zum Retraining.

## Bench-Tests (25.10.)

Bench-Modus im Pi-Dienst (`/bench/*`, `src/pi_service/bench.py`), Roboter hängend, Auswertung `sim/tools/bench_*.py`.

| Test | Erkenntnis |
| --- | --- |
| Sprünge pro Gelenk (`step`) | Beine (STS3250) folgen dem Speed-Register, Verzögerung ~40 ms, a ≈ 350 rad/s². Arme (STS3215): hartes Limit 1,8 rad/s, a ≈ 8 rad/s², 60 ms |
| Alle Gelenke zugleich (`rect`) | Packeinbruch 0,2/0,4/0,5/0,7 V bei Speed 1000/1500/2000/2500 → Speed 2000 gewählt |
| Durchhang unter Schwerkraft (`sag`) | Beine ~45 Nm/rad (P-Register 32 = Werkseinstellung; Sim hatte kp 16 = 22,7 Nm/rad), 100 % Last ≈ 9 Nm |
| Halten im Stand (`hold`) | Gewicht 2,5–2,6 kg (Modell 2,63); Neigung auf Parkett 12,9° = Modell 13,1° → Massen/Schwerpunkt passen. Auf der Isomatte 8,1° (Füße sinken ein) |

**Stolperstein:** Einzelne Ausreißer im Status-Register der Servos (Temperatur 137 °C) brachen den ersten Test ab →
Wächter entprellt.

---

## Servo-Ära (ab 25.10.)

Gemeinsame Basis aller Läufe: Servo-Modell mit gemessener Verzögerung, Tempo- und Beschleunigungsgrenze pro Gelenk
(`servo_model=True`), `servo_kp=32`, `dt=0.002`, Start in der echten Center-Pose (Hüfte +18,7° / −16,1°, `start_pose=center`).

### `servo_v1` — die Tiny-Policy im neuen Servo-Modell (25.10.)
- **Ziel:** die Tiny-Policy (0,05–0,10 m/s) an die echten Servos anpassen.
- **Start:** `cad2_v13_tiny` Schritt 905. Bis Schritt 1300.
- **Highlight:** Die alte Policy fällt im neuen Sim **nach ~1 s** — genau wie auf der Hardware. Das Servo-Modell bildet
  das reale Scheitern nach.
- **Ergebnis (Schritt 1300):** 0,04 m/s, 2/16 Stürze. Lernt das Stehen, kaum das Gehen.
- **Tiefpunkt nebenbei:** Ich hielt die alten Läufe zuerst für numerisch instabil (Klassen-Default `dt=0.005`); sie liefen
  aber mit `dt=0.002`. Lehre: nie mit dem Default-dt testen.

### `servo_v2_normal` und `servo_v3_calm` (25./26.10., außerhalb dieser Sitzung gestartet)
- `servo_v2_normal`: ab `cad2_v4_heading` 320, 0,20–0,35 m/s, bis 1200. **Einzige, die richtig geht:** 0,23 m/s, 1/16
  Stürze, geradeaus. Aber Aktionsrate 0,37 rad/Schritt (bang-bang), Hüft-Yaw die Hälfte der Zeit an der Grenze, Ziele
  in 99 % der Schritte jenseits der echten Gelenkgrenzen. Video: `servo_v2_normal/eval_final/walk_v2.mp4`.
- `servo_v3_calm`: ab `servo_v1` 1300, 0,08–0,15 m/s, stärkere Glättung, bis 2100. 0,05 m/s, 1/16 Stürze.

### `servo_calm_a` / `servo_calm_b` — Strafen für Hardwaregrenzen (26.10.)
- **Ziel:** v2 ruhiger machen, Hardwaregrenzen einhalten. Ende erst bei bestandenem Prüfer oder Stagnation (Vorgabe).
- **Start:** `servo_v2_normal` 1200. Neue Strafen: Ziel–Gelenk-Abstand, Saturation, Nähe zur Gelenkgrenze, Ziel jenseits
  der Grenze, Servo-Tempo über einem Puffer (A: 85 %, B: 70 %). Neu: Sim klemmt Ziele auf die echten Grenzen wie der Pi.
- **Ergebnis:** B Score 0,47 → 0,586 (Schritt 1365), dann Plateau. Die Beine liefen **61–68 % der Zeit am Servo-Limit**.
- **Lehre:** Widerspruch im Konzept — 0,20–0,35 m/s verlangt und schnelle Gelenke bestraft. Beide von Hand gestoppt.
- **Tiefpunkte (Infrastruktur):** cuSolver-/Speicher-Abstürze, OOM-Kills der Wächter (CPU-Auswertung braucht > 8,6 GB
  RAM), TF-Export bei jedem Checkpoint sprengt den GPU-Speicher → `export_for_inference=False`, Auswertungen auf GPU 0.
  Erst am 27.10. entdeckt: **der Watchdog startete die fertigen Läufe `servo_v1/v2/v3` alle 10 min neu**, jeder belegte
  kurz bis zu 20 GB GPU-Speicher — vermutlich die Ursache vieler dieser Abstürze.

### `servo_ctrl_v1` — Konzept v2: Grenzen erzwingen statt bestrafen (26.10.)
- **Ziel:** kontrolliertes Laufen. Der Nutzer schlägt vor, das Tempo zu senken, wenn die Gelenke langsamer sein sollen.
- **Start:** `servo_v3_calm` 2100. **Befehls-Ratenbegrenzer** (Ziel wandert höchstens mit 70 % der Servogeschwindigkeit,
  identisch in Sim und Pi-Runner), 0,06–0,12 m/s, Gangtakt 1,0–1,5 Hz.
- **Ergebnis:** Score 0,721 → **0,784** (Schritt 2145, 0 Stürze), Stagnation bei 2310. Servo-Grenzen und Ruhe der
  gesendeten Ziele erfüllt, Tracking 0,4–0,5.
- **Beobachtung (Video `servo_ctrl_v1/demo_2145.mp4`):** "eher ein Auf-der-Stelle-Trippeln, die Beinbewegung ist relativ
  zittrig."
- **Korrekturen unterwegs:** Prüfer verlangte 5° Abstand zur Hüft-Yaw-Grenze, die echte Grenze liegt aber nur 3° neben der
  Nullstellung (unerfüllbar) → Abstand pro Gelenk höchstens die Hälfte. Quadratische Strafe für Ziele jenseits der Grenze
  war bei kleinen Überschreitungen praktisch null → linear.

### `servo_ctrl_v2` — Konzept v3: von null, gegen Zittern und Trippeln (26./27.10.)
- **Ziel:** das Zittern (Roh-Aktion springt, Begrenzer kürzt zu einem 25-Hz-Zickzack) und das Trippeln beseitigen.
- **Start:** von null. Strafen auf Roh-Aktion (Überschreitung des Begrenzerschritts, zweite Differenz), Belohnungen für
  Schwingphase/Fußhub/Einbeinstand gesenkt, Vorwärts-Reward ×6, 0,08–0,14 m/s.
- **Ergebnis:** Stagnation bei 670 (bester Score 0,755): 0 Stürze, Tracking 0,63. Aber Zitter-Kennwert konstant am
  Maximum, 33–57 % der Beinbewegung über 5 Hz.
- **Beobachtung (Video `servo_ctrl_v2/demo_670.mp4`):** "Das ist das stärkste Zittern bisher. Genau das Gegenteil von dem,
  was wir angestrebt hatten." — "Er geht zwar, aber sehr trippelnd."
- **Diagnose danach:** 7,2 Bodenkontakte pro Fuß und Sekunde bei befohlenen 1,0–1,5 Hz, Schrittlänge im Median 5 mm.
  Die Füße vibrieren, statt zu schreiten; die Policy ignoriert den Gangtakt. Die Strafen auf die Roh-Aktion erreichten
  die Gelenke nicht, weil Begrenzer und Servo-Modell das Zittern vorher glätteten.
- **Lehre:** Zittern lässt sich nicht wegstrafen, wenn es nichts kostet. Es muss baulich unterdrückt und dort bestraft
  werden, wo man es sieht (Gelenkbewegung). Schritte entstehen nicht aus Schwingdauer-Belohnungen allein.

### Hardware-Kandidat `servo_ctrl_v2_step670_f02` (27.10.)
- **Entdeckung:** Beim ersten Test des Live-Viewers lief Checkpoint 670 von `servo_ctrl_v2` versehentlich mit den
  v3-Einstellungen, also **mit dem neuen Tiefpassfilter α = 0,2**, mit dem die Policy nie trainiert wurde. Nutzer: "aber
  dieser Checkpoint in ksim sieht überzeugend aus. Den würde ich gerne deployen und testen."
- **Highlight:** Der Filter allein scheint das Zittern zu beseitigen, ohne Neutraining.
- Export mit `sim/tools/export_policy.py ... --set action_filter_alpha=0.2` nach `sim/policies/servo_ctrl_v2_step670_f02/`;
  der Vertrag vermerkt die Abweichung (`export_overrides`: trainiert ohne Filter, eingesetzt mit 0,2).
- Prüfer-Ergebnis mit Filter (16 Rollouts mit Stößen): *folgt.* Hardwaretest: *folgt.*

### `servo_ctrl_v3` — Konzept v4: Filter, Gangtakt, Schrittlänge (gestartet 27.10. 16:38)
- **Ziel:** ruhige, echte Schritte im befohlenen Takt.
- **Start:** `servo_ctrl_v2` 670 (geht, fällt nicht). Startbefehl `sim/tools/launch_servo_ctrl3.sh`.
- **Neu:**
  - Tiefpass auf die Aktion (`action_filter_alpha=0.2`, in Sim und Pi identisch): Zickzack mit halber Abtastrate kommt
    zu 11 % durch, 10 Hz zu ~19 %, die Gangbewegung zu ~83 %.
  - Strafe auf die Gelenkbeschleunigung (was das Video zeigt).
  - Belohnung für Füße im Gangtakt (Schwingen/Stehen nach der Takt-Phase).
  - Belohnung für Schrittlänge pro echtem Schritt (≥ 0,2 s Schwingphase), voll bei 8 cm.
  - Stärkere Strafe für Kontaktwechsel (−0,5 statt −0,1).
- **Prüfer neu:** Zittern am Spektrum der Gelenkwinkel (≤ 15 % über 5 Hz) und an der Beschleunigung der gesendeten Ziele.
- **Zwischenstände (Gate, 16 Rollouts mit Stößen):**

  | Schritt | Score | Stürze | > 5 Hz | Ziel-Zickzack p99 | an Grenze | Tracking |
  | --- | --- | --- | --- | --- | --- | --- |
  | 680 | 0,738 | 0 | 0,43 | 0,086 | 0,51 | 0,45 |
  | 725 | 0,738 | 0 | 0,44 | 0,086 | 0,70 | 0,47 |
  | 765 | 0,734 | 0 | 0,43 | 0,084 | 0,92 | 0,30 |
  | 810 | 0,733 | 0 | 0,46 | 0,081 | 1,00 | 0,23 |
  | 850 | 0,734 | 0 | 0,45 | 0,078 | 1,00 | 0,19 |
  | 895 | 0,733 | 0 | 0,46 | 0,078 | 1,00 | 0,16 |
  | 940 | 0,732 | 0 | 0,47 | 0,076 | 1,00 | 0,09 |
  | 980 | 0,731 | 0 | 0,53 | 0,074 | 1,00 | 0,02 |
  | 1025 | 0,731 | 0 | 0,53 | 0,076 | 1,00 | 0,01 |
  | 1070 | 0,734 | 0 | 0,53 | 0,071 | 1,00 | −0,01 |
  | 1110 | 0,737 | 0 | 0,53 | 0,068 | 1,00 | −0,01 |

  Tiefpunkt-Kandidat: Zittern unverändert, die Policy rückt an die Gelenkgrenze und hört auf vorwärts zu laufen.
- **Video-Check 810 vs. 680** (Standbilder 10/s, Beine vergrößert): 810 steht aufrechter, Füße heben abwechselnd ab,
  der Oberkörper verdreht weniger als bei 680 (dort deutlich Gier um die Hochachse). Fortbewegung im Bild nicht
  erkennbar (Kamera folgt). Zittern über 5 Hz ist in 10-Bilder/s-Standbildern nicht beurteilbar.
- **Video-Check 940:** Haltung wie 810, ruhiger Oberkörper, Beine treten abwechselnd — aber laut Messung praktisch auf
  der Stelle (Tracking 0,09). Die Policy hat gelernt, das Vorwärtslaufen aufzugeben: Stehen-und-Treten ist unter den
  neuen Strafen billiger als Laufen. Zittern unverändert (> 5 Hz 0,47).
- **Video-Check 1070:** Treten auf der Stelle mit leicht gebeugten Knien, Oberkörper ruhig. Tracking −0,01: kein
  Vorwärtskommen mehr. Zittern auf dem Höchststand des Laufs (0,53). Der Score (0,734) bleibt flach, weil
  Verbesserungen (Ziel-Zickzack 0,086 → 0,071) und Verschlechterungen sich aufheben — der Wächter erkennt so keinen
  Abbruchgrund. **Lehre:** Ein Gesamtscore kann ein Kippen ins falsche Verhalten verdecken; Tracking muss ein harter
  Abbruchgrund sein.
- **Ergebnis (27.10. 20:22):** Wächter beendet den Lauf wegen Stagnation (Score < 3 % besser über 6 Bewertungen),
  letzter Checkpoint 1120, „bester" 725 (Score 0,738 — aber nur, weil er noch am nächsten an v2-670 liegt).
  **Gescheitert:** Konzept v4 macht aus „zittrig laufen" ein „zittrig auf der Stelle treten". Kein Checkpoint ist
  ein Hardware-Kandidat. Tiefpunkt für den Film: ruhiger Oberkörper, tretende Beine, null Vorwärtskommen.

### Diagnose 28.10.: Woher kommt das Zittern? — eine Regelschwingung durch die Servo-Totzeit
- **Frage:** Ist das Zittern Rauschen der Policy, ein Effekt von Begrenzer/Filter, oder Physik (Fußkontakt)?
- **Methode:** Spektrum von Rohaktion, gesendetem Ziel und Gelenkwinkel (Beine) in den Gate-Rollouts; dann dieselbe
  Policy (`servo_ctrl_v2` 670) mit veränderter Servo-Totzeit / ohne Begrenzer ausgerollt (16 Episoden je Variante).
- **Befund:** Schon die *Rohaktion* schwingt mit einer scharfen Spitze (70–80 % der Energie über 5 Hz). Die Frequenz
  folgt der Totzeit:

  | Variante | Totzeit Beine | Spitze Rohaktion | > 5 Hz Gelenk | Stürze | Tracking |
  | --- | --- | --- | --- | --- | --- |
  | ohne Totzeit | 0 ms | ~10,5 Hz | 0,48 | 0/16 | 0,84 |
  | trainiert | 40 ms | ~6,2 Hz | 0,46 | 0/16 | 0,63 |
  | trainiert + Filter 0,2 | 40 ms + Filter | ~5,6 Hz | 0,42 | 1/16 | 0,55 |
  | doppelte Totzeit | 80 ms | ~4,0 Hz | 0,30 | 3/16 | 0,65 |
  | ohne Begrenzer | 40 ms | ~6,0 Hz | 0,44 | 5/16 | 0,65 |

  Periode ≈ 2 × (Totzeit + ~45 ms) — das Kennzeichen einer Regelschwingung mit Totzeit: die Policy regelt mit hoher
  Verstärkung gegen ihre eigene, verzögert ankommende Bewegung. Der Begrenzer ist nicht die Ursache.
- **Folgen:**
  - Der Tiefpass wirkt wie mehr Totzeit: Frequenz sinkt, das Zittern bleibt. Darum hat Konzept v4 nicht geholfen.
  - Eine niedrigere Steuerrate (Aktion 2 Schritte halten) wäre ebenfalls mehr Totzeit → *verworfen*.
  - Strafen auf Ruck/Beschleunigung kämpfen gegen das, womit die Policy balanciert → Policy weicht aus (v3: stehen).
- **Lehre:** Zittern ist hier kein Glättungsproblem, sondern fehlende Information: die Policy sieht nur die letzte
  Aktion, nicht die ~2 Aktionen, die noch in der Servo-Totzeit „unterwegs" sind.
- **Filmnotiz:** guter Wendepunkt für den Film — nach drei Läufen Symptombekämpfung die Ursache gefunden.

### `servo_ctrl_v4` — Konzept v5: Aktionsverlauf + zufällige Totzeit (gestartet 28.10. ~01:20, von null)
- **Ziel:** ruhiges Laufen, indem die Ursache des Zitterns wegfällt statt es zu bestrafen.
- **Nutzerfrage auf dem Weg:** „Aber warum ist die Zitterfrequenz dann bei 0 ms Totzeit am höchsten?" — Antwort:
  die Frequenz sagt, wie *schnell* es zittert; die Schwingdauer ist ~2 × Gesamtverzögerung, und auch ohne Totzeit
  bleiben ~48 ms (Servo-Bewegung, 20-ms-Takt). Stärke des Zitterns bei 0 und 40 ms gleich (0,48 / 0,46).
- **Neu:**
  - `action_history=4`: der Actor sieht a(t-1) … a(t-4), also die Befehle, die in den ~85 ms Totzeit + Servo-Lag
    noch unterwegs sind (+48 Eingänge, 112 statt 64). Der Pi baut denselben Vektor (`ObsBuilder`, Metadatum
    `action_history`); geprüft: ONNX auf Sim-Beobachtungen = Sim-Aktion (3·10⁻⁷), Verlauf identisch.
  - `delay_rand=0.02`: Totzeit pro Episode zufällig ±20 ms (Beine 20–60 ms), gleich für den ganzen Bus.
  - Kein Aktionsfilter (ist Totzeit), keine Gelenkbeschleunigungs-, Schrittlängen- und Takt-Terme aus v4.
  - Tempo-Tracking 10 (war 6), Ruckstrafe −0,1 (war −0,5). Sonst Belohnungen wie `servo_ctrl_v2`.
  - Pi: die „letzte Aktion" startet jetzt mit der gemessenen Pose statt mit Nullen — wie in der Sim (alte
    Abweichung, mit dem Verlauf wären es 4 statt 1 falscher Eingang gewesen).
- **Wächter:** neue Regel „Tracking eingebrochen" (läuft die Policy einmal ≥ 30 % und dann zweimal darunter → Stopp,
  egal was der Score sagt; v3 wäre bei 850 statt 1110 gestoppt). Video alle 100 Iterationen.
- **Erwartung:** von null braucht es ~600 Iterationen bis zum Laufen (v2: Schritt 670 nach ~5,5 h).
- **Zwischenstände (Gate, 16 Rollouts mit Stößen):**

  | Schritt | Score | Stürze | > 5 Hz | Ziel-Zickzack p99 | an Grenze | Tracking |
  | --- | --- | --- | --- | --- | --- | --- |
  | 50 | 0,702 | 1 | 0,44 | 0,086 | 0,35 | 0,32 |
  | 180 | 0,740 | 0 | 0,39 | 0,086 | 0,60 | 0,43 |
  | 310 | 0,700 | 2 | 0,41 | 0,086 | 0,58 | 0,51 |
  | 440 | 0,691 | 3 | 0,42 | 0,086 | 0,51 | 0,44 |
  | 525 | 0,716 | 1 | 0,41 | 0,086 | 0,61 | 0,62 |
- **Video-Check 440:** aufrecht, Beine treten abwechselnd, Oberkörper ruhig — optisch wie `servo_ctrl_v2`.
- **Jitter-Analyse 525:** die Rohaktion schwingt weiter mit ~5,6 Hz (74 % über 5 Hz), der Begrenzer ist 76 % der
  Zeit aktiv; Ziel-Zickzack p99 = 0,086 = genau eine volle Richtungsumkehr bei Begrenzer-Maximum (2 × 0,043 rad).
  **Lehre:** Information allein beseitigt die Schwingung nicht — für PPO kostet sie fast nichts (Ruckstrafe −0,1).
  Der Verlauf macht ruhiges Regeln erst *möglich*; *belohnt* werden muss es zusätzlich.
- **Gemessen (Schritt 525, pro Schritt):** Tracking +0,036; Zitter-Strafen zusammen −0,0009 (Begrenzer −0,0005,
  Glätte −0,0003, Ruck −0,0001) = ~3 % — fast gratis.
- **Unbeaufsichtigte Kette (28.10. 06:14, Dienst `zbot-chain`, `sim/tools/train_chain.py`):**
  - `servo_ctrl_v5`: startet, sobald v4 zweimal hintereinander ohne Sturz mit Tracking ≥ 0,7 läuft (oder v4s Wächter
    endet), vom v4-Checkpoint mit bestem Tracking ohne Sturz; Zitter-Strafen ×10 (Ruck −1,0, Begrenzer −0,25,
    Glätte −3,0) ≈ 20 % der Tracking-Belohnung.
  - `servo_ctrl_v6`: wenn v5 endet und das Zittern noch durchfällt — vom ruhigsten v5-Checkpoint (ohne Sturz,
    Tracking ≥ 0,6), Strafen nochmal ×3.
  - Bricht das Tracking ein, endet die Kette (Strafe zu stark, Mensch entscheidet). Protokoll: `train_chain.json`.
- **Nutzerwunsch:** v4 Schritt 550 (im Viewer gezeigt) später an der Hardware testen → exportiert
  (`sim/policies/servo_ctrl_v4_step550`), in der Roadmap.
- **Ergebnis:** Wächter-Stopp bei 655 (Stagnation), bester Checkpoint 610: **0 Stürze, Tracking 0,84** — der beste
  Läufer bisher. Zittern unverändert (> 5 Hz 0,40).

### `servo_ctrl_v5` / `servo_ctrl_v6` — Zitter-Strafen ×10 und ×30 (unbeaufsichtigte Kette, 28.10. 06:48–~12:00)

| Lauf | Start | Strafen | Ende | > 5 Hz | Tracking (bester → letzter) |
| --- | --- | --- | --- | --- | --- |
| v5 | v4 610 | Ruck −1,0, Begrenzer −0,25, Glätte −3 | Stagnation bei 920 | 0,39–0,42 | 0,73 → 0,53 |
| v6 | v5 745 | Ruck −3,0, Begrenzer −0,75, Glätte −6 | Stagnation bei 1010 | 0,40–0,45 | 0,67 → 0,46 |

- Begrenzer-Anteil sinkt (0,80 → 0,54), aber die Rohaktion schwingt weiter mit ~5,5 Hz (65 % über 5 Hz), der
  Ziel-Zickzack bleibt bei 0,086, und das Tracking fällt. **Tiefpunkt:** mehr Strafe = weniger Laufen, nicht weniger Zittern.

### Entdeckung 28.10. nachmittags: Es gibt keine Schritte — die Roboter hüpfen
- Schwungphasen (Fuß in der Luft) in den Gate-Rollouts:

  | Policy | Schwünge | < 0,1 s | 0,1–0,2 s | ≥ 0,2 s (echter Schritt) |
  | --- | --- | --- | --- | --- |
  | `servo_ctrl_v2` 670 | 1160 | 95 % | 5 % | **0 %** |
  | `servo_ctrl_v4` 655 | 1104 | 92 % | 8 % | **0 %** |
  | `servo_ctrl_v6` 1010 | 969 | 90 % | 10 % | **0 %** |

  Die ganze Vorwärtsbewegung kommt aus Mikro-Hüpfern (< 0,2 s) mit 7–12 pro Fuß und Sekunde.
- **Lehre:** Das „Zittern" ist die Gangart selbst. Wer es bestraft, nimmt der Policy den Antrieb. Die
  Regelschwingung über die Totzeit ist der Takt dieser Hüpfer. Die Videos zeigten „abwechselnd tretende Beine" —
  mit 10 Bildern/s sieht ein 6-Hz-Hüpfer wie ein Schritt aus.
- Gate misst jetzt `swings_per_s_foot` und `real_step_share` (Anteil Schwünge ≥ 0,2 s), noch ohne Grenzwert.
- **Filmnotiz:** größter Wendepunkt — „er geht zwar, aber sehr trippelnd" (Nutzer, 27.10.) war wörtlich richtig.

### `servo_ctrl_v7` — Konzept v6: echte Schritte belohnen (gestartet 28.10. ~16:05, ab v4 610)
- Schwung-Belohnung 6,0 (war 0,3; +1 je Schritt für Schwünge 0,25–0,6 s, −1 für kürzere) ≈ 1/3 der Tracking-Belohnung,
  Kontaktwechsel −1,0 (war −0,1), Schrittlänge 15 (nur echte Schritte ≥ 0,2 s, voll bei 8 cm), Takt-Belohnung 1,0.
  Zitter-Strafen auf v4-Niveau. Start `sim/tools/launch_servo_ctrl7.sh`.
- Wächter: Tracking-Einbruch zählt erst nach 300 Iterationen (die Gangart muss umgebaut werden), Stagnation nach 400.
- **Nutzereinwand (28.10.):** „v4 hattest du mir visualisiert und das sah ganz klar nach Schritten aus." — Gegenprobe
  über die Fußhöhe statt des Kontaktsignals (v4 655): Fuß > 0,5 cm 5,2×/s, im Median 0,06 s; nie > 1 cm für ≥ 0,2 s;
  maximale Fußhöhe 1,7 cm. Kontaktsignal flackert nicht (5–6 % „kein Kontakt" bei Fuß am Boden). Erklärung des
  Eindrucks: die Beine wechseln das Gewicht langsam (Gelenkspektrum 0,2–1,4 Hz), die Füße hüpfen dabei 5–6×/s kurz
  an. Zeitlupe der Füße: `servo_ctrl_v4/videos/servo_ctrl_v4_step00570_feet_slowmo4x.mp4`.
- **Zwischenstände:**

  | Schritt | Stürze | Tracking | Schwünge/s/Fuß | echte Schritte |
  | --- | --- | --- | --- | --- |
  | 615 | 0 | 0,72 | 6,9 | 0 % |
  | 660 | 1 | 0,49 | 7,2 | 0,1 % |
  | 745 | 0 | 0,57 | 7,3 | 0 % |
  | 790 | 2 | 0,46 | 7,8 | 0 % |
  | 835 | 0 | 0,41 | 7,3 | 0 % |
- **Lehre:** Eine Belohnung, die erst ab 0,25 s Schwung zahlt, wird nie ausgelöst, wenn die Policy nie so lange
  schwingt — übrig bleibt nur die Strafe für kurze Schwünge, und die vermeidet sie durch langsameres Laufen.
- **Ergebnis (28.10. 19:52):** Wächter-Stopp wegen Stagnation bei 1045, bester Checkpoint = Startpunkt 615.
  Bis zum Ende 0 % echte Schritte, 7,3–8,2 Schwünge/s/Fuß (mehr als vorher), Tracking 0,41–0,49. **Gescheitert.**

### `servo_ctrl_v8` — Konzept v6b: dichte Schwung-Belohnung (gestartet 28.10. 18:10, ab v4 610, GPU 0 parallel zu v7)
- Wie v7, aber `gait_swing_dense=True`: je Schwungschritt 2·min(d / 0,25 s, 1) − 1 (0,04 s: −0,7; 0,125 s: 0; ab 0,25 s:
  +1) — jede Verlängerung eines Hüpfers wird belohnt, nicht erst der fertige Schritt. Start `sim/tools/launch_servo_ctrl8.sh`.
- Technik: GPU 0 trotz `XLA_PYTHON_CLIENT_MEM_FRACTION=0.6` bei 21,7 GB belegt → Wächter von v7 und v8 bewerten ab
  18:13 auf der CPU (`--eval-gpu -1`), Verlauf bleibt in `calm_watch.json`. Nach dem Ende von v7 (19:52) bewertet der
  v8-Wächter auf GPU 1.
- **Zwischenstände:**

  | Schritt | Stürze | Tracking | > 5 Hz | Schwünge/s/Fuß | echte Schritte |
  | --- | --- | --- | --- | --- | --- |
  | 610 | 0 | 0,83 | 0,40 | 6,7 | 0 % |
  | 650 | 0 | 0,79 | 0,30 | 5,7 | 0,3 % |
  | 690 | 1 | 0,62 | 0,43 | 6,9 | 0 % |
  | 730 | 1 | 0,60 | 0,40 | 6,4 | 0,3 % |
  | 770 | 3 | 0,49 | 0,29 | 4,8 | 3,7 % |
  | 810 | 1 | 0,35 | 0,26 | 3,9 | 17 % |
  | 855 | 3 | 0,40 | 0,24 | 3,6 | 19 % |
- **Highlight für den Film:** ab 770 die ersten echten Schritte seit Beginn der Servo-Ära; der Anteil über 5 Hz fällt
  auf den tiefsten Wert (0,24). Preis: Tracking 0,35–0,40, Stürze 1–3 von 16.
- **Video-Check 855** (Standbilder 10/s, Beine vergrößert): breiterer Stand als v4, der Oberkörper verlagert sich
  deutlich von Seite zu Seite, ein Bein ist sichtbar gebeugt und angehoben, während das andere trägt — erkennbare
  Einzelbeinphasen statt Gleichtakt-Hüpfen. Zeitlupe der Füße: `servo_ctrl_v8/videos/servo_ctrl_v8_step00855_feet_slowmo4x.mp4`.
- **Nutzer:** wollte v8 sehen → Live-Viewer mit Checkpoint 835.
- Ergebnis: *folgt.*

---

## Hardware-Tests 28.10. abends (Pi neu deployt: Torque frei bei Sturz, Ratenbegrenzer, Filter, Aktionsverlauf)

### `servo_ctrl_v2_step670_f02` — Frage: kommt das vorhergesagte Zittern auch am echten Roboter?
- **Dry-Run** (Servos stromlos, 15,8 s): Schleife 5,3 ms im Mittel, max 23,6 ms; Rohaktion nur 0,28 über 5 Hz —
  ohne Rückkopplung (Gelenke bewegen sich nicht) kaum Schwingung. Passt zur Diagnose „Regelschwingung über die Totzeit".
- **Hängend am Seil** (13,7 s, Not-Aus): Nutzer: **„war sehr hastig und zittrig"**.
  Gemessen: Rohaktion **0,73 über 5 Hz, Spitze 5,6 Hz** — die Sim sagte 0,70–0,74 und 5,6 Hz voraus.
  Gesendete Ziele 0,39, gemessene Gelenke 0,33 über 5 Hz; 11–16 Richtungswechsel pro Sekunde und Beingelenk;
  Gelenktempo p99 2,53 rad/s (Servo 3,07, Begrenzer 2,15). Pendeln am Seil bis 76° Neigung.
- **Lehre / Highlight:** Die Sim sagt das Zittern auf die Zehntel-Hertz genau voraus — das Servo-Modell (Totzeit,
  Tempo, Beschleunigung) stimmt. Das Problem ist die Policy, nicht die Simulation.
- Bodentest übersprungen: die Zitter-Frage ist beantwortet, auf dem Boden kämen nur Mikro-Hüpfer mit Sturzrisiko dazu.

### `servo_ctrl_v4_step550` — erste Policy mit Aktionsverlauf am Roboter
- **Dry-Run** (7,1 s): Schleife 5,7 ms im Mittel, max 11,4 ms. Beobachtung 112 Eingänge; Verlauf a(t−2)…a(t−4) exakt
  gleich den früheren Aktionen, beim Start = gemessene Pose (wie in der Sim). **Aber:** Rohaktion 0,84 über 5 Hz,
  Spitze ~8 Hz — obwohl sich kein Gelenk bewegt (v2 im Dry-Run: 0,28). Die Schleife läuft durch die Policy selbst
  (Aktion → Verlauf → Aktion): das Netz hat sich aus dem Aktionsverlauf einen eigenen Taktgeber für die
  Mikro-Hüpfer gebaut. Der Verlauf sollte ruhiges Regeln ermöglichen — er wird umgekehrt genutzt.
- **Hängend am Seil:** nach **2,4 s Abbruch „tilt 58° > 55° — fall"**, der Pi gab sofort den Torque frei
  (der Fix vom 22.10. wirkt; Roboter danach wieder aufrecht, Akku 12,3 V). Rohaktion 0,73 über 5 Hz, Spitzen 8 und
  9,7 Hz, 14–20 Richtungswechsel/s je Beingelenk, Gelenktempo p99 2,45 rad/s. Am Seil kippte der Roboter erst auf
  die rechte Seite (46°), richtete sich auf, dann nach hinten (54–58°).
- Auffällig im Start-Log: Gyro-Offset [−0,8, 13,8, −6,5] °/s aus 17 Proben (Ruhewert sonst ~−3 °/s auf Y) — der
  Roboter pendelte vermutlich bei der Kalibrierung; Befehl vx 0,11 (geplant war 0,08).
- **Lehre:** v4 zittert am Roboter schneller als v2 (8–10 statt 5,6 Hz) und schaukelt sich am Seil in 2,4 s bis
  zum Kippen auf. Aktionsverlauf ohne Anreiz zur Ruhe = eingebauter Oszillator. Für v8 vor jedem Seiltest im
  Dry-Run prüfen, ob die Rohaktion ohne Gelenkbewegung ruhig bleibt.
- **Filmnotiz:** Dry-Run vs. Seil von v2 und v4 nebeneinander — die Zahlen zeigen, woher das Zittern kommt.

### `servo_ctrl_v8_step895` — erste Policy mit echten Schritten in der Sim (37 % Schwünge ≥ 0,2 s)
- Vorab offline nachgespielter Dry-Run (feste Sensoren, nur die Policy mit eigenem Verlauf; trifft die echten
  Dry-Runs: v2 0,22 ↔ 0,28, v4 0,84 ↔ 0,84): v8 0,48 über 5 Hz, Spitze 3,7 Hz.
- **Dry-Run** (6,6 s): Rohaktion 0,52 über 5 Hz, **Hauptspitze 1,2 Hz** (= Gangtakt 1,25 Hz), Nebenspitzen ~4 Hz.
  Gyro-Kalibrierung ruhig (−2,2 °/s).
- **Hängend am Seil** (8,5 s, Nutzer-Not-Aus, kein Sturz-Abbruch): Rohaktion 0,61 über 5 Hz mit Spitzen 6,2/6,8 Hz —
  im geschlossenen Kreis kommt ein Teil der Schwingung zurück. **Gemessene Gelenke 0,26 über 5 Hz: der ruhigste
  Seiltest** (v2 0,33, v4 0,36). Gelenktempo p99 2,53 rad/s; Pendeln bis 74°, kippte am Seil zweimal ~50° nach
  hinten und richtete sich wieder auf. Akku danach 12,2 V.

| Seiltest | Rohaktion > 5 Hz | Spitze | Gelenke > 5 Hz | Dauer / Ende |
| --- | --- | --- | --- | --- |
| v2-670 + Filter | 0,73 | 5,6 Hz | 0,33 | 13,7 s, Not-Aus |
| v4-550 | 0,73 | 8 / 9,7 Hz | 0,36 | 2,4 s, Kippen (Torque frei) |
| v8-895 | 0,61 | 6,2 / 6,8 Hz | 0,26 | 8,5 s, Not-Aus |

- **Nutzer:** „das linke Bein war ziemlich ruhig, das rechte am Zittern". Log je Bein: das schnelle Hin-und-Her ist
  links und rechts gleich (Rohaktion je 0,61 über 5 Hz, Gelenkbewegung von Schritt zu Schritt ~1,7–1,9° Streuung
  auf beiden Seiten). Unterschied ist die langsame Bewegung: links Hüfte-Pitch 70° Zielbereich (rechts 43°) — das
  linke Bein machte große, langsame Schwünge, über die das Zittern kaum auffällt; das rechte bewegte sich weniger,
  dort dominiert das Zittern das Bild. Bei v2 und v4 war das Zittern ebenfalls seitengleich.
- **Bodentest auf der Yoga-Matte** (Nutzerentscheidung, Seil, Not-Aus; vx 0,11): Nutzer: **„läuft nicht"**.
  Abbruch nach **3,4 s**, „tilt 61° > 55°", Torque frei. Schon nach 0,4 s 22–43° Neigung, der Roboter schaukelt
  stark (Gyro bis 135 °/s), die Neigung springt zwischen 7° und 82° (Seil fängt ab, Stöße verfälschen das
  Beschleunigungssignal). Beine: große, schnelle Ausschläge (Hüfte links bis −35°, Knöchel bis −38°), gemessene Gelenke
  0,25 über 5 Hz. Die Matte (Füße sinken ein) weicht vom Training auf hartem Boden ab.
- **Lehre:** Ein Checkpoint, der in der Sim kaum vorwärts kommt (Tracking 0,23) und 1/16 stürzt, steht auf dem
  echten Roboter keine 4 s. Für den nächsten Bodentest: Sim-Gate ohne Sturz und mit Tracking ≥ 0,6, harter Boden.

### `servo_ctrl_v8` — Ende (28.10. 21:03)
- Wächter-Stopp „tracking collapsed": nach der Schonfrist zweimal Tracking < 0,3 (895: 0,23; 935: 0,30 knapp darunter; dort 36 % echte Schritte, 3,2 Schwünge/s, > 5 Hz 0,24).
  Bester Checkpoint nach Score: 650 (noch fast ohne echte Schritte).
- **Ergebnis:** Teilerfolg. Die dichte Schwung-Belohnung baut echte Schritte auf (0 → 37 %), halbiert die
  Hüpfrate (6,7 → 3,4/s) und senkt das Zittern auf den tiefsten Wert (0,23), aber das Vorwärtskommen geht dabei
  verloren.

### `servo_ctrl_v9` — Konzept v7: langsam und stetig (gestartet 28.10. ~21:20, ab v8 935)
- **Nutzer-Korrektur** auf meinen Vorschlag „stärkere Tempo-Belohnung": „Nein, langsam gehen ist nicht schlimm,
  hauptsache wir kommen kontrolliert und stetig vorwärts."
- **Entdeckung beim Umbau:** Die Tempo-Belohnung ist exp(−Fehler² / Skala) mit **quadriertem** Fehler. Mit Skala 0,12
  brachte Stillstehen bei 0,11 m/s Soll noch 90 % der Belohnung (bei 0,045 m/s wären es 98 %) — einer der Gründe,
  warum das Tempo in v3 und v8 so leicht wegbrach. Neu: Skala 0,002 (Stillstehen ~37 %, halbes Tempo ~78 %).
- **Neu gegenüber v8:** Soll 0,03–0,06 m/s (war 0,08–0,14), volle Schrittlängen-Belohnung bei 4 cm (war 8 cm),
  Gangtakt 1,0–1,25 Hz (war 1,0–1,5). Dichte Schwung-Belohnung bleibt. Start `sim/tools/launch_servo_ctrl9.sh`, GPU 1.
- **Kriterium für den nächsten Bodentest:** im Sim-Gate keine Stürze, Tracking ≥ 0,6 (vom langsamen Soll), echte
  Schritte, harter Boden.
- **Verlauf:**

  | Schritt | Stürze | Tracking | > 5 Hz | Schwünge/s/Fuß | echte Schritte |
  | --- | --- | --- | --- | --- | --- |
  | 935 | 1 | 0,40 | 0,24 | 3,2 | 35 % |
  | 995 | 6 | 0,05 | 0,22 | 2,7 | 52 % |
  | 1035 | 6 | 0,11 | 0,21 | 2,3 | 66 % |
  | 1080 | 6 | −0,46 | 0,21 | 2,2 | 69 % |
  | 1120 | 2 | 0,30 | 0,21 | 2,1 | 78 % |
  | 1165 | 2 | −0,22 | 0,22 | 1,9 | 88 % |
  | 1210 | 2 | 0,00 | 0,21 | 2,0 | 82 % |
  | 1250 | 1 | −0,14 | 0,23 | 1,9 | **91 %** |
- **Ergebnis (28.10. 23:57):** Wächter-Stopp „tracking collapsed" bei 1250. **Highlight und Tief zugleich:**
  91 % echte Schritte, ~2 Schwünge pro Fuß und Sekunde (≈ ein Schritt je Gangtakt), Zittern auf dem tiefsten Stand
  (0,21) — aber **Treten auf der Stelle**, Tracking um 0, teils rückwärts.
- **Video-Check 1165** (10 Bilder/s): ein Bein deutlich angehoben und gebeugt, während das andere trägt, Oberkörper
  verlagert sich seitlich, abwechselnd links/rechts — sichtbares Marschieren auf der Stelle, teils mit Drehung.
  Zeitlupe: `servo_ctrl_v9/videos/servo_ctrl_v9_step01165_feet_slowmo4x.mp4`.
- **Lehre:** Schritt-Struktur und Vortrieb sind zwei getrennte Probleme. Die Policy kann jetzt treten; vorwärts zu
  setzen hat sie nicht gelernt, obwohl Stillstehen jetzt teuer ist (Skala 0,002).

### Tempo-Lehrplan `servo_ctrl_v10` → `v11` → `v12` (Kette `zbot-chain-speed`, gestartet 29.10. 06:41)
- **Nutzer:** „ja, geh das an" (Vorschlag: vom Marschieren auf der Stelle aus das Soll-Tempo schrittweise anheben).
  Live-Viewer mit v9 1250 gezeigt.
- Es gibt keinen Lehrplan nach Trainingsfortschritt (der vorhandene hängt an der Episodenlänge) → Stufen als Kette
  (`sim/tools/train_chain.py speed`), neuer Wert `speed_zero_prob` (Anteil Soll 0 = Marschieren auf der Stelle;
  der Pi erlaubt dann auch vx 0):

  | Stufe | Soll m/s | Soll 0 | volle Schrittlänge | Tempo-Skala | Start |
  | --- | --- | --- | --- | --- | --- |
  | v10 | 0,01–0,03 | 30 % | 2 cm | 0,0004 | v9 1250 |
  | v11 | 0,02–0,045 | 20 % | 3 cm | 0,001 | bester v10 |
  | v12 | 0,03–0,06 | 10 % | 4 cm | 0,002 | bester v11 |
- Weiter, sobald zwei Bewertungen in Folge sturzfrei mit Tracking ≥ 0,6 und ≥ 50 % echten Schritten — oder wenn der
  Wächter die Stufe beendet; bei Tracking-Einbruch hält die Kette an.
- **Panne beim Start:** die Kette gab dem Startskript eine leere Umgebung ohne `XDG_RUNTIME_DIR` → systemd-run
  „Failed to connect to bus", v10 lief nicht los (nur `launch.sh` angelegt). Behoben (volle Umgebung), neu gestartet.
- **v10 (alte Füße):** Stagnation bei 1595 (09:38), Kette hielt an („kein Checkpoint ohne Sturz mit ≥ 50 % Schritten").

  | Schritt | Stürze | Tracking* | echte Schritte |
  | --- | --- | --- | --- |
  | 1250 | 1 | −1,65 | 86 % |
  | 1330 | 1 | 1,13 | 91 % |
  | 1460 | 2 | 3,15 | 93 % |
  | 1595 | 2 | 0,36 | 92 % |

  *Mit 30 % Soll 0 wird der mittlere Sollwert winzig, das Verhältnis springt (0,03 m/s ergeben schon 2–3).
  Kern: **echte Schritte und langsam vorwärts** — erstmals beides zusammen —, aber 1–3 Stürze in 16.

### Die Füße — Nutzerbeobachtung 29.10.
- **Nutzer:** „der Fußkontakt sieht in MuJoCo sehr unrealistisch aus … in der Policy sind sie am Boden großteils nicht
  parallel zum Boden (angewinkelt). das würde zu einem Kippen des Roboters führen … kann es sein, dass die Füße zu stark
  vereinfacht sind?" — und: „der echte Fuß hat eine Fase".
- **Gemessen:** v9 1250: Fußneigung bei Bodenkontakt im Median 9°, 82 % der Kontaktzeit > 5°; v10: 11,6°, 87 %.
  Die Policies stehen auf den Kanten des Kollisionsquaders.
- **Modell:** Kollision war ein Quader 10 × 5,8 cm, unten flach. Echte Sohle (CAD): nur ~1,7 cm (links) bzw. ~1,25 cm
  (rechts) flach, beidseits eine ~1,2 cm breite Fase mit 14–16° (~3,5 mm hoch). Seitliche Auflage im Modell also
  mehr als dreimal zu breit. Kontaktphysik selbst unauffällig (nur Fuß–Boden-Paare, condim 3, keine Rollreibung).
- **Änderung:** `build_model_cad.py` erzeugt jetzt pro Fuß drei Kollisionsquader (flacher Streifen + zwei geneigte
  Fasen), die Kontaktbeobachtung zählt alle drei. Beim Neubau kamen zwei veraltete Stellen mit: Schulter-Pitch hat
  jetzt den echten Bereich (vorher nur in eine Richtung), Rucksack 0,5 g leichter. Stand-Check in der Center-Pose
  unverändert (17,2° Neigung, stabil). Gate misst jetzt `foot_tilt_median_deg` und `foot_tilt_over5_share`.
- **Neue Strafe** `foot_flat_penalty` (Neigung in rad je Fuß am Boden), Skala −8 ≈ ¼ der Tracking-Belohnung bei 10°.

### Tempo-Lehrplan mit Fasen-Füßen `servo_ctrl_v13` → `v14` → `v15` (Kette `zbot-chain-speed2`, gestartet 29.10. 18:33)
- Wie v10–v12, zusätzlich `foot_flat_penalty=-8` und das neue Fußmodell; Start bei v10 1330 (fewest falls).
- Kette nimmt jetzt den schrittreichen Checkpoint mit den wenigsten Stürzen, wenn keiner sturzfrei ist.
- **Erste Bewertung (Schritt 1331 = v10 1330 auf den neuen Füßen): 16 von 16 Läufen stürzen.** Dieselbe Policy, die
  auf dem breiten Quader 1 von 16 Mal fiel, steht auf der echten Sohlenform keinen Lauf durch. **Wendepunkt:** die
  Policies haben sich auf eine seitliche Abstützung verlassen, die der echte Fuß nicht hat — eine plausible Erklärung,
  warum jede Policy auf der Hardware nach Sekunden umfiel. Nutzerbeobachtung damit bestätigt.
- **Nutzer-Präzisierung:** gemeint war das Anwinkeln über den Fußmotor (Spitze/Ferse = Pitch), nicht das seitliche
  Kippen. Messung v9: Pitch −14…+15° (p10–p90), Roll nur −7…+7° — Pitch ist der größere Anteil. Die
  `foot_flat_penalty` bestraft die Gesamtneigung, also vor allem diesen Pitch; die Fase (Roll) war ein zweiter,
  unabhängiger Modellfehler.
- **Tempo-Problem:** drei Quader pro Fuß → 60 statt 12 Kontakt-Slots, MJX-Schritt 25 statt 9 ms (1024 Envs), v13 lief
  mit ~0,5 Iterationen/min (v10: ~1,9). Fasen jetzt als dünne Kapsel (r 1 mm) auf der äußeren Fasenkante — dieselbe
  Kippkante, 32 Kontakt-Slots, 15,7 ms. v13 nach 30 Iterationen verworfen (`scratchpad/servo_ctrl_v13_boxchamfers`)
  und mit dem Kapselmodell neu gestartet (~19:50).
- **Verlauf (Kapselmodell):**

  | Schritt | Stürze | Tracking | echte Schritte | Fußneigung Median | > 5° |
  | --- | --- | --- | --- | --- | --- |
  | 1331 | 16 | – | – | – | – |
  | 1375 | 8 | 0,64 | 78 % | 10,1° | 84 % |
  | 1415 | 5 | −3,68 | 85 % | 9,1° | 81 % |
  | 1455 | 2 | −2,50 | 79 % | 8,1° | 76 % |
  | 1495 | 11 | −2,90 | – | – | – |
  | 1535 | 4 | −1,65* | 85 % | 8,9° | – |

  *neues Maß. **Tracking-Maß korrigiert** (`hardware_gate.py`): nur Zeitschritte mit Vorwärts-Soll zählen, Drift bei
  Soll 0 getrennt (`zero_cmd_drift_mps`) — das alte Episodenverhältnis sprang mit 30 % Soll 0 auf ±3.
- **Ergebnis (29.10. 23:33):** Wächter-Stopp „tracking collapsed" bei 1535, Kette `speed2` angehalten. Auch mit
  korrigiertem Maß echt: **~3 cm/s rückwärts bei Vorwärts-Soll**, Stürze schwanken 2–11 von 16, Füße etwas flacher
  (10 → 8–9°). Vermutung: auf der schmalen echten Sohle fängt sich die Policy durch Rückwärtstreten (Center-Pose
  vorgebeugt). Vorschlag an den Nutzer: Stufe 0 „nur auf der Stelle" bis sturzfrei, dann Tempo-Lehrplan.

### Stufe 0 + Tempo-Lehrplan `servo_ctrl_v16` → `v17` → `v18` → `v19` (Kette `zbot-chain-speed3`, gestartet 30.10. 00:05)
- **Nutzer:** „go".
- v16 = Stufe 0: nur Soll 0 (auf der Stelle treten), keine Schrittlängen-Belohnung, Tempo-Skala 0,0004 (bestraft
  Drift), `foot_flat_penalty=-8`, Kapsel-Füße. Start v13 1455 (2 Stürze). Weiter, sobald zwei Bewertungen in Folge
  sturzfrei mit ≥ 50 % echten Schritten — oder der Wächter v16 beendet.
- v17–v19 wie v13–v15 (0,01–0,03 / 0,02–0,045 / 0,03–0,06 m/s), Schrittlängen-Belohnung wieder an.
- **Panne:** erster Score „nan" — ohne Vorwärts-Soll ist das Tracking-Maß undefiniert und vergiftete den Score (und
  damit die Stagnationsprüfung). Gate lässt das Tracking-Kriterium jetzt weg, wenn es kein Vorwärts-Soll gibt;
  Eintrag nachgerechnet, Wächter neu gestartet.
- **Ausgangswert (v13 1455 nur mit Soll 0):** 9 von 16 Stürzen, 79 % echte Schritte, Fußneigung 8,4°, **Drift
  −3,9 cm/s** — die Policy läuft auch ohne Auftrag rückwärts. Genau das soll Stufe 0 abtrainieren.
- **Verlauf:** Drift −3,9 → −5,8 → −7,7 cm/s (1455/1500/1540), Stürze 9/4/9 — Stufe 0 machte es schlimmer.
  Gegenprobe: dieselbe Policy (v16 1540) auf dem **alten** Fußmodell läuft ebenfalls rückwärts (−4,9 cm/s median,
  2 statt 6 Stürze) → **gelernt, nicht Physik**; die neuen Füße erhöhen nur die Stürze. Gierwinkel geprüft: echtes
  Rückwärtsgehen (28–47 cm in 5 s), keine Drehung.
- **Ursache:** in der Belohnungsliste fehlte das Tempo praktisch ganz — exp(−Fehler²/0,0004) ist ab ~2 cm/s Abweichung
  flach bei 0, ohne Gefälle. Die Policy merkte das Rückwärtslaufen nicht und optimierte nur Schwung (+0,020) und
  Fußhaltung (−0,006). **Lehre:** eine strenge Gauß-Belohnung ist eine Klippe, kein Hang.
- v16 endete 04:37 wegen Stagnation (1700), die Kette übergab an **v17** (ab v16 1500), der ebenfalls rückwärts lief
  (Tracking −1,5 … −4,4, 1–9 Stürze) und GPU 1 belegte → v17 von Hand gestoppt (07:50).

### `servo_ctrl_v20` → `v21` → `v22` → `v23` — Tempo mit linearem Fehler (Kette `zbot-chain-speed4`, 30.10. ~07:55)
- Tempo-Belohnung jetzt `track_norm=l1`: exp(−|Fehler|/Skala) — spitz am Soll, überall ein Gefälle (Skala 0,02:
  auf Soll 1,0; 2 cm/s daneben 0,37; 5 cm/s rückwärts 0,08).
- Start **v13 1375** (letzter Checkpoint auf den echten Füßen, der vorwärts ging: Tracking 0,64, 8 Stürze).
  v20 = Stufe 0 (Soll 0, Skala 0,02), v21–v23 = 0,01–0,03 / 0,02–0,045 / 0,03–0,06 m/s (Skala 0,02 / 0,03 / 0,045).
- Fehlstart: v20 brach mit „cuSolver internal error" ab, weil v17 noch GPU 1 belegte; nach dem Stopp von v17 per
  `launch.sh` neu gestartet.
- **Nutzer:** „warum soll erst v20 mit Stillstand trainiert werden, wenn checkpoint v13 noch geradeaus läuft?" —
  berechtigt: Stufe 0 war mit der widerlegten Balance-Vermutung begründet; die erste Tempo-Stufe enthält 30 % Soll 0
  ohnehin. v20 nach wenigen Minuten gestoppt („okay").

### `servo_ctrl_v24` → `v25` → `v26` — Tempo-Lehrplan ohne Stufe 0 (Kette `zbot-chain-speed5`, 30.10. 08:09)
- v24 ab v13 1375: 0,01–0,03 m/s, 30 % Soll 0, `track_norm=l1` Skala 0,02, Schrittlänge 15, `foot_flat_penalty=-8`,
  Kapsel-Füße. v25/v26 wie v22/v23 (0,02–0,045 / 0,03–0,06 m/s, Skala 0,03 / 0,045).
- **Nutzer:** „Warum Sollwert 0?" — Anhalten/auf der Stelle treten erhalten (Pi erlaubt vx 0 nur dann), Drift
  bestrafen, Wechsel Stehen ↔ Gehen üben; Anteil sinkt in den späteren Stufen.
- **Ergebnis:** auch v24 läuft rückwärts — und schon der Start v13 1375 misst mit dem neuen Maß −0,51 („läuft noch
  vorwärts" war ein Artefakt des alten Maßes). Verlauf: Tracking −0,51 → −2,8, Drift −3,6 → −5,9 cm/s, Stürze 2–10,
  86 % echte Schritte, Fußneigung 8–10°. Belohnungen pro Schritt: **Schwung +0,020, Tempo +0,0005** (40×),
  Fußstrafe −0,0065. Die Policy optimiert das Schwingen; die Richtung ist ihr egal. Live-Viewer: v24 1540.
  Gestoppt 11:57.

### `servo_ctrl_v27` → `v28` → `v29` — Gewichte umverteilt (Kette `zbot-chain-speed6`, 30.10. 11:59)
- **Nutzer:** „vergiss nicht, dass eben aufgetreten werden soll" → Fußstrafe mit verstärkt.
- Tempo 10 → **30**, Schwung 6 → **2** (die Schritte sind da), Fußstrafe −8 → **−16**. Sonst wie v24–v26. Start v24 1540
  (2 Stürze, 86 % echte Schritte).
- **Ergebnis:** schlimmer — Schritt 1590: Tracking −4,2, Drift **−10,6 cm/s**, 8 Stürze, 70 % echte Schritte. Gegenprobe
  der Tempo-Belohnung an den Rollouts: Vorzeichen und Frame stimmen (Sensor ↔ Positionen Korrelation 0,98, Belohnung
  steigt mit Vorwärtstempo). Die Policy kann offenbar nicht vorwärts gehen, ohne zu stürzen. Hauptverdacht: die
  Fußstrafe (kam mit v13 dazu, genau als das Rückwärtslaufen begann; v10 ohne sie lief vorwärts).

### `servo_ctrl_v30` — Diagnose: ohne Fußstrafe (30.10. ~13:20)
- **Nutzer:** „ja. wenn das nicht klappt soll noch Mal komplett von Null mit sinnvollen Rewards und Punishments
  gerechnet werden."
- Wie v27, aber `foot_flat_penalty=0`, ab v24 1540, 120 Iterationen. Läuft er vorwärts → Fußstrafe ist die Ursache,
  dann Strafe mit **Totzone** (neu: `foot_flat_deadzone_deg`, z. B. 5°: leichtes Abrollen frei, Kantenstand bestraft).
- Fallback vorbereitet: `sim/tools/launch_servo_scratch2.sh` — von null, mit allen Lehren (Fasen-Füße, Aktionsverlauf,
  zufällige Totzeit, 0,03–0,06 m/s mit 20 % Soll 0, Tempo 30 mit linearem Fehler, kleine Schritt-Belohnungen,
  Fußstrafe −8 mit 5° Totzone, keine Extra-Zitterstrafen).
- **Ergebnis:** ohne Fußstrafe weniger Rückwärtsdrift (Tracking −2,64 → −1,96 → −1,35, Drift −4,6 → −3,2 → −3,4 cm/s)
  bei gleich wenigen Stürzen (2), Fußneigung nur leicht höher (8,3 → 9,0°) — die strenge Fußstrafe bremst das
  Vorwärtsgehen. Nach 1625 beendet.
- **Nutzer:** „aber was bringt diese Info? Das Fußtracking brauchen wir, da die Policy sonst auf dem realen Roboter
  nicht funktioniert" — die Strafe bleibt, nur ihre Form ändert sich (Totzone). Nutzer entschied: Weg 1 (weiter ab
  v30). Ein Befehl lief trotz Unterbrechung an: `servo_scratch2` startete kurz und wurde wieder gestoppt.

### `servo_ctrl_v31` — Fußstrafe mit Totzone (30.10. ~15:10, ab v30 1625)
- Wie v30 (Tempo 30 mit linearem Fehler, Schwung 2, 0,01–0,03 m/s, 30 % Soll 0), dazu `foot_flat_penalty=-8`,
  `foot_flat_deadzone_deg=5`: Abrollen bis 5° straffrei, Kantenstand (10–15°) bestraft.
- **Verlauf:**

  | Schritt | Stürze | Tracking | Drift Soll 0 | echte Schritte | Fußneigung | > 5° |
  | --- | --- | --- | --- | --- | --- | --- |
  | 1630 | 2 | −2,67 | −6,7 cm/s | 83 % | 7,8° | 73 % |
  | 1670 | 4 | −3,21 | −6,1 cm/s | 82 % | 7,5° | 72 % |
  | 1710 | 5 | −3,99 | −8,2 cm/s | 76 % | 7,4° | 71 % |
  | 1755 | 5 | −4,10 | −5,2 cm/s | 77 % | 7,9° | 74 % |
- **Ergebnis:** mit dem Nutzer vereinbart („ja"): keine Besserung bis 1750 → Neustart von null. Das Rückwärtslaufen
  steckt in der ganzen Abstammung v13–v31. **Lehre:** ein einmal gelerntes Fehlverhalten wird man durch Umgewichten
  nicht wieder los — seit v13 sechs Läufe Feinabstimmung ohne Erfolg.

### `servo_scratch2` — von null mit allen Lehren (gestartet 30.10. ~17:52)
- `sim/tools/launch_servo_scratch2.sh`: Fasen-Füße, Aktionsverlauf 4, zufällige Totzeit, 0,03–0,06 m/s mit 20 % Soll 0,
  Gangtakt 1,0–1,25 Hz, Tempo 30 mit linearem Fehler (Skala 0,03), dichte Schwung-Belohnung 2, Schrittlänge 15 (nur
  echte Schritte), Kontaktwechsel −1, Takt 1, Fußstrafe −8 mit 5° Totzone, keine Extra-Zitterstrafen. Wächter: Video
  alle 100, Stagnation und Tracking-Einbruch erst ab 800 Iterationen. Bis 4000 Iterationen.
- Erwartung: ~700+ Iterationen bis zum Laufen (v2/v4 von null: ~600–670), bei ~1 Iteration/min mindestens 12 h.
- **Verlauf (Stand 31.10. 00:10):**

  | Schritt | Stürze | Tracking | Drift Soll 0 | echte Schritte | Fußneigung | > 5° |
  | --- | --- | --- | --- | --- | --- | --- |
  | 45 / 90 | 16 | – | – | – | – | – |
  | 135 | 14 | 1,49 | +2,8 cm/s | 60 % | 4,5° | 46 % |
  | 215 | 10 | 0,89 | 0 | 76 % | 5,0° | 50 % |
  | 255 | 4 | 1,24 | +5,0 cm/s | 73 % | 4,3° | 41 % |
  | 335 | 2 | 1,49 | +4,9 cm/s | 74 % | 4,6° | 43 % |

  **Highlight:** zum ersten Mal seit v10 **vorwärts** (Tracking > 1, also eher zu schnell), dazu echte Schritte und
  Füße im Median unter der 5°-Totzone — schon nach 335 Iterationen von null. Noch offen: Stürze (2/16) und Vorwärtsdrift
  bei Soll 0.
- **Nutzer (30.10. abends):** „Die Erzeugung der Videos ist nicht mehr nötig. Wichtiger ist, dass alles autonom ohne
  menschlichen Eingriff läuft und überwacht wird." → Wächter läuft seit 31.10. 00:15 mit `--video-every 0`.
- **Abgebrochen bei 335 (31.10. ~00:30): rechtes Hüft-Roll im Modell spiegelverkehrt.** `hardware/model_invert.json`
  bekam am 29.10. 22:37 (WebUI) `"right_hip_roll": true`; der Nutzer bestätigte: „Ja, ist richtig". Alle Policies davor
  hatten die alte, falsche Achse. Lauf nach `servo_scratch2_oldaxis` verschoben. **Wendepunkt / Filmnotiz:** ein
  vertauschtes Gelenk-Vorzeichen in jeder bisher getesteten Policy.

### `servo_scratch2` (neu) und `servo_tpu1` — zwei Läufe von null mit korrigierter Achse (31.10. ~00:40)
- **Nutzer (30.10. abends):** „starte auf GPU 0 das Training einer Policy mit den TPU Schuhen."
- Modell `sim/assets/zbot-cad-tpu` (`build_model_cad.py --sole tpu`): TPU-Überschuh aus `hardware/foot_sole`
  — flache Sohle über die volle Fußbreite (10,2 × 5,6 cm), 3,5 mm tiefer, +28 g je Fuß, Reibung 1,1. Stand-Check stabil
  (Basis 0,320 statt 0,316 m).
- Beide mit `launch_servo_scratch2.sh` (jetzt mit RUN/GPU/ASSETS/EVAL_GPU): `servo_scratch2` GPU 1 gedruckte Sohle,
  `servo_tpu1` GPU 0 TPU-Schuhe. Wächter bewerten auf der CPU (beide GPUs trainieren) und nehmen jetzt das Modell
  des jeweiligen Laufs (vorher fest `zbot-cad`).
- **Speicher-Panne (31.10. morgens):** Live-Viewer neben zwei Trainings + CPU-Bewertung → OOM-Kills der Wächter,
  Fehlbewertungen mit Score 0 im Verlauf. Wächter wiederholt fehlgeschlagene Bewertungen jetzt, statt sie zu werten;
  Videos nur noch als Datei unter der Bewertungs-Sperre. **Nutzer:** „ich brauche trotzdem das Video".
- **`servo_tpu1`, Ende 08:05 (Stagnation):**

  | Schritt | Stürze | Tracking | Drift Soll 0 | echte Schritte | Fußneigung | > 5° |
  | --- | --- | --- | --- | --- | --- | --- |
  | 85 | 15 | 1,90 | +6,6 cm/s | 72 % | 5,4° | 53 % |
  | 205 | 4 | 1,11 | +8,2 cm/s | 86 % | 4,5° | 42 % |
  | 445 | 2 | 1,37 | +2,6 cm/s | 81 % | 4,3° | 41 % |
  | 770 | 2 | 1,47 | +5,3 cm/s | 89 % | 3,8° | 32 % |
  | 865 | 3 | 1,62 | +6,6 cm/s | 94 % | 4,0° | 35 % |

  **Highlight:** von null in unter 8 h echte Schritte, vorwärts, flache Füße — erste Policy, die alles zugleich kann.
  Exportiert: `sim/policies/servo_tpu1_step770` (Pi lädt sie; vx 0,03–0,06 m/s oder 0).
- **Neuer Befund:** sie **ignoriert den Sollwert**: 6,6 cm/s bei Soll 0, 6,8–7,8 cm/s bei Soll 3–5 cm/s. Gründe:
  (1) Tempo-Belohnung bewertet die Momentangeschwindigkeit; der Körper pendelt pro Schritt (vx ±10, vy ±15 cm/s bei
  Mittel 7 / 0,4), der Kern liest 0,036 egal wie gut das Mittel passt (0,8-s-Mittel: 0,147 und mit Unterschied zwischen
  den Sollwerten); (2) Schrittlänge und `naive_velocity` zahlen Vorwärtsgehen auch bei Soll 0. Der Gate-Score sah das
  nicht (kein Tempo-Limit nach oben, keine Drift).

### `servo_tpu2` — Sollwert befolgen (31.10. ~08:25, GPU 0, ab `servo_tpu1` 770)
- **Nutzer:** „mach das" (bester Checkpoint exportieren, GPU 0 weiter auslasten).
- Tempo über 0,8-s-Mittel (`track_window_s=0.8`), Schrittlänge nur bei Vorwärts-Soll (`stride_needs_command`),
  `naive_velocity_scale=0`. Sonst wie `servo_tpu1`.
- Gate neu: Tracking höchstens 1,3, |Drift bei Soll 0| ≤ 2 cm/s, höchstens 30 % Kontaktzeit > 5° Fußneigung. Wächter
  bewertet beim Start alle Einträge mit den aktuellen Kriterien neu. `servo_scratch2` läuft mit den alten Belohnungen
  weiter (Wächter neu gestartet).
- **Nutzer:** „ein TPU Schuh wiegt 22 Gramm" (Modell hatte 28 g geschätzt). Modell korrigiert (Roboter −12 g); `servo_tpu2`
  läuft ohne Neustart weiter und trainiert im Speicher mit 28 g, die Bewertungen rechnen ab jetzt mit 22 g.
- **Abgebrochen bei 815 (31.10. ~09:05): auch `left_hip_roll` war gespiegelt** (Nutzer: „der left-hip-roll Winkel ist
  auch invertiert"). Letzte Bewertung: Tracking 0,54 (vorher 1,66), Drift +1,8 cm/s (vorher +5,8), aber 6 Stürze, echte
  Schritte 86 %, > 5° 35 % — die Tempo-Korrektur wirkt.

### `servo_scratch3` und `servo_tpu3` — beide Achsen korrekt, von null (31.10. ~09:10)
- `model_invert.json` jetzt mit beiden Hüft-Roll-Gelenken. GPU 1: gedruckte Sohle, GPU 0: TPU-Schuhe (22 g), beide
  mit Tempo über 0,8-s-Mittel, Schrittlänge nur bei Vorwärts-Soll, ohne `naive_velocity`.
- **Einbein-Demo** (Nutzer: „auch die Demo auf einem Bein muss entsprechend angepasst werden"): erzeugt am 30.10. mit
  beiden Achsen falsch, daher beide `hip_roll`-Winkel negiert (Plan + `demos/one_leg_stand.json`); Physikprüfung auf dem
  korrigierten Modell. Weiterhin nur in der Sim geprüft, Pi-Kopie noch alt.
- **Nutzerfrage:** „können die Policies trotzdem verwendet werden, indem die Servowinkel entsprechend invertiert
  werden?" — Ja: Das Vorzeichen ist nur eine Bezeichnung, die Physik im Modell war dieselbe. Mit q = −s für die betroffenen Gelenke
  (Position, Geschwindigkeit, Ziel) macht der Roboter dieselbe Bewegung wie die Sim. Für v1–v31 beide Hüft-Roll, für
  `servo_tpu1`/`tpu2`/`scratch2` nur links. Die Hardware-Tests vom 28.10. liefen ohne diese Korrektur.
- **Umgesetzt** („ja"): `joint_sign_flip` in `policy_meta.json` (`export_policy.py --flip-joints`), Pi negiert Position,
  Geschwindigkeit und Aktion dieser Gelenke; Grenzen, Rampe, Servo-Befehle bleiben in Servo-Winkeln. Alle exportierten
  Policies markiert. Noch nicht aktiv auf dem Pi (Deploy mit Dienst-Neustart offen).
- **Nutzer:** testet die Einbein-Demo. Sie lag noch gar nicht auf dem Pi → korrigierte Fassung kopiert, ohne Dienst-Neustart.
- **Test am Roboter, Nutzer:** „keine einzige der 4 Posen aus der one_leg demo ist in Balance... Das Modell scheint
  grundsätzlich einen falschen CoM zu haben." Gewogen: **2624 g mit TPU-Schuhen** (Modell 2671 g, +1,8 %).
  Einordnung: Laut Modell liegt der Schwerpunkt in den Einbein-Posen 3/4 bei +30 mm im rechten Fuß, der TPU-Schuh endet bei ca. +7 mm,
  die gedruckte Sohle bei −13 mm; die Demo braucht die breite Sohle (+60 mm). Das Scheitern ist also auch mit korrektem
  CoM zu erwarten, schließt einen CoM-Fehler aber nicht aus: seitlich nie gemessen, Armlast im Sag-Test ungeklärt.
  Vorschlag: CoM mit zwei Waagen messen (Center-Pose, TPU; Modell: L/R 50,1/49,9 %, Spitze/Ferse 36/64 %). Offen.
- **Highlight 31.10. ~09:40, Nutzer:** „one_leg_left und one_leg_right demo balancieren echten Roboter auf einem Bein."
  Per Teach-in, Hüft-Yaw −40,7° bzw. +38,7°. Modell mit diesen Winkeln und flachem Fuß: Schwerpunkt **innerhalb** der TPU-Sohle, 20 mm (links)
  bzw. 13 mm (rechts) vor der Innenkante, längs 10–18 mm hinter der Sohlenmitte. Das widerlegt einen groben CoM-Fehler;
  seitlich bleibt grob −20 … +13 mm Spielraum. Live-Prüfung rechts: Fuß laut IMU + Gelenkwinkeln 12,9° gegen die Schwerkraft geneigt,
  CoM rechnerisch 42 mm neben der Sohle — nicht belastbar: IMU misst 1081 mg statt 1000 mg, und 1° entspricht ~5 mm. Vor der Auswertung
  IMU im Zweibeinstand kalibrieren. Offen.
- **Drei Lesungen** (`sim/tools/com_live.py`, `com_calib.py`, `com_readings_20261031/`), Korrektur aus dem Zweibeinstand 6,2°:
  rechts Fuß rechnerisch −11,8° längs / −8,3° quer, CoM 28 mm innen neben der Sohle; links +6,3° / +4,5°, CoM 6 mm innen
  neben der Sohle. **Beide nach innen — kein fester seitlicher CoM-Versatz im Körper kann das erklären** (rechts müsste er
  nach rechts, links nach links). Eher: der Körper neigt sich real um rund 4–8° weniger als die Encoder sagen
  (Biegung/Spiel, weicher TPU, IMU). Noch nicht getrennt. Dazu: Sohlen in der Center-Pose laut Modell 3,9° gegeneinander verdreht.
  Modell nicht geändert. Längs keine Aussage. Vorschlag: Frontfotos der Einbein-Posen.
- **Nutzer:** TPU-Schuhe an, „sohle lag flach auf" (also keine echte Fußneigung); „ich musste one_leg_right anpassen":
  Hüft-Pitch −10,6 → −24,3°, Hüft-Yaw 38,7 → 42,6°.

### Tiefpunkt 31.10.: `servo_tpu3` / `servo_scratch3` lernen zu fallen
- Von null mit Tempo über 0,8-s-Mittel, Schrittlänge nur bei Soll und ohne `naive_velocity`: Episoden 0,86 → **0,45 s**,
  16/16 Stürze bis Schritt 330, Belohnung pro Schritt steigt trotzdem. **Lehre:** diese Belohnungen funktionieren
  nur auf einer Policy, die schon läuft (`servo_tpu2`), von null gibt es keinen Anreiz zu überleben. 3 h unbemerkt, weil
  meine Überwachung nur Abbrüche meldete. Wächter stoppt jetzt nach 6 Bewertungen mit nur Stürzen (ab 240 Iterationen).
- **`servo_tpu4`** (GPU 0, 12:30): weiter ab `servo_tpu2` 815, Modell `zbot-cad-tpu-leftold` (linke Achse alt, 22 g); Export
  mit `--flip-joints left_hip_roll`. **`servo_scratch4`** (GPU 1): von null, korrekte Achsen, Startbelohnungen wie
  `servo_tpu1`; Kette `zbot-chain-boot` wechselt bei ≤ 4 Stürzen und ≥ 50 % echten Schritten (zweimal) oder Wächter-Ende
  auf `servo_scratch5` mit den Tempo-Korrekturen.
- **`servo_tpu4` steht auf der Stelle:** Drift bei Soll 0 weg (−0,2 cm/s), aber Tracking 0,39 → −0,07. Tempo-Kern bei
  gehender vs. tretender Policy: 0,14 vs. 0,15 — er zahlt nichts fürs Gehen. **Nutzer:** „wichtig ist erst Mal, dass der
  Roboter überhaupt vorwärts geht." Neu `forward_progress_reward` (Vorwärtstempo als Anteil des Solls, −1…1, 0 bei
  Soll 0; +0,82 vs. +0,03). **`servo_tpu5`** (GPU 0) ab `servo_tpu1` 770, Gewicht 10; auch in der Kette für `servo_scratch5`.
- **Hardware (Nutzer testet):** `servo_tpu1_step770` auf dem Pi, Dienst neu gestartet, `joint_sign_flip` links aktiv.
- Ergebnis: *folgt.*
- **Hardware 31.10. 13:41–13:51:** `servo_tpu1_step770` nur Trockenlauf (13:41); der Start am Seil wurde vom Pi abgelehnt (HTTP 400, genaue Meldung nicht geloggt, vermutlich Pendeln während der Gyro-Kalibrierung). Der Bodenlauf um 13:51 war laut Log **`cad2_v10_calm2_step850`** (altes Modell ohne Servo-Modell, Hüft-Roll-Flip beidseitig, vx 0,185 m/s, 1,625 Hz, 8,1 s bis E-Stop). Nutzer: "Der Roboter ist das erste Mal nicht direkt umgefallen. Minimal nach vorne hat er sich bewegt und ist dann nach hinten gekippt". Log: ab ~2,5 s dauerhaft etwa 20° nach hinten geneigt, 70 dps Zittern, nach dem Stopp auf dem Rücken; Sollwerte springen 20–25-mal/s um (60 % der Aktion über 5 Hz), Soll bis ±55°, gemessen nur ±20–45°, also das bekannte Zittern. `servo_tpu1_step770` ist damit noch **nicht** real gelaufen.
- **`servo_tpu5` beendet 31.10. 17:20 (Stagnation, Schritt 1190):** höchster Score 0,739 bei 1030; am ausgewogensten 1150 (1/16 Stürze, Tempo 1,16-fach, Drift +6,2 cm/s, 91 % echte Schritte, 36 % Fußneigung > 5°). Der Fortschrittsbonus hat das Laufen ohne Vorgabe nicht abgewöhnt (Drift über den ganzen Lauf 4–6 cm/s), Hardware-Gate nicht bestanden.
- **31.10. ~21:05:** `servo_tpu5_step1150` exportiert (`--flip-joints left_hip_roll`, Assets `zbot-cad-tpu-leftold`) und ohne Dienst-Neustart auf den Pi kopiert (`--skip-service`, Auswahl erscheint in `/policies`). Noch nicht gestartet.
- **Hardware 31.10. ~21:13–21:17, `servo_tpu5_step1150`, TPU-Schuhe, Boden:** Nutzer: "Auf Parkett schafft der Roboter ca. 2 Schritte, die bereits leicht rutschen und fällt dann durch Wegrutschen um. Auf einer Anti-Rutschmatte schafft er keinen einzigen Schritt". Fünf Läufe im Log: einer mit 3,2 s, vier mit 1,2–1,6 s (Sturzabschaltung). Befunde: Kopf-IMU steht real bei 9–13° nach vorn, das Modell bei 17,2°; Betrag real ~1106 mg statt ~1000 mg. Die Reibungs-Randomisierung im Training ändert nur `geom_friction` des Bodens, die Fuß-Kontaktpaare haben feste Reibung 1,1 und bleiben davon unberührt. Sim-Sweep (Reibung, Drehreibung, IMU-Versatz) läuft.
- **Hardware 1.11. 20:23–20:24, `servo_tpu5_step1150`, neue TPU-Schuhe, Kopf leicht nach hinten geknickt, Laminat:** Nutzer: rutscht vor allem, teils 2–3 Schritte. Drei Läufe (0,9 s, 1,3 s, 4,8 s bis E-Stop). Gegenüber den 9 Läufen vom 31.10. keine klare Differenz in den Logs; Kopf, Schuhe und Boden wurden zugleich geändert. In allen 12 Läufen überschreitet die Neigung 25° schon nach 0,3–0,7 s, also in der 1-s-Rampe.
- **1.11. IMU-Rate:** Kopf-Firmware war veraltet (kein `gap`-Feld, 16 Hz, gleich der Augen-Bildrate). Nach `deploy_head.sh --files-only` 47,6 Hz; im Trockenlauf wiederholte Werte 68 → 19 %, Alter im Mittel 31 → 12 ms, maximal 80 → 40 ms. Bodenläufe mit der neuen Firmware stehen aus.
- **1.11. Center-Pose:** 5× Center mit Halten: Gelenke identisch, Neigung 11,95–12,13°; nur das rechte Sprunggelenk bleibt zunächst bei +1,1° hängen und braucht zwei Center. Register der Beinservos: P 32, I 0, Totzone 0. Nach Wiederaufrichten 9,9° bei fast gleichen Gelenken (Leine damals nicht sicher locker, also kein Beleg). Nutzer: rechtes Bein hat durch PETG-Kriechen Spiel; das sieht der Servo-Encoder nicht. Nutzer-Entscheidung: kein I-Anteil, auch nicht als Center-Trim. Stattdessen warnt der Runner ab 1° Abweichung und loggt die Pose vor dem Start. Einmaliges Lösen des Drehmoments im Stand: Roboter knickt komplett ein (rechtes Knie −89,3°, über der Softgrenze −85°).
- **1.11. Reibungstest ohne Kraftmesser (`bench` `friction`):** Roboter steht frei und drückt die Füße langsam auseinander (±6°, 1,25°/s, Sohlen flach); Hüftlast aus Hin- und Rückhub minus Lauf in der Luft. Sim-Kurve (MuJoCo, nur mit No-Slip, im Standardkontakt kriechen die Füße schon bei ca. 0,5 N): 0,12 Nm bei μ 0,2 bis 1,07 Nm bei μ 1,1, darüber flach. Hardware 21:50–22:06, abwechselnd, Füße gleiten sichtbar: Laminat 0,083 / 0,114 / 0,116 Nm, Zeitschrift (Seite blieb liegen) 0,128 / 0,132 / 0,134 Nm. Wiederholbar und getrennt, aber nur ca. 2 Register-Einheiten Abstand. μ ≈ 0,2 ist **unkalibriert**: Kraftmesser-Vergleich und griffiger Boden stehen aus. Temperatur-Ausreißer bis 150 °C als Einzelwerte von Servo 45, Bus-Lesefehler von Servo 41 (beide rechtes Bein).
- **1.11. Fußreibung im Training:** `FloorFrictionRandomizer` skaliert `geom_friction` des Bodens ×0,1–2,0. In MuJoCo geprüft: Bei 0,1 / 1,0 / 2,0 bleibt die Kontaktreibung der Füße 1,1, die `<pair>`-Einträge in `robot.mjcf` übersteuern sie (MJX nicht eigens geprüft). `servo_tpu5` kennt also effektiv nur μ = 1,1.

## Video-Archiv

| Datei (unter `sim/train/zbot_walking_task/`) | Zeigt |
| --- | --- |
| `backpack_*/validation_step*/walk.mp4`, `backpack_v1/render_step*.mp4` | Phase 1: erste Gehversuche auf dem Rucksack-Modell |
| `best/cad_*/walk_nominal_15s.mp4`, `walk_randomized_8s.mp4` | Phase 2: die besten der ersten CAD-Generation |
| `best/cad_v10_calm2_step910/longwalk_nominal/walk.mp4` | Phase 2: Langstrecke |
| `servo_v2_normal/eval_final/walk_v2.mp4` | Phase 6: einzige richtig gehende Policy, aber bang-bang |
| `servo_ctrl_v1/demo_2145.mp4` | Phase 6: Trippeln auf der Stelle, zittrig |
| `servo_ctrl_v2/demo_670.mp4` | Phase 6: stärkstes Zittern |
| `servo_ctrl_v3/videos/servo_ctrl_v3_step*.mp4` | Phase 6: automatisch alle 100 Iterationen |

Für die fünf `cad2_*`-Policies gibt es noch keine Videos im Servo-Modell; sie lassen sich mit `sim/tools/render_policy.sh`
nachrendern (einmal mit altem Modell, einmal mit Servo-Modell = "so sah es in der Sim aus / so wäre es auf der Hardware").

## Filmnotizen: Höhe- und Tiefpunkte

1. **Hoch:** 8.9. — der Roboter läuft in der Sim zum ersten Mal geradeaus (Phase 1).
2. **Tief:** Die ersten CAD-Policies sind wertlos — falsche Massen, IMU an der falschen Stelle (Phase 2).
3. **Hoch:** 23.9. — fünf Policies, alle ohne Sturz in der Sim (Phase 3).
4. **Tief:** 21.10. — auf der echten Hardware fallen alle fünf nach einer Sekunde um.
5. **Tief:** 22.10. — `speed=3000`, das Bein dreht nach innen, das Hüftteil reißt.
6. **Hoch:** 25.10. — Messen statt raten: Bench-Tests liefern das echte Servo-Verhalten; Massen und Schwerpunkt stimmen.
7. **Hoch:** Die alte Policy fällt im neuen Servo-Sim nach einer Sekunde — die Sim bildet die Realität nach.
8. **Tief:** 26.10. — Abstürze, Speicherfehler, Wächter vom OOM-Killer beendet; widersprüchliche Ziele.
9. **Tief:** "Trippeln auf der Stelle, zittrig" (`servo_ctrl_v1`).
10. **Tief:** "Das stärkste Zittern bisher" (`servo_ctrl_v2`) — die Füße vibrieren mit 7 Hz.
11. `servo_ctrl_v3` (Tiefpunkt): ruhiger wirkend, aber Treten auf der Stelle — der Score merkt es nicht.
12. **Wendepunkt:** Die Ursache des Zitterns ist eine Regelschwingung durch die Servo-Totzeit — Frequenz folgt der Totzeit (Tabelle).
13. **Tief:** v5/v6 — dreißigfache Strafe, Zittern unverändert, Laufen schlechter.
14. **Wendepunkt:** Es gibt gar keine Schritte — 0 % Schwünge ≥ 0,2 s seit v2; das Zittern ist die Gangart (Mikro-Hüpfer).
15. *(folgt: `servo_ctrl_v7`, echte Schritte)*
