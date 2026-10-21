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
        self.assertGreaterEqual(len(examples), 100)
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
        self.assertEqual(len(result["rows"]), len(examples))

    def test_up_to_five_and_original_gto_or_lag_bot_modules_untouched(self):
        five = list(POLICIES)[:5]
        result = compare_request(request_for(
            [{"hole": "14 12", "board": "14-7-2"}], profiles=five,
        ))
        self.assertEqual(len(result["profiles"]), 5)
        self.assertEqual(set(result["rows"][0]["actions"]), set(five))
        for strategies in [[], five + ["tag_postflop_v1"],
                           ["gto_postflop_v1", "gto_postflop_v1"],
                           ["gto_postflop_v1", "unknown_postflop_profile"]]:
            with self.subTest(strategies=strategies):
                with self.assertRaises(ValueError):
                    compare_request({"strategies": strategies,
                                     "rows": [{"hole": "14 12", "board": "14-7-2"}]})

    def test_every_registered_policy_runs_on_each_street_and_bet_state(self):
        rows = [
            {"hole": "14 12", "board": "14-7-2"},
            {"hole": "14s 10s", "board": "7s-4s-2-9"},
            {"hole": "77", "board": "7-14-14-4-2"},
        ]
        names = list(POLICIES)
        for call in (0, 8):
            for start in (0, 5):
                with self.subTest(call=call,profiles=names[start:start+5]):
                    result = compare_request(request_for(
                        rows, profiles=names[start:start+5], to_call=call))
                    for row in result["rows"]:
                        for strategy in names[start:start+5]:
                            self.assertAlmostEqual(sum(row["actions"][strategy].values()), 1)

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
        too_many = request_for([{"hole":"14 12","board":"14-7-2"}] * 126)
        with self.assertRaises(ValueError):
            compare_request(too_many)

    def test_full_catalog_physical_batched_actions_and_validation(self):
        from postflop_composite_classifier import classify_composite_flop
        hero, board = "14s-13h", "7d-5c-2s"
        scenario = classify_composite_flop(hero, board)
        rows = [{"id":scenario["id"],"hero":hero,"board":board}]
        request = request_for(rows, profiles=["gto_postflop_20","lag_postflop_v1"])
        request["mode"]="physical_catalog"
        output = compare_request(request)
        self.assertEqual(output["method"],"empirical_bot_act_physical")
        self.assertEqual(output["suit_variants"],1)
        self.assertEqual(output["rows"][0]["scenario"]["id"],scenario["id"])
        for actions in output["rows"][0]["actions"].values():
            self.assertAlmostEqual(sum(actions.values()),1.0)
            self.assertTrue(set(actions) <= {"check","bet"})
        for invalid in [
            {**rows[0],"id":"F|INVALID"},
            {**rows[0],"hero":"7d-13h"},
            {**rows[0],"board":"7d-5c-5c"},
        ]:
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    compare_request({**request,"rows":[invalid]})
        with self.assertRaises(ValueError):
            compare_request({**request,"rows":rows*33})

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
                    self.assertEqual(data["rows"][0]["scenario"]["id"],"F-TPHK")
                original=urllib.request.Request(base+"/api/s100",headers={"X-Runner-Key":"compare_secret"})
                with urllib.request.urlopen(original,timeout=20) as r:
                    self.assertEqual(len(json.load(r)["scenarios"]),100)
            finally:
                server.shutdown();server.server_close();thread.join(timeout=5)


if __name__=="__main__":
    unittest.main()
