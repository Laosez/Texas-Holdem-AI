"""Regression tests for dealer-first labels as the tournament table shrinks."""
import unittest

from core.table_order import position_labels

EXPECTED = {
    2: ["BTN", "BB"],
    3: ["BTN", "SB", "BB"],
    4: ["BTN", "SB", "BB", "CO"],
    5: ["BTN", "SB", "BB", "HJ", "CO"],
    6: ["BTN", "SB", "BB", "UTG", "HJ", "CO"],
    7: ["BTN", "SB", "BB", "UTG", "LJ", "HJ", "CO"],
    8: ["BTN", "SB", "BB", "UTG", "MP", "LJ", "HJ", "CO"],
    9: ["BTN", "SB", "BB", "UTG", "UTG+1", "MP", "LJ", "HJ", "CO"],
    10: ["BTN", "SB", "BB", "UTG", "UTG+1", "UTG+2", "MP", "LJ", "HJ", "CO"],
}


class TestPositionLabels(unittest.TestCase):
    def test_all_supported_table_sizes(self):
        for count, expected in EXPECTED.items():
            with self.subTest(players=count):
                self.assertEqual(position_labels(count), expected)
                self.assertEqual(len(set(position_labels(count))), count)

    def test_invalid_table_sizes(self):
        for count in (0, 1, 11, -1):
            with self.subTest(players=count):
                with self.assertRaises(ValueError):
                    position_labels(count)

    def test_legacy_table_uses_shared_labels(self):
        from core.engine import Table
        for count, expected in EXPECTED.items():
            with self.subTest(players=count):
                self.assertEqual(Table()._positions(count), expected)

    def test_tournament_hybrid_uses_shared_labels(self):
        from bots.tournament_hybrid_bot import TournamentHybridBot
        for count, expected in EXPECTED.items():
            with self.subTest(players=count):
                self.assertEqual(TournamentHybridBot._positions_for_n(count), expected)


if __name__ == "__main__":
    unittest.main()
