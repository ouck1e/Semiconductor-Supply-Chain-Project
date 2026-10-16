# Agent team prompt versions

Each version is the short hash of `agents/prompts/` that `agent_sim.prompts_version()` stamps on every run. A new
version starts a new line on the scoreboard. Tune on **dev** dates only; the **exam** set (test dates) is scored only
at the end of a round of changes.

| Version | Name | Date |
|---|---|---|
| `42c55623` | v1 | 2026-10-15 |
| `fea4d1f9` | v2 | 2026-10-15 |
| `50302f80` | v2.5 | 2026-10-15 |
| `7108011e` | v3 | 2026-10-15 |
| `8915d28d` | v4 | 2026-10-16 |
| `eeeb0ee8` | v5 | 2026-10-16 |

## v1 `42c55623`
First version: six roles in our own words after the SebAI guide; Boss ends with a machine-readable DECISION block.
One run (Air Products 2021, NO TRADE). Found: no credit for good skips, a dev-years baseline result leaked into early
packets, agents mislabelled the next agent.

## v2 `fea4d1f9`
Team order in the shared rules; the Strategist hands to Agent 5; Boss confidence field matches the Researcher's score.
Scorer: compare with holding the stock (good skips); baseline note only after the dev years.
Five runs: all NO TRADE. Risk Managers vetoed both BUY plans, often for "no backtest" or "no headlines", which a
manual blind run can never have.

## v2.5 `50302f80`
Headlines in blind runs and backtests in manual runs are N/A BY DESIGN. Risk Manager gets REQUIRED vs CONTEXT items
and a 1.5 reward-to-risk floor after costs. Strategist entries cannot wait on Day 1.
Five runs: all NO TRADE. Bug: a REQUIRED check asks the Risk Manager to compare with the Researcher's numbers, but it
is not given the Researcher's handoff.

## v3 `7108011e`
Strategist ends with a PLAN block, so every veto can be graded (`plan_*`, `vetoed`, `veto_right` in the trade log).
Practice set, 8 dev stocks: 3 BUY plans; 1 approved (SK hynix 2019, stopped out -8.9%), 1 rejected at 1.38
reward-to-risk (TSMC 2021, would have made +8.2%), 1 INCOMPLETE because of the Researcher-handoff bug (MediaTek 2019,
would have made +15.5%). Two skips in strong rises (Applied Materials 2020 +15.1%, Air Products 2022 +18.9%).

## v4 `8915d28d`
Changes, all from the v3 practice results (dev only):
- **Bug fix:** the Risk Manager now receives the Researcher's handoff as well as the Strategist's.
- **Skipping is not free:** the Strategist and Risk Manager are told every decision is scored against holding the
  stock, so sitting out a rise is as much a mistake as buying before a fall; vetoes need a concrete reason.
- **Approved skip label:** a NO TRADE the Risk Manager agrees with is APPROVE FOR SIMULATION ONLY / NO TRADE.
- **Data (code, not prompts):** zero-volume days count as missing instead of showing as 0.00x volume.
- Deliberately unchanged: the 1.5 reward-to-risk floor (one rejected winner is not enough evidence to move it).

Practice set (same 8 stocks as v3): 5 BUY plans, 3 approved: MediaTek 2019 +15.5% (the bug fix let it through),
SUMCO 2018 +1.0%, SK hynix 2019 -8.9% (same loss as v3). Average per decision +0.96% (v3 -1.11%); average vs holding
the stock -5.32 (v3 -7.39). Two plans died at REVISE although the Risk Manager wrote the exact fix (TSMC 2021, would
have made +8.2%; Shin-Etsu 2021). Five plans so far missed the 1.5 floor at 1.34-1.47: Strategists aim for 1.5
before costs, the Risk Manager measures after costs. The two big skips (Applied Materials 2020, Air Products 2022) were
below all their averages on Day 0, so calling them mistakes would be hindsight; no change for them.

## v5 `eeeb0ee8`
Changes, all from the v4 practice results (dev only):
- **Same formula on both sides:** the Strategist shows reward-to-risk before and after costs, using the Risk Manager's
  after-cost formula, and picks levels that clear 1.5 after costs (or says none do).
- **REVISE can be completed:** if the Risk Manager writes one exact fix that would earn approval, the Boss may apply it
  and approve, quoting it in a new `APPLIED_FIX` field. The scorer accepts a BUY after REVISE only with `APPLIED_FIX`.
