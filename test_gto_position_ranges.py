"""GTO position chart extraction: value-equivalence and isolation regression."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bots.gto_bot import (
    ALL_HAND_CLASSES,
    DEFAULT_HAND_FREQUENCIES,
    GTOBot,
    POSITION_RANGES,
    _legacy_range_for_position,
    _numeric_range,
)
from core.table_order import position_labels


class GTOPositionRangeTests(unittest.TestCase):
    def test_complete_169_chart_per_position_and_table_size(self):
        self.assertEqual(len(ALL_HAND_CLASSES), 169)
        self.assertEqual(len(set(ALL_HAND_CLASSES)), 169)
        self.assertEqual(set(POSITION_RANGES), set(range(2, 11)))
        self.assertEqual(sum(len(seats) for seats in POSITION_RANGES.values()), 54)
        for n in range(2, 11):
            self.assertEqual(set(POSITION_RANGES[n]), set(position_labels(n)))
            for pos in position_labels(n):
                with self.subTest(n=n, pos=pos):
                    chart = _numeric_range(pos, n)
                    self.assertEqual(set(chart), set(ALL_HAND_CLASSES))
                    for triple in chart.values():
                        self.assertEqual(len(triple), 3)
                        self.assertAlmostEqual(sum(triple), 1.0, places=9)

    def test_seeding_preserves_every_original_group_frequency(self):
        for n in range(2, 11):
            for pos in position_labels(n):
                legacy = _legacy_range_for_position(pos, n)
                result = _numeric_range(pos, n)
                for hand in ALL_HAND_CLASSES:
                    with self.subTest(n=n, pos=pos, hand=hand):
                        self.assertEqual(
                            result[hand],
                            legacy.get(hand, DEFAULT_HAND_FREQUENCIES),
                        )

    def test_position_charts_do_not_alias_each_other(self):
        positions = [
            chart
            for seats in POSITION_RANGES.values()
            for chart in seats.values()
        ]
        self.assertEqual(len(set(map(id, positions))), len(positions))
        self.assertIsNot(_numeric_range("9", 9), _numeric_range("8", 9))
        self.assertIsNot(_numeric_range("SB", 9), _numeric_range("BB", 9))
        self.assertIsNot(_numeric_range("6", 6), _numeric_range("6", 9))
        self.assertIsNot(_numeric_range("SB", 2), _numeric_range("SB", 9))

    def test_customization_is_local_to_a_single_bot_and_position(self):
        original = _numeric_range("9", 9)["AKs"]
        changed = GTOBot()
        baseline = GTOBot()
        changed.set_hand_frequencies(9, "9", "AKs", (1.0, 0.0, 0.0))
        self.assertEqual(_numeric_range("9", 9)["AKs"], original)
        self.assertEqual(baseline.position_ranges[9]["9"]["AKs"], original)
        self.assertEqual(changed.position_ranges[9]["8"]["AKs"], original)
        self.assertEqual(changed.position_ranges[8]["8"]["AKs"], original)
        self.assertEqual(changed.position_ranges[9]["9"]["AKs"], (1.0, 0.0, 0.0))

    def test_hu_sb_and_bb_are_editable_independently(self):
        bot = GTOBot()
        before_bb = bot.position_ranges[2]["BB"]["AKs"]
        before_sb_9 = bot.position_ranges[9]["SB"]["AKs"]
        bot.set_hand_frequencies(2, "SB", "AKs", (1.0, 0.0, 0.0))
        self.assertEqual(bot.position_ranges[2]["BB"]["AKs"], before_bb)
        self.assertEqual(bot.position_ranges[9]["SB"]["AKs"], before_sb_9)

    def test_runtime_uses_instance_specific_position_chart(self):
        original = GTOBot()
        changed = GTOBot()
        changed.set_hand_frequencies(9, "9", "AKs", (1.0, 0.0, 0.0))
        state = SimpleNamespace(stacks={f"P{i}": 500 for i in range(9)})
        hole = [("A", "s"), ("K", "s")]
        legal = [
            {"type": "check"},
            {"type": "raise", "min": 2, "max": 80},
        ]
        with patch("bots.gto_bot.random.random", return_value=0.5):
            old_action = original._preflop(hole, "9", 30, 0, legal, state)
            new_action = changed._preflop(hole, "9", 30, 0, legal, state)
        self.assertEqual(old_action.type, "raise")
        self.assertEqual(new_action.type, "check")

    def test_reject_invalid_frequencies_and_labels(self):
        bot = GTOBot()
        for triple in (
            (0.5, 0.5),
            (0.3, 0.4, 0.4),
            (-0.1, 0.5, 0.6),
            (float("nan"), 0.5, 0.5),
            (float("inf"), 0.0, 0.0),
        ):
            with self.subTest(triple=triple):
                with self.assertRaises(ValueError):
                    bot.set_hand_frequencies(9, "9", "AKs", triple)
        with self.assertRaises(ValueError):
            bot.set_hand_frequencies(9, "9", "ZZ", (0.0, 0.0, 1.0))
        with self.assertRaises(ValueError):
            bot.set_hand_frequencies(9, "10", "AKs", (0.0, 0.0, 1.0))
        with self.assertRaises(ValueError):
            _numeric_range("BB", 1)


if __name__ == "__main__":
    unittest.main()
