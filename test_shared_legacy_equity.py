"""Ensure one shared legacy equity evaluator produces identical bot outputs.

A separate reference loop is intentionally kept in tests only: it fixes the
old sampling order and historical half-credit tie handling against refactors.
"""
import random
import unittest

from bots.gto_bot import GTOBot
from bots.poker_mind_bot import SmartBot
from bots.monte_carlo_bot import MonteCarloBot
from core.engine import _FULL_DECK, eval_hand
from core.equity_legacy import estimate_equity_legacy


def reference_legacy_equity(hole, board, num_opponents, sims, rng):
    """Pre-refactor Monte Carlo loop using independent reference code."""
    if not hole or len(hole) < 2:
        return 0.0
    num_opponents = max(1, num_opponents)
    wins, ties = 0, 0
    base_used = set(tuple(c) for c in hole) | set(tuple(c) for c in board)
    base_remaining = [card for card in _FULL_DECK if card not in base_used]
    need_board = 5 - len(board)
    for _ in range(sims):
        sim_used = base_used.copy()
        opp_hands = []
        valid = True
        for _ in range(num_opponents):
            avail = [c for c in base_remaining if c not in sim_used]
            if len(avail) < 2:
                valid = False
                break
            opp = rng.sample(avail, 2)
            opp_hands.append(opp)
            sim_used |= {tuple(c) for c in opp}
        if not valid:
            continue
        if need_board > 0:
            avail_board = [c for c in base_remaining if c not in sim_used]
            if len(avail_board) < need_board:
                continue
            full_board = list(board) + rng.sample(avail_board, need_board)
        else:
            full_board = list(board)
        score = eval_hand(hole, full_board)
        best_opponent = max(eval_hand(opp, full_board) for opp in opp_hands)
        wins += score > best_opponent
        ties += score == best_opponent
    return (wins + 0.5 * ties) / sims


class SharedLegacyEquityTests(unittest.TestCase):
    def test_reference_parity_and_rng_consumption(self):
        situations = [
            ([("A", "s"), ("K", "s")], [], 1, 40),
            ([("A", "s"), ("K", "s")], [("Q", "h"), ("J", "h"), ("2", "c")], 3, 40),
            ([("7", "c"), ("7", "d")], [("A", "h"), ("K", "d"), ("2", "s"), ("7", "h")], 2, 30),
            ([("A", "s"), ("K", "d")], [("T", "c"), ("J", "c"), ("Q", "c"), ("K", "c"), ("A", "c")], 3, 10),
        ]
        for seed in (0, 7, 42):
            for hole, board, opponents, sims in situations:
                with self.subTest(seed=seed, street=len(board), opponents=opponents):
                    old_rng = random.Random(seed)
                    new_rng = random.Random(seed)
                    expected = reference_legacy_equity(
                        hole, board, opponents, sims, old_rng
                    )
                    actual = estimate_equity_legacy(
                        hole, board, opponents, sims, rng=new_rng
                    )
                    self.assertEqual(actual, expected)
                    self.assertEqual(new_rng.getstate(), old_rng.getstate())

    def test_all_three_bots_use_same_equity_for_same_seed(self):
        hole = [("K", "h"), ("Q", "h")]
        board = [("9", "s"), ("T", "h"), ("2", "c")]
        sims = 24
        expected = estimate_equity_legacy(
            hole, board, 2, sims, rng=random.Random(31415)
        )
        bots = (
            GTOBot(),
            SmartBot(),
            MonteCarloBot(simulations=sims),
        )
        for bot in bots:
            random.seed(31415)
            if isinstance(bot, GTOBot):
                value = bot._hand_strength(hole, board, num_opponents=2, sims=sims)
            else:
                value = bot._estimate_equity(hole, board, num_opponents=2, sims=sims)
            with self.subTest(bot=type(bot).__name__):
                self.assertEqual(value, expected)
                # A seeded private RNG and the module-global one consume
                # equivalent samples when initialized to the same state.
                self.assertEqual(random.getstate(), random.Random(31415).getstate()
                                 if sims == 0 else self._reference_state(
                                     hole, board, 2, sims, 31415))

    @staticmethod
    def _reference_state(hole, board, opponents, sims, seed):
        rng = random.Random(seed)
        reference_legacy_equity(hole, board, opponents, sims, rng)
        return rng.getstate()

    def test_legacy_multiway_tie_scoring_is_intentionally_half(self):
        hole = [("A", "s"), ("K", "d")]
        royal_flush_on_board = [
            ("T", "c"), ("J", "c"), ("Q", "c"), ("K", "c"), ("A", "c")
        ]
        self.assertEqual(
            estimate_equity_legacy(hole, royal_flush_on_board, 3, 12,
                                   rng=random.Random(1)),
            0.5,
        )

    def test_missing_hole_and_zero_opponents(self):
        self.assertEqual(estimate_equity_legacy([], [], 1), 0.0)
        hole = [("Q", "s"), ("Q", "h")]
        board = [("J", "s"), ("8", "s"), ("3", "d")]
        self.assertEqual(
            estimate_equity_legacy(hole, board, 0, 20, rng=random.Random(88)),
            estimate_equity_legacy(hole, board, 1, 20, rng=random.Random(88)),
        )

    def test_seed_does_not_touch_global_rng_when_injected(self):
        random.seed(123)
        before = random.getstate()
        estimate_equity_legacy(
            [("A", "s"), ("K", "d")],
            [("Q", "s"), ("T", "h"), ("3", "c")],
            2, 12, rng=random.Random(44),
        )
        self.assertEqual(random.getstate(), before)

    def test_original_default_simulations_are_preserved(self):
        self.assertEqual(GTOBot._hand_strength.__defaults__, (1, 100))
        self.assertEqual(SmartBot._estimate_equity.__defaults__, (1, 100))
        self.assertEqual(MonteCarloBot._estimate_equity.__defaults__, (1, 500))
        self.assertEqual(MonteCarloBot().simulations, 500)


if __name__ == "__main__":
    unittest.main()
