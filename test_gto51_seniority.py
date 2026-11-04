"""GTO 5.1/5.1.5 rank-seniority rules and Shadow A/B regression."""
import os
import unittest
from unittest.mock import patch

from bots import create_bot
from bots.gto_postflop_50 import (
    HumanRangeGTO50Bot, RoundedHumanRangeGTO505Bot,
    RankAwareGTO51Bot, RoundedRankAwareGTO515Bot,
    board_distribution, _hero_quantile_51,
)
from bots.hand_seniority_51 import hero_seniority
from gto5_shadow_report import aggregate_shadow
from test_gto_postflop_50 import view
import replit_simulator


def cards(text):
    return [tuple(c) for c in text.split()]


class GTO51SeniorityTests(unittest.TestCase):
    def test_catalog_and_old_versions_unchanged(self):
        catalog = replit_simulator.strategy_catalog()
        self.assertIn("gto_postflop_51_5", catalog["postflop_strategies"])
        self.assertIn("gto_postflop_515_5", catalog["postflop_strategies"])
        self.assertEqual(catalog["postflop_profiles"]["gto_postflop_51_5"]["model"],
                         "human_board_ev_rank_seniority_alpha")
        self.assertEqual(catalog["postflop_profiles"]["gto_postflop_515_5"]["model"],
                         "human_board_ev_rank_seniority_round5_alpha")
        for label, expected_kind, rounded, rank_aware in [
            ("gto_postflop_50_5", "gto50", 0, False),
            ("gto_postflop_505_5", "gto505", 5, False),
            ("gto_postflop_51_5", "gto51", 0, True),
            ("gto_postflop_515_5", "gto515", 5, True),
        ]:
            bot = create_bot("split:random:" + label).postflop_bot
            self.assertEqual((bot.actor_kind, bot.round_step, bot.rank_aware),
                             (expected_kind, rounded, rank_aware))
            self.assertEqual(bot.profile, label)

    def test_top_pair_vs_low_pair_on_same_river(self):
        board = cards("Qh 8s 3d 2c 7h")
        top = cards("Ad Qs")
        low = cards("4c 4d")
        mass = board_distribution(board)["probability_mass"][1]
        stronger, desc_top = hero_seniority(top, board, mass)
        weaker, desc_low = hero_seniority(low, board, mass)
        self.assertEqual(desc_top["category"], 1)
        self.assertEqual(desc_low["category"], 1)
        self.assertGreater(stronger, weaker)
        self.assertGreater(stronger, .7)
        self.assertLess(weaker, .6)
        self.assertIn("PP", desc_top["method"])
        # Original GTO 5.0 did not distinguish these within-category ranks.
        state_top = view("river", board)
        state_top.hole_cards = top
        state_low = view("river", board)
        state_low.hole_cards = low
        d = board_distribution(board)
        q_top = _hero_quantile_51(state_top, d)[0]
        q_low = _hero_quantile_51(state_low, d)[0]
        self.assertGreater(q_top, q_low)

    def test_flush_rank_count_and_straight_routes(self):
        board = cards("9s 8s 3s 2s 5d")
        win, detail = hero_seniority(cards("Ts 4c"), board,
                                    board_distribution(board)["probability_mass"][5])
        self.assertEqual(detail["category"], 5)
        self.assertEqual((detail["danger"], detail["safe"], detail["tie"]), (4, 4, 0))
        self.assertAlmostEqual(win, .5)
        board = cards("Ac 2d 3h Ts Qc")
        win, detail = hero_seniority(cards("4c 5d"), board,
                                    board_distribution(board)["probability_mass"][4])
        self.assertEqual(detail["category"], 4)
        self.assertGreaterEqual(detail["danger"], 1)
        self.assertTrue(0 <= win <= 1)

    def test_shared_trips_and_shared_quads_have_kicker_rule(self):
        triple = cards("9c 9d 9h Ks 2c")
        low, _ = hero_seniority(cards("7d 4h"), triple, .7)
        high, _ = hero_seniority(cards("Ad Qh"), triple, .7)
        self.assertLess(low, high)
        quads = cards("7c 7d 7h 7s Kc")
        lo, desc = hero_seniority(cards("Qh 2d"), quads, 1.)
        hi, _ = hero_seniority(cards("Ah 2d"), quads, 1.)
        self.assertEqual(desc["category"], 7)
        self.assertGreater(hi, lo)

    def test_all_nine_categories_and_board_card_streets(self):
        cases = [
            ("Ac 9d 6h 3s 2c", "Kd Jh", 0),
            ("As 5d Th 7c Qs", "Tc 4d", 1),
            ("Kc Kd Qh 8s 3c", "Qc 2d", 2),
            ("9c 9d 9h Ks 2c", "7d 4h", 3),
            ("Ac 2d 3h Ts Qc", "4c 5d", 4),
            ("9s 8s 3s 2s 5d", "Ts 4c", 5),
            ("Kc Kd Kh 8s 8c", "Qd Jh", 6),
            ("7c 7d 7h 7s Kc", "Qh 2d", 7),
            ("5s 6s 7s 8s Kd", "4s 2d", 8),
        ]
        for board_string, hole_string, category in cases:
            with self.subTest(category=category):
                r, details = hero_seniority(cards(hole_string),
                                            cards(board_string), .5)
                self.assertEqual(details["category"], category)
                self.assertTrue(0 <= r <= 1)
                self.assertTrue(0 <= details["danger"] <= 13)
                self.assertTrue(0 <= details["safe"] <= 13)
                self.assertTrue(0 <= details["tie"] <= 13)
        for board in ("Qh 8s 3d", "Qh Qs 3d 2c", "Qh Qs 3d 3c 7h",
                      "Qh Qs Qc 3d 7h"):
            d = board_distribution(cards(board))
            state = view({3: "flop", 4: "turn", 5: "river"}[len(board.split())],
                         cards(board))
            q, category, details = _hero_quantile_51(state, d)
            self.assertTrue(.01 <= q <= .99)
            self.assertIn("win_fraction", details)

    def test_no_enumeration_or_mc_when_shadow_off(self):
        from bots import gto_postflop_41
        with patch.dict(os.environ, {"POKER_GTO5_SHADOW_PERCENT": "0"}):
            for actor in (RankAwareGTO51Bot(), RoundedRankAwareGTO515Bot()):
                with patch.object(gto_postflop_41, "_range_profile",
                                  side_effect=AssertionError("NO MC/enumeration")):
                    for street, board in [
                        ("flop", cards("Qh 8s 3d")),
                        ("turn", cards("Qh 8s 3d 2c")),
                        ("river", cards("Qh 8s 3d 2c 7h")),
                    ]:
                        a = actor.act(view(street, board))
                        self.assertIn(a.type, {"check", "bet"})
                        self.assertIn("seniority", actor.last_model["decision_inputs"])
                self.assertEqual(actor.shadow_records, [])

    def test_unrounded_and_rounded_share_exact_seniority_rules(self):
        board = cards("Qh 8s 3d 2c 7h")
        state = view("river", board)
        direct = board_distribution(board)
        rounded = board_distribution(board, round_to_five=True)
        self.assertEqual(direct["unrounded_probability_mass"],
                         rounded["unrounded_probability_mass"])
        self.assertNotEqual(direct["probability_mass"],
                            rounded["probability_mass"])
        # SENIORITY is not rounded: both use the same x/P_pair weight.
        q, cat, unrounded_rule = _hero_quantile_51(state, direct)
        q5, cat5, rounded_rule = _hero_quantile_51(state, rounded)
        self.assertEqual(cat, cat5)
        self.assertEqual(unrounded_rule, rounded_rule)
        self.assertNotEqual(q, q5)
        for x in rounded["categories_pct"].values():
            self.assertEqual(x % 5, 0)

    def test_shadow_51_vs_50_and_515_vs_51_not_recursive(self):
        for actor_cls, ref, actor_kind, expected in [
            (RankAwareGTO51Bot, "gto50", "gto51", "gto50"),
            (RoundedRankAwareGTO515Bot, "gto51", "gto515", "gto51"),
            (RankAwareGTO51Bot, "gto515", "gto51", "gto515"),
        ]:
            with self.subTest(actor=actor_kind, ref=ref):
                with patch.dict(os.environ, {"POKER_GTO5_SHADOW_PERCENT": "100",
                                             "POKER_GTO5_SHADOW_REFERENCE": ref}):
                    base = actor_cls(shadow_percent=0)
                    live = actor_cls()
                    state = view("river", cards("Qh 8s 3d 2c 7h"))
                    expected_action = base.act(state)
                    observed = live.act(state)
                    self.assertEqual((expected_action.type, expected_action.amount),
                                     (observed.type, observed.amount))
                    self.assertEqual(live.shadow_checked, 1)
                    event = live.shadow_records[0]
                    self.assertEqual(event["actor"], actor_kind)
                    self.assertEqual(event["reference_model"], expected)
                    self.assertEqual(live.shadow_reference.shadow_percent, 0)
                    report = aggregate_shadow([event])
                    self.assertEqual(report["compared"], 1)
                    self.assertEqual(len(report["comparisons"]), 1)
        with patch.dict(os.environ, {"POKER_GTO5_SHADOW_PERCENT": "100",
                                     "POKER_GTO5_SHADOW_REFERENCE": "gto51"}):
            same = RankAwareGTO51Bot()
            same.act(view())
            self.assertEqual(same.shadow_records, [])

    def test_p4_ph_fallback_is_not_silently_overridden(self):
        boards = [cards("7c 7d 7h 7s Kc"), cards("Kc Kd Kh 8s 8c")]
        for cls in (RankAwareGTO51Bot, RoundedRankAwareGTO515Bot):
            for board in boards:
                state = view("river", board)
                bot = cls(shadow_percent=0)
                action = bot.act(state)
                self.assertIn(action.type, {"check", "bet"})
                self.assertEqual(bot.last_model["distribution"]["formula_status"],
                                 "special_board")
                self.assertEqual(bot.last_model["decision_inputs"],
                                 {"special_board": True})


if __name__ == "__main__":
    unittest.main()
