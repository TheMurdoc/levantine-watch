"""Run: python collector/tests/test_spoof.py   (no pytest, no network)."""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import spoof  # noqa: E402


def ac(hexid, lat, lon, baro=35000, geo=36000, **kw):
    return {"hex": hexid, "flight": hexid.upper() + "  ", "lat": lat, "lon": lon, "alt_baro": baro, "alt_geom": geo,
            "gs": 450, "seen_pos": 0.5, "type": "adsb_icao", "version": 2, **kw}


raw = [
    ac("a1", 34.00, 33.00),                              # normal: 1,000 ft geo/baro difference
    ac("a2", 34.10, 33.10, geo=41000),                   # altitude: GNSS 6,000 ft above baro
    ac("a3", 34.20, 33.20, type="mlat"),                 # ADS-B equipped, only located by MLAT
    ac("a4", 33.80, 35.49), ac("a5", 33.801, 35.491, baro=24000, geo=25100), ac("a6", 33.802, 35.489, baro=12000, geo=13000),  # cluster
    ac("a7", 34.05, 33.05),                              # 2nd network has it 120 km away, by MLAT
    ac("g1", 34.0, 33.0, baro="ground", geo=None),       # on ground: ignored
    ac("lo", 34.0, 33.0, baro=1500, geo=9000),           # below 2,000 ft: ignored
]
raw2 = [ac("a1", 34.01, 33.01), ac("a7", 35.10, 33.30, type="mlat")]
f = {x["hex"]: x for x in spoof.analyse(raw, raw2)}
assert set(f) == {"a2", "a3", "a4", "a5", "a6", "a7"}, f
assert f["a2"]["methods"] == ["alt"] and f["a2"]["alt_diff"] == 6000
assert f["a3"]["methods"] == ["mlat"] and f["a4"]["methods"] == ["cluster"]
assert f["a7"]["methods"] == ["xnet"] and f["a7"]["offset_km"] > 100 and f["a7"]["lat"] == 35.10, f["a7"]  # counted at the MLAT fix

state = {}
t = datetime(2026, 11, 8, 20, 0, tzinfo=timezone.utc)
sp, st = spoof.update(state, list(f.values()), 6, t, "adsb.fi")
ns = sorted(x["n"] for x in sp["hexes"])
assert all(n >= 2 for n in ns) and sum(ns) <= 6, sp["hexes"]
assert "6 aircraft flagged" in st["note"] and "cross-network 1" in st["note"], st
# a later run inside the window keeps distinct aircraft, without double counting
sp2, _ = spoof.update(state, [f["a2"]], 6, t.replace(hour=21), None)
assert sorted(x["n"] for x in sp2["hexes"]) == ns and len(state["spoof_runs"]) == 2
# outside the window the old run drops out
sp3, _ = spoof.update(state, [], 6, t.replace(day=9, hour=4), None)
assert sp3["hexes"] == [] and len(state["spoof_runs"]) == 1
print("spoof OK:", len(f), "aircraft flagged,", len(sp["hexes"]), "hexagons")
