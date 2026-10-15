"""
Phase 5: what a supply shock does to the cost of a wafer and to the value of one fab.

Two scenario sizes, both taken from real events in phase 2:
  * neon-sized: the input's price rises ~3.75x on average for 12 months (Korea's neon, 2022: +275%),
                supply keeps flowing (Korea's neon volume actually rose 56%).
  * HF-sized:   one supplier's share is lost (Japan's HF to Korea, 2019: 33% -> 8% of supply), price
                unchanged; the cost is lost output if replacements arrive after on-site inventory runs out.

Cost per wafer (plan doc):  dC_m = q_m * dP_m  +  p_m * D_m * F / W
  price term   q_m * dP_m         usage per wafer x price rise
  output term  D_m * F / W        lost days of output x margin lost per idle day / wafers per day
              (the deterministic table shows it given the event, p_m = 1; the Monte Carlo draws events at p_m)

F here is the gross margin lost per idle day (revenue minus variable cash cost): fixed costs keep running
while no wafers ship, so that is what an idle day costs the fab.

Reads   data/processed/per_wafer_usage.csv        (phase4_wafer_usage.py)
Writes  data/processed/phase5_scenarios.csv        $/wafer by scenario and input
        data/processed/phase5_dcf_montecarlo.csv   one row per Monte Carlo run
        data/processed/phase5_summary.csv          headline numbers
        figures/phase5_cost_per_wafer.png, figures/phase5_npv_distribution.png

Run:  python phase5_cost_dcf.py     (no internet needed; set N_RUNS in the environment to change 10,000)
"""
import os
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
PROC = ROOT / "data" / "processed"
FIGS = ROOT / "figures"
FIGS.mkdir(parents=True, exist_ok=True)
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e6e5e0", "#fcfcfb"
SLOT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]

# ---------------------------------------------------------------- reference fab
# A 7 nm-class 300 mm foundry fab. Prices and capital intensity from CSET (Khan & Mann 2020):
# sale price $9,346 per wafer; capital investment $14,267 per wafer of annual capacity.
FAB = dict(
    wspm=50_000,                 # wafer starts per month (a mid-size leading-edge fab; TSMC GigaFabs run 100k+)
    utilization=0.90,
    price=9_346.0,               # US$ per wafer (CSET, 7 nm)
    capex_per_annual_wafer=14_267.0,
    gross_margin=0.53,           # TSMC 2020 gross margin (cost of goods incl. depreciation)
    depreciation_years=5,        # TSMC depreciates fab equipment over 5 years
    overhead=0.10,               # R&D + SG&A allocated to the fab, share of revenue
    tax=0.20,                    # Taiwan corporate rate
    wacc=0.09,
    years=10,
)

# Shock sizes from phase 2 (event_study_summary.csv) and the inventory/replacement evidence
NEON_PRICE_MULT = (2.5, 3.75, 6.0)     # low / central / high: +150%, +275% (12-month avg), ~6x (mid-2022 peak)
NEON_MONTHS = 12
HF_LOST_SHARE = (0.15, 0.25, 0.50)     # share of supply lost (Korea 2019: Japan 33% -> 8% = 25 pts)
HF_REPLACE_DAYS = (60, 90, 120)        # days to qualify and ramp a new supplier (Korea's switch took ~3 months)
HF_RAMP_COVER = (0.5, 0.8, 1.0)        # share of the gap other existing suppliers cover meanwhile
EVENTS_PER_YEAR = 0.10                 # p_m: ~4 major shocks across 3 inputs in 2015-2026 ≈ 1 per input per decade
INPUTS = ["helium", "neon", "hf"]      # silicon fab; gallium matters only for RF and power fabs


def fab_economics(f=FAB):
    wafers_yr = f["wspm"] * 12 * f["utilization"]
    capex = f["capex_per_annual_wafer"] * f["wspm"] * 12
    dep = capex / f["depreciation_years"]
    dep_per_wafer = dep / wafers_yr
    cogs_per_wafer = f["price"] * (1 - f["gross_margin"])
    cash_cogs_per_wafer = cogs_per_wafer - dep_per_wafer          # materials, labour, power, maintenance
    margin_per_idle_wafer = f["price"] - cash_cogs_per_wafer       # what one wafer not shipped costs
    wafers_per_day = wafers_yr / 365
    F = margin_per_idle_wafer * wafers_per_day                     # margin lost per idle day
    return dict(wafers_yr=wafers_yr, capex=capex, dep=dep, dep_per_wafer=dep_per_wafer,
                cash_cogs_per_wafer=cash_cogs_per_wafer, margin_per_idle_wafer=margin_per_idle_wafer,
                wafers_per_day=wafers_per_day, F=F)


def lost_days(lost_share, replace_days, ramp_cover, inventory_days):
    """Full-output days lost: after inventory runs out, output falls by the uncovered share of supply."""
    gap = np.maximum(0.0, np.asarray(replace_days) - inventory_days)
    return gap * np.asarray(lost_share) * (1 - np.asarray(ramp_cover))


# ---------------------------------------------------------------- deterministic scenarios
def scenario_table(use, econ):
    rows = []
    W, F = econ["wafers_per_day"], econ["F"]
    for _, u in use[use.input.isin(INPUTS)].iterrows():
        for case, i in (("low", 0), ("central", 1), ("high", 2)):
            q, p = u[case], u[f"price_{case}"]
            base = q * p
            # neon-sized: price x mult, averaged over the shock year -> per wafer made during the shock
            price_term = q * p * (NEON_PRICE_MULT[i] - 1)
            rows.append(dict(scenario="neon-sized (price spike)", input=u.input, case=case,
                             base_usd_per_wafer=base, price_term=price_term, output_term=0.0))
            # HF-sized: no price change; lost output spread over one year of wafers
            # low case = mildest disruption (small loss, fast replacement, full cover)
            sev = {"low": (0, 0, 2), "central": (1, 1, 1), "high": (2, 2, 0)}[case]
            D = lost_days(HF_LOST_SHARE[sev[0]], HF_REPLACE_DAYS[sev[1]], HF_RAMP_COVER[sev[2]],
                          u.inventory_days)
            rows.append(dict(scenario="HF-sized (supplier lost)", input=u.input, case=case,
                             base_usd_per_wafer=base, price_term=0.0,
                             output_term=float(D) * F / (W * 365), lost_days=float(D)))
    t = pd.DataFrame(rows)
    t["total"] = t.price_term + t.output_term
    t["pct_of_wafer_price"] = 100 * t.total / FAB["price"]
    return t


# ---------------------------------------------------------------- DCF + Monte Carlo
def npv(cash, r):
    return sum(c / (1 + r) ** t for t, c in enumerate(cash))


def baseline_cash(econ, f=FAB):
    rev = f["price"] * econ["wafers_yr"]
    cash = [-econ["capex"]]
    for y in range(1, f["years"] + 1):
        dep = econ["dep"] if y <= f["depreciation_years"] else 0.0
        ebit = rev - econ["cash_cogs_per_wafer"] * econ["wafers_yr"] - dep - f["overhead"] * rev
        cash.append(ebit * (1 - f["tax"]) + dep)
    return np.array(cash)


def tri(rng, lo_c_hi, n):
    lo, c, hi = lo_c_hi
    return rng.triangular(lo, c, hi, n) if hi > lo else np.full(n, c)


def monte_carlo(use, econ, n=10_000, seed=7):
    rng = np.random.default_rng(seed)
    years, r, tax = FAB["years"], FAB["wacc"], FAB["tax"]
    disc = 1 / (1 + r) ** np.arange(1, years + 1)
    loss = np.zeros((n, years))                                    # pre-tax extra cost per year
    detail = {f"{m}_events": np.zeros(n, int) for m in INPUTS}
    detail.update({f"{m}_loss_pv": np.zeros(n) for m in INPUTS})
    for _, u in use[use.input.isin(INPUTS)].iterrows():
        m = u.input
        q = tri(rng, (u.low, u.central, u.high), n)
        p = tri(rng, (u.price_low, u.price_central, u.price_high), n)
        events = rng.random((n, years)) < EVENTS_PER_YEAR
        kind_price = rng.random((n, years)) < 0.5                  # half price spikes, half supplier losses
        mult = tri(rng, NEON_PRICE_MULT, n * years).reshape(n, years)
        price_cost = q[:, None] * p[:, None] * (mult - 1) * econ["wafers_yr"] * NEON_MONTHS / 12
        D = lost_days(tri(rng, HF_LOST_SHARE, n * years), tri(rng, HF_REPLACE_DAYS, n * years),
                      tri(rng, HF_RAMP_COVER, n * years), u.inventory_days).reshape(n, years)
        output_cost = D * econ["F"]
        m_loss = np.where(events, np.where(kind_price, price_cost, output_cost), 0.0)
        loss += m_loss
        detail[f"{m}_events"] = events.sum(1)
        detail[f"{m}_loss_pv"] = (m_loss * (1 - tax)) @ disc
    d_npv = -(loss * (1 - tax)) @ disc
    out = pd.DataFrame({"run": np.arange(n), "delta_npv_usd": d_npv, **detail})
    return out


# ---------------------------------------------------------------- figures
def style(ax):
    ax.set_facecolor(SURF)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9, length=0)


def fig_cost(t):
    c = t[t.case == "central"].copy()
    lohi = t.pivot_table(index=["scenario", "input"], columns="case", values="total")
    c["label"] = c.input.str.replace("hf", "HF").str.capitalize().str.replace("Hf", "HF")
    order = [("neon-sized (price spike)", m) for m in INPUTS] + [("HF-sized (supplier lost)", m) for m in INPUTS]
    c = c.set_index(["scenario", "input"]).loc[order].reset_index()
    fig, ax = plt.subplots(figsize=(11, 5.2))
    fig.patch.set_facecolor(SURF)
    y = np.array([6.6, 5.6, 4.6, 2.4, 1.4, 0.4])
    ax.barh(y, c.price_term, color=SLOT[0], height=0.62, label="Price term  q × ΔP")
    ax.barh(y, c.output_term, left=c.price_term, color=SLOT[1], height=0.62, label="Output term  D × F / W")
    for yi, (_, row) in zip(y, c.iterrows()):
        lo, hi = lohi.loc[(row.scenario, row.input), "low"], lohi.loc[(row.scenario, row.input), "high"]
        ax.plot([lo, hi], [yi, yi], color=INK, lw=1)
        ax.plot([lo, lo], [yi - .12, yi + .12], color=INK, lw=1)
        ax.plot([hi, hi], [yi - .12, yi + .12], color=INK, lw=1)
        ax.annotate(f"${row.total:,.0f}  ({row.pct_of_wafer_price:.2f}% of price)", (hi, yi),
                    xytext=(8, 0), textcoords="offset points", va="center", fontsize=9, color=INK)
    ax.set_yticks(y)
    ax.set_yticklabels(c.label, color=INK, fontsize=10)
    ax.text(-0.01, 7.25, "Neon-sized shock: price ×3.75 for a year", transform=ax.get_yaxis_transform(),
            ha="right", fontsize=10, color=INK, weight="bold")
    ax.text(-0.01, 3.05, "HF-sized shock: lose 25% of supply", transform=ax.get_yaxis_transform(),
            ha="right", fontsize=10, color=INK, weight="bold")
    ax.set_xscale("symlog", linthresh=1)
    ax.set_xlim(0, max(lohi.values.max() * 6, 10))
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"${v:,.0f}"))
    ax.grid(axis="x", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    style(ax)
    ax.set_xlabel("Extra cost per wafer, US$ (log scale; bar = central, whisker = low–high)", color=INK2, fontsize=9)
    fig.legend(frameon=False, fontsize=9, loc="upper right", bbox_to_anchor=(0.98, 0.97), ncol=2, labelcolor=INK2)
    fig.suptitle("A lost supplier costs far more per wafer than a price spike", x=0.02, ha="left",
                 fontsize=14, color=INK)
    fig.text(0.02, 0.015, f"Reference fab: 7 nm-class, {FAB['wspm']:,} wafers/month, ${FAB['price']:,.0f} per wafer. "
             "Shock sizes from Korea's neon (2022) and HF (2019) events. HF-sized cost = lost output spread over a year of wafers.", fontsize=8.5, color=INK2)
    fig.subplots_adjust(left=0.27, right=0.86, top=0.88, bottom=0.17)
    fig.savefig(FIGS / "phase5_cost_per_wafer.png", dpi=150, facecolor=SURF)
    plt.close(fig)


def fig_npv(mc, base_npv):
    pct = 100 * mc.delta_npv_usd / base_npv
    fig, ax = plt.subplots(figsize=(11, 4.6))
    fig.patch.set_facecolor(SURF)
    hit = pct[pct < 0]
    ax.hist(hit, bins=60, color=SLOT[0], edgecolor=SURF, linewidth=0.4)
    p50, p95, p99 = np.percentile(pct, [50, 5, 1])
    for v, lab in ((p95, "1 in 20 runs worse than"), (p99, "1 in 100 worse than")):
        ax.axvline(v, color=INK, lw=1, ls="--")
        ax.annotate(f"{lab}\n{v:.2f}% of NPV", (v, ax.get_ylim()[1] * 0.92), xytext=(-6, 0),
                    textcoords="offset points", ha="right", va="top", fontsize=9, color=INK)
    style(ax)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    ax.set_xlabel("Change in the fab's 10-year NPV, % (runs with at least one shock)", color=INK2, fontsize=9)
    ax.set_ylabel("Runs", color=INK2, fontsize=9)
    share0 = 100 * (pct == 0).mean()
    fig.suptitle(f"Ten years of input shocks cost this fab little: median {np.median(pct):.2f}% of NPV",
                 x=0.02, ha="left", fontsize=14, color=INK)
    fig.text(0.02, 0.015, f"{len(mc):,} Monte Carlo runs; {share0:.0f}% had no shock. Each input: 10% chance of a "
             "shock a year, half neon-sized, half HF-sized. Base NPV "
             f"${base_npv/1e9:.1f}B at {FAB['wacc']:.0%}.", fontsize=8.5, color=INK2)
    fig.subplots_adjust(left=0.07, right=0.98, top=0.87, bottom=0.17)
    fig.savefig(FIGS / "phase5_npv_distribution.png", dpi=150, facecolor=SURF)
    plt.close(fig)


def main():
    use = pd.read_csv(PROC / "per_wafer_usage.csv")
    econ = fab_economics()
    t = scenario_table(use, econ)
    t.to_csv(PROC / "phase5_scenarios.csv", index=False)

    base = baseline_cash(econ)
    base_npv = npv(base, FAB["wacc"])
    mc = monte_carlo(use, econ, n=int(os.environ.get("N_RUNS", 10_000)))
    mc.to_csv(PROC / "phase5_dcf_montecarlo.csv", index=False)
    pct = 100 * mc.delta_npv_usd / base_npv

    summary = {
        "capex_usd_b": econ["capex"] / 1e9,
        "wafers_per_year": econ["wafers_yr"],
        "cash_cogs_per_wafer": econ["cash_cogs_per_wafer"],
        "margin_lost_per_idle_day_usd_m": econ["F"] / 1e6,
        "base_npv_usd_b": base_npv / 1e9,
        "share_runs_no_shock": float((mc.delta_npv_usd == 0).mean()),
        "mean_delta_npv_usd_m": mc.delta_npv_usd.mean() / 1e6,
        "p50_delta_npv_pct": float(np.percentile(pct, 50)),
        "p5_delta_npv_pct": float(np.percentile(pct, 5)),
        "p1_delta_npv_pct": float(np.percentile(pct, 1)),
        "worst_delta_npv_pct": float(pct.min()),
        **{f"mean_loss_pv_{m}_usd_m": mc[f"{m}_loss_pv"].mean() / 1e6 for m in INPUTS},
    }
    pd.Series(summary).to_csv(PROC / "phase5_summary.csv", header=["value"])

    fig_cost(t)
    fig_npv(mc, base_npv)

    pd.set_option("display.width", 200)
    print("Reference fab")
    for k, v in econ.items():
        print(f"  {k:24s} {v:,.1f}")
    print("\nExtra cost per wafer by scenario (US$)")
    print(t.round(2).to_string(index=False))
    print("\nDCF + Monte Carlo")
    for k, v in summary.items():
        print(f"  {k:32s} {v:,.3f}")


if __name__ == "__main__":
    main()
