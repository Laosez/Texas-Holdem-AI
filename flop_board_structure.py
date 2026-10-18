"""Exhaustive FLOP-ONLY board texture taxonomy for physical three-card boards.

Deliberately separate from HERO+board scenario identification. The numeric
scenario input's abstract s/z/y groups do NOT specify all four actual suits;
it must not be passed here as if it were a physical deck.
"""
from collections import Counter
from itertools import combinations

SUITS = frozenset("shdc")
RANKS = frozenset(range(2, 15))
STRAIGHT_WINDOWS = [set(range(lo, lo + 5)) for lo in range(2, 11)] + [
    {14, 2, 3, 4, 5}
]
THREE_RUNS = [set(range(lo, lo + 3)) for lo in range(2, 13)] + [
    {14, 2, 3}
]
BOARD_TYPES = {
    ("distinct", "rainbow"): "Без пары · радуга",
    ("distinct", "two_tone"): "Без пары · двухмастный (2s)",
    ("distinct", "monotone"): "Без пары · одномастный (3s)",
    ("paired", "rainbow"): "Парный · радуга",
    ("paired", "two_tone"): "Парный · двухмастный (2s)",
    ("trips", "rainbow"): "Тройка на борде · радуга",
}
RANK_CONNECTIONS = {
    "three_consecutive": "Три карты подряд",
    "three_within_straight_window": "Три ранга в пятиранговом стрит-окне",
    "two_consecutive": "Только две соседние карты",
    "two_one_gap": "Только две карты через один ранг",
    "unconnected": "Разрозненные ранги",
}


def _near(a, b, gap):
    # Ace behaves as 14 for A-K and as 1 for A-2, A-3 on wheel boards.
    return abs(a - b) == gap or ({a, b} == {14, gap + 1})


def classify_flop_board(cards):
    """Return exact texture of 3 distinct REAL physical cards (rank, suit).

    Card tuples use rank 2..14, physical suits s/h/d/c.
    No hero cards, action assumptions or reconstructed/unknown suits.
    """
    if not isinstance(cards, (list, tuple)) or len(cards) != 3:
        raise ValueError("Структура флопа: необходимы ровно три карты")
    if any(not isinstance(c, (tuple, list)) or len(c) != 2 or
           type(c[0]) is not int or c[0] not in RANKS or c[1] not in SUITS
           for c in cards):
        raise ValueError("Карта: номинал 2–14 и физическая масть s/h/d/c")
    if len(set(map(tuple, cards))) != 3:
        raise ValueError("Во флопе не может повторяться одна физическая карта")
    rank_counts = Counter(r for r, _ in cards)
    suit_counts = Counter(s for _, s in cards)
    if len(rank_counts) == 1:
        rank_shape = "trips"
    elif len(rank_counts) == 2:
        rank_shape = "paired"
    else:
        rank_shape = "distinct"
    if len(suit_counts) == 1:
        suit_shape = "monotone"
    elif len(suit_counts) == 2:
        suit_shape = "two_tone"
    else:
        suit_shape = "rainbow"
    key = (rank_shape, suit_shape)
    if key not in BOARD_TYPES:
        raise ValueError("Физически невозможное сочетание номиналов и мастей")
    ranks = set(rank_counts)
    result = {
        "id": rank_shape + "_" + suit_shape,
        "name": BOARD_TYPES[key],
        "rank_shape": rank_shape,
        "suit_shape": suit_shape,
        "high_rank": max(ranks),
        "connection": None,
        "pair_position": None,
        "pair_gap": None,
    }
    if rank_shape == "distinct":
        if any(ranks == w for w in THREE_RUNS):
            connection = "three_consecutive"
        elif any(ranks <= w for w in STRAIGHT_WINDOWS):
            connection = "three_within_straight_window"
        elif any(_near(a, b, 1) for a, b in combinations(ranks, 2)):
            connection = "two_consecutive"
        elif any(_near(a, b, 2) for a, b in combinations(ranks, 2)):
            connection = "two_one_gap"
        else:
            connection = "unconnected"
        result["connection"] = connection
    elif rank_shape == "paired":
        pair = next(r for r, n in rank_counts.items() if n == 2)
        singleton = next(r for r, n in rank_counts.items() if n == 1)
        result["pair_position"] = "high_pair" if pair > singleton else "low_pair"
        result["pair_gap"] = abs(pair - singleton)
    return result
