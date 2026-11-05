"""Independent river decision audit (version 1).

No GTO 4.1/5.x EV, seniority formulas, range assumptions or simulated hands.
Records the *realized* counterfactual value of calling vs folding in a
terminal heads-up river response. Training/evaluation on disjoint tournaments
prevents classifying one known villain hand as an exploitable EV oracle.

The experiment evaluates only eligible two-way CALL/FOLD decisions; BET,
RAISE, multiway and earlier streets are deliberately NOT scored.
"""
from collections import Counter, defaultdict
from hashlib import blake2b
import heapq
import math

from core.engine import eval_hand

FORMAT = "SKACHKOV_INDEPENDENT_RIVER_V1"


def _classify(score):
    category = score >> 24
    return ("high_card" if category == 0 else "pair" if category == 1
            else "two_pair" if category == 2 else "trips_plus")


def _bucket(odds):
    return ("0-20%" if odds < .20 else "20-35%" if odds < .35
            else "35-50%" if odds < .50 else "50%+")


class RiverDecisionCollector:
    """Hold a uniformly sampled, deterministic, RAM-capped river-only log.

    Private villain cards are used locally for the counterfactual showdown;
    they are never appended to records or passed to the tested strategy.
    """

    def __init__(self, tournament, percent=25, max_samples=128):
        if percent not in (0, 10, 25, 100):
            raise ValueError("Unexpected audit sampling rate")
        if max_samples < 1:
            raise ValueError("Unexpected audit sample cap")
        self.tournament = int(tournament)
        self.percent = percent
        self.max_samples = max_samples
        self._heap = []
        self.eligible = 0
        self.skipped_actions = 0
        self.sampled_before_cap = 0

    def observe(self, view, action, villain_hole, big_blind, bot_name, opponent_profile):
        # view has ONLY public data + Hero cards, never villain private cards.
        # For a full CALL, all active players reach an immediate showdown.
        if (view.street != "river" or len(view.opponents or ()) != 1
                or len(getattr(view, "all_in_opponents", ()) or ()) > 0
                or int(view.to_call) <= 0
                or {x.get("type") for x in view.legal_actions or ()}
                    .isdisjoint({"fold", "call"})
                or not {"fold", "call"}.issubset(
                    {x.get("type") for x in view.legal_actions or ()})
                or len(view.hole_cards or ()) != 2
                or len(view.board or ()) != 5
                or len(villain_hole or ()) != 2
                or (view.stacks or {}).get(view.me, 0) < view.to_call
                or big_blind <= 0):
            return
        self.eligible += 1
        if action.type not in ("fold", "call"):
            self.skipped_actions += 1
            return

        # Sampling excludes current action/hand strengths: no outcome bias.
        token = f"{self.tournament}:{view.hand_id}:{view.me}:{view.street}:{len(view.history or ())}"
        priority = int.from_bytes(
            blake2b(token.encode(), digest_size=8).digest(), "big")
        if priority % 10000 >= self.percent * 100:
            return
        self.sampled_before_cap += 1

        hero = eval_hand(list(view.hole_cards), list(view.board))
        opponent = eval_hand(list(villain_hole), list(view.board))
        share = 1.0 if hero > opponent else 0.5 if hero == opponent else 0.0
        pot, call, bb = int(view.pot), int(view.to_call), int(big_blind)
        call_realized_bb = (share * (pot + call) - call) / bb
        odds = call / (pot + call)
        record = {
            "bot": str(bot_name),
            "opponent_profile": str(opponent_profile),
            "tournament": self.tournament,
            "hand_id": int(view.hand_id),
            "actor": str(view.me),
            "board": ["".join(c) for c in view.board],
            "hero_hole": ["".join(c) for c in view.hole_cards],
            "hero_class": _classify(hero),
            "pot_odds_bucket": _bucket(odds),
            "pot_odds": round(odds, 6),
            "pot_bb": round(pot / bb, 6),
            "call_bb": round(call / bb, 6),
            "chosen": action.type,
            # Realized counterfactual outcome for this particular deal,
            # NOT estimated decision EV or ex-post per-hand regret.
            "call_realized_bb": round(call_realized_bb, 6),
            "policy_realized_bb": round(call_realized_bb if action.type == "call" else 0., 6),
        }
        item = (priority, token, record)
        if len(self._heap) < self.max_samples:
            heapq.heappush(self._heap, item)
        elif (priority, token) > (self._heap[0][0], self._heap[0][1]):
            heapq.heapreplace(self._heap, item)

    def records(self):
        return [row for _, _, row in sorted(self._heap, reverse=True)]

    def counts(self):
        return {
            "eligible": self.eligible,
            "skipped_actions": self.skipped_actions,
            "sampled_before_cap": self.sampled_before_cap,
            "sampled": len(self._heap),
            "max_samples_per_tournament": self.max_samples,
        }



class RiverAggressionCollector:
    """Sample realized BET/RAISE outcomes on river against one live opponent.

    This is NOT a counterfactual evaluator: an unplayed BET/RAISE alternative
    requires replay of villain's responses. In contrast to the CALL/FOLD
    collector, do not label its realized action payout as regret or oracle EV.
    No private villain cards are needed or saved.
    """

    def __init__(self, tournament, percent=25, max_samples=128):
        if percent not in (0, 10, 25, 100) or max_samples < 1:
            raise ValueError("Unexpected aggression sampling configuration")
        self.tournament = int(tournament)
        self.percent = percent
        self.max_samples = max_samples
        self.eligible = 0
        self.sampled_before_cap = 0
        self._pending = defaultdict(list)
        self._heap = []

    def observe(self, view, action, big_blind, bot_name, opponent_profile):
        if (view.street != "river" or len(view.opponents or ()) != 1
                or len(getattr(view, "all_in_opponents", ()) or ()) > 0
                or len(view.board or ()) != 5 or len(view.hole_cards or ()) != 2
                or action.type not in ("bet", "raise")
                or big_blind <= 0 or
                action.type not in {x.get("type") for x in view.legal_actions or ()}):
            return
        self.eligible += 1
        token = (f"{self.tournament}:{view.hand_id}:{view.me}:river:"
                 f"{len(view.history or ())}:{action.type}")
        priority = int.from_bytes(blake2b(token.encode(), digest_size=8).digest(),
                                  "big")
        if priority % 10000 >= self.percent * 100:
            return
        self.sampled_before_cap += 1
        hole = view.hole_cards
        hero_class = _classify(eval_hand(list(hole), list(view.board)))
        bb = int(big_blind)
        public = {
            "bot": str(bot_name), "opponent_profile": str(opponent_profile),
            "tournament": self.tournament, "hand_id": int(view.hand_id),
            "actor": str(view.me), "opponent": str(view.opponents[0]),
            "board": ["".join(c) for c in view.board],
            "hero_hole": ["".join(c) for c in hole],
            "hero_class": hero_class,
            "action": action.type,
            "amount_target_bb": round(int(action.amount or 0) / bb, 6),
            "pot_bb": round(int(view.pot) / bb, 6),
            "to_call_bb": round(int(view.to_call) / bb, 6),
        }
        # The current player's remaining chips are known before this action;
        # at hand completion, final chips - current chips gives realized
        # payoff strictly from this decision, excluding prior sunk costs.
        pending = {
            "priority": priority, "token": token,
            "start_stack": int((view.stacks or {})[view.me]),
            "street_history_index": len(view.history or ()),
            "bb": bb, "public": public,
        }
        self._pending[int(view.hand_id)].append(pending)

    def settle(self, hand_id, final_stacks, history):
        """Called exactly once after actual river fold/showdown settlement."""
        pending = self._pending.pop(int(hand_id), ())
        for event in pending:
            record = dict(event["public"])
            actor, opponent = record["actor"], record["opponent"]
            if actor not in final_stacks:
                continue
            record["realized_bb"] = round(
                (int(final_stacks[actor]) - event["start_stack"]) / event["bb"], 6)
            later = tuple(history)[event["street_history_index"]:]
            response = next((a.get("type") for a in later
                             if str(a.get("pid")) == opponent
                             and a.get("street") == "river"), None)
            record["opponent_response"] = response or "no_further_action"
            item = (event["priority"], event["token"], record)
            if len(self._heap) < self.max_samples:
                heapq.heappush(self._heap, item)
            elif item[:2] > self._heap[0][:2]:
                heapq.heapreplace(self._heap, item)

    def records(self):
        return [r for _, _, r in sorted(self._heap, reverse=True)]

    def counts(self):
        return {
            "eligible": self.eligible,
            "sampled_before_cap": self.sampled_before_cap,
            "sampled": len(self._heap),
            "max_samples_per_tournament": self.max_samples,
        }


def aggression_report(rows, collection_counts=None):
    """Descriptive observed outcomes only; NO invented alternative EV/regret."""
    samples = list(rows)
    groups = defaultdict(list)
    for sample in samples:
        groups[(sample["bot"], sample["action"])].append(sample)
    scored = []
    for (bot, action), entries in sorted(groups.items()):
        mean = _mean([x["realized_bb"] for x in entries])
        reactions = Counter(x["opponent_response"] for x in entries)
        scored.append({
            "bot": bot, "action": action,
            "n": len(entries),
            "tournaments": len({x["tournament"] for x in entries}),
            "mean_realized_bb": round(mean, 4),
            "ci95_bb": _cluster_interval(entries, lambda r: r["realized_bb"]),
            "opponent_responses": dict(reactions),
        })
    return {
        "n": len(samples),
        "collection": dict(collection_counts or {}),
        "by_bot_action": scored,
        "examples": sorted(samples, key=lambda r: abs(r["realized_bb"]),
                           reverse=True)[:20],
        "not_counterfactual": True,
        "message": (
            "Пока нет подходящих BET/RAISE на ривере HU"
            if not samples else None),
        "note": (
            "BET/RAISE: фактический результат выбранного действия и ответ OPP "
            "из реальной раздачи, относительно стека прямо перед решением. "
            "EV несыгранных альтернатив и regret НЕ рассчитываются. "
            "Для них нужен независимый розыгрыш реакций OPP."),
    }

def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def _cluster_interval(rows, value_fn):
    """Tournament-cluster robust CI of a mean, or null if not identifiable."""
    if not rows:
        return None
    vals = [value_fn(x) for x in rows]
    estimate = _mean(vals)
    buckets = defaultdict(float)
    for row, value in zip(rows, vals):
        buckets[row["tournament"]] += value - estimate
    g, n = len(buckets), len(vals)
    if g < 8 or n < 30:
        return None
    se = math.sqrt(g / (g - 1) * sum(x*x for x in buckets.values())) / n
    return [round(estimate - 1.96 * se, 4),
            round(estimate + 1.96 * se, 4)]


def _training_groups(rows):
    """Train on one tournament parity; evaluate on the opposite parity.

    Per-group rule is CALL when historical mean of realizable CALL payout > 0.
    Requires >=20 examples in the opposite-parity training sample; otherwise
    use less detailed group or mark the event as unsupported.
    """
    groups = defaultdict(list)
    for row in rows:
        fold = row["tournament"] % 2
        h, odds, opp = row["hero_class"], row["pot_odds_bucket"], row["opponent_profile"]
        for key in ((opp, h, odds), (h, odds), (h,)):
            groups[(fold, key)].append(row["call_realized_bb"])
    return groups


def _learn_action(row, training):
    fold = 1 - row["tournament"] % 2
    h, odds, opp = row["hero_class"], row["pot_odds_bucket"], row["opponent_profile"]
    for key in ((opp, h, odds), (h, odds), (h,)):
        values = training.get((fold, key), ())
        if len(values) >= 20:
            return "call" if _mean(values) > 0 else "fold"
    return None


def _summary(rows, *, counts=None):
    n = len(rows)
    policy = [r["policy_realized_bb"] for r in rows]
    call = [r["call_realized_bb"] for r in rows]
    compared = [r for r in rows if r.get("out_of_sample_action")]
    # Difference is a paired OOS policy comparison, not individual regret.
    diff = lambda r: (r["call_realized_bb"] if r["out_of_sample_action"] == "call"
                      else 0.) - r["policy_realized_bb"]
    result = {
        "n": n,
        "tournaments": len({r["tournament"] for r in rows}),
        "call_pct": round(100 * sum(r["chosen"] == "call" for r in rows) / n, 2) if n else None,
        "mean_policy_realized_bb": round(_mean(policy), 4) if n else None,
        "policy_ci95_bb": _cluster_interval(rows, lambda r: r["policy_realized_bb"]),
        "mean_always_call_realized_bb": round(_mean(call), 4) if n else None,
        "always_call_ci95_bb": _cluster_interval(rows, lambda r: r["call_realized_bb"]),
        "mean_always_fold_realized_bb": 0.0 if n else None,
        "out_of_sample_n": len(compared),
        "oos_delta_vs_policy_bb": round(_mean([diff(r) for r in compared]), 4)
                                  if compared else None,
        "oos_delta_ci95_bb": _cluster_interval(compared, diff),
        "oos_coverage_pct": round(100 * len(compared)/n, 2) if n else None,
    }
    if counts:
        result["eligible"] = counts.get("eligible", 0)
        result["skipped_actions"] = counts.get("skipped_actions", 0)
    return result


def build_report(records, *, percent=25, collection_counts=None,
                 aggression_records=(), aggression_counts=None):
    """Offline independent scoreboard; no same-hand action oracle allowed."""
    rows = [dict(r) for r in records]
    counts = dict(collection_counts or {})
    training = _training_groups(rows)
    for row in rows:
        row["out_of_sample_action"] = _learn_action(row, training)
    by_bot = defaultdict(list)
    by_class = defaultdict(list)
    for row in rows:
        by_bot[row["bot"]].append(row)
        by_class[(row["bot"], row["hero_class"])].append(row)
    bots = []
    for name, samples in by_bot.items():
        stats = _summary(samples)
        bots.append({"bot": name, **stats})
    bots.sort(key=lambda b: (b["oos_delta_vs_policy_bb"] is None,
                             -(b["mean_policy_realized_bb"] or 0), b["bot"]))
    classes = [
        {"bot": bot, "hero_class": cat, **_summary(items)}
        for (bot, cat), items in sorted(by_class.items())
    ]
    # Large single-hand swings are descriptive counterfactual *outcomes*,
    # not evidence of a bad decision on that hand.
    examples = sorted(rows, key=lambda r: abs(r["call_realized_bb"]), reverse=True)[:30]
    return {
        "format": FORMAT,
        "mode": "independent_river",
        "label": "Independent River Auditor · терминальные HU FOLD/CALL",
        "sample_percent": percent,
        "sample_count": len(rows),
        "tournament_count": len({r["tournament"] for r in rows}),
        "collection": counts,
        "aggression": aggression_report(aggression_records, aggression_counts),
        "overall": _summary(rows, counts=counts),
        "bots": bots,
        "by_hero_class": classes,
        "examples": examples,
        "limits": {
            "supported": "River, exactly 1 active opponent, facing a bet, full call affordable, FOLD/CALL selected, no all-in opponent",
            "not_supported": ["Flop", "Turn", "River BET/CHECK", "River RAISE", "Multiway", "Side pots", "All-in opponents"],
            "missing_not_zero": True,
            "single_hand_regret": False,
            "ground_truth": "actual hidden villain cards used only after action, never disclosed",
            "counterfactual": "Exact terminal showdown payout of CALL or FOLD, conditioned on the actually dealt hand",
            "policy_comparison": "Out-of-sample baseline learned only from opposite-parity tournaments; thresholds learned using independent observed deals",
            "ci": "Approximate 95% CI clustered by tournament; unavailable with fewer than 8 tournaments or 30 scored opportunities",
            "warning": "A single realized payout is NOT an EV or a per-hand decision error; policy comparisons across different encountered states are not causal head-to-head evidence",
        },
        "message": ("Нет подходящих риверных HU FOLD/CALL решений: это не 0 regret."
                    if not rows else None),
    }
