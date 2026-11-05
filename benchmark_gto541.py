"""Repeatable CPU microbenchmark: GTO 5.4/15% vs cache-only GTO 5.4.1/15%.

Usage: python benchmark_gto541.py
No runtime threshold assertions: CI hardware and tournament mix vary.
"""
import time
from bots.gto_postflop_50 import RankAwareGTO54Bot
from bots.gto_postflop_541 import RankAwareGTO541Bot
from test_gto_postflop_50 import view

CASES = [
    ("flop", [("Q","h"),("8","s"),("3","d")], [("A","s"),("Q","s")]),
    ("turn", [("6","c"),("7","d"),("5","h"),("4","h")], [("8","d"),("8","h")]),
    ("river", [("5","h"),("3","h"),("6","h"),("T","h"),("6","c")],
     [("2","h"),("A","h")]),
    ("river", [("3","h"),("5","c"),("2","s"),("9","c"),("7","c")],
     [("5","d"),("2","d")]),
    ("river", [("A","s"),("T","s"),("5","s"),("2","s"),("A","c")],
     [("K","s"),("Q","d")]),
]


def profile(bot, rounds=600):
    t0 = time.thread_time_ns()
    digest = 0
    for i in range(rounds):
        street, board, hole = CASES[i % len(CASES)]
        v = view(street, board, to_call=20 if i % 4 == 0 else 0,
                 opponents=("P2", "P3", "P4"))
        v.hole_cards = hole
        v.hand_id = 10000 + i
        a = bot.act(v)
        digest += (a.amount or 0) + (a.type == "call")
    return (time.thread_time_ns() - t0) / 1e6, digest


if __name__ == "__main__":
    # Use separate bot instances with the same no-history assumption.
    orig = RankAwareGTO54Bot(step_pct=15, shadow_percent=0)
    opt = RankAwareGTO541Bot(shadow_percent=0)
    old_ms, old_digest = profile(orig)
    new_ms, new_digest = profile(opt)
    assert old_digest == new_digest, (old_digest, new_digest)
    print(f"GTO 5.4/15%:   {old_ms:.2f} ms / 600 decisions = {old_ms/600:.4f} ms/decision")
    print(f"GTO 5.4.1/15%: {new_ms:.2f} ms / 600 decisions = {new_ms/600:.4f} ms/decision")
    print(f"CPU speedup (repeated card scenarios): {old_ms/max(0.001,new_ms):.2f}x")
    print("This is a warm-cache synthetic benchmark; not a tournament speed guarantee.")
