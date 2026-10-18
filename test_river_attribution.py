"""Regression: real street, suit S3/S4/S5 and rank/origin/settlement separation."""
import unittest

import planner_postflop_ev as sim
from planner_river_classifier import (
    board_texture, hand_details, classify_attribution, CAUSES, BOARDS
)


R="23456789TJQKA"
S="cdhs"
def c(rank,suit):
    return 4*R.index(rank)+S.index(suit)


def request(*,never=False,paired=False,trials=50):
    data={
        "model":"selected","hand":"K4s","trials":trials,"cycles":1,
        "hero_postflop":"gto2","hero_position":"3","hero_stack_bb":20,
        "opponents":[{"profile":"builtin:any_two","position":"9","scenario":"rfi",
          "players":9,"selector":"active","entry_mode":"never" if never else "always",
          "entry_pct":100,"postflop":"lag"}],
    }
    if paired:data["hero_postflop_b"]="tag"
    return data


def verify(result,trials):
    cube=result["river_attribution"]
    assert cube["reconciled"]
    assert cube["version"]=="river_reason_board_v1"
    assert cube["samples"]==trials
    rows=cube["rows"]
    assert sum(r["count"] for r in rows)==trials
    assert all(r["count"]==r["positive_count"]+r["negative_count"]+
               r["neutral_count"] for r in rows)
    assert abs(sum(r["contribution_bb"] for r in rows)-result["ev_bb"])<.003
    assert abs(sum(r["positive_ev_bb"]+r["negative_ev_bb"] for r in rows)-result["ev_bb"])<.003
    assert all(r["cause"] in CAUSES and r["board_id"] in BOARDS for r in rows)
    return rows


class RiverAttributionTests(unittest.TestCase):
    def test_three_four_five_suited_board_are_distinct(self):
        flop=[c("A","h"),c("7","h"),c("2","h")]
        turn=flop+[c("9","h")]
        river=turn+[c("K","h")]
        b3=board_texture(river,"flop")
        b4=board_texture(river,"turn")
        b5=board_texture(river,"river")
        self.assertEqual((b3["id"],b3["suit"]),("B03","S3"))
        self.assertEqual((b4["id"],b4["suit"]),("B02","S4"))
        self.assertEqual((b5["id"],b5["suit"]),("B05","S5"))
        self.assertEqual(b3["board_cards"],3)
        self.assertEqual(b4["board_cards"],4)
        self.assertEqual(b5["board_cards"],5)

    def test_board_pair_versus_own_and_pocket_pair(self):
        board=[c("A","h"),c("A","d"),c("7","c"),c("5","d"),c("2","c")]
        shared=hand_details([c("K","s"),c("Q","s")],board,"river")
        self.assertEqual(shared["origin"],"board_pair")
        self.assertEqual(shared["category"],1)
        own=hand_details([c("K","s"),c("7","s")],[
            c("7","d"),c("J","h"),c("4","c"),c("3","d"),c("2","c")],"river")
        self.assertEqual(own["origin"],"own_pair")
        pocket=hand_details([c("K","s"),c("K","h")],[
            c("7","d"),c("J","h"),c("4","c"),c("3","d"),c("2","c")],"river")
        self.assertEqual(pocket["origin"],"pocket_pair")

    def test_set_trips_and_board_trips(self):
        set_ = hand_details([c("7","s"),c("7","h")],[
            c("7","d"),c("K","h"),c("4","c"),c("3","d"),c("2","c")],"river")
        trips=hand_details([c("7","s"),c("A","h")],[
            c("7","d"),c("7","h"),c("4","c"),c("3","d"),c("2","c")],"river")
        shared=hand_details([c("A","s"),c("Q","h")],[
            c("7","d"),c("7","h"),c("7","c"),c("3","d"),c("2","c")],"river")
        self.assertEqual((set_["origin"],trips["origin"],shared["origin"]),
                         ("set","trips","board_trips"))

    def test_straights_zero_one_two_hole_cards(self):
        common=[c("9","c"),c("T","d"),c("J","h"),c("Q","s"),c("K","c")]
        own=hand_details([c("A","d"),c("2","d")],common,"river")
        self.assertEqual((own["category"],own["hole_use"]),(4,1))
        shared=hand_details([c("2","d"),c("3","d")],common,"river")
        self.assertEqual((shared["category"],shared["hole_use"]),(4,0))
        two=hand_details([c("8","d"),c("9","d")],[
            c("T","h"),c("J","s"),c("Q","c"),c("2","c"),c("3","h")],"river")
        self.assertEqual((two["category"],two["hole_use"]),(4,2))

    def test_equal_board_hand_and_kicker_category(self):
        # Same pair rank, different fifth-card kicker.
        board=[c("A","d"),c("A","h"),c("7","c"),c("4","d"),c("3","c")]
        picked=[("HERO",[c("K","s"),c("Q","s")],None),
                ("V1",[c("J","s"),c("T","s")],None)]
        d=classify_attribution(picked,board,"showdown_1_win",4,"river",("HERO","V1"),("HERO",))
        self.assertEqual((d["cause"],d["board"]["rank_texture"],d["hero"]["origin"]),
                         ("C06","one_pair","board_pair"))
        self.assertEqual(d["sign"],"profit")

    def test_pair_rank_kicker_and_different_categories_are_distinct_causes(self):
        board=[c("A","d"),c("7","h"),c("5","c"),c("4","d"),c("3","c")]
        # HERO AA versus villain KK: same final one-pair category, rank gap.
        rank=[("HERO",[c("A","s"),c("Q","s")],None),
              ("V1",[c("K","s"),c("K","h")],None)]
        r=classify_attribution(rank,board,"showdown_1_win",2.0,"river",
                                ("HERO","V1"),("HERO",))
        self.assertEqual(r["cause"],"C05")
        # HERO top pair vs villain two pairs: actual category gap.
        gap=[("HERO",[c("A","s"),c("Q","s")],None),
             ("V1",[c("K","s"),c("K","h")],None)]
        paired_board=[c("A","d"),c("7","h"),c("7","c"),c("4","d"),c("3","c")]
        v=classify_attribution(gap,paired_board,"showdown_2_loss",-2.0,"river",
                               ("HERO","V1"),("V1",))
        self.assertEqual(v["cause"],"C04")
        self.assertEqual(v["sign"],"loss")
        # Multiway split/side-pot payout conflicts are labelled explicitly.
        conflict=classify_attribution(gap,paired_board,"showdown_2_win",1.0,"river",
                                       ("HERO","V1"),("HERO",))
        self.assertEqual(conflict["cause"],"C08")

    def test_paired_uncontested_reconciles_in_both_strategies(self):
        q=sim.calculate_paired(request(never=True,paired=True,trials=50),workers=1)
        left=verify(q["a"]["decomposition"],50)
        right=verify(q["b"]["decomposition"],50)
        self.assertEqual({(r["cause"],r["board_id"]) for r in left},{("C01","B00")})
        self.assertEqual(left,right)

    def test_fold_at_flop_does_not_invent_river_texture(self):
        board=[c("A","h"),c("7","h"),c("2","h"),c("9","h"),c("K","h")]
        picked=[("HERO",[c("Q","s"),c("J","s")],None),
                ("V1",[c("T","s"),c("3","s")],None)]
        d=classify_attribution(picked,board,"fold_flop",-3,"flop")
        self.assertEqual((d["cause"],d["board"]["suit"],d["board"]["street"]),
                         ("C03","S3","flop"))
        self.assertNotEqual(d["board"]["id"],"B05")

    def test_preflop_uncontested_and_serial_rollout_reconcile(self):
        p=sim.calculate(request(never=True,trials=50))
        rows=verify(p["decomposition"],50)
        self.assertEqual({(r["cause"],r["board_id"]) for r in rows},{("C01","B00")})
        q=sim.calculate(request(trials=50))
        verify(q["decomposition"],50)
        verify(q["decomposition_by_opponents"][1]["decomposition"],50)

    def test_paired_same_deals_but_separate_cause_and_board_attribution(self):
        q=sim.calculate_paired(request(paired=True,trials=50),workers=1)
        verify(q["a"]["decomposition"],50)
        verify(q["b"]["decomposition"],50)
        self.assertEqual(q["comparison"]["samples"],50)

    def test_plan_river_report_retains_other_variants(self):
        from replit_simulator import PLAN_UI
        h=PLAN_UI.read_text(encoding="utf-8")
        for needle in ("value=\"bdr\" selected","value=\"catalog\"","value=\"river\"",
                       "function renderRiverLedger(root,a,b,compare){",
                       "function renderCatalogLedger(root,a,b,compare){",
                       "function renderCompareBdrLedger(root,a,b,compare=true)",
                       "RIVER_FILTERS","rank_texture","hero_hole_use",
                       "riverAdd(totals.a,r)","riverAdd(totals.b,r)",
                       "reasonBoardExpanded","Ср. BB",
                       "if(decompReportMode==='river'){"):
            self.assertIn(needle,h)


if __name__=="__main__":
    unittest.main()
