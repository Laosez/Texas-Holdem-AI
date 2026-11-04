"""GTO 4.0 all-street range EV and simulator integration tests."""
import os
import random
import unittest
from unittest.mock import patch

from bots import create_bot
from bots.gto_postflop_40 import _range_rows, _range_equity, StreetEVGTO40Bot
from core.engine import Seat, Table
from test_postflop_profiles import make_view
import replit_simulator as app


def rows(vals):
    return [(i,v) for i,v in enumerate(vals)], {
        "possible_hands":990,"sampled_hands":len(vals),
        "runouts_per_hand":1, "categories_pct":{}, "draws_4plus_pct":0}


BOARDS={
    "flop":[("K","c"),("Q","d"),("3","h")],
    "turn":[("K","c"),("Q","d"),("3","h"),("4","s")],
    "river":[("K","c"),("Q","d"),("3","h"),("4","s"),("5","c")],
}


class GTO40Tests(unittest.TestCase):
    def test_registration(self):
        for window in (5,10):
            name="gto_postflop_40_"+str(window)
            b=create_bot(name)
            self.assertIsInstance(b,StreetEVGTO40Bot)
            if window == 5:
                self.assertIn(name, app.strategy_catalog()["postflop_strategies"])
            else:
                self.assertNotIn(name, app.strategy_catalog()["postflop_strategies"])
                self.assertTrue(app.available_postflop(name))
            self.assertEqual(create_bot("split:a17_preflop:"+name).postflop_name,name)
        self.assertIn('id="gto40Matrix"',app.UI.read_text(encoding="utf-8"))

    def test_quantile_band(self):
        a=[(1,.9),(2,.7),(3,.3),(4,.1)]
        self.assertAlmostEqual(_range_equity(a),.5)
        self.assertAlmostEqual(_range_equity(a,.5,1),.2)
        self.assertAlmostEqual(_range_equity(a,0,.5),.8)
        self.assertAlmostEqual(_range_equity(a,.125,.375),.8)

    def test_real_anytwo_possible_hands_and_draw_runouts(self):
        hero=[("K","s"),("J","d")]
        for street,total in (("flop",1081),("turn",1035),("river",990)):
            a,info=_range_rows(hero,BOARDS[street])
            b,info2=_range_rows(hero,BOARDS[street])
            self.assertEqual((a,info),(b,info2))
            self.assertEqual(info["possible_hands"],total)
            self.assertTrue(all(0<=eq<=1 for _,eq in a))
            self.assertAlmostEqual(sum(info["categories_pct"].values()),100,delta=.8)
            self.assertGreater(info["runouts_per_hand"],1 if street!="river" else 0)

    def test_call_fold_uses_equity_on_all_three_streets(self):
        for street,board in BOARDS.items():
            view=make_view(hole=(("7","h"),("2","d")),board=board,street=street,
                           to_call=50,pot=150,opponents=("P2",),
                           history=({"street":street,"pid":"P2",
                                     "type":"bet","to_call_before":0},))
            for eq,expected in ((.9,"call"),(.1,"fold")):
                bot=StreetEVGTO40Bot(5)
                with patch("bots.gto_postflop_40._range_rows",
                           return_value=rows([eq]*20)):
                    decision=bot.act(view)
                self.assertEqual(decision.type,expected)
                self.assertEqual(bot.last_model["mode"],"gto40_vs_bet")
                self.assertAlmostEqual(bot.last_model["decision_inputs"]["pot_odds"],.25)

    def test_bet_check_uses_ev_on_all_three_streets(self):
        for street,board in BOARDS.items():
            view=make_view(hole=(("K","h"),("J","d")),board=board,
                           street=street,pot=100,opponents=("P2",))
            for eqs,expected in (([.4]*17+[0]*3,"bet"),
                                 ([0]*17+[1]*3,"check")):
                bot=StreetEVGTO40Bot(10)
                with patch("bots.gto_postflop_40._range_rows",
                           return_value=rows(eqs)):
                    decision=bot.act(view)
                self.assertEqual(decision.type,expected)
                self.assertIn("bet",bot.last_model["ev"])
                self.assertIn("check",bot.last_model["ev"])
                if expected=="bet":
                    self.assertEqual(decision.amount,50)

    def test_street_memory_separation_and_multiway_fallback(self):
        bot=StreetEVGTO40Bot(5)
        for i in range(5):
            bot.observe_hand(i,[{"street":"river","pid":"P2","type":"bet",
                "to_call_before":0,"legal_types":["check","bet"]}],[],"P1")
        matrix=bot.street_matrix("P2")
        self.assertEqual(matrix["river"]["open"]["bet"]["n"],5)
        self.assertEqual(matrix["flop"]["open"]["bet"]["n"],0)
        multi=make_view(opponents=("P2","P3"))
        action=bot.act(multi)
        self.assertIn(action.type,{"check","bet"})
        self.assertEqual(bot.last_model["version"],"gto4.0_multiway_fallback_3.3")

    def test_engine_hu_and_nine_max(self):
        with patch.dict(os.environ,{"POKER_PREFLOP_PROTOCOL":"any_two_limp"}):
            for n in (2,9):
                bots={f"P{i}":create_bot("split:a17_preflop:gto_postflop_40_"+
                    ("5" if i%2 else "10")) for i in range(1,n+1)}
                result=Table(rng=random.Random(n+902)).play_hand(
                    [Seat(pid,160) for pid in bots],small_blind=1,big_blind=2,
                    dealer_index=0,bot_for=bots)
                self.assertEqual(sum(result.values()),0)


if __name__=="__main__":
    unittest.main()
