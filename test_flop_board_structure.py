"""Exact enumeration over 22,100 3-card flops and their board-only structures."""
from collections import Counter
from itertools import combinations
import unittest

from flop_board_structure import BOARD_TYPES, RANK_CONNECTIONS, classify_flop_board


class FlopBoardStructureTests(unittest.TestCase):
    def test_the_six_physically_possible_flop_structures(self):
        examples = [
            ([(14,"s"), (7,"h"), (2,"d")], "distinct_rainbow"),
            ([(14,"s"), (7,"s"), (2,"d")], "distinct_two_tone"),
            ([(14,"s"), (7,"s"), (2,"s")], "distinct_monotone"),
            ([(7,"s"), (7,"h"), (2,"d")], "paired_rainbow"),
            ([(7,"s"), (7,"h"), (2,"s")], "paired_two_tone"),
            ([(7,"s"), (7,"h"), (7,"d")], "trips_rainbow"),
        ]
        self.assertEqual(len(BOARD_TYPES), 6)
        for flop, wanted in examples:
            with self.subTest(flop=flop):
                self.assertEqual(classify_flop_board(flop)["id"], wanted)

    def test_rank_connectivity_including_wheel_ace(self):
        fixtures = [
            ([(2,"s"),(3,"h"),(4,"d")],"three_consecutive"),
            ([(14,"s"),(2,"h"),(3,"d")],"three_consecutive"),
            ([(14,"s"),(13,"h"),(12,"d")],"three_consecutive"),
            ([(2,"s"),(4,"h"),(6,"d")],"three_within_straight_window"),
            ([(2,"s"),(3,"h"),(9,"d")],"two_consecutive"),
            ([(14,"s"),(2,"h"),(9,"d")],"two_consecutive"),
            ([(2,"s"),(4,"h"),(9,"d")],"two_one_gap"),
            ([(14,"s"),(3,"h"),(9,"d")],"two_one_gap"),
            ([(2,"s"),(6,"h"),(10,"d")],"unconnected"),
        ]
        self.assertEqual(len(RANK_CONNECTIONS), 5)
        for flop, wanted in fixtures:
            with self.subTest(flop=flop):
                self.assertEqual(classify_flop_board(flop)["connection"], wanted)

    def test_pairs_high_low_and_impossible_cards(self):
        self.assertEqual(
            classify_flop_board([(14,"s"),(14,"h"),(2,"s")])["pair_position"],
            "high_pair",
        )
        self.assertEqual(
            classify_flop_board([(2,"s"),(2,"h"),(14,"d")])["pair_position"],
            "low_pair",
        )
        for bad in (
            [(7,"s"),(7,"s"),(2,"d")],
            [(7,"s"),(7,"h")],
            [(15,"s"),(7,"h"),(2,"d")],
            [(7,"z"),(7,"h"),(2,"d")],
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    classify_flop_board(bad)

    def test_exhaustively_partition_all_22100_physical_flops(self):
        """C(52,3) physical flops, no double counting or unclassified flop."""
        deck = [(r,s) for r in range(2,15) for s in "shdc"]
        by_type = Counter()
        by_connection = Counter()
        by_pair_position = Counter()
        for cards in combinations(deck,3):
            result = classify_flop_board(cards)
            by_type[result["id"]] += 1
            if result["connection"]:
                by_connection[result["connection"]] += 1
            if result["pair_position"]:
                by_pair_position[result["pair_position"]] += 1
        self.assertEqual(sum(by_type.values()), 22100)
        self.assertEqual(by_type, {
            "distinct_rainbow": 6864,
            "distinct_two_tone": 10296,
            "distinct_monotone": 1144,
            "paired_rainbow": 1872,
            "paired_two_tone": 1872,
            "trips_rainbow": 52,
        })
        # Among C(13,3)=286 distinct-rank patterns: 12/52/76/75/71;
        # each can be realized with 4^3=64 suit patterns.
        self.assertEqual(by_connection, {
            "three_consecutive": 12*64,
            "three_within_straight_window": 52*64,
            "two_consecutive": 76*64,
            "two_one_gap": 75*64,
            "unconnected": 71*64,
        })
        self.assertEqual(by_pair_position, {
            "high_pair": 1872,
            "low_pair": 1872,
        })


if __name__ == "__main__":
    unittest.main()
