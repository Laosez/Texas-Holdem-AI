"""GTO 5.1: human-sized, board-aware within-category seniority.

Canonical rules: docs/GTO_5_1_SENIORITY.md
This module uses at most 13 rank levels (10 straight heights) per decision
component. It does NOT enumerate legal two-card opponent hands, sample
runouts, or use a Monte Carlo oracle.

For each hand category c: seniority = P(Hero wins | category c), estimated
by counting dangerous (D) / safe (B) rank choices or made-straight routes.
The separate board distribution supplies P(c). Ties contribute 1/2.
"""
from collections import Counter
from itertools import combinations
from core.engine import eval_hand

RANKS = "23456789TJQKA"
RANK_IDS = tuple(range(2, 15))
WINDOWS = [(5, {14, 2, 3, 4, 5})] + [
    (high, set(range(high-4, high+1))) for high in range(6, 15)]
CATEGORY_LENGTHS = (5, 4, 3, 3, 1, 5, 2, 2, 1)


def _key(score, category):
    """Decode the engine's canonical 5-card rank keys (base 15)."""
    size = CATEGORY_LENGTHS[category]
    packed = score & ((1 << 24) - 1)
    out = [0] * size
    for i in range(size - 1, -1, -1):
        out[i] = packed % 15 + 2
        packed //= 15
    return tuple(out)


def _rank_counts(board, hole):
    board_counts = Counter(RANKS.index(c[0]) + 2 for c in board)
    total_counts = board_counts + Counter(RANKS.index(c[0]) + 2 for c in hole)
    return board_counts, {r: 4 - total_counts[r] for r in RANK_IDS}


def _ratio(wins, loses, ties=0):
    total = wins + loses + ties
    return (wins + .5 * ties) / total if total else .5


def _rank_compare(pool, pivot):
    """Count at most 13 available rank choices below/equal/above pivot."""
    low = sum(r < pivot for r in pool)
    same = sum(r == pivot for r in pool)
    high = sum(r > pivot for r in pool)
    return _ratio(low, high, same), (high, low, same)


def _two_chance_safe(pool, pivot):
    """Two private ranks: probability neither beats the Hero kicker (proxy).

    Without-replacement cards and dependencies are intentionally omitted.
    """
    win, counts = _rank_compare(pool, pivot)
    return win * win, counts


def _tuple_compare(candidate, hero):
    return (1 if candidate < hero else 0 if candidate > hero else .5)


def _route_ratio(board_ranks, available, hero_high, suit_available=None):
    """Count at most ten rank-defined straight or straight-flush routes."""
    stronger = weaker = tied = 0
    for high, needed in WINDOWS:
        missing = needed - board_ranks
        if len(missing) > 2 or any(available[r] <= 0 for r in missing):
            continue
        if suit_available is not None and any(not suit_available[r] for r in missing):
            continue
        if high > hero_high:
            stronger += 1
        elif high < hero_high:
            weaker += 1
        else:
            tied += 1
    return _ratio(weaker, stronger, tied), (stronger, weaker, tied)


def _candidate_flush_key(board_suit_ranks, candidate, other=None):
    values = list(board_suit_ranks) + [candidate]
    if other is not None:
        values.append(other)
    return tuple(sorted(values, reverse=True)[:5])


def _simple_kicker_pool(board, hole, board_counts, available):
    """Available ranks that do not immediately duplicate a board rank."""
    return [r for r in RANK_IDS if available[r] > 0 and not board_counts[r]]


def hero_seniority(hole, board, category_mass=None, pocket_pair_pct=5.88):
    """Return within-category Hero-win fraction and auditable rank counts.

    Current-made-hand ranks only; F/T future-card improvements remain in
    the 5.0 draw term. No opponent-action posterior, no suit-aware opponent
    range weighting, no exact same-category tie enumeration.
    """
    hole, board = list(hole), list(board)
    score = eval_hand(hole, board)
    category = min(8, score >> 24)
    hero = _key(score, category)
    board_counts, available = _rank_counts(board, hole)
    board_ranks = set(board_counts)
    generic = [r for r in RANK_IDS if available[r] > 0]
    details = {"category": category, "hero_key": hero,
               "method": "", "danger": 0, "safe": 0, "tie": 0}
    def result(value, method, counts):
        details.update(method=method, danger=counts[0], safe=counts[1],
                       tie=counts[2], win_fraction=round(value, 6))
        return max(0., min(1., value)), details

    if category == 0:  # High card: top differing kicker, tie then next kicker.
        pool = _simple_kicker_pool(board, hole, board_counts, available)
        private = sorted((RANKS.index(c[0])+2 for c in hole), reverse=True)
        primary = private[0]
        secondary = private[1]
        lower = sum(r < primary for r in pool)
        higher = sum(r > primary for r in pool)
        tied = sum(r == primary for r in pool)
        next_win, _ = _rank_compare([r for r in pool if r != primary], secondary)
        total = lower + higher + tied
        fraction = ((lower + tied*next_win) / total) if total else .5
        return result(fraction, "highest-free-kicker then next kicker",
                      (higher, lower, tied))

    if category == 1:  # Pair: board contacts and pocket pairs are distinct.
        pair_rank = hero[0]
        board_pair = [r for r, n in board_counts.items() if n >= 2]
        if board_pair and pair_rank == max(board_pair):
            pool = _simple_kicker_pool(board, hole, board_counts, available)
            private = [RANKS.index(c[0])+2 for c in hole
                       if RANKS.index(c[0])+2 != pair_rank]
            hero_kicker = max(private) if private else hero[1]
            win, counts = _two_chance_safe(pool, hero_kicker)
            return result(win, "shared-board-pair: two kicker chances", counts)
        board_pair_routes = [r for r in board_ranks if available[r] > 0]
        kicker_pool = [r for r in generic if r != pair_rank]
        kicker_win, _ = _rank_compare(kicker_pool, hero[1])
        board_low = sum(r < pair_rank for r in board_pair_routes)
        board_high = sum(r > pair_rank for r in board_pair_routes)
        board_tied = sum(r == pair_rank for r in board_pair_routes)
        total = board_low + board_high + board_tied
        board_win = ((board_low+board_tied*kicker_win)/total
                     if total else .5)
        pocket_pool = [r for r in RANK_IDS if available[r] >= 2]
        pp_win, _ = _rank_compare(pocket_pool, pair_rank)
        mass = max(0., float(category_mass or 0))
        pp_weight = min(1., pocket_pair_pct/100/max(mass, 1e-9)) if mass else 0
        # If board already has a pair, a pocket pair usually changes the
        # category to two pairs, so do not spend x twice in the pair category.
        if board_pair:
            pp_weight = 0.
        win = (1-pp_weight)*board_win + pp_weight*pp_win
        return result(win, "board-pair ranks + non-overlapping PP share",
                      (board_high, board_low, board_tied))

    if category == 2:  # Two pairs: compare pair ranks, then kicker.
        shared = sorted((r for r, n in board_counts.items() if n >= 2),
                        reverse=True)
        if len(shared) >= 2:
            win, counts = _two_chance_safe(generic, hero[2])
            return result(win, "shared two-pair board: fifth kicker", counts)
        if shared:
            common = shared[0]
            routes = [tuple(sorted((common, r), reverse=True))
                      for r in generic if r != common]
        else:
            # With no board pair, both opponents' matching ranks must be
            # drawn from the board. At most C(5,2)=10 rank routes.
            routes = [tuple(sorted(pair, reverse=True))
                      for pair in combinations(sorted(board_ranks), 2)]
        if not routes:
            return result(.5, "no two-pair rank route", (0, 0, 0))
        stronger = sum(pair > hero[:2] for pair in routes)
        weaker = sum(pair < hero[:2] for pair in routes)
        tied = len(routes)-stronger-weaker
        kicker_win, _ = _rank_compare(generic, hero[2])
        fraction = (weaker+tied*kicker_win)/len(routes)
        return result(fraction, "two-pair rank routes then fifth kicker",
                      (stronger, weaker, tied))

    if category == 3:  # Trips: rank of trips or two kicker chances.
        trips_rank = hero[0]
        board_trip = [r for r, n in board_counts.items() if n >= 3]
        if board_trip and trips_rank == board_trip[0]:
            private = sorted((RANKS.index(c[0])+2 for c in hole), reverse=True)
            pool = _simple_kicker_pool(board, hole, board_counts, available)
            win, counts = _two_chance_safe(pool, private[0])
            return result(win, "shared board trips: two kicker chances", counts)
        pair_routes = [r for r, n in board_counts.items()
                       if n >= 2 and available[r] > 0]
        if not pair_routes:
            pair_routes = [r for r in board_ranks if available[r] >= 2]
        win, counts = _rank_compare(pair_routes, trips_rank)
        return result(win, "set/trips rank from paired-board routes", counts)

    if category == 4:
        win, counts = _route_ratio(board_ranks, available, hero[0])
        return result(win, "ten possible straight heights; <=2 missing ranks",
                      counts)

    if category == 5:
        suits = Counter(c[1] for c in board)
        suit = max(suits, key=suits.get)
        board_suit = [RANKS.index(c[0])+2 for c in board if c[1] == suit]
        own_suit = {RANKS.index(c[0])+2 for c in hole if c[1] == suit}
        pool = [r for r in RANK_IDS
                if r not in board_suit and r not in own_suit]
        # The marginal category distribution already accounts for completing
        # the flush. Here rank candidates only estimate *seniority*.
        stronger = weaker = tied = 0
        for r in pool:
            other = (min(v for v in pool if v != r)
                     if len(board_suit) == 3 and len(pool) > 1 else None)
            candidate = _candidate_flush_key(board_suit, r, other)
            if len(candidate) < 5:
                continue
            if candidate > hero:
                stronger += 1
            elif candidate < hero:
                weaker += 1
            else:
                tied += 1
        return result(_ratio(weaker, stronger, tied),
                      "same-suit ranks relative to Hero's five flush cards",
                      (stronger, weaker, tied))

    if category == 6:
        trip, pair = hero
        board_trips = [r for r, n in board_counts.items() if n >= 3]
        board_pairs = [r for r, n in board_counts.items() if n >= 2]
        if board_trips and len(board_pairs) > 1:
            # Full house already on the board. Only stronger private pocket
            # pairs can improve a player's full house *within the category*.
            shared_trip = max(board_trips)
            shared_pair = max(r for r in board_pairs if r != shared_trip)
            pocket_routes = [r for r in RANK_IDS if available[r] >= 2]
            danger = sum(r > shared_pair for r in pocket_routes)
            pool = len(pocket_routes)
            mass = max(0., float(category_mass or 0))
            danger_total = pocket_pair_pct/100*(danger/pool if pool else 0.)
            fraction = 1-min(1., danger_total/mass) if mass else 1.
            return result(fraction, "board full house: superior PP share only",
                          (danger, pool-danger, 0))
        if board_trips:
            pool = [r for r in RANK_IDS if available[r] >= 2]
            fraction, counts = _rank_compare(pool, pair)
            return result(fraction, "trip rank fixed; compare pocket-pair ranks",
                          counts)
        # Non-shared full house: trip rank is the leading comparison.
        pool = [r for r in RANK_IDS if available[r] > 0]
        fraction, counts = _rank_compare(pool, trip)
        return result(fraction, "trip rank first, pair as tiebreaker", counts)

    if category == 7:
        quad = hero[0]
        board_quads = [r for r, n in board_counts.items() if n == 4]
        if board_quads:
            private = max(RANKS.index(c[0])+2 for c in hole)
            pool = _simple_kicker_pool(board, hole, board_counts, available)
            fraction, counts = _two_chance_safe(pool, private)
            return result(fraction, "shared quads: two kicker chances", counts)
        # If Hero owns the only available fourth card, same-rank quads are
        # blocked for the opponent; any remaining candidate must be weaker.
        return result(1., "Hero quads block same-rank opponent quads", (0, 1, 0))

    if category == 8:
        suits = Counter(c[1] for c in board)
        suit = max(suits, key=suits.get)
        board_ranks_suit = {RANKS.index(c[0])+2 for c in board
                            if c[1] == suit}
        used = {(RANKS.index(c[0])+2, c[1]) for c in board+hole}
        can_suit = {r: (r, suit) not in used for r in RANK_IDS}
        win, counts = _route_ratio(
            board_ranks_suit, available, hero[0], suit_available=can_suit)
        return result(win, "ten suited straight routes; <=2 missing cards",
                      counts)
    raise AssertionError("Unknown made-hand category")


def hero_seniority_52(hole, board, category_mass=None, pocket_pair_pct=5.88):
    """GTO 5.2 A/B seniority: exactly two local changes; 5.1 is immutable.

    (1) High card: two-rank opponent chance proxy r_51 ** 2.
    (2) P0 board + Hero one pair: available-card-weighted *rank routes*.
        At most (5*13+13) route comparisons, not 990 concrete hole pairs.
        Ties contribute one half. Board suit interactions still approximate.
    Other categories and special P4/PH fallbacks stay at 5.1 behavior.
    """
    hole, board = list(hole), list(board)
    old, old_info = hero_seniority(
        hole, board, category_mass=category_mass, pocket_pair_pct=pocket_pair_pct
    )
    category = min(8, eval_hand(hole, board) >> 24)
    if category == 0:
        new = old * old
        return new, {**old_info, "method": "two-card high-card risk: r51 squared",
                     "win_fraction": round(new, 6), "baseline_51": round(old, 6)}
    board_counts, available = _rank_counts(board, hole)
    if category != 1 or len(board_counts) != len(board):
        return old, old_info

    hero_key = _key(eval_hand(hole, board), 1)
    board_ranks = set(board_counts)
    safe = danger = tie = 0

    def add_route(key, weight):
        nonlocal safe, danger, tie
        if key < hero_key:
            safe += weight
        elif key > hero_key:
            danger += weight
        else:
            tie += weight

    # One board-matching card plus a non-matching kicker. Weighted by
    # remaining physical cards of BOTH ranks, while iterating only ranks.
    for paired_rank in board_ranks:
        for kicker_rank in RANK_IDS:
            if kicker_rank in board_ranks or not available[kicker_rank]:
                continue
            weight = available[paired_rank] * available[kicker_rank]
            kickers = sorted((board_ranks - {paired_rank}) |
                             {kicker_rank}, reverse=True)[:3]
            add_route((paired_rank, *kickers), weight)

    # Non-board pocket pairs form the same category; 4/3/2 remaining
    # physical cards imply 6/3/1 possible PP combinations.
    board_kickers = tuple(sorted(board_ranks, reverse=True)[:3])
    for paired_rank in RANK_IDS:
        if paired_rank in board_ranks or available[paired_rank] < 2:
            continue
        add_route((paired_rank, *board_kickers),
                  available[paired_rank] * (available[paired_rank]-1) // 2)

    total = safe + danger + tie
    if not total:
        return old, old_info
    new = (safe + .5*tie) / total
    return new, {
        **old_info,
        "method": "P0 one-pair weighted rank routes + exact rank ties",
        "danger": danger, "safe": safe, "tie": tie,
        "route_weight": total,
        "win_fraction": round(new, 6),
        "baseline_51": round(old, 6),
    }
