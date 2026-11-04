"""GTO 3.1/5 and /10: public ALL-action opponent memory on GTO 2.1.

Unlike GTO 3.0 this observes all voluntary public actions (including
reactions to OTHER players), not only responses to our half-pot c-bets.
C-bet is distinguished from an ordinary postflop bet; Any Two forced
preflop Call/Check is excluded as non-informative.  Exact opponent hole
cards and simulator hidden state are NEVER available to this policy.

The estimated "strength_signal" is a conservative, UNCALIBRATED heuristic,
not a probability of a strong hand.  The strategy requires empirical EV
and showdown calibration; it is NOT a GTO solver.
"""
from __future__ import annotations

from collections import defaultdict, deque
from math import ceil
import os
import random

from bots.gto_postflop_21 import GTOPostflop21Bot
from bots.gto_postflop_20 import relative_tier
from bots.gto_postflop_30 import _board_class, AdaptiveGTO30Bot
from bots.postflop_profiles import _amount, _can_bluff, _fallthrough, _was_aggressor


_STREETS = {"flop": 3, "turn": 4, "river": 5}
_ALLOWED = {"fold", "check", "call", "bet", "raise"}
_PRIOR_STRENGTH = 4.0
_PRIORS = {
    "fold_to_bet": .35,
    "fold_to_cbet": .40,
    "call_to_bet": .50,
    "raise_to_bet": .15,
    "reraise_vs_raise": .08,
    "bet_when_checked": .45,
}
def _clamp(v, a, b):
    return min(b, max(a, v))

def _smoothed(k, n, prior):
    return (k + _PRIOR_STRENGTH * prior) / (n + _PRIOR_STRENGTH)


class AdaptiveGTO31Bot(GTOPostflop21Bot):
    """Bounded 5/10-action memory per villain. Only acts on observable data."""

    def __init__(self, window=5):
        if window not in (5, 10):
            raise ValueError("GTO 3.1: memory window must be 5 or 10")
        super().__init__()
        self.window = window
        self.profile = "gto_postflop_31_" + str(window)
        self.reset_memory()

    def reset_memory(self):
        self._events = defaultdict(lambda: deque(maxlen=self.window))
        self._hand_id = None
        self._seen_indexes = set()
        self._trace = deque(maxlen=5)
        self.last_model = None

    def observe_hand(self, hand_id, history, board, me):
        """Replay the public prefix; deduplicate by hand and action index.

        At hand end the engine passes the final public board.  Board codes
        are sliced to the historical street, never using future board cards.
        """
        if hand_id is None:
            return
        if hand_id != self._hand_id:
            self._hand_id = hand_id
            self._seen_indexes.clear()
        preflop_aggressor = None
        active_aggressor = {}
        active_aggressor_action = {}
        active_is_cbet = {}
        flop_open_seen = False
        street_raises = defaultdict(int)
        forced_anytwo = os.environ.get("POKER_PREFLOP_PROTOCOL") == "any_two_limp"
        cards = list(board or ())
        for index, e in enumerate(history or ()):
            if not isinstance(e, dict):
                continue
            street, pid, kind = e.get("street"), e.get("pid"), e.get("type")
            if street not in _STREETS and street != "preflop":
                continue
            if not pid or kind not in _ALLOWED:
                continue
            try:
                to_call = max(0, float(e.get("to_call_before") or 0))
                pot = max(0, float(e.get("pot_before") or 0))
            except (ValueError, TypeError):
                to_call, pot = 0.0, 0.0
            facing = to_call > 0
            # Must determine context BEFORE changing the active aggressor.
            facing_raise = facing and active_aggressor_action.get(street) == "raise"
            facing_cbet = (street == "flop" and facing
                           and active_is_cbet.get(street, False)
                           and pid != active_aggressor.get(street))
            is_reraise = kind == "raise" and street_raises[street] >= 1
            is_cbet = (street == "flop" and kind == "bet"
                       and not flop_open_seen and preflop_aggressor == pid)
            if index not in self._seen_indexes:
                self._seen_indexes.add(index)
                if pid != me and not (street == "preflop" and forced_anytwo):
                    count = _STREETS.get(street)
                    if count and len(cards) >= count:
                        board_code = _board_class(cards[:count], street)
                        board_id = board_code["id"] if board_code else None
                    else:
                        board_id = None
                    self._events[str(pid)].append({
                        "street": street, "action": kind, "facing": facing,
                        "facing_raise": facing_raise, "facing_cbet": facing_cbet,
                        "cbet": is_cbet, "reraise": is_reraise,
                        "board_id": board_id, "pot": pot, "to_call": to_call,
                    })
            if street == "preflop" and kind in ("bet", "raise"):
                preflop_aggressor = pid
            if street == "flop" and kind == "bet":
                flop_open_seen = True
            if kind in ("bet", "raise"):
                active_aggressor[street] = pid
                active_aggressor_action[street] = kind
                active_is_cbet[street] = is_cbet
            if kind == "raise":
                street_raises[street] += 1

    def opponent_stats(self, pid):
        """All rates use matching decision opportunities, not total hands."""
        rows = list(self._events.get(str(pid), ()))
        post = [r for r in rows if r["street"] in _STREETS]
        faced = [r for r in post if r["facing"] and r["action"] in ("fold", "call", "raise")]
        cbets = [r for r in faced if r["facing_cbet"]]
        faced_raise = [r for r in faced if r["facing_raise"]]
        unraised = [r for r in post if not r["facing"] and r["action"] in ("check", "bet")]
        def rate(sample, predicate, prior):
            k = sum(bool(predicate(r)) for r in sample)
            n = len(sample)
            return {"k": k, "n": n, "p": round(_smoothed(k, n, prior), 5)}
        metrics = {
            "fold_to_bet": rate(faced, lambda r:r["action"]=="fold", _PRIORS["fold_to_bet"]),
            "fold_to_cbet": rate(cbets, lambda r:r["action"]=="fold", _PRIORS["fold_to_cbet"]),
            "call_to_bet": rate(faced, lambda r:r["action"]=="call", _PRIORS["call_to_bet"]),
            "raise_to_bet": rate(faced, lambda r:r["action"]=="raise", _PRIORS["raise_to_bet"]),
            "reraise_vs_raise": rate(faced_raise, lambda r:r["reraise"], _PRIORS["reraise_vs_raise"]),
            "bet_when_checked": rate(unraised, lambda r:r["action"]=="bet", _PRIORS["bet_when_checked"]),
        }
        return {
            "n": len(rows), "postflop_n": len(post), "window": self.window,
            "counts": {a:sum(r["action"]==a for r in rows) for a in _ALLOWED},
            "metrics": metrics,
            "last_actions": tuple((r["street"],r["action"]) for r in rows),
        }

    @staticmethod
    def _pressure(view, stats):
        """Heuristic threat score for the CURRENT visible villain aggression.

        Do not claim this is P(strong hand): no strength labels are learned
        from folds/calls/raises. Strong/weak likelihood must be calibrated
        from showdown data in a later version.
        """
        aggressive = [r for r in (view.history or ())
                      if isinstance(r, dict) and r.get("street")==view.street
                      and r.get("type") in ("bet", "raise")]
        if not aggressive:
            return None
        current = aggressive[-1]
        if current.get("pid") not in (getattr(view, "opponents", ()) or ()):
            return None
        is_reraise = current.get("type")=="raise" and sum(
            r.get("type")=="raise" for r in aggressive) >= 2
        metric = ("reraise_vs_raise" if is_reraise else
                  "raise_to_bet" if current.get("type")=="raise" else
                  "bet_when_checked")
        base = .88 if is_reraise else .75 if current.get("type")=="raise" else .62
        prior = _PRIORS[metric]
        measured = stats["metrics"][metric]
        confidence = measured["n"] / (measured["n"] + _PRIOR_STRENGTH)
        signal = _clamp(base - .60 * (measured["p"] - prior) * confidence, .28, .95)
        return {"action": "reraise" if is_reraise else current["type"],
                "score": round(signal, 4),
                "kind": "uncalibrated_strength_signal",
                "metric": metric, "observations": measured["n"]}

    def trace_snapshot(self):
        return list(self._trace)

    def act(self, view):
        if view.street not in _STREETS:
            raise ValueError("GTO 3.1 is postflop-only")
        self.observe_hand(getattr(view, "hand_id", None),
                          getattr(view, "history", ()),
                          getattr(view, "board", ()), view.me)
        opponents = list(getattr(view, "opponents", ()) or ())
        villain = str(opponents[0]) if len(opponents) == 1 else None
        stats = self.opponent_stats(villain) if villain else None
        can_adapt = bool(stats and stats["postflop_n"] >= 3)
        pressure = self._pressure(view, stats) if can_adapt and view.to_call > 0 else None
        mode = "gto21_fallback"
        freq = None
        selected_fold_metric = None
        decision = None
        read = self._read_hand(list(view.hole_cards or ()), list(view.board or ()))
        tier = relative_tier(list(view.hole_cards or ()), list(view.board or ()))

        if can_adapt and view.to_call > 0 and pressure:
            # Tight/passive aggressors represent more strength; loose/
            # aggressive opponents less. This is a bounded heuristic,
            # NOT an equity estimate or a calibrated posterior.
            signal = pressure["score"]
            tuning = {
                "top_call_odds": _clamp(.25 + .28 * (.62 - signal), .15, .35),
                "weak_call_odds": _clamp(.14 + .20 * (.62 - signal), .06, .23),
                "draw_call_multiplier": _clamp(.95 + .85 * (.62 - signal), .65, 1.20),
            }
            self._policy_tuning = tuning
            try:
                decision = super().act(view)
            finally:
                del self._policy_tuning
            mode = "gto31_defense"
        elif (can_adapt and view.to_call == 0 and
              any(r.get("type")=="bet" for r in (view.legal_actions or ())) and
              stats["metrics"]["fold_to_bet"]["n"] >= 1):
            m = stats["metrics"]
            # A genuine flop continuation bet is meaningful only when
            # someone raised preflop. Any Two forced limps have no C-bet.
            selected_fold_metric = ("fold_to_cbet" if
                view.street == "flop" and _was_aggressor(view) and
                m["fold_to_cbet"]["n"] >= 1 else "fold_to_bet")
            fold = m[selected_fold_metric]["p"]
            call = m["call_to_bet"]["p"]
            raise_rate = m["raise_to_bet"]["p"]
            if tier >= 3:
                freq = _clamp(.80 + .45 * (call - .50), .48, .95)
            elif tier == 2:
                freq = _clamp(.58 + .55 * (call - .50), .20, .78)
            elif read.draw_outs >= 4 and view.street != "river":
                freq = _clamp(.59 + .90 * (fold - .35) - .25 * (raise_rate - .15),
                              .05, .80)
            elif read.made == "weak_pair":
                freq = .09 if view.street != "river" else 0.
            elif (read.made == "air" and _can_bluff(view) and
                  (view.stacks.get(view.me, 0) or 0)/max(1, view.pot) > .55):
                # Required fold equity for a zero-showdown-equity half-pot
                # bluff is 1/3; apply an additional margin for uncertainty.
                freq = _clamp(1.35 * (fold - .37) - .35 * raise_rate, 0, .60)
            if freq is not None:
                mode = "gto31_bet"
                if (tier < 3 and read.made == "air" and
                    (not _can_bluff(view) or
                     (view.stacks.get(view.me, 0) or 0)/max(1,view.pot)<=.55)):
                    freq = 0
                if random.random() < freq:
                    decision = _amount(view, .50)
                if decision is None:
                    decision = _fallthrough(view)
        if decision is None:
            decision = super().act(view)
        self.last_model = {
            "mode": mode, "adapted": mode != "gto21_fallback",
            "villain": villain, "stats": stats, "pressure": pressure,
            "hero_tier": tier, "hero_made": read.made,
            "bet_frequency": freq, "fold_metric": selected_fold_metric,
        }
        hand_id = getattr(view, "hand_id", None)
        if hand_id is not None:
            board = list(view.board or ())
            code = _board_class(board, view.street)
            m = stats["metrics"] if stats else {}
            step = {
                "street": view.street, "hand_id": hand_id,
                "hero_tier": tier, "hero_made": read.made,
                "hero_hole": ["".join(c) for c in (view.hole_cards or ())],
                "hero_draw_outs_estimate": read.draw_outs,
                "board": ["".join(c) for c in board],
                "board150": code["id"] if code else None,
                "board_anytwo_rank_pair_pct": AdaptiveGTO30Bot._anytwo_board_risk(board),
                "opponents_count": len(opponents),
                "decision": decision.type, "amount_chips": decision.amount,
                "decision_mode": mode,
                "opponents": ([{
                    "pid": villain, "n": stats["n"],
                    "fold": round(100*m["fold_to_bet"]["p"], 1),
                    "call": round(100*m["call_to_bet"]["p"], 1),
                    "raise": round(100*m["raise_to_bet"]["p"], 1),
                    "metrics": m, "pooled_streets": True,
                }] if stats else []),
                "pressure": pressure, "bet_frequency": freq,
                "fold_metric": selected_fold_metric,
                "reason": ("Оценка угрозы по действию соперника (эвристика, не equity)"
                           if pressure else "Частоты Fold/Call/Raise по всем игрокам"
                           if mode=="gto31_bet" else "GTO 2.1: мало данных или мультипот"),
            }
            if not self._trace or self._trace[-1]["hand_id"] != hand_id:
                self._trace.append({"hand_id": hand_id, "steps": []})
            self._trace[-1]["steps"].append(step)
        return decision
