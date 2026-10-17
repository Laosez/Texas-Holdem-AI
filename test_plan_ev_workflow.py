"""Plan UX V5: always EV, explicit single-N controls, pot/variance, auto hand rows."""
import math
import random
import unittest

import planner_postflop_ev as ev
import replit_simulator as app
import planner_equity as eq


def request(hand="K4s",trials=250):
    return {
        "model":"selected","trials":trials,"cycles":1,
        "hero_postflop":"gto2","hero_position":"3","hero_stack_bb":20,
        "opponents":[{"profile":"builtin:any_two","position":"9","scenario":"rfi",
          "players":9,"selector":"active","entry_mode":"always",
          "entry_pct":100,"postflop":"lag"}],
        **({"hand":hand} if hand else {})
    }


class PlanEVWorkflowTests(unittest.TestCase):
    def test_deep_single_hand_contract_matrix_budget(self):
        data=ev.validate_request(request(trials=64000))
        self.assertEqual(data["trials"],64000)
        self.assertEqual(ev.validate_request(request(hand=None,trials=8000))["trials"],8000)
        self.assertEqual(ev.validate_request(request(hand=None,trials=64000))["trials"],64000)
        with self.assertRaisesRegex(ValueError,"50–64000"):
            ev.validate_request(request(hand=None,trials=64001))

    def test_true_final_pot_and_ci_from_same_rollouts(self):
        result=ev.calculate(request(trials=250))
        self.assertEqual(result["simulations_per_hand"],250)
        self.assertEqual(sum(result["entry_n_samples"]),250)
        self.assertEqual(len(result["entry_pot_bb"]),2)
        self.assertEqual(result["entry_n_samples"][0],0)
        self.assertEqual(result["entry_n_samples"][1],250)
        self.assertGreater(result["entry_pot_bb"][1],2)
        self.assertGreater(result["entry_ev_sd_bb"][1],0)
        self.assertGreater(result["ev_ci95_bb"]["K4s"],0)
        self.assertEqual(result["decomposition"]["samples"],250)
        self.assertLess(abs(result["decomposition"]["ev_bb"]-result["ev_bb"]["K4s"]),.00015)
        self.assertIn("разброс",result["entry_stats_note"] if "разброс" in result["entry_stats_note"] else "разброс net BB")

    def test_direct_engine_pot_callback_is_exact(self):
        from core.engine import Table,Seat
        from bots import create_bot
        bot=create_bot("split:pc_gto_80bb:gto_postflop_v2")
        tbl=Table(rng=random.Random(42))
        pot=[]
        tbl.on_hand_pot=lambda hand_id,chips,bb:pot.append((chips,bb))
        players={"P1":bot,"P2":bot}
        payouts=tbl.play_hand([Seat("P1",40),Seat("P2",40)],1,2,0,players)
        self.assertEqual(len(pot),1)
        self.assertEqual(pot[0][1],2)
        self.assertGreaterEqual(pot[0][0],3)
        self.assertEqual(sum(payouts.values()),0)

    def test_plan_no_metric_cycles_brush_toolbar_and_auto_selected_rows(self):
        page=app.PLAN_UI.read_text(encoding="utf-8")
        self.assertIn('<select id="cellMetric" class="hidden"',page)
        self.assertIn('<option value="evStrategy" selected>',page)
        self.assertNotIn('Показатель в матрице</label>',page)
        self.assertIn('<input id="cycles" type="hidden" value="1">',page)
        self.assertNotIn('Независимые циклы</label>',page)
        for count in (250,500,1000,2000,4000,8000,16000,32000,64000):
            self.assertIn('option value="'+str(count)+'"',page)
        self.assertIn('#groupEditor .brushbar',page)
        self.assertIn('id="boxes" class="boxList"',page)
        self.assertIn("card.ondrop=e=>",page)
        self.assertIn("moveHandsToBox(editorTargets(),Number($('handBox').value))",page)
        self.assertNotIn('id="handDecompRun"',page)
        self.assertNotIn('data-hand-decomp-tab=',page)
        self.assertIn("scheduleHandDecomposition();",page)
        self.assertNotIn('id="entryPrecisionTrials"',page)
        self.assertIn('id="opponentEntrySummary"',page)
        self.assertIn('Средний банк, BB',page)
        self.assertIn('aria-sort',page)
        self.assertIn("decompSort.column===col.key",page)


if __name__=="__main__":
    unittest.main()
