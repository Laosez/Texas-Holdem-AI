"""A17 positional opening policy across 2-9 seated players.

The user-approved numeric-position thresholds are stable across the
elimination stages: '6' always has A01-A10, '3' always has A01-A15.
For 9-max, '9' is UTG; at 6-max, '6' is UTG and still opens A01-A10.

SB at every tournament stage: raise A01-A16 (including when facing a
voluntary raise, subject to legal raise availability); A17 call/check.
BB and all other non-RFI cases retain the separate fixed-GTO heuristic
until the user defines their corresponding ranges.

This is a custom strategy, not solver-derived GTO.
"""
from bots.a17_ranges import (
    A17_HAND_TO_BOX,
    A17_MAX_OPEN_BOX_BY_POSITION,
    A17_SB_MAX_RAISE_BOX,
)
from bots.gto_bot import _hand_key
from bots.gto_fixed_bot import FixedGTOPreflopBot


class A17PreflopBot(FixedGTOPreflopBot):
    """User A17 chart, evaluated by numeric position at all 2–9-max stages."""

    def _preflop(self, hole, position, pot, to_call, legal, state):
        n = len(state.stacks)
        pos = str(position).upper()
        # '10' (10-max) is not specified, nor is the BB defense chart.
        if not 2 <= n <= 9 or pos == "BB" or pos not in A17_MAX_OPEN_BOX_BY_POSITION:
            return super()._preflop(hole, position, pot, to_call, legal, state)

        r1, r2 = hole[0][0], hole[1][0]
        key = _hand_key(r1, r2, hole[0][1] == hole[1][1])
        box = A17_HAND_TO_BOX[key]

        if pos == "SB":
            # In every tournament stage, A01-A16 raises even facing a
            # prior opponent raise. Legal-action fallback from _do_raise
            # calls/checks when another raise is unavailable.
            if box <= A17_SB_MAX_RAISE_BOX:
                return self._do_raise(legal, pot, sizing_frac=0.70)
            # A17 remains call/complete/check (never voluntarily folds).
            return self._do_call_or_check(legal, to_call)

        if self._facing_opponent_raise(state):
            return super()._preflop(hole, position, pot, to_call, legal, state)

        # RFI: nobody has entered voluntarily on preflop.
        # A prior limp means the next action is not RFI and still uses
        # the earlier fixed-GTO heuristic, without inventing iso ranges.
        history = getattr(state, "history", None) or ()
        entered = any(
            isinstance(entry, dict)
            and entry.get("street") == "preflop"
            and entry.get("type") in ("call", "raise", "bet", "all_in")
            for entry in history
        )
        if entered:
            return super()._preflop(hole, position, pot, to_call, legal, state)

        if box <= A17_MAX_OPEN_BOX_BY_POSITION[pos]:
            return self._do_raise(legal, pot, sizing_frac=0.70)
        return self._do_fold_or_check(legal, to_call)
