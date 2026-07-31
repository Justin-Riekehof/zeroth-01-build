import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
"""Verify M2 connection config: /api/connect resolves the port from
hardware/connection.json ('auto' keeps auto-detection, explicit value pins,
UI choice always wins); /api/status exposes the merged connection config."""
import json, tempfile
from pathlib import Path
from fastapi.testclient import TestClient
import server
from zbot_core.config import ConfigStore

tmp = Path(tempfile.mkdtemp())
server.CFG = ConfigStore(tmp)
server.ENGINE.cfg = server.CFG

ok = True
def check(name, cond):
    global ok; ok = ok and cond
    print(("PASS" if cond else "FAIL"), name)


opened = []
class StubBus:
    simulated = False
    def __init__(self, port):
        self.port = port
        opened.append(port)
    def close(self): pass
server.ServoBus = StubBus

client = TestClient(server.app)

# defaults merge (no file on disk)
conn = client.get("/api/status").json()["connection"]
check(f"status exposes merged defaults ({conn})",
      conn["mode"] == "usb" and conn["port"] == "auto"
      and "pi_url" in conn)

# pinned port in connection.json is used when the UI sends none
server.CFG.connection_path.write_text(json.dumps({"port": "COM9"}))
r = client.post("/api/connect", json={})
check(f"pinned port used ({r.json()})",
      r.status_code == 200 and r.json()["port"] == "COM9"
      and opened == ["COM9"])
client.post("/api/disconnect")

# explicit UI port overrides the pin
r = client.post("/api/connect", json={"port": "COM7"})
check(f"UI override wins ({r.json()})",
      r.status_code == 200 and r.json()["port"] == "COM7"
      and opened[-1] == "COM7")
client.post("/api/disconnect")

# partial file still merges defaults
conn = client.get("/api/status").json()["connection"]
check("partial file merges defaults (mode/pi_url present)",
      conn["mode"] == "usb" and conn["port"] == "COM9"
      and conn["pi_url"].startswith("http"))

print("\nALL PASS" if ok else "\nSOME FAILED")
