# bots/gto_bot.py
"""
GTOBot — Approximates Game Theory Optimal play via balanced mixed strategies.

Key principles:
  • Preflop: independent position charts, seeded from early/mid/late/blinds, with
    randomised open-raise, 3-bet, and call frequencies.
  • Postflop: balanced continuation-bet (~60-70%), check-raise (~12-18%),
    and probe-bet frequencies.
  • River: value-to-bluff ratio ≈ 2:1 so villain cannot exploit by always
    calling or always folding.
  • Strong hands sometimes slowplay; weak hands sometimes bluff —
    every decision branch has a randomised component.
"""

import random
from core.bot_api import Action, PlayerView, acting_opponents_for
from core.table_order import position_group, position_labels
from core.equity_legacy import estimate_equity_legacy

# ═══════════════════════════════════════════════════════════════════════════════
#  PREFLOP RANGE TABLES
#  Each table maps (high_rank, low_rank, suited) → (fold%, call%, raise%)
#  The three values must sum to 1.0.  We store them as dicts keyed by a
#  canonical hand string like "AKs", "QTo", "77".
# ═══════════════════════════════════════════════════════════════════════════════

RANKS_ORDER = "23456789TJQKA"

def _hand_key(r1: str, r2: str, suited: bool) -> str:
    """Canonical hand key: high card first, 's' or 'o' suffix (pairs omit)."""
    i1, i2 = RANKS_ORDER.index(r1), RANKS_ORDER.index(r2)
    if i1 < i2:
        r1, r2 = r2, r1
    if r1 == r2:
        return f"{r1}{r2}"
    return f"{r1}{r2}{'s' if suited else 'o'}"


def _build_range(tier1: set, tier2: set, tier3: set):
    """
    Build a dict  hand_key → (fold_freq, call_freq, raise_freq).

    tier1 = premium  → mostly raise
    tier2 = playable → mixed call/raise
    tier3 = marginal → mostly fold with small call/raise bluff freq
    Everything else  → near-pure fold (with tiny open-bluff freq)
    """
    table = {}
    for key in tier1:
        table[key] = (0.0, 0.10, 0.90)   # raise 90%, call 10%
    for key in tier2:
        table[key] = (0.10, 0.50, 0.40)  # raise 40%, call 50%, fold 10%
    for key in tier3:
        table[key] = (0.55, 0.30, 0.15)  # fold 55%, call 30%, raise-bluff 15%
    return table


# --- EARLY POSITION (UTG, UTG+1) — tight ---
_EP_T1 = {"AA", "KK", "QQ", "JJ", "AKs", "AKo"}
_EP_T2 = {"TT", "99", "AQs", "AQo", "AJs", "KQs"}
_EP_T3 = {"88", "77", "ATs", "KJs", "KQo", "QJs"}

RANGE_EARLY = _build_range(_EP_T1, _EP_T2, _EP_T3)

# --- MIDDLE POSITION (MP, LJ) — moderate ---
_MP_T1 = {"AA", "KK", "QQ", "JJ", "TT", "AKs", "AKo", "AQs"}
_MP_T2 = {"99", "88", "AQo", "AJs", "ATs", "KQs", "KQo", "KJs", "QJs"}
_MP_T3 = {"77", "66", "A9s", "A8s", "KTs", "QTs", "JTs", "KJo", "QJo"}

RANGE_MIDDLE = _build_range(_MP_T1, _MP_T2, _MP_T3)

# --- LATE POSITION (HJ, CO, BTN) — wide ---
_LP_T1 = {"AA", "KK", "QQ", "JJ", "TT", "99", "AKs", "AKo", "AQs", "AQo"}
_LP_T2 = {
    "88", "77", "66", "AJs", "ATs", "A9s", "A8s", "A7s", "A6s", "A5s",
    "KQs", "KQo", "KJs", "KTs", "QJs", "QTs", "JTs", "AJo", "ATo",
}
_LP_T3 = {
    "55", "44", "33", "22", "A4s", "A3s", "A2s", "K9s", "K8s", "Q9s",
    "J9s", "T9s", "98s", "87s", "76s", "65s", "KJo", "QJo", "JTo",
}

RANGE_LATE = _build_range(_LP_T1, _LP_T2, _LP_T3)

# --- BLINDS (SB, BB) — SB defends tighter, BB defends wider ---
_BL_T1 = {"AA", "KK", "QQ", "JJ", "TT", "AKs", "AKo", "AQs"}
_BL_T2 = {
    "99", "88", "77", "AQo", "AJs", "ATs", "A9s", "KQs", "KQo",
    "KJs", "QJs", "JTs",
}
_BL_T3 = {
    "66", "55", "44", "33", "22", "A8s", "A7s", "A6s", "A5s", "A4s",
    "A3s", "A2s", "KTs", "K9s", "QTs", "Q9s", "J9s", "T9s", "98s",
    "87s", "76s", "65s", "AJo", "ATo", "KJo", "QJo",
}

RANGE_BLINDS = _build_range(_BL_T1, _BL_T2, _BL_T3)


# ═══════════════════════════════════════════════════════════════════════════════
#  INDEPENDENT POSITION RANGES (2–10 PLAYERS)
# ═══════════════════════════════════════════════════════════════════════════════

# Preserve the original default behavior for unlisted hand classes.
DEFAULT_HAND_FREQUENCIES = (0.85, 0.10, 0.05)


def _all_hand_classes():
    """Complete canonical 169-hand grid: 13 pairs, 78 suited, 78 offsuit."""
    ranks = RANKS_ORDER[::-1]
    hands = [r + r for r in ranks]
    for hi, high in enumerate(ranks):
        for low in ranks[hi + 1:]:
            hands.append(high + low + "s")
            hands.append(high + low + "o")
    return tuple(hands)


ALL_HAND_CLASSES = _all_hand_classes()


def _legacy_range_for_position(position, n_players):
    """Original group-selection rule; used only to seed independent charts."""
    if str(position).upper() == "SB" and n_players == 2:
        return RANGE_LATE  # HU SB is the button.
    group = position_group(position, n_players)
    return {
        "early": RANGE_EARLY,
        "middle": RANGE_MIDDLE,
        "late": RANGE_LATE,
        "sb": RANGE_BLINDS,
        "bb": RANGE_BLINDS,
    }[group]


def _seed_position_ranges():
    """Own 169-entry dictionary for each position at each table size.

    Copying here is intentional: "9" and "8" must not share an object,
    and neither should e.g. "6" at 6-max and "6" at 9-max. All initial
    frequencies remain identical to the previous grouped implementation.
    """
    result = {}
    for n_players in range(2, 11):
        result[n_players] = {}
        for position in position_labels(n_players):
            original = _legacy_range_for_position(position, n_players)
            result[n_players][position] = {
                hand: original.get(hand, DEFAULT_HAND_FREQUENCIES)
                for hand in ALL_HAND_CLASSES
            }
    return result


# Defaults are a baseline template, never mutated by an individual bot.
POSITION_RANGES = _seed_position_ranges()


def _numeric_range(position, n_players, ranges=None):
    """Return a 169-hand chart for this exact table size and numeric seat."""
    lookup = POSITION_RANGES if ranges is None else ranges
    n = int(n_players)
    p = str(position).upper()
    if n not in lookup or p not in lookup[n]:
        raise ValueError(f"Unknown position {position!r} at {n_players}-max")
    return lookup[n][p]


# ═══════════════════════════════════════════════════════════════════════════════
#  GTO BOT CLASS
# ═══════════════════════════════════════════════════════════════════════════════

class GTOBot:
    """
    Approximates Game Theory Optimal poker via balanced mixed strategies.

    All frequency-based decisions use ``random.random()`` so that the bot
    is never purely deterministic while still maintaining theoretically
    sound ratios across many hands.
    """

    # ------------------------------------------------------------------
    # Tunable GTO frequencies
    # ------------------------------------------------------------------
    CBET_FREQ          = 0.65   # continuation-bet frequency (60-70%)
    CHECK_RAISE_FREQ   = 0.15   # check-raise frequency     (12-18%)
    PROBE_BET_FREQ     = 0.35   # probe-bet when checker on later streets
    SLOWPLAY_FREQ      = 0.20   # slowplay strong hands
    BLUFF_RIVER_FREQ   = 0.33   # river bluff ≈ 1/(2+1) for 2:1 V:B ratio
    BLUFF_SEMIBLUFF_FREQ = 0.40 # semi-bluff frequency with draws
    THIN_VALUE_FREQ    = 0.55   # thin value-bet medium-strength hands

    def __init__(self):
        # A GTO instance owns its charts, so experimental edits cannot
        # contaminate other GTO players or the frozen baseline template.
        self.position_ranges = {
            n: {p: dict(chart) for p, chart in by_position.items()}
            for n, by_position in POSITION_RANGES.items()
        }

    def set_hand_frequencies(self, n_players, position, hand, frequencies):
        """Change one hand at one seat without affecting other seats/bots.

        Accept a fold/call/raise triple totaling one. Its value is used
        before the existing facing-bet adjustment in _preflop().
        """
        values = tuple(float(v) for v in frequencies)
        if len(values) != 3 or not all(0.0 <= v <= 1.0 for v in values):
            raise ValueError("Expected three finite probabilities in [0, 1]")
        if abs(sum(values) - 1.0) > 1e-9:
            raise ValueError("Fold/call/raise probabilities must sum to 1")
        key = str(hand)
        if key not in ALL_HAND_CLASSES:
            raise ValueError(f"Unknown canonical hand class: {hand!r}")
        chart = _numeric_range(position, n_players, self.position_ranges)
        chart[key] = values

    # ==================================================================
    #  PUBLIC INTERFACE — called by the engine
    # ==================================================================

    def act(self, state: PlayerView) -> Action:
        hole     = state.hole_cards
        board    = state.board
        pot      = state.pot
        to_call  = state.to_call
        legal    = state.legal_actions
        street   = state.street
        position = state.position

        # Guard: no hole cards (shouldn't happen, but be safe)
        if not hole or len(hole) < 2:
            return self._fallback_passive(legal)

        if street == "preflop":
            return self._preflop(hole, position, pot, to_call, legal, state)
        else:
            return self._postflop(hole, board, pot, to_call, legal, street,
                                  position, state)

    # ==================================================================
    #  PREFLOP — range-chart lookup with mixed frequencies
    # ==================================================================

    def _preflop(self, hole, position, pot, to_call, legal, state):
        r1, r2 = hole[0][0], hole[1][0]
        suited = hole[0][1] == hole[1][1]
        key = _hand_key(r1, r2, suited)

        range_chart = _numeric_range(position, len(state.stacks), self.position_ranges)
        # All 169 combinations are explicit in every position chart.
        fold_f, call_f, raise_f = range_chart[key]

        # When facing a raise (to_call > 0), tighten ranges — but
        # proportionally so premium hands barely shift while trash
        # hands fold much more often.
        if to_call > 0:
            # Scale tightening by how loose the hand already is
            base_tighten = 0.15
            tighten = base_tighten * (0.3 + fold_f)  # premium(fold=0)→0.045, trash(fold=0.85)→0.17
            fold_f  = min(1.0, fold_f + tighten)
            leftover = 1.0 - fold_f
            total_action = call_f + raise_f
            if total_action > 0:
                call_f  = leftover * (call_f / total_action)
                raise_f = leftover * (raise_f / total_action)
            else:
                call_f = leftover
                raise_f = 0.0

        # Roll the dice
        roll = random.random()
        if roll < fold_f:
            return self._do_fold_or_check(legal, to_call)
        elif roll < fold_f + call_f:
            return self._do_call_or_check(legal, to_call)
        else:
            return self._do_raise(legal, pot, sizing_frac=0.70)

    # ==================================================================
    #  POSTFLOP — balanced c-bet, check-raise, value/bluff on river
    # ==================================================================

    def _postflop(self, hole, board, pot, to_call, legal, street, position,
                  state):
        strength = self._hand_strength(
            hole, board, num_opponents=len(acting_opponents_for(state))
        )
        has_draw = self._has_draw(hole, board)

        # ----- RIVER: enforce 2:1 value-to-bluff ratio -----
        if street == "river":
            return self._river_strategy(strength, has_draw, pot, to_call,
                                        legal, state)

        # ----- FLOP / TURN -----
        if to_call > 0:
            return self._facing_bet_postflop(strength, has_draw, pot,
                                             to_call, legal, state)
        else:
            return self._no_bet_postflop(strength, has_draw, pot, legal,
                                         street, state)

    # ------------------------------------------------------------------
    #  River strategy — calibrated 2:1 value-to-bluff
    # ------------------------------------------------------------------

    def _river_strategy(self, strength, has_draw, pot, to_call, legal, state):
        if to_call > 0:
            # Facing a river bet
            pot_odds = to_call / (pot + to_call) if (pot + to_call) > 0 else 0
            my_stack = state.stacks.get(state.me, 0)

            if strength >= 0.70:
                # Strong hand → raise for value most of the time
                if random.random() < 0.75:
                    return self._do_raise(legal, pot, sizing_frac=0.80)
                return self._do_call(legal)

            if strength >= 0.45:
                # Medium — call if equity beats pot odds (bluff-catch)
                if strength > pot_odds:
                    return self._do_call(legal)
                # Sometimes hero-call (balanced)
                if random.random() < 0.20:
                    return self._do_call(legal)
                return self._do_fold_or_check(legal, to_call)

            # Weak — fold. Re-raising into a bet with trash burns chips
            # against opponents using fixed thresholds who will just call.
            return self._do_fold_or_check(legal, to_call)

        else:
            # No bet to face on river — we act first
            if strength >= 0.65:
                # Value-bet strong hands, but slowplay sometimes
                if random.random() < self.SLOWPLAY_FREQ:
                    return self._do_check(legal)
                return self._do_bet(legal, pot, sizing_frac=0.70)

            if strength >= 0.40:
                # Medium — thin value-bet at calibrated freq
                if random.random() < self.THIN_VALUE_FREQ:
                    return self._do_bet(legal, pot, sizing_frac=0.50)
                return self._do_check(legal)

            # Weak — bluff at 2:1 ratio freq
            if random.random() < self.BLUFF_RIVER_FREQ:
                return self._do_bet(legal, pot, sizing_frac=0.65)
            return self._do_check(legal)

    # ------------------------------------------------------------------
    #  Facing a bet on flop/turn
    # ------------------------------------------------------------------

    def _facing_bet_postflop(self, strength, has_draw, pot, to_call, legal,
                             state):
        pot_odds = to_call / (pot + to_call) if (pot + to_call) > 0 else 0
        my_stack = state.stacks.get(state.me, 0)

        # --- Strong hand ---
        if strength >= 0.70:
            # Raise most of the time (value), but flat-call to trap sometimes
            if random.random() < (1.0 - self.SLOWPLAY_FREQ):
                return self._do_raise(legal, pot, sizing_frac=0.75)
            return self._do_call(legal)

        # --- Medium hand ---
        if strength >= 0.40:
            if strength > pot_odds:
                # Check-raise bluff at calibrated frequency
                if random.random() < self.CHECK_RAISE_FREQ:
                    return self._do_raise(legal, pot, sizing_frac=0.65)
                return self._do_call(legal)
            # Marginal — sometimes float
            if random.random() < 0.25:
                return self._do_call(legal)
            return self._do_fold_or_check(legal, to_call)

        # --- Draw ---
        if has_draw:
            if random.random() < self.BLUFF_SEMIBLUFF_FREQ:
                return self._do_raise(legal, pot, sizing_frac=0.60)
            # Call to see next card if odds are close
            if strength + 0.20 > pot_odds:  # implied-odds fudge
                return self._do_call(legal)
            return self._do_fold_or_check(legal, to_call)

        # --- Weak ---
        # Occasionally bluff-raise to stay balanced
        if random.random() < 0.08:
            return self._do_raise(legal, pot, sizing_frac=0.60)

        if strength > pot_odds:
            return self._do_call(legal)

        return self._do_fold_or_check(legal, to_call)

    # ------------------------------------------------------------------
    #  No bet yet on flop/turn — c-bet / probe / check
    # ------------------------------------------------------------------

    def _no_bet_postflop(self, strength, has_draw, pot, legal, street, state):
        # Determine if we were the preflop aggressor (simplified heuristic:
        # check history for our own raise on preflop street)
        was_aggressor = self._was_preflop_aggressor(state)

        # --- Strong hand ---
        if strength >= 0.70:
            if random.random() < self.SLOWPLAY_FREQ:
                return self._do_check(legal)  # Slowplay to induce
            return self._do_bet(legal, pot, sizing_frac=0.65)

        # --- Medium hand ---
        if strength >= 0.40:
            if was_aggressor:
                # C-bet at balanced frequency
                if random.random() < self.CBET_FREQ:
                    return self._do_bet(legal, pot, sizing_frac=0.50)
                return self._do_check(legal)
            else:
                # Probe-bet on turn+ if we checked flop
                if street in ("turn", "river"):
                    if random.random() < self.PROBE_BET_FREQ:
                        return self._do_bet(legal, pot, sizing_frac=0.45)
                return self._do_check(legal)

        # --- Draw ---
        if has_draw:
            # Semi-bluff c-bet / probe
            freq = self.CBET_FREQ if was_aggressor else 0.30
            if random.random() < freq:
                return self._do_bet(legal, pot, sizing_frac=0.55)
            return self._do_check(legal)

        # --- Weak ---
        # Small bluff frequency to stay balanced
        bluff_freq = 0.12 if was_aggressor else 0.06
        if random.random() < bluff_freq:
            return self._do_bet(legal, pot, sizing_frac=0.45)
        return self._do_check(legal)

    # ==================================================================
    #  HAND EVALUATION HELPERS
    # ==================================================================

    def _hand_strength(self, hole, board, num_opponents=1, sims=100) -> float:
        """Legacy-equivalent Monte Carlo equity (shared with Smart/MC)."""
        return estimate_equity_legacy(hole, board, num_opponents, sims)

    # Draw detection is separate from equity.
    def _has_draw(self, hole, board) -> bool:
        """
        Lightweight draw detector: returns True if we have a flush draw
        (4 to a flush) or an open-ended straight draw (4 consecutive ranks).
        """
        if len(board) < 3:
            return False

        all_cards = list(hole) + list(board)

        # --- Flush draw: 4+ cards of one suit ---
        suit_counts: dict[str, int] = {}
        for card in all_cards:
            s = card[1]
            suit_counts[s] = suit_counts.get(s, 0) + 1
        if any(c >= 4 for c in suit_counts.values()):
            return True

        # --- Straight draw: 4 out of 5 consecutive ranks ---
        rank_indices = sorted(set(RANKS_ORDER.index(c[0]) for c in all_cards))
        for i in range(len(rank_indices) - 3):
            window = rank_indices[i:i + 4]
            if window[-1] - window[0] <= 4 and len(window) == 4:
                return True

        # Wheel draw (A-2-3-4)
        if {0, 1, 2, 12} <= set(rank_indices) or {0, 1, 2, 3} <= set(rank_indices):
            return True

        return False

    def _was_preflop_aggressor(self, state: PlayerView) -> bool:
        """Check if we were the last raiser preflop."""
        for entry in reversed(state.history):
            if entry.get("street") != "preflop":
                continue
            if entry.get("type") in ("raise", "bet"):
                return entry.get("pid") == state.me
        return False

    # ==================================================================
    #  ACTION HELPERS — interact with the legal_actions structure
    # ==================================================================

    def _do_fold_or_check(self, legal, to_call):
        if to_call == 0:
            return self._do_check(legal)
        return Action("fold")

    def _do_check(self, legal):
        for a in legal:
            if a["type"] == "check":
                return Action("check")
        # No check available — fold as last resort
        return Action("fold")

    def _do_call(self, legal):
        for a in legal:
            if a["type"] == "call":
                return Action("call")
        # Can't call → check if possible
        return self._do_check(legal)

    def _do_call_or_check(self, legal, to_call):
        if to_call > 0:
            return self._do_call(legal)
        return self._do_check(legal)

    def _do_bet(self, legal, pot, sizing_frac=0.50):
        """Place a bet sized as a fraction of the pot."""
        for a in legal:
            if a["type"] == "bet":
                target = max(a["min"], int(pot * sizing_frac))
                target = min(target, a["max"])
                return Action("bet", target)
        return self._do_check(legal)

    def _do_raise(self, legal, pot, sizing_frac=0.70):
        """Raise sized as a fraction of the pot."""
        for a in legal:
            if a["type"] == "raise":
                target = max(a["min"], int(pot * sizing_frac))
                target = min(target, a["max"])
                return Action("raise", target)
        # Can't raise → call or check
        for a in legal:
            if a["type"] == "call":
                return Action("call")
        return self._do_check(legal)

    def _fallback_passive(self, legal):
        for a in legal:
            if a["type"] == "check":
                return Action("check")
        return Action("fold")
