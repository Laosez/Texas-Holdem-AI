"""S100: exactly 100 real scenario IDs shared by teaching, policy and simulation."""
import random
import unittest
from unittest.mock import patch

from bots import create_bot
from bots.s100_postflop import (
    BY_KEY, CATALOG, SCENARIOS, S100PostflopBot, classify,
    inspect_request, probabilities, board_features,
)
from core.engine import Seat, Table
from test_postflop_profiles import make_view
import planner_postflop_ev as ev
import replit_simulator as app


class S100Tests(unittest.TestCase):
    def test_authoritative_catalog_has_one_hundred_unique_rows(self):
        self.assertEqual(CATALOG["format"], "SKACHKOV_S100_V1")
        self.assertEqual(len(SCENARIOS), len(BY_KEY))
        self.assertEqual(len(SCENARIOS), 100)
        self.assertEqual([s["id"] for s in SCENARIOS],
                         [f"S{i:03d}" for i in range(1, 101)])
        for f in set(row["family"] for row in SCENARIOS):
            rows = [r for r in SCENARIOS if r["family"] == f]
            self.assertEqual(len(rows), 10)
            self.assertEqual(len(set(r["variant"] for r in rows)), 5)
            for row in rows:
                self.assertIn(row["table_mode"], ("hu", "multi"))
                self.assertGreaterEqual(row["policy"]["call_odds_max"], 0)
                self.assertLessEqual(row["policy"]["raise_frequency"], 1)

    def test_aq_t6_are_three_different_states(self):
        aq = [("A", "s"), ("Q", "s")]
        t6 = [("T", "s"), ("6", "s")]
        strong = [("A", "d"), ("Q", "d"), ("7", "c"), ("7", "h")]
        shared = [("A", "d"), ("7", "c"), ("7", "h"), ("2", "d")]
        weak = [("K", "d"), ("7", "c"), ("7", "h"), ("T", "d")]
        self.assertEqual(classify(aq, strong)[0]["id"], "S061")
        self.assertEqual(classify(aq, shared)[0]["id"], "S055")
        self.assertEqual(classify(t6, weak)[0]["id"], "S059")
        self.assertEqual(classify(aq, strong, 3)[0]["id"], "S062")
        self.assertEqual(classify(aq, shared, 3)[0]["id"], "S056")
        self.assertEqual(classify(t6, weak, 3)[0]["id"], "S060")

    def test_other_hand_families_and_draws(self):
        checks = [
            ([("5", "s"), ("5", "h")], [("A", "c"), ("A", "h"), ("9", "d")], "shared_two_pair"),
            ([("K", "s"), ("2", "s")], [("K", "d"), ("7", "s"), ("4", "s")], "top_pair"),
            ([("T", "s"), ("T", "h")], [("T", "d"), ("7", "c"), ("2", "h")], "trips_set"),
            ([("A", "s"), ("Q", "s")], [("K", "h"), ("9", "d"), ("4", "c")], "air"),
            ([("A", "s"), ("Q", "s")], [("J", "s"), ("7", "s"), ("2", "d")], "draw"),
        ]
        for hole, board, family in checks:
            with self.subTest(family=family):
                row, data = classify(hole, board)
                self.assertEqual(row["family"], family)
                self.assertIn(data["board_texture"],
                              ("paired", "monotone", "connected", "two_tone", "dry"))

    def test_full_board_and_duplicate_validation(self):
        with self.assertRaisesRegex(ValueError, "повторяющиеся"):
            classify([("A", "s"), ("Q", "s")],
                     [("A", "s"), ("7", "d"), ("2", "h")])
        with self.assertRaisesRegex(ValueError, "3–5"):
            classify([("A", "s"), ("Q", "s")], [("A", "d"), ("7", "d")])
        self.assertEqual(board_features([("7", "c"), ("7", "h"), ("A", "d")])["texture"], "paired")
        self.assertEqual(board_features([("A", "s"), ("5", "s"), ("2", "s")])["texture"], "monotone")

    def test_same_actions_in_inspector_and_executable_policy(self):
        hero = [("A", "s"), ("Q", "s")]
        board = [("A", "d"), ("Q", "d"), ("7", "c"), ("7", "h")]
        api = inspect_request({"hole": ["As", "Qs"], "board": ["Ad", "Qd", "7c", "7h"],
                               "opponents": 1, "pot": 24, "to_call": 8, "stack": 80})
        real = probabilities(hero, board, 1, 24, 8, 80,
                             legal={"fold", "call", "raise"})
        self.assertEqual(api, real)
        self.assertEqual(sum(api["actions"].values()), 1.0)
        with patch("bots.s100_postflop.random.random", return_value=.99):
            action = S100PostflopBot().act(make_view(hole=hero, board=board,
                                                    street="turn", to_call=8, pot=24))
            self.assertEqual(action.type, "call")

    def test_bot_is_registered_for_both_interfaces_and_ev(self):
        self.assertEqual(create_bot("s100_postflop_v1").profile, "s100_postflop_v1")
        bot = create_bot("split:pc_gto_80bb:s100_postflop_v1")
        self.assertEqual(bot.postflop_bot.profile, "s100_postflop_v1")
        self.assertEqual(ev.PROFILE_NAMES["s100"], "s100_postflop_v1")
        catalog = app.strategy_catalog()
        self.assertIn("s100_postflop_v1", catalog["postflop_strategies"])
        self.assertNotIn("s100_postflop_v1", catalog["preflop_strategies"])
        self.assertEqual(len(catalog["postflop_strategies"]), 10)
        self.assertIn("S100", app.PLAN_UI.read_text(encoding="utf-8"))
        self.assertIn("s100_postflop_v1", app.UI.read_text(encoding="utf-8"))
        self.assertTrue((app.ROOT / "replit_ui/s100.html").is_file())

    def test_real_engine_and_postflop_monte_carlo_smoke(self):
        bots = {
            "P1": create_bot("split:pc_gto_80bb:s100_postflop_v1"),
            "P2": create_bot("split:pc_gto_80bb:gto_postflop_20"),
        }
        table = Table(rng=random.Random(535))
        changes = table.play_hand([Seat(pid, 160) for pid in bots],
                                  small_blind=1, big_blind=2,
                                  dealer_index=0, bot_for=bots)
        self.assertEqual(sum(changes.values()), 0)
        req = {"model": "selected", "hand": "AQs", "trials": 50, "cycles": 1,
               "hero_postflop": "s100", "hero_position": "3", "hero_stack_bb": 20,
               "opponents": [{"profile": "builtin:any_two", "position": "9",
                              "scenario": "rfi", "players": 9, "selector": "active",
                              "entry_mode": "always", "entry_pct": 100,
                              "postflop": "gto"}]}
        result = ev.calculate(req)
        self.assertIsInstance(result["ev_bb"]["AQs"], float)
        self.assertEqual(result["simulations_per_hand"], 50)


if __name__ == "__main__":
    unittest.main()
