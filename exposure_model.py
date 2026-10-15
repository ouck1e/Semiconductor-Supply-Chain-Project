"""
Phase 8, step 3: the exposure matrix. How much each chip company depends on each supplier country for helium,
neon (rare gases), hydrogen fluoride and gallium, and whether that exposure explains stock reactions to shocks.

  exposure(company, input, supplier, year) = sum over fab countries k of
        capacity_share(company, k) x import_share(k, input, supplier, year)

  * capacity shares: data/reference/fab_footprint.csv (sourced, with confidence); chip designers inherit their
    foundries' footprint via data/reference/foundry_mix.csv
  * import shares: phase-1/extra Comtrade imports by value, latest year each country has reported (<= the year
    asked for); Taiwan from partners' exports (data/raw_mirror, built by fetch_trade_extra.py)
  * coverage = share of the company's capacity in countries with trade data. Exposure is reported as measured
    (a lower bound) and scaled to full coverage.

Writes  data/processed/exposure_matrix.csv        every company x input x supplier x year
        data/processed/exposure_key_risks.csv     the supplier risks behind the four shocks, latest year
        data/processed/exposure_event_test.csv    stock reaction vs exposure for each shock
        figures/exposure_heatmap.png, exposure_qatar_helium.png, exposure_vs_reaction.png

Run:  python exposure_model.py     (no internet needed)
"""
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats

import phase2_event_study as p2
import phase8_market_models as m8

ROOT = Path(__file__).resolve().parent
REF = ROOT / "data" / "reference"
PROC = ROOT / "data" / "processed"
FIGS = ROOT / "figures"
INK, INK2, GRID, SURF, SLOT = m8.INK, m8.INK2, m8.GRID, m8.SURF, m8.SLOT

# fab-footprint country -> Comtrade importer name
IMPORTER = {"South Korea": "Rep. of Korea", "United States": "USA", "Taiwan": "Taiwan (mirror)", "China": "China",
            "Japan": "Japan", "Singapore": "Singapore", "Germany": "Germany", "Ireland": "Ireland",
            "Israel": "Israel", "Malaysia": "Malaysia"}
INPUTS = {"helium": "Helium", "rare gas": "Neon & rare gases", "hf": "Hydrogen fluoride", "gallium": "Gallium (minor-metal code)"}
KEY_RISKS = [("helium", "Qatar"), ("helium", "USA"), ("helium", "Russian Federation"),
             ("rare gas", "Ukraine"), ("rare gas", "Russian Federation"), ("rare gas", "China"),
             ("hf", "China"), ("hf", "Japan"), ("gallium", "China")]
SUPPLIER_LABEL = {"USA": "US", "Russian Federation": "Russia", "Rep. of Korea": "Korea", "Other Asia, nes": "Taiwan"}

# shock tests: which exposure, measured in which year (the last full year before the shock)
TESTS = [
    dict(key="hf_2019", label="HF 2019: exposure to Japanese HF (2018)", year=2018,
         risks=[("hf", "Japan")], date="2019-07-01"),
    dict(key="neon_2022", label="Neon 2022: exposure to Ukrainian + Russian rare gases (2021)", year=2021,
         risks=[("rare gas", "Ukraine"), ("rare gas", "Russian Federation")], date="2022-02-24"),
    dict(key="helium_2026", label="Helium 2026: exposure to Qatari helium (2025)", year=2025,
         risks=[("helium", "Qatar")], date="2026-03-02"),
]


# ---------------------------------------------------------------- trade shares
def load_trade():
    df = p2.load_raw()
    mdir = ROOT / "data" / "raw_mirror"
    if mdir.exists() and any(mdir.glob("*.csv")):
        frames = []
        for f in sorted(mdir.glob("*.csv")):
            d = pd.read_csv(f)
            d = d[d["partnerCode"] != 0].copy()
            d["material"] = f.stem.rsplit("_", 1)[0]
            frames.append(d)
        raw = pd.concat(frames, ignore_index=True)
        for c in ("isNetWgtEstimated", "isQtyEstimated"):
            if c not in raw:
                raw[c] = False
        mir = pd.DataFrame({
            "date": pd.to_datetime(raw["period"].astype(str), format="%Y%m"), "material": raw["material"],
            "importer": raw["reporterDesc"], "supplier": raw["partnerDesc"], "value_usd": raw["primaryValue"],
            "net_kg": raw["netWgt"].where(raw["netWgt"] > 0),
            "net_kg_reported": raw["netWgt"].where((raw["netWgt"] > 0) & ~raw["isNetWgtEstimated"].astype(bool)),
            "qty_m3_reported": np.nan})
        mir["usd_per_kg"] = mir["value_usd"] / mir["net_kg"]
        df = pd.concat([df, mir], ignore_index=True)
    df = p2.classify_gases(df)
    df["year"] = df["date"].dt.year
    # full years only: a country's year counts once it has 12 reported months
    months = df.groupby(["importer", "series", "year"])["date"].nunique()
    full = months[months >= 12].reset_index()[["importer", "series", "year"]]
    df = df.merge(full, on=["importer", "series", "year"])
    sh = df.groupby(["importer", "series", "year", "supplier"])["value_usd"].sum().reset_index()
    sh["share"] = sh["value_usd"] / sh.groupby(["importer", "series", "year"])["value_usd"].transform("sum")
    # Published shares replace mirror data where a big supplier doesn't report to Comtrade (Qatar doesn't report
    # monthly, so Taiwan's rebuilt helium imports miss it entirely). Mirror rows for that importer and input are
    # dropped for every year, so only the sourced year is used.
    ov_f = REF / "trade_overrides.csv"
    if ov_f.exists():
        ov = pd.read_csv(ov_f)
        drop = set(zip(ov.importer, ov.series))
        sh = sh[[(i, s) not in drop for i, s in zip(sh.importer, sh.series)]]
        sh = pd.concat([sh, ov[["importer", "series", "year", "supplier", "share"]].assign(value_usd=np.nan)],
                       ignore_index=True)
    return sh


def shares_asof(sh, year):
    """Each importer/series at the latest full year <= year."""
    s = sh[sh.year <= year]
    last = s.groupby(["importer", "series"])["year"].max().rename("data_year").reset_index()
    s = s.merge(last, on=["importer", "series"])
    return s[s["year"] == s["data_year"]]


# ---------------------------------------------------------------- footprints
def footprints():
    fab = pd.read_csv(REF / "fab_footprint.csv")
    mix = pd.read_csv(REF / "foundry_mix.csv")
    rows = fab[["company", "ticker", "country", "capacity_share"]].rename(columns={"capacity_share": "w"})
    via = mix.merge(fab[["ticker", "country", "capacity_share"]].rename(columns={"ticker": "foundry_ticker"}),
                    on="foundry_ticker")
    via["w"] = via["share"] * via["capacity_share"]
    via = via.groupby(["company", "ticker", "country"], as_index=False)["w"].sum()
    out = pd.concat([rows, via], ignore_index=True)
    out["importer"] = out["country"].map(IMPORTER)
    return out


def exposure(sh, fp, year):
    s = shares_asof(sh, year)
    rows = []
    for (comp, tick), f in fp.groupby(["company", "ticker"]):
        for series in INPUTS:
            ss = s[s.series == series]
            have = set(ss.importer)
            cov = f.loc[f.importer.isin(have), "w"].sum()
            m = f.merge(ss, on="importer")
            m["e"] = m["w"] * m["share"]
            e = m.groupby("supplier")["e"].sum()
            asof = ";".join(sorted({f"{r.importer}:{r.data_year}" for r in m[["importer", "data_year"]].drop_duplicates().itertuples()}))
            for sup, val in e.items():
                rows.append(dict(company=comp, ticker=tick, year=year, input=series, supplier=sup,
                                 exposure=val, coverage=cov, exposure_full=val / cov if cov else np.nan,
                                 data_years=asof))
            if e.empty:
                rows.append(dict(company=comp, ticker=tick, year=year, input=series, supplier="(no data)",
                                 exposure=np.nan, coverage=cov, exposure_full=np.nan, data_years=""))
    return pd.DataFrame(rows)


def key_value(E, comp, series, supplier, col="exposure_full"):
    """Exposure to one supplier; 0 if the company's countries import none from it, NaN if no trade data at all."""
    cov = E[(E.company == comp) & (E.input == series)]["coverage"]
    if cov.empty or cov.max() == 0:
        return np.nan
    r = E[(E.company == comp) & (E.input == series) & (E.supplier == supplier)]
    return float(r[col].iloc[0]) if len(r) else 0.0


# ---------------------------------------------------------------- figures
def style(ax, grid="x"):
    m8.style(ax, grid)


ORDER = ["TSMC", "Samsung Electronics", "SK hynix", "Micron", "Intel", "GlobalFoundries", "SMIC", "UMC",
         "Nvidia", "AMD", "Qualcomm", "MediaTek"]


def fig_heatmap(E, year):
    short = {"helium": "Helium", "rare gas": "Rare gases", "hf": "HF", "gallium": "Gallium"}
    cols = [f"{short[s]}\n{SUPPLIER_LABEL.get(sup, sup)}" for s, sup in KEY_RISKS]
    M = np.nan_to_num(np.array([[key_value(E, c, s, sup) for s, sup in KEY_RISKS] for c in ORDER]))
    cov = np.array([[E[(E.company == c) & (E.input == s)]["coverage"].max() if len(E[(E.company == c) & (E.input == s)]) else 0
                     for s, _ in KEY_RISKS] for c in ORDER])
    fig, ax = plt.subplots(figsize=(11.5, 7.4))
    fig.patch.set_facecolor(SURF)
    im = ax.imshow(M * 100, cmap="Blues", vmin=0, vmax=max(60, np.nanmax(M) * 100), aspect="auto")
    for i in range(M.shape[0]):
        for j in range(M.shape[1]):
            v = M[i, j] * 100
            low = cov[i, j] < 0.5
            txt = "n/a" if cov[i, j] == 0 else f"{v:.0f}" + ("*" if low else "")
            ax.text(j, i, txt, ha="center", va="center", fontsize=8.5,
                    color="white" if v > 35 else (INK2 if cov[i, j] == 0 else INK))
    ax.set_xticks(range(len(cols)), cols, fontsize=8.5, color=INK)
    ax.set_yticks(range(len(ORDER)), ORDER, fontsize=9, color=INK)
    ax.axhline(7.5, color=SURF, lw=4)
    ax.tick_params(length=0)
    ax.xaxis.tick_top()
    for sp in ax.spines.values():
        sp.set_visible(False)
    cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
    cb.outline.set_visible(False)
    cb.ax.tick_params(labelsize=8, colors=INK2, length=0)
    cb.set_label("% of the company's supply of that input", color=INK2, fontsize=8.5)
    fig.suptitle(f"Who depends on whom: share of each company's input supply from each risky supplier ({year})",
                 x=0.02, ha="left", fontsize=12.5, color=INK)
    fig.text(0.02, 0.015, "Exposure = fab capacity share by country x that country's import share by supplier (Comtrade, by value), "
             "scaled to the capacity the trade data covers.\n* = trade data covers under half of the company's capacity. "
             "Chip designers (Nvidia, AMD, Qualcomm, MediaTek) inherit their foundries' exposure.", fontsize=8.5, color=INK2)
    fig.subplots_adjust(left=0.14, right=0.97, top=0.85, bottom=0.11)
    fig.savefig(FIGS / "exposure_heatmap.png", dpi=150, facecolor=SURF)
    plt.close(fig)


def fig_qatar(Es):
    fabs = ["Samsung Electronics", "SK hynix", "TSMC", "Micron", "Intel", "GlobalFoundries", "SMIC", "UMC"]
    covy = Es[Es.input == "helium"].groupby(["company", "year"])["coverage"].max()
    fig, ax = plt.subplots(figsize=(11, 5.6))
    fig.patch.set_facecolor(SURF)
    style(ax, grid="y")
    years = sorted(Es.year.unique())
    ends = []
    for i, c in enumerate(fabs):
        # plot a year only when trade data covers at least half the company's capacity that year
        ys = [key_value(Es[Es.year == y], c, "helium", "Qatar") * 100 if covy.get((c, y), 0) >= 0.5 else np.nan
              for y in years]
        if all(v != v for v in ys):
            continue
        ax.plot(years, ys, color=SLOT[i % len(SLOT)], lw=2, marker="o", ms=3.5)
        last = next(v for v in reversed(ys) if v == v)
        ends.append([last, c, SLOT[i % len(SLOT)]])
    ends.sort(key=lambda e: e[0])
    for k in range(1, len(ends)):
        ends[k][0] = max(ends[k][0], ends[k - 1][0] + 3.2)
    for y, c, col in ends:
        ax.annotate(c, (years[-1], y), xytext=(8, 0), textcoords="offset points", va="center", fontsize=8.5,
                    color=col, annotation_clip=False)
    for d, lab in m8.fp.SHOCKS:
        yr = int(d[:4])
        if years[0] <= yr <= years[-1]:
            ax.axvline(yr - 0.5 if lab.startswith("Helium") else yr, color=INK2, lw=0.8, ls=":")
    ax.set_ylabel("% of helium supply from Qatar", color=INK2, fontsize=9)
    ax.set_xticks(years)
    fig.suptitle("Chipmakers' reliance on Qatari helium roughly doubled from 2015 to 2025",
                 x=0.02, ha="left", fontsize=13, color=INK)
    fig.text(0.02, 0.015, "A year is shown only when trade data covers at least half the company's fab capacity (Taiwan: 2025 "
             "only, from Taiwan customs via Nikkei Asia).\nUS figures count imports only, not US-produced helium.",
             fontsize=8.5, color=INK2)
    fig.subplots_adjust(left=0.07, right=0.84, top=0.9, bottom=0.14)
    fig.savefig(FIGS / "exposure_qatar_helium.png", dpi=150, facecolor=SURF)
    plt.close(fig)


# ---------------------------------------------------------------- does exposure explain the reaction?
def event_test(sh, fp, usd, uni):
    country = dict(zip(uni.ticker, uni.country))
    tick = fp.drop_duplicates("ticker")[["company", "ticker"]]
    rows = []
    for t in TESTS:
        E = exposure(sh, fp, t["year"])
        for _, r in tick.iterrows():
            x = np.nansum([key_value(E, r.company, s, sup) for s, sup in t["risks"]])
            cov = E[(E.ticker == r.ticker) & (E.input == t["risks"][0][0])]["coverage"].max()
            for bench, mk in (("home market", m8.HOME_INDEX.get(country.get(r.ticker), "URTH")), ("world market", "URTH")):
                w = m8.event_window(m8.daily_ar(usd, r.ticker, mkt=mk), t["date"]) if r.ticker in usd else None
                if w is None:
                    continue
                ar, est = w
                rows.append(dict(event=t["key"], company=r.company, ticker=r.ticker, exposure=x, coverage=cov,
                                 benchmark=bench, car_0_5=100 * ar.loc[0:5].sum(), car_0_20=100 * ar.loc[0:20].sum()))
    T = pd.DataFrame(rows)
    T.round(4).to_csv(PROC / "exposure_event_test.csv", index=False)

    # pooled test: all three shocks together, exposure standardized within each shock, event fixed effects
    pooled = []
    for bench in ("home market", "world market"):
        for win in ("car_0_5", "car_0_20"):
            d = T[(T.benchmark == bench) & (T.coverage >= 0.5)].copy()
            d["z"] = d.groupby("event")["exposure"].transform(lambda x: (x - x.mean()) / x.std(ddof=0))
            d["y"] = d[win] - d.groupby("event")[win].transform("mean")
            d = d.dropna(subset=["z"])
            b, a, r, p, se = stats.linregress(d["z"], d["y"])
            pooled.append(dict(benchmark=bench, window=win.replace("car_", "days "), n=len(d), events=d.event.nunique(),
                               slope_pct_per_sd=b, se=se, p=p))
    pd.DataFrame(pooled).round(4).to_csv(PROC / "exposure_pooled_test.csv", index=False)
    print("Pooled test across shocks (CAR on exposure z-score, event fixed effects):")
    print(pd.DataFrame(pooled).round(3).to_string(index=False))

    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.9))
    fig.patch.set_facecolor(SURF)
    summ = []
    for ax, t in zip(axes, TESTS):
        style(ax, grid="both")
        d = T[(T.event == t["key"]) & (T.benchmark == "home market") & (T.coverage >= 0.5)]
        x, y = 100 * d.exposure.values, d.car_0_5.values
        ax.scatter(x, y, s=46, color=SLOT[0], edgecolor=SURF, lw=1.5, zorder=3)
        # label placement: a point whose right-hand neighbour sits close by gets its label on the left / below
        xr, yr = max(np.ptp(x), 1), max(np.ptp(y), 1)
        for i, (xi, yi, n) in enumerate(zip(x, y, d.company)):
            crowded = any(j != i and 0 <= x[j] - xi < 0.08 * xr and abs(y[j] - yi) < 0.06 * yr
                          and (x[j] > xi or j > i) for j in range(len(x)))
            off, ha = ((-5, -9), "right") if crowded else ((4, 3), "left")
            ax.annotate(n, (xi, yi), xytext=off, textcoords="offset points", fontsize=7.5, color=INK2, ha=ha)
        sub = ""
        if len(d) >= 4 and np.ptp(x) > 0:
            b, a, r, p, se = stats.linregress(x, y)
            rho, prho = stats.spearmanr(x, y)
            xx = np.linspace(x.min(), x.max(), 10)
            ax.plot(xx, a + b * xx, color=SLOT[1], lw=1.5)
            sub = f"\nslope {b:+.2f} pp per 1 pp exposure, p = {p:.2f}, n = {len(d)}"
            summ.append(dict(event=t["key"], n=len(d), slope=b, p=p, spearman=rho, p_spearman=prho))
        ax.axhline(0, color=INK2, lw=0.8)
        ax.margins(x=0.18, y=0.1)
        ax.set_title(t["label"] + sub, loc="left", fontsize=9.5, color=INK, linespacing=1.5)
        ax.set_xlabel("Exposure, % of input supply from that supplier", color=INK2, fontsize=8.5)
    axes[0].set_ylabel("Abnormal return vs home market, days 0-5, %", color=INK2, fontsize=8.5)
    fig.suptitle("Did more-exposed companies fall more? Exposure vs. stock reaction, measured against each home market",
                 x=0.02, ha="left", fontsize=12.5, color=INK)
    fig.text(0.02, 0.015, "Chipmakers and chip designers whose trade data covers at least half their capacity. "
             "A negative slope would mean the market priced supply exposure.", fontsize=8.5, color=INK2)
    fig.subplots_adjust(left=0.06, right=0.98, top=0.8, bottom=0.17, wspace=0.22)
    fig.savefig(FIGS / "exposure_vs_reaction.png", dpi=150, facecolor=SURF)
    plt.close(fig)
    return T, pd.DataFrame(summ)


def main():
    sh = load_trade()
    fp = footprints()
    years = list(range(2015, 2026))
    Es = pd.concat([exposure(sh, fp, y) for y in years], ignore_index=True)
    Es.round(5).to_csv(PROC / "exposure_matrix.csv", index=False)
    latest = Es[Es.year == years[-1]]
    key = pd.DataFrame([dict(company=c, input=s, supplier=sup,
                             exposure_measured=key_value(latest, c, s, sup, "exposure"),
                             exposure_full=key_value(latest, c, s, sup),
                             coverage=latest[(latest.company == c) & (latest.input == s)]["coverage"].max())
                        for c in ORDER for s, sup in KEY_RISKS])
    key.round(4).to_csv(PROC / "exposure_key_risks.csv", index=False)
    fig_heatmap(latest, years[-1])
    fig_qatar(Es)

    usd, uni, _ = m8.load()
    T, summ = event_test(sh, fp, usd, uni)

    pd.set_option("display.width", 220)
    print("Importers with trade data:", ", ".join(sorted(sh.importer.unique())))
    print(f"\nKey supplier exposure, {years[-1]} (scaled to coverage; coverage = share of capacity with trade data)")
    piv = key.pivot_table(index="company", columns=["input", "supplier"], values="exposure_full").loc[ORDER]
    print((100 * piv).round(0).to_string())
    print("\nCoverage by company and input:")
    print(key.pivot_table(index="company", columns="input", values="coverage").loc[ORDER].round(2).to_string())
    print("\nExposure vs reaction (home-market benchmark, days 0-5):")
    print(summ.round(3).to_string(index=False))
    print(T[T.benchmark == "home market"].round(2).to_string(index=False))


if __name__ == "__main__":
    main()
