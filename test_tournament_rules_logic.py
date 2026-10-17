"""Rules-level invariants for tournaments and legacy Hold'em settlements."""
import unittest
from unittest.mock import patch
from core.engine import Seat, Table
from core.tournament_rules import append_eliminations
from core.tournament import run_tournament


class TournamentLogicAuditTests(unittest.TestCase):
    def test_simultaneous_bust_order_is_independent_of_seat_order(self):
        for order in ("ABC","BAC","CAB"):
            seats=[Seat(pid, 100) for pid in order]
            starting={"A":100,"B":50,"C":200}
            for seat in seats:
                seat.chips=200 if seat.player_id=="C" else 0
            ranked=[]
            appended=append_eliminations(seats,ranked,starting,1,3)
            self.assertEqual({pid:pos for pid,pos,_,_ in appended},{"A":2,"B":3})

    def test_equal_stacks_same_hand_share_rank(self):
        seats=[Seat(pid,0) for pid in ("A","B","C","D")]
        seats[0].chips=100
        pre={"A":100,"B":50,"C":50,"D":20}
        ranked=append_eliminations(seats,[],pre,4,4)
        self.assertEqual({pid:pos for pid,pos,_,_ in ranked},
                         {"D":4,"B":2,"C":2})

    def test_active_circle_does_not_skip_next_button_after_bust(self):
        class ScriptTable:
            def __init__(self):
                self.hands=[]
            def play_hand(self,seats,**kw):
                ids=[s.player_id for s in seats]
                button=ids[kw["dealer_index"]]
                self.hands.append(button)
                if len(self.hands)==1:
                    next(s for s in seats if s.player_id=="A").chips=0
        table=ScriptTable()
        result=run_tournament([Seat(pid,100) for pid in "ABCD"],
                              {pid:object() for pid in "ABCD"},
                              small_blind=1,big_blind=2,max_hands=2,
                              dealer_rotation="active_circle",table=table,
                              suppress_output=True,
                              winner_resolution="finish_order")
        self.assertEqual(table.hands,["A","B"])
        self.assertIsNone(result["winner"])
        self.assertFalse(result["completed"])

    def test_dead_button_transitions_include_empty_sb_and_button(self):
        from core.dead_button import initial_blinds,next_blinds
        seats=[Seat(pid,100) for pid in "ABCD"]
        self.assertEqual(initial_blinds(seats,0),(0,1,2))
        seats[2].chips=0  # BB busts
        self.assertEqual(next_blinds(seats,2),(1,None,3))
        # Heads-up: the active button is SB, never a dead physical seat.
        seats[1].chips=0
        self.assertEqual(next_blinds(seats,3),(0,0,3))

    def test_dead_button_engine_can_play_without_small_blind(self):
        from core.bot_api import Action
        observed_views=[]
        class FoldBot:
            def act(self,view):
                observed_views.append((view.position,dict(view.stacks)))
                return Action("fold") if view.to_call else Action("check")
        seats=[Seat(pid,100) for pid in "ABCDE"]
        # Physical BTN B and SB C are busted; BB D must still post.
        seats[1].chips=seats[2].chips=0
        table=Table()
        observed=[]
        table.on_deal=lambda hid,hole,positions,n: observed.append(
            (dict(positions),n))
        net=table.play_hand(
            seats=seats,small_blind=1,big_blind=2,dealer_index=1,
            blind_seats=(None,3),
            bot_for={pid:FoldBot() for pid in "ADE"})
        self.assertEqual(sum(net.values()),0)
        self.assertEqual(observed[0][1],3)
        self.assertEqual(observed[0][0]["D"],"BB")
        self.assertNotIn("SB",observed[0][0].values())
        self.assertTrue(observed_views)
        self.assertTrue(all(len(stacks)==5 for _,stacks in observed_views))
        self.assertTrue(all(stacks["DEAD_BTN"]==stacks["DEAD_SB"]==0
                            for _,stacks in observed_views))

    def test_dead_button_tournament_advances_bb_through_elimination(self):
        from core.engine import Table as LegacyTable
        class MockLegacy(LegacyTable):
            def __init__(self): self.calls=[]
            def play_hand(self,seats,**kw):
                self.calls.append((kw["dealer_index"],kw["blind_seats"]))
                if len(self.calls)==1:
                    seats[2].chips=0
        table=MockLegacy()
        run_tournament([Seat(pid,100) for pid in "ABCD"],
                       {pid:object() for pid in "ABCD"},
                       small_blind=1,big_blind=2,max_hands=2,
                       dealer_rotation="dead_button",table=table,
                       suppress_output=True,winner_resolution="finish_order")
        self.assertEqual(table.calls,[(0,(1,2)),(1,(None,3))])

    def test_max_hands_cannot_fabricate_natural_winner(self):
        class NoActionTable:
            def play_hand(self,seats,**kw):
                pass
        table=NoActionTable()
        args=dict(seats=[Seat("A",100),Seat("B",100)],
                  bot_for={"A":object(),"B":object()},
                  small_blind=1,big_blind=2,max_hands=1,
                  dealer_rotation="full_table",table=table,
                  suppress_output=True)
        result=run_tournament(**args,winner_resolution="finish_order")
        self.assertEqual(result["hand_count"],1)
        self.assertIsNone(result["winner"])
        self.assertIsNone(result["winner_source"])
        self.assertFalse(result["completed"])

    def test_odd_chip_goes_clockwise_left_of_button(self):
        table=Table()
        hole={"C":[("A","s"),("A","h")],
              "A":[("A","d"),("A","c")],
              "B":[("2","h"),("3","h")]}
        board=[("4","c"),("5","c"),("6","c"),("8","h"),("K","s")]
        # Dict insertion C,A differs from clockwise button-first C,A,B.
        with patch("core.engine.eval_hand",side_effect=[20,20,10]):
            net=table._showdown_and_settle(hole,board,{"C":1,"A":1,"B":1},
                                            ["C","A","B"])
        self.assertEqual(net["A"],2)
        self.assertEqual(net["C"],1)
        self.assertEqual(net["B"],0)
        self.assertEqual(sum(net.values()),3)


if __name__=="__main__":
    unittest.main()
