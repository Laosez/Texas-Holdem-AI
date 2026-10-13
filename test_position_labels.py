"""Regression tests for dealer-first labels as the tournament table shrinks."""
import unittest

from core.table_order import position_labels, position_group, position_tightness

EXPECTED = {
    n: (["SB", "BB"] if n == 2
        else ["3", "SB", "BB"] + [str(k) for k in range(n, 3, -1)])
    for n in range(2, 11)
}


class TestPositionLabels(unittest.TestCase):
    def test_all_supported_table_sizes(self):
        for count, expected in EXPECTED.items():
            with self.subTest(players=count):
                self.assertEqual(position_labels(count), expected)
                self.assertEqual(len(set(position_labels(count))), count)

    def test_numeric_scheme_is_consistent(self):
        self.assertEqual(position_labels(9),
                         ["3", "SB", "BB", "9", "8", "7", "6", "5", "4"])
        self.assertEqual(position_labels(2), ["SB", "BB"])
        self.assertEqual(position_group("9", 9), "early")
        self.assertEqual(position_group("6", 6), "early")
        self.assertEqual(position_group("6", 9), "middle")
        self.assertEqual(position_group("3", 3), "late")
        self.assertEqual(position_tightness("SB", 2), 0.0)
        self.assertEqual(position_tightness("SB", 9), 0.5)
        self.assertEqual(position_tightness("8", 8), 1.0)

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
