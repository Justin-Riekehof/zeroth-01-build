# AutoRL-Kontext — automatische Trainingssetups für den Z-Bot

Recherche vom 2026-09-07. Fragestellung: Kann ein System aus einer **verbalen Szenario-Beschreibung
(+ optional Skizzen/Fotos)** automatisch ein funktionierendes RL-Trainingssetup ableiten — Policy-Typ,
Reward-Terme mit konkreten Gewichten, PPO-Hyperparameter, Domain-Randomization, Curriculum — und dabei
den lokalen Qwen/vLLM-Server als semantische Instanz nutzen? Bezug: [sim-context.md](sim-context.md),
[sim/README.md](../sim/README.md), Trainings-Task `sim/train/walking.py`.

## 0. Kurzfazit

1. **Für die Zahlen (Gewichte, PPO-Skalare) ist klassische Multi-Fidelity-HPO der Stand der Technik,
   nicht das LLM.** DEHB bzw. Optuna-TPE + Hyperband/ASHA über den *vollen* Suchraum, 3–5 Tuning-Seeds,
   16–64 Vollrun-Äquivalente. PBT/PB2 fallen für PPO durch. Reward-Gewichte und PPO-Skalare gehören
   in *einen* gemeinsamen Suchraum (Dierkes 2024: Humanoid 4464 → 5433 Return).
2. **Das LLM ist stark bei Struktur und Semantik, schwach bei Numerik.** Belegt funktionierende Rollen:
   Szenario → Aufgabenspezifikation, Auswahl/Editieren von Reward-Termen aus einer festen Bibliothek,
   Curriculum-Stufen, Interpretation von Trainingskurven und Rollout-Bildern ("Reward Reflection").
   Vollständigen Reward-Code schreiben zu lassen (Eureka) funktioniert mit GPT-4-Klasse und ≥ 80
   Trainingsläufen; für 7–14B-Modelle ist das nirgends als erfolgreich dokumentiert. Ein lokales 27B
   (unser Qwen3.8) liegt dazwischen — Config-Editing ja, freier Code nur mit Sandbox und Fallback.
3. **Ein fester Fitness-Wert außerhalb der LLM-Reichweite ist Pflicht** (Eureka, DrEureka, RDA).
   Bei uns existiert er schon: `sim/tools/eval_policy.sh` liefert Vorwärtsweg, Geschwindigkeit,
   Seitendrift, Yaw-Drift, Stürze. Das plus das Contact-Sheet aus `validate_policy.sh` ist genau das,
   was ein VLM-Richter braucht.
4. **Policy-Typ ist keine Suchdimension.** Referenz überall: MLP [512,256,128] ELU + kurze
   Beobachtungshistorie; GRU/LSTM erst, wenn Domain-Randomization mit dem MLP nicht mehr transferiert
   (Cassie-Befund); Transformer lohnt erst bei Multi-Terrain/Skalierung. Asymmetrischer Critic
   (privilegierte Infos nur im Value-Netz) ist Standard und kostenlos.
5. **Constraints statt Straf-Gewichte** (CaT, "Constraints as Terminations") reduzieren den Reward auf
   1–3 echte Task-Terme; alle Limit-Strafen werden zu Terminierungswahrscheinlichkeiten mit
   physikalisch interpretierbaren Schwellen (Torque, Gelenkgeschwindigkeit, Action-Rate, Orientierung).
   Das ist der wirksamste Hebel, um den Suchraum klein und die Sim-to-Real-Sicherheit hoch zu halten.
6. **Rechenbudget ist der Engpass, nicht das LLM.** Ein PPO-Step (1,02 M Samples) dauert bei uns
   29–40 s auf einer 3090; ein bisheriger Run (150–240 Steps) 1,5–2,5 h. Eine Hyperband-Generation
   mit 16 Kandidaten braucht auf beiden GPUs ≈ 6–8 h → **eine Generation pro Nacht**. vLLM (TP=2, beide
   GPUs) und Training schließen sich aus; LLM-Phase und Trainingsphase müssen alternieren.

## 1. Forschungsstand: Hyperparameter-Optimierung für RL (AutoRL)

### 1.1 Welche HPO-Methoden für PPO funktionieren

- **Eimer, Lindauer, Raileanu, ICML 2023 — "Hyperparameters in RL and How to Tune Them"**
  ([arXiv 2306.01324](https://arxiv.org/abs/2306.01324), Code [how-to-autorl](https://github.com/facebookresearch/how-to-autorl)).
  PPO auf Brax Ant/Halfcheetah/Humanoid, 9-dimensionaler Suchraum (lr log[1e-6, 0.1], Epochs 1–15,
  Batch 128–2048, Minibatches 2^0–2^7, Entropy 1e-4–0.5, GAE-λ 0.5–0.9999, Clip 0.01–0.9, VF-Coef
  0.01–0.9, Reward-Scaling 0.01–1.0). Ergebnis: **DEHB** (Multi-Fidelity, differential evolution +
  Hyperband) ist die zuverlässigste Wahl; Random Search überfittet mit steigendem Budget auf die
  Tuning-Seeds (Humanoid bei 64 Runs: DEHB 5205, Baseline 3235, RS 325); PB2/BGT liefern "statische
  Konfigurationen statt Schedules" und fallen zurück. **3–5 Tuning-Seeds sind optimal**, 10 erhöhen die
  Varianz. Pro Environment dominieren 1–2 Hyperparameter (Humanoid: lr; Ant: Clip) — deshalb den
  vollen Raum tunen, nicht hand-auswählen. Protokoll: Train-/Test-Seeds trennen, Incumbent auf
  ungesehenen Seeds bestätigen.
- **HPO-RL-Bench** ([Shala et al., AutoML 2024](https://proceedings.mlr.press/v256/shala24a.html)):
  exhaustives PPO-Grid (lr, γ ∈ {0.8…1.0}, Clip ∈ {0.1, 0.2, 0.3}), 10 Seeds, 7 Optimierer. PBT/PB2
  führen früh, "mit genug Zeit finden RS, GP, Optuna, SMAC und DyHPO statische Konfigurationen, die die
  Schedules schlagen"; niedrigere Lernraten sind generell besser; PPO-Konfigurationen sind weniger
  robust als SAC/TD3; es gibt keine "Silver-Bullet"-Konfiguration.
- **ARLBench** ([arXiv 2409.18827](https://arxiv.org/abs/2409.18827), JAX): SMAC-Varianten im Mittel
  vorn, Unterschiede meist nicht signifikant, PBT am schlechtesten; fANOVA: nur 2–4 Hyperparameter
  haben ≥ 5 % Importance.
- **Landschaften wandern während des Trainings** ([Mohan et al. 2023](https://arxiv.org/abs/2304.02396),
  PPO auf BipedalWalker) — Motivation für dynamisches Tuning, das die Benchmarks oben aber (noch) nicht
  einlösen. In-Run-Bandit-Ansätze wie ULTHO ([arXiv 2503.06101](https://arxiv.org/abs/2503.06101))
  sind Forschungsstand.
- **Reward-Gewichte + Hyperparameter gemeinsam** ([Dierkes et al., RLC 2024, arXiv 2406.18293](https://arxiv.org/abs/2406.18293)):
  DEHB mit 3 Fidelity-Stufen (×3 Steps je Stufe), 133 Vollrun-Äquivalente. Brax-Humanoid-PPO:
  nur HPO 4464, nur Reward 4826, **gemeinsam 5433**. γ/lr und Distanz-Reward-Gewicht interagieren
  stark → gemeinsame Optimierung als Best Practice.

Methodenreferenzen: [DEHB](https://arxiv.org/abs/2105.09821), [BOHB](https://arxiv.org/abs/1807.01774),
[ASHA](https://arxiv.org/abs/1810.05934), [PBT](https://arxiv.org/abs/1711.09846),
[PB2](https://arxiv.org/abs/2002.02518), [Optuna](https://arxiv.org/abs/1907.10902).

### 1.2 Welche PPO-Hyperparameter zählen — Referenzwerte

| Parameter | legged_gym / RSL-RL ([Config](https://github.com/leggedrobotics/legged_gym/blob/master/legged_gym/envs/base/legged_robot_config.py)) | MuJoCo Playground ([locomotion_params.py](https://github.com/google-deepmind/mujoco_playground/blob/main/mujoco_playground/config/locomotion_params.py)) | ksim-Default | **walking.py (unser Run)** |
|---|---|---|---|---|
| lr | 1e-3, adaptiv auf KL 0.01 | 3e-4 | – | 3e-4 |
| Entropy | 0.01 | 1e-2 (Humanoide 5e-3) | 0.008 | 0.001 |
| Clip | 0.2 | 0.3 (Humanoide 0.2) | 0.2 | 0.3 |
| γ / λ | 0.99 / 0.95 | 0.97 / 0.95 | 0.99 / 0.95 | 0.97 / 0.95 |
| Envs × Rollout | 4096 × 24 Steps (0,5 s) | 8192 × 20 Steps | – | 4096 × **250 Steps (5 s)** |
| Minibatches / Epochs | 4 / 5 | 32 / 4 | – | 16 (à 256 Envs) / 10 |
| Netz | [512,256,128] ELU | Policy 4×128, Value 5×256 | – | MLP 5×256 (Actor & Critic) |
| Obs-Normalisierung | ja (empirisch) | ja (Running Stats) | – | nein |
| Grad-Clip | 1.0 | 1.0 | 10.0 | 1.0 |

Befunde aus [Andrychowicz et al. 2021](https://arxiv.org/abs/2006.05990) (250k Agenten):
Input-Normalisierung ist "crucial"; Advantages und Value-Targets normalisieren; letzte Policy-Schicht
100× kleiner initialisieren; initiale Std ≈ 0,5; Adam 3e-4 mit linearem Decay; **γ ist der
sensitivste Einzelparameter**; GAE-λ ≈ 0,9; Entropy-Regularisierung "mostly doesn't matter".
[Seo et al. 2025](https://arxiv.org/abs/2512.01996) (G1/T1-Humanoide): γ 0,97 für Velocity-Tracking,
0,99 für Whole-Body-Tracking; Observation- + Layer-Norm; < 10 Reward-Terme reichen bei starker DR.

**Praktikable Suchbereiche für Lokomotion-PPO:** lr log[5e-5, 2e-3]; Entropy log[1e-4, 2e-2] oder 0;
Clip [0.1, 0.3]; γ [0.96, 0.995]; λ [0.9, 0.98]; Epochs [3, 8]; Minibatch-Samples [4k, 32k]; initiale
Std [0.5, 1.0]. Architektur und Obs-Normalisierung fixieren, `num_envs` nur für Durchsatz wählen.

Auffällig bei uns: **Rollout 5 s (250 Steps) ist ~10× länger als jede Referenz** (24–32 Steps bei
50 Hz), Obs-Normalisierung fehlt, Entropy ist 5–10× niedriger als die Referenzen. Alles drei sind
Kandidaten für die erste Suche, wobei die Rollout-Länge ein Shape-Parameter ist (separate
Kompilierung, nur sequentiell suchbar).

### 1.3 Reward-Gewichte automatisch — ohne LLM

- **Gemeinsame Black-Box-Suche** (Dierkes 2024, s. o.): Gewichte als DEHB-Dimensionen, optional
  Varianz-Strafe als zweites Ziel.
- **Constraints as Terminations, CaT** ([Chane-Sane et al., IROS 2024, arXiv 2403.18765](https://arxiv.org/abs/2403.18765),
  [Isaac-Lab-Code](https://github.com/Gepetto/constraints-as-terminations)): statt Straf-Gewichten eine
  Terminierungswahrscheinlichkeit δ = max_i p_i^max · clip(c_i⁺ / c_i^max, 0, 1), c_i^max = EMA des
  Batch-Maximums der Verletzung. Harte Constraints (p^max = 1: Knie-/Basis-Kollision, Fußkraft);
  weiche Constraints rampen p^max 0,05 → 0,25 (Torque, Gelenkgeschwindigkeit ≤ 16 rad/s, Beschleunigung
  ≤ 800 rad/s², Action-Rate ≤ 80 rad/s, Basis-Orientierung ≤ 0,1 rad, Hüfte ≤ 0,2 rad, Air-Time
  0,25 s, 2 Kontakte). Einziger Reward: exp(−‖Δv‖²/0,25) + 0,5·exp(−Δω²/0,25). Solo-12: Return
  683 ± 6 mit 0,5 % Torque-Verletzungen vs. Lagrange-N-P3O 593 ± 50 / 8 %. "Drei Zeilen Code" über PPO.
  Auf den Bolt-Biped übertragen in [arXiv 2508.02194](https://arxiv.org/abs/2508.02194).
- **IPO-Constraints** ([Kim et al., T-RO 2024](https://arxiv.org/abs/2308.12517)): mehrere Laufroboter
  mit "nur einem Reward-Koeffizienten" trainiert. [Constraints as Rewards](https://arxiv.org/abs/2501.04228):
  Lagrange-Multiplikatoren werden zu Gewichten.
- **Meta-Gradient-Reward** für Unitree G1 ([Research 2025](https://pmc.ncbi.nlm.nih.gov/articles/PMC13395157/)):
  gelernter Reward mit Cosinus-Regularisierung zum Prior; 90 % Erfolg real, 12 % weniger Torque-Energie.
- **Curriculum auf Gewichten**: Strafgewichte mit wachsender Episodenlänge hochrampen (Seo 2025;
  Isaac Lab `modify_reward_weight`), Terrain-Curriculum nach [Rudin 2022](https://arxiv.org/abs/2109.11978).
- **Skalennormalisierung**: Brax `reward_scaling` (Eimer-Default 0,1, gesucht 0,01–1,0);
  Value-Target-Normalisierung / [PopArt](https://arxiv.org/abs/1809.04474);
  [37 PPO-Implementation-Details](https://iclr-blog-track.github.io/2022/03/25/ppo-implementation-details/).

Referenz-Gewichte legged_gym (Anymal/Cassie-Basis, `rewards.scales`): tracking_lin_vel 1.0
(σ = 0,25), tracking_ang_vel 0.5, lin_vel_z −2.0, ang_vel_xy −0.05, torques −1e-5, dof_acc −2.5e-7,
action_rate −0.01, feet_air_time 1.0, collision −1.0, termination 0. Unsere Skalen (walking.py,
Velocity-Tracking-Variante): Healthy 0.5, Termination −5, LinVelTrack 2.0 (σ 0,25), AngVelTrack 0.75,
Orientation −2, FeetContact −2, NaiveVel 0.25; Gait-Shaping: Step 0.2, Lateral −0.5, Yaw −0.3,
Smoothness −0.02. Achtung: ksim teilt jeden Term durch die Rollout-Länge in Steps
(`ksim/task/rl.py:172`) — absolute Werte sind nicht mit legged_gym vergleichbar, Verhältnisse schon.

### 1.4 Policy-Typ

- MLP + kurze Historie ist in legged_gym, Playground und Isaac Lab der Default.
- LSTM/GRU: [Siekmann et al. 2020](https://arxiv.org/abs/2006.02402) (Cassie) — in Sim klar besser,
  real gleichauf mit MLP, *außer* mit Dynamics-Randomization: dann transferiert LSTM + DR am besten.
  Regel: Rekurrenz, wenn die Policy randomisierte Dynamik online inferieren muss.
- Transformer: [Radosavovic 2024, Digit](https://hybrid-robotics.berkeley.edu/publications/ScienceRobotics2024_Learning_Humanoid_Locomotion.pdf),
  [ParkourFormer](https://arxiv.org/abs/2605.25782) — lohnt bei Multi-Terrain/Skalierung, nicht für
  einen kleinen Biped auf flachem Boden.
- Asymmetrischer Actor-Critic / Teacher-Student: Playground gibt `privileged_state` nur dem Value-Netz;
  [rsl_rl](https://github.com/leggedrobotics/rsl_rl) liefert Student-Teacher-Distillation.
- Automatisierte Wahl: HPO-RL-Bench zeigt, dass PBT/PB2 Architektur-Dimensionen nicht handhaben
  (SMAC/DyHPO schon); ARLBench-fANOVA: Architektur ist selten in der Top-Importance. Praxis:
  Architektur pro Roboterklasse fixieren, HPO-Budget für Skalare.

## 2. Forschungsstand: LLM/VLM-gestütztes Reward- und Setup-Design

### 2.1 Eureka-Linie (LLM schreibt Reward-Code, evolutionäre Suche)

- **Eureka** ([Ma et al., ICLR 2024](https://arxiv.org/abs/2310.12931), [Code](https://github.com/eureka-research/Eureka)):
  Prompt = unveränderter Environment-Quellcode + einzeiliger Task → GPT-4 schreibt Reward-Funktion mit
  Komponenten-Dict → **16 Samples × 5 Iterationen**, jedes mit PPO trainiert → bester nach fester
  Fitness F → nächste Iteration bekommt besten Code + **Reward Reflection** (Max/Mittel/Min jeder
  Komponente und F über die Trainingsepochen als Text). Ablation: ohne Reflection −28,6 %. Schlägt
  Human-Rewards auf 83 % von 29 Tasks. F ist fix: Vorwärtsfortschritt (Humanoid), −(linvel_err +
  angvel_err) (Anymal). GPT-3.5 "degradiert, aber erreicht/übertrifft Human auf den meisten Tasks".
- **DrEureka** ([RSS 2024](https://arxiv.org/abs/2406.01967)): (1) Eureka mit **Sicherheitsanweisung**
  im Prompt (Action-Rate, Gelenklimits, Torque strafen); Fitness exp(−(v_x − 2)²/0,25). (2)
  **Reward-Aware Physics Prior**: beste Policy unter Variation je eines Physikparameters
  (Reibung, Masse, COM, Motorstärke, Kp/Kd, Damping, Armature, Gravitation) testen, [min,max] des
  weiterhin erfolgreichen Bereichs notieren. (3) GPT-4 sampelt 16 DR-Konfigurationen innerhalb dieser
  Grenzen. Go1 real: 1,83 ± 0,07 m/s vs. 1,32 ± 0,44 Human. **Negativbefunde:** Reward ohne
  Sicherheitsanweisung → 0,0 m/s real (Reward-Hacking über Überaktuierung); DR ohne Prior → 15/16
  Policies lösen den Motorschutz aus; **DR-Konfigurationen sind in der Sim nicht rankbar.**
- **Language to Rewards** ([Yu et al., CoRL 2023](https://arxiv.org/abs/2306.08647)): LLM schreibt *keinen*
  Code, sondern füllt eine feste API mit vorgebauten Termen (CoM-Höhe, Basis-Orientierung,
  Fußpositionen, Gewichte); 90 % Erfolg auf 17 Tasks vs. 50 % Baseline. Ein zwischengeschalteter
  "Motion Descriptor" (LLM beschreibt erst die Bewegung strukturiert) ist entscheidend.
- **CurricuLLM** ([ICRA 2025](https://arxiv.org/abs/2409.18382), Berkeley Humanoid, Isaac Lab): GPT-4-turbo
  erzeugt Subtask-Sequenz + Reward-/Goal-Code pro Subtask (≤ 5 Kandidaten), Evaluator-LLM wählt anhand
  von Rollout-Statistiken. Real: Tracking-Fehler 0,46 ± 0,38 m/s (CurricuLLM) vs. 0,41 ± 0,10
  (Human-Reward) vs. 1,13 ± 0,57 (LLM Zero-Shot) — **erreicht den Human-Reward, schlägt ihn nicht**;
  Failure-Mode "Stehenbleiben".
- **STRIDE** ([2025](https://arxiv.org/abs/2502.04692), 16-DoF-Humanoid): GPT-4o-mini, 10 × 3;
  vollautomatische Variante stagniert ab Iteration 3 (0,3 Erfolg), human-initialisiert hält 0,7.
- **RF-Agent** ([2026](https://arxiv.org/abs/2602.23876)): MCTS über Reward-Code-Knoten, 80 Samples;
  Eureka 0,63 → 1,70 mit GPT-4o-mini; 2,00 → 2,68 mit GPT-4o — Modellgüte skaliert das Ergebnis ~3×.
- **Agentisches Config-Editing auf Quadruped** ([März 2026, arXiv 2603.27416](https://arxiv.org/abs/2603.27416)):
  Claude via OpenCode editiert Isaac-Lab-**Reward-Config** (Tracking 5.0 → 8.0, Gait/Airtime/
  Orientierung), Terrain-Config und Env-Zahl; 70+ Runs in 14 Wellen; Metrik = planarer
  Geschwindigkeitsfehler (0,263 bei Ziel < 0,27). Protokollierte Fallen: Strafen −10…−12 erzeugen "tote"
  Policies; höheres Tracking-Gewicht bläht den Reward auf, während das Tracking schlechter wird.
- Weitere: [Text2Reward](https://arxiv.org/abs/2309.11489) (Llama-2/Code-Llama seed-unzuverlässig vs.
  GPT-4), [REvolve](https://arxiv.org/abs/2406.01309) (automatische Variante nur gleichauf mit Eureka bei
  Lokomotion), [Video2Reward](https://arxiv.org/abs/2412.05515), [ProgressCounts](https://arxiv.org/abs/2410.09187)
  (LLM schreibt nur Fortschrittsfunktion: 4 statt 80 Samples; "LLM-Diskretisierung wegen schwacher
  numerischer Fähigkeit ineffektiv"), [R\*](https://proceedings.mlr.press/v267/li25v.html) (LLM =
  Struktur, Präferenzlernen = Parameter), [Agent²](https://arxiv.org/abs/2509.13368) (LLM entwirft MDP +
  Algorithmus/Hyperparameter).

### 2.2 VLM als Richter über Rollouts

- **RL-VLM-F** ([2024](https://arxiv.org/abs/2402.03681)): VLM gibt **paarweise Präferenzen** über
  Bildpaare statt absoluter Scores → gelernter Reward; deutlich robuster als CLIP-Ähnlichkeit
  ([VLM-RM](https://arxiv.org/abs/2310.12921), [RoboCLIP](https://arxiv.org/abs/2310.07899): Rohähnlichkeit
  schwankt 3 Größenordnungen). [GoalLadder](https://arxiv.org/abs/2506.16396): Rankings → Elo gegen Rauschen.
- **RDA** ([Juni 2026](https://arxiv.org/abs/2606.01672)): Reward-Evolution + VLM bewertet 5
  Rollout-Videos pro Policy (0 / 0,5 / 1) und diagnostiziert Verhalten; HumanoidBench-Alignment 0,70 vs.
  Eureka 0,47 — rein numerische Reflection kann Failure-Modes nicht unterscheiden.
- **MoVLR** ([2025](https://arxiv.org/abs/2512.23077)): VLM beurteilt Gang-Videos und wählt den Elite,
  **Qwen2.5-Coder-32B** schreibt den Code um; Befund: **ein Modell für Richten und Codieren lieferte
  ungültigen Code** → Rollen trennen (bei uns: getrennte Prompts/Aufrufe, gleiches Modell geht, aber
  nie beides in einem Aufruf).
- **RoboReward** ([2026](https://arxiv.org/abs/2601.00675)): kein Off-the-Shelf-VLM ist tasksübergreifend
  gut; trainierte 4B/8B schlagen größere Generalisten. [VIRAL](https://arxiv.org/abs/2505.22092):
  Qwen2.5-VL-7B-Videobeschreibungen als Feedback; Text-Overlays auf Bildern schadeten teils.

### 2.3 Bild/Skizze als Aufgabenspezifikation

Durchgängiges Muster: **das Bild wird erst in Symbole übersetzt** (Objektliste, Keypoints, Posen,
annotierte Pfeile/Text), dann in Reward-Code oder einen Erfolgstest — nie direkt in Gewichte.
[RoboGen](https://arxiv.org/abs/2311.01455) (Text → Szene → Reward-Code), [Gen2Sim](https://arxiv.org/abs/2310.18308)
(Foto → 3D-Asset + Physikparameter + Reward), [GRS](https://arxiv.org/abs/2410.15536) (RGB-D → SAM2 +
GPT-4o → Task-Code, Erfolg = generierter Unit-Test), [Sketch-to-Skill](https://arxiv.org/abs/2503.11918)
(2D-Skizze → Trajektorie → Demos → RL), [RT-Sketch](https://arxiv.org/abs/2403.02709) (Skizze
konditioniert Policy, kein Reward). Für uns: Skizze/Foto → strukturierte Task-Spec (Terrain, Ziel,
Geschwindigkeit, Hindernisse, Randbedingungen) → daraus Auswahl aus der Term-Bibliothek.

### 2.4 LLM als Hyperparameter-Optimierer

[AgentHPO](https://arxiv.org/abs/2402.01881), [LLAMBO](https://arxiv.org/abs/2402.03921) (LLM als
Warm-Start/Surrogat in BO — gewinnt nur früh, bei wenigen Beobachtungen), [Optuna vs. Code-Llama](https://arxiv.org/abs/2504.06006),
[AIDE](https://arxiv.org/abs/2502.13138). Die budgetgleiche Studie [arXiv 2606.21641](https://arxiv.org/abs/2606.21641)
findet: **der Vorteil des LLM ist der gute Startpunkt** (+0,4 pp über Default); geseedete Random
Search zieht nach 5 Evaluationen gleich und ab 12 vorbei. [AgentHPOBench](https://arxiv.org/abs/2607.29626):
"klare Grenzen bei anhaltender iterativer Verfeinerung und Log-Diagnose". **Kein Paper zeigt
LLM-HPO über getunten PPO-Defaults bei Laufrobotern.** → LLM liefert Priors/Startpunkte, DEHB sucht.

### 2.5 Was verlässlich funktioniert (Zusammenfassung)

| LLM-Rolle | Belege | Verlässlichkeit lokal (27B) |
|---|---|---|
| Szenario → strukturierte Task-Spec (JSON) | L2R Motion Descriptor, RoboGen, GRS | hoch (Schema-erzwungen) |
| Terme aus fester Bibliothek wählen + Startgewichte | L2R, 2026-Quadruped-Agent, R\* | hoch, Gewichte nur als Prior |
| Curriculum-Stufen vorschlagen | CurricuLLM | mittel |
| DR-Bereiche innerhalb gemessener Grenzen | DrEureka (RAPP nötig) | mittel, nur mit RAPP-Grenzen |
| Trainingskurven + Bilder interpretieren, Änderung vorschlagen | Eureka-Reflection, RDA, MoVLR | mittel–hoch (getrennte Aufrufe) |
| Neuen Reward-Term als Code schreiben | Eureka, STRIDE, CurricuLLM | niedrig ohne Sandbox/Tests; nur als Opt-in |
| Zahlen feinjustieren | ProgressCounts, AgentHPOBench | niedrig → DEHB |

Dokumentierte Failure-Modes, die das Design abfangen muss: Reward-Hacking durch Überaktuierung
(DrEureka: 0,0 m/s real), "Alive-Bonus → Stehenbleiben" (CurricuLLM), Reward-Aufblähung bei
schlechterem Tracking (2026-Agent), tote Policies durch zu hohe Strafen, Sim-only-Rankbarkeit von DR.

## 3. Was das für unseren Stack bedeutet (lokal verifiziert, 2026-09-07)

**Trainer (`sim/train/walking.py`, ksim 0.0.31):** Alle PPO-Skalare sind per CLI-Override setzbar
(`learning_rate`, `entropy_coef`, `clip_param`, `gamma`, `lam`, `num_passes`, `batch_size`,
`num_envs`, `rollout_length_seconds`, `max_grad_norm`, `normalize_advantages`, `value_loss_coef`,
`reward_clip_min/max`, `min/max_action_latency`). Reward-Gewichte sind nur für die vier
Gait-Shaping-Terme und den Geschwindigkeitsbereich als Config-Felder exponiert; die sieben übrigen
Skalen, `error_scale` der Tracking-Terme, die Terminierungs-Schwellen (Roll/Pitch 1,04 rad), die
DR-Bereiche (`get_physics_randomizers`, Push-Events), das Curriculum (`EpisodeLengthCurriculum`,
10 Level) und die MLP-Größe (5 × 256) sind hart codiert. `ksim.Reward` ist eine attrs-Klasse mit
`scale` und `__call__(trajectory, carry)` — neue Terme sind ~10 Zeilen JAX. Verfügbare Bibliothek
in ksim: StayAlive, LinearVelocity-/AngularVelocity-/JointVelocity-Penalty, BaseHeight(Range),
ActionSmoothness, ActuatorForce, BaseJerkZ, ActuatorJerk, AvoidLimits, ActionNearPosition,
FeetLinearVelocityTracking, FeetFlat, FeetNoContact, PositionTracking, Joystick; Terminierungen
Pitch/Roll/MinHeight/IllegalContact/BadZ/FastAcceleration/FarFromOrigin; Curricula Constant/Linear/
EpisodeLength/DistanceFromOrigin/RewardLevel/StepWhenSaturated; Randomizer Friction/Armature/Mass/
Damping/JointZero.

**Fitness & Artefakte:** `sim/tools/eval_policy.sh` → Vorwärtsweg, Speed, |y|-Drift, Yaw-Drift,
Basishöhe, Stürze/n; `validate_policy.sh` → zusätzlich Video + 12-Frame-Contact-Sheet;
`tb_read.py` → alle Reward-Komponenten-Kurven (= Eureka-Reflection-Rohdaten).

**Rechenbudget:** 1 Step = 4096 Envs × 5 s × 50 Hz = 1 024 000 Samples, gemessen 0,025–0,035 Steps/s
→ 29–40 s/Step auf einer 3090. Bisherige Runs: 150–240 Steps ≈ 1,5–2,5 h. Beide GPUs sind während
des Trainings zu ~22 GB belegt.

**LLM-Dienst:** `systemctl --user` Unit `qwen-vllm`: Qwen3.8-27B-FP8 (Architektur
`Qwen3_5ForConditionalGeneration` **mit Vision-Tower**), vLLM 0.27.1, TP=2 über beide 3090, 52k
Kontext, fp8-KV-Cache, DSpark-Spekulation, `--reasoning-parser qwen3`, Tool-Parser `qwen3_coder`,
Port 8000; Startzeit ≈ 2,5 min (Journal 2026-09-02). Der Encoder-Cache für Bilder wird initialisiert
(Default: 1 Bild pro Prompt). Strukturierte Ausgabe (`response_format={"type":"json_schema"}` bzw.
`extra_body={"structured_outputs":{"json":…}}`, Backends xgrammar/guidance, außerdem regex/choice/
grammar/structural_tag) ist in dieser Version vorhanden; die Grammatik greift erst nach `</think>`.
`--enable-sleep-mode` existiert, Level 1 bräuchte ≈ 27 GB Host-RAM (31 GB total, 22 belegt) → nicht
nutzbar; Level 2 (Gewichte verwerfen) oder Stop/Start wie in `~/text-modus.sh`. **Wichtig:** der
Context-Guard-Proxy auf Port 8001 ersetzt eingebettete Base64-Bilder durch Stubs — der Orchestrator
muss direkt gegen Port 8000 sprechen. Der Upstream-Report zu einem CUDA-Graph-Hang von FP8 auf
Ampere ([vllm #52682](https://github.com/vllm-project/vllm/issues/52682)) trifft hier nicht zu.

Modell-Alternativen (Sept 2026): Qwen3.6/3.8-27B sind nativ multimodal (Bild + Video) und decken
Vision, Code und Reasoning in einem Modell ab — kein Grund für einen VL/Coder-Split. AWQ-INT4-Varianten
(`cyankiwi/Qwen3.8-27B-AWQ-INT4`, ≈ 22 GB) laufen auf **einer** 3090 (70–72 tok/s, ~20k Kontext mit
Bildern) und würden ein Nebeneinander von LLM auf GPU 0 und Training auf GPU 1 erlauben — um den Preis
des halben Trainingsdurchsatzes. Quellen: [tfriedel/qwen3.6-rtx3090-lab](https://github.com/tfriedel/qwen3.6-rtx3090-lab),
[Armstrong, TP=2](https://derekarmstrong.dev/blog/running-qwen36-27b-dual-rtx-3090-vllm-v019/),
[vLLM Structured Outputs](https://docs.vllm.ai/en/latest/features/structured_outputs/),
[Reasoning Outputs](https://docs.vllm.ai/en/latest/features/reasoning_outputs/),
[Multimodal Inputs](https://docs.vllm.ai/en/stable/features/multimodal_inputs/),
[Sleep Mode](https://docs.vllm.ai/en/latest/features/sleep_mode/).

## 4. Zielarchitektur: "Szenario → Trainingssetup"

```
 Szenario (Text + Skizzen/Fotos)
        │  (1) Qwen, Thinking an, JSON-Schema erzwungen
        ▼
 Task-Spec (JSON): Ziel, Terrain, Geschwindigkeitsbereich, Randbedingungen,
                   Erfolgsmetrik-Parameter, Hardware-Limits (aus hardware/*.json)
        │  (2) Qwen: Auswahl aus Term-/Constraint-Bibliothek, Startgewichte,
        │      PPO-Prior, Curriculum-Stufen, DR-Bereiche — K=4–8 Kandidaten, JSON
        ▼
 Setup-Kandidaten ──► (3) DEHB / Optuna-Hyperband, geseedet mit den Kandidaten,
                          3 Seeds, Fidelity-Stufen 20 / 60 / 180 Steps
        │                  (Trainingsphase: vLLM gestoppt, beide GPUs)
        ▼
 Feste Fitness F + Reward-Kurven + Contact-Sheet/Keyframes
        │  (4) Qwen als Richter: paarweise Vergleich der Contact-Sheets (Rubrik),
        │      Diagnose-Text; (5) Qwen als Designer: Reflection → geänderte Term-Auswahl
        ▼
 nächste Generation (max. 3–5), dann Incumbent auf 5 frischen Seeds bestätigen
```

Designregeln, jeweils aus einem Befund oben:

1. **F ist fix und im Code** (Eureka/DrEureka): z. B. F = exp(−(v̄_x − v_cmd)²/0,25) · (1 − Sturzrate)
   − 0,5·|ȳ| − 0,2·|yaw| aus `eval_analyze.py`; das LLM sieht F, kann F nicht ändern.
2. **Sicherheitsterme sind immer aktiv, nicht wählbar** (DrEureka): Action-Rate, Gelenklimits
   (AvoidLimits), Torque (ActuatorForce) — am besten als CaT-Constraints mit Schwellen aus den
   Sys-ID-JSONs (STS3250 8,72 N·m / 8,94 rad/s; STS3215 5,47 N·m / 4,86 rad/s).
3. **LLM wählt Struktur, DEHB wählt Zahlen** (ProgressCounts, AgentHPOBench, budgetgleiche Studie):
   LLM-Gewichte sind nur der Seed der ersten Fidelity-Stufe.
4. **Richten und Entwerfen in getrennten Aufrufen** (MoVLR); Richter bekommt Bilder und Zahlen,
   Designer bekommt Richter-Text + Kurven.
5. **Paarweise Vergleiche statt absoluter Scores** vom VLM (RL-VLM-F, GoalLadder).
6. **DR-Bereiche nur innerhalb RAPP-Grenzen** (DrEureka): erst die beste Policy gegen Reibung/Masse/
   Kp-Kd/Latenz sweepen, dann darf das LLM Bereiche vorschlagen — und die werden real, nicht in Sim,
   bewertet.
7. **Bilder → Symbole → Config** (GRS, Gen2Sim): eine Skizze eines Hindernisparcours wird zu
   {Terrain-Typ, Stufenhöhe, Neigung, Zielentfernung}, nie direkt zu Gewichten.
8. **Freier Reward-Code nur als Opt-in** mit Sandbox-Lauf (`run_environment=True`, 1 Env, 50 Steps),
   Typprüfung und Fallback auf die Bibliothek; Aufruf mit Thinking und ganzer Datei im Kontext,
   Ausgabe als vollständige Datei (aider-Befund: "whole" schlägt "diff" bei Qwen).

**Budget einer Generation** (beide GPUs, 30 s/Step): 16 Kandidaten × 20 Steps = 2,7 h → 5 Kandidaten
× 60 Steps = 2,5 h → 2 × 180 Steps = 3 h; ≈ 8 h plus wenige Minuten LLM. Mit `num_envs=1024` für die
unterste Stufe (nur Ranking) sinkt die erste Stufe auf < 1 h. Realistisch: **eine Generation pro
Nacht, 3–5 Generationen pro Szenario.**

## 5. Implementierungsplan (Reihenfolge)

1. **Suchraum exponieren** (`walking.py`): alle Reward-Skalen + `error_scale`, Terminierungs-Schwellen,
   DR-Bereiche, Curriculum-Parameter, MLP-Breite/-Tiefe und initiale Std als `xax.field`; optional
   `ksim.RewardLevelCurriculum`-Variante. Damit ist ein Setup vollständig ein `key=value`-Overrideset,
   das `train_backpack.sh` schon durchreicht.
2. **CaT-Terminierung** als eigene `ksim.Termination`-Klasse (stochastisch, EMA der Batch-Maxima) für
   Torque, Gelenkgeschwindigkeit, Action-Rate, Orientierung; Straf-Terme dafür rauswerfen.
   Quelle: [Gepetto/constraints-as-terminations](https://github.com/Gepetto/constraints-as-terminations).
3. **`sim/tools/fitness.py`**: fester F aus dem Eval-Dataset + JSON mit allen Kennzahlen;
   Keyframe-Extraktion (6–10 Bilder ≤ 1 MPx) aus `walk.mp4`.
4. **Sweep-Runner** (`sim/autorl/`): Optuna (sqlite) mit `HyperbandPruner` oder DEHB
   ([automl/DEHB](https://github.com/automl/DEHB)); ein Trial = `train_backpack.sh`-Aufruf mit
   `max_steps`, zwei parallele Worker (GPU 0/1), Ergebnis aus `fitness.py`; Reflection-Text aus
   `tb_read.py` (Max/Mittel/Min jeder Komponente über 4–5 Zeitpunkte).
5. **vLLM-Unit ergänzen**: `--limit-mm-per-prompt '{"image":4}'`,
   `--mm-processor-kwargs '{"max_pixels":1048576}'` (Skizzen/Contact-Sheets ≈ 1000 Tokens je Bild),
   Phasenwechsel per `systemctl --user start/stop qwen-vllm` wie in `text-modus.sh`.
6. **Prompts + Schemas** (pydantic): TaskSpec, SetupCandidate (Term-Enum aus Schritt 1, Gewichts-
   Bereiche, PPO-Prior, Curriculum-Liste, DR-Bereiche mit RAPP-Grenzen), JudgeVerdict (paarweise,
   Rubrik: Sturz, Fußabstand, Schrittsymmetrie, Torso-Pitch, Armhaltung), DesignerRevision.
   Sampling: Thinking an, `temperature 0.6 / top_p 0.95 / top_k 20`, `max_tokens` ≥ 8k, ≤ 2 Repair-Retries
   bei Schema-Fehlern; direkt gegen Port 8000.
7. **Erst ohne LLM validieren**: eine DEHB-Generation auf dem heutigen Suchraum (lr, Entropy, Clip, γ,
   λ, Rollout-Länge, Tracking-/Orientierungs-Gewicht) gegen `backpack_v3_gait` als Baseline. Wenn
   das die Baseline schlägt, lohnt der LLM-Überbau; wenn nicht, liegt das Problem woanders
   (Modellmasse, Latenz, Obs-Normalisierung).

## 6. Grenzen & Risiken

- Evidenz für LLM-Reward-Design stammt fast vollständig von GPT-4-Klasse-Modellen; RF-Agent zeigt
  3× Ergebnisunterschied zwischen GPT-4o-mini und GPT-4o auf derselben Schleife. Ein lokales 27B ist
  ungetestet auf dieser Aufgabe — daher Config-Editing statt Codegenerierung als Standardpfad.
- Sim-Fitness ≠ Real-Fitness: DR-Bereiche sind in der Sim nicht rankbar (DrEureka), und unsere Sim
  hat offene Punkte (Link-Massen, IMU, kp/kd, Backlash — sim-context §8). AutoRL optimiert auf das
  Modell, das da ist.
- Rechenbudget: ~8 h pro Generation; ksim-Ökosystem eingefroren (Pins nicht anheben), PureJaxRL-artiges
  vmap über Konfigurationen ist mit ksim/xax nicht möglich (ein Prozess = eine Config).
- Reward-Hacking bleibt möglich; F und die Sicherheits-Constraints sind die einzige Abwehr.
