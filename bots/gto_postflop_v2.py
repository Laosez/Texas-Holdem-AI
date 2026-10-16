"""GTO-inspired Postflop V2: board-relative pocket-pair strength fix.

This is a heuristic policy, NOT a solver GTO equilibrium. All sizes, random
frequencies, multiway scaling and draw logic are inherited unchanged from V1.

Change scope: 22..66 holding + a paired board + hand evaluator category 2
(two pair). V1 had called these hands 'monster' simply because the pocket pair
uses hole cards. V2 differentiates weak board-overlaid two pair versus a true
overpair to all public cards. Genuine sets/trips/full houses remain monsters.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import replace

from bots.postflop_profiles import PostflopProfileBot, _RANK, read_hand


class GTOPostflopV2Bot(PostflopProfileBot):
    def __init__(self):
        super().__init__("gto_postflop_v1")
        self.profile = "gto_postflop_v2"

    def _read_hand(self, cards, board):
        read = read_hand(cards, board)
        if (len(cards) != 2 or len(board) < 3 or
                cards[0][0] != cards[1][0] or
                cards[0][0] not in "23456" or
                read.category != 2):
            return read
        counts = Counter(c[0] for c in board)
        if not any(n >= 2 for n in counts.values()):
            return read

        pocket_rank = _RANK[cards[0][0]]
        public_max = max(_RANK[c[0]] for c in board)
        if pocket_rank > public_max:
            # Example: 66 vs 2-2-3. The pocket is an overpair and contributes
            # the highest pair. One-pair/protection behavior is more appropriate
            # than automatic 'monster' value raises.
            return replace(read, made="top_pair")

        # Example: 55 vs A-A-9. Board pair dominates; vulnerable second pair.
        # The inherited V1 weak-pair branch uses 14% pot-odds call threshold
        # and limited betting. Relative equity remains an approximation.
        return replace(read, made="weak_pair")
