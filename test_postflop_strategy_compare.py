"""Compare actual registered postflop bot policies without modifying their logic."""
import ast
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from bots import create_bot
from postflop_strategy_compare import POLICIES, _physical_variants, compare_request
import replit_simulator as app


def request_for(rows, profiles=None, **context):
    return {
        "strategies": profiles or ["gto_postflop_v1", "lag_postflop_v1"],
        "rows": rows,
        "context": {"opponents": 1, "position": "IP", "preflop_aggressor": True,
                    "pot": 24, "to_call": 0, "stack": 80, **context},
    }


class PostflopStrategyCompareTests(unittest.TestCase):
    def test_all_dropdown_profiles_are_genuine_bots(self):
        self.assertGreaterEqual(len(POLICIES), 5)
        for name in POLICIES:
            with self.subTest(name=name):
                self.assertTrue(callable(create_bot(name).act))

    def test_facing_and_no_bet_use_real_legal_action_frequencies(self):
        rows = [{"hole": "14 12", "board": "14-7-2"},
                {"hole": "9s 8s", "board": "7s-6s-2"}]
        for call, allowed in [(0, {"bet", "check"}), (8, {"raise", "call", "fold"})]:
            with self.subTest(call=call):
                result = compare_request(request_for(rows, to_call=call))
                self.assertEqual(len(result["rows"]), len(rows))
                self.assertEqual(result["samples_per_strategy"], 96)
                self.assertEqual(result["method"], "empirical_bot_act")
                for row in result["rows"]:
                    for scores in row["actions"].values():
                        self.assertAlmostEqual(sum(scores.values()), 1.0)
                        self.assertTrue(set(scores) <= allowed)

    def test_examples_all_can_be_realized_with_real_cards_and_compared(self):
        text = Path("replit_ui/s100.html").read_text(encoding="utf-8")
        start = text.index("const rows=[") + len("const rows=[")
        end = text.index("\n];", start)
        examples = ast.literal_eval("[" + text[start:end] + "]")
        self.assertEqual(len(examples), 44)
        for street, hole, board, title, code in examples:
            with self.subTest(scenario=code):
                variations = _physical_variants(hole, board, code)
                self.assertGreaterEqual(len(variations), 1)
                self.assertEqual(len(variations[0][0]), 2)
                self.assertEqual(len(variations[0][1]), {"Флоп":3,"Тёрн":4,"Ривер":5}[street])
                cards = variations[0][0] + variations[0][1]
                self.assertEqual(len(cards), len(set(cards)))
        result = compare_request(request_for([
            {"hole": h, "board": b} for _,h,b,_,_ in examples
        ]))
        self.assertEqual(len(result["rows"]), 44)

    def test_up_to_five_and_original_gto_or_lag_bot_modules_untouched(self):
        five = list(POLICIES)[:5]
        result = compare_request(request_for(
            [{"hole": "14 12", "board": "14-7-2"}], profiles=five,
        ))
        self.assertEqual(len(result["profiles"]), 5)
        self.assertEqual(set(result["rows"][0]["actions"]), set(five))
        for strategies in [[], five + ["tag_postflop_v1"],
                           ["gto_postflop_v1", "gto_postflop_v1"],
                           ["gto_postflop_v1", "os.system('echo broken')"]]:
            with self.subTest(strategies=strategies):
                with self.assertRaises(ValueError):
                    compare_request({"strategies": strategies,
                                     "rows": [{"hole": "14 12", "board": "14-7-2"}]})

    def test_context_and_payload_are_bounded_and_validated(self):
        basic = request_for([{"hole":"14 12","board":"14-7-2"}])
        for changes in [
            {"opponents":9},{"opponents":0},{"opponents":True},
            {"position":"fake"},{"preflop_aggressor":"yes"},{"stack":0},
            {"pot":-1},{"to_call":81},{"pot":8,"to_call":16},
        ]:
            with self.subTest(changes=changes):
                data = {**basic,"context": {**basic["context"],**changes}}
                with self.assertRaises(ValueError):
                    compare_request(data)
        too_many = request_for([{"hole":"14 12","board":"14-7-2"}] * 51)
        with self.assertRaises(ValueError):
            compare_request(too_many)

    def test_authenticated_http_endpoint_and_existing_s100_intact(self):
        with patch.object(app,"TOKEN","compare_secret"):
            server = ThreadingHTTPServer(("127.0.0.1",0),app.Handler)
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            base=f"http://127.0.0.1:{server.server_address[1]}"
            body=json.dumps(request_for([{"hole":"14 12","board":"14-7-2"}])).encode()
            try:
                unauth=urllib.request.Request(base+"/api/postflop/compare",
                                              data=body,headers={"Content-Type":"application/json"})
                with self.assertRaises(urllib.error.HTTPError) as denied:
                    urllib.request.urlopen(unauth,timeout=20)
                self.assertEqual(denied.exception.code,401)
                authorized=urllib.request.Request(
                    base+"/api/postflop/compare",data=body,
                    headers={"Content-Type":"application/json","X-Runner-Key":"compare_secret"})
                with urllib.request.urlopen(authorized,timeout=25) as r:
                    self.assertEqual(r.status,200)
                    data=json.load(r)
                    self.assertEqual(data["rows"][0]["scenario"]["id"],"F-TP")
                original=urllib.request.Request(base+"/api/s100",headers={"X-Runner-Key":"compare_secret"})
                with urllib.request.urlopen(original,timeout=20) as r:
                    self.assertEqual(len(json.load(r)["scenarios"]),100)
            finally:
                server.shutdown();server.server_close();thread.join(timeout=5)


if __name__=="__main__":
    unittest.main()
