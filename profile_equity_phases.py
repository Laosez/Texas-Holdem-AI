"""Isolated wall-time and cProfile audit of the canonical equity hot path.

This intentionally mirrors core.equity.equity without modifying production logic.
Phase timing adds perf_counter_ns instrumentation; cProfile is a SEPARATE run
because deterministic profiler overhead would distort wall-time percentages.
"""
from __future__ import annotations

import argparse
import cProfile
import io
import json
import pstats
import random
import statistics
import time

from core.engine import _FULL_DECK, eval_hand
from core.equity import equity

CASES = {
    "preflop_hu": ([("A", "s"), ("K", "s")], [], 1),
    "preflop_multiway": ([("Q", "h"), ("J", "h")], [], 4),
    "flop_multiway": ([("T", "s"), ("9", "s")], [("8", "s"), ("7", "d"), ("2", "c")], 3),
    "turn_hu": ([("A", "h"), ("Q", "d")], [("A", "c"), ("7", "h"), ("2", "s"), ("J", "c")], 1),
    "river_multiway": ([("K", "c"), ("K", "d")], [("A", "s"), ("T", "h"), ("7", "d"), ("4", "c"), ("2", "h")], 4),
}
PHASES = ("deck_setup", "sample_cards", "build_board", "hero_eval", "opponent_eval", "compare_scores", "payout")


def timed_equity(hole_cards, board, opponents, n_sims, rng):
    """Same deals and outcomes as core.equity.equity, with phase timers."""
    ns = time.perf_counter_ns
    phases = {name: 0 for name in PHASES}
    total_start = ns()

    t0 = ns()
    known = [tuple(c) for c in hole_cards] + [tuple(c) for c in board]
    used = set(known)
    remaining = [c for c in _FULL_DECK if c not in used]
    missing = 5 - len(board)
    draw_count = 2 * opponents + missing
    hero_hole = list(hole_cards)
    board_prefix = list(board)
    sample = rng.sample
    phases["deck_setup"] += ns() - t0

    payout = 0.0
    for _ in range(n_sims):
        t0 = ns()
        drawn = sample(remaining, draw_count)
        phases["sample_cards"] += ns() - t0

        t0 = ns()
        full_board = board_prefix + drawn[2 * opponents:]
        phases["build_board"] += ns() - t0

        t0 = ns()
        hero_score = eval_hand(hero_hole, full_board)
        phases["hero_eval"] += ns() - t0

        best = hero_score
        winners = 1
        for j in range(0, 2 * opponents, 2):
            t0 = ns()
            score = eval_hand(drawn[j:j + 2], full_board)
            phases["opponent_eval"] += ns() - t0

            t0 = ns()
            if score > best:
                best = score
                winners = 0
            if score == best:
                winners += 1
            phases["compare_scores"] += ns() - t0

        t0 = ns()
        if hero_score == best:
            payout += 1.0 / winners
        phases["payout"] += ns() - t0

    elapsed = ns() - total_start
    known_time = sum(phases.values())
    phases["unattributed_loop_and_timers"] = max(0, elapsed - known_time)
    return payout / n_sims, elapsed, phases


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=8000)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--profile-samples", type=int, default=1000)
    args = parser.parse_args()
    if min(args.samples, args.repeats, args.profile_samples) < 1:
        parser.error("All sample counts and repeats must be positive")

    print("PHASE_AUDIT_BEGIN", flush=True)
    for name, (hole, board, opponents) in CASES.items():
        results = []
        for rep in range(args.repeats):
            seed = 20261016 + rep
            result, elapsed, phases = timed_equity(hole, board, opponents, args.samples, random.Random(seed))
            # Verify the instrumented copy on identical deals.
            reference = equity(hole, board, opponents, n_sims=args.samples, rng=random.Random(seed))
            if result != reference:
                raise AssertionError(f"{name}: instrumented result {result} != canonical {reference}")
            results.append((elapsed, phases, result))
        med_elapsed = statistics.median(row[0] for row in results)
        median_phases = {k: statistics.median(row[1][k] for row in results) for k in results[0][1]}
        # Use total of phase medians as the distribution denominator so the
        # presented percentage breakdown sums to exactly 100%.
        phase_sum = sum(median_phases.values())
        print("PHASE " + json.dumps({
            "scenario": name, "opponents": opponents, "samples": args.samples, "repeats": args.repeats,
            "median_wall_ms": round(med_elapsed / 1e6, 3),
            "simulations_per_sec": round(args.samples / (med_elapsed / 1e9), 1),
            "equity_median": round(statistics.median(row[2] for row in results), 6),
            "parts": {k: {"ms": round(v / 1e6, 3), "percent": round(100 * v / phase_sum, 2)}
                      for k, v in median_phases.items()}
        }, sort_keys=True), flush=True)
    print("PHASE_AUDIT_END", flush=True)

    for name in ("preflop_hu", "preflop_multiway", "river_multiway"):
        hole, board, opponents = CASES[name]
        profiler = cProfile.Profile()
        profiler.runcall(equity, hole, board, opponents, args.profile_samples, random.Random(20261016))
        stream = io.StringIO()
        pstats.Stats(profiler, stream=stream).strip_dirs().sort_stats("cumulative").print_stats(16)
        print(f"CPROFILE_BEGIN scenario={name} samples={args.profile_samples}", flush=True)
        print(stream.getvalue(), flush=True)
        print(f"CPROFILE_END scenario={name}", flush=True)


if __name__ == "__main__":
    main()
