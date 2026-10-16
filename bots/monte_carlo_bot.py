import random
from core.table_order import position_tightness
from core.bot_api import Action, PlayerView, acting_opponents_for
from core.engine import _FULL_DECK
from core.equity import equity


class MonteCarloBot:
    """
    Monte Carlo rollout bot updated to work with PlayerView objects.
    Simulates equity against N opponents in multi-way pots.
    """

    def __init__(self, simulations=500, num_opponents=None):
        self.simulations = simulations
        self.num_opponents = num_opponents  # None = auto-detect from state

    # ----------------------------------------------------
    # PUBLIC: act() for engine compatibility
    # ----------------------------------------------------
    def act(self, state: PlayerView):
        hole = state.hole_cards
        board = state.board
        pot = state.pot
        to_call = state.to_call
        legal = state.legal_actions
        street = state.street
        opponents = acting_opponents_for(state)
        position = state.position

        # If no hole cards (folded)
        if not hole:
            for a in legal:
                if a["type"] == "check":
                    return Action("check")
            return Action("fold")

        # Determine number of opponents for simulation
        n_opps = self.num_opponents or len(opponents) or 1

        # Monte Carlo equity estimate against N opponents
        winrate = self._estimate_equity(hole, board, n_opps, sims=self.simulations)

        # Pot odds
        pot_odds = to_call / (pot + to_call) if (pot + to_call) > 0 else 0.0

        # Position awareness: adjust thresholds based on position
        position_tightness = self._get_position_tightness(position, len(state.stacks))

        if position_tightness > 0.5:  # Early position
            bet_threshold = 0.70
            raise_threshold = 0.65
        else:  # Late position
            bet_threshold = 0.60
            raise_threshold = 0.55

        # -----------------------------
        # FACING A BET
        # -----------------------------
        if to_call > 0:
            my_stack = state.stacks.get(state.me, 0)

            # Weak hand: fold if equity doesn't beat pot odds
            if winrate < pot_odds:
                return self._choose("fold", legal)

            # Large call (>40% of stack) requires stronger hand
            if my_stack > 0 and to_call > my_stack * 0.4 and winrate < 0.70:
                return self._choose("fold", legal)

            # Medium hand → call
            if winrate < raise_threshold:
                return self._choose("call", legal)

            # Strong → raise
            return self._raise(pot, legal)

        # -----------------------------
        # NO BET YET
        # -----------------------------
        if winrate > bet_threshold:
            return self._bet(pot, legal)

        # Medium → check
        for a in legal:
            if a["type"] == "check":
                return Action("check")

        # fallback
        return self._choose("fold", legal)

    # ----------------------------------------------------
    # Monte Carlo equity estimation (multi-opponent)
    # ----------------------------------------------------
    def _estimate_equity(self, hole, board, num_opponents=1, sims=500):
        """Expected share of the showdown pot against random opponent hands.

        Delegate to the canonical calculator so multiway ties are split
        between *all* players sharing the best hand, not always 50/50.
        """
        return equity(hole, board, num_opponents, n_sims=sims)

    # ----------------------------------------------------
    # Remaining deck helper (used outside _estimate_equity)
    # ----------------------------------------------------
    def _remaining_deck(self, used):
        used_set = set(tuple(c) for c in used)
        return [c for c in _FULL_DECK if c not in used_set]

    # ----------------------------------------------------
    # Helper: choose legal action
    # ----------------------------------------------------
    def _choose(self, typ, legal):
        for a in legal:
            if a["type"] == typ:
                return Action(typ)
        # fallback if that action type isn't available
        for a in legal:
            if a["type"] in ("call", "check"):
                return Action(a["type"])
        return Action("fold")

    # ----------------------------------------------------
    # Raise helper
    # ----------------------------------------------------
    def _raise(self, pot, legal):
        for a in legal:
            if a["type"] == "raise":
                # Cap at 30% of stack to avoid all-in escalation
                stack_cap = a["max"] * 0.30
                amt = max(a["min"], min(a["max"], pot * 0.75, stack_cap))
                return Action("raise", int(amt))
        return self._choose("call", legal)

    # ----------------------------------------------------
    # Bet helper
    # ----------------------------------------------------
    def _bet(self, pot, legal):
        for a in legal:
            if a["type"] == "bet":
                stack_cap = a["max"] * 0.25
                amt = max(a["min"], min(a["max"], pot * 0.5, stack_cap))
                return Action("bet", int(amt))
        return self._choose("check", legal)

    def _get_position_tightness(self, position, n_players=9):
        return position_tightness(position, n_players)

