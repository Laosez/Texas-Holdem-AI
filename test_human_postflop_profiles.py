"""Regression tests for five-profile postflop catalog and new human archetypes."""
import random
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import replit_simulator as app
from bots import create_bot
from bots.postflop_archetypes_v1 import HumanPostflopBot


def make_view(*, hole=(("7", "h"), ("2", "d")),
              board=(("A", "c"), ("K", "d"), ("9", "s")),
              street="flop", to_call=0, pot=30,
              opponents=("P2",), max_raise=200):
    legal = ([{"type": "fold"}, {"type": "call"},
              {"type": "raise", "min": 12, "max": max_raise}]
             if to_call else
             [{"type": "check"}, {"type": "bet", "min": 4, "max": max_raise}])
    return SimpleNamespace(
        me="P1", street=street, position="BTN",
        hole_cards=list(hole), board=list(board),
        to_call=to_call, pot=pot, legal_actions=legal,
        opponents=list(opponents), acting_opponents=list(opponents),
        all_in_opponents=[], history=[],
        stacks={"P1": 200, **{p: 200 for p in opponents}},
        hand_id=17,
    )


class HumanPostflopTests(unittest.TestCase):
    PRIMARY = (
        "gto_postflop_v1", "tag_postflop_v1", "lag_postflop_v1",
        "chaser_postflop_v1", "trapper_postflop_v1",
    )

    def test_catalog_five_primary_and_legacy_read_compat(self):
        cat = app.strategy_catalog()
        self.assertEqual(tuple(cat["postflop_strategies"][:5]), self.PRIMARY)
        for p in self.PRIMARY[1::2] + ("trapper_postflop_v1",):
            self.assertIn(p, cat["postflop_profiles"])
        for p in ("smart", "tag_punisher", "wide_defender", "baseline_sane",
                  "nit", "loose_passive", "maniac", "maniac_mixed",
                  "pressure_filler"):
            self.assertNotIn(p, cat["postflop_strategies"])
            self.assertTrue(app.available_postflop(p))
        for name in ("tag_postflop_v1", "chaser_postflop_v1", "trapper_postflop_v1"):
            self.assertNotIn(name, cat["preflop_strategies"])
            bot = create_bot("split:a17_preflop:" + name)
            self.assertIsInstance(bot.postflop_bot, HumanPostflopBot)
            self.assertEqual(bot.postflop_bot.profile, name)
            with self.assertRaises(ValueError):
                HumanPostflopBot(name).act(make_view(street="preflop"))
        rows = [{"pre": "pc_gto_80bb", "post": "smart"},
                {"pre": "a17_preflop", "post": "tag_punisher"}]
        self.assertEqual(len(app.validate_config({"bots": rows})["players"]), 2)
        html = app.UI.read_text(encoding="utf-8")
        self.assertIn('id="compareFivePost"', html)
        self.assertIn("chaser_postflop_v1:'Draw Chaser V1'", html)

    def test_trapper_plays_strong_hand_passively_on_dry_board(self):
        v = make_view(hole=(("A", "s"), ("A", "d")),
                      board=(("A", "h"), ("9", "c"), ("2", "d")))
        with patch("bots.postflop_archetypes_v1.random.random", return_value=.5):
            self.assertEqual(HumanPostflopBot("tag_postflop_v1").act(v).type, "bet")
            self.assertEqual(HumanPostflopBot("trapper_postflop_v1").act(v).type, "check")
            v.to_call = 7
            v.legal_actions = [
                {"type": "fold"}, {"type": "call"},
                {"type": "raise", "min": 12, "max": 200}]
            self.assertEqual(HumanPostflopBot("tag_postflop_v1").act(v).type, "raise")
            self.assertEqual(HumanPostflopBot("trapper_postflop_v1").act(v).type, "call")

    def test_chaser_overpays_flush_draw_where_tag_folds(self):
        v = make_view(hole=(("A", "s"), ("6", "s")),
                      board=(("K", "s"), ("Q", "s"), ("4", "c")),
                      to_call=9, pot=30)
        with patch("bots.postflop_archetypes_v1.random.random", return_value=.99):
            self.assertEqual(HumanPostflopBot("tag_postflop_v1").act(v).type, "fold")
            self.assertEqual(HumanPostflopBot("chaser_postflop_v1").act(v).type, "call")
            self.assertEqual(HumanPostflopBot("trapper_postflop_v1").act(v).type, "fold")

    def test_bet_sizes_clamped_and_engine_smoke(self):
        v = make_view(hole=(("A", "s"), ("A", "d")),
                      board=(("A", "h"), ("9", "c"), ("2", "d")),
                      max_raise=9)
        with patch("bots.postflop_archetypes_v1.random.random", return_value=0):
            for name in ("tag_postflop_v1", "chaser_postflop_v1", "trapper_postflop_v1"):
                act = HumanPostflopBot(name).act(v)
                self.assertEqual(act.type, "bet")
                self.assertTrue(4 <= act.amount <= 9)

        from core.engine import Table, Seat
        for n in (2, 9):
            with self.subTest(players=n):
                options = ("gto_postflop_v1", "tag_postflop_v1",
                           "lag_postflop_v1", "chaser_postflop_v1",
                           "trapper_postflop_v1")
                bots = {f"P{i}": create_bot("split:pc_gto_80bb:" + options[(i-1)%5])
                        for i in range(1, n+1)}
                seats = [Seat(f"P{i}", 160) for i in range(1, n+1)]
                table = Table(rng=random.Random(77+n))
                net = table.play_hand(seats, small_blind=1, big_blind=2,
                                      dealer_index=0, bot_for=bots)
                self.assertEqual(sum(net.values()), 0)
                self.assertEqual(set(net), set(bots))


if __name__ == "__main__":
    unittest.main()
