"""Regression suite for the independent numeric postflop classification sheet."""
import json
import ast
import random
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from postflop_numeric_classifier import classify_numeric
import replit_simulator as app


class NumericPostflopClassifierTests(unittest.TestCase):
    def test_each_deal_yields_exactly_one_street_scenario(self):
        examples = [
            # Existing fundamental postflop classes remain deterministic.
            ("14 12", "14-7-2", "F-TPHK"),
            ("14s 12s", "14-10s-7s", "F-TPFD"),
            ("9 8", "7-6-2", "F-OESD"),
            ("10 7", "9-6-2", "F-GS"),
            ("77", "14-7-2", "F-SET"),
            ("9s 4s", "10s-7s-2", "F-FD"),
            ("14s 12s", "10s-7s-2s", "F-FL2"),
            # P0: combinations where the formerly generic class lost vital draw equity.
            ("9s 8s", "7s-6s-2", "F-FDOESD"),
            ("14s 13s", "12s-11s-2", "F-FDGS"),
            ("9s 8s", "9-7s-6s", "F-TPFDOESD"),
            ("10s 7s", "10-9s-6s", "F-TPFDGS"),
            ("9 8", "9-7-6", "F-TPOESD"),
            ("8 7", "9-8-6", "F-MPOESD"),
            ("10 7", "10-9-6", "F-TPGS"),
            ("14s 13s", "10s-7s-2", "F-OCFD"),
            ("14s 12", "10s-7s-2s", "F-1CFD"),
            ("14 13", "12-11-2", "F-OCGS"),
            ("6 12", "8-9-10", "F-DGS"),
            # P1: weaker situations kept separate only where semantics differ.
            ("14 4", "10-7-2", "F-1OC"),
            ("14 12", "7-7-2", "F-PBOC"),
            ("10 10", "14-7-2", "F-PMID"),
            ("33", "14-7-4", "F-UP"),
            ("9s 4s", "14s-7-2", "F-BFD"),
            ("8 3", "14-10-2", "F-AIR"),
            # Pre-existing turn/river results should not regress.
            ("14 10", "14-7-7-2", "T-TPBP"),
            ("10 6", "13-7-7-10", "T-MPBP"),
            ("14 7", "14-7-2-2", "T-2OWN"),
            ("9s 4s", "14s-7s-2-3-11", "R-MFD"),
            ("14 10", "7-7-4-4-2", "R-2BDHK"),
            ("88", "5s-7s-5z-3z-14z", "R-2PK"),
            ("77", "7-14-14-4-2", "R-FHSET"),
            ("77", "7-7-14-4-2", "R-4KPK"),
            ("14 2", "10-9-8-7-6", "R-BSTR"),
        ]
        for hand, board, code in examples:
            with self.subTest(hand=hand, board=board):
                result = classify_numeric(hand, board)
                self.assertEqual(result["scenario"]["id"], code)
                self.assertEqual(set(result), {"scenario", "hole", "board"})
                self.assertEqual(set(result["scenario"]), {"id", "name", "street"})

    def test_pair_draw_subclasses_do_not_collapse_made_hand_strength(self):
        scenarios = [
            ("9s 8s", "9-7s-6s", "F-TPFDOESD"),
            ("10s 7s", "10-9s-6s", "F-TPFDGS"),
            ("9s 8s", "10s-9-7s", "F-MPFDOESD"),
            ("8s 7s", "10s-9s-8", "F-BPFDOESD"),
            ("9s 7s", "10s-9-6s", "F-MPFDGS"),
            ("7s 6s", "10s-9s-7", "F-BPFDGS"),
            ("9 8", "9-7-6", "F-TPOESD"),
            ("9 8", "10-9-7", "F-MPOESD"),
            ("8 7", "10-9-8", "F-BPOESD"),
            ("10 7", "10-9-6", "F-TPGS"),
            ("9 7", "10-9-6", "F-MPGS"),
            ("7 6", "10-9-7", "F-BPGS"),
            ("10s 10", "9s-7s-2s", "F-OP1CFD"),
            ("88", "7-6-5", "F-OPOESD"),
            ("88", "7-6-4", "F-OPGS"),
            ("8s 8", "7s-6s-5s", "F-OP1CFDOESD"),
            ("7s 7", "10s-9s-8s", "F-UP1CFDOESD"),
            ("77", "10-8-6", "F-PMIDGS"),
            ("9s 8s", "9-7s-6s-2", "T-TPFDOESD"),
            # River: failed FD is no longer a live draw. If a pair exists,
            # classify that made pair rather than return FDOESD/FD.
            ("9s 8s", "9-7s-6s-2-3", "R-TP"),
        ]
        for hero, board, wanted in scenarios:
            with self.subTest(hero=hero, board=board):
                self.assertEqual(classify_numeric(hero, board)["scenario"]["id"], wanted)
        self.assertEqual(
            [classify_numeric("9s 8s", b)["scenario"]["id"] for b in
             ("9-7s-6s", "9-7s-6s-2", "9-7s-6s-2-3")],
            ["F-TPFDOESD", "T-TPFDOESD", "R-TP"],
        )

    def test_rank_validation_and_duplicate_physical_card(self):
        for hand, board in [
            ("15 12", "14-7-2"),
            ("14s 14s", "10-7-2"),
            ("14s 12s", "14s-7-2"),
            ("1414", "14-14-14"),
            ("14 12", "7-2"),
            ("14 12", "7-2-1"),
            ("14h 12h", "7-4-2"),
            ("14s 12", "14-7-2"), # Single suit annotation is forbidden
        ]:
            with self.subTest(hand=hand, board=board):
                with self.assertRaises(ValueError):
                    classify_numeric(hand, board)

    def test_4000_random_flops_are_total_and_independent_of_real_suit_names(self):
        """Every genuine 5-card flop is accepted in the minimal repeat-only notation."""
        rng = random.Random(17026)
        deck = [(rank, suit) for rank in range(2, 15) for suit in "cdhs"]
        for iteration in range(4000):
            sample = rng.sample(deck, 5)
            counts = {s: sum(x[1] == s for x in sample) for s in "cdhs"}
            recurring = [s for _, s in sample if counts[s] >= 2]
            recurring = list(dict.fromkeys(recurring))
            self.assertLessEqual(len(recurring), 2)
            name = {s: "szy"[i] for i, s in enumerate(recurring)}
            tokens = [str(rank) + name.get(suit, "") for rank, suit in sample]
            result = classify_numeric(" ".join(tokens[:2]), "-".join(tokens[2:]))
            self.assertTrue(result["scenario"]["id"].startswith("F-"))
            self.assertTrue(result["scenario"]["name"])
            self.assertEqual(len(result["scenario"]), 3)

    def test_3000_random_river_paths_have_one_scenario_per_street(self):
        """A full hand has F -> T -> R scenarios, not a single lifetime label."""
        rng = random.Random(31018)
        deck = [(rank, suit) for rank in range(2, 15) for suit in "cdhs"]
        for _ in range(3000):
            cards = rng.sample(deck, 7)
            observed = []
            for board_size, prefix in ((3, "F"), (4, "T"), (5, "R")):
                dealt = cards[:2] + cards[2:2 + board_size]
                suit_counts = {s: sum(c[1] == s for c in dealt) for s in "cdhs"}
                repeated = list(dict.fromkeys(
                    suit for _, suit in dealt if suit_counts[suit] >= 2))
                labels = {s: "szy"[i] for i, s in enumerate(repeated)}
                normalized = [str(rank) + labels.get(suit, "")
                              for rank, suit in dealt]
                found = classify_numeric(" ".join(normalized[:2]),
                                         "-".join(normalized[2:]))
                self.assertTrue(found["scenario"]["id"].startswith(prefix + "-"))
                observed.append(found["scenario"]["id"])
            self.assertEqual(len(observed), 3)
        self.assertEqual(
            [classify_numeric("14 12", b)["scenario"]["id"] for b in
             ("14-7-2", "14-7-2-7", "14-7-2-7-12")],
            ["F-TPHK", "T-TPBP", "R-2OWN"],
        )

    def test_strategy_ledger_examples_have_correct_single_scenario(self):
        html = (app.ROOT / "replit_ui/s100.html").read_text(encoding="utf-8")
        start = html.index("const rows=[") + len("const rows=[")
        end = html.index("\n];", start)
        entries = ast.literal_eval("[" + html[start:end] + "]")
        self.assertGreaterEqual(len(entries), 100)
        streets = {"Флоп": 0, "Тёрн": 0, "Ривер": 0}
        seen = set()
        for street, hole, board, title, expected in entries:
            with self.subTest(street=street, hole=hole, board=board):
                actual = classify_numeric(hole, board)
                self.assertEqual(actual["scenario"]["id"], expected)
                self.assertEqual(actual["scenario"]["name"], title)
                self.assertNotIn((street, expected), seen)
                seen.add((street, expected))
                streets[street] += 1
        self.assertGreaterEqual(streets["Флоп"], 60)
        self.assertGreaterEqual(streets["Тёрн"], 15)
        self.assertGreaterEqual(streets["Ривер"], 15)

    def test_original_s100_unchanged_and_numeric_api_authenticated(self):
        with patch.object(app, "TOKEN", "numeric_classifier_test_key"):
            server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            url = f"http://127.0.0.1:{server.server_address[1]}"
            payload = json.dumps({"hole": "14 12", "board": "14-7-2"}).encode()

            def post(path, authorized=True):
                headers = {"Content-Type": "application/json"}
                if authorized:
                    headers["X-Runner-Key"] = "numeric_classifier_test_key"
                return urllib.request.urlopen(
                    urllib.request.Request(url + path, data=payload, headers=headers),
                    timeout=10,
                )
            try:
                with self.assertRaises(urllib.error.HTTPError) as denied:
                    post("/api/postflop/classify", authorized=False)
                self.assertEqual(denied.exception.code, 401)
                with post("/api/postflop/classify") as response:
                    self.assertEqual(response.status, 200)
                    parsed = json.load(response)
                    self.assertEqual(parsed["scenario"]["id"], "F-TPHK")
                with urllib.request.urlopen(urllib.request.Request(
                        url + "/api/s100",
                        headers={"X-Runner-Key": "numeric_classifier_test_key"}),
                        timeout=10) as response:
                    self.assertEqual(len(json.load(response)["scenarios"]), 100)
                html = (app.ROOT / "replit_ui/s100.html").read_text(encoding="utf-8")
                for fragment in ('id="numericClassifier"', 'id="classHole"',
                                 'id="classBoard"', 'id="classify"',
                                 'id="classExamples"', 'id="classResult"'):
                    self.assertIn(fragment, html)
                self.assertIn("'/api/postflop/classify'", html)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
