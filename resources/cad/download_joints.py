#!/usr/bin/env python3
"""Download the joint (revolute mate) definitions of the pinned Zeroth-01 CAD
version from OnShape and store them as a local snapshot.

The GLB export contains geometry only — joint axes/origins live in the assembly
definition. This extracts every REVOLUTE mate: name, rotation axis and center
(in the assembly frame, meters), plus the names of the mated occurrences so the
servo GUI can match them to clicked parts.

Needs ONSHAPE_ACCESS_KEY / ONSHAPE_SECRET_KEY (like download_model.py).
Output: zeroth01-joints-v-cbb18739.json (next to this script).
"""

import base64
import json
import os
import sys
import urllib.request

DID = "b4672a7f8ce3947bd250f2c1"
WVM = "m"                                # microversion pin
WVMID = "93de75674ad4a5ad06ef4abc"
EID = "6e9a04dde965d2dab1a3d9af"

URL = (f"https://cad.onshape.com/api/v6/assemblies/d/{DID}/{WVM}/{WVMID}/e/{EID}"
       "?includeMateFeatures=true&includeMateConnectors=true")

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "z001-joints-m-93de7567.json")


def mat_vec(t, v, w=1.0):
    """Apply a row-major 4x4 transform (list of 16) to a 3-vector."""
    return [t[0] * v[0] + t[1] * v[1] + t[2] * v[2] + t[3] * w,
            t[4] * v[0] + t[5] * v[1] + t[6] * v[2] + t[7] * w,
            t[8] * v[0] + t[9] * v[1] + t[10] * v[2] + t[11] * w]


def main():
    access = os.environ.get("ONSHAPE_ACCESS_KEY")
    secret = os.environ.get("ONSHAPE_SECRET_KEY")
    if not access or not secret:
        sys.exit("ONSHAPE_ACCESS_KEY / ONSHAPE_SECRET_KEY not set "
                 "(see VERSION.md).")

    auth = base64.b64encode(f"{access}:{secret}".encode()).decode()
    req = urllib.request.Request(URL, headers={
        "Authorization": f"Basic {auth}", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        doc = json.load(resp)

    ra = doc["rootAssembly"]
    names = {i["id"]: i["name"] for i in ra.get("instances", [])}
    transforms = {tuple(o["path"]): o["transform"]
                  for o in ra.get("occurrences", [])}

    joints = []
    for f in ra.get("features", []):
        fd = f.get("featureData", {})
        if f.get("featureType") != "mate" or fd.get("mateType") != "REVOLUTE":
            continue
        ent = fd["matedEntities"][0]
        t = transforms.get(tuple(ent["matedOccurrence"]))
        cs = ent["matedCS"]
        origin = mat_vec(t, cs["origin"]) if t else cs["origin"]
        axis = mat_vec(t, cs["zAxis"], w=0.0) if t else cs["zAxis"]
        # x-axis of each mate connector (assembly frame) = in-plane zero
        # reference of the revolute mate, one per mated part
        xaxes = []
        for e in fd["matedEntities"]:
            te = transforms.get(tuple(e["matedOccurrence"]))
            xa = e["matedCS"]["xAxis"]
            xaxes.append([round(v, 6)
                          for v in (mat_vec(te, xa, w=0.0) if te else xa)])
        joints.append({
            "name": fd.get("name", "?"),
            "origin": [round(v, 6) for v in origin],
            "axis": [round(v, 6) for v in axis],
            "xaxes": xaxes,
            "occurrences": [names.get(e["matedOccurrence"][-1], "?")
                            for e in fd["matedEntities"]],
        })

    # rigid connections (FASTENED mates and mate groups) — needed to build
    # the kinematic tree for posing the model in the GUI
    fastened = []
    for f in ra.get("features", []):
        fd = f.get("featureData", {})
        if f.get("featureType") == "mate" and fd.get("mateType") == "FASTENED":
            ents = fd.get("matedEntities", [])
            if len(ents) >= 2:
                fastened.append([names.get(e["matedOccurrence"][-1], "?")
                                 for e in ents[:2]])
        elif f.get("featureType") == "mateGroup":
            occs = [names.get(o.get("occurrence", ["?"])[-1], "?")
                    for o in fd.get("occurrences", [])]
            fastened.extend([a, b] for a, b in zip(occs, occs[1:]))

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump({"document": DID, "microversion": WVMID, "element": EID,
                   "frame": "assembly (CAD, Z-up, meters)",
                   "joints": joints, "fastened": fastened}, fh, indent=2)
    print(f"OK: {len(joints)} revolute joints, "
          f"{len(fastened)} rigid links -> {OUT}")
    for j in joints:
        print(f"  {j['name']:24s} axis {j['axis']}  @ {j['origin']}")


if __name__ == "__main__":
    main()
