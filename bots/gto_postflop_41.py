"""GTO 4.1 experimental joint-range EV for HU and multiway postflop.

Preserves the GTO 4.0 assumption that stronger hands act first. The physical
board classifier identifies the texture; exact legal two-card enumeration
provides its *conditional* Any Two made-hand distribution with Hero blockers.

The same 24 GTO 3.3 street/action frequencies supply action quantile bands for
each opponent. Independent hands are never sampled with overlapping cards.
One common runout resolves the entire pot (including ties).

Not a solver or tournament-ICM model. Betting assumes Bet/Fold vs raises and
one-street checkdown otherwise; side-pot entitlements and future bets are not
modelled. In particular, the calculation is approximate when stacks differ.
"""
from __future__ import annotations

from collections import Counter, deque
from functools import lru_cache
from itertools import combinations
import random

from bots.gto_postflop_40 import (
    StreetEVGTO40Bot, CATEGORIES, _hand_proxy, _seed,
)
from bots.gto_postflop_30 import _board_class, AdaptiveGTO30Bot
from bots.postflop_profiles import _amount, _fallthrough, read_hand
from core.bot_api import Action
from core.engine import _FULL_DECK, eval_hand


TRIALS = {"flop": 128, "turn": 160, "river": 192}


@lru_cache(maxsize=64)
def _range_profile(hero, board):
    """Full exact enumeration of legal opponent hole cards, *not* 48/64/96."""
    visible = set(hero + board)
    deck = tuple(c for c in _FULL_DECK if c not in visible)
    scored = []
    hist = Counter()
    for hand in combinations(deck, 2):
        strength, category, _outs = _hand_proxy(hand, board)
        scored.append((strength, hand))
        hist[CATEGORIES[category]] += 1
    scored.sort(key=lambda x: x[0])
    # Average percentile within exact strength ties, not lexicographic order.
    rank = {}
    i = 0
    n = len(scored)
    while i < n:
        j = i + 1
        while j < n and scored[j][0] == scored[i][0]:
            j += 1
        percentile = (i + j) / (2 * n)
        for _, hand in scored[i:j]:
            rank[hand] = percentile
        i = j
    distribution = {
        "possible_hands": n,
        "evaluated_hands": n,
        "categories_pct": {
            cat: round(100 * hist[cat] / n, 3) for cat in CATEGORIES
        },
        "enumeration": "exact_with_hero_blockers",
    }
    return deck, rank, distribution


def _band_for(pid, street, history, groups):
    """Quantile interval for the player's last *public* action this street."""
    last = None
    for event in history or ():
        if (isinstance(event, dict) and str(event.get("pid")) == str(pid)
                and event.get("street") == street):
            last = event.get("type")
    open_bet = groups["open"]["bet"]["p"]
    if last == "bet":
        band = (1 - open_bet, 1)
    elif last == "raise":
        raise_prob = groups["vs_bet"]["raise"]["p"]
        band = (1 - raise_prob, 1)
    elif last == "call":
        fold_prob = groups["vs_bet"]["fold"]["p"]
        call_prob = groups["vs_bet"]["call"]["p"]
        band = (fold_prob, fold_prob + call_prob)
    elif last == "check":
        band = (0, 1 - open_bet)
    else:
        band = (0, 1)
    # Distinguish extremely unlikely actions without using an empty range.
    return max(0, min(1, band[0])), max(.01, min(1, band[1]))


def _showdown_share(hero, opponents, board):
    """Hero's share in a single main pot, including split pots."""
    hero_score = eval_hand(list(hero), board)
    scores = [eval_hand(list(h), board) for h in opponents]
    best = max([hero_score] + scores)
    if hero_score != best:
        return 0.0
    return 1.0 / (1 + sum(s == best for s in scores))


def _estimate_joint(view, ranks, deck, opponents, groups, trials, bet_size):
    """Paired Monte Carlo for Bet/Check or Call/Fold, common random runouts.

    Opponent candidate holdings are selected within their last-action bands.
    Every selected joint holding has unique physical cards; no independent
    multiplication of HU winning probabilities.
    """
    history = getattr(view, "history", ()) or ()
    pools = {}
    bands = {}
    for pid in opponents:
        band = _band_for(pid, view.street, history, groups[pid][view.street])
        candidates = [
            pair for pair, q in ranks.items() if band[0] <= q <= band[1]
        ]
        pools[pid] = candidates if candidates else list(ranks)
        bands[pid] = band
    # Constrained opponents first: reduces blocked-card rejection bias.
    order = sorted(opponents, key=lambda pid: (len(pools[pid]), str(pid)))
    rng = random.Random(_seed(list(view.hole_cards) + list(view.board)))
    future = 5 - len(view.board)
    pot = max(1, int(view.pot))
    to_call = max(0, int(view.to_call))
    total_check = total_bet = total_call = 0.0
    accepted = 0
    attempts = 0
    while accepted < trials and attempts < trials * 5:
        attempts += 1
        occupied = set(view.hole_cards) | set(view.board)
        holdings = {}
        for pid in order:
            choices = [h for h in pools[pid]
                       if h[0] not in occupied and h[1] not in occupied]
            if not choices:
                break
            hand = rng.choice(choices)
            holdings[pid] = hand
            occupied.update(hand)
        if len(holdings) != len(opponents):
            continue
        runout = rng.sample([c for c in deck if c not in occupied], future)
        final_board = list(view.board) + runout
        accepted += 1
        if to_call:
            total_call += (_showdown_share(view.hole_cards,
                           [holdings[p] for p in opponents], final_board)
                           * (pot + to_call) - to_call)
            continue
        total_check += _showdown_share(
            view.hole_cards, [holdings[p] for p in opponents], final_board
        ) * pot
        if bet_size is None:
            continue
        called = []
        raised = False
        for pid in opponents:
            q = ranks[holdings[pid]]
            responses = groups[pid][view.street]["vs_bet"]
            fold = responses["fold"]["p"]
            call = responses["call"]["p"]
            if q < fold:
                continue
            if q < fold + call:
                called.append(pid)
            else:
                raised = True
                break
        if raised:
            total_bet -= bet_size  # Bet/Fold, same assumption as GTO 4.0.
        elif not called:
            total_bet += pot
        else:
            share = _showdown_share(
                view.hole_cards, [holdings[p] for p in called], final_board
            )
            total_bet += share * (pot + (len(called) + 1) * bet_size) - bet_size
    if not accepted:
        return None
    return {
        "check": total_check / accepted,
        "bet": total_bet / accepted if bet_size is not None else None,
        "call": total_call / accepted if to_call else None,
        "fold": 0.0,
        "trials": accepted,
        "attempts": attempts,
        "bands": bands,
    }


class JointRangeGTO41Bot(StreetEVGTO40Bot):
    """Same 3.3/4.0 frequency memory; uniform joint-range EV for 1+ villains."""

    def __init__(self, window=5):
        super().__init__(window=window)
        self.profile = "gto_postflop_41_" + str(window)

    def act(self, view):
        if view.street not in TRIALS:
            raise ValueError("GTO 4.1 is postflop-only")
        self._active_street = view.street
        self.observe_hand(
            getattr(view, "hand_id", None), getattr(view, "history", ()),
            getattr(view, "board", ()), view.me,
        )
        opponents = [str(p) for p in (getattr(view, "opponents", ()) or ())]
        legal = {a["type"]: a for a in (view.legal_actions or ())}
        call = max(0, int(view.to_call))
        if (not opponents or len(view.hole_cards or ()) != 2
                or len(view.board or ()) not in (3, 4, 5)):
            action = _fallthrough(view, fold=bool(call))
            self.last_model = {"version": "gto4.1", "mode": "invalid_input"}
            return action
        matrices = {pid: self.street_matrix(pid) for pid in opponents}
        deck, ranks, dist = _range_profile(
            tuple(view.hole_cards), tuple(view.board)
        )
        board_class = _board_class(view.board, view.street)
        wager = _amount(view, .50) if call == 0 and "bet" in legal else None
        amount = (int(wager.amount) if wager and wager.type == "bet" else None)
        joint = _estimate_joint(
            view, ranks, deck, opponents, matrices, TRIALS[view.street], amount
        )
        ev = {}
        if joint is None:
            action = _fallthrough(view, fold=bool(call))
            mode = "no_compatible_joint_ranges"
        elif call and {"call", "fold"} <= set(legal):
            ev = {"call": joint["call"], "fold": 0.0}
            action = Action("call" if joint["call"] > 0 else "fold")
            mode = "vs_bet"
        elif call == 0 and {"bet", "check"} <= set(legal) and amount is not None:
            ev = {"bet": joint["bet"], "check": joint["check"]}
            action = wager if joint["bet"] > joint["check"] else Action("check")
            mode = "bet_or_check"
        else:
            action = _fallthrough(view, fold=bool(call))
            mode = "restricted_legal"
        model = {
            "version": "gto4.1",
            "mode": "gto41_" + mode,
            "adapted": True,
            "board_classifier": board_class,
            "distribution": dist,
            "street_matrices": matrices,
            "ev": {k: round(v, 4) for k, v in ev.items()},
            "decision_inputs": {
                "joint_trials": joint["trials"] if joint else 0,
                "rejected_attempts": (joint["attempts"] - joint["trials"])
                                     if joint else 0,
                "opponent_bands": joint["bands"] if joint else {},
                "pot_odds": round(call / (max(1, view.pot) + call), 5),
                "bet_size": amount,
                "side_pot_approximation": bool(
                    getattr(view, "all_in_opponents", ()) or ()
                ),
            },
            "opponents_count": len(opponents),
        }
        self.last_model = model
        hid = getattr(view, "hand_id", None)
        if hid is not None:
            trace = {
                "hand_id": hid, "street": view.street,
                "board": ["".join(c) for c in view.board],
                "board150": board_class["id"] if board_class else None,
                "board_anytwo_rank_pair_pct":
                    AdaptiveGTO30Bot._anytwo_board_risk(view.board),
                "hero_hole": ["".join(c) for c in view.hole_cards],
                "hero_tier": "EV", "hero_made": "joint-range",
                "hero_draw_outs_estimate":
                    read_hand(view.hole_cards, view.board).draw_outs,
                "opponents_count": len(opponents),
                "decision": action.type, "amount_chips": action.amount,
                "decision_mode": "gto41_" + mode,
                "street_matrix": matrices[opponents[0]],
                "street_matrices": matrices,
                "opponents": [
                    {
                        "pid": pid,
                        "n": max(cell["n"] for g in matrices[pid][view.street].values()
                                 for cell in g.values()),
                        "fold": round(100 * matrices[pid][view.street]["vs_bet"]["fold"]["p"], 1),
                        "call": round(100 * matrices[pid][view.street]["vs_bet"]["call"]["p"], 1),
                        "raise": round(100 * matrices[pid][view.street]["vs_bet"]["raise"]["p"], 1),
                        "pooled_streets": False,
                    } for pid in opponents
                ],
                "ev": model["ev"], "equity_model": model["decision_inputs"],
                "distribution": dist,
                "reason": "GTO 4.1: full legal Any Two enumeration and joint "
                          "shared-runout multiway chipEV; Bet/Fold checkdown approximation",
            }
            if not self._trace or self._trace[-1]["hand_id"] != hid:
                self._trace.append({"hand_id": hid, "steps": []})
            self._trace[-1]["steps"].append(trace)
        return action
