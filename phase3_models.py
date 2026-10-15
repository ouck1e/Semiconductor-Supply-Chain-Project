"""
Phase 3: forecasting and exposure models.

Model A  Price forecast: predicts the 3-month-ahead change in an importer's average import price
         for each material, and must beat two simple baselines to be worth keeping.
Model B  Supplier-drop exposure: predicts the chance that imports from a key supplier fall by more
         than half over the next 3 months.

Both are tested walk-forward: for each test year the models train only on months that were fully
known before that year started, so nothing from the future leaks into training.

Reads data/raw/ (via phase2_event_study.py). Writes:
  data/processed/model_a_price_forecast_results.csv
  data/processed/model_b_exposure_results.csv
  data/processed/exposure_scores_latest.csv      <- feeds the globe dashboard
  figures/model_a_skill.png, figures/model_b_cases.png

Run:  python phase3_models.py   (uses xgboost if installed, otherwise scikit-learn's gradient boosting)
"""
from pathlib import Path
import importlib.util
import warnings

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from sklearn.linear_model import HuberRegressor, LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss

warnings.filterwarnings("ignore", category=RuntimeWarning)

ROOT = Path(__file__).resolve().parent
PROC, FIGS = ROOT / "data" / "processed", ROOT / "figures"
FIGS.mkdir(parents=True, exist_ok=True)

try:  # same model family; XGBoost when available
    from xgboost import XGBRegressor, XGBClassifier
    BOOSTER = "XGBoost"
    def boost_reg():
        return XGBRegressor(objective="reg:absoluteerror", n_estimators=300, max_depth=3, learning_rate=0.03,
                            subsample=0.8, colsample_bytree=0.8, min_child_weight=30, reg_lambda=5.0)
    def boost_clf():
        return XGBClassifier(n_estimators=300, max_depth=3, learning_rate=0.05, subsample=0.8,
                             colsample_bytree=0.8, min_child_weight=10, reg_lambda=5.0, eval_metric="logloss")
except ImportError:
    from sklearn.ensemble import HistGradientBoostingRegressor, HistGradientBoostingClassifier
    BOOSTER = "Gradient boosting (scikit-learn)"
    def boost_reg():
        return HistGradientBoostingRegressor(loss="absolute_error", max_iter=300, max_depth=3, learning_rate=0.03,
                                             min_samples_leaf=30, l2_regularization=5.0, random_state=0)
    def boost_clf():
        return HistGradientBoostingClassifier(max_iter=300, max_depth=3, learning_rate=0.05,
                                              min_samples_leaf=20, l2_regularization=5.0, random_state=0)

# phase 2 already knows how to load raw files and split helium from rare gases
_spec = importlib.util.spec_from_file_location("phase2", ROOT / "phase2_event_study.py")
phase2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(phase2)

import os
HORIZON = int(os.environ.get("HORIZON", "3"))   # months ahead (set HORIZON=6 to test a longer window)
TEST_YEARS = range(2019, 2027)
MIN_SHARE = 0.10            # model B: supplier must hold 10%+ of trailing-12m imports...
MIN_ANNUAL_USD = 1e6        # ...and ship $1M+ a year, so tiny lumpy flows don't dominate
DROP = 0.5                  # "sharp drop": next 3 months < 50% of the usual 3 months
# The drop is measured in physical volume (kg) wherever the importer reports weights: in a supply shock,
# prices jump, so import VALUE can rise while shipments collapse (Korea's neon from Ukraine in 2022).
# Pairs with mostly unreported weights (US gases) fall back to value.

DISPLAY = {"Rep. of Korea": "South Korea", "Other Asia, nes": "Taiwan", "USA": "United States",
           "Russian Federation": "Russia"}
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e6e5e0", "#fcfcfb"
SLOT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]


# ---------------------------------------------------------------- data
def load() -> pd.DataFrame:
    df = phase2.classify_gases(phase2.load_raw())
    return df[["date", "series", "importer", "supplier", "value_usd", "net_kg_reported"]]


def full_grid(df: pd.DataFrame) -> pd.DataFrame:
    """Every (series, importer, supplier) gets every month the importer reported anything; no shipment = 0."""
    span = df.groupby("importer")["date"].agg(["min", "max"])
    parts = []
    for (s, i), g in df.groupby(["series", "importer"]):
        months = pd.date_range(span.loc[i, "min"], span.loc[i, "max"], freq="MS")
        agg = g.groupby(["supplier", "date"]).agg(value_usd=("value_usd", "sum"),
                                                  kg=("net_kg_reported", "sum")).reset_index()
        idx = pd.MultiIndex.from_product([agg["supplier"].unique(), months], names=["supplier", "date"])
        agg = agg.set_index(["supplier", "date"]).reindex(idx, fill_value=0).reset_index()
        agg["series"], agg["importer"] = s, i
        parts.append(agg)
    return pd.concat(parts, ignore_index=True)


# ---------------------------------------------------------------- geopolitical risk (GPR)
# Caldara & Iacoviello Geopolitical Risk Index (fetch_gpr.py). Country indexes exist for 44 countries.
# Suppliers without one: Gulf states use Saudi Arabia as a regional stand-in; Taiwan appears in Comtrade as
# "Other Asia, nes". Anyone else gets only the global index (their country feature is left blank).
GPR_FILE = ROOT / "data" / "external" / "gpr_monthly.csv"
SUPPLIER_ISO = {
    "Argentina": "ARG", "Australia": "AUS", "Belgium": "BEL", "Brazil": "BRA", "Canada": "CAN",
    "Switzerland": "CHE", "Chile": "CHL", "China": "CHN", "Colombia": "COL", "Germany": "DEU", "Denmark": "DNK",
    "Egypt": "EGY", "Spain": "ESP", "Finland": "FIN", "France": "FRA", "United Kingdom": "GBR",
    "China, Hong Kong SAR": "HKG", "Hungary": "HUN", "Indonesia": "IDN", "India": "IND", "Israel": "ISR",
    "Italy": "ITA", "Japan": "JPN", "Rep. of Korea": "KOR", "Mexico": "MEX", "Malaysia": "MYS",
    "Netherlands": "NLD", "Norway": "NOR", "Peru": "PER", "Philippines": "PHL", "Poland": "POL",
    "Portugal": "PRT", "Russian Federation": "RUS", "Saudi Arabia": "SAU", "Sweden": "SWE", "Thailand": "THA",
    "Tunisia": "TUN", "Türkiye": "TUR", "Turkey": "TUR", "Other Asia, nes": "TWN", "Ukraine": "UKR",
    "USA": "USA", "Venezuela": "VEN", "Viet Nam": "VNM", "South Africa": "ZAF",
    # regional stand-ins
    "Qatar": "SAU", "United Arab Emirates": "SAU", "Oman": "SAU", "Kuwait": "SAU", "Bahrain": "SAU",
}


def load_gpr():
    if not GPR_FILE.exists():
        return None
    g = pd.read_csv(GPR_FILE, parse_dates=["date"]).set_index("date").sort_index()

    def spike(x):  # recent 3 months vs. the previous 2 years, in logs: >0 means risk is rising
        return np.log((x.rolling(3).mean() + 0.1) / (x.shift(3).rolling(24, min_periods=12).mean() + 0.1))

    glob = pd.DataFrame({"gpr_global_spike": spike(g["GPR"]), "gpr_global_level": np.log(g["GPR"])})
    acts = spike(g["GPRA"]).rename("gpr_acts_spike") if "GPRA" in g else None
    if acts is not None:
        glob = glob.join(acts)
    cty = {c.replace("GPRC_", ""): c for c in g.columns if c.startswith("GPRC_")}
    country = pd.concat({iso: pd.DataFrame({"gpr_sup_spike": spike(g[col]), "gpr_sup_level": np.log(g[col] + 0.1)})
                         for iso, col in cty.items()}, names=["iso", "date"]).reset_index()
    return glob.reset_index(), country


# ---------------------------------------------------------------- model A: price forecast
def build_price_panel(grid: pd.DataFrame) -> pd.DataFrame:
    tot = grid.groupby(["series", "importer", "date"]).agg(value=("value_usd", "sum"), kg=("kg", "sum")).reset_index()
    rows = []
    for (s, i), g in tot.groupby(["series", "importer"]):
        g = g.sort_values("date").set_index("date")
        if g["kg"].sum() == 0 or (g.loc[g["kg"] > 0, "value"].sum() / g["value"].sum()) < 0.6:
            continue  # quantities mostly unreported: no trustworthy price
        v3, q3 = g["value"].rolling(3).sum(), g["kg"].rolling(3).sum()
        lp = np.log(v3 / q3.replace(0, np.nan))
        f = pd.DataFrame(index=g.index)
        f["series"], f["importer"] = s, i
        f["log_price"] = lp
        for k in (1, 3, 6, 12):
            f[f"dp_{k}"] = lp - lp.shift(k)
        f["price_vol_12"] = (lp - lp.shift(1)).rolling(12).std()
        f["value_mom"] = np.log((g["value"].rolling(3).mean() + 1) / (g["value"].rolling(12).mean() + 1))
        f["qty_mom"] = np.log((g["kg"].rolling(3).mean() + 1) / (g["kg"].rolling(12).mean() + 1))
        f["month_sin"], f["month_cos"] = np.sin(2 * np.pi * g.index.month / 12), np.cos(2 * np.pi * g.index.month / 12)
        f["y"] = lp.shift(-HORIZON) - lp                 # target: log change over the next 3 months
        f["seasonal_naive"] = lp.shift(12 - HORIZON) - lp.shift(12)   # same 3-month change a year earlier
        rows.append(f.reset_index())
    panel = pd.concat(rows, ignore_index=True)
    # concentration features at importer level
    conc = concentration(grid)
    panel = panel.merge(conc, on=["series", "importer", "date"], how="left")
    # peer signal: how prices of the same material moved in the OTHER importing countries
    for k in ("dp_3", "dp_12"):
        tot = panel.groupby(["series", "date"])[k].transform("sum")
        cnt = panel.groupby(["series", "date"])[k].transform("count")
        panel[f"peer_{k}"] = (tot - panel[k].fillna(0)) / (cnt - panel[k].notna().astype(int)).replace(0, np.nan)
    # mean reversion: how far the price sits from its own 2-year average
    panel["dev_24"] = panel["log_price"] - panel.groupby(["series", "importer"])["log_price"].transform(
        lambda x: x.rolling(24, min_periods=12).mean())
    for s in sorted(panel["series"].unique()):
        panel[f"is_{s.replace(' ', '_')}"] = (panel["series"] == s).astype(int)
    return panel


def concentration(grid: pd.DataFrame) -> pd.DataFrame:
    g = grid.sort_values("date").copy()
    g["v12"] = g.groupby(["series", "importer", "supplier"])["value_usd"].transform(lambda x: x.rolling(12, min_periods=6).sum())
    tot = g.groupby(["series", "importer", "date"])["v12"].transform("sum")
    g["share"] = g["v12"] / tot.replace(0, np.nan)
    c = g.groupby(["series", "importer", "date"]).agg(hhi=("share", lambda s: (s ** 2).sum()),
                                                     top_share=("share", "max")).reset_index()
    c = c.sort_values("date")
    c["d_top_share_3"] = c.groupby(["series", "importer"])["top_share"].diff(3)
    return c


A_FEATURES = ["dp_1", "dp_3", "dp_6", "dp_12", "price_vol_12", "value_mom", "qty_mom",
              "hhi", "top_share", "d_top_share_3", "peer_dp_3", "peer_dp_12", "dev_24",
              "month_sin", "month_cos"]


def run_model_a(panel: pd.DataFrame):
    feats = A_FEATURES + [c for c in panel.columns if c.startswith("is_")]
    data = panel.dropna(subset=["y", "dp_12", "price_vol_12"]).copy()
    preds = []
    for yr in TEST_YEARS:
        start = pd.Timestamp(f"{yr}-01-01")
        train = data[data["date"] + pd.DateOffset(months=HORIZON) < start]   # target fully known before test year
        test = data[(data["date"] >= start) & (data["date"] < pd.Timestamp(f"{yr + 1}-01-01"))]
        if len(train) < 200 or test.empty:
            continue
        y = train["y"].clip(train["y"].quantile(0.02), train["y"].quantile(0.98))  # tame extreme months
        huber = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), HuberRegressor(alpha=1.0, max_iter=1000))
        huber.fit(train[feats], y)
        boost = boost_reg()
        boost.fit(train[feats], y)
        out = test[["date", "series", "importer", "y", "seasonal_naive"]].copy()
        out["random_walk"] = 0.0
        out["seasonal_naive"] = out["seasonal_naive"].fillna(0.0)
        out["robust_linear"] = huber.predict(test[feats])
        out["boosted_trees"] = boost.predict(test[feats])
        out["blend"] = (out["robust_linear"] + out["boosted_trees"]) / 2
        out["test_year"] = yr
        preds.append(out)
    preds = pd.concat(preds, ignore_index=True)
    models = ["random_walk", "seasonal_naive", "robust_linear", "boosted_trees", "blend"]
    rows = []
    for m in models:
        err = (preds[m] - preds["y"]).abs()
        big = preds["y"].abs() > 0.05                        # direction only scored on moves above 5%
        rows.append(dict(model=m, mae_log=err.mean(),
                         skill_vs_random_walk=1 - err.mean() / (preds["y"].abs()).mean(),
                         direction_hit_rate=(np.sign(preds.loc[big, m]) == np.sign(preds.loc[big, "y"])).mean()
                         if m != "random_walk" else np.nan,
                         n=len(preds)))
    by_year = preds.groupby("test_year").apply(
        lambda d: pd.Series({m: (d[m] - d["y"]).abs().mean() for m in models}), include_groups=False)
    return preds, pd.DataFrame(rows), by_year


# ---------------------------------------------------------------- model B: supplier-drop exposure
def build_exposure_panel(grid: pd.DataFrame) -> pd.DataFrame:
    g = grid.sort_values("date").copy()
    key = ["series", "importer", "supplier"]
    grp = g.groupby(key)["value_usd"]
    g["v12_mean"] = grp.transform(lambda x: x.rolling(12, min_periods=12).mean())
    g["v3_mean"] = grp.transform(lambda x: x.rolling(3).mean())
    g["v_std12"] = grp.transform(lambda x: x.rolling(12, min_periods=12).std())
    g["zeros12"] = g.groupby(key)["value_usd"].transform(lambda x: (x == 0).rolling(12, min_periods=12).sum())
    # label basis: kg where the importer reports weights for this material, else US$
    pair_cov = g.assign(vk=g["value_usd"].where(g["kg"] > 0, 0)).groupby(["series", "importer"]).agg(
        vk=("vk", "sum"), v=("value_usd", "sum"))
    use_kg = (pair_cov["vk"] / pair_cov["v"] >= 0.6).rename("use_kg").reset_index()
    g = g.merge(use_kg, on=["series", "importer"], how="left")
    g["q"] = np.where(g["use_kg"], g["kg"], g["value_usd"])
    qg = g.groupby(key)["q"]
    g["q12_mean"] = qg.transform(lambda x: x.rolling(12, min_periods=12).mean())
    g["q3_mean"] = qg.transform(lambda x: x.rolling(3).mean())
    g["future3"] = qg.transform(lambda x: x[::-1].rolling(HORIZON).sum()[::-1].shift(-1))  # months t+1..t+3
    g["qty_momentum"] = np.log((g["q3_mean"] + 1) / (g["q12_mean"] + 1))
    tot12 = g.groupby(["series", "importer", "date"])["v12_mean"].transform("sum")
    g["share"] = g["v12_mean"] / tot12.replace(0, np.nan)
    g["hhi"] = g.groupby(["series", "importer", "date"])["share"].transform(lambda s: (s ** 2).sum())
    g["share_d6"] = g.groupby(key)["share"].diff(6)
    g["momentum"] = np.log((g["v3_mean"] + 1) / (g["v12_mean"] + 1))
    g["cv12"] = g["v_std12"] / g["v12_mean"].replace(0, np.nan)
    # supplier price momentum (where weight is reported)
    kgrp = g.groupby(key)
    g["upk3"] = kgrp["value_usd"].transform(lambda x: x.rolling(3).sum()) / kgrp["kg"].transform(lambda x: x.rolling(3).sum()).replace(0, np.nan)
    g["upk12"] = kgrp["value_usd"].transform(lambda x: x.rolling(12).sum()) / kgrp["kg"].transform(lambda x: x.rolling(12).sum()).replace(0, np.nan)
    g["price_mom"] = np.log(g["upk3"] / g["upk12"])
    # importer-wide momentum for this material
    imp = g.groupby(["series", "importer", "date"])[["v3_mean", "v12_mean"]].transform("sum")
    g["importer_mom"] = np.log((imp["v3_mean"] + 1) / (imp["v12_mean"] + 1))
    # supplier-wide stress: are OTHER importers already seeing this supplier slide?
    g["weak"] = (g["v3_mean"] < DROP * g["v12_mean"]).astype(float)
    w = g.groupby(["series", "supplier", "date"]).agg(weak_n=("weak", "sum"), n=("weak", "size")).reset_index()
    g = g.merge(w, on=["series", "supplier", "date"], how="left")
    g["supplier_stress"] = (g["weak_n"] - g["weak"]) / (g["n"] - 1).replace(0, np.nan)
    # geopolitical risk: global, and for the supplier's own country
    gpr = load_gpr()
    if gpr is not None:
        glob, country = gpr
        g = g.merge(glob, on="date", how="left")
        g["iso"] = g["supplier"].map(SUPPLIER_ISO)
        g = g.merge(country, on=["iso", "date"], how="left")
        g["gpr_sup_known"] = g["gpr_sup_spike"].notna().astype(int)
    # eligibility + label
    elig = (g["share"] >= MIN_SHARE) & (g["v12_mean"] * 12 >= MIN_ANNUAL_USD)
    g = g[elig].copy()
    g["label"] = np.where(g["future3"].notna(), (g["future3"] < DROP * HORIZON * g["q12_mean"]).astype(float), np.nan)
    g["label_basis"] = np.where(g["use_kg"], "kg", "US$")
    for s in sorted(g["series"].unique()):
        g[f"is_{s.replace(' ', '_')}"] = (g["series"] == s).astype(int)
    return g


B_FEATURES = ["share", "hhi", "share_d6", "momentum", "qty_momentum", "cv12", "zeros12", "price_mom",
              "importer_mom", "supplier_stress"]
GPR_FEATURES = ["gpr_global_spike", "gpr_global_level", "gpr_acts_spike", "gpr_sup_spike", "gpr_sup_level", "gpr_sup_known"]


def run_model_b(panel: pd.DataFrame, extra=()):
    feats = B_FEATURES + [f for f in extra if f in panel.columns] + [c for c in panel.columns if c.startswith("is_")]
    data = panel.dropna(subset=["label"]).copy()
    preds = []
    for yr in TEST_YEARS:
        start = pd.Timestamp(f"{yr}-01-01")
        train = data[data["date"] + pd.DateOffset(months=HORIZON) < start]
        test = data[(data["date"] >= start) & (data["date"] < pd.Timestamp(f"{yr + 1}-01-01"))]
        if len(train) < 300 or test.empty or train["label"].nunique() < 2:
            continue
        logit = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                              LogisticRegression(C=0.5, max_iter=2000))
        logit.fit(train[feats], train["label"])
        boost = boost_clf()
        boost.fit(train[feats], train["label"])
        out = test[["date", "series", "importer", "supplier", "share", "label"]].copy()
        out["base_rate"] = train["label"].mean()
        out["logistic"] = logit.predict_proba(test[feats])[:, 1]
        out["boosted_trees"] = boost.predict_proba(test[feats])[:, 1]
        out["test_year"] = yr
        preds.append(out)
    preds = pd.concat(preds, ignore_index=True)
    rows = []
    for m in ["base_rate", "logistic", "boosted_trees"]:
        rows.append(dict(model=m,
                         roc_auc=roc_auc_score(preds["label"], preds[m]) if m != "base_rate" else 0.5,
                         pr_auc=average_precision_score(preds["label"], preds[m]),
                         brier=brier_score_loss(preds["label"], preds[m]),
                         hit_rate_top_10pct=preds.loc[preds[m] >= preds[m].quantile(0.9), "label"].mean()
                         if m != "base_rate" else preds["label"].mean(),
                         event_rate=preds["label"].mean(), n=len(preds), events=int(preds["label"].sum())))
    # final fit on everything labelled, score the latest month of every eligible pair
    logit = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(C=0.5, max_iter=2000))
    logit.fit(data[feats], data["label"])
    boost = boost_clf()
    boost.fit(data[feats], data["label"])
    latest = panel[panel["date"] == panel.groupby("importer")["date"].transform("max")].copy()
    latest["p_logistic"] = logit.predict_proba(latest[feats])[:, 1]
    latest["p_boosted"] = boost.predict_proba(latest[feats])[:, 1]
    latest["exposure_score"] = (latest["p_logistic"] + latest["p_boosted"]) / 2
    coefs = pd.Series(logit[-1].coef_[0], index=feats).sort_values(key=np.abs, ascending=False)
    return preds, pd.DataFrame(rows), latest, coefs


# ---------------------------------------------------------------- charts
def style(ax):
    ax.set_facecolor(SURF)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.tick_params(colors=INK2, labelsize=9)
    for s in ax.spines.values():
        s.set_visible(False)


def chart_a(by_year: pd.DataFrame):
    names = {"random_walk": "No change (baseline)", "seasonal_naive": "Same as last year", "robust_linear": "Robust linear",
             "boosted_trees": BOOSTER, "blend": "Blend of the two models"}
    by_year = by_year[["random_walk", "seasonal_naive", "blend"]]
    fig, ax = plt.subplots(figsize=(11, 4.8))
    fig.patch.set_facecolor(SURF)
    x = np.arange(len(by_year))
    w = 0.26
    for k, m in enumerate(by_year.columns):
        ax.bar(x + (k - 1) * w, by_year[m] * 100, w - 0.04, color=SLOT[k], label=names[m])
    ax.set_xticks(x, [str(y) for y in by_year.index])
    ax.set_ylabel("Mean absolute error, % price change", color=INK2)
    ax.set_title("Model A: 3-month price forecast error by test year (lower is better)", loc="left", color=INK, fontsize=12)
    ax.legend(frameon=False, labelcolor=INK2, fontsize=9, ncol=4, loc="upper left")
    style(ax)
    fig.tight_layout()
    fig.savefig(FIGS / "model_a_skill.png", dpi=150, facecolor=SURF)
    plt.close(fig)


def chart_b(preds: pd.DataFrame, cases, base=None):
    fig, axes = plt.subplots(1, len(cases), figsize=(12, 4.6), sharey=True)
    fig.patch.set_facecolor(SURF)
    for ax, (title, s, i, sup, shock) in zip(np.atleast_1d(axes), cases):
        d = preds[(preds["series"] == s) & (preds["importer"] == i) & (preds["supplier"] == sup)].set_index("date")
        months = pd.date_range(d.index.min(), d.index.max(), freq="MS")
        d = d.reindex(months)                       # gaps (supplier not a key source) stay gaps
        ax.plot(d.index, d["boosted_trees"] * 100, color=SLOT[0], linewidth=2, label=f"{BOOSTER}, with GPR")
        ax.plot(d.index, d["logistic"] * 100, color=SLOT[1], linewidth=2, label="Logistic, with GPR")
        if base is not None:
            b = base[(base["series"] == s) & (base["importer"] == i) & (base["supplier"] == sup)].set_index("date").reindex(months)
            ax.plot(b.index, b["logistic"] * 100, color=SLOT[1], linewidth=1.2, linestyle=(0, (2, 2)),
                    label="Logistic, trade data only")
        hit = d[d["label"] == 1]
        ax.scatter(hit.index, np.full(len(hit), 2), marker="|", s=120, color=INK, label="A >50% volume drop followed")
        ax.axvline(pd.Timestamp(shock), color=INK, linewidth=1, linestyle=(0, (4, 3)))
        ax.text(pd.Timestamp(shock), 97, f" {pd.Timestamp(shock):%b %Y}", color=INK, fontsize=8.5, va="top")
        ax.set_title(title, loc="left", color=INK, fontsize=11)
        ax.set_ylim(0, 102)
        ax.xaxis.set_major_locator(mdates.YearLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        style(ax)
    first = np.atleast_1d(axes)[0]
    first.set_ylabel("Predicted chance of a >50% drop, %", color=INK2)
    h, l = first.get_legend_handles_labels()
    fig.legend(h, l, frameon=False, labelcolor=INK2, fontsize=9, ncol=4, loc="lower center")
    fig.suptitle("Model B: did the exposure model see it coming? (dashed line = shock)", x=0.02, ha="left",
                 color=INK, fontsize=13)
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    fig.savefig(FIGS / "model_b_cases.png", dpi=150, facecolor=SURF)
    plt.close(fig)


# ---------------------------------------------------------------- main
def main():
    print(f"Booster: {BOOSTER}")
    grid = full_grid(load())

    panel_a = build_price_panel(grid)
    preds_a, metrics_a, by_year_a = run_model_a(panel_a)
    preds_a.to_csv(PROC / "model_a_price_forecast_results.csv", index=False)
    chart_a(by_year_a)
    print("\nModel A - 3-month price change forecast, walk-forward", f"{by_year_a.index.min()}-{by_year_a.index.max()}")
    print(metrics_a.to_string(index=False, float_format=lambda v: f"{v:.3f}"))

    panel_b = build_exposure_panel(grid)
    has_gpr = "gpr_global_spike" in panel_b.columns
    preds_b0, metrics_b0, _, _ = run_model_b(panel_b)                       # trade data only
    if has_gpr:
        preds_b, metrics_b, latest, coefs = run_model_b(panel_b, GPR_FEATURES)  # + geopolitical risk
    else:
        print("\n(no data/external/gpr_monthly.csv: run fetch_gpr.py to add geopolitical risk)")
        preds_b, metrics_b, latest, coefs = preds_b0, metrics_b0, *run_model_b(panel_b)[2:]
    preds_b.to_csv(PROC / "model_b_exposure_results.csv", index=False)
    comp = pd.concat([metrics_b0.assign(features="trade only"), metrics_b.assign(features="trade + GPR")]) if has_gpr else metrics_b
    comp.to_csv(PROC / "model_b_metrics.csv", index=False)
    print("\nModel B - chance of a >50% drop from a key supplier within 3 months, walk-forward")
    print(comp.to_string(index=False, float_format=lambda v: f"{v:.3f}"))
    print("\nLogistic regression weights (standardized; + raises risk):")
    print(coefs.round(2).to_string())

    out = latest[["date", "series", "importer", "supplier", "share", "hhi", "momentum", "supplier_stress",
                  "p_logistic", "p_boosted", "exposure_score"]].sort_values("exposure_score", ascending=False)
    out.to_csv(PROC / "exposure_scores_latest.csv", index=False)
    print("\nHighest exposure right now (latest month each importer reports):")
    print(out.head(12).to_string(index=False, float_format=lambda v: f"{v:.2f}"))

    cases = [("South Korea: neon from Ukraine", "rare gas", "Rep. of Korea", "Ukraine", "2022-02-01"),
             ("United States: helium from Qatar", "helium", "USA", "Qatar", "2026-03-01"),
             ("Japan: gallium-code imports from China", "gallium", "Japan", "China", "2023-08-01")]
    chart_b(preds_b, cases, preds_b0 if has_gpr else None)
    for title, s, i, sup, shock in cases:
        d = preds_b[(preds_b["series"] == s) & (preds_b["importer"] == i) & (preds_b["supplier"] == sup)]
        win = d[(d["date"] >= pd.Timestamp(shock) - pd.DateOffset(months=4)) & (d["date"] <= pd.Timestamp(shock))]
        base = preds_b0[(preds_b0["series"] == s) & (preds_b0["importer"] == i) & (preds_b0["supplier"] == sup)]
        win = win.merge(base[["date", "logistic", "boosted_trees"]].rename(
            columns={"logistic": "logistic_trade_only", "boosted_trees": "boosted_trade_only"}), on="date", how="left")
        print(f"\n{title}: months before/at shock")
        print(win[["date", "label", "logistic_trade_only", "logistic", "boosted_trade_only", "boosted_trees"]]
              .to_string(index=False, float_format=lambda v: f"{v:.2f}"))


if __name__ == "__main__":
    main()
