"""GTO 5.3.1: only tie-aware conditioning of action-band equity."""
import unittest

from bots import create_bot
from bots.gto_postflop_50 import (
    _equity_in_band, _hero_quantile_51, board_distribution,
)
from test_gto_postflop_50 import view


def cards(value):
    return [tuple(card) for card in value.split()]


class GTO531TieBandTests(unittest.TestCase):
    def test_registration_keeps_53_as_control(self):
        baseline = create_bot("gto_postflop_53_5")
        updated = create_bot("gto_postflop_531_5")
        self.assertEqual(baseline.actor_kind, "gto53")
        self.assertEqual(updated.actor_kind, "gto531")
        self.assertFalse(getattr(baseline, "tie_aware", False))
        self.assertTrue(updated.tie_aware)
        self.assertEqual(updated.seniority_version, 53)
        self.assertEqual(updated.round_step, 0)
        self.assertEqual(updated.profile, "gto_postflop_531_5")
        baseline.shadow_reference_kind = "gto531"
        self.assertEqual(baseline._new_reference().actor_kind, "gto531")
        updated.shadow_reference_kind = "gto53"
        self.assertEqual(updated._new_reference().actor_kind, "gto53")

    def test_overlap_is_exact_and_unchanged_without_ties(self):
        q = .60
        tie_band = (.40, .80)
        self.assertAlmostEqual(_equity_in_band(q, 0, 1, tie_band), .60)
        self.assertAlmostEqual(_equity_in_band(q, .40, .80, tie_band), .50)
        self.assertAlmostEqual(_equity_in_band(q, .70, 1.0, tie_band), 1/6)
        self.assertAlmostEqual(_equity_in_band(q, .70, 1.0), .01)
        self.assertAlmostEqual(_equity_in_band(.75, .50, .95, None),
                               _equity_in_band(.75, .50, .95))
        self.assertAlmostEqual(_equity_in_band(.75, .50, .95, (.75, .75)),
                               _equity_in_band(.75, .50, .95))

    def test_expensive_straight_cases_preserve_seniority_and_add_ties(self):
        examples = (
            ("turn", "6c 7d 5h 4h", "8d 8h"),
            ("turn", "Ks 9c Ts Qc", "2h Jh"),
        )
        for street, board, hole in examples:
            with self.subTest(board=board):
                v = view(street, cards(board), to_call=40, opponents=("P2",))
                v.hole_cards = cards(hole)
                dist = board_distribution(v.board)
                q_old, cat_old, rule_old = _hero_quantile_51(v, dist, 53)
                q_new, cat_new, rule = _hero_quantile_51(
                    v, dist, 53, tie_aware=True)
                self.assertEqual(cat_old, cat_new)
                self.assertAlmostEqual(q_old, q_new, places=12)
                self.assertEqual(rule["safe"], rule_old["safe"])
                self.assertEqual(rule["tie"], rule_old["tie"])
                self.assertEqual(rule["danger"], rule_old["danger"])
                self.assertGreater(rule["tie"], 0)
                low, high = rule["tie_quantile_band"]
                self.assertLess(low, high)
                self.assertAlmostEqual(
                    high - low,
                    dist["probability_mass"][cat_new] * rule["tie"] / rule["route_weight"],
                    places=12)
                self.assertAlmostEqual(_equity_in_band(q_new, low, high, (low, high)), .5)

    def test_problem_hand_03_top_raise_band_includes_ties(self):
        v = view("turn", cards("6c 7d 5h 4h"), to_call=100,
                 opponents=("P8", "P4", "P5"))
        v.hole_cards = cards("8d 8h")
        dist = board_distribution(v.board)
        old, _, _ = _hero_quantile_51(v, dist, 53)
        new, _, details = _hero_quantile_51(v, dist, 53, tie_aware=True)
        self.assertAlmostEqual(new, old)
        low, high = details["tie_quantile_band"]
        original = _equity_in_band(old, .9333, 1.0)
        adjusted = _equity_in_band(new, .9333, 1.0, (low, high))
        self.assertAlmostEqual(original, .087, delta=.015)
        self.assertGreater(adjusted, original + .05)

    def test_actual_actions_use_tie_interval_only_for_531(self):
        v = view("turn", cards("6c 7d 5h 4h"), to_call=30,
                 opponents=("P2",))
        v.hole_cards = cards("8d 8h")
        baseline = create_bot("gto_postflop_53_5")
        updated = create_bot("gto_postflop_531_5")
        baseline.act(v)
        updated.act(v)
        old = baseline.last_model
        new = updated.last_model
        self.assertNotIn("tie_quantile_band", old["decision_inputs"]["seniority"])
        self.assertIn("tie_quantile_band", new["decision_inputs"]["seniority"])
        self.assertEqual(old["distribution"], new["distribution"])
        self.assertEqual(old["decision_inputs"]["hero_quantile"],
                         new["decision_inputs"]["hero_quantile"])
        self.assertIn("call", new["ev"])
        self.assertEqual(new["version"], "gto5.3.1-tie-alpha")


if __name__ == "__main__":
    unittest.main()
