"""GNSS spoofing indicators from free, crowd-sourced ADS-B networks (no paid API).

Wingbits' map flags an aircraft when its own receivers locate it by MLAT 50 km or more from the position it
broadcasts. Its customer API does not offer that layer, so this module builds a comparable one from what the
free aggregators (airplanes.live, adsb.lol, adsb.fi: readsb JSON) already publish. Per airborne aircraft above
2,000 ft it checks four independent indicators:

  alt      GNSS (geometric) altitude and barometric altitude disagree by SPOOF_ALT_FT or more (default 2,500 ft).
           In normal air they differ by up to about 1,300 ft; a spoofed receiver reports the spoofer's altitude.
  xnet     Two independent networks place the same aircraft 50 km or more apart after allowing for the time between
           their fixes (ground speed x age difference). One network has kept a broadcast position the other rejected.
  mlat     An ADS-B-equipped aircraft (it reports a DO-260 version) that the network could only locate by MLAT:
           its broadcast position was unusable (GPS lost or rejected as implausible).
  cluster  Three or more airborne aircraft broadcasting the same position (within about 1 km): a spoofing target point.

Flagged aircraft are counted per H3 hexagon (resolution 4, as the GNSS grid) over a rolling window, and, as on the
Wingbits map, only hexagons with at least two distinct aircraft are shown. Marks show where affected aircraft were,
not where the interference comes from.
"""
from __future__ import annotations

import math
import os
import time
from datetime import datetime
from statistics import median

import requests

H3_RES = 4
MIN_ALT_FT = 2000
XNET_KM = 50.0


def _km(la1, lo1, la2, lo2) -> float:
    p1, p2 = math.radians(la1), math.radians(la2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lo2 - lo1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(min(1.0, a)))


def _airborne(a: dict) -> bool:
    alt = a.get("alt_baro")
    return isinstance(alt, (int, float)) and alt >= MIN_ALT_FT and a.get("lat") is not None and a.get("lon") is not None


def fetch_second_network(primary: str, providers, points, radius_nm, ua: dict, in_box) -> tuple[str | None, list[dict], str]:
    """Same area from the next free aggregator after the one that served the map. Returns (name, records, error)."""
    names = [n for n, _ in providers]
    order = names[names.index(primary) + 1:] + names[:names.index(primary)] if primary in names else names
    err = ""
    for name in order:
        tpl = dict(providers)[name]
        seen: dict[str, dict] = {}
        try:
            for i, (lat, lon) in enumerate(points):
                if i:
                    time.sleep(1.5)
                r = requests.get(tpl.format(lat=lat, lon=lon, r=radius_nm), headers=ua, timeout=25)
                r.raise_for_status()
                for a in (r.json().get("ac") or r.json().get("aircraft") or []):
                    if a.get("hex"):
                        seen[a["hex"]] = a
            return name, [a for a in seen.values() if in_box(a.get("lat"), a.get("lon"))], ""
        except Exception as e:
            err = f"{name}: {e.__class__.__name__}"
    return None, [], err


def analyse(raw: list[dict], raw2: list[dict], alt_ft: float | None = None) -> list[dict]:
    """One record per flagged aircraft: hex, callsign, lat/lon (where it is counted), methods, offset_km, alt_diff."""
    alt_ft = alt_ft or float(os.environ.get("SPOOF_ALT_FT") or 2500)
    other = {a["hex"]: a for a in raw2 if a.get("hex")}
    flagged: dict[str, dict] = {}

    def flag(a: dict, method: str, **kw):
        f = flagged.setdefault(a["hex"], {"hex": a["hex"], "callsign": (a.get("flight") or "").strip() or None,
                                         "lat": a["lat"], "lon": a["lon"], "methods": []})
        if method not in f["methods"]:
            f["methods"].append(method)
        for k, v in kw.items():
            if v is not None:
                f[k] = v

    air = [a for a in raw if _airborne(a)]
    for a in air:
        geo, baro = a.get("alt_geom"), a.get("alt_baro")
        if isinstance(geo, (int, float)) and abs(geo - baro) >= alt_ft:
            flag(a, "alt", alt_diff=int(geo - baro))
        if str(a.get("type", "")).startswith("mlat") and a.get("version") is not None:
            flag(a, "mlat")
        b = other.get(a["hex"])
        if b and b.get("lat") is not None and b.get("lon") is not None:
            gs_kms = float(a.get("gs") or b.get("gs") or 0) * 1.852 / 3600
            dt = abs(float(a.get("seen_pos") or 0) - float(b.get("seen_pos") or 0)) + 2  # + fetch spacing
            off = _km(a["lat"], a["lon"], b["lat"], b["lon"])
            if off - gs_kms * dt >= XNET_KM:
                # count it where a network located it by MLAT if one did (the measured position), else at the map's position
                at = b if str(b.get("type", "")).startswith("mlat") and not str(a.get("type", "")).startswith("mlat") else a
                flag({**a, "lat": at["lat"], "lon": at["lon"]}, "xnet", offset_km=round(off, 1))
    spots: dict[tuple, list[dict]] = {}
    for a in air:
        spots.setdefault((round(a["lat"], 2), round(a["lon"], 2)), []).append(a)
    for group in spots.values():
        if len(group) >= 3:
            for a in group:
                flag(a, "cluster")
    return list(flagged.values())


def update(state: dict, flagged: list[dict], window_h: float, t_now: datetime, net2: str | None) -> tuple[dict, dict]:
    import h3
    t = int(t_now.timestamp())
    runs = [r for r in state.get("spoof_runs", []) if t - r["t"] <= window_h * 3600]
    cells: dict[str, dict] = {}
    for f in flagged:
        c = h3.latlng_to_cell(f["lat"], f["lon"], H3_RES)
        cells.setdefault(c, {})[f["hex"]] = [f["methods"], f.get("offset_km"), f.get("alt_diff")]
    runs.append({"t": t, "cells": cells})
    state["spoof_runs"] = runs
    agg: dict[str, dict] = {}
    for r in runs:
        for c, acs in r["cells"].items():
            agg.setdefault(c, {}).update(acs)  # distinct aircraft per hexagon; the latest run's reading wins
    hexes = []
    for c, acs in agg.items():
        if len(acs) < 2:
            continue
        m: dict[str, int] = {}
        for methods, _, _ in acs.values():
            for k in methods:
                m[k] = m.get(k, 0) + 1
        offs = [o for _, o, _ in acs.values() if o]
        alts = [abs(d) for _, _, d in acs.values() if d]
        hexes.append({"h3": c, "b": [[round(la, 4), round(lo, 4)] for la, lo in h3.cell_to_boundary(c)], "n": len(acs), "m": m,
                      **({"off_km": round(median(offs), 1)} if offs else {}), **({"alt_ft": int(median(alts))} if alts else {})})
    hexes.sort(key=lambda x: -x["n"])
    by = {k: sum(1 for f in flagged if k in f["methods"]) for k in ("alt", "xnet", "mlat", "cluster")}
    note = (f"{len(flagged)} aircraft flagged this run (altitude {by['alt']}, cross-network {by['xnet']}, MLAT-only {by['mlat']}, "
            f"cluster {by['cluster']}); {len(hexes)} hexagons with 2+ aircraft in {window_h:g} h"
            + (f"; cross-checked against {net2}" if net2 else "; no second network this run"))
    return ({"window_h": window_h, "updated": t_now.strftime("%Y-%m-%dT%H:%M:%SZ"), "hexes": hexes, "aircraft": flagged},
            {"name": "GNSS spoofing indicators", "note": note, "ok": True, "live": True})
