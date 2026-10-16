"""
Build the six ready-to-paste prompts (a "packet") for one manual run of the AI agent team: one stock, one decision date.

  python agent_packets.py --ticker 2330.TW --date 2022-03-15      one chosen stock and date
  python agent_packets.py --sample 3 --split dev                   3 random stock-date pairs from the dev years
  options: --named (show the real stock and dates), --blind (hide them), --seed N (repeat a random draw)

Dates before agents/config.json "blind_before" are blind by default: the stock becomes "Stock A", dates become
"Day -29 ... Day 0", and prices are rebased so Day 0 = 100. Claude remembers real market history, and blinding stops it
from answering from memory instead of from the data.

Writes  data/agents/runs/<run_id>/1_researcher.txt ... 6_boss.txt, 00_HOW_TO_RUN.txt
        data/agents/keys/<run_id>.json   the answer key (real stock and date). Never paste it into Claude.
Then score the Boss's reply with agent_score.py.
"""
import argparse
import json
import secrets
import sqlite3
import time
from datetime import datetime

import numpy as np
import pandas as pd

import agent_sim as sim

NEWS_DB = sim.ROOT / "data" / "news" / "news.db"
NEWS_LOOKBACK_DAYS = 7
SHOCK_NEWS_DAYS = 120
# Blind descriptions of the phase 8 shocks: what happened, without names or dates that give the period away.
GENERIC = {
    "hf_2019": "export curbs on hydrogen fluoride and photoresist (chip-making chemicals) sold to one country's fabs",
    "neon_2022": "a war that disrupted the supply of neon (a gas used in chip lithography lasers)",
    "gallium_2023": "export licensing on gallium and germanium (materials for chips and compound semiconductors)",
    "helium_2026": "a major helium plant going offline (helium cools and purges fab tools)",
}


def fmt(x, nd=1, unit=""):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "MISSING"
    return f"{x:,.{nd}f}{unit}"


def rules_text(cfg):
    return "\n".join([
        f"- Simulated portfolio: ${cfg['portfolio_usd']:,}. Long-only: BUY or NO TRADE. No shorting, no leverage.",
        "- The decision is made at the close of Day 0. A BUY fills at the next close (Day 1).",
        f"- Maximum position: {cfg['max_position_pct']}% of the portfolio.",
        f"- A stop and a target are required. Maximum stop: {cfg['max_stop_pct']}% below entry.",
        f"- Maximum holding period: {cfg['max_hold_days']} trading days; the position closes at that day's close.",
        f"- Fees {cfg['fee_pct_per_side']}% and slippage {cfg['slippage_pct_per_side']}% on each side (entry and exit).",
        "- Stops and targets are checked on daily closes only (there are no intraday highs or lows in the data).",
        "- Simulation only. No real order is ever placed.",
    ])


# ---------------------------------------------------------------- the three fact sheets
def researcher_facts(t, info, D, usd, vol, blind):
    s = usd[t].dropna()
    s = s[s.index <= D]
    v = vol[t].reindex(s.index) if t in vol else None
    ind = sim.indicators(usd[t], vol[t] if t in vol else None, usd["SOXX"], D)
    k = 100 / ind["close"] if blind else 1.0      # rebase factor
    unit = "" if blind else " USD"
    head = (f"Stock: Stock A (sector group: {info['group']})" if blind else
            f"Stock: {info['name']} ({t}), {info['group']}, listed in {info['country']}")
    lines = [
        head,
        "Timeframe: daily closes" + (", rebased so the Day 0 close = 100." if blind else ", converted to US dollars."),
        f"Decision point: the close of {'Day 0' if blind else D.date()}.",
        # The close count gives away how long the stock has traded (and so the year) in blind mode.
        f"Source: data/market/market.db daily closes (Yahoo Finance via fetch_prices.py), "
        f"{'at least 252' if blind else ind['obs']} closes up to {'Day 0' if blind else D.date()}; nothing after it.",
        "",
        "Indicators (computed by agent_sim.indicators from those closes):",
        f"- Close: {fmt(ind['close'] * k, 2)}{unit}",
    ]
    for n in (20, 50, 200):
        lines.append(f"- {n}-day average: {fmt(ind[f'ma{n}'] * k if ind[f'ma{n}'] else None, 2)}{unit}; "
                     f"close vs it: {fmt(ind[f'vs_ma{n}_pct'], 1, '%')}")
    lines.append("- Returns: " + ", ".join(f"{lab} {fmt(ind[f'ret_{lab}_pct'], 1, '%')}" for lab in ("1m", "3m", "6m", "12m")))
    lines.append("- Chip-sector ETF returns, same periods: " +
                 ", ".join(f"{lab} {fmt(ind[f'sector_ret_{lab}_pct'], 1, '%')}" for lab in ("1m", "3m", "6m", "12m")))
    lines += [
        f"- RSI (14-day): {fmt(ind['rsi14'], 1)}",
        f"- Volatility, annualised: 20-day {fmt(ind['vol20_ann_pct'], 1, '%')}, 120-day {fmt(ind['vol120_ann_pct'], 1, '%')}",
        f"- Volume, last 5 days vs 50-day average: {fmt(ind['volume_5d_vs_50d'], 2, 'x')}",
    ]
    for n in (20, 60, 252):
        lines.append(f"- {n}-day closing high / low: {fmt(ind[f'high_{n}d'] * k, 2)} / {fmt(ind[f'low_{n}d'] * k, 2)}{unit}")
    lines.append(f"- Close vs 252-day high: {fmt(ind['from_252d_high_pct'], 1, '%')}")
    lines += ["", "Last 30 closes:", "Day | Close | Volume" + (" (x 50-day average)" if blind else " (shares)")]
    tail = s.iloc[-30:]
    avg50 = v.rolling(50).mean() if v is not None else None
    for j, (d, px) in enumerate(tail.items()):
        label = f"Day {j - len(tail) + 1}" if blind else str(d.date())
        if v is None or pd.isna(v.get(d)):
            vtxt = "MISSING"
        elif blind:
            vtxt = fmt(v[d] / avg50[d], 2, "x") if avg50 is not None and avg50.get(d) == avg50.get(d) else "MISSING"
        else:
            vtxt = f"{int(v[d]):,}"
        lines.append(f"{label} | {fmt(px * k, 2)} | {vtxt}")
    return "\n".join(lines), ind


def headlines(info, D):
    """Archived headlines published in the week up to the end of D that mention the company or are alerts from its
    country. Returns (lines, note)."""
    if not NEWS_DB.exists():
        return [], "MISSING: no news archive (data/news/news.db) on this computer."
    con = sqlite3.connect(NEWS_DB)
    first = con.execute("SELECT min(published) FROM articles").fetchone()[0]
    if first is None or D + pd.Timedelta(days=1) <= pd.Timestamp(first[:10]):
        con.close()
        return [], f"MISSING: the news archive starts {first[:10] if first else 'later'}; no headlines exist for this date."
    a = (D - pd.Timedelta(days=NEWS_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    b = (D + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    rows = pd.read_sql("SELECT published, source, title, url, country, topics, alert FROM articles "
                       "WHERE published >= ? AND published < ? ORDER BY published DESC", con, params=(a, b))
    con.close()
    names = {info["name"].lower(), info["name"].split()[0].lower(), info["ticker"].split(".")[0].lower()}
    names = {n for n in names if len(n) >= 3}
    hit = rows.title.str.lower().apply(lambda x: any(n in x for n in names))
    pick = rows[hit | ((rows.alert == 1) & (rows.country == info["country"]))].head(15)
    out = [f"- {p.published} | {p.source} | {p.title} | {p.url} | topics: {p.topics or 'none'}" for p in pick.itertuples()]
    return out, (f"{len(out)} headlines from the {NEWS_LOOKBACK_DAYS} days up to the decision date "
                 f"(data/news/news.db, news_collector.py)." if out else "No matching headlines in the archive for this week.")


def news_facts(t, info, D, blind):
    lines = []
    if blind:
        lines.append("Headlines: MISSING. Headlines would reveal the stock and the dates, so blind runs have none.")
    else:
        h, note = headlines(dict(info, ticker=t), D)
        lines += [f"Headlines: {note}", *h]
    lines += ["", f"Supply-chain events from the phase 8 event list (Model 4) in the {SHOCK_NEWS_DAYS} days before the decision:"]
    ev = sim.shocks_before(D, t, within_days=SHOCK_NEWS_DAYS)
    if not ev:
        lines.append("- None.")
    for e in ev:
        what = GENERIC[e["key"]] if blind else f"{e['label']} ({e['date']})"
        lines.append(f"- {what}; began {e['days_ago']} calendar days before the decision; this stock: {e['role']}.")
    lines.append("Source: phase8_market_models.EVENTS; the expected losers and winners were fixed before looking at returns.")
    return "\n".join(lines)


def strategist_facts(t, D, usd, ff, uni, cfg, blind):
    tickers = list(sim.companies(uni).ticker)
    m = sim.trailing_model1(usd, ff, D, cfg, tickers)
    bc = cfg["baseline"]
    lines = [f"Model 1 (Fama-French 5-factor regression on weekly US-dollar returns, last {bc['lookback_weeks']} weeks "
             f"knowable at the decision; factor data lagged {bc['factor_lag_days']} days because it is published late):"]
    if t in m.index:
        r = m.loc[t]
        rank = int((m.alpha_t > r.alpha_t).sum()) + 1
        lines += [
            f"- Alpha (return not explained by the factors): {fmt(r.alpha_pct_yr, 1, '% a year')}, t-stat {fmt(r.alpha_t, 2)} "
            f"({int(r.weeks)} weeks). Rank {rank} of {len(m)} companies by alpha t-stat.",
            f"- Market beta: {fmt(r.beta_mkt, 2)}. Beta to the chip-sector ETF in up weeks {fmt(r.beta_up_soxx, 2)}, "
            f"in down weeks {fmt(r.beta_down_soxx, 2)}.",
            "- Note: the phase 8 baseline rule holds the top 5 by this t-stat each month. In its development-period test it "
            "returned less than simply holding the chip-sector ETF.",
        ]
    else:
        lines.append(f"- MISSING: fewer than {bc['min_weeks']} weeks of history.")
    lines += ["", "Model 4 supply shocks before the decision (all of them, with this stock's group):"]
    ev = sim.shocks_before(D, t)
    lines += [f"- {GENERIC[e['key']] if blind else e['label']}: {e['days_ago']} days before; this stock: {e['role']}." for e in ev] or ["- None."]
    ex = sim.ROOT / "data" / "processed" / "exposure_matrix.csv"
    lines += ["", "Supply exposure (exposure_model.py): share of the company's input supply traced to each supplier country,"
                  " via its fabs' countries and their imports."]
    if ex.exists():
        x = pd.read_csv(ex)
        x = x[(x.ticker == t) & (x.year < D.year)]
        if x.empty:
            lines.append("- MISSING: no exposure rows for this stock before the decision year.")
        else:
            y = x.year.max()
            top = x[x.year == y].sort_values("exposure", ascending=False).head(5)
            lines.append(f"Latest full year before the decision{'' if blind else f' ({y})'}, top suppliers:")
            lines += [f"- {p.input} from {p.supplier}: {p.exposure:.3f} (trade data covers {100 * p.coverage:.0f}% of capacity)"
                      for p in top.itertuples()]
    else:
        lines.append("- MISSING: data/processed/exposure_matrix.csv not found.")
    return "\n".join(lines)


# ---------------------------------------------------------------- packet
def build(t, D, blind, cfg, market, out_dir=None, seed=None):
    usd, vol, uni, ff = market
    info = uni.set_index("ticker").loc[t].to_dict()
    s = usd[t].dropna()
    D = s.index[s.index <= pd.Timestamp(D)][-1]          # last trading day on or before the requested date
    run_id = f"run-{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
    out_dir = out_dir or sim.OUT
    run_dir = out_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "keys").mkdir(parents=True, exist_ok=True)

    shared = (sim.PROMPTS / "0_shared_rules.md").read_text(encoding="utf-8").strip()
    rules = rules_text(cfg)
    rf, _ = researcher_facts(t, info, D, usd, vol, blind)
    facts = {"1_researcher": rf, "2_news_analyst": news_facts(t, info, D, blind),
             "3_strategist": strategist_facts(t, D, usd, ff, uni, cfg, blind), "4_coder": "", "5_risk_manager": "", "6_boss": ""}
    for name, fx in facts.items():
        tpl = (sim.PROMPTS / f"{name}.md").read_text(encoding="utf-8")
        text = tpl.replace("{SHARED_RULES}", shared).replace("{RULES}", rules).replace("{FACTS}", fx)
        (run_dir / f"{name}.txt").write_text(text, encoding="utf-8")
    (run_dir / "00_HOW_TO_RUN.txt").write_text(HOW_TO.format(run_id=run_id), encoding="utf-8")
    key = dict(run_id=run_id, ticker=t, name=info["name"], decision_date=str(D.date()), blind=blind,
               split=sim.split_of(D, cfg), prompts_version=sim.prompts_version(), seed=seed,
               created=datetime.now().isoformat(timespec="seconds"))
    (out_dir / "keys" / f"{run_id}.json").write_text(json.dumps(key, indent=2), encoding="utf-8")
    return run_id, run_dir, key


HOW_TO = """HOW TO RUN {run_id} (simulation only)

1. In Claude, open a new chat (or a Project chat) for each agent.
2. Paste 1_researcher.txt. Copy the handoff block it ends with.
3. Paste 2_news_analyst.txt, replacing [PASTE THE RESEARCHER'S HANDOFF BLOCK HERE] with that block.
4. Paste 3_strategist.txt with both handoffs.
5. Skip 4_coder.txt in manual runs (read it once to see why).
6. Paste 5_risk_manager.txt with the Strategist's handoff.
7. Paste 6_boss.txt with all four handoffs.
8. Save the Boss's whole reply as boss.txt in this folder, then score it:
       python agent_score.py {run_id}
   (or double-click run_agent_score.bat and type the run id)

Do not open or paste data/agents/keys/{run_id}.json: it holds the real stock and date.
"""


def sample(n, split, cfg, usd, uni, seed):
    rng = np.random.default_rng(seed)
    a, b = (cfg["splits"][split] if split in cfg["splits"] else [cfg["blind_before"], str(usd.index.max().date())])
    tickers = [t for t in sim.companies(uni).ticker if t in usd]
    picks = []
    while len(picks) < n:
        t = tickers[rng.integers(len(tickers))]
        s = usd[t].dropna()
        need_after = cfg["max_hold_days"] + 1 if split != "forward" else 0
        ok = [i for i, d in enumerate(s.index) if pd.Timestamp(a) <= d <= pd.Timestamp(b) and i >= 260
              and len(s) - 1 - i >= need_after]
        if ok:
            picks.append((t, s.index[ok[rng.integers(len(ok))]]))
    return picks


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ticker")
    ap.add_argument("--date")
    ap.add_argument("--sample", type=int)
    ap.add_argument("--split", default="dev", choices=["dev", "test", "forward"])
    ap.add_argument("--seed", type=int)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--blind", action="store_true")
    g.add_argument("--named", action="store_true")
    a = ap.parse_args()
    cfg = sim.config()
    market = sim.load_market()
    usd, _, uni, _ = market
    if a.sample:
        seed = a.seed if a.seed is not None else int(time.time())
        pairs = sample(a.sample, a.split, cfg, usd, uni, seed)
        print(f"Random draw: {a.sample} from {a.split}, seed {seed}")
    elif a.ticker and a.date:
        if a.ticker not in set(sim.companies(uni).ticker):
            raise SystemExit(f"Unknown ticker {a.ticker}. Choose one of: {' '.join(sim.companies(uni).ticker)}")
        seed, pairs = None, [(a.ticker, pd.Timestamp(a.date))]
    else:
        raise SystemExit("Give --ticker and --date, or --sample N.")
    for t, D in pairs:
        blind = True if a.blind else False if a.named else D < pd.Timestamp(cfg["blind_before"])
        run_id, run_dir, key = build(t, D, blind, cfg, market, seed=seed)
        print(f"{run_id}: {'blind' if blind else t + ' ' + key['decision_date']}, split {key['split']} -> {run_dir}")


if __name__ == "__main__":
    main()
