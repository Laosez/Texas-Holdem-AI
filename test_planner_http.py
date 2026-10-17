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
                    self.assertEqual(catalog["max_opponents"],8)
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
        page=service.PLAN_UI.read_text(encoding="utf-8")
        self.assertIn("function candidateSwaps(metric)",page)
        self.assertIn("candidateGold",page)
        self.assertIn("candidateRed",page)
        self.assertNotIn('id="equityMin"',page)
        self.assertIn("function renderPerOpponent()",page)
        self.assertIn("root.replaceChildren();",page)
        self.assertIn("item.handEq?.ev_bb?.[selected]",page)
    def test_pc_btn_is_explicit_and_non_rfi_not_falsely_filled(self):
        page=service.PLAN_UI.read_text(encoding="utf-8")
        self.assertIn("'3':'BTN · позиция 3'",page)
        self.assertIn("function positionCaption(pos)",page)
        self.assertIn("positionCaption(hero.position)",page)
        self.assertIn("doc.base_profile||doc.id",page)
        btn=core.preset("builtin:pc_gto_80bb",position="3",
                        scenario="rfi",players=9,stack_bb=80)
        self.assertEqual(len(btn["hands"]),169)
        self.assertEqual(btn["hands"]["K2s"]["open"],100)
        self.assertEqual(core.preset("builtin:pc_gto_80bb",position="3",
                        scenario="vs_open",players=9,stack_bb=80)["hands"],{})

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
        self.assertIn("const tag=el('span','handBoxTag'",page)
        self.assertIn(".matrixPane .handRank{position:absolute;top:2px;left:3px",page)
        self.assertIn(".matrixPane .handBoxTag{position:absolute;top:2px;right:3px",page)
        self.assertIn("const stripe=handActionStripe(actions);",page)
        self.assertIn(".hand.boxhit::before",page)
        self.assertNotIn(".hand.equityHit::after",page)


    def test_metric_gradient_and_action_stripe_are_independent(self):
        page=service.PLAN_UI.read_text(encoding="utf-8")
        self.assertIn(".matrixPane .hand{background:#303b49;background-image:none;",page)
        self.assertIn("const center=el('span','handMetric'",page)
        self.assertNotIn("function metricGradient(",page)
        self.assertIn("if(stripe)button.append(stripe)",page)
        self.assertIn('<select id="cellMetric" class="hidden"',page)
        self.assertIn('<option value="evStrategy" selected>',page)
        self.assertNotIn('Показатель в матрице</label>',page)
        self.assertIn(".matrixGrid .hand.playedRange",page)
    def test_all_in_call_ev_never_claims_to_be_full_action_ev(self):
        page = service.PLAN_UI.read_text(encoding="utf-8")
        self.assertIn("function modelCallEv(equityPct,potBB,callBB)",page)
        self.assertIn("return (equityPct/100)*(potBB+callBB)-callBB;",page)
        self.assertIn("modelCallEv(filtered,Number($('evPot').value),Number($('evCost').value))",page)
        self.assertIn("без побочных банков и будущих ставок",page)
        self.assertIn("EV сравнивается с Fold = 0",page)


    def test_multiway_all_in_ev_uses_actual_selected_equity(self):
        page=service.PLAN_UI.read_text(encoding="utf-8")
        # New main result is actual street-betting chip EV; old all-in diagnostic
        # math remains available in source but no longer drives the active metric.
        self.assertIn("if(metric==='evStrategy'){",page)
        self.assertIn("equityResults.filter?.ev_bb?.[h]",page)
        self.assertIn("if(metric==='showdownRate'){",page)
        self.assertIn("equityResults.filter?.showdown_pct?.[h]",page)
        self.assertIn("equityResults.filter=merged;equityResults.actual=merged;",page)
        self.assertIn("acceptCompleteMatrixResult(matrix,startedAt,context)",page)
    def test_a17_hand_lists_drag_to_pool_reorder_undo_and_save(self):
        page = service.PLAN_UI.read_text(encoding="utf-8")
        for css in (".boxHandList{",".boxHandChip{",".boxCard{",".boxPool{"):
            self.assertIn(css,page)
        for identifier in ("boxes","handBox","moveBox","undo"):
            self.assertIn('id="'+identifier+'"',page)
        self.assertIn("function boxChip(h)",page)
        self.assertNotIn("function reorderBox(from,to)",page)
        self.assertIn("function boxDropped(e,target)",page)
        self.assertIn("function markBoxDirty()",page)
        self.assertIn("'application/x-skachkov-hand'",page)
        self.assertNotIn("'application/x-skachkov-box'",page)
        self.assertIn("if(HANDS.includes(h))moveHandsToBox([h],target)",page)
        self.assertIn("moveHandToBox(h,0)",page)
        self.assertIn("for(const b of [...boxOrder(),0])",page)
        self.assertIn("hero.box_order=boxOrder()",page)
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
        self.assertIn("const groupEV=groupWeightedPostflopEV(b);",page)
        self.assertIn("function groupWeightedPostflopEV(b)",page)
        self.assertNotIn('id="computeBoxes"',page)
        self.assertNotIn("async function calculateBoxesEquity()",page)
        self.assertNotIn("await calculateBoxesEquity()",page)
        self.assertIn("cycles:Number($('cycles').value)",page)


    def test_gto_neutral_mode_and_detailed_hover(self):
        page = service.PLAN_UI.read_text(encoding="utf-8")
        self.assertIn('<option value="evStrategy" selected>',page)
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

    def test_planner_first_two_blocks_have_one_third_two_thirds_layout(self):
        page=service.PLAN_UI.read_text(encoding="utf-8")
        self.assertIn('<main class="plannerMain">',page)
        self.assertIn('class="panel plannerStrategyPanel"',page)
        self.assertIn('class="panel plannerOpponentsPanel"',page)
        self.assertIn("main.plannerMain{grid-template-columns:minmax(275px,1fr) minmax(0,3fr);align-items:start}",page)
        self.assertIn(".plannerMain>.plannerWorkspace{grid-column:1/-1;min-width:0}",page)
        self.assertIn(".plannerOpponentsPanel .filterTop{grid-template-columns:",page)
        self.assertIn("@media(max-width:1050px)",page)
        self.assertIn(".plannerMain>.plannerStrategyPanel,.plannerMain>.plannerOpponentsPanel,.plannerMain>.plannerWorkspace{grid-column:1/-1}",page)
        first=page.index('01 / </span>Мои соперники')
        second=page.index('02 / </span>Версии стратегии')
        third=page.index('03 / </span>Матрицы стартовых рук')
        self.assertIn('main.plannerMain{grid-template-columns:minmax(0,1fr);align-items:start}',page)
        self.assertTrue(first<second<third)

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

    def test_saved_a17_positions_share_one_editor_and_preserve_drafts(self):
        page=service.PLAN_UI.read_text(encoding="utf-8")
        for literal in ("function slotKey(players,position,scenario)",
            "function preserveCurrentSlot()","hero.contexts[key]=slot;",
            "hero={...hero,position,scenario,players,stack_bb:slot.stack_bb,",
            "preserveCurrentSlot();","const c=copy(hero);",
            "if(!preserveEdits()){if(hero)setHeroFields(hero);return}",
            "const prior=selectedValue===undefined?control.value:selectedValue;"):
            self.assertIn(literal,page)
        self.assertIn("useBbDefenseWhenRfi();renderOpponents();invalidateEquity();loadHero({contextChange:true});loadVillain()",page)
        self.assertIn("BB против открытия: используется GTO Fixed",page)
        self.assertIn("На BB нет RFI",page)
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


    def test_bb_rfi_automatically_uses_vs_open_not_empty_matrix(self):
        page=service.PLAN_UI.read_text(encoding="utf-8")
        self.assertIn('id="bbRfiInfo"',page)
        self.assertIn("function useBbDefenseWhenRfi()",page)
        self.assertIn("if($('heroPosition').value==='BB'&&$('heroScenario').value==='rfi')",page)
        self.assertIn("$('heroScenario').value='vs_open';",page)
        self.assertIn("useBbDefenseWhenRfi();\n const profile=",page)
        self.assertIn("useBbDefenseWhenRfi();\n   const doc=",page)
        self.assertIn("showBbRfiHint(doc);",page)
        self.assertIn("одна общая эвристика GTO Fixed",page)
        self.assertIn("PC GTO BB-чарты ещё не загружены",page)
        chart=core.preset("builtin:pc_gto_80bb",position="BB",scenario="vs_open",
                           players=9,stack_bb=80)
        self.assertEqual(chart["range_origin"],"gto_fixed_bb_vs_open")
        self.assertEqual(len(chart["hands"]),169)
        self.assertAlmostEqual(sum(chart["hands"]["AA"].values()),100,places=2)
        self.assertEqual(core.preset("builtin:pc_gto_80bb",position="BB",
                          scenario="rfi",players=9,stack_bb=80)["hands"],{})

    def test_entry_frequency_selector_and_marginal_active_counts(self):
        page=service.PLAN_UI.read_text(encoding="utf-8")
        for identifier in ("entryDistribution","opponentEntrySummary","entryDistributionNote"):
            self.assertIn('id="'+identifier+'"',page)
        self.assertIn("function entryPreviewMass(doc,selector='active')",page)
        self.assertIn("mass+=COMBOS(hand)*(share||0)/100",page)
        self.assertIn("{value:'range',label:'Ширина диапазона'}",page)
        self.assertIn("{value:'never',label:'0% · не участвует'}",page)
        self.assertIn("{value:'always',label:'100% · входит в банк'}",page)
        self.assertIn("opponents[i].entry_mode=mode.value",page)
        self.assertIn("opponents[i].entry_pct=mode.value==='never'?0:100",page)
        self.assertIn("entry_mode:i<3?'range':'never'",page)
        self.assertIn("entry_counts_pct",page)
        self.assertIn("renderEntryDistribution()",page)
        self.assertIn("function modelConditionalAllInEv(",page)
        self.assertIn("return stackBB*potMultiple+deadBB*equityPct/100-stackBB",page)
        self.assertIn("equityResults.actual?.pot_multiple?.[h]",page)
        self.assertIn("equityResults.actual?.pot_multiple",page)
        self.assertIn("Средний банк, BB",page)
        self.assertIn("entry_ev_sd_bb",page)
        self.assertIn("entry_pot_bb",page)

    def test_range_ev_overlap_and_reverse_opponent_matrix_controls(self):
        page=service.PLAN_UI.read_text(encoding="utf-8")
        # Historical reverse/opponent controls are hidden for archived
        # compatibility, not rendered as a second matrix.
        self.assertNotIn('<details id="villainPane"',page)
        self.assertIn('id="hiddenVillainLegacy"',page)
        self.assertIn('id="perOpponentHands"',page)
        self.assertIn("function pollPostflop(settings,epoch,report)",page)
        self.assertIn("function calculatePerOpponent()",page)
        self.assertIn("post('/api/plan/postflop',settings)",page)
        self.assertIn("const showIntersection=false;",page)
        self.assertIn("const showOpponent=$('villainPane').open;",page)
    def test_diagonal_background_is_permanent_and_local_matrix_metrics(self):
        page=service.PLAN_UI.read_text(encoding="utf-8")
        self.assertIn("const showIntersection=false;",page)
        self.assertIn('id="heroMatrix"',page)
        self.assertNotIn('<details id="villainPane"',page)
        self.assertIn('background:#365b76!important;',page)
        self.assertIn("const info=cellMetricValue(doc,h,metric);",page)
        self.assertIn("if(Number.isInteger(b)&&b>0){",page)
        self.assertIn("tag.style.setProperty('--group-color',groupPaletteColor(b))",page)
        self.assertIn('value="evStrategy"',page)
    def test_fixed_nine_positions_and_hidden_legacy_add_remove(self):
        page=service.PLAN_UI.read_text(encoding="utf-8")
        self.assertIn('id="addOpponent" class="btn sm hidden"',page)
        self.assertIn("opponents=Array.from({length:8}",page)
        self.assertIn("const FIXED_TABLE_POSITIONS=['9','8','7','6','5','4','3','SB','BB'];",page)
        self.assertIn("const heroSeat=normalizeFixedSeats();",page)
        self.assertIn("row.setAttribute('aria-label','Hero · моя стратегия');",page)
        self.assertNotIn("remove.disabled=true;remove.classList.add('hidden');",page)
        self.assertIn("row.append(heroSeatPositionPicker(opp.position,false));",page)
        self.assertIn("entry_mode:i<3?'range':'never'",page)
        self.assertIn("function opponentBulkRow(){",page)


    def test_box_click_white_frame_and_group_all_in_ev(self):
        page=service.PLAN_UI.read_text(encoding="utf-8")
        self.assertIn("const wasSelected=selectedBoxes.has(b)",page)
        self.assertIn("if(wasSelected)selectedBoxes.delete(b);else selectedBoxes.add(b);",page)
        self.assertIn(".matrixGrid .hand.boxhit{outline:2px solid #f0f7ff",page)
        self.assertIn("const boxhit=selectedBoxes.size>0&&selectedBoxes.has(hero?.boxes?.[h])",page)
        self.assertIn("choose.setAttribute('aria-pressed',String(selectedBoxes.has(b)))",page)
        self.assertIn("function groupWeightedAllInEV(b)",page)
        self.assertIn("const ev=modelConditionalAllInEv(eq[h],pots?.[h],stack,dead,n)",page)
        self.assertIn("const groupEV=groupWeightedPostflopEV(b)",page)
        self.assertIn("· EV '+(groupEV===null?",page)
        self.assertIn('id="cleanupStrategies"',page)
        self.assertIn("function preserveA17Strategy(name)",page)
        self.assertIn("if(!confirm('В корзину уйдут ВСЕ ВЕРСИИ '",page)
        self.assertIn('id="activeContext"',page)
        self.assertIn('id="players" class="hidden"',page)
        self.assertIn('id="stack" class="hidden"',page)

    def test_matrix_action_copy_paste_between_positions_preserves_boxes(self):
        page=service.PLAN_UI.read_text(encoding="utf-8")
        self.assertIn('id="copyMatrix"',page)
        self.assertIn('id="pasteMatrix"',page)
        self.assertIn('id="matrixClipboardStatus"',page)
        self.assertIn("function copyMatrixSettings()",page)
        self.assertIn("function pasteMatrixSettings()",page)
        self.assertIn("copiedMatrix.scenario===hero.scenario",page)
        self.assertIn("if(hero.scenario!==copiedMatrix.scenario)",page)
        self.assertIn("if(!confirm('Заменить все настройки 169 рук",page)
        self.assertIn("snapshotUndo();\n hero.hands=copy(copiedMatrix.hands);",page)
        self.assertIn("preserveCurrentSlot();\n noteDirty();",page)
        self.assertIn("updateMatrixClipboard();$('delete').disabled",page)
        self.assertIn("$('copyMatrix').onclick=copyMatrixSettings;",page)
        self.assertIn("$('pasteMatrix').onclick=pasteMatrixSettings;",page)
        self.assertNotIn("hero.boxes=copy(copiedMatrix",page)

    def test_fixed_four_box_columns_and_multi_hand_right_panel_transfer(self):
        page=service.PLAN_UI.read_text(encoding="utf-8")
        self.assertIn(".unifiedGroupList .boxList{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));",page)
        self.assertIn("return Array.from({length:17},(_,i)=>i+1);",page)
        self.assertNotIn("function reorderBox(from,to)",page)
        self.assertNotIn("const handle=el('button','boxHandle'",page)
        self.assertNotIn("application/x-skachkov-box",page)
        self.assertIn("e.dataTransfer.setData('application/x-skachkov-hands',JSON.stringify(hands))",page)
        self.assertIn("if(Array.isArray(hands)){moveHandsToBox(hands,target);return}",page)
        self.assertIn("$('moveBox').onclick=()=>moveHandsToBox(editorTargets(),Number($('handBox').value));",page)
        self.assertIn("const changed=[...new Set(hands)].filter(",page)
        self.assertIn("changed.forEach(h=>hero.boxes[h]=target)",page)
        self.assertIn("snapshotUndo();",page)
        self.assertIn("remove.onclick=()=>moveHandToBox(h,0)",page)
        self.assertIn("if(e.shiftKey||e.ctrlKey||e.metaKey)",page)

    def test_group_ids_no_longer_have_white_range_ring(self):
        page=service.PLAN_UI.read_text(encoding="utf-8")
        style=page.split(".matrixPane .handBoxTag.inRange{",1)[1].split("}",1)[0]
        self.assertIn("outline:none",style)
        self.assertIn("border:0",style)
        self.assertNotIn("#edf1f4",style)
        self.assertIn("box-shadow:inset 0 0 0 1px #5c7792",page)

    def test_colored_a17_badges_and_range_outlines(self):
        page=service.PLAN_UI.read_text(encoding="utf-8")
        # The box badge's color uses the existing A17 group palette.
        self.assertIn(".matrixPane .handBoxTag.inRange{",page)
        self.assertIn("box-shadow:none;background:var(--group-color,#8494a6);",page)
        self.assertIn("position:absolute;top:0;right:0;z-index:5;",page)
        self.assertIn("text-shadow:none;box-shadow:none;",page)
        self.assertNotIn("color-mix(",page)
        self.assertIn("tag.style.setProperty('--group-color',groupPaletteColor(b))",page)
        self.assertIn("tag.classList.add('inRange')",page)
        self.assertIn(".unifiedGroupList .boxCard.inRange{",page)
        self.assertIn("members.some(h=>handInRange(hero,h))",page)
        # Active means a positive participation, not an unknown or Fold 100%.
        self.assertIn("function handInRange(doc,hand)",page)
        self.assertIn("return participation!==null&&participation>0;",page)
        # Brush strokes refresh both the badge color and its range ring.
        self.assertIn("badge.style.setProperty('--group-color',groupPaletteColor(brushTarget))",page)
        self.assertIn("badge.classList.toggle('inRange',handInRange(hero,hand))",page)
        self.assertIn("if(!brushTarget){tag?.remove();return}",page)
        # Keep candidate highlighting while allowing blue fill for participating hands.
        self.assertIn(".hand.candidateGold{border:2px solid #f3c45c}",page)
        self.assertIn(".hand.candidateRed{border:2px solid #ee6d75}",page)
        self.assertIn(".matrixPane .hand{background:#303b49;background-image:none;",page)

    def test_numeric_metric_labels_use_visible_min_max_scale(self):
        page=service.PLAN_UI.read_text(encoding="utf-8")
        self.assertIn("function visibleMetricScale(metric,docs)",page)
        self.assertIn("function metricTextColor(metric,value,scale)",page)
        self.assertIn("Math.min(...values),max:Math.max(...values)",page)
        self.assertIn("const scale=visibleMetricScale(mainMetric,[hero]);",page)
        self.assertIn("if(color)center.style.color=color;",page)
        self.assertIn("Math.abs(value)<0.000001)return '#d7e1ee'",page)
        self.assertIn("const hue=value<0?3:159;",page)
        self.assertIn(".matrixPane .hand{background:#303b49;background-image:none;",page)

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
        self.assertIn("if(selectedBoxes.size&&hero)return HANDS.filter(h=>selectedBoxes.has(hero.boxes?.[h]));",page)
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
        self.assertIn('id="heroMatrix"',page)
        self.assertNotIn('<details id="villainPane"',page)
        self.assertIn('id="hiddenVillainLegacy"',page)
        self.assertIn("const showIntersection=false;",page)
        self.assertIn("if(showOpponent)matrix($('villainMatrix'),villain",page)
        self.assertNotIn('id="matrixMode"',page)
    def test_a17_brush_and_groups_are_one_panel(self):
        page=service.PLAN_UI.read_text(encoding="utf-8")
        self.assertEqual(page.count('id="groupEditor"'),1)
        self.assertEqual(page.count('id="boxes"'),1)
        self.assertNotIn('id="boxPalette"',page)
        self.assertNotIn('function drawBoxPalette()',page)
        self.assertIn('class="a17Workbench unifiedGroupEditor"',page)
        self.assertIn('id="groupDrawer" class="groupDrawer unifiedGroupList"',page)
        self.assertIn("updateBrushControls();drawStudioStats();",page)
        self.assertIn("choose.title='Выделить / снять белую рамку всех рук коробки'",page)
        self.assertIn('brushTarget=b;',page)
        self.assertIn("card.style.setProperty('--group-color',groupPaletteColor(b))",page)
        self.assertIn("for(const b of [...boxOrder(),0])",page)
        self.assertIn("function groupWeightedEquity(b)",page)


if __name__=="__main__":
    unittest.main()
