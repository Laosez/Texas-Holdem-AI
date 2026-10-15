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

    def test_equity_outline_and_lightweight_opponent_summary(self):
        # Gold equity indicator survives redesign; costly pairwise comparison
        # matrices have been replaced with lightweight opponent summary cards.
        page = service.PLAN_UI.read_text(encoding="utf-8")
        self.assertIn(".hand.equityHit::after", page)
        self.assertIn("border:1px dashed #efbf55", page)
        self.assertIn("if(hasEq&&equity>=min)button.classList.add('equityHit')", page)
        self.assertNotIn("if(hasEq&&eq[h]<min)button.classList.add('dim')", page)
        self.assertNotIn('id="pairwiseMatrix"', page)
        self.assertNotIn("function calculatePairwise(", page)
        self.assertNotIn("function renderComparisonGrid(", page)
        self.assertIn("function assignedParticipation(", page)
        self.assertIn("function renderPerOpponent(", page)
        self.assertIn("const incomplete=undefinedHands!==null&&undefinedHands>0;", page)
        self.assertIn("if(incomplete)card.append(", page)
        self.assertIn("if(!item.doc)card.append(", page)

    def test_a17_in_matrix_with_corner_labels_and_action_bars(self):
        page = service.PLAN_UI.read_text(encoding="utf-8")
        section02 = page[page.index('02 / </span>Equity-фильтр'):page.index('03 / </span>Матрицы стартовых рук')]
        section03 = page[page.index('03 / </span>Матрицы стартовых рук'):page.index('04 / </span>Редактор выбранной руки')]
        self.assertNotIn('id="boxes"', section02)
        self.assertIn('id="boxes"', section03)
        self.assertIn('id="clearBoxes"', section03)
        self.assertIn('id="heroMatrix"', section03)
        self.assertEqual(page.count('id="boxes"'), 1)
        self.assertIn("function knownActivePercent(doc,hand)", page)
        self.assertIn("button.append(tag)", page)
        self.assertIn("const tag=el('span','handBoxTag'", page)
        self.assertIn("tag.setAttribute('aria-hidden','true')", page)
        self.assertIn("pair('Коробка A17'", page)
        self.assertIn(".handBoxTag{position:absolute;top:2px;right:3px;", page)
        self.assertNotIn(".hand.played{", page)
        self.assertNotIn("button.classList.add('played')", page)
        self.assertIn(".hand.boxhit::before", page)
        self.assertIn(".hand.equityHit::after", page)
        self.assertNotIn(".hand.boxhit{outline:2px solid #a7d8ff", page)

    def test_metric_gradient_and_action_stripe_are_independent(self):
        page = service.PLAN_UI.read_text(encoding="utf-8")
        self.assertNotIn(".hand.played{", page)
        self.assertNotIn(".boxHandChip.played{", page)
        self.assertNotIn("minPlayFrequency", page)
        self.assertIn("if(stripe)button.append(stripe)", page)
        self.assertIn(".hand.metricShade{background-image:linear-gradient(", page)
        self.assertNotIn("--play-alpha", page)
        self.assertIn("function metricGradient(metric,value,box,action)", page)
        self.assertIn("const colors=metric==='none'?null:metricGradient(metric,value,b,action)", page)
        self.assertIn("const participation=knownActivePercent(doc,h);", page)
        for name in ("equity","participation","dominant","box","combos","delta","evCall","action"):
            self.assertIn('value="'+name+'"', page)

    def test_all_in_call_ev_never_claims_to_be_full_action_ev(self):
        page = service.PLAN_UI.read_text(encoding="utf-8")
        self.assertIn("function modelCallEv(equityPct,potBB,callBB)", page)
        self.assertIn("return (equityPct/100)*(potBB+callBB)-callBB;", page)
        self.assertIn("value=doc===hero&&equity!==null?modelCallEv", page)
        self.assertIn("без побочных банков и будущих ставок", page)
        self.assertIn("EV сравнивается с Fold = 0", page)

    def test_multiway_all_in_ev_uses_actual_selected_equity(self):
        page = service.PLAN_UI.read_text(encoding="utf-8")
        self.assertIn('value="evAllIn"', page)
        self.assertIn('id="allInDead"', page)
        self.assertIn('id="allInStatus"', page)
        self.assertIn('function modelAllInEv(equityPct,stackBB,deadBB,opponentCount)',page)
        self.assertIn('const finalPot=(opponentCount+1)*stackBB+deadBB;',page)
        self.assertIn('return (equityPct/100)*finalPot-stackBB;',page)
        self.assertIn("const allInEquity=equityResults.actual?.equity||null;",page)
        self.assertIn("value=doc===hero&&Number.isFinite(actual)?modelAllInEv(actual,stack,dead,n):null;",page)
        self.assertIn("if(metric==='evAllIn'){",page)
        self.assertIn("if(allIn){",page)
        self.assertIn("$('allInDead').oninput=drawMatrices;",page)
        self.assertIn("noteDirty();drawMatrices()",page)
        self.assertIn("без побочных банков / fold equity / ICM",page)

    def test_a17_hand_lists_drag_to_pool_reorder_undo_and_save(self):
        page = service.PLAN_UI.read_text(encoding="utf-8")
        for css in (".boxHandList{",".boxHandChip{",".boxCard{",".boxPool{"):
            self.assertIn(css,page)
        for identifier in ("boxes","handBox","moveBox","undo"):
            self.assertIn('id="'+identifier+'"',page)
        self.assertIn("function boxChip(h)",page)
        self.assertIn("function reorderBox(from,to)",page)
        self.assertIn("function boxDropped(e,target)",page)
        self.assertIn("function markBoxDirty()",page)
        self.assertIn("'application/x-skachkov-hand'",page)
        self.assertIn("'application/x-skachkov-box'",page)
        self.assertIn("if(HANDS.includes(h))moveHandToBox(h,target)",page)
        self.assertIn("moveHandToBox(h,0)",page)
        self.assertIn("for(const b of [...boxOrder(),0])",page)
        self.assertIn("hero.box_order=order",page)
        self.assertIn("box_order:[...boxOrder()]",page)
        self.assertIn("hero.box_order=prev.box_order||boxOrder()",page)
        self.assertIn("label:'Без коробки'",page)
        self.assertNotIn("Последняя рука не может покинуть коробку",page)

    def test_group_equity_and_multi_cycle_ui(self):
        page=service.PLAN_UI.read_text(encoding="utf-8")
        self.assertIn('id="computeBoxes"',page)
        self.assertIn('id="cycles"',page)
        self.assertIn("const eq=boxEquityResult?.equity||null;",page)
        self.assertIn("const groupEq=members.length&&Number.isFinite(eq?.[String(b)])",page)
        self.assertIn("/api/plan/boxes-equity",page)
        self.assertIn("while(job.status==='running'||job.status==='queued')",page)
        self.assertIn("boxEquityEpoch++;boxEquityResult=null;",page)
        self.assertIn("cycles:Number($('cycles').value)",page)
        self.assertIn("Eq</strong> — реальное showdown equity диапазона всей коробки",page)
        self.assertNotIn("Доля комбинаций с equity выше порога';head.append(summary)",page)

    def test_gto_neutral_mode_and_detailed_hover(self):
        page=service.PLAN_UI.read_text(encoding="utf-8")
        self.assertIn('value="none">Нет · серый фон',page)
        self.assertIn(".hand.metricNeutral{background:#37404b",page)
        self.assertNotIn('id="minPlayFrequency"',page)
        self.assertNotIn('id="playMinLabel"',page)
        self.assertIn("Нижняя полоска каждой руки показывает доли Fold / Raise / Limp / Call",page)
        self.assertIn('id="handHoverCard"',page)
        self.assertIn("function handMetricsRows(hand,doc)",page)
        self.assertIn("function showHandHover(hand,doc,event)",page)
        self.assertIn("function hideHandHover()",page)
        self.assertIn("button.onmouseenter=e=>showHandHover(h,doc,e)",page)
        self.assertIn("pair('Equity · выбранные соперники'",page)
        self.assertIn("pair('Equity коробки · multiway'",page)
        self.assertIn("pair('EV выставления'",page)
        self.assertIn("handBoxTag",page)

    def test_hand_action_frequency_stripes_accurately_defined(self):
        page=service.PLAN_UI.read_text(encoding="utf-8")
        self.assertIn("function handActionStripe(actions)",page)
        self.assertIn("const stripe=handActionStripe(actions);",page)
        self.assertIn("if(stripe)button.append(stripe)",page)
        for css in (".actionStripe{",".actionStripe .fold{background:#8995a2}",
                    ".actionStripe .raise{background:#e36b6e}",
                    ".actionStripe .limp{background:#53b98b}",
                    ".actionStripe .call{background:#63b2cf}",
                    "class=\"actionLegend\""):
            self.assertIn(css,page)
        self.assertIn("['fold',Number(actions.fold)||0]",page)
        self.assertIn("['limp',Number(actions.limp)||0]",page)
        self.assertIn("['call',Number(actions.call)||0]",page)
        self.assertIn("['open','threebet','fourbet','push']",page)
        self.assertIn("segment.style.width=(100*value/total).toFixed(3)+'%'",page)

    def test_strategy_studio_dense_layout_and_group_brush_editor(self):
        page=service.PLAN_UI.read_text(encoding="utf-8")
        self.assertIn('class="plannerWorkspace"',page)
        self.assertIn('class="panel editorSection"',page)
        self.assertIn('id="groupDrawer"',page)
        self.assertIn('id="boxPalette"',page)
        self.assertIn('id="brushInspect"',page)
        self.assertIn('id="brushPaint"',page)
        self.assertIn('id="brushTarget"',page)
        self.assertIn('id="brushSelectGroup"',page)
        self.assertIn('id="brushApply"',page)
        self.assertIn('id="brushClear"',page)
        self.assertIn('id="brushSelectedCount"',page)
        self.assertIn('.matrixGrid{display:grid;grid-template-columns:repeat(13,minmax(0,1fr));gap:2px',page)
        self.assertIn('class="matrixRanks"',page)
        self.assertIn('class="matrixAxisLeft"',page)
        self.assertIn('function moveHandsToBox(hands,target)',page)
        self.assertIn('function paintOneBox(hand,element)',page)
        self.assertIn('function beginBoxStroke(hand,button,event)',page)
        self.assertIn('function finishBoxStroke()',page)
        self.assertIn('if(doc===hero&&bulkSelected.has(h))button.classList.add(\'multiSelected\')',page)
        self.assertIn('brushPainting&&(e.buttons&1)',page)
        self.assertIn("if(target&&$('heroMatrix').contains(target))paintOneBox(target.dataset.hand,target)",page)
        self.assertIn('snapshotUndo();',page)
        self.assertIn('markBoxDirty();',page)
        self.assertIn("expandedBoxes=new Set([0])",page)
        self.assertNotIn('Матрица equity стратегий · каждая с каждой',page)

    def test_group_palette_and_sidebar_retain_equity_and_hand_controls(self):
        page=service.PLAN_UI.read_text(encoding="utf-8")
        for label in ('id="heroMatrix"','id="villainMatrix"','id="handBox"',
                      'id="applyHand"','id="applyBoxes"','id="computeBoxes"',
                      'id="perOpponentHands"','id="compEquity"'):
            self.assertIn(label,page)
        self.assertIn('function drawBoxPalette()',page)
        self.assertIn('const eq=boxEquityResult?.equity||null;',page)
        self.assertIn('class="actionLegend"',page)
        self.assertIn("if(stripe)button.append(stripe)",page)
        self.assertIn(".handBoxTag{position:absolute;",page)


if __name__=="__main__":
    unittest.main()
