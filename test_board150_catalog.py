"""Board150 v1: exact reference, physical validation and Plan Monte Carlo attribution."""
from collections import Counter
from pathlib import Path
import json
import shutil
import subprocess
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
NEW_DOC=json.loads((Path(__file__).parent/"data"/"postflop_compact16_catalog.json").read_text(encoding="utf-8"))
NEW_ROWS=NEW_DOC["rows"]


class RiverBoard150Tests(unittest.TestCase):
    def test_exact_census_75_unique_codes_and_weights(self):
        self.assertEqual(DOC["version"],"river_board_75_v2")
        self.assertEqual(DOC["physical_boards"],2598960)
        self.assertEqual(DOC["theoretical_codes"],864)
        self.assertEqual(DOC["reachable_codes"],75)
        self.assertEqual(len(ROWS),75)
        self.assertEqual(len({x["id"] for x in ROWS}),75)
        self.assertEqual(sum(r["deals"] for r in ROWS),2598960)
        self.assertEqual([sum(r["p"]=="P"+str(p) for r in ROWS) for p in range(6)],
                         [41,20,6,6,1,1])
        self.assertEqual(len({x["example"] for x in ROWS}),75)
        for row in ROWS:
            self.assertEqual(classify_board(parse_physical_board(row["example"]))["legacy_id"],row["id"])
            self.assertGreater(row["deals"],0)
            self.assertAlmostEqual(row["probability_pct"],100*row["deals"]/2598960,places=6)

    def test_all_physical_example_and_wheel(self):
        cards=parse_physical_board("5s-6s-7s-8s-8d")
        self.assertEqual(classify_board(cards)["id"],"S4 · F4 · SF4 · P1")
        board=next(r for r in ROWS if r["id"]=="P1 · S3 · F4 · SF3")
        self.assertEqual(board["deals"],528)
        self.assertEqual(classify_request({"board":"As-2d-3c-4h-5s"})["id"],
                         "S5 · F2")
        # Exactly same spelling accepted by the new Sheet 03 input.
        self.assertEqual(parse_physical_board("14s-13h-9c-5d-2c"),
                         parse_physical_board("As-Kh-9c-5d-2c"))

    def test_street_prefix_prevents_virtual_river(self):
        dealt=parse_physical_board("As-Ah-7s-8s-9s")
        self.assertEqual(classify_board(dealt[:3])["street"],"flop")
        self.assertTrue(classify_board(dealt[:3])["id"].startswith("FLOP|S"))
        self.assertTrue(classify_board(dealt[:4])["id"].startswith("TURN|"))
        self.assertTrue(classify_board(dealt)["id"].startswith("S"))
        self.assertEqual(classify_board([])["id"],"PRE|NO_BOARD")
        for value in ("As-As-3d-4c-5h","As-Qz-3d-4c-5h","As-2d-3c"):
            with self.assertRaises(ValueError):parse_physical_board(value,streets=(5,))

    def test_river_unique_id_for_uniform_random_physical_sample(self):
        universe={x["id"] for x in NEW_ROWS}
        rng=random.Random(42)
        for _ in range(3000):
            board=rng.sample(range(52),5)
            self.assertIn(classify_board(board)["id"],universe)

    def test_ev_reconciliation_in_live_single_and_paired_simulations(self):
        base={"model":"selected","hand":"K4s","trials":50,"cycles":1,
              "hero_postflop":"gto20","hero_position":"3","hero_stack_bb":20,
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
            self.assertTrue(all(r["outcome_code"] in
                                {"W1","L1","W2","L2","W3","L3","T1","X1"}
                                for r in data["rows"]))
            self.assertTrue(all(0 <= r["showdown_opponents"] <= 1
                                for r in data["rows"]))
            self.assertTrue(all((r["villain_category"] is None) ==
                                (r["showdown_opponents"] == 0)
                                for r in data["rows"]))
            self.assertTrue(all("board_code" in r for r in data["rows"]))
            self.assertTrue(all(r["board_code"].startswith(("PRE|","FLOP|","TURN|","S"))
                                for r in data["rows"]))

    def test_postflop_page_new_route_and_no_visible_old_catalog(self):
        page=(app.ROOT/"replit_ui/river_board.html").read_text(encoding="utf-8")
        server=(app.ROOT/"replit_simulator.py").read_text(encoding="utf-8")
        plan=(app.ROOT/"replit_ui/plan.html").read_text(encoding="utf-8")
        for x in ("id=\"board150Catalog\"","/api/postflop/board16-catalog",
                  "/api/postflop/board16-classify",
                  "const boardTitle=row=>", "boardName", "Название борда",
                  "function drawCatalog(){"):
            self.assertIn(x,page)
        for forbidden in ("id=\"board150Report\"","id=\"viewFinancial\"",
                          "function reportTree(){","function drawReport(){",
                          "skachkov_board150_report_v1","reportSummary"):
            self.assertNotIn(forbidden,page)
        self.assertIn('"river_board.html") if path == "/s100"',server)
        self.assertNotIn('1 019',page)
        self.assertIn('<option value="board150" selected>Плоский регистр · Борд / HERO / Оппонент / Исход',plan)
        self.assertIn('<option value="catalog" hidden>',plan)
        self.assertIn('↗ Справочник 49 типов',plan)
        self.assertNotIn('↗ Отчёт на листе 03 · Постфлоп',plan)
        self.assertIn('function riverBoardDescription(code){',plan)
        self.assertIn('function board150Parts(code){',plan)
        self.assertIn('record.board_code||record.board_id',plan)
        self.assertIn('renderRiverLedger(root,a,b,compare)',plan)

    def test_flat_bdr_is_sortable_and_uses_shared_showdown_selector(self):
        page=app.PLAN_UI.read_text(encoding="utf-8")
        required=(
            "function renderFlatBoard150(root,a,b,compare){",
            "id=\"handDecompOpponentHint\"",
            "flatMode?'all':selection",
            "if(showdownChoice!=='all'&&row.dims[4]!==Number(showdownChoice))continue;",
            "opponentPicker.setAttribute('aria-label',flatMode?",
            "flatBdrGroup abValueA",
            "flatBdrGroup abValueB",
            "flatBdrGroup abDelta",
            "Σ Net BB",
            "ИТОГО · ВЫБРАННЫЕ СЦЕНАРИИ",
            "record.net+=r.contribution_bb*totals[side]",
            "record.n?flatBdrFormat(record.net/record.n,3)",
            "if(flatReportSort===col.key)",
            "const grouped=flatAggregateVisible(eligible,showdownChoice)",
        )
        for keyword in required:
            with self.subTest(keyword=keyword):
                self.assertIn(keyword,page)
        self.assertNotIn("['opps','Опп. на вскрытии',4]",page)

    def test_board16_filters_and_labels(self):
        page=app.PLAN_UI.read_text(encoding="utf-8")
        for needle in (
            "const FLAT_BOARD_FACETS=[",
            "values:['P1','P2','P3','P3-2','P4']",
            "values:['S1','S2','S3','S4','S5']",
            "values:['F2','F3','F4','F5']",
            "values:['SF4','SF5']",
            "const FLAT_BOARD_FACET_LABELS={",
            "flatBoardFacetsMatch(r.dims[1])",
            "function flatAggregateVisible(rows,showdownChoice='all')",
            "function refreshDerivedBoards(){",
            "flatVisibleHeroCategories.has(r.dims[2])",
            "flatVisibleVillainCategories.has(r.dims[3])",
            "const boardFacetWrap=el('div','flatBdrFacetGroup')",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle,page)

    def test_board16_filter_runtime_and_showdown_rollup(self):
        if not shutil.which("node"):
            self.skipTest("Node.js unavailable")
        page=app.PLAN_UI.read_text(encoding="utf-8")
        part=page.split("const FLAT_BOARD_FACETS=[",1)[1].split(
            "/* End pure Board150 filter and aggregation helpers. */",1)[0]
        part=part.replace("const flatBoardParts=", "const flatBoardParts=")
        # New parser is declared earlier in Plan, so preload its source.
        begin=page.split("function board150Parts(code){",1)[1].split("function riverPass(row){",1)[0]
        js="function board150Parts(code){"+begin+"\nconst FLAT_BOARD_FACETS=["+part+'''
const assert=(v,msg)=>{if(!v)throw Error(msg)};
const board='S4 · F2 · P1';
assert(flatBoardFacetsMatch(board),'all facets');
assert(flatBoardFacetsMatch('PRE|NO_BOARD'),'preflop visible with all facets');
flatBoardFacets.P.clear();flatBoardFacets.P.add('P1');
flatBoardFacets.S.clear();flatBoardFacets.S.add('S4');
assert(flatBoardFacetsMatch(board),'selected class');
assert(!flatBoardFacetsMatch('S3 · F2 · P1'),'S3 excluded');
assert(!flatBoardFacetsMatch('S4 · F2 · P2'),'P2 excluded');
assert(!flatBoardFacetsMatch('PRE|NO_BOARD'),'preflop excluded under filtering');
flatBoardFacets.F.clear();flatBoardFacets.F.add('F3');
assert(!flatBoardFacetsMatch(board),'F2 excluded');
assert(flatBoardFacetsMatch('S4 · F3 · P1'),'F3 included');
const d=['river',board,2,2,1,'L3'];
const make=(n,net,opps)=>({dims:[d[0],d[1],d[2],d[3],opps,d[5]],
 a:{n,net},b:{n,net:net/2}});
const rows=[make(6,-420,1),make(5,-340,2)];
const merged=flatAggregateVisible(rows,'all');
assert(merged.length===1,'one row');
assert(merged[0].a.n===11,'sum n');
assert(merged[0].a.net===-760,'sum bb');
assert(flatAggregateVisible(rows,'1')[0].a.n===6,'opponent selection');
'''
        run=subprocess.run(["node","-e",js],capture_output=True,text=True,timeout=15)
        self.assertEqual(run.returncode,0,run.stderr)

    def test_flat_ev_graph_uses_sample_weighted_net_and_original_chart_preserved(self):
        page=app.PLAN_UI.read_text(encoding="utf-8")
        for needle in (
            "function renderFlatShowdownEvChart(rows,compare,selection)",
            "renderFlatShowdownEvChart(chartRows,compare,showdownChoice)",
            "totals[side].n+=row[side].n",
            "totals[side].net+=row[side].net",
            "d[side].net/d[side].n",
            "0 = без вскрытия",
            "EV, BB",
            "case 'avgA':return x.n?x.net/x.n:0",
            "case 'avgB':return y.n?y.net/y.n:0",
            "renderOpponentEvComparison(fullA,fullB)",
            "Оппонентов на вскрытии",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle,page)

    def test_new_composite_ids_are_unique_and_cover_all_physical_boards(self):
        self.assertEqual(NEW_DOC["version"],"board16_v1")
        self.assertEqual(NEW_DOC["reachable_codes"],49)
        self.assertEqual(len(NEW_ROWS),49)
        self.assertEqual(len({r["id"] for r in NEW_ROWS}),49)
        self.assertEqual(sum(r["deals"] for r in NEW_ROWS),2598960)
        for row in NEW_ROWS:
            info=classify_board(parse_physical_board(row["example"]))
            self.assertEqual(info["id"],row["id"])

    def test_flat_report_outcome_multiselect_minimum_n_and_hidden_showdown_column(self):
        page=app.PLAN_UI.read_text(encoding="utf-8")
        required=[
            "const FLAT_ALL_OUTCOMES=['W1','L1','W2','L2','W3','L3','T1','X1']",
            "const flatVisibleOutcomes=new Set(FLAT_ALL_OUTCOMES)",
            "for(const n of [0,10,20,50,100,200,500,1000,2000])",
            "flatVisibleOutcomes.has(r.dims[5])",
            "(compare?Math.max(r.a.n,r.b.n):r.a.n)>=flatMinN",
            "if(showdownChoice!=='all'&&row.dims[4]!==Number(showdownChoice))continue;",
            "for(const i of [0,1,2,3,5])",
            "dims.colSpan=5",
            "title.colSpan=5",
            "root.classList.toggle('flatReportHost',decompReportMode==='board150')",
            "flatBoardDisplayCode(r.dims[i])",
        ]
        for needle in required:
            with self.subTest(needle=needle):
                self.assertIn(needle,page)
        self.assertNotIn("{key:'showdown',label:'Опп. на вскрытии',dimension:4}",page)
        self.assertNotIn("['Тип исхода',5]",page)
        self.assertIn("const compactBoardCode=code=>",(app.ROOT/"replit_ui/river_board.html").read_text(encoding="utf-8"))
        self.assertIn("row.id,compactBoardCode(row.id)",(app.ROOT/"replit_ui/river_board.html").read_text(encoding="utf-8"))

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
                self.assertEqual(fetched["reachable_codes"],49)
                self.assertEqual(fetched["rows"][0]["id"],NEW_ROWS[0]["id"])
                url2=f"http://127.0.0.1:{server.server_address[1]}/api/postflop/board150-classify"
                req2=urllib.request.Request(url2,data=json.dumps({"board":"5s-6s-7s-8s-8d"}).encode(),
                    headers={"X-Runner-Key":"board150_key","Content-Type":"application/json"},method="POST")
                with urllib.request.urlopen(req2,timeout=15) as response:
                    out=json.load(response)
                self.assertEqual(out["id"],"S4 · F4 · SF4 · P1")
            finally:
                server.shutdown();server.server_close();thread.join(timeout=3)


if __name__=="__main__":
    unittest.main()
