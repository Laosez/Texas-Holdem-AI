"""Regression and integration coverage for GTO V4's genuine two-pair fix."""
import random
import unittest
from unittest.mock import patch

from bots import create_bot
from bots.gto_postflop_v2 import GTOPostflopV2Bot
from bots.gto_postflop_v3 import GTOPostflopV3Bot
from bots.gto_postflop_v4 import GTOPostflopV4Bot
from core.engine import Seat, Table
from test_postflop_profiles import make_view
import planner_postflop_ev as ev
import replit_simulator as app


class GTOV4Tests(unittest.TestCase):
    def setUp(self):
        self.v2 = GTOPostflopV2Bot()
        self.v3 = GTOPostflopV3Bot()
        self.v4 = GTOPostflopV4Bot()

    def test_aq_genuine_top_two_pair_turn_and_river(self):
        hole = [("A", "s"), ("Q", "s")]
        for board in (
            [("A", "d"), ("Q", "d"), ("7", "c"), ("7", "h")],
            [("A", "d"), ("Q", "d"), ("7", "c"), ("7", "h"), ("2", "s")],
        ):
            with self.subTest(board=board):
                self.assertEqual(self.v3._read_hand(hole, board).made, "top_pair")
                self.assertEqual(self.v4._read_hand(hole, board).made, "monster")
                self.assertEqual(self.v2._read_hand(hole, board).made, "monster")

    def test_does_not_revalue_shared_or_weak_two_pair(self):
        # Only A contributes to the best two pairs (AAKK), not A2.
        a2 = [("A", "s"), ("2", "s")]
        a2_board = [("A", "d"), ("2", "d"), ("K", "c"), ("K", "h")]
        self.assertNotEqual(self.v4._read_hand(a2, a2_board).made, "monster")
        self.assertEqual(self.v4._read_hand(a2, a2_board).made,
                         self.v3._read_hand(a2, a2_board).made)

        t6 = [("T", "s"), ("6", "s")]
        weak = [("K", "d"), ("7", "c"), ("7", "h"), ("T", "d")]
        self.assertEqual(self.v3._read_hand(t6, weak).made, "weak_pair")
        self.assertEqual(self.v4._read_hand(t6, weak).made, "weak_pair")
        strong = [("T", "d"), ("6", "d"), ("2", "c"), ("2", "h")]
        self.assertEqual(self.v3._read_hand(t6, strong).made, "top_pair")
        self.assertEqual(self.v4._read_hand(t6, strong).made, "monster")

    def test_unrelated_categories_and_existing_v3_behaviors_unchanged(self):
        scenarios = [
            ([("K", "s"), ("2", "s")], [("K", "d"), ("9", "h"), ("4", "c")]),
            ([("5", "h"), ("5", "d")], [("A", "s"), ("A", "d"), ("9", "c")]),
            ([("T", "s"), ("6", "s")], [("T", "d"), ("6", "d"), ("2", "c")]),
            ([("T", "h"), ("T", "d")], [("T", "s"), ("7", "c"), ("2", "h")]),
            ([("K", "s"), ("2", "s")], [("K", "d"), ("7", "s"), ("4", "s")]),
        ]
        for hole, board in scenarios:
            with self.subTest(hole=hole, board=board):
                self.assertEqual(self.v4._read_hand(hole, board),
                                 self.v3._read_hand(hole, board))

    def test_genuine_two_pairs_retain_value_bet(self):
        aq = [("A", "s"), ("Q", "s")]
        board = [("A", "d"), ("Q", "d"), ("7", "c"), ("7", "h")]
        with patch("bots.postflop_profiles.random.random", return_value=.70):
            self.assertEqual(self.v3.act(make_view(hole=aq, board=board)).type, "check")
            self.assertEqual(self.v4.act(make_view(hole=aq, board=board)).type, "bet")
        with patch("bots.postflop_profiles.random.random", return_value=.50):
            self.assertEqual(self.v3.act(make_view(hole=aq, board=board, to_call=8, pot=24)).type, "call")
            self.assertEqual(self.v4.act(make_view(hole=aq, board=board, to_call=8, pot=24)).type, "raise")

    def test_registration_ui_catalog_and_split(self):
        self.assertEqual(create_bot("gto_postflop_v4").profile, "gto_postflop_v4")
        self.assertEqual(create_bot("split:pc_gto_80bb:gto_postflop_v4")
                         .postflop_bot.profile, "gto_postflop_v4")
        catalog = app.strategy_catalog()
        self.assertIn("gto_postflop_v4", catalog["postflop_strategies"])
        self.assertNotIn("gto_postflop_v4", catalog["preflop_strategies"])
        self.assertEqual(ev.PROFILE_NAMES["gto4"], "gto_postflop_v4")
        self.assertIn("gto_postflop_v4", app.UI.read_text(encoding="utf-8"))
        self.assertIn('option value="gto4"', app.PLAN_UI.read_text(encoding="utf-8"))

    def test_tournament_and_selected_hand_monte_carlo(self):
        bots = {
            "P1": create_bot("split:pc_gto_80bb:gto_postflop_v4"),
            "P2": create_bot("split:pc_gto_80bb:gto_postflop_v3"),
        }
        table = Table(rng=random.Random(417))
        changes = table.play_hand([Seat(pid, 160) for pid in bots],
                                  small_blind=1, big_blind=2,
                                  dealer_index=0, bot_for=bots)
        self.assertEqual(sum(changes.values()), 0)

        req = {
            "model": "selected", "hand": "AQs", "trials": 32, "cycles": 1,
            "hero_postflop": "gto3", "hero_position": "3", "hero_stack_bb": 20,
            "opponents": [{
                "profile": "builtin:any_two", "position": "9",
                "scenario": "rfi", "players": 9, "selector": "active",
                "entry_mode": "always", "entry_pct": 100, "postflop": "gto",
            }]
        }
        v3 = ev.calculate(req)
        v4 = ev.calculate({**req, "hero_postflop": "gto4"})
        self.assertEqual(v3["equity"]["AQs"], v4["equity"]["AQs"])
        self.assertIsInstance(v4["ev_bb"]["AQs"], float)
        self.assertEqual(v4["simulations_per_hand"], 32)


if __name__ == "__main__":
    unittest.main()
