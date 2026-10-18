"""One-shot source of the checked-in 1,019-row composite scenario catalog.

Research step runs in CI ONLY; emits small per-row lines to retrieve through
GitHub logs, then a static data file is reviewed and committed. Does not run
in the web server, so browsing sheet 03 does not require millions of deals.
"""
from collections import Counter, defaultdict
from itertools import combinations, permutations
import json
import sys
import unittest

from flop_board_structure import classify_flop_board
from postflop_numeric_classifier import _make_kind, _NAMES
from postflop_composite_classifier import _legacy_notation, classify_composite_flop


class CompositeCatalogGeneration(unittest.TestCase):
    def test_emit_1019_verified_catalog_rows(self):
        deck = tuple((r, s) for r in range(2,15) for s in "shdc")
        renames = [dict(zip("shdc", p)) for p in permutations("shdc")]
        representatives = {}
        for board in combinations(deck, 3):
            equivalents = {
                tuple(sorted((r, mapping[s]) for r, s in board))
                for mapping in renames
            }
            key = min(equivalents)
            if key not in representatives:
                representatives[key] = (board, len(equivalents))
        self.assertEqual(len(representatives), 1755)
        examples = {}
        total_deals = Counter()
        weighted_total = 0
        for board, orbit_weight in representatives.values():
            board_info = classify_flop_board(board)
            group = board_info["group_id"]
            available = (card for card in deck if card not in set(board))
            for hole in combinations(available, 2):
                cards = hole + board
                kind = _make_kind(hole, board, [r for r,s in cards],
                                  Counter(r for r,s in cards), "flop")
                hero_id, hero_name = _NAMES[kind]
                scenario_id = f"F|{group}|{hero_id}"
                total_deals[scenario_id] += orbit_weight
                weighted_total += orbit_weight
                if scenario_id not in examples:
                    examples[scenario_id] = {
                        "id": scenario_id,
                        "board_group": group,
                        "board_name": board_info["group_name"],
                        "hero_class": "F-" + hero_id,
                        "hero_name": hero_name,
                        "hero": "-".join(str(r)+s for r,s in hole),
                        "board": "-".join(str(r)+s for r,s in board),
                    }
        self.assertEqual(weighted_total, 25989600)
        self.assertEqual(len(examples), 1019)
        for i, scenario_id in enumerate(sorted(examples)):
            row = examples[scenario_id]
            row["deals"] = total_deals[scenario_id]
            if i % 7 == 0:  # Genuine full 2+3 hand-level cross-check.
                result = classify_composite_flop(row["hero"],row["board"])
                self.assertEqual(result["id"], scenario_id)
            sys.stdout.write("COMPOSITE_CATALOG_ROW=" +
                json.dumps(row, ensure_ascii=False, separators=(",",":")) + "\n")
        sys.stdout.write("COMPOSITE_CATALOG_SUMMARY=" +
            json.dumps({"rows":len(examples),"total_deals":weighted_total,
                        "distinct_boards":len(representatives)},
                       ensure_ascii=False,separators=(",",":")) + "\n")
        sys.stdout.flush()


if __name__=="__main__":
    unittest.main()
