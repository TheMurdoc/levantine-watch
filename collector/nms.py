"""FAA NMS-API (NOTAM Management Service) for Levantine Watch: airspace NOTAMs around Cyprus and the Levant.

Auth is OAuth 2.0 client credentials: POST <host>/v1/auth/token with the KEY / SECRET from the FAA onboarding
spreadsheet returns a bearer token valid ~30 min. One token is fetched per refresh and never stored (state.json
is published with the site).

Response format (checked against a real staging answer for LCCC, 7 Nov 2026): with `nmsResponseFormat: AIXM`
the body is JSON whose data holds a list of AIXM 5.1 BasicMessage XML strings, one per NOTAM. Each has the
NOTAM fields (series, number, selectionCode, coordinates + radius in NM, effectiveStart/End as YYYYMMDDhhmm,
schedule, text, lower/upperLimit), the ICAO formatted text, and an FNSE extension (classification INTL/MIL, qline).
There is no area geometry: only the Q-line centre and radius, so areas are read from the coordinates in item E)
(polygons and "500M RADIUS OF PSN ..." circles), with the Q-line circle as the fallback.
GEOJSON is still accepted (NMS_FORMAT=GEOJSON) but its layout has not been seen yet, so it is read defensively.

Environment
  NMS_CLIENT_ID, NMS_CLIENT_SECRET   onboarding KEY and SECRET
  NMS_ENV            prod (default) | staging | fit
  NMS_FORMAT         AIXM (default, verified) | GEOJSON
  NMS_LOCATIONS      comma list of ICAO FIRs / aerodromes to query (default: Cyprus + neighbours, see LOCATIONS)
  NMS_GEO            "lat,lon,radius_nm;..." geospatial searches (default: Cyprus, Levant, Crete-Cyprus corridor; "off" disables)
  NMS_SUBJECTS       Q-code subject letters to keep (default "R,W,G,A": restrictions, warnings, GNSS, airspace; "*" = all)
  NMS_EVERY_MIN      minutes between refreshes (default 30)
"""
from __future__ import annotations

import html
import os
import re
import time
from datetime import datetime, timedelta, timezone

import requests

UA = {"User-Agent": "levantine-watch/1.0 (+https://github.com/TheMurdoc/levantine-watch)"}
HOSTS = {"prod": "https://api-nms.aim.faa.gov", "staging": "https://api-staging.cgifederal-aim.com", "fit": "https://api-fit.cgifederal-aim.com"}
REGION = (29.0, 37.3, 23.0, 40.2)  # lat_min, lat_max, lon_min, lon_max (map incl. the Crete-Cyprus corridor)
# Nicosia FIR + Cyprus aerodromes, Tel Aviv, Beirut, Damascus, Amman, Ankara FIRs, Antalya, Cairo, Athens FIR, Heraklion
LOCATIONS = "LCCC,LCLK,LCPH,LCRA,LLLL,OLBB,OSTT,OJAC,LTAA,LTAI,HECC,LGGG,LGIR"
GEO = "34.9,33.3,120;33.2,35.6,120;35.0,27.5,150"  # radius in NM (a 100 NM search off Paphos returned NOTAMs up to 96 NM away)

Q_SUBJECT = {
    "RA": "airspace reservation", "RD": "danger area", "RM": "military operating area", "RO": "overflying prohibited",
    "RP": "prohibited area", "RR": "restricted area", "RT": "temporary restricted / reserved area",
    "WA": "air display", "WB": "aerobatics", "WC": "captive balloon or kite", "WD": "demolition of explosives",
    "WE": "military exercise", "WF": "air refuelling", "WG": "glider flying", "WH": "blasting",
    "WJ": "banner / target towing", "WL": "free balloon ascent", "WM": "missile, gun or rocket firing",
    "WP": "parachute jumping", "WR": "radioactive or toxic materials", "WS": "burning or blowing gas",
    "WT": "mass movement of aircraft", "WU": "unmanned aircraft", "WV": "formation flight",
    "WW": "volcanic activity", "WY": "aerial survey", "WZ": "model flying",
    "GA": "GNSS, aerodrome operations", "GW": "GNSS, area-wide operations",
    "AA": "minimum altitude", "AD": "air defence identification zone", "AE": "control area", "AF": "flight information region",
    "AH": "upper control area", "AL": "minimum usable flight level", "AN": "RNAV route", "AO": "oceanic control area",
    "AP": "reporting point", "AR": "ATS route", "AT": "terminal control area", "AU": "upper flight information region",
    "AV": "upper advisory area", "AX": "significant point", "AZ": "aerodrome traffic zone",
}
Q_CONDITION = {
    "CA": "activated", "CD": "deactivated", "CH": "changed", "CS": "installed", "CE": "established", "CL": "realigned",
    "CR": "temporarily replaced", "CT": "on test", "LC": "closed", "LT": "limited", "LW": "will take place",
    "AU": "not available", "AW": "completely withdrawn", "AO": "operational", "XX": "see text", "TT": "trigger NOTAM",
}
CLS = {"INTL": "INTERNATIONAL", "DOM": "DOMESTIC", "MIL": "MILITARY"}
KEYWORDS = re.compile(r"\b(RESTRICTED|DANGER|PROHIBITED|FIRING|MISSILE|ROCKET|GUNNERY|EXERCISE|GNSS|GPS|JAMMING|UAS|UAV|DRONE|"
                      r"AIRSPACE CLOSED|NO FLY|CONFLICT ZONE)\b", re.I)
QLINE = re.compile(r"(?:Q\)\s*)?([A-Z]{4})\s*/\s*(Q[A-Z]{4})\s*/\s*([IVK]{1,3})?\s*/\s*([A-Z]{0,3})\s*/\s*([A-Z]{0,3})\s*/\s*(\d{3})\s*/\s*(\d{3})\s*/\s*"
                   r"(\d{2})(\d{2})([NS])(\d{3})(\d{2})([EW])(\d{3})")
ITEM_BC = re.compile(r"\b([BC])\)\s*(\d{10}|PERM)(\s*EST)?")
ITEM_D = re.compile(r"\bD\)\s*(.*?)(?=\s+E\)\s)", re.S)
ITEM_E = re.compile(r"\bE\)\s*(.*?)(?=\s+[FG]\)\s|\Z)", re.S)
ITEM_FG = re.compile(r"\b([FG])\)\s*([A-Z0-9 ]{2,20}?)(?=\s+[FG]\)|\s*$|\n)")
NOTAM_REF = re.compile(r"\b([A-Z]\d{4}/\d{2})\s+NOTAM([NRC])(?:\s+([A-Z]\d{4}/\d{2}))?")
# coordinates in item E): 343954N 0330800E, 343413N0331126E, 3425N 03326E
COORD = re.compile(r"(?<!\d)(\d{2})(\d{2})(\d{2}(?:\.\d+)?)?([NS])\s*/?\s*(\d{3})(\d{2})(\d{2}(?:\.\d+)?)?([EW])(?![A-Z0-9])")
RADIUS_OF = re.compile(r"(\d+(?:\.\d+)?)\s*(NM|KM|M)\s+RADI?O?US\s+(?:OF|CENTRED\s+ON|CENTERED\s+ON|AROUND)\s+(?:PSN|POSITION|POINT)?\s*$")
UNIT_NM = {"NM": 1.0, "KM": 1 / 1.852, "M": 1 / 1852}


def _env(n, d=""):
    return (os.environ.get(n) or d).strip()


def _now():
    return datetime.now(timezone.utc)


def _short(e):
    return f"{e.__class__.__name__}: {str(e)[:100]}"


def _iso(v):
    """Accept ISO strings, 'PERM', ICAO YYMMDDhhmm or NMS YYYYMMDDhhmm (optionally ending in EST); return ISO Z or None."""
    if not v:
        return None
    v = re.sub(r"\s*EST$", "", str(v).strip(), flags=re.I)
    if v.upper().startswith("PERM"):
        return "PERM"
    for pat, fmt in ((r"\d{12}", "%Y%m%d%H%M"), (r"\d{10}", "%y%m%d%H%M")):
        if re.fullmatch(pat, v):
            return datetime.strptime(v, fmt).replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None


def _when(v):
    return None if v in (None, "PERM") else datetime.strptime(v, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _features(j) -> list:
    """Find the NOTAMs in an NMS response, whatever the wrapper: GeoJSON features, or AIXM XML strings."""
    if isinstance(j, str):
        return [j] if "NOTAM" in j and "<" in j else []
    if isinstance(j, list):
        out = []
        for x in j:
            out += _features(x) if isinstance(x, (str, list)) or (isinstance(x, dict) and x.get("type") == "FeatureCollection") else [x]
        return out
    if not isinstance(j, dict):
        return []
    if j.get("type") == "FeatureCollection":
        return _features(j.get("features") or [])
    for k in ("data", "aixm", "geojson", "features", "items", "notams", "notamList", "results"):
        if k in j and j[k] is not None and j[k] is not j:
            got = _features(j[k])
            if got:
                return got
    return [j] if ("properties" in j or "coreNOTAMData" in j or "notam" in j) else []


def _geom_shapes(g) -> list:
    """GeoJSON geometry -> list of shapes in [lat, lon]."""
    if not isinstance(g, dict):
        return []
    t, c = g.get("type"), g.get("coordinates")
    if t == "GeometryCollection":
        return [s for gg in g.get("geometries") or [] for s in _geom_shapes(gg)]
    try:
        if t == "Point":
            return [{"shape": "point", "center": [round(c[1], 5), round(c[0], 5)]}]
        if t == "Polygon":
            return [{"shape": "polygon", "ring": [[round(p[1], 5), round(p[0], 5)] for p in c[0]]}]
        if t == "MultiPolygon":
            return [{"shape": "polygon", "ring": [[round(p[1], 5), round(p[0], 5)] for p in poly[0]]} for poly in c]
        if t == "LineString":
            return [{"shape": "line", "ring": [[round(p[1], 5), round(p[0], 5)] for p in c]}]
    except (TypeError, IndexError):
        return []
    return []


def _ll(m) -> list:
    la = int(m[0]) + int(m[1]) / 60 + float(m[2] or 0) / 3600
    lo = int(m[4]) + int(m[5]) / 60 + float(m[6] or 0) / 3600
    return [round(la if m[3] == "N" else -la, 5), round(lo if m[7] == "E" else -lo, 5)]


def text_shapes(text: str) -> list:
    """Areas written out in item E): coordinate chains -> polygons, '600M RADIUS OF PSN ...' -> circles.
    Areas that include an arc are left to the Q-line circle."""
    if not text:
        return []
    t = re.sub(r"\s+", " ", text.upper())
    shapes, chain, last_end = [], [], None

    def flush():
        if len(chain) >= 3 and not re.search(r"\bARC\b|CLOCKWISE", t):
            ring = chain + ([chain[0]] if chain[0] != chain[-1] else [])
            shapes.append({"shape": "polygon", "ring": ring})
        chain.clear()

    for m in COORD.finditer(t):
        r = RADIUS_OF.search(t[max(0, m.start() - 40):m.start()])
        if r:
            flush()
            shapes.append({"shape": "circle", "center": _ll(m.groups()), "r_nm": round(float(r.group(1)) * UNIT_NM[r.group(2)], 2)})
            last_end = None
            continue
        if last_end is not None and not re.fullmatch(r"\s*[-–,]?\s*", t[last_end:m.start()]):
            flush()
        chain.append(_ll(m.groups()))
        last_end = m.end()
    flush()
    return shapes


def _tag(xml: str, name: str):
    m = re.search(r"<(?:\w+:)?%s\b[^>]*>(.*?)</(?:\w+:)?%s>" % (name, name), xml, re.S)
    return html.unescape(m.group(1)).strip() if m else None


def aixm_to_feature(xml: str) -> dict | None:
    """One AIXM BasicMessage (NMS) -> the flat NOTAM dict parse_feature() reads."""
    xml = xml.replace('\\"', '"')
    nm = re.search(r"<(?:\w+:)?NOTAM\b[^>]*>(.*?)</(?:\w+:)?NOTAM>", xml, re.S)
    if not nm:
        return None
    body = nm.group(1)
    head = re.split(r"<(?:\w+:)?translation\b", body)[0]
    g = {k: _tag(head, k) for k in ("series", "number", "year", "type", "issued", "affectedFIR", "selectionCode", "minimumFL", "maximumFL",
                                    "coordinates", "radius", "location", "effectiveStart", "effectiveEnd", "schedule", "text", "lowerLimit", "upperLimit")}
    ft = _tag(body, "formattedText") or ""
    ft = re.sub(r"<[^>]+>", "", ft).replace("\r", "\n")
    qline = _tag(xml, "qline")
    num = f"{g['number']}/{(g['year'] or '')[-2:]}" if g["number"] and g["year"] else g["number"]
    if num and re.fullmatch(r"\d+/\d{2}", num):
        num = num.zfill(7)
    ident = _tag(xml, "identifier")
    return {"properties": {
        "id": ident or (f"{g['series']}{num} {g['location']}" if num else None), "series": g["series"], "number": num, "type": g["type"],
        "issued": g["issued"], "affectedFIR": g["affectedFIR"], "selectionCode": g["selectionCode"],
        "minimumFL": g["minimumFL"], "maximumFL": g["maximumFL"], "location": g["location"] or _tag(xml, "icaoLocation"),
        "effectiveStart": g["effectiveStart"], "effectiveEnd": g["effectiveEnd"], "schedule": g["schedule"],
        "lowerLimit": g["lowerLimit"], "upperLimit": g["upperLimit"], "classification": CLS.get(_tag(xml, "classification") or "", _tag(xml, "classification")),
        "etext": g["text"], "text": (ft or "") + (f"\nQ) {qline}" if qline and "Q)" not in ft else ""),
        "lastUpdated": _tag(xml, "lastUpdated"), "aixm": True}, "geometry": None}


def parse_feature(f) -> dict | None:
    if isinstance(f, str):
        f = aixm_to_feature(f)
        if not f:
            return None
    props = f.get("properties") if isinstance(f.get("properties"), dict) else f
    core = props.get("coreNOTAMData") or {}
    n = core.get("notam") or props.get("notam") or props
    trans = core.get("notamTranslation") or props.get("notamTranslation") or []
    icao = next((t.get("formattedText") or t.get("simpleText") for t in trans if isinstance(t, dict) and (t.get("type") or "").upper() == "ICAO"), None)
    text = icao or n.get("text") or n.get("icaoText") or props.get("text") or ""
    out = {"src": "FAA NMS"}
    out["id"] = str(n.get("id") or n.get("nmsId") or props.get("id") or f.get("id") or "") or None
    num = n.get("number") or n.get("notamNumber")
    series = n.get("series") or ""
    out["number"] = (f"{series}{num}" if series and num and not str(num).startswith(series) else num) or None
    out["loc"] = n.get("icaoLocation") or n.get("location") or props.get("location")
    out["fir"] = n.get("affectedFIR") or n.get("fir")
    out["cls"] = n.get("classification") or props.get("classification")
    out["ntype"] = (n.get("type") or "").upper()[:1] or None
    out["issued"] = _iso(n.get("issued") or n.get("issueDate"))
    out["from"] = _iso(n.get("effectiveStart") or n.get("startDate") or n.get("effectiveStartDate"))
    end = n.get("effectiveEnd") or n.get("endDate") or n.get("effectiveEndDate")
    out["to"] = _iso(end)
    out["to_est"] = bool(end and re.search(r"EST\s*$", str(end), re.I)) or None
    q = n.get("selectionCode") or n.get("qcode") or ""
    lower, upper = n.get("minimumFL"), n.get("maximumFL")
    qm = QLINE.search(text)
    if qm:
        fir, qcode, _traffic, _purpose, _scope, lo, up, la_d, la_m, ns, lo_d, lo_m, ew, rad = qm.groups()
        out["fir"] = out["fir"] or fir
        q = q or qcode
        lower, upper = lo or lower, up or upper  # the Q-line is authoritative (the AIXM maximumFL field can say 999 when the Q-line says 080)
        lat = (int(la_d) + int(la_m) / 60) * (1 if ns == "N" else -1)
        lon = (int(lo_d) + int(lo_m) / 60) * (1 if ew == "E" else -1)
        out["q_center"], out["q_radius_nm"] = [round(lat, 4), round(lon, 4)], int(rad)
    elif n.get("coordinates") and n.get("radius"):
        cm = re.fullmatch(r"(\d{2})(\d{2})([NS])(\d{3})(\d{2})([EW])", n["coordinates"].strip())
        if cm:
            lat = (int(cm[1]) + int(cm[2]) / 60) * (1 if cm[3] == "N" else -1)
            lon = (int(cm[4]) + int(cm[5]) / 60) * (1 if cm[6] == "E" else -1)
            out["q_center"], out["q_radius_nm"] = [round(lat, 4), round(lon, 4)], int(n["radius"])
    for k, v, _est in ITEM_BC.findall(text):
        if k == "B" and not out["from"]:
            out["from"] = _iso(v)
        if k == "C" and not out["to"]:
            out["to"], out["to_est"] = _iso(v), bool(_est) or None
    ref = NOTAM_REF.search(text)
    if ref:
        out["number"] = out["number"] or ref.group(1)
        out["ntype"] = out["ntype"] or ref.group(2)
        out["replaces"] = ref.group(3) if ref.group(2) == "R" else None
        out["cancels"] = ref.group(3) if ref.group(2) == "C" else None
    q = (q or "").upper().lstrip("Q")
    out["q"] = ("Q" + q) if q else None
    subj, cond = q[:2], q[2:4]
    out["subject"] = subj or None
    out["qtext"] = " · ".join(x for x in (Q_SUBJECT.get(subj), Q_CONDITION.get(cond)) if x) or None
    out["lower"] = str(lower).zfill(3) if lower not in (None, "") else None
    out["upper"] = str(upper).zfill(3) if upper not in (None, "") else None
    if n.get("lowerLimit") or n.get("upperLimit"):
        lim = [re.sub(r"\)+$", "", v) if v and "(" not in v else v for v in (n.get("lowerLimit"), n.get("upperLimit"))]  # NMS sometimes leaves a stray ")"
        out["limits_text"] = f"{lim[0] or '?'} – {lim[1] or '?'}"
    else:
        fg = dict(ITEM_FG.findall(text))
        if fg:
            out["limits_text"] = " – ".join(v.strip() for k, v in sorted(fg.items()))
    d = ITEM_D.search(text)
    out["schedule"] = n.get("schedule") or (re.sub(r"\s+", " ", d.group(1)).strip() if d else None)
    e = ITEM_E.search(text)
    etext = n.get("etext") or (e.group(1) if e else text)
    out["text"] = re.sub(r"\s+", " ", html.unescape(etext).replace("\u200b", "")).strip()[:1500]
    shapes = _geom_shapes(f.get("geometry"))
    if not [s for s in shapes if s["shape"] in ("polygon", "line", "circle")]:
        shapes = text_shapes(etext) or shapes
    if not shapes and out.get("q_center"):
        shapes = [{"shape": "circle", "center": out["q_center"], "r_nm": out["q_radius_nm"]}]
    out["shapes"] = shapes
    if subj.startswith("R"):
        out["cat"] = "restriction"
    elif subj in ("WM", "WD", "WH"):
        out["cat"] = "firing"
    elif subj == "WE":
        out["cat"] = "exercise"
    elif subj == "WU":
        out["cat"] = "uas"
    elif subj.startswith("W"):
        out["cat"] = "warning"
    elif subj.startswith("G") or re.search(r"\b(GNSS|GPS)\b", text, re.I):
        out["cat"] = "gnss"
    elif subj.startswith("A"):
        out["cat"] = "airspace"
    else:
        out["cat"] = "other"
    if not (out["id"] or out["number"]) and not text:
        return None
    return {k: v for k, v in out.items() if v is not None or k in ("from", "to", "shapes")}


def _points(m: dict) -> list:
    pts = []
    for s in m.get("shapes") or []:
        pts += s.get("ring") or ([s["center"]] if s.get("center") else [])
    return pts or ([m["q_center"]] if m.get("q_center") else [])


def _in_region(m: dict) -> bool:
    return any(REGION[0] <= la <= REGION[1] and REGION[2] <= lo <= REGION[3] for la, lo in _points(m))


def _keep(m: dict, now: datetime, subjects: set) -> bool:
    if m.get("ntype") == "C" or not _in_region(m):  # NOTAMC only announces a cancellation
        return False
    to = _when(m.get("to"))
    if to and to < now:
        return False
    fr = _when(m.get("from"))
    if fr and fr > now + timedelta(days=7):
        return False
    if subjects == {"*"}:
        return True
    if m.get("subject"):
        return m["subject"][0] in subjects
    return bool(KEYWORDS.search(m.get("text") or ""))


def _richness(m: dict) -> tuple:
    return (bool(m.get("q_center")), len(m.get("shapes") or []), len(m.get("text") or ""))


def _token(host: str, cid: str, secret: str) -> str:
    r = requests.post(f"{host}/v1/auth/token", data={"grant_type": "client_credentials"}, auth=(cid, secret), headers=UA, timeout=30)
    r.raise_for_status()
    tok = (r.json() or {}).get("access_token")
    if not tok:
        raise RuntimeError("no access_token in the token response")
    return tok


def _body(r):
    try:
        return r.json()
    except ValueError:
        return r.text


def fetch_notams(state: dict):
    cid, secret = _env("NMS_CLIENT_ID"), _env("NMS_CLIENT_SECRET")
    if not (cid and secret):
        return None, {"name": "FAA NMS NOTAMs", "note": "not configured (NMS_CLIENT_ID / NMS_CLIENT_SECRET)", "ok": False, "live": True}
    envname = _env("NMS_ENV", "prod").lower()
    host = HOSTS.get(envname, HOSTS["prod"])
    fmt = _env("NMS_FORMAT", "AIXM").upper()
    every = int(float(_env("NMS_EVERY_MIN", "30")) * 60)
    cache = state.get("nms")
    if cache and time.time() - cache.get("t", 0) < every:
        now = _now()
        live = [m for m in cache["items"] if not (_when(m.get("to")) and _when(m.get("to")) < now)]  # drop what expired since the last fetch
        return live, {"name": "FAA NMS NOTAMs", "note": f"{len(live)} airspace NOTAMs ({envname}; cached, refreshed every {every // 60} min)", "ok": True, "live": True}
    subjects = {s.strip().upper() for s in _env("NMS_SUBJECTS", "R,W,G,A").split(",") if s.strip()}
    now = _now()
    per_loc, errs, found = {}, [], {}
    try:
        tok = _token(host, cid, secret)
    except Exception as e:
        note = f"token request failed ({envname}): {_short(e)}"
        if cache:
            return cache["items"], {"name": "FAA NMS NOTAMs", "note": note + " (showing cached)", "ok": True, "live": True}
        return None, {"name": "FAA NMS NOTAMs", "note": note, "ok": False, "live": True}
    hdr = {**UA, "Authorization": f"Bearer {tok}", "nmsResponseFormat": fmt, "Accept": "application/json"}
    queries = [("loc", {"location": loc.strip()}) for loc in _env("NMS_LOCATIONS", LOCATIONS).split(",") if loc.strip()]
    geo = _env("NMS_GEO", GEO)
    for g in ([] if geo.lower() in ("0", "off", "none") else geo.split(";")):
        try:
            la, lo, rad = (float(x) for x in g.split(","))
            queries.append(("geo", {"latitude": la, "longitude": lo, "radius": rad}))
        except ValueError:
            continue
    for kind, params in queries:
        label = params.get("location") or f"{params['latitude']},{params['longitude']}"
        try:
            r = requests.get(f"{host}/nmsapi/v1/notams", headers=hdr, params=params, timeout=60)
            if r.status_code == 404:
                per_loc[label] = 0
                continue
            r.raise_for_status()
            feats = _features(_body(r))
            per_loc[label] = len(feats)
            for f in feats:
                m = parse_feature(f)
                if m and _keep(m, now, subjects):
                    key = f"{m.get('number') or m['id']} {m.get('loc') or ''}"
                    if key not in found or _richness(m) > _richness(found[key]):  # the same NOTAM comes back from several queries
                        found[key] = m
        except Exception as e:
            errs.append(f"{label}: {_short(e)}")
    order = {"restriction": 0, "firing": 1, "exercise": 2, "gnss": 3, "uas": 4, "warning": 5, "airspace": 6}
    items = sorted(found.values(), key=lambda m: (order.get(m["cat"], 9), m.get("from") or ""))[:400]
    for m in items:
        m["env"] = envname
    if errs and not found and cache:
        return cache["items"], {"name": "FAA NMS NOTAMs", "note": f"failed ({envname}): {'; '.join(errs[:3])} (showing cached)", "ok": True, "live": True}
    state["nms"] = {"t": int(time.time()), "items": items}
    empty = [k for k, v in per_loc.items() if not v]
    cats = {}
    for m in items:
        cats[m["cat"]] = cats.get(m["cat"], 0) + 1
    note = (f"{len(items)} airspace NOTAMs in the region ({', '.join(f'{v} {k}' for k, v in cats.items()) or 'none'}) from "
            f"{sum(per_loc.values())} returned, {envname} environment, {fmt}"
            + (f"; nothing returned for {', '.join(empty)}" if empty else "")
            + ("; staging is the FAA test system, its contents can differ from production" if envname != "prod" else "")
            + (f"; failed: {'; '.join(errs[:3])}" if errs else ""))
    return items, {"name": "FAA NMS NOTAMs", "note": note, "ok": not errs or bool(items), "live": True}
