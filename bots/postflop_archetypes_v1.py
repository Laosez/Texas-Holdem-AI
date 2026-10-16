"""Distinct postflop-only TAG / Draw Chaser / Trapper archetypes.

These are reproducible behavioral *models*, not poker solvers. They share the
existing V1 card reader and legal-sizing helpers with GTO/LAG; differences live
in action policies. Historical GTO/LAG implementations remain untouched.
"""
from __future__ import annotations

import random

from core.bot_api import BotAdapter
from bots.postflop_profiles import (
    read_hand, _to_call, _fallthrough, _amount, _opponents,
    _was_aggressor, _can_bluff,
)

_SUPPORTED = frozenset({
    "tag_postflop_v1", "chaser_postflop_v1", "trapper_postflop_v1",
})


class HumanPostflopBot(BotAdapter):
    """Postflop policies for controlled experiments with realistic tendencies.

    No claims of exact equity or human-population calibration:
    the shared reader counts nominal draws, not clean opponent-relative outs.
    """

    def __init__(self, profile: str):
        if profile not in _SUPPORTED:
            raise ValueError("Unsupported human postflop profile")
        self.profile = profile

    def act(self, view):
        if view.street not in ("flop", "turn", "river"):
            raise ValueError("Postflop-only profile cannot decide preflop")
        if len(view.hole_cards or ()) != 2 or len(view.board or ()) < 3:
            return _fallthrough(view, fold=True)
        hand = read_hand(list(view.hole_cards), list(view.board))
        facing = _to_call(view) > 0
        opponents = _opponents(view)
        heads_up = opponents == 1
        spr = (view.stacks.get(view.me, 0) or 0) / max(1, int(view.pot))
        pot_odds = _to_call(view) / max(1, int(view.pot) + _to_call(view))
        last_raiser = _was_aggressor(view)
        can_bluff = _can_bluff(view) and spr > 0.55
        kind = self.profile
        tag = kind == "tag_postflop_v1"
        chase = kind == "chaser_postflop_v1"
        trap = kind == "trapper_postflop_v1"

        # Legal-action helper clamps sizes and returns None when unavailable.
        size = (
            (.60 if view.street == "flop" else .72 if view.street == "turn" else .80)
            if tag else
            (.52 if view.street == "flop" else .62 if view.street == "turn" else .70)
            if chase else
            (.55 if view.street == "flop" else .68 if view.street == "turn" else .78)
        )

        def bet_or(fold=False):
            bet = _amount(view, size)
            return bet if bet is not None else _fallthrough(view, fold=fold)

        def mixed(probability, *, fold=False):
            if random.random() < min(1.0, max(0.0, probability)):
                bet = _amount(view, size)
                if bet is not None:
                    return bet
            return _fallthrough(view, fold=fold)

        if hand.made == "monster":
            if facing:
                # Trapper keeps strong hands in its calling range rather than
                # raising automatically. Chaser is willing to pay off, too.
                raise_frequency = (
                    .75 if tag else .48 if chase else
                    (.11 if heads_up and not hand.wet else .24)
                )
                return mixed(raise_frequency * (1.0 if heads_up else .75))
            if trap:
                # Slowplay more heads-up and on dry textures; avoid giving
                # too many free cards in wet or multiway pots.
                value_frequency = (.21 if heads_up and not hand.wet else .56)
            else:
                value_frequency = .88 if tag else .71
            return mixed(value_frequency)

        if hand.made == "top_pair":
            if facing:
                threshold = .29 if tag else .43 if chase else .34
                return _fallthrough(view, fold=pot_odds > threshold)
            return mixed((.65 if tag else .46 if chase else .24)
                         * (1 if heads_up else .75))

        if hand.made == "weak_pair":
            if facing:
                threshold = .15 if tag else .34 if chase else .20
                return _fallthrough(view, fold=pot_odds > threshold)
            return mixed((.12 if tag else .22 if chase else .06)
                         * (1 if heads_up else .55)
                         if view.street != "river" else 0)

        # Do not treat nominal outs as showdown equity. These are deliberately
        # archetype-specific call heuristics, not optimal implied-odds models.
        if view.street != "river" and hand.draw_outs:
            nominal = hand.draw_outs / (47 if view.street == "flop" else 46)
            multi_discount = 1 if heads_up else .75
            price_limit = nominal * multi_discount * (
                .92 if tag else 1.60 if chase else 1.0
            )
            if facing:
                semi_freq = (.12 if tag else .055 if chase else .025)
                if hand.draw_outs >= 8 and heads_up and can_bluff and spr > 1:
                    if random.random() < semi_freq:
                        bet = _amount(view, size)
                        if bet is not None:
                            return bet
                if pot_odds <= price_limit:
                    return _fallthrough(view)
                # The draw chaser calls some *unprofitable* prices by design.
                if chase and pot_odds < .44 and random.random() < .30:
                    return _fallthrough(view)
                return _fallthrough(view, fold=True)
            if can_bluff:
                return mixed((.38 if tag else .48 if chase else .12)
                             * (1 if heads_up else .55))
            return _fallthrough(view)

        # Air/no direct draw. TAG occasionally continuation-bets favorable
        # spots, Chaser hardly bluffs, and Trapper preserves a checking range.
        if facing:
            return _fallthrough(view, fold=True)
        if can_bluff and heads_up:
            if tag and last_raiser and view.street == "flop" and not hand.wet:
                return mixed(.14)
            if chase and last_raiser and view.street == "flop":
                return mixed(.045)
            if trap and last_raiser and view.street == "turn":
                return mixed(.055)
        return _fallthrough(view)
