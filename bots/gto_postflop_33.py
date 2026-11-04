"""GTO 3.3 — street-specific 8 × 3 opportunity matrix; GTO 3.2 policy unchanged.

Each opponent has three categorical opportunity windows on EACH of flop,
turn and river:
  open:       check | bet
  facing bet: fold | call | raise
  facing raise: fold | call | reraise

Thus 9 queues -> 24 visible probabilities, window 5 or 10 in each queue.
Only decisions with ALL actions of that context legally available are
recorded, so probabilities have a comparable denominator and sum to 100%.

Action selection is INHERITED UNCHANGED from GTO 3.2 (and GTO 2.1's
half-pot sizes and R0-R4 reader). The old pooled postflop frequency lookup
is replaced by this version's per-street estimates with low-sample fallback.
"""
from __future__ import annotations

from collections import Counter, defaultdict, deque

from bots.gto_postflop_32 import (
    METRICS,
    PRIOR_WEIGHT,
    OpportunityGTO32Bot,
)

STREETS = ("flop", "turn", "river")
GROUPS = {
    "open": ("check", "bet"),
    "vs_bet": ("fold", "call", "raise"),
    "vs_raise": ("fold", "call", "reraise"),
}
PRIORS = {
    "open": {"check": .55, "bet": .45},
    "vs_bet": {"fold": .35, "call": .50, "raise": .15},
    "vs_raise": {"fold": .50, "call": .42, "reraise": .08},
}
# The inherited 3.2 decision engine looks up these names. Map only its
# postflop metrics; preflop RFI and C-bet context are intentionally absent.
LOOKUPS = {
    "fold_to_bet": ("vs_bet", "fold"),
    "call_to_bet": ("vs_bet", "call"),
    "raise_to_bet": ("vs_bet", "raise"),
    "bet_when_checked": ("open", "bet"),
    "raise_flop": ("vs_bet", "raise"),
    "reraise": ("vs_raise", "reraise"),
    "fold_to_raise": ("vs_raise", "fold"),
    "bet_flop": ("open", "bet"),
}


class StreetMatrixGTO33Bot(OpportunityGTO32Bot):
    """Same 3.2 action formulas, 24 street-conditional behavior probabilities."""

    def __init__(self, window=10):
        super().__init__(window=window)
        self.profile = "gto_postflop_33_" + str(window)

    def reset_memory(self):
        super().reset_memory()
        self._street = defaultdict(dict)
        self._pooled = defaultdict(dict)
        self._active_street = None

    def _append(self, pid, street, group, outcome):
        pid = str(pid)
        store = self._street[pid]
        key = (street, group)
        if key not in store:
            store[key] = deque(maxlen=self.window)
        store[key].append(outcome)
        pooled = self._pooled[pid]
        if group not in pooled:
            pooled[group] = deque(maxlen=self.window)
        pooled[group].append((street, outcome))

    def observe_hand(self, hand_id, history, board, me):
        """Only public, eligible decision opportunities; safe on repeated replay."""
        if hand_id is None:
            return
        if self._hand_id != hand_id:
            self._hand_id = hand_id
            self._seen.clear()
        last_aggression = {}
        last_aggressor = {}
        for index, event in enumerate(history or ()):
            if not isinstance(event, dict):
                continue
            street = event.get("street")
            pid = event.get("pid")
            action = event.get("type")
            if street not in STREETS or not pid or action not in (
                "fold", "call", "check", "bet", "raise"):
                continue
            legal = set(event.get("legal_types") or ())
            try:
                facing = float(event.get("to_call_before") or 0) > 0
            except (TypeError, ValueError):
                facing = False
            if not facing:
                group = "open"
                result = action
            elif last_aggression.get(street) == "bet" and (
                    last_aggressor.get(street) != pid):
                group = "vs_bet"
                result = action
            elif last_aggression.get(street) == "raise" and (
                    last_aggressor.get(street) != pid):
                group = "vs_raise"
                result = "reraise" if action == "raise" else action
            else:
                group, result = None, None

            # With only Fold/Call legal, the missing Raise is NOT a
            # voluntarily rejected Raise; omit this context from the
            # comparable three-way sample. Likewise omit forced checks.
            complete = False
            if group:
                expected = {"raise" if a == "reraise" else a
                            for a in GROUPS[group]}
                complete = expected.issubset(legal)
            if (index not in self._seen and str(pid) != str(me) and
                    complete and result in GROUPS[group]):
                self._seen.add(index)
                self._append(pid, street, group, result)
            # Replay all public actions, including already-seen actions,
            # to reconstruct the actual context for later events.
            if action in ("bet", "raise"):
                last_aggression[street] = action
                last_aggressor[street] = pid

    @staticmethod
    def _posterior(rows, prior):
        n = len(rows)
        counts = Counter(rows)
        return {
            outcome: (counts[outcome] + PRIOR_WEIGHT * p) /
                     (n + PRIOR_WEIGHT)
            for outcome, p in prior.items()
        }

    def _context(self, pid, street, group):
        """Hierarchical shrinkage: street >=5, else similar pooled history.

        Pooled sample is used only as a fallback, and street observations
        are not double-counted when borrowing from OTHER streets.
        """
        local = list(self._street.get(str(pid), {}).get((street, group), ()))
        pool = list(self._pooled.get(str(pid), {}).get(group, ()))
        other = [outcome for st, outcome in pool if st != street]
        prior = PRIORS[group]
        if len(local) >= 5:
            source = "street"
            probabilities = self._posterior(local, prior)
            effective_n = len(local)
        elif len(pool) >= 5:
            # When OTHER streets are informative, use their smoothed
            # distribution as four virtual observations for the street.
            if len(other) >= 3 and local:
                p_other = self._posterior(other, prior)
                counts = Counter(local)
                probabilities = {
                    outcome: (counts[outcome] + PRIOR_WEIGHT * p_other[outcome]) /
                             (len(local) + PRIOR_WEIGHT)
                    for outcome in prior
                }
                source = "street_shrunk_to_other_streets"
            else:
                probabilities = self._posterior(
                    [outcome for _, outcome in pool], prior)
                source = "pooled_fallback"
            effective_n = len(pool)
        else:
            probabilities = self._posterior(local, prior)
            source = "insufficient"
            # Parent GTO 3.2 requires n>=3 to adapt. Here each street
            # source requires >=5 comparable opportunities; otherwise
            # the original baseline GTO 2.1 makes the decision.
            effective_n = 0

        counts = Counter(local)
        return {
            outcome: {
                "k": counts[outcome],
                "n": len(local),
                "raw": round(counts[outcome] / len(local), 5) if local else None,
                "p": round(probabilities[outcome], 5),
                "effective_n": effective_n,
                "pooled_n": len(pool),
                "source": source,
            }
            for outcome in prior
        }

    def street_matrix(self, pid):
        """All 24 cells including empty samples and their source."""
        return {
            street: {
                group: self._context(pid, street, group)
                for group in GROUPS
            }
            for street in STREETS
        }

    def opponent_stats(self, pid):
        # Adapter: same metric names consumed by GTO 3.2 formulas,
        # but every value is now tied to the current decision street.
        street = self._active_street or "flop"
        groups = {
            group: self._context(pid, street, group)
            for group in GROUPS
        }
        metrics = {}
        for name, prior in METRICS.items():
            if name in LOOKUPS and not (
                    name == "bet_flop" and street != "flop") and not (
                    name == "raise_flop" and street != "flop"):
                group, outcome = LOOKUPS[name]
                cell = groups[group][outcome]
                metrics[name] = {
                    **cell,
                    # Inherited 3.2 checks 'n>=3' to activate corrections.
                    "n": cell["effective_n"],
                    "street_n": cell["n"],
                }
            else:
                metrics[name] = {
                    "n": 0, "k": 0, "raw": None, "p": prior,
                    "street_n": 0, "pooled_n": 0,
                    "effective_n": 0, "source": "not_in_24",
                }
        return {
            "window": self.window,
            "metrics": metrics,
            "max_opportunities": max(
                (value["n"] for value in metrics.values()), default=0),
            "street": street,
            "opportunity_matrix": groups,
        }

    def act(self, view):
        self._active_street = view.street
        action = super().act(view)
        villain = self.last_model.get("villain") if self.last_model else None
        if villain:
            groups = self.street_matrix(villain)
            self.last_model["street_matrix"] = groups
            self.last_model["version"] = "gto3.3"
            if getattr(view, "hand_id", None) is not None and self._trace:
                steps = self._trace[-1].get("steps", ())
                if steps:
                    steps[-1]["street_matrix"] = groups
                    steps[-1]["reason"] += (
                        " · GTO 3.3: память 24 исходов по улицам")
        return action
