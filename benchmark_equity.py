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
from core.engine import eval_hand, _FULL_DECK

CASES = {
    "preflop_hu": ([("A","s"),("K","s")], [], 1),
    "preflop_multiway": ([("Q","h"),("J","h")], [], 4),
    "flop_multiway": ([("T","s"),("9","s")], [("8","s"),("7","d"),("2","c")], 3),
    "turn_hu": ([("A","h"),("Q","d")], [("A","c"),("7","h"),("2","s"),("J","c")], 1),
    "river_multiway": ([("K","c"),("K","d")], [("A","s"),("T","h"),("7","d"),("4","c"),("2","h")], 4),
}


def baseline_equity(hole_cards, board, n_opponents, n_sims, rng):
    """Original core/equity.py algorithm (before this audit) for timing parity."""
    used = set(tuple(c) for c in hole_cards) | set(tuple(c) for c in board)
    remaining = [c for c in _FULL_DECK if c not in used]
    wins, total = 0.0, 0
    for _ in range(n_sims):
        sampled = rng.sample(remaining, 2 * n_opponents)
        opp_hands = [sampled[i * 2:(i + 1) * 2] for i in range(n_opponents)]
        dealt_set = set(tuple(c) for c in sampled)
        rest = [c for c in remaining if tuple(c) not in dealt_set]
        need = 5 - len(board)
        if need > 0:
            extra = rng.sample(rest, need)
            full_board = list(board) + extra
        else:
            full_board = list(board)
        my_score = eval_hand(list(hole_cards), full_board)
        best_opp = max(eval_hand(oh, full_board) for oh in opp_hands)
        if my_score > best_opp:
            wins += 1
        elif my_score == best_opp:
            tying = sum(1 for oh in opp_hands if eval_hand(oh, full_board) == my_score)
            wins += 1.0 / (1 + tying)
        total += 1
    return wins / total if total > 0 else 0.5


def compare_engines():
    """Same evaluator, random opponent model, case and number of iterations."""
    print("HEAD_TO_HEAD_BEGIN", flush=True)
    for name, (hole, board, opponents) in CASES.items():
        for n in (2000, 8000):
            start = time.perf_counter()
            old = baseline_equity(hole, board, opponents, n, random.Random(481))
            old_time = time.perf_counter() - start
            start = time.perf_counter()
            new = equity(hole, board, opponents, n_sims=n, rng=random.Random(481))
            new_time = time.perf_counter() - start
            print("COMPARE case=%s n=%d old=%.6f new=%.6f old_s=%.4f new_s=%.4f speedup=%.3fx" %
                  (name, n, old, new, old_time, new_time, old_time / new_time), flush=True)
    print("HEAD_TO_HEAD_END", flush=True)


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
    compare_engines()


if __name__ == "__main__":
    main()
