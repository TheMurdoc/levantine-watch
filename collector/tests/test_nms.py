"""Run: python collector/tests/test_nms.py   (no pytest, no network: the NMS-API is mocked).

Part 1 (GeoJSON, mocked layouts): the FAA NOTAM API style (properties.coreNOTAMData.notam + ICAO translation),
flat properties, and a NOTAM whose only position is its ICAO Q-line.
Part 2 (AIXM, real): nms_aixm_lccc_sample.json holds 12 real NMS staging messages for the Nicosia FIR
(7 Nov 2026), checked with a fixed clock so the test does not age.
"""
import json
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import nms  # noqa: E402

now = datetime.now(timezone.utc)
iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%S.000Z")  # noqa: E731
icao = lambda d: d.strftime("%y%m%d%H%M")  # noqa: E731

danger = {  # FAA NOTAM API layout, polygon geometry, firing in the Nicosia FIR
    "type": "Feature",
    "properties": {"coreNOTAMData": {
        "notam": {"id": "NOTAM_1_1001", "series": "A", "number": "1234/26", "type": "N", "issued": iso(now - timedelta(days=1)),
                  "affectedFIR": "LCCC", "selectionCode": "QWMLW", "minimumFL": "000", "maximumFL": "250", "location": "LCCC",
                  "effectiveStart": iso(now - timedelta(hours=2)), "effectiveEnd": iso(now + timedelta(days=2)),
                  "text": "LIVE FIRING EXERCISE WILL TAKE PLACE IN AREA", "classification": "INTERNATIONAL", "icaoLocation": "LCCC"},
        "notamTranslation": [{"type": "ICAO", "formattedText": (
            "A1234/26 NOTAMN\nQ) LCCC/QWMLW/IV/BO/W/000/250/3440N03230E010\nA) LCCC B) " + icao(now - timedelta(hours=2)) +
            " C) " + icao(now + timedelta(days=2)) + "\nE) LIVE FIRING EXERCISE WILL TAKE PLACE WITHIN AREA 344000N 0322000E - 344000N 0324000E "
            "- 343000N 0324000E - 343000N 0322000E.\nF) SFC G) FL250")}]}},
    "geometry": {"type": "GeometryCollection", "geometries": [{"type": "Polygon", "coordinates": [[[32.333, 34.667], [32.667, 34.667], [32.667, 34.5], [32.333, 34.5], [32.333, 34.667]]]}]},
}
gnss_qline_only = {  # flat properties, no geometry: drawn from the Q-line circle
    "type": "Feature", "properties": {"id": "NOTAM_1_1002", "notamNumber": "B0456/26", "location": "LLLL", "classification": "INTERNATIONAL",
                                      "text": "Q) LLLL/QGWXX/IV/BO/E/000/999/3200N03500E150\nA) LLLL B) " + icao(now - timedelta(days=3)) +
                                              " C) " + icao(now + timedelta(days=30)) + " EST\nE) GNSS SIGNAL MAY BE UNRELIABLE WITHIN 150NM OF TEL AVIV."},
    "geometry": None}
runway = {"type": "Feature", "properties": {"coreNOTAMData": {"notam": {"id": "NOTAM_1_1003", "number": "0789/26", "selectionCode": "QMRLC", "location": "LCLK",
          "effectiveStart": iso(now - timedelta(hours=1)), "effectiveEnd": iso(now + timedelta(hours=5)), "text": "RWY 04/22 CLSD"},
          "notamTranslation": [{"type": "ICAO", "formattedText": "Q) LCCC/QMRLC/IV/NBO/A/000/999/3453N03338E005\nE) RWY 04/22 CLSD"}]}}, "geometry": None}
expired = {"type": "Feature", "properties": {"coreNOTAMData": {"notam": {"id": "NOTAM_1_1004", "number": "0001/26", "selectionCode": "QRDCA", "location": "LCCC",
           "effectiveStart": iso(now - timedelta(days=9)), "effectiveEnd": iso(now - timedelta(days=1)), "text": "DANGER AREA LCD10 ACT"},
           "notamTranslation": [{"type": "ICAO", "formattedText": "Q) LCCC/QRDCA/IV/BO/W/000/100/3500N03300E005\nE) DANGER AREA LCD10 ACT"}]}}, "geometry": None}
texas = {"type": "Feature", "properties": {"coreNOTAMData": {"notam": {"id": "NOTAM_1_1005", "number": "10/108", "selectionCode": "QRTCA", "location": "KDFW",
         "effectiveStart": iso(now - timedelta(hours=1)), "effectiveEnd": iso(now + timedelta(hours=5)), "text": "TFR"}}},
         "geometry": {"type": "Point", "coordinates": [-97.04, 32.9]}}

calls = []


class R:
    def __init__(self, status=200, js=None):
        self.status_code, self._js = status, js

    def json(self):
        return self._js

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(str(self.status_code))


def post(url, data=None, auth=None, headers=None, timeout=None):
    calls.append(("POST", url))
    assert url == "https://api-staging.cgifederal-aim.com/v1/auth/token" and data == {"grant_type": "client_credentials"} and auth == ("KEY", "SECRET")
    return R(js={"access_token": "TOKEN-123", "expires_in": "1799", "status": "approved"})


def get(url, headers=None, params=None, timeout=None):
    calls.append(("GET", url, tuple(sorted(params))))
    assert url == "https://api-staging.cgifederal-aim.com/nmsapi/v1/notams"
    assert headers["Authorization"] == "Bearer TOKEN-123" and headers["nmsResponseFormat"] == "GEOJSON"
    loc = params.get("location")
    if loc == "LCCC":
        return R(js={"status": "Success", "data": {"geojson": [danger, runway, expired]}})
    if loc == "LLLL":
        return R(js={"type": "FeatureCollection", "features": [gnss_qline_only]})
    if loc == "KDFW":
        return R(js={"items": [texas]})
    if loc == "OSTT":
        return R(status=500)
    return R(js={"data": {"geojson": []}})


nms.requests = types.SimpleNamespace(get=get, post=post)
os.environ.update(NMS_CLIENT_ID="KEY", NMS_CLIENT_SECRET="SECRET", NMS_ENV="staging", NMS_FORMAT="GEOJSON", NMS_LOCATIONS="LCCC,LLLL,KDFW,OSTT,OLBB", NMS_GEO="34.9,33.3,120")
state = {}
items, st = nms.fetch_notams(state)
ids = {m["id"] for m in items}
assert ids == {"NOTAM_1_1001", "NOTAM_1_1002"}, (ids, st)
d = next(m for m in items if m["id"] == "NOTAM_1_1001")
assert d["number"] == "A1234/26" and d["q"] == "QWMLW" and d["cat"] == "firing" and d["qtext"] == "missile, gun or rocket firing · will take place", d
assert d["shapes"][0]["shape"] == "polygon" and d["upper"] == "250" and d["limits_text"] == "SFC – FL250" and d["fir"] == "LCCC", d
assert d["text"].startswith("LIVE FIRING EXERCISE WILL TAKE PLACE WITHIN AREA"), d["text"]
g = next(m for m in items if m["id"] == "NOTAM_1_1002")
assert g["cat"] == "gnss" and g["shapes"] == [{"shape": "circle", "center": [32.0, 35.0], "r_nm": 150}] and g["to"] and g["from"], g
assert "staging" in st["note"] and "OSTT" in st["note"] and "OLBB" in st["note"], st
assert "TOKEN-123" not in repr(state), "the bearer token must never be stored"
n_calls = len(calls)
items2, st2 = nms.fetch_notams(state)  # within NMS_EVERY_MIN: served from cache, no calls
assert len(calls) == n_calls and len(items2) == 2 and "cached" in st2["note"]
print("nms geojson OK:", st["note"])

# ---- part 2: real AIXM answer
sample = json.loads((Path(__file__).with_name("nms_aixm_lccc_sample.json")).read_text(encoding="utf-8"))
nms._now = lambda: datetime(2026, 11, 7, 1, 0, tzinfo=timezone.utc)


def get_aixm(url, headers=None, params=None, timeout=None):
    assert headers["nmsResponseFormat"] == "AIXM"
    return R(js=sample if params.get("location") == "LCCC" else {"status": "Success", "data": {"aixm": []}})


nms.requests = types.SimpleNamespace(get=get_aixm, post=post)
os.environ.update(NMS_FORMAT="AIXM", NMS_LOCATIONS="LCCC,LCLK", NMS_GEO="off")
items, st = nms.fetch_notams({})
by = {m["number"]: m for m in items}
assert "A1253/26" not in by, "a NOTAMC (cancellation) is not shown"
assert "A0909/26" not in by, "obstacles (subject O) are filtered out by default"
assert list(by).count("A1121/26") == 1 and "A1121/26" in by, "duplicates collapse to one"
n = by["A1227/26"]  # NEMESIS-26: polygon from item E), limits from F)/G), Q-line beats the AIXM maximumFL field
assert n["cat"] == "exercise" and n["shapes"][0]["shape"] == "polygon" and len(n["shapes"][0]["ring"]) == 5, n
assert n["upper"] == "080" and n["limits_text"] == "SFC – 8000FT AMSL" and n["schedule"] == "0500-1200" and n["cls"] == "INTERNATIONAL", n
assert n["from"] == "2026-11-11T05:00:00Z" and n["to"] == "2026-11-12T12:00:00Z", n
u = by["A1059/26"]  # UAS: 600 m circle from the text, not the 1 NM Q-line circle
assert u["cat"] == "uas" and u["shapes"] == [{"shape": "circle", "center": [34.86694, 32.80083], "r_nm": 0.32}] and u["schedule"] == "SR-SS", u
g = by["A1194/26"]  # GNSS FIR-wide: Q-line circle, estimated end
assert g["cat"] == "gnss" and g["shapes"][0]["r_nm"] == 171 and g.get("to_est") and g.get("replaces"), g
assert by["A0994/26"]["shapes"][0]["shape"] == "circle", "an area with an arc falls back to the Q-line circle"
assert by["A3812/26"]["shapes"][0]["shape"] == "polygon", "coordinates separated by spaces only still make a polygon"
assert by["A0837/26"]["shapes"][0]["r_nm"] == 0.27, "500M RADIUS OF PSN -> 0.27 NM"
assert "AIXM" in st["note"] and "staging" in st["note"], st
print("nms aixm OK:", st["note"])

os.environ.pop("NMS_CLIENT_ID")
assert nms.fetch_notams({})[1]["note"].startswith("not configured")
