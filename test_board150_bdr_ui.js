'use strict';
/* Execute the production Sheet 02 Board150 classifier/accounting helpers.
   Sheet 03 is now deliberately glossary-only, with 150 readable titles. */
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const plan=fs.readFileSync('replit_ui/plan.html','utf8');
const glossary=fs.readFileSync('replit_ui/river_board.html','utf8');
for(const marker of [
  'id="handDecompReportVariant"', '<option value="board150" selected>',
  'function renderRiverLedger(root,a,b,compare){','function riverBoardDescription(code){',
  'function riverReportHead(table,compare){','function riverControls(root,compare,active){',
  'reasonBoardExpanded.clear()','Раскрыть всё','Свернуть всё',
  'function board150Parts(code){','riverBoardCode','aria-sort',
  'ВСЯ ВЫБОРКА · КОНТРОЛЬ EV','↗ Справочник 150 бордов',
  "if(decompReportMode==='river'||decompReportMode==='board150'){"
 ])assert.ok(plan.includes(marker),'Missing financial UI: '+marker);
for(const marker of ['id="board150Catalog"','Название борда','function boardTitle(row){',
  'function drawCatalog(){','function exportCSV(){',
  'id="filterP"','id="filterS"','id="filterF"','id="filterSF"','id="filterA"'
 ])assert.ok(glossary.includes(marker),'Glossary regression: '+marker);
for(const forbidden of ['id="board150Report"','viewFinancial','drawReport()',
 'function reportTree(){','skachkov_board150_report_v1',
 'reportSign','reportSort','loadReport()'])
 assert.ok(!glossary.includes(forbidden),'Financial view must leave Sheet 03: '+forbidden);
assert.ok(!plan.includes('↗ Отчёт на листе 03 · Постфлоп'));
const start=plan.indexOf('const RIVER_SIGN_LABELS=');
const end=plan.indexOf('function renderRiverLedger(root,a,b,compare){',start);
assert.ok(start>0&&end>start,'Failed to locate actual financial-report methods');
const initial={
 sign:'all',p:'all',s:'all',f:'all',sf:'all',a:'all',
 street:'all',origin:'all',holeUse:'all'
};
const code=plan.slice(start,end);
const ctx={};
vm.createContext(ctx);
vm.runInContext(
 'var riverFilters='+JSON.stringify(initial)+';'+
 "var riverSort='impact',riverDescending=true,riverSampleTotals={a:20,b:20};\n"+
 code+"\nthis.methods={parts:board150Parts,pass:riverPass,tree:riverTree,"+
 "title:riverBoardDescription,ordered:riverOrdered,val:riverSortValue};",ctx);
const m=ctx.methods;
const c='P1 · S3 · F4 · SF3 · A0';
const d='P0 · S5 · F2 · SF0 · A1';
assert.deepEqual(JSON.parse(JSON.stringify(m.parts(c))),{
 p:'P1',s:'S3',f:'F4',sf:'SF3',a:'A0'
});
assert.equal(m.parts('PRE|NO_BOARD'),null);
assert.match(m.title(c),/Пара на столе/);
assert.match(m.title(c),/четыре подряд/);
assert.match(m.title(c),/4s/);
assert.match(m.title(c),/стрит-флеш −1/);
assert.match(m.title('PRE|NO_BOARD'),/Префлоп/);
assert.match(m.title('TURN|'+c),/Тёрн/);
assert.match(m.title('FLOP|'+c),/Флоп/);
const record=(sign,cause,code,count,ev)=>({
 sign,cause,cause_name:cause==='C04'?'Разница комбинаций':'Фолд HERO',
 board_code:code,count,
 origin:'own_pair',origin_name:'Своя пара',detail:'Тест',
 street:code.startsWith('FLOP|')?'flop':code==='PRE|NO_BOARD'?'preflop':'river',
 suit:'S2',rank_texture:'one_pair',straight:'connected',
 hero_category:1,hero_hole_use:1,
 positive_ev_bb:Math.max(0,ev),negative_ev_bb:Math.min(0,ev),
 contribution_bb:ev
});
const A={samples:20,ev_bb:0.1,river_attribution:{rows:[
 record('profit','C04',c,9,0.9),
 record('loss','C04',c,4,-0.5),
 record('loss','C04',d,3,-0.2),
 record('loss','C03','FLOP|P0 · S1 · F2 · SF0 · A0',2,-0.1),
 record('neutral','C07','PRE|NO_BOARD',2,0)]}};
const B={samples:20,ev_bb:0.2,river_attribution:{rows:[
 record('profit','C04',c,10,1.1),
 record('loss','C04',c,4,-0.6),
 record('loss','C04',d,3,-0.2),
 record('loss','C03','FLOP|P0 · S1 · F2 · SF0 · A0',1,-0.1),
 record('neutral','C07','PRE|NO_BOARD',2,0)]}};
const totals=(tree,side)=>{
 let count=0,net=0;
 for(const g of tree.values()){count+=g[side].count;net+=g[side].contribution_bb}
 return {count,net}
};
const initialTree=m.tree(A,B);
assert.equal(initialTree.size,3);
assert.equal(totals(initialTree,'a').count,20);
assert.ok(Math.abs(totals(initialTree,'a').net-0.1)<1e-9);
assert.equal(totals(initialTree,'b').count,20);
assert.ok(Math.abs(totals(initialTree,'b').net-0.2)<1e-9);
assert.equal(initialTree.get('loss').children.get('cause:loss:C04').a.count,7);
ctx.riverFilters.f='F4';
const filtered=m.tree(A,B);
assert.equal(totals(filtered,'a').count,13);
assert.equal(filtered.get('loss').a.count,4);
assert.equal(filtered.get('profit').a.count,9);
assert.equal(filtered.has('neutral'),false);
ctx.riverFilters.f='all';
ctx.riverFilters.p='P1';
assert.equal(totals(m.tree(A,B),'a').count,13);
ctx.riverFilters.p='all';
ctx.riverFilters.street='flop';
assert.equal(totals(m.tree(A,B),'a').count,2);
ctx.riverFilters.street='all';
ctx.riverFilters.a='A1';
assert.equal(totals(m.tree(A,B),'a').count,3);
ctx.riverFilters.a='all';
ctx.riverFilters.s='S3';
assert.equal(totals(m.tree(A,B),'a').count,13);
ctx.riverFilters.s='all';
ctx.riverSort='negative_ev_bb:a';
ctx.riverDescending=false;
const lossRows=[...m.tree(A,B).get('loss').children.get('cause:loss:C04').children.values()];
const byLoss=m.ordered(lossRows).map(row=>row.label);
assert.equal(byLoss[0],c,'ascending signed EV− must put biggest loss first');
ctx.riverSort='count:a';
ctx.riverDescending=true;
assert.equal(m.val(initialTree.get('profit')),9);
ctx.riverSort='percentage:a';
assert.equal(m.val(initialTree.get('profit')),45);
ctx.riverSort='delta';
assert.ok(Math.abs(m.val(initialTree.get('profit'))-0.2)<1e-9);
// The glossary labels must discriminate every one of the 150 physical codes.
const catalog=JSON.parse(fs.readFileSync('data/postflop_board150_catalog.json','utf8'));
assert.equal(catalog.rows.length,150);
const gStart=glossary.indexOf('function boardTitle(row){'),gEnd=glossary.indexOf('function drawCatalog(){',gStart);
assert.ok(gStart>0&&gEnd>gStart);
const gc={};
vm.createContext(gc);
vm.runInContext(glossary.slice(gStart,gEnd)+'\nthis.nameOf=boardTitle',gc);
const names=catalog.rows.map(row=>gc.nameOf(row));
assert.equal(new Set(names).size,150,'Read-friendly titles must be unique per physical board type');
assert.match(gc.nameOf(catalog.rows.find(row=>row.id===c)),/Пара на столе.*4s.*без туза/);
console.log('Board150 accounting migrated to Plan: cause → board, complete A/B EV, 5 code filters, human labels, 150 unique glossary titles');
