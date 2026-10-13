"""A17 experimental preflop: legacy GTO charts with correct raise detection.

This is a bug-fixed heuristic, NOT a Nash-equilibrium/GTO solver.
It intentionally leaves bots.gto_bot.GTOBot unchanged for control runs.

Only the original preflop adjustment boundary changes: posting a blind
makes to_call > 0 even in unopened pots. Tighten only when an actual
opponent bet/raise is visible in the preflop action history.
"""
from __future__ import annotations

import random

from bots.gto_bot import GTOBot, _hand_key, _numeric_range


class FixedGTOPreflopBot(GTOBot):
    """Existing GTO group charts, corrected to distinguish blinds from raises."""

    @staticmethod
    def _facing_opponent_raise(state) -> bool:
        """True when a voluntary opponent preflop bet/raise preceded us.

        Engine history contains executed player actions, not blind postings.
        A raise by this bot alone is not a reason to tighten its own range.
        """
        me = getattr(state, "me", None)
        return any(
            isinstance(entry, dict)
            and entry.get("street") == "preflop"
            and entry.get("type") in ("raise", "bet", "all_in")
            and entry.get("pid") != me
            for entry in (getattr(state, "history", None) or ())
        )

    def _preflop(self, hole, position, pot, to_call, legal, state):
        r1, r2 = hole[0][0], hole[1][0]
        suited = hole[0][1] == hole[1][1]
        key = _hand_key(r1, r2, suited)
        n = len(state.stacks)

        # Work with both the original grouped charts and the newer
        # independent 54-position charts, without changing either baseline.
        own_ranges = getattr(self, "position_ranges", None)
        if own_ranges is not None:
            chart = own_ranges[n][str(position).upper()]
        else:
            chart = _numeric_range(position, n)

        fold_f, call_f, raise_f = chart.get(key, (0.85, 0.10, 0.05))

        # Crucial fix: to_call > 0 does NOT imply an opponent raise.
        # Unopened pots have a posted big blind, so they remain untightened.
        if to_call > 0 and self._facing_opponent_raise(state):
            fold_f = min(1.0, fold_f + 0.15 * (0.30 + fold_f))
            remainder = 1.0 - fold_f
            prior_continue = call_f + raise_f
            if prior_continue:
                call_f = remainder * call_f / prior_continue
                raise_f = remainder * raise_f / prior_continue
            else:
                call_f, raise_f = remainder, 0.0

        roll = random.random()
        if roll < fold_f:
            return self._do_fold_or_check(legal, to_call)
        if roll < fold_f + call_f:
            return self._do_call_or_check(legal, to_call)
        return self._do_raise(legal, pot, sizing_frac=0.70)
