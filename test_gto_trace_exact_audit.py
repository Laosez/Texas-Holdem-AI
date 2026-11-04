"""Structured trace audit: exact Any Two current made-hand rank and logging."""
import unittest
from collections import deque
from math import comb

from gto_trace_exact_audit import exact_current_hand_audit
from bots.gto_postflop_50 import RankAwareGTO51Bot, RoundedRankAwareGTO515Bot
from test_gto_postflop_50 import view


def cards(text):
    return [tuple(t) for t in text.split()]


class ExactTraceAuditTests(unittest.TestCase):
    def _step(self, street, board, hole):
        bot = RankAwareGTO51Bot(shadow_percent=0)
        state = view(street, cards(board), opponents=("P2",))
        state.hole_cards = cards(hole)
        bot.act(state)
        step = bot.trace_snapshot()[0]["steps"][0]
        self.assertEqual(len(step["opponent_models"]), 1)
        opp = step["opponent_models"][0]
        self.assertIn("equity_proxy", opp)
        self.assertEqual(set(opp["vs_bet"]), {"fold", "call", "raise"})
        return step

    def test_exact_enumeration_totals_and_category_rank(self):
        for street, board, hole, count in [
            ("flop", "Qh 8s 3d", "As Qs", 1081),
            ("turn", "Qh 8s 3d 2c", "As Qs", 1035),
            ("river", "Qh 8s 3d 2c 7h", "As Qs", 990),
        ]:
            with self.subTest(street=street):
                result = exact_current_hand_audit(self._step(street, board, hole))
                self.assertEqual(result["opponent_hands_examined"], count)
                self.assertEqual(result["same_category_count"],
                    result["same_category_weaker"]+
                    result["same_category_tied"]+
                    result["same_category_stronger"])
                self.assertEqual(result["overall_weaker"]+
                    result["overall_tied"]+
                    result["overall_stronger"], count)
                self.assertGreaterEqual(result["exact_win_fraction"], 0)
                self.assertLessEqual(result["exact_win_fraction"], 1)
                self.assertEqual(result["current_only"], street != "river")

    def test_board_quads_same_hand_tie_and_kicker(self):
        result = exact_current_hand_audit(self._step(
            "river", "7c 7d 7h 7s Kc", "Qh 2d"))
        self.assertEqual(result["opponent_hands_examined"], 990)
        self.assertEqual(result["hero_category"], "quads")
        self.assertEqual(result["same_category_count"], 990)
        self.assertGreater(result["overall_tied"], 0)
        self.assertGreater(result["overall_stronger"], 0)

    def test_known_flush_example_has_four_unsafe_spades(self):
        result = exact_current_hand_audit(self._step(
            "river", "9s 8s 3s 2s 5d", "Ts 4c"))
        self.assertEqual(result["hero_category"], "flush")
        self.assertEqual(result["opponent_hands_examined"], 990)
        self.assertGreater(result["same_category_stronger"], 0)
        self.assertGreater(result["same_category_weaker"], 0)
        self.assertGreater(result["same_category_count"], 0)

    def test_reject_duplicate_cards(self):
        self.assertRaises(ValueError, exact_current_hand_audit, {
            "street": "flop", "board": ["As", "As", "2c"],
            "hero_hole": ["Kd", "Qd"],
        })

    def test_trace_keeps_one_hundred_not_five(self):
        bot = RankAwareGTO51Bot(shadow_percent=0)
        self.assertEqual(bot._trace.maxlen, 100)
        for i in range(104):
            state = view("flop", cards("Qh 8s 3d"), opponents=("P2",))
            state.hand_id = i
            bot.act(state)
        self.assertEqual(len(bot.trace_snapshot()), 100)
        self.assertIsInstance(RoundedRankAwareGTO515Bot(shadow_percent=0)._trace, deque)

    def test_audit_does_not_call_bot_or_mutate_trace(self):
        step = self._step("river", "Qh 8s 3d 2c 7h", "As Qs")
        before = repr(step)
        exact_current_hand_audit(step)
        self.assertEqual(repr(step), before)


if __name__ == "__main__":
    unittest.main()
