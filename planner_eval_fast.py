"""Compact 7-card integer evaluator for the Plan Monte Carlo hot path.

Physical cards use rank*4+suit with ranks 2..A represented by 0..12.
The numeric score follows core.fast_eval's encoding and requires no table,
tuple conversion, Counter, sorting, or 21 five-card evaluations.
"""
from core.fast_eval import _straight_high, _pack


def score_seven_fast(cards):
    """Exact order-preserving 5–7 card Hold'em score."""
    counts = [0] * 13
    suits = [0, 0, 0, 0]
    mask = 0
    for card in cards:
        rank = card >> 2
        bit = 1 << rank
        counts[rank] += 1
        suits[card & 3] |= bit
        mask |= bit

    for suit_mask in suits:
        if suit_mask.bit_count() >= 5:
            sf = _straight_high(suit_mask)
            if sf >= 0:
                return (8 << 24) | sf
            flush = (5 << 24) | _pack(
                [r for r in range(12, -1, -1) if suit_mask & (1 << r)][:5])
            break
    else:
        flush = None

    for r in range(12, -1, -1):
        if counts[r] == 4:
            kicker = next(k for k in range(12, -1, -1) if k != r and counts[k])
            return (7 << 24) | _pack((r, kicker))

    trips = [r for r in range(12, -1, -1) if counts[r] >= 3]
    if trips:
        primary = trips[0]
        secondary = next((r for r in range(12, -1, -1)
                          if r != primary and counts[r] >= 2), -1)
        if secondary >= 0:
            return (6 << 24) | _pack((primary, secondary))
    if flush is not None:
        return flush

    straight = _straight_high(mask)
    if straight >= 0:
        return (4 << 24) | straight

    if trips:
        primary = trips[0]
        kickers = [r for r in range(12, -1, -1) if r != primary and counts[r]][:2]
        return (3 << 24) | _pack((primary, *kickers))
    pairs = [r for r in range(12, -1, -1) if counts[r] >= 2]
    if len(pairs) >= 2:
        p, q = pairs[:2]
        kicker = next(r for r in range(12, -1, -1) if counts[r] and r not in (p, q))
        return (2 << 24) | _pack((p, q, kicker))
    if pairs:
        p = pairs[0]
        kickers = [r for r in range(12, -1, -1) if counts[r] and r != p][:3]
        return (1 << 24) | _pack((p, *kickers))
    return _pack([r for r in range(12, -1, -1) if counts[r]][:5])
