"""
News layer: collect semiconductor and supply-chain news worldwide, tag each story by place and topic,
and write a feed the globe (and later the app) can read.

Sources (edit news_sources.json): trade-press RSS, think-tank / economic-forum RSS, GDELT (global news in
65 languages), Google News regional editions in local languages, Hacker News and Reddit.
Only headlines, links, dates and a short summary are stored; the globe links out to the full story.

Tagging (edit news_gazetteer.py):
  * countries named in the headline (weight 3), summary (1) or via a company's home country (0.5)
  * primary country = highest weight; falls back to the outlet's own country; region follows the country
  * topics (export controls, materials, fabs, AI demand, ...), tracked inputs (helium, neon, HF, gallium)
  * alert = a disruption or export-control story about a tracked input or critical material, or a chip headline
    reporting a physical disruption (fire, outage, shortage, war...), for the globe's risk monitor

Writes
  data/news/news.db            SQLite archive, every story ever collected (what an app would query)
  data/news/news_latest.json   last 30 days, grouped by region and country, ready for the globe
  data/news/news_by_region.csv counts by region and topic
  news_log.txt                 which sources worked (written by run_news.bat)

Run:  python news_collector.py            (needs internet; no API keys)
      python news_collector.py --days 7   look back further on the first run
"""
import argparse
import html
import json
import math
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote_plus, urlsplit, urlunsplit, parse_qsl, urlencode
import xml.etree.ElementTree as ET

import news_gazetteer as gz

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "news"
UA = "semiconductor-risk-engine/1.0 (student research project; news headlines only)"
NOW = datetime.now(timezone.utc)



# ---------------------------------------------------------------- compiled patterns
def _c(pats, flags=re.I):
    return [re.compile(p, flags) for p in pats]


PLACE_RX = {c: _c(p) for c, p in gz.PLACE_PATTERNS.items()}
for c, p in gz.CASE_SENSITIVE.items():
    PLACE_RX.setdefault(c, []).extend(_c(p, 0))
COMPANY_RX = {c: [re.compile(r"\b" + n + r"\b" if not n.startswith("\\") else n) for n in names]
              for c, names in gz.COMPANIES.items()}
STRIP_RX = _c(gz.STRIP + gz.EXCLUDE)
JUNK_RX = _c(gz.JUNK)
CORE_RX = _c(gz.CORE)
TOPIC_RX = {t: _c(p) for t, p in gz.TOPICS.items()}
INPUT_RX = {i: [re.compile(p, 0 if p == r"\bHF\b" else re.I) for p in ps] for i, ps in gz.TRACKED_INPUTS.items()}
DISRUPT_RX = TOPIC_RX["conflict & disruption"] + TOPIC_RX["export controls & sanctions"]
TAG_RX = re.compile(r"<[^>]+>")


# ---------------------------------------------------------------- helpers
def clean(text, limit=None):
    text = html.unescape(TAG_RX.sub(" ", text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    if limit and len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "…"
    return text


def parse_date(s):
    if not s:
        return None
    s = s.strip()
    for fn in (parsedate_to_datetime,
               lambda x: datetime.fromisoformat(x.replace("Z", "+00:00")),
               lambda x: datetime.strptime(x, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)):
        try:
            d = fn(s)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None


def canon_url(u):
    try:
        p = urlsplit(u)
        q = [(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith(("utm_", "fbclid", "gclid", "ref"))]
        return urlunsplit((p.scheme, p.netloc.lower(), p.path.rstrip("/"), urlencode(q), ""))
    except Exception:
        return u


def title_key(t):
    return re.sub(r"[^\w]+", "", t.lower())[:90]


def http_get(url, session, tries=2, timeout=(8, 20)):
    last = None
    for i in range(tries):
        try:
            r = session.get(url, timeout=timeout, headers={"User-Agent": UA})
            if r.status_code == 429 and i + 1 < tries:
                time.sleep(8)
                continue
            r.raise_for_status()
            return r.content
        except Exception as e:  # noqa: BLE001 - one bad source must not stop the run
            last = e
            time.sleep(2)
    raise last


def _text(el, *names):
    for n in names:
        x = el.find(n)
        if x is not None:
            if x.text and x.text.strip():
                return x.text
            if x.get("href"):
                return x.get("href")
    return ""


BAD_AMP = re.compile(rb"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)")


def parse_feed(raw):
    """RSS 2.0, Atom and RSS 1.0 (RDF) with the standard library only. Retries once after fixing the
    most common feed error (HTML entities such as &nbsp; or a bare & that XML does not allow)."""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        root = ET.fromstring(BAD_AMP.sub(b"&amp;", raw.lstrip()))
    for el in root.iter():                      # drop namespaces so one set of names works for all three
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    out = []
    for it in list(root.iter("item")) + list(root.iter("entry")):
        link = _text(it, "link")
        if not link:
            for l in it.findall("link"):
                if l.get("rel", "alternate") == "alternate" and l.get("href"):
                    link = l.get("href")
        src = it.find("source")
        out.append(dict(
            title=clean(_text(it, "title")),
            url=(link or "").strip(),
            published=parse_date(_text(it, "pubDate", "published", "updated", "date")),
            summary=clean(_text(it, "description", "summary", "content", "encoded"), 400),
            outlet=clean(src.text) if src is not None and src.text else "",
        ))
    return out


# ---------------------------------------------------------------- fetchers (each returns raw items)
def fetch_rss(cfg, session, since):
    items = []
    for s in [x for x in cfg.get("rss", []) if x.get("on", True)]:
        try:
            got = [i for i in parse_feed(http_get(s["url"], session)) if not i["published"] or i["published"] >= since]
            for i in got:
                i.update(source=s["name"], kind=s["kind"], home=s.get("country") if s.get("local") else None,
                         lang="en", via="rss")
            items += got
            yield_log(s["name"], "ok", len(got))
        except Exception as e:  # noqa: BLE001
            yield_log(s["name"], "failed", 0, e)
    return items


def fetch_googlenews(cfg, session, since):
    g = cfg.get("googlenews", {})
    items = []
    if not g.get("on", True):
        return items
    days = max(1, (NOW - since).days)
    for ed in g.get("editions", []):
        q = quote_plus(f'{ed["q"]} when:{days}d')
        url = f'https://news.google.com/rss/search?q={q}&hl={ed["hl"]}&gl={ed["gl"]}&ceid={ed["ceid"]}'
        name = f'Google News {ed["gl"]} "{ed["q"]}"'
        try:
            got = parse_feed(http_get(url, session))
            for i in got:
                outlet = i["outlet"]
                if outlet and i["title"].endswith(" - " + outlet):
                    i["title"] = i["title"][: -len(outlet) - 3]
                local = not ed["hl"].lower().startswith("en")      # a local-language edition = local news
                i.update(source=outlet or "Google News", kind="general news", home=ed["country"] if local else None,
                         lang=ed["hl"].split("-")[0], via="google news", summary="")
            got = [i for i in got if not i["published"] or i["published"] >= since]
            items += got
            yield_log(name, "ok", len(got))
        except Exception as e:  # noqa: BLE001
            yield_log(name, "failed", 0, e)
        time.sleep(1.5)
    return items


GDELT_COUNTRY = {"Taiwan": "Taiwan", "South Korea": "South Korea", "Korea, South": "South Korea",
                 "United States": "United States", "United Kingdom": "United Kingdom", "Russia": "Russia",
                 "China": "China", "Japan": "Japan", "Hong Kong": "China"}


def fetch_gdelt(cfg, session, since):
    g = cfg.get("gdelt", {})
    items = []
    if not g.get("on", True):
        return items
    hours = max(1, int((NOW - since).total_seconds() // 3600))
    for n, q in enumerate(g.get("queries", [])):
        url = ("https://api.gdeltproject.org/api/v2/doc/doc?mode=ArtList&format=json&sort=DateDesc"
               f"&maxrecords=250&timespan={hours}h&query={quote_plus(q)}")
        name = f"GDELT query {n + 1}"
        try:
            raw = http_get(url, session, timeout=(10, 60))     # GDELT is slow to answer
            arts = json.loads(raw.decode("utf-8", "replace")).get("articles", [])
            got = []
            for a in arts:
                sc = a.get("sourcecountry") or ""
                got.append(dict(title=clean(a.get("title")), url=a.get("url", ""), summary="",
                                published=parse_date(a.get("seendate")), source=a.get("domain", "GDELT"),
                                kind="general news", home=None,
                                lang=(a.get("language") or "English")[:2].lower(), via="gdelt", outlet=""))
            items += got
            yield_log(name, "ok", len(got))
        except Exception as e:  # noqa: BLE001
            yield_log(name, "failed", 0, e)
        time.sleep(6)                          # GDELT asks for at most one request every 5 seconds
    return items


def fetch_hn(cfg, session, since):
    h = cfg.get("hn", {})
    items = []
    if not h.get("on", True):
        return items
    ts = int(since.timestamp())
    for q in h.get("queries", []):
        url = ("https://hn.algolia.com/api/v1/search_by_date?tags=story&hitsPerPage=100"
               f"&numericFilters=created_at_i>{ts}&query={quote_plus(q)}")
        name = f'Hacker News "{q}"'
        try:
            hits = json.loads(http_get(url, session)).get("hits", [])
            got = []
            for x in hits:
                disc = f'https://news.ycombinator.com/item?id={x["objectID"]}'
                got.append(dict(title=clean(x.get("title")), url=x.get("url") or disc, discussion=disc,
                                summary="", published=parse_date(x.get("created_at")), source="Hacker News",
                                kind="forum", home=None, lang="en", via="hn", outlet="",
                                engagement=(x.get("points") or 0) + (x.get("num_comments") or 0)))
            items += got
            yield_log(name, "ok", len(got))
        except Exception as e:  # noqa: BLE001
            yield_log(name, "failed", 0, e)
    return items


def fetch_reddit(cfg, session, since):
    r = cfg.get("reddit", {})
    items = []
    if not r.get("on", True):
        return items
    for sub in r.get("subreddits", []):
        name = f"Reddit r/{sub}"
        try:
            kids = json.loads(http_get(f"https://www.reddit.com/r/{sub}/new.json?limit=100&raw_json=1",
                                       session)).get("data", {}).get("children", [])
            got = []
            for k in kids:
                d = k.get("data", {})
                pub = datetime.fromtimestamp(d.get("created_utc", 0), timezone.utc)
                if pub < since:
                    continue
                disc = "https://www.reddit.com" + d.get("permalink", "")
                ext = d.get("url_overridden_by_dest") or ""
                got.append(dict(title=clean(d.get("title")), url=ext or disc, discussion=disc,
                                summary=clean(d.get("selftext"), 400), published=pub, source=f"r/{sub}",
                                kind="forum", home=None, lang="en", via="reddit", outlet="",
                                engagement=(d.get("score") or 0) + (d.get("num_comments") or 0)))
            items += got
            yield_log(name, "ok", len(got))
        except Exception as e:  # noqa: BLE001
            yield_log(name, "failed", 0, e)
        time.sleep(2)
    return items


LOG = []


class Tee:
    """Print to the window and to news_log.txt at the same time, so progress shows while it runs."""
    def __init__(self, path):
        self.f = open(path, "w", encoding="utf-8")
        self.out = sys.stdout

    def write(self, s):
        self.out.write(s)
        self.f.write(s)

    def flush(self):
        self.out.flush()
        self.f.flush()


def yield_log(name, status, n, err=None):
    line = f"{status:6s} {n:4d}  {name}" + (f"  ({type(err).__name__}: {str(err)[:120]})" if err else "")
    LOG.append(dict(source=name, status=status, items=n, error=str(err)[:200] if err else ""))
    print(line, flush=True)


# ---------------------------------------------------------------- tagging
def strip_false_friends(text):
    for rx in STRIP_RX:
        text = rx.sub(" ", text)
    return text


def place_weights(title, summary):
    w = Counter()
    for part, wt in ((title, 3.0), (summary, 1.0)):
        if not part:
            continue
        for c, rxs in PLACE_RX.items():
            if any(rx.search(part) for rx in rxs):
                w[c] += wt
        for c, rxs in COMPANY_RX.items():
            if any(rx.search(part) for rx in rxs):
                w[c] += 0.5 * wt
    return w


def tag(item):
    title = strip_false_friends(item["title"])
    summary = strip_false_friends(item.get("summary", ""))
    both = f"{title} {summary}"
    core_title = sum(bool(rx.search(title)) for rx in CORE_RX)
    core_all = sum(bool(rx.search(both)) for rx in CORE_RX)
    if core_all == 0 or any(rx.search(item["title"]) for rx in JUNK_RX):
        return None                                            # not about chips, or filler: drop

    w = place_weights(title, summary)
    countries = [c for c, _ in w.most_common()]
    primary = countries[0] if countries else item.get("home")
    located_by = "story" if countries else ("outlet" if primary else "none")
    region, lat, lon = gz.COUNTRIES.get(primary, (None, None, None)) if primary else (None, None, None)

    topics = [t for t, rxs in TOPIC_RX.items() if any(rx.search(both) for rx in rxs)]
    inputs = [i for i, rxs in INPUT_RX.items() if any(rx.search(both) for rx in rxs)]
    disrupt = any(rx.search(both) for rx in DISRUPT_RX)
    # alert = a disruption or export-control story about an input the risk engine tracks or a critical material
    # ...or a physical disruption (fire, outage, war, shortage...) named in a chip headline
    hard = any(rx.search(title) for rx in TOPIC_RX["conflict & disruption"]) and core_title > 0
    alert = bool((disrupt and (inputs or "critical materials" in topics)) or hard)

    score = 2.0 * core_title + 1.0 * min(core_all, 3) + 0.5 * len(topics) + 1.5 * len(inputs)
    score += {"trade press": 1.0, "industry body": 1.0, "policy & economics": 0.8}.get(item["kind"], 0.0)
    if item.get("engagement"):
        score += min(2.0, math.log10(1 + item["engagement"]))
    if located_by == "none":
        score -= 1.0

    pub = item.get("published") or NOW
    return dict(
        id=title_key(item["title"]) or canon_url(item["url"]),
        title=item["title"], url=canon_url(item["url"]), discussion=item.get("discussion", ""),
        summary=item.get("summary", ""), source=item["source"], kind=item["kind"], via=item["via"],
        lang=item.get("lang", "en"), published=pub.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        countries=countries, country=primary, located_by=located_by, region=region, lat=lat, lon=lon,
        topics=topics, inputs=inputs, alert=bool(alert), score=round(score, 2),
        engagement=int(item.get("engagement") or 0),
    )


# ---------------------------------------------------------------- storage
SCHEMA = """CREATE TABLE IF NOT EXISTS articles (
  id TEXT PRIMARY KEY, title TEXT, url TEXT, discussion TEXT, summary TEXT, source TEXT, kind TEXT, via TEXT,
  lang TEXT, published TEXT, fetched TEXT, countries TEXT, country TEXT, located_by TEXT, region TEXT,
  lat REAL, lon REAL, topics TEXT, inputs TEXT, alert INTEGER, score REAL, engagement INTEGER)"""
COLS = ["id", "title", "url", "discussion", "summary", "source", "kind", "via", "lang", "published", "fetched",
        "countries", "country", "located_by", "region", "lat", "lon", "topics", "inputs", "alert", "score",
        "engagement"]
PREFER = {"trade press": 4, "industry body": 3, "policy & economics": 3, "general news": 2, "forum": 1}


def save(db, rows):
    con = sqlite3.connect(db)
    con.execute(SCHEMA)
    new = 0
    for r in rows:
        old = con.execute("SELECT kind, engagement FROM articles WHERE id=?", (r["id"],)).fetchone()
        rec = {**r, "fetched": NOW.strftime("%Y-%m-%dT%H:%MZ"),
               "countries": json.dumps(r["countries"]), "topics": json.dumps(r["topics"]),
               "inputs": json.dumps(r["inputs"]), "alert": int(r["alert"])}
        if old is None:
            new += 1
        elif PREFER.get(old[0], 0) > PREFER.get(r["kind"], 0) and (old[1] or 0) >= r["engagement"]:
            continue                                            # keep the better source we already have
        con.execute(f"INSERT OR REPLACE INTO articles ({','.join(COLS)}) VALUES ({','.join('?' * len(COLS))})",
                    [rec[c] for c in COLS])
    con.commit()
    con.close()
    return new


CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")
STOP = {"the", "and", "for", "with", "from", "that", "this", "its", "into", "will", "has", "are", "was", "new", "says",
        "after", "over", "amid", "as", "to", "of", "in", "on", "a", "an", "by", "at", "up", "us", "is",
        # words almost every story shares, so they say nothing about whether two headlines are the same news
        "semiconductor", "semiconductors", "chip", "chips", "chipmaker", "supply", "chain", "chains", "industry",
        "market", "global", "stock", "stocks", "tech", "technology", "company", "firm", "firms", "news", "report",
        "2025", "2026", "2027", "反導體", "半導", "導體", "导体", "반도", "도체"}


NUM_RX = [(re.compile(r"\$?\s?(\d+(?:\.\d+)?)\s?(?:billion|bn|bil|b)\b"), r" \1b "),
          (re.compile(r"\$?\s?(\d+(?:\.\d+)?)\s?(?:million|mn|mil|m)\b"), r" \1m ")]


def tokens(title):
    t = title.lower()
    for rx, rep in NUM_RX:                      # "$21B", "21bn", "21 billion" -> "21b"
        t = rx.sub(rep, t)
    words = {w for w in re.findall(r"[a-z0-9]+", t) if len(w) > 2 and w not in STOP}
    cjk = "".join(CJK.findall(t))
    return words | {cjk[i:i + 2] for i in range(len(cjk) - 1)}


def cluster(rows, threshold=0.5, days=4):
    """Merge stories that are the same news from different outlets (3+ shared headline words covering >= 60% of
    the shorter headline, ignoring generic chip words,
    within a few days). Keeps the best-sourced copy and records how many outlets covered it."""
    order = sorted(rows, key=lambda r: (-PREFER.get(r["kind"], 0), -r["score"], r["published"]))
    kept = []
    for r in order:
        tk = tokens(r["title"])
        t = parse_date(r["published"].replace("Z", ":00Z")) if len(r["published"]) == 17 else parse_date(r["published"])
        home = None
        for k in kept:
            if abs((k["_t"] - t).total_seconds()) > days * 86400 or not tk or not k["_tk"]:
                continue
            shared = len(tk & k["_tk"])
            if shared >= 3 and shared / min(len(tk), len(k["_tk"])) >= threshold:
                home = k
                break
        if home is None:
            r.update(_tk=tk, _t=t, coverage=1, outlets=[r["source"]])
            kept.append(r)
        else:
            home["coverage"] += 1
            if r["source"] not in home["outlets"]:
                home["outlets"].append(r["source"])
            home["alert"] = home["alert"] or r["alert"]
            for c in r["countries"]:
                if c not in home["countries"]:
                    home["countries"].append(c)
            home["discussion"] = home["discussion"] or r["discussion"]
    for k in kept:
        k.pop("_tk"), k.pop("_t")
        k["outlets"] = k["outlets"][:8]
        k["score"] = round(k["score"] + min(2.0, math.log2(k["coverage"])), 2)
    return sorted(kept, key=lambda r: r["published"], reverse=True)


def export(db, keep_days, sources_log):
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    since = (NOW - timedelta(days=keep_days)).strftime("%Y-%m-%dT%H:%MZ")
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM articles WHERE published >= ? ORDER BY published DESC", (since,))]
    con.close()
    for r in rows:
        for k in ("countries", "topics", "inputs"):
            r[k] = json.loads(r[k] or "[]")
        r["alert"] = bool(r["alert"])
        r.pop("fetched", None)
    rows = cluster([r for r in rows if r["score"] >= 2.0])[:1500]

    by_region = defaultdict(list)
    for r in rows:
        by_region[r["region"] or "Global"].append(r)
    regions = []
    for reg, items in sorted(by_region.items(), key=lambda kv: -len(kv[1])):
        cs = defaultdict(list)
        for r in items:
            cs[r["country"]].append(r)
        regions.append(dict(
            region=reg, count=len(items), alerts=sum(r["alert"] for r in items),
            top_topics=[t for t, _ in Counter(t for r in items for t in r["topics"]).most_common(3)],
            countries=[dict(country=c, lat=gz.COUNTRIES.get(c, (None, None, None))[1],
                            lon=gz.COUNTRIES.get(c, (None, None, None))[2], count=len(v),
                            alerts=sum(x["alert"] for x in v),
                            top_ids=[x["id"] for x in sorted(v, key=lambda x: -x["score"])[:5]])
                       for c, v in sorted(cs.items(), key=lambda kv: -len(kv[1]))],
        ))
    feed = dict(generated_at=NOW.strftime("%Y-%m-%dT%H:%MZ"), window_days=keep_days, count=len(rows),
                sources=sources_log, regions=regions, items=rows)
    (OUT / "news_latest.json").write_text(json.dumps(feed, ensure_ascii=False, indent=1), encoding="utf-8")

    lines = ["region,country,stories,alerts,top_topics"]
    for reg in regions:
        for c in reg["countries"]:
            tops = Counter(t for r in by_region[reg["region"]] if r["country"] == c["country"] for t in r["topics"])
            lines.append(f'"{reg["region"]}","{c["country"]}",{c["count"]},{c["alerts"]},'
                         f'"{"; ".join(t for t, _ in tops.most_common(3))}"')
    (OUT / "news_by_region.csv").write_text("\n".join(lines), encoding="utf-8")
    return feed


LOCAL_OUTLETS = set()


def retag(db):
    """Apply an edited gazetteer to stories already in the archive (no internet needed)."""
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute("SELECT * FROM articles")]
    con.close()
    out = []
    for r in rows:
        item = dict(title=r["title"], summary=r["summary"] or "", url=r["url"], discussion=r["discussion"] or "",
                    source=r["source"], kind=r["kind"], via=r["via"], lang=r["lang"], engagement=r["engagement"],
                    published=parse_date(r["published"].replace("Z", ":00Z")),
                    home=(r["country"] if r["located_by"] == "outlet" and (r["lang"] != "en" or r["source"] in LOCAL_OUTLETS)
                          else None))
        t = tag(item)
        if t:
            t["id"] = r["id"]
            out.append(t)
    con = sqlite3.connect(db)
    con.execute("DELETE FROM articles")
    con.commit()
    con.close()
    save(db, out)
    return len(out)


# ---------------------------------------------------------------- main
def collect(cfg, since, session):
    raw = []
    for fn in (fetch_rss, fetch_googlenews, fetch_gdelt, fetch_hn, fetch_reddit):
        raw += fn(cfg, session, since)
    tagged, seen = {}, {}
    for it in raw:
        if not it.get("title") or not it.get("url"):
            continue
        t = tag(it)
        if t is None:
            continue
        k = t["id"]
        prev = tagged.get(k)
        if prev is None or (PREFER.get(t["kind"], 0), t["score"]) > (PREFER.get(prev["kind"], 0), prev["score"]):
            if prev is not None:                                 # keep forum discussion links and engagement
                t["discussion"] = t["discussion"] or prev["discussion"]
                t["engagement"] = max(t["engagement"], prev["engagement"])
            tagged[k] = t
        elif t["discussion"] and not prev["discussion"]:
            prev["discussion"] = t["discussion"]
        seen[k] = seen.get(k, 0) + 1
    return raw, list(tagged.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, help="look back this many days (default: lookback_days in news_sources.json)")
    ap.add_argument("--export-only", action="store_true", help="rebuild news_latest.json from the archive")
    ap.add_argument("--retag", action="store_true", help="re-tag every stored story with the current gazetteer")
    args = ap.parse_args()
    sys.stdout = Tee(ROOT / "news_log.txt")
    cfg = json.loads((ROOT / "news_sources.json").read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    db = OUT / "news.db"

    LOCAL_OUTLETS.update(s["name"] for s in cfg.get("rss", []) if s.get("local"))
    if args.retag:
        print(f"Re-tagged {retag(db)} stories with the current news_gazetteer.py")
    elif not args.export_only:
        import requests
        since = NOW - timedelta(days=args.days or cfg.get("lookback_days", 3))
        print(f"Collecting stories since {since:%Y-%m-%d %H:%M} UTC. This takes about 3-5 minutes; "
              f"each line below is one source.\n")
        with requests.Session() as s:
            raw, rows = collect(cfg, since, s)
        new = save(db, rows)
        print(f"\n{len(raw)} items fetched, {len(rows)} about chips after filtering and de-duplication, {new} new.")
    log = LOG
    if not log and (OUT / "news_latest.json").exists():          # re-tag / export only: keep the last run's source list
        try:
            log = json.loads((OUT / "news_latest.json").read_text(encoding="utf-8")).get("sources", [])
        except Exception:
            log = []
    feed = export(db, cfg.get("keep_days_in_feed", 30), log)
    print(f"news_latest.json: {feed['count']} stories over {feed['window_days']} days\n")
    for r in feed["regions"]:
        top = ", ".join(f'{c["country"]} {c["count"]}' for c in r["countries"][:4])
        print(f'{r["region"]:22s} {r["count"]:4d} stories  {r["alerts"]:3d} alerts   {top}')
    ok = sum(l["status"] == "ok" for l in LOG)
    if LOG and not args.retag and not args.export_only:
        print(f"\nSources: {ok} of {len(LOG)} worked. Failed ones are listed above; fix or switch them off "
              f"in news_sources.json.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
