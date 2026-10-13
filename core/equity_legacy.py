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

    for _ in range(sims):
        sim_used = base_used.copy()
        opp_hands = []
        valid = True
        for _ in range(opponents):
            avail = [c for c in base_remaining if c not in sim_used]
            if len(avail) < 2:
                valid = False
                break
            opp = sampler.sample(avail, 2)
            opp_hands.append(opp)
            sim_used |= {tuple(c) for c in opp}
        if not valid:
            continue

        if need_board > 0:
            avail_board = [c for c in base_remaining if c not in sim_used]
            if len(avail_board) < need_board:
                continue
            full_board = list(board) + sampler.sample(avail_board, need_board)
        else:
            full_board = list(board)

        my_score = eval_hand(hole_cards, full_board)
        best_opp = max(eval_hand(opp, full_board) for opp in opp_hands)
        if my_score > best_opp:
            wins += 1
        elif my_score == best_opp:
            ties += 1

    return (wins + ties * 0.5) / sims
