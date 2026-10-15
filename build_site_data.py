"""
Build the website's data files in docs/data/ from the research pipeline's outputs.

  python build_site_data.py news     docs/data/news.json      <- data/news/news_latest.json (news_collector.py)
  python build_site_data.py prices   docs/data/meta.json, fx.json, prices/<ticker>.json
                                     <- data/market/market.db (fetch_prices.py) + event reactions (phase 8, Model 4)
  python build_site_data.py risk     docs/data/risk.json and the risk layer inside docs/index.html
                                     <- data/processed/exposure_scores_latest.csv (phase3_models.py)
                                        + data/external/gpr_monthly.csv (fetch_gpr.py)
  python build_site_data.py all      all of the above (skips any part whose inputs are missing)

Every run also updates docs/data/status.json, which the page shows as "last updated" times.
"""
import json
import math
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
OUT = DOCS / "data"
EPOCH = pd.Timestamp("2015-01-01")


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def write_json(path, obj, pretty=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(obj, ensure_ascii=False, indent=1 if pretty else None, separators=None if pretty else (",", ":"))
    old = path.read_text(encoding="utf-8") if path.exists() else None
    if old != txt:
        path.write_text(txt, encoding="utf-8")
    return old != txt


def set_status(part, **info):
    p = OUT / "status.json"
    st = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    st[part] = {"built": now(), **info}
    write_json(p, st, pretty=True)


# ---------------------------------------------------------------- news
def build_news():
    src = ROOT / "data" / "news" / "news_latest.json"
    if not src.exists():
        print("news: no data/news/news_latest.json, skipped")
        return
    d = json.loads(src.read_text(encoding="utf-8"))
    sources = d.pop("sources", None)
    if isinstance(sources, list):
        d["sources_total"] = len(sources)
        d["sources_ok"] = sum(1 for s in sources if s.get("status") == "ok")
    write_json(OUT / "news.json", d)
    set_status("news", asof=d.get("generated_at"), count=d.get("count"),
               sources=f"{d.get('sources_ok', '?')}/{d.get('sources_total', '?')}")
    print(f"news: {d.get('count')} stories, generated {d.get('generated_at')}")


# ---------------------------------------------------------------- prices
def sig(x, n=6):
    if x is None or not math.isfinite(x) or x == 0:
        return 0
    d = n - int(math.floor(math.log10(abs(x)))) - 1
    return round(x, d) if d > 0 else float(round(x, d))


def pack_dates(ds):
    off = ((ds - EPOCH).dt.days).astype(int).tolist()
    return off[0], [b - a for a, b in zip(off, off[1:])]


def safe(t):
    return t.replace("^", "_")


def build_prices():
    db = ROOT / "data" / "market" / "market.db"
    if not db.exists():
        print("prices: no data/market/market.db, skipped")
        return
    con = sqlite3.connect(db)
    uni = pd.read_sql("select * from universe", con)
    p = pd.read_sql("select * from prices", con, parse_dates=["date"])
    fx = pd.read_sql("select * from fx", con, parse_dates=["date"])
    con.close()

    for t, g in p.sort_values("date").groupby("ticker"):
        g = g.dropna(subset=["adj_close"])
        if g.empty:
            continue
        s, d = pack_dates(g["date"])
        vol = g["volume"].fillna(0).astype(float)
        write_json(OUT / "prices" / f"{safe(t)}.json",
                   dict(s=s, d=d, c=[sig(x) for x in g["adj_close"]],
                        v=None if (vol == 0).mean() > 0.5 else [int(sig(x, 3)) for x in vol]))
    fxo = {}
    for cur, g in fx.sort_values("date").groupby("currency"):
        s, d = pack_dates(g["date"])
        fxo[cur] = dict(s=s, d=d, r=[sig(x, 6) for x in g["usd_per_unit"]])
    write_json(OUT / "fx.json", fxo)

    # per-stock reaction to each supply shock (same method as phase 8 Model 4)
    import phase8_market_models as m8
    usd, _, _ = m8.load()
    react = {}
    for ev in m8.EVENTS:
        for t in usd.columns:
            if t == "URTH":
                continue
            try:
                w = m8.event_window(m8.daily_ar(usd, t), ev["date"])
            except Exception:  # noqa: BLE001 - a stock that wasn't trading yet
                w = None
            if w is None:
                continue
            ar, ar_est = w
            sd = ar_est.std()
            out = {}
            for k, hi in (("d5", 5), ("d20", 20)):
                seg = ar[(ar.index >= 0) & (ar.index <= hi)]
                car = float(seg.sum())
                tt = car / (sd * math.sqrt(len(seg))) if sd > 0 and len(seg) else float("nan")
                out[k] = [round(100 * (math.exp(car) - 1), 2), round(float(tt), 2) if math.isfinite(tt) else None]
            react.setdefault(ev["key"], {})[t] = out
    events = [dict(key=e["key"], date=e["date"],
                   role={**{t: "loser" for t in e["exposed"]}, **{t: "winner" for t in e["winners"]}})
              for e in m8.EVENTS]
    asof = str(p["date"].max().date())
    write_json(OUT / "meta.json", dict(asof=asof, u=uni.rename(columns={"group": "grp"}).to_dict("records"),
                                       ev=events, react=react, files={t: safe(t) for t in uni["ticker"]}))
    set_status("prices", asof=asof, symbols=int(p["ticker"].nunique()))
    print(f"prices: {p['ticker'].nunique()} symbols through {asof}")


# ---------------------------------------------------------------- risk
COUNTRY = {   # trade name: display name, lat, lon, GPR country code (None = no index), proxy flag
    "Russian Federation": ("Russia", 55.8, 37.6, "RUS", False), "Canada": ("Canada", 52.0, -106.0, "CAN", False),
    "Rep. of Korea": ("South Korea", 36.5, 127.9, "KOR", False), "Netherlands": ("Netherlands", 52.1, 5.3, "NLD", False),
    "Portugal": ("Portugal", 39.5, -8.0, "PRT", False), "Israel": ("Israel", 31.0, 34.9, "ISR", False),
    "Qatar": ("Qatar", 25.3, 51.2, "SAU", True), "Other Asia, nes": ("Taiwan", 23.7, 121.0, "TWN", False),
    "USA": ("United States", 39.0, -98.0, "USA", False), "Ukraine": ("Ukraine", 48.4, 31.2, "UKR", False),
    "Singapore": ("Singapore", 1.35, 103.8, None, False), "Japan": ("Japan", 36.2, 138.3, "JPN", False),
    "Germany": ("Germany", 51.2, 10.4, "DEU", False), "France": ("France", 46.6, 2.4, "FRA", False),
    "China": ("China", 35.0, 104.0, "CHN", False), "Brazil": ("Brazil", -14.2, -51.9, "BRA", False),
    "Mexico": ("Mexico", 23.6, -102.5, "MEX", False), "United Kingdom": ("United Kingdom", 54.0, -2.0, "GBR", False),
    "Algeria": ("Algeria", 28.0, 2.6, None, False), "Australia": ("Australia", -25.3, 133.8, "AUS", False),
    "Poland": ("Poland", 52.0, 19.1, "POL", False), "Malaysia": ("Malaysia", 4.2, 101.9, "MYS", False),
    "India": ("India", 22.0, 79.0, "IND", False), "Italy": ("Italy", 42.8, 12.6, "ITA", False),
    "Belgium": ("Belgium", 50.6, 4.5, "BEL", False), "Spain": ("Spain", 40.2, -3.6, "ESP", False),
    "Sweden": ("Sweden", 62.0, 15.0, "SWE", False), "Switzerland": ("Switzerland", 46.8, 8.2, "CHE", False),
    "Hungary": ("Hungary", 47.2, 19.5, "HUN", False), "Viet Nam": ("Vietnam", 16.0, 107.8, None, False),
    "Thailand": ("Thailand", 15.1, 101.0, "THA", False), "Indonesia": ("Indonesia", -2.5, 118.0, "IDN", False),
    "Philippines": ("Philippines", 12.9, 122.0, "PHL", False), "Ireland": ("Ireland", 53.2, -8.0, None, False),
    "Austria": ("Austria", 47.6, 14.1, None, False), "Kazakhstan": ("Kazakhstan", 48.0, 67.0, None, False),
    "South Africa": ("South Africa", -29.0, 24.0, None, False), "Saudi Arabia": ("Saudi Arabia", 24.0, 45.0, "SAU", False),
}
MATERIAL = {"helium": "Helium", "rare gas": "Neon & rare gases", "gallium": "Gallium (minor-metal code)",
            "hf": "Hydrogen fluoride"}


def gpr_status(r):
    if r is None:
        return "normal"
    return "critical" if r >= 1.75 else "serious" if r >= 1.4 else "warning" if r >= 1.2 else "normal"


def pair_status(score, share, ratio):
    """Same transparent rule the page applies (keep the two in step)."""
    r = ratio or 1
    if score >= 0.35 or (r >= 1.75 and share >= 0.5) or (score >= 0.15 and r >= 1.5):
        return "critical"
    if score >= 0.15 or (r >= 1.4 and share >= 0.2):
        return "serious"
    if score >= 0.12:
        return "warning"
    return None


def build_risk():
    scores_f = ROOT / "data" / "processed" / "exposure_scores_latest.csv"
    gpr_f = ROOT / "data" / "external" / "gpr_monthly.csv"
    if not scores_f.exists() or not gpr_f.exists():
        print("risk: model scores or GPR file missing, skipped")
        return
    sc = pd.read_csv(scores_f, parse_dates=["date"])
    g = pd.read_csv(gpr_f, parse_dates=["date"]).set_index("date").sort_index()
    countries = {}
    for key in sorted(set(sc["supplier"]) | set(sc["importer"])):
        name, lat, lon, iso, proxy = COUNTRY.get(key, (key, None, None, None, False))
        if lat is None:
            continue
        c = dict(name=name, lat=lat, lon=lon, iso=iso)
        col = f"GPRC_{iso}" if iso else None
        if col and col in g:
            s = g[col].dropna()
            if len(s) >= 27:
                ratio = float(s.iloc[-3:].mean() / s.iloc[-27:-3].mean())   # last 3 months vs the 24 before
                c.update(proxy=proxy, ratio=round(ratio, 2), latest=round(float(s.iloc[-1]), 2),
                         spark=[round(float(x), 2) for x in s.iloc[-24:]], status=gpr_status(ratio))
        c.setdefault("status", "normal")
        countries[key] = c
    pairs = []
    for _, r in sc.iterrows():
        ratio = countries.get(r["supplier"], {}).get("ratio")
        st = pair_status(float(r["exposure_score"]), float(r["share"]), ratio)
        if st is None or r["supplier"] not in countries or r["importer"] not in countries:
            continue
        pairs.append(dict(sup=r["supplier"], imp=r["importer"], mat=MATERIAL.get(r["series"], r["series"]),
                          share=round(float(r["share"]), 3), score=round(float(r["exposure_score"]), 3),
                          asof=r["date"].strftime("%Y-%m"), status=st))
    pairs.sort(key=lambda p: ({"critical": 0, "serious": 1, "warning": 2}[p["status"]], -p["score"]))
    risk = dict(gprAsof=g.index.max().strftime("%Y-%m"), countries=countries, pairs=pairs)
    write_json(OUT / "risk.json", risk)
    inject_risk(risk)
    trade_asof = sc["date"].max().strftime("%Y-%m")
    set_status("risk", asof=risk["gprAsof"], trade_asof=trade_asof, alerts=len(pairs))
    print(f"risk: {len(pairs)} supply routes flagged, GPR through {risk['gprAsof']}, trade through {trade_asof}")


def inject_risk(risk):
    page = DOCS / "index.html"
    html = page.read_text(encoding="utf-8")
    a, b = "/*RISK_JSON*/", "/*END_RISK*/"
    i, j = html.index(a) + len(a), html.index(b)
    new = html[:i] + json.dumps(risk, separators=(",", ":")) + html[j:]
    if new != html:
        page.write_text(new, encoding="utf-8")


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("news", "all"):
        build_news()
    if what in ("prices", "all"):
        build_prices()
    if what in ("risk", "all"):
        build_risk()
