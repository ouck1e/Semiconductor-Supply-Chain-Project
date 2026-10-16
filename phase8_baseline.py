"""
Phase 8 baseline v1: the phase 8 models turned into a fixed, walk-forward, long-only trading rule.
This is the opponent the AI agent team has to beat. It is frozen: change it only by making a v2.

  Monthly    On the first trading day of each month, hold an equal-weight basket of the top 5 companies by trailing
             156-week Fama-French 5-factor alpha t-stat (Model 1), positive t only; the rest stays in cash.
             Only data knowable that day is used: complete weeks up to the day, factor data lagged 2 months.
  Shocks     The trading day after a Model 4 supply shock, sell any held expected losers and buy the expected
             winners, for 20 trading days.
  Costs      Fees and slippage from agents/config.json on every change in weights. Decisions at the close.

Also runs two plain benchmarks for context: SOXX bought and held, and an equal-weight basket of all companies
rebalanced monthly.

Reads   data/market/market.db (fetch_prices.py), agents/config.json
Writes  data/agents/baseline_weights.csv   end-of-day weights, one column per company
        data/agents/baseline_holdings.csv  every rebalance: date, reason, tickers
        data/agents/baseline_equity.csv    daily value of phase8_v1, soxx, equal_weight (start = 1)
        data/agents/baseline_stats.csv     per split (dev, test, forward): return, volatility, drawdown, losing streak
        figures/phase8_baseline.png

Run:  python phase8_baseline.py      (or double-click run_phase8_baseline.bat; no internet needed)
"""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import agent_sim as sim
import phase8_market_models as pm


def basket(usd, ff, date, cfg, tickers):
    """The monthly basket: top_n companies by trailing alpha t-stat, positive only."""
    m = sim.trailing_model1(usd, ff, date, cfg, tickers)
    if m.empty:
        return [], m
    top = m[m.alpha_t > 0].sort_values("alpha_t", ascending=False).head(cfg["baseline"]["top_n"])
    return list(top.index), m


def run(usd, ff, uni, cfg):
    tickers = [t for t in sim.companies(uni).ticker if t in usd]
    cal = usd["SOXX"].dropna().index
    px = usd[tickers].reindex(cal).ffill()
    r = px.pct_change().fillna(0.0)
    cost = (cfg["fee_pct_per_side"] + cfg["slippage_pct_per_side"]) / 100
    hold = cfg["baseline"]["shock_hold_days"]

    month_start = pd.Series(cal.to_period("M"), index=cal).pipe(lambda s: s != s.shift())
    shock_days = []          # (first day, last day, event) in calendar positions
    for ev in pm.EVENTS:
        i = cal.searchsorted(pd.Timestamp(ev["date"]), side="right")      # first trading day after the event date
        if i < len(cal):
            shock_days.append((i, min(i + hold, len(cal) - 1), ev))

    W = np.zeros((len(cal), len(tickers)))
    equity = np.ones(len(cal))
    w = np.zeros(len(tickers))
    base, active_prev, log = [], (), []
    started = False
    for i, t in enumerate(cal):
        if i > 0:
            pr = float(w @ r.iloc[i].values)
            equity[i] = equity[i - 1] * (1 + pr)
            w = w * (1 + r.iloc[i].values) / (1 + pr)
        active = tuple(ev["key"] for a, b, ev in shock_days if a <= i < b)
        reason = []
        if month_start.iloc[i]:
            new, _ = basket(usd, ff, t, cfg, tickers)
            if new or started:
                base, started = new, True
                reason.append("monthly")
        if active != active_prev and started:
            reason.append("shock start" if len(active) > len(active_prev) else "shock end")
        if reason:
            held = list(base)
            for a, b, ev in shock_days:
                if ev["key"] in active:
                    held = [x for x in held if x not in ev["exposed"]]
                    held += [x for x in ev["winners"] if x in tickers and x not in held and px[x].iloc[i] == px[x].iloc[i]]
            target = np.array([1.0 / len(held) if x in held else 0.0 for x in tickers]) if held else np.zeros(len(tickers))
            equity[i] *= 1 - cost * np.abs(target - w).sum()
            w = target
            log.append(dict(date=t.date(), reason=" + ".join(reason), shocks=" ".join(active), n=len(held), tickers=" ".join(held)))
        active_prev = active
        W[i] = w
    first = next(k for k, row in enumerate(W) if row.any())
    weights = pd.DataFrame(W, index=cal, columns=tickers).iloc[first:]
    eq = pd.Series(equity, index=cal).iloc[first:]
    return weights, eq / eq.iloc[0], pd.DataFrame(log)


def equal_weight(usd, uni, cal, cfg):
    tickers = [t for t in sim.companies(uni).ticker if t in usd]
    px = usd[tickers].reindex(cal).ffill()
    r = px.pct_change().fillna(0.0)
    cost = (cfg["fee_pct_per_side"] + cfg["slippage_pct_per_side"]) / 100
    month_start = pd.Series(cal.to_period("M"), index=cal).pipe(lambda s: s != s.shift())
    w = np.zeros(len(tickers))
    eq = np.ones(len(cal))
    for i in range(len(cal)):
        if i > 0:
            pr = float(w @ r.iloc[i].values)
            eq[i] = eq[i - 1] * (1 + pr)
            w = w * (1 + r.iloc[i].values) / (1 + pr)
        if month_start.iloc[i] or i == 0:
            live = px.iloc[i].notna().values
            target = live / live.sum()
            eq[i] *= 1 - cost * np.abs(target - w).sum()
            w = target
    return pd.Series(eq, index=cal)


def stats(eq, name, split, a, b):
    s = eq[(eq.index >= a) & (eq.index <= b)].dropna()
    if len(s) < 40:
        return None
    s = s / s.iloc[0]
    d = s.pct_change().dropna()
    years = (s.index[-1] - s.index[0]).days / 365.25
    m = s.resample("ME").last().pct_change().dropna()
    streak = run_ = 0
    for x in m:
        run_ = run_ + 1 if x < 0 else 0
        streak = max(streak, run_)
    return dict(strategy=name, split=split, start=s.index[0].date(), end=s.index[-1].date(), days=len(s),
                total_return_pct=100 * (s.iloc[-1] - 1), annual_return_pct=100 * (s.iloc[-1] ** (1 / years) - 1),
                annual_vol_pct=100 * d.std() * np.sqrt(252), max_drawdown_pct=100 * (s / s.cummax() - 1).min(),
                worst_month_pct=100 * m.min(), longest_losing_months=streak)


def figure(curves, cfg):
    fig, ax = plt.subplots(figsize=(10, 5.2), facecolor=pm.SURF)
    pm.style(ax, grid="y")
    for (a, b), lab in zip(cfg["splits"].values(), cfg["splits"]):
        ax.axvspan(pd.Timestamp(a), pd.Timestamp(b), color=pm.GRID, alpha=0.35 if lab == "dev" else 0.15, lw=0)
        ax.text(pd.Timestamp(a), 1.0, f" {lab}", transform=ax.get_xaxis_transform(), va="top", fontsize=8, color=pm.INK2)
    for (name, s), c in zip(curves.items(), (pm.SLOT[0], pm.INK2, pm.SLOT[1])):
        ax.plot(s.index, s.values, color=c, lw=1.6 if name == "phase8_v1" else 1.1, label=name)
    ax.set_yscale("log")
    ax.set_title("Phase 8 baseline v1 vs benchmarks (start = 1, log scale, after fees and slippage)", loc="left",
                 fontsize=10.5, color=pm.INK)
    ax.legend(frameon=False, fontsize=8.5)
    fig.tight_layout()
    fig.savefig(pm.FIGS / "phase8_baseline.png", dpi=150, facecolor=pm.SURF)
    plt.close(fig)


def main():
    cfg = sim.config()
    sim.OUT.mkdir(parents=True, exist_ok=True)
    pm.FIGS.mkdir(exist_ok=True)
    usd, _, uni, ff = sim.load_market()
    weights, eq, log = run(usd, ff, uni, cfg)
    cal = eq.index
    soxx = usd["SOXX"].reindex(cal)
    curves = {"phase8_v1": eq, "soxx": soxx / soxx.iloc[0], "equal_weight": equal_weight(usd, uni, cal, cfg)}
    curves["equal_weight"] /= curves["equal_weight"].iloc[0]

    weights.round(5).to_csv(sim.OUT / "baseline_weights.csv", index_label="date")
    log.to_csv(sim.OUT / "baseline_holdings.csv", index=False)
    pd.DataFrame(curves).round(6).to_csv(sim.OUT / "baseline_equity.csv", index_label="date")
    splits = dict(cfg["splits"], forward=[cfg["blind_before"], str(cal[-1].date())])
    rows = [x for name, s in curves.items() for sp, (a, b) in splits.items() if (x := stats(s, name, sp, a, b))]
    st = pd.DataFrame(rows)
    st.round(2).to_csv(sim.OUT / "baseline_stats.csv", index=False)
    figure(curves, cfg)

    pd.set_option("display.width", 200)
    print(f"Phase 8 baseline {cfg['baseline']['version']}: {len(log)} rebalances, {cal[0].date()} to {cal[-1].date()}")
    print(st.round(1).to_string(index=False))
    print("\nLatest basket:", log.iloc[-1].to_dict())
    print("Wrote data/agents/baseline_*.csv and figures/phase8_baseline.png")


if __name__ == "__main__":
    main()
