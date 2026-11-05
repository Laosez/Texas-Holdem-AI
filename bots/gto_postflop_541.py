"""GTO 5.4.1/15%: pure memoization of GTO 5.4/15% computations.

No new action/EV logic. Card-derived caches use bounded LRU entries, while
opponent context statistics are stored per bot and invalidated immediately
when a newly observed public action updates that player's memory.
"""
from copy import deepcopy
from functools import lru_cache

from bots.gto_postflop_50 import RankAwareGTO54Bot, board_distribution
from bots.hand_seniority_53 import hero_seniority_53


@lru_cache(maxsize=2048)
def _board_distribution_541(board):
    # Source is a pure function of the board. Its returned dictionaries/lists
    # are never exposed directly: callers receive their own copies.
    return board_distribution(list(board), round_to_five=False)


@lru_cache(maxsize=4096)
def _hero_seniority_541(hole, board):
    # GTO 5.3's category_mass and pocket_pair_pct are compatibility args
    # explicitly ignored by the scorer (Any Two).
    return hero_seniority_53(list(hole), list(board),
                             category_mass=None, pocket_pair_pct=5.88)


class RankAwareGTO541Bot(RankAwareGTO54Bot):
    """Same 15pp accumulator, bands and EV as GTO 5.4/15%, faster to reuse."""

    def __init__(self, window=5, *, shadow_percent=None, shadow_reference=None):
        super().__init__(step_pct=15, window=window,
                         shadow_percent=shadow_percent,
                         shadow_reference=shadow_reference)
        self.profile = "gto_postflop_541_step15"

    @property
    def actor_kind(self):
        return "gto541"

    def reset_memory(self):
        super().reset_memory()
        # Per-opponent cached posteriors are ONLY valid until a new action.
        self._context_cache_541 = {}

    def _append(self, pid, street, group, outcome):
        super()._append(pid, street, group, outcome)
        # Even an event on another street can change a pooled fallback;
        # invalidate all cached contexts for this opponent, not just street.
        cache = getattr(self, "_context_cache_541", None)
        if cache is not None:
            for key in tuple(cache):
                if key[0] == str(pid):
                    del cache[key]

    def _context(self, pid, street, group):
        key = (str(pid), street, group)
        cache = getattr(self, "_context_cache_541", None)
        if cache is None:
            return super()._context(pid, street, group)
        if key not in cache:
            cache[key] = super()._context(pid, street, group)
        # GTO 5.4 modifies p/source for RAISE, Fold and Call in its copy of
        # street_matrix. Never let those modifications pollute the cache.
        return {outcome: stats.copy()
                for outcome, stats in cache[key].items()}

    def _distribution_541(self, board):
        key = tuple(tuple(c) for c in board)
        return deepcopy(_board_distribution_541(key))

    def _seniority_541(self, hole, board):
        hole_key = tuple(tuple(c) for c in hole)
        board_key = tuple(tuple(c) for c in board)
        fraction, info = _hero_seniority_541(hole_key, board_key)
        return fraction, info.copy()
