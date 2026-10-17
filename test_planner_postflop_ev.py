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

    def test_9max_fixed_seats_keep_blinds_on_real_sb_bb(self):
        """Inactive blinds post, fold and cannot transfer obligations to UTG."""
        from core.engine import Table
        raw = setup(hero="gto3", hand="T6s")
        raw["hero_position"] = "9"
        active = dict(raw["opponents"][0], position="8", entry_mode="always")
        sb = dict(raw["opponents"][0], position="SB", entry_mode="never")
        bb = dict(raw["opponents"][0], position="BB", entry_mode="never")
        raw["opponents"] = [active, sb, bb]
        ranges, _ = eq.build_ranges(raw["opponents"], "selected")
        import random
        picked, board = post._draw_case("T6s", ranges, raw["opponents"], random.Random(14))
        self.assertEqual(len(picked), 2)
        capture = {}
        original = Table.play_hand

        def spy(table, seats, *args, **kwargs):
            capture["ring"] = [seat.player_id for seat in seats]
            capture["policies"] = kwargs["bot_for"]
            capture["on_deal"] = {}
            table.on_deal = lambda hand_id, holes, positions, n: capture["on_deal"].update(
                {"positions": dict(positions), "seats": n})
            original_end = table.on_hand_end

            def on_end(hand_id, net, bb_value, players, winners):
                capture["net"] = dict(net)
                return original_end(hand_id, net, bb_value, players, winners)

            table.on_hand_end = on_end
            return original(table, seats, *args, **kwargs)

        with patch.object(Table, "play_hand", spy):
            net, showdown, classified, pot = post._play_case(
                picked, board, "gto3", "9", 20, 77, detail=True, metrics=True)
        self.assertEqual(capture["ring"], [
            "FOLD_3", "FOLD_SB", "FOLD_BB", "HERO", "V1",
            "FOLD_7", "FOLD_6", "FOLD_5", "FOLD_4"])
        self.assertEqual(capture["on_deal"]["seats"], 9)
        self.assertEqual(capture["on_deal"]["positions"]["HERO"], "9")
        self.assertEqual(capture["on_deal"]["positions"]["FOLD_SB"], "SB")
        self.assertEqual(capture["on_deal"]["positions"]["FOLD_BB"], "BB")
        self.assertIsInstance(capture["policies"]["FOLD_SB"], post._InactivePolicy)
        self.assertIsInstance(capture["policies"]["FOLD_BB"], post._InactivePolicy)
        self.assertEqual(capture["net"]["FOLD_SB"], -1)  # chips: 0.5 BB
        self.assertEqual(capture["net"]["FOLD_BB"], -2)  # chips: 1.0 BB
        self.assertAlmostEqual(sum(capture["net"].values()), 0)
        self.assertAlmostEqual(net, capture["net"]["HERO"] / 2)
        self.assertGreaterEqual(pot, 1.5)

    def test_inactive_preflop_policy_checks_without_calling_and_folds_to_bet(self):
        from types import SimpleNamespace
        dead = post._InactivePolicy()
        self.assertEqual(dead.act(SimpleNamespace(to_call=2)).type, "fold")
        self.assertEqual(dead.act(SimpleNamespace(to_call=0)).type, "check")

    def test_paired_physical_deal_is_prepared_once_per_trial(self):
        import random
        raw=setup(hero="gto3",profile="tag",hand="T6s",trials=50)
        raw["hero_postflop_b"]="lag"
        with patch("planner_postflop_ev._physical_deal",
                   wraps=post._physical_deal) as prepared:
            result=post.calculate_parallel(raw,workers=1)
        self.assertEqual(prepared.call_count,50)
        self.assertEqual(result["comparison"]["samples"],50)
        self.assertAlmostEqual(
            result["comparison"]["delta_ev_bb"],
            result["b"]["ev_bb"]["T6s"]-result["a"]["ev_bb"]["T6s"],
            delta=.00011)
        ranges,_=eq.build_ranges(raw["opponents"],"selected")
        picked,board=post._draw_case("T6s",ranges,raw["opponents"],random.Random(42))
        fixed=post._physical_deal(picked,board,raw["hero_position"],2026)
        for strategy in ("gto3","lag"):
            params=(picked,board,strategy,raw["hero_position"],20,2026)
            self.assertEqual(
                post._play_case(*params,detail=True,metrics=True),
                post._play_case(*params,detail=True,metrics=True,prepared=fixed))

    def test_paired_multi_process_2000_cases(self):
        """Exercise spawn-based worker path, not just the 50-trial inline path."""
        raw=setup(hero="gto3",hand="AQs",entry="never",trials=2000)
        raw["hero_postflop_b"]="tag"
        report=post.calculate_parallel(raw,workers=2)
        self.assertEqual(report["comparison"]["samples"],2000)
        self.assertEqual(report["comparison"]["delta_ev_bb"],0)
        self.assertEqual(report["comparison"]["delta_ci95_bb"],0)
        self.assertEqual(report["a"]["entry_n_samples"][0],2000)
        self.assertEqual(report["b"]["entry_n_samples"][0],2000)
        self.assertEqual(report["a"]["ev_bb"]["AQs"],1.5)
        self.assertEqual(report["b"]["ev_bb"]["AQs"],1.5)

    def test_paired_disk_cache_survives_restart_and_corruption(self):
        import tempfile
        from pathlib import Path
        import planner_api as api
        class ImmediateExecutor:
            def submit(self,work):
                work()
        result={
            "model":"postflop_paired_v1",
            "a":{"equity":{"AQs":40.},"decomposition":{"samples":3000}},
            "b":{"equity":{"AQs":42.},"decomposition":{"samples":3000}},
            "comparison":{"method":"paired_common_deals_v1",
                          "samples":3000,"by_opponents":[]}
        }
        identity="a"*64
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(api,"CACHE_PATH",Path(folder)), \
             patch.object(api,"EQUITY_TASKS",{}):
            first=api._schedule(identity,lambda progress:result,3000,
                                executor=ImmediateExecutor())
            self.assertEqual(first["status"],"completed")
            api.EQUITY_TASKS.clear()  # simulate a new server instance
            cached=api._schedule(identity,
                 lambda progress: self.fail("Unexpected repeat Monte Carlo"),
                 3000,executor=ImmediateExecutor())
            self.assertEqual(cached["status"],"completed")
            self.assertTrue(cached["cached"])
            self.assertEqual(cached["done"],3000)
            self.assertEqual(cached["total"],3000)
            self.assertEqual(api.get_task(identity)["result"],result)
            bad="b"*64
            (Path(folder)/(bad+".json")).write_text("{corrupted",encoding="utf-8")
            self.assertIsNone(api._cached_task(bad))
            with self.assertRaises(KeyError):
                api.get_task(bad)
            basic="c"*64
            (Path(folder)/(basic+".json")).write_text(
                '{"equity":{"AQs":50.0},"simulations_per_hand":2500}',encoding="utf-8")
            self.assertEqual(api.get_task(basic)["done"],2500)

    def test_paired_same_policy_shares_deals_and_has_zero_delta(self):
        raw = setup(hero="gto3",profile="tag",hand="AQs",trials=50)
        raw["hero_postflop_b"] = "gto3"
        with patch("planner_postflop_ev._draw_case",wraps=post._draw_case) as draw:
            result = post.calculate_parallel(raw,workers=1)
        self.assertEqual(draw.call_count, 50)
        self.assertEqual(result["model"], "postflop_paired_v1")
        self.assertEqual(result["comparison"]["samples"], 50)
        self.assertEqual(result["comparison"]["delta_ev_bb"], 0)
        self.assertEqual(result["comparison"]["delta_ci95_bb"], 0)
        self.assertEqual(result["a"]["ev_bb"],result["b"]["ev_bb"])
        self.assertEqual(result["a"]["decomposition"],result["b"]["decomposition"])
        self.assertEqual(sum(x["samples"] for x in result["comparison"]["by_opponents"]),50)
        unpaired=post.calculate({k:v for k,v in raw.items()
                                 if k!="hero_postflop_b"})
        self.assertEqual(result["a"]["ev_bb"],unpaired["ev_bb"])
        self.assertEqual(result["a"]["equity"],unpaired["equity"])

    def test_paired_different_policies_delta_and_conditional_strata(self):
        raw = setup(hero="gto3",profile="tag",hand="T6s",trials=50)
        raw["hero_postflop_b"] = "tag"
        result = post.calculate_parallel(raw,workers=2)
        pair = result["comparison"]
        self.assertEqual(pair["method"],"paired_common_deals_v1")
        self.assertEqual(pair["samples"],50)
        self.assertAlmostEqual(pair["delta_ev_bb"],
            result["b"]["ev_bb"]["T6s"]-result["a"]["ev_bb"]["T6s"],
            places=3)
        self.assertGreaterEqual(pair["delta_ci95_bb"],0)
        weighted=sum((x["delta_ev_bb"] or 0)*x["samples"]
                     for x in pair["by_opponents"])/50
        self.assertAlmostEqual(weighted,pair["delta_ev_bb"],places=3)
        self.assertEqual(result["a"]["entry_n_samples"],
                         result["b"]["entry_n_samples"])
        self.assertEqual(result["a"]["equity"],result["b"]["equity"])

    def test_paired_request_rejects_invalid_shapes(self):
        raw=setup()
        raw["hero_postflop_b"]="gto3"
        raw["hand"]=None
        with self.assertRaises(ValueError):
            post.validate_request(raw)
        raw["hand"]="AQs"
        raw["hero_postflop_b"]="none"
        with self.assertRaises(ValueError):
            post.validate_request(raw)

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
        self.assertIn("background:#365b76!important;",page)
        self.assertIn("background:var(--group-color,#8494a6)!important",page)
        self.assertIn(".editorSection .actionGrid{display:flex!important;flex-direction:column!important;",page)
        self.assertIn("['Соперник / линия','Equity','EV BB','Вскрытие']",page)
        self.assertIn("post('/api/plan/postflop',settings)",page)


if __name__=="__main__":
    unittest.main()
