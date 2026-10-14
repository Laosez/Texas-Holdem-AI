"""Screen 2 HTTP integration: real auth, catalog, plan page, save and compare."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import planner_core as core
import planner_api
import replit_simulator as service


class PlanHttpTests(unittest.TestCase):
    def test_end_to_end_plan_http_with_auth(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.object(core,"STORE",Path(td)/"plans"), \
                 patch.object(service,"OUT",Path(td)), \
                 patch.object(service,"TOKEN","test_plan_secret"):
                server=ThreadingHTTPServer(("127.0.0.1",0),service.Handler)
                thread=threading.Thread(target=server.serve_forever,daemon=True)
                thread.start()
                base=f"http://127.0.0.1:{server.server_address[1]}"
                def request(path,payload=None,method=None,auth=True):
                    headers={"X-Runner-Key":"test_plan_secret"} if auth else {}
                    if payload is not None:
                        headers["Content-Type"]="application/json"
                    req=urllib.request.Request(base+path,headers=headers,
                                               data=json.dumps(payload).encode() if payload is not None else None,
                                               method=method)
                    with urllib.request.urlopen(req,timeout=15) as response:
                        return response.status,response.read()
                try:
                    status,html=request("/plan",auth=False)
                    self.assertEqual(status,200)
                    self.assertIn(b"id=\"heroMatrix\"",html)
                    self.assertIn(b"id=\"opponents\"",html)
                    with self.assertRaises(urllib.error.HTTPError) as unauthorized:
                        request("/api/plan/catalog",auth=False)
                    self.assertEqual(unauthorized.exception.code,401)
                    code,body=request("/api/plan/catalog")
                    catalog=json.loads(body)
                    self.assertEqual(code,200)
                    self.assertEqual(catalog["max_opponents"],5)
                    self.assertEqual(len(catalog["hands"]),169)
                    code,body=request("/api/plan/source?profile=builtin%3Aa17_v5&position=3&scenario=rfi&players=9")
                    own=json.loads(body)
                    self.assertEqual(own["boxes"]["JTo"],14)
                    own["name"]="HTTP test strategy"
                    code,body=request("/api/plan/strategies",{"plan":own},method="POST")
                    self.assertEqual(code,201)
                    saved=json.loads(body)
                    self.assertEqual(saved["version"],1)
                    code,body=request("/api/plan/source?profile="+urllib.parse.quote(saved["ref"]))
                    self.assertEqual(json.loads(body)["name"],"HTTP test strategy")
                    code,body=request("/api/plan/compare",{"hero":own,"villain":saved},method="POST")
                    self.assertEqual(code,200)
                    self.assertEqual(json.loads(body)["overlap_pct"],100)
                    code,body=request("/api/plan/strategies/"+saved["id"],method="DELETE")
                    self.assertEqual(code,200)
                    self.assertEqual(json.loads(body)["deleted"],saved["id"])
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)

    def test_equity_outline_and_opponent_matrix_regressions(self):
        # UI contract: the equity threshold uses a gold outline rather than dimming;
        # comparison matrices must distinguish unassigned data from explicit Fold.
        page = service.PLAN_UI.read_text(encoding="utf-8")
        self.assertIn(".hand.equityHit::after", page)
        self.assertIn("border:2px dashed #efbf55", page)
        self.assertIn("if(hit)button.classList.add('equityHit')", page)
        self.assertNotIn("if(hasEq&&eq[h]<min)button.classList.add('dim')", page)
        self.assertIn("function renderComparisonGrid(", page)
        self.assertIn("function assignedParticipation(", page)
        self.assertIn("function renderPerOpponent(", page)
        self.assertIn("const incomplete=undefinedHands!==null&&undefinedHands>0;", page)
        self.assertIn("if(incomplete)card.append(", page)
        self.assertIn("cell.onclick=()=>{selected=h;drawMatrices();paintEditor()}", page)

    def test_a17_moved_to_matrix_and_played_hand_encoding(self):
        page = service.PLAN_UI.read_text(encoding="utf-8")
        section02 = page[page.index('02 / </span>Equity-фильтр'):page.index('03 / </span>Матрицы стартовых рук')]
        section03 = page[page.index('03 / </span>Матрицы стартовых рук'):page.index('04 / </span>Сравнение стратегий')]
        self.assertNotIn('id="boxes"', section02)
        self.assertIn('id="boxes"', section03)
        self.assertIn('id="clearBoxes"', section03)
        self.assertIn('id="heroMatrix"', section03)
        self.assertEqual(page.count('id="boxes"'), 1)
        self.assertIn("function knownActivePercent(doc,hand)", page)
        self.assertIn("button.classList.add('played')", page)
        self.assertIn("button.append(tag)", page)
        self.assertIn("const tag=el('span','handBoxTag'", page)
        self.assertIn(".hand.played{border:2px solid #70b7ff", page)
        # Action background shorthands must not erase the played-range gradient.
        self.assertGreater(page.index(".hand.played{"), page.index(".hand.push{background:"))
        self.assertIn(".hand.boxhit::before", page)
        self.assertIn(".hand.equityHit::after", page)
        self.assertNotIn(".hand.boxhit{outline:2px solid #a7d8ff", page)


if __name__=="__main__":
    unittest.main()
