"""Poker System selected 16 human-facing board features.

This is an educational/presentation adapter. Never replace the stable
P/S/F/SF Board75 IDs used for EV aggregation and simulation.
The workbook S2-gapped subtype requires an agreed rank-gap threshold:
until then, a two-rank S2 means an *adjacent* rank pair only.
"""
from itertools import combinations

LABELS = {
    "S1": "Нет выраженных стритовых признаков",
    "S2": "Коннекторы",
    "S3": "Три связанных ранга",
    "S4": "Четыре связанных ранга / стрит-дро",
    "S5": "Стрит на столе",
    "F2": "Две одной масти",
    "F3": "Три одной масти",
    "F4": "Четыре одной масти / флеш-дро",
    "F5": "Флеш на столе",
    "SF4": "Стрит-флеш-дро (1 или 2 выхода)",
    "SF5": "Стрит-флеш на столе",
    "P1": "Пара",
    "P2": "Две пары",
    "P3": "Тройка",
    "P3-2": "Фулл-хаус",
    "P4": "Каре",
}
assert len(LABELS) == 16

# Rank indices: 2 -> 0, ... K -> 11, A -> 12.
# Ace in A2345 is treated as a low card, and as high in TJQKA.
WINDOWS = tuple(
    tuple(12 if value == 1 else value - 2 for value in range(lo, lo + 5))
    for lo in range(1, 11)
)


def _outs(ranks):
    """Unique missing rank indices which complete 5 BOARD ranks in a window."""
    ranks = set(ranks)
    if any(set(window) <= ranks for window in WINDOWS):
        return []
    return sorted({
        next(iter(set(window) - ranks))
        for window in WINDOWS
        if len(set(window) & ranks) == 4
    })


def selected_features(board_ids, p, s, f, sf):
    """Return selected workbook labels, without altering canonical board IDs.

    S1/S2 split canonical S0 by an *adjacent* pair; broader gapped S2
    remains intentionally unclassified pending a formal workbook threshold.
    PP-only weights, HERO blockers and opponent ranges do not enter this
    board-only classifier; percent heuristics are not hard-coded.
    """
    ranks = {card // 4 for card in board_ids}
    by_suit = [{card // 4 for card in board_ids if card % 4 == suit}
               for suit in range(4)]
    adjacent = any(
        set(pair) <= ranks
        for window in WINDOWS
        for pair in zip(window, window[1:])
    )
    # Record potential 2-rank gapped patterns for auditing, not classification.
    gap_pairs = sorted({
        tuple(sorted((left, right)))
        for window in WINDOWS
        for left, right in combinations(window, 2)
        if 1 <= abs(window.index(right) - window.index(left)) - 1 <= 2
        and left in ranks and right in ranks
    })
    if s == 0:
        rank_code = "S2" if adjacent else "S1"
    elif s in (1, 2):
        rank_code = "S3"
    elif s in (3, 4):
        rank_code = "S4"
    else:
        rank_code = "S5"

    codes = [rank_code]
    if f >= 2:
        codes.append("F" + str(f))
    if sf in (3, 4):
        codes.append("SF4")
    elif sf == 5:
        codes.append("SF5")
    pairs = {1: "P1", 2: "P2", 3: "P3", 4: "P3-2", 5: "P4"}
    if p in pairs:
        codes.append(pairs[p])

    straight_outs = _outs(ranks) if rank_code == "S4" else []
    sf_outs = sorted({
        missing
        for suited_ranks in by_suit
        for missing in _outs(suited_ranks)
    }) if "SF4" in codes else []
    return {
        "codes": codes,
        "labels": {code: LABELS[code] for code in codes},
        "straight_completion_ranks": [rank + 2 for rank in straight_outs],
        "straight_completion_count": len(straight_outs),
        "straight_flush_completion_cards": [
            {"rank": missing + 2, "suit": suit}
            for suit, suited_ranks in enumerate(by_suit)
            for missing in _outs(suited_ranks)
        ] if "SF4" in codes else [],
        "straight_flush_completion_count": len(sf_outs),
        "s2_gapped_pairs_pending_definition": [
            [left + 2, right + 2] for left, right in gap_pairs
        ],
        "note": "Коды учебного слоя; базовый P/S/F/SF классификатор и EV неизменны.",
    }
