# Hardware-Testaufnahmen

Fotos und Videos der Hardwaretests mit Lauf-Policies. Jede Datei ist nach dem Pi-Log benannt, zu dem sie gehört:
`<HHMMSS>_<Ansicht>_<Einstellung>.mp4`. Das Log liegt unter
`sim/policies/<policy>/hw_logs_<datum>/<datum>-<HHMMSS>_<policy>.npz`. Die Auswertung steht in
[docs/training-journal.md](../../docs/training-journal.md).

Videos: iPhone-Zeitlupe (120 FPS, 4-fach verlangsamt), per WhatsApp weitergeleitet (1024×576, komprimiert). Die
Clips enthalten nur den Zeitlupen-Teil, ihr Anfang fällt also nicht genau mit dem Policy-Start zusammen. Echte
Zeit = Videozeit / 4.

Namenszusätze:
- `ramp1s`: Der Pi blendete die Policy noch über 1 s ein (`RAMP_STEPS = 50`).
- `noramp`: Volle Wirkung ab Schritt 0 wie im Sim (`start_ramp_steps 0`, Fix vom 21.11. abends).
- `hipfixed`: Linke Hüfte nachgezogen (saß locker).

## 2026-11-21, `servo_rubber23_step3315`, Gummisohle, Parkett

Rechtes Bein und Hüfte vorher repariert. Logs: `sim/policies/servo_rubber23_step3315/hw_logs_2026-11-21/`.

| Datei | Befehl | Pi-Ende (Logdauer) | Beobachtung |
|---|---|---|---|
| `gui_walking_policy_settings.png` | – | – | GUI-Einstellung der Läufe 19:02 (vx 0,045, Gang 1,125 Hz) |
| `190243_side_vx0.045_ramp1s.mp4` | vx 0,045 · 1,125 Hz | Sturz (1,9 s) | Trippelt und dreht sich um die Hochachse (am Ende frontal zur Kamera) |
| `190306_side_vx0.045_ramp1s.mp4` | vx 0,045 · 1,125 Hz | Sturz (5,2 s) | Kippt steif über die vordere Sohlenkante, kein Ausfallschritt |
| `191325_side_vx0.03_ramp1s.mp4` | vx 0,03 · 1,0 Hz | Sturz (2,5 s) | Steht ~1 s still, 1–2 Schritte mit Drehung, kippt nach vorn |
| `191344_side_vx0.03_ramp1s.mp4` | vx 0,03 · 1,0 Hz | E-Stopp (5,3 s) | wie oben |
| `191356_side_vx0.03_ramp1s.mp4` | vx 0,03 · 1,0 Hz | Sturz (1,9 s) | wie oben |
| `210112_side_vx0.03_noramp.mp4` | vx 0,03 · 1,0 Hz | Sturz (2,2 s) | Echte Schritte ab Start, dreht sich nach ~1,5 s |
| `210131_side_vx0.03_noramp.mp4` | vx 0,03 · 1,0 Hz | Sturz (1,7 s) | wie oben |
| `210147_side_vx0.03_noramp.mp4` | vx 0,03 · 1,0 Hz | Sturz (2,3 s) | Legt sich nach vorn, fängt sich mit einem Schritt, dreht später |

## 2026-11-22, `servo_rubber23_step3315`, ohne Rampe, linke Hüfte fixiert

Logs: `sim/policies/servo_rubber23_step3315/hw_logs_2026-11-22/`. Die Zuordnung der Videos zu den Logs folgt der
Reihenfolge (seitlich und von oben abwechselnd). Die Clip-Längen passen zu den Logdauern. Von oben verdeckt der
Rucksack die Füße.

| Datei | Befehl | Pi-Ende (Logdauer) |
|---|---|---|
| `125550_side_vx0.03_noramp_hipfixed.mp4` | vx 0,03 · 1,0 Hz | Sturz (1,4 s) |
| `125621_top_vx0.03_noramp_hipfixed.mp4` | vx 0,03 · 1,0 Hz | E-Stopp (2,4 s) |
| `125653_side_vx0.03_noramp_hipfixed.mp4` | vx 0,03 · 1,0 Hz | Sturz (1,1 s) |
| `125718_top_vx0.03_noramp_hipfixed.mp4` | vx 0,03 · 1,0 Hz | E-Stopp (1,7 s) |
| `125733_side_vx0.03_noramp_hipfixed.mp4` | vx 0,03 · 1,0 Hz | E-Stopp (2,2 s) |
| `125753_top_vx0.03_noramp_hipfixed.mp4` | vx 0,03 · 1,0 Hz | E-Stopp (2,3 s) |

## 2026-11-23, Torsions-Handtest (ohne Policy)

Der Roboter steht in Center-Pose auf Parkett, mit Krepp-Marken an den Fußspitzen. Der Nutzer drückt mit der Hand am
Rucksack ein Giermoment ein. Die Drehrichtung ist im Uhrzeigersinn, wenn man von oben auf den nach vorn gerichteten
Roboter schaut. Kein Pi-Log. Die Fotos sind nach Reihenfolge benannt (WhatsApp 07:00:23). Bei den Fußfotos ist nicht
angegeben, welches zu welchem Moment gehört. Die Zuordnung `ccw`/`cw` der Fotos von oben ist aus der Angabe des
Nutzers abgeleitet: Nur gegen den Uhrzeigersinn war ein Unterschied zu sehen.

| Datei | Moment | Beobachtung |
|---|---|---|
| `torsion_feet_1.jpg`, `torsion_feet_2.jpg`, `torsion_feet_3.jpg` | ohne / CW / CCW (Reihenfolge offen) | Sohlenkanten auf allen drei Fotos gleich zum Krepp, keine Verdrehung oder Verschiebung sichtbar (Auflösung ~1–2 mm, ~1°) |
| `torsion_top_none.jpg` | ohne | Referenz: Kopfkante etwa parallel zur Linie durch die Fußmarken |
| `torsion_top_ccw.jpg` | gegen Uhrzeigersinn | Kopf etwa 3° gegen die Fußmarken verdreht (Schätzung aus dem Foto, ±1°), elastisch |
| `torsion_top_cw.jpg` | im Uhrzeigersinn | wie ohne Moment |

## 2026-11-28, `servo_comp6_step6115` (vx 0,045, Gang 1,1 Hz, Parkett, Kabel als Leine)

Erste Policy aus dem Training mit Gelenkspiel/Elastizität. WhatsApp-Zeitlupen (120 FPS, 4-fach). Benannt nach der Pi-Log-Zeit
(Reihenfolge = Logs). Dauer = Policy-Laufzeit laut Pi-Log, Ende in Klammern.

| Datei | Dauer | Beobachtung |
|---|---|---|
| `143521_side_servo_comp6_step6115.mp4` | 2,0 s (Sturz) | 2–3 Schritte, dreht, kippt nach vorn |
| `143558_top_servo_comp6_step6115.mp4` | 2,1 s (E-Stopp) | Gierung ~30–45° im Uhrzeigersinn, kippt |
| `143626_side_servo_comp6_step6115.mp4` | 1,7 s (Sturz) | kleine Schritte, dreht, fällt über den vorderen Fuß |
| `143641_top_servo_comp6_step6115.mp4` | 1,8 s (Sturz) | Gierung ~30–40° |
| `143705_side_servo_comp6_step6115.mp4` | 5,7 s (Sturz) | **erste mehreren Schritte etwa vorwärts** (Meilenstein), starker Zug nach links |
| `143853_top_servo_comp6_step6115.mp4` | 3,3 s (E-Stopp) | mehrere Schritte fast rein nach links, kaum vorwärts |
