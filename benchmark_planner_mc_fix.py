"""Railway A/B: Plan Monte Carlo evaluator, equity and end-to-end postflop EV.

Runs both implementations in the same environment with identical random seeds.
Only the scorer changes within each A/B pair. For biased-entry bug use
test_planner_mc_fix, which compares entrant frequencies to the model.
"""
import json
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
    print("PLAN_MC_BENCHMARK_PASS",flush=True)


if __name__=="__main__":
    main()
