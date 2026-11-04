"""GTO 5.0/5 alpha: human-sized board formulas and approximate multiway EV.

No per-decision full opponent-hand enumeration and no Monte Carlo.  The exact
P0..P3 river approximations and elementary y street offsets are taken from
SKACHKOV POKER / "14 · GTO 5.0 · F/T/R".  K=1 and x=5.88 are the Any Two
baseline; further preflop-range conditioning remains research work.

EV uses an explicitly approximate category-quantile proxy, a one-street
checkdown and independent response frequencies.  It is NOT solver/GTO/Nash
equilibrium equity and should be calibrated in optional GTO 4.1 Shadow Mode.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
from itertools import combinations
from math import comb, prod, floor
import os
import time

from bots.gto_postflop_33 import StreetMatrixGTO33Bot
from bots.gto_postflop_30 import _board_class, AdaptiveGTO30Bot
from bots.postflop_profiles import _amount, _fallthrough, read_hand
from core.engine import eval_hand
from core.bot_api import Action
from gto5_shadow_report import board_tags
from bots.hand_seniority_51 import hero_seniority

RANKS = "23456789TJQKA"
WINDOWS = [set(range(i, i + 5)) for i in range(2, 11)] + [{14, 2, 3, 4, 5}]
CATEGORIES = ("high_card", "pair", "two_pair", "trips", "straight",
              "flush", "full_house", "quads", "straight_flush")
OFFSETS = {
    "P0": (10, -6, -3, -1, 0, 0, 0, 0, 0),
    "P1": (0, 9, -8, 0, 0, 0, -1, 0, 0),
    "P2": (0, 0, 0, 0, 0, 0, 0, 0, 0),
    "P3": (0, 0, 0, 12, 0, 0, -11, 0, 0),
}
X_ANY_TWO = 5.88
SHADOW_CHOICES = (0, 10, 25, 100)
SHADOW_REFERENCES = ("gto41", "gto50", "gto505", "gto51", "gto515")


def round_probability_to_five(value):
    """Round percentage to the nearest 5 pp, half up (not bankers' rounding)."""
    return max(0., min(100., 5. * floor(max(0., min(100., value)) / 5. + .5)))


def _completed_made(board):
    """Low-cost rank-combinatoric estimate of current made straight / flush.

    13*13 rank classes max. This is independent of Hero blockers and is
    only an approximation (not the exact opponent posterior).
    """
    board_ranks = [RANKS.index(c[0]) + 2 for c in board]
    available = {r: 4 - board_ranks.count(r) for r in range(2, 15)}
    board_mask = set(board_ranks)
    unknown = 52 - len(board)
    denominator = comb(unknown, 2)
    straight_pairs = 0
    for a in range(2, 15):
        for b in range(a, 15):
            rankset = board_mask | {a, b}
            if not any(window <= rankset for window in WINDOWS):
                continue
            quantity = (comb(available[a], 2) if a == b else
                        available[a] * available[b])
            straight_pairs += quantity
    sp = straight_pairs / denominator
    suit_counts = Counter(c[1] for c in board)
    fp = 0.0
    for s, on_board in suit_counts.items():
        remaining = 13 - on_board
        if on_board >= 5:
            fp = 1.0
            break
        if on_board == 4:
            fp = 1 - comb(unknown - remaining, 2) / denominator
        elif on_board == 3:
            fp = comb(remaining, 2) / denominator
    # The exact overlap includes SF; product is a light approximation.
    return min(100.0, 100 * (sp + fp - sp*fp)), 100*sp, 100*fp


def board_distribution(board, round_to_five=False):
    """Return formula percentages plus normalized EV mass.

    5.0.5 rounds each clamped category independently BEFORE normalizing EV
    mass. Rounded categories need not sum to 100 (a deliberate human rule).
    """
    tags = board_tags(board)
    kind = tags["P"]
    h, straight, flush = _completed_made(board)
    # P4 and PH are special 5-card boards outside the calibrated formulas.
    if kind not in OFFSETS:
        return {
            "structure": tags, "h": h, "formula_status": "special_board",
            "categories_pct": {}, "probability_mass": (),
        }
    y = 5-len(board)
    x = X_ANY_TWO
    # neutral K=1 for uniform AnyTwo, avoids pretending to model UTG ranges.
    base = {
        "P0": [40-.7*(x-6)-.6*h,
               50+.5*(x-6)-.5*h,
               8, x/4, 0, 0, 0, 0, 0],
        "P1": [0, 55-(x-6)-.7*h,
               35+.8*(x-6)-.2*h, 7, 0, 0,
               x/6+1.5, x/65, 0],
        "P2": [0, 0, 85-.1*x-1.3*h, 0, 0, 0,
               15+.1*x, x/32, 0],
        "P3": [0, 0, 0, 65-.9*(x-6)-.9*h, 0, 0,
               29+.9*(x-6), 5-x/20, 0],
    }[kind]
    offsets = OFFSETS[kind]
    vals = [max(0., min(100., base[i] + offsets[i]*y))
            for i in range(9)]
    # Separate S/F made-hand hypotheses (do not add draw probabilities).
    vals[4] = straight
    vals[5] = flush
    # Conditional rank seniority must use the SAME unrounded x/P_pair
    # weight in GTO 5.1 and GTO 5.1.5. Rounding only changes EV masses.
    unrounded_total = sum(vals)
    unrounded_mass = ([v/unrounded_total for v in vals]
                      if unrounded_total > 0 else [1.] + [0.]*8)
    if round_to_five:
        vals = [round_probability_to_five(v) for v in vals]
    raw = dict(zip(CATEGORIES, (round(v, 2) for v in vals)))
    # The human table intentionally does not force its marginal estimates to
    # total 100%. EV needs a probability measure: only for EV, renormalize.
    mass = [max(0., v) for v in vals]
    total = sum(mass)
    if total <= 0:
        mass = [1.0] + [0.0]*8
    else:
        mass = [v/total for v in mass]
    return {
        "structure": tags, "h": round(h, 3),
        "formula_status": ("P0-P3 / AnyTwo neutral K · round 5%"
                           if round_to_five else "P0-P3 / AnyTwo neutral K"),
        "round_step_pct": 5 if round_to_five else 0,
        "categories_pct": raw,
        "raw_total_pct": round(sum(vals), 2),
        "probability_mass": mass,
        "unrounded_probability_mass": unrounded_mass,
    }


def _hero_quantile(view, dist):
    """Category-centre proxy with small draw improvement in F/T streets."""
    hole, board = list(view.hole_cards), list(view.board)
    category = min(8, eval_hand(hole, board) >> 24)
    masses = dist["probability_mass"]
    if not masses:
        return .50, category
    q = sum(masses[:category]) + .5*masses[category]
    if len(board) < 5 and category < 4:
        outs = max(0, min(15, read_hand(hole, board).draw_outs))
        odds = min(.35, outs * (5-len(board)) / 47)
        q += odds * (1-q) * .65
    return max(.01, min(.99, q)), category


def _hero_quantile_51(view, dist):
    """Rank-aware Hero percentile, replacing category midpoint 0.5.

    A rank-only danger/safe fraction is weighted by the opponent made-hand
    category mass. The existing 5.0 F/T draw improvement is kept identical.
    """
    hole, board = list(view.hole_cards), list(view.board)
    category = min(8, eval_hand(hole, board) >> 24)
    masses = dist["probability_mass"]
    if not masses:
        return .50, category, {"method": "no mass", "win_fraction": .5}
    win_fraction, rule = hero_seniority(
        hole, board,
        category_mass=dist["unrounded_probability_mass"][category],
        pocket_pair_pct=X_ANY_TWO)
    q = sum(masses[:category]) + masses[category] * win_fraction
    if len(board) < 5 and category < 4:
        outs = max(0, min(15, read_hand(hole, board).draw_outs))
        odds = min(.35, outs * (5-len(board)) / 47)
        q += odds * (1-q) * .65
    return max(.01, min(.99, q)), category, rule


def _equity_in_band(hero_q, low, high):
    low, high = max(0., min(1., low)), max(0., min(1., high))
    if high <= low:
        return .5
    # Opponent rank percentile uniformly distributed inside its action band.
    return max(.01, min(.99, (hero_q - low) / (high-low)))


def _band(pid, street, history, groups):
    """Same last-action band convention as GTO 4.1, without enumerating hands."""
    from bots.gto_postflop_41 import _band_for
    return _band_for(pid, street, history, groups[pid][street])


def _estimate_actions(view, groups, distribution, bet_size, *, rank_aware=False):
    """Quick EV approximation using category quantiles and response frequencies."""
    opponents = [str(p) for p in (view.opponents or ())]
    seniority_inputs = {}
    if rank_aware:
        rank, category, rule = _hero_quantile_51(view, distribution)
        seniority_inputs["seniority"] = rule
        seniority_inputs["hero_quantile"] = round(rank, 6)
    else:
        rank, category = _hero_quantile(view, distribution)
    history = getattr(view, "history", ()) or ()
    pot = max(1, int(view.pot))
    to_call = max(0, int(view.to_call))
    eq_all = []
    bands = {}
    for pid in opponents:
        lo, hi = _band(pid, view.street, history, groups)
        bands[pid] = (lo, hi)
        eq_all.append(_equity_in_band(rank, lo, hi))
    # Multiplication assumes opponent conditional equities are independent.
    # True joint ranges and side pots are NOT computed.
    equity = prod(eq_all) if eq_all else .5
    equity_by_pid = dict(zip(opponents, eq_all))
    if to_call:
        return {"call": equity * (pot+to_call)-to_call, "fold": 0.0}, {
            "band": bands, "proxy_equity": equity,
            "hero_category": CATEGORIES[category],
            "equity_by_opponent": equity_by_pid, **seniority_inputs,
        }
    ev = {"check": equity * pot}
    if bet_size is None:
        return ev, {"band": bands, "proxy_equity": equity,
                    "equity_by_opponent": equity_by_pid, **seniority_inputs}
    # P(0..n calls, no raises): dynamic program, O(n^2) not 3^n.
    dp = [1.0]
    call_equities = []
    for pid in opponents:
        resp = groups[pid][view.street]["vs_bet"]
        fold = max(0., min(1., float(resp["fold"]["p"])))
        call = max(0., min(1.-fold, float(resp["call"]["p"])))
        prev = dp
        dp = [0.0]*(len(prev)+1)
        for j, mass in enumerate(prev):
            dp[j] += mass*fold
            dp[j+1] += mass*call
        call_equities.append(_equity_in_band(rank, fold, min(1., fold+call)))
    ev_bet = -(1-sum(dp))*bet_size + dp[0]*pot
    mean_call_eq = sum(call_equities)/len(call_equities) if call_equities else .5
    for callers in range(1, len(dp)):
        if dp[callers]:
            share = mean_call_eq**callers
            ev_bet += dp[callers] * (
                share*(pot+(callers+1)*bet_size)-bet_size)
    ev["bet"] = ev_bet
    return ev, {
        "band": bands, "proxy_equity": equity,
        "mean_call_equity": mean_call_eq,
        "hero_category": CATEGORIES[category],
        "bet_size": bet_size,
        "equity_by_opponent": equity_by_pid,
        "bet_call_equity_by_opponent": dict(zip(opponents, call_equities)),
        **seniority_inputs,
    }


class HumanRangeGTO50Bot(StreetMatrixGTO33Bot):
    """Cheap human board formulas; selectable paired Shadow benchmark."""

    def __init__(self, window=5, *, shadow_percent=None, shadow_reference=None):
        if window != 5:
            raise ValueError("GTO 5.0 supports five-observation memory only")
        super().__init__(window=window)
        self.profile = "gto_postflop_50_5"
        self.round_step = 0
        self.rank_aware = False
        rate = (int(os.getenv("POKER_GTO5_SHADOW_PERCENT", "0"))
                if shadow_percent is None else int(shadow_percent))
        if rate not in SHADOW_CHOICES:
            raise ValueError("Invalid Shadow sampling percentage")
        ref = (os.getenv("POKER_GTO5_SHADOW_REFERENCE", "gto41")
               if shadow_reference is None else shadow_reference)
        if ref not in SHADOW_REFERENCES:
            raise ValueError("Invalid Shadow reference model")
        self.shadow_percent = rate
        self.shadow_reference_kind = ref
        self.shadow_records = []
        self.shadow_checked = 0
        self.shadow_reference = None

    @property
    def actor_kind(self):
        if self.rank_aware:
            return "gto515" if self.round_step == 5 else "gto51"
        return "gto505" if self.round_step == 5 else "gto50"

    def _new_reference(self):
        if self.shadow_reference_kind == "gto41":
            from bots.gto_postflop_41 import JointRangeGTO41Bot
            return JointRangeGTO41Bot(window=5)
        if self.shadow_reference_kind == "gto505":
            return RoundedHumanRangeGTO505Bot(window=5, shadow_percent=0)
        if self.shadow_reference_kind == "gto51":
            return RankAwareGTO51Bot(window=5, shadow_percent=0)
        if self.shadow_reference_kind == "gto515":
            return RoundedRankAwareGTO515Bot(window=5, shadow_percent=0)
        return HumanRangeGTO50Bot(window=5, shadow_percent=0)

    def reset_memory(self):
        super().reset_memory()
        self.shadow_records = []
        self.shadow_checked = 0
        if getattr(self, "shadow_reference", None) is not None:
            self.shadow_reference.reset_memory()

    def _shadow_enabled(self, view):
        if self.shadow_percent <= 0:
            return False
        details = [os.getenv("POKER_SHADOW_TOURNAMENT", ""), str(view.me),
                   str(getattr(view, "hand_id", "")), str(view.street),
                   str(sum(isinstance(e, dict) and e.get("street") == view.street
                           and str(e.get("pid")) == str(view.me)
                           for e in (view.history or ())))]
        h = int.from_bytes(sha256("|".join(details).encode()).digest()[:8],
                           "big")
        return h < self.shadow_percent*(1 << 64)//100

    def act(self, view):
        if view.street not in ("flop", "turn", "river"):
            raise ValueError("GTO 5.0 is postflop only")
        self._active_street = view.street
        self.observe_hand(getattr(view, "hand_id", None),
                          getattr(view, "history", ()),
                          getattr(view, "board", ()), view.me)
        opponents = [str(v) for v in (view.opponents or ())]
        legal = {a["type"]: a for a in (view.legal_actions or ())}
        call = max(0, int(view.to_call))
        if not opponents or len(view.board or ()) not in (3, 4, 5):
            return _fallthrough(view, fold=bool(call))

        started = time.perf_counter_ns()
        groups = {pid: self.street_matrix(pid) for pid in opponents}
        dist = board_distribution(view.board, round_to_five=self.round_step == 5)
        bet = _amount(view, .50) if not call and "bet" in legal else None
        size = int(bet.amount) if bet and bet.type == "bet" else None
        if dist["formula_status"] == "special_board":
            # Exceptional P4/PH structures get a conservative, cheap decision.
            # They must not pretend to use the P0-P3 calibrated equations.
            action = _fallthrough(view, fold=bool(call))
            ev = {}
            inputs = {"special_board": True}
        else:
            ev, inputs = _estimate_actions(view, groups, dist, size,
                                           rank_aware=self.rank_aware)
            if call and {"fold", "call"} <= set(legal):
                action = Action("call" if ev.get("call", -1) > 0 else "fold")
            elif not call and {"bet", "check"} <= set(legal) and size is not None:
                action = bet if ev.get("bet", -1) > ev["check"] else Action("check")
            else:
                action = _fallthrough(view, fold=bool(call))
                ev = {}
        quick_ns = time.perf_counter_ns()-started
        versions = {"gto50": "gto5.0-alpha",
                    "gto505": "gto5.0.5-alpha",
                    "gto51": "gto5.1-alpha",
                    "gto515": "gto5.1.5-alpha"}
        self.last_model = {
            "version": versions[self.actor_kind],
            "distribution": dist,
            "board_classifier": _board_class(view.board, view.street),
            "ev": {a: round(v, 4) for a, v in ev.items()},
            "decision_inputs": inputs, "opponents_count": len(opponents),
            "mode": "human_formula_multiway", "quick_wall_ns": quick_ns,
        }
        if getattr(view, "hand_id", None) is not None:
            step = {
                "street": view.street,
                "board": ["".join(c) for c in view.board],
                "board150": (self.last_model["board_classifier"] or {}).get("id"),
                "board_anytwo_rank_pair_pct": AdaptiveGTO30Bot._anytwo_board_risk(view.board),
                "hero_hole": ["".join(c) for c in view.hole_cards],
                "hero_tier": "EV",
                "hero_made": ("human P0-P3 + rank seniority"
                              if self.rank_aware else "human P0-P3 formula"),
                "hero_draw_outs_estimate": read_hand(view.hole_cards, view.board).draw_outs,
                "opponents_count": len(opponents),
                "decision": action.type, "amount_chips": action.amount,
                "decision_mode": (self.actor_kind + "_rank_seniority"
                                   if self.rank_aware else
                                   "gto505_round5" if self.round_step else "gto50_alpha"),
                "street_matrix": groups[opponents[0]],
                # Old generic opponent metrics remain unchanged. New GTO 5.x
                # row lists ALL opponents, not only the first street matrix.
                "opponents": [],
                "opponent_models": [{
                    "pid": pid,
                    "band": inputs.get("band", {}).get(pid),
                    "equity_proxy": inputs.get("equity_by_opponent", {}).get(pid),
                    "bet_call_equity_proxy": inputs.get(
                        "bet_call_equity_by_opponent", {}).get(pid),
                    "vs_bet": {
                        name: {k: stats.get(k) for k in ("p", "k", "n", "source")}
                        for name, stats in groups[pid][view.street]["vs_bet"].items()
                    },
                } for pid in opponents],
                "ev": self.last_model["ev"], "equity_model": inputs,
                "distribution": dist,
                "reason": ("GTO 5.1: rank seniority + category masses"
                           if self.rank_aware else
                           "GTO 5.0.5: each category round to 5% + proxy EV"
                           if self.round_step else
                           "GTO 5.0 alpha: board formulas + proxy EV"),
            }
            if not self._trace or self._trace[-1]["hand_id"] != view.hand_id:
                self._trace.append({"hand_id": view.hand_id, "steps": []})
            self._trace[-1]["steps"].append(step)
        # Reference observes the SAME public information state. Shadow never
        # changes actual gameplay, and comparable actions use the same wager.
        # A bot may be its own selected reference when both versions sit at
        # one table: do not record tautological self-comparisons.
        if self.shadow_percent and self.shadow_reference_kind != self.actor_kind:
            if self.shadow_reference is None:
                self.shadow_reference = self._new_reference()
            self.shadow_reference.observe_hand(
                getattr(view, "hand_id", None), view.history,
                view.board, view.me,
            )
            if ev and self._shadow_enabled(view):
                try:
                    started_ref = time.perf_counter_ns()
                    self.shadow_reference.act(view)
                    reference_ns = time.perf_counter_ns()-started_ref
                    ref = self.shadow_reference.last_model or {}
                    ref_ev = ref.get("ev") or {}
                    if set(ref_ev) == set(ev) and set(ev) in (
                            {"call", "fold"}, {"bet", "check"}):
                        new_ev, old_ev = dict(ev), dict(ref_ev)
                        name = action.type
                        if "bet" in ev:
                            key = "bet:" + str(size)
                            new_ev[key] = new_ev.pop("bet")
                            old_ev[key] = old_ev.pop("bet")
                            if name == "bet":
                                name = key
                        self.shadow_records.append({
                            "street": view.street,
                            "opponents": len(opponents),
                            "board": ["".join(c) for c in view.board],
                            "hole": ["".join(c) for c in view.hole_cards],
                            "hand_id": view.hand_id,
                            "bb": max(1, int(os.getenv("POKER_CURRENT_BB", "2"))),
                            "ev5": new_ev, "ev41": old_ev,
                            "chosen5": name,
                            "actor": self.actor_kind,
                            "reference_model": self.shadow_reference_kind,
                            "wall5_ns": quick_ns, "wall41_ns": reference_ns,
                            "reference_trials": ref.get(
                                "decision_inputs", {}).get("joint_trials", 0),
                            "model": self.last_model["distribution"],
                        })
                        self.shadow_checked += 1
                except (ValueError, TypeError, KeyError, ZeroDivisionError):
                    # Reference failure must never alter the actor's action.
                    pass
        return action


class RoundedHumanRangeGTO505Bot(HumanRangeGTO50Bot):
    """A/B variant: identical 5.0 rules, only marginal category rounding."""

    def __init__(self, window=5, *, shadow_percent=None, shadow_reference=None):
        super().__init__(window=window, shadow_percent=shadow_percent,
                         shadow_reference=shadow_reference)
        self.profile = "gto_postflop_505_5"
        self.round_step = 5


class RankAwareGTO51Bot(HumanRangeGTO50Bot):
    """GTO 5.1: within-category seniority without probability rounding."""

    def __init__(self, window=5, *, shadow_percent=None, shadow_reference=None):
        super().__init__(window=window, shadow_percent=shadow_percent,
                         shadow_reference=shadow_reference)
        self.profile = "gto_postflop_51_5"
        self.rank_aware = True


class RoundedRankAwareGTO515Bot(RankAwareGTO51Bot):
    """GTO 5.1.5: same seniority as 5.1; category percentages round to 5%."""

    def __init__(self, window=5, *, shadow_percent=None, shadow_reference=None):
        super().__init__(window=window, shadow_percent=shadow_percent,
                         shadow_reference=shadow_reference)
        self.profile = "gto_postflop_515_5"
        self.round_step = 5
