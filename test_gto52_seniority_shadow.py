"""GTO 5.2 seniority ablation + Shadow-to-hand forensic contract."""
import json
import tempfile
import unittest
from pathlib import Path

from bots import create_bot
from bots.gto_postflop_50 import (
    RankAwareGTO51Bot, RankAwareGTO52Bot, _hero_quantile_51, board_distribution,
)
from bots.hand_seniority_51 import hero_seniority, hero_seniority_52
from gto5_shadow_report import aggregate_shadow
from gto5_shadow_detail import enrich_legacy_report, get_shadow_hand
from gto_trace_exact_audit import exact_current_hand_audit
from test_gto_postflop_50 import view


def cards(s):
    return [tuple(t) for t in s.split()]


class GTO52Tests(unittest.TestCase):
    def test_registration_and_a_b(self):
        a = create_bot("gto_postflop_51_5")
        b = create_bot("gto_postflop_52_5")
        self.assertIsInstance(a, RankAwareGTO51Bot)
        self.assertIsInstance(b, RankAwareGTO52Bot)
        self.assertEqual(a.actor_kind, "gto51")
        self.assertEqual(b.actor_kind, "gto52")
        self.assertEqual(a.seniority_version, 51)
        self.assertEqual(b.seniority_version, 52)

    def test_high_card_square_without_touching_51(self):
        h = cards("5s 9d")
        b = cards("Ad Jd Tc 6c 7c")
        old, _ = hero_seniority(h, b)
        updated, details = hero_seniority_52(h, b)
        self.assertAlmostEqual(updated, old**2, places=10)
        self.assertGreater(old, updated)
        self.assertIn("r51 squared", details["method"])
        self.assertAlmostEqual(hero_seniority(h, b)[0], old)

    def test_pair_p0_matches_25_exact_with_ties(self):
        b, h = cards("Ts Js Ad"), cards("5c Ah")
        dist = board_distribution(b)
        baseline = hero_seniority(h, b, dist["unrounded_probability_mass"][1])[0]
        new, rule = hero_seniority_52(h, b, dist["unrounded_probability_mass"][1])
        exact = exact_current_hand_audit({
            "street": "flop", "board": ["Ts", "Js", "Ad"],
            "hero_hole": ["5c", "Ah"],
        })
        self.assertAlmostEqual(baseline, .9354, delta=.002)
        self.assertAlmostEqual(new, (315+3)/369, places=9)
        self.assertAlmostEqual(new, exact["exact_win_fraction"], delta=.0001)
        self.assertEqual(rule["tie"], 6)
        self.assertEqual(rule["route_weight"], 369)

    def test_non_p0_pair_keeps_51(self):
        h, b = cards("As 5h"), cards("6s 9s 9c Ad")
        self.assertAlmostEqual(hero_seniority(h, b)[0], hero_seniority_52(h, b)[0])

    def test_quantile_route_and_shadow_complete_hand(self):
        bot = RankAwareGTO52Bot(shadow_percent=100, shadow_reference="gto51")
        flop = view("flop", cards("Ad Jd Tc"), opponents=("P2",))
        flop.hole_cards = cards("5s 9d")
        flop.hand_id = 21
        turn = view("turn", cards("Ad Jd Tc 6c"), opponents=("P2",))
        turn.hole_cards = cards("5s 9d")
        turn.hand_id = 21
        bot.act(flop)
        self.assertTrue(bot.shadow_records)
        first = bot.shadow_records[0]
        self.assertEqual(first["actor"], "gto52")
        self.assertEqual(len(first["hand_steps"]), 1)
        bot.act(turn)
        self.assertEqual(len(first["hand_steps"]), 2)
        self.assertEqual([x["street"] for x in first["hand_steps"]], ["flop","turn"])
        self.assertEqual(first["hole"], ["5s","9d"])
        self.assertEqual(first["decision_step_index"], 0)
        self.assertEqual(first["hand_steps"][0]["hero_hole"], ["5s","9d"])
        d = board_distribution(flop.board)
        q51 = _hero_quantile_51(flop, d)[0]
        q52 = _hero_quantile_51(flop, d, 52)[0]
        self.assertNotEqual(q51, q52)

    def test_shadow_jsonl_source_id_historical_and_exact(self):
        b,h = cards("Ts Js Ad"), cards("5c Ah")
        mass = board_distribution(b)
        rec = {
            "tournament": 152, "hand_id": 55, "bot": "Hero",
            "street": "flop", "opponents": 8,
            "hole": ["5c","Ah"], "board": ["Ts","Js","Ad"],
            "bb": 2, "actor": "gto51", "reference_model": "gto41",
            "chosen5": "bet:9", "ev5": {"check": 12.0, "bet:9": 15.0},
            "ev41": {"check": 14.0, "bet:9": 13.0},
            "model": mass,
        }
        report = aggregate_shadow([rec])
        row = report["rankings"]["worst_decisions"][0]
        self.assertEqual(row["hole"], ["5c","Ah"])
        self.assertEqual(row["shadow_id"], 0)
        self.assertEqual(row["regret_bb"], .5)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"gto5_shadow_decisions.jsonl"
            path.write_text(json.dumps(rec)+"\n", encoding="utf-8")
            legacy = aggregate_shadow([rec])
            for scope in [legacy]+legacy["comparisons"]:
                row = scope["rankings"]["worst_decisions"][0]
                row.pop("shadow_id", None)
                row.pop("hole", None)
            enrich_legacy_report(legacy, path)
            self.assertEqual(legacy["rankings"]["worst_decisions"][0]["shadow_id"], 0)
            detail = get_shadow_hand(path,0,exact=True)
            self.assertEqual(detail["trace_source"], "shadow_samples_only")
            self.assertEqual(detail["hole"], ["5c","Ah"])
            self.assertEqual(detail["exact_audit"]["same_category_tied"], 6)
            self.assertAlmostEqual(detail["exact_audit"]["exact_win_fraction"], .861789, places=5)
            with self.assertRaises(IndexError):
                get_shadow_hand(path, 1)


if __name__ == "__main__":
    unittest.main()
