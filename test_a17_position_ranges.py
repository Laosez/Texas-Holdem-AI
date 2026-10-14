"""A17 9-max positional RFI and full-range SB limp, from user's 169-hand JSON."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bots import create_bot
from bots.a17_preflop_bot import A17PreflopBot
from bots.a17_ranges import A17_HAND_TO_BOX, A17_MAX_OPEN_BOX_9MAX


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
        me="P9", street="preflop", position=position,
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
            {"9": 9, "8": 9, "7": 9, "6": 10, "5": 12,
             "4": 14, "3": 15, "SB": 17},
        )
        self.assertEqual(
            {p: sum(6 if len(h) == 2 else 4 if h.endswith("s") else 12
                    for h, box in A17_HAND_TO_BOX.items() if box <= max_box)
             for p, max_box in A17_MAX_OPEN_BOX_9MAX.items()},
            {"9": 306, "8": 306, "7": 306, "6": 402, "5": 550,
             "4": 774, "3": 858, "SB": 1326},
        )

    def test_pure_open_raise_at_every_user_defined_boundary(self):
        bot = create_bot("a17_tag")
        self.assertIsInstance(bot.preflop_bot.bot, A17PreflopBot)
        for pos, inside, outside in [
            ("9", "98s", "KJo"),
            ("8", "98s", "KJo"),
            ("7", "98s", "KJo"),
            ("6", "Q9o", "K2s"),
            ("5", "A2o", "Q2s"),
            ("4", "T9o", "K8o"),
            ("3", "K8o", "J8o"),
        ]:
            with self.subTest(position=pos):
                self.assertEqual(bot.act(_view(inside, position=pos)).type, "raise")
                self.assertEqual(bot.act(_view(outside, position=pos)).type, "fold")

    def test_sb_completes_every_hand_in_unopened_or_limped_pot(self):
        bot = create_bot("a17_tag")
        for h in ("AA", "72o", "32o"):
            for history in ((), ({"street": "preflop", "pid": "P1", "type": "call"},)):
                with self.subTest(hand=h, history=bool(history)):
                    self.assertEqual(
                        bot.act(_view(h, position="SB", history=history)).type,
                        "call",
                    )

    def test_preflop_prior_limp_uses_fixed_gto_instead_of_rfi(self):
        bot = create_bot("a17_tag")
        # 98s is box A09 and pure RFI raise from UTG; after a limp,
        # original grouped EP default mixed strategy applies instead.
        history = ({"street": "preflop", "pid": "P1", "type": "call"},)
        with patch("bots.gto_fixed_bot.random.random", return_value=0.90):
            self.assertEqual(bot.act(_view("98s", history=history)).type, "call")

    def test_facing_real_raise_does_not_use_a17_rfi_or_sb_limp(self):
        bot = create_bot("a17_tag")
        history = ({"street": "preflop", "pid": "P1", "type": "raise"},)
        with patch("bots.gto_fixed_bot.random.random", return_value=0.90):
            self.assertEqual(bot.act(_view("98s", history=history)).type, "fold")
            self.assertEqual(bot.act(_view("72o", position="SB", history=history)).type, "fold")

    def test_short_handed_and_bb_use_existing_fixed_gto(self):
        bot = create_bot("a17_tag")
        baseline = create_bot("gto_fixed")
        short = _view("72o", position="8", n=8)
        with patch("bots.gto_fixed_bot.random.random", return_value=0.90):
            self.assertEqual(bot.act(short), baseline.act(short))
            self.assertEqual(bot.act(short).type, "call")

        bb = _view(
            "72o", position="BB", n=9, to_call=0,
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
