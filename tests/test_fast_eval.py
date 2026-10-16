"""Score compatibility of fast evaluator against the legacy engine.

python -m unittest discover -s tests -p 'test_fast_eval.py'
"""
import random
import unittest

from core.engine import _FULL_DECK, eval_hand
from core.fast_eval import fast_eval_hand


class FastEvaluatorParity(unittest.TestCase):
    def assert_cards_equal(self, cards):
        hole, board = cards[:2], cards[2:]
        self.assertEqual(eval_hand(hole, board), fast_eval_hand(hole, board),
                         msg=str(cards))

    def test_randomized_five_six_seven_cards(self):
        # Three independent board sizes, deterministic random seed.
        rng = random.Random(20261016)
        for size in (5, 6, 7):
            for _ in range(30000):
                self.assert_cards_equal(rng.sample(_FULL_DECK, size))

    def test_named_edge_cases(self):
        # 7-card edge cases: wheel, wheel straight flush, three pairs,
        # two trips for full house, three of a kind with strong kickers,
        # flush with 6/7 suited, board-only straight flush, quads.
        cases = [
            "As 2d 3h 4c 5s 9h Kd",
            "As 2s 3s 4s 5s Kh Qd",
            "As Ad Ks Kd Qs Qd 2h",
            "As Ad Ah Ks Kd Kh 2c",
            "As Ad Ah Ks Qd Jc 2h",
            "As Ks Qs Js 9s 4s 3s",
            "As Ks Qs Js Ts 4d 3c",
            "As Ad Ah Ac Ks Kh Kd",
            "2s 2d 3s 3h 4s 4c 5d",
            "As Ks Qs Js 9s Ts 8s",
            "Ac Kd Qs Jh Tc 4d 3s",
        ]
        for encoded in cases:
            with self.subTest(cards=encoded):
                cards = [(x[0], x[1]) for x in encoded.split()]
                self.assert_cards_equal(cards)

    def test_preflop_heuristic_parity(self):
        for cards in ("As Ad", "As Kd", "2c 7s"):
            hole = [(x[0], x[1]) for x in cards.split()]
            self.assertEqual(eval_hand(hole, []), fast_eval_hand(hole, []))


if __name__ == "__main__":
    unittest.main()
