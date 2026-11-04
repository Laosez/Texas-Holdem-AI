"""Ablations GTO 2.1a-f: behavior, legal actions, risk and original controls."""
import os
import random
import unittest
from unittest.mock import patch

from bots import create_bot
from bots.gto_postflop_21_variants import GTOPostflop21VariantBot
from core.engine import Seat, Table
from test_postflop_profiles import make_view
import replit_simulator as app


def action(bot, view, roll):
    with patch("bots.postflop_profiles.random.random", return_value=roll):
        return bot.act(view)


class GTO21VariantTests(unittest.TestCase):
    def setUp(self):
        self.base = create_bot("gto_postflop_21")

    def test_all_six_variants_registered_and_legal_in_any_two(self):
        available = app.strategy_catalog()["postflop_strategies"]
        for letter in "abcdef":
            name = "gto_postflop_21" + letter
            with self.subTest(variant=letter):
                self.assertIn(name, available)
                self.assertIn(name, app.strategy_catalog()["postflop_profiles"])
                self.assertIsInstance(create_bot(name), GTOPostflop21VariantBot)
                split = create_bot("split:a17_preflop:" + name)
                self.assertEqual(split.postflop_name, name)
        self.assertIn("gto21Variants", app.UI.read_text(encoding="utf-8"))
        self.assertEqual(app.validate_config({"preflop_protocol": "any_two_limp"})["preflop_protocol"],
                         "any_two_limp")

    def test_a_looser_calls_and_b_tighter_calls(self):
        board = (("A", "c"), ("9", "d"), ("2", "h"))
        hand = (("A", "s"), ("Q", "d"))
        v = make_view(hole=hand, board=board, to_call=9, pot=25)
        self.assertEqual(action(self.base, v, .90).type, "fold")
        self.assertEqual(action(create_bot("gto_postflop_21a"), v, .90).type, "call")
        self.assertEqual(action(create_bot("gto_postflop_21b"), v, .90).type, "fold")
        v.to_call = 6
        self.assertEqual(action(self.base, v, .90).type, "call")
        self.assertEqual(action(create_bot("gto_postflop_21b"), v, .90).type, "fold")
        self.assertEqual(action(create_bot("gto_postflop_21a"), v, .90).type, "call")

    def test_c_more_air_bluffs_only(self):
        v = make_view(hole=(("7", "s"), ("2", "d")),
                      board=(("K", "c"), ("Q", "d"), ("3", "h")),
                      street="flop", to_call=0, pot=24, position="BB")
        self.assertEqual(action(self.base, v, .10).type, "check")
        c = action(create_bot("gto_postflop_21c"), v, .10)
        self.assertEqual(c.type, "bet")
        self.assertEqual(c.amount, 12)
        # With a wager facing it, both air policies fold.
        v.to_call = 8
        v.legal_actions = [{"type": "fold"}, {"type": "call"},
                           {"type": "raise", "min": 16, "max": 200}]
        self.assertEqual(action(self.base, v, .0).type, "fold")
        self.assertEqual(action(create_bot("gto_postflop_21c"), v, .0).type, "fold")

    def test_d_value_bets_and_raises_more(self):
        v = make_view(hole=(("A", "s"), ("A", "d")),
                      board=(("A", "h"), ("9", "c"), ("2", "d")),
                      to_call=0, pot=24)
        self.assertEqual(action(self.base, v, .90).type, "check")
        d = action(create_bot("gto_postflop_21d"), v, .90)
        self.assertEqual((d.type, d.amount), ("bet", 12))
        v.to_call = 6
        v.legal_actions = [{"type": "fold"}, {"type": "call"},
                           {"type": "raise", "min": 12, "max": 200}]
        self.assertEqual(action(self.base, v, .65).type, "call")
        self.assertEqual(action(create_bot("gto_postflop_21d"), v, .65).type, "raise")

    def test_e_corrects_only_heads_up_sb_ip(self):
        v = make_view(hole=(("7", "s"), ("2", "d")),
                      board=(("K", "c"), ("Q", "d"), ("3", "h")),
                      street="flop", to_call=0, pot=24, position="SB")
        self.assertEqual(action(self.base, v, .07).type, "check")
        self.assertEqual(action(create_bot("gto_postflop_21e"), v, .07).type, "bet")
        self.assertEqual(v.position, "SB")  # original view never mutated
        v.position = "BB"
        self.assertEqual(action(self.base, v, .07).type, "check")
        self.assertEqual(action(create_bot("gto_postflop_21e"), v, .07).type, "check")
        v.position = "SB"
        v.opponents = ["P2", "P3"]
        v.acting_opponents = ["P2", "P3"]
        self.assertEqual(action(create_bot("gto_postflop_21e"), v, .04).type,
                         action(self.base, v, .04).type)

    def test_f_reclassifies_only_dominated_four_suit_flush(self):
        board = (("A", "s"), ("K", "s"), ("8", "s"), ("5", "s"), ("2", "d"))
        weak = (("3", "s"), ("4", "h"))
        strong = (("Q", "s"), ("4", "h"))
        f = create_bot("gto_postflop_21f")
        self.assertEqual(self.base._read_hand(weak, board).made, "monster")
        self.assertEqual(f._read_hand(weak, board).made, "top_pair")
        self.assertEqual(f._read_hand(strong, board).made, "monster")
        self.assertEqual(self.base._read_hand(strong, board).made, "monster")
        view = make_view(hole=weak, board=board, street="river", pot=24)
        self.assertEqual(action(self.base, view, .70).type, "bet")
        self.assertEqual(action(f, view, .70).type, "check")

    def test_original_gto20_gto21_and_gto1_remain_unchanged(self):
        base20 = create_bot("gto_postflop_20")
        base21 = create_bot("gto_postflop_21")
        self.assertFalse(hasattr(base20, "_policy_tuning"))
        self.assertFalse(hasattr(base21, "_policy_tuning"))
        cases = random.Random(20261104)
        deck = [(r, s) for r in "23456789TJQKA" for s in "shdc"]
        for i in range(120):
            sample = cases.sample(deck, 7)
            street = ("flop", "turn", "river")[i % 3]
            v = make_view(hole=sample[:2], board=sample[2:5+i%3],
                          street=street, pot=32, to_call=6 if i % 2 else 0)
            for roll in (.0, .08, .2, .5, .75, .99):
                a = action(base20, v, roll)
                b = action(base21, v, roll)
                self.assertEqual(a.type, b.type)

    def test_live_engine_two_and_nine_players(self):
        with patch.dict(os.environ, {"POKER_PREFLOP_PROTOCOL": "any_two_limp"}):
            for n in (2, 9):
                names = ("abcdef"*2)[:n]
                bots = {f"P{i}": create_bot("split:a17_preflop:gto_postflop_21"+names[i-1])
                        for i in range(1,n+1)}
                result = Table(rng=random.Random(20261104+n)).play_hand(
                    [Seat(pid, 160) for pid in bots], 1, 2, 0, bots)
                self.assertEqual(sum(result.values()), 0)
                self.assertEqual(set(result), set(bots))


if __name__ == "__main__":
    unittest.main()
