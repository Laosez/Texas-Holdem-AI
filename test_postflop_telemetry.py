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

    def test_three_barrels_require_calls_and_a_legal_bet(self):
        bot=self.make_bot()
        pre=[{"street":"preflop","pid":"P1","type":"raise"}]
        flop=pre[:]
        bot.observe_postflop(view("flop",flop),SimpleNamespace(type="bet"))
        self.assertEqual(bot.postflop_counts["flop_cbet_n"],1)
        self.assertEqual(bot.postflop_counts["cbet_n"],1)
        flop += [{"street":"flop","pid":"P1","type":"bet"},
                 {"street":"flop","pid":"P2","type":"call"}]
        bot.observe_postflop(view("turn",flop),SimpleNamespace(type="bet"))
        self.assertEqual(bot.postflop_counts["turn_cbet_opp"],1)
        self.assertEqual(bot.postflop_counts["turn_cbet_n"],1)
        turn=flop+[{"street":"turn","pid":"P1","type":"bet"},
                   {"street":"turn","pid":"P2","type":"call"}]
        bot.observe_postflop(view("river",turn),SimpleNamespace(type="check"))
        self.assertEqual(bot.postflop_counts["river_cbet_opp"],1)
        self.assertEqual(bot.postflop_counts["river_cbet_n"],0)
        bot.observe_postflop(view("river",turn+[{"street":"river","pid":"P1","type":"check"}]),
                             SimpleNamespace(type="bet"))
        self.assertEqual(bot.postflop_counts["river_cbet_opp"],1)
        self.assertEqual(bot.postflop_position_counts["3"]["turn_cbet_n"],1)
        self.assertEqual(bot.postflop_position_counts["3"]["river_cbet_opp"],1)

    def test_barrel_denominator_excludes_uncalled_or_raised_prior_bet(self):
        for tail in (
            [],
            [{"street":"flop","pid":"P2","type":"raise"},
             {"street":"flop","pid":"P1","type":"call"}],
        ):
            bot=self.make_bot()
            pre=[{"street":"preflop","pid":"P1","type":"raise"}]
            bot.observe_postflop(view("flop",pre),SimpleNamespace(type="bet"))
            flop=pre+[{"street":"flop","pid":"P1","type":"bet"}]+tail
            bot.observe_postflop(view("turn",flop),SimpleNamespace(type="bet"))
            self.assertEqual(bot.postflop_counts["turn_cbet_opp"],0)
        bot=self.make_bot()
        pre=[{"street":"preflop","pid":"P1","type":"raise"}]
        bot.observe_postflop(view("flop",pre),SimpleNamespace(type="check"))
        flop=pre+[{"street":"flop","pid":"P1","type":"check"},
                  {"street":"flop","pid":"P1","type":"bet"},
                  {"street":"flop","pid":"P2","type":"call"}]
        bot.observe_postflop(view("turn",flop),SimpleNamespace(type="bet"))
        self.assertEqual(bot.postflop_counts["turn_cbet_opp"],0)

    def test_no_barrel_opportunity_when_all_in_or_facing_bet(self):
        bot=self.make_bot()
        hist=[{"street":"preflop","pid":"P1","type":"raise"}]
        bot.observe_postflop(view("flop",hist,to_call=3,legal=("fold","call","raise")),
                             SimpleNamespace(type="call"))
        self.assertEqual(bot.postflop_counts["flop_cbet_opp"],0)
        self.assertEqual(bot.postflop_counts["cbet_opp"],0)

    def test_showdown_and_current_bb(self):
        bot = self.make_bot()
        bot.observe_hand_end(1, {"P1":18}, 6, ("P1","P2"), ("P1",))
        self.assertEqual(bot.postflop_counts["net_hands"], 1)
        self.assertEqual(bot.postflop_counts["net_bb_units"], 3)
        self.assertEqual(bot.postflop_position_counts["3"]["net_bb_units"], 3)
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

    def test_position_and_three_barrel_csv_are_merged_only_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            (folder/"summary_position_all.csv").write_text(
                "bot,position,hands_observed,vpip_pct,pfr_pct,rfi_pct,threebet_pct,fourbet_pct\\n"
                "P1,9,80,18,11,9,2,1\\n"
                "P1,BB,50,21,13,,,\\n",
                encoding="utf-8")
            (folder/"postflop_summary.csv").write_text(
                "bot,flop_cbet,turn_cbet,river_cbet,cbet\\n"
                "P1,50,33.3333,20,50\\n",encoding="utf-8")
            (folder/"postflop_position_summary.csv").write_text(
                "bot,position,flop_cbet,turn_cbet,river_cbet,net_bb_100\\n"
                "P1,9,60,40,25,8\\nP1,BB,,,,\\n",encoding="utf-8")
            d=replit_simulator.stats_for_folder(folder)["P1"]
            self.assertEqual(d["turn_cbet"],33.3333)
            self.assertEqual(d["positions"]["9"]["hands_observed"],80)
            self.assertEqual(d["positions"]["9"]["river_cbet"],25)
            self.assertEqual(d["positions"]["9"]["net_bb_100"],8)
            self.assertIsNone(d["positions"]["BB"]["turn_cbet"])
            self.assertEqual(d["positions"]["BB"]["vpip"],21)

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
