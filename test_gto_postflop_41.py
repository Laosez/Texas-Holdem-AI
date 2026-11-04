"""Regression checks for GTO 4.1 multiway EV and full street opportunity stats."""
import unittest
from collections import Counter
from types import SimpleNamespace
from unittest.mock import patch

from bots import create_bot
from bots.gto_postflop_41 import (
    JointRangeGTO41Bot, _band_for, _range_profile, _showdown_share,
)
from export_preflop_ranges_v4 import TrackedBot
from test_postflop_profiles import make_view
import replit_simulator


class GTO41MultiwayTests(unittest.TestCase):
    def test_registered_and_selectable_without_overwriting_40(self):
        for n in (5, 10):
            name = "gto_postflop_41_" + str(n)
            if n == 5:
                self.assertIn(name, replit_simulator.strategy_catalog()["postflop_strategies"])
            else:
                self.assertNotIn(name, replit_simulator.strategy_catalog()["postflop_strategies"])
                self.assertTrue(replit_simulator.available_postflop(name))
            self.assertEqual(create_bot(name).profile, name)
            self.assertIsInstance(create_bot(name), JointRangeGTO41Bot)
            split = create_bot("split:a17_preflop:" + name)
            self.assertEqual(split.postflop_name, name)

    def test_exact_legal_card_distribution_includes_hero_blockers(self):
        hero = (("K", "s"), ("J", "d"))
        for board, expected in (
            ((("K", "c"), ("Q", "d"), ("3", "h")), 1081),
            ((("K", "c"), ("Q", "d"), ("3", "h"), ("4", "s")), 1035),
            ((("K", "c"), ("Q", "d"), ("3", "h"), ("4", "s"), ("5", "c")), 990),
        ):
            deck, percentiles, info = _range_profile(hero, board)
            self.assertEqual(len(percentiles), expected)
            self.assertEqual(info["possible_hands"], expected)
            self.assertAlmostEqual(sum(info["categories_pct"].values()), 100, delta=.02)
            for hand in percentiles:
                self.assertFalse(set(hand) & set(hero + board))
            self.assertEqual(len(deck), 52 - len(hero + board))

    def test_prior_top_fraction_is_preserved(self):
        bot = JointRangeGTO41Bot(5)
        groups = bot.street_matrix("P2")["flop"]
        self.assertEqual(_band_for("P2", "flop", [], groups), (0, 1))
        band = _band_for("P2", "flop", [
            {"street": "flop", "pid": "P2", "type": "bet"}
        ], groups)
        self.assertAlmostEqual(band[0], .55)
        self.assertEqual(band[1], 1)

    def test_multiway_no_33_fallback_and_deterministic(self):
        # Small valid replacement range keeps the integration test cheap.
        hero = [("A", "s"), ("K", "s")]
        board = [("2", "c"), ("6", "h"), ("9", "d")]
        hands = [
            (("3", "c"), ("4", "c")),
            (("5", "d"), ("7", "h")),
            (("8", "c"), ("T", "h")),
            (("J", "c"), ("Q", "d")),
            (("4", "d"), ("5", "c")),
            (("7", "c"), ("8", "d")),
        ]
        ranks = {hand: (i + .5) / len(hands) for i, hand in enumerate(hands)}
        deck = tuple(c for c in __import__("core.engine", fromlist=["_FULL_DECK"])._FULL_DECK
                     if c not in set(hero + board))
        profile = (deck, ranks, {"possible_hands": 1081,
                                "evaluated_hands": 1081,
                                "categories_pct": {},
                                "enumeration": "exact_with_hero_blockers"})
        view = make_view(hole=hero, board=board, opponents=("P2", "P3"), pot=100)
        with patch("bots.gto_postflop_41._range_profile", return_value=profile):
            first = JointRangeGTO41Bot(5)
            a = first.act(view)
            second = JointRangeGTO41Bot(5)
            b = second.act(view)
        self.assertEqual((a.type, a.amount), (b.type, b.amount))
        self.assertIn(a.type, {"check", "bet"})
        self.assertEqual(first.last_model["version"], "gto4.1")
        self.assertEqual(first.last_model["opponents_count"], 2)
        self.assertEqual(first.last_model["decision_inputs"]["joint_trials"], 128)
        self.assertEqual(len(first.last_model["street_matrices"]), 2)

    def test_multiway_call_and_sidepot_diagnostic(self):
        hero = [("A", "s"), ("K", "s")]
        board = [("2", "c"), ("6", "h"), ("9", "d"), ("J", "s"), ("Q", "h")]
        v = make_view(hole=hero, board=board, street="river", to_call=30,
                      pot=100, opponents=("P2", "P3"),
                      history=({"street": "river", "pid": "P2", "type": "bet"},))
        v.all_in_opponents = ["P3"]
        bot = JointRangeGTO41Bot(10)
        # The river is exact but still uses joint Monte Carlo over villain holdings.
        action = bot.act(v)
        self.assertIn(action.type, {"fold", "call"})
        self.assertEqual(bot.last_model["version"], "gto4.1")
        self.assertTrue(bot.last_model["decision_inputs"]["side_pot_approximation"])
        self.assertEqual(bot.last_model["decision_inputs"]["joint_trials"], 192)

    def test_shared_board_tie_share(self):
        board = [("A", "s"), ("K", "s"), ("Q", "s"), ("J", "s"), ("T", "s")]
        self.assertAlmostEqual(
            _showdown_share((("2", "c"), ("3", "d")),
                            [(("4", "c"), ("5", "d")), (("6", "c"), ("7", "d"))],
                            board),
            1 / 3)


class FullStreetStatsTests(unittest.TestCase):
    def test_response_contexts_and_sizing(self):
        bot = TrackedBot(object(), "test")
        bot.player_id = "P1"
        bot.observe_deal(1, [("A", "s"), ("K", "s")], "3", 9)
        base = dict(street="turn", me="P1", hand_id=1, opponents=["P2", "P3"],
                    pot=100)
        def observe(legal, to_call, history, kind, amount=None):
            view = SimpleNamespace(**base, legal_actions=[{"type": x} for x in legal],
                                   to_call=to_call, history=history)
            bot.observe_postflop(view, SimpleNamespace(type=kind, amount=amount))
        observe(("check", "bet"), 0, [], "bet", 50)
        observe(("fold", "call", "raise"), 25,
                [{"street": "turn", "pid": "P2", "type": "bet"}], "call")
        observe(("fold", "call", "raise"), 35,
                [{"street": "turn", "pid": "P3", "type": "raise"}], "raise", 90)
        observe(("fold", "call"), 20,
                [{"street": "turn", "pid": "P2", "type": "bet"}], "call")
        s = bot.postflop_opponent_counts[(2, "turn")]
        self.assertEqual((s["open_opp"], s["open_bet_n"]), (1, 1))
        self.assertEqual((s["vs_bet_opp"], s["vs_bet_call_n"]), (1, 1))
        self.assertEqual((s["vs_raise_opp"], s["vs_raise_reraise_n"]), (1, 1))
        self.assertEqual(s["restricted_response_opp"], 1)
        self.assertEqual((s["bet_size_pot_n"], s["bet_size_pot_sum"]), (1, 50))
        self.assertEqual((s["raise_size_pot_n"], s["raise_size_pot_sum"]), (1, 90))


if __name__ == "__main__":
    unittest.main()
