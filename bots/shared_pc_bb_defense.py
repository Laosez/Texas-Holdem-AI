"""Shared BB response module for all Screen 1 split preflop strategies.

Source policy: the current PokerCoaching 80bb bot delegates non-RFI
(including its BB defense) to FixedGTOPreflopBot. This shared module
deliberately reuses that IDENTICAL fallback; it is NOT the still
undigitized seven opponent-position-specific PokerCoaching BB charts.

Apply only to BB's FIRST decision against exactly one conventional
opponent open-raise, without any limpers/other callers. Other contexts
(4-bets, shoves, multiway, limped pots) retain each strategy's code.
"""
from __future__ import annotations

from bots.gto_fixed_bot import FixedGTOPreflopBot

BB_DEFENSE_SOURCE = "pc_gto_80bb/fallback:gto_fixed:vs_single_rfi"


def first_bb_vs_single_open(view) -> bool:
    if view.street != "preflop" or str(view.position).upper() != "BB":
        return False
    if getattr(view, "to_call", 0) <= 0:
        return False
    history = [
        e for e in (getattr(view, "history", None) or ())
        if isinstance(e, dict) and e.get("street") == "preflop"
        and e.get("type") in ("call", "raise", "bet", "all_in", "check")
    ]
    # Only one ordinary opponent open; exclude callers, prior own
    # actions, all-in shoves and 3-bet / 4-bet situations.
    return (
        len(history) == 1
        and history[0].get("type") in ("raise", "bet")
        and history[0].get("pid") != getattr(view, "me", None)
    )


class SharedPCBBDefense:
    """The PC 80bb *current fallback* until exact BB source charts exist."""
    source = BB_DEFENSE_SOURCE

    def __init__(self):
        self._fallback = FixedGTOPreflopBot()

    def act(self, view):
        return self._fallback.act(view)
