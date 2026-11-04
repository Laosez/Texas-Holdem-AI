"""GTO 5.3 weighted rank routes: independent exact Any Two controls."""
import random
import unittest
from itertools import combinations

from bots import create_bot
from bots.hand_seniority_51 import hero_seniority, hero_seniority_52
from bots.hand_seniority_53 import hero_seniority_53
from core.engine import eval_hand

RANKS = "23456789TJQKA"
SUITS = "shdc"
DECK = [(r, s) for r in RANKS for s in SUITS]


def cards(tokens):
    return [tuple(t) for t in tokens.split()]


def exact_within_category(hero, board):
    known = set(hero + board)
    hero_score = eval_hand(hero, board)
    category = min(8, hero_score >> 24)
    wins = ties = n = 0
    unknown = [c for c in DECK if c not in known]
    for opp in combinations(unknown, 2):
        score = eval_hand(list(opp), board)
        if min(8, score >> 24) != category:
            continue
        n += 1
        wins += score < hero_score
        ties += score == hero_score
    return (wins + .5 * ties) / n if n else .5, n


class GTO53WeightedSeniorityTests(unittest.TestCase):
    def test_registered_isolated_model(self):
        model = create_bot("gto_postflop_53_5")
        self.assertEqual(model.actor_kind, "gto53")
        self.assertEqual(model.seniority_version, 53)
        self.assertEqual(model.profile, "gto_postflop_53_5")
        self.assertTrue(model.rank_aware)
        self.assertEqual(model.round_step, 0)
        self.assertEqual(model._new_reference().__class__.__name__, "JointRangeGTO41Bot")
        mirror = create_bot("gto_postflop_53_5")
        mirror.shadow_reference_kind = "gto53"
        self.assertEqual(mirror._new_reference().actor_kind, "gto53")

    def test_gto51_and_gto52_stay_unchanged(self):
        h, b = cards("5s 9d"), cards("Ad Jd Tc 6c 7c")
        old, _ = hero_seniority(h, b)
        new_52, _ = hero_seniority_52(h, b)
        self.assertAlmostEqual(new_52, old * old)
        self.assertNotAlmostEqual(hero_seniority_53(h, b)[0], old)

    def test_frozen_52_audit_representatives(self):
        # Control sample: (board, hero, conditional Any Two count, exact r %).
        cases = (
            ("9s Jd 2d", "5h 8c", 649, 26.58),    # high card
            ("Ks Qc 5d", "7c 7s", 397, 34.89),   # PP on P0
            ("6s Ts Kh 6d Qs", "7h 9d",  # P1 pair: count verified by oracle below
             None, 29.71),
            ("9s 8c 8s", "5c 5s", None, 29.81),   # two pair P1
            ("4c 5s 7s 4d 5d", "7d 6d", None, 87.30),  # two pair P2
            ("9d 3h 9s", "9h 2d", None, 3.49),  # trips P1
            ("2s 3d 9h 2h", "3s 3h", None, 72.73),  # FH P1
            ("2s 8s 7s", "5s Ts", 28, 21.43),  # flush F3
            ("4c 2c Ac Td 3c", "Ah 7c", 280, 13.21), # flush F4
            ("3h Ah 8h 2h 6c", "5d 4d", 4, 50.0), # straight F4
            ("4h 3d As 5c 2d", "9h Qc", 990, 41.41), # shared straight
            ("7c Qd 8s Jd 7s", "9h Th", 9, 50.0), # straight P1
        )
        for board, hero, expected_n, expected_percent in cases:
            with self.subTest(board=board, hero=hero):
                h, b = cards(hero), cards(board)
                weighted, rule = hero_seniority_53(h, b)
                exact, n = exact_within_category(h, b)
                self.assertAlmostEqual(weighted, exact, places=10)
                self.assertEqual(rule["route_weight"], n)
                self.assertLessEqual(rule["rank_pairs"], 91)
                if expected_n is not None:
                    self.assertEqual(n, expected_n)
                self.assertAlmostEqual(weighted * 100, expected_percent, delta=.006)

    def test_independent_any_two_random_flop_turn_river(self):
        rng = random.Random(20261104)
        for board_size in (3, 4, 5):
            for sample in range(12):
                known = rng.sample(DECK, board_size + 2)
                board, hero = known[:board_size], known[board_size:]
                with self.subTest(street=board_size, sample=sample):
                    exact, count = exact_within_category(hero, board)
                    result, rule = hero_seniority_53(hero, board)
                    self.assertAlmostEqual(result, exact, places=10)
                    self.assertEqual(rule["route_weight"], count)
                    self.assertLessEqual(rule["rank_pairs"], 91)


if __name__ == "__main__":
    unittest.main()
