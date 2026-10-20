"""
Daily paper trading: run the six-agent team through the Claude API, one forward decision per watchlist stock, dated at
the latest close, and score each run (it stays "pending" until later prices close it).

  python agent_daily.py                  every stock on the watchlist (agents/config.json "automation")
  python agent_daily.py --ticker MU      one stock (it need not be on the watchlist)

Each run is built and scored exactly like a manual one: agent_packets.build() writes the prompts (named, since the date
is after "blind_before"), each agent's reply is saved as reply_N.txt and handed on with agent_handoff.fill(), the
Boss's reply is saved as boss.txt and scored with agent_score.score_run(). The Coder is skipped, as in manual runs.

Skips a stock that already has a run for its latest close, or that still has an open BUY paper trade (no stacking).
Refuses dates before "blind_before", so the practice and exam sets are never touched.
Logs every API call (tokens and dollars) to data/agents/api_usage.csv and stops before going over monthly_budget_usd.
Needs the ANTHROPIC_API_KEY environment variable (a GitHub secret in the scheduled job). It is never read from a file.

Simulation only: this script talks to the Claude API and nothing else. No broker, no orders.
"""
import argparse
import os
from datetime import datetime

import pandas as pd

import agent_handoff
import agent_packets
import agent_score
import agent_sim as sim

STAGES = [(1, "1_researcher"), (2, "2_news_analyst"), (3, "3_strategist"), (5, "5_risk_manager"), (6, "6_boss")]
USAGE_COLS = ["date_time", "run_id", "ticker", "decision_date", "stage", "model", "served_by", "input_tokens",
              "output_tokens", "cost_usd", "stop_reason", "note"]
FIRST_RUN_GUESS_USD = 1.0       # what the budget check assumes a run costs before any run has been logged
FIX_BLOCK = ("The scoring script could not read your DECISION block: {err}\n"
             "Reply with only the corrected block, from DECISION to END DECISION, with the same decision.")


class RunFailed(Exception):
    pass


# ---------------------------------------------------------------- records
def usage_path(out_dir):
    return out_dir / "api_usage.csv"


def load_usage(out_dir):
    p = usage_path(out_dir)
    return pd.read_csv(p) if p.exists() else pd.DataFrame(columns=USAGE_COLS)


def log_usage(out_dir, rows):
    if rows:
        u = pd.concat([load_usage(out_dir), pd.DataFrame(rows)], ignore_index=True)
        u.reindex(columns=USAGE_COLS).to_csv(usage_path(out_dir), index=False)


def month_spent(out_dir, month):
    u = load_usage(out_dir)
    return float(u[u.date_time.astype(str).str.startswith(month)].cost_usd.sum()) if len(u) else 0.0


def run_cost_guess(out_dir):
    """Average dollars per run so far (the most expensive guess while there is no history)."""
    u = load_usage(out_dir)
    return float(u.groupby("run_id").cost_usd.sum().mean()) if len(u) else FIRST_RUN_GUESS_USD


def cost(auto, model, usage):
    price_in, price_out = auto["usd_per_million_tokens"].get(model, max(auto["usd_per_million_tokens"].values()))
    return (usage.input_tokens * price_in + usage.output_tokens * price_out) / 1e6


def runner_label(auto):
    models = list(dict.fromkeys(auto["models"].values()))
    return f"Claude API daily ({', '.join(models)}, effort {auto['effort']})"


# ---------------------------------------------------------------- one API call = one pasted prompt
def ask(client, auto, stage, messages, usage_rows, base):
    """Send one agent its prompt (and, for a fix, the conversation so far). Returns (reply text, content blocks)."""
    model = auto["models"][stage]
    r = client.beta.messages.create(
        model=model, max_tokens=auto["max_tokens"], output_config={"effort": auto["effort"]}, messages=messages,
        # on a rare safety decline the API re-runs the call on a fallback model; served_by records which one answered
        betas=["server-side-fallback-2026-07-01"], fallbacks="default")
    text = "\n".join(b.text for b in r.content if b.type == "text").strip()
    usage_rows.append(dict(base, date_time=datetime.now().isoformat(timespec="seconds"), stage=stage, model=model,
                           served_by=r.model, input_tokens=r.usage.input_tokens, output_tokens=r.usage.output_tokens,
                           cost_usd=round(cost(auto, r.model, r.usage), 5), stop_reason=r.stop_reason, note=""))
    if r.stop_reason == "refusal":
        raise RunFailed(f"{stage}: the model declined to answer")
    if r.stop_reason == "max_tokens":
        raise RunFailed(f"{stage}: reply cut off at max_tokens ({auto['max_tokens']})")
    return text, r.content


# ---------------------------------------------------------------- which stocks run today
def decision_date(usd, t, cfg):
    """The stock's latest close, if it is a forward date and the prices are current; else None with a reason."""
    s = usd[t].dropna()
    D = s.index[-1]
    if D < pd.Timestamp(cfg["blind_before"]):
        return None, f"latest close {D.date()} is before blind_before {cfg['blind_before']}; forward runs only"
    if D < usd.index.max() - pd.Timedelta(days=7):
        return None, f"latest close {D.date()} is more than a week old; prices look stale"
    return D, ""


def skip_reason(t, D, log):
    mine = log[log.market == t]
    if (mine.decision_date.astype(str) == str(D.date())).any():
        return f"already has a run for {D.date()}"
    if ((mine.status == "pending") & (mine.action == "BUY")).any():
        return "has an open BUY paper trade"
    return ""


# ---------------------------------------------------------------- one run
def run_one(t, D, cfg, market, client, out_dir, blind=False, eval_set="", history=""):
    """Build the packet, run the five agents in order, score the Boss's decision. Returns the trade-log row.
    blind, eval_set and history are for other callers (agent_span.py); the daily run uses the defaults."""
    auto = cfg["automation"]
    run_id, run_dir, key = agent_packets.build(t, D, blind, cfg, market, out_dir=out_dir, runner=runner_label(auto),
                                               eval_set=eval_set, history=history)
    base = dict(run_id=run_id, ticker=t, decision_date=key["decision_date"])
    usage = []
    try:
        for n, stage in STAGES:
            prompt = run_dir / f"{stage}.txt"
            if n > 1:
                try:
                    prompt = agent_handoff.fill(n, run_dir)
                except SystemExit as e:          # agent_handoff stops when a reply has no handoff block
                    raise RunFailed(str(e)) from None
            messages = [{"role": "user", "content": prompt.read_text(encoding="utf-8")}]
            text, content = ask(client, auto, stage, messages, usage, base)
            if n < 6:
                (run_dir / f"reply_{n}.txt").write_text(text, encoding="utf-8")
                continue
            try:
                agent_score.parse_decision(text)
            except agent_score.DecisionError as e:
                # one chance to fix the block, in the same conversation; the scorer reads the last DECISION block
                messages += [{"role": "assistant", "content": content},
                             {"role": "user", "content": FIX_BLOCK.format(err=e)}]
                fix, _ = ask(client, auto, stage, messages, usage, base)
                text = f"{text}\n\n{fix}"
            (run_dir / "boss.txt").write_text(text, encoding="utf-8")
        try:
            row, _ = agent_score.score_run(run_id, run_dir / "boss.txt", out_dir, market[0], cfg)
        except agent_score.DecisionError as e:
            raise RunFailed(f"Boss's DECISION block still unreadable after one fix: {e}") from None
        return row
    except RunFailed as e:
        usage.append(dict(base, date_time=datetime.now().isoformat(timespec="seconds"), stage="failed",
                          cost_usd=0.0, note=str(e)))
        raise
    finally:
        log_usage(out_dir, usage)


# ---------------------------------------------------------------- the day's runs
def run_day(tickers, cfg, market, client, out_dir, today=None):
    """Run every ticker that is due. Returns a list of (ticker, outcome text)."""
    auto = cfg["automation"]
    month = (today or datetime.now()).strftime("%Y-%m")
    usd = market[0]
    results = []
    for t in tickers:
        if t not in usd:
            results.append((t, "skipped: not in market.db"))
            continue
        D, why = decision_date(usd, t, cfg)
        why = why or skip_reason(t, D, agent_score.load_log(out_dir))
        if why:
            results.append((t, f"skipped: {why}"))
            continue
        spent, guess = month_spent(out_dir, month), run_cost_guess(out_dir)
        if spent + guess > auto["monthly_budget_usd"]:
            results.append((t, f"stopped: ${spent:.2f} spent in {month}; another run (about ${guess:.2f}) "
                               f"could pass the ${auto['monthly_budget_usd']} monthly budget"))
            break
        try:
            row = run_one(t, D, cfg, market, client, out_dir)
            results.append((t, f"{row['run_id']} {D.date()}: {row['boss_decision']} -> {row['action']} ({row['status']})"))
        except RunFailed as e:
            results.append((t, f"failed, not scored: {e}"))
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ticker", help="run one stock instead of the watchlist")
    a = ap.parse_args()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("No ANTHROPIC_API_KEY set, so no agent runs today. Set it as a Windows user environment variable "
              "(locally) or as the repository secret ANTHROPIC_API_KEY (GitHub Actions). Never put it in a file here.")
        return
    import anthropic
    cfg = sim.config()
    client = anthropic.Anthropic(max_retries=4)
    market = sim.load_market()
    tickers = [a.ticker] if a.ticker else cfg["automation"]["watchlist"]
    for t, outcome in run_day(tickers, cfg, market, client, sim.OUT):
        print(f"{t}: {outcome}")
    month = datetime.now().strftime("%Y-%m")
    print(f"API spend {month}: ${month_spent(sim.OUT, month):.2f} of ${cfg['automation']['monthly_budget_usd']} "
          f"(data/agents/api_usage.csv)")


if __name__ == "__main__":
    main()
