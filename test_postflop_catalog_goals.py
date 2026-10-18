"""Choose exactly what HERO seeks by river and what villain hit on flop."""
from math import comb
import unittest
from postflop_catalog_metrics import (
    HERO_GOALS, VILLAIN_GOALS, RANGE_KEYS,
    _villain_goal_flags, calculate_goal_metrics, calculate_example_metrics
)


class SelectedFlopGoalTests(unittest.TestCase):
    def test_ak_on_752_hit_either_a_or_k_is_exact_six_outs(self):
        # Hero A♠ K♥, flop 7♦ 5♣ 2♠: 6 unseen matching ranks.
        result=calculate_goal_metrics("14s-13h","7d-5c-2s")
        goals=result["hero_goals"]
        expected=1-comb(41,2)/comb(47,2)
        exact_one=1-comb(44,2)/comb(47,2)
        self.assertEqual(result["runouts"],1081)
        self.assertAlmostEqual(goals["new_pair_either"],expected)
        self.assertAlmostEqual(goals["new_pair_high"],exact_one)
        self.assertAlmostEqual(goals["new_pair_low"],exact_one)
        self.assertAlmostEqual(goals["top_pair_plus"],expected)
        # Pair+ includes shared pair on runout (77,55,22) even without A/K.
        self.assertGreater(goals["pair_plus"],goals["top_pair_plus"])
        self.assertEqual(goals["straight_plus"],0)
        self.assertEqual(goals["flush_plus"],0)
        self.assertEqual(goals["full_house_plus"],0)

    def test_selection_is_not_same_as_improvement(self):
        hero="9s-8s";flop="9d-7s-6s"
        result=calculate_goal_metrics(hero,flop)
        base=calculate_example_metrics(hero,flop)
        self.assertAlmostEqual(result["hero_goals"]["improve_category"],base["hero_improve"])
        self.assertNotEqual(result["hero_goals"]["new_pair_either"],
                            result["hero_goals"]["improve_category"])
        self.assertEqual(set(result["hero_goals"]),set(HERO_GOALS))
        self.assertEqual(set(result["villain_goals"]),set(VILLAIN_GOALS))
        for goal,by_range in result["villain_goals"].items():
            self.assertEqual(set(by_range),set(RANGE_KEYS))
            self.assertTrue(all(value is None or 0<=value<=1
                                for value in by_range.values()))

    def test_villain_contact_definitions_and_complement(self):
        for hand,board in [
            (((14,"s"),(13,"h")),((7,"s"),(5,"h"),(2,"d"))),
            (((7,"h"),(13,"h")),((7,"s"),(5,"h"),(2,"d"))),
            (((14,"s"),(14,"h")),((7,"s"),(5,"h"),(2,"d"))),
            (((9,"s"),(8,"s")),((7,"s"),(6,"h"),(2,"d"))),
            (((6,"s"),(4,"s")),((7,"s"),(5,"s"),(2,"d"))),
            (((14,"c"),(13,"c")),((7,"h"),(7,"s"),(2,"d"))),
        ]:
            with self.subTest(hand=hand,board=board):
                flags=_villain_goal_flags(hand,board)
                self.assertEqual(set(flags),set(VILLAIN_GOALS))
                self.assertEqual(flags["no_contact"],not flags["pair_or_draw"])
                self.assertGreaterEqual(int(flags["any_draw"]),int(flags["flush_draw"]))
                self.assertGreaterEqual(int(flags["any_draw"]),int(flags["straight_draw"]))
                self.assertGreaterEqual(int(flags["pair_or_draw"]),int(flags["private_pair"]))
                self.assertGreaterEqual(int(flags["private_pair"]),int(flags["top_pair_overpair"]))
                self.assertGreaterEqual(int(flags["two_pair_plus"]),int(flags["trips_plus"]))

        shared_trips=_villain_goal_flags(
            ((14,"c"),(13,"c")),((7,"s"),(7,"h"),(7,"d"))
        )
        self.assertFalse(shared_trips["trips_plus"])
        self.assertTrue(shared_trips["no_contact"])

    def test_full_per_position_probability_partition(self):
        result=calculate_goal_metrics("14s-13h","7d-5c-2s")
        base=calculate_example_metrics("14s-13h","7d-5c-2s")
        for pos in RANGE_KEYS:
            pair_or_draw=result["villain_goals"]["pair_or_draw"][pos]
            self.assertAlmostEqual(pair_or_draw+result["villain_goals"]["no_contact"][pos],1)
            self.assertAlmostEqual(pair_or_draw,base["opponent_contact"][pos])

    def test_different_objectives_on_monotone_board_and_made_hands(self):
        full=calculate_goal_metrics("9s-8s","7s-6s-5s")
        self.assertEqual(full["hero_goals"]["improve_category"],0)
        self.assertEqual(full["hero_goals"]["flush_plus"],1)
        self.assertEqual(full["hero_goals"]["straight_plus"],1)
        self.assertGreater(full["hero_goals"]["new_pair_either"],0)


if __name__ == "__main__":
    unittest.main()
