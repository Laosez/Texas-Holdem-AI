"""A17 positional 9-max opening policy; other scenarios keep fixed GTO v0.

Do not confuse these user-selected ranges with solver-generated GTO.
Only 9-max unopened pots receive A17 RFI thresholds; an SB that has
not faced a raise completes/limps all hands. Other actions (including
isolation raises, 3-bets, 4-bets, BB and <9-handed play) retain the
separate fixed-GTO preflop policy until explicitly specified.
"""
from bots.a17_ranges import A17_HAND_TO_BOX, A17_MAX_OPEN_BOX_9MAX
from bots.gto_bot import _hand_key
from bots.gto_fixed_bot import FixedGTOPreflopBot


class A17PreflopBot(FixedGTOPreflopBot):
    """Independent A17 9-max opening ranges, with TAG postflop via factory."""

    def _preflop(self, hole, position, pot, to_call, legal, state):
        # Short-handed tables have different position meanings (6=UTG
        # at 6-max but LJ at 9-max), so we NEVER silently reuse the
        # 9-max ranges after player eliminations.
        n = len(state.stacks)
        pos = str(position).upper()
        if n != 9 or pos == "BB" or pos not in A17_MAX_OPEN_BOX_9MAX:
            return super()._preflop(hole, position, pot, to_call, legal, state)

        if self._facing_opponent_raise(state):
            return super()._preflop(hole, position, pot, to_call, legal, state)

        if pos == "SB":
            # 100% range through box A17: call/complete without a raise,
            # including limped pots. Never turn an SB limp into an auto-raise.
            return self._do_call_or_check(legal, to_call)

        # RFI (Raise First In) means nobody has voluntarily entered this
        # preflop pot. Prior folds are fine; limps do NOT count as RFI.
        history = getattr(state, "history", None) or ()
        entered = any(
            isinstance(entry, dict)
            and entry.get("street") == "preflop"
            and entry.get("type") in ("call", "raise", "bet", "all_in")
            for entry in history
        )
        if entered:
            return super()._preflop(hole, position, pot, to_call, legal, state)

        r1, r2 = hole[0][0], hole[1][0]
        key = _hand_key(r1, r2, hole[0][1] == hole[1][1])
        if A17_HAND_TO_BOX[key] <= A17_MAX_OPEN_BOX_9MAX[pos]:
            return self._do_raise(legal, pot, sizing_frac=0.70)
        return self._do_fold_or_check(legal, to_call)
