"""Legacy-compatible Monte Carlo equity estimator for strategy bots.

Does not alter core/equity.py, a frozen CFR evaluator with different
sampling and multiway-tie accounting.

GTO, Smart and MonteCarloBot share the legacy RNG sampling sequence and
half-win tie credit. Values are not interchangeable with core.equity.equity().
"""
from __future__ import annotations

import random

from core.engine import _FULL_DECK, eval_hand


def estimate_equity_legacy(
    hole_cards,
    board,
    num_opponents: int = 1,
    sims: int = 100,
    *,
    rng=None,
) -> float:
    """Legacy-equivalent estimated equity against random hands.

    The optional rng object should expose sample(population, k).
    None deliberately uses the global random module to preserve previous
    RNG consumption by GTO, Smart and MonteCarloBot.

    A tie with the best opponent counts as 0.5 even in multiway pots.
    Correct split-pot accounting is a later, separately versioned change.
    """
    if not hole_cards or len(hole_cards) < 2:
        return 0.0

    opponents = max(1, num_opponents)
    sampler = random if rng is None else rng
    wins = 0
    ties = 0
    base_used = set(tuple(c) for c in hole_cards) | set(tuple(c) for c in board)
    base_remaining = [c for c in _FULL_DECK if c not in base_used]
    need_board = 5 - len(board)

    # Repeated turn cards and all river boards have the same hero score.
    # No change to the sequence of random draws: only pure evaluations are
    # reused. On the flop or preflop, the runout changes on every trial.
    fixed_hero_score = None
    turn_hero_scores = {}
    if need_board == 0 and sims > 0:
        fixed_hero_score = eval_hand(hole_cards, board)
    board_prefix = list(board)

    for _ in range(sims):
        # Keep deck order identical to the old list-comprehension filtering
        # while avoiding repeated full-deck scans and set allocations.
        remaining = list(base_remaining)
        opp_hands = []
        valid = True
        for _ in range(opponents):
            if len(remaining) < 2:
                valid = False
                break
            opp = sampler.sample(remaining, 2)
            opp_hands.append(opp)
            remaining.remove(opp[0])
            remaining.remove(opp[1])
        if not valid:
            continue

        if need_board > 0:
            if len(remaining) < need_board:
                continue
            extra_board = sampler.sample(remaining, need_board)
            full_board = board_prefix + extra_board
        else:
            full_board = board_prefix

        if need_board == 0:
            my_score = fixed_hero_score
        elif need_board == 1:
            # At most 46 possible runouts; repeated cards reuse a score.
            last_card = extra_board[0]
            if last_card not in turn_hero_scores:
                turn_hero_scores[last_card] = eval_hand(hole_cards, full_board)
            my_score = turn_hero_scores[last_card]
        else:
            my_score = eval_hand(hole_cards, full_board)

        # Only the best opposing hand matters. As soon as any opponent
        # outranks hero, no later evaluation can change the loss. Opponent
        # cards and board have already been sampled, so RNG stays identical.
        beaten = False
        tied = False
        for opp in opp_hands:
            opp_score = eval_hand(opp, full_board)
            if opp_score > my_score:
                beaten = True
                break
            if opp_score == my_score:
                tied = True
        if not beaten:
            if tied:
                ties += 1
            else:
                wins += 1

    return (wins + ties * 0.5) / sims
