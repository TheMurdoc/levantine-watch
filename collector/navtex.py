"""NAVTEX / navigational-warning ingestion for Levantine Watch.

There is no open, official API for the national NAVTEX stations that matter in the
Eastern Mediterranean (Irakleio, Antalya, Cyprus/JRCC Larnaca). The warning TEXT is
public and is reproduced in full by the press and by the issuing authorities, so the
lowest-friction route is an *inbox*:

  1. Paste the raw message into a GitHub issue labelled `navtex` (phone is fine), or
     drop a .txt file into `navtex/` in the repo.
  2. This module parses it (header, times, waypoints, tags) and the collector publishes it
     in live.json under "navtex". Closing the issue marks the warning cancelled.

Only issues opened by the repository owner (or NAVTEX_ALLOWED_AUTHORS) are read, because
issues on a public repo are open to anyone.

Environment (all optional; the workflow provides the first two automatically)
  GITHUB_TOKEN, GITHUB_REPOSITORY   read issues via the GitHub API
  NAVTEX_ALLOWED_AUTHORS            comma list of GitHub logins allowed to post (default: repo owner)
  NAVTEX_LABEL                      issue label to read (default "navtex")
  NAVTEX_INBOX_FILE                 issues already fetched by the workflow (JSON list); used instead of the API,
                                    so the collector step never holds a GitHub token
  NAVTEX_MAX_DAYS                   drop a warning with no validity or cancel time this many days after it was
                                    issued / posted (default 30)
  NAVTEX_UPCOMING_DAYS              keep a warning whose validity starts within this many days (default 14)

SeaLagom (https://www.sealagom.com, optional): the same warnings pulled from an aggregator of NAVAREA and
coastal / NAVTEX broadcasts, so the layer fills without anyone pasting text. Only the warning TEXT is read
(free developer allowance); positions are parsed here, as for the inbox.
  SEALAGOM_API_TOKEN (or SEALAGOM_API_KEY)   X-API-Token for https://www.sealagom.com/api/v2/
  SEALAGOM_EVERY_MIN                minutes between pulls (default 120; the free allowance is ~100 calls a day)
  SEALAGOM_MAX_PAGES                pages per pull (default 4; 50 records a page on the free tier, 200 paid)
  SEALAGOM_BBOX                     west,south,east,north (default: the dashboard region incl. the GSI corridor)
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import requests

UA = {"User-Agent": "levantine-watch/1.0 (+https://github.com/TheMurdoc/levantine-watch)"}
MONTHS = {m: i for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split(), 1)}

# Region the dashboard may be extended to (west edge covers Crete and the whole GSI corridor).
REGION = (29.0, 37.3, 23.0, 40.2)  # lat_min, lat_max, lon_min, lon_max

# NAVTEX B2 subject indicator (ITU-R M.540 / IMO NAVTEX Manual).
SUBJECTS = {"A": "navigational warning", "B": "meteorological warning", "C": "ice report",
            "D": "SAR / piracy", "E": "weather forecast", "F": "pilot service", "G": "AIS",
            "H": "LORAN", "J": "SATNAV", "K": "other electronic navaids", "L": "navigational warning (additional)"}

# Survey / cable vessels worth recognising by name in warning text. The page matches AIS by MMSI, IMO or name.
# ABEILLE MARENGO (AIS name "VB ABEILLE MARENGO") checked on VesselFinder / vesseltracker, Nov 2026; IMO is the
# stable key (one site lists a second MMSI, which suggests a reflag). The other two entries are unverified.
WATCH_VESSELS = {
    "ABEILLE MARENGO": {"mmsi": "228505700", "imo": "9388613", "note": "GSI Crete-Cyprus survey; AIS name VB ABEILLE MARENGO"},
    "KOBI RUEGG": {"imo": "9713753", "note": "EMC cable survey, Turkish NAVTEX 1032/26"},
    "IEVOLI RELUME": {"note": "GSI survey ship interrupted off Kasos, July 2024"},
}

# Inside one coordinate only spaces / tabs may separate the parts (never a line break), so that a stray digit on
# the line above ("SAHA-1" followed by "36 50.43 N") is not read as degrees of a DMS position.
COORD_DMS = re.compile(  # 35-12-30N 025-45-10E, 351230N 0254510E, 35 12 30.5N 025 45 10E
    r"(?<![\d.])(\d{1,2})[ \t]*[°\- ]?[ \t]*(\d{2})[ \t]*['′\- ]?[ \t]*(\d{2}(?:\.\d+)?)[ \t]*[\"″]?[ \t]*([NS])"
    r"\s*[-,/ ]*\s*"
    r"(\d{1,3})[ \t]*[°\- ]?[ \t]*(\d{2})[ \t]*['′\- ]?[ \t]*(\d{2}(?:\.\d+)?)[ \t]*[\"″]?[ \t]*([EW])")
COORD = re.compile(  # "A.34°20.15N": a list letter and dot may precede the degrees, a digit may not
    r"(?<!\d)(\d{1,2})[ \t]*[°\- ]?[ \t]*(\d{1,2}(?:\.\d+)?)[ \t]*['′]?[ \t]*([NS])"
    r"\s*[-,/ ]*\s*"
    r"(\d{1,3})[ \t]*[°\- ]?[ \t]*(\d{1,2}(?:\.\d+)?)[ \t]*['′]?[ \t]*([EW])")
# 061800 UTC NOV 26 | 06 1800 UTC NOV 2026 | 27 0001UTC DEC 2026 | 20 0001 UTC MARCH 2027
DTG = r"(\d{2})\s?(\d{2})(\d{2})\s*(?:UTC|Z)\s+([A-Z]{3})[A-Z]*\.?\s+(?:20)?(\d{2})\b"
# FROM 080600Z TO 081500Z NOV 26 (one month for both times)
DTG_PAIR = re.compile(r"FROM\s+(\d{2})(\d{2})(\d{2})\s*(?:UTC|Z)\s+(?:TO|UNTIL)\s+(\d{2})(\d{2})(\d{2})\s*(?:UTC|Z)\s+([A-Z]{3})[A-Z]*\s+(?:20)?(\d{2})\b", re.I)
CANCEL = re.compile(r"CANCEL\s+(?:THIS\s+)?(?:MSG|MESSAGE)\s+(?:ON\s+)?" + DTG, re.I)
ISSUED = re.compile(r"\b" + DTG, re.I)
NUMBER = r"(NAVWARN|NAV\s+WRNG|NAVIGATIONAL\s+WARNING|NAVAREA\s+[IVX]+|HYDRO[A-Z]+|TURNHOS\s+N/W|(?:CYPRUS\s+)?NAVTEX)\s*(?:NR\.?|NO\.?)?\s*:?\s*(\d{1,4}/\d{2})\b"
NUMBER_KIND = {"NAV WRNG": "NAVWARN", "NAVIGATIONAL WARNING": "NAVWARN"}
CANCEL_OTHER = re.compile(r"CANCEL(?:S|LED)?\s+" + NUMBER, re.I)
VALID_DAY = re.compile(r"\bON\s+(\d{1,2})\s+([A-Z]{3})\s+(\d{2})\s+(?:FROM|BETWEEN)\s+(\d{2})(\d{2})\s*(?:UTC|Z)?\s+(?:TO|AND|UNTIL)\s+(\d{2})(\d{2})", re.I)
VALID_DTG = re.compile(r"FROM\s+" + DTG + r"\s+(?:TO|UNTIL)\s+" + DTG, re.I)
# FROM 03 NOV 2026 UNTIL 27 DEC 2026 | DAYS 05 NOV 26 TO 15 FEB 27
VALID = re.compile(r"(?:FROM|DAYS)\s+(\d{1,2})\s+([A-Z]{3})[A-Z]*\s+(?:20)?(\d{2})\s+(?:UNTIL|TO)\s+(\d{1,2})\s+([A-Z]{3})[A-Z]*\s+(?:20)?(\d{2})\b", re.I)
# Text clean-up before parsing: typographic dashes and quotes, Greek capitals typed for Latin ones (ZCZC, M/V),
# decimal commas inside coordinates (42 11,718N) and, for Turkish broadcasts, K (kuzey) / D (dogu) after a coordinate.
_DASHES = str.maketrans({"\u2013": "-", "\u2014": "-", "\u2010": "-", "\u2011": "-", "\u2212": "-", "\u2019": "'", "\u2018": "'",
                         "\u2032": "'", "\u201c": '"', "\u201d": '"', "\u2033": '"', "\u00a0": " ",
                         "\u0391": "A", "\u0392": "B", "\u0395": "E", "\u0396": "Z", "\u0397": "H", "\u0399": "I", "\u039a": "K",
                         "\u039c": "M", "\u039d": "N", "\u039f": "O", "\u03a1": "P", "\u03a4": "T", "\u03a5": "Y", "\u03a7": "X"})
_DEC_COMMA = re.compile(r"(\d{1,2}),(\d{1,4})(?=\s*'?\s*[NSEW]\b)")
_TR_NS = re.compile(r"(\d)\s*K\b")
_TR_EW = re.compile(r"(\d)\s*D\b")


def normalize(text: str, lang: str | None = None) -> str:
    t = text.translate(_DASHES)
    t = _DEC_COMMA.sub(r"\1.\2", t)
    if (lang or "").lower().startswith("tr"):
        t = _TR_EW.sub(r"\1E", _TR_NS.sub(r"\1N", t))
    return t
TAGS = [
    ("cable", r"\b(CABLE|PIPELINE)\b"),
    ("survey", r"\b(SURVEY|RESEARCH|SEISMIC|HYDROGRAPHIC|GEOTECHNICAL|BATHYMETR)"),
    ("firing", r"\b(FIRING|GUNNERY|LIVE[- ]FIRE|MISSILE|TORPEDO|ARTILLERY)"),
    ("exercise", r"\b(EXERCISE|MANOEUVRES?|MANEUVERS?|DRILLS?)\b"),
    ("drilling", r"\b(DRILLING|DRILLSHIP|RIG)\b"),
]


def _dtg(d, h, m, mon, yy):
    mm = MONTHS.get(mon.upper()[:3])
    try:
        return datetime(2000 + int(yy), mm, int(d), int(h), int(m), tzinfo=timezone.utc) if mm else None
    except ValueError:  # 40 14 10N read as a time, 31 FEB, ...
        return None


def _date(d, mon, yy, end=False):
    mm = MONTHS.get(mon.upper()[:3])
    try:
        return datetime(2000 + int(yy), mm, int(d), 23 if end else 0, 59 if end else 0, tzinfo=timezone.utc) if mm else None
    except ValueError:
        return None


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def parse_coords(text: str) -> list[list[float]]:
    found = []  # (position in text, [lat, lon])
    taken = []
    for m in COORD_DMS.finditer(text):
        la_d, la_m, la_s, ns, lo_d, lo_m, lo_s, ew = m.groups()
        la_d, la_m, la_s, lo_d, lo_m, lo_s = int(la_d), int(la_m), float(la_s), int(lo_d), int(lo_m), float(lo_s)
        if la_d > 90 or lo_d > 180 or max(la_m, lo_m) >= 60 or max(la_s, lo_s) >= 60:
            continue
        lat = (la_d + la_m / 60 + la_s / 3600) * (-1 if ns.upper() == "S" else 1)
        lon = (lo_d + lo_m / 60 + lo_s / 3600) * (-1 if ew.upper() == "W" else 1)
        found.append((m.start(), [round(lat, 5), round(lon, 5)]))
        taken.append(m.span())
    for m in COORD.finditer(text):
        if any(a <= m.start() < b for a, b in taken):
            continue
        la_d, la_m, ns, lo_d, lo_m, ew = m.groups()
        la_d, lo_d, la_m, lo_m = int(la_d), int(lo_d), float(la_m), float(lo_m)
        if la_d > 90 or lo_d > 180 or la_m >= 60 or lo_m >= 60:
            continue
        lat = (la_d + la_m / 60) * (-1 if ns.upper() == "S" else 1)
        lon = (lo_d + lo_m / 60) * (-1 if ew.upper() == "W" else 1)
        found.append((m.start(), [round(lat, 5), round(lon, 5)]))
    return [p for _, p in sorted(found)]


def parse_navtex(text: str, source: str = "", url: str | None = None, lang: str | None = None) -> dict | None:
    """Parse one NAVTEX / NAVAREA-style warning. Returns None if it carries nothing usable."""
    raw = normalize(text.replace("\r", ""), lang).strip()
    if not raw:
        return None
    flat = re.sub(r"[ \t]+", " ", raw)
    out: dict = {"source": source, "url": url, "text": flat[:4000]}

    h = re.search(r"ZCZC\s*([A-Z])([A-Z])(\d{2})", flat)
    if h:
        out.update(b1=h.group(1), b2=h.group(2), serial=h.group(3),
                   header=f"{h.group(1)}{h.group(2)}{h.group(3)}", subject=SUBJECTS.get(h.group(2)))
    st = re.search(r"^\s*([A-Z][A-Z ]{2,25}?)\s+RADIO\s*$", flat, re.M)
    if st:
        out["station"] = st.group(1).title() + " Radio"
    cancels = [" ".join(k.upper().split()) + " " + num for k, num in CANCEL_OTHER.findall(flat)]
    if cancels:
        out["cancels"] = cancels
    n = re.search(NUMBER, CANCEL_OTHER.sub(" ", flat), re.I)
    if n:
        kind = re.sub(r"\s+", " ", n.group(1)).upper()
        out["number"] = f"{NUMBER_KIND.get(kind, kind)} {n.group(2)}"

    c = CANCEL.search(flat)
    cancel_on = _dtg(*c.groups()) if c else None
    body_wo_cancel = DTG_PAIR.sub("", CANCEL.sub("", flat))
    i = ISSUED.search(body_wo_cancel)
    issued = _dtg(*i.groups()) if i else None
    v, vd, vt, vp = VALID.search(flat), VALID_DAY.search(flat), VALID_DTG.search(flat), DTG_PAIR.search(flat)
    if v:
        valid_from, valid_to = _date(v.group(1), v.group(2), v.group(3)), _date(v.group(4), v.group(5), v.group(6), end=True)
    elif vp:
        d1, h1, m1, d2, h2, m2, mon, yy = vp.groups()
        valid_from, valid_to = _dtg(d1, h1, m1, mon, yy), _dtg(d2, h2, m2, mon, yy)
    elif vt:
        g = vt.groups()
        valid_from, valid_to = _dtg(*g[:5]), _dtg(*g[5:])
    elif vd:
        d_, mon, yy, h1, m1, h2, m2 = vd.groups()
        valid_from, valid_to = _dtg(d_, h1, m1, mon, yy), _dtg(d_, h2, m2, mon, yy)
    else:
        valid_from, valid_to = issued, None
    out.update(issued=_iso(issued), valid_from=_iso(valid_from), valid_to=_iso(cancel_on or valid_to), cancel_on=_iso(cancel_on))

    pts = parse_coords(flat)
    tags = [t for t, pat in TAGS if re.search(pat, flat, re.I)]
    out["tags"] = tags
    if pts:
        area = re.search(r"\b(AREA|BOUNDED|ENCLOSED|POLYGON|ZONE)\b", flat, re.I)
        line = re.search(r"\b(LINE|ALONG|ROUTE|JOINING|TRACK|CORRIDOR)\b", flat, re.I) or "cable" in tags
        listed = re.search(r"(?m)^\s*(?:\d{1,2}|[A-Z])[.)]\s+\d", raw) or re.search(r"\b(POSITIONS|BUOYS|WRECKS|OBSTRUCTIONS|BEACONS)\b", flat, re.I)
        if len(pts) == 1:
            geom = "point"
        elif area and len(pts) >= 3:
            geom = "polygon"
        elif line:
            geom = "line"
        elif listed:
            geom = "points"
        elif len(pts) == 2:
            geom = "line"
        else:
            geom = "polygon"
        out["geom"], out["points"] = geom, pts
        if geom == "polygon" and pts[0] != pts[-1]:
            out["points"] = pts + [pts[0]]
        r = re.search(r"(?:RADIUS|WITHIN)\s+(?:OF\s+)?(\d+(?:\.\d+)?)\s*(?:NM|MILES?)", flat, re.I)
        if r and geom == "point":
            out["radius_nm"] = float(r.group(1))
    wb = re.search(r"WIDE\s+B[EI]RTH\s+(?:OF\s+|REQUESTED\s+)?(\d+(?:\.\d+)?)\s*NM", flat, re.I)
    if wb:
        out["clearance_nm"] = float(wb.group(1))

    up = flat.upper()
    out["vessels"] = [dict(name=k, **v) for k, v in WATCH_VESSELS.items() if k in up]
    gv = re.search(r"\b(?:M/V|R/V|MV|RV|VESSEL)\s+\"?([A-Z][A-Z0-9 .'-]{2,28}?)\"?(?=\s+(?:WILL|IS|ARE|CONDUCT|OPERAT|PERFORM|ENGAGED|IMO|MMSI)|\s+-\s|\s*\(|[,.;\n\"])", up)
    if gv and not out["vessels"]:
        out["vessels"] = [{"name": gv.group(1).strip()}]
    if len(out["vessels"]) == 1:  # identifiers printed in the text (MMSI: 228505700, IMO 9388613) help the AIS match
        mmsi, imo = re.search(r"\bMMSI\s*:?\s*(\d{9})\b", up), re.search(r"\bIMO\s*:?\s*(\d{7})\b", up)
        if mmsi and not out["vessels"][0].get("mmsi"):
            out["vessels"][0]["mmsi"] = mmsi.group(1)
        if imo and not out["vessels"][0].get("imo"):
            out["vessels"][0]["imo"] = imo.group(1)

    out["id"] = out.get("number") or (f"{out.get('station', 'NAVTEX')} {out.get('header', '')}".strip() + " " + (out.get("issued") or ""))
    if not (out.get("points") or out.get("number") or out.get("header") or out.get("cancels")):
        return None
    return out


def split_messages(body: str) -> list[str]:
    body = re.sub(r"```[a-z]*", "", body)
    msgs = re.findall(r"ZCZC.*?NNNN", body, re.S)
    return msgs if msgs else [body]


def _ts(v):
    return datetime.strptime(v, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) if v else None


def _active(m: dict, now: datetime) -> bool:
    vt = m.get("valid_to")
    if vt and datetime.strptime(vt, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) < now:
        return False
    if not vt:  # no end time in the text: keep it NAVTEX_MAX_DAYS after it was issued / posted
        start = _ts(m.get("issued")) or _ts(m.get("received"))
        if start and (now - start).days >= int(os.environ.get("NAVTEX_MAX_DAYS") or 30):
            return False
    vf = m.get("valid_from")
    if vf and datetime.strptime(vf, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) > now:
        # broadcast already, validity still ahead: keep it (flagged) if it starts soon, like the NOTAM layer does
        if (datetime.strptime(vf, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) - now).days >= int(os.environ.get("NAVTEX_UPCOMING_DAYS") or 14):
            return False
        m["upcoming"] = True
    return True


def _in_region(m: dict) -> bool:
    pts = m.get("points") or []
    return (not pts) or any(REGION[0] <= la <= REGION[1] and REGION[2] <= lo <= REGION[3] for la, lo in pts)


def _issue_list(errs: list):
    inbox = os.environ.get("NAVTEX_INBOX_FILE", "").strip()
    if inbox:
        try:
            j = json.loads(Path(inbox).read_text(encoding="utf-8") or "[]")
            return j if isinstance(j, list) else []
        except Exception as e:
            errs.append(f"inbox file: {str(e)[:80]}")
            return []
    tok, repo = os.environ.get("GITHUB_TOKEN", "").strip(), os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not (tok and repo):
        return None
    r = requests.get(f"https://api.github.com/repos/{repo}/issues", timeout=30,
                     headers={**UA, "Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"},
                     params={"labels": os.environ.get("NAVTEX_LABEL", "navtex"), "state": "all", "per_page": 60, "sort": "created", "direction": "desc"})
    r.raise_for_status()
    return r.json()


def _from_issues(errs: list) -> list[dict]:
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    allowed = {a.strip().lower() for a in os.environ.get("NAVTEX_ALLOWED_AUTHORS", repo.split("/")[0] if repo else "").split(",") if a.strip()}
    label = os.environ.get("NAVTEX_LABEL", "navtex").lower()
    out: list[dict] = []
    try:
        items = _issue_list(errs)
        if not items:
            return []
        for it in items:
            if label not in {(lb.get("name") or "").lower() for lb in it.get("labels") or []}:
                continue
            if "pull_request" in it or (it.get("user") or {}).get("login", "").lower() not in allowed:
                continue
            if it.get("state") == "closed":  # closing the issue = cancel the warning
                continue
            for k, chunk in enumerate(split_messages(it.get("body") or "")):
                m = parse_navtex(chunk, source=f"issue #{it['number']}", url=it.get("html_url"))
                if m:
                    m["id"] += f" #{it['number']}.{k}"
                    m["received"] = (it.get("created_at") or "")[:19] + "Z" if it.get("created_at") else None
                    out.append(m)
    except Exception as e:
        errs.append(f"issues: {str(e)[:100]}")
    return out


def _from_files(errs: list) -> list[dict]:
    d = Path(__file__).resolve().parent.parent / "navtex"
    out: list[dict] = []
    if d.is_dir():
        for f in sorted(d.glob("*.txt")):
            try:
                for k, chunk in enumerate(split_messages(f.read_text(encoding="utf-8", errors="replace"))):
                    m = parse_navtex(chunk, source=f"navtex/{f.name}")
                    if m:
                        m["id"] += f" {f.stem}.{k}"
                        m["received"] = datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                        out.append(m)
            except Exception as e:
                errs.append(f"{f.name}: {str(e)[:80]}")
    return out


SEALAGOM = "https://www.sealagom.com"
_SL_KEEP = ("id", "scope", "region_id", "region_title", "title", "country", "number", "content", "content_en",
            "source_language", "added_on", "cancel_date")


def _sealagom_pull(token: str, errs: list) -> tuple[list[dict], int]:
    """One refresh: every warning in force whose SeaLagom-parsed position falls in the box. Text only."""
    bbox = os.environ.get("SEALAGOM_BBOX", "").strip() or f"{REGION[2]},{REGION[0]},{REGION[3]},{REGION[1]}"
    pages = max(1, int(os.environ.get("SEALAGOM_MAX_PAGES") or 4))
    hdr = {**UA, "X-API-Token": token, "Accept": "application/json"}
    params = {"bbox": bbox, "status": "in_force", "has_coordinates": "true", "page_size": 200}
    out, calls = [], 0
    for page in range(1, pages + 1):
        calls += 1
        r = requests.get(f"{SEALAGOM}/api/v2/messages/", headers=hdr, params={**params, "page": page}, timeout=60)
        if r.status_code in (401, 402, 403, 429):  # 402 = free allowance used up (SeaLagom)
            detail = ""
            if r.headers.get("content-type", "").startswith("application/json"):
                detail = (r.json() or {}).get("detail") or ""
            errs.append(f"SeaLagom {r.status_code}: {str(detail or r.reason)[:80]}")
            break
        r.raise_for_status()
        j = r.json() or {}
        out += [{k: x.get(k) for k in _SL_KEEP} for x in (j.get("results") or [])]
        if not j.get("next"):
            break
    return out, calls


# Short region prefixes so that warning numbers stay unique across stations ("NAVWARN 1089/26" is issued by
# Antalya, Izmir and the Hellenic service alike). Cyprus keeps the plain NAVWARN number so that the same
# warning pasted into the inbox is recognised as a duplicate.
_SL_PREFIX = {"Hellenic Navigational Warnings": "HELLENIC NAVWARN", "Cyprus Coastal": "NAVWARN"}


def _sl_number(title: str, parsed: str | None, api_number: str | None) -> str | None:
    num = (parsed or "").split(" ")[-1] if parsed else (api_number or "")
    if not num:
        return parsed
    kind = parsed.rsplit(" ", 1)[0] if parsed else ""
    if kind and kind != "NAVWARN":  # NAVAREA III, TURNHOS N/W, CYPRUS NAVTEX ...: already specific
        return parsed
    prefix = _SL_PREFIX.get(title) or title.upper().replace("NAVIGATIONAL WARNINGS", "NAVWARN").replace("NAVIGATIONAL WARNING", "NAVWARN")
    return f"{prefix} {num}"


def _sealagom_convert(rec: dict) -> dict | None:
    title = (rec.get("title") or rec.get("region_title") or "SeaLagom").strip()
    src = f"SeaLagom · {title}"
    url = f"{SEALAGOM}/{rec.get('scope') or 'coastal'}/{rec.get('region_id')}/message/{rec.get('id')}/"
    lang = rec.get("source_language") or "en"
    content = rec.get("content") or ""
    m = parse_navtex(content, source=src, url=url, lang=lang)
    if (not m or not m.get("points")) and rec.get("content_en") and lang != "en":
        m2 = parse_navtex(rec["content_en"], source=src, url=url, lang="en")
        if m2 and (m2.get("points") or not m):
            m = m2
    if not m:
        if not (content.strip() and rec.get("number")):
            return None
        m = {"source": src, "url": url, "text": normalize(content, lang)[:4000], "tags": [], "vessels": [],
             "issued": None, "valid_from": None, "valid_to": None, "cancel_on": None}
    m["number"] = _sl_number(title, m.get("number"), rec.get("number"))
    if not m.get("station"):
        m["station"] = title
    added = (rec.get("added_on") or "")[:19]
    m["received"] = added + "Z" if added else None
    if not m.get("issued") and m["received"]:
        m["issued"] = m["received"]
    if not m.get("valid_to") and rec.get("cancel_date"):
        m["valid_to"] = rec["cancel_date"][:19] + "Z"
    m["id"] = f"sealagom {rec.get('scope')}/{rec.get('id')}"
    m["country"] = rec.get("country")
    return m


def _from_sealagom(state: dict, errs: list) -> tuple[list[dict], dict]:
    import time as _time
    token = os.environ.get("SEALAGOM_API_TOKEN", "").strip() or os.environ.get("SEALAGOM_API_KEY", "").strip()
    if not token:
        return [], {"name": "SeaLagom", "note": "not configured (SEALAGOM_API_TOKEN)", "ok": False, "live": True}
    every = int(float(os.environ.get("SEALAGOM_EVERY_MIN") or 120) * 60)
    cache = state.get("sealagom")
    fresh = cache is not None and _time.time() - state.get("_t", {}).get("sealagom", 0) < every
    note_tail = f"refreshed every {every // 60} min"
    if fresh:
        note_tail = "cached, " + note_tail
    else:
        before = len(errs)
        try:
            recs, calls = _sealagom_pull(token, errs)
            if recs or len(errs) == before:
                state["sealagom"] = cache = recs
                state.setdefault("_t", {})["sealagom"] = int(_time.time())
                note_tail = f"{calls} call{'s' if calls != 1 else ''}, {note_tail}"
            else:
                note_tail = "showing cached, " + note_tail
        except Exception as e:
            errs.append(f"SeaLagom: {str(e)[:100]}")
            note_tail = "showing cached, " + note_tail
    cache = cache or []
    out = [m for m in (_sealagom_convert(r) for r in cache) if m]
    regions = sorted({(r.get("title") or r.get("region_title") or "?").strip() for r in cache})
    sl_errs = [e for e in errs if e.startswith("SeaLagom")]
    note = f"{len(cache)} warnings in force in the box from {len(regions)} regions ({note_tail})" + (f"; {'; '.join(sl_errs)}" if sl_errs else "")
    return out, {"name": "SeaLagom", "note": note, "ok": bool(cache) and not sl_errs, "live": True}


def fetch_navtex(state: dict):
    """Collector hook: returns (list_of_warnings | None, [inbox_status, sealagom_status])."""
    errs: list[str] = []
    now = datetime.now(timezone.utc)
    sl_msgs, sl_status = _from_sealagom(state, errs)
    msgs = _from_issues(errs) + _from_files(errs) + sl_msgs
    cancelled = {c for m in msgs for c in m.get("cancels", [])}
    seen, keep = set(), []
    for m in msgs:
        key = m.get("number") or m["id"]
        if m.get("cancels") and not m.get("points"):
            continue  # a pure cancellation message: it removes others, it is not a warning itself
        if key in seen or key in cancelled or not _in_region(m) or not _active(m, now):
            continue
        seen.add(key)
        keep.append(m)
    keep.sort(key=lambda m: m.get("issued") or "", reverse=True)
    inbox_on = bool(os.environ.get("NAVTEX_INBOX_FILE") or (os.environ.get("GITHUB_TOKEN") and os.environ.get("GITHUB_REPOSITORY"))) or (Path(__file__).resolve().parent.parent / "navtex").is_dir()
    inbox_errs = [e for e in errs if not e.startswith("SeaLagom")]
    n_inbox = sum(1 for m in keep if not str(m.get("id", "")).startswith("sealagom"))
    n_sl = len(keep) - n_inbox
    if inbox_on:
        note = f"{n_inbox} active warnings from the inbox" + (f" ({len(cancelled)} cancelled by later messages)" if cancelled else "") + (f"; problems: {'; '.join(inbox_errs)}" if inbox_errs else "")
        inbox_status = {"name": "NAVTEX inbox", "note": note, "ok": not inbox_errs, "live": True}
    else:
        inbox_status = {"name": "NAVTEX inbox", "note": "not configured (label an issue `navtex`, or add navtex/*.txt)", "ok": False, "live": True}
        if not sl_msgs and "not configured" in sl_status["note"]:
            return None, [inbox_status, sl_status]
    if sl_msgs:
        sl_status["note"] = f"{n_sl} shown (in the region, active or starting within {os.environ.get('NAVTEX_UPCOMING_DAYS') or 14} days) · " + sl_status["note"]
    return keep, [inbox_status, sl_status]
