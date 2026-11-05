"""GTO 5.4 controlled A/B: fixed-step accumulated RAISE/RERAISE widths."""
import unittest

from bots import create_bot
from bots.gto_postflop_50 import RankAwareGTO54Bot
from test_gto_postflop_50 import view


class GTO54StepWidthTests(unittest.TestCase):
    def test_three_profiles_and_control_are_independent(self):
        for step, bounds in ((10, (.10, .90)), (15, (.05, .95)),
                             (20, (.10, .90))):
            with self.subTest(step=step):
                b = create_bot("gto_postflop_54_step" + str(step))
                self.assertEqual(b.actor_kind, "gto54_" + str(step))
                self.assertEqual(b.profile, "gto_postflop_54_step" + str(step))
                self.assertEqual(b.range_step_pct, step)
                self.assertTrue(b.tie_aware)
                self.assertEqual(b.seniority_version, 53)
                self.assertEqual(b.round_step, 0)
                self.assertEqual(b.STEP_LIMITS[step], bounds)
                self.assertEqual(b._street_matrix_54("P2")["flop"]["vs_bet"]["raise"]["p"], .50)
                b.shadow_reference_kind = "gto531"
                self.assertEqual(b._new_reference().actor_kind, "gto531")
                b.shadow_reference_kind = "gto54_15"
                self.assertEqual(b._new_reference().actor_kind, "gto54_15")
        control = create_bot("gto_postflop_531_5")
        self.assertEqual(control.actor_kind, "gto531")
        self.assertFalse(hasattr(control, "range_step_pct"))

    def test_direct_accumulation_10_15_20_and_bounds(self):
        for step, limit in ((10, (.10, .90)), (15, (.05, .95)),
                            (20, (.10, .90))):
            with self.subTest(step=step):
                b = RankAwareGTO54Bot(step_pct=step, shadow_percent=0)
                key = ("P2", "river", "vs_bet")
                self.assertEqual(b._range_widths.get(key, .50), .50)
                b._append("P2", "river", "vs_bet", "raise")
                self.assertAlmostEqual(b._range_widths[key], .50 + step/100)
                b._append("P2", "river", "vs_bet", "raise")
                self.assertAlmostEqual(b._range_widths[key],
                                       min(limit[1], .50 + 2*step/100))
                b._append("P2", "river", "vs_bet", "call")
                self.assertAlmostEqual(b._range_widths[key],
                                       min(limit[1], .50 + 2*step/100)-step/100)
                for _ in range(30):
                    b._append("P2", "river", "vs_bet", "raise")
                self.assertEqual(b._range_widths[key], limit[1])
                for _ in range(30):
                    b._append("P2", "river", "vs_bet", "fold")
                self.assertEqual(b._range_widths[key], limit[0])
                b.reset_memory()
                self.assertEqual(b._range_widths.get(key, .50), .50)

    def test_separate_street_and_reraise_and_probability_conservation(self):
        b = RankAwareGTO54Bot(step_pct=15, shadow_percent=0)
        b._append("P2", "river", "vs_bet", "raise")
        b._append("P2", "river", "vs_bet", "raise")
        b._append("P2", "river", "vs_raise", "reraise")
        m = b._street_matrix_54("P2")
        self.assertEqual(m["river"]["vs_bet"]["raise"]["p"], .8)
        self.assertEqual(m["river"]["vs_raise"]["reraise"]["p"], .65)
        self.assertEqual(m["turn"]["vs_bet"]["raise"]["p"], .5)
        self.assertEqual(b._street_matrix_54("P3")["river"]["vs_bet"]["raise"]["p"], .5)
        for street in ("flop", "turn", "river"):
            for group, action in (("vs_bet", "raise"), ("vs_raise", "reraise")):
                values = m[street][group]
                self.assertAlmostEqual(
                    sum(values[k]["p"] for k in ("fold", "call", action)), 1.,
                    places=5)
                self.assertEqual(values[action]["source"], "step_54_accumulated")
        self.assertEqual(b._range_widths[("P2", "river", "vs_bet")], .8)

    @staticmethod
    def _event(pid, action, street="river", facing=0):
        return {
            "pid": pid, "type": action, "street": street,
            "to_call_before": facing,
            "legal_types": ["fold", "call", "raise"] if facing else
                           ["check", "bet"],
        }

    def test_replayed_public_history_is_deduplicated_and_action_band_updates(self):
        b = RankAwareGTO54Bot(step_pct=10, shadow_percent=0)
        hist = [self._event("P1", "bet"), self._event("P2", "raise", facing=20)]
        b.observe_hand(71, hist, [], "P1")
        self.assertEqual(b._range_widths[("P2", "river", "vs_bet")], .6)
        b.observe_hand(71, hist, [], "P1")
        self.assertEqual(b._range_widths[("P2", "river", "vs_bet")], .6)
        v = view("river", [("Q", "h"), ("8", "s"), ("3", "d"),
                           ("2", "c"), ("9", "h")], to_call=20, opponents=("P2",))
        v.hand_id = 71
        v.history = hist
        b.act(v)
        self.assertEqual(b.last_model["version"], "gto5.4-step10-alpha")
        self.assertAlmostEqual(b.last_model["decision_inputs"]["band"]["P2"][0], .4)
        self.assertAlmostEqual(b.last_model["decision_inputs"]["band"]["P2"][1], 1.)
        self.assertEqual(b._range_widths[("P2", "river", "vs_bet")], .6)
        # A new legal chance in the following hand without a raise shrinks width.
        b.observe_hand(72, [self._event("P1", "bet"),
                            self._event("P2", "call", facing=20)], [], "P1")
        self.assertEqual(b._range_widths[("P2", "river", "vs_bet")], .5)

    def test_re_raise_uses_own_band_not_ordinary_raise_frequency(self):
        b = RankAwareGTO54Bot(step_pct=20, shadow_percent=0)
        hist = [self._event("P1", "bet"),
                self._event("P3", "raise", facing=20),
                self._event("P2", "raise", facing=45)]
        b.observe_hand(73, hist, [], "P1")
        self.assertEqual(b._range_widths[("P2", "river", "vs_raise")], .7)
        self.assertNotIn(("P2", "river", "vs_bet"), b._range_widths)
        groups = {"P2": b._street_matrix_54("P2")}
        low, high = b._band_54("P2", "river", hist, groups)
        self.assertAlmostEqual(low, .30)
        self.assertAlmostEqual(high, 1.)
        self.assertAlmostEqual(groups["P2"]["river"]["vs_bet"]["raise"]["p"], .5)

    def test_only_fully_legal_opp_choices_update_state(self):
        b = RankAwareGTO54Bot(step_pct=10, shadow_percent=0)
        hist = [self._event("P1", "bet"),
                {"pid": "P2", "type": "call", "street": "river",
                 "to_call_before": 20, "legal_types": ["fold", "call"]}]
        b.observe_hand(74, hist, [], "P1")
        self.assertEqual(b._range_widths, {})

    def test_factory_and_web_catalog(self):
        import replit_simulator as app
        cat = app.strategy_catalog()
        for step in (10, 15, 20):
            code = "gto_postflop_54_step" + str(step)
            if step == 15:
                self.assertIn(code, cat["postflop_strategies"])
            else:
                self.assertIn(code, cat["postflop_archived"])
                self.assertNotIn(code, cat["postflop_strategies"])
            self.assertIn(code, cat["postflop_profiles"])
            self.assertEqual(create_bot("split:random:" + code).postflop_bot.profile, code)


if __name__ == "__main__":
    unittest.main()
