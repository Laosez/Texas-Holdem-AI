"""Exact 1,019-scenario glossary attribution for the selected-hand EV report."""
import unittest

from planner_ev_decomposition import EVDecomposition,catalog_flop_case
from postflop_composite_classifier import classify_composite_flop
import planner_postflop_ev as ev
import replit_simulator as app


def request(*, never=False, paired=False, trials=50):
    data={
        "model":"selected","hand":"K4s","trials":trials,"cycles":1,
        "hero_postflop":"gto2","hero_position":"3","hero_stack_bb":20,
        "opponents":[{"profile":"builtin:any_two","position":"9","scenario":"rfi",
          "players":9,"selector":"active","entry_mode":"never" if never else "always",
          "entry_pct":100,"postflop":"lag"}],
    }
    if paired:
        data["hero_postflop_b"]="tag"
    return data


def verify(report,n):
    catalog=report["catalog_attribution"]
    rows=catalog["rows"]
    assert catalog["reconciled"] and catalog["samples"]==n
    assert sum(r["count"] for r in rows)==n
    assert all(r["count"]==r["positive_count"]+r["negative_count"]+r["neutral_count"]
               for r in rows)
    assert abs(sum(r["contribution_bb"] for r in rows)-report["ev_bb"])<0.001
    assert abs(sum(r["positive_ev_bb"]+r["negative_ev_bb"] for r in rows)-
               report["ev_bb"])<0.001
    return rows


class CatalogEVReportTests(unittest.TestCase):
    def test_physical_flop_code_matches_canonical_classifier(self):
        # _card maps integers with rank 2..14 and suit c,d,h,s.
        hero=(8*4+3, 7*4+3)  # T♠, 9♠
        board=[5*4+0,3*4+1,0*4+2,9*4+0,11*4+1]  # 7c,5d,2h,...
        result=catalog_flop_case([("HERO",hero,None),("V1",(40,41),None)],board)
        direct=classify_composite_flop("10s-9s","7c-5d-2h")
        self.assertEqual(result["id"],direct["id"])
        self.assertEqual(result["board_group"],direct["board"]["group_id"])
        self.assertEqual(result["hero_class"],direct["hero_state"]["id"])
        self.assertEqual(result["hero_name"],direct["hero_state"]["name"])

    def test_incomplete_hand_before_flop_is_not_fabricated(self):
        case=catalog_flop_case([("HERO",(0,1),None)],[2,3,4,5,6])
        self.assertEqual(case["id"],"PRE|NO_FLOP")
        self.assertEqual(case["board_name"],"00 · До флопа")

    def test_positive_negative_net_and_zero_counts_reconcile(self):
        case={"id":"F|test|A","board_group":"test","board_name":"Тест",
              "hero_class":"A","hero_name":"Сценарий A"}
        before={"id":"PRE|NO_FLOP","board_group":"PRE|NO_FLOP",
                "board_name":"До флопа","hero_class":"PRE|NO_FLOP","hero_name":"Без флопа"}
        book=EVDecomposition("K4s")
        book.add(2.0,"uncontested",catalog=before)
        book.add(-5.0,"fold_flop",catalog=case)
        book.add(10.0,"showdown_1_win",catalog=case)
        book.add(0.0,"showdown_0_loss",catalog=case)
        rows=verify(book.result(),4)
        self.assertEqual(len(rows),2)
        scenario=next(r for r in rows if r["id"]==case["id"])
        self.assertEqual((scenario["positive_count"],scenario["negative_count"],scenario["neutral_count"]),(1,1,1))
        self.assertAlmostEqual(scenario["positive_ev_bb"],2.5)
        self.assertAlmostEqual(scenario["negative_ev_bb"],-1.25)
        self.assertAlmostEqual(scenario["contribution_bb"],1.25)

    def test_actual_mc_and_conditional_strata_share_catalog(self):
        result=ev.calculate(request(trials=50))
        rows=verify(result["decomposition"],50)
        self.assertTrue(rows)
        self.assertTrue(all(row["id"].startswith("F|") for row in rows))
        self.assertEqual(result["entry_n_samples"],[0,50])
        assert result["decomposition_by_opponents"][0]["decomposition"] is None
        verify(result["decomposition_by_opponents"][1]["decomposition"],50)

    def test_preflop_uncontested_has_one_real_article(self):
        result=ev.calculate(request(never=True,trials=50))
        rows=verify(result["decomposition"],50)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["id"],"PRE|NO_FLOP")
        self.assertEqual(rows[0]["count"],50)
        self.assertEqual(result["entry_n_samples"],[50,0])

    def test_paired_mc_uses_the_same_composite_ids(self):
        result=ev.calculate_paired(request(paired=True,trials=50),workers=1)
        a=verify(result["a"]["decomposition"],50)
        b=verify(result["b"]["decomposition"],50)
        self.assertEqual({r["id"]:r["count"] for r in a},
                         {r["id"]:r["count"] for r in b})
        self.assertEqual(result["comparison"]["samples"],50)

    def test_new_report_variant_switch_preserves_existing_bdr(self):
        html=app.PLAN_UI.read_text(encoding="utf-8")
        self.assertIn('id="handDecompReportVariant"',html)
        self.assertIn('<option value="bdr" selected>',html)
        self.assertIn('<option value="catalog">По справочнику · флоп</option>',html)
        self.assertIn("function renderCatalogLedger(root,a,b,compare){",html)
        self.assertIn("if(decompReportMode==='catalog'){",html)
        self.assertIn("renderCompareBdrLedger(root,a,b,compare);",html)
        self.assertIn("catalogOpenBoards=new Set()",html)
        self.assertIn("PRE|NO_FLOP",html)
        self.assertIn("sum",html)


if __name__=="__main__":
    unittest.main()
