"""Run: python collector/tests/test_navtex.py   (no pytest needed)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import navtex  # noqa: E402

here = Path(__file__).parent
m = navtex.parse_navtex((here / "gsi_navwarn_1411_26.txt").read_text())
assert m["header"] == "HA15" and m["b1"] == "H" and m["subject"] == "navigational warning", m
assert m["station"] == "Irakleio Radio", m.get("station")
assert m["number"] == "NAVWARN 1411/26", m.get("number")
assert m["issued"] == "2026-11-06T14:13:00Z", m["issued"]
assert m["valid_from"] == "2026-11-06T00:00:00Z" and m["valid_to"] == "2027-03-06T22:00:00Z", (m["valid_from"], m["valid_to"])
assert m["geom"] == "line" and len(m["points"]) == 21, (m["geom"], len(m["points"]))
assert m["points"][0] == [35.41633, 24.93550] and m["points"][-1] == [34.16133, 30.07183], (m["points"][0], m["points"][-1])
assert m["clearance_nm"] == 2.0
assert {"cable", "survey"} <= set(m["tags"]), m["tags"]
assert m["vessels"][0]["name"] == "ABEILLE MARENGO" and m["vessels"][0]["mmsi"] == "228505700"

# coordinate formats seen in NAVTEX / NAVAREA text
for txt, want in [("34-12.5N 033-45.2E", [34.20833, 33.75333]), ("3412.5N 03345.2E", [34.20833, 33.75333]),
                  ("34°12.5'N 033°45.2'E", [34.20833, 33.75333]), ("34 12.5 N 033 45.2 E", [34.20833, 33.75333]),
                  ("12 30.0S 045 15.0W", [-12.5, -45.25])]:
    got = navtex.parse_coords(txt)
    assert got == [want], (txt, got)
# a time stamp must not be read as a coordinate
assert navtex.parse_coords("061413 UTC NOV 26 CANCEL 062200 UTC MAR 27") == []

# an area (no cable) closes into a polygon; a firing exercise is tagged
a = navtex.parse_navtex("ZCZC MA01\nANTALYA RADIO\nTURNHOS N/W 1032/26\nLIVE FIRING EXERCISE WITHIN AREA:\n35 00.0N 029 00.0E\n35 00.0N 030 00.0E\n34 30.0N 030 00.0E\nNNNN")
assert a["geom"] == "polygon" and a["points"][0] == a["points"][-1] and "firing" in a["tags"], a
assert a["number"] == "TURNHOS N/W 1032/26" and a["station"] == "Antalya Radio"

# expiry: the GSI warning is active on 7 Nov 2026 and expired after cancel date
from datetime import datetime, timezone
assert navtex._active(m, datetime(2026, 11, 7, tzinfo=timezone.utc))
assert not navtex._active(m, datetime(2027, 3, 7, tzinfo=timezone.utc))
assert navtex._in_region(m)
print("navtex parser OK:", m["number"], "-", len(m["points"]), "waypoints,", m["valid_from"][:10], "->", m["valid_to"][:10])

# ---- formats seen in Turkish, Greek and Cyprus warnings (added with the parser fixes) ----
t = navtex.parse_navtex("ZCZC MA42\nANTALYA RADIO\nTURNHOS N/W : 1042/26\nEASTERN MEDITERRANEAN\nSURVEY OPERATION BY R/V ORUC REIS WILL BE CONDUCTED IN AREA\n36 10.00 N - 029 30.00 E\n36 10.00 N - 030 30.00 E\n35 40.00 N - 030 30.00 E\n35 40.00 N - 029 30.00 E\nFROM 05 NOV 26 TO 20 NOV 26\nNNNN")
assert t["number"] == "TURNHOS N/W 1042/26" and t["geom"] == "polygon" and t["vessels"][0]["name"] == "ORUC REIS", t
d = navtex.parse_navtex("ZCZC HA20\nIRAKLEIO RADIO\nNAVWARN 1500/26\nFIRING EXERCISE AREA BOUNDED BY\n35-12-30N 025-45-10E\n35-20-00N 025-55-00E\n35-05-00N 026-00-00E\nNNNN")
assert d["geom"] == "polygon" and d["points"][0] == [35.20833, 25.75278], d.get("points")
assert navtex.parse_coords("351230N 0254510E") == [[35.20833, 25.75278]]
b = navtex.parse_navtex("ZCZC HA21\nIRAKLEIO RADIO\nNAVWARN 1501/26\nUNLIT BUOYS ESTABLISHED IN POSITIONS:\n1. 35 20.0N 024 10.0E\n2. 35 25.0N 024 40.0E\n3. 35 30.0N 025 10.0E\nNNNN")
assert b["geom"] == "points" and len(b["points"]) == 3, b
c = navtex.parse_navtex("ZCZC HA23\nIRAKLEIO RADIO\n071000 UTC NOV 26\nNAVWARN 1503/26\nCANCEL NAVWARN 1411/26\nNNNN")
assert c["number"] == "NAVWARN 1503/26" and c["cancels"] == ["NAVWARN 1411/26"], c
cy = navtex.parse_navtex("CYPRUS RADIO\nCYPRUS NAVTEX 1234/26\nLIVE FIRING EXERCISES WILL BE CONDUCTED WITHIN AREA BOUNDED BY:\n34-40N 032-20E\n34-40N 032-40E\n34-30N 032-40E\n34-30N 032-20E\nON 10 NOV 26 FROM 0600 UTC TO 1200 UTC\nNNNN")
assert cy["number"] == "CYPRUS NAVTEX 1234/26" and cy["geom"] == "polygon", cy
assert cy["valid_from"] == "2026-11-10T06:00:00Z" and cy["valid_to"] == "2026-11-10T12:00:00Z", (cy["valid_from"], cy["valid_to"])
n = navtex.parse_navtex("ZCZC HA22\nIRAKLEIO RADIO\n061200 UTC NOV 26\nNAVWARN 1502/26\nDRIFTING OBJECT REPORTED IN 35 10.0N 026 20.0E\nNNNN")
assert navtex._active(n, datetime(2026, 11, 20, tzinfo=timezone.utc)) and not navtex._active(n, datetime(2026, 12, 10, tzinfo=timezone.utc))
print("navtex format variants OK")
