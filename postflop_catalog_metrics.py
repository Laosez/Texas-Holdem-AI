"""Exact next-two-card and villain-flop metrics for a *physical example*.

This is NOT range-averaged equity or a probability for the entire 1,019-class
bucket. The reference HERO and flop are fixed. Seven PC GTO 80bb RFI raising
ranges are weighted by their 0/25/50/75/100% chart frequencies.
No Monte Carlo, no bot actions, no hidden assumptions about villains.
"""
from collections import Counter
from itertools import combinations

from bots.pc_gto_80bb_ranges import HANDS, RAISE
from postflop_composite_classifier import parse_physical_hero
from flop_board_structure import parse_physical_flop

RANKS = "23456789TJQKA"
RANK_LABEL = {r: RANKS[r-2] for r in range(2,15)}
POSITIONS = ("UTG", "UTG1", "LJ", "HJ", "CO", "BTN", "SB")
PC_WEIGHTS = {
    pos: dict(zip(HANDS,weights)) for pos,weights in RAISE.items()
}
STREETS = tuple(
    {14,2,3,4,5} if low == 1 else set(range(low,low+5))
    for low in range(1,11)
)


def hand_class(hole):
    a,b=hole
    high,low=sorted((a[0],b[0]),reverse=True)
    if high==low:
        return RANK_LABEL[high]*2
    return RANK_LABEL[high]+RANK_LABEL[low]+(
        "s" if a[1]==b[1] else "o"
    )


def _straight(ranks):
    ranks=set(ranks)
    return any(window<=ranks for window in STREETS)


def made_category(cards):
    """Made-hand category of 5–7 known physical cards (0 high card .. 8 SF)."""
    counts=Counter(rank for rank,_ in cards)
    multiplicities=counts.values()
    suits=Counter(s for _,s in cards)
    flush_suits=[s for s,n in suits.items() if n>=5]
    if any(_straight(rank for rank,s in cards if s==suit)
           for suit in flush_suits):
        return 8
    if any(n>=4 for n in multiplicities):
        return 7
    trip_ranks=[r for r,n in counts.items() if n>=3]
    if trip_ranks and any(n>=2 for r,n in counts.items() if r!=trip_ranks[0]):
        return 6
    if flush_suits:
        return 5
    if _straight(counts):
        return 4
    if trip_ranks:
        return 3
    if sum(n>=2 for n in counts.values())>=2:
        return 2
    if any(n>=2 for n in counts.values()):
        return 1
    return 0


def opponent_connected(hole,board):
    """Board engagement = private pair or immediate flush/straight draw.

    A shared board pair by itself does NOT count; a pocket pair does count.
    On a 3-card flop, 4 connected distinct straight ranks always include an
    opponent hole card. Backdoor-only draws do not count.
    """
    board_ranks={rank for rank,_ in board}
    hole_ranks=[rank for rank,_ in hole]
    pair=hole_ranks[0]==hole_ranks[1] or any(r in board_ranks for r in hole_ranks)
    if pair:
        return True
    cards=tuple(hole)+tuple(board)
    if any(n>=4 for n in Counter(s for _,s in cards).values()):
        return True
    ranks={r for r,s in cards}
    if any(len(window&ranks)>=4 for window in STREETS):
        return True
    return False


def calculate_example_metrics(hero_text,board_text):
    hero=tuple(parse_physical_hero(hero_text))
    board=tuple(parse_physical_flop(board_text))
    if len(set(hero+board)) != 5:
        raise ValueError("HERO и борд содержат одну и ту же физическую карту")
    deck=((r,s) for r in range(2,15) for s in "shdc")
    remaining=[c for c in deck if c not in set(hero+board)]
    combos=tuple(combinations(remaining,2))
    assert len(combos)==1081
    flop_category=made_category(hero+board)
    improvement=sum(
        made_category(hero+board+(a,b))>flop_category
        for a,b in combos
    )
    villain_hits={key:0 for key in ("any",)+POSITIONS}
    villain_total={key:0 for key in ("any",)+POSITIONS}
    for hole in combos:
        hit=opponent_connected(hole,board)
        villain_total["any"]+=1
        villain_hits["any"]+=int(hit)
        cls=hand_class(hole)
        for pos in POSITIONS:
            # 0..4 quarter-units, physically weighted by legal combos.
            weight=PC_WEIGHTS[pos][cls]
            villain_total[pos]+=weight
            villain_hits[pos]+=weight*int(hit)
    opp={pos:(villain_hits[pos]/villain_total[pos]
              if villain_total[pos] else None)
         for pos in villain_total}
    return {"hero_improve":improvement/1081,
            "flop_category":flop_category,
            "opponent_contact":opp,
            "turn_river_combinations":1081}
