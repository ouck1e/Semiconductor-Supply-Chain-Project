"""
Tests for daily paper trading (agent_daily.py). No API calls and no cost: a fake client replays the replies saved in an
earlier run folder.  Run:  python -m unittest discover tests

Most tests need data/market/market.db and are skipped without it.
"""
import contextlib
import io
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent_daily as daily      # noqa: E402
import agent_score as score      # noqa: E402
import agent_sim as sim          # noqa: E402

HAVE_DB = (sim.MKT / "market.db").exists()
SAVED = sim.OUT / "runs" / "run-20261016-175940-fc53"       # a full v5 run: replies 1, 2, 3, 5 and the Boss
HAVE_SAVED = all((SAVED / f).exists() for f in ("reply_1.txt", "reply_2.txt", "reply_3.txt", "reply_5.txt", "boss.txt"))


def saved_replies():
    return [(SAVED / f).read_text(encoding="utf-8") for f in
            ("reply_1.txt", "reply_2.txt", "reply_3.txt", "reply_5.txt", "boss.txt")]


class FakeClient:
    """Stands in for anthropic.Anthropic(): client.beta.messages.create(...) returns the next saved reply."""
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []
        self.beta = self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        block = SimpleNamespace(type="text", text=self.replies.pop(0))
        return SimpleNamespace(content=[block], model=kw["model"], stop_reason="end_turn",
                               usage=SimpleNamespace(input_tokens=2000, output_tokens=1000))


class NoMarketNeeded(unittest.TestCase):
    def test_no_broker_code(self):
        src = (sim.ROOT / "agent_daily.py").read_text(encoding="utf-8").lower()
        for word in ("alpaca", "ib_insync", "ibapi", "ccxt", "robin_stocks", "tda", "schwab", "place_order",
                     "submit_order", "create_order", "broker_key", "broker_secret"):
            self.assertIsNone(re.search(rf"\b{word}\b", src), f"{word!r} in agent_daily.py: simulation only")
        imports = set(re.findall(r"^\s*(?:import|from) (\w+)", src, re.M))
        self.assertLessEqual(imports, {"argparse", "os", "datetime", "pandas", "anthropic", "agent_handoff",
                                       "agent_packets", "agent_score", "agent_sim"})

    def test_config_has_watchlist_models_and_budget(self):
        auto = sim.config()["automation"]
        self.assertEqual(len(auto["watchlist"]), 5)
        self.assertEqual(set(auto["models"]), {s for _, s in daily.STAGES})
        self.assertTrue(all(m in auto["usd_per_million_tokens"] for m in auto["models"].values()))
        self.assertEqual(auto["monthly_budget_usd"], 60)

    def test_missing_key_runs_nothing(self):
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        out = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(sys, "argv", ["agent_daily.py"]), \
                mock.patch.object(sim, "load_market") as load, contextlib.redirect_stdout(out):
            daily.main()
        load.assert_not_called()
        self.assertIn("No ANTHROPIC_API_KEY", out.getvalue())

    def test_open_buy_and_same_day_are_skipped(self):
        log = pd.DataFrame([dict(market="MU", decision_date="2026-10-01", status="pending", action="BUY"),
                            dict(market="ASML.AS", decision_date="2026-10-19", status="pending", action="NO TRADE")])
        D = pd.Timestamp("2026-10-19")
        self.assertIn("open BUY", daily.skip_reason("MU", D, log))
        self.assertIn("already has a run", daily.skip_reason("ASML.AS", D, log))
        self.assertEqual(daily.skip_reason("ASML.AS", pd.Timestamp("2026-10-20"), log), "")   # a pending skip doesn't block
        self.assertEqual(daily.skip_reason("2330.TW", D, log), "")


@unittest.skipUnless(HAVE_DB and HAVE_SAVED, "needs data/market/market.db and a saved run folder")
class DailyRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = sim.config()
        cls.market = sim.load_market()
        cls.usd = cls.market[0]
        cls.t = "2330.TW"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        shutil.copy(sim.OUT / "baseline_weights.csv", self.out / "baseline_weights.csv")

    def tearDown(self):
        self.tmp.cleanup()

    def run_day(self, client, tickers=None):
        return daily.run_day(tickers or [self.t], self.cfg, self.market, client, self.out)

    def test_a_run_is_built_handed_on_and_scored_pending(self):
        client = FakeClient(saved_replies())
        (t, outcome), = self.run_day(client)
        self.assertEqual(len(client.calls), 5)                                   # the Coder is skipped
        self.assertEqual({c["model"] for c in client.calls}, {"claude-opus-5-5"})
        self.assertEqual({c["output_config"]["effort"] for c in client.calls}, {"medium"})
        log = score.load_log(self.out)
        row = log.iloc[0]
        self.assertEqual((row.market, row.status, row.split, str(row.blind)), (t, "pending", "forward", "False"))
        self.assertEqual(row.decision_date, str(self.usd[t].dropna().index[-1].date()))
        self.assertEqual(row.prompts_version, sim.prompts_version())
        self.assertTrue(row.runner.startswith("Claude API daily (claude-opus-5-5"))
        run_dir = self.out / "runs" / row.run_id
        for f in ("reply_1.txt", "reply_2.txt", "reply_3.txt", "reply_5.txt", "boss.txt", "filled_6_boss.txt"):
            self.assertTrue((run_dir / f).exists(), f)
        # the News Analyst got the Researcher's handoff, and the Boss got all four
        self.assertIn(client.calls[0]["messages"][0]["content"][:200], (run_dir / "1_researcher.txt").read_text(encoding="utf-8"))
        self.assertIn("--- RISK MANAGER ---", client.calls[4]["messages"][0]["content"])
        self.assertNotIn("[PASTE", client.calls[4]["messages"][0]["content"])
        u = daily.load_usage(self.out)
        self.assertEqual(len(u), 5)
        self.assertAlmostEqual(u.cost_usd.sum(), 5 * (2000 * 4 + 1000 * 20) / 1e6)
        self.assertIn("pending", outcome)

    def test_second_call_the_same_day_costs_nothing(self):
        self.run_day(FakeClient(saved_replies()))
        client = FakeClient([])
        (_, outcome), = self.run_day(client)
        self.assertEqual(client.calls, [])
        self.assertIn("skipped", outcome)

    def test_dates_before_blind_before_are_refused(self):
        cfg = dict(self.cfg, blind_before="2099-01-01")
        client = FakeClient([])
        (_, outcome), = daily.run_day([self.t], cfg, self.market, client, self.out)
        self.assertEqual(client.calls, [])
        self.assertIn("forward runs only", outcome)

    def test_budget_stops_before_a_run(self):
        month = pd.Timestamp.now().strftime("%Y-%m")
        pd.DataFrame([dict(date_time=f"{month}-01T22:30:00", run_id="run-x", cost_usd=59.8)]) \
            .to_csv(self.out / "api_usage.csv", index=False)
        client = FakeClient([])
        (_, outcome), = self.run_day(client)
        self.assertEqual(client.calls, [])
        self.assertIn("monthly budget", outcome)

    def test_unreadable_decision_is_fixed_once(self):
        r = saved_replies()
        boss = r[4]
        block = boss[boss.rindex("\nDECISION\n"):]                         # just the corrected block
        client = FakeClient(r[:4] + [boss.replace("END DECISION", "(block ends)"), block])
        self.run_day(client)
        self.assertEqual(len(client.calls), 6)
        self.assertEqual([m["role"] for m in client.calls[5]["messages"]], ["user", "assistant", "user"])
        self.assertEqual(score.load_log(self.out).iloc[0].status, "pending")

    def test_still_unreadable_decision_is_logged_not_scored(self):
        r = saved_replies()
        bad = r[4].replace("END DECISION", "(block ends)")
        client = FakeClient(r[:4] + [bad, "Sorry, here it is: ACTION BUY"])
        (_, outcome), = self.run_day(client)
        self.assertIn("failed, not scored", outcome)
        self.assertEqual(len(score.load_log(self.out)), 0)
        u = daily.load_usage(self.out)
        self.assertEqual(u.stage.iloc[-1], "failed")
        self.assertEqual(len(u), 7)                                          # 6 calls + the failure note


if __name__ == "__main__":
    unittest.main()
