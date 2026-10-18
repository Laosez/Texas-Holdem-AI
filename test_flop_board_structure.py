"""Exhaustive 46-group taxonomy: every one of the 22,100 physical flops."""
from collections import Counter
from itertools import combinations
import unittest

from flop_board_structure import (
    BOARD_TYPES, CONNECTION_CODE, RANK_CONNECTIONS,
    classify_flop_board, classify_flop_request, parse_physical_flop,
)


class FlopBoardStructureTests(unittest.TestCase):
    def test_six_physical_suit_and_rank_shapes(self):
        cases = [
            ("14s-7h-2d", "distinct_rainbow"),
            ("14s-7s-2d", "distinct_two_tone"),
            ("14s-7s-2s", "distinct_monotone"),
            ("7s-7h-2d", "paired_rainbow"),
            ("7s-7h-2s", "paired_two_tone"),
            ("7s-7h-7d", "trips_rainbow"),
        ]
        self.assertEqual(len(BOARD_TYPES), 6)
        for physical, wanted in cases:
            with self.subTest(physical=physical):
                self.assertEqual(
                    classify_flop_board(parse_physical_flop(physical))["id"],
                    wanted,
                )

    def test_all_six_connection_classes_with_high_and_wheel_ace(self):
        fixtures = [
            ("2s-3h-4d", "C3", "three_consecutive"),
            ("14s-2h-3d", "C3", "three_consecutive"),
            ("14s-13h-12d", "C3", "three_consecutive"),
            ("9s-8h-6d", "C4", "three_with_one_gap"),
            ("9s-7h-6d", "C4", "three_with_one_gap"),
            ("14s-13h-11d", "C4", "three_with_one_gap"),
            ("14s-2h-4d", "C4", "three_with_one_gap"),
            ("9s-7h-5d", "C5", "three_with_two_gaps"),
            ("2s-4h-6d", "C5", "three_with_two_gaps"),
            ("14s-12h-10d", "C5", "three_with_two_gaps"),
            ("14s-3h-5d", "C5", "three_with_two_gaps"),
            ("2s-3h-9d", "C2", "two_consecutive"),
            ("14s-2h-9d", "C2", "two_consecutive"),
            ("2s-4h-9d", "G2", "two_one_gap"),
            ("14s-3h-9d", "G2", "two_one_gap"),
            ("2s-6h-10d", "D", "unconnected"),
        ]
        self.assertEqual(set(CONNECTION_CODE.values()), {"C3","C4","C5","C2","G2","D"})
        self.assertEqual(len(RANK_CONNECTIONS), 6)
        for physical, code, kind in fixtures:
            with self.subTest(physical=physical):
                actual = classify_flop_request({"board": physical})
                self.assertEqual(actual["connection"], kind)
                self.assertEqual(actual["group_id"].split("-")[1], code)

    def test_ace_pairstyles_and_no_hm_hl_ml_split(self):
        labels = {
            "14s-7h-2d": "A-D-R",
            "13s-7h-2d": "N-D-R",
            "14s-14h-2d": "P-AA-R",
            "2s-2h-14d": "P-AX-R",
            "13s-13h-2d": "P-H-R",
            "2s-2h-13d": "P-L-R",
            "14s-14h-14d": "T-A",
            "7s-7h-7d": "T-X",
        }
        for physical, wanted in labels.items():
            with self.subTest(physical=physical):
                self.assertEqual(classify_flop_request({"board": physical})["group_id"], wanted)
        for physical in ("14s-13s-2d", "14s-13d-2s", "14d-13s-2s"):
            self.assertEqual(
                classify_flop_request({"board": physical})["group_id"], "A-C2-2S"
            )
        self.assertTrue(classify_flop_request({"board":"14s-2h-3d"})["wheel_ace"])
        self.assertFalse(classify_flop_request({"board":"14s-9h-2d"})["wheel_ace"])
        self.assertEqual(classify_flop_request({"board":"14s-13h-12d"})["broadway_count"],3)

    def test_physical_input_validation(self):
        invalid = (
            "", "14-7-2", "14s-7z-2y", "14s-7s", "14s-7h-2d-9c",
            "14s-14s-2d", "15s-7h-2d", "As-7h-2d", "14x-7h-2d",
        )
        for text in invalid:
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    classify_flop_request({"board":text})
        for payload in (None,[],{},{"board":7}):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    classify_flop_request(payload)

    def test_partition_all_22100_physical_flops_into_exactly_46_groups(self):
        deck = [(r,s) for r in range(2,15) for s in "shdc"]
        by_shape, by_conn, by_group, family = (Counter() for _ in range(4))
        for cards in combinations(deck,3):
            result = classify_flop_board(cards)
            by_shape[result["id"]] += 1
            by_group[result["group_id"]] += 1
            family[result["rank_shape"]] += 1
            if result["connection"]:
                by_conn[result["connection"]] += 1
        self.assertEqual(sum(by_shape.values()), 22100)
        self.assertEqual(by_shape, {
            "distinct_rainbow": 6864,
            "distinct_two_tone": 10296,
            "distinct_monotone": 1144,
            "paired_rainbow": 1872,
            "paired_two_tone": 1872,
            "trips_rainbow": 52,
        })
        self.assertEqual(by_conn, {
            "three_consecutive": 12*64,
            "three_with_one_gap": 22*64,
            "three_with_two_gaps": 30*64,
            "two_consecutive": 76*64,
            "two_one_gap": 75*64,
            "unconnected": 71*64,
        })
        self.assertEqual(family, {"distinct":18304, "paired":3744, "trips":52})
        self.assertEqual(len(by_group), 46)
        self.assertEqual(len([k for k in by_group if k.startswith(("A-","N-"))]),36)
        self.assertEqual(len([k for k in by_group if k.startswith("P-")]),8)
        self.assertEqual(len([k for k in by_group if k.startswith("T-")]),2)
        self.assertTrue(all(v>0 for v in by_group.values()))


if __name__ == "__main__":
    unittest.main()
