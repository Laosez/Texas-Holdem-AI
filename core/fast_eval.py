"""Direct five-to-seven-card evaluator compatible with core.engine.eval_hand.

For 2 hole cards and a 3-, 4- or 5-card board, reproduce EXACTLY the
legacy integer score, including base-15 kickers and A-5 straight handling.
This module never imports the legacy 2.6-million-entry lookup table.
"""

_RANKS = '23456789TJQKA'
_SUITS = 'cdhs'
_CARD_INFO = {(r, s): (ri, si, 1 << ri) for ri, r in enumerate(_RANKS)
              for si, s in enumerate(_SUITS)}


def _straight_high(mask: int) -> int:
    """Highest straight's top rank index (3 for the five-high wheel), or -1."""
    for high in range(12, 3, -1):
        if (mask >> (high - 4)) & 31 == 31:
            return high
    if mask & 0x100f == 0x100f:
        return 3
    return -1


def _pack(ranks) -> int:
    value = 0
    for rank in ranks:
        value = value * 15 + rank
    return value


def fast_eval_hand(hole, board) -> int:
    """Evaluate best five cards among 5..7 cards, in legacy score encoding."""
    cards = list(hole) + list(board)
    if len(cards) < 5:
        # Preserve eval_hand preflop heuristic for drop-in behavior.
        ranks = [card[0] for card in hole]
        base = sum(_RANKS.find(r) if r in _RANKS else 0 for r in ranks)
        return base + (40 if len(ranks) == 2 and ranks[0] == ranks[1] else 0)
    if len(cards) > 7:
        raise ValueError('Expected at most seven cards')
    counts = [0] * 13
    suit_masks = [0, 0, 0, 0]
    rank_mask = 0
    for card in cards:
        rank, suit, bit = _CARD_INFO[tuple(card)]
        counts[rank] += 1
        rank_mask |= bit
        suit_masks[suit] |= bit

    # At most one suit can contain five cards among seven.
    for suit_mask in suit_masks:
        if suit_mask.bit_count() >= 5:
            straight_flush = _straight_high(suit_mask)
            if straight_flush >= 0:
                return (8 << 24) | straight_flush
            top_flush = [r for r in range(12, -1, -1) if suit_mask & (1 << r)][:5]
            flush_score = (5 << 24) | _pack(top_flush)
            break
    else:
        flush_score = None

    for rank in range(12, -1, -1):
        if counts[rank] == 4:
            kicker = next(r for r in range(12, -1, -1) if r != rank and counts[r])
            return (7 << 24) | _pack((rank, kicker))

    trips = [r for r in range(12, -1, -1) if counts[r] >= 3]
    if trips:
        triple = trips[0]
        pair = next((r for r in range(12, -1, -1)
                     if r != triple and counts[r] >= 2), -1)
        if pair >= 0:
            return (6 << 24) | _pack((triple, pair))

    if flush_score is not None:
        return flush_score

    straight = _straight_high(rank_mask)
    if straight >= 0:
        return (4 << 24) | straight

    if trips:
        triple = trips[0]
        kickers = [r for r in range(12, -1, -1) if r != triple and counts[r]][:2]
        return (3 << 24) | _pack((triple, *kickers))

    pairs = [r for r in range(12, -1, -1) if counts[r] >= 2]
    if len(pairs) >= 2:
        first, second = pairs[:2]
        kicker = next(r for r in range(12, -1, -1) if r != first and r != second and counts[r])
        return (2 << 24) | _pack((first, second, kicker))
    if pairs:
        pair = pairs[0]
        kickers = [r for r in range(12, -1, -1) if r != pair and counts[r]][:3]
        return (1 << 24) | _pack((pair, *kickers))

    high_cards = [r for r in range(12, -1, -1) if counts[r]][:5]
    return _pack(high_cards)
