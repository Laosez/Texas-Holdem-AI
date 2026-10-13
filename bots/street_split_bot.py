"""Independent preflop and postflop policy bases for controlled experiments.

The engine provides a full PlayerView on every decision. StreetSplitBot routes
that view to one of two existing strategies without changing either policy.
The history, hand, board, position, stacks, and legal actions are preserved.

Stage routing is an experiment boundary, not a solver: changes in preflop
ranges necessarily alter which boards and opponents reach the postflop phase.
"""
from __future__ import annotations

from core.bot_api import Action, BotAdapter, PlayerView


# Curated experiment bases with known self-contained preflop/postflop code.
# Stateful TournamentHybridBot and other advanced strategies need a
# cross-street-memory audit before they are added here.
EXPERIMENT_BASES = frozenset({
    "gto",
    "smart",
    "tag_punisher",
    "wide_defender",
    "baseline_sane",
    "nit",
    "loose_passive",
    "maniac",
    "maniac_mixed",  # Same ManiacPolicy, lower jam/probe frequencies.
    "pressure_filler",
    "random",  # Stateless legal-action baseline; may be used on either street.
} | {f"random_{i}" for i in range(2, 11)})  # Distinct exporter labels for clones.


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

    def act(self, view: PlayerView) -> Action:
        street = view.street
        if street == "preflop":
            return self.preflop_bot.act(view)
        if street in ("flop", "turn", "river"):
            return self.postflop_bot.act(view)
        raise ValueError(f"Unknown poker street for split strategy: {street!r}")

    def reset_memory(self) -> None:
        seen = set()
        for bot in (self.preflop_bot, self.postflop_bot):
            if id(bot) in seen:
                continue
            seen.add(id(bot))
            reset = getattr(bot, "reset_memory", None)
            if callable(reset):
                reset()
