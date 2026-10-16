"""GTO-inspired postflop V3: kicker, pair+draw, board-relative two pair.

Versioned behavioral hypothesis for EV comparison, NOT a Nash/GTO solver.
GTO V1 and V2 remain byte-for-byte unchanged.

V3 extends V2's low-pocket correction to non-pocket board-overlaid two pair,
then uses cautious kicker-aware top-pair play and a mixed pair+flush-draw line.
No opponent-range-conditioned equity is claimed; count-dependent frequencies
still use the original V1 multiway discount.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import replace
import random

from bots.gto_postflop_v2 import GTOPostflopV2Bot
from bots.postflop_profiles import (
    _RANK, _opponents, _to_call, _can_bluff, _amount, _fallthrough,
)


class GTOPostflopV3Bot(GTOPostflopV2Bot):
    def __init__(self):
        super().__init__()
        self.profile = "gto_postflop_v3"

    def _read_hand(self, cards, board):
        read = super()._read_hand(cards, board)
        if len(cards) != 2 or len(board) < 3 or read.category != 2:
            return read
        # Board contains exactly one distinct pair. K2 on K-7-7 is NOT
        # independent two-pair value (K7 is shared with all other Kx).
        # A two-pair hand using BOTH hole cards on an unpaired board remains
        # a genuine "monster"; sets/full houses have category >=3.
        repeats = [rank for rank,n in Counter(c[0] for c in board).items()
                   if n == 2]
        if len(repeats) != 1 or cards[0][0] == cards[1][0]:
            return read
        board_pair = repeats[0]
        matches = [c[0] for c in cards if c[0] != board_pair
                   and any(b[0] == c[0] for b in board)]
        if not matches:
            return read
        strength = max(_RANK[rank] for rank in matches)
        highest_board = max(_RANK[card[0]] for card in board)
        if strength == highest_board and strength > _RANK[board_pair]:
            return replace(read, made="top_pair")
        return replace(read, made="weak_pair")

    @staticmethod
    def _top_kicker(cards, board):
        """Kicker rank only for one non-pocket hole card matching top board."""
        if cards[0][0] == cards[1][0]:
            return None
        top = max(_RANK[c[0]] for c in board)
        matching = [i for i,c in enumerate(cards) if _RANK[c[0]] == top]
        if len(matching) != 1:
            return None
        return _RANK[cards[1-matching[0]][0]]

    def act(self, view):
        if view.street not in ("flop","turn","river"):
            return super().act(view)
        cards = list(view.hole_cards or ())
        board = list(view.board or ())
        if len(cards) != 2 or len(board) < 3:
            return super().act(view)
        read = self._read_hand(cards, board)
        if read.made not in ("top_pair","weak_pair"):
            return super().act(view)

        n = _opponents(view)
        multi = 1 / (1 + .55 * max(0,n-1))
        to_call = _to_call(view)
        pot_odds = to_call / max(1,int(view.pot) + to_call)
        spr = (view.stacks.get(view.me,0) or 0) / max(1,int(view.pot))
        street = view.street
        size = (.33 if street == "flop" and not read.wet else .66
                if street == "flop" else .72 if street == "turn" else .78)

        # Combine pair showdown strength with the live one-card flush/straight
        # draw. We cannot simply treat 9 nominal outs as true clean outs, so
        # cap and discount the decision threshold in multiway pots.
        if street != "river" and read.draw_outs >= 8:
            if to_call > 0:
                threshold = (.32 if read.made == "top_pair" else .25)
                if street == "turn":
                    threshold -= .035
                if n >= 2:
                    threshold -= .035 if n == 2 else .065
                if pot_odds > threshold:
                    return _fallthrough(view,fold=True)
                if (n == 1 and spr > 1.0 and _can_bluff(view)
                        and random.random() < .10 * multi):
                    raise_action = _amount(view,size)
                    if raise_action is not None:
                        return raise_action
                return _fallthrough(view)
            frequency = (.72 if read.made == "top_pair" else .44) * multi
            if random.random() < frequency:
                bet = _amount(view,size)
                if bet is not None:
                    return bet
            return _fallthrough(view)

        # Axs/Kxs/Qxs top pair: make kicker matter, rather than treating K2
        # and KQ equally. All numbers are heuristic policy parameters.
        kicker = self._top_kicker(cards,board) if read.made == "top_pair" else None
        if kicker is not None:
            if kicker >= 11:
                value_freq, price_limit = .65, .29
            elif kicker >= 8:
                value_freq, price_limit = .52, .25
            else:
                value_freq, price_limit = .35, .20
            if n >= 2:
                price_limit = max(.12,price_limit-(.02 if n == 2 else .04))
            if to_call > 0:
                return _fallthrough(view,fold=pot_odds > price_limit)
            if random.random() < value_freq * multi:
                bet = _amount(view,size)
                if bet is not None:
                    return bet
            return _fallthrough(view)

        # Other hand classes, true sets, pocket overpairs, and all bluffs
        # retain V2 behavior byte-for-byte through its inherited policy.
        return super().act(view)
