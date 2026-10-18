"""Composite flop scenario: physical HERO + board -> board structure + HERO hit.

No solver/bot integration: exactly one deterministic card scenario. A physical
deal is the canonical source of truth, never an inferred s/z/y representation.
"""
from collections import Counter
import re

from flop_board_structure import classify_flop_board, parse_physical_flop
from postflop_numeric_classifier import classify_numeric, _draw_type, _straight_high


_PHYSICAL = re.compile(r"(1[0-4]|[2-9])([shdc])\Z")
_RANK_NAMES = {14: "A", 13: "K", 12: "Q", 11: "J", 10: "10"}
_DRAW_NAMES = {
    "oesd": "двустороннее стрит-дро",
    "gutshot": "гатшот",
    "double_gutshot": "двойной гатшот",
}


def _rank_name(rank):
    return _RANK_NAMES.get(rank, str(rank))


def parse_physical_hero(value):
    """Accept exactly two literal physical cards, e.g. 9s-8s."""
    if not isinstance(value, str) or len(value) > 100:
        raise ValueError("HERO: укажите две физические карты, например 9s-8s")
    raw = [x for x in re.split(r"[\s,;\-]+", value.strip()) if x]
    if len(raw) != 2:
        raise ValueError("HERO: нужны ровно две физические карты с мастями s/h/d/c")
    cards = []
    for word in raw:
        match = _PHYSICAL.fullmatch(word.lower())
        if not match:
            raise ValueError("HERO: у каждой карты нужна физическая масть s/h/d/c")
        cards.append((int(match.group(1)), match.group(2)))
    if len(set(cards)) != 2:
        raise ValueError("Карты HERO должны быть различными физическими картами")
    return cards


def _legacy_notation(hero, board):
    """Only repeated physical suit groups get abstract tags s/z/y.

    This reproduces the existing numeric classifier's contract exactly. The
    two input classifiers therefore see the SAME five physically valid cards.
    """
    all_cards = hero + board
    counts = Counter(suit for _, suit in all_cards)
    repeated = list(dict.fromkeys(suit for _, suit in all_cards if counts[suit] >= 2))
    if len(repeated) > 3:
        raise ValueError("Слишком много различных повторяющихся мастей")
    names = dict(zip(repeated, "szy"))
    tokens = [str(rank) + names.get(suit, "") for rank, suit in all_cards]
    return " ".join(tokens[:2]), "-".join(tokens[2:])


def _rank_hit(hero, board):
    b = Counter(rank for rank, _ in board)
    h = [rank for rank, _ in hero]
    matched = [r for r in h if r in b]
    distinct = sorted(set(b), reverse=True)
    if h[0] == h[1]:
        rank = h[0]
        if b[rank] == 3:
            return ("pocket_quads", "Карманная пара образовала каре")
        if b[rank] == 2:
            return ("pocket_quads", "Карманная пара образовала каре")
        if b[rank] == 1:
            return ("pocket_set", "Карманная пара образовала сет")
        if rank > max(b):
            return ("pocket_overpair", "Карманная пара выше всех карт борда")
        if rank < min(b):
            return ("pocket_underpair", "Карманная пара ниже всех карт борда")
        return ("pocket_middle", "Карманная пара между картами борда")
    if len(matched) == 2:
        if h[0] == h[1]:
            raise AssertionError("Карманная пара обрабатывается отдельно")
        return ("two_hits", "Обе карты HERO совпали с номиналами борда")
    if matched:
        rank = matched[0]
        if b[rank] == 3:
            return ("board_quads", "HERO дополнил тройку борда до каре")
        if b[rank] == 2:
            return ("board_trips", "HERO дополнил пару борда до трипса")
        spot = "старшей" if rank == distinct[0] else (
            "нижней" if rank == distinct[-1] else "средней"
        )
        return ("top_pair" if spot == "старшей" else
                "bottom_pair" if spot == "нижней" else "middle_pair",
                "HERO образовал пару со " + spot + " картой борда")
    if len(distinct) == 1:
        return ("board_trips", "Совпадений нет · тройка целиком на борде")
    if len(distinct) == 2:
        return ("board_pair", "Совпадений нет · пара целиком на борде")
    highs = sum(rank > max(b) for rank in h)
    return ("two_overcards" if highs == 2 else "one_overcard" if highs == 1 else "no_pair",
            "Совпадений нет · " + ("две оверкарты" if highs == 2 else
                                     "одна оверкарта" if highs == 1 else "нет оверкарт"))


def _suit_hit(hero, board):
    b = Counter(s for _, s in board)
    h = Counter(s for _, s in hero)
    for suit in "shdc":
        total = b[suit] + h[suit]
        if h[suit] and total >= 5:
            return {"id":"made_flush", "name":"Готовый флеш", "hole_cards":h[suit],
                    "nut_draw":None, "suit":suit}
        if h[suit] and total == 4:
            board_and_hero_ranks = {
                rank for rank, s in hero + board if s == suit
            }
            highest_remaining = max(
                rank for rank in range(2, 15) if rank not in board_and_hero_ranks
            )
            best_hero = max(rank for rank, s in hero if s == suit)
            nut = best_hero > highest_remaining
            desc = ("двумя" if h[suit] == 2 else "одной") + " картой HERO"
            return {"id":"flush_draw_two" if h[suit] == 2 else "flush_draw_one",
                    "name":"Флеш-дро с " + desc + (" · натсовое" if nut else " · ненатсовое"),
                    "hole_cards":h[suit], "nut_draw":nut, "suit":suit}
    for suit in "shdc":
        if h[suit] and b[suit]+h[suit] == 3:
            return {"id":"backdoor_flush", "name":"Бэкдор-флеш", "hole_cards":h[suit],
                    "nut_draw":None, "suit":suit}
    return {"id":"no_flush_draw", "name":"Нет флеш-дро", "hole_cards":0,
            "nut_draw":None,"suit":None}


def _straight_hit(hero, board):
    ranks = [r for r, _ in hero + board]
    if _straight_high(ranks):
        return {"id":"made_straight", "name":"Готовый стрит"}
    draw = _draw_type(hero, board)
    return {"id":draw or "no_straight_draw",
            "name":_DRAW_NAMES.get(draw, "Нет готового стрит-дро")}


def _hole_kicker(hero, board, rank_hit_id):
    if rank_hit_id in ("top_pair", "middle_pair", "bottom_pair", "board_trips"):
        matches = {r for r, _ in board}
        unpaired = [r for r, _ in hero if r not in matches]
        if len(unpaired) == 1:
            return {"hole_rank":unpaired[0],
                    "name":"Вторая карта HERO: " + _rank_name(unpaired[0])}
    return {"hole_rank":None, "name":"Отдельный кикер не выделен"}


def classify_composite_flop(hero_text, board_text):
    """Classify a real 2+3 hand; return board, hit details and composite ID."""
    hero = parse_physical_hero(hero_text)
    board = parse_physical_flop(board_text)
    if len(set(hero + board)) != 5:
        raise ValueError("HERO и борд содержат одну и ту же физическую карту")
    board_info = classify_flop_board(board)
    old_hero, old_board = _legacy_notation(hero, board)
    made = classify_numeric(old_hero, old_board)["scenario"]
    rank_id, rank_name = _rank_hit(hero, board)
    suit_info = _suit_hit(hero, board)
    straight_info = _straight_hit(hero, board)
    kicker = _hole_kicker(hero, board, rank_id)
    composite_id = "F|" + board_info["group_id"] + "|" + made["id"][2:]
    return {
        "id": composite_id,
        "name": board_info["group_name"] + " × " + made["name"],
        "street": "flop",
        "hero": "-".join(str(r) + s for r,s in hero),
        "board_cards": "-".join(str(r) + s for r,s in board),
        "board": board_info,
        "hero_state": made,
        "hit": {
            "rank": {"id":rank_id, "name":rank_name},
            "suit": suit_info,
            "straight": straight_info,
            "kicker": kicker,
        },
    }


def classify_composite_request(payload):
    if not isinstance(payload, dict):
        raise ValueError("Ожидается JSON-объект")
    return classify_composite_flop(payload.get("hero"), payload.get("board"))
