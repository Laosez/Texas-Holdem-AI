"""Physical flop composite scenarios: 46 board groups x HERO hit, no bot changes."""
import ast
from collections import Counter
from itertools import combinations
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import replit_simulator as app
from flop_board_structure import classify_flop_board
from postflop_composite_classifier import (
    classify_composite_flop, classify_composite_request, parse_physical_hero,
)
from postflop_strategy_compare import _physical_variants


class CompositeFlopTests(unittest.TestCase):
    def test_requested_example_and_alternative_hero_hits(self):
        cases = [
            ("9s-8s","9d-7s-6s","N-C4-2S","F-TPFDOESD","top_pair","flush_draw_two","oesd"),
            ("14s-13s","9d-7s-6s","N-C4-2S","F-OCFD","two_overcards","flush_draw_two","no_straight_draw"),
            ("9h-9c","9d-7s-6s","N-C4-2S","F-SET","pocket_set","no_flush_draw","no_straight_draw"),
            ("14s-7h","7s-7d-2c","P-H-R","F-TRPHK","board_trips","no_flush_draw","no_straight_draw"),
            ("10h-10c","9s-7h-2d","N-G2-R","F-OP","pocket_overpair","no_flush_draw","no_straight_draw"),
            ("14s-13s","12s-11s-2d","N-C2-2S","F-FDGS","two_overcards","flush_draw_two","gutshot"),
            ("14s-13h","14d-7s-2c","A-C2-R","F-TPHK","top_pair","no_flush_draw","no_straight_draw"),
        ]
        for h,b,board_id,hand_id,r,s,d in cases:
            with self.subTest(hero=h,board=b):
                result=classify_composite_flop(h,b)
                self.assertEqual(result["board"]["group_id"],board_id)
                self.assertEqual(result["hero_state"]["id"],hand_id)
                self.assertEqual(result["hit"]["rank"]["id"],r)
                self.assertEqual(result["hit"]["suit"]["id"],s)
                self.assertEqual(result["hit"]["straight"]["id"],d)
                self.assertEqual(result["id"],"F|"+board_id+"|"+hand_id[2:])

    def test_three_two_tone_locations_stay_one_board_group(self):
        for board in ("14s-13s-2d","14s-13d-2s","14d-13s-2s"):
            with self.subTest(board=board):
                hit=classify_composite_flop("9h-8h",board)
                self.assertEqual(hit["board"]["group_id"],"A-C2-2S")

    def test_suited_nut_draw_and_provenance(self):
        nut=classify_composite_flop("14s-13s","9d-7s-6s")
        self.assertTrue(nut["hit"]["suit"]["nut_draw"])
        dominated=classify_composite_flop("9s-8s","9d-7s-6s")
        self.assertFalse(dominated["hit"]["suit"]["nut_draw"])
        self.assertEqual(dominated["hit"]["suit"]["hole_cards"],2)
        self.assertEqual(dominated["hit"]["kicker"]["hole_rank"],8)

    def test_physical_input_and_duplicate_rejection(self):
        for hero,board in (
            ("9s-9s","9d-7s-6s"),
            ("9s-8s","9s-7h-2d"),
            ("9s-8s","9d-7s"),
            ("9-8","9d-7s-6s"),
            ("9s-8s","9-7-6"),
            ("15s-8s","9d-7s-6s"),
            ("9s-8s","7s-7s-6d"),
        ):
            with self.subTest(hero=hero,board=board):
                with self.assertRaises(ValueError):
                    classify_composite_flop(hero,board)
        for bad in (None, {}, [], {"hero": "9s-8s"}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    classify_composite_request(bad)

    def test_all_existing_flop_scenarios_reused_unchanged(self):
        html=(app.ROOT/"replit_ui/s100.html").read_text(encoding="utf-8")
        start=html.index("const rows=[")+len("const rows=[")
        end=html.index("\n];",start)
        samples=ast.literal_eval("["+html[start:end]+"]")
        checked=0
        for street,hole,board,title,code in samples:
            if street!="Флоп":
                continue
            physical_hero,physical_board=_physical_variants(hole,board,code)[0]
            hero="-".join(str(r)+s for r,s in physical_hero)
            flop="-".join(str(r)+s for r,s in physical_board)
            with self.subTest(scenario=code):
                result=classify_composite_flop(hero,flop)
                self.assertEqual(result["hero_state"]["id"],code)
                self.assertEqual(result["hero_state"]["name"],title)
            checked+=1
        self.assertGreaterEqual(checked,60)

    def test_all_19600_possible_flops_for_fixed_hero(self):
        """Exact C(50,3) enumeration; every physical deal gets 1 coherent ID."""
        hero="14s-13s"
        deck=[(rank,suit) for rank in range(2,15) for suit in "shdc"
              if (rank,suit) not in {(14,"s"),(13,"s")}]
        ids=Counter()
        for board in combinations(deck,3):
            physical="-".join(str(r)+s for r,s in board)
            result=classify_composite_flop(hero,physical)
            self.assertEqual(result["board"]["group_id"],
                             classify_flop_board(list(board))["group_id"])
            self.assertEqual(result["id"].split("|")[1],
                             result["board"]["group_id"])
            ids[result["id"]]+=1
        self.assertEqual(sum(ids.values()),19600)
        self.assertGreater(len(ids),46)

    def test_http_authorization_and_ui(self):
        with patch.object(app,"TOKEN","composite_key"):
            server=ThreadingHTTPServer(("127.0.0.1",0),app.Handler)
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            url=f"http://127.0.0.1:{server.server_address[1]}"
            def call(body,auth=True):
                headers={"Content-Type":"application/json"}
                if auth: headers["X-Runner-Key"]="composite_key"
                return urllib.request.urlopen(urllib.request.Request(
                    url+"/api/postflop/composite",data=json.dumps(body).encode(),
                    headers=headers),timeout=10)
            try:
                data={"hero":"9s-8s","board":"9d-7s-6s"}
                with self.assertRaises(urllib.error.HTTPError) as denied:
                    call(data,auth=False)
                self.assertEqual(denied.exception.code,401)
                with call(data) as response:
                    result=json.load(response)
                    self.assertEqual(result["id"],"F|N-C4-2S|TPFDOESD")
                with self.assertRaises(urllib.error.HTTPError) as bad:
                    call({"hero":"9s-8s","board":"9s-7s-6s"})
                self.assertEqual(bad.exception.code,400)
                html=(app.ROOT/"replit_ui/s100.html").read_text(encoding="utf-8")
                for marker in (
                    'id="compositeClassifier"','id="compositeHero"',
                    'id="compositeBoard"','id="classifyComposite"',
                    'id="compositeResult"','/api/postflop/composite',
                ):
                    self.assertIn(marker,html)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__=="__main__":
    unittest.main()
