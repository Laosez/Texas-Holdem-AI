"""One-off audit: count ACTUALLY REACHABLE composite F|board|HERO IDs.

All 25,989,600 physical 2+3 allocations have suit symmetry. Exactly one
representative of each of the 1,755 unlabeled 3-card flop suit orbits,
followed by all valid 2-card holes, covers the entire space of unique IDs.
No bot policies, web endpoints or class definitions changed.
"""
from collections import Counter, defaultdict
from itertools import combinations, permutations
import json
import sys
import time
import unittest

from flop_board_structure import classify_flop_board
from postflop_numeric_classifier import _make_kind, _NAMES, classify_numeric
from postflop_composite_classifier import _legacy_notation


class CompositeCensusResearch(unittest.TestCase):
    def test_exhaustive_census(self):
        deck = tuple((r, s) for r in range(2,15) for s in "shdc")
        suits = "shdc"
        maps = [
            dict(zip(suits, perm)) for perm in permutations(suits)
        ]
        reps = {}
        for board in combinations(deck,3):
            canonical = min(
                tuple(sorted(((rank, m[suit]) for rank,suit in board)))
                for m in maps
            )
            reps.setdefault(canonical,board)
        self.assertEqual(len(reps),1755)
        categories = defaultdict(set)
        physical_counts = Counter()
        first_cases = 0
        started=time.monotonic()
        for board in reps.values():
            gid = classify_flop_board(board)["group_id"]
            board_set = set(board)
            available = tuple(c for c in deck if c not in board_set)
            for hole in combinations(available,2):
                cards=hole+board
                ranks=[r for r,s in cards]
                kind=_make_kind(hole,board,ranks,Counter(ranks),"flop")
                hero_code=_NAMES[kind][0]
                categories[gid].add(hero_code)
                physical_counts[gid]+=1
                if first_cases < 500:
                    actual_h,actual_b=_legacy_notation(list(hole),list(board))
                    actual_code=classify_numeric(actual_h,actual_b)["scenario"]["id"][2:]
                    self.assertEqual(actual_code,hero_code)
                    first_cases+=1
        self.assertEqual(sum(physical_counts.values()),1755*1176)
        self.assertEqual(len(categories),46)
        unique=sum(len(v) for v in categories.values())
        all_hits = set().union(*categories.values())
        perboard={g:len(h) for g,h in sorted(categories.items())}
        result={
            "unique_composite_ids":unique,
            "board_groups":len(categories),
            "hero_codes_seen":len(all_hits),
            "naive_product":46*len(all_hits),
            "flop_suit_orbits":len(reps),
            "enumerated_board_hero_pairs":sum(physical_counts.values()),
            "all_physical_board_hero_deals":25989600,
            "per_board_group_counts":perboard,
            "all_hero_codes":sorted(all_hits),
            "elapsed_s":round(time.monotonic()-started,2),
        }
        sys.stderr.write("COMPOSITE_CENSUS_RESULT="+json.dumps(result,ensure_ascii=False,sort_keys=True)+"\n")
        self.assertGreater(unique,46)
        self.assertLess(unique,46*len(all_hits))


if __name__=="__main__":
    unittest.main()
