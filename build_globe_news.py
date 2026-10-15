"""
Put the latest news into the globe page.

Reads  data/news/news_latest.json   (from news_collector.py)
Writes globe/orbit_globe.html       the same page with the stories embedded; open it in any browser,
                                    or ask Claude to publish it to your Orbit Globe link.

Run:  python build_globe_news.py      (run_news.bat runs this after collecting)
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FEED = ROOT / "data" / "news" / "news_latest.json"
PAGE = ROOT / "globe" / "orbit_globe.html"
START, END = "/*NEWS_JSON*/", "/*END_NEWS*/"
KEEP = ["title", "url", "discussion", "source", "kind", "lang", "published", "country", "countries", "region",
        "lat", "lon", "topics", "inputs", "alert", "score", "coverage", "outlets"]
MAX_ITEMS = 700          # keeps the page small; the archive in news.db keeps everything


def main():
    feed = json.loads(FEED.read_text(encoding="utf-8"))
    items = sorted(feed.get("items", []), key=lambda r: (r.get("published") or ""), reverse=True)
    if len(items) > MAX_ITEMS:                       # keep alerts, then the best-scored of the rest
        alerts = [r for r in items if r.get("alert")]
        rest = sorted([r for r in items if not r.get("alert")], key=lambda r: -r.get("score", 0))
        items = sorted(alerts + rest[: max(0, MAX_ITEMS - len(alerts))],
                       key=lambda r: (r.get("published") or ""), reverse=True)[:MAX_ITEMS]
    src = feed.get("sources", [])
    slim = dict(generated_at=feed.get("generated_at"), window_days=feed.get("window_days", 30),
                count=len(items), sources_ok=sum(s.get("status") == "ok" for s in src), sources_total=len(src),
                items=[{k: r.get(k) for k in KEEP if r.get(k) not in (None, "", [])} | {"alert": bool(r.get("alert"))}
                       for r in items])
    blob = json.dumps(slim, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

    html = PAGE.read_text(encoding="utf-8")
    a, b = html.index(START) + len(START), html.index(END)
    PAGE.write_text(html[:a] + blob + html[b:], encoding="utf-8")
    print(f"Globe updated: {len(items)} stories in {len({r.get('country') for r in items if r.get('country')})} "
          f"countries, collected {slim['generated_at']}. Open globe/orbit_globe.html to view.")


if __name__ == "__main__":
    main()
