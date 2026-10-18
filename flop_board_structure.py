"""Independent, exhaustive 46-class flop BOARD taxonomy (not HERO strategy).

Accepts exactly three physical cards. Relative suit location HM/HL/ML is
intentionally NOT a classifier dimension. Abstract s/z/y numeric shorthand
does not establish the full physical board and must never be inferred here.
"""
from collections import Counter
from itertools import combinations
import re

SUITS = frozenset("shdc")
RANKS = frozenset(range(2, 15))
FOUR_WINDOWS = [set(range(lo, lo + 4)) for lo in range(2, 12)] + [
    {14, 2, 3, 4}
]
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
    "three_consecutive": "Три подряд",
    "three_with_one_gap": "Три из четырёх, одна дырка",
    "three_with_two_gaps": "Три из пяти, две дырки",
    "two_consecutive": "Две подряд, третья отдельно",
    "two_one_gap": "Две через ранг, третья отдельно",
    "unconnected": "Разрозненные",
}
CONNECTION_CODE = {
    "three_consecutive": "C3",
    "three_with_one_gap": "C4",
    "three_with_two_gaps": "C5",
    "two_consecutive": "C2",
    "two_one_gap": "G2",
    "unconnected": "D",
}
SUIT_CODE = {"rainbow": "R", "two_tone": "2S", "monotone": "3S"}
SUIT_NAME = {
    "rainbow": "радуга", "two_tone": "двухмастный (2s)",
    "monotone": "одномастный (3s)",
}
_PHYSICAL = re.compile(r"(1[0-4]|[2-9])([shdc])\Z")


def _near(a, b, gap):
    # Ace is high next to K/Q and low next to 2/3 (wheel).
    return abs(a - b) == gap or {a, b} == {14, gap + 1}


def _connection(ranks):
    if any(ranks == window for window in THREE_RUNS):
        return "three_consecutive"
    if any(ranks <= window for window in FOUR_WINDOWS):
        return "three_with_one_gap"
    if any(ranks <= window for window in STRAIGHT_WINDOWS):
        return "three_with_two_gaps"
    if any(_near(a, b, 1) for a, b in combinations(ranks, 2)):
        return "two_consecutive"
    if any(_near(a, b, 2) for a, b in combinations(ranks, 2)):
        return "two_one_gap"
    return "unconnected"


def parse_physical_flop(text):
    """Strict 14s-7h-2d text; each physical suit must be specified."""
    if not isinstance(text, str) or len(text) > 100:
        raise ValueError("Введите три физические карты, например 14s-7h-2d")
    raw = [word for word in re.split(r"[\s,;\-]+", text.strip()) if word]
    if len(raw) != 3:
        raise ValueError("Для флопа нужны ровно три карты с мастями s/h/d/c")
    cards = []
    for word in raw:
        found = _PHYSICAL.fullmatch(word.lower())
        if not found:
            raise ValueError("Нужны реальные масти s/h/d/c у каждой карты: 14s-7h-2d")
        cards.append((int(found.group(1)), found.group(2)))
    return cards


def classify_flop_board(cards):
    """Exactly one of 46 groups, without looking at HERO or assigning EV.

    Valid input is three distinct physical (rank 2..14, suit s/h/d/c) tuples.
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
    rank_shape = ("trips" if len(rank_counts) == 1
                  else "paired" if len(rank_counts) == 2 else "distinct")
    suit_shape = ("monotone" if len(suit_counts) == 1
                  else "two_tone" if len(suit_counts) == 2 else "rainbow")
    key = (rank_shape, suit_shape)
    if key not in BOARD_TYPES:
        raise ValueError("Физически невозможное сочетание номиналов и мастей")
    ranks = set(rank_counts)
    ace = 14 in ranks
    connection, pair_position, pair_gap = None, None, None
    if rank_shape == "distinct":
        connection = _connection(ranks)
        group_id = ("A" if ace else "N") + "-" + CONNECTION_CODE[connection] + "-" + SUIT_CODE[suit_shape]
        group_name = ("С тузом" if ace else "Без туза") + " · " + RANK_CONNECTIONS[connection] + " · " + SUIT_NAME[suit_shape]
    elif rank_shape == "paired":
        pair = next(r for r, n in rank_counts.items() if n == 2)
        singleton = next(r for r, n in rank_counts.items() if n == 1)
        pair_position = "high_pair" if pair > singleton else "low_pair"
        pair_gap = abs(pair - singleton)
        variant = ("AA" if pair == 14 else "AX" if singleton == 14
                   else "H" if pair_position == "high_pair" else "L")
        group_id = "P-" + variant + "-" + SUIT_CODE[suit_shape]
        group_name = {
            "AA": "Пара тузов", "AX": "Туз отдельно от пары",
            "H": "Старшая пара без туза", "L": "Младшая пара без туза",
        }[variant] + " · " + SUIT_NAME[suit_shape]
    else:
        group_id = "T-" + ("A" if ace else "X")
        group_name = "Тройка тузов" if ace else "Тройка на борде без туза"
    return {
        "id": rank_shape + "_" + suit_shape,
        "name": BOARD_TYPES[key],
        "group_id": group_id,
        "group_name": group_name,
        "rank_shape": rank_shape,
        "suit_shape": suit_shape,
        "is_ace": ace,
        "high_rank": max(ranks),
        "connection": connection,
        "connection_name": RANK_CONNECTIONS[connection] if connection else None,
        "pair_position": pair_position,
        "pair_gap": pair_gap,
        "wheel_ace": rank_shape == "distinct" and ace and ranks <= {14, 2, 3, 4, 5},
        "broadway_count": sum(rank >= 10 for rank in ranks),
    }


def classify_flop_request(payload):
    if not isinstance(payload, dict):
        raise ValueError("Ожидается JSON-объект")
    cards = parse_physical_flop(payload.get("board"))
    result = classify_flop_board(cards)
    result["board"] = "-".join(str(rank) + suit for rank, suit in cards)
    return result
