"""Run: python collector/tests/test_sealagom.py   (no pytest, no network: the SeaLagom API is mocked).

sealagom_sample.json is a trimmed copy of a real GET /api/v2/messages/ answer (7 Nov 2026, free tier, text only):
Cyprus (JRCC Larnaca), Antalya and Izmir NAVTEX, Hellenic NAVWARNs and one NAVAREA III message. The clock is fixed
so the test does not age.
"""
import json
import os
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import navtex  # noqa: E402

HERE = Path(__file__).resolve().parent
PAGE = json.loads((HERE / "sealagom_sample.json").read_text(encoding="utf-8"))


class FixedDT(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 11, 7, 20, 0, tzinfo=tz or timezone.utc)


navtex.datetime = FixedDT

calls = []


class Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body
        self.headers = {"content-type": "application/json"}
        self.reason = "Too Many Requests" if status == 429 else "OK"

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def fake_get(url, headers=None, params=None, timeout=None):
    calls.append((url, dict(params or {}), headers.get("X-API-Token")))
    if fake_get.status != 200:
        return Resp(fake_get.status, {"detail": "allowance reached"})
    return Resp(200, PAGE)


fake_get.status = 200
navtex.requests = types.SimpleNamespace(get=fake_get)

# ---------------------------------------------------------------- conversion of single records
by_num = {}
for rec in PAGE["results"]:
    m = navtex._sealagom_convert(rec)
    assert m, rec["number"]
    by_num.setdefault(rec["number"], []).append(m)

cy = by_num["345/26"][0]  # Cyprus: Abeille Marengo GSI survey polygon, degree sign + en dash coordinates, 4-digit years
assert cy["number"] == "NAVWARN 345/26", cy["number"]
assert cy["geom"] == "polygon" and len(cy["points"]) >= 19, (cy["geom"], len(cy["points"]))
assert cy["issued"] == "2026-11-06T18:00:00Z" and cy["valid_from"] == "2026-11-19T00:00:00Z", (cy["issued"], cy["valid_from"])
assert cy["valid_to"] == "2027-03-20T00:01:00Z", cy["valid_to"]
assert cy["vessels"] and cy["vessels"][0]["mmsi"] == "228505700" and cy["vessels"][0]["imo"] == "9388613", cy["vessels"]
assert "survey" in cy["tags"] and cy["clearance_nm"] == 2.0, (cy["tags"], cy.get("clearance_nm"))
assert cy["url"] == "https://www.sealagom.com/coastal/128/message/%s/" % cy["id"].split("/")[-1], cy["url"]
assert cy["station"] == "Cyprus Coastal"

cable = by_num["336/26"][0]  # curly apostrophes, "-033°22.25'E", vessel in quotes with MMSI
assert cable["geom"] == "polygon" and len(cable["points"]) >= 12 and "cable" in cable["tags"]
assert cable["vessels"] == [{"name": "SOPHIE GERMAIN", "mmsi": "228438600"}], cable["vessels"]
assert cable["valid_from"] == "2026-11-03T00:00:00Z" and cable["valid_to"] == "2026-12-27T00:01:00Z"

route = by_num["335/26"][0]
assert route["vessels"] == [{"name": "SOPHIE GERMAIN", "imo": "9930507"}], route["vessels"]

firing = by_num["342/26"][0]  # Greek zeta in ZCZC, "03 1230 UTC NOV 2026", cancel "12 1300 UTC NOV 2026"
assert firing["header"] == "MA94" and firing["issued"] == "2026-11-03T12:30:00Z" and firing["valid_to"] == "2026-11-12T13:00:00Z", (firing.get("header"), firing["issued"], firing["valid_to"])
assert firing["geom"] == "polygon" and len(firing["points"]) >= 14 and "firing" in firing["tags"]

tr = by_num["1111/26"][0]  # Turkish: "36 50.43 K - 030 47.57 D", two areas
assert tr["number"] == "ANTALYA NAVTEX 1111/26", tr["number"]
assert len(tr["points"]) >= 8 and abs(tr["points"][0][0] - 36.8405) < 0.01 and abs(tr["points"][0][1] - 30.7928) < 0.01, tr["points"][:2]

tr2 = by_num["1107/26"][0]  # Turkish point, falls back to the English translation when needed
assert tr2["geom"] == "point" and abs(tr2["points"][0][0] - 36.7838) < 0.01, tr2.get("points")

unparsed = by_num["1106/26"][0]  # no coordinates in the text: still listed, with number and text
assert unparsed["number"] == "ANTALYA NAVTEX 1106/26" and unparsed["text"] and not unparsed.get("points")

gr = by_num["1343/26"][0]  # "FROM 080600Z TO 081500Z NOV 26", DMS with en dash
assert gr["number"] == "HELLENIC NAVWARN 1343/26" and gr["valid_from"] == "2026-11-08T06:00:00Z" and gr["valid_to"] == "2026-11-08T15:00:00Z", (gr["number"], gr["valid_from"], gr["valid_to"])
assert gr["issued"] == "2026-11-06T00:00:00Z", gr["issued"]  # from added_on, not from the FROM..TO pair
assert gr["geom"] == "polygon" and len(gr["points"]) == 5

n3 = by_num["0169/26"][0]  # NAVAREA III, decimal commas, DAYS .. TO .., outside the region
assert n3["number"] == "NAVAREA III 0169/26" and n3["geom"] == "line" and len(n3["points"]) >= 25, (n3["number"], n3["geom"], len(n3["points"]))
assert n3["valid_from"] == "2026-11-05T00:00:00Z" and n3["valid_to"] == "2027-02-15T23:59:00Z"
assert not navtex._in_region(n3)

same = {m["number"] for m in by_num["1089/26"]}
assert same == {"ANTALYA NAVTEX 1089/26", "IZMIR NAVTEX 1089/26"}, same
print("sealagom conversion OK:", len(PAGE["results"]), "records")

# ---------------------------------------------------------------- fetch_navtex with the feed on, inbox off
os.environ["SEALAGOM_API_TOKEN"] = "test-token"
os.environ["SEALAGOM_FEEDS"] = "off"  # API path only here; the open station feeds are tested in test_sealagom_feeds.py
for k in ("NAVTEX_INBOX_FILE", "GITHUB_TOKEN", "GITHUB_REPOSITORY"):
    os.environ.pop(k, None)
state = {}
keep, statuses = navtex.fetch_navtex(state)
names = [s["name"] for s in statuses]
assert names == ["NAVTEX inbox", "SeaLagom"], names
sl = statuses[1]
assert sl["ok"] and len(calls) == 1 and calls[0][2] == "test-token", (sl, calls)
assert calls[0][1]["bbox"] == "23.0,29.0,40.2,37.3" and calls[0][1]["status"] == "in_force", calls[0][1]
nums = {m["number"] for m in keep}
assert "NAVWARN 345/26" in nums and "ANTALYA NAVTEX 1111/26" in nums and "NAVWARN 342/26" in nums, nums
assert "NAVAREA III 0169/26" not in nums and "HELLENIC NAVWARN 1350/26" not in nums, nums  # outside the box
assert "HELLENIC NAVWARN 1343/26" not in nums, nums  # Samos, north of the map
assert next(m for m in keep if m["number"] == "NAVWARN 345/26")["upcoming"] is True
assert all(m["id"].startswith("sealagom ") for m in keep)
assert "sealagom" in state and state["_t"]["sealagom"] > 0
assert "shown" in sl["note"] and "1 call" in sl["note"], sl["note"]

# second run inside the refresh window: served from state, no request
keep2, statuses2 = navtex.fetch_navtex(state)
assert len(calls) == 1 and len(keep2) == len(keep) and "cached" in statuses2[1]["note"], statuses2[1]["note"]

# allowance exhausted: cached data stays, the status says why
state["_t"]["sealagom"] = 0
fake_get.status = 429
keep3, statuses3 = navtex.fetch_navtex(state)
assert len(calls) == 2 and len(keep3) == len(keep) and not statuses3[1]["ok"] and "429" in statuses3[1]["note"], statuses3[1]
print("sealagom fetch OK:", len(keep), "warnings kept of", len(PAGE["results"]), "·", sl["note"])
