"""Real deal regression tests for postflop EV planner V1."""
import unittest
from unittest.mock import patch

import planner_core as core
import planner_postflop_ev as post
import planner_equity as eq
import replit_simulator as app


def setup(profile="tag",hero="gto",hand="AQs",entry="always",trials=50):
    return {
        "model":"selected","hand":hand,"trials":trials,"cycles":1,
        "hero_postflop":hero,"hero_position":"3","hero_stack_bb":20,
        "opponents":[{"profile":"builtin:any_two","position":"9","scenario":"rfi",
                      "players":9,"selector":"active","entry_mode":entry,
                      "entry_pct":100,"postflop":profile}]
    }


class PostflopEVTests(unittest.TestCase):
    def test_profile_validation_and_disabled_ev(self):
        with self.assertRaises(ValueError):
            post.validate_request(setup(profile="injected_python"))
        with self.assertRaises(ValueError):
            post.validate_request(setup(hero="injected_python"))
        raw=setup(profile="none")
        with patch("planner_postflop_ev._play_case",side_effect=AssertionError("behavioral EV must be off")):
            result=post.calculate(raw)
        self.assertFalse(result["behavioral_ev_enabled"])
        self.assertIsNone(result["ev_bb"]["AQs"])
        self.assertIsInstance(result["equity"]["AQs"],float)

    def test_actual_poker_engine_deal_with_all_five_profiles(self):
        rng=__import__("random").Random(19)
        hero=eq.HAND_COMBOS["AQs"][0]
        ranges,_=eq.build_ranges(setup()["opponents"],"selected")
        selected=None
        for i in range(100):
            picked,board=post._draw_case("AQs",ranges,setup()["opponents"],rng)
            if len(picked)==2:
                selected=(picked,board)
                break
        self.assertIsNotNone(selected)
        picked,board=selected
        self.assertEqual(len(set((*picked[0][1],*picked[1][1],*board))),9)
        for profile in ("gto","tag","lag","chaser","trapper","random"):
            picked[1]=(picked[1][0],picked[1][1],{**picked[1][2],"postflop":profile})
            amount,show=post._play_case(picked,board,"gto","3",20,100+len(profile))
            self.assertTrue(-20 <= amount <= 20)
            self.assertIsInstance(show,bool)

    def test_replay_ev_converges_to_legal_chip_range_and_equity(self):
        out=post.calculate(setup(hand="AA",trials=50))
        self.assertGreater(out["equity"]["AA"],30)
        self.assertIsNotNone(out["ev_bb"]["AA"])
        self.assertGreaterEqual(out["fold_win_pct"]["AA"],0)
        self.assertLessEqual(out["showdown_pct"]["AA"],100)
        self.assertEqual(out["simulations_per_hand"],50)
        self.assertAlmostEqual(sum(out["entry_counts_pct"]),100.,delta=.1)

    def test_screen_2_profile_selector_single_matrix_and_vertical_sliders(self):
        page=app.PLAN_UI.read_text(encoding="utf-8")
        self.assertIn('id="heroPostflop"',page)
        self.assertIn('id="handShowdown"',page)
        self.assertIn('EV розыгрыша · BB',page)
        self.assertIn("postflop.onchange=()=>",page)
        self.assertIn("const showIntersection=false;",page)
        self.assertNotIn('<details id="villainPane"',page)
        self.assertIn("background:#2179c5!important;",page)
        self.assertIn("background:var(--group-color,#8494a6)!important",page)
        self.assertIn(".editorSection .actionGrid{display:flex!important;flex-direction:column!important;",page)
        self.assertIn("['Соперник / линия','Equity','EV BB','Вскрытие']",page)
        self.assertIn("post('/api/plan/postflop',settings)",page)


if __name__=="__main__":
    unittest.main()
