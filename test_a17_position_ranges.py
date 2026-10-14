"""A17 RFI ranges, SB opens, SB defense and table-size regression tests."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bots import create_bot
from bots.a17_preflop_bot import A17PreflopBot
from bots.a17_ranges import (
    A17_HAND_TO_BOX, A17_MAX_OPEN_BOX_9MAX,
    A17_MAX_OPEN_BOX_BY_POSITION, A17_RFI_EXTRA_BOXES_BY_POSITION,
    A17_SB_MAX_RAISE_BOX,
)


def _view(hand, position="9", n=9, history=(), to_call=2, legal=None):
    if legal is None:
        legal = [
            {"type": "fold"},
            {"type": "call"},
            {"type": "raise", "min": 4, "max": 100},
        ]
    ranks = [("A", "s"), ("A", "h")] if hand == "AA" else None
    if ranks is None:
        if len(hand) == 2:
            ranks = [(hand[0], "s"), (hand[1], "d")]
        elif hand.endswith("s"):
            ranks = [(hand[0], "s"), (hand[1], "s")]
        else:
            ranks = [(hand[0], "s"), (hand[1], "d")]
    return SimpleNamespace(
        me=f"P{n}", street="preflop", position=position,
        hole_cards=ranks, pot=3, board=[],
        to_call=to_call, legal_actions=legal,
        stacks={f"P{i}": 500 for i in range(1, n + 1)},
        history=list(history),
    )


class A17PositionRangesTests(unittest.TestCase):
    def test_source_169_hands_1326_combos_and_exact_boundaries(self):
        self.assertEqual(len(A17_HAND_TO_BOX), 169)
        self.assertEqual(
            sum(6 if len(h) == 2 else 4 if h.endswith("s") else 12
                for h in A17_HAND_TO_BOX),
            1326,
        )
        self.assertEqual(
            A17_MAX_OPEN_BOX_9MAX,
            {"9": 9, "8": 9, "7": 9, "6": 10, "5": 11,
             "4": 11, "3": 12, "SB": 17},
        )
        self.assertEqual(A17_RFI_EXTRA_BOXES_BY_POSITION, {"3": frozenset({15})})
        self.assertEqual(
            {p: sum(6 if len(h) == 2 else 4 if h.endswith("s") else 12
                    for h, box in A17_HAND_TO_BOX.items()
                    if box <= max_box or box in A17_RFI_EXTRA_BOXES_BY_POSITION.get(p, ()))
             for p, max_box in A17_MAX_OPEN_BOX_9MAX.items()},
            {"9": 306, "8": 306, "7": 306, "6": 402, "5": 454,
             "4": 454, "3": 634, "SB": 1326},
        )

    def test_pure_open_raise_at_every_user_defined_boundary(self):
        bot = create_bot("a17_tag")
        self.assertIsInstance(bot.preflop_bot.bot, A17PreflopBot)
        for pos, inside, outside in [
            ("9", "98s", "KJo"),
            ("8", "98s", "KJo"),
            ("7", "98s", "KJo"),
            ("6", "Q9o", "K2s"),
            ("5", "K2s", "A9o"),
            ("4", "K2s", "A9o"),
            ("3", "K8o", "T9o"),
        ]:
            with self.subTest(position=pos):
                self.assertEqual(bot.act(_view(inside, position=pos)).type, "raise")
                self.assertEqual(bot.act(_view(outside, position=pos)).type, "fold")

    def test_btn_non_contiguous_a15_without_a13_a14(self):
        bot = create_bot("a17_tag")
        for n in range(3, 10):
            for hand in ("A9o", "A2o", "K8o", "K2o"):
                with self.subTest(n=n, hand=hand, action="raise"):
                    self.assertEqual(
                        bot.act(_view(hand, position="3", n=n)).type, "raise"
                    )
            for hand in ("Q2s", "T9o", "87o", "J8o"):
                with self.subTest(n=n, hand=hand, action="fold"):
                    self.assertEqual(
                        bot.act(_view(hand, position="3", n=n)).type, "fold"
                    )

    def test_hj_and_co_stop_at_a11(self):
        bot = create_bot("a17_tag")
        for pos in ("5", "4"):
            for hand in ("K6s", "Q5s", "A9o", "A2o", "K8o"):
                want = "raise" if A17_HAND_TO_BOX[hand] <= 11 else "fold"
                with self.subTest(position=pos, hand=hand):
                    self.assertEqual(
                        bot.act(_view(hand, position=pos)).type, want
                    )

    def test_sb_raises_a01_a16_and_calls_a17_at_every_stage(self):
        bot = create_bot("a17_tag")
        self.assertIs(A17_MAX_OPEN_BOX_9MAX, A17_MAX_OPEN_BOX_BY_POSITION)
        self.assertEqual(A17_SB_MAX_RAISE_BOX, 16)
        nraise = sum(
            6 if len(hand) == 2 else 4 if hand.endswith("s") else 12
            for hand, box in A17_HAND_TO_BOX.items()
            if box <= A17_SB_MAX_RAISE_BOX
        )
        self.assertEqual(nraise, 918)
        for n in range(2, 10):
            for history in (
                (),
                ({"street": "preflop", "pid": "P1", "type": "call"},),
            ):
                for hand in ("AA", "J8o", "74o"):
                    with self.subTest(n=n, action="raise", hand=hand, history=history):
                        self.assertEqual(
                            bot.act(_view(hand, position="SB", n=n, history=history)).type,
                            "raise",
                        )
                for hand in ("72o", "32o"):
                    with self.subTest(n=n, action="call", hand=hand, history=history):
                        self.assertEqual(
                            bot.act(_view(hand, position="SB", n=n, history=history)).type,
                            "call",
                        )

    def test_sb_legal_action_fallback_when_raise_unavailable(self):
        bot = create_bot("a17_tag")
        call_only = [{"type": "fold"}, {"type": "call"}]
        check_only = [{"type": "check"}]
        self.assertEqual(
            bot.act(_view("AA", position="SB", n=2, legal=call_only)).type,
            "call",
        )
        self.assertEqual(
            bot.act(_view("AA", position="SB", n=2, to_call=0, legal=check_only)).type,
            "check",
        )
        self.assertEqual(
            bot.act(_view("72o", position="SB", n=2, to_call=0, legal=check_only)).type,
            "check",
        )

    def test_preflop_prior_limp_uses_fixed_gto_instead_of_rfi(self):
        bot = create_bot("a17_tag")
        # 98s is box A09 and pure RFI raise from UTG; after a limp,
        # original grouped EP default mixed strategy applies instead.
        history = ({"street": "preflop", "pid": "P1", "type": "call"},)
        with patch("bots.gto_fixed_bot.random.random", return_value=0.90):
            self.assertEqual(bot.act(_view("98s", history=history)).type, "call")

    def test_facing_real_raise_uses_fixed_gto_including_sb(self):
        bot = create_bot("a17_tag")
        control = create_bot("gto_fixed")
        open_raise = ({"street": "preflop", "pid": "P1", "type": "raise"},)
        later_fourbet = (
            {"street": "preflop", "pid": "P2", "type": "raise"},
            {"street": "preflop", "pid": "P1", "type": "raise"},
            {"street": "preflop", "pid": "P3", "type": "raise"},
        )
        # The A17 SB A01-A16 rule applies only without a prior raise.
        # An opponent open (or 4-bet) is not a reason to 3-/5-bet J8o.
        for n in range(2, 10):
            for history in (open_raise, later_fourbet):
                for hand in ("AA", "K9s", "J8o", "72o"):
                    with self.subTest(n=n, hand=hand, raises=len(history)):
                        state = _view(hand, position="SB", n=n, history=history)
                        with patch("bots.gto_fixed_bot.random.random",
                                   return_value=0.40):
                            self.assertEqual(bot.act(state), control.act(state))
                        if hand == "J8o":
                            with patch("bots.gto_fixed_bot.random.random",
                                       return_value=0.40):
                                self.assertEqual(bot.act(state).type, "fold")

        # Numeric positions continue to use the same fixed-GTO policy.
        with patch("bots.gto_fixed_bot.random.random", return_value=0.90):
            self.assertEqual(
                bot.act(_view("98s", history=open_raise)).type, "fold"
            )

    def test_short_handed_numeric_positions_keep_same_cutoffs(self):
        bot = create_bot("a17_tag")
        positions = [
            ("9", "98s", "KJo"),
            ("8", "98s", "KJo"),
            ("7", "98s", "KJo"),
            ("6", "Q9o", "K2s"),
            ("5", "K2s", "A9o"),
            ("4", "K2s", "A9o"),
            ("3", "K8o", "T9o"),
        ]
        for n in range(3, 10):
            for pos, inside, outside in positions:
                if int(pos) > n:
                    continue
                with self.subTest(n=n, position=pos):
                    self.assertEqual(
                        bot.act(_view(inside, position=pos, n=n)).type, "raise"
                    )
                    self.assertEqual(
                        bot.act(_view(outside, position=pos, n=n)).type, "fold"
                    )

    def test_bb_remains_fixed_gto_even_on_short_handed_tables(self):
        bot = create_bot("a17_tag")
        for n in (2, 4, 9):
            bb = _view(
                "72o", position="BB", n=n, to_call=0,
                legal=[{"type": "check"}, {"type": "raise", "min": 4, "max": 100}],
            )
            with patch("bots.gto_fixed_bot.random.random", return_value=0.50):
                self.assertEqual(bot.act(bb).type, "check")

    def test_base_gto_controls_remain_distinct_from_user_a17_policy(self):
        control = create_bot("split:gto:tag_punisher")
        new = create_bot("a17_tag")
        self.assertEqual(control.preflop_name, "gto")
        self.assertEqual(new.preflop_name, "a17_preflop")
        self.assertEqual(control.postflop_name, new.postflop_name)


if __name__ == "__main__":
    unittest.main()
