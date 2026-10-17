"""Regression suite for the independent numeric postflop classification sheet."""
import json
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
            ("14 12", "14-7-2", "F-TP"),
            ("14s 12s", "14-10s-7s", "F-TPFD"),
            ("9 8", "7-6-2", "F-OESD"),
            ("10 7", "9-6-2", "F-GS"),
            ("77", "14-7-2", "F-SET"),
            ("14s 12s", "10s-7s-2", "F-FD"),
            ("14s 12s", "10s-7s-2s", "F-FL"),
            ("14 10", "14-7-7-2", "T-2SH"),
            ("10 6", "13-7-7-10", "T-2SL"),
            ("14 7", "14-7-2-2", "T-2OWN"),
            ("14s 10s", "7s-4s-2-9", "T-FD"),
            ("14 10", "7-7-4-4-2", "R-2BD"),
            ("14s 10s", "7s-4s-2-9-3", "R-MFD"),
            ("88", "5s-7s-5z-3z-14z", "R-2PK"),
            ("77", "7-14-14-4-2", "R-FH"),
            ("77", "7-7-14-4-2", "R-4K"),
            ("14 2", "10-9-8-7-6", "R-BSTR"),
        ]
        for hand, board, code in examples:
            with self.subTest(hand=hand, board=board):
                result = classify_numeric(hand, board)
                self.assertEqual(result["scenario"]["id"], code)
                self.assertEqual(set(result), {"scenario", "hole", "board"})
                self.assertEqual(set(result["scenario"]), {"id", "name", "street"})

    def test_rank_validation_and_duplicate_physical_card(self):
        for hand, board in [
            ("15 12", "14-7-2"),
            ("14s 14s", "10-7-2"),
            ("14s 12s", "14s-7-2"),
            ("1414", "14-14-14"),
            ("14 12", "7-2"),
            ("14 12", "7-2-1"),
            ("14h 12h", "7-4-2"),
        ]:
            with self.subTest(hand=hand, board=board):
                with self.assertRaises(ValueError):
                    classify_numeric(hand, board)

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
                    self.assertEqual(parsed["scenario"]["id"], "F-TP")
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
