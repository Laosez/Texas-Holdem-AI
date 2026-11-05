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
from bots.hand_seniority_51 import hero_seniority, hero_seniority_52
from bots.hand_seniority_53 import hero_seniority_53

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
SHADOW_REFERENCES = ("gto41", "gto50", "gto505", "gto51", "gto515", "gto52", "gto53", "gto531", "gto54_10", "gto54_15", "gto54_20", "gto541")


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


def _hero_quantile_51(view, dist, seniority_version=51, *, tie_aware=False, seniority_resolver=None):
    """Rank-aware Hero percentile, replacing category midpoint 0.5.

    A rank-only danger/safe fraction is weighted by the opponent made-hand
    category mass. The existing 5.0 F/T draw improvement is kept identical.
    """
    hole, board = list(view.hole_cards), list(view.board)
    category = min(8, eval_hand(hole, board) >> 24)
    masses = dist["probability_mass"]
    if not masses:
        return .50, category, {"method": "no mass", "win_fraction": .5}
    seniority_fn = {51: hero_seniority, 52: hero_seniority_52,
                    53: hero_seniority_53}[seniority_version]
    if seniority_resolver is not None and seniority_version == 53:
        win_fraction, rule = seniority_resolver(hole, board)
    else:
        win_fraction, rule = seniority_fn(
            hole, board,
            category_mass=dist["unrounded_probability_mass"][category],
            pocket_pair_pct=X_ANY_TWO)
    q = sum(masses[:category]) + masses[category] * win_fraction
    # GTO 5.3.1 ONLY: retain the exact tie interval instead of collapsing
    # ties to the single midpoint percentile. Other versions stay unchanged.
    tie_band = None
    if tie_aware and seniority_version == 53:
        total = int(rule.get("route_weight") or 0)
        tied = int(rule.get("tie") or 0)
        if total and tied:
            base = sum(masses[:category])
            lower = base + masses[category] * rule["safe"] / total
            upper = lower + masses[category] * tied / total
            tie_band = (lower, upper)
    if len(board) < 5 and category < 4:
        outs = max(0, min(15, read_hand(hole, board).draw_outs))
        odds = min(.35, outs * (5-len(board)) / 47)
        q += odds * (1-q) * .65
        if tie_band is not None:
            # Preserve the unchanged 5.x draw proxy as an affine shift of
            # BOTH tie boundaries (not merely of their midpoint).
            bump = odds * .65
            tie_band = tuple(x + (1-x) * bump for x in tie_band)
    if tie_band is not None:
        rule = {**rule, "tie_quantile_band": tie_band}
    return max(.01, min(.99, q)), category, rule


def _equity_in_band(hero_q, low, high, tie_band=None):
    low, high = max(0., min(1., low)), max(0., min(1., high))
    if high <= low:
        return .5
    # Uniform percentile density within the opponent's action band.
    if tie_band is not None:
        # [0, tie_low): Hero wins; [tie_low, tie_high): shared pot.
        # [tie_high, 1]: Hero loses. All overlaps are O(1).
        tie_low, tie_high = tie_band
        wins = max(0., min(high, tie_low) - low)
        ties = max(0., min(high, tie_high) - max(low, tie_low))
        return max(.01, min(.99, (wins + .5 * ties) / (high - low)))
    return max(.01, min(.99, (hero_q - low) / (high-low)))


def _band(pid, street, history, groups):
    """Same last-action band convention as GTO 4.1, without enumerating hands."""
    from bots.gto_postflop_41 import _band_for
    return _band_for(pid, street, history, groups[pid][street])


def _estimate_actions(view, groups, distribution, bet_size, *, rank_aware=False, seniority_version=51, tie_aware=False, band_resolver=None, seniority_resolver=None):
    """Quick EV approximation using category quantiles and response frequencies."""
    opponents = [str(p) for p in (view.opponents or ())]
    seniority_inputs = {}
    if rank_aware:
        rank, category, rule = _hero_quantile_51(
            view, distribution, seniority_version, tie_aware=tie_aware,
            seniority_resolver=seniority_resolver)
        seniority_inputs["seniority"] = rule
        seniority_inputs["hero_quantile"] = round(rank, 6)
    else:
        rank, category = _hero_quantile(view, distribution)
    tie_band = seniority_inputs.get("seniority", {}).get("tie_quantile_band")
    history = getattr(view, "history", ()) or ()
    pot = max(1, int(view.pot))
    to_call = max(0, int(view.to_call))
    eq_all = []
    bands = {}
    for pid in opponents:
        lo, hi = (band_resolver(pid, view.street, history, groups)
                  if band_resolver is not None else _band(pid, view.street, history, groups))
        bands[pid] = (lo, hi)
        eq_all.append(_equity_in_band(rank, lo, hi, tie_band))
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
        call_equities.append(_equity_in_band(rank, fold, min(1., fold+call), tie_band))
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
        self.seniority_version = 51
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
        if getattr(self, "range_step_pct", None) in (10, 15, 20):
            return "gto54_" + str(self.range_step_pct)
        if self.rank_aware:
            if getattr(self, "tie_aware", False) and self.seniority_version == 53:
                return "gto531"
            if self.seniority_version == 53:
                return "gto53"
            if self.seniority_version == 52:
                return "gto52"
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
        if self.shadow_reference_kind == "gto52":
            return RankAwareGTO52Bot(window=5, shadow_percent=0)
        if self.shadow_reference_kind == "gto53":
            return RankAwareGTO53Bot(window=5, shadow_percent=0)
        if self.shadow_reference_kind == "gto531":
            return RankAwareGTO531Bot(window=5, shadow_percent=0)
        if self.shadow_reference_kind == "gto541":
            from bots.gto_postflop_541 import RankAwareGTO541Bot
            return RankAwareGTO541Bot(window=5, shadow_percent=0)
        for step in (10, 15, 20):
            if self.shadow_reference_kind == "gto54_" + str(step):
                return RankAwareGTO54Bot(step_pct=step, window=5, shadow_percent=0)
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
        groups = {pid: (self._street_matrix_54(pid)
                        if getattr(self, "range_step_pct", None) else self.street_matrix(pid))
                  for pid in opponents}
        distribution_resolver = getattr(self, "_distribution_541", None)
        dist = (distribution_resolver(view.board)
                if distribution_resolver is not None
                else board_distribution(view.board, round_to_five=self.round_step == 5))
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
                                           rank_aware=self.rank_aware,
                                            seniority_version=self.seniority_version,
                                           tie_aware=getattr(self, "tie_aware", False),
                                           band_resolver=getattr(self, "_band_54", None),
                                           seniority_resolver=getattr(self, "_seniority_541", None))
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
                    "gto515": "gto5.1.5-alpha",
                    "gto52": "gto5.2-alpha",
                    "gto53": "gto5.3-alpha",
                    "gto531": "gto5.3.1-tie-alpha",
                    "gto54_10": "gto5.4-step10-alpha",
                    "gto54_15": "gto5.4-step15-alpha",
                    "gto54_20": "gto5.4-step20-alpha",
                    "gto541": "gto5.4.1-step15-cached-alpha"}
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
                "reason": ("GTO 5.4.1: GTO 5.4/15% with memoized board/rank/opponent contexts"
                           if self.actor_kind == "gto541" else
                           "GTO 5.4: accumulated RAISE/RERAISE width (50%, step "
                           + str(self.range_step_pct) + " pp)"
                           if getattr(self, "range_step_pct", None) else
                           "GTO 5.3.1: tie-aware opponent action-band equity"
                           if getattr(self, "tie_aware", False) else
                           "GTO 5.3: weighted rank-pair + suit seniority"
                           if self.seniority_version == 53 and self.rank_aware else
                           "GTO 5.2: corrected high-card and P0 pair seniority"
                           if self.seniority_version == 52 and self.rank_aware else
                           "GTO 5.1: rank seniority + category masses"
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
                            # Same mutable list accumulates ALL Hero decisions
                            # in the hand, including non-Shadow and later F/T/R.
                            "hand_steps": self._trace[-1]["steps"]
                                          if self._trace else [],
                            "decision_step_index": (
                                len(self._trace[-1]["steps"])-1
                                if self._trace else None),
                            "decision_inputs": inputs,
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


class RankAwareGTO52Bot(RankAwareGTO51Bot):
    """GTO 5.2: experimental isolated seniority corrections; 5.1 unchanged."""

    def __init__(self, window=5, *, shadow_percent=None, shadow_reference=None):
        super().__init__(window=window, shadow_percent=shadow_percent,
                         shadow_reference=shadow_reference)
        self.profile = "gto_postflop_52_5"
        self.seniority_version = 52


class RankAwareGTO53Bot(RankAwareGTO51Bot):
    """GTO 5.3: exact Any Two within-category ranking via 91 weighted rank pairs."""

    def __init__(self, window=5, *, shadow_percent=None, shadow_reference=None):
        super().__init__(window=window, shadow_percent=shadow_percent,
                         shadow_reference=shadow_reference)
        self.profile = "gto_postflop_53_5"
        self.seniority_version = 53



class RankAwareGTO531Bot(RankAwareGTO53Bot):
    """GTO 5.3.1: only keep ties inside conditional action-band equity.

    Same weighted rank seniority, P(category), action frequencies, EV formula,
    bet sizing and multiway assumptions as 5.3. This is a clean A/B ablation.
    """

    def __init__(self, window=5, *, shadow_percent=None, shadow_reference=None):
        super().__init__(window=window, shadow_percent=shadow_percent,
                         shadow_reference=shadow_reference)
        self.profile = "gto_postflop_531_5"
        self.tie_aware = True



class RankAwareGTO54Bot(RankAwareGTO531Bot):
    """GTO 5.4 A/B: accumulate RAISE widths, starting at 50%.

    Three independent arms: step 10/20 pp bounded to 10..90%, or
    step 15 pp bounded to 5..95%. For each eligible facing-BET
    opportunity, RAISE expands the top action band; Fold/Call contracts
    it. Facing-RAISE (RERAISE) is tracked separately. State is one
    floating-point number per player/street/context and survives beyond
    the parent's five-event probability-smoothing window.

    The old smoothed Fold/Call proportions are retained and rescaled to
    the mass left by the accumulated RAISE/RERAISE probability. Seniority,
    draws, ties, EV payoff and multiway independence are unchanged.
    """

    STEP_LIMITS = {10: (.10, .90), 15: (.05, .95), 20: (.10, .90)}

    def __init__(self, step_pct=10, window=5, *,
                 shadow_percent=None, shadow_reference=None):
        if step_pct not in self.STEP_LIMITS:
            raise ValueError("GTO 5.4 step must be 10, 15 or 20 pp")
        super().__init__(window=window, shadow_percent=shadow_percent,
                         shadow_reference=shadow_reference)
        self.range_step_pct = step_pct
        self.profile = "gto_postflop_54_step" + str(step_pct)

    def reset_memory(self):
        super().reset_memory()
        self._range_widths = {}

    def _append(self, pid, street, group, outcome):
        # Parent only calls this for genuine three-way legal opportunities,
        # once per event (observe_hand deduplicates history replay).
        super()._append(pid, street, group, outcome)
        if group not in ("vs_bet", "vs_raise"):
            return
        target = "raise" if group == "vs_bet" else "reraise"
        key = (str(pid), street, group)
        current = self._range_widths.get(key, .50)
        direction = 1 if outcome == target else -1
        lower, upper = self.STEP_LIMITS[self.range_step_pct]
        self._range_widths[key] = round(max(lower, min(
            upper, current + direction * self.range_step_pct / 100)), 8)

    def _street_matrix_54(self, pid):
        """Keep fold/call ratios, replace RAISE width using the scalar."""
        matrix = self.street_matrix(pid)
        for street in ("flop", "turn", "river"):
            for group, target in (("vs_bet", "raise"),
                                  ("vs_raise", "reraise")):
                block = matrix[street][group]
                width = self._range_widths.get(
                    (str(pid), street, group), .50)
                # A three-way response must sum to 1, including in EV BET.
                original_other = (block["fold"]["p"] + block["call"]["p"])
                fold_share = (block["fold"]["p"] / original_other
                              if original_other else .5)
                fold = (1. - width) * fold_share
                call = (1. - width) - fold
                block["fold"] = {**block["fold"],
                                 "prior_smoothed_p": block["fold"]["p"],
                                 "p": round(fold, 6),
                                 "source": "step_54_rescaled"}
                block["call"] = {**block["call"],
                                 "prior_smoothed_p": block["call"]["p"],
                                 "p": round(call, 6),
                                 "source": "step_54_rescaled"}
                block[target] = {
                    **block[target],
                    "prior_smoothed_p": block[target]["p"],
                    "p": width,
                    "source": "step_54_accumulated",
                    "initial_p": .50,
                    "step_pct": self.range_step_pct,
                    "bounds": self.STEP_LIMITS[self.range_step_pct],
                }
        return matrix

    @staticmethod
    def _last_raise_context(pid, street, history):
        """Classify the opponent's last raise by the preceding aggression."""
        last_action, last_context = None, None
        previous_aggression = None
        previous_aggressor = None
        for event in history or ():
            if not isinstance(event, dict) or event.get("street") != street:
                continue
            action = event.get("type")
            actor = str(event.get("pid"))
            if actor == str(pid):
                last_action = action
                last_context = (
                    previous_aggression if previous_aggressor != actor
                    else None)
            if action in ("bet", "raise"):
                previous_aggression = action
                previous_aggressor = actor
        return last_action, last_context

    def _band_54(self, pid, street, history, groups):
        # Unlike legacy 4.1/5.3, an actual RERAISE uses its own accumulator.
        action, faced = self._last_raise_context(pid, street, history)
        if action == "raise" and faced == "raise":
            width = groups[pid][street]["vs_raise"]["reraise"]["p"]
            return 1. - width, 1.
        return _band(pid, street, history, groups)
