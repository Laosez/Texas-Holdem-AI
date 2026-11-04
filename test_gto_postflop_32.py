"""GTO 3.2 per-metric opportunity memory and engine integration tests."""
import os
import random
import unittest
from unittest.mock import patch

from bots import create_bot
from bots.gto_postflop_32 import OpportunityGTO32Bot
from core.engine import Seat, Table
from test_postflop_profiles import make_view
import replit_simulator as app


FLOP = [("K", "c"), ("Q", "d"), ("3", "h")]


def entry(street, pid, action, call=0, legal=None):
    if legal is None:
        legal = (("fold", "call", "raise") if call
                 else ("check", "bet"))
    return {"street":street, "pid":pid, "type":action,
            "to_call_before":call, "pot_before":30,
            "legal_types":list(legal)}


class GTO32Tests(unittest.TestCase):
    def test_registry_and_explicit_windows(self):
        catalog = app.strategy_catalog()
        for size in (5, 10):
            name = f"gto_postflop_32_{size}"
            self.assertIn(name, catalog["postflop_strategies"])
            self.assertIn(name, catalog["postflop_profiles"])
            self.assertNotIn(name, catalog["preflop_strategies"])
            bot = create_bot(name)
            self.assertIsInstance(bot, OpportunityGTO32Bot)
            self.assertEqual(bot.window, size)
            self.assertEqual(create_bot("split:pc_gto_80bb:"+name)
                             .postflop_bot.window,size)
            self.assertIn(name,app.UI.read_text(encoding="utf-8"))
        self.assertIn("gto32Matrix",app.UI.read_text(encoding="utf-8"))
        with self.assertRaises(ValueError):
            OpportunityGTO32Bot(7)

    def test_rfi_exact_denominator_by_opportunity_not_hands(self):
        bot = OpportunityGTO32Bot(10)
        # 10 opportunities: four raises, six folds/limps.
        for i in range(10):
            action = "raise" if i in (0,2,5,9) else "fold"
            bot.observe_hand(i,[entry("preflop","P2",action,1)],FLOP,"P1")
        metric=bot.opponent_stats("P2")["metrics"]["rfi"]
        self.assertEqual((metric["k"],metric["n"],metric["raw"]),(4,10,.4))
        # 20 unrelated decisions (not RFI) cannot displace the RFI memory.
        for i in range(10,30):
            bot.observe_hand(i,[entry("flop","P2","check")],FLOP,"P1")
        metric=bot.opponent_stats("P2")["metrics"]["rfi"]
        self.assertEqual((metric["k"],metric["n"],metric["raw"]),(4,10,.4))
        self.assertEqual(bot.opponent_stats("P2")["metrics"]["bet_flop"]["n"],10)
        bot.observe_hand(30,[entry("preflop","P2","raise",1)],FLOP,"P1")
        self.assertEqual(bot.opponent_stats("P2")["metrics"]["rfi"]["k"],4)
        self.assertEqual(bot.opponent_stats("P2")["metrics"]["rfi"]["n"],10)
        bot.reset_memory()
        self.assertEqual(bot.opponent_stats("P2")["metrics"]["rfi"]["n"],0)

    def test_last_five_and_ten_are_independent_per_metric(self):
        small,large=OpportunityGTO32Bot(5),OpportunityGTO32Bot(10)
        for i in range(12):
            history=[entry("flop","P3","bet"),
                     entry("flop","P2","fold" if i >= 7 else "call",8,
                           ("fold","call","raise"))]
            for bot in (small,large):
                bot.observe_hand(i,history,FLOP,"P1")
        sm=small.opponent_stats("P2")["metrics"]["fold_to_bet"]
        lg=large.opponent_stats("P2")["metrics"]["fold_to_bet"]
        self.assertEqual((sm["n"],sm["k"],sm["raw"]),(5,5,1))
        self.assertEqual((lg["n"],lg["k"],lg["raw"]),(10,5,.5))

    def test_legal_raise_opportunity_excludes_all_in_and_duplicates(self):
        bot=OpportunityGTO32Bot(10)
        hist=[entry("flop","P3","bet"),
              entry("flop","P2","call",4,("fold","call"))]
        bot.observe_hand(1,hist[:1],FLOP,"P1")
        bot.observe_hand(1,hist,FLOP,"P1")
        bot.observe_hand(1,hist,FLOP,"P1")
        m=bot.opponent_stats("P2")["metrics"]
        self.assertEqual(m["raise_to_bet"]["n"],0)
        self.assertEqual(m["fold_to_bet"]["n"],1)
        self.assertEqual(m["call_to_bet"]["n"],1)
        # Older event without legal snapshot contributes no denominator.
        bot.observe_hand(2,[{"street":"flop","pid":"P2","type":"check",
                              "to_call_before":0}],FLOP,"P1")
        self.assertEqual(bot.opponent_stats("P2")["metrics"]["bet_flop"]["n"],0)

    def test_fold_to_raise_preflop_threebet_fourbet(self):
        bot=OpportunityGTO32Bot(10)
        hist=[entry("preflop","P3","raise",1),
              entry("preflop","P2","raise",6),
              entry("preflop","P3","raise",12),
              entry("preflop","P4","fold",25)]
        bot.observe_hand(1,hist,FLOP,"P1")
        m=bot.opponent_stats("P2")["metrics"]
        self.assertEqual((m["three_bet"]["n"],m["three_bet"]["k"]),(1,1))
        self.assertEqual((m["reraise"]["n"],m["reraise"]["k"]),(1,1))
        p3=bot.opponent_stats("P3")["metrics"]
        self.assertEqual((p3["four_bet"]["n"],p3["four_bet"]["k"]),(1,1))
        p4=bot.opponent_stats("P4")["metrics"]
        self.assertEqual((p4["fold_to_raise"]["n"],p4["fold_to_raise"]["k"]),(1,1))
        self.assertEqual(p4["fold_to_three_bet"]["n"],0)
        # Facing an actual 3-bet in a separate hand.
        bot.observe_hand(2,[entry("preflop","P3","raise",1),
                            entry("preflop","P2","raise",6),
                            entry("preflop","P4","fold",12)],FLOP,"P1")
        p4=bot.opponent_stats("P4")["metrics"]
        self.assertEqual((p4["fold_to_three_bet"]["n"],
                          p4["fold_to_three_bet"]["k"]),(1,1))

    def test_rfi_excludes_isolation_raise_after_limp(self):
        bot=OpportunityGTO32Bot(10)
        hist=[entry("preflop","P3","call",2),
              entry("preflop","P2","raise",2)]
        bot.observe_hand(1,hist,FLOP,"P1")
        self.assertEqual(bot.opponent_stats("P3")["metrics"]["rfi"]["n"],1)
        self.assertEqual(bot.opponent_stats("P2")["metrics"]["rfi"]["n"],0)

    def test_cbet_fold_cbet_and_flop_raise_reraise(self):
        bot=OpportunityGTO32Bot(10)
        hist=[entry("preflop","P3","raise",1),
              entry("preflop","P2","call",5),
              entry("flop","P2","check"),
              entry("flop","P3","bet"),
              entry("flop","P2","raise",7),
              entry("flop","P4","fold",15)]
        bot.observe_hand(1,hist,FLOP,"P1")
        p3=bot.opponent_stats("P3")["metrics"]
        p2=bot.opponent_stats("P2")["metrics"]
        p4=bot.opponent_stats("P4")["metrics"]
        self.assertEqual((p3["cbet"]["n"],p3["cbet"]["k"]),(1,1))
        self.assertEqual((p2["bet_flop"]["n"],p2["bet_flop"]["k"]),(1,0))
        self.assertEqual((p2["raise_flop"]["n"],p2["raise_flop"]["k"]),(1,1))
        # P4 is facing a raise, not a direct C-bet.
        self.assertEqual(p4["fold_to_cbet"]["n"],0)
        self.assertEqual((p4["fold_to_raise"]["n"],p4["fold_to_raise"]["k"]),(1,1))
        bot.observe_hand(2,[entry("preflop","P3","raise",1),
                            entry("flop","P3","bet"),
                            entry("flop","P2","fold",6)],FLOP,"P1")
        p2=bot.opponent_stats("P2")["metrics"]
        self.assertEqual((p2["fold_to_cbet"]["n"],p2["fold_to_cbet"]["k"]),(2,1))

    def test_anytwo_preflop_has_no_behavioral_denominators(self):
        bot=OpportunityGTO32Bot(5)
        history=[entry("preflop","P2","call",1),
                 entry("flop","P2","bet"),
                 entry("flop","P3","fold",6)]
        with patch.dict(os.environ,{"POKER_PREFLOP_PROTOCOL":"any_two_limp"}):
            bot.observe_hand(1,history,FLOP,"P1")
        self.assertEqual(bot.opponent_stats("P2")["metrics"]["rfi"]["n"],0)
        self.assertEqual(bot.opponent_stats("P2")["metrics"]["cbet"]["n"],0)
        self.assertEqual(bot.opponent_stats("P3")["metrics"]["fold_to_cbet"]["n"],0)
        self.assertEqual(bot.opponent_stats("P3")["metrics"]["fold_to_bet"]["n"],1)

    def test_no_data_and_multiway_identical_to_gto21(self):
        bot=OpportunityGTO32Bot(5)
        baseline=create_bot("gto_postflop_21")
        for street, board in (("flop",FLOP),("turn",FLOP+[("4","s")])):
            v=make_view(hole=(("A","s"),("A","d")),board=board,street=street,
                        pot=30,to_call=7)
            for roll in (.0,.3,.99):
                with patch("bots.postflop_profiles.random.random",return_value=roll):
                    self.assertEqual(bot.act(v),baseline.act(v))
                    self.assertEqual(bot.last_model["mode"],"gto21_fallback")
        bot.observe_hand(1,[entry("flop","P2","bet")]*5,FLOP,"P1")
        multi=make_view(opponents=("P2","P3"),board=FLOP)
        with patch("bots.postflop_profiles.random.random",return_value=.9):
            bot.act(multi)
        self.assertFalse(bot.last_model["adapted"])

    def test_fold_to_bet_from_other_players_drives_bluff(self):
        bot=OpportunityGTO32Bot(5)
        for i in range(3):
            bot.observe_hand(i,[entry("flop","P3","bet"),
                                entry("flop","P2","fold",6)],FLOP,"P1")
        v=make_view(hole=(("7","s"),("2","d")),board=FLOP,
                    opponents=("P2",),position="BB",pot=24)
        v.hand_id=90
        with patch("bots.gto_postflop_32.random.random",return_value=.1):
            out=bot.act(v)
        self.assertEqual((out.type,out.amount),("bet",12))
        self.assertEqual(bot.last_model["active_metric"],"fold_to_bet")
        self.assertEqual(bot.last_model["stats"]["metrics"]["fold_to_bet"]["n"],3)

    def test_pressure_requires_three_specific_opportunities(self):
        bot=OpportunityGTO32Bot(10)
        v=make_view(hole=(("K","s"),("J","d")),board=FLOP,
                    to_call=9,pot=25,opponents=("P2",))
        v.history=[entry("flop","P2","bet")]
        v.hand_id=100
        # 10 unrelated checks do NOT train the bet aggressiveness metric.
        for i in range(10):
            bot.observe_hand(i,[entry("flop","P2","check",legal=("check",))],
                             FLOP,"P1")
        with patch("bots.postflop_profiles.random.random",return_value=.9):
            base=create_bot("gto_postflop_21").act(v)
            prior=bot.act(v)
        self.assertEqual(base,prior)
        self.assertEqual(bot.last_model["mode"],"gto21_fallback")
        for i in range(20,23):
            bot.observe_hand(i,[entry("flop","P2","bet")],FLOP,"P1")
        v.hand_id=110
        with patch("bots.postflop_profiles.random.random",return_value=.9):
            out=bot.act(v)
        self.assertEqual(out.type,"call")
        self.assertEqual(bot.last_model["mode"],"gto32_defense")
        self.assertGreaterEqual(bot.last_model["pressure"]["observations"],3)

    def test_engine_exposes_legal_types_and_two_nine_player_smoke(self):
        with patch.dict(os.environ,{"POKER_PREFLOP_PROTOCOL":"any_two_limp"}):
            for n in (2,9):
                name="gto_postflop_32_5" if n==2 else "gto_postflop_32_10"
                bots={f"P{i}":create_bot("split:a17_preflop:"+name)
                      for i in range(1,n+1)}
                seen=[]
                table=Table(rng=random.Random(509+n))
                table.on_event=lambda *args,**kwargs:None
                original_observe=bots["P1"].observe_hand
                def recorder(hand_id,history,board,me):
                    seen.extend(dict(row) for row in history)
                    original_observe(hand_id,history,board,me)
                bots["P1"].observe_hand=recorder
                result=table.play_hand([Seat(pid,160) for pid in bots],
                                       small_blind=1,big_blind=2,
                                       dealer_index=0,bot_for=bots)
                self.assertEqual(sum(result.values()),0)
                self.assertEqual(set(result),set(bots))
                self.assertTrue(seen)
                self.assertTrue(all("legal_types" in row for row in seen))
                self.assertTrue(all(isinstance(row["legal_types"],list)
                                    for row in seen))


if __name__=="__main__":
    unittest.main()
