"""GTO-inspired postflop V4: preserve genuine two-pair value on paired boards.

V3 correctly downgraded hands whose second pair is shared by everyone,
but also downgraded hands like AQ on A-Q-7-7, where BOTH hole cards form
the two highest pairs. V4 changes only that classification. It inherits
every sizing, stochastic frequency, draw, multiway and kicker rule from V3.

Experimental heuristic policy, NOT a Nash-equilibrium/GTO solver.
V1/V2/V3 remain unchanged for reproducible A/B comparisons.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import replace

from bots.gto_postflop_v3 import GTOPostflopV3Bot
from bots.postflop_profiles import _RANK


class GTOPostflopV4Bot(GTOPostflopV3Bot):
    def __init__(self):
        super().__init__()
        self.profile = "gto_postflop_v4"

    def _read_hand(self, cards, board):
        read = super()._read_hand(cards, board)
        if (len(cards) != 2 or len(board) < 4 or read.category != 2
                or cards[0][0] == cards[1][0]):
            return read

        counts = Counter(card[0] for card in board)
        board_pairs = [rank for rank, count in counts.items() if count == 2]
        if len(board_pairs) != 1:
            return read

        shared_rank = board_pairs[0]
        # Both different hole ranks must EACH match a board singleton and
        # outrank the common board pair. Thus both hole cards create the
        # two highest pairs in the best five-card hand (AQ on A-Q-7-7).
        # A2 on A-2-K-K must NOT qualify: only the A pair plays alongside KK.
        hole_ranks = (cards[0][0], cards[1][0])
        if all(
            rank != shared_rank
            and counts[rank] == 1
            and _RANK[rank] > _RANK[shared_rank]
            for rank in hole_ranks
        ):
            return replace(read, made="monster")
        return read
