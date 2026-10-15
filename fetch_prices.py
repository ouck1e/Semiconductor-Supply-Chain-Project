"""
Phase 8, step 1: daily stock prices for the chip supply chain, over the same years as the Comtrade data.

Downloads (free, no keys):
  * ~26 companies across fabs, toolmakers, chip designers and input suppliers, on their home exchanges
  * benchmarks (semiconductor ETF and index, S&P 500, KOSPI, TAIEX, Nikkei 225, Hang Seng, MSCI World ETF)
  * exchange rates, so every return can be compared in US dollars
  * Fama-French daily factors (US and developed markets), used later to strip out market-wide moves

Writes
  data/market/market.db             SQLite: prices, fx, factors, universe (what the app and models will query)
  data/market/prices_adj_close.csv  wide table, one column per ticker (adjusted for splits and dividends)
  data/market/stock_summary.csv     per stock: return, volatility, beta and correlation to the chip sector, drawdown
  figures/stocks_by_group.png       every stock indexed to 100, by group, with the four supply shocks marked
  figures/stock_correlations.png    weekly return correlations (who moves together)
  prices_log.txt

Run:  python fetch_prices.py            (or double-click run_prices.bat; needs internet, takes ~2 minutes)
      python fetch_prices.py --stats    rebuild the summary and figures from market.db without downloading
"""
import argparse
import io
import re
import sqlite3
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "market"
FIGS = ROOT / "figures"
START = "2015-01-01"

INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e6e5e0", "#fcfcfb"
SLOT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]

# ticker (Yahoo Finance symbol), name, group, home country, currency
UNIVERSE = [
    ("2330.TW", "TSMC", "Foundries & memory", "Taiwan", "TWD"),
    ("005930.KS", "Samsung Electronics", "Foundries & memory", "South Korea", "KRW"),
    ("000660.KS", "SK hynix", "Foundries & memory", "South Korea", "KRW"),
    ("MU", "Micron", "Foundries & memory", "United States", "USD"),
    ("INTC", "Intel", "Foundries & memory", "United States", "USD"),
    ("GFS", "GlobalFoundries", "Foundries & memory", "United States", "USD"),          # listed Oct 2021
    ("0981.HK", "SMIC", "Foundries & memory", "China", "HKD"),
    ("2303.TW", "UMC", "Foundries & memory", "Taiwan", "TWD"),
    ("ASML.AS", "ASML", "Equipment", "Netherlands", "EUR"),
    ("AMAT", "Applied Materials", "Equipment", "United States", "USD"),
    ("LRCX", "Lam Research", "Equipment", "United States", "USD"),
    ("KLAC", "KLA", "Equipment", "United States", "USD"),
    ("8035.T", "Tokyo Electron", "Equipment", "Japan", "JPY"),
    ("NVDA", "Nvidia", "Chip designers", "United States", "USD"),
    ("AMD", "AMD", "Chip designers", "United States", "USD"),
    ("QCOM", "Qualcomm", "Chip designers", "United States", "USD"),
    ("2454.TW", "MediaTek", "Chip designers", "Taiwan", "TWD"),
    ("LIN", "Linde", "Gases & materials", "United States", "USD"),
    ("APD", "Air Products", "Gases & materials", "United States", "USD"),
    ("AI.PA", "Air Liquide", "Gases & materials", "France", "EUR"),
    ("ENTG", "Entegris", "Gases & materials", "United States", "USD"),
    ("4063.T", "Shin-Etsu Chemical", "Gases & materials", "Japan", "JPY"),
    ("3436.T", "SUMCO", "Gases & materials", "Japan", "JPY"),
    ("4091.T", "Nippon Sanso", "Gases & materials", "Japan", "JPY"),
    ("MP", "MP Materials", "Rare earths", "United States", "USD"),                    # listed Nov 2020
    ("LYC.AX", "Lynas", "Rare earths", "Australia", "AUD"),
]
BENCHMARKS = [
    ("SOXX", "iShares Semiconductor ETF", "Benchmark", "United States", "USD"),
    ("^SOX", "Philadelphia Semiconductor Index", "Benchmark", "United States", "USD"),
    ("^GSPC", "S&P 500", "Benchmark", "United States", "USD"),
    ("URTH", "iShares MSCI World ETF", "Benchmark", "Global", "USD"),
    ("^KS11", "KOSPI", "Benchmark", "South Korea", "KRW"),
    ("^TWII", "TAIEX", "Benchmark", "Taiwan", "TWD"),
    ("^N225", "Nikkei 225", "Benchmark", "Japan", "JPY"),
    ("^HSI", "Hang Seng", "Benchmark", "China", "HKD"),
]
# Yahoo FX: "KRW=X" = KRW per 1 USD; "EURUSD=X" = USD per 1 EUR
FX = {"KRW": ("KRW=X", "per_usd"), "TWD": ("TWD=X", "per_usd"), "JPY": ("JPY=X", "per_usd"),
      "HKD": ("HKD=X", "per_usd"), "EUR": ("EURUSD=X", "usd_per"), "AUD": ("AUDUSD=X", "usd_per")}
FF_URLS = {
    "us": "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_5_Factors_2x3_daily_CSV.zip",
    "developed": "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/Developed_5_Factors_Daily_CSV.zip",
}
SHOCKS = [("2019-07-01", "HF 2019"), ("2022-02-24", "Neon 2022"), ("2023-07-03", "Gallium 2023"),
          ("2026-03-02", "Helium 2026")]


class Tee:
    def __init__(self, path):
        self.f, self.out = open(path, "w", encoding="utf-8"), sys.stdout

    def write(self, s):
        self.out.write(s)
        self.f.write(s)

    def flush(self):
        self.out.flush()
        self.f.flush()


# ---------------------------------------------------------------- download
def yahoo_history(symbol, tries=3):
    """Daily adjusted close and volume for one symbol, index = trading date."""
    import yfinance as yf
    last = None
    for i in range(tries):
        try:
            h = yf.Ticker(symbol).history(start=START, auto_adjust=True, actions=False)
            if h is None or h.empty:
                raise ValueError("no data returned")
            h.index = pd.to_datetime(h.index).tz_localize(None).normalize()
            return h[["Close", "Volume"]].rename(columns={"Close": "adj_close", "Volume": "volume"})
        except Exception as e:  # noqa: BLE001 - one bad symbol must not stop the run
            last = e
            time.sleep(2 + 2 * i)
    raise last


def fama_french(url):
    """Ken French data library zip -> daily factors in decimal returns."""
    import requests
    raw = requests.get(url, timeout=(10, 60), headers={"User-Agent": "semiconductor-risk-engine/1.0"}).content
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        text = z.read(z.namelist()[0]).decode("latin-1")
    lines = text.splitlines()
    head = next(i for i, l in enumerate(lines) if l.strip().lower().startswith(",mkt-rf"))
    cols = ["date"] + [c.strip().lower().replace("-", "_") for c in lines[head].split(",")[1:]]
    rows = [l.split(",") for l in lines[head + 1:] if re.match(r"^\s*\d{8}\s*,", l)]
    df = pd.DataFrame(rows, columns=cols)
    df["date"] = pd.to_datetime(df["date"].str.strip(), format="%Y%m%d")
    for c in cols[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce") / 100.0
    return df[df["date"] >= START]


def download(db):
    con = sqlite3.connect(db)
    uni = pd.DataFrame(UNIVERSE + BENCHMARKS, columns=["ticker", "name", "group", "country", "currency"])
    uni.to_sql("universe", con, if_exists="replace", index=False)

    ok, failed, frames = 0, [], []
    for t, name, *_ in UNIVERSE + BENCHMARKS:
        try:
            h = yahoo_history(t)
            h = h.reset_index().rename(columns={"index": "date", "Date": "date"})
            h["ticker"] = t
            frames.append(h)
            ok += 1
            print(f"ok     {len(h):5d} days  {t:10s} {name}  ({h['date'].min():%Y-%m-%d} to {h['date'].max():%Y-%m-%d})")
        except Exception as e:  # noqa: BLE001
            failed.append(t)
            print(f"failed            {t:10s} {name}  ({type(e).__name__}: {str(e)[:100]})")
    if frames:
        pd.concat(frames)[["date", "ticker", "adj_close", "volume"]].to_sql("prices", con, if_exists="replace", index=False)

    fx_frames = []
    for cur, (sym, kind) in FX.items():
        try:
            h = yahoo_history(sym).reset_index().rename(columns={"index": "date", "Date": "date"})
            # store as USD per 1 unit of local currency, whatever Yahoo's quoting convention
            h["usd_per_unit"] = 1.0 / h["adj_close"] if kind == "per_usd" else h["adj_close"]
            h["currency"] = cur
            fx_frames.append(h[["date", "currency", "usd_per_unit"]])
            print(f"ok     {len(h):5d} days  FX {cur}")
        except Exception as e:  # noqa: BLE001
            print(f"failed            FX {cur}  ({type(e).__name__}: {str(e)[:100]})")
    if fx_frames:
        pd.concat(fx_frames).to_sql("fx", con, if_exists="replace", index=False)

    for region, url in FF_URLS.items():
        try:
            ff = fama_french(url)
            ff.to_sql(f"factors_{region}", con, if_exists="replace", index=False)
            print(f"ok     {len(ff):5d} days  Fama-French factors ({region}), to {ff['date'].max():%Y-%m-%d}")
        except Exception as e:  # noqa: BLE001
            print(f"failed            Fama-French factors ({region})  ({type(e).__name__}: {str(e)[:100]})")
    con.close()
    print(f"\nPrices: {ok} of {len(UNIVERSE) + len(BENCHMARKS)} symbols downloaded." +
          (f" Failed: {', '.join(failed)}" if failed else ""))


# ---------------------------------------------------------------- stats
def load(db):
    con = sqlite3.connect(db)
    px = pd.read_sql("SELECT * FROM prices", con, parse_dates=["date"])
    uni = pd.read_sql("SELECT * FROM universe", con)
    try:
        fx = pd.read_sql("SELECT * FROM fx", con, parse_dates=["date"])
    except Exception:  # noqa: BLE001
        fx = pd.DataFrame(columns=["date", "currency", "usd_per_unit"])
    con.close()
    wide = px.pivot_table(index="date", columns="ticker", values="adj_close").sort_index()
    return wide, uni, fx


def to_usd(wide, uni, fx):
    """Convert each local-currency price series to US dollars at that day's exchange rate."""
    usd = wide.copy()
    cur = dict(zip(uni.ticker, uni.currency))
    for t in usd.columns:
        c = cur.get(t, "USD")
        if c == "USD":
            continue
        rate = fx[fx.currency == c].set_index("date")["usd_per_unit"].sort_index()
        if rate.empty:
            usd[t] = np.nan
            continue
        usd[t] = usd[t] * rate.reindex(usd.index).ffill()
    return usd


def summary(usd, uni):
    weekly = usd.resample("W-FRI").last()
    wr = np.log(weekly).diff()
    bench = "SOXX" if "SOXX" in wr else wr.columns[0]
    rows = []
    for _, u in uni.iterrows():
        t = u.ticker
        if t not in usd or usd[t].dropna().empty:
            continue
        s = usd[t].dropna()
        years = (s.index[-1] - s.index[0]).days / 365.25
        r = wr[t].dropna()
        both = wr[[t, bench]].dropna()
        beta = np.cov(both[t], both[bench])[0, 1] / np.var(both[bench], ddof=1) if len(both) > 20 and t != bench else np.nan
        rows.append(dict(
            ticker=t, name=u["name"], group=u["group"], country=u.country, first=s.index[0].date(), last=s.index[-1].date(),
            total_return_usd_pct=round(100 * (s.iloc[-1] / s.iloc[0] - 1), 1),
            annual_return_usd_pct=round(100 * ((s.iloc[-1] / s.iloc[0]) ** (1 / years) - 1), 1) if years > 0.5 else np.nan,
            annual_vol_pct=round(100 * r.std() * np.sqrt(52), 1),
            beta_to_soxx=round(beta, 2) if beta == beta else np.nan,
            corr_to_soxx=round(both[t].corr(both[bench]), 2) if t != bench and len(both) > 20 else np.nan,
            max_drawdown_pct=round(100 * (s / s.cummax() - 1).min(), 1),
        ))
    return pd.DataFrame(rows), wr


def style(ax):
    ax.set_facecolor(SURF)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=8.5, length=0)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)


def fig_groups(usd, uni):
    groups = [g for g in uni.group.unique() if g != "Benchmark"]
    fig, axes = plt.subplots(len(groups), 1, figsize=(11, 2.6 * len(groups)), sharex=True)
    fig.patch.set_facecolor(SURF)
    soxx = usd["SOXX"].dropna() if "SOXX" in usd else None
    for ax, g in zip(axes, groups):
        style(ax)
        tick = [t for t in uni[uni.group == g].ticker if t in usd and usd[t].notna().any()]
        ends = []
        for i, t in enumerate(tick):
            s = usd[t].dropna()
            s = 100 * s / s.iloc[0]
            ax.plot(s.index, s, color=SLOT[i % len(SLOT)], lw=1.2)
            ends.append([np.log10(s.iloc[-1]), uni.set_index("ticker").loc[t, "name"], SLOT[i % len(SLOT)], s.index[-1]])
        # spread end labels so they don't overlap: at least `gap` apart in log10 units, order kept
        ends.sort(key=lambda e: e[0])
        ax.set_yscale("log")
        lo, hi = ax.get_ylim()
        gap = 0.06 * (np.log10(hi) - np.log10(max(lo, 1e-3)))
        for k in range(1, len(ends)):
            ends[k][0] = max(ends[k][0], ends[k - 1][0] + gap)
        x_end = max(e[3] for e in ends)
        for y, name, col, _ in ends:
            ax.annotate(name, (x_end, 10 ** y), xytext=(6, 0), textcoords="offset points", va="center",
                        fontsize=8, color=col, annotation_clip=False)
        if soxx is not None:
            sx = 100 * soxx / soxx.iloc[0]
            ax.plot(sx.index, sx, color=INK2, lw=1, ls="--", alpha=0.7)
        for d, lab in SHOCKS:
            ax.axvline(pd.Timestamp(d), color=INK, lw=0.8, ls=":")
        ax.set_yscale("log")
        ax.set_title(g, loc="left", fontsize=11, color=INK)
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
        ax.yaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    for d, lab in SHOCKS:
        axes[0].annotate(lab, (pd.Timestamp(d), 0), xycoords=("data", "axes fraction"), xytext=(3, 3),
                         textcoords="offset points", va="bottom", fontsize=8, color=INK2)
    fig.suptitle("Chip supply-chain stocks in US dollars, indexed to 100 at first trading day (log scale)",
                 x=0.02, ha="left", fontsize=13, color=INK)
    fig.text(0.02, 0.005, "Dashed grey = iShares Semiconductor ETF (SOXX). Dotted lines = the four supply shocks from "
             "phase 2. Prices adjusted for splits and dividends. Source: Yahoo Finance.", fontsize=8.5, color=INK2)
    fig.subplots_adjust(left=0.06, right=0.86, top=0.935, bottom=0.04, hspace=0.3)
    fig.savefig(FIGS / "stocks_by_group.png", dpi=150, facecolor=SURF)
    plt.close(fig)


def fig_corr(wr, uni):
    tick = [t for t in uni[uni.group != "Benchmark"].ticker if t in wr and wr[t].notna().sum() > 100]
    c = wr[tick].corr(min_periods=100)
    names = uni.set_index("ticker").loc[tick, "name"]
    fig, ax = plt.subplots(figsize=(10.5, 9))
    fig.patch.set_facecolor(SURF)
    im = ax.imshow(c.values, cmap="Blues", vmin=0, vmax=1)
    ax.set_xticks(range(len(tick)), names, rotation=70, ha="right", fontsize=8, color=INK)
    ax.set_yticks(range(len(tick)), names, fontsize=8, color=INK)
    for i in range(len(tick)):
        for j in range(len(tick)):
            v = c.values[i, j]
            if v == v:
                ax.text(j, i, f"{v:.1f}", ha="center", va="center", fontsize=6.5, color="white" if v > 0.6 else INK2)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.tick_params(length=0)
    cb = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
    cb.outline.set_visible(False)
    cb.ax.tick_params(labelsize=8, colors=INK2, length=0)
    fig.suptitle("Who moves together: correlation of weekly US-dollar returns, 2015–2026", x=0.02, ha="left",
                 fontsize=13, color=INK)
    fig.text(0.02, 0.01, "Weekly returns avoid mismatched trading hours between Asian, European and US markets. "
             "Source: Yahoo Finance.", fontsize=8.5, color=INK2)
    fig.subplots_adjust(left=0.2, right=0.95, top=0.94, bottom=0.2)
    fig.savefig(FIGS / "stock_correlations.png", dpi=150, facecolor=SURF)
    plt.close(fig)


def stats(db):
    wide, uni, fx = load(db)
    wide.to_csv(OUT / "prices_adj_close.csv")
    usd = to_usd(wide, uni, fx)
    summ, wr = summary(usd, uni)
    summ.to_csv(OUT / "stock_summary.csv", index=False)
    fig_groups(usd, uni)
    fig_corr(wr, uni)
    pd.set_option("display.width", 200)
    print("\nStock summary (US dollars)")
    print(summ.drop(columns=["first"]).to_string(index=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stats", action="store_true", help="skip downloading; rebuild summary and figures")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    FIGS.mkdir(parents=True, exist_ok=True)
    sys.stdout = Tee(ROOT / "prices_log.txt")
    db = OUT / "market.db"
    if not args.stats:
        print(f"Downloading daily prices since {START}. Takes about 2 minutes; each line is one symbol.\n")
        download(db)
    stats(db)
    print("\nDone. Outputs in data/market/ and figures/.")


if __name__ == "__main__":
    main()
