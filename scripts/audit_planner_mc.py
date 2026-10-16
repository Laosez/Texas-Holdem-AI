"""Independent audit of Monte Carlo on Screen 2 /plan (no production mutations).

Checks ranking parity, equity sampler throughput, the participant-frequency
model under blockers, and Python CPU time distribution. Prints audit markers
to Railway deployment logs for verification.
"""
import collections
import cProfile
import io
import json
import math
import pstats
import random
import time

import planner_equity as eq
import planner_postflop_ev as post
from core.fast_eval import fast_eval_hand

RANKS = "23456789TJQKA"
SUITS = "cdhs"


def score_fast(cards):
    tuples = [(RANKS[c // 4], SUITS[c % 4]) for c in cards]
    value = fast_eval_hand(tuples[:2], tuples[2:])
    return value


def ranking_parity():
    rng = random.Random(14112026)
    cards = list(range(52))
    hands = [rng.sample(cards, 7) for _ in range(25000)]
    # Compare ordering, not raw scores: planner uses tuples; engine integers.
    pairs = [(rng.randrange(len(hands)), rng.randrange(len(hands))) for _ in range(50000)]
    old = [eq.score_seven(h) for h in hands]
    new = [score_fast(h) for h in hands]
    by_cat = collections.Counter(value[0] for value in old)
    disagreements = []
    for i, j in pairs:
        old_cmp = (old[i] > old[j]) - (old[i] < old[j])
        new_cmp = (new[i] > new[j]) - (new[i] < new[j])
        if old_cmp != new_cmp:
            disagreements.append((i, j, old[i], old[j], new[i], new[j]))
    print("RANKING_PARITY " + json.dumps({
        "sampled_7_card_hands":len(hands),
        "head_to_head_rank_order_checks":len(pairs),
        "disagreements":len(disagreements),
        "examples":disagreements[:3],
        "category_counts":dict(by_cat)
    },sort_keys=True),flush=True)


def sample_entry_bias():
    # With externally specified independent 50% manual entrance probabilities,
    # the visible entry-frequency model is exactly [25%, 50%, 25%].
    # Two AA-only ranges are severely mutually card-blocking.
    aa = eq.WeightedRange({"AA":1.0})
    specs = [{"entry_mode":"manual","entry_pct":50.0}] * 2
    predicted, _ = eq.entry_distributions("KK", [aa,aa], specs)
    rng = random.Random(424242)
    counts = [0,0,0]
    n=12000
    for _ in range(n):
        picked, _ = post._draw_case("KK",[aa,aa],specs,rng)
        counts[len(picked)-1] += 1
    observed = [round(x/n,5) for x in counts]
    print("ENTRY_BIAS " + json.dumps({
        "case":"Hero KK; two villains AA-only; each manual enter 50%",
        "expected_entry_mixture":[round(x,5) for x in predicted],
        "observed_accepted_mixture":observed,
        "observations":n,
        "discrepancy_pp":[round(100*(observed[i]-predicted[i]),2) for i in range(3)]
    },sort_keys=True),flush=True)


def profile_planner():
    # Representative all-in matrix simulation, measured independently of
    # the postflop engine and without evaluator switch.
    for label, n in (("any_two_hu",1),("any_two_4_way",4)):
        ranges = [eq.WeightedRange({h:1.0 for h in eq.planner.HANDS}) for _ in range(n)]
        start=time.perf_counter()
        value=eq.simulate_hand("AKs",ranges,trials=1500,seed=1234)
        elapsed=time.perf_counter()-start
        print("PLANNER_EQUITY_BENCH "+json.dumps({"scenario":label,"trials":1500,
            "seconds":round(elapsed,4),"trials_per_second":round(1500/elapsed,1),
            "equity_pct":value}),flush=True)

    ranges=[eq.WeightedRange({h:1.0 for h in eq.planner.HANDS}) for _ in range(3)]
    pr=cProfile.Profile()
    pr.runcall(eq.simulate_hand,"AKs",ranges,1000,1234)
    out=io.StringIO()
    pstats.Stats(pr,stream=out).strip_dirs().sort_stats("cumulative").print_stats(24)
    print("PLANNER_CPROFILE_BEGIN",flush=True)
    print(out.getvalue(),flush=True)
    print("PLANNER_CPROFILE_END",flush=True)


def main():
    print("PLANNER_MC_AUDIT_BEGIN",flush=True)
    ranking_parity()
    sample_entry_bias()
    profile_planner()
    print("PLANNER_MC_AUDIT_END",flush=True)


if __name__=="__main__":
    main()
