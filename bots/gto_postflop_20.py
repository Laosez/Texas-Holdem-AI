"""GTO 2.0 — board-relative postflop policy, NOT a game-theoretic solver.

The original GTO 1 policy remains untouched for paired, seeded comparisons.
R0..R4 measure *incremental* made-hand strength over the public board; the
original HandRead draw, texture and blocker attributes are preserved.

This is an initial deterministic hand-strength layer. Opponent range equity
and the choice between alternative actions still require separate EV tests.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import replace

from bots.postflop_profiles import PostflopProfileBot, _RANK, read_hand


def relative_tier(hole, board) -> int:
    """R0=no value, R1=weak bluff-catcher, R2=pair-like, R3=strong, R4=very strong.

    Unlike the evaluator category, the tier acknowledges common board pairs.
    No unrealistically precise equity estimates are asserted.
    """
    if len(hole) != 2 or len(board) < 3:
        return 0

    from core.engine import eval_hand

    score = eval_hand(list(hole), list(board))
    category = score >> 24
    counts = Counter(c[0] for c in board)
    hole_counts = Counter(c[0] for c in hole)
    board_pairs = [r for r,n in counts.items() if n >= 2]
    max_board = max(_RANK[c[0]] for c in board)
    max_suit = max(Counter(c[1] for c in board).values())
    board_ranks = {_RANK[c[0]] for c in board}
    straight_windows = [set(range(x,x+5)) for x in range(2,11)] + [{14,2,3,4,5}]
    four_straight = len(board) >= 4 and any(len(w & board_ranks) >= 4
                                              for w in straight_windows)

    # The best five cards are fully shared. E.g. AQ on K-K-7-5-2 with
    # no better kicker, or any hand facing a straight on the board.
    if len(board) == 5 and score == eval_hand([], list(board)):
        return 0

    if category == 0:
        return 0

    if category == 1:
        if board_pairs and not any(r in counts for r in hole_counts):
            # Any pair is public; it is not an independently made pair.
            return 0
        if hole[0][0] == hole[1][0]:
            return 2 if _RANK[hole[0][0]] > max_board else 1
        top_match = any(_RANK[r] == max_board for r in hole_counts if r in counts)
        return 2 if top_match else 1

    if category == 2:
        if not board_pairs:
            # Genuine two pair from HERO on an unpaired board.
            return 3 if max_suit < 4 and not four_straight else 2

        if len(board_pairs) == 1 and counts[board_pairs[0]] == 2:
            shared = board_pairs[0]
            # Both private cards pair TWO different singleton board ranks
            # and both pairs outrank the public pair (AQ on A-Q-7-7).
            unique_hole = hole[0][0] != hole[1][0]
            both_private = unique_hole and all(
                counts[r] == 1 and _RANK[r] > _RANK[shared]
                for r in hole_counts
            )
            if both_private:
                return 3 if max_suit < 4 and not four_straight else 2
            pocket = hole[0][0] == hole[1][0]
            own_pair = (pocket or any(counts[r] == 1 for r in hole_counts))
            if not own_pair:
                return 0
            if pocket:
                return 2 if _RANK[hole[0][0]] > max_board else 1
            highest_own = max((_RANK[r] for r in hole_counts if counts[r] == 1),
                              default=0)
            return 2 if highest_own == max_board and max_suit < 4 else 1

        # Two public pairs: the other player also has the same two pairs.
        # A hole kicker may win, but is a bluff-catcher, not a monster.
        return 1

    if category >= 6:
        return 4

    if category == 5:
        # Flush is strong, but neither automatically the nuts nor range equity.
        return 3
    if category == 4:
        return 2 if max_suit >= 4 and len(board) >= 4 else 3
    # Sets and trips, except facing a more obviously threatening texture.
    return 2 if max_suit >= 4 or four_straight else 3


class GTOPostflop20Bot(PostflopProfileBot):
    """GTO 2.0: original V1 action engine driven by board-relative strength."""

    def __init__(self):
        super().__init__("gto_postflop_v1")
        self.profile = "gto_postflop_20"

    def _read_hand(self, cards, board):
        basic = read_hand(cards, board)
        tier = relative_tier(cards, board)
        made = ("air", "weak_pair", "top_pair", "monster", "monster")[tier]
        return replace(basic, made=made)

    def relative_tier(self, cards, board):
        return relative_tier(cards, board)
