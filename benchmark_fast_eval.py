"""A/B benchmark: same Monte Carlo draws, only the evaluator changes.

python -u benchmark_fast_eval.py --samples 8000 --repeats 3
"""
import argparse
import json
import random
import statistics
import time

from core.engine import _legacy_eval_hand as legacy_eval_hand
from core.fast_eval import fast_eval_hand
from core.equity import equity

CASES = {
    "preflop_hu": ([("A", "s"), ("K", "s")], [], 1),
    "preflop_multiway": ([("Q", "h"), ("J", "h")], [], 4),
    "flop_multiway": ([("T", "s"), ("9", "s")], [("8", "s"), ("7", "d"), ("2", "c")], 3),
    "turn_hu": ([("A", "h"), ("Q", "d")], [("A", "c"), ("7", "h"), ("2", "s"), ("J", "c")], 1),
    "river_multiway": ([("K", "c"), ("K", "d")], [("A", "s"), ("T", "h"), ("7", "d"), ("4", "c"), ("2", "h")], 4),
}


def benchmark_case(name, hole, board, opponents, samples, repeats):
    durations = {"legacy": [], "fast": []}
    methods = {"legacy": legacy_eval_hand, "fast": fast_eval_hand}
    for rep in range(repeats):
        seed = 20261016 + rep
        # Alternate invocation order to reduce warm-up or scheduling bias.
        order = ("legacy", "fast") if rep % 2 == 0 else ("fast", "legacy")
        values = {}
        for mode in order:
            started = time.perf_counter()
            values[mode] = equity(hole, board, opponents, n_sims=samples,
                                  rng=random.Random(seed), evaluator=methods[mode])
            durations[mode].append(time.perf_counter() - started)
        if values["legacy"] != values["fast"]:
            raise AssertionError(f"{name}: equity differs with seed {seed}: {values}")
    old = statistics.median(durations["legacy"])
    new = statistics.median(durations["fast"])
    return {"scenario": name, "opponents": opponents, "samples": samples,
            "repeats": repeats, "legacy_seconds": round(old, 6),
            "fast_seconds": round(new, 6), "speedup": round(old / new, 3),
            "legacy_sims_per_sec": round(samples / old, 1),
            "fast_sims_per_sec": round(samples / new, 1),
            "equity": round(values["fast"], 6)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=8000)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.samples <= 0 or args.repeats <= 0:
        parser.error("Positive samples and repeats required")
    print("FAST_EVAL_BENCHMARK_BEGIN", flush=True)
    for name, (hole, board, opponents) in CASES.items():
        print("FAST_EVAL " + json.dumps(
            benchmark_case(name, hole, board, opponents, args.samples, args.repeats),
            sort_keys=True), flush=True)
    print("FAST_EVAL_BENCHMARK_END", flush=True)


if __name__ == "__main__":
    main()
