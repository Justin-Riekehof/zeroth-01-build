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
- **1.11. Nutzer:** „Das ist ja ein fundamentaler Policy-Fehler... beginne sofort das Training einer Policy. Und zwar tatsächlich am besten von vorne." Umgesetzt: `FootFrictionRandomizer` setzt `pair_friction` (μ 0,2–1,2 je Umgebung; in MJX bis in die Kontakte geprüft), ersetzt den wirkungslosen Boden-Randomizer. In den Checkpoints von `servo_tpu1` und `servo_tpu5` steht `domain_randomize: true`, die Randomisierung lief also, nur ohne Wirkung auf die Füße. Start `sim/tools/launch_servo_fric.sh`: `servo_fric1` von null auf `zbot-cad-tpu` mit den Startbelohnungen aus dem Checkpoint von `servo_tpu1` (`naive_velocity_scale` 1,5, Momentantempo, Schrittlänge ohne Soll), weil die Fenster-Belohnungen allein von null das Fallen lehren (`servo_tpu3`); Kette `zbot-chain-friction` wechselt danach auf `servo_fric2`. Noch nicht gestartet.

### `servo_fric1` — von null mit Fußreibung 0,1–1,5 (gestartet 1.11. 22:55, GPU 0)
- **Nutzer:** „Starte ein neues Policy-Training von 0. Nimm dabei alle Erkenntnisse der bisherigen Trainings mit. Es soll Reibung von 0,1 bis 1,5 abgedeckt werden." und „es geht nach wie vor nur ums geradeaus laufen".
- **Start:** `GPU=0 EVAL_GPU=1 sim/tools/launch_servo_fric.sh`, Modell `zbot-cad-tpu` (beide Hüft-Roll-Achsen korrekt, Schuh 22 g, also Export ohne `--flip-joints`). `qwen-vllm` dafür gestoppt (Nutzer: ja). Bewertung und Videos alle 100 Iterationen auf GPU 1.
- **Übernommen aus den bisherigen Läufen:** Servo-Modell mit gemessener Totzeit, Ratenbegrenzer 70 %, reale Gelenkgrenzen, Aktionsverlauf 4, `dt=0.002`, Startbelohnungen von `servo_tpu1` (sonst lernt der Lauf von null zu fallen, `servo_tpu3`), danach Übergabe per Kette an `servo_fric2` mit Tempo über 0,8-s-Mittel und Fortschrittsbonus.
- **Neu gegenüber `servo_tpu1`:**
  - μ gleichverteilt 0,1–1,5 je Umgebung auf den Fuß-Kontaktpaaren.
  - `speed_zero_prob=0`: nur Vorwärtsbefehle 3–6 cm/s, das Drift-Kriterium bei Soll 0 entfällt damit.
  - `imu_tilt_deg=8`: feste IMU-Neigung bis ±8° je Umgebung, neu als `ImuTiltRandomizer`. Grund: real 9–13° gegen 17,2° im Modell; nicht getrennt, ob Kopfhalterung oder Nachgiebigkeit der Beine.
- **Vorab behoben:** `train_chain.py` setzte jede Folgestufe fest auf `zbot-cad` und GPU 1, Bewertung auf GPU 0. `servo_fric2` wäre damit auf dem falschen Fußmodell gelaufen. Modell und GPU kommen jetzt aus der `launch.sh` des Vorgängers, die Bewertung läuft auf der anderen GPU.
- **Kontaktmodell geprüft** (starrer Block 2,62 kg, Löser wie im Training): Unterhalb der Rutschgrenze kriecht er nur 0,01–8 mm/s, `impratio` und Reibkegel bleiben daher unverändert. Gerutscht wird früher als μ·M·g: bei μ 0,1 und 1,1 zwischen 80 und 95 %, bei μ 0,5 und 1,5 zwischen 50 und 80 %. Das obere Ende wirkt also schwächer als nominell.
- **Nicht abgebildet:** die 1-s-Einblendrampe des Pi (in allen 12 Bodenläufen fällt die Neigung schon dort über 25°), das Spiel im rechten Bein und die IMU-Latenz. μ ≈ 0,2 für Laminat bleibt unkalibriert.
- **Ergebnis (2.11. 06:26, Wächter: Stagnation nach Bewertung 875):** bester Score 0,749 bei Schritt 750 mit 3/16 Stürzen, Tracking 1,31, 42 % echte Schritte. Spätere Bewertungen schwanken zwischen 6 und 10 Stürzen. Echte Schritte seit Schritt 335 nur 35–43 % (`servo_tpu1`: 81–94 %). Gate nicht bestanden. Kette `zbot-chain-friction` gestoppt, weil kein Checkpoint ≥ 50 % echte Schritte erreicht: `servo_fric2` nicht gestartet. Letztes Video `servo_fric1/videos/servo_fric1_step00795.mp4`.
- **Sweep Checkpoint 750 je μ** (`servo_fric1/mu_sweep_750/`, 16 Episoden à 5 s, μ fest):

  | μ | Stürze | Tracking | echte Schritte | Fußneigung > 5° |
  | --- | --- | --- | --- | --- |
  | 0,1 | 16 | – | – | – |
  | 0,2 | 15 | 0,50 | 18 % | 53 % |
  | 0,4 | 6 | 0,76 | 32 % | 42 % |
  | 0,8 | 3 | 1,67 | 59 % | 37 % |
  | 1,5 | 3 | 1,63 | 80 % | 39 % |

  **Tiefpunkt:** Der Bereich um μ 0,2, in dem der Laminat-Schätzwert liegt, wird gerade nicht beherrscht. Bei μ 0,8 und 1,5 geht sie echte Schritte mit 7 cm/s (Soll 3–6), aber seitlich rund 17 cm auf 35 cm Strecke, also nicht gerade. Die 42 % echte Schritte im Mittel kamen vor allem von den glatten Umgebungen. Gleichverteilt lagen nur 21 % der Umgebungen unter μ 0,4; neu vorbereitet ist `foot_friction_log` (51 % darunter).

### `servo_fric2` — weiter ab `servo_fric1` 750 mit log-verteilter Reibung (gestartet 2.11., GPU 0)
- **Nutzer:** Weiter ab Checkpoint 750 statt von null (Auswahl auf Rückfrage). `qwen-vllm` bleibt dafür aus.
- **Änderung:** nur `foot_friction_log=True` (μ 0,1–1,5, 51 % der Umgebungen unter 0,4 statt 21 %). Belohnungen unverändert, damit eine Änderung bei den Stürzen auf die Verteilung zurückgeht.
- **Start:** `sim/tools/launch_servo_fric2.sh`, bis Schritt 3250. Kette `zbot-chain-friction2` wechselt bei höchstens 4/16 Stürzen und ≥ 50 % echten Schritten (zweimal in Folge) auf `servo_fric3` mit den Tempo-Korrekturen.
- **Ergebnis (2.11. 11:05, von Hand gestoppt bei 1205):** keine Besserung. 4–13/16 Stürze, Tracking 0,64–1,20, echte Schritte nur noch 15–21 % (fric1: ~40 %). Die glatten Umgebungen haben die Policy ins Tippeln gedrängt. Gestoppt, weil der Nutzer auf Kletterschuhgummi umsteigt. Checkpoints bleiben (`servo_fric2/snapshots/`).

### `servo_rubber1` — von null für Kletterschuhgummi, μ 0,5–1,3 (gestartet 2.11. ~11:10, GPU 0)
- **Nutzer:** „ich habe kletterschuh-sohlen-gummi bestellt und erwarte eine haftung von 0,6 bis 1,0. starte ein entsprechendes policy training von Null. nach dem besten wissen, das du bisher hast"
- **Reibung gleichverteilt 0,5–1,3:**
  - Unten 0,1 Reserve unter der Erwartung.
  - Oben 0,3 darüber, weil das Kontaktmodell schon bei 50–95 % von μ·M·g rutschen lässt.
  - Die Erwartung 0,6–1,0 ist noch nicht gemessen. Vor dem Hardware-Test mit dem Kipptest prüfen.
- **Modell:** `zbot-cad-tpu` (flache Sohle über die ganze Fußfläche, 3,5 mm tiefer, 22 g). Annahme: Der Gummi wird flach unter die PETG-Sohle geklebt, eine 3–4-mm-Platte wiegt etwa 20–30 g. Weichen Dicke oder Gewicht deutlich ab, muss das Modell neu gebaut werden.
- **Sonst wie `servo_fric1`:**
  - Bootstrap-Belohnungen von `servo_tpu1`.
  - Nur Vorwärtsbefehle 3–6 cm/s.
  - IMU-Neigung ±8°.
  - Servo-Modell, Ratenbegrenzer, Aktionsverlauf 4.
  - Kette `zbot-chain-rubber` wechselt auf `servo_rubber2` mit den Tempo-Korrekturen, sobald der Lauf zweimal in Folge höchstens 4/16 Stürze und ≥ 50 % echte Schritte hat.
- **Erwartung aus `servo_fric1`:** Bei μ 0,8–1,5 hatte Checkpoint 750 3/16 Stürze und 59–80 % echte Schritte. Ab μ ≥ 0,5 sollte die Kette diesmal greifen.
- **Ergebnis (2.11. 18:26, Wächter: Stagnation nach 885):** echte Schritte früh über 50 % (54–67 % ab Schritt 425), aber die Stürze blieben hoch: 6–14 von 16, bester Score 0,742 bei 760 mit 9 Stürzen. Das Wenigste waren 4/16 bei Schritt 175. Zum Vergleich `servo_fric1` 750 bei festem μ 0,8–1,5: 3/16, hier aber über den ganzen Bereich ab 0,5 bewertet. Das Bootstrap-Kriterium (≤ 4 Stürze zweimal in Folge) wurde nie erreicht; die Kette übernahm beim Wächter-Ende den Checkpoint mit den wenigsten Stürzen bei ≥ 50 % echten Schritten: **Schritt 175**.

### `servo_rubber2` — Tempo-Korrekturen ab `servo_rubber1` 175 (gestartet 2.11. 18:34, Kette, GPU 0)
- Tempo über 0,8-s-Mittel, Schrittlänge nur bei Soll, kein `naive_velocity`, Fortschrittsbonus 10. Sonst wie `servo_rubber1`.
- **Verlauf (Stand 20:38):**

  | Schritt | Stürze | Tracking | echte Schritte | Fußneigung > 5° |
  | --- | --- | --- | --- | --- |
  | 175 | 5 | 1,86 | 52 % | 43 % |
  | 230 | 7 | 1,31 | 49 % | 50 % |
  | 270 | 6 | 1,12 | 53 % | 42 % |
  | 315 | 4 | 1,20 | 51 % | 36 % |
  | 355 | 3 | 1,16 | 54 % | 43 % |

  | 400 | 2 | 1,09 | 50 % | 48 % |
  | 440 | 1 | 1,17 | 47 % | 43 % |
  | 481 | 6 | 1,18 | 48 % | 43 % |
  | 525 | 3 | 1,37 | 49 % | 48 % |

- **Ergebnis (Wächter: Stagnation nach 525):** bester Checkpoint **440**: 1/16 Stürze, Tempo 1,17-fach, 47 % echte Schritte, Score 0,747. Gate nicht bestanden: Stürze, Fußneigung (43 % statt ≤ 30 %), Zittern und Ratenbegrenzer. Danach wieder 3–6 Stürze. Kette damit zu Ende, keine weitere Stufe. Video `servo_rubber2/videos/servo_rubber2_step00440.mp4`.
- **Export (3.11.):** `sim/policies/servo_rubber2_step440` (ONNX = JAX, keine Gelenk-Spiegelung, Metadaten mit μ 0,5–1,3). Noch nicht auf dem Pi.
- **Sweep Checkpoint 440 je μ** (`servo_rubber2/mu_sweep_440/`, 16 Episoden à 5 s):

  | μ | Stürze | Tracking | echte Schritte | Fußneigung > 5° |
  | --- | --- | --- | --- | --- |
  | 0,5 | 2 | 1,04 | 30 % | 55 % |
  | 0,7 | 6 | 1,18 | 41 % | 50 % |
  | 1,0 | 1 | 1,08 | 83 % | 52 % |
  | 1,3 | 2 | 1,08 | 93 % | 55 % |

  Insgesamt 11 von 64 Episoden gestürzt (17 %). Die 1/16 der Wächter-Bewertung war Glück. Die Stürze hängen nicht klar von μ ab (0,7 schlechter als 0,5), bei 16 Episoden streut das stark. Bei fester Reibung neigen sich die Füße in über 50 % der Kontaktzeit mehr als 5°, also noch mehr als in der gemischten Bewertung.

### `servo_rubber3` — von null, Fußstrafe −30 (gestartet 3.11. ~18:05, GPU 0)
- **Nutzer:** „ja, setze das so um" (Vorschlag: Export von 440 und neuer Lauf mit stärkerer Fußstrafe von Anfang an).
- **Einstellungen:** wie `servo_rubber1` (μ 0,5–1,3, Bootstrap-Belohnungen, nur vorwärts, IMU ±8°), aber `foot_flat_penalty=-30` statt −8. Kette `zbot-chain-rubber3` → `servo_rubber4` mit Tempo-Korrekturen.
- **Ab jetzt autonom (Nutzer, 3.11.):** „bitte agiere ab jetzt komplett autonom. wenn eine Policy aus Stagnation abbricht, analysiere die Ursachen und stoße entsprechend ab einem geeigneten Checkpoint ein angepasstes Training an oder treffe andere geeignete Maßnahmen."
- **Ergebnis:** 16/16 Stürze bis 130, dann rasch besser: 335 mit 3/16 Stürzen, 64 % echten Schritten und nur **18 %** Fußneigung > 5° (`servo_rubber2`: 43 %). **Die stärkere Fußstrafe von Anfang an wirkt.** Bootstrap-Kriterium zweimal erfüllt → Kette übergab 3.11. 21:12 an `servo_rubber4` ab 335.

### `servo_rubber4` — Tempo-Korrekturen ab `servo_rubber3` 335 (3.11. 21:12–23:36)
- **Verlauf:**

  | Schritt | Stürze | Tracking | echte Schritte | Fußneigung > 5° |
  | --- | --- | --- | --- | --- |
  | 345 | 2 | 1,53 | 63 % | 33 % |
  | 385 | 1 | 1,51 | 63 % | 16 % |
  | 465 | 1 | 1,47 | 63 % | 17 % |
  | 545 | 1 | 1,51 | 59 % | 21 % |
  | 585 | 2 | 1,18 | 63 % | 27 % |

- **Highlight:** bester Stand bisher. 1–2/16 Stürze und flache Füße zugleich. Bester Checkpoint **465** (Score 0,758).
- **Ende 23:36 (Stagnation).** Danach standen die GPUs bis 4.11. 05:50 still: Mein Hintergrund-Wecker hatte sich schon beim Kettenwechsel um 21:14 beendet und lief danach nicht weiter.
- **Analyse (autonom, 4.11.):** Gate scheitert an Stürzen, `tracking_ratio_max` (1,47 > 1,3) und den alten Dauerbrennern Zittern, Ratenbegrenzer und Zielgrenzen. Die Fußneigung ist mit 17 % bestanden.
  - **Ursache für das Übertempo:** Die Schrittlängen-Belohnung zahlt voll erst bei 4 cm Fußweg pro Schwung. Bei 1,0–1,25 Hz Gangtakt sind das 4–5 cm/s, egal welches Soll gilt. Bei Soll 3 cm/s lohnt also Übertempo.
  - Das passt zum gemessenen Tracking von 1,2–1,6.

### `servo_rubber5` — Schrittlänge passend zum Soll (gestartet 4.11. ~05:58, ab `servo_rubber4` 465, GPU 0)
- **Änderung:** nur `stride_per_command=True`. Ziel-Schrittlänge = Soll-Tempo ÷ Gangtakt, höchstens 4 cm (bei 3 cm/s und 1 Hz also 3 cm). Im Einzeltest geprüft.
- Neues Startskript `sim/tools/launch_continue.sh` (Lauf + Wächter, Modell vom Quell-Lauf). Wächter: Stagnation ab 200 Iterationen.
- **Ergebnis:** Ende 4.11. 08:17 (Stagnation).

  | Schritt | Stürze | Tracking | echte Schritte | Fußneigung > 5° |
  | --- | --- | --- | --- | --- |
  | 465 (Start) | 1 | 1,76 | 61 % | 35 % |
  | 520 | 3 | 1,32 | 58 % | 32 % |
  | 560 | 1 | 1,68 | 60 % | 29 % |
  | **600** | **1** | **1,18** | 60 % | **20 %** |
  | 640 | 2 | 1,43 | 57 % | 35 % |
  | 680 | 3 | 1,65 | 61 % | 23 % |
  | 720 | 4 | 1,37 | 59 % | 33 % |

- **Analyse:** Step 600 ist der erste Checkpoint, bei dem Tracking (1,18 ≤ 1,3) und Fußneigung (20 % ≤ 30 %) zugleich im Ziel liegen. Am Gate fehlen nur noch 1 Sturz und die alten Dauerbrenner. Danach pendelte der Lauf: Tracking 1,4–1,7, Stürze stiegen auf 4. Die Belohnungsstruktur scheint zu stimmen, aber die Policy springt mit Lernrate 3e-4 zwischen guten und schlechten Ständen hin und her.
- **Panne:** Der Wecker meldete das Ende um 08:17, die Nachricht erreichte mich aber erst um 19:27. Die GPU stand also wieder ~11 h still. Der sitzungsunabhängige Supervisor ist weiterhin nicht installiert.

### `servo_rubber6` — Festigen mit kleinerer Lernrate (gestartet 4.11. 19:30, ab `servo_rubber5` 600, GPU 0)
- **Änderung:** nur `learning_rate=1e-4` statt 3e-4. Ziel ist, den guten Stand von 600 zu halten und Stürze sowie Tempo-Schwankung zu senken, statt wieder wegzupendeln.
- **Ergebnis:** Ende 4.11. 21:47 (Stagnation). Gemeldet wurde es mir erst am 5.11. um 06:02, die GPU stand also wieder ~8 h still.

  | Schritt | Stürze | Tracking | echte Schritte | Fußneigung > 5° |
  | --- | --- | --- | --- | --- |
  | 605 | 2 | 1,14 | 60 % | 30 % |
  | **645** | **1** | **1,13** | 60 % | 29 % |
  | 685 | 3 | 1,35 | 59 % | 37 % |
  | 725 | 2 | 1,61 | 60 % | 34 % |
  | 765 | 1 | 1,41 | 62 % | 18 % |
  | 805 | 1 | 1,48 | 57 % | 34 % |
  | 845 | 1 | 1,34 | 62 % | 20 % |

- **Analyse:** Die kleinere Lernrate hat das Pendeln nicht beseitigt. Das Tempo schwankt weiter zwischen 1,13 und 1,61, die Fußneigung zwischen 18 und 37 %. Es liegt also nicht an zu großen Lernschritten. Das Übertempo ist offenbar zu billig: Mit `track_error_scale=0.03` (L1) verliert die Policy bei 1,5-fachem Tempo und Soll 4,5 cm/s nur gut die Hälfte der Tracking-Belohnung, und Schrittlänge und Vortrieb gleichen das teilweise aus.

### `servo_rubber7` — schärferes Tempo-Tracking (gestartet 5.11. 06:05, ab `servo_rubber6` 645, GPU 0)
- **Änderung:** nur `track_error_scale=0.015` statt 0,03. Bei 1,5-fachem Tempo bleiben damit ~22 % statt ~47 % der Tracking-Belohnung. Lernrate bleibt 1e-4.
- **Ergebnis:** Ende 5.11. 08:28 (Stagnation), bester Stand blieb der Start 645. Tracking wurde **schlechter**: 1,26 → 1,45–1,70. Stürze 1–3, Fußneigung 12–26 %.
- **Analyse je Episode (Step 900):** Bei Soll 3,2–5,2 cm/s läuft die Policy **immer 6–10 cm/s, im Mittel ~8 cm/s**, egal welches Soll gilt.
  - Der Belohnungssensor misst dieselbe Geschwindigkeit wie die Weltposition, ein Messfehler ist es also nicht.
  - Die Policy verzichtet bewusst auf den Großteil der Tracking-Belohnung (pro Episode 1–3 statt bis ~30). Ihr Gang hat also ein festes Tempo.
  - **Ursache:** Die Startbelohnung für Läufe von null, `NaiveVelocityReward` (Skala 1,5 in `servo_rubber3`), zahlt für jede Vorwärtsgeschwindigkeit bis 5 m/s. Der Gang mit festem, hohem Tempo entsteht dort, und alle Folgeläufe (`servo_rubber4`–7) erben ihn. Wie schon bei `servo_ctrl_v13`–v31 entfernt Umgewichten im Nachhinein so einen Fehler nicht.

### `servo_rubber8` — von null, Start-Tempo gedeckelt (gestartet 5.11. ~12:30, GPU 0, Kette `rubber8` → `servo_rubber9`)
- **Code:** `NaiveVelocityReward` hat den neuen Schalter `naive_velocity_cap`. Ist er gesetzt, zahlt die Belohnung höchstens bis zum 1,2-fachen Soll-Tempo. Im Einzeltest geprüft: 8 cm/s bei Soll 4 cm/s → 4,8 statt 8.
- **Einstellungen:** wie `servo_rubber3` (μ 0,5–1,3, Fußstrafe −30, IMU ±8°, Startbelohnungen), dazu `naive_velocity_cap=1.2` und `stride_per_command=True` von Anfang an.
- **Kette:** Sobald der Lauf überlebt und echte Schritte macht, wechselt die Kette `rubber8` wie bisher zu `servo_rubber9` mit den Folge-Einstellungen (Fenster 0,8 s, Vortrieb 10, keine naive Belohnung).
- **Ergebnis:** Bootstrap-Kriterium bei 600 erfüllt. Bester Stand 400 mit 1/16 Stürzen, Tracking 0,99, Fußneigung 21 %. Die Kette übergab ab 400 an `servo_rubber9`.

### `servo_rubber9` — Folge-Einstellungen ab `servo_rubber8` 400 (Kette, Ende 5.11. 20:13)
- **Verlauf:**

  | Schritt | Stürze | Tracking | echte Schritte | Fußneigung > 5° |
  | --- | --- | --- | --- | --- |
  | 401 | 9 | 0,59 | 66 % | 28 % |
  | 460 | 2 | 1,42 | 61 % | 18 % |
  | 500 | 2 | 1,17 | 58 % | 28 % |
  | 585 | 3 | 1,60 | 56 % | 36 % |
  | 665 | 1 | 1,13 | 60 % | 35 % |
  | **705** | **1** | 1,38 | 60 % | **19 %** |

- **Analyse je Episode (705):** Das Tempo liegt bei 4,5–7,3 cm/s, im Mittel ~6 cm/s statt ~8 cm/s bei `servo_rubber7`. Die Tracking-Belohnung pro Episode beträgt 4–9 statt 1–3. **Der Deckel wirkt.** Das Soll befolgt die Policy aber noch kaum: Bei Soll 3,2 läuft sie 6,6 cm/s, bei Soll 5,2 nur 4,6 cm/s.
- Die GPU stand von 20:13 bis 22:35 still, weil der Wecker wieder zu spät kam.

### `servo_rubber10` — schärferes Tempo-Tracking ab `servo_rubber9` 705 (gestartet 5.11. 22:36, GPU 0)
- **Änderung:** nur `track_error_scale=0.015` statt 0,03. Bei `servo_rubber7` half das nicht, weil der Gang dort fest auf ~8 cm/s stand. Hier liegt das Tempo schon nahe am Soll, also sollte sich ein Anpassen ans Soll jetzt deutlich mehr lohnen. Lernrate wieder 3e-4.
- **Ergebnis:** Ende 6.11. 00:59 (Stagnation), bester Stand blieb der Start 705. Das Tempo **stieg** von 1,18 auf 2,0, Stürze 3–7.
  - Je Episode (960): 7,4–9,4 cm/s bei Soll 3,2–4,6. Tracking-Belohnung 0,2–2, Vortrieb fast immer die vollen 10.
- **Ursache, jetzt klar (gilt auch für `servo_rubber7`):** Der schärfere Tracking-Kern macht die Tracking-Belohnung für jedes erreichbare Tempo fast null, und damit gibt sie keine Richtung mehr vor. Übrig bleibt `ForwardProgressReward`. Der Vortrieb ist zwar beim Soll gedeckelt, Übertempo zahlt aber genauso voll und hält jedes 0,8-s-Fenster sicher bei 1. Also lohnt sich Übertempo.

### `servo_rubber11` — Vortrieb mit Spitze beim Soll (gestartet 6.11. ~06:10, ab `servo_rubber9` 705, GPU 0)
- **Code:** neuer Schalter `forward_progress_peak`. Der Vortrieb ist dann min(v/Soll, 2 − v/Soll): Er ist beim Soll am höchsten und fällt bei doppeltem Soll auf 0. Im Einzeltest geprüft: bei Soll 4 cm/s und Tempo 2/4/6/8 cm/s → 0,5/1/0,5/0. Die 7 bestehenden Tests laufen weiter durch.
- **Änderung:** nur `forward_progress_peak=True`. Tracking-Skala wieder 0,03 wie in `servo_rubber9`.
- **Ergebnis:** Ende 6.11. 08:28 (Stagnation). Gemeldet erst um 13:57, die GPU stand also ~5,5 h still. Das Tempo kippte ins Gegenteil:

  | Schritt | Stürze | Tracking | echte Schritte | Fußneigung > 5° |
  | --- | --- | --- | --- | --- |
  | 705 | 2 | 1,41 | 59 % | 26 % |
  | **760** | **1** | **0,69** | 57 % | 27 % |
  | 800 | 2 | 0,26 | 58 % | 32 % |
  | 885 | 1 | 0,60 | 55 % | 32 % |
  | 965 | 3 | 0,49 | 60 % | 23 % |

- **Analyse je Episode (965):** Die Policy schlurft mit −3 bis 4 cm/s, manchmal rückwärts. Einen Zusammenhang mit dem Soll gibt es weiter nicht.
  - Die spitze Belohnung bestraft auch die kurzen Tempo-Spitzen innerhalb eines Schritts. Langsam laufen ist damit die sichere Wahl.
  - Mit den Läufen 9 und 10 zusammen heißt das: Der Vortrieb steuert das mittlere Tempo, aber nicht, ob die Policy dem Soll folgt.

### `servo_rubber12` — Vortrieb mit Plateau (gestartet 6.11. ~14:05, ab `servo_rubber11` 760, GPU 0)
- **Code:** `forward_progress_peak_tol`. Volle Belohnung beim 1,0- bis 1,3-fachen Soll, also genau im Gate-Band. Darüber fällt sie linear und ist beim 2,3-fachen Soll 0. Im Einzeltest geprüft: 0,5/1/1,3/1,8/2,3 × Soll → 0,5/1/1/0,5/0.
- **Änderung:** nur `forward_progress_peak_tol=0.3`. Start bei 760 (Tracking 0,69, 1 Sturz), weil der Stand zwischen zu schnell (705) und zu langsam (800+) liegt.
- **Ergebnis:** Ende 6.11. 16:19 (Stagnation). **Erste sturzfreie Checkpoints der Gummi-Serie.**

  | Schritt | Stürze | Tracking | echte Schritte | Fußneigung > 5° | > 5 Hz | Begrenzer |
  | --- | --- | --- | --- | --- | --- | --- |
  | **765** | **0** | 0,76 | 57 % | 36 % | 0,28 | 0,83 |
  | **805** | **0** | 0,74 | 57 % | 37 % | 0,28 | 0,82 |
  | 845 | 3 | 0,64 | 60 % | 32 % | 0,30 | 0,83 |
  | **885** | **0** | 0,77 | 57 % | 37 % | 0,27 | 0,83 |
  | 1005 | 4 | 0,74 | 58 % | 33 % | 0,29 | 0,83 |

  Es bleiben die Fußneigung (36 % statt ≤ 30 %) und das Zittern. Das Zittern ist seit Wochen in allen Läufen gleich: Ziel-Zickzack p99 = 0,086 = volle Richtungsumkehr am Begrenzer, Begrenzer 83 % aktiv, 27–30 % über 5 Hz.

### Neue Prioritäten (Nutzer, 6.11. ~14:30)
„das soll und ist tempo ist gar nicht die Prio. wichtig ist, dass der roboter vorwärts kommt. und das stabil ohne zittern und mit sohlen, die parallel zum boden auftreten. und gerne andere Metriken etc, die vielversprechend sind um das laufen stabiler zu machen"
- Gate: Tracking-Band jetzt 0,5–2,0 statt 0,75–1,3 (`sim/tools/hardware_gate.py`). Vorwärts muss er, das genaue Tempo ist egal.
- Weitere Schwerpunkte: Stürze, Zittern, Fußneigung.

### `servo_rubber13` — CAPS-Glättung im Verlust (gestartet 6.11. ~17:25, ab `servo_rubber12` 765, GPU 0)
- **Idee (Mysore et al. 2021, „Regularizing Action Policies for Smooth Control"):** Glättung nicht als Belohnung, sondern direkt als Term im Verlust des Actors.
  - Als Belohnung kosteten die Zitter-Strafen PPO fast nichts (`servo_ctrl_v4`: ~3 % der Rendite). Stärkere Strafen ließen die Policy das Laufen aufgeben (`servo_ctrl_v5`/v6), weil das Zittern damals die Gangart *war* (Hüpfer).
  - Heute macht die Policy echte Schritte (57–65 % ≥ 0,2 s). Der Gradient im Verlust geht direkt in den Actor und braucht keine Zuordnung über die Rendite.
- **Code (`get_loss_and_metrics` in `walking.py`):**
  - `caps_temporal`: quadratische 2. Differenz der *mittleren* Aktion über aufeinanderfolgende Schritte. Ein 1-Hz-Gang mit 0,3 rad Amplitude hat ~0,005 rad Ruck, der 5–6-Hz-Zickzack ~0,17 rad. Quadriert trifft der Term das Zittern also ~1000-mal stärker als den Gang.
  - `caps_spatial`: quadratische Änderung der mittleren Aktion, wenn die Sensoreingänge leicht verrauscht werden (Gelenkwinkel 0,01 rad, Gelenkgeschwindigkeit 0,1 rad/s, Gyro 0,05 rad/s, Beschleunigung 0,1 m/s²). Das senkt die Verstärkung des Regelkreises, der laut Diagnose vom 28.10. über die Totzeit schwingt.
- **Änderung:** `caps_temporal=1.0 caps_spatial=1.0`, sonst wie `servo_rubber12`.
- **Rauchtest:** Das Training läuft. Der PPO-Verlust stieg von ~0,01 auf ~0,03–0,04 (die CAPS-Terme), die Ruckstrafe der Belohnung sank in den ersten Iterationen um ~20 %. Die Gesamtbelohnung pro Schritt fiel von 0,037 auf 0,021–0,028. Das muss die Auswertung zeigen.
- **Ergebnis:** Ende 6.11. 20:20 (Stagnation). Gemeldet erst 7.11. 09:40, die GPU stand also ~13 h still.

  | Schritt | Stürze | Tracking | Fußneigung > 5° | > 5 Hz | Begrenzer |
  | --- | --- | --- | --- | --- | --- |
  | 765 (Start) | 2 | 0,76 | 33 % | 0,29 | 0,83 |
  | 855 | 2 | 0,63 | 28 % | 0,29 | 0,68 |
  | **910** | **1** | **0,82** | **23 %** | 0,29 | 0,61 |
  | 1005 | 2 | 0,64 | 21 % | 0,28 | 0,56 |
  | 1060 | 3 | 0,68 | 25 % | 0,27 | 0,54 |

- **Analyse:** **CAPS wirkt.**
  - Der Begrenzer ist nur noch 54 % aktiv (vorher 83 %), stetig fallend.
  - Die Fußneigung ist jetzt **bestanden** (21–25 %). Ruhigere Aktionen setzen den Fuß offenbar flacher auf.
  - Spektrum (1060 gegen `servo_rubber12` 1005): Der scharfe 5–6-Hz-Gipfel der Regelschwingung ist weg, die Spitze liegt beim Gangtakt 1,6 Hz bzw. 3,2 Hz. Anteil über 5 Hz in der Aktion 0,62 → 0,40. In den Gelenken über 5 Hz Effektivwert: Hüfte-Pitch 1,21° → 1,04°, Knie 1,11° → 0,90°, Knöchel 1,46° → 1,22°, Hüfte-Roll 1,40° → 0,93°.
  - Das Gate-Kriterium „> 5 Hz" (Amplitudenspektrum, 0,15) sieht davon kaum etwas (0,29 → 0,27). Es zählt auch den breitbandigen Anteil der Fußaufsätze mit. Ziel-Zickzack p99 bleibt 0,086.
  - Stürze 1–3, also etwas mehr als in `servo_rubber12`.

### `servo_rubber14` — CAPS ×3 (gestartet 7.11. ~09:50, ab `servo_rubber13` 910, GPU 0)
- **Änderung:** nur `caps_temporal=3.0 caps_spatial=3.0`. Die Richtung stimmt, die Stärke reicht noch nicht.
- **Ergebnis:** Ende 7.11. 14:23 (Stagnation). **Bester Lauf bisher** (höchster Score 0,825).

  | Schritt | Stürze | Tracking | echte Schritte | Fußneigung > 5° | > 5 Hz | Begrenzer | Zickzack p99 |
  | --- | --- | --- | --- | --- | --- | --- | --- |
  | 910 (Start) | 1 | 0,73 | 60 % | 21 % | 0,30 | 0,61 | 0,086 |
  | 1000 | **0** | 0,43 | 63 % | 25 % | 0,28 | 0,41 | 0,086 |
  | 1110 | **0** | 0,78 | 63 % | 24 % | 0,29 | 0,31 | 0,086 |
  | 1150 | **0** | 0,71 | 63 % | 23 % | 0,28 | 0,30 | 0,086 |
  | **1205** | **0** | **0,93** | 64 % | **22 %** | 0,27 | 0,26 | 0,082 |
  | 1260 | 1 | 0,99 | 63 % | 14 % | 0,29 | 0,25 | 0,083 |
  | 1355 | 1 | 0,96 | 67 % | 13 % | 0,29 | 0,24 | 0,081 |
  | 1410 | 1 | 0,70 | 70 % | 34 % | 0,28 | 0,19 | 0,077 |

- **Highlight:** Drei sturzfreie Checkpoints hintereinander. Fußneigung bestanden, und der Begrenzer greift nur noch 26 % der Zeit (`servo_rubber12`: 83 %). Mit 1410 fällt zum ersten Mal überhaupt auch der Ziel-Zickzack unter die volle Umkehr (0,077).
  - Stärkere CAPS-Gewichte kosten also kein Laufen, eher im Gegenteil: echte Schritte 60 → 70 %.
  - Das Gate-Kriterium „> 5 Hz" bleibt bei 0,27–0,29 (siehe Analyse `servo_rubber13`).
- **Export:** `sim/policies/servo_rubber14_step1205` (ONNX = JAX, Abweichung 0). Nicht auf den Pi kopiert, die Hardware entscheidet der Nutzer.

### `servo_rubber15` — CAPS ×6 (gestartet 7.11. ~16:00, ab `servo_rubber14` 1205, GPU 0)
- **Änderung:** nur `caps_temporal=6.0 caps_spatial=6.0`. Der Begrenzer-Anteil fiel bis zuletzt stetig, das Laufen blieb dabei gut. Ziel: Begrenzer ≤ 20 % und Zickzack deutlich unter 0,086 bei 0 Stürzen.
- **Ergebnis:** Ende 7.11. 19:03 (Stagnation nach der 3-%-Regel, die Einzelwerte wurden aber weiter besser).

  | Schritt | Stürze | Tracking | echte Schritte | Fußneigung > 5° | > 5 Hz | Begrenzer | Zickzack p99 |
  | --- | --- | --- | --- | --- | --- | --- | --- |
  | 1206 | 0 | 0,88 | 62 % | 22 % | 0,28 | 0,26 | 0,083 |
  | **1265** | **0** | 0,91 | 67 % | **19 %** | 0,28 | 0,22 | 0,076 |
  | 1320 | 1 | 0,88 | 67 % | 21 % | 0,28 | 0,19 | 0,073 |
  | 1375 | 0 | 0,86 | 72 % | 30 % | 0,27 | **0,16** | 0,069 |
  | 1430 | 0 | 0,81 | 75 % | 35 % | 0,27 | 0,15 | 0,067 |
  | 1470 | 0 | 0,88 | 79 % | 36 % | 0,27 | 0,14 | 0,067 |
  | **1525** | **0** | 0,83 | 78 % | 32 % | 0,27 | **0,13** | **0,065** |

- **Highlight:** 6 von 7 Auswertungen sturzfrei. **Begrenzer-Kriterium (≤ 20 %) erstmals bestanden**, ab 1375. Zickzack 0,086 → 0,065, echte Schritte 62 → 78 %.
- **Rückschritt:** Die Fußneigung stieg mit den längeren, echteren Schritten wieder auf 30–36 %.
  - Bester Kompromiss für die Hardware ist 1265: 0 Stürze, 19 % Neigung, Begrenzer 22 %.
  - 1525 ist am ruhigsten, setzt den Fuß aber schräger auf.

### `servo_rubber16` — Fußstrafe −50 (gestartet 7.11. ~19:10, ab `servo_rubber15` 1525, GPU 0)
- **Änderung:** nur `foot_flat_penalty=-50` statt −30, CAPS bleibt bei 6. Ziel: die Ruhe von 1525 behalten und die Sohlen wieder ≤ 30 % (besser ~20 %) bringen.
- **Zwischenfall:** Der Rechner wurde zwischen 19:29 und 19:52 neu gestartet. Der Watchdog startete den Lauf ab seinem eigenen Checkpoint (~1560) neu, der Wächter fehlte aber. Ich habe ihn von Hand neu gestartet. `zbot_watchdog.sh` startet seitdem auch den Wächter eines laufenden Laufs neu.
- **Ergebnis:** Ende 7.11. 22:30 (Stagnation).

  | Schritt | Stürze | Tracking | echte Schritte | Fußneigung > 5° | Begrenzer | Zickzack p99 |
  | --- | --- | --- | --- | --- | --- | --- |
  | 1530 | 0 | 0,90 | 80 % | 32 % | 0,13 | 0,063 |
  | 1575 | 1 | 0,81 | 82 % | 35 % | 0,12 | 0,063 |
  | 1685 | 0 | 0,94 | 79 % | 28 % | 0,12 | 0,061 |
  | 1780 | 0 | 0,92 | 86 % | 33 % | 0,12 | 0,061 |
  | **1835** | **0** | **0,94** | **89 %** | **28 %** | 0,12 | 0,061 |

- **Highlight:** 6 von 7 Auswertungen sturzfrei, 89 % echte Schritte, höchster Score bisher (0,848). Die Fußneigung liegt knapp unter 30 %.
- **Analyse der Dauerbrenner „Ziel außerhalb" (≈ 100 %) und „an der Grenze" (93 %), je Gelenk (1835):**
  - Alle Gelenke bleiben weit weg von ihren Grenzen, **nur die Hüftdrehung nicht**. Ihre realen Grenzen sind einseitig eng: rechts [−3°, 90°], links [−90°, 5°].
  - Die Policy fordert rechts bis −19° und links bis +29°, also beide Füße stark nach innen. Damit liegt das Ziel 59 % bzw. 43 % der Zeit jenseits der Grenze.
  - Der Clamp (Sim wie Pi) hält das Gelenk bei −3°/+5°, gemessen −3,6°/+5,6°. Die Policy nutzt den Clamp also als Anschlag.
  - Für die Hardware ist das der wichtigste offene Punkt (vgl. das gerissene Hüftteil vom 22.10.).
  - `target_limit_penalty=-4` ist linear und über 16 Gelenke gemittelt, also zu schwach.

### `servo_rubber17` — Zielgrenzen-Strafe −20 (gestartet 7.11. ~22:33, wirklich trainierend ab ~22:50, ab `servo_rubber16` 1835, GPU 0)
- **Änderung:** nur `target_limit_penalty=-20` statt −4. Ziel: die Hüftdrehung innerhalb der realen Grenzen halten, ohne Stürze und Sohlen zu verschlechtern.
- **Zwischenfall:** `qwen-vllm` ist ein aktivierter Dienst mit Neustart bei Fehler. Seit dem Neustart des Rechners hatte er es 175-mal versucht und belegte in der Minute, in der `servo_rubber16` die GPUs freigab, beide GPUs. Der neue Lauf brach dreimal mit CUDA-Speichermangel ab. Ich habe den Dienst wieder gestoppt (Zustimmung des Nutzers vom 1.11.), aber nicht deaktiviert. **Nach jedem Neustart des Rechners wiederholt sich das.**
- **Nachtrag 7.11.:** Auf Wunsch des Nutzers ist der Automatismus abgeschaltet. qwen-vllm hat kein Restart mehr, ist deaktiviert und wird nur noch von Hand im Qwen-Core-Monitor (http://localhost:8090) geschaltet. Der Monitor zeigt die GPU-Belegung und verweigert den Start während eines Trainings (409).
- **Ergebnis (Wächter-Stopp 8.11. 01:39, Stagnation bei 2125, bestes 1935, Score 0,849):** Stürze bei 0, Sohlen-Kippanteil 0,25–0,30, Limiter 0,10–0,12. Die Strafe hat aber **nichts** bewirkt: target_out_share 0,99, margin_share 0,94, wie in rubber16.
- **Ursachenanalyse (limits.py auf 2125):** Ausschließlich die Hüftdrehung ist betroffen. Die Policy steuert rechts bis −17,7° an (Grenze −3°, in 60 % der Schritte jenseits) und links bis +25° (Grenze +5°, in 40 %). Die Klemme des Sim-Aktuators (`clamp_to_real_limits`) und auf dem Pi dient ihr als Anschlag.
  - `TargetLimitPenalty` und `JointLimitPenalty` **mitteln über alle 20 Gelenke**. Zwei betroffene Gelenke kosten dadurch nur ein Zehntel. Mit −20 waren das −0,001 bei einer Gesamtbelohnung von 0,041; das hat die Policy in Kauf genommen.
- **Probe ohne Training:** Checkpoint 1935 mit geklemmtem Policy-Ausgang (s. rubber18). target_out_share fällt auf **0**, aber margin_share bleibt bei 0,85 und es gibt 2 Stürze. Unter Last drückt der Boden das Gelenk etwa 1,5° über den Sollwert hinaus bis an den Anschlag (rechts −3,0°, links +4,9°). Die Policy muss lernen, den Sollwert aktiv weiter nach innen zu legen.
- **Videos:** `servo_rubber17/videos/` (automatisch alle 100 Iterationen).

### `servo_rubber18` — Policy-Ausgang hart geklemmt + Gelenkgrenzen-Strafe als Summe (gestartet 8.11. ~09:35, ab `servo_rubber17` 1935, GPU 0)
- **Neu in `walking.py`:**
  - `action_clip_margin_deg` (>0): `ZbotActor` klemmt den Mittelwert jedes Gelenks auf den echten Bereich minus Rand. Der Rand ist höchstens die halbe Distanz zur Nullstellung und entspricht damit genau dem Gate-Rand (Hüftdrehung 1,5°/2,5°).
  - Die Klemme steckt im Netz selbst. `export_policy.py` schreibt sie als Max/Min-Knoten ins ONNX, der Pi braucht seine Klemme also nicht mehr. Die Gate-Prüfung „Sollwert in den Grenzen" ist damit konstruktiv erfüllt.
  - `joint_limit_sum`: `JointLimitPenalty` summiert über die Gelenke (Tiefe auf 2 gekappt), statt zu mitteln.
- **Änderungen:** `action_clip_margin_deg=5`, `joint_limit_sum=true`, `joint_limit_penalty=-8`. Der erste Start mit −2 ergab im Log nur −0,0011 bei einer Gesamtbelohnung von 0,044 (2,5 %, so schwach wie die wirkungslose Strafe in rubber17). Nach dem ersten Schritt abgebrochen (`_aborted_servo_rubber18a`) und mit −8 neu gestartet: −0,0044 von 0,040, also etwa 11 %.
- **Ziel:** margin_share < 0,01, Stürze bei 0, Kippanteil ≤ 0,30.
- **Ergebnis (Wächter-Stopp 8.11. 12:47, „Stagnation“ bei 2245, bester Score 2095 mit 0,904):** Der Clip wirkt: target_out_share **0** in allen Bewertungen. margin_share sinkt stetig von 0,87 (1935) über 0,79 (2095) auf **0,48** (2245), die Hüftdrehung entfernt sich also vom Anschlag. Stürze immer 0, Kippanteil 0,17–0,24, Limiter 0,10, echte Schritte 84–87 %. Ruck (0,061–0,066) und Hochfrequenzanteil (0,25–0,28) bleiben über dem Gate.
  - Der Abbruch war verfrüht. Der Score misst nur, ob ein Kriterium besteht, nicht wie weit es entfernt ist, deshalb hat er den Fortschritt bei margin_share kaum abgebildet.

### `servo_rubber19` — Fortsetzung, Gelenkgrenzen-Strafe −12 (gestartet 8.11. 12:50, ab `servo_rubber18` 2245, GPU 0)
- **Änderungen:** `joint_limit_penalty=-12` (statt −8); Wächter mit `MIN_ITERS=500`, damit die Stagnationsregel den laufenden Rückgang von margin_share nicht wieder abschneidet.
- **Ziel:** margin_share < 0,01, Stürze bei 0, Kippanteil ≤ 0,30.
- **Ergebnis (Wächter-Stopp 8.11. 17:29 bei 2745, bester Score 2745 mit 0,903):** margin_share bleibt auf einem Plateau von 0,39–0,54, −12 statt −8 hat nicht weitergeholfen. Bei 2445, 2540, 2650 und 2705 gab es 1–2 Stürze, bei 2745 wieder 0. Kippanteil 0,11–0,26, Limiter 0,10, target_out 0.
- **Analyse (Datensatz 2745):** Der Sollwert der **rechten** Hüftdrehung liegt in 53 % der Schritte genau auf der Klemme bei −1,5° (Median = Klemme). Die Policy will rechts weiter nach außen drehen, als die Grenze von −3° erlaubt. Unter Last gibt das Gelenk über den Sollwert hinaus nach und landet in 40 % der Schritte im Sicherheitsabstand. Links ist das nur in 5 % der Schritte der Fall.

### `servo_rubber20` — Lastreserve in der Klemme (gestartet 8.11. 17:33, ab `servo_rubber19` 2745, GPU 0)
- **Neu:** `action_clip_reserve_deg` hält den Sollwert zusätzlich zum Gate-Rand weiter innen, nie über die Nullstellung hinaus. Auch der Export übernimmt den Wert.
- **Änderungen:** `action_clip_reserve_deg=1.5`. Klemme der Hüftdrehung damit rechts bei 0° (statt −1,5°), links bei +1,0° (statt +2,5°), alle anderen Gelenke bei 6,5° Abstand zur WebUI-Grenze. Die Grenzen selbst kommen weiter aus `hardware/joint_limits.json`. `joint_limit_penalty=-12` bleibt. Wächter mit `MIN_ITERS=400`.
- **Ziel:** margin_share < 0,01 bei 0 Stürzen.
- **Ergebnis (Wächter-Stopp 8.11. 21:50 bei 3200, bester Score 2845 mit 0,960):** Die Lastreserve löst das Grenzproblem. margin_share ist bei 2750 und 2845 **0,000**, bei 2995 0,007, target_out immer 0.
  - 2750, 2845 und 2995 haben 0 Stürze, Kippanteil 0,20–0,21, Limiter 0,10, 88–91 % echte Schritte. **Nur noch Ruck (jerk_p99 ≈ 0,060 statt ≤ 0,04) und Hochfrequenzanteil (0,24–0,27 statt ≤ 0,15) verfehlen das Gate.**
  - Ab 3050 wird es wieder schlechter: je 1 Sturz, margin_share steigt bis 0,12.
- **Videos:** `servo_rubber20/videos/`.

### `servo_rubber21` — Ruck angehen (gestartet 8.11. 22:30, ab `servo_rubber20` 2845, GPU 0)
- **Analyse:** jerk_p99 misst die zweite Differenz der gesendeten (ratenbegrenzten) Sollwerte. 0,060 rad liegt über einem vollen Limiter-Schritt (0,7·3,07 rad/s·0,02 s = 0,043 rad). Die Spitzen entstehen also, wenn ein Gelenk aus der Ruhe mit voller Begrenzer-Geschwindigkeit startet oder abrupt umkehrt.
  - `action_jerk_penalty=-0,1` mittelt über 16 Gelenke und lag im Log bei −0,00002 von 0,04 Gesamtbelohnung, war also wirkungslos.
- **Änderungen:** `action_jerk_penalty=-3` (30-fach), `caps_temporal=12` (statt 6). Wächter mit `MIN_ITERS=300`.
- **Ziel:** jerk_p99 → 0,04, ohne Stürze und ohne dass margin_share zurückkommt.
- **Ergebnis (Wächter-Stopp 9.11. 01:54 bei 3200, bester Score 2995 mit 0,969):** Der Ruck sinkt von 0,062 auf **0,050**. In allen Bewertungen 0 Stürze, der Kippanteil sinkt bis 0,14, Limiter 0,08, 88–95 % echte Schritte. margin_share bleibt bis 2995 unter 0,01 (0,006) und steigt danach langsam auf 0,04.
- **Analyse (Datensatz 3200):**
  - **Ruck:** Die Spitzen über p99 kommen von Knien und Sprunggelenken (rechtes Knie 28 %, rechtes Sprunggelenk 18 %). 43 % davon sind Umkehrungen bei voller Begrenzer-Geschwindigkeit, also Bang-Bang am Limiter; ein Start aus der Ruhe ist nur in 4 % der Fälle die Ursache.
  - **Hochfrequenzanteil:** kein Gipfel über 5 Hz. Die Bänder 5–8, 8–12, 12–18 und 18–25 Hz liegen bei je 0,05–0,07, das ist ein flaches Breitband. Die gesendeten Sollwerte haben denselben Anteil (0,254). Es ist also Rauschen im Policy-Ausgang, kein mechanisches Zittern.

### `servo_rubber22` — Ruck und Ausgangsrauschen (gestartet 9.11. ~05:10, ab `servo_rubber21` 2995, GPU 0)
- **Änderungen:** `action_jerk_penalty=-10` (statt −3), `caps_spatial=12` (statt 6; macht die Policy unempfindlich gegen Rauschen in den Beobachtungen und zielt auf das Breitband). Wächter mit `MIN_ITERS=300`.
- **Ziel:** jerk_p99 ≤ 0,04, highfreq_share sinkt, 0 Stürze, margin_share ≤ 0,01.
- **Ergebnis (Wächter-Stopp 9.11. 08:16 bei 3305, bester Score 3060 mit 0,971; die Benachrichtigung kam erst 20:12, die GPU stand ~12 h still):**
  - **Bestanden in allen Bewertungen:** 0 Stürze, margin_share ≤ 0,005 (3210: 0,000), Limiter 0,06–0,07, Kippanteil 0,17–0,25, 90–94 % echte Schritte.
  - **Noch nicht bestanden:** jerk_p99 stagniert bei 0,047–0,049, highfreq_share bei 0,22–0,25. Die Strafen sind ausgereizt.
- **Export:** 3210 nach `sim/policies/servo_rubber22_step3210/`. Der Clip ist als Max/Min im ONNX, die Abweichung ONNX gegen JAX beträgt 1e-11. **Nicht auf dem Pi.** Das ist der aktuelle Hardware-Kandidat.

### `servo_rubber23` — milder Tiefpass α = 0,5 (gestartet 9.11. 20:14, ab `servo_rubber22` 3210, GPU 0)
- **Begründung:**
  - Früher (servo_ctrl_v3) half der Tiefpass nicht: Gegen die Totzeit-Regelschwingung wirkte er wie zusätzliche Totzeit.
  - Seit `action_history=4` schwingt die Policy nicht mehr. Der Rest-Ruck besteht aus Umkehrungen bei voller Begrenzer-Geschwindigkeit, der Hochfrequenzanteil ist flaches Breitbandrauschen im Ausgang.
  - α = 0,5 lässt ein Zickzack über zwei Schritte nur zu ~33 % durch und fügt ~1 Steuerschritt (20 ms) Totzeit hinzu.
  - Sim, Gate (`sent_targets`) und Pi-Runner (`action_filter_alpha` in `policy_meta.json`) filtern identisch.
- **Änderung:** nur `action_filter_alpha=0.5`. Wächter mit `MIN_ITERS=300`.
- **Ziel:** jerk_p99 ≤ 0,04, highfreq_share runter, ohne Stürze.
- **Ergebnis (Wächter-Stopp 9.11. 23:12 bei 3520; die Benachrichtigung kam erst 11.11. 20:34, die GPU stand ~45 h still):**
  - **Bester Checkpoint 3315, Score 0,992.** Der Filter halbiert den Ruck: jerk_p99 0,019–0,023, das Gate verlangt ≤ 0,04 — **bestanden**.
  - Überall 0 Stürze, margin_share 0,000, Kippanteil 0,14–0,26, Limiter 0,11–0,13, 95–97 % echte Schritte.
  - **Einziges offenes Gate-Kriterium:** highfreq_share 0,17–0,19 (Grenze 0,15).
- **Export:** 3315 nach `sim/policies/servo_rubber23_step3315/` (ONNX = JAX, `action_filter_alpha=0.5` in `policy_meta.json`). **Nicht auf dem Pi.** Das ist der beste Kandidat bisher.

### `servo_rubber24` — Tiefpass α = 0,35 (gestartet 11.11. 20:36, ab `servo_rubber23` 3315, GPU 0)
- **Änderung:** nur `action_filter_alpha=0.35` (statt 0,5). Wächter mit `MIN_ITERS=300`.
- **Ziel:** highfreq_share ≤ 0,15 ohne Stürze.
- **Ergebnis:** Auf Wunsch des Nutzers am 11.11. ~21:45 bei Step 3423 gestoppt (letzter Snapshot 3415), noch ohne Auswertung. Alle Trainings ruhen. `active_runs.txt` ist geleert, Sicherung in `active_runs.txt.bak-2026-11-11`.

### Hardwaretest 11.11. ~21:22–21:35, `servo_rubber23_step3315` (vx 0,04, Gangfrequenz 1,1, α 0,5)
- **Vorab:** Die Winkelgrenzen auf dem Pi sind identisch mit `hardware/joint_limits.json` (16/16), der Policy-Runner ist identisch mit dem im Repo. Hochgeladen wurden nur `policy.onnx` und `policy_meta.json`.
- **Trockenlauf (14,6 s):** Schritt im Mittel 5,6 ms, p99 8,2 ms, 2 Überläufe (max. 25 ms). Kein Sollwert außerhalb der Grenzen, Hüftklemme wie im Sim (rechts ≥ 0°, links ≤ +1,0°).
  - Kopf-IMU: 12,7° Neigung, Betrag 1,09 g. Das Modell erwartet 17,4°, die Abweichung von 5° liegt im Trainingsbereich `imu_tilt_deg=8`.
- **14 echte Läufe:** 2,2 / **10,4** / **14,8 (E-Stop)** / 2,6 / 3,9 / 2,6 / 5,6 (E-Stop) / 2,7 / 2,7 / 2,1 / 6,2 (E-Stop) / 3,9 / 2,5 / 2,3 s. Die übrigen endeten mit Sturzabschaltung (Neigung > 55°).
  - **Nutzer:** „Es wurde mit jedem Mal schlechter und kürzer. Insgesamt lief er immer nach links statt geradeaus. Bei den ersten Versuchen sogar selbstständig mehrere Schritte. Das linke Bein hat mittlerweile sehr viel Spiel."
  - **Log:** Das linke Bein folgt in jedem Lauf schlechter (mittlere Abweichung Soll/Ist 1,4–2,0° gegenüber rechts 1,1–1,6°).
  - In der ersten Sekunde geht der Roboter aus der Mittelpose in dieselbe Gangpose wie im Sim (Hüfte L ≈ 7°, R ≈ 0°, Sprunggelenk R ≈ 14°). Der Anfang verläuft also wie im Sim.
- **Erster Meilenstein:** mehrere selbstständige Schritte auf echter Hardware mit einer Policy, die alle Gelenkgrenzen einhält.
- **Nächster Schritt:** Spiel im linken Bein beheben (Nutzer), dann 2–3 Vergleichsläufe mit gleichen Einstellungen. Logs in `sim/policies/servo_rubber23_step3315/hw_logs_2026-11-11/`.

### Hardwaretest 21.11. 16:44, `servo_rubber23_step3315`, rechtes Bein/Hüfte repariert (Nutzer)
- **Drei Läufe** (vx 0,045, Gangfrequenz 1,125): 17,9 s (E-Stop), 6,0 s (E-Stop), 7,3 s (Sturz, Neigung 75°). Nutzer: zweimal einfach nach vorn gefallen, beim dritten Mal wie zuletzt mehrere Schritte nach links.
- **Beinfolge:** Soll/Ist-Abweichung links 0,9–2,0°, rechts 0,9–1,4°. Der Unterschied ist viel kleiner als am 11.11. (1,4–2,0° gegen 1,1–1,6° bei jedem Lauf).
- **Dynamik viel heftiger als im Sim:** Drehraten der Kopf-IMU im Mittel 36–76 °/s auf allen Achsen, im Sim 60/16/11 °/s (x/y/z). Neigung (aus dem Beschleunigungssensor, enthält Stoßanteile) im Median 18–30°, p95 46–60°, im Sim p95 13°. Jeder Lauf beginnt mit einem Vorwärtsausfall (Neigung 35–55° nach ~1,3–2 s), den die Hüfte abfängt oder nicht.
- **Ruhephase:** Lauf 1 steht von 3,8 s bis 10 s reglos in einer stabilen Pose (linkes Knie 15°, linke Hüftdrehung −13°, rechte Hüftdrehung 0°). Die Policy hat dort nicht gegangen, nur gestanden.
- **Linksdrall steckt schon im Sim:** Alle 16 Sim-Episoden driften nach links (+4 bis +9 cm seitlich bei 16–27 cm vorwärts), der Kurswinkel ist im Mittel kaum verdreht. Das Gate lässt das zu (Seitenverhältnis ≤ 0,26).
- **Sohle:** Kletterschuh-Gummi (Nutzer). Gewicht 2687 g (Nutzer) gegen 2671 g im Modell, also 0,6 % Unterschied.
- **Empfindlichkeits-Sweep im Sim** (Checkpoint 3315, je 16 Episoden à 5 s, Modellvarianten mit veränderter Masse/Schwerpunkt von Rumpf und Rucksack): Basis 0 Stürze; Reibung 0,5/1,3/1,8 0 Stürze; Reibung 2,5 2 Stürze (Fuß klebt, kein Vorwärtskommen); Schwerpunkt +2 cm nach vorn 0 Stürze, +2 cm hoch 0 Stürze, **−2 cm nach hinten 5 Stürze** (Schwerpunkt hinten); Masse +15 %/+30 % 0 Stürze. Die maximale Neigung bleibt in **allen** Szenarien bei 14–16°, real sind es 35–55°. **Keine dieser Störungen erzeugt den Vorwärtsausfall der Hardware.**
- **Zeitverhalten real:** Servo-Verzögerung 2 Schritte (40 ms), wie modelliert. Die IMU-Daten sind im Mittel 13 ms alt (p95 30 ms), das fehlt im Sim.
- **Ursache offen.** Verdächtig: IMU-Latenz, Spiel/Nachgiebigkeit in Sprunggelenken oder Knien, Kontaktgeometrie der Sohle. Logs: `sim/policies/servo_rubber23_step3315/hw_logs_2026-11-21/`.
- **Zeitlupen der Läufe 1 und 2** (WhatsApp, 4-fache Zeitlupe, `media/hw_tests/2026-11-21/190243_*`, `190306_*`, s. [Index](../media/hw_tests/README.md), Seitenansicht, Einstellung vx 0,045 / Gang 1,125 Hz): Der Rumpf steht schon vor dem Start nach vorn geneigt. Lauf 2: Der ganze Körper kippt steif über die vordere Sohlenkante nach vorn. Die Ferse hebt ab, und es kommt kein Ausfallschritt, der ihn fängt. Lauf 1: Er stolpert in kurzen Trippelschritten und **dreht sich dabei um die Hochachse** (am Ende steht er frontal zur Kamera). Das „nach links Laufen“ ist also eher ein Linksdrehen und passt zur Asymmetrie, dass nur die linke Hüftgierung arbeitet. Drei weitere Läufe mit vx 0,03 / Gang 1,0 Hz folgen.
- **Hardware 21.11. ~19:13, `servo_rubber23_step3315`, vx 0,03 / Gang 1,0 Hz** (3 Läufe, Zeitlupen in `media/hw_tests/2026-11-21/1913*`, Logs `hw_logs_2026-11-21/` dazu): 2,5 s (Sturz), 5,3 s (E-Stopp), 1,9 s (Sturz). Kaum besser als mit 0,045/1,125 (1,9/5,2/3,8 s). Die Neigung überschreitet 30° bei 1,2/1,2/0,66 s (vorher immer ~0,62 s), das Kippen beginnt also etwas später, kommt aber trotzdem. Die Gierung dreht in allen 6 Läufen in den ersten 2 s um 16–37° (im Sim praktisch 0). Video (4-fache Zeitlupe, 120 FPS): Er steht ~0,7–1 s still, macht innerhalb von ~0,5–1 s nur 1–2 Schritte mit Drehung und kippt dann steif nach vorn, ohne Ausfallschritt, also schon im ersten Gangzyklus. **Langsamer hilft nicht, der Fehler steckt in den ersten 1–2 Schritten.** Hinweis: `tilt_deg` im Log ist auf `up_in_imu` des Modells bezogen und zeigt im Stand schon 14–16° (Montageversatz Kopf-IMU, Modell 17,2° gegen real 9–13°).
- **Sim/Hardware-Vergleich der ersten 2 s (21.11. abends)** (`hw_logs_2026-11-21/sim_vs_hw_first2s.txt`; Sim: 16 Starts je Befehl, Reibung 0,9). **Ursache gefunden: Der Pi-Runner blendet die ersten 50 Schritte (1 s, `RAMP_STEPS` in `src/pi_service/policy.py`) linear von der Startpose in die Policy-Sollwerte ein, das Sim nicht.** Im Sim ist die Hüftnickung links nach 0,2 s von 18,7° auf ~1° unten, das rechte Sprunggelenk von 0 auf 13°, die linke Hüftgierung auf −11°. Real laufen dieselben Gelenke mit ~13–20 °/s als Rampe und erreichen diese Werte erst nach ~0,9 s. Die Policy gibt anfangs dieselben Sollwerte wie im Sim aus (z. B. linke Hüftgierung −8,5° gegen −8,8°). Während der Rampe hält sie diese Sollwerte, der Gangtakt läuft aber weiter. Wenn die Rampe bei 1 s endet, steht der Roboter in einem Zustand, den sie nie gesehen hat. Dann springen die Sollwerte (Hüftnickung links +20°, Hüftgierung rechts +9–15°), und er kippt nach 1,2 s. Die IMU-Ruhewerte passen dagegen (Sim acc z 2,96 gegen real 2,7–3,2 m/s²).
- **Nebenbefund ksim:** `RLTask.collect_dataset` speichert pro Batch nur Umgebung 0 (`range(0, len(done), batch_size)`). Alle bisherigen Gate-, Sweep- und Validierungs-Auswertungen mit „16 Episoden à 5 s“ waren in Wirklichkeit **eine** Umgebung über 80 s mit genau einem Start. Behelf für Auswertungen: Wrapper mit Stride 1 (scratchpad `cmp/walkfix.py`).










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
- **Fix Startrampe (21.11. abends):** `src/pi_service/policy.py` hat jetzt `LoadedPolicy.ramp_steps`. Policies mit `start_pose=center` bekommen 0 (volle Wirkung ab Schritt 0 wie im Sim), ältere Policies behalten 50. Ein Eintrag `start_ramp_steps` in `policy_meta.json` überschreibt beides, und das Log-Meta enthält den Wert. Test `test_start_ramp_follows_the_trained_start`, `test_policy.py` 26/26 bestanden. Auf den Pi kopiert (Backup `policy.py.bak-2026-11-21`), `zbot-pi` neu gestartet, `servo_rubber23_step3315` lädt mit `ramp_steps 0`. Ratenbegrenzung und Tiefpass starten wie im Sim an der aktuellen Pose.
- **Hardware 21.11. ~21:01, `servo_rubber23_step3315` OHNE Startrampe** (`start_ramp_steps 0`, vx 0,03 / Gang 1,0 Hz, 3 Läufe, Zeitlupen `media/hw_tests/2026-11-21/2101*`): 2,2 s, 1,7 s, 2,3 s, alle drei Sturz (Neigung > 30° nach 0,7–0,9 s). Vergleich mit dem Sim (`sim_vs_hw_first2s_noramp.txt`): **Die ersten 0,4 s stimmen jetzt Gelenk für Gelenk mit dem Sim überein** (Hüftnickung 18,7°→0°, Knie, Sprunggelenk, Hüftrollen, Policy-Sollwerte), und er macht von Anfang an echte Schritte (Video). **Neuer Hauptunterschied: Gierrate** (Roh-gyro_y = Körper-Hochachse). Beim ersten Umstellen (0,2 s, linke Hüftgierung auf −11° bei beiden Füßen am Boden) dreht sich der echte Körper mit 64–88 °/s, im Sim mit 4 °/s (p90 19). Auch im Gang ist die Gierrate 2–3-mal größer. Die rechte Hüftgierung bleibt laut Encoder auf 0. Also verdreht sich entweder der rechte Fuß auf dem Boden, oder im rechten Bein bzw. in der Hüfte gibt etwas um die Hochachse nach. Im Sim hält die flache Fußbox mit Eckkontakten (Paar-condim 3, μ 1,1) gegen Verdrehung voll. Die Nick- und Rollraten liegen näher am Sim (gyro_x 60–95 gegen 39 °/s bei 0,1 s).
- **Hardware 22.11. ~12:56, `servo_rubber23_step3315`, ohne Startrampe, linke Hüfte fixiert (saß locker)**, vx 0,03 / Gang 1,0 Hz, 6 Läufe (Zeitlupen `media/hw_tests/2026-11-22/`, 3 seitlich, 3 von oben; von oben sind die Füße vom Rucksack verdeckt). Dauer 1,4 / 2,4 / 1,1 / 1,7 / 2,2 / 2,3 s, zwei Stürze und vier E-Stopps. Gierung in den ersten 2 s −8 bis +73°. Die neigungsbasierte Schwelle „> 30° nach 0,24 s“ ist hier ein Beschleunigungsartefakt des Umstellruckens (acc_x 4 m/s²), kein echtes Kippen. **Die Gierspitze beim ersten Umstellen bleibt: 76–94 °/s nach 0,2 s (Sim 4 °/s)**, also nicht vom Hüftspiel verursacht. Handtest des Nutzers (Rumpf in Center-Pose bei Bodenkontakt um die Hochachse gedreht): kein Spiel, nur leichte elastische Torsion. Schluss: Die Policy macht beim Start im Doppelstand eine schnelle Hüftgier-Bewegung (−11° in 0,2 s), die im Sim die Füße abfangen (Fußbox, 4 Ecken, μ 1,1). Real dreht dabei der Körper samt rechtem Fuß und Bein mit. Logs `hw_logs_2026-11-22/`, Vergleich `report_d.txt`.
- **23.11., Torsions-Handtest und Sim-Fußgierung: Die echten Füße drehen nicht, die Sim-Füße schon.** Fotos `media/hw_tests/2026-11-23/` (3× Füße mit Krepp-Marken, 3× von oben, ohne Moment, im und gegen den Uhrzeigersinn per Hand). Die Sohlen bleiben auf allen Fotos an den Marken. Gegen den Uhrzeigersinn gibt der Körper etwa 3° elastisch nach, im Uhrzeigersinn ist nichts zu sehen. Gegenprüfung im Sim (`slow2`, 16 Starts, Vorwärtskinematik aus `qpos`): Zwischen 0,1 und 0,26 s trägt **der linke Fuß allein** (≈ 22 N, rechter Fuß in der Luft). Die Policy dreht dabei die linke Hüftgierung auf −11°, und **der belastete linke Fuß dreht sich im Sim um −5° auf dem Boden** (p10 −6,8° bei 0,2 s). Der Rumpf bleibt fast stehen (+0,5°). Real haftet die Gummisohle, also dreht stattdessen der Körper: Das integrierte gyro_y liegt bei 0,3 s bei +6 bis +10° und bleibt dort, federt also nicht zurück. Das passt zur Größe der Hüftbewegung. **Die frühere Vermutung kehrt sich damit um: Nicht die Hardware ist zu weich gegen Verdrehen, sondern die Sim-Sohle hält kein Bohrmoment.** Der Kontakt `Foot_collision_box`–`floor` hat condim 3, die Torsionsreibung 0,005 im `<pair>` wird damit gar nicht ausgewertet. Die Policy hat gelernt, dass eine Hüftgier-Bewegung im Standbein den Fuß dreht statt den Körper. Folge für ein Retraining (noch nicht freigegeben): Fußkontakt mit condim 4/6 und realistischer Torsionsreibung, statt Torsionsnachgiebigkeit einzubauen. Nachtrag 24.11.: Die Sim-Sohle steht in dieser Phase 5–10° schräg (max. 14°), meist mit nur einem Kontaktpunkt. Damit fehlt auch der Hebelarm mehrerer Ecken, und der Fuß dreht frei. Übersicht aller Policies mit Fußmodell und Reibung: [policy-friction.md](policy-friction.md).
- **24.11., Sim-Test Bohrreibung (kein Training):** `servo_rubber23_step3315`, 16 Starts, vx 0,03 / Gang 1,0 Hz, μ 0,9. Die Fußpaare laufen mit `condim 4` und einer Bohrreibung von 0,01, 0,03, 0,1 und 0,3 m. Das Repo-Modell bleibt unverändert, die Varianten liegen nur im Scratchpad. Zum Vergleich die Basis (`condim 3`) und die 6 Hardwareläufe vom 22.11.:

  | Variante | gyro_y bei 0,1 / 0,2 / 0,3 s (°/s) | Rumpfgier bei 0,2 / 0,3 / 0,4 s | linker Fuß gier bei 0,2 s | Stürze | \|Gier\| nach 5 s |
  |---|---|---|---|---|---|
  | Hardware 22.11. | −14 / **85** / 20 | 4,3 / 8,5 / 9,0° | (fest, Fotos) | – | – |
  | Basis condim 3 | 2 / 4 / 20 | 0,5 / 2,6 / 4,1° | −5,0° | 1/16 | 15° |
  | condim 4, 0,01 | 4 / 9 / 20 | 0,7 / 2,9 / 4,7° | −4,8° | 2/16 | 13° |
  | condim 4, 0,03 | 11 / 13 / 19 | 1,9 / 4,3 / 6,4° | −3,6° | 2/16 | 12° |
  | condim 4, 0,1 | 20 / 13 / 15 | 2,8 / 4,6 / 7,1° | −2,7° | 3/16 | 34° |
  | condim 4, 0,3 | 24 / 14 / 13 | 3,2 / 4,6 / 7,3° | −2,1° | 4/16 | 38° |

  **Ergebnis:**
  - Je fester der Fuß hält, desto mehr dreht der Rumpf mit. Nach 0,4 s sind es 7° statt 4°, nahe an den 9° der Hardware.
  - Die Policy wird dabei schlechter: Die Stürze steigen von 1/16 auf 3–4/16, und die Gierabweichung nach 5 s steigt von 15° auf 34–38°. **Sie verlässt sich also darauf, dass der Fuß sich drehen kann.** Das spricht für ein Retraining mit Bohrreibung.
  - **Nicht nachgebildet wird die schmale Spitze von 85 °/s bei 0,2 s.** Im Sim liegt die Gierrate auch bei festem Fuß nur bei 13–24 °/s, mit dem Maximum schon bei 0,1 s. Auch der Rumpfwinkel bei 0,3 s ist real doppelt so groß. Die Hardware hat also zusätzlich etwas Nachgiebiges oder Schnelles um die Hochachse, zum Beispiel den Kopf mit der IMU am Hals, das Spiel im Hüftgier-Servo oder die Torsion der Beine. Die Bohrreibung allein erklärt die Abweichung nicht.
- **25.11., Nutzer:** „der Kopf bewegt sich auf dem Rumpf kein bisschen“. Hals scheidet aus.
- **25.11., Starrkörper-Gegenrechnung** (`sim/tools/hw_kin_yaw.py`): Aus den gemessenen Gelenkwinkeln allein wird berechnet, wie weit sich der Rumpf drehen müsste, wenn der linke Fuß fest steht und der Roboter starr ist. Am Sim geprüft: Vorhersage plus wahre Fußdrehung trifft die wahre Rumpfgier auf ≤ 1°, das integrierte gyro_y ebenfalls.

  | t | 0,1 s | 0,2 s | 0,3 s | 0,4 s | 0,6 s |
  |---|---|---|---|---|---|
  | HW starr, Fuß fest (Mittel 6 Läufe) | 5,6° | 7,3° | 6,9° | 6,4° | 5,6° |
  | HW integriertes gyro_y | −0,4° | 4,3° | 8,5° | 9,0° | 10,6° |
  | Sim starr, Fuß fest | 4,1° | 6,0° | 6,2° | 5,7° | 5,0° |
  | Sim wahre Rumpfgier | −0,2° | 0,5° | 2,6° | 4,1° | 5,9° |

  **Befund:**
  - In den ersten 0,1 s dreht die Hüftgierung den Rumpf auf der Hardware gar nicht, obwohl er starr schon 5,6° weit sein müsste. Die Hardware verhält sich hier wie der Sim, nur ohne Fußdrehung: Etwas zwischen Servo-Abtrieb und Boden verdreht sich um etwa 5–6°.
  - Zwischen 0,1 und 0,3 s holt der Rumpf das nach und schießt über die starre Lage hinaus (8,5 statt 6,9°). Das ist die Gierspitze von 85 °/s.
  - **Signatur einer Torsionsfeder, die erst aufgezogen wird und dann losschnellt.** Im Sim rutscht der Fuß stattdessen dauerhaft weg.
  - Die Richtung passt zum Handtest: Der Start dreht den Rumpf gegen den Uhrzeigersinn (gyro_y > 0, von oben gesehen), und nur in diese Richtung hat der Nutzer ein Nachgeben gesehen.

  **Kandidaten:**
  - Scherung der Gummisohle (3–4 mm Kletterschuhgummi, geklebt)
  - Fuß- oder Sprunggelenkhalter
  - Torsion der PETG-Beinteile
  - Servohorn oder Getriebespiel der linken Hüftgierung, falls der Encoder hinter dem Spiel misst
- **25.11., Nutzer:** „es ist eigentlich auch egal, was die genaue Ursache ist. Die Policie muss robust gegen ein gewisses Gelenkspiel und Elastizitäten sein“.
- **25.11., Sim-Erweiterung Gelenkspiel und Elastizität** (`sim/train/common.py`, `joint_compliance`, Standard aus):
  - **Modell:** Jedes Beinservo treibt nur noch seinen eigenen Abtrieb θ_s. Das ist der Wert, den der Encoder liest. Das Glied hängt über eine Totzone ±Spiel und eine Feder k (Dämpfung k·5 ms) daran.
  - **Lösung je Physikschritt:** Der Abtrieb ist masselos. Das Servo-Drehmoment (Duty-Gesetz auf θ_s) ist gleich dem Federmoment und wird per Bisektion gelöst, eindeutig, weil die eine Seite fällt und die andere steigt.
  - **Beobachtung:** Die Policy sieht θ_s und dessen Geschwindigkeit, wie am Pi. Die Netzeingänge bleiben gleich, alte Checkpoints laufen also weiter.
  - **Zufallswerte je Episode:**
    - Hüftgierung: Spiel 0–2° je Seite, k 8–60 Nm/rad
    - Hüftrollen: Spiel 0–1°, k 60–400
    - Hüftnicken, Knie, Sprunggelenk: Spiel 0–0,5°, k 200–1000 Nm/rad (steif gehalten, weil die gemessenen 45 Nm/rad schon im Servo stecken)
    - Arme: unverändert direkt
    - `compliance_prob` regelt den Anteil der Episoden mit Spiel.
  - **Fußkontakt:** dazu `foot_condim` (4 = mit Bohrreibung) und `foot_torsion` (Bereich in m, je Umgebung).
  - **Tests:** `sim/tests/test_joint_compliance.py` (14 Tests): steife Feder ohne Spiel = altes Servo, statische Auslenkung = Spiel + Reihenfedern, im Spiel wird nichts übertragen, Sättigung, Ziehen je Episode, ohne Spiel identisches Moment, Sprungantwort stabil. Mit `test_servo_model.py` und `test_foot_friction.py` zusammen 50/50 bestanden.
- **25.11., `servo_rubber23_step3315` im erweiterten Sim** (16 Starts, vx 0,03 / 1,0 Hz, μ 0,9, `condim 4`, Bohrreibung 0,02–0,04 m, kein Training):

  | Variante | Stürze | Tempo | seitlich/vorwärts (Median) | \|Gier\| nach 5 s |
  |---|---|---|---|---|
  | wie trainiert (`condim 3`, starr) | 1/16 | 0,034 m/s | 0,15 | 13° |
  | nur Bohrreibung 0,03 | 2/16 | 0,025 m/s | 0,14 | 14° |
  | + Spiel/Elastizität zufällig | 2/16 | 0,035 m/s | **0,74** | 21° |
  | + Hüftgierung k 10, Spiel bis 2° | 2/16 | 0,022 m/s | 0,36 | 10° |

  - **Folgen für die Policy:** Mit Spiel und Elastizität läuft sie nicht mehr gerade. Der seitliche Versatz steigt auf das Fünffache. Sie ist dagegen also nicht robust.
  - **Was sich jetzt deckt:** Der Sim-Fuß hält jetzt (−1,6° statt −5°), und der Rumpf folgt der Starrkörper-Vorhersage.
  - **Was noch fehlt:** Die Hardware-Signatur entsteht noch nicht. Die Hardware steht bis 0,1 s still und dreht bei 0,3 s schon um 8,5°. Der Sim dreht dagegen sofort mit (1,5° bei 0,1 s) und kommt bei 0,3 s nur auf 4,5–5°.
  - **Mögliche Erklärung, offen:** Der Sim hebt den rechten Fuß schon nach 0,1 s ab. Real steht er vermutlich länger, hält den Rumpf gegen die drehende linke Hüfte und gibt ihn beim Abheben frei. Prüfbar an den Zeitlupen.

### `servo_comp1`: Feintuning ab `servo_rubber23` 3315 mit Gelenkspiel, Elastizität und Bohrreibung (gestartet 25.11., GPU 0)
- **Nutzer:** „ja, starte das Training so“
- **Start:** `GPU=0 ASSETS=zbot-cad-tpu sim/tools/train_backpack.sh servo_comp1 …` mit allen Einstellungen von `servo_rubber24` (μ 0,5–1,3, Filter α 0,35, Ratenbegrenzer 70 %, Aktionsverlauf 4, Totzeit ±20 ms, IMU ±8°, Startpose Mitte). Neu:
  - `joint_compliance=True compliance_prob=0.8`: Spiel und Elastizität in 80 % der Episoden, Bereiche wie oben.
  - `foot_condim=4 foot_torsion=0.01,0.05`: Bohrreibung der Sohle je Umgebung.
- **Lauf:** ab `servo_rubber23/snapshots/ckpt.3315.bin` bis Schritt 6315.
- **Wächter:** `zbot-calmwatch-servo_comp1`, alle 40 Iterationen, Bewertung auf GPU 1, Videos alle 100.
- **Bewertung jetzt echt:**
  - `sim/train/walking.py` korrigiert den ksim-Fehler in `collect_dataset` beim Import. Er schrieb nur Umgebung 0 je Batch.
  - `calm_watch.py`, `sweep_snapshots.sh`, `validate_policy.sh` und `long_walk.sh` nehmen jetzt einen Batch mit 16 Umgebungen, also 16 echte Starts.
  - Die Bewertung läuft mit den Einstellungen des Laufs, also mit Spiel und Elastizität.
- **Neues Gate-Kriterium:** `lateral_ratio` ≤ 0,25 (Median des Verhältnisses seitlicher zu Vorwärts-Versatz, `hardware_gate.py`). `servo_rubber23` hat starr 0,15, mit Spiel 0,89.
- **Vergleichbarkeit:** Werte aus früheren Wächter-Läufen (ein Start, 80 s) sind mit den neuen nicht direkt vergleichbar.
- **Ergebnis `servo_comp1` (25.11. 11:45, Wächter: Stagnation bei 3760, nach 450 Iterationen):**
  - Bester Score 0,920 bei 3565, Gate nicht bestanden.
  - **Seitlicher Versatz** (`lateral_ratio`) 0,59 → 0,33–0,41 (Grenze 0,25).
  - **Stürze:** 0/16 bei 3465–3565, danach wieder 1–2.
  - **Weitere offene Kriterien:**
    - `highfreq_share` 0,21–0,23 (Grenze 0,15). Mit Spiel schon am Startpunkt 0,23, starr 0,17.
    - `foot_tilt_over5_share` 0,35–0,39 (Grenze 0,30)
    - `margin_share` 0,02–0,03 (Grenze 0,01)
  - Echte Schritte nur 30–41 %.
  - **Bewertung:** Mit 16 echten Starts streut der Score stärker (1–2 Stürze kommen und gehen). Die Regel „+3 % in 6 Bewertungen“ hat den Lauf zu früh beendet, obwohl der Versatz noch fiel.
- **`servo_comp2`** (25.11. 17:57, GPU 0; die GPU stand von 11:45 bis 17:57 still, weil mich die Meldung vom Ende von `servo_comp1` erst spät erreichte): weiter ab `servo_comp1` 3565 mit unveränderten Einstellungen, 3000 Iterationen. Der Wächter hat ein Fenster von 12 Bewertungen und prüft Stagnation erst ab 600 Iterationen. Dafür hat `launch_continue.sh` die neue Option `WINDOW`.
- **Ergebnis `servo_comp2` (26.11. 01:08, Wächter: Stagnation bei 4270, nach 705 Iterationen):**
  - Bester Score 0,926 bei 4220, Gate nicht bestanden. Ab 3825 meist 0 Stürze, vereinzelt 1/16.
  - Plateau über alle offenen Kriterien: `lateral_ratio` 0,28–0,41, `highfreq_share` 0,20–0,23, `foot_tilt_over5_share` 0,37–0,46 (schlechter als `servo_comp1`), `margin_share` 0,02–0,07.
  - Echte Schritte fallen von 0,40 auf 0,23: Die Policy schlurft zunehmend.
  - **Lehre:** Mit unveränderten Gewichten bringt Weitertrainieren nichts mehr. Die Belohnung muss sich ändern.
### `servo_comp3`: Versatz und Fußneigung stärker bestraft (gestartet 26.11. ~01:20, ab `servo_comp2` 4220, GPU 0)
- **Änderungen:** `lateral_position_penalty` −0,5 → −2,0, `gait_lateral_penalty` −1,0 → −3,0, `foot_flat_penalty` −50 → −80. Sonst alles wie `servo_comp2`.
- **Ziel:** `lateral_ratio` ≤ 0,25 und `foot_tilt_over5_share` ≤ 0,30 ohne Stürze. Den Anteil echter Schritte im Blick behalten.
- **Lauf:** 3000 Iterationen. Wächter mit Fenster 12 und `MIN_ITERS=400`, Video alle 100.
- **Ergebnis `servo_comp3` (26.11. 11:02, Wächter: Stagnation bei 4640, nach 420 Iterationen):**
  - Bester Score 0,934 bei 4565, Gate nicht bestanden. Durchgehend 1/16 Stürze.
  - `lateral_ratio` 0,26–0,42 (bester Wert 0,26 bei 4515), kaum besser als `servo_comp2`. `foot_tilt_over5_share` 0,39 → 0,36, `margin_share` 0,03 → 0,006 (jetzt bestanden).
  - `highfreq_share` unverändert 0,23–0,25 (Grenze 0,15). Echte Schritte 0,25 → 0,23.
  - **Analyse highfreq (Rollout 4640, je Gelenk):** Schon die rohe Aktion hat 15–53 % Anteil über 5 Hz, am stärksten rechtes Knie (0,53), rechtes Sprunggelenk (0,47) und rechte Hüfte nickend (0,34). Das Zittern kommt also aus der Policy, nicht aus der Feder des Spielmodells.
  - Die GPU stand von 11:02 bis 20:15 still (kein Supervisor aktiv).
### `servo_comp4`: Tiefpass α 0,35 → 0,25 (gestartet 26.11. ~20:15, ab `servo_comp3` 4565, GPU 0)
- **Änderung:** nur `action_filter_alpha=0.25`. Belohnungen wie `servo_comp3`. Bei α 0,25 kommt der Gang mit ~1,2 Hz noch fast ungedämpft durch, 10 Hz deutlich schwächer (vgl. Hilfetext in `common.py`).
- **Ziel:** `highfreq_share` ≤ 0,15 ohne Stürze, `lateral_ratio` und Fußneigung nicht schlechter.
- **Lauf:** 3000 Iterationen bis 7565. Wächter mit Fenster 12, `MIN_ITERS=600`, Video alle 100.
- **Ergebnis `servo_comp4` (27.11. 02:52, Wächter: Stagnation bei 5170, Fenster 12):**
  - Bester Score 0,946 bei 5170, dem letzten bewerteten Schritt. Gate nicht bestanden.
  - **Erstmals bestanden:** `lateral_ratio` 0,24 und `foot_tilt_over5_share` 0,24. Die Fußneigung fiel stetig von 0,34 auf 0,24.
  - **Offen:**
    - Stürze: weiter 1/16, immer früh, bei 5170 nach 0,84 s.
    - `highfreq_share` 0,23–0,25, unverändert.
    - `limiter_share` 0,21–0,235 (Grenze 0,20). Neu durchgefallen, die Folge des stärkeren Filters.
  - **Analyse:** Der stärkere Filter hat das Zittern nicht gesenkt.
    - Über 5 Hz liegen in den gefilterten Sollwerten weiter 0,6–0,8° RMS an der rechten Hüfte (nickend) und am rechten Sprunggelenk, wie bei `servo_comp3`.
    - Die Policy gleicht den Filter also mit stärkerem rohem Zickzack aus. Die Strafen auf die rohe Aktion (Jerk, CAPS) greifen dort nicht.
    - Als Leistungsanteil sind es nur 1–11 % je Gelenk. `highfreq_share` summiert Betragsspektren und bewertet den Breitbandboden deshalb stark.
  - Die GPU stand von 02:52 bis 06:55 still. Die Meldung des Weckers kam erst spät an.
### `servo_comp5`: Strafe auf die Gelenkbeschleunigung (gestartet 27.11. ~06:55, ab `servo_comp4` 5170, GPU 0)
- **Änderung:** `joint_accel_penalty=-3.0`. Erster Einsatz von `JointAccelerationPenalty`, also mittleres (qvel(t) − qvel(t−1))² der Gelenke selbst. Damit trifft die Strafe das Zittern dort, wo es entsteht, also hinter Filter und Spiel.
  - Bei 5170 liegt der Rohwert bei 0,048. Mit −3 wiegt die Strafe etwa 6 % der Gesamtbelohnung, ähnlich wie `foot_flat`.
  - Filter α bleibt 0,25, sonst alles wie `servo_comp4`.
- **Ziel:** Zittern weg (`highfreq_share` ≤ 0,15) bei gleichbleibendem `lateral_ratio` und gleicher Fußneigung.
- **Lauf:** 3000 Iterationen. Wächter mit Fenster 12, `MIN_ITERS=600`, Video alle 100.
- **Ergebnis `servo_comp5` (27.11. 14:30, Wächter: Stagnation bei 5810, Fenster 12):**
  - Bester Score **0,978 bei 5515**, der bisher beste Wert mit Spiel und Elastizität. Gate nicht bestanden.

  | Schritt | Stürze | `highfreq_share` | `limiter_share` | `lateral_ratio` | Fußneigung > 5° | echte Schritte | Tracking |
  |---|---|---|---|---|---|---|---|
  | 5170 (Start) | 1/16 | 0,236 | 0,234 | 0,26 | 0,24 | 0,23 | 1,02 |
  | 5415 | 1/16 | 0,241 | 0,205 | 0,25 | 0,22 | 0,23 | 0,92 |
  | **5515** | **0/16** | 0,227 | 0,215 | **0,17** | **0,18** | 0,17 | 1,02 |
  | 5660 | 2/16 | 0,233 | 0,216 | 0,29 | 0,19 | 0,16 | 1,03 |
  | 5810 (Ende) | 1/16 | 0,242 | 0,189 | 0,15 | 0,17 | 0,11 | 0,89 |

  - **Besser geworden:** Fußneigung 0,24 → 0,17, Begrenzer 0,23 → 0,19 (am Ende bestanden). Das Tracking bleibt im Band.
  - **Unverändert:** `highfreq_share` 0,23–0,25, im dritten Lauf hintereinander trotz drei verschiedener Maßnahmen (Belohnungen in `servo_comp3`, Filter in `servo_comp4`, Beschleunigungsstrafe hier). Stürze bis auf 5515 weiter 1–2/16.
  - **Schlechter geworden:** Der Anteil echter Schritte fällt von 0,23 auf 0,11. Die Policy schlurft immer mehr. Dieser Trend läuft schon seit `servo_comp2` (0,40). Laut Log sind die Gangterme winzig: `swing_duration` 0,0009 und `stride_length` 0,0003 je Schritt, gegen 0,043 für das Tempo-Tracking und 0,023 für den Vorwärtsfortschritt.
  - **Analyse:** Die Beschleunigungsstrafe war zu schwach, um etwas zu zeigen. Im Trainingslog liegt sie bei −0,0011 je Schritt und ist über 640 Iterationen nur um 17 % gefallen (−0,00135 → −0,00113). Das sind etwa 1,5 % der positiven Belohnung (~0,075), nicht die 6 %, die ich beim Start geschätzt hatte. Aussagekräftig ist der Lauf für die Strafe also noch nicht.
  - Eigene Zusatzauswertungen (absolutes HF-RMS je Gelenk, Reibungs-Sweep) waren in dieser Supervisor-Sitzung nicht möglich: Python-Aufrufe wurden nicht freigegeben. Offen bleibt deshalb, ob der HF-Anteil im Gelenkwinkel aus dem Spielmodell selbst kommt. Starr lag `servo_rubber23` bei 0,17, mit Spiel schon am Start bei 0,23.
### `servo_comp6`: Beschleunigungsstrafe vervierfacht (gestartet 27.11. ~14:45 vom Supervisor, ab `servo_comp5` 5515, GPU 0)
- **Änderung:** nur `joint_accel_penalty` −3 → −12. Damit wiegt die Strafe etwa 6 % der positiven Belohnung, so viel, wie für `servo_comp5` gedacht war. Sonst alles wie `servo_comp5`.
- **Warum:** `highfreq_share` ist das einzige Gate-Kriterium, das in keinem Lauf seit `servo_comp3` gesunken ist. Die Gelenkbeschleunigung gewichtet hohe Frequenzen mit ω² und trifft damit genau das, was der Gate-Wert misst (Gelenkwinkel der Beine über 5 Hz). Start bei 5515, weil dort als einzigem Schritt Stürze, Versatz und Fußneigung zugleich bestanden waren.
- **Risiko:** Die Policy könnte noch mehr schlurfen. Der Anteil echter Schritte ist deshalb das Abbruchsignal: Sinkt er unter ~0,08, ohne dass der HF-Anteil fällt, ist die Strafe der falsche Hebel. Dann als Nächstes Gangterme stärken oder den HF-Anteil starr gegen das Spielmodell auswerten.
- **Lauf:** 3000 Iterationen bis 8515. Wächter mit Fenster 12, `MIN_ITERS=600`, Video alle 100, Bewertung auf GPU 1.
- **Zwischenstand 27.11. 19:57 (Schritt 6016, nach ~500 Iterationen, manuelle Kontrolle):**
  - Bester Score bisher 0,970 bei 5960 (0/16 Stürze). Sonst meist 1–2/16.
  - Fußneigung > 5° weiter fallend: 0,19 → 0,14.
  - `highfreq_share` unverändert 0,23–0,25. Die Strafe selbst ist um 25 % gesunken (−0,0046 → −0,0035 je Schritt). Die Policy senkt also die Gelenkbeschleunigung, das Gate-Maß reagiert aber nicht. Das spricht dafür, dass der HF-Anteil aus dem Spielmodell kommt und nicht aus der Policy.
  - Echte Schritte 0,20 → 0,12–0,13, über der Abbruchschwelle 0,08. `lateral_ratio` 0,18–0,30, `limiter_share` um 0,21.
  - Kein Eingriff. Der Wächter prüft Stagnation ab Iteration 600 (Schritt ~6115), danach übernimmt der Supervisor-Timer.
  - **Nächster Kandidat, falls der Lauf stagniert:** den HF-Anteil eines Checkpoints starr (ohne `joint_compliance`) gegen mit Spiel auswerten. Liegt er starr unter 0,15, muss das Gate-Maß für Läufe mit Spiel angepasst werden, nicht die Policy.
- **Ergebnis `servo_comp6` (28.11. ~01:20, Wächter: Stagnation bei 6516, Fenster 12):**
  - Bester Score **0,979 bei 6115**, knapp über `servo_comp5` (0,978). Gate nicht bestanden, offen nur noch `highfreq_share` und `limiter_share` (0,20–0,215, Grenze 0,20).

  | Schritt | Stürze | `highfreq_share` | `limiter_share` | `lateral_ratio` | Fußneigung > 5° | echte Schritte | Tracking |
  |---|---|---|---|---|---|---|---|
  | 5516 (Start) | 1/16 | 0,239 | 0,214 | 0,23 | 0,19 | 0,20 | 1,01 |
  | 5960 | 0/16 | 0,243 | 0,209 | 0,27 | 0,16 | 0,12 | 0,91 |
  | **6115** | **0/16** | 0,245 | 0,201 | 0,25 | 0,15 | 0,10 | 0,87 |
  | 6260 | 0/16 | 0,247 | 0,200 | 0,18 | 0,13 | 0,06 | 0,88 |
  | 6516 (Ende) | 0/16 | 0,246 | 0,213 | 0,13 | 0,14 | **0,05** | 0,94 |

  - **Gut:** Ab 6115 durchgehend 0/16 Stürze, Fußneigung 0,19 → 0,14, `lateral_ratio` am Ende 0,13. Das sind die besten Werte bisher mit Spiel und Elastizität.
  - **Schlecht:** Der Anteil echter Schritte fiel von 0,20 auf 0,05, unter die beim Start festgelegte Abbruchschwelle 0,08. Die Policy schlurft fast nur noch. `highfreq_share` blieb trotz vierfacher Beschleunigungsstrafe bei 0,24–0,25.
  - **Starr gegen Spiel (Supervisor, 16 Starts auf GPU 1, `joint_compliance=False`):** 6115 starr hat `highfreq_share` **0,233**, mit Spiel 0,245. **Die Vermutung vom 27.11. ist damit widerlegt: Der HF-Anteil kommt nicht aus dem Spielmodell, sondern aus der Policy.** Starr macht dieselbe Policy übrigens mehr echte Schritte (0,35), kippt die Füße aber stärker (0,35) und fällt 1/16.
  - **Absolut ist das Zittern klein:** Über 5 Hz sind es im Mittel 0,4° RMS je Beingelenk (rechte Hüfte nickend 0,85–0,90°, rechtes Sprunggelenk 0,75°), das ist nur 1,6–1,8 % der Bewegungsleistung. `highfreq_share` summiert Betragsspektren, und von 0–25 Hz liegen 80 % der Frequenzstützstellen über 5 Hz. Der Breitbandboden zählt deshalb stark, und je kleiner die Gangbewegung, desto größer der Anteil. **Schlurfen treibt das Gate-Maß also eher nach oben.** Ein Gate auf absolutes HF-RMS (z. B. ≤ 0,5°) wäre aussagekräftiger. Ich ändere das Gate aber nicht eigenmächtig, damit die Läufe vergleichbar bleiben; Vorschlag an den Nutzer.
  - **Gangbild:** Rechtes Knie bewegt sich im Gangband (< 3 Hz) nur 0,9° RMS, linkes 6°. Der Roboter schiebt das rechte Bein mehr, als er es hebt.
  - **Belohnungsanteile im Log (je Schritt):** Tempo-Tracking 0,048, Vorwärtsfortschritt 0,024, Schwungdauer nur **0,0007**, Schrittlänge 0,00016, Bodenfreiheit 0,0001. Echtes Schreiten bringt der Policy praktisch nichts, das Tempo bekommt sie auch schlurfend.
- **Lehre:** Die Beschleunigungsstrafe ist der falsche Hebel gegen `highfreq_share`. Sie senkte die Gelenkbeschleunigung (Strafe −25 %), das Gate-Maß nicht, und förderte das Schlurfen.
### `servo_comp7`: Schwungbelohnung vervierfacht (gestartet 28.11. ~01:30 vom Supervisor, ab `servo_comp5` 5515, GPU 0)
- **Änderung:** nur `gait_swing_reward` 2 → 8 gegenüber `servo_comp5`. Die Beschleunigungsstrafe bleibt damit bei −3 wie in `servo_comp5`; die −12 aus `servo_comp6` werden nicht übernommen, weil sie nichts gebracht haben.
- **Warum:** Das drängendste Problem ist das Schlurfen (echte Schritte 0,40 in `servo_comp2` → 0,05). Die Schwungbelohnung (dicht, +1 je Schritt eines Schwungs von 0,25–0,6 s, Rampe bei kürzeren) misst fast genau das, was `real_step_share` zählt. Mit 8 kann ein echter Gang mit ~40 % Schwungzeit etwa so viel einbringen wie das Tempo-Tracking. Start bei 5515 statt 6115, weil dort noch 17 % echte Schritte waren und die Policy noch nicht auf die starke Beschleunigungsstrafe eingestellt ist. 5515 hatte ebenfalls 0/16 Stürze, Versatz 0,17 und Fußneigung 0,18.
- **Ziel:** `real_step_share` deutlich über 0,2, ohne Stürze, Fußneigung ≤ 0,30, `lateral_ratio` ≤ 0,25. Nebenbei prüfen, ob `highfreq_share` mit größerer Gangbewegung fällt.
- **Risiko:** Mehr Schwungphasen können mehr Stürze und mehr Fußneigung bringen. Steigen die Stürze dauerhaft auf ≥ 2/16, ist 8 zu viel (dann z. B. 4).
- **Lauf:** 3000 Iterationen bis 8515. Wächter mit Fenster 12, `MIN_ITERS=600`, Video alle 100, Bewertung auf GPU 1.
- **Ergebnis `servo_comp7` (28.11. ~07:52, Wächter: „Stagnation“ bei 6120, nach 605 Iterationen):**
  - Bester Score 0,978 ist der **Startpunkt 5515** selbst. Gate nicht bestanden, offen `highfreq_share` und `limiter_share`.

  | Schritt | Stürze | `highfreq_share` | `limiter_share` | `lateral_ratio` | Fußneigung > 5° | echte Schritte | Tracking |
  |---|---|---|---|---|---|---|---|
  | 5515 (Start) | 0/16 | 0,240 | 0,208 | 0,25 | 0,20 | 0,19 | 1,00 |
  | 5763 | 2/16 | 0,236 | 0,218 | 0,27 | 0,20 | 0,26 | 0,99 |
  | 5815 | 2/16 | 0,247 | 0,217 | 0,25 | 0,20 | **0,28** | 0,97 |
  | 6020 | 1/16 | 0,241 | 0,212 | 0,19 | 0,17 | 0,18 | 0,93 |
  | **6120 (Ende)** | **0/16** | 0,243 | 0,215 | **0,18** | **0,17** | **0,24** | 1,02 |

  - **Die Schwungbelohnung wirkt:** Der Anteil echter Schritte stieg von 0,19 auf 0,24–0,28. Der Abwärtstrend seit `servo_comp2` ist damit erstmals umgekehrt. Dazwischen gab es 1–2/16 Stürze, am Ende wieder 0/16. `lateral_ratio` und Fußneigung wurden besser (0,25 → 0,18 und 0,20 → 0,17), das Tracking blieb im Band.
  - **Unverändert:** `highfreq_share` 0,23–0,25 und `limiter_share` 0,21–0,22. Mit etwas mehr Schritten fiel der HF-Anteil also nicht.
  - **Warum der Lauf endete:** Das lag nicht an der Policy, sondern an der Stagnationsregel. Der Score hat 1,0 als Obergrenze. Bei einem Start mit 0,978 müsste ein späterer Wert über 1,007 liegen, um „+3 %“ zu schaffen, und das geht nicht. Jede Fortsetzung von einem so guten Checkpoint endet deshalb zwangsläufig bei `MIN_ITERS`. Das betraf schon `servo_comp6`, und `real_step_share` fließt in den Score gar nicht ein. Vorschlag an den Nutzer: die Regel auf absolute Verbesserung bzw. auf den Abstand zu 1 umstellen. Ich ändere sie nicht selbst, damit die Läufe vergleichbar bleiben.
- **Lehre:** Bei Fortsetzungen ab einem Score über ~0,95 entscheidet `MIN_ITERS` über die Laufzeit, nicht die Stagnationsregel.
### `servo_comp8`: `servo_comp7` unverändert länger (gestartet 28.11. ~07:58 vom Supervisor, ab `servo_comp7` 6120, GPU 0)
- **Änderung:** keine an Belohnungen oder Sim, alle Einstellungen wie `servo_comp7` (`gait_swing_reward` 8, `joint_accel_penalty` −3). Geändert ist nur die Laufzeit: Der Wächter darf frühestens nach 1500 Iterationen wegen Stagnation stoppen (`MIN_ITERS=1500`, Fenster 12).
- **Warum:** `servo_comp7` wurde nach 605 Iterationen von der gedeckelten Score-Regel beendet, während die Zielgröße (echte Schritte) noch stieg und die Stürze am Ende wieder bei 0/16 lagen. 6120 ist der beste Kompromiss bisher: 0/16 Stürze, echte Schritte 0,24, Versatz 0,18, Fußneigung 0,17. Eine neue Gewichtung jetzt würde nicht zeigen, ob die Schwungbelohnung allein ausreicht.
- **Ziel:** echte Schritte stabil über 0,3 bei 0/16 Stürzen, `lateral_ratio` ≤ 0,25, Fußneigung ≤ 0,30. Beobachten, ob `highfreq_share` bei größerer Gangbewegung fällt.
- **Abbruchsignal für die nächste Stufe:** Stürze dauerhaft ≥ 2/16, dann `gait_swing_reward` auf 5. Bleiben die echten Schritte unter 0,3, dann auf 12.
- **Lauf:** 3000 Iterationen bis 9120. Wächter mit Fenster 12, `MIN_ITERS=1500`, Video alle 100, Bewertung auf GPU 1.
- **Ergebnis:** Am 28.11. ~14:55 nach dem Hardwaretest mit Zustimmung des Nutzers bei ~6800 gestoppt („Sounds like a plan, Go Ahead!“). Letzte Bewertungen 6635–6790: Score 0,95, 1/16 Stürze, `lateral_ratio` 0,15–0,18, echte Schritte 0,27–0,29. Der Lauf tat, was er sollte (mehr echte Schritte). Der Hardwaretest zeigte aber, dass der Roboter auch mit 10 % „echten Schritten“ laut Sim sichtbar die Füße hebt, und dass Geradeauslauf das eigentliche Problem ist. Snapshots bleiben als Ausgangspunkt erhalten. Aus `active_runs.txt` entfernt, damit der Watchdog ihn nicht wiederbelebt.
### Hardwaretest-Vorbereitung 28.11., `servo_comp6_step6115`
- **Auswahl:** `servo_comp6` 6115 (Score 0,979). 0/16 Stürze bei 6115 und in allen zehn Bewertungen danach bis 6516, Fußneigung 0,15, `lateral_ratio` 0,25, echte Schritte 0,10. Danach schlurft die Policy zunehmend (0,05). Offen im Gate: `highfreq_share` 0,245 und `limiter_share` 0,201. Der Test soll vor allem zeigen, ob das Zittern im Sim am Roboter überhaupt sichtbar ist. Erster Hardwaretest seit `servo_rubber23_step3315` (21./22.11.), erster mit Spiel/Elastizität trainiert.
- **Export:** nach `sim/policies/servo_comp6_step6115/` (ONNX = JAX, Differenz 0, α 0,25, `start_pose=center`, Tempo 0,03–0,06 m/s, Gang 1,0–1,25 Hz). Nur dieser Ordner per scp auf den Pi kopiert (Prüfsummen gleich), kein Neustart von `zbot-pi`. Der Pi listet die Policy.
- **Hardwaretest 28.11. ~14:35–14:42** (Parkett, Kabel als Leine in der Hand des Nutzers, vx 0,045, Gang 1,1 Hz; 3 Trockenläufe ohne Befund: Schritt 6 ms, max. 25 ms, IMU-Alter ≤ 50 ms). 6 Läufe, abwechselnd seitlich und von oben gefilmt (120 FPS, 4-fache Zeitlupe, `media/hw_tests/2026-11-28/`):

  | Lauf | Ansicht | Dauer (Video ÷ 4) | Beobachtung |
  |---|---|---|---|
  | 1 | seitlich | ~3,2 s | ~0,5 s Stand, 2–3 Schritte, dreht zur Kamera, kippt nach vorn, an der Leine gefangen |
  | 2 | oben | ~2,5 s | Schritte, dann Gierung ~30–45° im Uhrzeigersinn, kippt |
  | 3 | seitlich | ~3,1 s | kleine Schritte, dreht, geht über den vorderen Fuß zu Boden |
  | 4 | oben | ~3,2 s | erst ruhig, dann dieselbe Gierung ~30–40° |
  | 5 | seitlich | **~8,6 s** | **mehrere Schritte etwa vorwärts**, dreht dabei langsam fast 90° weg, steht am Ende noch |
  | 6 | oben | ~4,1 s | mehrere Schritte fast nur nach links, Gierpendeln ±20–30° |

  - **Nutzer:** „Especially the 5th run and 6th are memorable: 5th was the first one to walk several steps roughly forward! Great milestone!! But it was still strong tendency to the left. TH 6th run walked several steps pretty much directly left, basically no forward trajectory.“
  - **Meilenstein:** erste Policy, die am echten Roboter mehrere Schritte etwa vorwärts läuft (Lauf 5). Die Füße heben sichtbar ab, obwohl das Sim nur 10 % echte Schritte misst. Zittern ist im Video nicht zu erkennen.
  - **Offen:** starker Zug nach links (Lauf 6 fast rein seitlich) und Gierung in den ersten 1–2 s, wie am 21./22.11. Im Sim liegt `lateral_ratio` bei 0,25 und die Gierung bei fast 0. Das Training mit Spiel und Elastizität hat das also nicht behoben.
  - **Spur:** Im Sim nutzt die Policy die Hüftgierung asymmetrisch (Bewertung 6016: rechts −1…+14,5°, links −5,7…+3,2°). Gleicht sie damit im Sim etwas aus, das es am Roboter nicht gibt, wäre der Linkszug erklärt. Prüfen mit den Pi-Logs (noch auf dem Pi, der war beim Auswerten aus).
- **Pi-Logs** (`sim/policies/servo_comp6_step6115/hw_logs_2026-11-28/`, Videos jetzt nach Log-Zeit benannt): Laufzeiten 2,0 / 2,1 / 1,7 / 1,8 / **5,7** / 3,3 s (Lauf 2 und 6 E-Stopp, sonst Sturz mit Neigung > 55°). Die Videos sind länger, weil sie vor dem Start beginnen und nach dem Ende weiterlaufen. Lauf 5 (14:37:05) ist trotzdem der längste bisher (`servo_rubber23` max. 2,5 s bis zum Sturz, 5,3 s bis zum E-Stopp).
- **Vergleich mit dem Sim** (gleicher Checkpoint, 16 Starts à 5 s mit den Einstellungen des Laufs, GPU 1):
  - **Hüftgierung real = Sim:** Sollwerte links −6…+1°, rechts 0…+14° (Sim −6…+3° / −1…+14°). Die Asymmetrie ist gelernt und auch im Sim da, wo der Roboter trotzdem fast gerade läuft. Sie ist also nicht die Ursache. (Beide Gelenke drehen dabei nach außen, die Vorzeichen sind gespiegelt.)
  - **Erste Sekunde real = Sim:** Gierwinkel bei 0,5 s real +3…+7°, Sim Median +4°.
  - **Gierrate real 2–4-mal so hoch:** |gyro| p95 in den ersten 1,5 s real 100–210 °/s, Sim 52 °/s. Wie am 21./22.11. ist die Verdrehung um die Hochachse im Sim zu steif, trotz `foot_condim=4` und `joint_compliance`.
  - **Das Sim läuft auch nicht gerade:** Nach 5 s ist die Gierung im Median |22°| (−35…+23°), der Seitenversatz liegt bei 0,25 m je Meter vorwärts. Die Linksdrehung von Lauf 5 (+22…+30°) liegt damit im Streubereich des Sims. Das Gate prüft die Gierung gar nicht. Diese Schwäche der Policy hat es also nicht gesehen.
  - **IMU:** Real misst die Schwerkraft beim Start durchgehend 2–3° zur Seite geneigt (Sim Mittel 0,4°, randomisiert −4…+6°) und ~8 % zu groß (10,8 gegen 9,8 m/s²). Das liegt im trainierten Bereich, könnte als fester Versatz aber zum Seitwärtslaufen (Lauf 6) beitragen. Im Sim mit festem Versatz prüfen.
  - **Echte Schritte:** Der Roboter hebt die Füße sichtbar, obwohl das Sim nur 10 % echte Schritte zählt. Die Kennzahl unterschätzt das Schrittverhalten offenbar. Dass `servo_comp7` gegen das Schlurfen trainiert, ist damit weniger dringend als gedacht.
- **Folgerung:** Als Nächstes zählen Geradeauslauf und Gierstabilität: Gierung als Gate-Kriterium, stärkere Strafe auf Kursabweichung, breitere Torsions-/Gierspiel-Randomisierung. Ein fester IMU-Rollversatz von ~3° gehört in die Sim-Prüfung.
### `servo_yaw1`: Geradeauslauf (gestartet 28.11. ~14:55, ab `servo_comp6` 6115, GPU 0)
- **Start:** der am Roboter getestete Checkpoint 6115, nicht `servo_comp8`. So lässt sich das nächste Ergebnis direkt mit dem Hardwaretest vergleichen.
- **Änderungen:**
  - `heading_penalty` −1 → −8. Der Term lag bei −0,0016 je Schritt, unter 3 % der positiven Belohnung (~0,06), obwohl das Sim nach 5 s im Median 22° vom Kurs ist.
  - Weicheres Gierspiel, weil die echte Gierrate 2–4-mal so hoch ist wie im Sim: `play_yaw_deg` 2 → 4, `k_yaw` 8–60 → 4–40 Nm/rad, `foot_torsion` 0,01–0,05 → 0,003–0,05.
  - Alles andere wie `servo_comp6`.
- **Neues Gate-Kriterium:** `yaw_end_deg` ≤ 10° (Median |Gierung| am Episodenende der laufenden Episoden, `hardware_gate.py`). 6115 hat 21,9°. Der Score des Wächters enthält das Kriterium, ist also mit früheren Läufen nicht direkt vergleichbar.
- **Ziel:** |Gierung| am Ende ≤ 10° ohne Stürze, `lateral_ratio` ≤ 0,25, Fußneigung nicht schlechter.
- **Parallel:** Sim-Prüfung von 6115 mit festem IMU-Rollversatz ±3° (Modellkopien mit gedrehter IMU-Site, `imu_tilt_deg=0`), ob ein fester Versatz das Seitwärtslaufen von Lauf 6 erklärt.
  - **Ergebnis (28.11. ~15:30): IMU-Versatz ist es nicht.** +3° gibt im Sim genau die reale Startmessung (acc_x +0,49 gegen real +0,35…+0,62). Trotzdem gleiche Bahn wie ohne Versatz: Seitenversatz im Median +0,028 / +0,032 / +0,036 m (+3° / 0° / −3°), Vorwärts 0,18–0,19 m, Gierung am Ende −22 / −24 / −23°. Das Sim driftet in allen drei Fällen gleich: leicht nach links versetzt, dabei nach rechts gedreht. Der Roboter drehte dagegen nach links. Der Linkszug kommt also aus der Mechanik (Gier-Nachgiebigkeit/Fußverdrehung), nicht aus der IMU.
- **Lauf:** 3000 Iterationen. Wächter mit Fenster 12, `MIN_ITERS=600`, Video alle 100, Bewertung auf GPU 1.
- **Ergebnis:** *folgt.*
