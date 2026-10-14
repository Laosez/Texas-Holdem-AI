"""A17 positional opening policy across 2-9 seated players.

The user-approved numeric-position thresholds are stable across the
elimination stages: '6' always opens A01-A10, '5' and '4' A01-A11,
and '3' A01-A12 plus the non-contiguous A15 (not A13/A14).
For 9-max, '9' is UTG; at 6-max, '6' is UTG and still opens A01-A10.

The first response when facing exactly a three-bet takes precedence
at every table size and position, including SB/BB: A01-A07 and A09 mix
50% four-bet, 50% call; A08 and A10-A17 fold. A four-bet choice that
is not legal falls back to call/check using the existing raise helper.

Otherwise SB at every tournament stage raises A01-A16 (subject to
legal raise availability); A17 calls/checks. BB and all other non-RFI
cases retain the separate fixed-GTO heuristic.

This is a custom strategy, not solver-derived GTO.
"""
import random

from bots.a17_ranges import (
    A17_HAND_TO_BOX,
    A17_MAX_OPEN_BOX_BY_POSITION,
    A17_RFI_EXTRA_BOXES_BY_POSITION,
    A17_SB_MAX_RAISE_BOX,
    A17_VS_3BET_CONTINUE_BOXES,
    A17_VS_3BET_FOURBET_FREQ,
)
from bots.gto_bot import _hand_key
from bots.gto_fixed_bot import FixedGTOPreflopBot


class A17PreflopBot(FixedGTOPreflopBot):
    """User A17 chart, evaluated by numeric position at all 2–9-max stages."""

    @staticmethod
    def _facing_three_bet(state, to_call):
        """Detect the second preflop voluntary raise, not a blind or a 4-bet.

        Engine history contains executed player actions; blinds are not
        stored as raises. The last aggressor must be an opponent, and
        this player must actually have chips to call.
        """
        if to_call <= 0:
            return False
        raises = [
            entry for entry in (getattr(state, "history", None) or ())
            if isinstance(entry, dict)
            and entry.get("street") == "preflop"
            and entry.get("type") in ("raise", "bet")
        ]
        return (
            len(raises) == 2
            and raises[-1].get("pid") != getattr(state, "me", None)
        )

    def _preflop(self, hole, position, pot, to_call, legal, state):
        n = len(state.stacks)
        pos = str(position).upper()
        r1, r2 = hole[0][0], hole[1][0]
        key = _hand_key(r1, r2, hole[0][1] == hole[1][1])
        box = A17_HAND_TO_BOX[key]

        # The user's 3-bet response overrides all positional rules,
        # including SB A01-A16 raise and BB fixed-GTO defense.
        if self._facing_three_bet(state, to_call):
            if box not in A17_VS_3BET_CONTINUE_BOXES:
                return self._do_fold_or_check(legal, to_call)
            if random.random() < A17_VS_3BET_FOURBET_FREQ:
                return self._do_raise(legal, pot, sizing_frac=0.70)
            return self._do_call_or_check(legal, to_call)

        # '10' (10-max) is not specified, nor is the BB defense chart.
        if not 2 <= n <= 9 or pos == "BB" or pos not in A17_MAX_OPEN_BOX_BY_POSITION:
            return super()._preflop(hole, position, pot, to_call, legal, state)

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

        if (box <= A17_MAX_OPEN_BOX_BY_POSITION[pos]
                or box in A17_RFI_EXTRA_BOXES_BY_POSITION.get(pos, ())):
            return self._do_raise(legal, pot, sizing_frac=0.70)
        return self._do_fold_or_check(legal, to_call)
