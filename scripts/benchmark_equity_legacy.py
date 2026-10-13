"""Run a comparable warmed-equity microbenchmark in Codespaces.

Each original-vs-optimized pair has the same cards, seed and simulation
budget. Both paths are checked for identical output before timing results
are reported. No wall-time assertions are made.
"""
import argparse
import random
import statistics
import time

from core.equity_legacy import estimate_equity_legacy
from test_shared_legacy_equity import reference_legacy_equity


def benchmark(repeats=4, sims=100):
    hole = [("A", "s"), ("K", "h")]
    boards = {
        "flop": [("Q", "d"), ("J", "d"), ("2", "c")],
        "turn": [("Q", "d"), ("J", "d"), ("2", "c"), ("9", "h")],
        "river": [("Q", "d"), ("J", "d"), ("2", "c"), ("9", "h"), ("3", "s")],
    }
    print("Warmed benchmark: identical seeds, cards, opponents, sims")
    print(f"{'street':<8} {'opp':>4} {'legacy ms':>12} {'fast ms':>12} {'speedup':>9}")
    print("-" * 50)
    for street, board in boards.items():
        for opponents in (1, 3, 8):
            # Imports, table loads, and initialization are NOT timed.
            reference_legacy_equity(hole, board, opponents, 2, random.Random(0))
            estimate_equity_legacy(hole, board, opponents, 2, rng=random.Random(0))
            reference_times = []
            optimized_times = []
            for i in range(repeats):
                seed = 20261014 + i
                original_rng = random.Random(seed)
                optimized_rng = random.Random(seed)

                start = time.perf_counter()
                old = reference_legacy_equity(
                    hole, board, opponents, sims, original_rng
                )
                reference_times.append(time.perf_counter() - start)

                start = time.perf_counter()
                new = estimate_equity_legacy(
                    hole, board, opponents, sims, rng=optimized_rng
                )
                optimized_times.append(time.perf_counter() - start)

                if old != new or original_rng.getstate() != optimized_rng.getstate():
                    raise AssertionError(
                        f"Mismatch at {street}, opponents={opponents}, seed={seed}"
                    )
            old_ms = statistics.median(reference_times) * 1000
            new_ms = statistics.median(optimized_times) * 1000
            ratio = old_ms / new_ms if new_ms > 0 else float("inf")
            print(f"{street:<8} {opponents:>4d} {old_ms:>12.2f} {new_ms:>12.2f} {ratio:>8.2f}x")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=4)
    parser.add_argument("--sims", type=int, default=100)
    args = parser.parse_args()
    benchmark(args.repeats, args.sims)
