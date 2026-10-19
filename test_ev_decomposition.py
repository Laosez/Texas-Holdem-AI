"""Loss exposure attribution for a single hand without claiming counterfactual error."""
import math
import unittest

from planner_ev_decomposition import EVDecomposition,classify_showdown,preflop_domination,showdown_group,showdown_mechanism,reason_for_event
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
        tied=[("Q","h"),("3","h")]
        river_flush=[("A","s"),("J","s"),("9","s"),("5","s"),("2","s")]
        self.assertEqual(classify_showdown([("K","d"),("4","d")],[tied],river_flush,hero_won=True)[2],
                         "equal_flush")

    def test_kicker_and_higher_pair_losses(self):
        board=[("K","d"),("9","h"),("4","c"),("3","h"),("T","d")]
        hero=[("K","s"),("2","s")]
        self.assertEqual(classify_showdown(hero,[[("K","h"),("Q","s")]],board,hero_won=False)[1],"better_kicker")
        self.assertEqual(classify_showdown(hero,[[("A","h"),("A","s")]],board,hero_won=False)[1],"higher_pair")

    def test_preflop_domination_only_same_high_card_or_pocket_pair(self):
        self.assertEqual(preflop_domination(
            [("A","s"),("K","d")],[("A","d"),("Q","h")])[0],"hero")
        self.assertEqual(preflop_domination(
            [("K","s"),("4","d")],[("K","d"),("Q","h")])[0],"villain")
        self.assertEqual(preflop_domination(
            [("Q","s"),("Q","d")],[("9","d"),("9","h")])[0],"hero")
        self.assertIsNone(preflop_domination(
            [("A","s"),("K","d")],[("Q","d"),("J","h")])[0])

    def test_showdown_domination_categories_and_board_ties(self):
        board=[("2","c"),("6","s"),("9","h"),("J","c"),("3","d")]
        group,matchup=showdown_group(
            [("A","s"),("K","d")],[[("A","d"),("Q","h")]],board,True)
        self.assertEqual(group,"showdown_win_dominates")
        self.assertEqual(matchup,("hero","AK","AQ"))
        group,matchup=showdown_group(
            [("K","s"),("4","d")],[[("K","d"),("Q","h")]],board,False)
        self.assertEqual(group,"showdown_loss_dominated")
        self.assertEqual(matchup,("villain","K4","KQ"))
        tied=[("A","c"),("K","c"),("Q","c"),("J","c"),("T","c")]
        group,_=showdown_group(
            [("4","s"),("3","d")],[[("8","d"),("7","h")]],tied,True)
        self.assertEqual(group,"showdown_split")

    def test_showdown_explanation_by_hand_class_and_kicker(self):
        board=[("K","d"),("9","h"),("4","c"),("3","h"),("T","d")]
        label=showdown_mechanism(
            [("K","s"),("2","s")],[[("K","h"),("Q","s")]],board)[1]
        self.assertIn("Преимущество кикера",label)
        label=showdown_mechanism(
            [("A","s"),("A","h")],[[("K","h"),("Q","s")]],board)[1]
        self.assertIn("Одна пара",label)
        self.assertIn("Старшая пара",label)
        label=showdown_mechanism(
            [("J","s"),("8","s")],[[("A","h"),("Q","h")]],
            [("2","s"),("4","s"),("7","s"),("K","c"),("3","d")])[1]
        self.assertIn("Флеш против",label)
        self.assertEqual(reason_for_event("uncontested")[0],"pre_uncontested")
        self.assertEqual(reason_for_event("win_without_showdown")[0],"pre_villain_folds")
        self.assertIn("тёрне",reason_for_event("fold_turn")[1])

    def test_reasons_partition_each_group_and_reconcile_ev(self):
        d=EVDecomposition("AKo")
        d.add(1.5,"uncontested",group="pre_win")
        d.add(3,"win_without_showdown",group="pre_win")
        d.add(-2,"fold_flop",group="pre_loss")
        d.add(10,"showdown_5_win",group="showdown_win",
              reason=("showdown_categories_5_4","Флеш против стрита"))
        d.add(-5,"showdown_1_loss",group="showdown_loss",
              reason=("showdown_same_1_kicker","Одна пара · Преимущество кикера"))
        output=d.result()
        self.assertEqual(output["samples"],5)
        self.assertEqual(sum(x["count"] for x in output["outcome_groups"]),5)
        self.assertAlmostEqual(output["ev_bb"],1.5)
        for group in output["outcome_groups"]:
            self.assertEqual(group["count"],sum(x["count"] for x in group["reasons"]))
            self.assertAlmostEqual(
                group["contribution_bb"],
                sum(x["contribution_bb"] for x in group["reasons"]),places=4)
        pre_win=output["outcome_groups"][0]
        self.assertEqual(pre_win["count"],2)
        self.assertEqual(len(pre_win["reasons"]),2)

    def test_final_hand_domination_is_not_preflop_domination(self):
        # A7 has no matching high card with KQ preflop, but wins at
        # showdown with the SAME five-card hand category (high card).
        board=[("2","c"),("4","d"),("9","h"),("J","c"),("3","d")]
        category,matchup=showdown_group(
            [("A","s"),("7","h")],[ [("K","h"),("Q","s")] ],board,True)
        self.assertEqual(category,"showdown_win_dominates")
        self.assertIsNone(matchup)

        # AK preflop dominates AQ, but on this board Hero has trips K,
        # rival only has two pair (K and Q): different made-hand category.
        board=[("K","s"),("K","d"),("Q","h"),("3","d"),("2","c")]
        category,matchup=showdown_group(
            [("A","s"),("K","h")],[ [("A","d"),("Q","s")] ],board,True)
        self.assertEqual(category,"showdown_win")
        self.assertEqual(matchup[0],"hero")

    def test_same_final_hand_category_domination_rank_and_kicker(self):
        board=[("2","c"),("5","d"),("9","h"),("J","c"),("3","d")]
        # Different pair ranks.
        category,_=showdown_group(
            [("A","s"),("A","d")],[ [("K","s"),("K","h")] ],board,True)
        self.assertEqual(category,"showdown_win_dominates")
        # Same pair rank; Q kicker dominates our four.
        board=[("K","s"),("5","d"),("9","h"),("J","c"),("3","d")]
        category,_=showdown_group(
            [("K","h"),("4","c")],[ [("K","d"),("Q","s")] ],board,False)
        self.assertEqual(category,"showdown_loss_dominated")
        # Different made-hand categories are NOT domination.
        board=[("A","h"),("2","d"),("9","h"),("J","c"),("3","d")]
        category,_=showdown_group(
            [("A","s"),("A","d")],[ [("K","s"),("Q","s")] ],board,True)
        self.assertEqual(category,"showdown_win")

    def test_bdr_gross_income_loss_ledger_reconciles_without_double_count(self):
        d=EVDecomposition("AKo")
        for value,group,reason in [
            (8,"showdown_win","pair"),
            (-3,"showdown_win","side_pot_loss"),
            (7,"pre_win","opponents_fold"),
            (-2,"pre_loss","fold_flop"),
            (0,"showdown_split","split"),
            (-5,"showdown_loss","opponent_straight"),
            (4,"showdown_loss","side_pot_win"),
        ]:
            d.add(value,"win_without_showdown",group=group,reason=(reason,reason))
        v=d.result()
        groups=v["outcome_groups"]
        n=v["samples"]
        self.assertEqual(n,7)
        self.assertEqual(sum(g["count"] for g in groups),n)
        self.assertEqual(sum(g["positive_count"]+g["negative_count"]+
                             g["neutral_count"] for g in groups),n)
        positive=sum(g["positive_ev_bb"] for g in groups)
        negative=sum(g["negative_ev_bb"] for g in groups)
        self.assertAlmostEqual(positive,19/7,places=4)
        self.assertAlmostEqual(negative,-10/7,places=4)
        self.assertAlmostEqual(positive+negative,v["ev_bb"],places=4)
        for g in groups:
            self.assertEqual(sum(r["positive_count"] for r in g["reasons"]),
                             g["positive_count"])
            self.assertEqual(sum(r["negative_count"] for r in g["reasons"]),
                             g["negative_count"])
            self.assertAlmostEqual(sum(r["positive_ev_bb"] for r in g["reasons"]),
                                   g["positive_ev_bb"],places=4)
            self.assertAlmostEqual(sum(r["negative_ev_bb"] for r in g["reasons"]),
                                   g["negative_ev_bb"],places=4)

    def test_six_primary_groups_plus_ties_reconcile(self):
        d=EVDecomposition("AKo")
        cases=[
            (2,"uncontested","pre_win",None),
            (-3,"fold_flop","pre_loss",None),
            (6,"showdown_1_win","showdown_win_dominates",("hero","AK","AQ")),
            (4,"showdown_1_win","showdown_win",("villain","AK","AA")),
            (-5,"showdown_1_loss","showdown_loss_dominated",("villain","AK","AQ")),
            (-2,"showdown_1_loss","showdown_loss",None),
            (0,"showdown_0_win","showdown_split",None),
        ]
        for net,event,group,matchup in cases:
            d.add(net,event,group=group,matchup=matchup)
        r=d.result()
        self.assertEqual(sum(x["count"] for x in r["outcome_groups"]),7)
        self.assertEqual([x["count"] for x in r["outcome_groups"]],[1]*7)
        self.assertAlmostEqual(sum(x["contribution_bb"] for x in r["outcome_groups"]),
                               r["ev_bb"],places=4)
        self.assertEqual(len(r["domination_matchups"]),3)

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


    def test_conditional_ev_breakdown_reconciles_by_number_of_opponents(self):
        q = {
            "model": "selected", "hand": "K4s", "trials": 90, "cycles": 1,
            "hero_postflop": "gto2", "hero_position": "3", "hero_stack_bb": 20,
            "opponents": [
                {"profile": "builtin:a17_v5", "position": position,
                 "scenario": "rfi", "players": 9, "selector": "active",
                 "entry_mode": "range", "entry_pct": 100, "postflop": "lag"}
                for position in ("9", "8")
            ],
        }
        output = ev.calculate(q)
        buckets = output["decomposition_by_opponents"]
        self.assertEqual(len(buckets), 3)
        self.assertEqual([item["opponents"] for item in buckets], [0, 1, 2])
        self.assertEqual(sum(item["samples"] for item in buckets), 90)
        self.assertEqual([item["samples"] for item in buckets],
                         output["entry_n_samples"])
        self.assertAlmostEqual(sum(item["frequency_pct"] for item in buckets),
                               100, delta=0.03)
        overall_ev = output["decomposition"]["ev_bb"]
        mean_by_bucket = sum(item["samples"] * (item["ev_bb"] or 0)
                             for item in buckets) / 90
        self.assertAlmostEqual(overall_ev, mean_by_bucket, delta=0.0002)
        for item in buckets:
            breakdown = item["decomposition"]
            if not item["samples"]:
                self.assertIsNone(breakdown)
                self.assertIsNone(item["ev_bb"])
                self.assertIsNone(item["ev_ci95_bb"])
                continue
            self.assertEqual(breakdown["samples"], item["samples"])
            self.assertAlmostEqual(breakdown["ev_bb"], item["ev_bb"])
            self.assertEqual(sum(group["count"] for group in
                                 breakdown["outcome_groups"]), item["samples"])
            self.assertAlmostEqual(
                sum(group["contribution_bb"] for group in
                    breakdown["outcome_groups"]), item["ev_bb"], delta=0.0002)

    def test_zero_opponents_bucket_and_empty_group_are_explicit(self):
        q = {
            "model": "selected", "hand": "T6s", "trials": 50, "cycles": 1,
            "hero_postflop": "gto2", "hero_position": "3", "hero_stack_bb": 20,
            "opponents": [{
                "profile": "builtin:any_two", "position": "9",
                "scenario": "rfi", "players": 9, "selector": "active",
                "entry_mode": "never", "entry_pct": 0, "postflop": "lag"
            }],
        }
        out = ev.calculate(q)
        no_opponent, one_opponent = out["decomposition_by_opponents"]
        self.assertEqual(no_opponent["samples"], 50)
        self.assertAlmostEqual(no_opponent["ev_bb"], 1.5)
        self.assertAlmostEqual(no_opponent["frequency_pct"], 100.)
        self.assertAlmostEqual(no_opponent["ev_ci95_bb"], 0.)
        self.assertEqual(one_opponent["samples"], 0)
        self.assertIsNone(one_opponent["decomposition"])
        self.assertIsNone(one_opponent["ev_bb"])
        self.assertEqual(no_opponent["decomposition"]["samples"], 50)
        self.assertEqual(out["ev_bb"]["T6s"], 1.5)

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
        self.assertEqual(sum(x["count"] for x in d["outcome_groups"]),75)
        for group in d["outcome_groups"]:
            self.assertEqual(sum(x["count"] for x in group["reasons"]),group["count"])
            self.assertAlmostEqual(sum(x["contribution_bb"] for x in group["reasons"]),
                                   group["contribution_bb"],places=4)
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

    def test_full_width_section_is_direct_child_of_main_not_workspace(self):
        from html.parser import HTMLParser

        class Structure(HTMLParser):
            def __init__(self):
                super().__init__()
                self.stack=[]
                self.parents={}
            def handle_starttag(self,tag,attrs):
                if tag not in ('main','div','section'):
                    return
                attrs=dict(attrs)
                kind=(tag,attrs.get('class',''),attrs.get('id',''))
                classes=kind[1].split()
                if ('plannerMain' in classes or 'plannerWorkspace' in classes
                    or 'editorSection' in classes or 'handEVBreakdown' in classes):
                    self.parents[classes[0] if 'plannerMain' in classes
                                 else next(c for c in ('plannerWorkspace','editorSection','handEVBreakdown')
                                           if c in classes)]=self.stack[-1] if self.stack else None
                self.stack.append(kind)
            def handle_endtag(self,tag):
                if tag in ('main','div','section'):
                    if not self.stack or self.stack[-1][0]!=tag:
                        raise AssertionError('Malformed planner layout: '+tag)
                    self.stack.pop()

        checker=Structure()
        checker.feed(app.PLAN_UI.read_text(encoding='utf-8'))
        self.assertEqual(checker.stack,[])
        self.assertIn('plannerMain',checker.parents)
        self.assertEqual(checker.parents['editorSection'][1],'plannerWorkspace')
        self.assertEqual(checker.parents['handEVBreakdown'][1],'plannerMain')

    def test_panel_is_full_width_below_matrix_with_editor_as_sidebar(self):
        s=app.PLAN_UI.read_text(encoding="utf-8")
        matrix=s.index('id="heroMatrix"')
        editor=s.index('class="panel editorSection"')
        block=s.index('id="handEVBreakdown"')
        end=s.index('</main>')
        self.assertLess(matrix,editor)
        self.assertLess(editor,block)
        self.assertLess(block,end)
        self.assertIn('</section>\n</div>\n\n<section class="panel handEVBreakdown"',s)
        self.assertIn('.plannerMain>.handEVBreakdown{grid-column:1/-1;width:100%;min-width:0',s)
        self.assertIn('.plannerWorkspace{display:grid;grid-template-columns:minmax(0,1fr) 342px',s)
        self.assertIn('@media(max-width:1000px){.plannerWorkspace{grid-template-columns:1fr}',s)
        self.assertNotIn('.plannerWorkspace>.editorSection{grid-column:2',s)
        self.assertIn('<span class="index">05 / </span>Декомпозиция выбранной руки',s)
        for key in ("handDecompTag","handDecompRows","handDecompCost",
                    "handDecompSamples","handDecompEV"):
            self.assertIn('id="'+key+'"',s)
        self.assertNotIn('id="handDecompRun"',s)
        self.assertNotIn('data-hand-decomp-tab=',s)
        self.assertIn("decomposition.add(chip_ev,event,risk=risk,flush=flush,",
                      __import__("inspect").getsource(ev.calculate))
        self.assertIn("const output=await pollPostflop(settings,epoch",s)
        self.assertIn("function renderHandDecomposition(){",s)
        self.assertIn("evLedgerTable",s)
        self.assertIn("let decompReportMode='board150';",s)
        self.assertIn("function renderBdrLedger(root,data)",s)
        self.assertIn("function renderBalanceLedger(root,data)",s)
        self.assertIn("function renderCompareBdrLedger(root,a,b,compare=true)",s)
        self.assertIn("function renderCompareBalanceLedger(root,a,b)",s)
        self.assertIn("abNumber(a,countA),abNumber(b,countB)",s)
        self.assertIn("const profile=side==='a' ? $('heroPostflop').value : $('handDecompProfileB').value;",s)
        self.assertIn("{value:'=',label:'= · та же рука A'}",s)
        self.assertIn("top.colSpan=compare?3:1",s)
        self.assertIn("function abDisplayedColumns(compare){",s)
        self.assertIn("function toggleAbColumn(key){",s)
        self.assertIn("const abOpenColumns=new Set(['n','pct','avg','ev','diff']);",s)
        self.assertIn("function renderOpponentEvComparison(chartA,chartB){",s)
        self.assertIn("function opponentEvChartPoints(buckets){",s)
        self.assertIn("function opponentEvChartCi(group,combined){",s)
        self.assertIn("renderOpponentEvComparison(fullA,fullB);",s)
        self.assertIn(".handDecompRows .handDecompTable td{font-size:13px;",s)
        self.assertIn("font-weight:400!important",s)
        self.assertIn("const overallA=fullA?.data||null,overallB=fullB?.data||null;",s)
        self.assertIn('id="handDecompChartAB"',s)
        self.assertIn('id="handDecompLegendB"',s)
        self.assertIn('id="handDecompSampleBWrap"',s)
        self.assertIn("function abRelativePct(a,b,base,other){",s)
        self.assertIn("abRelativePct(a,b,ea,eb)",s)
        self.assertIn("abRelativePct(a,b,totalA,totalB)",s)
        self.assertIn(".abMetricGood{color:#95e0ab!",s)
        self.assertIn(".abMetricBad{color:#ff9c9f!",s)
        self.assertIn("renderCompareBdrLedger(root,a,b,compare);",s)
        self.assertIn("const abOpenSections=new Set(['gain','loss']);",s)
        self.assertIn("const abOpenReasons=new Set();",s)
        self.assertIn("button.setAttribute('aria-expanded',String(disclosure.open));",s)
        self.assertIn("if(!settings)return;",s)
        self.assertIn("Promise.allSettled(sides.map(calculateSide))",s)
        self.assertIn("statuses[side]='очередь'",s)
        self.assertNotIn("renderDominationMatchups(",s)
        self.assertIn("renderHandDecomposition();",s)


if __name__=="__main__":
    unittest.main()
