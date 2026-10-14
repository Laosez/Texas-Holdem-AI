"""Regression tests for fixed-GTO preflop and unchanged TAG postflop."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bots import create_bot, parse_players
from bots.gto_fixed_bot import FixedGTOPreflopBot
from bots.a17_preflop_bot import A17PreflopBot
from bots.street_split_bot import StreetSplitBot
from core.bot_api import Action


def _view(
    *,
    street="preflop",
    hole=(("7", "c"), ("2", "d")),
    board=(),
    position="9",
    to_call=2,
    history=(),
    pot=3,
    legal=None,
):
    if legal is None:
        legal = [
            {"type": "fold"},
            {"type": "call"},
            {"type": "raise", "min": 4, "max": 100},
        ]
    return SimpleNamespace(
        me="P6",
        street=street,
        position=position,
        hole_cards=list(hole),
        board=list(board),
        pot=pot,
        to_call=to_call,
        legal_actions=legal,
        stacks={f"P{i}": 500 for i in range(1, 10)},
        history=list(history),
        hand_id=1,
        min_raise=2,
        max_raise=100,
        opponents=["P1", "P2"],
    )


class A17FixedGTOTagTests(unittest.TestCase):
    def test_named_a17_tag_routes_approved_a17_preflop_and_tag_postflop(self):
        bot = create_bot("a17_tag")
        self.assertIsInstance(bot, StreetSplitBot)
        self.assertEqual(bot.preflop_name, "a17_preflop")
        self.assertEqual(bot.postflop_name, "tag_punisher")
        self.assertIsInstance(bot.preflop_bot.bot, A17PreflopBot)
        self.assertEqual(bot.postflop_bot.bot.config.policy_name, "tag_punisher")
        self.assertEqual(create_bot("split:gto_fixed:tag_punisher").preflop_name, "gto_fixed")
        self.assertEqual(parse_players("P6=a17_tag")[0][1], "a17_tag")

    def test_unopened_pot_does_not_count_posted_blind_as_raise(self):
        view = _view(to_call=2, history=())
        fixed = create_bot("gto_fixed")
        baseline = create_bot("gto")
        # 72o is not listed in EP tiers: fold/call/raise = 0.85/0.10/0.05.
        # Legacy GTO erroneously tightens it to fold 100% because to_call > 0.
        with patch("bots.gto_fixed_bot.random.random", return_value=0.90):
            self.assertEqual(fixed.act(view).type, "call")
            self.assertEqual(baseline.act(view).type, "fold")

    def test_limp_and_own_raise_do_not_trigger_tightening(self):
        limp = _view(history=({"street": "preflop", "pid": "P1", "type": "call"},))
        own_raise = _view(history=({"street": "preflop", "pid": "P6", "type": "raise"},))
        bot = create_bot("gto_fixed")
        with patch("bots.gto_fixed_bot.random.random", return_value=0.90):
            self.assertEqual(bot.act(limp).type, "call")
            self.assertEqual(bot.act(own_raise).type, "call")

    def test_real_opponent_raise_preserves_original_tightening(self):
        raised = _view(history=({"street": "preflop", "pid": "P2", "type": "raise"},))
        bot = create_bot("gto_fixed")
        with patch("bots.gto_fixed_bot.random.random", return_value=0.90):
            self.assertEqual(bot.act(raised).type, "fold")
        self.assertTrue(
            FixedGTOPreflopBot._facing_opponent_raise(raised)
        )

    def test_free_big_blind_check_and_voluntary_raise_detection(self):
        bb = _view(
            position="BB", to_call=0,
            legal=[{"type": "check"}, {"type": "raise", "min": 4, "max": 100}],
        )
        bot = create_bot("gto_fixed")
        with patch("bots.gto_fixed_bot.random.random", return_value=0.90):
            self.assertEqual(bot.act(bb), Action("check"))
        self.assertFalse(
            FixedGTOPreflopBot._facing_opponent_raise(bb)
        )

    def test_postflop_is_tag_punisher_not_fixed_gto(self):
        flop = _view(
            street="flop",
            hole=(("A", "s"), ("K", "s")),
            board=(("A", "d"), ("K", "d"), ("2", "c")),
            to_call=0,
            pot=30,
            history=(),
            legal=[{"type": "check"}, {"type": "bet", "min": 2, "max": 100}],
        )
        a17 = create_bot("a17_tag")
        tag = create_bot("tag_punisher")
        self.assertEqual(a17.act(flop), tag.act(flop))


if __name__ == "__main__":
    unittest.main()
