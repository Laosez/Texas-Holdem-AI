"""GTO 2.1 A-F: isolated, explicit experiments for postflop HU.

All versions inherit 2.1's board-relative R0-R4 classifier and half-pot sizing.
A-D change only one behavioral axis via optional policy coefficients.
E corrects the HU SB position interpretation (SB/button plays IP postflop).
F reclassifies ONLY dominated low flushes on four-suit public boards.
The original GTO 2.0 and 2.1 remain independent, unchanged control arms.
No solver, hidden cards, or opponent-range oracle.
"""
from __future__ import annotations

from collections import Counter
from copy import copy
from dataclasses import replace

from bots.gto_postflop_21 import GTOPostflop21Bot
from bots.postflop_profiles import _RANK


VARIANT_SETTINGS = {
    # 2.1a: looser calls, original bets/raises unchanged.
    "a": {"top_call_odds": 0.35, "weak_call_odds": 0.22,
          "draw_call_multiplier": 1.20},
    # 2.1b: tighter calls, original bets/raises unchanged.
    "b": {"top_call_odds": 0.18, "weak_call_odds": 0.08,
          "draw_call_multiplier": 0.75},
    # 2.1c: more pure bluffs and semi-bluffs, value unchanged.
    "c": {"air_bluff_multiplier": 2.0, "draw_bet": 0.80,
          "draw_raise": 0.40},
    # 2.1d: more value bets and strong-hand raises, bluffs unchanged.
    "d": {"monster_bet": 0.95, "monster_raise": 0.75,
          "top_bet": 0.75, "weak_bet": 0.15},
    # 2.1e: positional correction only.
    "e": {},
    # 2.1f: cautious low-flush strength evaluation only.
    "f": {},
}


class GTOPostflop21VariantBot(GTOPostflop21Bot):
    """Independent ablation variant of GTO 2.1."""

    def __init__(self, letter: str):
        if letter not in VARIANT_SETTINGS:
            raise ValueError("Unknown GTO 2.1 variant: " + repr(letter))
        super().__init__()
        self.letter = letter
        self.profile = "gto_postflop_21" + letter
        self._policy_tuning = dict(VARIANT_SETTINGS[letter])

    def _read_hand(self, cards, board):
        read = super()._read_hand(cards, board)
        if self.letter != "f" or read.category != 5 or read.made != "monster":
            return read
        # A flush on a board with 4+ cards of one suit can be dominated.
        # Treat it as medium-strength (R2) if >=3 higher suited private
        # card ranks could exist, without assuming the opponent has them.
        suits = Counter(s for _, s in board)
        for suit, board_count in suits.items():
            if board_count < 4:
                continue
            private = [_RANK[r] for r, s in cards if s == suit]
            if not private:
                continue
            highest_private = max(private)
            board_ranks = {_RANK[r] for r, s in board if s == suit}
            superior_unseen = sum(
                rank > highest_private and rank not in board_ranks
                for rank in range(2, 15)
            )
            if superior_unseen >= 3:
                return replace(read, made="top_pair")
        return read

    def act(self, view):
        if self.letter == "e" and view.street in ("flop", "turn", "river"):
            # The engine labels HU button as SB, while V1's old
            # _in_position() recognizes only BTN/CO/numeric. SB is IP.
            # Avoid global engine changes and adjust only this variant.
            if str(getattr(view, "position", "")).upper() == "SB" and len(
                getattr(view, "opponents", ()) or ()
            ) == 1:
                view = copy(view)
                view.position = "BTN"
        return super().act(view)
