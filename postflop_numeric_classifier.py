"""Read-only, compact postflop scenario classifier for numeric 2..14 notation.

This module does not replace S100 V1 or alter any tournament bot. Unmarked
suits are intentionally not inferred; marked s/z/y represent abstract suit
groups only when needed to describe a scenario.
"""
from collections import Counter
import re

_RANK = re.compile(r"(1[0-4]|[2-9])([szy]?)\Z")
_PAIR = re.compile(r"(1[0-4]|[2-9])\1\Z")
_STREETS = {3: "flop", 4: "turn", 5: "river"}
_PREFIX = {"flop": "F", "turn": "T", "river": "R"}
_NAMES = {
    "flush_oesd": ("FDOESD", "Флеш-дро + OESD"),
    "flush_gutshot": ("FDGS", "Флеш-дро + гатшот"),
    "pair_flush_oesd": ("PFDOESD", "Пара + флеш-дро + OESD"),
    "pair_flush_gutshot": ("PFDGS", "Пара + флеш-дро + гатшот"),
    "top_pair_oesd": ("TPOESD", "Топ-пара + OESD"),
    "pair_oesd": ("POESD", "Пара + OESD"),
    "pair_gutshot": ("PGS", "Пара + гатшот"),
    "overcards_flush": ("OCFD", "Две оверкарты + флеш-дро"),
    "one_card_flush": ("1CFD", "Однокарточное флеш-дро"),
    "overcards_gutshot": ("OCGS", "Две оверкарты + гатшот"),
    "one_overcard": ("1OC", "Одна оверкарта"),
    "board_pair_overcards": ("PBOC", "Пара борда + две оверкарты"),
    "pocket_middle": ("PMID", "Карманная пара между картами борда"),
    "double_gutshot": ("DGS", "Двойной гатшот"),
    "air": ("AIR", "Воздух"),
    "overcards": ("OC", "Две оверкарты"),
    "backdoor_flush": ("BFD", "Бэкдор-флеш"),
    "flush_draw": ("FD", "Флеш-дро"),
    "missed_flush_draw": ("MFD", "Незакрывшееся флеш-дро"),
    "oesd": ("OESD", "Двустороннее стрит-дро"),
    "gutshot": ("GS", "Гатшот"),
    "top_pair": ("TP", "Топ-пара"),
    "middle_pair": ("MP", "Средняя пара"),
    "bottom_pair": ("BP", "Нижняя пара"),
    "top_pair_flush_draw": ("TPFD", "Топ-пара + флеш-дро"),
    "pair_flush_draw": ("PFD", "Пара + флеш-дро"),
    "overpair": ("OP", "Оверпара"),
    "underpair": ("UP", "Карманная пара ниже борда"),
    "board_pair": ("PB", "Пара борда"),
    "two_pair_own": ("2OWN", "Две собственные пары"),
    "two_pair_shared_high": ("2SH", "Сильные общие две пары"),
    "two_pair_shared_low": ("2SL", "Уязвимые общие две пары"),
    "two_pair_board": ("2BD", "Две пары на борде"),
    "two_pair_pocket_board": ("2PK", "Карманная + общая пара"),
    "set": ("SET", "Сет"),
    "trips": ("TRP", "Трипс"),
    "board_trips": ("BTR", "Тройка на борде"),
    "straight": ("STR", "Стрит"),
    "board_straight": ("BSTR", "Стрит на борде"),
    "flush": ("FL", "Флеш"),
    "full_house": ("FH", "Фулл-хаус"),
    "four_kind": ("4K", "Каре"),
    "straight_flush": ("SF", "Стрит-флеш"),
}


def _tokens(value, expected=None, board=False):
    if not isinstance(value, str) or len(value) > 100:
        raise ValueError("Карты нужно указать строкой, например: 14 12 / 14-7-2")
    raw = [v for v in re.split(r"[\s,;-]+", value.strip()) if v]
    if not board and len(raw) == 1 and _PAIR.fullmatch(raw[0]):
        rank = raw[0][:len(raw[0]) // 2]
        raw = [rank, rank]
    if len(raw) not in ((3, 4, 5) if board else (2,)):
        raise ValueError("HERO: две карты; борд: от трёх до пяти")
    cards = []
    for word in raw:
        match = _RANK.fullmatch(word)
        if not match:
            raise ValueError("Номиналы: 2–14, масти только s/z/y; пример 14s 12s")
        cards.append((int(match.group(1)), match.group(2)))
    return cards


def _straight_high(ranks):
    ranks = set(ranks)
    if 14 in ranks:
        ranks.add(1)
    return max((hi for hi in range(5, 15)
                if all(r in ranks for r in range(hi - 4, hi + 1))), default=0)


def _draw_type(hole, board):
    """Recognize one-card straight draws: OESD vs double-gutshot vs gutshot."""
    if len(board) == 5 or _straight_high([r for r, _ in hole + board]):
        return None
    ranks = {r for r, _ in hole + board}
    board_ranks = {r for r, _ in board}
    outs = [
        r for r in range(2, 15)
        if r not in ranks
        and _straight_high(ranks | {r})
        and not _straight_high(board_ranks | {r})
    ]
    if len(outs) >= 2:
        ordered = ranks | ({1} if 14 in ranks else set())
        for low in range(1, 11):
            if set(range(low, low + 4)).issubset(ordered):
                left, right = low - 1, low + 4
                if left == 1:
                    left = 14
                if left in outs and right in outs:
                    return "oesd"
        return "double_gutshot"
    return "gutshot" if outs else None


def _suit_status(hole, board):
    all_cards = hole + board
    suits = Counter(s for _, s in all_cards if s)
    owned = {s for _, s in hole if s}
    flush_suit = next((s for s, count in suits.items()
                       if count >= 5 and s in owned), None)
    sf = flush_suit is not None and bool(_straight_high(
        [r for r, s in all_cards if s == flush_suit]))
    draw_suit = next((s for s in owned if suits[s] == 4), None)
    draw_hole_cards = sum(s == draw_suit for _, s in hole) if draw_suit else 0
    backdoor = len(board) == 3 and any(suits[s] == 3 for s in owned)
    return sf, flush_suit is not None, draw_suit is not None, draw_hole_cards, backdoor


def _pair_class(hole, board, ranks, counts):
    board_counts = Counter(r for r, _ in board)
    hole_ranks = [r for r, _ in hole]
    pairs = sorted((r for r, n in counts.items() if n >= 2), reverse=True)
    if len(pairs) >= 2:
        best = pairs[:2]
        if sum(board_counts[r] >= 2 for r in best) == 2:
            return "two_pair_board"
        if hole_ranks[0] != hole_ranks[1] and all(
                r in best and board_counts[r] >= 1 for r in hole_ranks):
            return "two_pair_own"
        if hole_ranks[0] == hole_ranks[1] and hole_ranks[0] in best:
            return "two_pair_pocket_board"
        shared = [r for r in best if board_counts[r] >= 2]
        own = [r for r in best if r in hole_ranks and board_counts[r] == 1]
        if shared and own:
            highest_unpaired_board = max(
                (r for r, n in board_counts.items() if n == 1), default=0)
            if highest_unpaired_board > own[0]:
                return "two_pair_shared_low"
            return "two_pair_shared_high"
        return "two_pair_board"
    pair = pairs[0]
    if hole_ranks[0] == hole_ranks[1]:
        board_ranks = [r for r, _ in board]
        if pair > max(board_ranks):
            return "overpair"
        return "pocket_middle" if pair > min(board_ranks) else "underpair"
    if board_counts[pair] >= 2:
        return ("board_pair_overcards" if all(r > max(board_counts) for r in hole_ranks)
                else "board_pair")
    ranks_on_board = sorted(set(r for r, _ in board))
    if pair == ranks_on_board[-1]:
        return "top_pair"
    if pair == ranks_on_board[0]:
        return "bottom_pair"
    return "middle_pair"


def classify_numeric(hole_text, board_text):
    """Return exactly one scenario, without appended attribute flags.

    Omitted suits are unspecified and never silently used to infer a flush
    or flush draw. The user marks meaningful same-suit groups with s/z/y.
    """
    hole = _tokens(hole_text)
    board = _tokens(board_text, board=True)
    all_cards = hole + board
    ranks = [r for r, _ in all_cards]
    counts = Counter(ranks)
    if max(counts.values()) > 4:
        raise ValueError("В колоде не бывает больше четырёх карт одного номинала")
    tagged = [(r, s) for r, s in all_cards if s]
    if len(tagged) != len(set(tagged)):
        raise ValueError("Одна физическая карта указана дважды")
    suits = Counter(s for _, s in tagged)
    # One suit may contain five or more cards: that is how a flush is made.
    # The physical-card uniqueness check above prevents duplicate rank+suit.
    # A rank can appear in a given suit only once; generic tokens are
    # unconstrained except for the four-card rank limit above.
    street = _STREETS[len(board)]
    if any(count == 1 for count in suits.values()):
        raise ValueError("Буква масти ставится только для повторяющейся группы карт")
    sf, flush, four_suited, flush_hole_count, three_suited = _suit_status(hole, board)
    triples = sorted((r for r, n in counts.items() if n >= 3), reverse=True)
    pairs = sorted((r for r, n in counts.items() if n >= 2), reverse=True)
    board_ranks = [r for r, _ in board]
    straight_draw = _draw_type(hole, board)
    two_overcards = all(r > max(board_ranks) for r, _ in hole)
    one_overcard = sum(r > max(board_ranks) for r, _ in hole) == 1
    if sf:
        kind = "straight_flush"
    elif 4 in counts.values():
        kind = "four_kind"
    elif triples and any(r != triples[0] for r in pairs):
        kind = "full_house"
    elif flush:
        kind = "flush"
    elif _straight_high(ranks):
        kind = ("board_straight" if len(board) == 5
                and _straight_high(board_ranks) == _straight_high(ranks)
                else "straight")
    elif triples:
        trip = triples[0]
        bc = sum(r == trip for r, _ in board)
        hc = sum(r == trip for r, _ in hole)
        kind = "set" if hc == 2 and bc >= 1 else "trips" if hc else "board_trips"
    elif pairs:
        kind = _pair_class(hole, board, ranks, counts)
        if kind in ("top_pair", "middle_pair", "bottom_pair"):
            if four_suited and straight_draw in ("oesd", "double_gutshot"):
                kind = "pair_flush_oesd"
            elif four_suited and straight_draw == "gutshot":
                kind = "pair_flush_gutshot"
            elif four_suited:
                kind = "top_pair_flush_draw" if kind == "top_pair" else "pair_flush_draw"
            elif straight_draw in ("oesd", "double_gutshot"):
                kind = "top_pair_oesd" if kind == "top_pair" else "pair_oesd"
            elif straight_draw == "gutshot":
                kind = "pair_gutshot"
    elif four_suited:
        if straight_draw in ("oesd", "double_gutshot"):
            kind = "flush_oesd"
        elif straight_draw == "gutshot":
            kind = "flush_gutshot"
        elif street == "river":
            kind = "missed_flush_draw"
        elif two_overcards:
            kind = "overcards_flush"
        elif flush_hole_count == 1:
            kind = "one_card_flush"
        else:
            kind = "flush_draw"
    elif straight_draw == "double_gutshot":
        kind = "double_gutshot"
    elif straight_draw == "oesd":
        kind = "oesd"
    elif straight_draw == "gutshot":
        kind = "overcards_gutshot" if two_overcards else "gutshot"
    elif three_suited:
        kind = "backdoor_flush"
    else:
        kind = "overcards" if two_overcards else "one_overcard" if one_overcard else "air"
    abbreviation, name = _NAMES[kind]
    return {
        "scenario": {
            "id": _PREFIX[street] + "-" + abbreviation,
            "name": name,
            "street": street,
        },
        "hole": " ".join(f"{r}{s}" for r, s in hole),
        "board": "-".join(f"{r}{s}" for r, s in board),
    }


def classify_request(data):
    if not isinstance(data, dict):
        raise ValueError("Ожидается JSON-объект")
    return classify_numeric(data.get("hole"), data.get("board"))
