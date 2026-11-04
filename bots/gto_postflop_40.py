"""GTO 4.0: board-relative range EV on flop, turn and river.

Experimental, human-reproducible decision skeleton:
1) Board classifier + Any Two distribution (sampled from legal unknown cards).
2) Assume opponents act with stronger hands first (not a calibrated read).
3) Use the 24 street-specific frequencies in GTO 3.3 to select quantiles.
4) Compare Bet/Check EV or Call/Fold equity against pot odds.

On flop/turn, equity is a deterministic SAMPLE of possible showdown runouts;
draws enter both the opponent strength proxy (hit-out probability) and real
sampled showdown outcomes. River scores are exact for each sampled hand.
This is a simplified one-street checkdown chipEV calculation, not a poker
solver, and never sees an opponent's actual private cards.

The 3.3 memory is reused unchanged. If more than one opponent remains,
fall back to 3.3, because this implementation only models HU ranges.
"""
from __future__ import annotations

from collections import Counter, deque
from itertools import combinations
import random
import zlib

from bots.gto_postflop_33 import StreetMatrixGTO33Bot
from bots.gto_postflop_30 import _board_class, AdaptiveGTO30Bot
from bots.postflop_profiles import _amount, read_hand, _fallthrough
from core.bot_api import Action
from core.engine import eval_hand, _FULL_DECK

STREET_SAMPLES = {"flop": (48, 8), "turn": (64, 6), "river": (96, 1)}
CATEGORIES = ("high_card", "pair", "two_pair", "trips", "straight",
              "flush", "full_house", "quads", "straight_flush")


def _seed(cards):
    # Never rely on Python's randomized hash() or the global game RNG.
    raw = "|".join("".join(c) for c in cards)
    return zlib.crc32(raw.encode("ascii")) & 0xffffffff


def _hand_proxy(hole, board):
    """Current showdown rank plus a transparent improvement-outs bonus.

    The exact rank (including kickers) decides the river order. On earlier
    streets this heuristic uses category, kicker and approximate outs: it
    is NOT a claim about the opponent's real hand-strength percentile.
    """
    score = eval_hand(list(hole), list(board))
    category = min(8, score >> 24)
    packed = score & 0xFFFFFF
    denom = (15**5 if category == 0 else 15**4 if category == 1
             else 15**3 if category in (2, 3) else 15**2)
    within = min(.99, packed / denom)
    outs = min(15, max(0, read_hand(hole, board).draw_outs)) if len(board)<5 else 0
    if len(board) == 3:
        improve = 1 - (47-outs)*(46-outs)/(47*46)
    elif len(board) == 4:
        improve = outs / 46
    else:
        improve = 0.0
    # A high-card draw can outrank a high card, but doesn't automatically
    # outrank every made pair. Actual equity is calculated on runouts.
    return category + within + 1.6 * improve, category, outs


def _equity(hero, villain, board, deck, rng, trials):
    if len(board) == 5:
        hero_score = eval_hand(hero, board)
        opp_score = eval_hand(villain, board)
        return (1.0 if hero_score > opp_score else
                .5 if hero_score == opp_score else 0.0)
    unknown = [c for c in deck if c not in villain]
    future = 5-len(board)
    score = 0.0
    for _ in range(trials):
        completion = rng.sample(unknown, future)
        full_board = board + completion
        h = eval_hand(hero, full_board)
        o = eval_hand(villain, full_board)
        score += 1.0 if h>o else .5 if h==o else 0.0
    return score / trials


def _range_rows(hole, board):
    """Sample only visible-card-compatible opponent holdings.

    Exact number of possible opponents: 1081 flop, 1035 turn, 990 river.
    Use a fixed uniform sample for simulator throughput and disclose its
    size instead of pretending the estimator is exact.
    """
    hero = list(hole)
    board = list(board)
    known = set(hero + board)
    deck = [c for c in _FULL_DECK if c not in known]
    pairs = list(combinations(deck,2))
    samples,trials = STREET_SAMPLES[{3:"flop",4:"turn",5:"river"}[len(board)]]
    rng = random.Random(_seed(board+hero))
    chosen = rng.sample(pairs, min(samples,len(pairs)))
    rows=[]
    histogram = Counter()
    draws=0
    for opp in chosen:
        strength,category,outs = _hand_proxy(opp, board)
        equity = _equity(hero,list(opp),board,deck,rng,trials)
        histogram[CATEGORIES[category]]+=1
        draws += bool(outs >= 4)
        rows.append((strength,equity))
    rows.sort(key=lambda row: row[0])
    n = len(rows)
    return rows, {
        "possible_hands":len(pairs),
        "sampled_hands":n,
        "runouts_per_hand":trials,
        "categories_pct":{
            cat:round(100*histogram.get(cat,0)/n,1)
            for cat in CATEGORIES
        },
        "draws_4plus_pct":round(100*draws/n,1),
    }


def _range_equity(rows, low=0.0, high=1.0):
    """Equity versus a strength-quantile band, including partial edge bins."""
    low=max(0.0,min(1.0,low))
    high=max(low,min(1.0,high))
    if not rows or high<=low:
        return 0.5
    n=len(rows)
    num=den=0.0
    for i,(_,eq) in enumerate(rows):
        weight=max(0.0,min(high,(i+1)/n)-max(low,i/n))
        if weight:
            num+=weight*eq
            den+=weight
    return num/den if den else .5


def _opponent_action(view):
    """Most recent live bet/raise by this HU villain on the current street."""
    opp=set(str(p) for p in (view.opponents or ()))
    for event in reversed(view.history or ()):
        if (isinstance(event,dict) and event.get("street")==view.street and
                event.get("type") in ("bet","raise") and
                str(event.get("pid")) in opp):
            return event["type"]
    return None


class StreetEVGTO40Bot(StreetMatrixGTO33Bot):
    """GTO 4.0/5 and /10: same memory, EV choices on ALL postflop streets."""

    def __init__(self, window=5):
        super().__init__(window=window)
        self.profile="gto_postflop_40_"+str(window)

    def act(self, view):
        street=view.street
        if street not in STREET_SAMPLES:
            raise ValueError("GTO 4.0 is postflop-only")
        self._active_street=street
        self.observe_hand(getattr(view,"hand_id",None),
                          getattr(view,"history",()),
                          getattr(view,"board",()),view.me)
        opponents=list(view.opponents or ())
        # Multiway modelling would need a joint range and side-pot EV.
        if len(opponents)!=1 or len(view.hole_cards or ())!=2 or len(view.board or ()) not in (3,4,5):
            action=super().act(view)
            if self.last_model:
                self.last_model["version"]="gto4.0_multiway_fallback_3.3"
            return action

        villain=str(opponents[0])
        matrix=self.street_matrix(villain)
        groups=matrix[street]
        available={s["type"]:s for s in (view.legal_actions or ())}
        pot=max(1,int(view.pot))
        call=max(0,int(view.to_call))
        board=list(view.board)
        hole=list(view.hole_cards)
        rows,distribution=_range_rows(hole,board)
        all_equity=_range_equity(rows)
        bet_p=groups["open"]["bet"]["p"]
        evs={}
        action=None
        band={}
        mode=""

        if call>0 and "call" in available and "fold" in available:
            last=_opponent_action(view)
            if last=="raise":
                # A raise is assumed to select the strongest share of hands
                # among the current street range; conditioning on prior
                # actions will be a separate experiment.
                fraction=groups["vs_bet"]["raise"]["p"]
                if sum(1 for e in (view.history or ())
                       if isinstance(e,dict) and e.get("street")==street and
                       e.get("type")=="raise")>=2:
                    fraction=groups["vs_raise"]["reraise"]["p"]
                mode="vs_raise"
            else:
                fraction=bet_p
                mode="vs_bet"
            fraction=max(.01,min(1.0,fraction))
            equity=_range_equity(rows,1-fraction,1)
            ev_call=equity*(pot+call)-call
            evs={"call":round(ev_call,3),"fold":0.0}
            action=Action("call" if ev_call>0 else "fold")
            band={"action_frequency":round(fraction,5),
                  "equity_vs_action":round(equity,5),
                  "pot_odds":round(call/(pot+call),5)}
        elif call==0 and "bet" in available and "check" in available:
            bet=_amount(view,.50)
            if bet is not None and bet.type=="bet":
                size=max(0,int(bet.amount))
                fold_p=groups["vs_bet"]["fold"]["p"]
                call_p=groups["vs_bet"]["call"]["p"]
                raise_p=groups["vs_bet"]["raise"]["p"]
                eq_call=_range_equity(rows,fold_p,fold_p+call_p)
                # Conservative: fold to a raise, even with a monster;
                # future re-raise branches are NOT in this one-step EV.
                ev_bet=(fold_p*pot+
                        call_p*(eq_call*(pot+2*size)-size)-
                        raise_p*size)
                ev_check=all_equity*pot
                evs={"bet":round(ev_bet,3),"check":round(ev_check,3)}
                action=bet if ev_bet>ev_check else Action("check")
                band={"fold":round(fold_p,5),"call":round(call_p,5),
                      "raise":round(raise_p,5),
                      "equity_vs_call":round(eq_call,5),
                      "equity_vs_anytwo":round(all_equity,5),
                      "bet_size":size}
                mode="bet_or_check"
        if action is None:
            # A restricted legal action set has no comparable EV choice.
            # Never force an illegal bet/raise.
            action=_fallthrough(view)
            mode="restricted_legal"

        self.last_model={
            "version":"gto4.0","mode":"gto40_"+mode,"adapted":True,
            "villain":villain,"street":street,
            "board_classifier":_board_class(board,street),
            "distribution":distribution,"street_matrix":matrix,
            "ev":evs,"decision_inputs":band,"opponents_count":1,
        }
        hand_id=getattr(view,"hand_id",None)
        if hand_id is not None:
            board_code=self.last_model["board_classifier"]
            step={
                "hand_id":hand_id, "street":street,
                "board":["".join(c) for c in board],
                "board150":board_code["id"] if board_code else None,
                "board_anytwo_rank_pair_pct":AdaptiveGTO30Bot._anytwo_board_risk(board),
                "hero_hole":["".join(c) for c in hole],
                "hero_tier":"EV", "hero_made":"range-based",
                "hero_draw_outs_estimate":read_hand(hole,board).draw_outs,
                "opponents_count":1,"decision":action.type,
                "amount_chips":action.amount,
                "decision_mode":"gto40_"+mode,"street_matrix":matrix,
                "opponents":[{"pid":villain,"n":max(
                    v["n"] for g in groups.values() for v in g.values()),
                    "fold":round(groups["vs_bet"]["fold"]["p"]*100,1),
                    "call":round(groups["vs_bet"]["call"]["p"]*100,1),
                    "raise":round(groups["vs_bet"]["raise"]["p"]*100,1),
                    "pooled_streets":False}],
                "ev":evs,"equity_model":band,"distribution":distribution,
                "reason":"GTO 4.0: Any Two board distribution + street action frequencies + sampled showdown equity (checkdown model)",
            }
            if not self._trace or self._trace[-1]["hand_id"]!=hand_id:
                self._trace.append({"hand_id":hand_id,"steps":[]})
            self._trace[-1]["steps"].append(step)
        return action
