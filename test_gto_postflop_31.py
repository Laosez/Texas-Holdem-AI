"""GTO 3.1: all public actions, separate response denominators, HU adaptation."""
import os
import random
import unittest
from unittest.mock import patch

from bots import create_bot
from bots.gto_postflop_31 import AdaptiveGTO31Bot
from core.engine import Seat, Table
from test_postflop_profiles import make_view
import replit_simulator as app

FLOP = [("K","c"),("Q","d"),("3","h")]
TURN = FLOP + [("4","s")]
RIVER = TURN + [("5","c")]

def event(street, pid, kind, call=0, pot=20, amount=None):
    return {"street":street,"pid":pid,"type":kind,"amount":amount,
            "to_call_before":call,"pot_before":pot}


class GTO31Tests(unittest.TestCase):
    def test_catalog_and_independent_baseline(self):
        catalog=app.strategy_catalog()
        for n in (5,10):
            name=f"gto_postflop_31_{n}"
            if n == 5:
                self.assertIn(name, catalog["postflop_strategies"])
            else:
                self.assertNotIn(name, catalog["postflop_strategies"])
                self.assertTrue(app.available_postflop(name))
            self.assertIn(name,catalog["postflop_profiles"])
            self.assertNotIn(name,catalog["preflop_strategies"])
            self.assertEqual(create_bot(name).window,n)
            self.assertEqual(create_bot("split:pc_gto_80bb:"+name).postflop_bot.window,n)
            self.assertIn(name,app.UI.read_text(encoding="utf-8"))
        self.assertIn("gto31Matrix",app.UI.read_text(encoding="utf-8"))

    def test_last_five_vs_ten_all_actions_and_reset(self):
        a,b=AdaptiveGTO31Bot(5),AdaptiveGTO31Bot(10)
        for hand in range(12):
            history=[event("flop","P2","check" if hand<7 else "bet")]
            for bot in (a,b):
                bot.observe_hand(hand,history,FLOP,"P1")
        self.assertEqual(a.opponent_stats("P2")["n"],5)
        self.assertEqual(a.opponent_stats("P2")["counts"]["bet"],5)
        self.assertEqual(b.opponent_stats("P2")["n"],10)
        self.assertEqual(b.opponent_stats("P2")["counts"]["check"],5)
        self.assertEqual(b.opponent_stats("P2")["counts"]["bet"],5)
        a.reset_memory()
        self.assertEqual(a.opponent_stats("P2")["n"],0)
        with self.assertRaises(ValueError):
            AdaptiveGTO31Bot(6)

    def test_observes_responses_to_any_players_bets_and_dedup(self):
        bot=AdaptiveGTO31Bot(10)
        hist=[event("flop","P3","bet"),event("flop","P2","fold",call=10,pot=30)]
        bot.observe_hand(1,hist[:1],FLOP,"P1")
        bot.observe_hand(1,hist,FLOP,"P1")
        bot.observe_hand(1,hist,FLOP,"P1")
        self.assertEqual(bot.opponent_stats("P2")["counts"]["fold"],1)
        self.assertEqual(bot.opponent_stats("P2")["metrics"]["fold_to_bet"]["n"],1)
        self.assertEqual(bot.opponent_stats("P2")["metrics"]["fold_to_cbet"]["n"],0)
        self.assertEqual(bot.opponent_stats("P3")["counts"]["bet"],1)
        bot.observe_hand(2,hist,FLOP,"P1")
        self.assertEqual(bot.opponent_stats("P2")["counts"]["fold"],2)

    def test_cbet_and_reraise_have_true_context(self):
        bot=AdaptiveGTO31Bot(10)
        # P3 is preflop aggressor, bets first on flop, P2 responds.
        cb=[event("preflop","P3","raise"),event("preflop","P2","call",call=4),
            event("flop","P3","bet"),event("flop","P2","fold",call=10,pot=30)]
        bot.observe_hand(1,cb,FLOP,"P1")
        self.assertEqual(bot.opponent_stats("P2")["metrics"]["fold_to_cbet"]["n"],1)
        self.assertEqual(bot.opponent_stats("P2")["metrics"]["fold_to_cbet"]["k"],1)
        self.assertEqual(bot.opponent_stats("P3")["counts"]["bet"],1)
        # A later raise over another raise is a reraise (not merely a bet).
        rr=[event("flop","P3","bet"),event("flop","P1","raise",call=8),
            event("flop","P2","raise",call=20)]
        bot.observe_hand(2,rr,FLOP,"P1")
        self.assertEqual(bot.opponent_stats("P2")["metrics"]["reraise_vs_raise"]["n"],1)
        self.assertEqual(bot.opponent_stats("P2")["metrics"]["reraise_vs_raise"]["k"],1)
        self.assertEqual(bot.opponent_stats("P2")["metrics"]["raise_to_bet"]["k"],1)

    def test_board_codes_are_street_scoped_no_lookahead(self):
        bot=AdaptiveGTO31Bot(10)
        hist=[event("flop","P2","check"),event("turn","P2","bet"),
              event("river","P2","check")]
        bot.observe_hand(10,hist,RIVER,"P1")
        events=list(bot._events["P2"])
        self.assertTrue(events[0]["board_id"].startswith("FLOP|"))
        self.assertTrue(events[1]["board_id"].startswith("TURN|"))
        self.assertIsNotNone(events[2]["board_id"])

    def test_anytwo_forced_preflop_excluded(self):
        bot=AdaptiveGTO31Bot(5)
        hist=[event("preflop","P2","call",call=1),event("preflop","P3","check"),
              event("flop","P2","bet"),event("flop","P3","fold",call=3)]
        with patch.dict(os.environ,{"POKER_PREFLOP_PROTOCOL":"any_two_limp"}):
            bot.observe_hand(1,hist,FLOP,"P1")
        self.assertEqual(bot.opponent_stats("P2")["n"],1)
        self.assertEqual(bot.opponent_stats("P3")["n"],1)
        self.assertEqual(bot.opponent_stats("P3")["metrics"]["fold_to_cbet"]["n"],0)

    def test_no_memory_parity_with_gto21_and_multiway_fallback(self):
        base=create_bot("gto_postflop_21")
        bot=AdaptiveGTO31Bot(5)
        for hand in range(20):
            hole=random.Random(hand).sample([(r,s) for r in "23456789TJQKA" for s in "shdc"], 2)
            view=make_view(hole=hole,board=FLOP,street="flop",pot=30,to_call=(6 if hand%2 else 0))
            for roll in (.0,.1,.5,.95):
                with patch("bots.postflop_profiles.random.random",return_value=roll):
                    a=base.act(view);b=bot.act(view)
                self.assertEqual((a.type,a.amount),(b.type,b.amount))
                self.assertEqual(bot.last_model["mode"],"gto21_fallback")
        multi=make_view(opponents=("P2","P3"),board=FLOP)
        bot.observe_hand(90,[event("flop","P2","check")]*5,FLOP,"P1")
        with patch("bots.postflop_profiles.random.random",return_value=.99):
            bot.act(multi)
        self.assertFalse(bot.last_model["adapted"])

    def test_all_player_fold_data_changes_bluff_frequency(self):
        bot=AdaptiveGTO31Bot(5)
        for hand in (1,2,3):
            bot.observe_hand(hand,[event("flop","P3","bet"),
                                   event("flop","P2","fold",call=5,pot=15)],FLOP,"P1")
        v=make_view(hole=(("7","s"),("2","d")),board=FLOP,position="BB",
                    opponents=("P2",),pot=24)
        v.hand_id=70
        with patch("bots.postflop_profiles.random.random",return_value=.10),patch(
            "bots.gto_postflop_31.random.random",return_value=.10):
            base=create_bot("gto_postflop_21").act(v)
            adaptive=bot.act(v)
        self.assertEqual(base.type,"check")
        self.assertEqual((adaptive.type,adaptive.amount),("bet",12))
        self.assertTrue(bot.last_model["adapted"])
        self.assertGreater(bot.last_model["stats"]["metrics"]["fold_to_bet"]["p"],.35)

    def test_cbet_metric_used_only_when_hero_was_preflop_aggressor(self):
        bot=AdaptiveGTO31Bot(10)
        for hand in (1,2,3):
            hist=[event("preflop","P1","raise"),
                  event("flop","P1","bet"),
                  event("flop","P2","fold",call=5,pot=15)]
            bot.observe_hand(hand,hist,FLOP,"P1")
        self.assertEqual(bot.opponent_stats("P2")["metrics"]["fold_to_cbet"]["n"],3)
        view=make_view(hole=(("7","s"),("2","d")),board=FLOP,
                       opponents=("P2",),pot=24,position="BB",
                       history=[event("preflop","P1","raise")])
        view.hand_id=80
        with patch("bots.gto_postflop_31.random.random",return_value=.0):
            bot.act(view)
        self.assertEqual(bot.last_model["fold_metric"],"fold_to_cbet")
        view.history=[]
        view.hand_id=81
        with patch("bots.gto_postflop_31.random.random",return_value=.0):
            bot.act(view)
        self.assertEqual(bot.last_model["fold_metric"],"fold_to_bet")

    def test_reraise_pressure_is_more_cautious_than_simple_bet(self):
        bot=AdaptiveGTO31Bot(10)
        for hand in (1,2,3):
            bot.observe_hand(hand,[event("flop","P2","check")],FLOP,"P1")
        view=make_view(hole=(("K","s"),("J","d")),board=FLOP,
                       to_call=9,pot=25,opponents=("P2",))
        view.hand_id=77
        view.history=[event("flop","P2","bet")]
        with patch("bots.postflop_profiles.random.random",return_value=.9):
            bot.act(view)
        bet_score=bot.last_model["pressure"]["score"]
        view.hand_id=78
        view.history=[event("flop","P1","bet"),event("flop","P2","raise",call=6),
                      event("flop","P1","raise",call=12),
                      event("flop","P2","raise",call=24)]
        with patch("bots.postflop_profiles.random.random",return_value=.9):
            bot.act(view)
        self.assertEqual(bot.last_model["pressure"]["action"],"reraise")
        self.assertGreater(bot.last_model["pressure"]["score"],bet_score)

    def test_open_aggression_changes_threat_not_claimed_equity(self):
        bot=AdaptiveGTO31Bot(10)
        for hand in (1,2,3):
            bot.observe_hand(hand,[event("flop","P2","bet",pot=25)],FLOP,"P1")
        v=make_view(hole=(("K","s"),("J","d")),board=FLOP,
                    to_call=9,pot=25,opponents=("P2",))
        v.hand_id=70
        v.history=[event("flop","P2","bet",pot=25)]
        with patch("bots.postflop_profiles.random.random",return_value=.9):
            base=create_bot("gto_postflop_21").act(v)
            adapted=bot.act(v)
        self.assertEqual(base.type,"fold")
        self.assertEqual(adapted.type,"call")
        self.assertEqual(bot.last_model["pressure"]["kind"],"uncalibrated_strength_signal")
        self.assertEqual(bot.last_model["pressure"]["action"],"bet")
        self.assertGreater(bot.last_model["pressure"]["score"],0)

    def test_real_engine_both_windows_hu_and_nine_max(self):
        with patch.dict(os.environ,{"POKER_PREFLOP_PROTOCOL":"any_two_limp"}):
            for n in (2,9):
                bots={f"P{i}":create_bot("split:a17_preflop:gto_postflop_31_"+str(
                    5 if i%2 else 10)) for i in range(1,n+1)}
                results=Table(rng=random.Random(150+n)).play_hand(
                    [Seat(pid,160) for pid in bots],small_blind=1,big_blind=2,
                    dealer_index=0,bot_for=bots)
                self.assertEqual(sum(results.values()),0)
                self.assertEqual(set(results),set(bots))


if __name__=="__main__":
    unittest.main()
