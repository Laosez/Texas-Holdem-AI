"""PC GTO 80bb: quarter-step PokerCoaching RFI preflop bot.

RFI frequencies are extracted from 80bb charts (PDF pp. 4-5), rounded to
0/25/50/75/100% per hand and action. Postflop inherits GTOBot when used
standalone, and can be independently replaced in StreetSplitBot.

Non-RFI situations, including BB defense and 3-/4-bet responses, deliberately
fall back to FixedGTOPreflopBot until the corresponding source chart sections
are digitized. Never present this as exact full-source GTO.
"""
from __future__ import annotations

import random

from core.bot_api import Action
from bots.gto_bot import _hand_key
from bots.gto_fixed_bot import FixedGTOPreflopBot
from bots.pc_gto_80bb_ranges import rfi_actions


class PCGTO80bbBot(FixedGTOPreflopBot):
    """80 BB positional RFI baseline, no stack-specific range alterations."""

    @staticmethod
    def _is_unopened(state):
        """Posted blinds are not voluntary, and neither is our current turn."""
        return not any(
            isinstance(entry, dict)
            and entry.get("street") == "preflop"
            and entry.get("type") in ("call", "raise", "bet", "all_in")
            for entry in (getattr(state, "history", None) or ())
        )

    def _open_raise(self, legal, position):
        """Source chart: 2.3bb opens, 3.5bb from SB; obey engine min/max.

        An untouched preflop pot has a minimum total open to 2bb.
        Thus the engine's legal raise minimum is twice the live big blind.
        If the short-stack legal amount is all-in, clamp to that amount.
        """
        for item in legal:
            if item["type"] == "raise":
                lower,upper=int(item["min"]),int(item["max"])
                target_bb=3.5 if str(position).upper()=="SB" else 2.3
                intended=round(target_bb*(lower/2.0))
                return Action("raise",max(lower,min(upper,intended)))
        return self._do_call_or_check(legal, 1)

    def _preflop(self, hole, position, pot, to_call, legal, state):
        if not self._is_unopened(state):
            return super()._preflop(hole,position,pot,to_call,legal,state)
        card1,card2=hole
        hand=_hand_key(card1[0],card2[0],card1[1]==card2[1])
        actions=rfi_actions(hand,str(position),len(state.stacks))
        if actions is None:
            # No RFI chart for BB; never apply positional opens to BB defense.
            return super()._preflop(hole,position,pot,to_call,legal,state)
        roll=random.randrange(100)
        if roll<actions["open"]:
            return self._open_raise(legal,position)
        if roll<actions["open"]+actions.get("limp",0):
            return self._do_call_or_check(legal,to_call)
        return self._do_fold_or_check(legal,to_call)
