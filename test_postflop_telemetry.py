"""Regression tests for observed postflop opportunities and BB-normalized results."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from export_preflop_ranges_v4 import TrackedBot
import replit_simulator


def view(street, history=(), to_call=0, legal=("check", "bet")):
    return SimpleNamespace(street=street, history=list(history), me="P1",
                           hand_id=1, to_call=to_call,
                           legal_actions=[{"type": action} for action in legal])


class PostflopTelemetryTests(unittest.TestCase):
    def make_bot(self):
        bot = TrackedBot(object(), "P1=split:gto:smart")
        bot.player_id = "P1"
        bot.observe_deal(1, [("A", "s"), ("K", "s")], "3", 9)
        return bot

    def test_cbet_and_aggression_count_once(self):
        bot = self.make_bot()
        hist = [{"street": "preflop", "pid": "P1", "type": "raise"}]
        bot.observe_postflop(view("flop", hist), SimpleNamespace(type="bet"))
        self.assertEqual(bot.postflop_counts["cbet_opp"], 1)
        self.assertEqual(bot.postflop_counts["cbet_n"], 1)
        self.assertEqual(bot.postflop_counts["flop_aggressive"], 1)
        bot.observe_postflop(view("flop", hist + [{"street":"flop","pid":"P1","type":"bet"}],
                                  to_call=2, legal=("fold","call","raise")),
                             SimpleNamespace(type="call"))
        self.assertEqual(bot.postflop_counts["cbet_opp"], 1)
        self.assertEqual(bot.postflop_counts["flop_calls"], 1)

    def test_fold_to_bet_and_check_raise(self):
        bot = self.make_bot()
        hist = [{"street":"turn","pid":"P1","type":"check"},
                {"street":"turn","pid":"P2","type":"bet"}]
        bot.observe_postflop(view("turn", hist, to_call=3, legal=("fold","call","raise")),
                             SimpleNamespace(type="raise"))
        self.assertEqual(bot.postflop_counts["check_raise_opp"], 1)
        self.assertEqual(bot.postflop_counts["check_raise_n"], 1)
        self.assertEqual(bot.postflop_counts["fold_to_bet_opp"], 1)
        self.assertEqual(bot.postflop_counts["fold_to_bet_n"], 0)
        bot.observe_postflop(view("river", [{"street":"river","pid":"P2","type":"bet"}],
                                  to_call=4,legal=("fold","call","raise")),
                             SimpleNamespace(type="fold"))
        self.assertEqual(bot.postflop_counts["fold_to_bet_n"], 1)

    def test_showdown_and_current_bb(self):
        bot = self.make_bot()
        bot.observe_hand_end(1, {"P1":18}, 6, ("P1","P2"), ("P1",))
        self.assertEqual(bot.postflop_counts["net_hands"], 1)
        self.assertEqual(bot.postflop_counts["net_bb_units"], 3)
        self.assertEqual(bot.postflop_counts["wsd_opp"], 1)
        self.assertEqual(bot.postflop_counts["wsd_n"], 1)
        bot.observe_hand_end(999, {"P1":-4}, 2, (), ())
        self.assertEqual(bot.postflop_counts["net_hands"], 1)

    def test_legacy_session_missing_telemetry(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            (folder/"summary_all.csv").write_text(
                "bot,hands_observed,vpip_pct,pfr_pct,rfi_pct,threebet_pct,fourbet_pct\n"
                "P1,100,20,15,10,5,1\n", encoding="utf-8")
            self.assertNotIn("flop_af", replit_simulator.stats_for_folder(folder)["P1"])

    def test_new_session_uses_observed_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            (folder/"postflop_summary.csv").write_text(
                "bot,flop_af,turn_af,river_af,cbet,fold_to_bet,check_raise,wsd,net_bb_100\n"
                "P1,1.5,,,42.0,30.0,15.0,60.0,-2.5\n", encoding="utf-8")
            data = replit_simulator.stats_for_folder(folder)["P1"]
            self.assertEqual(data["flop_af"], 1.5)
            self.assertIsNone(data["river_af"])
            self.assertEqual(data["net_bb_100"], -2.5)


if __name__ == "__main__":
    unittest.main()
