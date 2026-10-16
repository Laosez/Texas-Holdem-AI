"""Railway A/B: Plan Monte Carlo evaluator, equity and end-to-end postflop EV.

Runs both implementations in the same environment with identical random seeds.
Only the scorer changes within each A/B pair. For biased-entry bug use
test_planner_mc_fix, which compares entrant frequencies to the model.
"""
import json
from collections import Counter
import random
import statistics
import time
from unittest.mock import patch

import planner_equity as eq
import planner_postflop_ev as post


def benchmark_pair(label, calculation, repeats=3):
    modes = (("legacy",eq.score_seven),("fast",eq.score_seven_fast))
    values = {}
    timing = {}
    for name, func in modes:
        rows = []
        outcomes = []
        for _ in range(repeats):
            # Some postflop strategies draw on module-level random.random.
            # Reset that RNG too, so the exact same strategy decisions replay.
            random.seed(20261016)
            t0 = time.perf_counter()
            with patch.object(eq, "score_seven_fast", func):
                result = calculation()
            rows.append(time.perf_counter()-t0)
            outcomes.append(result)
        assert all(x == outcomes[0] for x in outcomes), (label, name, "non-deterministic")
        values[name] = outcomes[0]
        timing[name] = statistics.median(rows)
    if values["legacy"] != values["fast"]:
        raise AssertionError("%s: fast scorer changed EV/equity: %s" % (label,values))
    old,new=timing["legacy"],timing["fast"]
    print("PLAN_AB "+json.dumps({"scenario":label,"repeats":repeats,
        "legacy_seconds":round(old,5),"fast_seconds":round(new,5),
        "speedup":round(old/new,3),
        "result_identical":True},sort_keys=True),flush=True)


def main():
    print("PLAN_MC_BENCHMARK_BEGIN",flush=True)
    any_two = eq.WeightedRange({h:1.0 for h in eq.planner.HANDS})
    for n in (1,4,8):
        ranges=[any_two]*n
        benchmark_pair("showdown_AKs_%d_opponents"%n,
                       lambda r=ranges:eq.simulate_hand("AKs",r,trials=2000,seed=42))
    aces = eq.WeightedRange({"AA":1.0})
    manual=[{"entry_mode":"manual","entry_pct":50.0}]*2
    benchmark_pair("conditional_showdown_KK_2xAA",
                   lambda:eq.simulate_hand_variable("KK",[aces,aces],manual,trials=1500,seed=42))

    payload={"hand":"AKs", "trials":200, "cycles":1,
             "hero_position":"3","hero_stack_bb":20,"hero_postflop":"gto2",
             "opponents":[{"profile":"builtin:any_two","position":"4",
                           "scenario":"rfi","players":9,"entry_mode":"manual",
                           "entry_pct":75.0,"postflop":"tag"},
                          {"profile":"builtin:any_two","position":"5",
                           "scenario":"rfi","players":9,"entry_mode":"manual",
                           "entry_pct":75.0,"postflop":"gto"}]}
    benchmark_pair("postflop_line_200_AKs_2_opponents",
                   lambda:post.calculate(payload),repeats=2)
    # Same stress case that exposed the original 25/50/25 -> 31/64/5 bias.
    rng=random.Random(424242)
    specs=[{"entry_mode":"manual","entry_pct":50.0}]*2
    counts=Counter(len(post._draw_case("KK",[aces,aces],specs,rng)[0])-1
                   for _ in range(12000))
    actual=[round(100*counts[i]/12000,2) for i in range(3)]
    print("PLAN_ENTRY_FREQUENCY "+json.dumps({
         "scenario":"Hero KK vs two AA-only 50% entrants",
         "expected_pct":[25,50,25],"observed_pct":actual,"trials":12000,
         "max_abs_error_pp":round(max(abs(a-b) for a,b in zip(actual,(25,50,25))),2)
         },sort_keys=True),flush=True)
    if max(abs(a-b) for a,b in zip(actual,(25,50,25)))>2:
        raise AssertionError("Entrant distribution still biased")

    # Full 169-cell calculation: measure the actual user-visible matrix path.
    op={"profile":"builtin:any_two","position":"4","scenario":"rfi",
        "players":9,"selector":"active","entry_mode":"always","entry_pct":100.0}
    benchmark_pair("full_169_hand_matrix_250_each_1_opponent",
                   lambda:eq.calculate_matrix([op],trials=250,cycles=1),
                   repeats=2)
    print("PLAN_MC_BENCHMARK_PASS",flush=True)


if __name__=="__main__":
    main()
