"""Loss exposure attribution for a single hand without claiming counterfactual error."""
import math
import unittest

from planner_ev_decomposition import EVDecomposition,classify_showdown
import planner_postflop_ev as ev
import replit_simulator as app


class EVDecompositionTests(unittest.TestCase):
    def test_higher_flush_and_lower_flush(self):
        board=[("J","s"),("9","s"),("2","s"),("3","d"),("T","d")]
        hero=[("K","s"),("4","s")]
        lower=[("8","s"),("7","s")]
        upper=[("A","s"),("5","s")]
        self.assertEqual(classify_showdown(hero,[lower],board,hero_won=True)[2],"lower_flush")
        self.assertEqual(classify_showdown(hero,[upper],board,hero_won=False)[1],"higher_flush")
        self.assertEqual(classify_showdown(hero,[upper],board,hero_won=False)[2],"higher_flush")
        tied=[("K","d"),("4","d")]
        river_flush=[("A","s"),("K","s"),("Q","s"),("J","s"),("T","s")]
        self.assertEqual(classify_showdown(hero,[tied],river_flush,hero_won=True)[2],
                         "equal_flush")

    def test_kicker_and_higher_pair_losses(self):
        board=[("K","d"),("9","h"),("4","c"),("3","h"),("T","d")]
        hero=[("K","s"),("2","s")]
        self.assertEqual(classify_showdown(hero,[[("K","h"),("Q","s")]],board,hero_won=False)[1],"better_kicker")
        self.assertEqual(classify_showdown(hero,[[("A","h"),("A","s")]],board,hero_won=False)[1],"higher_pair")

    def test_mutually_exclusive_ev_and_gross_negative_cost(self):
        d=EVDecomposition("K4s")
        d.add(1.5,"uncontested")
        d.add(-2,"fold_flop",risk="fold_flop_loss")
        d.add(-6,"showdown_5_loss",risk="higher_flush",flush="higher_flush")
        d.add(12,"showdown_5_win",flush="lower_flush")
        result=d.result()
        self.assertEqual(result["samples"],4)
        self.assertAlmostEqual(result["ev_bb"],1.375)
        self.assertEqual(sum(x["count"] for x in result["events"]),4)
        self.assertAlmostEqual(sum(x["contribution_bb"] for x in result["events"]),result["ev_bb"])
        self.assertEqual(result["loss_exposures"][0]["key"],"higher_flush")
        self.assertEqual(result["loss_exposures"][0]["cost_bb"],1.5)
        self.assertEqual(result["loss_exposures"][1]["cost_bb"],.5)
        self.assertAlmostEqual(sum(x["frequency_pct"] for x in result["events"]),100)

    def test_full_engine_selected_hand_detailed_output_reconciles_to_ev(self):
        q={
            "model":"selected","hand":"K4s","trials":75,"cycles":1,
            "hero_postflop":"gto2","hero_position":"3","hero_stack_bb":20,
            "opponents":[{"profile":"builtin:any_two","position":"9","scenario":"rfi",
                 "players":9,"selector":"active","entry_mode":"always",
                 "entry_pct":100,"postflop":"lag"}]
        }
        result=ev.calculate(q)
        d=result["decomposition"]
        self.assertEqual(d["samples"],75)
        self.assertEqual(d["hand"],"K4s")
        self.assertEqual(sum(row["count"] for row in d["events"]),75)
        self.assertLess(abs(sum(row["contribution_bb"] for row in d["events"])-result["ev_bb"]["K4s"]),.0003)
        self.assertTrue(d["diagnostic_only"])
        self.assertTrue(all(x["cost_bb"]>=0 for x in d["loss_exposures"]))
        self.assertTrue(all(x["count"]>=1 for x in d["flush"]))
        self.assertIn("НЕ стоимость ошибки",d["note"])
        # Previous benchmark contract remains two values.
        import planner_equity as equity
        ranges,_=equity.build_ranges(q["opponents"],"selected")
        import random
        picked,board=ev._draw_case("K4s",ranges,q["opponents"],random.Random(42))
        original=ev._play_case(picked,board,"gto2","3",20,99)
        self.assertEqual(len(original),2)

    def test_disabled_and_all_hand_runs_do_not_generate_details(self):
        q={
            "model":"selected","hand":"K4s","trials":50,"cycles":1,
            "hero_postflop":"none","hero_position":"3","hero_stack_bb":20,
            "opponents":[{"profile":"builtin:any_two","position":"9","scenario":"rfi",
                 "players":9,"selector":"active","entry_mode":"always",
                 "entry_pct":100,"postflop":"gto"}]
        }
        result=ev.calculate(q)
        self.assertIsNone(result["decomposition"])
        self.assertIsNone(result["ev_bb"]["K4s"])

    def test_panel_appears_between_matrix_and_editor(self):
        s=app.PLAN_UI.read_text(encoding="utf-8")
        before=s.index('id="heroMatrix"')
        block=s.index('id="handEVBreakdown"')
        after=s.index('class="panel editorSection"')
        self.assertLess(before,block)
        self.assertLess(block,after)
        for key in ("handDecompRun","handDecompTag","handDecompRows","handDecompCost",
                    "handDecompSamples","handDecompEV"):
            self.assertIn('id="'+key+'"',s)
        for tab in ("sources","domination","losses"):
            self.assertIn('data-hand-decomp-tab="'+tab+'"',s)
        self.assertIn("decomposition.add(chip_ev,event,risk=risk,flush=flush)",
                      __import__("inspect").getsource(ev.calculate))
        self.assertIn("const output=await pollPostflop(settings,epoch",s)
        self.assertIn("function renderHandDecomposition(){",s)
        self.assertIn("renderHandDecomposition();",s)


if __name__=="__main__":
    unittest.main()
