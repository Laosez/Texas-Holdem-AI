"""Regression tests for Monte Carlo showdown equity and split pots.

Run from repository root:
    python -m unittest tests/test_monte_carlo_equity.py
"""
import unittest
import random
import os
from unittest.mock import patch

from bots.monte_carlo_bot import MonteCarloBot
from core.equity import equity


class MonteCarloEquityTests(unittest.TestCase):
    # Royal flush on board: every live player shares the exact same best hand.
    BOARD = [("A", "s"), ("K", "s"), ("Q", "s"), ("J", "s"), ("T", "s")]
    HERO = [("2", "c"), ("3", "d")]

    def test_heads_up_board_tie(self):
        self.assertAlmostEqual(MonteCarloBot()._estimate_equity(self.HERO, self.BOARD, 1, 100), 0.5)

    def test_three_way_board_tie(self):
        self.assertAlmostEqual(MonteCarloBot()._estimate_equity(self.HERO, self.BOARD, 2, 100), 1 / 3)

    def test_four_way_board_tie(self):
        self.assertAlmostEqual(MonteCarloBot()._estimate_equity(self.HERO, self.BOARD, 3, 100), 0.25)

    def test_shared_calculator_consistency(self):
        for n_opponents in (1, 2, 3, 5, 8):
            with self.subTest(n_opponents=n_opponents):
                result = MonteCarloBot()._estimate_equity(self.HERO, self.BOARD, n_opponents, 20)
                self.assertAlmostEqual(result, equity(self.HERO, self.BOARD, n_opponents, 20))
                self.assertAlmostEqual(result, 1 / (n_opponents + 1))

    def test_reproducible_sampling(self):
        hole = [("A", "h"), ("K", "d")]
        board = [("2", "s"), ("7", "c"), ("J", "h")]
        one = equity(hole, board, 3, n_sims=200, rng=random.Random(42))
        two = equity(hole, board, 3, n_sims=200, rng=random.Random(42))
        self.assertEqual(one, two)
        self.assertTrue(0 <= one <= 1)

    def test_duplicate_or_invalid_cards_rejected(self):
        with self.assertRaises(ValueError):
            equity([("A", "s"), ("A", "s")], [], 1, 10)
        with self.assertRaises(ValueError):
            equity([("A", "s"), ("K", "s")], [("A", "s"), ("2", "h"), ("3", "c")], 1, 10)
        with self.assertRaises(ValueError):
            equity([("A", "s"), ("K", "s")], [("X", "s"), ("2", "h"), ("3", "c")], 1, 10)

    def test_impossible_deal_rejected(self):
        with self.assertRaises(ValueError):
            equity([("A", "s"), ("K", "s")], [], 23, 10)
        with self.assertRaises(ValueError):
            equity([("A", "s"), ("K", "s")], [], 1, 0)

    def test_hero_unbeatable_on_river(self):
        hole = [("A", "s"), ("K", "s")]
        board = [("Q", "s"), ("J", "s"), ("T", "s"), ("2", "d"), ("3", "c")]
        self.assertEqual(equity(hole, board, 5, 30, rng=random.Random(2)), 1.0)

    def test_default_fast_matches_legacy_for_same_deals(self):
        hole = [("Q", "h"), ("J", "h")]
        board = [("8", "s"), ("7", "d"), ("2", "c")]
        kwargs = dict(hole_cards=hole, board=board, n_opponents=4, n_sims=2000)
        with patch.dict(os.environ, {"THAI_EQUITY_EVALUATOR": "fast"}):
            fast = equity(**kwargs, rng=random.Random(771))
        with patch.dict(os.environ, {"THAI_EQUITY_EVALUATOR": "legacy"}):
            legacy = equity(**kwargs, rng=random.Random(771))
        self.assertEqual(fast, legacy)

    def test_invalid_evaluator_switch(self):
        with patch.dict(os.environ, {"THAI_EQUITY_EVALUATOR": "unknown"}):
            with self.assertRaises(ValueError):
                equity([("A", "s"), ("K", "d")], [], 1, 1, rng=random.Random(1))


if __name__ == "__main__":
    unittest.main()
