"""Independent river audit: exact settled CALL/FOLD, privacy, CI and wiring."""
import json
import random
import unittest
from types import SimpleNamespace

from core.engine import Action, Seat, Table
from independent_river_auditor import (
    FORMAT, RiverDecisionCollector, RiverAggressionCollector,
    aggression_report, build_report)


BOARD = [("K","s"),("9","h"),("7","d"),("5","c"),("2","h")]


def scenario(hero=None, history=None, me="P1"):
    return SimpleNamespace(
        street="river", me=me, hand_id=105,
        board=list(BOARD), hole_cards=hero or [("A","c"),("A","d")],
        opponents=["P2"], all_in_opponents=[],
        to_call=20, pot=100, stacks={"P1":90,"P2":90},
        legal_actions=[{"type":"fold"}, {"type":"call"}, {"type":"raise","min":40,"max":90}],
        history=list(history or []))


class IndependentRiverAuditorTests(unittest.TestCase):
    def test_exact_win_loss_tie_and_private_cards_never_stored(self):
        tests = [
            (105,[("A","c"),("A","d")],[("3","c"),("4","c")],50.0),
            (106,[("3","c"),("4","c")],[("A","c"),("A","d")],-10.0),
        ]
        for hid, hero, opponent, expected in tests:
            with self.subTest(hid=hid):
                view = scenario(hero=hero)
                view.hand_id = hid
                collector = RiverDecisionCollector(tournament=1, percent=100)
                collector.observe(view, Action("fold"), opponent, 2,
                                  "P1=split:random:gto_postflop_541_step15", "random")
                rows = collector.records()
                self.assertEqual(len(rows),1)
                self.assertAlmostEqual(rows[0]["call_realized_bb"], expected)
                self.assertEqual(rows[0]["policy_realized_bb"], 0.0)
                self.assertEqual(rows[0]["chosen"], "fold")
                self.assertNotIn("villain_hole", rows[0])
                self.assertNotIn("opponent_hole", rows[0])
                self.assertNotIn("".join(opponent[0]), json.dumps(rows[0]))

        tie_board=[("A","s"),("K","s"),("Q","s"),("J","s"),("T","s")]
        tie=scenario(hero=[("2","c"),("3","d")])
        tie.board=tie_board
        collector=RiverDecisionCollector(1,percent=100)
        collector.observe(tie,Action("call"),[("4","c"),("5","d")],2,"P1","P2")
        self.assertAlmostEqual(collector.records()[0]["call_realized_bb"],20.0)
        self.assertAlmostEqual(collector.records()[0]["policy_realized_bb"],20.0)

    def test_invalid_contexts_are_explicitly_excluded(self):
        collector=RiverDecisionCollector(1,percent=100)
        view=scenario()
        cases=[
            ("flop",["P2"],20,[],"fold",90),
            ("turn",["P2"],20,[],"call",90),
            ("river",["P2","P3"],20,[],"fold",90),
            ("river",["P2"],0,[],"check",90),
            ("river",["P2"],20,["P3"],"fold",90),
            ("river",["P2"],20,[],"fold",10),
        ]
        for street, opponents, to_call, allins, action, stack in cases:
            with self.subTest(street=street, opponents=opponents, allins=allins):
                view.street=street
                view.opponents=opponents
                view.to_call=to_call
                view.all_in_opponents=allins
                view.stacks["P1"]=stack
                collector.observe(view,Action(action),[("3","c"),("4","c")],2,"P1","P2")
        self.assertEqual(collector.counts()["eligible"],0)
        self.assertEqual(collector.records(),[])

        view=scenario()
        collector.observe(view,Action("raise",70),[("3","c"),("4","c")],2,"P1","P2")
        self.assertEqual(collector.counts()["eligible"],1)
        self.assertEqual(collector.counts()["skipped_actions"],1)
        self.assertEqual(collector.records(),[])

    def test_deterministic_priority_sample_and_hard_memory_cap(self):
        collector1=RiverDecisionCollector(7,percent=100,max_samples=5)
        collector2=RiverDecisionCollector(7,percent=100,max_samples=5)
        for hid in range(100):
            view=scenario()
            view.hand_id=hid
            collector1.observe(view,Action("call"),[("3","c"),("4","c")],2,"P1","P2")
        for hid in reversed(range(100)):
            view=scenario()
            view.hand_id=hid
            collector2.observe(view,Action("call"),[("3","c"),("4","c")],2,"P1","P2")
        self.assertEqual(collector1.records(),collector2.records())
        self.assertEqual(len(collector1.records()),5)
        self.assertEqual(collector1.counts()["sampled_before_cap"],100)

    def test_no_hindsight_regret_and_oos_trained_on_other_tournaments(self):
        records=[]
        for tournament in range(40):
            for i in range(3):
                outcome=4.0 if i % 2 == 0 else -1.0
                records.append({
                    "bot":"P1", "opponent_profile":"random",
                    "tournament":tournament,
                    "hand_id":i,"hero_class":"pair","pot_odds_bucket":"20-35%",
                    "chosen":"fold","call_realized_bb":outcome,
                    "policy_realized_bb":0.0,
                })
        report=build_report(records,percent=100,collection_counts={"eligible":120})
        self.assertEqual(report["format"],FORMAT)
        self.assertEqual(report["overall"]["n"],120)
        self.assertEqual(report["overall"]["mean_policy_realized_bb"],0.0)
        self.assertAlmostEqual(report["overall"]["mean_always_call_realized_bb"],7/3,places=3)
        self.assertEqual(report["overall"]["out_of_sample_n"],120)
        self.assertAlmostEqual(report["overall"]["oos_delta_vs_policy_bb"],7/3,places=3)
        self.assertIsNotNone(report["overall"]["oos_delta_ci95_bb"])
        self.assertFalse(report["limits"]["single_hand_regret"])
        self.assertNotIn("regret_bb", report["examples"][0])

    def test_insufficient_data_reports_null_not_zero_ev_difference(self):
        report=build_report([
            {"bot":"P1","opponent_profile":"P2","tournament":1,
             "hand_id":3, "hero_class":"pair", "pot_odds_bucket":"20-35%",
             "chosen":"call","call_realized_bb":-5.0,
             "policy_realized_bb":-5.0},
        ])
        self.assertEqual(report["sample_count"],1)
        self.assertIsNone(report["overall"]["oos_delta_vs_policy_bb"])
        self.assertIsNone(report["overall"]["oos_delta_ci95_bb"])
        self.assertIsNone(report["overall"]["policy_ci95_bb"])
        self.assertEqual(build_report([])["sample_count"],0)

    def test_bet_raise_realized_only_from_current_stack(self):
        auditor=RiverAggressionCollector(17, percent=100)
        bet=scenario()
        bet.to_call=0
        bet.legal_actions=[{"type":"check"},{"type":"bet","min":2,"max":90}]
        bet.hand_id=201
        auditor.observe(bet,Action("bet",30),2,"GTO 5.4.1","Random")
        # Opponent folds to the actual bet; Hero wins current bank.
        auditor.settle(201, {"P1":190, "P2":0}, [
            {"street":"river","pid":"P1","type":"bet","amount":30},
            {"street":"river","pid":"P2","type":"fold"}])
        [first]=auditor.records()
        self.assertEqual(first["action"],"bet")
        self.assertEqual(first["opponent_response"],"fold")
        self.assertEqual(first["realized_bb"],50.0)  # (190 - 90) / 2
        self.assertEqual(first["amount_target_bb"],15.0)
        self.assertNotIn("regret_bb",first)
        self.assertNotIn("ev",first)
        self.assertNotIn("villain_hole",first)
        summary=aggression_report(auditor.records(),auditor.counts())
        self.assertEqual(summary["n"],1)
        self.assertTrue(summary["not_counterfactual"])
        self.assertIsNone(summary["by_bot_action"][0]["ci95_bb"])
        self.assertEqual(summary["by_bot_action"][0]["opponent_responses"]["fold"],1)

        raise_view=scenario()
        raise_view.hand_id=202
        raise_view.history=[{"street":"river","pid":"P2","type":"bet"}]
        raise_view.stacks["P1"]=80
        auditor.observe(raise_view,Action("raise",45),2,"GTO 5.4.1","Random")
        auditor.settle(202, {"P1":30, "P2":150}, [
            *raise_view.history,
            {"street":"river","pid":"P1","type":"raise","amount":45},
            {"street":"river","pid":"P2","type":"call"}])
        records=auditor.records()
        raised=next(x for x in records if x["action"]=="raise")
        self.assertEqual(raised["opponent_response"],"call")
        self.assertEqual(raised["realized_bb"],-25.0)
        self.assertEqual(raised["to_call_bb"],10.0)

    def test_aggression_coverage_not_mixed_with_call_fold(self):
        collector=RiverAggressionCollector(3,percent=100)
        view=scenario()
        collector.observe(view,Action("call"),2,"P1","P2")
        self.assertEqual(collector.counts()["eligible"],0)
        view.legal_actions=[{"type":"check"},{"type":"bet","min":2,"max":90}]
        view.to_call=0
        view.all_in_opponents=["P2"]
        collector.observe(view,Action("bet",10),2,"P1","P2")
        self.assertEqual(collector.counts()["eligible"],0)
        report=build_report([],percent=25,aggression_records=[{
            "bot":"P1","action":"bet","tournament":3,"hand_id":1,
            "realized_bb":2.0,"opponent_response":"fold",
        }])
        self.assertEqual(report["sample_count"],0)
        self.assertEqual(report["aggression"]["n"],1)
        self.assertNotIn("regret_bb",report["aggression"]["by_bot_action"][0])

    def test_engine_hook_fires_after_bot_decision_and_not_on_other_streets(self):
        class Toy:
            def act(self, view):
                legal={v["type"] for v in view.legal_actions}
                if view.street=="river" and "bet" in legal:
                    return Action("bet",2)
                if "call" in legal:
                    return Action("call")
                return Action("check")
        table=Table(rng=random.Random(29))
        auditor=RiverDecisionCollector(1,percent=100)
        events=[]
        def hook(view, action, villain_hole, big_blind):
            events.append((view.street,action.type,len(villain_hole)))
            auditor.observe(view,action,villain_hole,big_blind,
                            "P"+view.me,"toy")
        table.on_independent_river_decision=hook
        players={"P1":Toy(),"P2":Toy()}
        before=[Seat("P1",100),Seat("P2",100)]
        result=table.play_hand(before,small_blind=1,big_blind=2,
                               dealer_index=0,bot_for=players)
        self.assertEqual(sum(result.values()),0)
        self.assertTrue(events)
        self.assertTrue(all(street=="river" and size==2 for street,_,size in events))
        self.assertGreater(auditor.counts()["eligible"],0)
        self.assertTrue(auditor.records())
        self.assertTrue(all(r["chosen"] in ("call","fold") for r in auditor.records()))


if __name__=="__main__":
    unittest.main()
