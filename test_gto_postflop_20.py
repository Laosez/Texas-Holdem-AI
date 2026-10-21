"""GTO 2.0 board-relative hand strength and legacy retirement regression tests."""
import random
import unittest
from unittest.mock import patch

from bots import create_bot
from bots.gto_postflop_20 import GTOPostflop20Bot, relative_tier
from bots.postflop_profiles import PostflopProfileBot, read_hand
from core.engine import Seat, Table
from test_postflop_profiles import make_view
import planner_postflop_ev as ev
import replit_simulator as app


class GTO20Tests(unittest.TestCase):
    def setUp(self):
        self.bot=GTOPostflop20Bot()

    def test_common_board_pair_is_not_a_value_hand(self):
        board=[("K","s"),("K","d"),("7","c"),("5","h"),("2","s")]
        hand=[("A","c"),("Q","d")]
        self.assertEqual(read_hand(hand,board).category,1)
        self.assertEqual(relative_tier(hand,board),0)
        self.assertEqual(self.bot._read_hand(hand,board).made,"air")
        self.assertEqual(relative_tier([("7","h"),("Q","d")],board),1)
        self.assertEqual(relative_tier([("A","c"),("A","h")],board),2)

    def test_shared_pair_downgrades_fake_two_pairs(self):
        self.assertEqual(relative_tier(
            [("5","h"),("5","d")],[("A","s"),("A","d"),("9","c")]),1)
        self.assertEqual(relative_tier(
            [("6","h"),("6","d")],[("2","s"),("2","c"),("3","h")]),2)
        self.assertEqual(relative_tier(
            [("K","s"),("2","d")],[("K","d"),("7","h"),("7","c")]),2)

    def test_real_two_pairs_and_stronger_hands_remain_value(self):
        # AQ improves the best two pairs; on A-Q-7-7 it is NOT merely top pair.
        board=[("A","d"),("Q","d"),("7","h"),("7","c"),("2","s")]
        self.assertEqual(relative_tier([("A","s"),("Q","h")],board),3)
        self.assertEqual(self.bot._read_hand([("A","s"),("Q","h")],board).made,"monster")
        self.assertEqual(relative_tier(
            [("A","s"),("Q","h")],[("A","d"),("Q","d"),("7","c")]),3)
        self.assertEqual(relative_tier(
            [("K","s"),("K","h")],[("K","d"),("7","h"),("2","c")]),3)
        self.assertEqual(relative_tier(
            [("A","s"),("Q","h")],[("K","s"),("K","d"),("K","c"),("2","s"),("2","d")]),0)

    def test_new_policy_changes_action_but_keeps_v1_unchanged(self):
        hole=[("5","h"),("5","d")]
        board=[("A","s"),("A","d"),("9","c")]
        view=make_view(hole=hole,board=board,to_call=8,pot=24)
        baseline=PostflopProfileBot("gto_postflop_v1")
        self.assertEqual(baseline._read_hand(hole,board).made,"monster")
        self.assertEqual(self.bot._read_hand(hole,board).made,"weak_pair")
        with patch("bots.postflop_profiles.random.random",return_value=.50):
            self.assertEqual(baseline.act(view).type,"raise")
            self.assertEqual(self.bot.act(view).type,"fold")

    def test_gto_1_and_20_retained_alongside_adaptive_30(self):
        catalog=app.strategy_catalog()
        expected={"gto_postflop_v1","gto_postflop_20",
                  "gto_postflop_30_5","gto_postflop_30_10"}
        self.assertEqual({name for name in catalog["postflop_strategies"]
                          if name.startswith("gto_postflop_")},expected)
        self.assertEqual(ev.PROFILE_NAMES["gto"],"gto_postflop_v1")
        self.assertEqual(ev.PROFILE_NAMES["gto20"],"gto_postflop_20")
        self.assertEqual(create_bot("gto_postflop_20").profile,"gto_postflop_20")
        self.assertEqual(create_bot("split:pc_gto_80bb:gto_postflop_20")
                         .postflop_bot.profile,"gto_postflop_20")
        for old in ("gto_postflop_v2","gto_postflop_v3","gto_postflop_v4"):
            with self.subTest(old=old),self.assertRaises(ValueError):
                create_bot(old)
            self.assertNotIn(old,catalog["postflop_strategies"])
        for old in ("gto2","gto3","gto4"):
            self.assertNotIn(old,ev.PROFILE_NAMES)
        page=app.PLAN_UI.read_text(encoding="utf-8")
        self.assertIn('<option value="gto20">GTO 2.0',page)
        self.assertIn('<option value="gto" selected>GTO 1',page)
        for old in ("<option value=\"gto2\"","<option value=\"gto3\"",
                    "<option value=\"gto4\""):
            self.assertNotIn(old,page)

    def test_engine_and_50_trial_ev_smoke(self):
        bots={
            "P1":create_bot("split:pc_gto_80bb:gto_postflop_v1"),
            "P2":create_bot("split:pc_gto_80bb:gto_postflop_20"),
        }
        table=Table(rng=random.Random(311))
        delta=table.play_hand([Seat(pid,160) for pid in bots],
                              small_blind=1,big_blind=2,dealer_index=0,bot_for=bots)
        self.assertEqual(sum(delta.values()),0)
        request={
            "model":"selected","hand":"K2s","trials":50,"cycles":1,
            "hero_postflop":"gto20","hero_position":"3","hero_stack_bb":20,
            "opponents":[{
                "profile":"builtin:any_two","position":"9","scenario":"rfi",
                "players":9,"selector":"active","entry_mode":"always",
                "entry_pct":100,"postflop":"gto",
            }]
        }
        result=ev.calculate(request)
        self.assertEqual(result["simulations_per_hand"],50)
        self.assertIsInstance(result["ev_bb"]["K2s"],float)
        self.assertAlmostEqual(result["decomposition"]["ev_bb"],
                               result["ev_bb"]["K2s"],places=3)


if __name__ == "__main__":
    unittest.main()
