"""Regression tests for the user-defined A17 response to a 3-bet."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bots import create_bot
from bots.a17_preflop_bot import A17PreflopBot
from bots.a17_ranges import (
    A17_HAND_TO_BOX,
    A17_VS_3BET_CONTINUE_BOXES,
    A17_VS_3BET_FOURBET_FREQ,
)


def view(hand, *, position="9", n=9, raises=2, to_call=10, legal=None):
    if legal is None:
        legal = [
            {"type": "fold"},
            {"type": "call"},
            {"type": "raise", "min": 16, "max": 300},
        ]
    if len(hand) == 2:
        hole = ((hand[0], "s"), (hand[1], "h"))
    elif hand.endswith("s"):
        hole = ((hand[0], "s"), (hand[1], "s"))
    else:
        hole = ((hand[0], "s"), (hand[1], "h"))
    # Hero opened, a different player 3-bet. Use 'P1' for an
    # opponent in heads-up (hero is P2).
    history = []
    for i in range(raises):
        history.append({
            "street": "preflop",
            "pid": f"P{n}" if i == 0 else "P1",
            "type": "raise",
            "amount": 6 + i * 8,
        })
    return SimpleNamespace(
        me=f"P{n}",
        street="preflop",
        position=position,
        hole_cards=list(hole),
        board=[],
        pot=35,
        to_call=to_call,
        legal_actions=legal,
        stacks={f"P{i}": 500 for i in range(1, n + 1)},
        history=history,
    )


class A17VersusThreeBetTests(unittest.TestCase):
    def test_approved_groups_and_weighted_range(self):
        self.assertEqual(A17_VS_3BET_CONTINUE_BOXES,
                         frozenset((1, 2, 3, 4, 5, 6, 7, 9)))
        self.assertEqual(A17_VS_3BET_FOURBET_FREQ, 0.50)
        combos = sum(
            6 if len(hand) == 2 else 4 if hand.endswith("s") else 12
            for hand, box in A17_HAND_TO_BOX.items()
            if box in A17_VS_3BET_CONTINUE_BOXES
        )
        self.assertEqual(combos, 258)
        self.assertEqual(A17_HAND_TO_BOX["K9s"], 8)
        self.assertEqual(A17_HAND_TO_BOX["98s"], 9)

    def test_each_approved_box_mixes_fourbet_and_call(self):
        bot = create_bot("a17_tag")
        samples = ("AA", "AKs", "AQs", "AJs", "A9s", "KQs", "A4s", "98s")
        for hand in samples:
            with self.subTest(hand=hand):
                for roll, wanted in ((0.0, "raise"),
                                     (0.49, "raise"),
                                     (0.5, "call"),
                                     (0.99, "call")):
                    with patch("bots.a17_preflop_bot.random.random",
                               return_value=roll):
                        self.assertEqual(bot.act(view(hand)).type, wanted)

    def test_a08_and_every_a10_a17_box_are_pure_fold(self):
        bot = create_bot("a17_tag")
        for box in (8, *range(10, 18)):
            hand = next(hand for hand, b in A17_HAND_TO_BOX.items()
                        if b == box)
            with self.subTest(box=box, hand=hand):
                for roll in (0.0, 0.99):
                    with patch("bots.a17_preflop_bot.random.random",
                               return_value=roll):
                        self.assertEqual(bot.act(view(hand)).type, "fold")

    def test_same_rule_for_all_positions_including_sb_bb(self):
        bot = create_bot("a17_tag")
        for pos in ("9", "8", "7", "6", "5", "4", "3", "SB", "BB"):
            with self.subTest(position=pos):
                with patch("bots.a17_preflop_bot.random.random",
                           return_value=0.49):
                    self.assertEqual(
                        bot.act(view("98s", position=pos)).type,
                        "raise",
                    )
                with patch("bots.a17_preflop_bot.random.random",
                           return_value=0.50):
                    self.assertEqual(
                        bot.act(view("98s", position=pos)).type,
                        "call",
                    )
                self.assertEqual(
                    bot.act(view("K9s", position=pos)).type, "fold"
                )

    def test_same_rule_from_nine_max_to_heads_up(self):
        bot = create_bot("a17_tag")
        for n, pos in ((9, "9"), (6, "6"), (4, "3"), (2, "SB")):
            with self.subTest(n=n):
                with patch("bots.a17_preflop_bot.random.random",
                           return_value=0.49):
                    self.assertEqual(
                        bot.act(view("98s", position=pos, n=n)).type,
                        "raise",
                    )
                self.assertEqual(
                    bot.act(view("K9s", position=pos, n=n)).type,
                    "fold",
                )

    def test_illegal_fourbet_falls_back_to_call(self):
        bot = create_bot("a17_tag")
        with patch("bots.a17_preflop_bot.random.random",
                   return_value=0.2):
            self.assertEqual(
                bot.act(view("AA", legal=[
                    {"type": "fold"}, {"type": "call"},
                ])).type,
                "call",
            )

    def test_one_open_is_not_threebet_and_a_fourbet_is_not_threebet(self):
        bot = create_bot("a17_tag")
        # Under existing SB rule, A08 (K9s) always raises unless
        # actually facing a three-bet, where it becomes a pure fold.
        self.assertEqual(
            bot.act(view("K9s", position="SB", raises=0, to_call=1)).type,
            "raise",
        )
        self.assertEqual(
            bot.act(view("K9s", position="SB", raises=1)).type,
            "raise",
        )
        self.assertEqual(
            bot.act(view("K9s", position="SB", raises=2)).type,
            "fold",
        )
        # In this test, the last aggression after three prior raises
        # is still handled by SB's pre-existing (not 3-bet) policy.
        self.assertEqual(
            bot.act(view("K9s", position="SB", raises=3)).type,
            "raise",
        )

    def test_3bet_detection_requires_hero_facing_opponent_bet(self):
        state = view("AA")
        self.assertTrue(A17PreflopBot._facing_three_bet(state, state.to_call))
        self.assertFalse(A17PreflopBot._facing_three_bet(state, 0))
        state.history[1]["pid"] = state.me
        self.assertFalse(A17PreflopBot._facing_three_bet(state, 10))
        state.history[1]["pid"] = "P1"
        state.history[1]["street"] = "flop"
        self.assertFalse(A17PreflopBot._facing_three_bet(state, 10))


if __name__ == "__main__":
    unittest.main()
