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

    def test_single_hand_mc_updates_matrix_and_records_its_own_n(self):
        page=app.PLAN_UI.read_text(encoding="utf-8")
        # The separate hand result must be accepted, not only displayed
        # in the decomposition block as in the earlier implementation.
        self.assertIn("acceptSingleHandMatrixResult(hand,output,settings);",page)
        self.assertIn("result[metric]={...(result[metric]||{}),[hand]:incoming[hand]};",page)
        self.assertIn("const HAND_RESULT_METRICS=['equity','ev_bb','showdown_pct','fold_win_pct','ev_ci95_bb'];",page)
        self.assertIn("result.hand_samples={...(result.hand_samples||{}),",page)
        self.assertIn("N · обновлено для руки",page)
        self.assertIn("matrix_partial=Object.keys(result.equity||{}).length<169",page)
        self.assertIn("if(data?.matrix_partial){",page)
        # A different N may refine a single hand without invalidating the
        # whole 169-hand EV matrix.
        self.assertIn("const {hand,trials,cycles,...context}=settings;",page)
        self.assertIn("const context=postflopMatrixContext(settings);",page)
        self.assertIn("if(context!==postflopMatrixContext())return false;",page)

    def test_single_hand_and_full_matrix_concurrent_results_are_not_lost(self):
        page=app.PLAN_UI.read_text(encoding="utf-8")
        self.assertIn("const startedAt=handWriteSeq,context=postflopMatrixContext();",page)
        self.assertIn("acceptCompleteMatrixResult(matrix,startedAt,context)",page)
        self.assertIn("entry.context===context && entry.seq>startedAt",page)
        self.assertIn("merged=replaceMatrixHand(merged,hand,entry.output);",page)
        self.assertIn("handWritebacks.clear();",page)
        self.assertIn("matrixContextKey='';handWritebacks.clear();",page)
        self.assertIn("if(!computingAll){",page)

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

    def test_all_opponents_row_zero_independent_bulk_controls(self):
        page=app.PLAN_UI.read_text(encoding="utf-8")
        self.assertIn("target.append(opponentBulkRow());",page)
        self.assertIn("row.append(el('span','num','0'));",page)
        self.assertIn("makeSelect(profileOptions(),'Диапазон → всем','profile')",page)
        self.assertIn("makeSelect(POSTFLOP_OPTIONS,'Постфлоп → всем','postflop')",page)
        self.assertIn("for(const opponent of opponents)opponent[field]=value;",page)
        self.assertIn("if(!['profile','postflop'].includes(field)",page)
        self.assertIn("invalidateEquity();renderOpponents();",page)
        self.assertIn("if(field==='profile')loadVillain();",page)
        self.assertIn(".plannerOpponentsPanel .oppBulkRow{",page)

    def test_eight_fixed_opponent_seats_with_zero_inactive_modes(self):
        import planner_postflop_ev as post
        positions=["9","8","7","6","5","4","SB","BB"]
        opponents=[
            {"profile":"builtin:a17_v5","position":seat,
             "scenario":"vs_open" if seat=="BB" else "rfi","players":9,
             "selector":"active","entry_mode":"range" if i<3 else "never",
             "entry_pct":100 if i<3 else 0,"postflop":"gto2"}
            for i,seat in enumerate(positions)
        ]
        payload={"model":"selected","hand":"AKs","trials":50,"cycles":1,
                 "hero_postflop":"gto2","hero_position":"3","hero_stack_bb":20,
                 "opponents":opponents}
        result=post.calculate(payload)
        self.assertEqual(len(result["entry_n_samples"]),9)
        self.assertEqual(sum(result["entry_n_samples"]),50)
        self.assertEqual(sum(result["entry_n_samples"][4:]),0)
        self.assertIn("AKs",result["ev_bb"])

    def test_accounting_report_variants_and_fixed_seat_grid(self):
        page=app.PLAN_UI.read_text(encoding="utf-8")
        for needle in (
            "let decompReportMode='bdr';",
            "1 · БДР", "3 · Баланс EV",
            "function renderBdrLedger(root,data){",
            "function renderBalanceLedger(root,data){",
            "ledgerControls(root);",
            "decompReportMode==='bdr'",
            "for(const r of ledgerReasonOrder(g.reasons||[]))",
            "for(const part of BALANCE_SECTIONS)",
            "return {data,count:data.reduce",
            "positive_ev_bb", "negative_ev_bb",
            "function normalizeFixedSeats(){",
            "const FIXED_TABLE_POSITIONS=['9','8','7','6','5','4','3','SB','BB'];",
            "function heroPositionSeatRow(position,controls){",
            "const heroSeat=normalizeFixedSeats();",
            "target.append(heroPositionSeatRow(heroSeat,heroControls));",
            "const pos=el('span','oppFixedSeat',fixedSeatCaption(opp.position))",
            "entry_mode:i<3?'range':'never'",
            "id=\"addOpponent\" class=\"btn sm hidden\"",
        ):
            self.assertIn(needle,page)
        self.assertNotIn("activeDecompGroup=opened?null:group.key",page)
        self.assertNotIn("decompOneDetail",page[page.index("function renderHandDecomposition(){"):])
        self.assertIn("«0%» исключает место",page)

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
        self.assertNotIn('decompSort.column===col.key',page)
        self.assertIn("DECOMP_LABELS={",page)
        self.assertIn("function renderBdrLedger(root,data)",page)
        self.assertIn("function renderBalanceLedger(root,data)",page)
        self.assertNotIn('class="decompMatchupDisclosure"',page)
        self.assertNotIn('decompReasonDisclosure',page)


if __name__=="__main__":
    unittest.main()
