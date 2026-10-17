"""
Summarise every scored agent run: what each agent concluded and why, what the team decided, and what happened.

  python agent_report.py

Reads   data/agents/trade_log.csv, data/agents/keys/*.json, the replies saved in data/agents/runs/<run_id>/,
        agents/CHANGELOG.md
Writes  data/agents/run_summaries.csv   one row per run: decision, plan, outcome and each agent's handoff summary
        data/agents/report_data.json    the same plus per-version totals and the changelog, for the report page
        figures/agent_training.png      practice and exam results by prompt version
"""
import json
import re

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import agent_sim as sim
import phase8_market_models as pm

RUNS = sim.OUT / "runs"


def summary(run_dir, name, limit=480):
    """The HANDOFF SUMMARY an agent wrote, trimmed for the page."""
    p = run_dir / name
    if not p.exists():
        return ""
    m = re.findall(r"^\**HANDOFF SUMMARY:?\**\s*(.+?)(?:\n\s*\n|\n[A-Z ]{4,}\n|\Z)", p.read_text(encoding="utf-8"),
                   re.M | re.S)
    if not m:
        return ""
    text = " ".join(m[-1].split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "..."


def versions():
    """Version hash -> short name, from the table at the top of agents/CHANGELOG.md."""
    text = (sim.AGENTS / "CHANGELOG.md").read_text(encoding="utf-8")
    names = dict(re.findall(r"^\| `([0-9a-f]{8})` \| (v[\d.]+) \|", text, re.M))
    sections = re.split(r"^## ", text, flags=re.M)[1:]
    log = []
    for s in sections:
        head, _, body = s.partition("\n")
        log.append(dict(title=head.strip().replace("`", ""), body=body.strip()))
    return names, log


def main():
    names, changelog = versions()
    log = pd.read_csv(sim.OUT / "trade_log.csv", dtype={"prompts_version": str})
    log = log[log.status == "scored"].copy()
    rows = []
    for r in log.itertuples():
        key = json.loads((sim.OUT / "keys" / f"{r.run_id}.json").read_text(encoding="utf-8"))
        d = RUNS / r.run_id
        rows.append(dict(
            run_id=r.run_id, version=names.get(r.prompts_version, r.prompts_version), prompts_version=r.prompts_version,
            eval_set=r.eval_set if isinstance(r.eval_set, str) else "", split=r.split, ticker=r.market,
            company=key["name"], decision_date=r.decision_date, plan_action=r.plan_action, plan_size=r.plan_size_pct,
            plan_stop=r.plan_stop_pct, plan_target=r.plan_target_pct, risk_decision=r.risk_decision,
            final=r.boss_decision, action=r.action, agent_ret=r.agent_ret_pct, hold_ret=r.stock_hold_ret_pct,
            vs_hold=r.vs_buy_and_hold_pct, vs_baseline=r.excess_vs_baseline_pct, plan_ret=r.plan_ret_pct,
            vetoed=r.vetoed, veto_right=r.veto_right, exit_reason=r.exit_reason,
            researcher=summary(d, "reply_1.txt"), strategist=summary(d, "reply_3.txt"),
            risk_manager=summary(d, "reply_5.txt"), boss=summary(d, "boss.txt")))
    df = pd.DataFrame(rows).sort_values(["decision_date", "version"])
    df.to_csv(sim.OUT / "run_summaries.csv", index=False)

    fixed = df[df.eval_set.isin(["practice", "exam"])]
    totals = (fixed.groupby(["eval_set", "version"])
              .agg(runs=("run_id", "count"), plans=("plan_action", lambda a: int((a == "BUY").sum())),
                   buys=("action", lambda a: int((a == "BUY").sum())), avg_agent=("agent_ret", "mean"),
                   avg_hold=("hold_ret", "mean"), avg_vs_hold=("vs_hold", "mean"),
                   avg_vs_baseline=("vs_baseline", "mean"),
                   wins=("agent_ret", lambda x: int((x > 0).sum())), losses=("agent_ret", lambda x: int((x < 0).sum())))
              .reset_index())
    vet = df[df.vetoed == "yes"]
    vetoes = (vet.groupby("version").agg(vetoes=("run_id", "count"), right=("veto_right", lambda v: int((v == "yes").sum())),
                                         saved=("plan_ret", lambda x: float(-x.sum())))
              .reset_index())
    clean = lambda o: None if isinstance(o, float) and np.isnan(o) else o
    data = dict(runs=[{k: clean(v) for k, v in row.items()} for row in df.to_dict("records")],
                totals=[{k: clean(v) for k, v in row.items()} for row in totals.round(3).to_dict("records")],
                vetoes=vetoes.round(3).to_dict("records"), changelog=changelog,
                baseline=pd.read_csv(sim.OUT / "baseline_stats.csv").round(2).to_dict("records"))
    (sim.OUT / "report_data.json").write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")

    # figure for the repo: practice by version, exam v3 vs v5
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2), facecolor=pm.SURF)
    for ax, (setname, title) in zip(axes, (("practice", "Practice set (8 dev stocks)"), ("exam", "Exam set (8 test stocks)"))):
        pm.style(ax, grid="y")
        t = totals[totals.eval_set == setname]
        x = np.arange(len(t))
        ax.bar(x - 0.18, t.avg_agent, 0.36, color=pm.SLOT[0], label="team, average per decision")
        ax.bar(x + 0.18, t.avg_vs_hold, 0.36, color=pm.SLOT[1], label="team minus holding the stock")
        ax.axhline(0, color=pm.INK2, lw=1)
        ax.set_xticks(x, t.version)
        ax.set_title(title, loc="left", fontsize=10, color=pm.INK)
        ax.set_ylabel("% over the holding period", fontsize=8.5, color=pm.INK2)
    axes[0].legend(frameon=False, fontsize=8)
    fig.suptitle("AI agent team by prompt version (simulation, same stocks for every version)", x=0.01, ha="left",
                 fontsize=10.5, color=pm.INK)
    fig.tight_layout()
    fig.savefig(pm.FIGS / "agent_training.png", dpi=150, facecolor=pm.SURF)
    plt.close(fig)
    pd.set_option("display.width", 200)
    print(totals.round(2).to_string(index=False))
    print(vetoes.round(2).to_string(index=False))
    print(f"Wrote data/agents/run_summaries.csv ({len(df)} runs), report_data.json, figures/agent_training.png")


if __name__ == "__main__":
    main()
