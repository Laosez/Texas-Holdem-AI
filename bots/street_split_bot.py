"""Independent preflop and postflop policy bases for controlled experiments.

The engine provides a full PlayerView on every decision. StreetSplitBot routes
that view to one of two existing strategies without changing either policy.
The history, hand, board, position, stacks, and legal actions are preserved.

Stage routing is an experiment boundary, not a solver: changes in preflop
ranges necessarily alter which boards and opponents reach the postflop phase.
"""
from __future__ import annotations

from core.bot_api import Action, BotAdapter, PlayerView
from bots.shared_pc_bb_defense import SharedPCBBDefense, first_bb_vs_single_open


# Curated experiment bases with known self-contained preflop/postflop code.
# Stateful TournamentHybridBot and other advanced strategies need a
# cross-street-memory audit before they are added here.
import json
import os
from pathlib import Path

_CATALOG = Path(__file__).resolve().parents[1] / "strategy_catalog" / "available_bases.json"
EXPERIMENT_BASES = frozenset(json.loads(_CATALOG.read_text(encoding="utf-8"))["bases"])



class StreetSplitBot(BotAdapter):
    """Use the first policy only before the flop, the second thereafter.

    Identical bases may share the same adapter object to preserve their
    behavior and avoid duplicate resets. Different bases have separate memory
    by design. Both receive the complete, unmodified PlayerView.
    """

    def __init__(
        self,
        preflop_bot: BotAdapter,
        postflop_bot: BotAdapter,
        *,
        preflop_name: str,
        postflop_name: str,
    ) -> None:
        self.preflop_bot = preflop_bot
        self.postflop_bot = postflop_bot
        self.preflop_name = preflop_name
        self.postflop_name = postflop_name
        self.bb_defense = SharedPCBBDefense()
        # A per-tournament subprocess flag; no global mutation of bot ranges.
        self.preflop_protocol = os.environ.get("POKER_PREFLOP_PROTOCOL", "legacy")

    def act(self, view: PlayerView) -> Action:
        street = view.street
        if street == "preflop":
            # Random is the experimental negative control: under standard_v1
            # it must remain truly random rather than inherit shared
            # deterministic response ranges and standard raise sizes.
            if self.preflop_name == "random":
                return self.preflop_bot.act(view)
            if self.preflop_protocol == "standard_v1":
                from bots.standard_preflop import response_action,normalize_rfi_raise
                shared=response_action(view)
                if shared is not None:
                    return shared
                # Preserve each strategy's RFI membership/frequencies,
                # normalize the sizes of its chosen open-raises only.
                return normalize_rfi_raise(view, self.preflop_bot.act(view))
            if first_bb_vs_single_open(view):
                return self.bb_defense.act(view)
            return self.preflop_bot.act(view)
        if street in ("flop", "turn", "river"):
            return self.postflop_bot.act(view)
        raise ValueError(f"Unknown poker street for split strategy: {street!r}")

    def observe_hand(self, hand_id, history, board, me):
        observer = getattr(self.postflop_bot, "observe_hand", None)
        if callable(observer):
            observer(hand_id, history, board, me)

    def reset_memory(self) -> None:
        seen = set()
        for bot in (self.preflop_bot, self.postflop_bot):
            if id(bot) in seen:
                continue
            seen.add(id(bot))
            reset = getattr(bot, "reset_memory", None)
            if callable(reset):
                reset()
