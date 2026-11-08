"""Run: python collector/tests/test_airnav.py   (no pytest, no network: the AirNav Radar API is mocked).

The answers below follow the FlightsResponse / ApiFlight schema of the AirNav On Demand API v2 OpenAPI
(https://www.airnavradar.com/api/openapi, v2.4.22). No real AirNav answer was available when this was written.
"""
import os
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import extra  # noqa: E402

posts = []


def flight(cs, hexid, lat, lon, dep="LCLK", arr="EGLL", classes=("AIRLINER",)):
    return {"callsign": cs, "aircraftModeS": hexid.upper(), "aircraftRegistration": "5B-DCX", "aircraftType": "A20N",
            "aircraftClasses": list(classes), "latitude": lat, "longitude": lon, "altitude": 36000, "groundSpeed": 450,
            "heading": 290, "squawkCode": 4512, "depAirportIcao": dep, "depAirportIata": "LCA", "depAirportCity": "Larnaca",
            "arrAirportIcao": arr, "arrAirportIata": "LHR", "arrAirportCity": "London", "airlineIcao": "CYP",
            "flightNumberIata": "CY326", "flightUrl": f"https://www.airnavradar.com/data/flights/{cs}"}


class Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def fake_post(url, json=None, headers=None, timeout=None):
    posts.append((url, json, headers.get("Authorization")))
    if fake_post.status != 200:
        return Resp(fake_post.status, {})
    if "flightIds" in json:
        return Resp(200, {"success": True, "cost": len(json["flightIds"]), "flights": [flight("CYP326", "4b1801", 35.0, 31.0)]})
    return Resp(200, {"success": True, "cost": 40, "flights": [flight("CYP326", "4b1801", 35.0, 31.0),
                                                                flight("RRR4951", "43c6f1", 35.2, 24.9, "LGSA", "LCRA", ("MILITARY",))]})


fake_post.status = 200
extra.requests = types.SimpleNamespace(post=fake_post, get=None)
for k in ("FR24_API_TOKEN", "FLIGHTAWARE_API_KEY", "AIRNAV_MODE", "AIRNAV_EVERY_MIN", "AIRNAV_MAX_PER_DAY"):
    os.environ.pop(k, None)

# ---------------------------------------------------------------- not configured: nothing called
os.environ.pop("AIRNAV_API_TOKEN", None)
fl, st = extra.fetch_airnav_area({}, have_adsb=True)
assert fl is None and st is None and extra.enrich_flights([{"callsign": "CYP326"}], {}) == [] and not posts

# ---------------------------------------------------------------- routes mode (default)
os.environ["AIRNAV_API_TOKEN"] = "test-token"
state = {}
flights = [{"callsign": "CYP326", "hex": "4b1801"}, {"callsign": "THY7RX", "hex": "4ba9c1"}]
st = extra.enrich_flights(flights, state)
assert len(posts) == 1 and posts[0][0].endswith("/v2/flights/live") and posts[0][2] == "Bearer test-token", posts
assert posts[0][1] == {"flightIds": ["CYP326", "THY7RX"]}, posts[0][1]
assert flights[0]["route"]["orig"] == "LCLK" and flights[0]["route"]["src"] == "AirNav Radar" and "route" not in flights[1], flights
assert st[0]["name"] == "AirNav Radar" and "1/2 callsigns" in st[0]["note"], st
fl, st_area = extra.fetch_airnav_area(state, have_adsb=True)
assert fl is None and st_area is None  # area mode off while ADS-B works

# inside the 30 min window: no new request even for a new callsign
flights2 = [{"callsign": "MSR781"}]
st = extra.enrich_flights(flights2, state)
assert len(posts) == 1 and "cached" in st[0]["note"], st

# ---------------------------------------------------------------- area mode, and the fallback when ADS-B is down
os.environ["AIRNAV_MODE"] = "routes,area"
fl, st = extra.fetch_airnav_area(state, have_adsb=True)
assert len(posts) == 2 and posts[1][1]["minLongitude"] == 23.0 and posts[1][1]["maxLongitude"] == 40.2, posts[1][1]
assert len(fl) == 2 and fl[1]["mil"] and fl[1]["hex"] == "43c6f1" and fl[1]["src"] == "AirNav Radar", fl
adsb = [{"callsign": "CYP326", "hex": "4b1801", "lat": 35.0, "lon": 31.0}]
assert extra.merge_airnav(adsb, fl) == 1 and adsb[1]["callsign"] == "RRR4951"
assert state["routes"]["RRR4951"]["d"]["dest"] == "LCRA"

os.environ["AIRNAV_MODE"] = "routes"
state2 = {}
fl, st = extra.fetch_airnav_area(state2, have_adsb=False)  # area off, but no ADS-B this run: AirNav fills in
assert len(fl) == 2 and "ADS-B aggregators down" in st["note"], st

# ---------------------------------------------------------------- daily cap and errors
os.environ["AIRNAV_MAX_PER_DAY"] = "1"
fl, st = extra.fetch_airnav_area(state2, have_adsb=False)
assert len(posts) == 3 and "daily request cap" in st["note"] and fl, st  # cached positions (< 30 min) reused
os.environ["AIRNAV_MAX_PER_DAY"] = "48"
state3 = {}
fake_post.status = 401
st = extra.enrich_flights([{"callsign": "CYP326"}], state3)
assert not st[0]["ok"] and "401" in st[0]["note"], st

# an expired token comes back as HTTP 200, success=false, with the token in the comment: it must not reach live.json
fake_post.status = 200
extra.requests = types.SimpleNamespace(post=lambda url, json=None, headers=None, timeout=None: Resp(
    200, {"success": False, "cost": 0, "comment": "Token test-token is inactive/expired ."}), get=None)
st = extra.enrich_flights([{"callsign": "CYP326"}], {})
assert not st[0]["ok"] and "test-token" not in st[0]["note"] and "<token> is inactive" in st[0]["note"], st
print("airnav OK:", len(posts), "requests mocked")
