"""Extra Levantine Watch sources: GDELT, NASA FIRMS, Cloudflare Radar, GDACS, HDX HAPI,
Wingbits GNSS, and paid-API enrichment (Datalastic, Data Docked, Flightradar24, AirNav Radar, FlightAware).

ACLED is deliberately NOT here: its licence does not allow ACLED data on a public site, so it is
fetched only by the private, local build (private/acled_private.py, outside this repository).

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
AIR_BOX = (29.0, 37.3, 23.0, 40.2)  # aircraft / GNSS extent incl. Crete, Rhodes and the Turkish south-west coast
REGION_CC = {"CY", "LB", "SY", "IL", "PS", "JO", "EG", "TR", "IQ", "SA"}


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


# ----------------------------------------------------------------------------- GDACS natural hazards (no key)
# GDACS answers at most 100 records per page, newest first, for the whole world, so the region would be
# drowned out by global green earthquakes. Querying one country at a time keeps it small. Country names must
# match GDACS's own spelling ("Türkiye"); a name with no events answers HTTP 204.
GDACS_COUNTRIES = ["Cyprus", "Türkiye", "Syria", "Lebanon", "Israel", "Palestine", "Jordan", "Egypt"]
GDACS_TYPES = {"EQ": "Earthquake", "FL": "Flood", "TC": "Tropical cyclone", "VO": "Volcano", "DR": "Drought", "WF": "Wildfire"}
# keep events near the map; large countries (Türkiye, Egypt) reach far outside it
HZ_LAT_MIN, HZ_LAT_MAX, HZ_LON_MIN, HZ_LON_MAX = 27.5, 39.0, 29.5, 42.5


def fetch_gdacs(state: dict, every_s: int = 3600, days: int = 30):
    cache = state.get("gdacs")
    if cache is not None and not _due(state, "gdacs", every_s):
        return cache, {"name": "GDACS", "note": f"{len(cache)} hazard events near the map, last {days} days (cached, hourly refresh)", "ok": True, "live": True}
    countries = [c.strip() for c in (_env("GDACS_COUNTRIES") or ";".join(GDACS_COUNTRIES)).split(";") if c.strip()]
    today = datetime.now(timezone.utc).date()
    base = {"eventlist": ";".join(GDACS_TYPES), "alertlevel": "green;orange;red",
            "fromdate": str(today - timedelta(days=days)), "todate": str(today + timedelta(days=1))}
    found: dict[tuple, dict] = {}
    errs, calls = [], 0
    for c in countries:
        for page in (1, 2, 3):
            try:
                calls += 1
                r = requests.get("https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH", headers=UA, timeout=30,
                                 params={**base, "country": c, "pagenumber": page})
                if r.status_code == 204:
                    break
                r.raise_for_status()
                feats = (r.json() or {}).get("features") or []
            except Exception as e:
                errs.append(f"{c}: {_short(e)}")
                break
            for f in feats:
                p, g = f.get("properties") or {}, f.get("geometry") or {}
                try:
                    lon, lat = float(g["coordinates"][0]), float(g["coordinates"][1])
                except (KeyError, IndexError, TypeError, ValueError):
                    continue
                if not (HZ_LAT_MIN <= lat <= HZ_LAT_MAX and HZ_LON_MIN <= lon <= HZ_LON_MAX):
                    continue
                key = (p.get("eventtype"), p.get("eventid"))
                if key in found and (found[key]["episode"] or 0) >= (p.get("episodeid") or 0):
                    continue
                sev = p.get("severitydata") or {}
                urls = p.get("url") or {}
                found[key] = {
                    "lat": round(lat, 4), "lon": round(lon, 4), "type": p.get("eventtype"), "typeName": GDACS_TYPES.get(p.get("eventtype"), p.get("eventtype")),
                    "id": p.get("eventid"), "episode": p.get("episodeid"), "name": (p.get("name") or "").strip(),
                    "alert": (p.get("alertlevel") or "Green").capitalize(), "score": p.get("alertscore"),
                    "sev": sev.get("severity"), "sevText": (sev.get("severitytext") or "").strip(), "sevUnit": sev.get("severityunit"),
                    "from": p.get("fromdate"), "to": p.get("todate"), "current": str(p.get("iscurrent")).lower() == "true",
                    "country": p.get("country"), "glide": p.get("glide") or None,
                    "report": urls.get("report"), "details": urls.get("details"), "inMap": _in_box(lat, lon)}
            if len(feats) < 100:
                break
    out = sorted(found.values(), key=lambda e: e.get("from") or "", reverse=True)
    if errs and not out and cache is not None:
        return cache, {"name": "GDACS", "note": f"failed: {'; '.join(errs[:3])} (showing cached)", "ok": True, "live": True}
    state["gdacs"] = out
    _mark(state, "gdacs")
    n_map = sum(1 for e in out if e["inMap"])
    note = f"{len(out)} hazard events near the map ({n_map} inside it), last {days} days, {len(countries)} countries" + (f"; failed: {'; '.join(errs[:3])}" if errs else "")
    return out, {"name": "GDACS", "note": note, "ok": not errs or bool(out), "live": True}


# ----------------------------------------------------------------------------- HDX HAPI humanitarian context (free app identifier)
# Public-safe themes only. HAPI's conflict-events endpoint is ACLED data (HDX licence: "By using ACLED data you
# agree to abide by the Terms of Use and Attribution Policy"), so it is NOT fetched here; it lives in the
# private, local-only build (see private/README-PRIVATE.md).
HAPI_BASE = "https://hapi.humdata.org/api/v2/"
HAPI_COUNTRIES = {"CYP": "Cyprus", "LBN": "Lebanon", "SYR": "Syria", "PSE": "Palestine", "ISR": "Israel", "JOR": "Jordan", "TUR": "Türkiye", "EGY": "Egypt"}
HAPI_DETAIL = ["LBN", "SYR", "PSE"]  # countries with IDP / IPC / appeal data in HAPI


def _hapi(path: str, app_id: str, **params) -> list[dict]:
    r = requests.get(HAPI_BASE + path, headers=UA, timeout=45,
                     params={"app_identifier": app_id, "output_format": "json", "limit": 10000, **params})
    if r.status_code >= 400:  # HTTPError text carries the URL, and the identifier is base64 of name:email; errors end up in public live.json
        raise RuntimeError(f"HTTP {r.status_code} for {path}")
    return (r.json() or {}).get("data") or []


def _latest_idps(rows: list[dict]):
    """Latest IOM DTM figure per displacement operation, at the lowest admin level that has it."""
    by_op: dict[str, list[dict]] = {}
    for x in rows:
        if x.get("population") is not None:
            by_op.setdefault(x.get("operation") or "IDPs", []).append(x)
    out = []
    for op, xs in by_op.items():
        d = max(x["reference_period_start"] for x in xs)
        xs = [x for x in xs if x["reference_period_start"] == d]
        lvl = min(x.get("admin_level", 0) for x in xs)
        xs = [x for x in xs if x.get("admin_level", 0) == lvl]
        rnd = max((x.get("reporting_round") or 0) for x in xs)
        xs = [x for x in xs if (x.get("reporting_round") or 0) == rnd]
        out.append({"op": op, "pop": int(sum(x["population"] for x in xs)), "date": d[:10], "round": rnd or None,
                    "level": lvl, "type": xs[0].get("assessment_type")})
    out.sort(key=lambda o: (o["date"], o["pop"]), reverse=True)
    return out[:2]


def _latest_ipc(rows: list[dict]):
    a0 = [x for x in rows if x.get("admin_level") == 0 and x.get("ipc_phase") in ("3+", "all")]
    if not a0:
        return None
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # prefer the period covering today (current or projection), else the most recent one
    periods = sorted({(x["reference_period_start"], x["reference_period_end"], x["ipc_type"]) for x in a0})
    covering = [p for p in periods if p[0][:10] <= today <= p[1][:10]]
    s, e, t = (covering or periods)[-1]
    sel = {x["ipc_phase"]: x for x in a0 if (x["reference_period_start"], x["reference_period_end"], x["ipc_type"]) == (s, e, t)}
    p3 = sel.get("3+")
    if not p3:
        return None
    return {"pop": p3.get("population_in_phase"), "pct": round(100 * (p3.get("population_fraction_in_phase") or 0)),
            "analysed": (sel.get("all") or {}).get("population_in_phase"), "from": s[:10], "to": e[:10], "kind": t}


def _latest_appeal(rows: list[dict]):
    rows = [x for x in rows if x.get("requirements_usd") and x.get("appeal_code") not in (None, "Not specified")]
    if not rows:
        return None
    yr = max(x["reference_period_start"][:4] for x in rows)
    x = max((x for x in rows if x["reference_period_start"][:4] == yr), key=lambda x: x["requirements_usd"])
    return {"name": x.get("appeal_name"), "code": x.get("appeal_code"), "type": x.get("appeal_type"), "year": yr,
            "req": x.get("requirements_usd"), "funded": x.get("funding_usd"), "pct": x.get("funding_pct")}


def fetch_hapi_context(state: dict, every_s: int = 12 * 3600):
    app_id = _env("HAPI_APP_IDENTIFIER")
    if not app_id:
        return None, {"name": "HDX HAPI", "note": "not configured (HAPI_APP_IDENTIFIER)", "ok": False, "live": True}
    cache = state.get("hapi_ctx")
    if cache is not None and not _due(state, "hapi_ctx", every_s):
        return cache, {"name": "HDX HAPI", "note": f"humanitarian context for {len(cache['countries'])} countries (cached, refreshed every {every_s // 3600} h)", "ok": True, "live": True}
    errs = []
    rows: dict[str, dict] = {cc: {"iso3": cc, "name": nm} for cc, nm in HAPI_COUNTRIES.items()}
    try:
        for x in _hapi("coordination-context/national-risk", app_id):
            if x.get("location_code") in rows:
                rows[x["location_code"]]["risk"] = {"overall": x.get("overall_risk"), "class": x.get("risk_class"), "rank": x.get("global_rank"),
                                                     "hazard": x.get("hazard_exposure_risk"), "vuln": x.get("vulnerability_risk"),
                                                     "coping": x.get("coping_capacity_risk"), "year": (x.get("reference_period_start") or "")[:4]}
    except Exception as e:
        errs.append(f"national-risk: {_short(e)}")
    for cc in HAPI_DETAIL:
        for path, key, fn in (("affected-people/idps", "idps", _latest_idps),
                              ("food-security-nutrition-poverty/food-security", "ipc", _latest_ipc),
                              ("coordination-context/funding", "appeal", _latest_appeal)):
            try:
                v = fn(_hapi(path, app_id, location_code=cc))
                if v:
                    rows[cc][key] = v
            except Exception as e:
                errs.append(f"{cc} {key}: {_short(e)}")
    got = [r for r in rows.values() if len(r) > 2]
    if not got and cache is not None:
        return cache, {"name": "HDX HAPI", "note": f"failed: {'; '.join(errs[:3])} (showing cached)", "ok": True, "live": True}
    res = {"updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "countries": got,
           "credits": "INFORM Risk (national risk), IOM DTM (IDPs), IPC (food insecurity), OCHA FTS (appeal funding), via HDX HAPI"}
    state["hapi_ctx"] = res
    _mark(state, "hapi_ctx")
    note = f"humanitarian context for {len(got)} countries (INFORM risk, IOM DTM IDPs, IPC, OCHA FTS)" + (f"; failed: {'; '.join(errs[:3])}" if errs else "")
    return res, {"name": "HDX HAPI", "note": note, "ok": bool(got), "live": True}


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
                         params={"min_lat": AIR_BOX[0], "max_lat": AIR_BOX[1], "min_lng": AIR_BOX[2], "max_lng": AIR_BOX[3]})
        r.raise_for_status()
        j = r.json()
        hexes = []
        for hx in j.get("hexes", []):
            npm = float(hx.get("npAvg") or 0)
            b = [[round(la, 4), round(lo, 4)] for la, lo in h3.cell_to_boundary(hx["h3Index"])]
            # mlatAircraftHours: aircraft that lost GPS entirely and were located by MLAT (Wingbits counts them as NACp 0)
            mlat_h, ah, anp = hx.get("mlatAircraftHours"), hx.get("aircraftHours"), hx.get("adsbNpAvg")
            hexes.append({"h3": h3.int_to_str(h3.str_to_int(hx["h3Index"])), "b": b,  # Wingbits zero-pads to 16 chars; h3 keys are 15 "np": round(npm, 2), "samples": int(hx.get("sampleCount") or 0), "aircraft": int(hx.get("aircraftCount") or 0),
                          "sev": round(max(0.0, min(1.0, (9 - npm) / 9)), 3),
                          **({"mlat_h": round(float(mlat_h), 1)} if mlat_h else {}), **({"ah": round(float(ah), 1)} if ah else {}),
                          **({"adsb_np": round(float(anp), 2)} if anp is not None else {})})
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


# ----------------------------------------------------------------------------- AirNav Radar (On Demand API v2)
# OpenAPI: https://www.airnavradar.com/api/openapi (v2.4.22, Nov 2026). Bearer token from the AirNav API dashboard.
# POST /flights/live takes a bounding box and/or lists (flightIds = callsigns, modeSHexCodes, registrations) and
# returns positions plus departure / arrival airports. Every answer carries its credit "cost".
AIRNAV = "https://api.airnavradar.com/v2"


def _airnav_modes() -> set[str]:
    return {m.strip().lower() for m in (_env("AIRNAV_MODE") or "routes").split(",") if m.strip()}


def _airnav_post(tok: str, body: dict, state: dict) -> dict:
    _spend(state, "AirNav")
    r = requests.post(f"{AIRNAV}/flights/live", json=body, timeout=40,
                      headers={**UA, "Accept": "application/json", "Authorization": f"Bearer {tok}"})
    r.raise_for_status()
    j = r.json() or {}
    if j.get("success") is False:  # the comment can echo the token ("Token <tok> is inactive/expired"); it ends up in public live.json
        raise RuntimeError(str(j.get("comment") or "success=false").replace(tok, "<token>")[:100])
    state.setdefault("_airnav", {})["cost"] = state.get("_airnav", {}).get("cost", 0) + int(j.get("cost") or 0)
    return j


def _airnav_route(x: dict) -> dict:
    return {"orig": x.get("depAirportIcao"), "orig_iata": x.get("depAirportIata"), "orig_city": x.get("depAirportCity"),
            "dest": x.get("arrAirportIcao"), "dest_iata": x.get("arrAirportIata"), "dest_city": x.get("arrAirportCity"),
            "op": x.get("airlineIcao") or x.get("airlineName"), "flight": x.get("flightNumberIata") or x.get("flightNumberIcao"),
            "type": x.get("aircraftType"), "reg": x.get("aircraftRegistration"), "url": x.get("flightUrl")}


def _airnav_ok_to_call(state: dict, key: str) -> str | None:
    """None when a call is allowed now, else the reason it is not."""
    if _budget_left(state, "AirNav", _per_day("AIRNAV_MAX_PER_DAY", 48)) <= 0:
        return "daily request cap reached (AIRNAV_MAX_PER_DAY)"
    if not _due(state, key, int(float(_env("AIRNAV_EVERY_MIN") or 30) * 60)):
        return "cached"
    return None


def fetch_airnav_area(state: dict, have_adsb: bool):
    """AIRNAV_MODE=area, or ADS-B aggregators all down: every live flight in the aircraft box.
    Returns (flights in the collector's format, status) or (None, None) when not in use this run."""
    tok = _env("AIRNAV_API_TOKEN") or _env("AIRNAV_API_KEY")
    if not tok or ("area" not in _airnav_modes() and have_adsb):
        return None, None
    cache = state.get("airnav_area")
    why = _airnav_ok_to_call(state, "airnav_area")
    if why:  # cached positions are only reused when ADS-B is down and they are under 30 min old
        stale = not cache or time.time() - cache.get("t", 0) > 1800
        return (None if have_adsb or stale else cache["flights"]), {"name": "AirNav Radar (area)", "note": f"{len((cache or {}).get('flights') or [])} aircraft at the last call, {why}", "ok": bool(cache), "live": True}
    try:
        j = _airnav_post(tok, {"minLatitude": AIR_BOX[0], "maxLatitude": AIR_BOX[1], "minLongitude": AIR_BOX[2], "maxLongitude": AIR_BOX[3]}, state)
        out, routes = [], state.setdefault("routes", {})
        now = int(time.time())
        for x in j.get("flights") or []:
            if x.get("latitude") is None or x.get("longitude") is None:
                continue
            cs = (x.get("callsign") or "").strip() or None
            alt = x.get("altitude")
            out.append({"lat": round(x["latitude"], 4), "lon": round(x["longitude"], 4), "hex": (x.get("aircraftModeS") or "").lower() or None,
                        "callsign": cs, "reg": x.get("aircraftRegistration"), "type": x.get("aircraftType"),
                        "alt": alt, "spd": x.get("groundSpeed"), "trk": x.get("heading"), "sq": str(x["squawkCode"]) if x.get("squawkCode") else None,
                        "mil": "MILITARY" in [c.upper() for c in (x.get("aircraftClasses") or [])], "gnd": (alt == 0) or None,
                        "src": "AirNav Radar"})
            if cs and (x.get("depAirportIcao") or x.get("arrAirportIcao")):
                routes[cs] = {"t": now, "ok": True, "src": "airnav", "d": _airnav_route(x)}
        state["airnav_area"] = {"t": now, "flights": out}
        _mark(state, "airnav_area")
        return out, {"name": "AirNav Radar (area)", "note": f"{len(out)} aircraft in the box, {j.get('cost', '?')} credits this call" + ("" if have_adsb else " (ADS-B aggregators down)"), "ok": True, "live": True}
    except Exception as e:
        return (cache or {}).get("flights"), {"name": "AirNav Radar (area)", "note": f"failed: {_short(e)}" + (" (showing cached)" if cache else ""), "ok": bool(cache), "live": True}


def merge_airnav(flights: list[dict], extra_fl: list[dict] | None) -> int:
    """Adds AirNav aircraft that ADS-B did not report (by ICAO hex, else callsign). Returns how many were added."""
    if not extra_fl:
        return 0
    hexes = {f.get("hex") for f in flights if f.get("hex")}
    calls = {f.get("callsign") for f in flights if f.get("callsign")}
    add = [f for f in extra_fl if not (f.get("hex") and f["hex"] in hexes) and not (f.get("callsign") and f["callsign"] in calls)]
    flights.extend(add)
    return len(add)


# ----------------------------------------------------------------------------- flight enrichment (FR24 -> AirNav -> FlightAware)
def _priority(f: dict) -> tuple:
    return (not f.get("mil"), f.get("type") is not None, f.get("callsign") or "")


def enrich_flights(flights: list[dict], state: dict):
    fr_tok, fa_key = _env("FR24_API_TOKEN"), _env("FLIGHTAWARE_API_KEY")
    an_tok = (_env("AIRNAV_API_TOKEN") or _env("AIRNAV_API_KEY")) if "routes" in _airnav_modes() else ""
    if not (fr_tok or fa_key or an_tok) or not flights:
        return []
    cache = state.setdefault("routes", {})
    now = int(time.time())
    for k in [k for k, v in cache.items() if now - v.get("t", 0) > (6 if v.get("ok") else 12) * 3600]:
        del cache[k]
    todo = sorted([f for f in flights if f.get("callsign") and f["callsign"] not in cache], key=_priority)
    statuses = []
    # FR24 rejects the whole request (400 "not a valid ICAO callsign") for one callsign with a space or under 3 chars
    fr_todo = [f for f in todo if re.fullmatch(r"[A-Z0-9-]{3,8}", f["callsign"])]
    if fr_tok and fr_todo:
        batch = fr_todo[: min(15, int(_env("FR24_MAX_PER_RUN") or 15))]
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
    if an_tok:  # callsigns still without a route after FR24 (or every callsign when FR24 is not set up)
        an_todo = [f for f in sorted(flights, key=_priority) if f.get("callsign") and (f["callsign"] not in cache or (not cache[f["callsign"]].get("ok") and cache[f["callsign"]].get("src") == "fr24"))]
        an_todo = an_todo[: int(_env("AIRNAV_MAX_PER_RUN") or 20)]
        why = _airnav_ok_to_call(state, "airnav_routes") if an_todo else "nothing to look up"
        if why:
            statuses.append({"name": "AirNav Radar", "note": f"routes: {why}; {_budget_left(state, 'AirNav', _per_day('AIRNAV_MAX_PER_DAY', 48)):g} requests left today", "ok": True, "live": True})
        else:
            try:
                j = _airnav_post(an_tok, {"flightIds": [f["callsign"] for f in an_todo]}, state)
                found = {(x.get("callsign") or "").strip(): x for x in (j.get("flights") or []) if x.get("callsign")}
                for f in an_todo:
                    x = found.get(f["callsign"])
                    cache[f["callsign"]] = {"t": now, "ok": bool(x), "src": "airnav", "d": _airnav_route(x) if x else {}}
                _mark(state, "airnav_routes")
                statuses.append({"name": "AirNav Radar", "note": f"routes for {sum(1 for f in an_todo if f['callsign'] in found)}/{len(an_todo)} callsigns, {j.get('cost', '?')} credits this call (cached 6 h)", "ok": True, "live": True})
            except Exception as e:
                statuses.append({"name": "AirNav Radar", "note": f"failed: {_short(e)}", "ok": False, "live": True})
    if fa_key:
        fa_todo = [f for f in sorted(flights, key=_priority) if f.get("callsign") and (f["callsign"] not in cache or (not cache[f["callsign"]].get("ok") and cache[f["callsign"]].get("src") in ("fr24", "airnav")))]
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
            f["route"]["src"] = {"fr24": "Flightradar24", "airnav": "AirNav Radar"}.get(c["src"], "FlightAware")
            if not f.get("type") and d.get("type"):
                f["type"] = d["type"]
            if not f.get("reg") and d.get("reg"):
                f["reg"] = d["reg"]
    return statuses
