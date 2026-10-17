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
    "top_pair_high_kicker": ("TPHK", "Топ-пара + старший кикер"),
    "top_pair_weak_kicker": ("TPWK", "Топ-пара + слабый кикер"),
    "top_pair_board_pair_high": ("TPBPHK", "Топ-пара + пара борда + старший кикер"),
    "top_pair_board_pair": ("TPBP", "Топ-пара + пара борда"),
    "top_pair_board_pair_weak": ("TPBPWK", "Топ-пара + пара борда + слабый кикер"),
    "top_pair_board_pair_board_kicker": ("TPBPBDK", "Топ-пара + пара борда + общий кикер"),
    "middle_pair_board_pair": ("MPBP", "Средняя пара + пара борда"),
    "bottom_pair_board_pair": ("BPBP", "Нижняя пара + пара борда"),
    "two_pair_board_high_kicker": ("2BDHK", "Две пары борда + старший кикер HERO"),
    "trips_high_kicker": ("TRPHK", "Трипс от пары борда + старший кикер"),
    "trips_weak_kicker": ("TRPWK", "Трипс от пары борда + слабый кикер"),
    "trips_board_kicker": ("TRPBDK", "Трипс от пары борда + общие кикеры"),
    "board_trips_high_kicker": ("BTRHK", "Тройка борда + старший кикер HERO"),
    "board_trips_board_kicker": ("BTRBDK", "Тройка борда + общие кикеры"),
    "straight_one_hole": ("STR1", "Стрит с одной картой HERO"),
    "straight_two_hole": ("STR2", "Стрит с двумя картами HERO"),
    "flush_one_hole": ("FL1", "Флеш с одной картой HERO"),
    "flush_two_hole": ("FL2", "Флеш с двумя картами HERO"),
    "flush_board": ("FLBD", "Флеш на борде"),
    "full_house_set": ("FHSET", "Фулл-хаус: сет + пара"),
    "full_house_trips": ("FHTRP", "Фулл-хаус: трипс + пара"),
    "full_house_board_trips": ("FHBTR", "Фулл-хаус: тройка борда + пара HERO"),
    "full_house_board": ("FHBD", "Фулл-хаус на борде"),
    "quads_pocket": ("4KPK", "Каре: карманная пара + пара борда"),
    "quads_trips": ("4KTRP", "Каре: тройка борда + карта HERO"),
    "quads_board": ("4KBD", "Каре на борде"),
    "straight_flush_one_hole": ("SF1", "Стрит-флеш с одной картой HERO"),
    "straight_flush_two_hole": ("SF2", "Стрит-флеш с двумя картами HERO"),
    "straight_flush_board": ("SFBD", "Стрит-флеш на борде"),
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


def _best_full_house(counts):
    """Highest available trips and a separate highest available pair."""
    triples = sorted((rank for rank, n in counts.items() if n >= 3), reverse=True)
    for trip in triples:
        pairs = [rank for rank, n in counts.items() if rank != trip and n >= 2]
        if pairs:
            return trip, max(pairs)
    return None


def _straight_hole_use(hole, board, high):
    window = {14, 2, 3, 4, 5} if high == 5 else set(range(high - 4, high + 1))
    return max(0, 5 - len(window & {r for r, _ in board}))


def _flush_rank_and_hole_use(hole, board, suit):
    """How many HERO cards are actually in the highest suited five cards."""
    options = sorted([(rank, 1) for rank, s in hole if s == suit] +
                     [(rank, 0) for rank, s in board if s == suit],
                     reverse=True)
    return sum(is_hole for _, is_hole in options[:5])


def _trips_kicker_kind(hole, board, trip):
    """Hero's paired-board trips with a materially contributing kicker."""
    other_hole = [r for r, _ in hole if r != trip]
    if not other_hole:
        return "trips"
    h = other_hole[0]
    top_two = sorted([r for r, _ in hole + board if r != trip], reverse=True)[:2]
    if h not in top_two:
        return "trips_board_kicker"
    if h >= 13:
        return "trips_high_kicker"
    return "trips_weak_kicker" if h <= 9 else "trips"


def _board_trips_kind(hole, board, trip):
    top_two = sorted([r for r, _ in hole + board if r != trip], reverse=True)[:2]
    highest_hole = max(r for r, _ in hole)
    if all(r not in top_two for r, _ in hole):
        return "board_trips_board_kicker"
    return "board_trips_high_kicker" if highest_hole >= 13 else "board_trips"


def _pair_kind(hole, board, counts):
    b = Counter(rank for rank, _ in board)
    h = [rank for rank, _ in hole]
    paired = sorted((rank for rank, n in counts.items() if n >= 2), reverse=True)
    top_board = max(b)
    if len(paired) >= 2:
        p0, p1 = paired[:2]  # Actual two highest pairs; lower ones do not play.
        selected = {p0, p1}
        if h[0] != h[1] and all(r in selected and b[r] == 1 for r in h):
            return "two_pair_own"
        shared = [r for r in selected if b[r] >= 2]
        own = [r for r in selected if r in h and b[r] == 1]
        if len(shared) == 2:
            board_fifth = max((r for r, n in b.items() if r not in selected), default=0)
            hole_fifth = max((r for r in h if r not in selected), default=0)
            return "two_pair_board_high_kicker" if hole_fifth > board_fifth else "two_pair_board"
        if h[0] == h[1] and h[0] in selected:
            return "two_pair_pocket_board"
        if len(shared) == 1 and len(own) == 1:
            matched = own[0]
            if matched == top_board:
                remaining_hole = [r for r in h if r != matched]
                hero_kicker = max(remaining_hole, default=0)
                other_board = max((r for r in b if r not in selected), default=0)
                if hero_kicker <= other_board:
                    return "top_pair_board_pair_board_kicker"
                if hero_kicker >= 13:
                    return "top_pair_board_pair_high"
                if hero_kicker <= 7:
                    return "top_pair_board_pair_weak"
                return "top_pair_board_pair"
            return ("middle_pair_board_pair" if matched > shared[0]
                    else "bottom_pair_board_pair")
        return "two_pair_board"
    pair = paired[0]
    if h[0] == h[1]:
        if pair > top_board:
            return "overpair"
        return "pocket_middle" if pair > min(b) else "underpair"
    if b[pair] >= 2:
        return "board_pair_overcards" if all(r > top_board for r in h) else "board_pair"
    if pair == top_board:
        kicker = next(r for r in h if r != pair)
        if kicker >= 11 and kicker > max((r for r in b if r != pair), default=0):
            return "top_pair_high_kicker"
        if kicker <= 7:
            return "top_pair_weak_kicker"
        return "top_pair"
    if pair == min(b):
        return "bottom_pair"
    return "middle_pair"


def _make_kind(hole, board, ranks, counts, street):
    b = Counter(r for r, _ in board)
    suits = Counter(s for _, s in hole + board if s)
    full = _best_full_house(counts)
    # Five known cards of one suit can be board-only; no HERO suit required.
    suited_sf = []
    suited_flush = []
    for suit, n in suits.items():
        if n >= 5:
            suited_flush.append(suit)
            high = _straight_high([r for r, s in hole + board if s == suit])
            if high:
                suited_sf.append((high, suit))
    if suited_sf:
        high, suit = max(suited_sf)
        hole_use = _straight_hole_use(
            [(r, s) for r, s in hole if s == suit],
            [(r, s) for r, s in board if s == suit], high)
        return ("straight_flush_board" if hole_use == 0
                else "straight_flush_one_hole" if hole_use == 1
                else "straight_flush_two_hole")
    quad = max((r for r, n in counts.items() if n >= 4), default=0)
    if quad:
        return ("quads_board" if b[quad] == 4
                else "quads_pocket" if b[quad] == 2 else "quads_trips")
    if full:
        trip, pair = full
        # The best full house can be completed entirely by the river board.
        board_full = _best_full_house(b)
        if board_full is not None and board_full >= full:
            return "full_house_board"
        return ("full_house_set" if b[trip] == 1
                else "full_house_trips" if b[trip] == 2
                else "full_house_board_trips")
    if suited_flush:
        # Two suited options cannot both have 5 cards within max 7.
        suit = suited_flush[0]
        used = _flush_rank_and_hole_use(hole, board, suit)
        return "flush_board" if used == 0 else "flush_one_hole" if used == 1 else "flush_two_hole"
    high = _straight_high(ranks)
    if high:
        needed = _straight_hole_use(hole, board, high)
        return "board_straight" if needed == 0 else "straight_one_hole" if needed == 1 else "straight_two_hole"
    triple = max((rank for rank, n in counts.items() if n >= 3), default=0)
    if triple:
        if b[triple] == 1:
            return "set"
        if b[triple] == 2:
            return _trips_kicker_kind(hole, board, triple)
        return _board_trips_kind(hole, board, triple)

    _, _, four_suited, flush_hole_count, three_suited = _suit_status(hole, board)
    draw = _draw_type(hole, board)
    bmax = max(r for r, _ in board)
    two_overcards = all(r > bmax for r, _ in hole)
    one_overcard = sum(r > bmax for r, _ in hole) == 1
    pairs = any(n >= 2 for n in counts.values())
    if pairs:
        kind = _pair_kind(hole, board, counts)
        if kind in ("top_pair", "top_pair_high_kicker", "top_pair_weak_kicker",
                    "middle_pair", "bottom_pair"):
            if four_suited and draw in ("oesd", "double_gutshot"):
                return "pair_flush_oesd"
            if four_suited and draw == "gutshot":
                return "pair_flush_gutshot"
            if four_suited:
                return "top_pair_flush_draw" if kind.startswith("top_pair") else "pair_flush_draw"
            if draw in ("oesd", "double_gutshot"):
                return "top_pair_oesd" if kind.startswith("top_pair") else "pair_oesd"
            if draw == "gutshot":
                return "pair_gutshot"
        return kind
    if four_suited:
        if draw in ("oesd", "double_gutshot"):
            return "flush_oesd"
        if draw == "gutshot":
            return "flush_gutshot"
        if flush_hole_count == 1:
            return "one_card_flush"
        if two_overcards:
            return "overcards_flush"
        return "flush_draw"
    if draw == "double_gutshot":
        return "double_gutshot"
    if draw == "oesd":
        return "oesd"
    if draw == "gutshot":
        return "overcards_gutshot" if two_overcards else "gutshot"
    if three_suited:
        return "backdoor_flush"
    return "overcards" if two_overcards else "one_overcard" if one_overcard else "air"


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
    kind = _make_kind(hole, board, ranks, counts, street)
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
