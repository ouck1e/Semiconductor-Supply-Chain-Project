"""
Tests for the AI agent team code (simulation only).  Run:  python -m unittest discover tests

The look-ahead and packet tests need data/market/market.db and are skipped without it.
"""
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent_sim as sim          # noqa: E402
import agent_score as score      # noqa: E402

CFG = {"fee_pct_per_side": 0.1, "slippage_pct_per_side": 0.1, "max_position_pct": 10, "max_stop_pct": 15,
       "max_hold_days": 20, "portfolio_usd": 100000}
HAVE_DB = (sim.MKT / "market.db").exists()


def series(values, start="2024-01-01"):
    return pd.Series(values, index=pd.bdate_range(start, periods=len(values)), dtype=float)


class SimulateTrade(unittest.TestCase):
    def test_stop(self):
        s = series([100, 100, 98, 91, 120])        # decide day 0, enter at day 1 (100), day 3 is -9%
        o = sim.simulate_trade(s, s.index[0], "BUY", 5, 8, 20, 10, CFG)
        self.assertEqual((o["status"], o["exit_reason"], o["exit_date"]), ("closed", "stop", s.index[3]))
        self.assertAlmostEqual(o["ret_pct"], 100 * ((91 * 0.999) / (100 * 1.001) - 1 - 0.002), places=6)

    def test_target(self):
        s = series([100, 100, 104, 111, 50])
        o = sim.simulate_trade(s, s.index[0], "BUY", 5, 8, 10, 10, CFG)
        self.assertEqual((o["exit_reason"], o["exit_date"]), ("target", s.index[3]))

    def test_time_exit(self):
        s = series([100] + [100 + i * 0.1 for i in range(30)])
        o = sim.simulate_trade(s, s.index[0], "BUY", 5, 8, 50, 5, CFG)
        self.assertEqual((o["status"], o["exit_reason"], o["days"]), ("closed", "time", 5))
        self.assertEqual(o["exit_date"], s.index[6])

    def test_fees_make_a_flat_trade_lose(self):
        s = series([100] * 10)
        o = sim.simulate_trade(s, s.index[0], "BUY", 5, 8, 50, 3, CFG)
        self.assertLess(o["ret_pct"], 0)
        self.assertAlmostEqual(o["ret_pct"], 100 * (0.999 / 1.001 - 1 - 0.002), places=6)

    def test_not_enough_later_prices_is_open(self):
        s = series([100, 101, 102])
        self.assertEqual(sim.simulate_trade(s, s.index[0], "BUY", 5, 8, 50, 10, CFG)["status"], "open")
        self.assertEqual(sim.simulate_trade(s, s.index[-1], "BUY", 5, 8, 50, 10, CFG)["status"], "open")

    def test_missing_rows_are_skipped_not_filled(self):
        s = series([100, 100, np.nan, 90, 100])
        o = sim.simulate_trade(s, s.index[0], "BUY", 5, 8, 50, 10, CFG)
        self.assertEqual(o["exit_reason"], "stop")
        self.assertEqual(o["exit_date"], s.index[3])

    def test_no_trade_has_no_position(self):
        s = series([100, 50])
        self.assertEqual(sim.simulate_trade(s, s.index[0], "NO TRADE", 0, 0, 0, 10, CFG)["status"], "no position")


GOOD = """Some analysis first.

DECISION
FINAL_STATUS: APPROVE FOR SIMULATION ONLY
ACTION: BUY
SETUP: pullback to 50-day average
RESEARCH_CONFIDENCE: 80
RISK_DECISION: APPROVE FOR SIMULATION ONLY
SIZE_PCT: 5
STOP_PCT: 7
TARGET_PCT: 14
MAX_HOLD_DAYS: 20
END DECISION
"""


class ParseDecision(unittest.TestCase):
    def test_good_block(self):
        d = score.parse_decision(GOOD)
        self.assertEqual((d["ACTION"], d["SIZE_PCT"], d["STOP_PCT"]), ("BUY", 5.0, 7.0))

    def test_markdown_bold_is_tolerated(self):
        d = score.parse_decision(GOOD.replace("DECISION\nFINAL", "**DECISION**\n**FINAL_STATUS:** APPROVE FOR SIMULATION ONLY\nX")
                                 .replace("END DECISION", "**END DECISION**"))
        self.assertEqual(d["FINAL_STATUS"], "APPROVE FOR SIMULATION ONLY")

    def test_rejects_missing_block(self):
        with self.assertRaises(score.DecisionError):
            score.parse_decision("I think we should buy.")

    def test_rejects_missing_field(self):
        with self.assertRaises(score.DecisionError):
            score.parse_decision(GOOD.replace("STOP_PCT: 7\n", ""))

    def test_rejects_words_for_numbers(self):
        with self.assertRaises(score.DecisionError):
            score.parse_decision(GOOD.replace("SIZE_PCT: 5", "SIZE_PCT: about five"))

    def test_rejects_short_selling(self):
        with self.assertRaises(score.DecisionError):
            score.parse_decision(GOOD.replace("ACTION: BUY", "ACTION: SHORT"))

    def test_broken_rules_become_no_trade(self):
        d = score.parse_decision(GOOD.replace("RISK_DECISION: APPROVE FOR SIMULATION ONLY", "RISK_DECISION: REJECT"))
        self.assertEqual(score.check_rules(d, CFG)[0], "NO TRADE")
        d = score.parse_decision(GOOD.replace("SIZE_PCT: 5", "SIZE_PCT: 40"))
        action, broken = score.check_rules(d, CFG)
        self.assertEqual(action, "NO TRADE")
        self.assertTrue(any("size" in b for b in broken))
        self.assertEqual(score.check_rules(score.parse_decision(GOOD), CFG), ("BUY", []))

    def test_revise_becomes_buy_only_with_an_applied_fix(self):
        revise = GOOD.replace("RISK_DECISION: APPROVE FOR SIMULATION ONLY", "RISK_DECISION: REVISE")
        self.assertEqual(score.check_rules(score.parse_decision(revise), CFG)[0], "NO TRADE")
        none = revise.replace("END DECISION", "APPLIED_FIX: none\nEND DECISION")
        self.assertEqual(score.check_rules(score.parse_decision(none), CFG)[0], "NO TRADE")
        fixed = revise.replace("END DECISION", 'APPLIED_FIX: "cut the stop from 8 to 7"\nEND DECISION')
        self.assertEqual(score.check_rules(score.parse_decision(fixed), CFG), ("BUY", []))


PLAN = """Strategist analysis...

PLAN
ACTION: BUY
SETUP: pullback
SIZE_PCT: 5
STOP_PCT: 8
TARGET_PCT: 10
MAX_HOLD_DAYS: 20
END PLAN
"""


class StrategistPlan(unittest.TestCase):
    def test_parse_and_missing(self):
        self.assertEqual(score.parse_plan(PLAN)["STOP_PCT"], 8.0)
        self.assertIsNone(score.parse_plan("No plan block here."))
        with self.assertRaises(score.DecisionError):
            score.parse_plan(PLAN.replace("STOP_PCT: 8\n", ""))

    def test_plan_and_decision_blocks_are_read_separately(self):
        both = PLAN + "\n" + GOOD
        self.assertEqual(score.parse_plan(both)["TARGET_PCT"], 10.0)
        self.assertEqual(score.parse_decision(both)["TARGET_PCT"], 14.0)

    def test_veto_of_a_loser_is_right(self):
        s = series([100, 100, 95, 91, 90])                  # plan's 8% stop is hit
        cols, pending = score.score_plan(score.parse_plan(PLAN), "x", "NO TRADE", s, s.index[0], CFG)
        self.assertFalse(pending)
        self.assertEqual((cols["vetoed"], cols["veto_right"], cols["plan_exit_reason"]), ("yes", "yes", "stop"))
        self.assertAlmostEqual(cols["veto_saved_pct"], -cols["plan_ret_pct"])
        self.assertGreater(cols["veto_saved_pct"], 0)

    def test_veto_of_a_winner_is_wrong_and_approval_is_not_a_veto(self):
        s = series([100, 100, 104, 111, 112])
        cols, _ = score.score_plan(score.parse_plan(PLAN), "x", "NO TRADE", s, s.index[0], CFG)
        self.assertEqual((cols["veto_right"], cols["plan_exit_reason"]), ("no", "target"))
        self.assertLess(cols["veto_saved_pct"], 0)
        cols, _ = score.score_plan(score.parse_plan(PLAN), "x", "BUY", s, s.index[0], CFG)
        self.assertEqual((cols["vetoed"], cols["veto_right"]), ("no", ""))

    def test_find_plan_prefers_the_saved_reply_over_the_backfill(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            self.assertEqual(score.find_plan(d), (None, ""))
            (d / "strategist_plan.txt").write_text(PLAN.replace("ACTION: BUY", "ACTION: NO TRADE"), encoding="utf-8")
            (d / "reply_3.txt").write_text("an old reply with no PLAN block", encoding="utf-8")
            self.assertEqual(score.find_plan(d)[1], "strategist_plan.txt")
            (d / "strategist.txt").write_text(PLAN, encoding="utf-8")
            plan, src = score.find_plan(d)
            self.assertEqual((plan["ACTION"], src), ("BUY", "strategist.txt"))


@unittest.skipUnless(HAVE_DB and (sim.OUT / "trade_log.csv").exists(), "needs market.db and a trade log")
class Dashboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import agent_dashboard
        cls.d = agent_dashboard.build()

    def test_every_run_has_prices_for_its_dates(self):
        for r in self.d["runs"]:
            dates = set(self.d["stocks"][r["ticker"]]["dates"])
            self.assertIn(r["decision_date"], dates, r["run_id"])
            if r["action"] == "BUY":
                self.assertIn(r["entry_date"], dates, r["run_id"])
                if r["status"] == "scored":
                    self.assertIn(r["exit_date"], dates, r["run_id"])

    def test_stop_and_target_levels_match_the_decision(self):
        for r in self.d["runs"]:
            if r["action"] == "BUY" and r["entry_px"]:
                self.assertAlmostEqual(r["stop_px"], r["entry_px"] * (1 - r["stop"] / 100), places=3)
                self.assertAlmostEqual(r["target_px"], r["entry_px"] * (1 + r["target"] / 100), places=3)

    def test_exit_reason_agrees_with_prices(self):
        for r in self.d["runs"]:
            if r["action"] == "BUY" and r["status"] == "scored" and r["exit_reason"] == "target":
                self.assertGreaterEqual(r["exit_px"], r["target_px"] - 1e-6, r["run_id"])
            if r["action"] == "BUY" and r["status"] == "scored" and r["exit_reason"] == "stop":
                self.assertLessEqual(r["exit_px"], r["stop_px"] + 1e-6, r["run_id"])


@unittest.skipUnless(HAVE_DB, "needs data/market/market.db")
class WithMarketData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = sim.config()
        cls.market = sim.load_market()
        cls.usd, cls.vol, cls.uni, cls.ff = cls.market
        cls.D = pd.Timestamp("2022-03-15")

    def test_indicators_ignore_the_future(self):
        t = "2330.TW"
        full = sim.indicators(self.usd[t], self.vol[t], self.usd["SOXX"], self.D)
        cut = lambda s: s[s.index <= self.D]
        trimmed = sim.indicators(cut(self.usd[t]), cut(self.vol[t]), cut(self.usd["SOXX"]), self.D)
        self.assertEqual(full, trimmed)

    def test_model1_signal_ignores_the_future(self):
        tick = list(sim.companies(self.uni).ticker)
        full = sim.trailing_model1(self.usd, self.ff, self.D, self.cfg, tick)
        cut = sim.trailing_model1(self.usd[self.usd.index <= self.D], self.ff[self.ff.index <= self.D], self.D, self.cfg, tick)
        pd.testing.assert_frame_equal(full, cut)

    def test_blind_packet_leaks_nothing(self):
        import agent_packets as ap
        with tempfile.TemporaryDirectory() as tmp:
            for t in ("2330.TW", "MU", "ASML.AS"):
                run_id, run_dir, key = ap.build(t, self.D, True, self.cfg, self.market, out_dir=Path(tmp))
                text = "\n".join(p.read_text(encoding="utf-8") for p in run_dir.glob("*.txt")).lower()
                u = self.uni.set_index("ticker").loc[t]
                for word in (t.lower(), t.split(".")[0].lower(), u["name"].lower(), u.currency.lower(), u.country.lower()):
                    self.assertIsNone(re.search(rf"\b{re.escape(word)}\b", text), f"{word!r} leaked into the blind packet for {t}")
                self.assertEqual(re.findall(r"\b20(?:1[5-9]|2[0-6])\b", text), [], "a calendar year leaked")
                self.assertNotIn("2022-03", text)
                # the baseline's dev-years result is only known after 2022, so a 2022 decision must not see it
                self.assertNotIn("development years", text)
                self.assertTrue((Path(tmp) / "keys" / f"{run_id}.json").exists())

    def test_score_end_to_end(self):
        import agent_packets as ap
        if not (sim.OUT / "baseline_weights.csv").exists():
            self.skipTest("run phase8_baseline.py first")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            shutil.copy(sim.OUT / "baseline_weights.csv", out / "baseline_weights.csv")
            run_id, run_dir, key = ap.build("2330.TW", self.D, True, self.cfg, self.market, out_dir=out)
            (run_dir / "boss.txt").write_text(GOOD, encoding="utf-8")
            row, board = score.score_run(run_id, run_dir / "boss.txt", out, self.usd, self.cfg)
            self.assertEqual((row["status"], row["action"], row["rules_followed"]), ("scored", "BUY", "yes"))
            self.assertIsNotNone(row["baseline_ret_pct"])
            self.assertAlmostEqual(row["excess_vs_baseline_pct"], row["agent_ret_pct"] - row["baseline_ret_pct"])
            # scoring the same run again replaces its row instead of adding one
            score.score_run(run_id, run_dir / "boss.txt", out, self.usd, self.cfg)
            self.assertEqual(len(pd.read_csv(out / "trade_log.csv")), 1)
            self.assertEqual(set(board.prompts_version), {key["prompts_version"], "all versions"})
            self.assertEqual(row["good_skip"], "")                       # a BUY is not a skip

    def test_no_trade_is_compared_with_holding_the_stock(self):
        import agent_packets as ap
        if not (sim.OUT / "baseline_weights.csv").exists():
            self.skipTest("run phase8_baseline.py first")
        skip = GOOD.replace("APPROVE FOR SIMULATION ONLY\nACTION: BUY", "REJECT\nACTION: NO TRADE")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            shutil.copy(sim.OUT / "baseline_weights.csv", out / "baseline_weights.csv")
            run_id, run_dir, _ = ap.build("2330.TW", self.D, True, self.cfg, self.market, out_dir=out)
            (run_dir / "boss.txt").write_text(skip, encoding="utf-8")
            row, board = score.score_run(run_id, run_dir / "boss.txt", out, self.usd, self.cfg)
            self.assertEqual((row["action"], row["agent_ret_pct"]), ("NO TRADE", 0.0))
            self.assertAlmostEqual(row["vs_buy_and_hold_pct"], -row["stock_hold_ret_pct"])
            self.assertEqual(row["good_skip"], "yes" if row["stock_hold_ret_pct"] < 0 else "no")
            self.assertIn("good_skip_pct", board.columns)

    def test_baseline_note_appears_only_after_the_dev_years(self):
        import agent_packets as ap
        late = ap.strategist_facts("2330.TW", pd.Timestamp("2023-06-01"), self.usd, self.ff, self.uni, self.cfg, False)
        early = ap.strategist_facts("2330.TW", self.D, self.usd, self.ff, self.uni, self.cfg, False)
        self.assertIn("development years", late)
        self.assertNotIn("development years", early)


if __name__ == "__main__":
    unittest.main()
