# Pinned CAD model — Zeroth Z001 ("[0]th Z001" / assembly "Opus")

The OnShape document is under continuous development. All work in this repo refers to
the **exact state pinned below**. The user-facing URL points to a *workspace* (`/w/`,
mutable), so the pin is the **microversion** captured on the date below — microversion
URLs (`/m/<id>/`) are immutable and always reproduce this exact geometry.

| Field             | Value                                       |
| ----------------- | ------------------------------------------- |
| Document          | [0]th Z001 (owner: Kelsey Pool / K-Scale)   |
| Document ID       | `b4672a7f8ce3947bd250f2c1`                  |
| **Microversion**  | `93de75674ad4a5ad06ef4abc`                  |
| Element           | Assembly **"Opus"** (full body)             |
| Element ID        | `6e9a04dde965d2dab1a3d9af`                  |
| Pinned on         | 2026-07-19                                  |

**Workspace URL (live, for browsing):**
<https://cad.onshape.com/documents/b4672a7f8ce3947bd250f2c1/w/ff02744612b3ad395d4541a6/e/6e9a04dde965d2dab1a3d9af>

**Pinned URL (immutable, the reference):**
<https://cad.onshape.com/documents/b4672a7f8ce3947bd250f2c1/m/93de75674ad4a5ad06ef4abc/e/6e9a04dde965d2dab1a3d9af>

## Local snapshots

| File | Content | Created by |
| ---- | ------- | ---------- |
| `z001-opus-m-93de7567.glb` | Geometry (binary glTF, 16.2 MB) | `download_model.py` |
| `z001-joints-m-93de7567.json` | All 16 revolute joints: name, rotation axis, center (assembly frame, Z-up, meters), mate-connector x-axes, mated occurrence names | `download_joints.py` |

The servo test GUI (`src/servo_gui/`) loads both from here — the joints file drives
the automatic orientation of the test-interval gauge (axis, rotation center and the
0°/zero direction along the mounted part).

## Re-creating the snapshots

OnShape gates geometry export behind authentication (free API keys:
<https://dev-portal.onshape.com/keys>, Read scope is enough):

```powershell
$env:ONSHAPE_ACCESS_KEY = "..."
$env:ONSHAPE_SECRET_KEY = "..."
python resources\cad\download_model.py
python resources\cad\download_joints.py
```

Because the microversion is immutable, re-running anytime yields identical data.
To move the pin to a newer state of the workspace: get the current microversion
(`GET /api/v6/documents/d/<did>/w/<wid>/currentmicroversion`), update `WVMID` and the
output filenames in both scripts, re-run, and update the paths in
`src/servo_gui/server.py` + the drop-hint in `src/servo_gui/static/index.html`.

## Superseded reference (kept for history)

Until 2026-07-19 this repo referenced the older "OpenLCH" document, assembly "Opus":
document `cacc96f8a7850b951e7aa69a`, version `cbb187394d36d76f5d27cf84`, element
`b53fc045ae6c03f8f08a378f` — snapshots `zeroth01-opus-v-cbb18739.glb` /
`zeroth01-joints-v-cbb18739.json` remain in this folder.

> Note: the GLBs are 8–17 MB. If repo size becomes an issue, move them to Git LFS.
