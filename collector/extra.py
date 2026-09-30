"""Extra Levantine Watch sources: GDELT, NASA FIRMS, Cloudflare Radar, ACLED,
Wingbits GNSS, and paid-API enrichment (Datalastic, Flightradar24, FlightAware).

Every function is optional (skipped without its key), fails soft, and throttles itself
with timestamps kept in the rolling `state` so paid credits are not burned every run.
"""
from __future__ import annotations

import csv
import hashlib
import io
import os
import re
import time
from datetime import datetime, timedelta, timezone

import requests

UA = {"User-Agent": "levantine-watch/1.0 (+https://github.com/TheMurdoc/levantine-watch)"}
LAT_MIN, LAT_MAX, LON_MIN, LON_MAX = 29.0, 37.3, 32.0, 40.2
REGION_CC = {"CY", "LB", "SY", "IL", "PS", "JO", "EG", "TR", "IQ", "SA"}
ACLED_COUNTRIES = ["Cyprus", "Lebanon", "Syria", "Israel", "Palestine", "Jordan", "Egypt", "Turkey"]


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _due(state: dict, key: str, every_s: int) -> bool:
    return time.time() - state.get("_t", {}).get(key, 0) >= every_s


def _mark(state: dict, key: str):
    state.setdefault("_t", {})[key] = int(time.time())


def _budget_left(state: dict, name: str, per_day) -> float:
    """Calls left today for a metered API (None = unlimited). Resets at 00:00 UTC."""
    if per_day is None:
        return float("inf")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d = state.setdefault("_daily", {}).setdefault(name, {"d": today, "n": 0})
    if d["d"] != today:
        d.update(d=today, n=0)
    return max(0, per_day - d["n"])


def _spend(state: dict, name: str, n: int = 1):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d = state.setdefault("_daily", {}).setdefault(name, {"d": today, "n": 0})
    if d["d"] != today:
        d.update(d=today, n=0)
    d["n"] += n


def _per_day(env_name: str, default):
    v = _env(env_name)
    return int(v) if v else default


def _in_box(lat, lon) -> bool:
    try:
        return LAT_MIN <= float(lat) <= LAT_MAX and LON_MIN <= float(lon) <= LON_MAX
    except (TypeError, ValueError):
        return False


def _short(e) -> str:
    return f"{e.__class__.__name__}: {str(e)[:100]}"


# ----------------------------------------------------------------------------- gazetteer
# Specific places first; a generic country name is only used when nothing more precise matches.
PLACES = [
    ("Nicosia|Lefkosia|Lefkoşa", 35.17, 33.36), ("Limassol|Lemesos", 34.68, 33.04), ("Larnaca", 34.92, 33.63),
    ("Paphos|Pafos", 34.77, 32.42), ("Famagusta|Gazimağusa|Gazimagusa|Varosha", 35.12, 33.94), ("Kyrenia|Girne", 35.34, 33.32),
    ("Ayia Napa", 34.99, 34.0), ("Troodos", 34.93, 32.88), ("Akrotiri", 34.59, 32.99), ("Dhekelia", 34.98, 33.72),
    ("Protaras", 35.01, 34.06), ("Morphou|Güzelyurt", 35.2, 32.99), ("Vasilikos", 34.72, 33.32),
    ("Beirut", 33.89, 35.5), ("Sidon|Saida", 33.56, 35.37), ("Tyre|Sour", 33.27, 35.2), ("Baalbek", 34.0, 36.21),
    ("Nabatieh|Nabatiyeh", 33.38, 35.48), ("Bekaa|Beqaa", 33.85, 35.9), ("Dahiyeh|Dahieh", 33.85, 35.51),
    ("southern Lebanon|south Lebanon", 33.25, 35.4), ("Hermel", 34.39, 36.39),
    ("Damascus", 33.51, 36.29), ("Aleppo", 36.2, 37.16), ("Homs", 34.73, 36.72), ("Hama", 35.13, 36.75),
    ("Latakia|Lattakia", 35.52, 35.78), ("Tartus|Tartous", 34.89, 35.89), ("Idlib", 35.93, 36.63),
    ("Deir ez-Zor|Deir al-Zor|Deir Ezzor", 35.33, 40.14), ("Raqqa", 35.95, 39.01), ("Daraa|Deraa", 32.62, 36.1),
    ("Quneitra", 33.13, 35.82), ("Sweida|Suwayda", 32.71, 36.57), ("Palmyra|Tadmur", 34.56, 38.28), ("Hmeimim|Khmeimim", 35.41, 35.95),
    ("Tel Aviv", 32.08, 34.78), ("Jerusalem", 31.77, 35.21), ("Haifa", 32.79, 34.99), ("Ashdod", 31.8, 34.65),
    ("Ashkelon", 31.67, 34.57), ("Beersheba|Be'er Sheva", 31.25, 34.79), ("Eilat", 29.56, 34.95), ("Dimona", 31.07, 35.03),
    ("Khan Younis|Khan Yunis", 31.35, 34.3), ("Rafah", 31.29, 34.25), ("Gaza City", 31.52, 34.45), ("Gaza", 31.45, 34.4),
    ("Jenin", 32.46, 35.3), ("Nablus", 32.22, 35.26), ("Ramallah", 31.9, 35.2), ("Hebron", 31.53, 35.1),
    ("Tulkarm", 32.31, 35.03), ("West Bank", 31.95, 35.25), ("Golan", 33.0, 35.75), ("Galilee", 32.9, 35.4),
    ("Amman", 31.95, 35.93), ("Aqaba", 29.53, 35.0), ("Zarqa", 32.07, 36.09), ("Irbid", 32.56, 35.85),
    ("Port Said", 31.26, 32.3), ("Suez", 29.97, 32.55), ("Ismailia", 30.6, 32.27), ("El Arish|Al-Arish", 31.13, 33.8),
    ("Sinai", 29.9, 33.8), ("Adana", 37.0, 35.32), ("Incirlik|İncirlik", 37.0, 35.43), ("Mersin", 36.8, 34.63),
    ("Iskenderun|İskenderun", 36.59, 36.17), ("Hatay|Antakya", 36.2, 36.16), ("Gaziantep", 37.06, 37.38),
    ("Tabqa", 35.83, 38.55), ("Kobani|Kobane", 36.89, 38.35), ("Manbij", 36.53, 37.95), ("Afrin", 36.51, 36.87),
    ("Eastern Mediterranean|East Med", 34.0, 33.3), ("Levantine Sea|Levant Basin", 33.6, 34.2),
    ("Cyprus|Cypriot", 35.05, 33.35), ("Lebanon|Lebanese|Hezbollah", 33.9, 35.85), ("Syria|Syrian", 35.0, 38.3),
    ("Israel|Israeli|IDF", 31.6, 34.9), ("Palestinian", 31.9, 35.2), ("Jordan|Jordanian", 31.3, 36.5),
]
_PLACE_RE = [(re.compile(r"\b(?:%s)\b" % pat, re.I), pat.split("|")[0], lat, lon) for pat, lat, lon in PLACES]


def geolocate(text: str):
    for rx, name, lat, lon in _PLACE_RE:
        if rx.search(text or ""):
            return name, lat, lon
    return None


def _jitter(key: str, lat: float, lon: float, r: float = 0.06):
    h = hashlib.md5(key.encode()).digest()
    return round(lat + (h[0] / 255 - 0.5) * r, 4), round(lon + (h[1] / 255 - 0.5) * r, 4)


def events_from_headlines(items: list[dict], limit: int = 120) -> list[dict]:
    out, seen = [], set()
    for it in items:
        g = geolocate(it.get("title", ""))
        if not g or not it.get("url") or it["url"] in seen:
            continue
        seen.add(it["url"])
        name, lat, lon = g
        lat, lon = _jitter(it["url"], lat, lon)
        out.append({"lat": lat, "lon": lon, "place": name, "title": it["title"], "url": it["url"],
                    "source": it.get("source"), "t": it.get("publishedAt"), "via": it.get("via", "rss")})
        if len(out) >= limit:
            break
    return out


# ----------------------------------------------------------------------------- GDELT (no key)
GDELT_QUERY = ('(Cyprus OR Lebanon OR Syria OR Israel OR Gaza OR Jordan OR Beirut OR Nicosia OR Hezbollah '
               'OR "Eastern Mediterranean" OR Latakia OR Tartus OR Limassol OR Larnaca) sourcelang:english')


def fetch_gdelt(timespan: str = "6h", maxrecords: int = 120):
    try:
        r = requests.get("https://api.gdeltproject.org/api/v2/doc/doc", headers=UA, timeout=30, params={
            "query": GDELT_QUERY, "mode": "artlist", "format": "json", "maxrecords": maxrecords,
            "timespan": timespan, "sort": "datedesc"})
        r.raise_for_status()
        try:
            arts = r.json().get("articles", [])
        except ValueError:  # GDELT answers plain text for query errors / throttling
            raise RuntimeError(r.text.strip()[:120])
        items = []
        for a in arts:
            sd = a.get("seendate") or ""
            try:
                pub = datetime.strptime(sd, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                pub = None
            regional = (a.get("sourcecountry") or "") in ("Cyprus", "Lebanon", "Israel", "Syria", "Jordan", "Egypt", "Turkey")
            if a.get("title") and a.get("url") and (regional or geolocate(a["title"])):
                items.append({"title": a["title"].strip(), "source": a.get("domain") or "GDELT", "url": a["url"],
                              "publishedAt": pub, "via": "gdelt", "country": a.get("sourcecountry")})
        return items, {"name": "GDELT", "note": f"{len(items)} articles in the last {timespan} (DOC 2.0 API)", "ok": bool(items), "live": True}
    except Exception as e:
        return [], {"name": "GDELT", "note": f"failed: {_short(e)}", "ok": False, "live": True}


# ----------------------------------------------------------------------------- NASA FIRMS
FIRMS_SOURCES = ["VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT", "MODIS_NRT"]


def fetch_firms(state: dict, days: int = 1):
    key = _env("FIRMS_MAP_KEY")
    if not key:
        return None, {"name": "NASA FIRMS", "note": "not configured (FIRMS_MAP_KEY)", "ok": False, "live": True}
    area = f"{LON_MIN},{LAT_MIN},{LON_MAX},{LAT_MAX}"
    pts: dict[tuple, dict] = {}
    errs = []
    for src in FIRMS_SOURCES:
        try:
            r = requests.get(f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{src}/{area}/{days}", headers=UA, timeout=40)
            r.raise_for_status()
            txt = r.text
            if not txt.lower().startswith("latitude"):
                raise RuntimeError(txt.strip()[:100])
            for row in csv.DictReader(io.StringIO(txt)):
                lat, lon = float(row["latitude"]), float(row["longitude"])
                conf = (row.get("confidence") or "").strip().lower()
                if conf in ("l", "low") or (conf.isdigit() and int(conf) < 40):
                    continue
                frp = float(row.get("frp") or 0)
                t = f"{row.get('acq_date', '')} {str(row.get('acq_time', '')).zfill(4)[:2]}:{str(row.get('acq_time', '')).zfill(4)[2:]}"
                k = (round(lat, 2), round(lon, 2))
                if k not in pts or frp > pts[k]["frp"]:
                    pts[k] = {"lat": round(lat, 4), "lon": round(lon, 4), "frp": round(frp, 1), "conf": conf,
                              "t": t.strip() + " UTC", "sat": src.split("_")[0] + (" " + src.split("_")[1] if src.startswith("VIIRS") else ""),
                              "dn": row.get("daynight")}
        except Exception as e:
            errs.append(f"{src}: {_short(e)}")
    out = sorted(pts.values(), key=lambda p: -p["frp"])[:1500]
    note = f"{len(out)} thermal hotspots, last {24 * days} h (VIIRS + MODIS)" + (f"; failed: {'; '.join(errs)}" if errs else "")
    return out, {"name": "NASA FIRMS", "note": note, "ok": bool(out) or not errs, "live": True}


# ----------------------------------------------------------------------------- Cloudflare Radar
def fetch_outages(state: dict, every_s: int = 3600):
    tok = _env("CLOUDFLARE_API_TOKEN")
    if not tok:
        return None, {"name": "Cloudflare Radar", "note": "not configured (CLOUDFLARE_API_TOKEN)", "ok": False, "live": True}
    cache = state.get("cf_outages")
    if cache is not None and not _due(state, "cf", every_s):
        return cache, {"name": "Cloudflare Radar", "note": f"{len(cache)} outages in the region, last 14 days (cached, hourly refresh)", "ok": True, "live": True}
    try:
        r = requests.get("https://api.cloudflare.com/client/v4/radar/annotations/outages", timeout=30,
                         headers={**UA, "Authorization": f"Bearer {tok}"}, params={"dateRange": "14d", "limit": 200, "format": "json"})
        r.raise_for_status()
        anns = (r.json().get("result") or {}).get("annotations", [])
        out = []
        for a in anns:
            locs = [l.upper() for l in (a.get("locations") or [])]
            if not REGION_CC.intersection(locs):
                continue
            det = a.get("locationsDetails") or []
            o = a.get("outage") or {}
            out.append({"loc": [l for l in locs if l in REGION_CC], "locName": ", ".join(d.get("name", d.get("code", "")) for d in det if (d.get("code") or "").upper() in REGION_CC),
                        "start": a.get("startDate"), "end": a.get("endDate"), "cause": o.get("outageCause"), "type": o.get("outageType"),
                        "scope": a.get("scope"), "desc": (a.get("description") or "")[:300], "url": a.get("linkedUrl"),
                        "asns": [d.get("name") or d.get("asn") for d in (a.get("asnsDetails") or [])][:6], "id": a.get("id")})
        out.sort(key=lambda x: (x["end"] is not None, x["start"] or ""), reverse=False)
        out.sort(key=lambda x: x["start"] or "", reverse=True)
        state["cf_outages"] = out
        _mark(state, "cf")
        return out, {"name": "Cloudflare Radar", "note": f"{len(out)} outages in the region, last 14 days", "ok": True, "live": True}
    except Exception as e:
        return cache, {"name": "Cloudflare Radar", "note": f"failed: {_short(e)}" + (" (showing cached)" if cache else ""), "ok": bool(cache), "live": True}


# ----------------------------------------------------------------------------- ACLED
def fetch_acled(state: dict, every_s: int = 6 * 3600, days: int = 30):
    user, pw = _env("ACLED_EMAIL"), _env("ACLED_PASSWORD")
    if not (user and pw):
        return None, {"name": "ACLED", "note": "not configured (ACLED_EMAIL / ACLED_PASSWORD)", "ok": False, "live": True}
    cache = state.get("acled")
    if cache is not None and not _due(state, "acled", every_s):
        return cache, {"name": "ACLED", "note": f"{len(cache)} conflict events, last {days} days (cached, refreshed every {every_s // 3600} h)", "ok": True, "live": True}
    try:
        t = requests.post("https://acleddata.com/oauth/token", headers=UA, timeout=30, data={
            "username": user, "password": pw, "grant_type": "password", "client_id": "acled", "scope": "authenticated"})
        t.raise_for_status()
        tok = t.json()["access_token"]
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=days)
        q = ":OR:".join(f"country={c}" for c in ACLED_COUNTRIES)
        url = (f"https://acleddata.com/api/acled/read?_format=json&{q}&event_date={start}|{end}&event_date_where=BETWEEN"
               "&fields=event_id_cnty|event_date|event_type|sub_event_type|actor1|actor2|country|location|latitude|longitude|fatalities|notes|source&limit=4000")
        r = requests.get(url, headers={**UA, "Authorization": f"Bearer {tok}"}, timeout=60)
        r.raise_for_status()
        rows = r.json().get("data", [])
        out = []
        for d in rows:
            if not _in_box(d.get("latitude"), d.get("longitude")):
                continue
            out.append({"lat": round(float(d["latitude"]), 4), "lon": round(float(d["longitude"]), 4), "id": d.get("event_id_cnty"),
                        "date": d.get("event_date"), "type": d.get("event_type"), "sub": d.get("sub_event_type"),
                        "actor1": d.get("actor1"), "actor2": d.get("actor2"), "country": d.get("country"), "location": d.get("location"),
                        "fatalities": int(d.get("fatalities") or 0), "notes": (d.get("notes") or "")[:300], "source": (d.get("source") or "")[:120]})
        out.sort(key=lambda e: e["date"] or "", reverse=True)
        state["acled"] = out
        _mark(state, "acled")
        return out, {"name": "ACLED", "note": f"{len(out)} conflict events, last {days} days", "ok": True, "live": True}
    except Exception as e:
        return cache, {"name": "ACLED", "note": f"failed: {_short(e)}" + (" (showing cached)" if cache else ""), "ok": bool(cache), "live": True}


# ----------------------------------------------------------------------------- Wingbits GNSS
def fetch_wingbits_gnss(state: dict, every_s: int = 1800):
    key = _env("WINGBITS_API_KEY")
    if not key:
        return None, None
    cache = state.get("wb_gnss")
    if cache is not None and not _due(state, "wb", every_s):
        return cache, {"name": "Wingbits GNSS", "note": f"{len(cache['hexes'])} H3 hexagons, data to {cache['updated']} (cached)", "ok": True, "live": True}
    try:
        import h3
        r = requests.get("https://customer-api.wingbits.com/v1/gps/jam", timeout=40, headers={**UA, "x-api-key": key},
                         params={"min_lat": LAT_MIN, "max_lat": LAT_MAX, "min_lng": LON_MIN, "max_lng": LON_MAX})
        r.raise_for_status()
        j = r.json()
        hexes = []
        for hx in j.get("hexes", []):
            npm = float(hx.get("npAvg") or 0)
            b = [[round(la, 4), round(lo, 4)] for la, lo in h3.cell_to_boundary(hx["h3Index"])]
            hexes.append({"b": b, "np": round(npm, 2), "samples": int(hx.get("sampleCount") or 0), "aircraft": int(hx.get("aircraftCount") or 0),
                          "sev": round(max(0.0, min(1.0, (9 - npm) / 9)), 3)})
        upd = (j.get("lastUpdated") or "").replace("Z", "")[:19]
        res = {"window_h": 1, "updated": (upd + "Z") if upd else None, "hexes": hexes, "src": "Wingbits"}
        state["wb_gnss"] = res
        _mark(state, "wb")
        return res, {"name": "Wingbits GNSS", "note": f"{len(hexes)} H3 hexagons (NACp), data to {upd or '?'}", "ok": bool(hexes), "live": True}
    except Exception as e:
        return cache, {"name": "Wingbits GNSS", "note": f"failed: {_short(e)}" + (" (showing cached)" if cache else "; using ADS-B NACp fallback"), "ok": bool(cache), "live": True}


# ----------------------------------------------------------------------------- vessel enrichment (Datalastic -> Data Docked)
def _dd_json(r):
    j = r.json()
    if isinstance(j, dict):
        for k in ("detail", "data", "vessel", "result"):
            if isinstance(j.get(k), dict):
                return j[k]
    return j if isinstance(j, dict) else {}


def _lookup_datalastic(key, mmsi):
    r = requests.get("https://api.datalastic.com/api/v0/vessel_info", headers=UA, timeout=20, params={"api-key": key, "mmsi": mmsi})
    if r.status_code == 404:
        return {}
    r.raise_for_status()
    d = r.json().get("data") or {}
    return {k: d.get(k) for k in ("name", "imo", "callsign", "type_specific", "length", "breadth", "year_built", "gross_tonnage",
                                  "deadweight", "country_name", "home_port")}


def _lookup_datadocked(key, mmsi):
    r = requests.get("https://datadocked.com/api/vessels_operations/get-vessel-particulars", headers={**UA, "x-api-key": key},
                     timeout=20, params={"imo_or_mmsi": mmsi})
    if r.status_code == 404:
        return {}
    r.raise_for_status()
    d = _dd_json(r)
    return {"name": d.get("name"), "imo": d.get("imo"), "callsign": d.get("callsign"), "type_specific": d.get("typeSpecific") or d.get("shipType"),
            "length": d.get("length"), "breadth": d.get("beam"), "year_built": d.get("yearOfBuilt") or d.get("yearBuilt"),
            "gross_tonnage": d.get("grossTonnage"), "deadweight": d.get("deadweight"), "country_name": d.get("flag"), "home_port": d.get("homePort")}


def enrich_vessels(vessels: list[dict], state: dict):
    providers = [(n, k, fn, int(min(int(_env(cap) or dflt), _budget_left(state, n + " details", _per_day(pd, pd_dflt)))))
                 for n, k, fn, cap, dflt, pd, pd_dflt in (
        ("Datalastic", _env("DATALASTIC_API_KEY"), _lookup_datalastic, "DATALASTIC_MAX_PER_RUN", 15, "DATALASTIC_MAX_PER_DAY", None),
        ("Data Docked", _env("DATADOCKED_API_KEY"), _lookup_datadocked, "DATADOCKED_MAX_PER_RUN", 1, "DATADOCKED_MAX_PER_DAY", 1)) if k]
    # Data Docked details: at most one lookup per DATADOCKED_DETAILS_EVERY_MIN (default 1 week)
    if not _due(state, "dd_details", int(_env("DATADOCKED_DETAILS_EVERY_MIN") or 10080) * 60):
        providers = [(n, k, fn, 0 if n == "Data Docked" else cap) for n, k, fn, cap in providers]
    if not providers or not vessels:
        return []
    cache = state.setdefault("dl", {})
    now = int(time.time())
    for k in [k for k, v in cache.items() if now - v.get("t", 0) > (30 if v.get("ok") else 7) * 86400]:
        del cache[k]
    need = [v for v in vessels if v.get("mmsi") and (v["mmsi"] not in cache or (not cache[v["mmsi"]].get("ok") and len(cache[v["mmsi"]].get("tried", [])) < len(providers)))
            and (not v.get("type_specific") or not v.get("length") or not v.get("imo") or not v.get("name"))]
    need.sort(key=lambda v: (v.get("type_specific") not in ("Military Ops", "Law Enforcement"), v.get("age_min", 99)))
    stats = {n: [0, 0, 0] for n, *_ in providers}  # calls, hits, errors
    for v in need:
        c = cache.setdefault(v["mmsi"], {"t": now, "ok": False, "tried": []})
        for name, key, fn, cap in providers:
            if name in c.get("tried", []) or stats[name][0] >= cap:
                continue
            try:
                stats[name][0] += 1
                _spend(state, name + " details")
                if name == "Data Docked":
                    _mark(state, "dd_details")
                d = {k: x for k, x in fn(key, v["mmsi"]).items() if x not in (None, "", 0, "0")}
                c.setdefault("tried", []).append(name)
                if d:
                    stats[name][1] += 1
                    cache[v["mmsi"]] = {"t": now, "ok": True, "src": name, "d": d, "tried": c["tried"]}
                    break
            except Exception:
                stats[name][2] += 1
                break  # retry this provider next run
    enriched = 0
    for v in vessels:
        c = cache.get(v.get("mmsi") or "")
        if not c or not c.get("d"):
            continue
        d = c["d"]
        if d.get("type_specific"):
            v["type_specific"] = d["type_specific"]
        for a in ("name", "imo", "callsign", "length"):
            if not v.get(a) and d.get(a):
                v[a] = str(d[a]) if a == "imo" else d[a]
        v["dl"] = {k: d[k] for k in ("year_built", "gross_tonnage", "deadweight", "home_port", "country_name", "breadth") if d.get(k)}
        v["dl"]["src"] = c.get("src", "Datalastic")
        enriched += 1
    return [{"name": n + " details", "note": f"vessel details: {h} found in {c_} lookups this run (cached 30 days; {enriched} ships enriched in total)" + (f"; {e} errors" if e else ""),
             "ok": e == 0 or h > 0, "live": True} for n, (c_, h, e) in stats.items()]


# ----------------------------------------------------------------------------- Data Docked vessels by area (terrestrial AIS)
# Minimal-cost default: ONE 50 km circle (Limassol) ONCE a day. Add circles with DATADOCKED_AREAS="lat,lon;lat,lon".
DD_AREAS = [("Limassol", 34.6, 33.1)]


def fetch_datadocked_area(state: dict):
    key = _env("DATADOCKED_API_KEY")
    if not key:
        return None, None
    every = int(_env("DATADOCKED_EVERY_MIN") or 10080) * 60
    keep = int(float(_env("DATADOCKED_KEEP_HOURS") or 24) * 3600)
    cache = state.setdefault("dd_area", {})
    now = int(time.time())
    for k in [k for k, v in cache.items() if now - v.get("t", 0) > keep]:  # positions go stale; show them for `keep` only
        del cache[k]
    left = max(0, every - (now - state.get('_t', {}).get('dd_area', 0)))
    note = f"cached; next refresh in {left // 86400} d {left % 86400 // 3600} h"
    if _due(state, "dd_area", every) and _budget_left(state, "Data Docked area", _per_day("DATADOCKED_AREA_MAX_PER_DAY", 1)) > 0:
        areas = DD_AREAS
        if _env("DATADOCKED_AREAS"):  # "lat,lon;lat,lon"
            areas = [("custom", float(a.split(",")[0]), float(a.split(",")[1])) for a in _env("DATADOCKED_AREAS").split(";") if "," in a]
        n = errs = 0
        for name, lat, lon in areas:
            try:
                if _budget_left(state, "Data Docked area", _per_day("DATADOCKED_AREA_MAX_PER_DAY", 1)) <= 0:
                    break
                _spend(state, "Data Docked area")
                r = requests.get("https://datadocked.com/api/vessels_operations/get-vessels-by-area", headers={**UA, "x-api-key": key}, timeout=25,
                                 params={"latitude": lat, "longitude": lon, "circle_radius": 50})
                r.raise_for_status()
                j = r.json()
                for x in (j.get("vessels") if isinstance(j, dict) else j) or []:
                    try:
                        la, lo = float(x.get("latitude")), float(x.get("longitude"))
                    except (TypeError, ValueError):
                        continue
                    if not x.get("mmsi") or not _in_box(la, lo):
                        continue
                    sp = x.get("speed")
                    cache[str(x["mmsi"])] = {"t": now, "lat": round(la, 5), "lon": round(lo, 5), "mmsi": str(x["mmsi"]), "name": (x.get("name") or "").strip() or None,
                                             "type_specific": x.get("typeSpecific"), "sog": round(float(sp) / 10, 1) if sp not in (None, "") else None,
                                             "cog": float(x["course"]) if x.get("course") not in (None, "") else None,
                                             "hdg": float(x["heading"]) if x.get("heading") not in (None, "", "511") else None}
                    n += 1
            except Exception:
                errs += 1
        _mark(state, "dd_area")
        note = f"{n} positions from {len(areas) - errs}/{len(areas)} port circle(s), refreshed every {every // 86400} d, shown for {keep // 3600} h"
    out = [dict(v, type=v.get("type_specific"), age_min=round((now - v["t"]) / 60, 1), src="Data Docked (terrestrial AIS)") for v in cache.values()]
    for v in out:
        v.pop("t", None)
    return out, {"name": "Data Docked", "note": f"{len(out)} vessels near ports; {note}", "ok": bool(out), "live": True}


# ----------------------------------------------------------------------------- flight enrichment (FR24 -> FlightAware)
def _priority(f: dict) -> tuple:
    return (not f.get("mil"), f.get("type") is not None, f.get("callsign") or "")


def enrich_flights(flights: list[dict], state: dict):
    fr_tok, fa_key = _env("FR24_API_TOKEN"), _env("FLIGHTAWARE_API_KEY")
    if not (fr_tok or fa_key) or not flights:
        return []
    cache = state.setdefault("routes", {})
    now = int(time.time())
    for k in [k for k, v in cache.items() if now - v.get("t", 0) > (6 if v.get("ok") else 12) * 3600]:
        del cache[k]
    todo = sorted([f for f in flights if f.get("callsign") and f["callsign"] not in cache], key=_priority)
    statuses = []
    if fr_tok and todo:
        batch = todo[: min(15, int(_env("FR24_MAX_PER_RUN") or 15))]
        try:
            r = requests.get("https://fr24api.flightradar24.com/api/live/flight-positions/full", timeout=30,
                             headers={**UA, "Accept": "application/json", "Accept-Version": "v1", "Authorization": f"Bearer {fr_tok}"},
                             params={"callsigns": ",".join(f["callsign"] for f in batch), "limit": 30})
            r.raise_for_status()
            found = {d.get("callsign"): d for d in (r.json().get("data") or []) if d.get("callsign")}
            for f in batch:
                d = found.get(f["callsign"])
                cache[f["callsign"]] = {"t": now, "ok": bool(d), "src": "fr24", "d": {
                    "orig": d.get("orig_icao") or d.get("orig_iata"), "orig_iata": d.get("orig_iata"),
                    "dest": d.get("dest_icao") or d.get("dest_iata"), "dest_iata": d.get("dest_iata"),
                    "op": d.get("operating_as") or d.get("painted_as"), "eta": d.get("eta"), "flight": d.get("flight"),
                    "type": d.get("type"), "reg": d.get("reg")} if d else {}}
            statuses.append({"name": "Flightradar24 API", "note": f"routes for {sum(1 for f in batch if found.get(f['callsign']))}/{len(batch)} callsigns this run (cached 6 h)", "ok": True, "live": True})
        except Exception as e:
            statuses.append({"name": "Flightradar24 API", "note": f"failed: {_short(e)}", "ok": False, "live": True})
    if fa_key:
        fa_todo = [f for f in sorted(flights, key=_priority) if f.get("callsign") and (f["callsign"] not in cache or (not cache[f["callsign"]].get("ok") and cache[f["callsign"]].get("src") == "fr24"))]
        n_ok = n = 0
        for f in fa_todo[: int(_env("FLIGHTAWARE_MAX_PER_RUN") or 5)]:
            try:
                r = requests.get(f"https://aeroapi.flightaware.com/aeroapi/flights/{f['callsign']}", timeout=20,
                                 headers={**UA, "x-apikey": fa_key}, params={"max_pages": 1})
                n += 1
                r.raise_for_status()
                fl = [x for x in (r.json().get("flights") or []) if (x.get("status") or "").lower().find("arrived") < 0] or (r.json().get("flights") or [])
                x = fl[0] if fl else None
                o, d = (x or {}).get("origin") or {}, (x or {}).get("destination") or {}
                cache[f["callsign"]] = {"t": now, "ok": bool(x), "src": "fa", "d": {
                    "orig": o.get("code_icao") or o.get("code"), "orig_iata": o.get("code_iata"), "orig_city": o.get("city"),
                    "dest": d.get("code_icao") or d.get("code"), "dest_iata": d.get("code_iata"), "dest_city": d.get("city"),
                    "op": x.get("operator_icao") or x.get("operator"), "flight": x.get("ident_iata") or x.get("ident"),
                    "type": x.get("aircraft_type"), "reg": x.get("registration")} if x else {}}
                n_ok += bool(x)
            except Exception:
                pass
        statuses.append({"name": "FlightAware AeroAPI", "note": f"routes for {n_ok}/{n} callsigns this run (fallback, cached 6 h)", "ok": True, "live": True})
    for f in flights:
        c = cache.get(f.get("callsign") or "")
        if c and c.get("d"):
            d = c["d"]
            f["route"] = {k: v for k, v in d.items() if v and k not in ("type", "reg")}
            f["route"]["src"] = "Flightradar24" if c["src"] == "fr24" else "FlightAware"
            if not f.get("type") and d.get("type"):
                f["type"] = d["type"]
            if not f.get("reg") and d.get("reg"):
                f["reg"] = d["reg"]
    return statuses
