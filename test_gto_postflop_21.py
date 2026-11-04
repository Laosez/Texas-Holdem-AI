"""GTO 2.1: identical action choices to GTO 2.0, half-pot size only."""
import math
import os
import random
import unittest
from unittest.mock import patch

from bots import create_bot
from bots.gto_postflop_20 import GTOPostflop20Bot
from bots.gto_postflop_21 import GTOPostflop21Bot
from core.engine import Seat, Table
from test_postflop_profiles import make_view
import replit_simulator as app


class GTOPostflop21Tests(unittest.TestCase):
    def setUp(self):
        self.v20 = GTOPostflop20Bot()
        self.v21 = GTOPostflop21Bot()

    def compare(self, view, roll=0.0):
        with patch("bots.postflop_profiles.random.random", return_value=roll):
            a = self.v20.act(view)
            b = self.v21.act(view)
        self.assertEqual(a.type, b.type)
        if b.type in ("bet", "raise"):
            self.assertIn(b.type, {v["type"] for v in view.legal_actions})
            minimum = next(v["min"] for v in view.legal_actions if v["type"] == b.type)
            maximum = next(v["max"] for v in view.legal_actions if v["type"] == b.type)
            self.assertGreaterEqual(b.amount, minimum)
            self.assertLessEqual(b.amount, maximum)
        return a, b

    def test_bet_is_half_pot_every_street_including_dry_and_wet(self):
        boards = [
            ("flop", (("A", "h"), ("9", "c"), ("2", "d"))),
            ("flop", (("A", "h"), ("9", "h"), ("2", "d"))),
            ("turn", (("A", "h"), ("9", "c"), ("2", "d"), ("4", "s"))),
            ("river", (("A", "h"), ("9", "c"), ("2", "d"), ("4", "s"), ("5", "c"))),
        ]
        for street, board in boards:
            with self.subTest(street=street, board=board):
                v = make_view(hole=(("A", "s"), ("A", "d")),
                              board=board, street=street, pot=31)
                _, b = self.compare(v, roll=0.0)
                self.assertEqual(b.type, "bet")
                self.assertEqual(b.amount, math.ceil(31 * 0.5))

    def test_raise_sizes_and_legal_bounds(self):
        view = make_view(hole=(("A", "s"), ("A", "d")),
                         board=(("A", "h"), ("9", "c"), ("2", "d")),
                         street="flop", to_call=9, pot=38)
        _, b = self.compare(view, roll=0.0)
        self.assertEqual(b.type, "raise")
        self.assertEqual(b.amount, 9 + math.ceil((38 + 9) * 0.50))
        view.legal_actions[-1]["min"] = 40
        _, b = self.compare(view, roll=0.0)
        self.assertEqual(b.amount, 40)
        view.legal_actions[-1]["max"] = 42
        _, b = self.compare(view, roll=0.0)
        self.assertEqual(b.amount, 40)
        view.legal_actions[-1]["min"] = 8
        view.legal_actions[-1]["max"] = 20
        _, b = self.compare(view, roll=0.0)
        self.assertEqual(b.amount, 20)

    def test_action_selection_parity_on_sampled_deals(self):
        deck = [(r, s) for r in "23456789TJQKA" for s in "shdc"]
        rng = random.Random(20261104)
        for i in range(120):
            cards = rng.sample(deck, 7)
            stage = ("flop", "turn", "river")[i % 3]
            board = cards[2:5 + i % 3]
            view = make_view(hole=cards[:2], board=board,
                             street=stage, to_call=6 if i % 2 == 0 else 0,
                             pot=35, position="BB" if i % 4 else "SB")
            self.compare(view, roll=(i % 19) / 19.0)

    def test_registered_and_any_two_experiment_compatibility(self):
        c = app.strategy_catalog()
        self.assertIn("gto_postflop_21", c["postflop_strategies"])
        self.assertIn("gto_postflop_21", c["postflop_profiles"])
        self.assertNotIn("gto_postflop_21", c["preflop_strategies"])
        self.assertIn("gto_postflop_21", app.UI.read_text(encoding="utf-8"))
        with patch.dict(os.environ, {"POKER_PREFLOP_PROTOCOL": "any_two_limp"}):
            bots = {
                "P1": create_bot("split:pc_gto_80bb:gto_postflop_20"),
                "P2": create_bot("split:pc_gto_80bb:gto_postflop_21")
            }
            table = Table(rng=random.Random(21))
            result = table.play_hand([Seat("P1", 160), Seat("P2", 160)],
                                     small_blind=1, big_blind=2,
                                     dealer_index=0, bot_for=bots)
        self.assertEqual(sum(result.values()), 0)
        self.assertEqual(set(result), {"P1", "P2"})


if __name__ == "__main__":
    unittest.main()
