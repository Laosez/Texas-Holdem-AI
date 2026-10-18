"""Postflop profile semantics and genuine engine integration."""
import random
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from bots.postflop_profiles import PostflopProfileBot,read_hand
from bots import create_bot
import replit_simulator as app


def make_view(*,hole=(("7","h"),("2","d")),
              board=(("A","c"),("K","d"),("9","s")),
              street="flop",to_call=0,pot=24,
              position="BTN",opponents=("P2",),
              history=(),max_raise=200):
    specs=([{"type":"fold"},{"type":"call"},{"type":"raise","min":8,"max":max_raise}]
           if to_call else [{"type":"check"},{"type":"bet","min":4,"max":max_raise}])
    return SimpleNamespace(
        me="P1",street=street,position=position,hole_cards=list(hole),
        board=list(board),pot=pot,to_call=to_call,legal_actions=specs,
        stacks={"P1":200,**{p:200 for p in opponents}},
        opponents=list(opponents),acting_opponents=list(opponents),
        all_in_opponents=[],history=list(history),hand_id=42)


class PostflopProfileTests(unittest.TestCase):
    def test_both_profiles_registered_for_postflop_only(self):
        catalog=app.strategy_catalog()
        for name in ("gto_postflop_v1","lag_postflop_v1"):
            self.assertIn(name,catalog["postflop_strategies"])
            self.assertNotIn(name,catalog["preflop_strategies"])
            self.assertIn(name,catalog["postflop_profiles"])
            self.assertEqual(catalog["postflop_profiles"][name]["model"],"heuristic")
            bot=create_bot("split:a17_preflop:"+name)
            self.assertEqual(bot.postflop_name,name)
            self.assertEqual(bot.postflop_bot.profile,name)
        self.assertNotIn("gto",catalog["postflop_strategies"])
        self.assertTrue(app.available_postflop("gto"))  # archive only
        with self.assertRaises(ValueError):
            PostflopProfileBot("gto")
        for name in ("gto_postflop_v1","lag_postflop_v1"):
            with self.assertRaises(ValueError):
                PostflopProfileBot(name).act(make_view(street="preflop"))
        ui=app.UI.read_text(encoding="utf-8")
        # Legacy quick experiment buttons were replaced by the mass-edit row.
        self.assertNotIn('id="comparePost"',ui)
        self.assertNotIn('id="compareFivePost"',ui)
        self.assertIn("function botBulkRow(){",ui)
        self.assertIn("function bulkChangeBots(street,value){",ui)
        self.assertIn("root.append(botBulkRow());",ui)
        self.assertIn('id="postflopModels"',ui)
        self.assertIn("gto_postflop_v1:'GTO Postflop V1 (model)'",ui)

    def test_made_value_relative_to_board_not_board_alone(self):
        board=[("Q","h"),("Q","d"),("2","s"),("2","c"),("7","h")]
        self.assertNotEqual(read_hand([("A","s"),("K","d")],board).made,"monster")
        board=[("5","h"),("6","d"),("7","s"),("8","c"),("9","h")]
        self.assertNotEqual(read_hand([("A","s"),("K","d")],board).made,"monster")
        board=[("A","s"),("9","d"),("2","h")]
        self.assertEqual(read_hand([("A","c"),("Q","d")],board).made,"top_pair")
        self.assertEqual(read_hand([("A","c"),("A","d")],board).made,"monster")

    def test_draws_flush_open_ender_missed_and_blockers(self):
        flush=read_hand([("6","s"),("5","s")],
                        [("9","s"),("8","s"),("K","d")])
        self.assertGreaterEqual(flush.draw_outs,9)
        missed=read_hand([("A","s"),("6","s")],
                         [("K","s"),("Q","s"),("4","c"),("2","d"),("9","h")])
        self.assertTrue(missed.missed_draw)
        self.assertEqual(missed.made,"air")
        blocker=read_hand([("A","h"),("3","c")],
                          [("K","h"),("J","h"),("8","h"),("2","s"),("5","c")])
        self.assertTrue(blocker.blocker)

    def test_lag_bluffs_air_more_often_than_gto_and_uses_same_legal_sizes(self):
        pfr=({"street":"preflop","pid":"P1","type":"raise","amount":6},)
        v=make_view(history=pfr)
        with patch("bots.postflop_profiles.random.random",return_value=.50):
            gto=PostflopProfileBot("gto_postflop_v1").act(v)
            lag=PostflopProfileBot("lag_postflop_v1").act(v)
        self.assertEqual(gto.type,"check")
        self.assertEqual(lag.type,"bet")
        self.assertTrue(4<=lag.amount<=200)
        # Multiway scaling: at this exact roll LAG checks rather than
        # auto-bluffing five-way.
        v5=make_view(history=pfr,opponents=("P2","P3","P4","P5"))
        with patch("bots.postflop_profiles.random.random",return_value=.50):
            self.assertEqual(PostflopProfileBot("lag_postflop_v1").act(v5).type,"check")

    def test_lag_semi_bluff_raises_and_gto_calls_a_live_draw(self):
        v=make_view(
            hole=(("6","s"),("5","s")),
            board=(("9","s"),("8","s"),("K","d")),
            to_call=3,pot=30)
        with patch("bots.postflop_profiles.random.random",return_value=.35):
            self.assertEqual(PostflopProfileBot("gto_postflop_v1").act(v).type,"call")
            lag=PostflopProfileBot("lag_postflop_v1").act(v)
        self.assertEqual(lag.type,"raise")
        self.assertTrue(8<=lag.amount<=200)

    def test_river_missed_draw_bluff_and_no_air_hero_calls(self):
        v=make_view(hole=(("A","s"),("6","s")),
                    board=(("K","s"),("Q","s"),("4","c"),("2","d"),("9","h")),
                    street="river")
        with patch("bots.postflop_profiles.random.random",return_value=0.0):
            self.assertEqual(PostflopProfileBot("gto_postflop_v1").act(v).type,"bet")
            self.assertEqual(PostflopProfileBot("lag_postflop_v1").act(v).type,"bet")
        with patch("bots.postflop_profiles.random.random",return_value=.9999):
            self.assertEqual(PostflopProfileBot("gto_postflop_v1").act(v).type,"check")
        v.to_call=11
        v.legal_actions=[{"type":"fold"},{"type":"call"},{"type":"raise","min":24,"max":200}]
        with patch("bots.postflop_profiles.random.random",return_value=.9999):
            self.assertEqual(PostflopProfileBot("gto_postflop_v1").act(v).type,"fold")

    def test_short_stack_sizing_and_real_hands_chip_conservation(self):
        v=make_view(hole=(("A","s"),("A","d")),
                    board=(("A","h"),("9","c"),("2","d")),max_raise=9)
        with patch("bots.postflop_profiles.random.random",return_value=.0):
            for name in ("gto_postflop_v1","lag_postflop_v1"):
                out=PostflopProfileBot(name).act(v)
                self.assertEqual(out.type,"bet")
                self.assertTrue(4<=out.amount<=9)
        from core.engine import Table,Seat
        for n in (2,9):
            with self.subTest(players=n):
                bots={f"P{i}":create_bot("split:pc_gto_80bb:"+(
                    "lag_postflop_v1" if i%2 else "gto_postflop_v1"))
                    for i in range(1,n+1)}
                seats=[Seat(f"P{i}",160) for i in range(1,n+1)]
                t=Table(rng=random.Random(91+n))
                net=t.play_hand(seats,small_blind=1,big_blind=2,
                                dealer_index=0,bot_for=bots)
                self.assertEqual(sum(net.values()),0)
                self.assertEqual(set(net),set(bots))

if __name__=="__main__":unittest.main()
