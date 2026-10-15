"""Independent postflop GTO-inspired and LAG profiles (not solver equilibria).

Both policies use the same observable information and evaluator. They differ in
value/protection frequencies, semibluffs, selective air bluffs and bet sizes.
They NEVER make a preflop decision; use in split:<pre>:<post> tournament seats.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import ceil
import random

from core.bot_api import Action, BotAdapter, acting_opponents_for

_RANK = {r:i for i,r in enumerate("23456789TJQKA",start=2)}
_STRAIGHTS = [set(range(i,i+5)) for i in range(2,11)] + [{14,2,3,4,5}]
_SUPPORTED = frozenset(("gto_postflop_v1","lag_postflop_v1"))


@dataclass(frozen=True)
class HandRead:
    made: str                     # monster / top_pair / weak_pair / air
    category: int                 # evaluator category, 0..8
    draw_outs: int                # raw rough outs, max 15
    backdoor: bool
    missed_draw: bool
    blocker: bool
    wet: bool


def _draws(hole, board):
    """Find live one-card straight/flush draws actually using hole cards."""
    if len(board)>=5:return (0,False)
    cards=list(hole)+list(board)
    ranks={_RANK[c[0]] for c in cards}
    hole_ranks={_RANK[c[0]] for c in hole}
    straight_completions=set()
    for window in _STRAIGHTS:
        common=window & ranks
        if len(common)==4 and common & hole_ranks:
            straight_completions |= window-common
    suit_counts=Counter(c[1] for c in cards)
    flush=any(count==4 and any(c[1]==suit for c in hole)
              for suit,count in suit_counts.items())
    # If our hand has both a flush and an OESD, cap correlated raw outs.
    outs=min(15,(9 if flush else 0)+4*len(straight_completions))
    backdoor=(len(board)==3 and not flush and
              any(suit_counts[suit]==3 and sum(c[1]==suit for c in hole)>=2
                  for suit in suit_counts))
    return (outs,backdoor)


def read_hand(hole, board) -> HandRead:
    """Conservative hand reading; never confuse a board-play with a value hand."""
    if len(hole)!=2 or len(board)<3:
        return HandRead("air",0,0,False,False,False,False)
    from core.engine import eval_hand
    category=eval_hand(list(hole),list(board))>>24
    board_category=eval_hand([],list(board))>>24 if len(board)==5 else 0
    board_play=(len(board)==5 and
                eval_hand(list(hole),list(board))==eval_hand([],list(board)))
    counts=Counter(c[0] for c in board)
    pocket=hole[0][0]==hole[1][0]
    pairs_on_board=sum(x==2 for x in counts.values())
    trips_on_board=any(x>=3 for x in counts.values())
    paired_hole=(pocket or any(c[0] in counts for c in hole))
    board_only_strength=(pairs_on_board>=2 or trips_on_board)
    top_board=max(_RANK[c[0]] for c in board)
    top_match=any(_RANK[c[0]]==top_board for c in hole)
    overpair=pocket and _RANK[hole[0][0]]>top_board
    # A pair or two pair that is entirely present on the board is *not*
    # a value raise. At river additionally compare exact board strength.
    if not board_play and category>=2 and (
            category>=4 or (paired_hole and not board_only_strength)
            or (len(board)==5 and category>board_category)):
        made="monster"
    elif not board_play and category==1 and paired_hole and (
            top_match or overpair):
        made="top_pair"
    elif not board_play and ((category==1 and paired_hole)
                             or (category>=2 and not board_only_strength
                                 and paired_hole)):
        made="weak_pair"
    else:
        made="air"
    draw_outs,backdoor=_draws(hole,board) if category<4 else (0,False)
    # A drawing hand on the turn which remains unmade is a missed river draw.
    prev_outs=_draws(hole,board[:4])[0] if len(board)==5 else 0
    missed_draw=bool(len(board)==5 and prev_outs and made=="air")
    suits=Counter(c[1] for c in board)
    blockers=any(_RANK[c[0]]==14 and suits[c[1]]>=3 for c in hole)
    values=sorted({_RANK[c[0]] for c in board})
    wet=(max(suits.values(),default=0)>=2 or
         any(abs(x-y)<=2 for x,y in zip(values,values[1:])))
    return HandRead(made,category,draw_outs,backdoor,missed_draw,blockers,wet)


def _to_call(view):return max(0,int(getattr(view,"to_call",0) or 0))
def _legal(view):return {s["type"]:s for s in (view.legal_actions or ()) if isinstance(s,dict)}
def _fallthrough(view,fold=False):
    legal=_legal(view)
    if fold and _to_call(view)>0 and "fold" in legal:return Action("fold")
    if _to_call(view)>0 and "call" in legal:return Action("call")
    if "check" in legal:return Action("check")
    if "fold" in legal:return Action("fold")
    return Action(next(iter(legal)) if legal else "check")


def _amount(view,fraction):
    legal=_legal(view);call=_to_call(view)
    kind="raise" if call>0 else "bet"
    spec=legal.get(kind)
    if spec is None:return None
    street=view.street;contrib=0
    for e in (view.history or ()):
        if not isinstance(e,dict) or e.get("street")!=street or e.get("pid")!=view.me:
            continue
        if e.get("type")=="call":
            contrib+=int(e.get("amount") or 0)
        elif e.get("type") in ("bet","raise"):
            contrib=int(e.get("amount") or 0)
    # Pot in PlayerView includes the opponent bet, not our call.
    target=contrib+call+ceil(max(1,int(view.pot)+call)*fraction)
    lo,hi=int(spec["min"]),int(spec["max"])
    if lo>hi:return None
    return Action(kind,max(lo,min(hi,target)))


def _opponents(view):
    live=list(getattr(view,"opponents",None) or ())
    if live:return max(1,len(live))
    return max(1,len(acting_opponents_for(view)))


def _was_aggressor(view):
    events=[e for e in (view.history or ())
            if isinstance(e,dict) and e.get("street")=="preflop"
            and e.get("type") in ("bet","raise","all_in")]
    return bool(events and events[-1].get("pid")==view.me)


def _in_position(view):
    return str(getattr(view,"position","")).upper() in ("BTN","CO","3","4","IP")


def _can_bluff(view):
    return _opponents(view)<=3 and not (
        getattr(view,"all_in_opponents",None) and
        not acting_opponents_for(view))


class PostflopProfileBot(BotAdapter):
    """Two distinct, static profile policies sharing card/equity approximations."""
    def __init__(self,profile:str):
        if profile not in _SUPPORTED:raise ValueError("Unknown postflop profile")
        self.profile=profile
        self.lag=profile=="lag_postflop_v1"

    def act(self,view):
        if view.street not in ("flop","turn","river"):
            raise ValueError("Postflop profile cannot decide preflop")
        cards=list(view.hole_cards or ())
        board=list(view.board or ())
        if len(cards)!=2 or len(board)<3:return _fallthrough(view)
        read=read_hand(cards,board)
        call=_to_call(view)
        n=_opponents(view)
        ip=_in_position(view)
        spr=(view.stacks.get(view.me,0) or 0)/max(1,int(view.pot))
        pot_odds=call/(max(1,int(view.pot))+call)
        # Diminish semibluffs in multiway pots and in low-SPR situations.
        multi=1/(1+.55*max(0,n-1))
        bluff_allowed=_can_bluff(view) and spr>.55
        pfr=_was_aggressor(view)
        street=view.street
        roll=random.random
        # Common sizing on value and bluffs; 0.33/0.66 small/large V1.
        size=(.33 if street=="flop" and not read.wet else .66
              if street=="flop" else .72 if street=="turn" else .78)
        if self.lag:size=(.65 if street=="flop" else .80 if street=="turn" else .95)
        # River 5-card made-hand decisions. Strong value is defined relative
        # to playing the board; one pair never treated as the nuts.
        if read.made=="monster":
            if call>0:
                freq=(.78 if self.lag else .57)*(1 if n==1 else .82)
                if roll()<freq:
                    bet=_amount(view,size)
                    if bet:return bet
                return _fallthrough(view)
            freq=.93 if self.lag else .80
            if roll()<freq:
                bet=_amount(view,size)
                if bet:return bet
            return _fallthrough(view)
        if read.made=="top_pair":
            if call>0:
                # Do not bluff-raise a one-pair bluff-catcher by default.
                return _fallthrough(view,fold=pot_odds>(.30 if self.lag else .25))
            freq=(.77 if self.lag else .58)*multi
            if roll()<freq:
                bet=_amount(view,size)
                if bet:return bet
            return _fallthrough(view)
        if read.made=="weak_pair":
            if call>0:
                return _fallthrough(view,fold=pot_odds>(.18 if self.lag else .14))
            if roll()<(.24 if self.lag else .09)*multi and street!="river":
                bet=_amount(view,size)
                if bet:return bet
            return _fallthrough(view)
        # Draws: raw 4/8/9/13/15 outs; intentionally conservative because
        # obtaining both cards for the price of one flop call is not assured.
        if street!="river" and read.draw_outs:
            draw_equity=read.draw_outs/(47 if street=="flop" else 46)
            if call>0:
                semi=(.54 if self.lag else .22)*multi
                if read.draw_outs>=8 and bluff_allowed and roll()<semi:
                    bet=_amount(view,size)
                    if bet:return bet
                if pot_odds<=draw_equity*(1.2 if self.lag else .95):
                    return _fallthrough(view)
                return _fallthrough(view,fold=True)
            freq=(.89 if self.lag else .59)*multi
            if bluff_allowed and roll()<freq:
                bet=_amount(view,size)
                if bet:return bet
            return _fallthrough(view)
        # No made hand and no direct draw: selective c-bets and river bluffs.
        if call>0:
            # Avoid bluff-catching with air against bets. LAG may occasionally
            # use an ace blocker as a bluff-raise with a healthy SPR.
            if self.lag and bluff_allowed and street=="river" and read.blocker and ip:
                if roll()<.10*multi:
                    bet=_amount(view,size)
                    if bet:return bet
            return _fallthrough(view,fold=True)
        if not bluff_allowed:return _fallthrough(view)
        if street=="river":
            freq=(.40 if self.lag else .19) if read.missed_draw or read.blocker else (
                .14 if self.lag else .035)
        elif street=="flop":
            freq=(.67 if self.lag else .33) if pfr else (.29 if self.lag else .08)
            if not ip:freq*=.80
            if not read.wet and pfr:freq*=1.10
        else:
            freq=(.51 if self.lag else .19) if pfr else (.23 if self.lag else .06)
        if read.backdoor and street=="flop":freq*=1.25
        if roll()<min(.95,freq*multi):
            bet=_amount(view,size)
            if bet:return bet
        return _fallthrough(view)
