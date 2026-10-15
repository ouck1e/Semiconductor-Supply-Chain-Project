"""
Phase 8: what the stock data says about the chip supply chain. Four models, all in US dollars.

  Model 1  Return decomposition: did chip stocks beat the market, or just carry more risk?
           Weekly Fama-French 5-factor regressions (developed markets): alpha, market beta, R².
           Plus up-market and down-market beta to the chip sector (who falls less when chips fall).
  Model 2  What moves each stock: share of weekly return variance from the world market, the chip sector,
           the home stock market, and company-specific news.
  Model 3  Clusters: which stocks move together once the world market is taken out.
  Model 4  Event study of the four supply shocks (HF 2019, neon 2022, gallium 2023, helium 2026):
           abnormal returns of the companies expected to lose and to win, fixed in advance.

Reads   data/market/market.db                       (fetch_prices.py)
Writes  data/market/model1_factor_regressions.csv, model2_variance_shares.csv, model3_clusters.csv,
        model4_event_study.csv, model4_event_paths.csv
        figures/m1_alpha.png, m1_defensive.png, m2_drivers.png, m3_clusters.png, m4_shocks.png

Run:  python phase8_market_models.py      (no internet needed)
"""
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats
from scipy.cluster.hierarchy import linkage, dendrogram, fcluster
from scipy.spatial.distance import squareform

import fetch_prices as fp

ROOT = Path(__file__).resolve().parent
MKT = ROOT / "data" / "market"
FIGS = ROOT / "figures"
INK, INK2, GRID, SURF, MUTED = fp.INK, fp.INK2, fp.GRID, fp.SURF, "#b9b8b3"
SLOT = fp.SLOT
GROUPS = ["Foundries & memory", "Equipment", "Chip designers", "Gases & materials", "Rare earths"]
GCOL = dict(zip(GROUPS, SLOT))
HOME_INDEX = {"Taiwan": "^TWII", "South Korea": "^KS11", "Japan": "^N225", "China": "^HSI", "United States": "^GSPC"}


# ---------------------------------------------------------------- data
def load():
    wide, uni, fx = fp.load(MKT / "market.db")
    usd = fp.to_usd(wide, uni, fx)
    con = sqlite3.connect(MKT / "market.db")
    ff = pd.read_sql("SELECT * FROM factors_developed", con, parse_dates=["date"]).set_index("date")
    con.close()
    return usd, uni, ff


def weekly(usd, ff):
    w = np.log(usd.resample("W-FRI").last()).diff()
    fw = np.log1p(ff).resample("W-FRI").sum()          # compound daily factors into weeks
    fw = fw[fw.index <= ff.index.max()]
    return w, fw


def ols(y, X):
    """OLS with Newey-West (4-lag) standard errors. Returns coef, se, r2."""
    X = np.column_stack([np.ones(len(X)), X])
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    e = y - X @ b
    n, k = X.shape
    XtXi = np.linalg.inv(X.T @ X)
    S = (X * e[:, None]).T @ (X * e[:, None])
    for L in range(1, 5):
        w = 1 - L / 5
        G = (X[L:] * e[L:, None]).T @ (X[:-L] * e[:-L, None])
        S += w * (G + G.T)
    V = XtXi @ S @ XtXi * n / (n - k)
    r2 = 1 - e.var() / y.var()
    return b, np.sqrt(np.diag(V)), r2


def style(ax, grid="x"):
    ax.set_facecolor(SURF)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=8.5, length=0)
    ax.grid(axis=grid, color=GRID, lw=0.8)
    ax.set_axisbelow(True)


def companies(uni):
    return uni[uni.group != "Benchmark"].reset_index(drop=True)


# ---------------------------------------------------------------- model 1
def model1(w, fw, uni):
    rows = []
    cols = ["mkt_rf", "smb", "hml", "rmw", "cma"]
    for _, u in pd.concat([companies(uni), uni[uni.ticker.isin(["SOXX", "^GSPC"])]]).iterrows():
        t = u.ticker
        d = pd.concat([w[t], fw], axis=1, join="inner").dropna()
        if len(d) < 100:
            continue
        y = d[t].values - d["rf"].values
        b, se, r2 = ols(y, d[cols].values)
        b1, se1, r21 = ols(y, d[["mkt_rf"]].values)
        s = pd.concat([w[t], w["SOXX"]], axis=1).dropna()
        up, dn = s[s["SOXX"] > 0], s[s["SOXX"] < 0]
        beta_up = np.polyfit(up["SOXX"], up[t], 1)[0] if t != "SOXX" else 1.0
        beta_dn = np.polyfit(dn["SOXX"], dn[t], 1)[0] if t != "SOXX" else 1.0
        rows.append(dict(
            ticker=t, name=u["name"], group=u["group"], weeks=len(d),
            alpha_ff5_pct_yr=100 * 52 * b[0], alpha_ff5_se=100 * 52 * se[0], alpha_ff5_t=b[0] / se[0],
            beta_mkt=b[1], beta_smb=b[2], beta_hml=b[3], beta_rmw=b[4], beta_cma=b[5], r2_ff5=r2,
            alpha_capm_pct_yr=100 * 52 * b1[0], alpha_capm_t=b1[0] / se1[0], beta_capm=b1[1],
            beta_up_soxx=beta_up, beta_down_soxx=beta_dn,
        ))
    m1 = pd.DataFrame(rows)
    m1.round(4).to_csv(MKT / "model1_factor_regressions.csv", index=False)

    # figure A: alpha with 95% CI, by group
    c = m1[m1.group.isin(GROUPS)].copy()
    c["g"] = c.group.map({g: i for i, g in enumerate(GROUPS)})
    c = c.sort_values(["g", "alpha_ff5_pct_yr"], ascending=[False, True])
    bench = m1[m1.ticker.isin(["SOXX", "^GSPC"])].set_index("ticker")
    fig, ax = plt.subplots(figsize=(10, 9.2))
    fig.patch.set_facecolor(SURF)
    style(ax)
    y = np.arange(len(c))
    gap = c.g.diff().fillna(0).ne(0).cumsum().values * 0.8
    yy = y + gap
    for yi, (_, r) in zip(yy, c.iterrows()):
        lo, hi = r.alpha_ff5_pct_yr - 1.96 * r.alpha_ff5_se, r.alpha_ff5_pct_yr + 1.96 * r.alpha_ff5_se
        sig = lo > 0 or hi < 0
        col = GCOL[r.group]
        ax.plot([lo, hi], [yi, yi], color=col, lw=2, alpha=0.9 if sig else 0.35, solid_capstyle="round")
        ax.scatter([r.alpha_ff5_pct_yr], [yi], s=46, color=col if sig else SURF, edgecolor=col, lw=1.6, zorder=3)
    ax.axvline(0, color=INK2, lw=1)
    sx = bench.loc["SOXX"]
    ax.axvline(sx.alpha_ff5_pct_yr, color=INK2, lw=1, ls="--")
    ax.annotate(f"Chip ETF (SOXX) {sx.alpha_ff5_pct_yr:+.0f}%/yr", (sx.alpha_ff5_pct_yr, yy.max() + 1.2),
                ha="center", fontsize=8.5, color=INK2, annotation_clip=False)
    ax.set_yticks(yy, c["name"], fontsize=9, color=INK)
    for g in GROUPS:
        ys = yy[c.group.values == g]
        if len(ys):
            ax.text(1.01, ys.mean(), g, transform=ax.get_yaxis_transform(), fontsize=9, color=GCOL[g],
                    va="center", weight="bold")
    ax.set_xlabel("Alpha: yearly return the market and style factors don't explain, % per year (95% range)",
                  color=INK2, fontsize=9)
    fig.suptitle("Beyond market risk, only TSMC, Nvidia and AMD clearly earned extra return; the rest is too noisy to call",
                 x=0.02, ha="left", fontsize=13, color=INK)
    fig.text(0.02, 0.012, "Weekly US-dollar returns, Jan 2015 to Aug 2026, regressed on the Fama-French developed-market "
             "5 factors. Filled dot = range excludes zero.", fontsize=8.5, color=INK2)
    fig.subplots_adjust(left=0.2, right=0.8, top=0.93, bottom=0.08)
    fig.savefig(FIGS / "m1_alpha.png", dpi=150, facecolor=SURF)
    plt.close(fig)

    # figure B: up vs down beta to chip sector
    fig, ax = plt.subplots(figsize=(9.5, 7.2))
    fig.patch.set_facecolor(SURF)
    style(ax, grid="both")
    lim = (0, max(1.6, m1[["beta_up_soxx", "beta_down_soxx"]].max().max() + 0.1))
    ax.plot(lim, lim, color=MUTED, lw=1, ls="--")
    ax.text(lim[1] * 0.97, lim[1] * 0.9, "falls as much as it rises", rotation=38, ha="right", fontsize=8, color=INK2)
    for _, r in c.iterrows():
        ax.scatter(r.beta_up_soxx, r.beta_down_soxx, s=60, color=GCOL[r.group], edgecolor=SURF, lw=1.5, zorder=3)
        off = {"Qualcomm": (-48, -10), "Intel": (-10, -12), "Air Products": (5, -9), "Samsung Electronics": (6, 5), "Nippon Sanso": (-70, 4), "TSMC": (6, -3),
               "SMIC": (-26, 3)}.get(r["name"], (5, 3))
        ax.annotate(r["name"], (r.beta_up_soxx, r.beta_down_soxx), xytext=off, textcoords="offset points",
                    fontsize=7.5, color=INK2)
    ax.set_xlim(*lim)
    ax.set_ylim(*lim)
    ax.set_xlabel("Up-market beta: move per 1% weekly RISE in the chip ETF", color=INK2, fontsize=9)
    ax.set_ylabel("Down-market beta: move per 1% weekly FALL in the chip ETF", color=INK2, fontsize=9)
    for g in GROUPS:
        ax.scatter([], [], color=GCOL[g], label=g, s=40)
    ax.legend(frameon=False, fontsize=8.5, loc="upper left", labelcolor=INK2)
    fig.suptitle("Gas suppliers barely follow chip sell-offs; toolmakers and memory amplify them",
                 x=0.02, ha="left", fontsize=13, color=INK)
    fig.text(0.02, 0.012, "Betas from weekly US-dollar returns, 2015-2026, split by whether the iShares Semiconductor "
             "ETF rose or fell that week. Below the dashed line = cushions falls.", fontsize=8.5, color=INK2)
    fig.subplots_adjust(left=0.1, right=0.97, top=0.92, bottom=0.11)
    fig.savefig(FIGS / "m1_defensive.png", dpi=150, facecolor=SURF)
    plt.close(fig)
    return m1


# ---------------------------------------------------------------- model 2
def resid(y, X):
    X = np.column_stack([np.ones(len(X)), X])
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    return y - X @ b


def model2(w, uni):
    rows = []
    world, chip = "URTH", "SOXX"
    for _, u in companies(uni).iterrows():
        t = u.ticker
        home = HOME_INDEX.get(u.country)
        cols = [t, world, chip] + ([home] if home else [])
        d = w[cols].dropna()
        y = d[t].values
        W = d[world].values
        C = resid(d[chip].values, W[:, None])                      # chip sector beyond the world market
        parts = [W[:, None], C[:, None]]
        if home:
            H = resid(d[home].values, np.column_stack([W, C]))      # home market beyond world and chips
            parts.append(H[:, None])
        tot = y.var()
        r2 = []
        for k in range(1, len(parts) + 1):
            r2.append(1 - resid(y, np.column_stack(parts[:k])).var() / tot)
        world_s = r2[0]
        chip_s = r2[1] - r2[0]
        home_s = (r2[2] - r2[1]) if home else 0.0
        rows.append(dict(ticker=t, name=u["name"], group=u["group"], country=u.country, home_index=home or "",
                         world_market=world_s, chip_sector=chip_s, home_market=home_s,
                         company_specific=1 - world_s - chip_s - home_s, weeks=len(d)))
    m2 = pd.DataFrame(rows)
    m2.round(4).to_csv(MKT / "model2_variance_shares.csv", index=False)

    c = m2.copy()
    c["g"] = c.group.map({g: i for i, g in enumerate(GROUPS)})
    c = c.sort_values(["g", "company_specific"], ascending=[False, False])
    parts = [("world_market", "World stock market", SLOT[0]), ("chip_sector", "Chip sector", SLOT[1]),
             ("home_market", "Home stock market", SLOT[2]), ("company_specific", "Company-specific", "#d9d8d3")]
    fig, ax = plt.subplots(figsize=(10.5, 9.2))
    fig.patch.set_facecolor(SURF)
    style(ax)
    gap = c.g.diff().fillna(0).ne(0).cumsum().values * 0.8
    yy = np.arange(len(c)) + gap
    left = np.zeros(len(c))
    for key, lab, col in parts:
        v = 100 * c[key].clip(lower=0).values
        ax.barh(yy, v, left=left, color=col, height=0.72, edgecolor=SURF, lw=1.5, label=lab)
        for yi, l, val in zip(yy, left, v):
            if val >= 9:
                ax.text(l + val / 2, yi, f"{val:.0f}", ha="center", va="center", fontsize=7.5,
                        color="white" if key != "company_specific" else INK2)
        left += v
    ax.set_yticks(yy, c["name"], fontsize=9, color=INK)
    for g in GROUPS:
        ys = yy[c.group.values == g]
        ax.text(1.01, ys.mean(), g, transform=ax.get_yaxis_transform(), fontsize=9, color=GCOL[g], va="center",
                weight="bold")
    ax.set_xlim(0, 100)
    ax.set_xlabel("Share of weekly return variance, %", color=INK2, fontsize=9)
    ax.legend(frameon=False, ncol=4, fontsize=8.5, loc="lower left", bbox_to_anchor=(0, 1.0), labelcolor=INK2)
    fig.suptitle("What moves each stock: toolmakers ride the chip cycle; SMIC, rare earths and gases follow their own news",
                 x=0.02, ha="left", fontsize=12, color=INK)
    fig.text(0.02, 0.012, "Weekly US-dollar returns 2015-2026. Each driver counts only what the ones before it don't explain.\n"
             "World: MSCI World ETF. Chips: SOXX. Home: KOSPI, TAIEX, Nikkei, Hang Seng or S&P 500 (none for ASML, "
             "Air Liquide, Lynas).", fontsize=8.5, color=INK2)
    fig.subplots_adjust(left=0.2, right=0.8, top=0.9, bottom=0.1)
    fig.savefig(FIGS / "m2_drivers.png", dpi=150, facecolor=SURF)
    plt.close(fig)
    return m2


# ---------------------------------------------------------------- model 3
def model3(w, uni, k=6):
    comp = companies(uni)
    tick = [t for t in comp.ticker if w[t].notna().sum() > 150]
    d = w[tick + ["URTH"]]
    res = pd.DataFrame(index=d.index)
    for t in tick:
        dd = d[[t, "URTH"]].dropna()
        res.loc[dd.index, t] = resid(dd[t].values, dd[["URTH"]].values)
    C = res.corr(min_periods=100).fillna(0)
    D = 1 - C.values
    np.fill_diagonal(D, 0)
    Z = linkage(squareform(D, checks=False), method="average")
    lab = fcluster(Z, k, criterion="maxclust")
    names = comp.set_index("ticker").loc[tick, "name"].values
    groups = comp.set_index("ticker").loc[tick, "group"].values
    out = pd.DataFrame(dict(ticker=tick, name=names, group=groups, cluster=lab))
    # most typical partner for each stock
    out["closest"] = [names[np.argsort(-C.values[i] + (np.arange(len(tick)) == i) * 9)[0]] for i in range(len(tick))]
    out["closest_corr"] = [np.sort(C.values[i])[-2] for i in range(len(tick))]
    out.round(3).to_csv(MKT / "model3_clusters.csv", index=False)

    fig, ax = plt.subplots(figsize=(10.5, 8.6))
    fig.patch.set_facecolor(SURF)
    ax.set_facecolor(SURF)
    dn = dendrogram(Z, labels=list(names), orientation="right", color_threshold=0, above_threshold_color=INK2,
                    ax=ax, leaf_font_size=9)
    gmap = dict(zip(names, groups))
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(length=0, colors=INK2, labelsize=8.5)
    ax.tick_params(axis="y", labelsize=9.5)
    fig.canvas.draw()
    for tl in ax.get_yticklabels():
        tl.set_color(GCOL[gmap[tl.get_text()]])
    ax.set_xlabel("Distance = 1 − correlation after removing the world market (shorter branch = move more alike)",
                  color=INK2, fontsize=9)
    ax.grid(axis="x", color=GRID, lw=0.8)
    for g in GROUPS:
        ax.scatter([], [], color=GCOL[g], label=g, s=40)
    ax.legend(frameon=False, fontsize=8.5, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=5, labelcolor=INK2)
    fig.suptitle("Stocks cluster by business and by country: US toolmakers, Korean memory, Taiwan, Japan, gases",
                 x=0.02, ha="left", fontsize=12.5, color=INK)
    fig.text(0.02, 0.012, "Hierarchical clustering (average linkage) of weekly US-dollar returns, 2015-2026, after "
             "subtracting each stock's link to the MSCI World ETF.", fontsize=8.5, color=INK2)
    fig.subplots_adjust(left=0.2, right=0.97, top=0.9, bottom=0.09)
    fig.savefig(FIGS / "m3_clusters.png", dpi=150, facecolor=SURF)
    plt.close(fig)
    return out, C


# ---------------------------------------------------------------- model 4
# Hypotheses fixed before looking at returns: who should lose (exposed) and who could win from each shock.
EVENTS = [
    dict(key="hf_2019", label="HF 2019: Japan curbs HF and photoresist exports to Korea", date="2019-07-01",
         exposed=["005930.KS", "000660.KS"], winners=[],
         note="exposed = Korean fabs that bought Japanese HF"),
    dict(key="neon_2022", label="Neon 2022: Russia invades Ukraine", date="2022-02-24",
         exposed=["2330.TW", "005930.KS", "000660.KS", "MU", "INTC", "GFS", "0981.HK", "2303.TW"],
         winners=["LIN", "APD", "AI.PA", "4091.T"],
         note="exposed = all fabs (laser neon); winners = industrial gas majors"),
    dict(key="gallium_2023", label="Gallium 2023: China licenses gallium and germanium exports", date="2023-07-03",
         exposed=[], winners=["MP", "LYC.AX"],
         note="winners = critical-mineral producers outside China"),
    dict(key="helium_2026", label="Helium 2026: Ras Laffan, Qatar offline", date="2026-03-02",
         exposed=["005930.KS", "000660.KS", "2330.TW", "2303.TW"], winners=["LIN", "APD", "AI.PA", "4091.T"],
         note="exposed = Korean and Taiwanese fabs (Qatar's largest chip customers); winners = gas majors"),
]
EST, PRE, POST = (-260, -31), 10, 20


def daily_ar(usd, t, mkt="URTH"):
    """Abnormal returns for stock t on its own trading days: market model with same-interval and lagged
    world-market returns (Dimson), which handles Asian markets closing before the US opens."""
    s = usd[t].dropna()
    m = usd[mkt].reindex(s.index.union(usd[mkt].dropna().index)).ffill().reindex(s.index)
    r = np.log(s).diff()
    rm = np.log(m).diff()
    return pd.DataFrame({"r": r, "m": rm, "m1": rm.shift(1)}).dropna()


def event_window(df, date):
    d0 = df.index.searchsorted(pd.Timestamp(date))
    if d0 + EST[0] < 0 or d0 >= len(df):
        return None
    est = df.iloc[d0 + EST[0]: d0 + EST[1] + 1]
    X = np.column_stack([np.ones(len(est)), est[["m", "m1"]].values])
    b, *_ = np.linalg.lstsq(X, est["r"].values, rcond=None)
    win = df.iloc[max(0, d0 - PRE): d0 + POST + 1]
    Xw = np.column_stack([np.ones(len(win)), win[["m", "m1"]].values])
    ar = pd.Series(win["r"].values - Xw @ b, index=np.arange(len(win)) - min(PRE, d0))
    ar_est = pd.Series(est["r"].values - X @ b, index=np.arange(EST[0], EST[0] + len(est)))
    return ar, ar_est


def portfolio(usd, tickers, date):
    """Equal-weight portfolio of abnormal returns in event time; its own estimation-window spread gives the
    standard error, which accounts for the stocks moving together on the same days."""
    ars, ests = [], []
    for t in tickers:
        if t not in usd:
            continue
        w = event_window(daily_ar(usd, t), date)
        if w is None:
            continue
        ars.append(w[0])
        ests.append(w[1])
    if not ars:
        return None
    AR = pd.concat(ars, axis=1).mean(axis=1)
    sd = pd.concat(ests, axis=1).mean(axis=1).std()
    return AR, sd, len(ars)


def car(AR, sd, a, b):
    seg = AR.loc[a:b]
    v = seg.sum()
    se = sd * np.sqrt(len(seg))
    return v, v / se


def model4(usd, uni):
    comp = companies(uni)
    allchip = [t for t in comp.ticker if t in usd]
    rows, paths = [], []
    for ev in EVENTS:
        rest = [t for t in allchip if t not in ev["exposed"] + ev["winners"]]
        for role, tick in (("Expected losers", ev["exposed"]), ("Expected winners", ev["winners"]),
                           ("Rest of chip universe", rest)):
            p = portfolio(usd, tick, ev["date"])
            if p is None:
                continue
            AR, sd, n = p
            row = dict(event=ev["key"], role=role, n_stocks=n, tickers=" ".join(tick))
            for a, b, name in ((-5, -1, "pre_5d"), (0, 1, "d0_1"), (0, 5, "d0_5"), (0, 20, "d0_20")):
                v, tt = car(AR, sd, a, b)
                row[f"car_{name}_pct"] = 100 * v
                row[f"t_{name}"] = tt
                row[f"p_{name}"] = 2 * (1 - stats.norm.cdf(abs(tt)))
            rows.append(row)
            cum = AR.loc[-5:].cumsum() - AR.loc[-5:-6].sum()
            paths.append(pd.DataFrame(dict(event=ev["key"], role=role, day=cum.index, car_pct=100 * cum.values,
                                           band_pct=100 * 1.96 * sd * np.sqrt(np.arange(1, len(cum) + 1)))))
        # each stock individually, for the write-up
        for t in ev["exposed"] + ev["winners"]:
            w = event_window(daily_ar(usd, t), ev["date"]) if t in usd else None
            if w is None:
                continue
            ar, ar_est = w
            v, tt = car(ar, ar_est.std(), 0, 5)
            v20, tt20 = car(ar, ar_est.std(), 0, 20)
            rows.append(dict(event=ev["key"], role="stock: " + comp.set_index("ticker").loc[t, "name"], n_stocks=1,
                             tickers=t, car_d0_5_pct=100 * v, t_d0_5=tt, car_d0_20_pct=100 * v20, t_d0_20=tt20))
    m4 = pd.DataFrame(rows)
    m4.round(4).to_csv(MKT / "model4_event_study.csv", index=False)
    P = pd.concat(paths)
    P.round(4).to_csv(MKT / "model4_event_paths.csv", index=False)

    col = {"Expected losers": SLOT[7], "Expected winners": SLOT[2], "Rest of chip universe": INK2}
    fig, axes = plt.subplots(2, 2, figsize=(12, 8.4), sharex=True)
    fig.patch.set_facecolor(SURF)
    ymax = np.nanmax(np.abs(P.car_pct.values)) * 1.15
    for ax, ev in zip(axes.flat, EVENTS):
        style(ax, grid="y")
        sub = P[P.event == ev["key"]]
        for role in ("Rest of chip universe", "Expected losers", "Expected winners"):
            s = sub[sub.role == role]
            if s.empty:
                continue
            ax.plot(s.day, s.car_pct, color=col[role], lw=2 if role != "Rest of chip universe" else 1.4,
                    ls="-" if role != "Rest of chip universe" else "--", label=role)
            if role != "Rest of chip universe":
                ax.fill_between(s.day, s.car_pct - s.band_pct, s.car_pct + s.band_pct, color=col[role], alpha=0.1, lw=0)
            r = m4[(m4.event == ev["key"]) & (m4.role == role)].iloc[0]
            star = "*" if r.p_d0_20 < 0.05 else ""
            ax.annotate(f"{r.car_d0_20_pct:+.1f}%{star}", (s.day.iloc[-1], s.car_pct.iloc[-1]), xytext=(4, 0),
                        textcoords="offset points", va="center", fontsize=8.5, color=col[role], annotation_clip=False)
        ax.axvline(0, color=INK, lw=0.8, ls=":")
        ax.axhline(0, color=INK2, lw=0.8)
        ax.set_ylim(-ymax, ymax)
        ax.set_title(ev["label"], loc="left", fontsize=10, color=INK)
    for ax in axes[1]:
        ax.set_xlabel("Trading days from the event", color=INK2, fontsize=9)
    for ax in axes[:, 0]:
        ax.set_ylabel("Cumulative abnormal return, %", color=INK2, fontsize=9)
    axes[0, 0].legend(frameon=False, fontsize=8.5, loc="lower left", labelcolor=INK2)
    fig.suptitle("How chip stocks reacted to the four supply shocks, beyond what the world market did",
                 x=0.02, ha="left", fontsize=13, color=INK)
    fig.text(0.02, 0.012, "Equal-weight groups fixed in advance. Market model: MSCI World ETF same-day and previous-day "
             "returns, fitted on days -260 to -31. Shading = 95% range; * = day 0-20 total differs from zero at 5%.",
             fontsize=8.5, color=INK2)
    fig.subplots_adjust(left=0.07, right=0.93, top=0.9, bottom=0.1, hspace=0.3, wspace=0.18)
    fig.savefig(FIGS / "m4_shocks.png", dpi=150, facecolor=SURF)
    plt.close(fig)
    return m4


def portfolio_mkt(usd, tickers, date, mkt_of):
    ars, ests = [], []
    for t in tickers:
        if t not in usd:
            continue
        w = event_window(daily_ar(usd, t, mkt=mkt_of(t)), date)
        if w is None:
            continue
        ars.append(w[0])
        ests.append(w[1])
    AR = pd.concat(ars, axis=1).mean(axis=1)
    sd = pd.concat(ests, axis=1).mean(axis=1).std()
    return AR, sd


def model4_benchmarks(usd, uni):
    """Same shock groups, three yardsticks: world market, chip sector, home stock market. If the effect only
    survives against the world market, the move was country-wide, not specific to the supply chain."""
    country = dict(zip(uni.ticker, uni.country))
    marks = [("World market", lambda t: "URTH"), ("Chip sector (SOXX)", lambda t: "SOXX"),
             ("Home stock market", lambda t: HOME_INDEX.get(country.get(t), "URTH"))]
    rows = []
    for ev in EVENTS:
        for role, tick in (("Expected losers", ev["exposed"]), ("Expected winners", ev["winners"])):
            if not tick:
                continue
            for mname, f in marks:
                AR, sd = portfolio_mkt(usd, tick, ev["date"], f)
                for a, b in ((0, 1), (0, 5), (0, 20)):
                    v, tt = car(AR, sd, a, b)
                    rows.append(dict(event=ev["key"], label=ev["label"].split(":")[0], role=role, benchmark=mname,
                                     window=f"{a}-{b}", car_pct=100 * v, se_pct=100 * v / tt if tt else np.nan,
                                     t=tt, p=2 * (1 - stats.norm.cdf(abs(tt)))))
    rb = pd.DataFrame(rows)
    rb.round(4).to_csv(MKT / "model4_benchmarks.csv", index=False)

    d = rb[rb.window == "0-5"]
    cases = d[["label", "role"]].drop_duplicates().values.tolist()
    mcol = {"World market": SLOT[0], "Chip sector (SOXX)": SLOT[1], "Home stock market": SLOT[2]}
    fig, ax = plt.subplots(figsize=(10.5, 6.4))
    fig.patch.set_facecolor(SURF)
    style(ax)
    ylab = []
    for i, (lab, role) in enumerate(cases):
        for j, (mname, _) in enumerate(marks):
            r = d[(d.label == lab) & (d.role == role) & (d.benchmark == mname)].iloc[0]
            y = -(i * 4.6 + j * 1.25)
            sig = r.p < 0.05
            ax.plot([r.car_pct - 1.96 * abs(r.se_pct), r.car_pct + 1.96 * abs(r.se_pct)], [y, y], color=mcol[mname],
                    lw=2, alpha=0.9 if sig else 0.4, solid_capstyle="round")
            ax.scatter([r.car_pct], [y], s=50, color=mcol[mname] if sig else SURF, edgecolor=mcol[mname], lw=1.6, zorder=3)
            ax.annotate(f"{r.car_pct:+.1f}%", (r.car_pct, y), xytext=(0, 7), textcoords="offset points", ha="center",
                        fontsize=7.5, color=INK2)
        ylab.append((-(i * 4.6 + 1.25), f"{lab}\n{role.lower()}"))
    ax.set_yticks([y for y, _ in ylab], [t for _, t in ylab], fontsize=9, color=INK)
    ax.axvline(0, color=INK2, lw=1)
    for mname, _ in marks:
        ax.scatter([], [], color=mcol[mname], label="vs " + mname[0].lower() + mname[1:], s=40)
    ax.legend(frameon=False, ncol=3, fontsize=8.5, loc="lower left", bbox_to_anchor=(0, 1.0), labelcolor=INK2)
    ax.set_xlabel("Abnormal return, trading days 0 to 5 after the shock, % (95% range)", color=INK2, fontsize=9)
    fig.suptitle("Change the yardstick and most shock effects shrink: the moves were largely country-wide",
                 x=0.02, ha="left", fontsize=13, color=INK)
    fig.text(0.02, 0.012, "Same stock groups as the event-study chart. Home market: KOSPI, TAIEX, Nikkei, Hang Seng or S&P 500 "
             "(MSCI World ETF where none). Filled dot = differs from zero at 5%.", fontsize=8.5, color=INK2)
    fig.subplots_adjust(left=0.2, right=0.97, top=0.86, bottom=0.12)
    fig.savefig(FIGS / "m4_benchmarks.png", dpi=150, facecolor=SURF)
    plt.close(fig)
    return rb


def main():
    FIGS.mkdir(exist_ok=True)
    usd, uni, ff = load()
    w, fw = weekly(usd, ff)
    pd.set_option("display.width", 220)
    m1 = model1(w, fw, uni)
    print("MODEL 1  factor regressions")
    print(m1[["name", "group", "alpha_ff5_pct_yr", "alpha_ff5_t", "beta_mkt", "r2_ff5", "alpha_capm_pct_yr",
              "beta_capm", "beta_up_soxx", "beta_down_soxx"]].round(2).to_string(index=False))
    m2 = model2(w, uni)
    print("\nMODEL 2  variance shares")
    print(m2[["name", "world_market", "chip_sector", "home_market", "company_specific"]].round(2).to_string(index=False))
    m3, C = model3(w, uni)
    print("\nMODEL 3  clusters")
    print(m3.sort_values("cluster").to_string(index=False))
    m4 = model4(usd, uni)
    print("\nMODEL 4  event study")
    print(m4.round(2).to_string(index=False))
    rb = model4_benchmarks(usd, uni)
    print("\nMODEL 4b  same groups, three benchmarks (days 0-5 and 0-20)")
    print(rb[rb.window != "0-1"].round(2).to_string(index=False))


if __name__ == "__main__":
    main()
