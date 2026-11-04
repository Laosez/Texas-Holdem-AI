"""On-demand audit of a saved GTO decision: exact CURRENT 5-7-card ranking.

Enumerates C(52-board-Hero,2) = 1081 / 1035 / 990 uniformly weighted
opponent hole-card pairs. Exact only for *made* hands at this visible street;
does not enumerate future runouts (F/T), condition on opponent actions,
model multiway correlations, or change the bot's decisions.
"""
from collections import Counter
from itertools import combinations
from core.engine import _FULL_DECK, eval_hand


def exact_current_hand_audit(step):
    """Return validated numerical comparison of formula vs exact Any Two.

    Input trace holds only Hero and public board, never opponents' hole cards.
    """
    hole = [tuple(c) for c in step["hero_hole"]]
    board = [tuple(c) for c in step["board"]]
    if len(hole) != 2 or len(board) not in (3, 4, 5):
        raise ValueError("Неверная длина руки/борда")
    seen = hole + board
    if any(len(c) != 2 or c[0] not in "23456789TJQKA" or c[1] not in "cdhs"
           for c in seen) or len(set(seen)) != len(seen):
        raise ValueError("Недопустимые или повторяющиеся карты")
    hero_strength = eval_hand(hole, board)
    hero_category = hero_strength >> 24
    deck = [c for c in _FULL_DECK if c not in seen]
    n = 0
    categories = Counter()
    weaker = tied = stronger = 0
    same_weaker = same_tied = same_stronger = 0
    for opponent in combinations(deck, 2):
        score = eval_hand(opponent, board)
        category = score >> 24
        categories[category] += 1
        n += 1
        if score < hero_strength:
            weaker += 1
            if category == hero_category:
                same_weaker += 1
        elif score > hero_strength:
            stronger += 1
            if category == hero_category:
                same_stronger += 1
        else:
            tied += 1
            if category == hero_category:
                same_tied += 1
    assert n == {3: 1081, 4: 1035, 5: 990}[len(board)]
    same_n = categories[hero_category]
    exact_fraction = ((same_weaker + .5*same_tied) / same_n
                      if same_n else None)
    distribution = step.get("distribution") or {}
    model = step.get("equity_model") or {}
    seniority = model.get("seniority") or {}
    names = ("high_card", "pair", "two_pair", "trips", "straight",
             "flush", "full_house", "quads", "straight_flush")
    formula_distribution = distribution.get("categories_pct") or {}
    formula_category_pct = formula_distribution.get(names[hero_category])
    model_fraction = seniority.get("win_fraction")
    return {
        "format": "SKACHKOV_GTO_TRACE_CURRENT_HAND_EXACT_V1",
        "street": step["street"],
        "hand_id": step.get("hand_id"),
        "board": step["board"],
        "hero_hole": step["hero_hole"],
        "hero_category": names[hero_category],
        "opponent_hands_examined": n,
        "current_only": len(board) < 5,
        "opponent_range": "uniform Any Two with Hero and board blockers",
        "same_category_count": same_n,
        "same_category_weaker": same_weaker,
        "same_category_tied": same_tied,
        "same_category_stronger": same_stronger,
        "formula_category_pct": formula_category_pct,
        "exact_category_pct": round(100*same_n/n, 4),
        "category_delta_pp": (round(float(formula_category_pct)-100*same_n/n, 4)
                              if formula_category_pct is not None else None),
        "formula_win_fraction": model_fraction,
        "exact_win_fraction": (round(exact_fraction, 6)
                               if exact_fraction is not None else None),
        "seniority_delta_pp": (round(100*(float(model_fraction)-exact_fraction), 4)
                               if model_fraction is not None
                               and exact_fraction is not None else None),
        "formula_hero_quantile": model.get("hero_quantile"),
        "exact_current_hu_showdown_share": round((weaker+.5*tied)/n, 6),
        "overall_weaker": weaker,
        "overall_tied": tied,
        "overall_stronger": stronger,
        "interpretation": ("FLOP/TURN: exact current-made-hand ranking ONLY. "
                           "No future runouts; cannot compare it directly to "
                           "draw-adjusted EV equity." if len(board) < 5 else
                           "RIVER: exact Any Two heads-up showdown share for "
                           "the current public board and Hero blockers. "
                           "Not a conditional opponent range or multiway EV."),
    }
