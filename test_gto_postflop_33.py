"""GTO 3.3 street-matrix tests: 24 probabilities / 9 independent windows."""
import os
import random
import unittest
from unittest.mock import patch

from bots import create_bot
from bots.gto_postflop_33 import StreetMatrixGTO33Bot, GROUPS, STREETS
from core.engine import Seat, Table
from test_postflop_profiles import make_view
import replit_simulator as app


def event(street, pid, action, call=0, legal=None):
    if legal is None:
        legal = ("fold", "call", "raise") if call else ("check", "bet")
    return {
        "street": street, "pid": pid, "type": action,
        "to_call_before": call, "pot_before": 32,
        "legal_types": list(legal),
    }


def response(street, action, legal=None):
    return [
        event(street, "P3", "bet"),
        event(street, "P2", action, call=8, legal=legal),
    ]


class GTO33Tests(unittest.TestCase):
    def test_registration_and_24_probabilities(self):
        catalog = app.strategy_catalog()
        for window in (5, 10):
            name = "gto_postflop_33_" + str(window)
            if window == 5:
                self.assertIn(name, catalog["postflop_strategies"])
            else:
                self.assertNotIn(name, catalog["postflop_strategies"])
                self.assertTrue(app.available_postflop(name))
            self.assertIn(name, catalog["postflop_profiles"])
            self.assertNotIn(name, catalog["preflop_strategies"])
            bot = create_bot(name)
            self.assertIsInstance(bot, StreetMatrixGTO33Bot)
            self.assertEqual(bot.window, window)
            self.assertEqual(create_bot("split:a17_preflop:"+name).postflop_name, name)
            matrix = bot.street_matrix("P2")
            self.assertEqual(sum(len(outcomes) for st in matrix.values()
                                 for outcomes in st.values()), 24)
            self.assertEqual(len(matrix), 3)
            self.assertEqual([len(matrix[st]) for st in STREETS], [3, 3, 3])
            for street in STREETS:
                for group, actions in GROUPS.items():
                    self.assertEqual(tuple(matrix[street][group]), actions)
        page = app.UI.read_text(encoding="utf-8")
        self.assertIn('id="modelArchiveInfo"', page)
        self.assertNotIn('id="gto33Matrix"', page)

    def test_exact_three_contexts_and_action_translation(self):
        bot = StreetMatrixGTO33Bot(10)
        for street in STREETS:
            history = [
                event(street, "P2", "check"),
                event(street, "P3", "bet"),
                event(street, "P2", "raise", call=8),
                event(street, "P4", "raise", call=16),
                event(street, "P3", "fold", call=32),
            ]
            bot.observe_hand({"flop":1,"turn":2,"river":3}[street],
                             history, [], "P1")
        matrix = bot.street_matrix("P2")
        for street in STREETS:
            self.assertEqual(matrix[street]["open"]["check"]["k"], 1)
            self.assertEqual(matrix[street]["vs_bet"]["raise"]["k"], 1)
            self.assertEqual(matrix[street]["vs_raise"]["reraise"]["n"], 0)
        for street in STREETS:
            self.assertEqual(bot.street_matrix("P4")[street]["vs_raise"]["reraise"]["k"], 1)
            self.assertEqual(bot.street_matrix("P3")[street]["vs_raise"]["fold"]["k"], 1)

    def test_street_separation_and_probability_normalization(self):
        bot = StreetMatrixGTO33Bot(10)
        for i in range(10):
            bot.observe_hand(i,response("flop","fold"),[],"P1")
        for i in range(10,20):
            bot.observe_hand(i,response("turn","call"),[],"P1")
        m = bot.street_matrix("P2")
        self.assertEqual((m["flop"]["vs_bet"]["fold"]["k"],
                          m["flop"]["vs_bet"]["fold"]["n"]), (10,10))
        self.assertEqual((m["turn"]["vs_bet"]["fold"]["k"],
                          m["turn"]["vs_bet"]["fold"]["n"]), (0,10))
        self.assertGreater(m["flop"]["vs_bet"]["fold"]["p"],
                           m["turn"]["vs_bet"]["fold"]["p"])
        for street in STREETS:
            for group in GROUPS:
                self.assertAlmostEqual(
                    sum(x["p"] for x in m[street][group].values()), 1, places=4)
        self.assertEqual(m["river"]["vs_bet"]["fold"]["source"], "pooled_fallback")

    def test_windows_independent_and_unrelated_events_do_not_evict(self):
        small, large = StreetMatrixGTO33Bot(5), StreetMatrixGTO33Bot(10)
        for i in range(12):
            history = response("flop","fold" if i>=7 else "call")
            for bot in (small,large):
                bot.observe_hand(i, history, [], "P1")
        self.assertEqual(small.street_matrix("P2")["flop"]["vs_bet"]["fold"]["k"], 5)
        self.assertEqual(small.street_matrix("P2")["flop"]["vs_bet"]["fold"]["n"], 5)
        self.assertEqual(large.street_matrix("P2")["flop"]["vs_bet"]["fold"]["k"], 5)
        self.assertEqual(large.street_matrix("P2")["flop"]["vs_bet"]["fold"]["n"], 10)
        for i in range(20,40):
            small.observe_hand(i,[event("turn","P2","check")],[],"P1")
        self.assertEqual(small.street_matrix("P2")["flop"]["vs_bet"]["fold"]["k"], 5)
        self.assertEqual(small.street_matrix("P2")["flop"]["vs_bet"]["fold"]["n"], 5)

    def test_partial_legal_actions_are_not_full_opportunity(self):
        bot=StreetMatrixGTO33Bot(10)
        history=[
            event("flop","P2","check",legal=("check",)), # cannot bet
            event("flop","P3","bet"),
            event("flop","P2","fold",call=10,legal=("fold","call")), # cannot raise
            event("turn","P2","bet",legal=("check","bet")),
        ]
        bot.observe_hand(1,history,[],"P1")
        matrix=bot.street_matrix("P2")
        self.assertEqual(matrix["flop"]["open"]["check"]["n"],0)
        self.assertEqual(matrix["flop"]["vs_bet"]["fold"]["n"],0)
        self.assertEqual(matrix["turn"]["open"]["bet"]["n"],1)
        bot.observe_hand(1,history,[],"P1")
        self.assertEqual(bot.street_matrix("P2")["turn"]["open"]["bet"]["n"],1)

    def test_shrink_river_two_opportunities_using_other_streets(self):
        bot=StreetMatrixGTO33Bot(10)
        for i in range(8):
            bot.observe_hand(i,response("flop","call"),[],"P1")
        for i in range(8,10):
            bot.observe_hand(i,response("river","fold"),[],"P1")
        river=bot.street_matrix("P2")["river"]["vs_bet"]["fold"]
        self.assertEqual((river["k"],river["n"],river["pooled_n"]),(2,2,10))
        self.assertEqual(river["source"],"street_shrunk_to_other_streets")
        p_other = (0 + 4*.35) / (8+4)
        self.assertAlmostEqual(river["p"],(2+4*p_other)/(2+4),places=4)
        self.assertEqual(bot.street_matrix("P2")["turn"]["vs_bet"]["fold"]["source"],
                         "pooled_fallback")

    def test_no_adaptation_without_five_comparable_opportunities(self):
        bot=StreetMatrixGTO33Bot(10)
        base=create_bot("gto_postflop_32_10")
        for i in range(4):
            bot.observe_hand(i, response("flop","fold"),[],"P1")
        view=make_view(hole=(("7","s"),("2","d")),
                       board=(("K","c"),("Q","d"),("3","h")),
                       position="BB",pot=24)
        view.hand_id=80
        self.assertEqual(bot.opponent_stats("P2")["metrics"]["fold_to_bet"]["n"],0)
        with patch("bots.gto_postflop_32.random.random",return_value=.10), \
             patch("bots.postflop_profiles.random.random",return_value=.10):
            a=base.act(view)
            b=bot.act(view)
        self.assertEqual((a.type,a.amount),(b.type,b.amount))
        self.assertEqual(bot.last_model["mode"],"gto21_fallback")

    def test_street_memory_changes_bluff_but_keeps_gto32_formula(self):
        bot=StreetMatrixGTO33Bot(10)
        for i in range(10):
            bot.observe_hand(i,response("flop","fold"),[],"P1")
        view=make_view(hole=(("7","s"),("2","d")),
                       board=(("K","c"),("Q","d"),("3","h")),
                       position="BB",pot=24)
        view.hand_id=90
        with patch("bots.gto_postflop_32.random.random",return_value=.10):
            action=bot.act(view)
        self.assertEqual((action.type,action.amount),("bet",12))
        self.assertEqual(bot.last_model["mode"],"gto32_bet")
        self.assertEqual(bot.last_model["version"],"gto3.3")
        self.assertEqual(bot.last_model["active_metric"],"fold_to_bet")
        self.assertEqual(bot.last_model["stats"]["metrics"]["fold_to_bet"]["source"],
                         "street")

    def test_river_aggression_affects_river_call_not_flop(self):
        bot=StreetMatrixGTO33Bot(10)
        for i in range(10):
            bot.observe_hand(i,[event("river","P2","bet")],[],"P1")
        for i in range(10,15):
            bot.observe_hand(i,[event("flop","P2","check")],[],"P1")
        river=make_view(hole=(("K","s"),("J","d")),
                        board=(("K","c"),("Q","d"),("3","h"),("4","s"),("5","c")),
                        street="river",to_call=9,pot=25,opponents=("P2",),
                        history=[event("river","P2","bet")])
        river.hand_id=91
        flop=make_view(hole=(("K","s"),("J","d")),
                       board=(("K","c"),("Q","d"),("3","h")),
                       street="flop",to_call=9,pot=25,
                       opponents=("P2",),history=[event("flop","P2","bet")])
        flop.hand_id=92
        with patch("bots.postflop_profiles.random.random",return_value=.90):
            self.assertEqual(bot.act(river).type,"call")
            self.assertEqual(bot.last_model["mode"],"gto32_defense")
            self.assertEqual(bot.act(flop).type,"fold")
            self.assertEqual(bot.last_model["stats"]["metrics"]["bet_when_checked"]["source"],
                             "street")

    def test_real_engine_hu_and_nine_max_anytwo(self):
        with patch.dict(os.environ,{"POKER_PREFLOP_PROTOCOL":"any_two_limp"}):
            for n in (2,9):
                bots={f"P{i}":create_bot("split:a17_preflop:gto_postflop_33_"+(
                    "5" if i%2 else "10")) for i in range(1,n+1)}
                result=Table(rng=random.Random(903+n)).play_hand(
                    [Seat(pid,160) for pid in bots],small_blind=1,big_blind=2,
                    dealer_index=0,bot_for=bots)
                self.assertEqual(sum(result.values()),0)
                self.assertEqual(set(result),set(bots))
                self.assertEqual(bots["P1"].postflop_bot.profile,
                                 "gto_postflop_33_5")
                for bot in bots.values():
                    self.assertEqual(bot.postflop_bot.opponent_stats("P1")
                                     ["metrics"]["rfi"]["n"],0)


if __name__=="__main__":
    unittest.main()
