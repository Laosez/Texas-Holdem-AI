"""Correctness gate for Plan multiway Monte Carlo and direct evaluator."""
import random
import unittest
from collections import Counter
from unittest.mock import patch

import planner_equity as eq
import planner_postflop_ev as post
from core.fast_eval import fast_eval_hand

RANKS = "23456789TJQKA"
SUITS = "cdhs"


class PlanMonteCarloFixTests(unittest.TestCase):
    def test_fast_score_matches_reference_across_random_7_card_hands(self):
        rng = random.Random(716)
        for _ in range(30000):
            physical = rng.sample(range(52), 7)
            converted = [(RANKS[c // 4], SUITS[c % 4]) for c in physical]
            self.assertEqual(
                eq.score_seven_fast(physical),
                fast_eval_hand(converted[:2], converted[2:]),
                physical,
            )

    def test_fast_score_order_matches_original(self):
        rng = random.Random(1234)
        cards = [rng.sample(range(52), 7) for _ in range(20000)]
        original = [eq.score_seven(x) for x in cards]
        fast = [eq.score_seven_fast(x) for x in cards]
        for i in range(0, len(cards) - 1, 2):
            self.assertEqual((original[i] > original[i+1])-(original[i] < original[i+1]),
                             (fast[i] > fast[i+1])-(fast[i] < fast[i+1]))

    def test_fixed_entry_masks_preserve_manual_probabilities(self):
        aces = eq.WeightedRange({"AA": 1.0})
        specs = [{"entry_mode": "manual", "entry_pct": 50.0}] * 2
        predicted, _ = eq.entry_distributions("KK", [aces, aces], specs)
        counts = Counter()
        rng = random.Random(101)
        for _ in range(5000):
            picked, board = post._draw_case("KK", [aces, aces], specs, rng)
            self.assertEqual(len(board), 5)
            all_cards = [c for _, pair, _ in picked for c in pair] + board
            self.assertEqual(len(all_cards), len(set(all_cards)))
            counts[len(picked) - 1] += 1
        for n in range(3):
            self.assertAlmostEqual(counts[n]/5000, predicted[n], delta=0.025)

    def test_variable_equity_preserves_conditional_entry_masks(self):
        aces = eq.WeightedRange({"AA": 1.0})
        specs = [{"entry_mode": "manual", "entry_pct": 50.0}] * 2
        counts = Counter()
        original = eq.sample_compatible_hands

        def observed(active, hero, rng, max_attempts=1000):
            counts[len(active)] += 1
            return original(active, hero, rng, max_attempts=max_attempts)

        with patch.object(eq, "sample_compatible_hands", side_effect=observed):
            value, pot, probabilities = eq.simulate_hand_variable(
                "KK", [aces, aces], specs, trials=1500, seed=123)
        self.assertTrue(0 <= value <= 100)
        self.assertAlmostEqual(sum(probabilities), 1.0)
        # Conditional on >=1 active: 2 opponents = 0.25 / 0.75 = 1/3.
        self.assertAlmostEqual(counts[2]/sum(counts.values()), 1/3, delta=0.04)

    def test_impossible_lineup_fails_explicitly(self):
        aces = eq.WeightedRange({"AA":1.0})
        hero = eq.HAND_COMBOS["AA"][0]
        with self.assertRaisesRegex(ValueError, "несовместимые диапазоны"):
            eq.sample_compatible_hands([aces, aces], hero, random.Random(2), max_attempts=15)

    def test_uncontested_blind_profit_is_position_correct(self):
        for position, expected in (("3",1.5),("SB",1.0),("BB",0.5)):
            with self.subTest(position=position):
                request = {
                    "hand":"AKs","trials":50,"cycles":1,
                    "hero_position":position,"hero_stack_bb":20,
                    "hero_postflop":"gto2",
                    "opponents":[{
                        "profile":"builtin:any_two","position":"4",
                        "scenario":"rfi","players":9,"entry_mode":"never",
                        "entry_pct":0,"postflop":"none"
                    }]
                }
                result = post.calculate(request)
                self.assertEqual(result["ev_bb"]["AKs"], expected)
                self.assertEqual(result["entry_counts_pct"], [100.0, 0.0])


    def test_no_entry_is_not_showdown(self):
        any_two = eq.WeightedRange({h:1.0 for h in eq.planner.HANDS})
        entry = [{"entry_mode":"never","entry_pct":0}]
        result, pot, distribution = eq.simulate_hand_variable(
            "AKs", [any_two], entry, trials=100, seed=2)
        self.assertIsNone(result)
        self.assertIsNone(pot)
        self.assertEqual(distribution,[1.0,0.0])

if __name__ == "__main__":
    unittest.main()
