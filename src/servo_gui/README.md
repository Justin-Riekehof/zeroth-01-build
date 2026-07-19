# Servo test GUI

Browser GUI to test **one servo at a time** (STS3215 / STS3250) with a 3D view of the
Zeroth-01 CAD model — click the servo you are testing, set the position interval, and
watch the range gauge + live position while the test runs.

## Run

PowerShell (Windows):

```powershell
cd src\servo_gui; uv sync; uv run server.py
```

Bash (Ubuntu/macOS):

```bash
cd src/servo_gui && uv sync && uv run server.py
```

Open <http://127.0.0.1:8451>. (The 3D libraries load from a CDN — internet required.)

## CAD model

The viewer loads the **pinned OnShape version** from
`resources/cad/zeroth01-opus-v-cbb18739.glb` (see [resources/cad/VERSION.md](../../resources/cad/VERSION.md)).
If the file is missing, the GUI shows instructions — either run
`python resources/cad/download_model.py` (needs free OnShape API keys) or export the
GLB manually from the pinned URL and drag & drop it into the GUI window.

## Usage

1. **Connection** — pick the COM port of the Waveshare bus servo adapter and *Connect*
   (12 V on, jumper on B, one servo attached — same bench setup as
   `src/tests/servos/sts3250_test.py`). Or leave **Simulation** checked to try
   everything without hardware.
2. **Servo** — click the part in the 3D model that corresponds to the servo on the
   bench. *save mapping* remembers servo ID + model per CAD part
   (stored in `servo_map.json`).
3. **Test interval** — set min/max in degrees **relative to the center position**
   (see calibration convention below; seam-safe limits ±176.5° are enforced), speed,
   acceleration, cycles. *Run test* pings the servo, moves to min, then sweeps
   min → max → min. The orange sector in the 3D view shows the interval (gray marker
   = 0° center); the white needle is the live position. Torque is always disabled at
   the end — also on *Stop* or error.

## Calibration convention

Before mounting a printed part, move the servo to its **center position** with the
*⌂ Move to center* button: tick 2048 = 180° absolute. The part is then mounted in its
neutral pose, giving **±180° of travel in both directions** (±176.5° with seam-safety).
All angles in the GUI and API are **relative to this center** — 0° = mount position,
negative = one direction, positive = the other.

The **gauge axis** dropdown only orients the visualization ring; it does not affect
the hardware.

## Safety

- Output shaft must be free to rotate — same rule as the bench test.
- Position limits keep distance to the 0/4095 encoder seam
  (see the comment block in `sts3250_test.py` for why).
- One servo per test run, matching the single-servo bench wiring.
