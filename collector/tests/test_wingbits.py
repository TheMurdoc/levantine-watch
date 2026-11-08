"""Run: python collector/tests/test_wingbits.py   (no pytest, no network: the Wingbits customer API is mocked).

Answers follow the /v1/gps/jam and /v1/account/usage schemas of https://customer-api.wingbits.com/openapi.json.
"""
import os
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import extra  # noqa: E402

calls = []


class Resp:
    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body

    def raise_for_status(self):
        pass


def fake_get(url, timeout=None, headers=None, params=None):
    calls.append((url, dict(params or {})))
    if url.endswith("/account/usage"):
        return Resp({"plan": "x", "monthlyLimit": 10000, "monthlyUsed": 40, "monthlyRemaining": 9960})
    if "date" in (params or {}):  # day aggregate: zero-padded index, documented optional fields
        return Resp({"lastUpdated": "2026-11-08T18:00:00Z", "hexes": [
            {"h3Index": "0843f495ffffffff", "sampleCount": 900, "aircraftCount": 40, "npAvg": 6.5,
             "aircraftHours": 55, "mlatAircraftHours": 4, "adsbNpAvg": 7.9}]})
    return Resp({"lastUpdated": "2026-11-08T17:00:00Z", "hexes": [
        {"h3Index": "0843f495ffffffff", "sampleCount": 2264, "aircraftCount": 7, "npAvg": 8.2},
        {"h3Index": "0842da3bffffffff", "sampleCount": 10, "aircraftCount": 2, "npAvg": 2.0}]})


extra.requests = types.SimpleNamespace(get=fake_get, post=None)
os.environ["WINGBITS_API_KEY"] = "k"
state = {}
res, st = extra.fetch_wingbits_gnss(state)
a, b = res["hexes"]
assert a["h3"] == "843f495ffffffff" and a["np"] == 8.2 and a["samples"] == 2264 and a["aircraft"] == 7, a
assert a["mlat_h"] == 4 and a["ah"] == 55 and a["adsb_np"] == 7.9 and a["day_np"] == 6.5, a
assert "mlat_h" not in b and b["sev"] > 0.7, b
assert "1 with GPS-lost aircraft" in st["note"] and "9960 of 10000 monthly requests left" in st["note"], st
assert len(calls) == 3, calls
# within 30 min: hourly and day grids cached, only no-quota work
res, st = extra.fetch_wingbits_gnss(state)
assert len(calls) == 3 and "(cached)" in st["note"] and res["hexes"][0]["mlat_h"] == 4, st
print("wingbits OK:", len(calls), "requests mocked")
