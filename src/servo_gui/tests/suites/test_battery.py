import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
"""Verify: /api/battery reads the pack voltage through the bus (register 62
of the first configured servo that answers), caches for 2 s, and reports
a disconnected bus / silent servos instead of failing. Temp configs only."""
import json, tempfile
from pathlib import Path
from fastapi.testclient import TestClient
import server
from zbot_core.config import ConfigStore

tmp = Path(tempfile.mkdtemp())
server.CFG = ConfigStore(tmp)
server.ENGINE.cfg = server.CFG
server.CFG.servo_ids_path.write_text(json.dumps({"a": 12, "b": 11}))

ok = True
def check(name, cond):
    global ok; ok = ok and cond
    print(("PASS" if cond else "FAIL"), name)


class VoltBus:
    """Fake bus: ID 11 silent, ID 12 answers 11.9 V; counts the reads."""
    simulated = False
    port = "FAKE"
    def __init__(self): self.reads = []
    def close(self): pass
    def read_voltage(self, sid):
        self.reads.append(sid)
        return 11.9 if sid == 12 else None


c = TestClient(server.app)

r = c.get("/api/battery").json()
check("disconnected -> error, no volts", r["volts"] is None and r["error"] == "not connected")

bus = VoltBus()
server._BATT.update(t=0.0)
with server.S.lock:
    server.S.bus = bus
r = c.get("/api/battery").json()
check("first answering configured ID wins (11 silent, 12 answers)",
      r["volts"] == 11.9 and r["servo_id"] == 12 and r["error"] is None)
check("IDs tried in ascending order", bus.reads == [11, 12])
r2 = c.get("/api/battery").json()
check("cached for 2 s (no second bus read)", r2["volts"] == 11.9 and bus.reads == [11, 12])

class SilentBus(VoltBus):
    def read_voltage(self, sid): return None
server._BATT.update(t=0.0)
with server.S.lock:
    server.S.bus = SilentBus()
r = c.get("/api/battery").json()
check("no servo answers -> error, volts None", r["volts"] is None and r["error"] == "no servo answers")

with server.S.lock:
    server.S.bus = None
sys.exit(0 if ok else 1)
