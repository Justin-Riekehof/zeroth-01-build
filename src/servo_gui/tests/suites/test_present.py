import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
import json, tempfile
from pathlib import Path
from fastapi.testclient import TestClient
import server
from zbot_core.config import ConfigStore

tmp = Path(tempfile.mkdtemp())
server.CFG = ConfigStore(tmp)
server.ENGINE.cfg = server.CFG
server.CFG.servo_ids_path.write_text(json.dumps(
    {"a": 11, "b": 12, "c": 13, "d": 21, "e": 22, "f": 23}))


class FakeBus:
    simulated = False
    port = "FAKE"
    present = {11, 12, 21}

    def ping(self, sid):
        if sid in self.present:
            return 3215
        raise server.ServoBusError("no response")


server.S.bus = FakeBus()
server.S.live["running"] = False
r = TestClient(server.app).get("/api/present").json()
ok = r["present"] == [11, 12, 21] and r["configured"] == [11, 12, 13, 21, 22, 23]
print("present:", r["present"], "| configured:", r["configured"],
      "=>", "PASS" if ok else "FAIL")
