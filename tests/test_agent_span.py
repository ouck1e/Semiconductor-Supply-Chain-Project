"""Tests for the time-span simulator (agent_span.py). No API calls: the agents are replaced by a fake runner."""
import re
import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent_sim as sim      # noqa: E402
import agent_span as span    # noqa: E402

CFG = {"max_hold_days": 20, "blind_before": "2026-07-01", "fee_pct_per_side": 0.1, "slippage_pct_per_side": 0.1,
       "portfolio_usd": 100000}
DATES = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2021-01-04", periods=120)]
CLOSES = [100 + i * 0.5 for i in range(len(DATES))]


def fake_runner(buy_on=(), hold=6, calls=None):
    """BUY on the listed decision numbers (0-based), exiting `hold` trading days after the next-close entry."""
    def run(date, history, blind):
        n = len(calls)
        calls.append(dict(date=date, history=history, blind=blind))
        if n in buy_on:
            i = DATES.index(date)
            return dict(run_id=f"r{n}", action="BUY", setup="pullback", size=5, stop=7, target=12, hold_days=20,
                        entry_date=DATES[i + 1], exit_date=DATES[i + 1 + hold], exit_reason="target", ret=11.0, status="scored")
        return dict(run_id=f"r{n}", action="NO TRADE", setup="none", size=0, stop=0, target=0, hold_days=0,
                    entry_date="", exit_date="", exit_reason="no position", ret=0.0, status="scored")
    return run


def new_state(a=0, b=40, cadence=5):
    return dict(sim_id="t", ticker="X", span_index=[a, b], cadence=cadence, next_check=None, decisions=[], status="new")


class Loop(unittest.TestCase):
    def test_weekly_checks_while_flat(self):
        calls = []
        s = span.step_span(new_state(), DATES, CLOSES, fake_runner(calls=calls), CFG)
        idx = [DATES.index(c["date"]) for c in calls]
        self.assertEqual(idx, list(range(0, 41, 5)))
        self.assertEqual(s["status"], "done")

    def test_after_a_trade_it_looks_again_the_day_after_the_exit_and_never_overlaps(self):
        calls = []
        s = span.step_span(new_state(), DATES, CLOSES, fake_runner(buy_on=(1,), hold=6, calls=calls), CFG)
        idx = [DATES.index(c["date"]) for c in calls]
        # decision 1 on day 5 buys at day 6 and exits at day 12; the next check is day 13
        self.assertEqual(idx[:3], [0, 5, 13])
        trade = s["decisions"][1]
        for d in s["decisions"][2:]:
            self.assertGreater(d["date"], trade["exit_date"])

    def test_resume_after_a_budget_stop_continues_where_it_stopped(self):
        calls, n = [], {"ok": 2}
        def budget_ok():
            n["ok"] -= 1
            return n["ok"] >= 0
        s = span.step_span(new_state(), DATES, CLOSES, fake_runner(calls=calls), CFG, budget_ok=budget_ok)
        self.assertTrue(s["status"].startswith("stopped"))
        self.assertEqual(len(s["decisions"]), 2)
        s = span.step_span(s, DATES, CLOSES, fake_runner(calls=calls), CFG)
        self.assertEqual([d["date"] for d in s["decisions"]], [DATES[i] for i in range(0, 41, 5)])

    def test_span_must_leave_room_to_score_the_last_decision(self):
        with self.assertRaises(SystemExit):
            span.plan_span(DATES, DATES[0], DATES[-5], CFG)
        self.assertEqual(span.plan_span(DATES, DATES[0], DATES[40], CFG), (0, 40))


class History(unittest.TestCase):
    def test_history_is_blind_and_complete(self):
        calls = []
        span.step_span(new_state(), DATES, CLOSES, fake_runner(buy_on=(1,), calls=calls), CFG)
        last = calls[-1]["history"]
        self.assertIn("BUY 5% (pullback), stop -7%, target +12%", last)
        self.assertIn("at the target, +11.0%", last)
        self.assertIn("no trade; the stock then moved", last)
        self.assertRegex(last, r"Day -\d+")
        self.assertEqual(re.findall(r"\b(19|20)\d\d\b", last), [], "a year leaked into the history")
        self.assertNotIn("$", last)
        self.assertIn("first decision", calls[0]["history"])

    def test_decisions_before_blind_before_are_blind(self):
        calls = []
        span.step_span(new_state(b=10), DATES, CLOSES, fake_runner(calls=calls), CFG)
        self.assertTrue(all(c["blind"] for c in calls))


class Curves(unittest.TestCase):
    def test_strategy_is_flat_without_trades_and_tracks_one_trade(self):
        s = span.step_span(new_state(), DATES, CLOSES, fake_runner(calls=[]), CFG)
        out, st = span.curves(s, DATES, CLOSES, CFG)
        self.assertTrue(all(o["strategy"] == 100 for o in out))
        self.assertAlmostEqual(st["hold_pct"], 100 * (CLOSES[40] / CLOSES[0] - 1), places=2)
        s = span.step_span(new_state(), DATES, CLOSES, fake_runner(buy_on=(1,), hold=6, calls=[]), CFG)
        out, st = span.curves(s, DATES, CLOSES, CFG)
        gross = CLOSES[12] / CLOSES[6]
        self.assertAlmostEqual(st["strategy_pct"], 100 * (gross * 0.999 * 0.999 / 1.001 * 0.999 - 1), places=2)
        self.assertEqual(st["trades"], 1)
        self.assertLess(out[-1]["portfolio"], 100000 * 1.01)        # a 5% position moves the portfolio a little


@unittest.skipUnless((sim.MKT / "market.db").exists(), "needs market.db")
class Candles(unittest.TestCase):
    def test_candles_are_consistent_and_match_closes(self):
        try:
            o = sim.load_ohlc("2330.TW")
        except SystemExit:
            self.skipTest("market.db has no open/high/low yet")
        self.assertTrue((o.high >= o[["open", "close"]].max(axis=1) - 1e-6).all())
        self.assertTrue((o.low <= o[["open", "close"]].min(axis=1) + 1e-6).all())
        usd = sim.load_market()[0]["2330.TW"].reindex(o.index)
        self.assertLess((o.close - usd).abs().max(), 1e-6)


if __name__ == "__main__":
    unittest.main()
