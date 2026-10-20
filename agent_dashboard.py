"""
Build the data for the local agent dashboard (dashboard/index.html).

  python agent_dashboard.py          (or double-click run_dashboard.bat, which also opens the page)

Reads   data/agents/trade_log.csv, run_summaries.csv, keys/, runs/<run_id>/boss.txt, agents/CHANGELOG.md,
        data/market/market.db
Writes  dashboard/data.json   prices of every stock the agents traded, every run with its plan, trade and the
                              agents' reasoning, results by prompt version, and open paper trades

Everything is rebuilt from the trade log, so each newly scored run (manual or automated) shows up the next time this
runs. Simulation only: nothing here places a real order.
"""
import json
from datetime import datetime

import numpy as np
import pandas as pd

import agent_report
import agent_score
import agent_sim as sim

DASH = sim.ROOT / "dashboard"
START = "2016-01-01"


def num(x, nd=4):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), nd)


def text(x):
    return x if isinstance(x, str) else ""


def close_on(series, date):
    """USD close on `date`, or None when the stock did not trade that day."""
    if not isinstance(date, str) or not date:
        return None
    d = pd.Timestamp(date[:10])
    return num(series.get(d)) if d in series.index else None


def decision_numbers(run_id):
    """The numbers the Boss actually decided (they can differ from the Strategist's plan when a fix was applied)."""
    p = sim.OUT / "runs" / run_id / "boss.txt"
    try:
        d = agent_score.parse_decision(p.read_text(encoding="utf-8"))
        return {k.lower(): d[k] for k in agent_score.NUMBERS} | {"applied_fix": d.get("APPLIED_FIX", "")}
    except (OSError, agent_score.DecisionError):
        return {}


def build():
    cfg = sim.config()
    usd, vol, uni, _ = sim.load_market()
    names, changelog = agent_report.versions()
    log = agent_score.load_log(sim.OUT)
    summaries = pd.read_csv(sim.OUT / "run_summaries.csv").set_index("run_id") if (sim.OUT / "run_summaries.csv").exists() \
        else pd.DataFrame()
    info = uni.set_index("ticker")
    fee = 2 * (cfg["fee_pct_per_side"] + cfg["slippage_pct_per_side"]) / 100

    stocks = {}
    for t in sorted(log.market.dropna().unique()):
        s = usd[t].dropna()
        s = s[s.index >= START]
        v = vol[t].reindex(s.index) if t in vol else pd.Series(index=s.index, dtype=float)
        stocks[t] = dict(name=info.loc[t, "name"], group=info.loc[t, "group"], country=info.loc[t, "country"],
                         dates=[d.strftime("%Y-%m-%d") for d in s.index], close=[round(float(x), 4) for x in s],
                         volume=[None if pd.isna(x) else int(x) for x in v])

    runs = []
    for r in log.sort_values("date_time").itertuples():
        key = json.loads((sim.OUT / "keys" / f"{r.run_id}.json").read_text(encoding="utf-8"))
        s = usd[r.market].dropna()
        dec = decision_numbers(r.run_id)
        entry_px, exit_px = close_on(s, text(r.entry_date)), close_on(s, text(r.exit_date))
        buy = r.action == "BUY"
        last_px, last_date = num(s.iloc[-1]), s.index[-1].strftime("%Y-%m-%d")
        mark = None
        if r.status == "pending" and buy and entry_px:     # open paper trade, marked to the latest close
            mark = 100 * ((last_px * (1 - fee / 2)) / (entry_px * (1 + fee / 2)) - 1 - fee)
        sm = summaries.loc[r.run_id] if r.run_id in summaries.index else {}
        runs.append(dict(
            run_id=r.run_id, ticker=r.market, company=key["name"], version=names.get(str(r.prompts_version), str(r.prompts_version)),
            prompts_version=str(r.prompts_version), eval_set=text(r.eval_set), split=r.split, blind=bool(key.get("blind")),
            runner=text(r.runner) or key.get("runner", ""), scored_at=text(r.date_time)[:10], decision_date=r.decision_date,
            status=r.status, action=r.action, final=text(r.boss_decision), risk_decision=text(r.risk_decision),
            size=num(dec.get("size_pct")), stop=num(dec.get("stop_pct")), target=num(dec.get("target_pct")),
            hold_days=num(dec.get("max_hold_days")), applied_fix=text(dec.get("applied_fix")),
            plan=dict(action=text(r.plan_action), setup=text(r.plan_setup), size=num(r.plan_size_pct),
                      stop=num(r.plan_stop_pct), target=num(r.plan_target_pct), ret=num(r.plan_ret_pct)),
            entry_date=text(r.entry_date)[:10], exit_date=text(r.exit_date)[:10], exit_reason=text(r.exit_reason),
            entry_px=entry_px, exit_px=exit_px,
            stop_px=num(entry_px * (1 - dec["stop_pct"] / 100)) if buy and entry_px and dec.get("stop_pct") else None,
            target_px=num(entry_px * (1 + dec["target_pct"] / 100)) if buy and entry_px and dec.get("target_pct") else None,
            ret=num(r.agent_ret_pct, 3), hold_ret=num(r.stock_hold_ret_pct, 3), vs_hold=num(r.vs_buy_and_hold_pct, 3),
            vs_baseline=num(r.excess_vs_baseline_pct, 3), soxx_ret=num(r.soxx_ret_pct, 3), good_skip=text(r.good_skip),
            vetoed=text(r.vetoed), veto_right=text(r.veto_right), mark_pct=num(mark, 3), mark_date=last_date if mark is not None else "",
            researcher=text(sm.get("researcher", "")), strategist=text(sm.get("strategist", "")),
            risk_manager=text(sm.get("risk_manager", "")), boss=text(sm.get("boss", ""))))

    sims = build_sims(cfg, usd, names, summaries)
    order = list(dict.fromkeys(names[h] for h in names))            # v1, v2, ... in changelog order
    return dict(generated=datetime.now().isoformat(timespec="seconds"),
                asof=max(st["dates"][-1] for st in stocks.values()), config=dict(
                    portfolio=cfg["portfolio_usd"], max_position=cfg["max_position_pct"], max_hold=cfg["max_hold_days"],
                    fee=cfg["fee_pct_per_side"], slippage=cfg["slippage_pct_per_side"], blind_before=cfg["blind_before"]),
                versions=order, stocks=stocks, runs=runs, changelog=changelog, sims=sims)


def build_sims(cfg, usd, names, summaries):
    """Every time-span simulation (agent_span.py) with candles for its span, its curves, and each decision with
    what the agents remembered at that moment and their own reasons."""
    import agent_span
    out = []
    for p in sorted((sim.OUT / "sims").glob("*/sim.json")):
        st = json.loads(p.read_text(encoding="utf-8"))
        if not st.get("decisions"):
            continue
        t = st["ticker"]
        dates = agent_span.trading_days(usd, t)
        closes = usd[t].dropna().tolist()
        curve, stats = agent_span.curves(st, dates, closes, cfg)
        ohlc = sim.load_ohlc(t)
        a = dates[max(0, st["span_index"][0] - 30)]
        b = dates[min(len(dates) - 1, dates.index(curve[-1]["date"]) + 10)]
        o = ohlc[(ohlc.index >= a) & (ohlc.index <= b)]
        decisions = []
        for k, d in enumerate(st["decisions"]):
            i = dates.index(d["date"])
            sm = summaries.loc[d["run_id"]] if d.get("run_id") and d["run_id"] in summaries.index else {}
            decisions.append(dict(d, memory=agent_span.history_text(st["decisions"][:k], dates, i),
                                  strategist=text(sm.get("strategist", "")) or d.get("reason", ""),
                                  risk_manager=text(sm.get("risk_manager", "")), boss=text(sm.get("boss", "")),
                                  exit_px=close_on(usd[t].dropna(), d.get("exit_date", "")),
                                  entry_px=close_on(usd[t].dropna(), d.get("entry_date", ""))))
        version = "demo" if st.get("demo") else names.get(st.get("prompts_version", ""), st.get("prompts_version", ""))
        out.append(dict(sim_id=st["sim_id"], ticker=t, company=st["company"], start=st["start"], end=st["end"],
                        cadence=st["cadence"], version=version, runner=st.get("runner", ""), demo=bool(st.get("demo")),
                        status=st.get("status", ""), created=st.get("created", ""), stats=stats, decisions=decisions,
                        curve=curve, candles=[dict(time=d.strftime("%Y-%m-%d"), open=round(r.open, 4), high=round(r.high, 4),
                                                   low=round(r.low, 4), close=round(r.close, 4),
                                                   volume=None if pd.isna(r.volume) else int(r.volume))
                                              for d, r in o.iterrows()]))
    return out


def main():
    data = build()
    DASH.mkdir(exist_ok=True)
    out = DASH / "data.json"
    out.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    runs = data["runs"]
    print(f"dashboard/data.json: {len(data['stocks'])} stocks, {len(runs)} runs "
          f"({sum(r['action'] == 'BUY' for r in runs)} trades, {sum(r['status'] == 'pending' for r in runs)} open), "
          f"prices to {data['asof']}, {out.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
