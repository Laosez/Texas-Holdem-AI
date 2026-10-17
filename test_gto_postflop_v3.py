"""GTO V3 postflop classification, decisions and Monte Carlo integration."""
import random
import unittest
from unittest.mock import patch

import planner_postflop_ev as ev
import replit_simulator as app
from bots import create_bot
from bots.gto_postflop_v2 import GTOPostflopV2Bot
from bots.gto_postflop_v3 import GTOPostflopV3Bot
from bots.postflop_profiles import read_hand
from core.engine import Seat,Table
from test_postflop_profiles import make_view


class GTOV3Tests(unittest.TestCase):
    def setUp(self):
        self.v2=GTOPostflopV2Bot()
        self.v3=GTOPostflopV3Bot()

    def test_board_shared_two_pairs_no_longer_monsters(self):
        hole=[("K","s"),("2","s")]
        for board,expected in (
            ([("K","d"),("7","h"),("7","c")],"top_pair"),
            ([("A","h"),("A","c"),("K","d")],"weak_pair"),
        ):
            with self.subTest(board=board):
                self.assertEqual(self.v2._read_hand(hole,board).made,"monster")
                self.assertEqual(self.v3._read_hand(hole,board).made,expected)
        self.assertEqual(self.v3._read_hand(hole,[("K","d"),("2","d"),("7","c")]).made,"monster")
        self.assertEqual(self.v3._read_hand([("K","h"),("K","c")],[("K","d"),("2","h"),("7","c")]).made,"monster")
        self.assertEqual(self.v3._read_hand([("5","h"),("5","c")],[("A","h"),("A","c"),("9","d")]).made,"weak_pair")
        self.assertEqual(self.v3._read_hand([("6","h"),("6","c")],[("2","h"),("2","c"),("3","d")]).made,"top_pair")

    def test_kicker_changes_bet_and_call_on_same_board(self):
        board=[("K","d"),("9","h"),("4","c")]
        kq=[("K","s"),("Q","s")]
        k2=[("K","s"),("2","s")]
        with patch("bots.gto_postflop_v3.random.random",return_value=.5):
            self.assertEqual(self.v2.act(make_view(hole=kq,board=board)).type,"bet")
            self.assertEqual(self.v2.act(make_view(hole=k2,board=board)).type,"bet")
            self.assertEqual(self.v3.act(make_view(hole=kq,board=board)).type,"bet")
            self.assertEqual(self.v3.act(make_view(hole=k2,board=board)).type,"check")
        with patch("bots.gto_postflop_v3.random.random",return_value=.5):
            self.assertEqual(self.v3.act(make_view(hole=kq,board=board,to_call=8,pot=24)).type,"call")
            self.assertEqual(self.v3.act(make_view(hole=k2,board=board,to_call=8,pot=24)).type,"fold")

    def test_top_pair_plus_flush_draw_has_its_own_line(self):
        hole=[("K","s"),("2","s")]
        board=[("K","d"),("7","s"),("4","s")]
        hand=read_hand(hole,board)
        self.assertEqual(hand.made,"top_pair")
        self.assertGreaterEqual(hand.draw_outs,8)
        with patch("bots.gto_postflop_v3.random.random",return_value=.5):
            self.assertEqual(self.v3.act(make_view(hole=hole,board=board)).type,"bet")
        # 0.25 price: pure weak-kicker top pair folds, pair+flush draw calls.
        with patch("bots.gto_postflop_v3.random.random",return_value=.5):
            self.assertEqual(self.v3.act(make_view(hole=hole,board=board,to_call=8,pot=24)).type,"call")
            self.assertEqual(self.v3.act(make_view(
                hole=hole,board=[("K","d"),("7","h"),("4","c")],to_call=8,pot=24)).type,"fold")
        self.assertEqual(self.v3.act(make_view(hole=hole,board=board,
                                               to_call=25,pot=24)).type,"fold")

    def test_multiway_reduces_value_bet_frequency(self):
        board=[("K","d"),("9","h"),("4","c")]
        hole=[("K","s"),("Q","s")]
        with patch("bots.gto_postflop_v3.random.random",return_value=.5):
            self.assertEqual(self.v3.act(make_view(hole=hole,board=board)).type,"bet")
            self.assertEqual(self.v3.act(make_view(hole=hole,board=board,
                                                  opponents=("P2","P3","P4"))).type,"check")

    def test_existing_v2_unaffected_and_registration(self):
        self.assertEqual(self.v2.profile,"gto_postflop_v2")
        self.assertEqual(create_bot("gto_postflop_v3").profile,"gto_postflop_v3")
        split=create_bot("split:pc_gto_80bb:gto_postflop_v3")
        self.assertEqual(split.postflop_bot.profile,"gto_postflop_v3")
        catalog=app.strategy_catalog()
        self.assertEqual(len(catalog["postflop_strategies"]),9)
        self.assertIn("random",catalog["postflop_strategies"])
        self.assertIn("gto_postflop_v3",catalog["postflop_strategies"])
        self.assertNotIn("gto_postflop_v3",catalog["preflop_strategies"])
        self.assertEqual(ev.PROFILE_NAMES["gto3"],"gto_postflop_v3")
        page=app.PLAN_UI.read_text(encoding="utf-8")
        self.assertIn('option value="gto3"',page)
        self.assertIn("{value:'gto3',label:'GTO V3 · эксперимент'}",page)
        self.assertIn("hero_postflop:$('heroPostflop').value",page)
        self.assertIn("gto_postflop_v3",app.UI.read_text(encoding="utf-8"))

    def test_v3_folds_and_calls_through_real_engine(self):
        for seatcount in (2,9):
            with self.subTest(seats=seatcount):
                names=["gto_postflop_v3","gto_postflop_v2","gto_postflop_v1",
                       "lag_postflop_v1","tag_postflop_v1"]
                bots={f"P{i}":create_bot("split:pc_gto_80bb:"+names[(i-1)%len(names)])
                      for i in range(1,seatcount+1)}
                table=Table(rng=random.Random(453+seatcount))
                changes=table.play_hand([Seat(pid,160) for pid in bots],small_blind=1,big_blind=2,
                                        dealer_index=0,bot_for=bots)
                self.assertEqual(sum(changes.values()),0)

    def test_equity_does_not_change_only_ev(self):
        req={
            "model":"selected","hand":"K2s","trials":60,"cycles":1,
            "hero_postflop":"gto2","hero_position":"3","hero_stack_bb":20,
            "opponents":[{"profile":"builtin:any_two","position":"9","scenario":"rfi",
                          "players":9,"selector":"active","entry_mode":"always",
                          "entry_pct":100,"postflop":"gto"}]
        }
        old=ev.calculate(req)
        new=ev.calculate({**req,"hero_postflop":"gto3"})
        self.assertEqual(old["equity"]["K2s"],new["equity"]["K2s"])
        self.assertIsInstance(old["ev_bb"]["K2s"],float)
        self.assertIsInstance(new["ev_bb"]["K2s"],float)


if __name__=="__main__":
    unittest.main()
