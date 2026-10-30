"""GTO 3.0/5-/10: real public-event memory, Board150 and engine regression."""
import random
import unittest
from unittest.mock import patch

from bots import create_bot
from bots.gto_postflop_30 import AdaptiveGTO30Bot, _board_class
from core.engine import Seat, Table
from test_postflop_profiles import make_view
import planner_postflop_ev as ev
import replit_simulator as app

FLOP = [("7", "c"), ("8", "d"), ("2", "h")]
WET = [("A", "s"), ("K", "s"), ("8", "d")]


def response(pid, kind, street="flop", amount=5, pot_before=15):
    # HERO stakes half original pot: before=15, to_call=5 -> 5/(15-5)=1/2.
    return [{"street": street, "pid": "P1", "type": "bet",
             "amount": 5, "to_call_before": 0, "pot_before": 10},
            {"street": street, "pid": pid, "type": kind,
             "amount": amount if kind != "fold" else None,
             "to_call_before": amount, "pot_before": pot_before}]


class AdaptiveGTO30Tests(unittest.TestCase):
    def test_registration_in_catalog_plan_and_tournaments(self):
        catalog = app.strategy_catalog()
        for window in (5, 10):
            name = f"gto_postflop_30_{window}"
            self.assertIn(name, catalog["postflop_strategies"])
            self.assertNotIn(name, catalog["preflop_strategies"])
            self.assertTrue(app.available_postflop(name))
            self.assertEqual(create_bot(name).window, window)
            bot = create_bot("split:pc_gto_80bb:"+name)
            self.assertEqual(bot.postflop_bot.window, window)
            self.assertEqual(ev.PROFILE_NAMES[f"gto30_{window}"], name)
            self.assertIn(name, app.UI.read_text())
            self.assertIn(f"gto30_{window}", app.PLAN_UI.read_text())

    def test_board150_canonical_codes_without_invented_classification(self):
        dry = _board_class(FLOP, "flop")
        wet = _board_class(WET, "flop")
        self.assertTrue(dry["id"].startswith("FLOP|S"))
        self.assertEqual(dry["f"], "F1")
        self.assertEqual(wet["f"], "F2")
        self.assertEqual(wet["a"], "A1")
        self.assertNotEqual(dry["id"], wet["id"])

    def test_per_opponent_window_and_reset(self):
        small = AdaptiveGTO30Bot(5)
        large = AdaptiveGTO30Bot(10)
        for hand in range(12):
            action = "fold" if hand >= 7 else "call"
            for bot in (small, large):
                bot.observe_hand(hand, response("P2", action), FLOP, "P1")
        s = small.opponent_stats("P2")
        l = large.opponent_stats("P2")
        self.assertEqual(s["n"], 5)
        self.assertEqual(s["counts"]["fold"], 5)
        self.assertEqual(l["n"], 10)
        self.assertEqual(l["counts"]["fold"], 5)
        self.assertEqual(l["counts"]["call"], 5)
        self.assertGreater(s["rates"]["fold"], l["rates"]["fold"])
        self.assertEqual(small.opponent_stats("P3")["n"], 0)
        small.reset_memory()
        self.assertEqual(small.opponent_stats("P2")["n"], 0)

    def test_dedup_current_hand_and_fold_ends_hand(self):
        bot = AdaptiveGTO30Bot(5)
        hist = response("P2", "fold")
        bot.observe_hand(3, hist, FLOP, "P1")
        bot.observe_hand(3, hist, FLOP, "P1")
        self.assertEqual(bot.opponent_stats("P2")["n"], 1)
        bot.observe_hand(4, hist, FLOP, "P1")
        self.assertEqual(bot.opponent_stats("P2")["n"], 2)

    def test_only_responses_to_our_half_pot_bets_are_counted(self):
        bot = AdaptiveGTO30Bot(5)
        bot.observe_hand(1, response("P2","raise"), FLOP, "P1")
        self.assertEqual(bot.opponent_stats("P2")["counts"]["raise"], 1)
        third_party = response("P2", "call")
        third_party[0]["pid"] = "P3"
        bot.observe_hand(2, third_party, FLOP, "P1")
        self.assertEqual(bot.opponent_stats("P2")["n"], 1)
        overbet = response("P2", "fold", amount=20, pot_before=30)
        bot.observe_hand(3, overbet, FLOP, "P1")
        self.assertEqual(bot.opponent_stats("P2")["n"], 1)
        check_only = [{"street":"flop","pid":"P2","type":"check",
                       "to_call_before":0,"pot_before":10}]
        bot.observe_hand(4, check_only, FLOP, "P1")
        self.assertEqual(bot.opponent_stats("P2")["n"], 1)
        # Never count responses facing a preflop 3bet as postflop samples.
        preflop = response("P2", "call", street="preflop")
        bot.observe_hand(5, preflop, FLOP, "P1")
        self.assertEqual(bot.opponent_stats("P2")["n"], 1)

    def test_three_observations_switch_on_adaptation_and_board_changes(self):
        bot = AdaptiveGTO30Bot(5)
        for hand in range(4):
            bot.observe_hand(hand,response("P2","fold"),FLOP,"P1")
        view = make_view(hole=(("Q","h"),("J","c")),board=FLOP,opponents=("P2",))
        with patch("bots.gto_postflop_30.random.random", return_value=.05):
            chosen=bot.act(view)
        self.assertEqual(chosen.type, "bet")
        self.assertGreater(chosen.amount, 0)
        self.assertEqual(bot.last_model["stats"]["n"], 4)
        self.assertEqual(bot.last_model["board_id"],_board_class(FLOP,"flop")["id"])
        wetview = make_view(hole=(("Q","h"),("J","c")),board=WET,opponents=("P2",))
        with patch("bots.gto_postflop_30.random.random", return_value=.99):
            self.assertEqual(bot.act(wetview).type, "check")
        self.assertEqual(bot.last_model["board_id"],_board_class(WET,"flop")["id"])

    def test_short_vs_long_window_leads_to_different_bluff_decisions(self):
        short=AdaptiveGTO30Bot(5)
        long=AdaptiveGTO30Bot(10)
        for hand in range(12):
            hist=response("P2","fold" if hand>=7 else "call")
            short.observe_hand(hand,hist,FLOP,"P1")
            long.observe_hand(hand,hist,FLOP,"P1")
        view=make_view(hole=(("Q","h"),("J","c")),board=FLOP,
                       opponents=("P2",))
        with patch("bots.gto_postflop_30.random.random",return_value=.30):
            short_action=short.act(view)
            long_action=long.act(view)
        self.assertEqual(short_action.type,"bet")
        self.assertEqual(long_action.type,"check")
        self.assertEqual(short.last_model["stats"]["n"],5)
        self.assertEqual(long.last_model["stats"]["n"],10)

    def test_trace_retains_last_five_hands_and_all_three_streets(self):
        bot=AdaptiveGTO30Bot(5)
        def view_at(street,board,hand_id):
            v=make_view(hole=(("Q","h"),("J","c")),board=board,
                        street=street,opponents=("P2",))
            v.hand_id=hand_id
            return v
        boards=(FLOP,FLOP+[("T","c")],FLOP+[("T","c"),("A","h")])
        for hand_id in range(6):
            for street,board in zip(("flop","turn","river"),boards):
                with patch("bots.postflop_profiles.random.random",return_value=.99):
                    bot.act(view_at(street,board,hand_id))
        trace=bot.trace_snapshot()
        self.assertEqual(len(trace),5)
        self.assertEqual([x["hand_id"] for x in trace],[1,2,3,4,5])
        for hand in trace:
            self.assertEqual([x["street"] for x in hand["steps"]],
                             ["flop","turn","river"])
            self.assertTrue(all(x["board150"].startswith(x["street"].upper()+"|")
                                if x["street"]!="river" else
                                x["board150"].startswith("S")
                                for x in hand["steps"]))
            self.assertTrue(all(0<=x["board_anytwo_rank_pair_pct"]<=100
                                for x in hand["steps"]))

    def test_no_data_and_multiway_use_baseline_without_bogus_learning(self):
        bot=AdaptiveGTO30Bot(10)
        view=make_view(hole=(("Q","h"),("J","c")),board=FLOP,
                       opponents=("P2","P3"))
        with patch("bots.postflop_profiles.random.random", return_value=.99):
            self.assertIn(bot.act(view).type,("check","bet"))
        self.assertIsNone(bot.last_model["stats"])
        self.assertEqual(bot.opponent_stats("P2")["n"],0)

    def test_end_of_hand_engine_delivers_history_once_to_split_policy(self):
        class Recorder:
            def __init__(self):self.hands=[]
            def act(self,view):
                from core.bot_api import Action
                if view.to_call:
                    return Action("fold")
                return Action("check")
            def observe_hand(self,hand_id,history,board,me):
                self.hands.append((hand_id,tuple(history),tuple(board),me))
        observer=Recorder()
        other=Recorder()
        table=Table(rng=random.Random(11))
        seats=[Seat("P1",100),Seat("P2",100)]
        delta=table.play_hand(seats,small_blind=1,big_blind=2,
            dealer_index=0,bot_for={"P1":observer,"P2":other})
        self.assertEqual(sum(delta.values()),0)
        self.assertEqual(len(observer.hands),1)
        self.assertEqual(len(other.hands),1)
        self.assertEqual(observer.hands[0][3],"P1")
        self.assertEqual(observer.hands[0][0],0)

    def test_real_exporter_keeps_last_five_traces_from_completed_tournament(self):
        from export_preflop_ranges_v4 import run_one
        with patch.dict("os.environ", {"THAI_ENGINE_IMPL":"legacy"}):
            result = run_one((1, [
                "split:pc_gto_80bb:gto_postflop_30_5",
                "split:pc_gto_80bb:gto_postflop_30_10",
            ], 80, 1, 2, 20, 60, 311, 0))
        tournament_id, _, _, outcome, _, _, _ = result
        self.assertEqual(tournament_id, 1)
        log = outcome["gto30_last5"]
        self.assertEqual(len(log), 2)
        self.assertEqual({item["window"] for item in log}, {5,10})
        for entry in log:
            self.assertLessEqual(len(entry["hands"]), 5)
            for hand in entry["hands"]:
                for step in hand["steps"]:
                    self.assertIn(step["street"], ("flop","turn","river"))
                    self.assertIn("board150", step)
                    self.assertIn("board_anytwo_rank_pair_pct", step)
                    self.assertEqual(len(step["hero_hole"]), 2)
                    self.assertIn(step["decision"],
                                  ("fold","call","check","bet","raise"))
                    self.assertIn(step["decision_mode"],
                                  ("gto20_fallback","gto30_adapted"))

    def test_postflop_only_not_full_preflop_equilibrium(self):
        bot=AdaptiveGTO30Bot(5)
        with self.assertRaisesRegex(ValueError,"postflop-only"):
            bot.act(make_view(street="preflop"))


if __name__ == "__main__":
    unittest.main()
