"""GTO 2.1 — exactly GTO 2.0's action frequencies with standardized sizing.

Purpose: isolate the causal effect of bet/raise size on postflop EV.
No edits to the 2.0 hand reader, draw logic, bluff frequencies or memory.
GTO-inspired heuristic only; NOT a Nash/GTO solver.
"""
from __future__ import annotations

from bots.gto_postflop_20 import GTOPostflop20Bot
from bots.postflop_profiles import _amount


class GTOPostflop21Bot(GTOPostflop20Bot):
    """Same decision as 2.0; rescale legal bet/raise actions to half pot."""

    def __init__(self):
        super().__init__()
        self.profile = "gto_postflop_21"

    def act(self, view):
        action = super().act(view)
        if action.type not in ("bet", "raise"):
            return action
        # _amount uses the actual pot after a hypothetical call for raises:
        # street total = already invested + call + ceil(0.5 * (pot + call)).
        # Bet is ceil(0.5 * pot). Both obey min/max legal action limits.
        resized = _amount(view, 0.50)
        if resized is None or resized.type != action.type:
            return action
        return resized
