"""GTO 3.0/5 and GTO 3.0/10 — experimental, NOT Nash/GTO solvers.

Learn the LAST 5 or 10 *observed responses to this bot's postflop bets*
per opponent, and use the existing P/S/F/SF/A physical-board classifier
to adjust betting of HERO's R0–R4 relative hand strength.

The information set is public history and HERO's own cards only; opponent
hole cards, showdown cards and hidden simulator state are never inspected.

Responses are observed at *hand completion* even if the opponent folded
and the bot would not get another PlayerView in that hand. In real tournaments
a split bot and the engine preserve memory; isolated Plan Monte Carlo trials
create fresh bots and therefore revert to the GTO 2.0 baseline until trained.
"""
from __future__ import annotations

from collections import defaultdict, deque
import random

from bots.gto_postflop_20 import GTOPostflop20Bot, relative_tier
from bots.postflop_profiles import _amount, _can_bluff, _fallthrough, _opponents
from postflop_board150 import RANKS, SUITS, classify_board


_STREETS = {"flop": 3, "turn": 4, "river": 5}
_ACTIONS = {"fold", "call", "raise"}
_PRIOR = {"fold": 0.35, "call": 0.50, "raise": 0.15}
_PRIOR_STRENGTH = 4.0  # shrinkage prevents 1/5 being treated as ground truth


def _board_class(board, street):
    """Canonical Board150 code for a *visible* 3/4/5-card street."""
    count = _STREETS[street]
    if len(board) < count:
        return None
    try:
        cards = [(RANKS.index(c[0]) * 4 + SUITS.index(c[1]))
                 for c in board[:count]]
        return classify_board(cards, street)
    except (ValueError, IndexError, TypeError, KeyError):
        return None


def _half_pot_response(entry):
    """Only compare facing a roughly half-pot wager, not shove/overbet."""
    try:
        amount = float(entry["to_call_before"])
        before = float(entry["pot_before"])
    except (KeyError, ValueError, TypeError, ZeroDivisionError):
        return False
    pot_before_bet = before - amount
    return amount > 0 and pot_before_bet > 0 and 0.30 <= amount / pot_before_bet <= 0.80


class AdaptiveGTO30Bot(GTOPostflop20Bot):
    def __init__(self, window=5):
        if window not in (5, 10):
            raise ValueError("GTO 3.0: window must be 5 or 10")
        super().__init__()
        self.window = window
        self.profile = "gto_postflop_30_{}".format(window)
        self.reset_memory()

    def reset_memory(self):
        self._observed = defaultdict(lambda: deque(maxlen=self.window))
        self._seen = set()
        self._seen_hand_id = None
        self.last_model = None

    def observe_hand(self, hand_id, history, board, me):
        """Consume observable street responses once; one per pid/street/hand.

        A call or raise must actually FACING this bot's last bet/raise.
        Does not count passive checks, blind calls, voluntary bets,
        or opponents responding to third-party aggression.
        """
        if hand_id is None:
            return
        if self._seen_hand_id != hand_id:
            self._seen.clear()  # bound dedup memory to one tournament hand
            self._seen_hand_id = hand_id
        current_aggressor = {}
        for row in history or ():
            if not isinstance(row, dict):
                continue
            street = row.get("street")
            if street not in _STREETS:
                continue
            pid = row.get("pid")
            action = row.get("type")
            # First classify the RESPONSE to the previous aggressor.
            # Processing a villain's raise as a new aggressor *before*
            # observing it would incorrectly discard every raise.
            if pid != me and action in _ACTIONS and (
                    current_aggressor.get(street) == me and
                    _half_pot_response(row)):
                key = (hand_id, street, pid)
                if key not in self._seen:
                    classification = _board_class(board, street)
                    if classification is not None:
                        self._seen.add(key)
                        self._observed[pid].append(
                            (action, street, classification["id"]))
            if action in ("bet", "raise"):
                current_aggressor[street] = pid

    def opponent_stats(self, pid, *, street=None):
        """Smoothed probabilities plus unshrunk sample counts for audit."""
        rows = list(self._observed.get(pid, ()))
        on_street = [row for row in rows if row[1] == street]
        # Too few same-street events? Pool across all postflop streets.
        selected = on_street if len(on_street) >= 3 else rows
        n = len(selected)
        counts = {kind: sum(row[0] == kind for row in selected)
                  for kind in _ACTIONS}
        rates = {kind: (_PRIOR_STRENGTH * _PRIOR[kind] + counts[kind]) /
                        (_PRIOR_STRENGTH + n) for kind in _ACTIONS}
        return {"n": n, "window": self.window, "counts": counts, "rates": rates,
                "board_classes": tuple(row[2] for row in selected),
                "pooled": len(on_street) < 3}

    def _current_stats(self, view):
        ids = list(getattr(view, "opponents", ()) or ())
        if len(ids) != 1:
            return None  # multiway: never falsely infer one villain's folds
        model = self.opponent_stats(ids[0], street=view.street)
        if model["n"] < 3:
            return None
        return model

    def _baseline(self, view):
        # Preserve the original GTO 2.0 action decision while standardizing
        # an unopened pot bet to half-pot for the observational experiment.
        chosen = super().act(view)
        if chosen.type == "bet":
            return _amount(view, .50) or chosen
        return chosen

    def act(self, view):
        if view.street not in _STREETS:
            raise ValueError("GTO 3.0 is a postflop-only policy")
        # Read public responses already completed in this hand, without waiting
        # for a future action; duplicate processing is eliminated by _seen.
        self.observe_hand(getattr(view, "hand_id", None),
                          view.history, view.board, view.me)
        board = list(view.board or ())
        hole = list(view.hole_cards or ())
        classification = _board_class(board, view.street)
        model = self._current_stats(view)
        self.last_model = {
            "board_id": classification["id"] if classification else None,
            "opponent": list(getattr(view, "opponents", ()) or ()),
            "stats": model,
            "relative_tier": relative_tier(hole, board),
        }
        # Do not invent learned behavior on the first hands / in 1-hand EV.
        if model is None or classification is None:
            return self._baseline(view)
        legal = {v["type"] for v in (view.legal_actions or ())}
        read = self._read_hand(hole, board)
        tier = self.last_model["relative_tier"]
        rates = model["rates"]
        # The board code supplies texture, not an estimated adversary range.
        wet = (int(classification["f"][1:]) >= 2 or
               int(classification["s"][1:]) >= 1 or
               classification["p"] not in ("P0",))
        very_wet = (int(classification["f"][1:]) >= 3 or
                    int(classification["s"][1:]) >= 3)
        # Facing a bet, observed reaction-to-our-cbet is NOT a model of
        # villain's bluffing frequency; retain the vetted GTO 2.0 defense.
        if view.to_call > 0 or "bet" not in legal or not _can_bluff(view):
            return self._baseline(view)

        if tier >= 3:
            # Value bet slightly more versus calling stations, but a scary
            # board tempers thin value; half-pot is the comparison standard.
            chance = min(.95, max(.48, .70 + .45 * (rates["call"] - .50)
                                  - (.08 if very_wet else 0)))
        elif tier == 2:
            chance = min(.72, max(.15, .37 + .60 * (rates["call"] - .50)
                                  - (.15 if very_wet else .05 if wet else 0)))
        elif read.draw_outs >= 4 and view.street != "river":
            chance = min(.75, max(.06, .24 + 1.0 * (rates["fold"] - .35)
                                  - .30 * (rates["raise"] - .15)))
        else:
            # Zero-equity pure-bluff threshold for half-pot: 33.3% folds.
            # Riskier board classes lower the frequency; no automatic
            # profitable-bluff claim because showdown/realization is unknown.
            chance = min(.70, max(0.0, 1.25 * (rates["fold"] - 1/3)
                                  - .50 * rates["raise"]
                                  - (.14 if very_wet else .07 if wet else 0)))
        if random.random() < chance:
            bet = _amount(view, .50)
            if bet:
                return bet
        return _fallthrough(view)
