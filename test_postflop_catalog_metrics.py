"""Exact mathematical meaning of sheet-03 probability columns."""
import unittest
from postflop_catalog_metrics import (
    POSITIONS, made_category, hand_class, opponent_connected,
    calculate_example_metrics
)


class PostflopCatalogMetricsTests(unittest.TestCase):
    def test_hand_class_169_notation(self):
        self.assertEqual(hand_class(((14,"s"),(13,"s"))),"AKs")
        self.assertEqual(hand_class(((14,"s"),(13,"h"))),"AKo")
        self.assertEqual(hand_class(((10,"h"),(10,"d"))),"TT")
        self.assertEqual(hand_class(((2,"d"),(14,"s"))),"A2o")

    def test_exact_made_hand_categories_and_wheel(self):
        hands={
            0:[(14,"s"),(13,"h"),(9,"d"),(7,"c"),(2,"s")],
            1:[(14,"s"),(14,"h"),(9,"d"),(7,"c"),(2,"s")],
            2:[(14,"s"),(14,"h"),(9,"d"),(9,"c"),(2,"s")],
            3:[(14,"s"),(14,"h"),(14,"d"),(7,"c"),(2,"s")],
            4:[(14,"s"),(2,"h"),(3,"d"),(4,"c"),(5,"s")],
            5:[(14,"s"),(13,"s"),(9,"s"),(7,"s"),(2,"s")],
            6:[(14,"s"),(14,"h"),(14,"d"),(7,"c"),(7,"s")],
            7:[(14,"s"),(14,"h"),(14,"d"),(14,"c"),(2,"s")],
            8:[(9,"s"),(8,"s"),(7,"s"),(6,"s"),(5,"s")],
        }
        for cat,cards in hands.items():
            with self.subTest(cat=cat):
                self.assertEqual(made_category(cards),cat)
                self.assertEqual(made_category(cards+[(3,"h"),(10,"c")]),cat)

    def test_board_only_pair_not_automatically_a_hit_for_villain(self):
        board=((7,"s"),(7,"h"),(2,"d"))
        self.assertFalse(opponent_connected(((14,"d"),(13,"h")),board))
        self.assertTrue(opponent_connected(((4,"c"),(4,"d")),board))
        self.assertTrue(opponent_connected(((7,"d"),(14,"h")),board))
        # Straight/flush draws count, backdoor alone does not.
        self.assertTrue(opponent_connected(((3,"s"),(4,"s")),((14,"s"),(13,"s"),(2,"d"))))
        self.assertFalse(opponent_connected(((6,"d"),(8,"c")),((14,"h"),(13,"s"),(2,"d"))))

    def test_representative_probabilities_and_range_blockers(self):
        baseline=calculate_example_metrics("9s-8s","9d-7s-6s")
        self.assertEqual(baseline["turn_river_combinations"],1081)
        self.assertEqual(baseline["flop_category"],1)
        self.assertAlmostEqual(baseline["hero_improve"],892/1081)
        for key in ("any",)+POSITIONS:
            self.assertIsNotNone(baseline["opponent_contact"][key])
            self.assertTrue(0<=baseline["opponent_contact"][key]<=1)
        another=calculate_example_metrics("14s-13s","12s-11s-2d")
        self.assertEqual(another["flop_category"],0)
        already=calculate_example_metrics("9s-8s","7s-6s-5s")
        self.assertEqual(already["flop_category"],8)
        self.assertEqual(already["hero_improve"],0)

    def test_impossible_physical_cards(self):
        for hero,board in (("9s-8s","9s-7s-6d"),
                           ("9-8","9d-7s-6s"),
                           ("9s-8s","7s-7s-6s")):
            with self.subTest(hero=hero,board=board):
                with self.assertRaises(ValueError):
                    calculate_example_metrics(hero,board)


if __name__=="__main__":
    unittest.main()
