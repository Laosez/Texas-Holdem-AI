"""GTO 5.4.1/15%: exactly identical actions/EV to GTO 5.4/15%."""
import unittest

from bots import create_bot
from bots.gto_postflop_50 import RankAwareGTO54Bot
from bots.gto_postflop_541 import (
    RankAwareGTO541Bot, _board_distribution_541, _hero_seniority_541)
from test_gto_postflop_50 import view


def event(pid, action, street, to_call=0):
    return {"pid": pid, "type": action, "street": street,
            "to_call_before": to_call,
            "legal_types": (["fold", "call", "raise"] if to_call
                            else ["check", "bet"])}


class GTO541OptimizationTests(unittest.TestCase):
    def setUp(self):
        _board_distribution_541.cache_clear()
        _hero_seniority_541.cache_clear()

    def test_profile_only_15pp_and_baselines_unchanged(self):
        cached = create_bot("gto_postflop_541_step15")
        self.assertIsInstance(cached, RankAwareGTO541Bot)
        self.assertEqual(cached.actor_kind, "gto541")
        self.assertEqual(cached.profile, "gto_postflop_541_step15")
        self.assertEqual(cached.range_step_pct, 15)
        self.assertTrue(cached.tie_aware)
        self.assertEqual(cached.seniority_version, 53)
        for step in (10, 15, 20):
            baseline = create_bot("gto_postflop_54_step" + str(step))
            self.assertEqual(baseline.actor_kind, "gto54_" + str(step))
            self.assertFalse(hasattr(baseline, "_distribution_541"))
            self.assertFalse(hasattr(baseline, "_context_cache_541"))
        self.assertEqual(cached._new_reference().actor_kind, "gto41")
        cached.shadow_reference_kind = "gto54_15"
        self.assertEqual(cached._new_reference().actor_kind, "gto54_15")
        reference = create_bot("gto_postflop_54_step15")
        reference.shadow_reference_kind = "gto541"
        self.assertEqual(reference._new_reference().actor_kind, "gto541")

    def test_equivalence_on_streets_board_types_and_opponent_raises(self):
        original = RankAwareGTO54Bot(step_pct=15, shadow_percent=0)
        optimized = RankAwareGTO541Bot(shadow_percent=0)
        cases = [
            ("flop", [("Q","h"),("8","s"),("3","d")],
             [("A","s"),("Q","s")], 0, []),
            ("flop", [("Q","h"),("Q","s"),("3","d")],
             [("A","c"),("3","c")], 0,
             [event("P2", "check", "flop")]),
            ("turn", [("6","c"),("7","d"),("5","h"),("4","h")],
             [("8","d"),("8","h")], 18,
             [event("P2","bet","turn"),event("P3","raise","turn",18)]),
            ("turn", [("K","s"),("9","c"),("T","s"),("Q","c")],
             [("2","h"),("J","h")], 24,
             [event("P2","bet","turn"),event("P3","call","turn",20)]),
            ("river", [("5","h"),("3","h"),("6","h"),("T","h"),("6","c")],
             [("2","h"),("A","h")], 28,
             [event("P2","bet","river"),event("P3","raise","river",20)]),
            ("river", [("3","h"),("5","c"),("2","s"),("9","c"),("7","c")],
             [("5","d"),("2","d")], 0, []),
            ("river", [("A","s"),("T","s"),("5","s"),("2","s"),("A","c")],
             [("K","s"),("Q","d")], 0,
             [event("P3","check","river")]),
            ("river", [("J","d"),("J","s"),("9","c"),("T","d"),("4","d")],
             [("J","c"),("K","s")], 0, []),
        ]
        for idx, (street, board, hole, to_call, history) in enumerate(cases):
            with self.subTest(street=street, board=board):
                v = view(street, board, to_call=to_call,
                         opponents=("P2", "P3", "P4"))
                v.hole_cards = hole
                v.hand_id = 600 + idx
                v.history = history
                a = original.act(v)
                b = optimized.act(v)
                self.assertEqual((a.type, a.amount), (b.type, b.amount))
                self.assertEqual(original.last_model["ev"], optimized.last_model["ev"])
                self.assertEqual(original.last_model["distribution"],
                                 optimized.last_model["distribution"])
                self.assertEqual(original.last_model["decision_inputs"],
                                 optimized.last_model["decision_inputs"])
                self.assertEqual(original.last_model["opponents_count"],
                                 optimized.last_model["opponents_count"])
                self.assertEqual(original.last_model["board_classifier"],
                                 optimized.last_model["board_classifier"])
                self.assertEqual(original._range_widths, optimized._range_widths)
                self.assertEqual(optimized.last_model["version"],
                                 "gto5.4.1-step15-cached-alpha")

    def test_identical_ev_when_board_and_hero_repeat(self):
        original = RankAwareGTO54Bot(step_pct=15, shadow_percent=0)
        optimized = RankAwareGTO541Bot(shadow_percent=0)
        for i in range(4):
            v = view("river",
                     [("A","s"),("T","s"),("5","s"),("2","s"),("A","c")],
                     to_call=30, opponents=("P2","P3"))
            v.hole_cards = [("K","s"),("Q","d")]
            v.hand_id = 700+i
            v.history = ([event("P2","bet","river"),
                          event("P3","raise","river",20)] if i%2==0 else
                         [event("P2","bet","river"),
                          event("P3","call","river",20)])
            x, y = original.act(v), optimized.act(v)
            self.assertEqual((x.type, x.amount), (y.type, y.amount))
            self.assertEqual(original.last_model["ev"], optimized.last_model["ev"])
            self.assertEqual(original.last_model["decision_inputs"],
                             optimized.last_model["decision_inputs"])
            self.assertEqual(original._range_widths, optimized._range_widths)
        self.assertGreater(_board_distribution_541.cache_info().hits, 0)
        self.assertGreater(_hero_seniority_541.cache_info().hits, 0)

    def test_cached_objects_do_not_leak_mutations(self):
        b = RankAwareGTO541Bot(shadow_percent=0)
        board = [("K","h"),("7","s"),("2","c")]
        hole = [("K","c"),("A","d")]
        a = b._distribution_541(board)
        raw = b._distribution_541(board)
        self.assertEqual(a, raw)
        a["probability_mass"][0] = 666
        a["categories_pct"]["pair"] = 123
        a["structure"]["P"] = "BAD"
        self.assertEqual(b._distribution_541(board), raw)
        _, seniority1 = b._seniority_541(hole, board)
        original_rule = seniority1.copy()
        seniority1["safe"] = -100
        self.assertEqual(b._seniority_541(hole, board)[1], original_rule)
        self.assertEqual(_board_distribution_541.cache_info().maxsize, 2048)
        self.assertEqual(_hero_seniority_541.cache_info().maxsize, 4096)

    def test_context_cache_invalidates_on_any_street_and_reset(self):
        b = RankAwareGTO541Bot(shadow_percent=0)
        baseline = RankAwareGTO54Bot(step_pct=15, shadow_percent=0)
        for bot in (b, baseline):
            bot._append("P2", "flop", "vs_bet", "raise")
            bot._append("P2", "turn", "vs_bet", "call")
        before = b._context("P2", "river", "vs_bet")
        self.assertEqual(before, baseline._context("P2", "river", "vs_bet"))
        self.assertIn(("P2", "river", "vs_bet"), b._context_cache_541)
        before["call"]["p"] = -10
        self.assertEqual(b._context("P2", "river", "vs_bet"),
                         baseline._context("P2", "river", "vs_bet"))
        b._append("P2", "flop", "vs_bet", "call")
        baseline._append("P2", "flop", "vs_bet", "call")
        self.assertNotIn(("P2", "river", "vs_bet"), b._context_cache_541)
        self.assertEqual(b._context("P2", "river", "vs_bet"),
                         baseline._context("P2", "river", "vs_bet"))
        b._street_matrix_54("P2")
        b.reset_memory()
        self.assertEqual(b._context_cache_541, {})
        self.assertEqual(b._range_widths, {})

    def test_registration_and_ui_metadata(self):
        import replit_simulator
        names = replit_simulator.strategy_catalog()["postflop_strategies"]
        self.assertIn("gto_postflop_541_step15", names)
        meta = replit_simulator.strategy_catalog()["postflop_profiles"]
        self.assertEqual(meta["gto_postflop_541_step15"]["model"],
                         "human_tie_aware_541_step15_memoized")


if __name__ == "__main__":
    unittest.main()
