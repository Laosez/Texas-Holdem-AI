"""Preflop/postflop separation: routing, lifecycle and factory regression."""
import unittest
from types import SimpleNamespace

from bots import create_bot, parse_players
from bots.street_split_bot import EXPERIMENT_BASES, StreetSplitBot
from core.bot_api import Action, BotAdapter


class _CounterBot(BotAdapter):
    def __init__(self, action_type):
        self.action_type = action_type
        self.views = []
        self.resets = 0

    def act(self, view):
        self.views.append(view)
        return Action(self.action_type)

    def reset_memory(self):
        self.resets += 1


class TestStreetSplitBot(unittest.TestCase):
    def test_routes_exact_original_view_by_street(self):
        pre = _CounterBot("fold")
        post = _CounterBot("call")
        mix = StreetSplitBot(pre, post, preflop_name="gto", postflop_name="tag_punisher")
        for street in ("preflop", "flop", "turn", "river"):
            view = SimpleNamespace(street=street, history=[{"street": "preflop"}])
            decision = mix.act(view)
            self.assertEqual(decision.type, "fold" if street == "preflop" else "call")
            self.assertIs((pre.views if street == "preflop" else post.views)[-1], view)
        self.assertEqual([v.street for v in pre.views], ["preflop"])
        self.assertEqual([v.street for v in post.views], ["flop", "turn", "river"])

    def test_rejects_unknown_street(self):
        mix = StreetSplitBot(_CounterBot("fold"), _CounterBot("call"),
                             preflop_name="gto", postflop_name="tag_punisher")
        with self.assertRaisesRegex(ValueError, "Unknown poker street"):
            mix.act(SimpleNamespace(street="showdown"))

    def test_reset_both_and_only_once_if_same(self):
        pre, post = _CounterBot("fold"), _CounterBot("call")
        mix = StreetSplitBot(pre, post, preflop_name="gto", postflop_name="tag_punisher")
        mix.reset_memory()
        self.assertEqual((pre.resets, post.resets), (1, 1))
        shared = StreetSplitBot(pre, pre, preflop_name="gto", postflop_name="gto")
        shared.reset_memory()
        self.assertEqual(pre.resets, 2)

    def test_factory_creates_independent_hybrids(self):
        cases = [
            ("split:gto:tag_punisher", "gto", "tag_punisher"),
            ("split:tag_punisher:gto", "tag_punisher", "gto"),
            ("split:wide_defender:gto", "wide_defender", "gto"),
            ("split:smart:tag_punisher", "smart", "tag_punisher"),
        ]
        for spec, first, second in cases:
            with self.subTest(spec=spec):
                bot = create_bot(spec)
                self.assertIsInstance(bot, StreetSplitBot)
                self.assertEqual((bot.preflop_name, bot.postflop_name), (first, second))
                self.assertIsNot(bot.preflop_bot, bot.postflop_bot)
                bot.reset_memory()

    def test_random_can_be_postflop_under_gto_preflop(self):
        from unittest.mock import patch

        bot = create_bot("split:gto:random")
        self.assertIsInstance(bot, StreetSplitBot)
        self.assertEqual((bot.preflop_name, bot.postflop_name), ("gto", "random"))
        self.assertIn("random", EXPERIMENT_BASES)

        # With only one legal postflop action, RandomBot chooses that
        # action deterministically and the engine adapter returns Action.
        postflop_view = SimpleNamespace(
            street="flop", legal_actions=[{"type": "check"}]
        )
        self.assertEqual(bot.act(postflop_view), Action("check"))

        # Confirm routing: preflop cannot reach RandomBot.
        with patch.object(bot.preflop_bot, "act", return_value=Action("fold")) as pre:
            with patch.object(bot.postflop_bot, "act") as post:
                preflop_view = SimpleNamespace(street="preflop")
                self.assertEqual(bot.act(preflop_view), Action("fold"))
                pre.assert_called_once_with(preflop_view)
                post.assert_not_called()

    def test_fully_random_preflop_not_replaced_by_standard_v1(self):
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {"POKER_PREFLOP_PROTOCOL": "standard_v1"}):
            bot = create_bot("split:random:random")
            self.assertEqual((bot.preflop_name, bot.postflop_name), ("random", "random"))
            self.assertEqual(bot.preflop_protocol, "standard_v1")
            for street in ("preflop", "flop", "turn", "river"):
                with patch("bots.standard_preflop.response_action",
                           side_effect=AssertionError("Random must bypass V1")):
                    result = bot.act(SimpleNamespace(
                        street=street,legal_actions=[{"type":"check"}]))
                self.assertEqual(result, Action("check"))

    def test_random_preflop_can_pair_with_nonrandom_postflop(self):
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {"POKER_PREFLOP_PROTOCOL": "standard_v1"}):
            bot = create_bot("split:random:gto_postflop_v2")
            self.assertEqual(bot.preflop_name, "random")
            self.assertEqual(bot.postflop_name, "gto_postflop_v2")
            self.assertEqual(bot.act(SimpleNamespace(
                street="preflop",legal_actions=[{"type":"check"}])), Action("check"))

    def test_maniac_mixed_postflop_uses_distinct_preset(self):
        mixed = create_bot("split:gto:maniac_mixed")
        trigger = create_bot("split:gto:maniac")
        self.assertEqual(mixed.preflop_name, "gto")
        self.assertEqual(mixed.postflop_name, "maniac_mixed")
        self.assertEqual(
            mixed.postflop_bot.bot.config.policy_name,
            trigger.postflop_bot.bot.config.policy_name,
        )
        self.assertEqual(mixed.postflop_bot.bot.knob("jam_freq"), 0.43)
        self.assertEqual(trigger.postflop_bot.bot.knob("jam_freq"), 0.65)
        self.assertEqual(mixed.postflop_bot.bot.knob("postflop_probe_freq"), 0.34)
        self.assertEqual(trigger.postflop_bot.bot.knob("postflop_probe_freq"), 0.42)

    def test_random_clones_have_distinct_export_labels(self):
        from core.engine import InProcessBot, RandomBot

        names = ("random", "random_2", "random_3", "random_10")
        for name in names:
            with self.subTest(name=name):
                direct = create_bot(name)
                self.assertIsInstance(direct, InProcessBot)
                self.assertIsInstance(direct.bot, RandomBot)
                hybrid = create_bot(f"split:gto:{name}")
                self.assertEqual(hybrid.preflop_name, "gto")
                self.assertEqual(hybrid.postflop_name, name)
                self.assertEqual(
                    hybrid.act(SimpleNamespace(street="flop", legal_actions=[{"type": "check"}])),
                    Action("check"),
                )

        seats = parse_players(
            "P7=split:gto:random,P8=split:gto:random_2,"
            "P9=split:gto:random_3"
        )
        self.assertEqual([pid for pid, _, _ in seats], ["P7", "P8", "P9"])
        self.assertEqual(len({btype for _, btype, _ in seats}), 3)
        self.assertIsNot(seats[0][2].postflop_bot, seats[1][2].postflop_bot)

        for invalid in ("random_0", "random_1", "random_11", "random_x"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    create_bot(f"split:gto:{invalid}")

    def test_same_base_keeps_same_adapter_instance(self):
        bot = create_bot("split:gto:gto")
        self.assertIs(bot.preflop_bot, bot.postflop_bot)

    def test_baselines_remain_direct(self):
        for name in ("gto", "tag_punisher", "wide_defender", "smart"):
            with self.subTest(name=name):
                bot = create_bot(name)
                self.assertNotIsInstance(bot, StreetSplitBot)

    def test_factory_validation(self):
        for spec in ("split:gto", "split:gto:", "split::gto",
                     "split:gto:unknown", "split:final:gto", "split:gto:gto:tag"):
            with self.subTest(spec=spec):
                with self.assertRaises(ValueError):
                    create_bot(spec)

    def test_tournament_player_specs(self):
        specs = parse_players("P1=split:gto:tag_punisher,P2=split:tag_punisher:gto,P3=gto")
        self.assertEqual([pid for pid, _, _ in specs], ["P1", "P2", "P3"])
        self.assertTrue(isinstance(specs[0][2], StreetSplitBot))
        self.assertEqual(specs[1][1], "split:tag_punisher:gto")

    def test_expected_bases_supported(self):
        self.assertTrue({"gto", "smart", "tag_punisher",
                         "wide_defender"}.issubset(EXPERIMENT_BASES))


if __name__ == "__main__":
    unittest.main()
