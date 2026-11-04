"""GTO 5.3: exact Any-Two within-category seniority through weighted rank routes.

No physical two-card opponent-hand enumeration: at most C(13+1, 2)=91
rank-pair groups. For board suits that can complete a flush, each group is
split into up to four analytic suit-availability weights. Hero blockers are
honoured. No Monte Carlo, runouts, opponent action-conditioning or range
posteriors. This changes r(category) only, not P(category) or decision EV.
"""
from collections import Counter

RANKS = "23456789TJQKA"
RANK_IDS = range(2, 15)
CATEGORIES = ("high_card", "pair", "two_pair", "trips", "straight",
              "flush", "full_house", "quads", "straight_flush")


def _rank(card):
    return RANKS.index(card[0]) + 2


def _choose_two(n):
    return n * (n - 1) // 2


def _straight_high(counts):
    """Highest valid five-rank straight; Ace may play low."""
    for high in range(14, 4, -1):
        ranks = (14, 2, 3, 4, 5) if high == 5 else range(high - 4, high + 1)
        if all(counts[r] for r in ranks):
            return high
    return 0


def _rank_key(ranks):
    """Lexicographic 5-card hand key for 5 to 7 ranks, without flushes."""
    counts = Counter(ranks)
    present = sorted(counts, reverse=True)
    quads = [r for r in present if counts[r] >= 4]
    trips = [r for r in present if counts[r] >= 3]
    pairs = [r for r in present if counts[r] >= 2]
    if quads:
        return (7, quads[0], next(r for r in present if r != quads[0]))
    if trips and any(r != trips[0] for r in pairs):
        return (6, trips[0], next(r for r in pairs if r != trips[0]))
    straight = _straight_high(counts)
    if straight:
        return (4, straight)
    if trips:
        return (3, trips[0], *[r for r in present if r != trips[0]][:2])
    if len(pairs) >= 2:
        return (2, pairs[0], pairs[1],
                next(r for r in present if r not in pairs[:2]))
    if pairs:
        return (1, pairs[0], *[r for r in present if r != pairs[0]][:3])
    return (0, *present[:5])


def _hand_key(ranks, focus_suit_ranks):
    """Return best 5-card rank key; only a potentially complete suit is needed."""
    key = _rank_key(ranks)
    if len(focus_suit_ranks) >= 5:
        straight = _straight_high(Counter(focus_suit_ranks))
        flush_key = ((8, straight) if straight else
                     (5, *sorted(focus_suit_ranks, reverse=True)[:5]))
        key = max(key, flush_key)
    return key


def hero_seniority_53(hole, board, category_mass=None, pocket_pair_pct=5.88):
    """Weighted, blocker-aware r within Hero's *current* made-hand category.

    category_mass/pocket_pair_pct are accepted for signature compatibility;
    the within-category estimate is uniform Any Two, not a range posterior.
    The separate distribution layer retains its existing category masses.
    """
    hole, board = list(hole), list(board)
    known = board + hole
    if len(hole) != 2 or len(board) not in (3, 4, 5):
        raise ValueError("Expected two Hero cards and a flop/turn/river board")
    if len(set(known)) != len(known):
        raise ValueError("Duplicate board/Hero card")

    board_suits = Counter(card[1] for card in board)
    suit, board_suit_count = board_suits.most_common(1)[0]
    board_ranks = [_rank(card) for card in board]
    board_focus = [_rank(card) for card in board if card[1] == suit]
    hero_key = _hand_key(
        [_rank(card) for card in known],
        [_rank(card) for card in known if card[1] == suit])
    category = hero_key[0]

    used = Counter(_rank(card) for card in known)
    used_focus = Counter(_rank(card) for card in known if card[1] == suit)
    available = {r: 4 - used[r] for r in RANK_IDS}
    focus_available = {r: 1 - used_focus[r] for r in RANK_IDS}

    safe = tie = danger = routes = rank_pairs = 0

    def add_route(a, b, focus_cards, weight):
        nonlocal safe, tie, danger, routes
        if weight <= 0:
            return
        opponent = _hand_key(board_ranks + [a, b],
                             board_focus + focus_cards)
        if opponent[0] != category:
            return
        routes += 1
        if opponent < hero_key:
            safe += weight
        elif opponent > hero_key:
            danger += weight
        else:
            tie += weight

    for a in RANK_IDS:
        if available[a] <= 0:
            continue
        for b in range(a, 15):
            if available[b] <= 0:
                continue
            rank_pairs += 1
            na, nb = available[a], available[b]
            if board_suit_count < 3:
                # A flush is impossible for BOTH players with <=2 suited
                # board cards; aggregate all suits in a single rank route.
                add_route(a, b, [], _choose_two(na) if a == b else na * nb)
                continue
            sa, sb = focus_available[a], focus_available[b]
            oa, ob = na - sa, nb - sb
            if a == b:
                # There is only one card of a given rank in any suit.
                add_route(a, b, [], _choose_two(oa))
                add_route(a, b, [a], sa * oa)
            else:
                # Suit partitions: none / a only / b only / both.
                add_route(a, b, [], oa * ob)
                add_route(a, b, [a], sa * ob)
                add_route(a, b, [b], oa * sb)
                add_route(a, b, [a, b], sa * sb)

    total = safe + tie + danger
    fraction = (safe + .5 * tie) / total if total else .5
    return fraction, {
        "category": category,
        "hero_key": hero_key[1:],
        "method": "GTO 5.3: weighted rank pairs + analytic suit partitions",
        "danger": danger,
        "safe": safe,
        "tie": tie,
        "route_weight": total,
        "rank_pairs": rank_pairs,
        "nonzero_routes": routes,
        "win_fraction": round(fraction, 6),
        "range_assumption": "Any Two / uniform physical combinations",
    }
