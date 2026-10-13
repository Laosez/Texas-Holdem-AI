"""Numeric position model regression tests for 2–10 handed Texas Hold'em."""
import unittest

from core.table_order import position_labels, position_group, position_tightness


class NumericPositionModelTests(unittest.TestCase):
    def test_positions_by_table_size(self):
        expected = {
            9: ["3", "SB", "BB", "9", "8", "7", "6", "5", "4"],
            8: ["3", "SB", "BB", "8", "7", "6", "5", "4"],
            7: ["3", "SB", "BB", "7", "6", "5", "4"],
            6: ["3", "SB", "BB", "6", "5", "4"],
            5: ["3", "SB", "BB", "5", "4"],
            4: ["3", "SB", "BB", "4"],
            3: ["3", "SB", "BB"],
            2: ["SB", "BB"],
        }
        for n, labels in expected.items():
            with self.subTest(n=n):
                self.assertEqual(position_labels(n), labels)
                self.assertEqual(len(set(labels)), n)

    def test_positions_are_unambiguous(self):
        for n in range(2, 11):
            labels = position_labels(n)
            self.assertTrue(all(label.isdecimal() or label in {"SB", "BB"} for label in labels))
            if n == 2:
                self.assertEqual(labels[0], "SB")
                self.assertEqual(labels[1], "BB")
            else:
                self.assertEqual(labels[0], "3")
                self.assertEqual(labels[1:3], ["SB", "BB"])

    def test_relative_position_groups(self):
        self.assertEqual(position_group("9", 9), "early")
        self.assertEqual(position_group("8", 8), "early")
        self.assertEqual(position_group("6", 6), "early")
        self.assertEqual(position_group("6", 9), "middle")
        self.assertEqual(position_group("3", 3), "late")
        self.assertEqual(position_group("SB", 2), "sb")
        self.assertEqual(position_group("BB", 2), "bb")

    def test_hu_sb_has_button_tightness(self):
        self.assertEqual(position_tightness("SB", 2), 0.0)
        self.assertEqual(position_tightness("SB", 9), 0.5)
        self.assertEqual(position_tightness("BB", 2), 0.7)

    def test_gto_hu_sb_uses_late_range(self):
        from bots.gto_bot import (
            _numeric_range, RANGE_LATE, RANGE_EARLY,
            DEFAULT_HAND_FREQUENCIES, ALL_HAND_CLASSES,
        )
        # Values stay historically identical, but charts are now independent.
        for hand in ALL_HAND_CLASSES:
            self.assertEqual(
                _numeric_range("SB", 2)[hand],
                RANGE_LATE.get(hand, DEFAULT_HAND_FREQUENCIES),
            )
            self.assertEqual(
                _numeric_range("9", 9)[hand],
                RANGE_EARLY.get(hand, DEFAULT_HAND_FREQUENCIES),
            )
        self.assertIsNot(_numeric_range("9", 9), _numeric_range("8", 9))
        self.assertIsNot(_numeric_range("SB", 9), _numeric_range("BB", 9))

    def test_smart_and_hybrid_new_positions(self):
        from bots.poker_mind_bot import SmartBot
        from bots.tournament_hybrid_bot import TournamentHybridBot
        bot = SmartBot()
        self.assertEqual(bot._get_position_tightness("SB", 2), 0.0)
        self.assertEqual(bot._get_position_tightness("9", 9), 1.0)
        self.assertEqual(TournamentHybridBot._positions_for_n(2), ["SB", "BB"])
        self.assertEqual(TournamentHybridBot._classify_position("9", 9), "early")


if __name__ == "__main__":
    unittest.main()
