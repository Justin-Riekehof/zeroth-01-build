#!/usr/bin/env python3
"""Download the pinned Zeroth-01 CAD version as GLB from OnShape.

The document is public, but OnShape gates geometry export behind authentication.
Create free API keys at https://dev-portal.onshape.com/keys and set:

    ONSHAPE_ACCESS_KEY / ONSHAPE_SECRET_KEY

Then run:  python resources/cad/download_model.py

Pinned reference (immutable, see VERSION.md):
    document b4672a7f8ce3947bd250f2c1 ("[0]th Z001")
    microversion 93de75674ad4a5ad06ef4abc
    element 6e9a04dde965d2dab1a3d9af (assembly "Opus")
"""

import base64
import os
import sys
import urllib.request

DID = "b4672a7f8ce3947bd250f2c1"
WVM = "m"                                # microversion pin
WVMID = "93de75674ad4a5ad06ef4abc"
EID = "6e9a04dde965d2dab1a3d9af"

URL = (f"https://cad.onshape.com/api/v6/assemblies/d/{DID}/{WVM}/{WVMID}/e/{EID}/gltf"
       "?outputSeparateFaceNodes=false&outputFaceAppearances=true")

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "z001-opus-m-93de7567.glb")


def main():
    access = os.environ.get("ONSHAPE_ACCESS_KEY")
    secret = os.environ.get("ONSHAPE_SECRET_KEY")
    if not access or not secret:
        sys.exit("ONSHAPE_ACCESS_KEY / ONSHAPE_SECRET_KEY not set.\n"
                 "Create free API keys at https://dev-portal.onshape.com/keys\n"
                 "(or export the GLB manually — see VERSION.md).")

    auth = base64.b64encode(f"{access}:{secret}".encode()).decode()
    req = urllib.request.Request(URL, headers={
        "Authorization": f"Basic {auth}",
        "Accept": "model/gltf-binary",
    })
    print("Downloading pinned GLB from OnShape (may take a minute) ...")
    with urllib.request.urlopen(req, timeout=600) as resp:
        data = resp.read()

    if data[:4] != b"glTF":
        sys.exit(f"Unexpected response (not a GLB): {data[:200]!r}")

    with open(OUT, "wb") as f:
        f.write(data)
    print(f"OK: {OUT} ({len(data) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
