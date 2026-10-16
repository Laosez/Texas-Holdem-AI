"""Regression tests for engine-level evaluator selection and parity."""
import unittest
from unittest.mock import patch

from core import engine
from core.fast_eval import fast_eval_hand


class EngineEvaluatorTests(unittest.TestCase):
    def test_engine_fast_path_never_needs_legacy_lookup(self):
        hole = [("A", "s"), ("K", "s")]
        board = [("Q", "s"), ("J", "s"), ("T", "s"), ("2", "c"), ("3", "d")]
        # If the engine accidentally calls the legacy evaluator, this fails.
        with patch.object(engine, "_load_or_build_five_card_table", side_effect=AssertionError("eager table use")):
            self.assertEqual(engine.eval_hand(hole, board), fast_eval_hand(hole, board))

    def test_preflop_engine_parity(self):
        for hole in ([("A", "s"), ("A", "h")], [("A", "s"), ("K", "s")],
                     [("2", "s"), ("7", "h")]):
            with self.subTest(hole=hole):
                self.assertEqual(engine.eval_hand(hole, []), engine._legacy_eval_hand(hole, []))


if __name__ == "__main__":
    unittest.main()
