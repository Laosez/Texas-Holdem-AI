'use strict';
/* Execute the ACTUAL financial reporting helpers from live Sheet 03.
   Verify hierarchy, signs, sorting, physical board labels and A/B accounting.
   No mocked poker decisions or substituted analytical logic. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const sheet=fs.readFileSync('replit_ui/river_board.html','utf8');
const plan=fs.readFileSync('replit_ui/plan.html','utf8');
assert.match(sheet,/id="viewFinancial"[^>]*role="tab"/);
assert.match(sheet,/id="viewCatalog"[^>]*role="tab"/);
assert.match(sheet,/id="board150Report"[^>]*hidden/);
assert.match(sheet,/function setView\(view\)/);
assert.match(sheet,/function renderReportHead\(\)/);
assert.match(sheet,/function collectGroupKeys\(tree\)/);
assert.match(sheet,/id="reportExpandAll"/);
assert.match(sheet,/id="reportCollapseAll"/);
assert.match(sheet,/id="reportSortDirection"/);
assert.match(sheet,/abGroupHeader/);
assert.match(sheet,/aria-sort/);
assert.match(sheet,/ВСЯ ВЫБОРКА · КОНТРОЛЬ EV/);
assert.match(plan,/function riverReportHead\(table,compare\)/);
assert.match(plan,/function riverBoardDescription\(code\)/);
assert.match(plan,/const activeTree=\{a,b\}/);
assert.match(plan,/window\.location\.assign\('\/s100'\)/);
const start=sheet.indexOf('const $=id=>');
const end=sheet.indexOf('function exportCSV(){',start);
assert.ok(start>0&&end>start);
const elements={reportSign:{value:''},reportSort:{value:'impact'},
 filterP:{value:''},filterS:{value:''},filterF:{value:''},filterSF:{value:''},filterA:{value:''}};
const ctx={document:{getElementById:id=>{assert.ok(elements[id],'unexpected '+id);return elements[id]}}};
vm.createContext(ctx);
vm.runInContext(sheet.slice(start,end),ctx);
const c='P1 · S3 · F4 · SF3 · A0',d='P0 · S5 · F2 · SF0 · A1';
const record=(sign,cause,code,count,ev)=>({
 sign,cause,cause_name:cause==='C04'?'Разница категорий комбинаций':'Фолд HERO',
 board_code:code,count,
 positive_ev_bb:Math.max(0,ev),negative_ev_bb:Math.min(0,ev),contribution_bb:ev
});
const data={
 version:'river_board_150_v1',hand:'AQs',profile:'GTO',
 a:{samples:20,ev_bb:0.1,rows:[
  record('profit','C04',c,9,0.9),
  record('loss','C04',c,4,-0.5),
  record('loss','C04',d,3,-0.2),
  record('loss','C03','FLOP|P0 · S1 · F2 · SF0 · A0',2,-0.1),
  record('neutral','C07','PRE|NO_BOARD',2,0)]},
 b:{samples:20,ev_bb:0.2,rows:[
  record('profit','C04',c,10,1.1),
  record('loss','C04',c,4,-0.6),
  record('loss','C04',d,3,-0.2),
  record('loss','C03','FLOP|P0 · S1 · F2 · SF0 · A0',1,-0.1),
  record('neutral','C07','PRE|NO_BOARD',2,0)]}
};
vm.runInContext('report='+JSON.stringify(data),ctx);
const totalTree=vm.runInContext('reportTree()',ctx);
assert.equal(totalTree.size,3);
const loss=totalTree.get('sign:loss');
assert.equal(loss.a.count,9);
assert.ok(Math.abs(loss.a.contribution_bb-(-0.8))<1e-9);
const cause=loss.children.get('sign:loss:C04');
assert.equal(cause.a.count,7);
assert.equal(cause.children.size,2);
const actual=vm.runInContext('readableCode('+JSON.stringify(c)+')',ctx);
assert.match(actual,/Ривер/);assert.match(actual,/Пара/);assert.match(actual,/4s/);
assert.match(vm.runInContext("readableCode('PRE|NO_BOARD')",ctx),/До флопа/);
assert.match(vm.runInContext("readableCode('FLOP|P0 · S1 · F2 · SF0 · A0')",ctx),/Флоп/);
const groups=vm.runInContext('collectGroupKeys(reportTree())',ctx);
assert.ok(groups.includes('sign:loss:C04'));
assert.ok(groups.includes('sign:profit'));
vm.runInContext("reportDirection='asc'",ctx);
elements.reportSort.value='negative_ev_bb:a';
const sorted=vm.runInContext("order(reportTree().get('sign:loss').children.get('sign:loss:C04').children.values()).map(n=>n.label)",ctx);
assert.equal(sorted[0],c,'large loss should sort ahead for ascending signed negative EV');
elements.filterF.value='F4';
const filtered=vm.runInContext('reportTree()',ctx);
assert.equal(filtered.get('sign:loss').a.count,4);
assert.equal(filtered.get('sign:profit').a.count,9);
assert.equal(filtered.has('sign:neutral'),false);
elements.filterF.value='';
elements.reportSort.value='delta';
const delta=vm.runInContext("columnValue(reportTree().get('sign:profit'),'delta')",ctx);
assert.ok(Math.abs(delta-0.2)<1e-9);
assert.equal(vm.runInContext("FINANCE_COLS.filter(c=>c.group==='a').length",ctx),6);
assert.equal(vm.runInContext("reportCols().length",ctx),13);
vm.runInContext('report.b=null',ctx);
assert.equal(vm.runInContext("reportCols().length",ctx),6);
const planStart=plan.indexOf('function riverSortValue(node){');
const planEnd=plan.indexOf('function riverControls(',planStart);
assert.ok(planStart>0&&planEnd>planStart);
const px={};
vm.createContext(px);
vm.runInContext('let riverSort="count:a",riverDescending=true,riverSampleTotals={a:100,b:200};'+
 'function riverEmpty(){return {count:0,contribution_bb:0,negative_ev_bb:0}}'+
 plan.slice(planStart,planEnd),px);
const rank=vm.runInContext("riverSortValue({a:{count:15},b:{count:8}})",px);
assert.equal(rank,15);
const proportion=vm.runInContext("riverSort='percentage:a';riverSortValue({a:{count:15},b:{count:8}})",px);
assert.equal(proportion,15);
console.log('BDR Board150 UI: two modes, exact reason → code hierarchy, sort, cause totals, filters, A/B and readable board aliases verified');
