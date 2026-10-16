"""
core/equity.py — Canonical multiway equity calculator
-----------------------------------------------------
Single source of truth for Monte Carlo equity estimation.
Extracted from bots/cfr_bot.py (session 2026-04-26).

Both Path A and Path B import from here. This module is read-only
after Gate 1 closes.
"""
from __future__ import annotations

import random
from itertools import combinations
from typing import List, Tuple

from core.engine import eval_hand, _FULL_DECK


def equity(hole_cards, board, n_opponents, n_sims=100, rng=None, evaluator=None):
    """Estimate Hero's expected showdown pot share against random hands.

    Draw opponent hands and missing board cards in one without-replacement
    sample. Ties are split across every player holding the best hand.
    An optional rng allows reproducible independent simulations.
    """
    if not hole_cards or len(hole_cards) < 2:
        return 0.5
    if len(hole_cards) != 2 or len(board) not in (0, 3, 4, 5):
        raise ValueError("Expected two hole cards and 0, 3, 4 or 5 board cards")
    if not isinstance(n_opponents, int) or not 1 <= n_opponents <= 22:
        raise ValueError("Invalid number of opponents")
    if not isinstance(n_sims, int) or n_sims < 1:
        raise ValueError("n_sims must be a positive integer")
    known = [tuple(c) for c in hole_cards] + [tuple(c) for c in board]
    if len(set(known)) != len(known) or any(c not in _FULL_DECK for c in known):
        raise ValueError("Duplicate or invalid cards")
    remaining = [c for c in _FULL_DECK if c not in set(known)]
    missing = 5 - len(board)
    draw_count = 2 * n_opponents + missing
    if draw_count > len(remaining):
        raise ValueError("Not enough cards for opponents and board")
    score_hand = evaluator if evaluator is not None else eval_hand
    sample = (rng or random).sample
    hero_hole = list(hole_cards)
    board_prefix = list(board)
    payout = 0.0
    for _ in range(n_sims):
        drawn = sample(remaining, draw_count)
        full_board = board_prefix + drawn[2 * n_opponents:]
        hero_score = score_hand(hero_hole, full_board)
        best = hero_score
        winners = 1
        for j in range(0, 2 * n_opponents, 2):
            score = score_hand(drawn[j:j + 2], full_board)
            if score > best:
                best = score
                winners = 0
            if score == best:
                winners += 1
        if hero_score == best:
            payout += 1.0 / winners
    return payout / n_sims


def equity_bucket(hole_cards, board, n_opponents, n_buckets=20, n_sims=100):
    """Integer bucket [0, n_buckets) for hero's equity.

    Used for Path A info-set keying.

    Parameters
    ----------
    hole_cards : list of (rank, suit) tuples
    board : list of (rank, suit) tuples
    n_opponents : int (required, no default)
    n_buckets : int
    n_sims : int
    """
    if not hole_cards or len(hole_cards) < 2 or not board:
        return n_buckets // 2  # neutral bucket when no board

    eq = equity(hole_cards, board, n_opponents, n_sims=n_sims)
    bucket = int(eq * n_buckets)
    return max(0, min(n_buckets - 1, bucket))
