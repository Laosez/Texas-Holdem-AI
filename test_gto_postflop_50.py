"""Executable GTO 5.0 alpha and opt-in shadow regression tests."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bots import create_bot
from bots.gto_postflop_50 import (
    HumanRangeGTO50Bot, board_distribution, _completed_made, OFFSETS,
)
from core.bot_api import Action
from gto5_shadow_report import aggregate_shadow


def view(street="flop", board=None, to_call=0, opponents=None):
    if board is None:
        board = [("Q", "h"), ("8", "s"), ("3", "d")]
    if opponents is None:
        opponents = ("P2", "P3")
    types = ([{"type": "fold"}, {"type": "call"},
              {"type": "raise", "min": 8, "max": 200}]
             if to_call else [{"type": "check"},
                              {"type": "bet", "min": 4, "max": 200}])
    return SimpleNamespace(
        me="P1", street=street, position="BTN",
        hole_cards=[("A", "s"), ("Q", "s")],
        board=list(board), pot=100, to_call=to_call,
        legal_actions=types, stacks={"P1": 200, **{x: 200 for x in opponents}},
        opponents=list(opponents), acting_opponents=list(opponents),
        all_in_opponents=[], history=[], hand_id=71,
    )


class GTO50Tests(unittest.TestCase):
    def test_registration_and_shared_catalog(self):
        import replit_simulator as app
        self.assertIn("gto_postflop_50_5", app.strategy_catalog()["postflop_archived"])
        self.assertEqual(app.strategy_catalog()["postflop_profiles"]["gto_postflop_50_5"]["model"],
                         "human_board_ev_alpha")
        bot = create_bot("split:random:gto_postflop_50_5")
        self.assertEqual(bot.postflop_bot.profile, "gto_postflop_50_5")

    def test_simple_y_offsets_and_all_categories(self):
        self.assertEqual(OFFSETS["P0"][:4], (10, -6, -3, -1))
        self.assertEqual(OFFSETS["P1"][:4], (0, 9, -8, 0))
        self.assertEqual(OFFSETS["P2"][2], 0)
        self.assertEqual(OFFSETS["P3"][3], 12)
        self.assertEqual(OFFSETS["P3"][6], -11)
        for board in [
            [("Q", "h"), ("8", "s"), ("3", "d")],
            [("Q", "h"), ("Q", "s"), ("3", "d")],
            [("Q", "h"), ("Q", "s"), ("3", "d"), ("3", "c")],
            [("Q", "h"), ("Q", "s"), ("Q", "c")],
        ]:
            dist = board_distribution(board)
            self.assertEqual(dist["formula_status"], "P0-P3 / AnyTwo neutral K")
            self.assertEqual(len(dist["categories_pct"]), 9)
            self.assertAlmostEqual(sum(dist["probability_mass"]), 1.0, places=6)

    def test_no_opponent_enumeration_or_mc_when_off(self):
        with patch.dict(os.environ, {"POKER_GTO5_SHADOW_PERCENT": "0"}):
            bot = HumanRangeGTO50Bot()
            from bots import gto_postflop_41
            with patch.object(gto_postflop_41, "_range_profile",
                              side_effect=AssertionError("not allowed")):
                for st, board in [
                    ("flop", [("Q","h"),("8","s"),("3","d")]),
                    ("turn", [("Q","h"),("8","s"),("3","d"),("2","c")]),
                    ("river", [("Q","h"),("8","s"),("3","d"),("2","c"),("9","h")]),
                ]:
                    action = bot.act(view(st, board))
                    self.assertIn(action.type, {"check", "bet"})
                    self.assertIn("check", bot.last_model["ev"])
                    self.assertEqual(bot.last_model["version"], "gto5.0-alpha")
            self.assertEqual(bot.shadow_records, [])

    def test_vs_bet_all_opponents_legal(self):
        with patch.dict(os.environ, {"POKER_GTO5_SHADOW_PERCENT": "0"}):
            bot = HumanRangeGTO50Bot()
            action = bot.act(view(to_call=25, opponents=("P2","P3","P4")))
            self.assertIn(action.type, {"call", "fold"})
            self.assertIn("call", bot.last_model["ev"])
            self.assertEqual(bot.last_model["opponents_count"], 3)

    def test_shadow_100_does_not_override_player_action(self):
        def fake_reference_act(observer, v):
            observer.last_model = {
                "version": "gto4.1",
                "ev": {"check": 110.0, "bet": 135.0},
                "decision_inputs": {"joint_trials": 128},
            }
            return Action("bet", 55)
        from bots.gto_postflop_41 import JointRangeGTO41Bot
        with patch.dict(os.environ, {"POKER_GTO5_SHADOW_PERCENT": "100"}):
            bot = HumanRangeGTO50Bot()
            with patch.object(JointRangeGTO41Bot, "act", fake_reference_act):
                action = bot.act(view())
            self.assertIn(action.type, {"check", "bet"})
            self.assertEqual(bot.shadow_checked, 1)
            self.assertEqual(len(bot.shadow_records), 1)
            event = bot.shadow_records[0]
            self.assertEqual(set(event["ev5"]), set(event["ev41"]))
            self.assertTrue(any(k.startswith("bet:") for k in event["ev5"]))
            self.assertEqual(aggregate_shadow([event])["compared"], 1)

    def test_special_board_is_not_misclassified(self):
        special = [("A","h"), ("A","s"), ("A","d"), ("A","c"), ("3","h")]
        info = board_distribution(special)
        self.assertEqual(info["formula_status"], "special_board")
        with patch.dict(os.environ, {"POKER_GTO5_SHADOW_PERCENT": "0"}):
            bot = HumanRangeGTO50Bot()
            action = bot.act(view("river", special))
            self.assertIn(action.type, {"check", "bet"})


if __name__ == "__main__":
    unittest.main()
