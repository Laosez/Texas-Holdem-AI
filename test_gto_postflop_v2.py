"""Versioned GTO V2 pocket-pair classification and engine integration tests."""
import random
import unittest
from unittest.mock import patch

from bots import create_bot
from bots.postflop_profiles import PostflopProfileBot, read_hand
from bots.gto_postflop_v2 import GTOPostflopV2Bot
from test_postflop_profiles import make_view
from core.engine import Seat, Table
import planner_postflop_ev as ev
import replit_simulator as app


class GTOPostflopV2Tests(unittest.TestCase):
    def test_weak_board_two_pair_no_longer_monster(self):
        cards=[("5","h"),("5","d")]
        board=[("A","s"),("A","d"),("9","c")]
        v2=GTOPostflopV2Bot()
        self.assertEqual(read_hand(cards,board).made,"monster")
        self.assertEqual(v2._read_hand(cards,board).made,"weak_pair")
        view=make_view(hole=cards,board=board,pot=24)
        with patch("bots.postflop_profiles.random.random",return_value=.5):
            self.assertEqual(PostflopProfileBot("gto_postflop_v1").act(view).type,"bet")
            self.assertEqual(v2.act(view).type,"check")
        view.to_call=8
        view.legal_actions=[
            {"type":"fold"},{"type":"call"},
            {"type":"raise","min":8,"max":200}]
        with patch("bots.postflop_profiles.random.random",return_value=.5):
            self.assertEqual(PostflopProfileBot("gto_postflop_v1").act(view).type,"raise")
            self.assertEqual(v2.act(view).type,"fold")

    def test_low_overpair_to_paired_board_keeps_protection(self):
        cards=[("6","h"),("6","d")]
        board=[("2","s"),("2","c"),("3","h")]
        bot=GTOPostflopV2Bot()
        self.assertEqual(bot._read_hand(cards,board).made,"top_pair")
        view=make_view(hole=cards,board=board,to_call=8,pot=24)
        with patch("bots.postflop_profiles.random.random",return_value=.5):
            self.assertEqual(bot.act(view).type,"call")

    def test_real_set_and_board_only_paired_river_are_untouched(self):
        bot=GTOPostflopV2Bot()
        cards=[("5","h"),("5","d")]
        self.assertEqual(bot._read_hand(cards,[("K","s"),("5","c"),("2","h")]).made,
                         "monster")
        board=[("A","h"),("A","d"),("9","s"),("9","c"),("K","h")]
        self.assertEqual(bot._read_hand(cards,board).made,
                         read_hand(cards,board).made)
        for hole,board in [
            ([("7","h"),("7","d")],[("A","s"),("A","d"),("9","c")]),
            ([("A","h"),("K","d")],[("A","s"),("9","c"),("5","c")]),
            ([("5","h"),("5","d")],[("K","s"),("Q","c"),("8","h")]),
        ]:
            self.assertEqual(bot._read_hand(hole,board),read_hand(hole,board))

    def test_registration_catalog_and_both_screen_selectors(self):
        self.assertEqual(create_bot("gto_postflop_v2").profile,"gto_postflop_v2")
        bot=create_bot("split:pc_gto_80bb:gto_postflop_v2")
        self.assertEqual(bot.postflop_bot.profile,"gto_postflop_v2")
        catalog=app.strategy_catalog()
        self.assertIn("gto_postflop_v1",catalog["postflop_strategies"])
        self.assertIn("gto_postflop_v2",catalog["postflop_strategies"])
        self.assertEqual(len(catalog["postflop_strategies"]),6)
        self.assertNotIn("gto_postflop_v2",catalog["preflop_strategies"])
        self.assertIn("gto_postflop_v2",app.UI.read_text(encoding="utf-8"))
        self.assertIn("{value:'gto2',label:'GTO V2'}",
                      app.PLAN_UI.read_text(encoding="utf-8"))
        self.assertEqual(ev.PROFILE_NAMES["gto2"],"gto_postflop_v2")
        request={
            "model":"selected","hand":"55","trials":50,"cycles":1,
            "hero_postflop":"gto2","hero_position":"3","hero_stack_bb":20,
            "opponents":[{
                "profile":"builtin:any_two","position":"9","scenario":"rfi",
                "players":9,"selector":"active","entry_mode":"always",
                "entry_pct":100,"postflop":"gto",
            }]
        }
        result=ev.calculate(request)
        self.assertIsInstance(result["ev_bb"]["55"],float)

    def test_v1_v2_and_other_profiles_engine_smoke(self):
        for players in (2,9):
            with self.subTest(players=players):
                profiles=["gto_postflop_v1","gto_postflop_v2","lag_postflop_v1",
                          "tag_postflop_v1","chaser_postflop_v1","trapper_postflop_v1"]
                bots={f"P{i}":create_bot("split:pc_gto_80bb:"+profiles[(i-1)%len(profiles)])
                      for i in range(1,players+1)}
                table=Table(rng=random.Random(900+players))
                net=table.play_hand([Seat(pid,160) for pid in bots],
                    small_blind=1,big_blind=2,dealer_index=0,bot_for=bots)
                self.assertEqual(sum(net.values()),0)


if __name__=="__main__":
    unittest.main()
