"""Board150 v1: exact reference, physical validation and Plan Monte Carlo attribution."""
from collections import Counter
from pathlib import Path
import json
import random
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
import threading
import urllib.request

from postflop_board150 import classify_board,parse_physical_board,classify_request
import planner_postflop_ev as engine
import replit_simulator as app


DOC=json.loads((Path(__file__).parent/"data"/"postflop_board150_catalog.json").read_text(encoding="utf-8"))
ROWS=DOC["rows"]


class RiverBoard150Tests(unittest.TestCase):
    def test_exact_census_150_unique_codes_and_weights(self):
        self.assertEqual(DOC["version"],"river_board_150_v1")
        self.assertEqual(DOC["physical_boards"],2598960)
        self.assertEqual(DOC["theoretical_codes"],1728)
        self.assertEqual(DOC["reachable_codes"],150)
        self.assertEqual(len(ROWS),150)
        self.assertEqual(len({x["id"] for x in ROWS}),150)
        self.assertEqual(sum(r["deals"] for r in ROWS),2598960)
        self.assertEqual([sum(r["p"]=="P"+str(p) for r in ROWS) for p in range(6)],
                         [82,40,12,12,2,2])
        self.assertEqual(len({x["example"] for x in ROWS}),150)
        for row in ROWS:
            self.assertEqual(classify_board(parse_physical_board(row["example"]))["id"],row["id"])
            self.assertGreater(row["deals"],0)
            self.assertAlmostEqual(row["probability_pct"],100*row["deals"]/2598960,places=6)

    def test_all_physical_example_and_wheel(self):
        cards=parse_physical_board("5s-6s-7s-8s-8d")
        self.assertEqual(classify_board(cards)["id"],"P1 · S3 · F4 · SF3 · A0")
        board=next(r for r in ROWS if r["id"]=="P1 · S3 · F4 · SF3 · A0")
        self.assertEqual(board["deals"],432)
        self.assertEqual(classify_request({"board":"As-2d-3c-4h-5s"})["id"],
                         "P0 · S5 · F2 · SF0 · A1")
        # Exactly same spelling accepted by the new Sheet 03 input.
        self.assertEqual(parse_physical_board("14s-13h-9c-5d-2c"),
                         parse_physical_board("As-Kh-9c-5d-2c"))

    def test_street_prefix_prevents_virtual_river(self):
        dealt=parse_physical_board("As-Ah-7s-8s-9s")
        self.assertEqual(classify_board(dealt[:3])["street"],"flop")
        self.assertTrue(classify_board(dealt[:3])["id"].startswith("FLOP|P1"))
        self.assertTrue(classify_board(dealt[:4])["id"].startswith("TURN|"))
        self.assertTrue(classify_board(dealt)["id"].startswith("P1 ·"))
        self.assertEqual(classify_board([])["id"],"PRE|NO_BOARD")
        for value in ("As-As-3d-4c-5h","As-Qz-3d-4c-5h","As-2d-3c"):
            with self.assertRaises(ValueError):parse_physical_board(value,streets=(5,))

    def test_river_unique_id_for_uniform_random_physical_sample(self):
        universe={x["id"] for x in ROWS}
        rng=random.Random(42)
        for _ in range(3000):
            board=rng.sample(range(52),5)
            self.assertIn(classify_board(board)["id"],universe)

    def test_ev_reconciliation_in_live_single_and_paired_simulations(self):
        base={"model":"selected","hand":"K4s","trials":50,"cycles":1,
              "hero_postflop":"gto2","hero_position":"3","hero_stack_bb":20,
              "opponents":[{"profile":"builtin:any_two","position":"9",
                "scenario":"rfi","players":9,"selector":"active",
                "entry_mode":"always","entry_pct":100,"postflop":"lag"}]}
        result=engine.calculate(base)
        reports=[result["decomposition"]]
        paired=engine.calculate_paired({**base,"hero_postflop_b":"tag"},workers=1)
        reports +=[paired["a"]["decomposition"],paired["b"]["decomposition"]]
        for report in reports:
            data=report["river_attribution"]
            self.assertEqual(data["samples"],50)
            self.assertTrue(data["reconciled"])
            self.assertEqual(sum(row["count"] for row in data["rows"]),50)
            self.assertAlmostEqual(sum(row["contribution_bb"] for row in data["rows"]),
                                   report["ev_bb"],delta=.004)
            self.assertTrue(all("board_code" in r for r in data["rows"]))
            self.assertTrue(all(r["board_code"].startswith(("PRE|","FLOP|","TURN|","P"))
                                for r in data["rows"]))

    def test_postflop_page_new_route_and_no_visible_old_catalog(self):
        page=(app.ROOT/"replit_ui/river_board.html").read_text(encoding="utf-8")
        server=(app.ROOT/"replit_simulator.py").read_text(encoding="utf-8")
        plan=(app.ROOT/"replit_ui/plan.html").read_text(encoding="utf-8")
        for x in ("id=\"board150Catalog\"","id=\"board150Report\"",
                  "skachkov_board150_report_v1","/api/postflop/board150-catalog",
                  "/api/postflop/board150-classify",
                  "function reportTree(){","function drawReport(){"):
            self.assertIn(x,page)
        self.assertIn('"river_board.html") if path == "/s100"',server)
        self.assertNotIn('1 019',page)
        self.assertIn('<option value="board150">Справочник 150',plan)
        self.assertIn('<option value="catalog" hidden>',plan)
        self.assertIn('↗ Отчёт на листе 03 · Постфлоп',plan)
        self.assertIn('record.board_code||record.board_id',plan)
        self.assertIn('renderRiverLedger(root,a,b,compare)',plan)

    def test_authenticated_catalog_and_classify_api(self):
        with patch.object(app,"TOKEN","board150_key"):
            server=ThreadingHTTPServer(("127.0.0.1",0),app.Handler)
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            try:
                url=f"http://127.0.0.1:{server.server_address[1]}/api/postflop/board150-catalog"
                req=urllib.request.Request(url,headers={"X-Runner-Key":"board150_key"})
                with urllib.request.urlopen(req,timeout=15) as response:
                    fetched=json.load(response)
                self.assertEqual(fetched["reachable_codes"],150)
                self.assertEqual(fetched["rows"][0]["id"],ROWS[0]["id"])
                url2=f"http://127.0.0.1:{server.server_address[1]}/api/postflop/board150-classify"
                req2=urllib.request.Request(url2,data=json.dumps({"board":"5s-6s-7s-8s-8d"}).encode(),
                    headers={"X-Runner-Key":"board150_key","Content-Type":"application/json"},method="POST")
                with urllib.request.urlopen(req2,timeout=15) as response:
                    out=json.load(response)
                self.assertEqual(out["id"],"P1 · S3 · F4 · SF3 · A0")
            finally:
                server.shutdown();server.server_close();thread.join(timeout=3)


if __name__=="__main__":
    unittest.main()
