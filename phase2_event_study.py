"""
Phase 2: event studies of four supply shocks to chipmaking inputs.

Reads the raw Comtrade files in data/raw/ (made by fetch_trade.py) and writes:
  data/processed/imports_classified.csv   rows tagged helium / rare gas (neon etc.) / uncertain
  data/processed/event_study_summary.csv  12 months before vs. 12 months after each shock
  figures/event_*.png                     one chart per shock

Run:  python phase2_event_study.py     (no internet or API key needed)
"""
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

ROOT = Path(__file__).resolve().parent
PROC = ROOT / "data" / "processed"
FIGS = ROOT / "figures"
FIGS.mkdir(parents=True, exist_ok=True)

# ---------- 1. split HS 2804.29 into helium vs. other rare gases ----------
# HS 2804.29 lumps helium with neon, krypton and xenon. Rule, stated so it can be challenged:
#   * helium   = shipped from a helium-producing country AND priced under $300/kg
#   * rare gas = everything else (neon, krypton, xenon), i.e. any non-producer origin, or any row at $300/kg+
# The supplier test comes first on purpose: a price-only rule is circular in a price-shock study,
# because rows "become" neon only once neon gets expensive. gas_flag marks rows the rule is unsure about:
# cheap rows from non-producers, which may be re-exported helium (e.g. via Germany or France).
HELIUM_PRODUCERS = {"USA", "Qatar", "Algeria", "Australia", "Russian Federation", "Canada",
                    "Poland", "South Africa", "United Rep. of Tanzania"}
RARE_GAS_USD_PER_KG = 300


def classify_gases(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    is_gas = df["material"] == "helium"
    upk = df["usd_per_kg"]
    producer = df["supplier"].isin(HELIUM_PRODUCERS)
    helium = is_gas & producer & (upk < RARE_GAS_USD_PER_KG)
    df["series"] = df["material"]
    df.loc[is_gas & helium, "series"] = "helium"
    df.loc[is_gas & ~helium, "series"] = "rare gas"
    df["gas_flag"] = ""
    df.loc[is_gas & ~helium & ~producer & (upk < RARE_GAS_USD_PER_KG), "gas_flag"] = "cheap non-producer row: may be helium"
    return df


# ---------- loading: keep only quantities the country actually reported ----------
# Comtrade fills missing weights with its own estimates (isNetWgtEstimated). Those are built from
# standard unit values, so they flatten prices to a constant: useless for a price study. We drop them.
# Gases are priced per cubic meter (the unit the US, Japan and Korea report helium in), solids per kg.
GASES = {"helium", "rare gas"}


def load_raw() -> pd.DataFrame:
    frames = []
    for f in sorted((ROOT / "data" / "raw").glob("*.csv")):
        material = f.stem.rsplit("_", 1)[0]
        d = pd.read_csv(f)
        d = d[d["partnerCode"] != 0].copy()
        d["material"] = material
        frames.append(d)
    raw = pd.concat(frames, ignore_index=True)
    out = pd.DataFrame({
        "date": pd.to_datetime(raw["period"].astype(str), format="%Y%m"),
        "material": raw["material"],
        "importer": raw["reporterDesc"],
        "supplier": raw["partnerDesc"],
        "value_usd": raw["primaryValue"],
        "net_kg": raw["netWgt"].where(raw["netWgt"] > 0),
        "net_kg_reported": raw["netWgt"].where((raw["netWgt"] > 0) & ~raw["isNetWgtEstimated"].astype(bool)),
        "qty_m3_reported": raw["qty"].where((raw["qtyUnitAbbr"] == "m³") & (raw["qty"] > 0)
                                            & ~raw["isQtyEstimated"].astype(bool)),
    })
    out["usd_per_kg"] = out["value_usd"] / out["net_kg"]   # coarse, used only to sort gases
    return out


MIN_QTY_COVERAGE = 0.6   # show a unit price only if reported quantities cover 60%+ of import value


def price_basis(sub: pd.DataFrame, series: str):
    """Pick the quantity the importer actually reports for this series: m³ or kg, whichever covers
    more of the import value (Korea reports gases by weight, the US and Japan by volume)."""
    options = [("net_kg_reported", "US$ per kg")]
    if series in GASES:
        options.insert(0, ("qty_m3_reported", "US$ per m³"))
    total = sub["value_usd"].sum()
    cover = {c: sub.loc[sub[c].notna(), "value_usd"].sum() / total if total else 0 for c, _ in options}
    best = max(options, key=lambda o: cover[o[0]])
    return best[0], best[1], cover[best[0]]


# ---------- 2. the four shocks ----------
EVENTS = [
    dict(key="hf_2019", title="Japan restricts hydrogen fluoride exports to South Korea",
         series="hf", importer="Rep. of Korea", shock="2019-07-01",
         window=("2017-07-01", "2021-06-01"), watch="Japan",
         note="Japan tightened licensing for HF, photoresist and fluorinated polyimide to Korea in July 2019."),
    dict(key="neon_2022", title="Russia invades Ukraine; Ukrainian neon supply collapses",
         series="rare gas", importer="Rep. of Korea", shock="2022-02-01",
         window=("2020-01-01", "2024-12-01"), watch="Ukraine",
         note="HS 2804.29 minus helium from helium-producing countries: mostly neon, plus krypton and xenon."),
    dict(key="gallium_2023", title="China puts gallium exports under licensing",
         series="gallium", importer="Japan", shock="2023-08-01",
         window=("2021-08-01", "2025-07-01"), watch="China",
         note="HS 8112.92 also covers other minor metals, so this is a noisy proxy for gallium."),
    dict(key="gallium_2023_us", title="China puts gallium exports under licensing (US view)",
         series="gallium", importer="USA", shock="2023-08-01",
         window=("2021-08-01", "2025-07-01"), watch="China",
         note="HS 8112.92 also covers other minor metals, so this is a noisy proxy for gallium."),
    dict(key="helium_2026", title="Ras Laffan, Qatar goes offline after drone strikes",
         series="helium", importer="USA", shock="2026-03-01",
         window=("2024-07-01", "2026-07-01"), watch="Qatar",
         note="Korea and China have not yet reported 2026 data; the US and Japan report through Jul 2026."),
]

DISPLAY = {"Rep. of Korea": "South Korea", "Other Asia, nes": "Taiwan (Other Asia, nes)",
           "USA": "United States", "Russian Federation": "Russia"}

# chart colors: fixed categorical order (validated reference palette, light mode)
SLOT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
OTHER = "#b9b8b3"
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e6e5e0", "#fcfcfb"


def event_frame(df, ev):
    sub = df[(df["series"] == ev["series"]) & (df["importer"] == ev["importer"])]
    lo, hi = pd.Timestamp(ev["window"][0]), pd.Timestamp(ev["window"][1])
    sub = sub[(sub["date"] >= lo) & (sub["date"] <= hi)]
    months = pd.date_range(lo, min(hi, sub["date"].max()) if len(sub) else hi, freq="MS")
    return sub, months


def summarize(sub, ev):
    qcol, unit, coverage = price_basis(sub, ev["series"])
    price_ok = coverage >= MIN_QTY_COVERAGE
    shock = pd.Timestamp(ev["shock"])
    pre = sub[(sub["date"] < shock) & (sub["date"] >= shock - pd.DateOffset(months=12))]
    post = sub[(sub["date"] >= shock) & (sub["date"] < shock + pd.DateOffset(months=12))]

    def stats(x):
        n_months = x["date"].nunique()
        if n_months == 0:
            return dict(months=0, usd_m_per_month=np.nan, qty_per_month=np.nan, unit_price=np.nan,
                        watch_share=np.nan, hhi=np.nan, top_supplier=None)
        v = x["value_usd"].sum()
        has_q = x[qcol].notna()
        kg = x.loc[has_q, qcol].sum()
        v_q = x.loc[has_q, "value_usd"].sum()
        by = x.groupby("supplier")["value_usd"].sum()
        s = by / by.sum()
        return dict(months=n_months, usd_m_per_month=v / 1e6 / n_months, qty_per_month=kg / n_months,
                    unit_price=v_q / kg if (kg and price_ok) else np.nan, watch_share=s.get(ev["watch"], 0.0),
                    hhi=float((s ** 2).sum()), top_supplier=s.idxmax())

    a, b = stats(pre), stats(post)
    row = dict(event=ev["key"], importer=ev["importer"], series=ev["series"], shock=ev["shock"],
               watched_supplier=ev["watch"], price_unit=unit if price_ok else "not reliable",
               qty_coverage=round(coverage, 2))
    for k in a:
        row[f"pre_{k}"], row[f"post_{k}"] = a[k], b[k]
    for k in ("usd_m_per_month", "qty_per_month", "unit_price"):
        ok = price_ok or k == "usd_m_per_month"
        row[f"change_{k}_pct"] = (b[k] / a[k] - 1) * 100 if ok and a[k] and not np.isnan(a[k]) and not np.isnan(b[k]) else np.nan
    row["change_watch_share_pts"] = (b["watch_share"] - a["watch_share"]) * 100 if b["months"] else np.nan
    return row


def plot_event(sub, months, ev):
    shock = pd.Timestamp(ev["shock"])
    by = sub.pivot_table(index="date", columns="supplier", values="value_usd", aggfunc="sum").reindex(months).fillna(0)
    by = by.rolling(3, min_periods=1).sum()   # 3-month rolling, so thin months don't whipsaw the shares
    totals = by.sum(axis=1)
    # watched supplier first, then the next largest, up to 4 named; rest = Other
    rank = by.sum().sort_values(ascending=False).index.tolist()
    named = [ev["watch"]] + [s for s in rank if s != ev["watch"]][:3]
    named = [s for s in named if s in by.columns]
    shares = by[named].div(totals.replace(0, np.nan), axis=0) * 100
    shares["Other"] = 100 - shares.sum(axis=1)
    qcol, unit, coverage = price_basis(sub, ev["series"])
    price_ok = coverage >= MIN_QTY_COVERAGE
    if price_ok:
        q = sub[sub[qcol].notna()]
        kg = q.groupby("date")[qcol].sum().reindex(months)
        val = q.groupby("date")["value_usd"].sum().reindex(months)
        line = val.rolling(3, min_periods=2).sum() / kg.rolling(3, min_periods=2).sum()
        line_label, line_title = f"{unit} (3-month)", "Average import price"
        u = unit.split(" per ")[1]
        fmt = (lambda v: f"${v:,.2f}/{u}" if v < 10 else f"${v:,.0f}/{u}")
    else:   # quantities mostly unreported: show what was spent instead of a misleading price
        line = sub.groupby("date")["value_usd"].sum().reindex(months).fillna(0) / 1e6
        line_label = "US$ million per month"
        line_title = (f"Monthly import value (no price: only {coverage:.0%} of value has a reported quantity)")
        fmt = (lambda v: f"${v:,.1f}M")

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7.2), sharex=True,
                                   gridspec_kw=dict(height_ratios=[1.35, 1], hspace=0.28))
    fig.patch.set_facecolor(SURF)
    colors = SLOT[:len(named)] + [OTHER]
    ax1.stackplot(shares.index, [shares[c].fillna(0) for c in shares.columns], colors=colors,
                  edgecolor=SURF, linewidth=0.8)
    ax1.set_ylim(0, 100)
    ax1.set_ylabel("Share of import value, %", color=INK2)
    imp = DISPLAY.get(ev["importer"], ev["importer"])
    ax1.set_title(f"{imp} imports: share by supplier (3-month rolling)", loc="left", color=INK, fontsize=11)
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in colors]
    ax1.legend(handles, [DISPLAY.get(c, c) for c in shares.columns], loc="upper left", bbox_to_anchor=(1.0, 1.0), frameon=False,
               labelcolor=INK2, fontsize=9)

    ax2.plot(line.index, line.values, color=SLOT[0], linewidth=2)
    ax2.set_ylabel(line_label, color=INK2)
    ax2.set_title(line_title, loc="left", color=INK, fontsize=11)
    ax2.set_ylim(bottom=0)
    last = line.dropna()
    if len(last):
        v = last.iloc[-1]
        ax2.annotate(fmt(v), (last.index[-1], last.iloc[-1]), xytext=(6, 0),
                     textcoords="offset points", va="center", color=INK, fontsize=9)

    for ax in (ax1, ax2):
        ax.set_facecolor(SURF)
        ax.axvline(shock, color=INK, linewidth=1, linestyle=(0, (4, 3)))
        ax.grid(axis="y", color=GRID, linewidth=0.8)
        ax.tick_params(colors=INK2, labelsize=9)
        for s in ax.spines.values():
            s.set_visible(False)
    ax1.text(shock, 3, f" {shock:%b %Y}", color=INK, fontsize=9, va="bottom", ha="left",
             bbox=dict(facecolor=SURF, edgecolor="none", pad=1.5))
    ax2.xaxis.set_major_locator(mdates.YearLocator())
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.suptitle(ev["title"], x=0.06, ha="left", fontsize=14, color=INK, y=0.985)
    fig.text(0.06, 0.012, ev["note"] + "  Source: UN Comtrade monthly imports.", fontsize=8.5, color=INK2)
    fig.subplots_adjust(left=0.08, right=0.82, top=0.88, bottom=0.08)
    out = FIGS / f"event_{ev['key']}.png"
    fig.savefig(out, dpi=150, facecolor=SURF)
    plt.close(fig)
    return out


def main():
    df = classify_gases(load_raw())
    df.to_csv(PROC / "imports_classified.csv", index=False)
    gas = df[df["material"] == "helium"]
    split = gas.groupby("series")["value_usd"].sum() / gas["value_usd"].sum() * 100
    flagged = gas.loc[gas["gas_flag"] != "", "value_usd"].sum() / gas["value_usd"].sum() * 100
    print("HS 2804.29 split by import value:", ", ".join(f"{k} {v:.0f}%" for k, v in split.items()),
          f"(flagged as unsure: {flagged:.0f}%)")

    rows = []
    for ev in EVENTS:
        sub, months = event_frame(df, ev)
        if sub.empty:
            print(f"{ev['key']}: no data in window")
            continue
        rows.append(summarize(sub, ev))
        print(f"Saved chart: {plot_event(sub, months, ev)}")
    summary = pd.DataFrame(rows)
    summary.to_csv(PROC / "event_study_summary.csv", index=False)
    cols = ["event", "importer", "watched_supplier", "pre_watch_share", "post_watch_share",
            "price_unit", "change_unit_price_pct", "change_qty_per_month_pct", "post_months"]
    print("\n12 months before vs. after each shock:")
    print(summary[cols].to_string(index=False, formatters={
        "pre_watch_share": "{:.0%}".format, "post_watch_share": "{:.0%}".format,
        "change_unit_price_pct": "{:+.0f}%".format, "change_qty_per_month_pct": "{:+.0f}%".format}))


if __name__ == "__main__":
    main()
