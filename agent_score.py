"""
Score one manual run of the AI agent team against the phase 8 baseline, and keep the long-term record.

  python agent_score.py <run_id>                  reads data/agents/runs/<run_id>/boss.txt
  python agent_score.py <run_id> path/to/reply.txt
  python agent_score.py --update                  re-score runs still waiting for later prices (forward runs)

Reads the DECISION block at the end of the Boss's reply, simulates it on the prices that followed (agent_sim.simulate_trade),
and compares it over the same days with what the phase 8 baseline earned on that stock (phase8_baseline.py) and with SOXX.
A NO TRADE is judged over the next max_hold_days: it earns 0, so it wins when the baseline lost money on the stock.
A BUY the rules did not allow (no approval, Risk Manager rejected, size or stop over the limit) is logged as a broken
rule and counted as NO TRADE.

Writes  data/agents/trade_log.csv     one row per run (the guide's trade-log columns plus the scores)
        data/agents/scoreboard.csv    totals per prompt version and split: hit rate, excess vs baseline, losing streak
        figures/agent_vs_phase8.png   running average excess return over the phase 8 baseline, run by run
Simulation only: nothing here places a real order.
"""
import argparse
import json
import re
from datetime import datetime

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

import agent_sim as sim
import phase8_market_models as pm

FIELDS = ["FINAL_STATUS", "ACTION", "SETUP", "RESEARCH_CONFIDENCE", "RISK_DECISION", "SIZE_PCT", "STOP_PCT",
          "TARGET_PCT", "MAX_HOLD_DAYS"]
REQUIRED = ["FINAL_STATUS", "ACTION", "SIZE_PCT", "STOP_PCT", "TARGET_PCT", "MAX_HOLD_DAYS"]
STATUSES = {"REJECT", "INCOMPLETE", "APPROVE FOR SIMULATION ONLY"}
LOG_COLS = [
    # the guide's trade-log columns
    "date_time", "market", "timeframe", "data_source", "setup", "research_confidence", "news_summary", "entry_rule",
    "stop_rule", "exit_rule", "simulated_size", "fees_and_slippage", "risk_decision", "boss_decision", "outcome",
    "rules_followed", "notes",
    # scoring
    "run_id", "split", "blind", "prompts_version", "baseline_version", "decision_date", "action", "entry_date",
    "exit_date", "exit_reason", "agent_ret_pct", "baseline_ret_pct", "soxx_ret_pct", "excess_vs_baseline_pct", "status",
]


class DecisionError(ValueError):
    pass


def parse_decision(text):
    """Read the Boss's DECISION block. Raises DecisionError rather than guessing when it is missing or malformed."""
    m = re.search(r"^\s*\**DECISION\**\s*$(.*?)^\s*\**END DECISION\**\s*$", text, re.S | re.M | re.I)
    if not m:
        raise DecisionError("No DECISION ... END DECISION block found at the end of the Boss's reply.")
    d = {}
    for line in m.group(1).splitlines():
        k, sep, v = line.strip().strip("*").partition(":")
        k = k.strip().strip("*").upper().replace(" ", "_")
        if sep and k in FIELDS:
            d[k] = v.strip().strip("*").strip()
    missing = [k for k in REQUIRED if not d.get(k)]
    if missing:
        raise DecisionError(f"DECISION block is missing: {', '.join(missing)}")
    d["FINAL_STATUS"] = d["FINAL_STATUS"].upper()
    d["ACTION"] = d["ACTION"].upper().replace("_", " ")
    if d["FINAL_STATUS"] not in STATUSES:
        raise DecisionError(f"FINAL_STATUS must be one of {sorted(STATUSES)}, got {d['FINAL_STATUS']!r}")
    if d["ACTION"] not in {"BUY", "NO TRADE"}:
        raise DecisionError(f"ACTION must be BUY or NO TRADE (long-only), got {d['ACTION']!r}")
    for k in ("SIZE_PCT", "STOP_PCT", "TARGET_PCT", "MAX_HOLD_DAYS"):
        try:
            d[k] = float(d[k].replace("%", "").replace(",", ""))
        except ValueError:
            raise DecisionError(f"{k} must be a plain number, got {d[k]!r}") from None
    d["RISK_DECISION"] = d.get("RISK_DECISION", "").upper()
    return d


def check_rules(d, cfg):
    """Return (action actually simulated, list of broken rules)."""
    broken = []
    if d["ACTION"] == "BUY":
        if d["FINAL_STATUS"] != "APPROVE FOR SIMULATION ONLY":
            broken.append(f"BUY with final status {d['FINAL_STATUS']}")
        if d["RISK_DECISION"].startswith("REJECT") or d["RISK_DECISION"].startswith("REVISE"):
            broken.append(f"BUY although the Risk Manager said {d['RISK_DECISION']}")
        if not 0 < d["SIZE_PCT"] <= cfg["max_position_pct"]:
            broken.append(f"size {d['SIZE_PCT']}% outside 0-{cfg['max_position_pct']}%")
        if not 0 < d["STOP_PCT"] <= cfg["max_stop_pct"]:
            broken.append(f"stop {d['STOP_PCT']}% outside 0-{cfg['max_stop_pct']}%")
        if d["TARGET_PCT"] <= 0:
            broken.append("no target")
        if not 1 <= d["MAX_HOLD_DAYS"] <= cfg["max_hold_days"]:
            broken.append(f"max hold {d['MAX_HOLD_DAYS']:g} days outside 1-{cfg['max_hold_days']}")
    return ("NO TRADE" if broken else d["ACTION"]), broken


def baseline_held(ticker, out_dir):
    """1 on days the phase 8 baseline held the stock at the previous close, else 0."""
    p = out_dir / "baseline_weights.csv"
    if not p.exists():
        raise SystemExit("Run phase8_baseline.py first (data/agents/baseline_weights.csv is missing).")
    w = pd.read_csv(p, index_col="date", parse_dates=["date"])
    if ticker not in w:
        return None, w.index
    return (w[ticker] > 0).astype(float).shift(1).fillna(0), w.index


def score(key, decision, cfg, usd, out_dir):
    t, D = key["ticker"], pd.Timestamp(key["decision_date"])
    price = usd[t]
    action, broken = check_rules(decision, cfg)
    hold = int(decision["MAX_HOLD_DAYS"]) if action == "BUY" else cfg["max_hold_days"]
    o = sim.simulate_trade(price, D, action, decision["SIZE_PCT"], decision["STOP_PCT"], decision["TARGET_PCT"], hold, cfg)
    if action == "BUY":
        pending = o["status"] != "closed"
        start, end = o["entry_date"], o["exit_date"]
        agent = o["ret_pct"]
    else:
        win = sim.window_dates(price, D, hold)
        pending = win is None
        start, end = win if win else (None, None)
        agent = 0.0
    row = dict(status="pending" if pending else "scored", action=action, entry_date=start, exit_date=end,
               exit_reason=o["exit_reason"] if action == "BUY" else "no position",
               agent_ret_pct=None, baseline_ret_pct=None, soxx_ret_pct=None, excess_vs_baseline_pct=None)
    if not pending:
        held, cal = baseline_held(t, out_dir)
        base = None
        if held is not None and cal.min() <= start:
            base = sim.window_return(price, start, end, held)
        soxx = sim.window_return(usd["SOXX"], start, end)
        row.update(agent_ret_pct=agent, baseline_ret_pct=base, soxx_ret_pct=soxx,
                   excess_vs_baseline_pct=None if base is None else agent - base)
    fees = f"{cfg['fee_pct_per_side']}% fee + {cfg['slippage_pct_per_side']}% slippage per side"
    buy = action == "BUY"
    row.update(
        date_time=datetime.now().isoformat(timespec="seconds"), market=t, timeframe="daily closes",
        data_source="market.db (Yahoo Finance), news.db, phase 8 and exposure models", setup=decision.get("SETUP", ""),
        research_confidence=decision.get("RESEARCH_CONFIDENCE", ""),
        news_summary="blind: headlines withheld" if key["blind"] else "headlines from news.db (if any in that week)",
        entry_rule="next close after the decision" if buy else "", stop_rule=f"-{decision['STOP_PCT']:g}% on closes" if buy else "",
        exit_rule=f"+{decision['TARGET_PCT']:g}% or {hold} days" if buy else "",
        simulated_size=f"{decision['SIZE_PCT']:g}% of ${cfg['portfolio_usd']:,}" if buy else "0", fees_and_slippage=fees,
        risk_decision=decision.get("RISK_DECISION", ""), boss_decision=f"{decision['FINAL_STATUS']} / {decision['ACTION']}",
        outcome=("pending: needs later prices" if pending else
                 f"{agent:+.2f}% ({row['exit_reason']})" if buy else "no position"),
        rules_followed="yes" if not broken else "no: " + "; ".join(broken),
        notes="", run_id=key["run_id"], split=key["split"], blind=key["blind"], prompts_version=key["prompts_version"],
        baseline_version=cfg["baseline"]["version"], decision_date=key["decision_date"])
    return row


def longest_streak(xs):
    best = cur = 0
    for x in xs:
        cur = cur + 1 if x < 0 else 0
        best = max(best, cur)
    return best


def scoreboard(log):
    done = log[log.status == "scored"].copy()
    rows = []
    groups = [((v, s), g) for (v, s), g in done.groupby(["prompts_version", "split"])]
    groups += [(("all versions", s), g) for s, g in done.groupby("split")]
    for (ver, split), g in groups:
        buys = g[g.action == "BUY"]
        ex = g.excess_vs_baseline_pct.dropna()
        rows.append(dict(
            prompts_version=ver, split=split, runs=len(g), buys=len(buys), no_trades=len(g) - len(buys),
            rules_broken=int((g.rules_followed != "yes").sum()),
            hit_rate_pct=100 * (buys.agent_ret_pct > 0).mean() if len(buys) else np.nan,
            avg_agent_ret_pct=g.agent_ret_pct.mean(), avg_baseline_ret_pct=g.baseline_ret_pct.mean(),
            avg_soxx_ret_pct=g.soxx_ret_pct.mean(), avg_excess_vs_baseline_pct=ex.mean() if len(ex) else np.nan,
            beat_baseline_pct=100 * (ex > 0).mean() if len(ex) else np.nan,
            worst_trade_pct=buys.agent_ret_pct.min() if len(buys) else np.nan,
            longest_losing_streak=longest_streak(buys.agent_ret_pct), first_run=g.date_time.min()[:10],
            last_run=g.date_time.max()[:10]))
    return pd.DataFrame(rows)


def figure(log, path):
    done = log[(log.status == "scored") & log.excess_vs_baseline_pct.notna()].sort_values("date_time").reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(9, 4.6), facecolor=pm.SURF)
    pm.style(ax, grid="y")
    ax.axhline(0, color=pm.INK2, lw=1)
    ax.text(0.01, 0.02, "0 = same as the phase 8 baseline", transform=ax.transAxes, fontsize=8, color=pm.INK2)
    if len(done):
        x = np.arange(1, len(done) + 1)
        vers = list(dict.fromkeys(done.prompts_version))
        for v, c in zip(vers, pm.SLOT * 3):
            m = done.prompts_version == v
            ax.scatter(x[m], done.excess_vs_baseline_pct[m], s=18, color=c, alpha=0.45, label=f"prompts {v}")
        ax.plot(x, done.excess_vs_baseline_pct.expanding().mean(), color=pm.INK, lw=1.6, label="running average")
        ax.legend(frameon=False, fontsize=8)
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_xlabel("scored run, in order", fontsize=8.5, color=pm.INK2)
    ax.set_ylabel("agent minus phase 8 baseline, % (same stock, same days)", fontsize=8.5, color=pm.INK2)
    ax.set_title("AI agent team vs phase 8 baseline (simulation)", loc="left", fontsize=10.5, color=pm.INK)
    fig.tight_layout()
    path.parent.mkdir(exist_ok=True)
    fig.savefig(path, dpi=150, facecolor=pm.SURF)
    plt.close(fig)


def save(log, out_dir):
    log = log[LOG_COLS].sort_values("date_time")
    log.to_csv(out_dir / "trade_log.csv", index=False)
    board = scoreboard(log)
    board.round(2).to_csv(out_dir / "scoreboard.csv", index=False)
    # the real record draws into figures/; tests and other output folders keep their chart to themselves
    figure(log, pm.FIGS / "agent_vs_phase8.png" if out_dir == sim.OUT else out_dir / "agent_vs_phase8.png")
    return board


def load_log(out_dir):
    p = out_dir / "trade_log.csv"
    return pd.read_csv(p, dtype={"prompts_version": str}) if p.exists() else pd.DataFrame(columns=LOG_COLS)


def score_run(run_id, boss_file, out_dir, usd, cfg):
    key = json.loads((out_dir / "keys" / f"{run_id}.json").read_text(encoding="utf-8"))
    run_dir = out_dir / "runs" / run_id
    text = boss_file.read_text(encoding="utf-8")
    if boss_file.resolve() != (run_dir / "boss.txt").resolve():
        (run_dir / "boss.txt").write_text(text, encoding="utf-8")      # keep the reply with the run
    row = score(key, parse_decision(text), cfg, usd, out_dir)
    log = load_log(out_dir)
    log = pd.concat([log[log.run_id != run_id], pd.DataFrame([row])], ignore_index=True)
    return row, save(log, out_dir)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_id", nargs="?")
    ap.add_argument("boss_file", nargs="?")
    ap.add_argument("--update", action="store_true", help="re-score runs that were waiting for later prices")
    a = ap.parse_args()
    cfg = sim.config()
    usd = sim.load_market()[0]
    out = sim.OUT
    if a.update:
        todo = load_log(out).query("status == 'pending'").run_id.tolist()
        print(f"{len(todo)} pending run(s)")
        for r in todo:
            score_run(r, out / "runs" / r / "boss.txt", out, usd, cfg)
    elif a.run_id:
        boss = sim.Path(a.boss_file) if a.boss_file else out / "runs" / a.run_id / "boss.txt"
        if not boss.exists():
            raise SystemExit(f"Save the Boss's reply as {boss} first.")
        try:
            row, _ = score_run(a.run_id, boss, out, usd, cfg)
        except DecisionError as e:
            raise SystemExit(f"Not scored: {e}\nFix the Boss's DECISION block (or ask the Boss to redo it) and run again.")
        print(f"{a.run_id}: {row['market']} {row['decision_date']}, {row['boss_decision']} -> simulated {row['action']}")
        print(f"  rules followed: {row['rules_followed']}")
        if row["status"] == "pending":
            print("  pending: the prices after the decision aren't in market.db yet. Run  python agent_score.py --update  later.")
        else:
            f = lambda x: "n/a" if x is None or x != x else f"{x:+.2f}%"
            print(f"  agent {f(row['agent_ret_pct'])} | phase 8 baseline {f(row['baseline_ret_pct'])} | SOXX {f(row['soxx_ret_pct'])}"
                  f" | agent minus baseline {f(row['excess_vs_baseline_pct'])}")
    else:
        raise SystemExit("Give a run id, or --update.")
    board = pd.read_csv(out / "scoreboard.csv")
    pd.set_option("display.width", 200)
    print("\nScoreboard (data/agents/scoreboard.csv):")
    print(board.to_string(index=False) if len(board) else "  no scored runs yet")


if __name__ == "__main__":
    main()
