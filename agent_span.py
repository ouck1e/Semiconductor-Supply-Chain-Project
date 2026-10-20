"""
Time-span simulation: let the six-agent team trade one stock through a period, then watch it in the dashboard.

  python agent_span.py --ticker MU --start 2022-01-03 --end 2022-03-31          plan and cost estimate only
  python agent_span.py --ticker MU --start 2022-01-03 --end 2022-03-31 --yes    run it (Claude API)
  python agent_span.py --resume <sim_id> --yes                                  continue after an interruption
  python agent_span.py --ticker MU --start 2022-01-03 --end 2022-03-31 --manual run it by hand in Claude chats (free)
  python agent_span.py --resume <sim_id>                                        continue a hand run where you stopped

How it trades:
  - While the team holds nothing, it makes a full five-agent decision every `cadence` trading days (default 5,
    weekly), and on the trading day after each exit.
  - A BUY runs on its own rules (next-close fill, stop, target, max hold, checked on closes, with fees), exactly as
    agent_sim.simulate_trade scores every run. So exits are rule-based and visible, and positions never overlap.
  - Each decision sees what the team did earlier in the span (history_text: blind, relative days and percentages only).
  - Each decision is an ordinary scored run (eval_set "sim:<id>"), so it also goes into trade_log.csv and the
    Improvement record. Past dates are blind, as in training.

Writes  data/agents/sims/<sim_id>/sim.json   saved after every decision, so a stopped span can be resumed
By hand (--manual): for each decision the script puts each agent's prompt on the clipboard; paste it into a new
Claude chat, copy the reply, press Enter. Handoffs are filled in for you, and q stops at any point (resume later).
With --yes, the agents run through agent_daily.run_one (Claude API, ANTHROPIC_API_KEY environment variable, monthly budget in
agents/config.json). Simulation only: no broker, no orders.
"""
import argparse
import json
import math
import sys
from datetime import datetime

import pandas as pd

import agent_score
import agent_sim as sim

SIMS = sim.OUT / "sims"


# ---------------------------------------------------------------- what the team remembers
def history_text(decisions, dates, today_i):
    """Earlier decisions in this span, told without dates or prices: 'Day -23' is 23 trading days before today."""
    if not decisions:
        return "None yet: this is the first decision of this simulation."
    pos = {d: i for i, d in enumerate(dates)}
    lines = []
    for k, d in enumerate(decisions):
        day = pos[d["date"]] - today_i
        if d["action"] == "BUY":
            setup = f" ({d['setup']})" if d.get("setup") and d["setup"].lower() != "none" else ""
            sold = pos.get(d.get("exit_date"))
            how = {"stop": "at the stop", "target": "at the target", "time": "at the time limit"}.get(d.get("exit_reason"), d.get("exit_reason", ""))
            lines.append(f"- Day {day}: BUY {d['size']:g}%{setup}, stop -{d['stop']:g}%, target +{d['target']:g}%; "
                         f"sold Day {sold - today_i} {how}, {d['ret']:+.1f}% on the position.")
        else:
            nxt = pos[decisions[k + 1]["date"]] if k + 1 < len(decisions) else today_i
            move = d.get("move_after")
            moved = f"; the stock then moved {move:+.1f}% over the next {nxt - pos[d['date']]} trading days" if move is not None else ""
            lines.append(f"- Day {day}: no trade{moved}.")
    trades = [d for d in decisions if d["action"] == "BUY"]
    won = sum(d["ret"] > 0 for d in trades)
    plural = lambda n, w: f"{n} {w}" + ("" if n == 1 else "s")
    lines.append(f"So far: {plural(len(decisions), 'decision')}, {plural(len(trades), 'trade')} "
                 f"({won} won, {len(trades) - won} lost).")
    return "\n".join(lines)


# ---------------------------------------------------------------- the loop
def trading_days(usd, ticker):
    return [d.strftime("%Y-%m-%d") for d in usd[ticker].dropna().index]


def plan_span(dates, start, end, cfg):
    """Index range of the span; checks that every decision can be scored (max_hold + 1 closes after the end)."""
    a = next((i for i, d in enumerate(dates) if d >= start), None)
    b = max((i for i, d in enumerate(dates) if d <= end), default=None)
    if a is None or b is None or b < a:
        raise SystemExit(f"No trading days between {start} and {end}.")
    need = b + cfg["max_hold_days"] + 1
    if need > len(dates) - 1:
        last_ok = dates[len(dates) - 1 - cfg["max_hold_days"] - 1]
        raise SystemExit(f"The span must end by {last_ok}: every decision needs {cfg['max_hold_days']} later closes to be "
                         f"scored, and prices end on {dates[-1]}. (For days after that, use paper trading.)")
    return a, b


def decision_row(row, run_dir):
    """The parts of a scored run the span needs, with the Boss's actual numbers."""
    d = agent_score.parse_decision((run_dir / "boss.txt").read_text(encoding="utf-8"))
    ts = lambda x: "" if x is None or (isinstance(x, float) and math.isnan(x)) else str(x)[:10]
    return dict(run_id=row["run_id"], action=row["action"], setup=d.get("SETUP", ""), size=d["SIZE_PCT"], stop=d["STOP_PCT"],
                target=d["TARGET_PCT"], hold_days=d["MAX_HOLD_DAYS"], entry_date=ts(row.get("entry_date")),
                exit_date=ts(row.get("exit_date")) if row["action"] == "BUY" else "", exit_reason=row.get("exit_reason", ""),
                ret=float(row.get("agent_ret_pct") or 0.0), status=row.get("status", ""))


def step_span(state, dates, closes, runner, cfg, save=lambda s: None, budget_ok=lambda: True):
    """Run decisions until the span ends or the budget stops it. `runner(date, history, blind)` makes one scored
    decision and returns its decision_row dict. Pure loop logic, so it can be tested with a fake runner."""
    a, b = state["span_index"]
    i = dates.index(state["next_check"]) if state.get("next_check") else a
    while i <= b:
        if not budget_ok():
            state["status"] = "stopped: monthly API budget reached"
            save(state)
            return state
        date = dates[i]
        blind = date < cfg["blind_before"]
        d = runner(date, history_text(state["decisions"], dates, i), blind)
        d["date"] = date
        if state["decisions"] and state["decisions"][-1]["action"] != "BUY":     # how the stock moved after the last skip
            p = dates.index(state["decisions"][-1]["date"])
            state["decisions"][-1]["move_after"] = round(100 * (closes[i] / closes[p] - 1), 2)
        state["decisions"].append(d)
        if d["action"] == "BUY" and d.get("exit_date"):
            i = dates.index(d["exit_date"]) + 1           # look again the trading day after the exit
        else:
            i += state["cadence"]
        state["next_check"] = dates[i] if i < len(dates) else None
        save(state)
    state["status"] = "done"
    save(state)
    return state


# ---------------------------------------------------------------- results
def curves(state, dates, closes, cfg):
    """Daily strategy index (fully in each trade, flat between) vs buy & hold, both 100 at the span's first close,
    plus a portfolio that uses the agents' own position sizes."""
    a, b = state["span_index"]
    end = b                                                  # a paused or stopped span ends where its checks stopped
    if state.get("status") != "done" and state.get("next_check") in dates:
        end = max(a, min(b, dates.index(state["next_check"]) - 1))
    for d in state["decisions"]:
        if d["action"] == "BUY" and d.get("exit_date"):
            end = max(end, dates.index(d["exit_date"]))
    slip, fee = cfg["slippage_pct_per_side"] / 100, cfg["fee_pct_per_side"] / 100
    trades = {dates.index(d["entry_date"]): d for d in state["decisions"] if d["action"] == "BUY" and d.get("entry_date")}
    cash_idx, units = 100.0, 0.0                             # strategy index: all in during each trade
    port_cash, shares = float(cfg["portfolio_usd"]), 0.0     # portfolio: the agents' own position size
    open_trade, out = None, []
    for i in range(a, end + 1):
        px = closes[i]
        if i in trades:                                    # buy at this close (the decision was the close before)
            open_trade = trades[i]
            units = cash_idx * (1 - fee) / (px * (1 + slip)); cash_idx = 0.0
            invest = port_cash * open_trade["size"] / 100   # flat before every entry, so cash is the whole portfolio
            shares = invest * (1 - fee) / (px * (1 + slip)); port_cash -= invest
        if open_trade and dates[i] == open_trade["exit_date"]:   # sell at this close
            cash_idx = units * px * (1 - slip) * (1 - fee); units = 0.0
            port_cash += shares * px * (1 - slip) * (1 - fee); shares = 0.0; open_trade = None
        value, pv = cash_idx + units * px, port_cash + shares * px
        out.append(dict(date=dates[i], close=round(px, 4), strategy=round(value, 4), hold=round(100 * px / closes[a], 4),
                        portfolio=round(pv, 2), in_trade=bool(units)))
    s = pd.Series([o["strategy"] for o in out])
    trades_l = [d for d in state["decisions"] if d["action"] == "BUY"]
    stats = dict(strategy_pct=round(out[-1]["strategy"] - 100, 2) if out else 0, hold_pct=round(out[-1]["hold"] - 100, 2) if out else 0,
                 decisions=len(state["decisions"]), trades=len(trades_l), won=sum(d["ret"] > 0 for d in trades_l),
                 max_drawdown_pct=round(100 * (s / s.cummax() - 1).min(), 2) if len(s) else 0,
                 portfolio_end=out[-1]["portfolio"] if out else cfg["portfolio_usd"])
    stats["vs_hold"] = round(stats["strategy_pct"] - stats["hold_pct"], 2)
    return out, stats


# ---------------------------------------------------------------- command line
def sim_path(sim_id):
    return SIMS / sim_id / "sim.json"


def save_state(state):
    p = sim_path(state["sim_id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=1), encoding="utf-8")


def estimate(state, dates, cfg, out_dir):
    """Most decisions the span can need (every check a skip), the dollars that could cost, and the month so far."""
    a, b = state["span_index"]
    start = dates.index(state["next_check"]) if state.get("next_check") else a
    n = 0 if start > b else math.ceil((b - start + 1) / state["cadence"])
    try:
        import agent_daily
        per, spent = agent_daily.run_cost_guess(out_dir), agent_daily.month_spent(out_dir, datetime.now().strftime("%Y-%m"))
    except Exception:  # noqa: BLE001 - the estimate must still print without the API runner
        per, spent = 1.0, 0.0
    return n, per, spent


def api_runner(state, cfg, market):
    import agent_daily
    try:
        import anthropic
    except ImportError:
        raise SystemExit("The anthropic package is missing: python -m pip install anthropic") from None
    client = anthropic.Anthropic(max_retries=4)

    def run(date, history, blind):
        try:
            row = agent_daily.run_one(state["ticker"], pd.Timestamp(date), cfg, market, client, sim.OUT, blind=blind,
                                      eval_set=f"sim:{state['sim_id']}", history=history)
        except TypeError as e:
            raise SystemExit("agent_daily.run_one doesn't accept blind / eval_set / history yet; update agent_daily.py. "
                             f"({e})") from None
        return decision_row(row, sim.OUT / "runs" / row["run_id"])
    return run


# ---------------------------------------------------------------- by hand, in Claude chats (free)
class Paused(Exception):
    """The person running the agents by hand stopped; the span resumes from the same decision."""


def clipboard_set(path):
    """Put a UTF-8 text file on the clipboard."""
    import subprocess
    if sys.platform == "win32":
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        f"Get-Content -LiteralPath '{path}' -Raw -Encoding UTF8 | Set-Clipboard"],
                       check=True, capture_output=True)
    else:
        import tkinter
        r = tkinter.Tk(); r.withdraw(); r.clipboard_clear(); r.clipboard_append(path.read_text(encoding="utf-8"))
        r.update(); r.destroy()


def clipboard_get():
    import subprocess
    if sys.platform == "win32":
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Clipboard -Raw"],
                             check=True, capture_output=True)
        return out.stdout.decode("utf-8", "replace").replace("\r\n", "\n").strip()
    import tkinter
    r = tkinter.Tk(); r.withdraw()
    try:
        return r.clipboard_get().strip()
    finally:
        r.destroy()


HAND_STAGES = [(1, "1_researcher", "Researcher", "reply_1.txt"), (2, "2_news_analyst", "News Analyst", "reply_2.txt"),
               (3, "3_strategist", "Strategist", "reply_3.txt"), (5, "5_risk_manager", "Risk Manager", "reply_5.txt"),
               (6, "6_boss", "Boss", "boss.txt")]


def check_reply(n, text, prompt):
    """Why a copied reply can't be used yet, or '' when it can."""
    import re
    if len(text) < 40:
        return "the clipboard is (nearly) empty"
    if text.strip() == prompt.strip() or text.startswith(prompt[:200]):
        return "the clipboard still holds the prompt, not the agent's reply"
    if n < 6 and not re.search(r"^\W*AGENT:", text, re.M):
        return "the reply has no handoff block (a line starting with AGENT:); copy the whole reply"
    if n == 6:
        try:
            agent_score.parse_decision(text)
        except agent_score.DecisionError as e:
            return (f"the Boss's DECISION block can't be read ({e}). In the Boss's chat, ask: \"Please repeat your "
                    "DECISION block exactly in the required format.\" Then copy that reply (it is added to the first)")
    return ""


def walk_by_hand(run_dir, label, ask=input, say=print, clip_set=clipboard_set, clip_get=clipboard_get):
    """Take one packet through the agents by hand: each prompt goes onto the clipboard, the person pastes it into a
    new Claude chat, copies the reply, and presses Enter. Replies saved earlier are skipped, so it resumes mid-way."""
    import agent_handoff
    for n, stage, name, reply in HAND_STAGES:
        out = run_dir / reply
        if out.exists():
            continue
        prompt_file = run_dir / f"{stage}.txt" if n == 1 else agent_handoff.fill(n, run_dir)
        prompt = prompt_file.read_text(encoding="utf-8")
        try:
            clip_set(prompt_file)
            say(f"\n{label} | {name}: the prompt is on your clipboard. Open a NEW Claude chat, paste it (Ctrl+V), send,")
            say("  then click Copy under the whole reply and come back here.")
        except Exception:  # noqa: BLE001 - clipboard trouble shouldn't stop a free run
            clip_get = None
            say(f"\n{label} | {name}: open {prompt_file} and paste all of it into a NEW Claude chat. Save the reply as {out}.")
        kept = ""                          # a first Boss reply whose DECISION block needs a fix
        while True:
            if ask("  Press Enter when the reply is copied (q to stop for now): ").strip().lower() == "q":
                raise Paused()
            got = clip_get() if clip_get else (out.read_text(encoding="utf-8") if out.exists() else "")
            text = f"{kept}\n\n{got}".strip() if kept and got != kept else got
            why = check_reply(n, text, prompt)
            if not why:
                break
            if n == 6 and "DECISION block" in why and not kept:
                kept = got
            say(f"  Not yet: {why}.")
        out.write_text(text, encoding="utf-8")


def hand_runner(state, cfg, market, save=None, **walk):
    """Runs each decision by hand in Claude chats: free, but about five pastes a decision. A stop (q) keeps the
    packet, so --resume carries on with the same decision."""
    import agent_packets
    save = save or save_state

    def run(date, history, blind):
        p = state.get("pending")
        if not (p and p["date"] == date):
            run_id, run_dir, _ = agent_packets.build(state["ticker"], pd.Timestamp(date), blind, cfg, market, out_dir=sim.OUT,
                                                     runner="manual chat (span)", eval_set=f"sim:{state['sim_id']}",
                                                     history=history)
            state["pending"] = p = dict(date=date, run_id=run_id)
            save(state)
        run_dir = sim.OUT / "runs" / p["run_id"]
        k = len(state["decisions"]) + 1
        walk_by_hand(run_dir, f"Check {k} ({date})", **walk)
        row, _ = agent_score.score_run(p["run_id"], run_dir / "boss.txt", sim.OUT, market[0], cfg)
        state["pending"] = None
        d = decision_row(row, run_dir)
        print(f"  Scored {p['run_id']}: {d['action']}" + (f", exit {d['exit_date']} ({d['exit_reason']}), {d['ret']:+.2f}%"
                                                         if d["action"] == "BUY" else ""))
        return d
    return run


def demo_runner(state, cfg, usd):
    """A stand-in for the agents, so the dashboard's Simulations tab can be tried without an API key: buy a pullback
    (close above its 50-day average but below its 5-day-ago close), stop -7%, target +12%, 20 days. It is a simple
    rule, not the agents; demo sims are labelled as such and never go into the trade log."""
    s = usd[state["ticker"]].dropna()

    def run(date, history, blind):
        D = pd.Timestamp(date)
        h = s[s.index <= D]
        up = len(h) > 50 and h.iloc[-1] > h.iloc[-50:].mean()
        dip = len(h) > 5 and h.iloc[-1] < h.iloc[-6]
        if up and dip:
            o = sim.simulate_trade(s, D, "BUY", 5, 7, 12, 20, cfg)
            return dict(run_id="", action="BUY", setup="demo rule: pullback in uptrend", size=5, stop=7, target=12,
                        hold_days=20, entry_date=str(o["entry_date"])[:10], exit_date=str(o["exit_date"])[:10],
                        exit_reason=o["exit_reason"], ret=round(o["ret_pct"], 3), status=o["status"],
                        reason="Close is above its 50-day average and below where it was 5 days ago: a pullback in an uptrend.")
        why = "below its 50-day average (no uptrend)" if not up else "no pullback over the last 5 days"
        return dict(run_id="", action="NO TRADE", setup="none", size=0, stop=0, target=0, hold_days=0, entry_date="",
                    exit_date="", exit_reason="no position", ret=0.0, status="scored", reason=f"No trade: {why}.")
    return run


def finish(state, dates, closes, cfg):
    stats = curves(state, dates, closes, cfg)[1]
    state["stats"] = stats
    save_state(state)
    return stats


def run_by_hand(state, dates, closes, cfg, market):
    a, b = state["span_index"]
    start = dates.index(state["next_check"]) if state.get("next_check") else a
    n = 0 if start > b else math.ceil((b - start + 1) / state["cadence"])
    print(f"{state['sim_id']}: {state['company']} ({state['ticker']}), {state['start']} to {state['end']}, by hand (free).")
    print(f"  {len(state['decisions'])} decisions done, at most {n} to go (fewer when trades are open), five agents each.")
    print("  Tips: a new chat for every agent; turn web search off so the agents can't look up the real stock;")
    print("  type q at any prompt to stop, then continue with: python agent_span.py --resume " + state["sim_id"])
    state["status"] = "running"
    save_state(state)
    try:
        step_span(state, dates, closes, hand_runner(state, cfg, market), cfg, save=save_state)
    except Paused:
        state["status"] = "paused"
        stats = finish(state, dates, closes, cfg)
        print(f"\nPaused after {stats['decisions']} decisions. Continue: python agent_span.py --resume {state['sim_id']}")
        print("The dashboard can already show the part done so far: python agent_dashboard.py")
        return
    stats = finish(state, dates, closes, cfg)
    print(f"\nDone: {stats['decisions']} decisions, {stats['trades']} trades ({stats['won']} won); strategy "
          f"{stats['strategy_pct']:+.2f}% vs buy & hold {stats['hold_pct']:+.2f}%. Rebuild the dashboard: python agent_dashboard.py")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo", action="store_true", help="run a simple rule instead of the agents (free, labelled DEMO)")
    ap.add_argument("--ticker")
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--cadence", type=int, default=5, help="trading days between checks while flat (default 5)")
    ap.add_argument("--resume", metavar="SIM_ID")
    ap.add_argument("--yes", action="store_true", help="actually run (spends API credit); without it, only the plan")
    ap.add_argument("--manual", action="store_true", help="run the agents by hand in Claude chats (free)")
    a = ap.parse_args()
    cfg = sim.config()
    market = sim.load_market()
    usd = market[0]
    if a.resume:
        state = json.loads(sim_path(a.resume).read_text(encoding="utf-8"))
        if state.get("status") == "done":
            raise SystemExit(f"{a.resume} is already finished.")
    else:
        if not (a.ticker and a.start and a.end):
            raise SystemExit("Give --ticker, --start and --end (or --resume SIM_ID).")
        if a.ticker not in usd:
            raise SystemExit(f"Unknown ticker {a.ticker}.")
        dates = trading_days(usd, a.ticker)
        idx = plan_span(dates, a.start, a.end, cfg)
        info = market[2].set_index("ticker").loc[a.ticker]
        sim_id = f"{'demo' if a.demo else 'hand' if a.manual else 'sim'}-{datetime.now():%Y%m%d-%H%M%S}-{a.ticker.split('.')[0].lower()}"
        state = dict(sim_id=sim_id, ticker=a.ticker, company=info["name"], start=dates[idx[0]], end=dates[idx[1]],
                     span_index=list(idx), cadence=a.cadence, prompts_version="demo" if a.demo else sim.prompts_version(),
                     runner="DEMO rule (not the agents)" if a.demo else "by hand in Claude chats" if a.manual else "Claude API",
                     demo=a.demo, manual=a.manual,
                     created=datetime.now().isoformat(timespec="seconds"), status="new", next_check=None, decisions=[])
    dates = trading_days(usd, state["ticker"])
    closes = usd[state["ticker"]].dropna().tolist()
    if state.get("demo"):
        state["status"] = "running"
        step_span(state, dates, closes, demo_runner(state, cfg, usd), cfg, save=save_state)
        state["stats"] = curves(state, dates, closes, cfg)[1]
        save_state(state)
        st = state["stats"]
        print(f"DEMO {state['sim_id']} ({state['company']}): {st['decisions']} checks, {st['trades']} trades by the demo rule; "
              f"{st['strategy_pct']:+.2f}% vs buy & hold {st['hold_pct']:+.2f}%. Not the agents. Rebuild: python agent_dashboard.py")
        return
    if state.get("manual"):
        return run_by_hand(state, dates, closes, cfg, market)
    n, per, spent = estimate(state, dates, cfg, sim.OUT)
    budget = cfg.get("automation", {}).get("monthly_budget_usd")
    print(f"{state['sim_id']}: {state['company']} ({state['ticker']}), {state['start']} to {state['end']}, "
          f"{state['span_index'][1] - state['span_index'][0] + 1} trading days, a check every {state['cadence']} days while flat")
    print(f"  prompt version {state['prompts_version']}; decisions are blind before {cfg['blind_before']}")
    if state["start"] >= cfg["splits"]["test"][0]:
        print("  note: this span is in the test years; fine to watch, but don't tune prompts on what you see")
    print(f"  at most {n} decisions (fewer when trades are open), roughly ${n * per:.2f} at ${per:.2f} each; "
          f"spent this month ${spent:.2f}" + (f" of ${budget:.0f}" if budget else ""))
    if not a.yes:
        print("Nothing was run. Add --yes to run it.")
        return
    state["status"] = "running"
    save_state(state)

    def budget_ok():
        if not budget:
            return True
        _, per_now, spent_now = estimate(state, dates, cfg, sim.OUT)
        return spent_now + per_now <= budget

    step_span(state, dates, closes, api_runner(state, cfg, market), cfg, save=save_state, budget_ok=budget_ok)
    curve, stats = curves(state, dates, closes, cfg)
    state["stats"] = stats
    save_state(state)
    print(f"{state['status']}: {stats['decisions']} decisions, {stats['trades']} trades ({stats['won']} won); strategy "
          f"{stats['strategy_pct']:+.2f}% vs buy & hold {stats['hold_pct']:+.2f}%. Rebuild the dashboard: python agent_dashboard.py")


if __name__ == "__main__":
    sys.exit(main())
