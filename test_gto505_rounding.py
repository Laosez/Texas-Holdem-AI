"""GTO 5.0.5 A/B regression: independent 5 pp rounding and paired Shadow."""
import os
import unittest
from unittest.mock import patch

from bots import create_bot
from bots.gto_postflop_50 import (
    HumanRangeGTO50Bot, RoundedHumanRangeGTO505Bot,
    board_distribution, round_probability_to_five, CATEGORIES,
)
from gto5_shadow_report import aggregate_shadow
from test_gto_postflop_50 import view


class GTO505Round5Tests(unittest.TestCase):
    def test_registration_and_unmodified_baseline(self):
        import replit_simulator
        catalog = replit_simulator.strategy_catalog()
        self.assertIn("gto_postflop_505_5", catalog["postflop_strategies"])
        self.assertEqual(catalog["postflop_profiles"]["gto_postflop_505_5"]["model"],
                         "human_board_ev_round5_alpha")
        baseline = create_bot("split:random:gto_postflop_50_5").postflop_bot
        rounded = create_bot("split:random:gto_postflop_505_5").postflop_bot
        self.assertEqual(baseline.round_step, 0)
        self.assertEqual(rounded.round_step, 5)
        self.assertEqual(rounded.profile, "gto_postflop_505_5")

    def test_round_half_up_exact_five_percentage_points(self):
        self.assertEqual([round_probability_to_five(x)
                          for x in (0, 2.49, 2.5, 7.49, 7.5, 12.5, 99.9, 100)],
                         [0, 0, 5, 5, 10, 15, 100, 100])

    def test_rounding_changes_only_probability_marginals(self):
        boards = [
            [("Q","h"),("8","s"),("3","d")],
            [("Q","h"),("Q","s"),("3","d"),("2","c")],
            [("Q","h"),("Q","s"),("3","d"),("3","c"),("7","h")],
            [("Q","h"),("Q","s"),("Q","c"),("3","d"),("7","h")],
            [("T","h"),("J","h"),("Q","h"),("K","h"),("A","h")],
        ]
        changed = 0
        for board in boards:
            exact = board_distribution(board)
            rounded = board_distribution(board, round_to_five=True)
            self.assertEqual(rounded["round_step_pct"], 5)
            self.assertEqual(exact["round_step_pct"], 0)
            self.assertEqual(tuple(rounded["categories_pct"]), CATEGORIES)
            for name in CATEGORIES:
                a, b = exact["categories_pct"][name], rounded["categories_pct"][name]
                self.assertEqual(b, round_probability_to_five(a))
                self.assertEqual(b % 5, 0)
                changed += a != b
            self.assertAlmostEqual(sum(rounded["probability_mass"]), 1, places=10)
        self.assertGreater(changed, 0)

    def test_cross_version_shadow_does_not_override_play(self):
        board = [("Q","h"), ("8","s"), ("3","d")]
        state = view("flop", board)
        with patch.dict(os.environ, {"POKER_GTO5_SHADOW_PERCENT": "100",
                                     "POKER_GTO5_SHADOW_REFERENCE": "gto50"}):
            rounded = RoundedHumanRangeGTO505Bot()
            playing = RoundedHumanRangeGTO505Bot(shadow_percent=0)
            target_action = playing.act(state)
            live = rounded.act(state)
            self.assertEqual((live.type, live.amount),
                             (target_action.type, target_action.amount))
            self.assertEqual(rounded.shadow_checked, 1)
            event = rounded.shadow_records[0]
            self.assertEqual(event["actor"], "gto505")
            self.assertEqual(event["reference_model"], "gto50")
            self.assertEqual(set(event["ev5"]), set(event["ev41"]))
            self.assertEqual(rounded.shadow_reference.shadow_percent, 0)
            report = aggregate_shadow([event])
            self.assertEqual(report["comparisons"][0]["label"],
                             "GTO 5.0.5 → GTO 5.0")
            self.assertEqual(report["compared"], 1)
            self.assertEqual(report["overall"]["mean_regret_bb"],
                             report["comparisons"][0]["overall"]["mean_regret_bb"])

    def test_reverse_comparison_and_same_model_is_skipped(self):
        with patch.dict(os.environ, {"POKER_GTO5_SHADOW_PERCENT": "100",
                                     "POKER_GTO5_SHADOW_REFERENCE": "gto505"}):
            actor = HumanRangeGTO50Bot()
            actor.act(view())
            self.assertEqual(actor.shadow_checked, 1)
            self.assertEqual(actor.shadow_records[0]["reference_model"], "gto505")
            self.assertEqual(actor.shadow_reference.profile, "gto_postflop_505_5")
            self.assertEqual(actor.shadow_reference.shadow_percent, 0)
            rounded = RoundedHumanRangeGTO505Bot()
            rounded.act(view())
            self.assertEqual(rounded.shadow_checked, 0)
            self.assertEqual(rounded.shadow_records, [])

    def test_old_four_one_benchmark_still_supported(self):
        with patch.dict(os.environ, {"POKER_GTO5_SHADOW_PERCENT": "0",
                                     "POKER_GTO5_SHADOW_REFERENCE": "gto41"}):
            actor = RoundedHumanRangeGTO505Bot()
            action = actor.act(view())
            self.assertIn(action.type, {"check", "bet"})
            self.assertEqual(actor.last_model["version"], "gto5.0.5-alpha")


if __name__ == "__main__":
    unittest.main()
