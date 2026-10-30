"""Selected 16-feature Poker System board taxonomy.

Public code is a composed group of selected features. P0 and SF0..SF3
are deliberately omitted. F1 is the exclusive fallback if NONE of the
other 15 chosen traits is present. This module never handles OPP probabilities.
"""
from collections import Counter

LABELS = {
    "F1": "Нет особых признаков",
    "S2": "Коннекторы",
    "S3": "Три связанных ранга (в том числе с дырками)",
    "S4": "Четыре связанных ранга (в том числе с дырками)",
    "S5": "Стрит на столе",
    "F2": "Две одной масти",
    "F3": "Три одной масти",
    "F4": "Четыре одной масти / флеш-дро",
    "F5": "Флеш на столе",
    "SF4": "Стрит-флеш-дро",
    "SF5": "Стрит-флеш на столе",
    "P1": "Пара",
    "P2": "Две пары",
    "P3": "Тройка",
    "P3-2": "Фулл-хаус",
    "P4": "Каре",
}
assert len(LABELS) == 16
WINDOWS = [tuple(12 if x == 1 else x - 2 for x in range(lo, lo + 5))
           for lo in range(1, 11)]


def _rank_outs(ranks):
    """Cards' rank indices making five on the BOARD, A-wheel supported."""
    r = set(ranks)
    if any(set(window) <= r for window in WINDOWS):
        return []
    return sorted({
        next(iter(set(window) - r))
        for window in WINDOWS if len(set(window) & r) == 4
    })


def classify_compact(board_ids, *, legacy_p=None, legacy_s=None,
                     legacy_f=None, legacy_sf=None):
    """Classify a physical flop, turn or river into selected P/S/F/SF codes.

    S2 is any *adjacent* two-rank connector (including A-2); mere gaps
    between two ranks are NOT enough, because the workbook dry-board
    example includes one-gap rank pairs. Gapped patterns are supported
    starting at S3, where at least 3 ranks fit a 5-rank straight window.
    """
    ids = tuple(board_ids)
    ranks = {card // 4 for card in ids}
    suited = [{card // 4 for card in ids if card % 4 == suit}
              for suit in range(4)]
    if legacy_s is None or legacy_p is None or legacy_f is None or legacy_sf is None:
        rank_counts = sorted(Counter(card // 4 for card in ids).values(),
                             reverse=True)
        legacy_p = (5 if rank_counts[0] == 4 else
                    4 if rank_counts == [3, 2] else
                    3 if rank_counts[0] == 3 else
                    2 if rank_counts[:2] == [2, 2] else
                    1 if rank_counts[0] == 2 else 0)
        legacy_f = max(Counter(card % 4 for card in ids).values())
        legacy_s = _old_sequence(ranks)
        legacy_sf = max(_old_sequence(s) for s in suited)

    adjacent = any(
        left in ranks and right in ranks
        for window in WINDOWS for left, right in zip(window, window[1:])
    )
    straight = ("S5" if legacy_s == 5 else "S4" if legacy_s >= 3 else
                "S3" if legacy_s >= 1 else "S2" if adjacent else None)
    codes = [straight] if straight else []
    if legacy_f >= 2:
        codes.append("F" + str(legacy_f))
    if legacy_sf == 5:
        codes.append("SF5")
    elif legacy_sf >= 3:
        codes.append("SF4")
    pairs = {1: "P1", 2: "P2", 3: "P3", 4: "P3-2", 5: "P4"}
    if legacy_p:
        codes.append(pairs[legacy_p])
    if not codes:
        codes = ["F1"]

    straight_outs = _rank_outs(ranks) if straight == "S4" else []
    sf_outs = [
        {"rank": missing + 2, "suit": suit}
        for suit, suited_ranks in enumerate(suited)
        if "SF4" in codes
        for missing in _rank_outs(suited_ranks)
    ]
    return {
        "id": " · ".join(codes),
        "codes": codes,
        "labels": {c: LABELS[c] for c in codes},
        "straight_completion_ranks": [r + 2 for r in straight_outs],
        "straight_completion_count": len(straight_outs),
        "straight_flush_completion_cards": sf_outs,
        "straight_flush_completion_count": len(sf_outs),
    }


def _old_sequence(ranks):
    """Compute internal strong-category ranking; not an exposed old code."""
    mask = 0
    for rank in ranks:
        mask |= 1 << rank
    best = (0, 0)
    for window in WINDOWS:
        flags = [(mask >> x) & 1 for x in window]
        n = sum(flags)
        if n == 5:
            return 5
        if n == 4:
            strength = (4, 2 if all(flags[:4]) or all(flags[1:]) else 1)
        elif n == 3:
            strength = (3, 2 if any(all(flags[i:i + 3]) for i in range(3)) else 1)
        else:
            continue
        if strength > best:
            best = strength
    return {(0, 0): 0, (3, 2): 1, (3, 1): 2,
            (4, 2): 3, (4, 1): 4}[best]
