"""SKACHKOV S100 postflop: one classifier/policy dictionary for humans and bots.

S100_V1 has exactly 100 scenario IDs (10 hand families × 5 subtypes × HU/MW).
The authoritative rows live in strategy_catalog/s100_v1.json and are exposed
unchanged to the human reference and used by this bot. This is an experimental
heuristic policy, not a GTO equilibrium solver. No V1–V4 code is modified.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
import random
import re
from types import SimpleNamespace

from core.bot_api import Action, BotAdapter
from core.engine import eval_hand
from bots.postflop_profiles import _RANK, _draws, _amount, _fallthrough, _opponents

CATALOG_PATH = Path(__file__).resolve().parents[1] / "strategy_catalog" / "s100_v1.json"
CATALOG = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
SCENARIOS = tuple(CATALOG["scenarios"])
BY_KEY = {(s["family"], s["variant"], s["table_mode"]): s for s in SCENARIOS}
assert len(SCENARIOS) == len(BY_KEY) == 100
assert [s["id"] for s in SCENARIOS] == [f"S{i:03d}" for i in range(1, 101)]

FAMILIES = (
    "air", "draw", "weak_pair", "top_pair", "overpair", "shared_two_pair",
    "true_two_pair", "trips_set", "straight_flush", "premium",
)


def _straight_density(board):
    ranks = {_RANK[card[0]] for card in board}
    if 14 in ranks:
        ranks.add(1)  # Wheel: A-2-3-4-5.
    return max(sum(start <= rank <= start + 4 for rank in ranks)
               for start in range(1, 11))


def board_features(board):
    rank_counts = Counter(card[0] for card in board)
    suits = Counter(card[1] for card in board)
    flush_count = max(suits.values(), default=0)
    linked = _straight_density(board) >= 3
    paired = any(n > 1 for n in rank_counts.values())
    if paired:
        texture = "paired"
    elif flush_count >= 3:
        texture = "monotone"
    elif linked:
        texture = "connected"
    elif flush_count >= 2:
        texture = "two_tone"
    else:
        texture = "dry"
    return {"texture": texture, "paired": paired,
            "flush_count": flush_count, "straight_density": _straight_density(board),
            "rank_counts": rank_counts}


def _matching_top_pair(hole, board):
    top = max(_RANK[c[0]] for c in board)
    idxs = [i for i, c in enumerate(hole) if _RANK[c[0]] == top]
    if len(idxs) == 1 and hole[0][0] != hole[1][0]:
        return _RANK[hole[1-idxs[0]][0]]
    return None


def classify(hole, board, n_opponents=1):
    """Return exactly one S100 row plus objectively measured card features.

    All possible valid flop/turn/river deals map to one row. The classification
    uses actual rank/suit evaluation, NOT V3/V4's subjective 'monster' labels.
    """
    if len(hole) != 2 or len(board) not in (3, 4, 5):
        raise ValueError("S100: нужны 2 карманные карты и 3–5 карт борда")
    if len(set(tuple(card) for card in [*hole, *board])) != len(hole) + len(board):
        raise ValueError("S100: повторяющиеся карты")
    if not 1 <= n_opponents <= 8:
        raise ValueError("S100: число соперников должно быть 1–8")
    features = board_features(board)
    counts = features["rank_counts"]
    category = eval_hand(list(hole), list(board)) >> 24
    board_play = len(board) == 5 and eval_hand(list(hole), list(board)) == eval_hand([], list(board))
    draw_outs, backdoor = _draws(hole, board)
    missed = bool(len(board) == 5 and _draws(hole, board[:4])[0] > 0)
    pocket = hole[0][0] == hole[1][0]
    hole_ranks = [c[0] for c in hole]
    top = max(_RANK[c[0]] for c in board)
    kicker = _matching_top_pair(hole, board)
    origin = "board" if board_play else "hero"

    if category >= 6:
        family = "premium"
        if board_play:
            variant = "board_only"
        elif category == 8:
            variant = "straight_flush"
        elif category == 7:
            variant = "quads"
        else:
            trip_rank = max((r for r, ct in Counter(hole_ranks + list(counts.elements())).items()
                             if ct >= 3), key=lambda r: _RANK[r], default="2")
            variant = "full_high" if _RANK[trip_rank] >= 10 else "full_other"
    elif category in (4, 5):
        family = "straight_flush"
        if board_play:
            variant = "board_only"
        elif category == 5:
            flush_suit = next((s for s, num in Counter(c[1] for c in [*hole, *board]).items()
                               if num >= 5), None)
            variant = "nut_flush" if flush_suit and ("A", flush_suit) in hole else "other_flush"
        else:
            variant = "high_straight" if (eval_hand(list(hole), list(board)) & 0xffffff) >= 8 else "low_straight"
    elif category == 3:
        family = "trips_set"
        if board_play:
            variant = "board_only"
        elif any(v >= 3 for v in counts.values()):
            variant = "board_kicker"
        elif pocket and counts[hole_ranks[0]] >= 1:
            variant = "set_wet" if features["flush_count"] >= 2 or features["straight_density"] >= 3 else "set_dry"
        elif any(counts[r] >= 2 for r in hole_ranks):
            variant = "own_trips"
        else:
            variant = "board_kicker"
    elif category == 2:
        # A-Q on A-Q-7-7 is a genuine top-two-pair hand. T-6 on K-7-7-T
        # is NOT: Kx still dominates; their scenario IDs must differ.
        total_counts = Counter(hole_ranks + list(counts.elements()))
        paired_ranks = sorted((r for r, v in total_counts.items() if v >= 2),
                              key=lambda r: _RANK[r], reverse=True)
        best_two = set(paired_ranks[:2])
        two_own = (not pocket and set(hole_ranks) == best_two
                   and all(counts[r] >= 1 for r in hole_ranks))
        if two_own:
            family = "true_two_pair"
            if features["paired"]:
                variant = "paired"
            elif features["flush_count"] >= 3:
                variant = "flush_danger"
            elif features["straight_density"] >= 3:
                variant = "straight_danger"
            elif len(board) == 3:
                variant = "flop_dry"
            else:
                variant = "later_dry"
        else:
            family = "shared_two_pair"
            board_pairs = [r for r, v in counts.items() if v >= 2]
            if board_play:
                variant = "board_only"
            elif pocket and board_pairs:
                variant = "pocket_board"
            elif len(board_pairs) == 1:
                shared_rank = _RANK[board_pairs[0]]
                own_pair_ranks = [_RANK[r] for r in hole_ranks if counts[r] >= 1 and r != board_pairs[0]]
                if pocket:
                    own_pair_ranks = [_RANK[hole_ranks[0]]]
                own = max(own_pair_ranks, default=0)
                if own and own >= top and own > shared_rank:
                    variant = "above_shared"
                elif own and own < shared_rank:
                    variant = "below_shared"
                else:
                    variant = "other_shared"
            else:
                variant = "other_shared"
    elif category == 1:
        if pocket and _RANK[hole_ranks[0]] > top:
            family, variant = "overpair", (
                "pair_draw" if draw_outs >= 8 else
                "flop_dry" if len(board) == 3 and not features["paired"]
                                and features["straight_density"] < 3 and features["flush_count"] < 2 else
                "flop_wet" if len(board) == 3 else
                "turn" if len(board) == 4 else "river"
            )
        elif kicker is not None:
            family = "top_pair"
            variant = ("pair_draw" if draw_outs >= 8 else
                       "danger" if features["paired"] or features["flush_count"] >= 3
                                      or features["straight_density"] >= 3 else
                       "high_kicker" if kicker >= 11 else
                       "mid_kicker" if kicker >= 8 else "low_kicker")
        else:
            family = "weak_pair"
            matching_ranks = [_RANK[r] for r in hole_ranks if counts[r]]
            variant = ("pair_draw" if draw_outs >= 8 else
                       "board_pair" if board_play or not matching_ranks and not pocket else
                       "underpair" if pocket else
                       "bottom" if min(matching_ranks) == min(_RANK[r] for r in counts) else
                       "middle")
    else:
        if draw_outs > 0 or backdoor:
            family = "draw"
            variant = ("combo" if draw_outs >= 13 else
                       "flush" if draw_outs >= 9 else
                       "oesd" if draw_outs >= 8 else
                       "gutshot" if draw_outs >= 4 else "backdoor")
        else:
            family = "air"
            overcards = sum(_RANK[r] > top for r in hole_ranks)
            suits = Counter(card[1] for card in board)
            blocker = any(rank == "A" and suits[suit] >= 3 for rank, suit in hole)
            variant = ("missed" if missed else "blocker" if blocker else
                       "two_over" if overcards == 2 else
                       "one_over" if overcards == 1 else "nothing")

    mode = "hu" if n_opponents == 1 else "multi"
    scenario = BY_KEY[(family, variant, mode)]
    return scenario, {
        "family": family, "variant": variant, "category": category,
        "board_texture": features["texture"], "board_flush_count": features["flush_count"],
        "board_straight_density": features["straight_density"],
        "draw_outs": draw_outs, "backdoor": backdoor, "board_play": board_play,
        "origin": origin, "kicker_rank": kicker, "opponents": n_opponents,
        "street": ("flop" if len(board) == 3 else "turn" if len(board) == 4 else "river"),
    }


def probabilities(hole, board, opponents, pot, to_call, stack=80, legal=None):
    """Transparent Fold/Call/Raise or Check/Bet distribution from the S100 row.

    Frequencies are heuristic initial parameters. Results are a strategy
    proposal, NOT equity, not Nash frequencies and not empirical optimality.
    """
    row, features = classify(hole, board, opponents)
    pol = row["policy"]
    pot = max(0, float(pot))
    to_call = max(0, float(to_call))
    stack = max(0, float(stack))
    street = features["street"]
    danger = features["board_flush_count"] >= 4 or features["board_straight_density"] >= 4
    board_only = features["board_play"]
    made = features["category"] >= 1
    can_bluff = stack > max(1, pot) * .55 and not board_only and opponents <= 3
    odds = to_call / max(1, pot + to_call)
    facing = to_call > 0
    allowed = set(legal) if legal is not None else ({"fold", "call", "raise"} if facing else {"check", "bet"})
    frequency = pol["raise_frequency"] if facing else pol["bet_frequency"]
    if danger and made and features["family"] not in ("premium", "straight_flush"):
        frequency *= .78
    if street == "river" and features["family"] in ("air", "draw"):
        frequency *= .5
    if not made and not can_bluff:
        frequency = 0
    if board_only:
        frequency = 0
    frequency = max(0, min(.95, frequency))
    if facing:
        threshold = pol["call_odds_max"]
        if features["family"] == "draw" and street != "river":
            raw_draw_equity = features["draw_outs"] / (47 if street == "flop" else 46)
            threshold = min(.42, raw_draw_equity * (.95 if opponents == 1 else .72))
        if features["family"] in ("air", "draw") and street == "river":
            threshold = 0
        if danger and features["family"] in ("weak_pair", "shared_two_pair"):
            threshold *= .85
        if board_only:
            threshold = min(threshold, .13)
        if odds > threshold or "call" not in allowed:
            actions = {"fold": 1.0} if "fold" in allowed else {"call": 1.0}
        else:
            can_raise = "raise" in allowed and stack > to_call and (
                features["family"] not in ("air",) or can_bluff
            )
            r = frequency if can_raise else 0
            actions = {"raise": round(r, 4), "call": round(1-r, 4)}
    else:
        b = frequency if "bet" in allowed else 0
        actions = {"bet": round(b, 4), "check": round(1-b, 4)}
    return {"scenario": row, "features": features, "pot_odds": round(odds, 4),
            "call_threshold": round(threshold, 4) if facing else None,
            "actions": actions}


class S100PostflopBot(BotAdapter):
    profile = "s100_postflop_v1"

    def act(self, view):
        if view.street not in ("flop", "turn", "river"):
            raise ValueError("S100 is a postflop-only strategy")
        hole = list(view.hole_cards or ())
        board = list(view.board or ())
        if len(hole) != 2 or len(board) < 3:
            return _fallthrough(view)
        legal = {item["type"] for item in view.legal_actions if "type" in item}
        decision = probabilities(hole, board, _opponents(view), view.pot,
                                 view.to_call, view.stacks.get(view.me, 0), legal)
        roll = random.random()
        acc = 0
        chosen = next(reversed(decision["actions"]))
        for action, chance in decision["actions"].items():
            acc += chance
            if roll < acc:
                chosen = action
                break
        if chosen in ("bet", "raise"):
            bet = _amount(view, decision["scenario"]["policy"]["bet_size_pot"])
            if bet is not None:
                return bet
            return _fallthrough(view)
        return Action(chosen)


def inspect_request(data):
    """Strict read-only public inspector (no code/string evaluation)."""
    if not isinstance(data, dict):
        raise ValueError("S100: ожидается объект")
    def parse_cards(value, expected=None):
        if not isinstance(value, list) or (expected and len(value) != expected):
            raise ValueError("S100: карты нужно передать списком")
        if not 3 <= len(value) <= 5 and expected is None:
            raise ValueError("S100: борд должен иметь 3–5 карт")
        cards = []
        for token in value:
            if not isinstance(token, str) or not re.fullmatch(r"[2-9TJQKA][cdhs]", token):
                raise ValueError("S100: формат карты As, Qh, 7d, Tc")
            cards.append((token[0], token[1]))
        return cards
    hole = parse_cards(data.get("hole"), expected=2)
    board = parse_cards(data.get("board"))
    opponents, pot, call, stack = (data.get("opponents", 1), data.get("pot", 24),
                                     data.get("to_call", 0), data.get("stack", 80))
    if type(opponents) is not int or not 1 <= opponents <= 8:
        raise ValueError("S100: число соперников 1–8")
    if any(type(v) not in (int, float) or not 0 <= v <= 100000 for v in (pot, call, stack)):
        raise ValueError("S100: банк, ставка и стек должны быть неотрицательными")
    return probabilities(hole, board, opponents, pot, call, stack)
