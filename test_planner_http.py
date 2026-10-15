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
                    self.assertFalse((core.STORE/saved["id"]).exists())
                    trash=list((core.STORE/".trash").glob(saved["id"]+"_*"))
                    self.assertEqual(len(trash),1)
                    self.assertTrue((trash[0]/"v00001.json").is_file())
                    _,fresh=request("/api/plan/catalog")
                    self.assertFalse(any(item["id"]==saved["id"] for item in json.loads(fresh)["saved"]))
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)

    def test_equity_outline_and_lightweight_opponent_summary(self):
        page = service.PLAN_UI.read_text(encoding="utf-8")
        self.assertIn("function candidateSwaps(metric)",page)
        self.assertIn("candidateGold",page)
        self.assertIn("candidateRed",page)
        self.assertIn("if(excluded[i].value<=selectedHands[i].value+1e-7)break",page)
        self.assertIn("if(participation===null)continue",page)
        self.assertNotIn('id="equityMin"',page)
        self.assertNotIn('id="perOpponentComparison"',page)
        self.assertNotIn('Сводка диапазонов',page)
        self.assertNotIn("function renderComparisonGrid(",page)
        self.assertIn("function renderPerOpponent()",page)
        self.assertIn("hands.replaceChildren();",page)


    def test_a17_in_matrix_with_corner_labels_and_action_bars(self):
        page = service.PLAN_UI.read_text(encoding="utf-8")
        section03 = page[page.index('03 / </span>Матрицы стартовых рук'):page.index('04 / </span>Редактор выбранной руки')]
        self.assertIn('id="boxes"',section03)
        self.assertIn('id="groupEditor"',section03)
        self.assertIn('id="groupDrawer"',section03)
        self.assertIn('id="heroMatrix"',section03)
        self.assertIn('id="brushTarget"',section03)
        self.assertEqual(page.count('id="boxes"'),1)
        self.assertIn("button.append(el('span','handRank',h))",page)
        self.assertIn("button.append(el('span','handBoxTag'",page)
        self.assertIn(".matrixPane .handRank{position:absolute;top:2px;left:3px",page)
        self.assertIn(".matrixPane .handBoxTag{position:absolute;top:2px;right:3px",page)
        self.assertIn("const stripe=handActionStripe(actions)",page)
        self.assertIn(".hand.boxhit::before",page)
        self.assertNotIn(".hand.equityHit::after",page)


    def test_metric_gradient_and_action_stripe_are_independent(self):
        page = service.PLAN_UI.read_text(encoding="utf-8")
        self.assertIn(".hand.none,.hand.fold,.hand.open,.hand.limp,.hand.call,.hand.threebet,.hand.fourbet,.hand.push{background:#303b49}",page)
        self.assertIn(".matrixPane .hand{background:#303b49!important;background-image:none!important",page)
        self.assertIn("const center=el('span','handMetric'",page)
        self.assertNotIn("function metricGradient(",page)
        self.assertNotIn("const colors=metricGradient(",page)
        self.assertNotIn('id="equityMin"',page)
        self.assertIn("if(stripe)button.append(stripe)",page)
        for name in ("equity","participation","dominant","box","combos","delta","evCall","evAllIn","action"):
            self.assertIn('value="'+name+'"',page)


    def test_all_in_call_ev_never_claims_to_be_full_action_ev(self):
        page = service.PLAN_UI.read_text(encoding="utf-8")
        self.assertIn("function modelCallEv(equityPct,potBB,callBB)",page)
        self.assertIn("return (equityPct/100)*(potBB+callBB)-callBB;",page)
        self.assertIn("modelCallEv(filtered,Number($('evPot').value),Number($('evCost').value))",page)
        self.assertIn("без побочных банков и будущих ставок",page)
        self.assertIn("EV сравнивается с Fold = 0",page)


    def test_multiway_all_in_ev_uses_actual_selected_equity(self):
        page = service.PLAN_UI.read_text(encoding="utf-8")
        self.assertIn('value="evAllIn"',page)
        self.assertIn('id="allInDead"',page)
        self.assertIn('function modelAllInEv(equityPct,stackBB,deadBB,opponentCount)',page)
        self.assertIn('const finalPot=(opponentCount+1)*stackBB+deadBB;',page)
        self.assertIn('return (equityPct/100)*finalPot-stackBB;',page)
        self.assertIn("equityResults.actual?.equity?.[h]",page)
        self.assertIn("modelAllInEv(actual,Number($('stack').value),Number($('allInDead').value),currentPeople().length)",page)
        self.assertIn("if(metric==='evAllIn'){",page)
        self.assertIn("$('allInDead').oninput=drawMatrices;",page)


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
        page = service.PLAN_UI.read_text(encoding="utf-8")
        self.assertIn('id="cycles"',page)
        self.assertIn("function groupWeightedEquity(b)",page)
        self.assertIn("equityResults.actual?.equity||",page)
        self.assertIn("if(!Number.isFinite(eq[h]))return null;",page)
        self.assertIn("const w=COMBOS(h);mass+=w;total+=w*eq[h]",page)
        self.assertIn("return mass?total/mass:null;",page)
        self.assertIn("const groupEq=groupWeightedEquity(b);",page)
        self.assertIn("const groupEq=groupWeightedEquity(box);",page)
        self.assertNotIn('id="computeBoxes"',page)
        self.assertNotIn("async function calculateBoxesEquity()",page)
        self.assertNotIn("await calculateBoxesEquity()",page)
        self.assertIn("cycles:Number($('cycles').value)",page)


    def test_gto_neutral_mode_and_detailed_hover(self):
        page = service.PLAN_UI.read_text(encoding="utf-8")
        self.assertIn('value="none">Нет · серый фон',page)
        self.assertIn(".hand.metricNeutral{background:#303b49",page)
        self.assertNotIn('id="minPlayFrequency"',page)
        self.assertNotIn('id="playMinLabel"',page)
        self.assertIn("function handMetricsRows(hand,doc)",page)
        self.assertIn("function showHandHover(hand,doc,event)",page)
        self.assertIn("function hideHandHover()",page)
        self.assertIn("button.onmouseenter=e=>showHandHover(h,doc,e)",page)
        self.assertIn("pair('Equity · выбранные соперники'",page)
        self.assertIn("pair('Equity A17 · взвешенное'",page)
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
        self.assertNotIn('id="boxPalette"',page)
        self.assertIn('class="a17Workbench unifiedGroupEditor"',page)
        self.assertIn('id="groupDrawer" class="groupDrawer unifiedGroupList"',page)
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
        self.assertIn('id="groupEditor" class="groupDrawer groupEditor"',page)
        self.assertIn('id="groupDrawer" class="groupDrawer unifiedGroupList"',page)
        self.assertNotIn("expandedBoxes",page)
        self.assertNotIn('id="expandAllBoxes"',page)
        self.assertNotIn('id="collapseAllBoxes"',page)
        self.assertNotIn("const exp=el('button','boxExpand'",page)
        self.assertNotIn('Матрица equity стратегий · каждая с каждой',page)

    def test_group_palette_and_sidebar_retain_equity_and_hand_controls(self):
        page = service.PLAN_UI.read_text(encoding="utf-8")
        for label in ('id="heroMatrix"','id="villainMatrix"','id="handBox"',
                      'id="actionInputs"','id="selectionInfo"','id="boxes"',
                      'id="perOpponentHands"','id="groupEditor"'):
            self.assertIn(label,page)
        self.assertNotIn('function drawBoxPalette()',page)
        self.assertIn('function drawBoxes()',page)
        self.assertIn('brushTarget=b;',page)
        self.assertIn('function groupWeightedEquity(b)',page)
        self.assertIn('class="actionLegend"',page)
        self.assertIn("if(stripe)button.append(stripe)",page)
        self.assertIn(".handBoxTag{position:absolute;",page)


    def test_numeric_metric_labels_use_visible_min_max_scale(self):
        page=service.PLAN_UI.read_text(encoding="utf-8")
        self.assertIn("function visibleMetricScale(metric,docs)",page)
        self.assertIn("function metricTextColor(metric,value,scale)",page)
        self.assertIn("Math.min(...values),max:Math.max(...values)",page)
        self.assertIn("const scale=visibleMetricScale($('cellMetric').value,showOpponent?[hero,villain]:[hero])",page)
        self.assertIn("if(color)center.style.color=color;",page)
        self.assertIn("Math.abs(value)<0.000001)return '#d7e1ee'",page)
        self.assertIn("const hue=value<0?3:159;",page)
        self.assertIn(".matrixPane .hand{background:#303b49!important;background-image:none!important",page)

    def test_live_action_sliders_and_multiselection_contract(self):
        page=service.PLAN_UI.read_text(encoding="utf-8")
        for label in ('id="handSelectionMode"','id="selectionInfo"','id="selectionCount"',
                      'id="selectedHandChips"','id="clearHandSelection"',
                      'id="actionStatus"','id="resetHand"'):
            self.assertIn(label,page)
        self.assertNotIn('id="applyHand"',page)
        self.assertNotIn('id="applyBoxes"',page)
        self.assertNotIn("function doApply(",page)
        self.assertIn("function editorActions(scenario)",page)
        self.assertIn("if(scenario==='rfi')return ['fold','open','limp'];",page)
        self.assertIn("if(scenario==='vs_open')return ['fold','threebet','call'];",page)
        self.assertIn("function rebalanceEditorSplit(current,changed,requested,keys)",page)
        self.assertIn("input.type='range';input.min='0';input.max='100';input.step='25';",page)
        self.assertIn("input.oninput=()=>applySliderInput(key,input);",page)
        self.assertIn("function editorTargets(){return bulkSelected.size?",page)
        self.assertIn("const targets=editorTargets();",page)
        self.assertIn("for(const h of targets)hero.hands[h]={...actions};",page)
        self.assertIn("if(!sliderGesture){",page)
        self.assertIn("snapshotUndo();sliderGesture=true;",page)
        self.assertIn("button.onclick=e=>{",page)
        self.assertIn("if(!bulkSelected.size){",page)
        self.assertIn("if(h!==selected)bulkSelected.add(h);",page)
        self.assertIn("drawMatrices();paintEditor();return;",page)
        self.assertIn("function updateSelectionDisplay()",page)
        self.assertIn("function renderSliderNumbers(values)",page)
        self.assertIn("$('clearHandSelection').onclick=",page)

    def test_single_outer_group_disclosure_and_trash_deletion(self):
        page=service.PLAN_UI.read_text(encoding="utf-8")
        self.assertIn('<details id="groupEditor"',page)
        self.assertIn('id="groupDrawer" class="groupDrawer unifiedGroupList"',page)
        self.assertNotIn('id="expandAllBoxes"',page)
        self.assertNotIn('id="collapseAllBoxes"',page)
        self.assertNotIn("const exp=el('button','boxExpand'",page)
        self.assertIn("const list=el('div','boxHandList');",page)
        self.assertIn("if(members.length)for(const h of members)list.append(boxChip(h));",page)
        self.assertIn("const id=hero.id,displayName=hero.name;",page)
        self.assertIn("if(result.deleted!==id)throw Error(",page)
        self.assertIn("hero=null;dirty=false;undos=[];bulkSelected.clear();",page)
        self.assertIn("await loadHero();",page)

    def test_vertical_equal_matrices_default_and_collapsible_opponent(self):
        page=service.PLAN_UI.read_text(encoding="utf-8")
        self.assertIn('<details id="villainPane" class="matrixPane comparisonDisclosure" open>',page)
        self.assertIn('<summary><span>02 · Соперник</span>',page)
        self.assertIn("const showOpponent=$('villainPane').open;",page)
        self.assertIn("if(showOpponent)matrix($('villainMatrix'),villain,scale);",page)
        self.assertIn("else $('villainMatrix').replaceChildren();",page)
        self.assertIn("$('villainPane').ontoggle=()=>{if(hero)drawMatrices()};",page)
        self.assertIn('.matrixLayout{display:flex;flex-direction:column;gap:10px}',page)
        self.assertIn('.matrixLayout>.matrixPane{width:100%;min-width:0;box-sizing:border-box}',page)
        self.assertNotIn('id="matrixMode"',page)
        self.assertNotIn(".matrixLayout.double .hand{",page)

    def test_a17_brush_and_groups_are_one_panel(self):
        page=service.PLAN_UI.read_text(encoding="utf-8")
        self.assertEqual(page.count('id="groupEditor"'),1)
        self.assertEqual(page.count('id="boxes"'),1)
        self.assertNotIn('id="boxPalette"',page)
        self.assertNotIn('function drawBoxPalette()',page)
        self.assertIn('class="a17Workbench unifiedGroupEditor"',page)
        self.assertIn('id="groupDrawer" class="groupDrawer unifiedGroupList"',page)
        self.assertIn("updateBrushControls();drawStudioStats();",page)
        self.assertIn("choose.title='Выбрать рабочую коробку для кисти и переноса'",page)
        self.assertIn('brushTarget=b;',page)
        self.assertIn("card.style.setProperty('--group-color',groupPaletteColor(b))",page)
        self.assertIn("for(const b of [...boxOrder(),0])",page)
        self.assertIn("function groupWeightedEquity(b)",page)


if __name__=="__main__":
    unittest.main()
