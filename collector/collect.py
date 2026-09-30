#!/usr/bin/env python3
"""Levantine Watch live collector.

Runs on a schedule (GitHub Actions) and writes:
  <out>/live.json   what the dashboard loads (aircraft, vessels, GNSS hexes, headlines, source status)
  <out>/state.json  rolling state carried between runs (GNSS window, AIS static/position cache)

Every source is optional and fails soft: a broken source is reported in `sources`
and the rest of the file is still written.

Environment
  AISSTREAM_API_KEY   aisstream.io key (vessels). Without it the page keeps its snapshot vessels.
  NEWSAPI_KEY         optional NewsAPI.org key (adds to the RSS headlines).
  PAGES_BASE_URL      e.g. https://themurdoc.github.io/levantine-watch/ (to read the previous state.json)
  AIS_LISTEN_SECONDS  how long to listen to the AIS stream per run (default 90)
  GNSS_WINDOW_HOURS   rolling window for GNSS hexes (default 6)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# Map extent of the dashboard (matches the page's linear lat/lon grid).
LAT_MIN, LAT_MAX = 29.0, 37.3
LON_MIN, LON_MAX = 32.0, 40.2
# Four 250 nm circles cover the whole map extent.
AIR_POINTS = [(35.3, 33.8), (35.3, 38.4), (31.2, 33.8), (31.2, 38.4)]
AIR_RADIUS_NM = 250
AIR_PROVIDERS = [
    ("airplanes.live", "https://api.airplanes.live/v2/point/{lat}/{lon}/{r}"),
    ("adsb.lol", "https://api.adsb.lol/v2/point/{lat}/{lon}/{r}"),
    ("adsb.fi", "https://opendata.adsb.fi/api/v2/lat/{lat}/lon/{lon}/dist/{r}"),
]
H3_RES = 4
UA = {"User-Agent": "levantine-watch/1.0 (+https://github.com/TheMurdoc/levantine-watch)"}

NEWS_EXCLUDE = re.compile(r"\b(football|basketball|tennis|horoscope|recipe|fashion|celebrity|lifestyle|travel deals)\b|/sport", re.I)
RSS_FEEDS = [
    ("Cyprus Mail", "https://cyprus-mail.com/feed/"),
    ("in-cyprus", "https://in-cyprus.philenews.com/feed/"),
    ("BBC Middle East", "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml"),
    ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
]
NEWS_KEYWORDS = re.compile(
    r"\b(cyprus|cypriot|nicosia|limassol|larnaca|famagusta|kyrenia|lebanon|lebanese|beirut|hezbollah|israel|israeli|gaza|"
    r"west bank|syria|syrian|damascus|jordan|egypt|sinai|suez|turkey|t[uü]rkiye|turkish|eastern mediterranean|"
    r"east med|levant|red sea|houthi|navy|frigate|warship|gnss|gps jamming|spoofing)\b", re.I)

# AIS ship type code -> text understood by the page's vessel classifier.
def ais_type_text(code) -> str | None:
    try:
        c = int(code)
    except (TypeError, ValueError):
        return None
    named = {30: "Fishing", 31: "Towing", 32: "Towing (large)", 33: "Dredging", 34: "Diving ops", 35: "Military Ops",
             36: "Sailing Vessel", 37: "Pleasure Craft", 50: "Pilot Vessel", 51: "Search and Rescue", 52: "Tug",
             53: "Port Tender", 54: "Anti-pollution", 55: "Law Enforcement", 58: "Medical Transport"}
    if c in named:
        return named[c]
    if 20 <= c <= 29: return "Wing in Ground"
    if 40 <= c <= 49: return "High Speed Craft"
    if 60 <= c <= 69: return "Passenger"
    if 70 <= c <= 79: return "Cargo"
    if 80 <= c <= 89: return "Tanker"
    return "Other"

# Maritime Identification Digits -> flag (ISO 3166 alpha-3), regional + common flags of convenience.
MID = {
    **{m: "CYP" for m in (209, 210, 212)}, **{m: "GRC" for m in (237, 239, 240, 241)}, 271: "TUR", 450: "LBN",
    428: "ISR", 468: "SYR", 438: "JOR", 622: "EGY", **{m: "MLT" for m in (215, 229, 248, 249, 256)},
    636: "LBR", 637: "LBR", 538: "MHL", **{m: "PAN" for m in (351, 352, 353, 354, 355, 356, 357, 370, 371, 372, 373, 374)},
    **{m: "BHS" for m in (308, 309, 311)}, 477: "HKG", **{m: "SGP" for m in (563, 564, 565, 566)},
    **{m: "GBR" for m in (232, 233, 234, 235)}, **{m: "DEU" for m in (211, 218)}, **{m: "FRA" for m in (226, 227, 228)},
    247: "ITA", **{m: "ESP" for m in (224, 225)}, 273: "RUS", **{m: "CHN" for m in (412, 413, 414)},
    **{m: "USA" for m in (338, 366, 367, 368, 369)}, 403: "SAU", 470: "ARE", 466: "QAT", 572: "TUV", 667: "SLE",
    613: "CMR", 341: "KNA", 312: "BLZ", 518: "COK", 620: "COM", 671: "TGO", 244: "NLD", 245: "NLD", 246: "NLD",
    219: "DNK", 220: "DNK", 257: "NOR", 258: "NOR", 259: "NOR", 230: "FIN", 265: "SWE", 266: "SWE", 272: "UKR",
    214: "MDA", 267: "SVK", 273: "RUS", 422: "IRN", 425: "IRQ", 419: "IND", 533: "MYS", 574: "VNM", 440: "KOR", 441: "KOR",
    431: "JPN", 432: "JPN", 725: "CHL", 710: "BRA",
}

def flag_of(mmsi: str) -> str | None:
    return MID.get(int(mmsi[:3])) if mmsi and mmsi[:3].isdigit() and len(mmsi) == 9 else None

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

def in_box(lat, lon) -> bool:
    return lat is not None and lon is not None and LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX

def log(*a):
    print("[collect]", *a, file=sys.stderr, flush=True)


# ------------------------------------------------------------------ previous state
def load_previous_state(out: Path) -> dict:
    local = out / "state.json"
    if local.exists():
        try:
            return json.loads(local.read_text())
        except Exception:
            pass
    base = os.environ.get("PAGES_BASE_URL", "").strip()
    if base:
        url = base.rstrip("/") + "/data/state.json"
        try:
            r = requests.get(url, headers=UA, timeout=15, params={"t": int(time.time())})
            if r.ok:
                log("loaded previous state from", url)
                return r.json()
            log("no previous state at", url, r.status_code)
        except Exception as e:
            log("previous state fetch failed:", e)
    return {}


# ------------------------------------------------------------------ aircraft
def fetch_aircraft() -> tuple[list[dict], dict, list[dict]]:
    """Returns (flights, source_status, raw readsb records for GNSS)."""
    last_err = None
    for name, tpl in AIR_PROVIDERS:
        seen: dict[str, dict] = {}
        try:
            for i, (lat, lon) in enumerate(AIR_POINTS):
                if i:
                    time.sleep(1.5)  # public APIs allow ~1 request/second
                r = requests.get(tpl.format(lat=lat, lon=lon, r=AIR_RADIUS_NM), headers=UA, timeout=25)
                r.raise_for_status()
                for a in (r.json().get("ac") or r.json().get("aircraft") or []):
                    if a.get("hex"):
                        seen[a["hex"]] = a
            raw = [a for a in seen.values() if in_box(a.get("lat"), a.get("lon"))]
            flights = []
            for a in raw:
                alt = a.get("alt_baro")
                on_ground = alt == "ground"
                flights.append({
                    "lat": round(a["lat"], 4), "lon": round(a["lon"], 4), "hex": a.get("hex"),
                    "callsign": (a.get("flight") or "").strip() or None, "reg": a.get("r"), "type": a.get("t"),
                    "alt": 0 if on_ground else (alt if isinstance(alt, (int, float)) else a.get("alt_geom")),
                    "spd": round(a["gs"]) if isinstance(a.get("gs"), (int, float)) else None,
                    "trk": round(a["track"]) if isinstance(a.get("track"), (int, float)) else (round(a["true_heading"]) if isinstance(a.get("true_heading"), (int, float)) else None),
                    "mil": bool((a.get("dbFlags") or 0) & 1), "cat": a.get("category"), "sq": a.get("squawk"),
                    "gnd": on_ground or None, "nacp": a.get("nac_p"), "src": name + " ADS-B",
                })
            flights.sort(key=lambda f: (not f["mil"], f["callsign"] or "zzz"))
            log(f"aircraft: {len(flights)} from {name}")
            return flights, {"name": name, "note": f"live aircraft positions ({len(flights)} in area)", "ok": True, "live": True}, raw
        except Exception as e:
            last_err = f"{name}: {str(e)[:120]}"
            log("aircraft provider failed:", last_err)
    return [], {"name": "ADS-B aggregators", "note": f"no aircraft this run ({last_err})", "ok": False, "live": True}, []


# ------------------------------------------------------------------ GNSS (from ADS-B NACp)
def update_gnss(raw: list[dict], state: dict, window_h: float, t_now: datetime) -> tuple[dict, dict]:
    import h3
    runs = [r for r in state.get("gnss_runs", []) if (t_now.timestamp() - r["t"]) <= window_h * 3600]
    cells: dict[str, list] = {}
    for a in raw:
        np_ = a.get("nac_p")
        if not isinstance(np_, (int, float)) or not str(a.get("type", "adsb")).startswith("adsb"):
            continue
        c = h3.latlng_to_cell(a["lat"], a["lon"], H3_RES)
        e = cells.setdefault(c, [0.0, 0, []])
        e[0] += np_; e[1] += 1; e[2].append(a["hex"])
    if cells:
        runs.append({"t": int(t_now.timestamp()), "cells": cells})
    agg: dict[str, list] = {}
    for r in runs:
        for c, (s, n, ids) in r["cells"].items():
            e = agg.setdefault(c, [0.0, 0, set()])
            e[0] += s; e[1] += n; e[2].update(ids)
    hexes = []
    for c, (s, n, ids) in agg.items():
        npm = s / n
        b = [[round(la, 4), round(lo, 4)] for la, lo in h3.cell_to_boundary(c)]
        hexes.append({"b": b, "np": round(npm, 2), "samples": n, "aircraft": len(ids), "sev": round(max(0.0, min(1.0, (9 - npm) / 9)), 3)})
    state["gnss_runs"] = runs
    status = {"name": "GNSS (ADS-B NACp)", "note": f"accuracy per H3 hexagon, rolling {window_h:g} h window, {len(runs)} runs", "ok": bool(hexes), "live": True}
    return {"window_h": window_h, "updated": iso(t_now), "hexes": hexes}, status


# ------------------------------------------------------------------ vessels (aisstream.io)
async def _ais_listen(key: str, seconds: int, cache: dict) -> int:
    import websockets
    sub = {"APIKey": key, "BoundingBoxes": [[[LAT_MIN, LON_MIN], [LAT_MAX, LON_MAX]]],
           "FilterMessageTypes": ["PositionReport", "StandardClassBPositionReport", "ExtendedClassBPositionReport", "ShipStaticData", "StaticDataReport"]}
    n = 0
    deadline = time.monotonic() + seconds
    async with websockets.connect(os.environ.get("AISSTREAM_URL", "wss://stream.aisstream.io/v0/stream"), open_timeout=20, max_size=2**22) as ws:
        await ws.send(json.dumps(sub))
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                break
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=left)
            except asyncio.TimeoutError:
                break
            m = json.loads(raw)
            if "error" in m:
                raise RuntimeError(m["error"])
            n += 1
            meta = {k.lower(): v for k, v in (m.get("MetaData") or {}).items()}
            mmsi = str(meta.get("mmsi") or "")
            if not mmsi:
                continue
            v = cache.setdefault(mmsi, {"mmsi": mmsi})
            if meta.get("shipname", "").strip():
                v["name"] = meta["shipname"].strip()
            mt = m.get("MessageType")
            body = (m.get("Message") or {}).get(mt) or {}
            if mt in ("PositionReport", "StandardClassBPositionReport", "ExtendedClassBPositionReport"):
                lat, lon = body.get("Latitude", meta.get("latitude")), body.get("Longitude", meta.get("longitude"))
                if in_box(lat, lon):
                    v.update(lat=round(lat, 5), lon=round(lon, 5), t=int(time.time()))
                    for src, dst in (("Sog", "sog"), ("Cog", "cog"), ("TrueHeading", "hdg"), ("NavigationalStatus", "status")):
                        if body.get(src) is not None:
                            v[dst] = body[src]
                    if mt == "ExtendedClassBPositionReport" and body.get("Type"):
                        v["ais_type"] = body["Type"]
            elif mt == "ShipStaticData":
                v["st"] = int(time.time())
                if body.get("Name", "").strip(): v["name"] = body["Name"].strip()
                if body.get("CallSign", "").strip(): v["callsign"] = body["CallSign"].strip()
                if body.get("ImoNumber"): v["imo"] = str(body["ImoNumber"])
                if body.get("Type"): v["ais_type"] = body["Type"]
                d = body.get("Dimension") or {}
                if d.get("A") is not None and d.get("B") is not None and (d["A"] + d["B"]) > 0:
                    v["length"] = d["A"] + d["B"]
                if body.get("Destination", "").strip(): v["dest"] = body["Destination"].strip()
            elif mt == "StaticDataReport":
                v["st"] = int(time.time())
                a, b = body.get("ReportA") or {}, body.get("ReportB") or {}
                if a.get("Name", "").strip(): v["name"] = a["Name"].strip()
                if b.get("CallSign", "").strip(): v["callsign"] = b["CallSign"].strip()
                if b.get("ShipType"): v["ais_type"] = b["ShipType"]
                d = b.get("Dimension") or {}
                if d.get("A") is not None and d.get("B") is not None and (d["A"] + d["B"]) > 0:
                    v["length"] = d["A"] + d["B"]
    return n


def fetch_vessels(state: dict, seconds: int) -> tuple[list[dict] | None, dict]:
    key = os.environ.get("AISSTREAM_API_KEY", "").strip()
    cache: dict = state.get("ais", {})
    now = int(time.time())
    # forget positions older than 60 min and static data older than 7 days
    for k in list(cache):
        v = cache[k]
        if v.get("t") and now - v["t"] > 3600:
            for f in ("lat", "lon", "t", "sog", "cog", "hdg", "status"):
                v.pop(f, None)
        if not v.get("t") and (not v.get("st") or now - v["st"] > 7 * 86400):
            del cache[k]
    if not key:
        return None, {"name": "aisstream.io", "note": "not configured (add AISSTREAM_API_KEY secret); showing snapshot vessels", "ok": False, "live": True}
    note = ""
    try:
        msgs = asyncio.run(_ais_listen(key, seconds, cache))
        note = f"{msgs} AIS messages in {seconds}s"
    except Exception as e:
        note = f"stream error: {e}"
        log("AIS failed:", e)
    state["ais"] = cache
    out = []
    for v in cache.values():
        if "lat" not in v:
            continue
        ts = ais_type_text(v.get("ais_type"))
        out.append({
            "lat": v["lat"], "lon": v["lon"], "mmsi": v["mmsi"], "name": v.get("name") or None, "imo": v.get("imo"),
            "callsign": v.get("callsign"), "type_specific": ts, "type": ts, "length": v.get("length"),
            "sog": v.get("sog"), "cog": v.get("cog"), "hdg": v.get("hdg") if v.get("hdg") not in (511, None) else None,
            "status": v.get("status"), "dest": v.get("dest"), "flag": flag_of(v["mmsi"]),
            "age_min": round((now - v["t"]) / 60, 1), "src": "aisstream.io live AIS",
        })
    out.sort(key=lambda v: (v["age_min"], v["name"] or "~"))
    ok = bool(out)
    return out, {"name": "aisstream.io", "note": f"live AIS, positions from the last 60 min ({len(out)} vessels; {note})", "ok": ok, "live": True}


# ------------------------------------------------------------------ news
def fetch_news(limit: int = 14) -> tuple[list[dict] | None, dict]:
    items = []
    errors = []
    try:
        import feedparser
    except ImportError:
        feedparser = None
    for src, url in RSS_FEEDS if feedparser else []:
        try:
            r = requests.get(url, headers=UA, timeout=20)
            r.raise_for_status()
            feed = feedparser.parse(r.content)
            regional = src in ("Cyprus Mail", "in-cyprus")
            for e in feed.entries[:40]:
                title = (e.get("title") or "").strip()
                if not title or not (regional or NEWS_KEYWORDS.search(title + " " + (e.get("summary") or ""))):
                    continue
                if NEWS_EXCLUDE.search(title + " " + (e.get("link") or "")):
                    continue
                t = e.get("published_parsed") or e.get("updated_parsed")
                pub = datetime(*t[:6], tzinfo=timezone.utc) if t else now_utc()
                items.append({"title": title, "source": src, "url": e.get("link"), "publishedAt": iso(pub)})
        except Exception as ex:
            errors.append(f"{src}: {ex.__class__.__name__}")
    key = os.environ.get("NEWSAPI_KEY", "").strip()
    if key:
        try:
            r = requests.get("https://newsapi.org/v2/everything", headers=UA, timeout=20, params={
                "q": "Cyprus OR Lebanon OR Syria OR Israel OR \"Eastern Mediterranean\"", "language": "en",
                "sortBy": "publishedAt", "pageSize": 20, "apiKey": key})
            r.raise_for_status()
            for a in r.json().get("articles", []):
                items.append({"title": a.get("title"), "source": (a.get("source") or {}).get("name"), "url": a.get("url"), "publishedAt": a.get("publishedAt")})
        except Exception as ex:
            errors.append(f"NewsAPI: {ex.__class__.__name__}")
    seen, out = set(), []
    for it in sorted(items, key=lambda x: x["publishedAt"] or "", reverse=True):
        k = re.sub(r"\W+", "", (it["title"] or "").lower())[:80]
        if k and k not in seen and it.get("url"):
            seen.add(k); out.append(it)
    out = out[:limit]
    note = f"{len(out)} regional headlines (RSS{' + NewsAPI' if key else ''})" + (f"; failed: {', '.join(errors)}" if errors else "")
    return (out or None), {"name": "Headlines", "note": note, "ok": bool(out), "live": True}


# ------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data", help="output directory (live.json, state.json)")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    t_now = now_utc()
    state = load_previous_state(out)
    window_h = float(os.environ.get("GNSS_WINDOW_HOURS", "6"))
    listen = int(os.environ.get("AIS_LISTEN_SECONDS", "90"))

    live: dict = {"generated": iso(t_now), "sources": []}

    flights, st, raw = fetch_aircraft()
    if flights:
        state["last_flights"] = {"t": int(t_now.timestamp()), "flights": flights}
    elif (state.get("last_flights") or {}).get("t", 0) > t_now.timestamp() - 1800:
        flights = state["last_flights"]["flights"]  # keep the previous run's aircraft (< 30 min) rather than an empty sky
        st["note"] += f"; showing previous run's {len(flights)} aircraft"
    live["flights"] = flights
    live["sources"].append(st)
    try:
        gnss, st = update_gnss(raw, state, window_h, t_now)
        live["gnss"] = gnss
    except Exception as e:
        st = {"name": "GNSS (ADS-B NACp)", "note": f"failed: {e}", "ok": False, "live": True}
    live["sources"].append(st)

    vessels, st = fetch_vessels(state, listen)
    if vessels is not None:
        live["vessels"] = vessels
    live["sources"].append(st)

    news, st = fetch_news()
    if news:
        live["news"] = news
    live["sources"].append(st)

    state["updated"] = iso(t_now)
    (out / "live.json").write_text(json.dumps(live, separators=(",", ":"), ensure_ascii=False))
    (out / "state.json").write_text(json.dumps(state, separators=(",", ":"), ensure_ascii=False))
    log("wrote", out / "live.json", f"flights={len(flights)} vessels={len(vessels or [])} hexes={len((live.get('gnss') or {}).get('hexes', []))} news={len(news or [])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
