"""Run: python collector/tests/test_sealagom_feeds.py   (no pytest, no network: the feeds are mocked).

sealagom_feed_irakleio.json and sealagom_feed_antalya.json are real answers of the open SeaLagom station feeds
(GET https://www.sealagom.com/feeds/coastal/82.json and /33.json, 8 Nov 2026, no token). Irakleio (Crete) NAVTEX
is reachable only through its feed: its messages are not in the /api/v2/messages/ index.
"""
import json
import os
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import navtex  # noqa: E402

HERE = Path(__file__).resolve().parent
FEEDS = {"coastal/82": json.loads((HERE / "sealagom_feed_irakleio.json").read_text(encoding="utf-8")),
         "coastal/33": json.loads((HERE / "sealagom_feed_antalya.json").read_text(encoding="utf-8"))}


class FixedDT(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 11, 8, 0, 30, tzinfo=tz or timezone.utc)


navtex.datetime = FixedDT
calls = []


class Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body
        self.headers = {"content-type": "application/feed+json"}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def fake_get(url, headers=None, params=None, timeout=None):
    calls.append(url)
    assert "X-API-Token" not in (headers or {}), "feeds need no token"
    path = url.split("/feeds/", 1)[1].removesuffix(".json")
    if fake_get.fail or path not in FEEDS:
        return Resp(503, {})
    return Resp(200, FEEDS[path])


fake_get.fail = False
navtex.requests = types.SimpleNamespace(get=fake_get)

# ---------------------------------------------------------------- one feed item -> API record shape
item = FEEDS["coastal/82"]["items"][0]
rec = navtex._feed_to_rec("coastal/82", item)
assert rec["scope"] == "coastal" and rec["region_id"] == 82 and rec["id"] == 52962 and rec["number"] == "1411/26", rec
m = navtex._sealagom_convert(rec)
assert m["number"] == "IRAKLEIO NAVWARN 1411/26" and m["station"].startswith("Irakleio"), (m["number"], m["station"])
assert m["source"] == "SeaLagom · Irakleio NAVTEX (Crete)" and m["url"].endswith("/coastal/82/message/52962/")
assert m["geom"] == "line" and len(m["points"]) >= 20 and "cable" in m["tags"], (m.get("geom"), len(m.get("points") or []))
assert m["vessels"] and m["vessels"][0]["name"] == "ABEILLE MARENGO", m["vessels"]

tr = navtex._feed_to_rec("coastal/33", FEEDS["coastal/33"]["items"][0])
assert tr["source_language"] == "tr" and tr["number"] == "1111/26", tr
t = navtex._sealagom_convert(tr)
assert t["number"] == "ANTALYA NAVTEX 1111/26" and abs(t["points"][0][0] - 36.8405) < 0.01, (t["number"], t.get("points", [])[:1])

# ---------------------------------------------------------------- fetch_navtex: feeds on, no token, inbox has the same 1411/26
os.environ.pop("SEALAGOM_API_TOKEN", None)
os.environ.pop("SEALAGOM_API_KEY", None)
os.environ["SEALAGOM_FEEDS"] = "coastal/82,coastal/33"
inbox = HERE / "_inbox_tmp.json"
inbox.write_text(json.dumps([{"number": 7, "state": "open", "user": {"login": "TheMurdoc"}, "labels": [{"name": "navtex"}],
                              "html_url": "https://github.com/TheMurdoc/levantine-watch/issues/7", "created_at": "2026-11-06T15:00:00Z",
                              "body": (HERE / "gsi_navwarn_1411_26.txt").read_text(encoding="utf-8")}]), encoding="utf-8")
os.environ["NAVTEX_INBOX_FILE"] = str(inbox)
os.environ["GITHUB_REPOSITORY"] = "TheMurdoc/levantine-watch"
try:
    state = {}
    keep, statuses = navtex.fetch_navtex(state)
    sl = statuses[1]
    assert len(calls) == 2 and sl["ok"], (calls, sl)
    assert "Irakleio" in sl["note"] and "Antalya" in sl["note"] and "API box query off" in sl["note"], sl["note"]
    nums = [m["number"] for m in keep]
    # the inbox copy wins and the feed copy of the same broadcast (Irakleio, B1 "H", 1411/26) is dropped
    assert nums.count("NAVWARN 1411/26") == 1 and "IRAKLEIO NAVWARN 1411/26" not in nums, nums
    assert "IRAKLEIO NAVWARN 1404/26" in nums, nums  # Kobi Ruegg cable survey, south-east Cretan Sea
    assert "ANTALYA NAVTEX 1111/26" in nums, nums
    assert not any("1140/26" in n for n in nums), nums  # Laconian Gulf, west of the map
    assert all(navtex._in_region(m) for m in keep)

    # second run inside the hour: no request
    keep2, _ = navtex.fetch_navtex(state)
    assert len(calls) == 2 and len(keep2) == len(keep)

    # feed down at the next pull: the previous pull is kept, the status says so
    state["_t"]["sealagom_feeds"] = 0
    fake_get.fail = True
    keep3, statuses3 = navtex.fetch_navtex(state)
    assert len(calls) == 4 and len(keep3) == len(keep) and "503" in statuses3[1]["note"], statuses3[1]
finally:
    inbox.unlink(missing_ok=True)
print("sealagom feeds OK:", len(keep), "warnings ·", sl["note"])
