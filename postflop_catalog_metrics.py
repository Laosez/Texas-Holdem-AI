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


# Explicit independent questions. Every key has a precise, testable event.
HERO_GOALS = (
    "improve_category",    # Existing baseline: stronger MADE-HAND category than flop
    "new_pair_either",     # At least one new board card matches either HERO rank
    "new_pair_high",       # At least one new board card matches higher HERO rank
    "new_pair_low",        # At least one new board card matches lower HERO rank
    "top_pair_plus",      # On river: own top board rank paired OR overpair OR >=2 pairs
    "pair_plus",          # Final made category pair+, includes board-only pairs
    "two_pair_plus",
    "trips_plus",
    "straight_plus",
    "flush_plus",
    "full_house_plus",
)
VILLAIN_GOALS = (
    "pair_or_draw",       # Backward compatible union
    "private_pair",       # Pocket pair or matches a flop rank; board-only pair excluded
    "top_pair_overpair",  # Best board rank matched, pair above board, or trips via pocket
    "two_pair_plus",     # Category >= two pair, requires private participation
    "trips_plus",        # Category >= three of a kind, requires private participation
    "flush_draw",        # Four suited cards, no made flush
    "straight_draw",     # At least four in five-rank window, no made straight
    "any_draw",
    "no_contact",        # None of those pair/draw events
)
RANGE_KEYS = ("any",)+POSITIONS


def _hero_goal_hit(goal, hero, flop, runout, flop_category, river_category):
    board = flop+runout
    hi=max(r for r,_ in hero)
    lo=min(r for r,_ in hero)
    river_ranks={r for r,_ in board}
    if goal=="improve_category":
        return river_category>flop_category
    if goal=="new_pair_either":
        return bool({r for r,_ in runout}&{hi,lo})
    if goal=="new_pair_high":
        return any(r==hi for r,s in runout)
    if goal=="new_pair_low":
        return any(r==lo for r,s in runout)
    if goal=="pair_plus":
        return river_category>=1
    if goal=="top_pair_plus":
        # The pocket pair may be an overpair; an own matched board card
        # must match the HIGHEST RANK of the final 5-card board.
        own_top_pair = any(r==max(river_ranks) for r,s in hero
                           if r in river_ranks)
        pocket_overpair=(hi==lo and hi>max(river_ranks))
        return river_category>=2 or own_top_pair or pocket_overpair
    category_floor={
        "two_pair_plus":2, "trips_plus":3, "straight_plus":4,
        "flush_plus":5, "full_house_plus":6,
    }.get(goal)
    if category_floor is None:
        raise ValueError("Неизвестная цель усиления HERO")
    return river_category>=category_floor


def _villain_goal_flags(hole, board):
    hole_ranks=[r for r,s in hole]
    board_ranks={r for r,s in board}
    highest=max(board_ranks)
    is_pocket=hole_ranks[0]==hole_ranks[1]
    matches=bool(set(hole_ranks)&board_ranks)
    private_pair=is_pocket or matches
    all_cards=hole+board
    category=made_category(all_cards)
    flush_draw=any(n==4 for n in Counter(s for r,s in all_cards).values()) and category<5
    rankset=set(r for r,s in all_cards)
    straight_draw=(category<4 and
                   any(len(window&rankset)>=4 for window in STREETS))
    draw=flush_draw or straight_draw
    board_has_trips=len(board_ranks)==1
    trip_on_board_only=board_has_trips and not private_pair
    top_pair_overpair=(
        (is_pocket and hole_ranks[0]>highest) or
        (matches and highest in hole_ranks) or
        (board_has_trips and matches)
    )
    flags={
        "private_pair":private_pair,
        "top_pair_overpair":top_pair_overpair,
        "two_pair_plus":category>=2 and not trip_on_board_only,
        "trips_plus":category>=3 and not trip_on_board_only,
        "flush_draw":flush_draw,
        "straight_draw":straight_draw,
        "any_draw":draw,
        "pair_or_draw":private_pair or draw,
        "no_contact":not(private_pair or draw),
    }
    return flags


def calculate_goal_metrics(hero_text, board_text):
    """Exact goal-conditioned rates for one real HERO + flop example.

    HERO: all C(47,2) turn/river runouts; no opponent range is specified.
    Villain: all C(47,2) physical hole hands, weighted by chosen PC 80bb
    RFI raise chart (or uniformly random). Hero blockers are excluded.
    Hero runout probabilities are NOT opponent-range conditional.
    """
    hero=tuple(parse_physical_hero(hero_text))
    board=tuple(parse_physical_flop(board_text))
    if len(set(hero+board))!=5:
        raise ValueError("HERO и флоп не могут содержать одну физическую карту дважды")
    excluded=set(hero+board)
    rest=tuple((r,s) for r in range(2,15) for s in "shdc" if (r,s) not in excluded)
    flop_cat=made_category(hero+board)
    hits=dict.fromkeys(HERO_GOALS,0)
    villain_hits={goal:dict.fromkeys(RANGE_KEYS,0) for goal in VILLAIN_GOALS}
    denominators=dict.fromkeys(RANGE_KEYS,0)
    count=0
    for a,b in combinations(rest,2):
        hole=(a,b)
        count+=1
        cat=made_category(hero+board+hole)
        for goal in HERO_GOALS:
            hits[goal]+=_hero_goal_hit(goal,hero,board,hole,flop_cat,cat)
        flags=_villain_goal_flags(hole,board)
        weights={"any":1}
        cls=hand_class(hole)
        for pos in POSITIONS:
            weights[pos]=PC_WEIGHTS[pos][cls]  # quarter units
        for pos,w in weights.items():
            denominators[pos]+=w
            if w:
                for goal in VILLAIN_GOALS:
                    if flags[goal]:
                        villain_hits[goal][pos]+=w
    if count!=1081:
        raise AssertionError("Ожидаются C(47,2)=1081 физических сочетаний")
    return {
        "hero_goals":{goal:hits[goal]/count for goal in HERO_GOALS},
        "villain_goals":{
            goal:{pos:(villain_hits[goal][pos]/denominators[pos]
                       if denominators[pos] else None)
                  for pos in RANGE_KEYS}
            for goal in VILLAIN_GOALS
        },
        "runouts":count,
    }
