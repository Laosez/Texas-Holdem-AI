# bots/poker_mind_bot.py

import random
from core.table_order import position_tightness
from core.bot_api import Action, PlayerView, acting_opponents_for
from core.equity_legacy import estimate_equity_legacy


class SmartBot:
    """
    Updated SmartBot compatible with PlayerView object.
    Uses heuristic poker logic with pot odds, position, suited awareness, and bluffing.
    """

    def act(self, state: PlayerView):
        """
        Main decision function.
        'state' is a PlayerView, NOT a dict.
        """
        hole = state.hole_cards
        board = state.board
        pot = state.pot
        to_call = state.to_call
        legal = state.legal_actions
        stacks = state.stacks
        street = state.street
        position = state.position

        # ===========================
        #        PREFLOP LOGIC
        # ===========================
        if street == "preflop":
            r1, r2 = sorted([c[0] for c in hole], key=lambda r: "23456789TJQKA".index(r), reverse=True)
            suited = hole[0][1] == hole[1][1]

            # Position awareness: play tighter in early position
            position_tightness = self._get_position_tightness(position, len(state.stacks))

            tier = self._classify_preflop(r1, r2, suited)

            if tier == 1:  # Premium
                return self._raise_or_call(legal, pot)

            if tier == 2:  # Strong
                if position_tightness > 0.5:  # Early position
                    return self._call_or_check(legal)
                else:  # Late position
                    return self._raise_or_call(legal, pot)

            # Trash hands
            return self._fold_or_check(legal, to_call)

        # ===========================
        #        POSTFLOP LOGIC
        # ===========================
        strength = self._estimate_equity(
            hole, board, len(acting_opponents_for(state))
        )

        # Position awareness: boost strength in late position (20-25%)
        position_tightness = self._get_position_tightness(position, len(state.stacks))
        position_boost = (1.0 - position_tightness) * 0.25
        adjusted_strength = strength * (1.0 + position_boost)

        # Pot odds calculation
        pot_odds = to_call / (pot + to_call) if to_call > 0 and (pot + to_call) > 0 else 0.0

        # Bluff frequency: ~7% chance to bet/raise with weak hands
        bluffing = random.random() < 0.07 and adjusted_strength < 0.35

        # Facing a bet
        if to_call > 0:
            # Need hand strength to exceed pot odds by a margin to continue
            if adjusted_strength < pot_odds and not bluffing:
                return self._fold_or_check(legal, to_call)

            if adjusted_strength >= 0.75 or bluffing:
                return self._raise_or_call(legal, pot)

            if adjusted_strength >= pot_odds:
                return self._call_or_check(legal)

            return self._fold_or_check(legal, to_call)

        # No bet to face
        if adjusted_strength >= 0.75 or bluffing:
            return self._raise_or_call(legal, pot)

        if adjusted_strength >= 0.40:
            return self._call_or_check(legal)

        return self._fold_or_check(legal, to_call)

    def _classify_preflop(self, r1, r2, suited):
        """
        Classify preflop hand into tiers. Suited hands get bumped up one tier.
        Tier 1 = premium, Tier 2 = playable, Tier 3 = trash.
        """
        rank_values = "23456789TJQKA"
        broadways = set("TJQKA")
        pair = r1 == r2

        # Tier 1: Premium pairs and top aces
        if pair and r1 in ("A", "K", "Q", "J"):
            return 1
        if r1 == "A" and r2 in ("K", "Q", "J"):
            return 1

        # Tier 2 base: medium pairs, broadway combos, suited connectors
        if pair:
            return 2

        # Both broadway
        if r1 in broadways and r2 in broadways:
            if suited:
                return 1  # Suited broadways bump to tier 1
            return 2

        # Suited connectors (adjacent ranks)
        idx1, idx2 = rank_values.index(r1), rank_values.index(r2)
        if suited and abs(idx1 - idx2) <= 2:
            return 2  # Suited connectors/gappers are tier 2

        # Any ace or king suited
        if suited and r1 in ("A", "K"):
            return 2

        # High card hands
        if r1 in ("A", "K", "Q", "J"):
            if suited:
                return 2  # Suited high card bumped to playable
            return 3

        return 3

    def _get_position_tightness(self, position, n_players=9):
        return position_tightness(position, n_players)

    # -----------------------------------------------------
    # HELPER DECISION FUNCTIONS
    # -----------------------------------------------------

    def _fold_or_check(self, legal, to_call):
        """Check if possible, otherwise fold."""
        if to_call > 0:
            return Action("fold")

        # check if allowed
        for a in legal:
            if a["type"] == "check":
                return Action("check")

        return Action("fold")

    def _call_or_check(self, legal):
        """Call if facing a bet, otherwise check."""
        for a in legal:
            if a["type"] == "call":
                return Action("call")

        for a in legal:
            if a["type"] == "check":
                return Action("check")

        return Action("fold")

    def _raise_or_call(self, legal, pot):
        """Raise about 50% pot if possible, else call. Cap at 25% of stack."""
        for a in legal:
            if a["type"] in ("raise", "bet"):
                stack_cap = a["max"] * 0.25
                size = max(a["min"], min(a["max"], pot * 0.5, stack_cap))
                if size > a["max"] * 0.5:
                    return Action("call") if any(x["type"] == "call" for x in legal) else Action(a["type"], a["min"])
                return Action(a["type"], int(size))

        for a in legal:
            if a["type"] == "call":
                return Action("call")

        for a in legal:
            if a["type"] == "check":
                return Action("check")

        return Action("fold")

    # -----------------------------------------------------
    # Hand strength estimator
    # -----------------------------------------------------
    def _estimate_equity(self, hole, board, num_opponents=1, sims=100):
        """Legacy-equivalent Monte Carlo equity shared across strategy bots."""
        return estimate_equity_legacy(hole, board, num_opponents, sims)


# backward compatibility
PokerMindBot = SmartBot
