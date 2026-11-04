"""GTO 3.2: memory of the last N *opportunities* for EACH action metric.

A separate bounded deque is maintained for every (opponent, metric); only
a genuine eligible decision adds 0 or 1. Example: 4 RFI out of 10 RFI
opportunities = 40%, regardless of unrelated hands or actions.

Engine history carries PUBLIC legal action types at decision time. Never
infer a missed raise opportunity if raise was illegal due to stack/rules.
All opponent actions, including responses to other players, are observed.
Original GTO 2.1 is used as baseline. No opponent cards / Nash solving.
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

# Explicit denominator and prior for every conditional frequency.
METRICS = {
    "rfi": .27,
    "fold_to_raise": .50,
    "three_bet": .09,
    "four_bet": .08,
    "fold_to_three_bet": .50,
    "cbet": .62,
    "fold_to_cbet": .40,
    "bet_flop": .45,
    "raise_flop": .15,
    "reraise": .08,
    "fold_to_bet": .35,
    "call_to_bet": .50,
    "raise_to_bet": .15,
    "bet_when_checked": .45,
}
STREETS = {"flop", "turn", "river"}
PRIOR_WEIGHT = 4.0


def clamp(value, low, high):
    return max(low, min(high, value))


class OpportunityGTO32Bot(GTOPostflop21Bot):
    def __init__(self, window=5):
        if window not in (5, 10):
            raise ValueError("GTO 3.2 opportunity window must be 5 or 10")
        super().__init__()
        self.window = window
        self.profile = "gto_postflop_32_" + str(window)
        self.reset_memory()

    def reset_memory(self):
        self._memory = defaultdict(dict)
        self._hand_id = None
        self._seen = set()
        self.last_model = None
        self._trace = deque(maxlen=5)

    def _remember(self, pid, metric, success):
        store = self._memory[str(pid)]
        if metric not in store:
            store[metric] = deque(maxlen=self.window)
        store[metric].append(1 if success else 0)

    def opponent_stats(self, pid):
        entries = self._memory.get(str(pid), {})
        metrics = {}
        for name, prior in METRICS.items():
            seq = entries.get(name, ())
            n, k = len(seq), sum(seq)
            metrics[name] = {
                "n": n, "k": k, "raw": round(k / n, 5) if n else None,
                "p": round((k + PRIOR_WEIGHT * prior) /
                           (n + PRIOR_WEIGHT), 5),
            }
        return {"window": self.window, "metrics": metrics,
                "max_opportunities": max((row["n"] for row in metrics.values()),
                                          default=0)}

    def observe_hand(self, hand_id, history, board, me):
        """Read all public actions, counting only genuine legal opportunities.

        legal_types reflects the actions offered at the time, including
        stack-constrained unavailable raises. Older history without this
        metadata is NOT used as a denominator.
        """
        if hand_id is None:
            return
        if self._hand_id != hand_id:
            self._hand_id = hand_id
            self._seen.clear()

        voluntary_preflop_entry = False
        preflop_raise_count = 0
        preflop_aggressor = None
        last_aggressor = {}
        last_aggression = {}
        last_flop_bet_is_cbet = False
        flop_bet_seen = False
        forced_anytwo = os.environ.get("POKER_PREFLOP_PROTOCOL") == "any_two_limp"

        for i, entry in enumerate(history or ()):
            if not isinstance(entry, dict):
                continue
            street = entry.get("street")
            pid = entry.get("pid")
            kind = entry.get("type")
            if street not in (STREETS | {"preflop"}) or not pid or kind not in (
                "fold", "check", "call", "bet", "raise"):
                continue
            try:
                to_call = float(entry.get("to_call_before") or 0)
            except (ValueError, TypeError):
                to_call = 0
            legal = set(entry.get("legal_types") or ())
            facing = to_call > 0
            previous = last_aggression.get(street)
            previous_pid = last_aggressor.get(street)
            facing_bet = facing and previous == "bet" and pid != previous_pid
            facing_raise = facing and previous == "raise" and pid != previous_pid
            is_flop_cbet = (street == "flop" and kind == "bet" and
                            not flop_bet_seen and preflop_aggressor == pid and
                            not forced_anytwo)
            facing_cbet = (street == "flop" and facing_bet and
                           last_flop_bet_is_cbet)
            eligible = (i not in self._seen and pid != me and
                        bool(legal) and not (street == "preflop" and forced_anytwo))

            if eligible:
                self._seen.add(i)
                if street == "preflop":
                    # RFI is the FIRST voluntary entry. A limp makes any
                    # later raise an isolation raise, not a first-in raise.
                    if not voluntary_preflop_entry and "raise" in legal:
                        self._remember(pid, "rfi", kind == "raise")
                    if facing_raise and "fold" in legal:
                        self._remember(pid, "fold_to_raise", kind == "fold")
                        if preflop_raise_count == 2:
                            self._remember(pid, "fold_to_three_bet", kind == "fold")
                    if facing_raise and "raise" in legal:
                        if preflop_raise_count == 1:
                            self._remember(pid, "three_bet", kind == "raise")
                        elif preflop_raise_count == 2:
                            self._remember(pid, "four_bet", kind == "raise")
                        self._remember(pid, "reraise", kind == "raise")
                else:
                    if "bet" in legal and not facing:
                        self._remember(pid, "bet_when_checked", kind == "bet")
                        if street == "flop":
                            self._remember(pid, "bet_flop", kind == "bet")
                        if (street == "flop" and not flop_bet_seen and
                                pid == preflop_aggressor and not forced_anytwo):
                            self._remember(pid, "cbet", kind == "bet")
                    if facing_bet:
                        if "fold" in legal:
                            self._remember(pid, "fold_to_bet", kind == "fold")
                        if "call" in legal:
                            self._remember(pid, "call_to_bet", kind == "call")
                        if "raise" in legal:
                            self._remember(pid, "raise_to_bet", kind == "raise")
                    if facing_cbet and "fold" in legal:
                        self._remember(pid, "fold_to_cbet", kind == "fold")
                    if facing_raise and "fold" in legal:
                        self._remember(pid, "fold_to_raise", kind == "fold")
                    if street == "flop" and facing and "raise" in legal:
                        self._remember(pid, "raise_flop", kind == "raise")
                    if facing_raise and "raise" in legal:
                        self._remember(pid, "reraise", kind == "raise")

            # Reconstruct historical context for both seen and unseen rows.
            if street == "preflop":
                if kind in ("call", "raise", "bet"):
                    voluntary_preflop_entry = True
                if kind in ("raise", "bet"):
                    preflop_raise_count += 1
                    preflop_aggressor = pid
            if street == "flop" and kind == "bet":
                flop_bet_seen = True
                last_flop_bet_is_cbet = is_flop_cbet
            elif street == "flop" and kind == "raise":
                last_flop_bet_is_cbet = False
            if kind in ("bet", "raise"):
                last_aggressor[street] = pid
                last_aggression[street] = kind

    def _pressure(self, view, stats):
        # This is an UNCALIBRATED risk/strength signal, NOT a posterior.
        rows = [r for r in (getattr(view, "history", ()) or ())
                if isinstance(r, dict) and r.get("street") == view.street
                and r.get("type") in ("bet", "raise")]
        if not rows or rows[-1].get("pid") not in (view.opponents or ()):
            return None
        last = rows[-1]
        is_reraise = last["type"] == "raise" and sum(
            r["type"] == "raise" for r in rows) >= 2
        if is_reraise:
            metric, base = "reraise", .88
        elif last["type"] == "raise":
            metric, base = ("raise_flop" if view.street == "flop"
                            else "raise_to_bet"), .75
        else:
            metric, base = "bet_when_checked", .62
        info = stats["metrics"][metric]
        if info["n"] < 3:
            return None
        confidence = info["n"] / (info["n"] + PRIOR_WEIGHT)
        score = clamp(base - .60 * (info["p"] - METRICS[metric]) * confidence,
                      .28, .95)
        return {"kind": "uncalibrated_strength_signal",
                "action": ("reraise" if is_reraise else last["type"]),
                "metric": metric, "score": round(score, 4),
                "observations": info["n"]}

    def trace_snapshot(self):
        return list(self._trace)

    def act(self, view):
        if view.street not in STREETS:
            raise ValueError("GTO 3.2 is postflop-only")
        self.observe_hand(getattr(view, "hand_id", None),
                          getattr(view, "history", ()),
                          getattr(view, "board", ()), view.me)

        opponents = list(getattr(view, "opponents", ()) or ())
        villain = str(opponents[0]) if len(opponents) == 1 else None
        stats = self.opponent_stats(villain) if villain else None
        metrics = stats["metrics"] if stats else None
        read = self._read_hand(list(view.hole_cards or ()),
                               list(view.board or ()))
        tier = relative_tier(list(view.hole_cards or ()),
                             list(view.board or ()))
        mode, frequency, signal, active_metric = "gto21_fallback", None, None, None
        action = None

        if villain and view.to_call > 0:
            signal = self._pressure(view, stats)
            if signal is not None:
                risk = signal["score"]
                self._policy_tuning = {
                    "top_call_odds": clamp(.25 + .28 * (.62 - risk), .15, .35),
                    "weak_call_odds": clamp(.14 + .20 * (.62 - risk), .06, .23),
                    "draw_call_multiplier": clamp(
                        .95 + .85 * (.62 - risk), .65, 1.20),
                }
                try:
                    action = super().act(view)
                finally:
                    del self._policy_tuning
                mode, active_metric = "gto32_defense", signal["metric"]

        elif villain and view.to_call == 0 and any(
                a.get("type") == "bet" for a in (view.legal_actions or ())):
            fold_key = ("fold_to_cbet" if view.street == "flop" and
                        _was_aggressor(view) and
                        metrics["fold_to_cbet"]["n"] >= 3
                        else "fold_to_bet")
            fold = metrics[fold_key]
            calling = metrics["call_to_bet"]
            raise_rate = metrics["raise_to_bet"]
            if tier >= 3 and calling["n"] >= 3:
                frequency = clamp(.80 + .45 * (calling["p"] - .50), .48, .95)
                active_metric = "call_to_bet"
            elif tier == 2 and calling["n"] >= 3:
                frequency = clamp(.58 + .55 * (calling["p"] - .50), .20, .78)
                active_metric = "call_to_bet"
            elif (read.draw_outs >= 4 and view.street != "river"
                  and fold["n"] >= 3):
                frequency = clamp(.59 + .90 * (fold["p"] - METRICS[fold_key])
                                  - .25 * (raise_rate["p"] - .15), .05, .80)
                active_metric = fold_key
            elif (tier == 0 and read.made == "air"
                  and fold["n"] >= 3 and _can_bluff(view)
                  and (view.stacks.get(view.me, 0) or 0) /
                        max(1, view.pot) > .55):
                frequency = clamp(1.35 * (fold["p"] - .37)
                                  - .35 * raise_rate["p"], 0, .60)
                active_metric = fold_key
            if frequency is not None:
                mode = "gto32_bet"
                action = (_amount(view, .50) if
                          random.random() < frequency else None)
                if action is None:
                    action = _fallthrough(view)

        if action is None:
            action = super().act(view)

        self.last_model = {
            "mode": mode, "adapted": mode != "gto21_fallback",
            "villain": villain, "stats": stats, "pressure": signal,
            "hero_tier": tier, "hero_made": read.made,
            "bet_frequency": frequency, "active_metric": active_metric,
        }
        hand_id = getattr(view, "hand_id", None)
        if hand_id is not None:
            board = list(view.board or ())
            code = _board_class(board, view.street)
            step = {
                "hand_id": hand_id, "street": view.street,
                "hero_hole": ["".join(card) for card in (view.hole_cards or ())],
                "hero_tier": tier, "hero_made": read.made,
                "hero_draw_outs_estimate": read.draw_outs,
                "board": ["".join(card) for card in board],
                "board150": code["id"] if code else None,
                "opponents_count": len(opponents),
                "board_anytwo_rank_pair_pct": AdaptiveGTO30Bot._anytwo_board_risk(board),
                "decision": action.type, "amount_chips": action.amount,
                "decision_mode": mode, "bet_frequency": frequency,
                "active_metric": active_metric, "pressure": signal,
                "opponents": ([{
                    "pid": villain, "n": stats["max_opportunities"],
                    "metrics": metrics,
                    "fold": round(metrics["fold_to_bet"]["p"] * 100, 1),
                    "call": round(metrics["call_to_bet"]["p"] * 100, 1),
                    "raise": round(metrics["raise_to_bet"]["p"] * 100, 1),
                    "pooled_streets": True,
                }] if villain else []),
                "reason": ("Условные частоты по отдельным окнам возможностей"
                           if mode != "gto21_fallback" else
                           "GTO 2.1: недостаточно сравнимых возможностей"),
            }
            if not self._trace or self._trace[-1]["hand_id"] != hand_id:
                self._trace.append({"hand_id": hand_id, "steps": []})
            self._trace[-1]["steps"].append(step)
        return action
