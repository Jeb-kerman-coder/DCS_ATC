import sys, types
import os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from atc_pipeline import ATCPipeline
from contact_manager import ContactManager
from core.braa_calculator import BRAACalculator
from loadout_parser import LoadoutParser
from procedure_manager import ProcedureManager

class FakeParser:
    def __init__(self, r): self.r = r
    def parse(self, t): return self.r
class FakeLLM:
    def generate_controller_response(self, **kw):
        FakeLLM.last = kw; return "ok"

NM = 1852
cm = ContactManager()
cm.update({"ownship": {"x": 0, "y": 6000, "z": 0},
           "contacts": [
              {"id": 1, "type": "MiG-29", "x": 10*NM, "y": 9000, "z": 0, "relationship": "HOSTILE"},
              {"id": 2, "type": "F-16C", "x": 2*NM, "y": 3000, "z": 0, "relationship": "FRIENDLY"},
           ]})
logs = []
def mk(intent, heading=90, fallback=None):
    return ATCPipeline(FakeParser(intent), LoadoutParser(), ProcedureManager(), FakeLLM(), cm,
                       BRAACalculator(), lambda: heading, fallback, lambda: ("Enfield 2-1", "F-16C"),
                       lambda s, m: logs.append((s, m)))

# bogey dope: nearest = friendly #2 (2NM) -> bearing 000, rel -90 = 270
p = mk("BOGEY_DOPE_REQUEST"); r = p.respond("AWACS", 225.87, "bogey dope")
d = FakeLLM.last["response_data"]; print("BOGEY", r, d["contact_type"], d["bearing_deg"], d["relative_bearing_deg"], d["range_nm"], d["altitude_ft"], FakeLLM.last["callsign"], FakeLLM.last["aircraft"])
assert d["bearing_deg"] == 0 and d["relative_bearing_deg"] == 270 and d["range_nm"] == 2.0

# picture sorted by range, relationship carried through
p = mk("PICTURE_REQUEST"); p.respond("GCI", 1, "picture")
d = FakeLLM.last["response_data"]; print("PIC", [(c["id"], c["relationship"], c["range_nm"]) for c in d["contacts"]])
assert [c["id"] for c in d["contacts"]] == [2, 1]

# on station tasks hostile only (this is the GCI path that used to crash)
p = mk("ON_STATION_REQUEST"); p.respond("GCI", 1, "gci on station 4 amraam 2 sidewinder")
d = FakeLLM.last["response_data"]; print("ONSTA", d["tasking_available"], d["task_target"]["type"], d["task_target"]["range_nm"], d["amraam"], d["sidewinder"])
assert d["tasking_available"] and d["task_target"]["id"] == 1

# no heading -> picture refuses; on-station still answers without tasking
p = mk("PICTURE_REQUEST", heading=None); print("NOHDG pic ->", p.respond("AWACS", 1, "picture"))
FakeLLM.last = None
p = mk("ON_STATION_REQUEST", heading=None); p.respond("AWACS", 1, "on station"); print("NOHDG onsta", FakeLLM.last["response_data"]["tasking_available"])

# ownship fallback from telemetry when the AWACS feed has none
cm2 = ContactManager(); cm2.update({"contacts": [{"id": 9, "type": "Su-27", "x": 5*NM, "y": 1000, "z": 0, "relationship": "HOSTILE"}]})
p = ATCPipeline(FakeParser("BOGEY_DOPE_REQUEST"), LoadoutParser(), ProcedureManager(), FakeLLM(), cm2, BRAACalculator(),
                lambda: 0, lambda: {"x": 0, "y": 0, "z": 0}, None, None)
p.respond("AWACS", 1, "bogey dope"); print("FALLBACK", FakeLLM.last["response_data"]["range_nm"], FakeLLM.last["callsign"])

# tower passes straight through, unknown request -> None
p = mk("TAXI_REQUEST"); print("TOWER", p.respond("TOWER", 127.8, "taxi"), FakeLLM.last["controller_action"])
p = mk(None); print("UNKNOWN", p.respond("TOWER", 127.8, "mumble"))
p = mk("PICTURE_REQUEST"); print("NOPROC", p.respond("TOWER", 127.8, "picture"))
print("ALL PIPELINE TESTS PASSED")
