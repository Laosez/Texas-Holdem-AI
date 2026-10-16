"""Benchmark canonical equity with fixed cases and reproducible seeds.

Usage:
 python benchmark_equity.py --output equity_benchmark.csv
 python benchmark_equity.py --counts 250,500,1000 --output quick.csv
"""
import argparse
import csv
import random
import statistics
import time

from core.equity import equity

CASES = {
    "preflop_hu": ([("A","s"),("K","s")], [], 1),
    "preflop_multiway": ([("Q","h"),("J","h")], [], 4),
    "flop_multiway": ([("T","s"),("9","s")], [("8","s"),("7","d"),("2","c")], 3),
    "turn_hu": ([("A","h"),("Q","d")], [("A","c"),("7","h"),("2","s"),("J","c")], 1),
    "river_multiway": ([("K","c"),("K","d")], [("A","s"),("T","h"),("7","d"),("4","c"),("2","h")], 4),
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--counts", default="250,500,1000,2000,4000,8000,16000,32000,64000")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", default="equity_benchmark.csv")
    args = parser.parse_args()
    counts = [int(x.strip()) for x in args.counts.split(",")]
    if args.repeats < 1 or any(n < 1 for n in counts):
        parser.error("counts and repeats must be positive")
    results = []
    for name, (hole, board, opponents) in CASES.items():
        for n in counts:
            timings, estimates = [], []
            for repeat in range(args.repeats):
                rng = random.Random(20261016 + repeat)
                start = time.perf_counter()
                estimate = equity(hole, board, opponents, n_sims=n, rng=rng)
                elapsed = time.perf_counter() - start
                timings.append(elapsed)
                estimates.append(estimate)
            row = dict(case=name, opponents=opponents, simulations=n,
                       repeats=args.repeats,
                       seconds_median=round(statistics.median(timings), 6),
                       sims_per_sec_median=round(statistics.median(n/t for t in timings), 1),
                       equity_mean=round(statistics.mean(estimates), 6),
                       equity_std=round(statistics.stdev(estimates), 6) if len(estimates)>1 else 0)
            results.append(row)
            print(row, flush=True)
    with open(args.output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=results[0])
        writer.writeheader()
        writer.writerows(results)
    print("Wrote", args.output)


if __name__ == "__main__":
    main()
