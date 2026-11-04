'use strict';
/* Board16 canonical selected-feature UI and EV reconciliation regression. */
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const plan=fs.readFileSync('replit_ui/plan.html','utf8');
const glossary=fs.readFileSync('replit_ui/river_board.html','utf8');
for(const marker of ['function renderRiverLedger(root,a,b,compare){',
 'function riverBoardDescription(code){','function board150Parts(code){',
 'const FLAT_BOARD_FACETS=[','↗ Справочник 49 типов'])
 assert.ok(plan.includes(marker),'missing Plan UI: '+marker);
for(const marker of ['id="board150Catalog"','function drawCatalog(){',
 '/api/postflop/board16-catalog','/api/postflop/board16-classify',
 'id="filterP"','id="filterS"','id="filterF"','id="filterSF"'])
 assert.ok(glossary.includes(marker),'missing catalog UI: '+marker);
assert.ok(!glossary.includes('75 типов ривера'));
const start=plan.indexOf('const RIVER_SIGN_LABELS=');
const end=plan.indexOf('function renderRiverLedger(root,a,b,compare){',start);
assert.ok(start>0&&end>start);
const ctx={};vm.createContext(ctx);
vm.runInContext('var riverFilters={sign:"all",p:"all",s:"all",f:"all",sf:"all",street:"all",origin:"all",holeUse:"all"};'+
 'var riverSort="impact",riverDescending=true,riverSampleTotals={a:20,b:20};'+
 plan.slice(start,end)+'\nthis.methods={parts:board150Parts,title:riverBoardDescription,tree:riverTree};',ctx);
const m=ctx.methods;
const c='S4 · F4 · SF4 · P1',d='S5 · F2';
assert.deepEqual(JSON.parse(JSON.stringify(m.parts(c))),{p:'P1',s:'S4',f:'F4',sf:'SF4'});
assert.equal(m.parts('PRE|NO_BOARD'),null);
assert.equal(m.parts('P1 · S3 · F4 · SF3'),null,'old IDs must not be silently reclassified');
assert.match(m.title(c),/Четыре связанных/);
assert.match(m.title(c),/Стрит-флеш-дро/);
assert.match(m.title('TURN|'+c),/Тёрн/);
const record=(code,count,ev)=>({sign:ev<0?'loss':'profit',
 cause:'C04',cause_name:'Разница комбинаций',board_code:code,count,
 origin:'own_pair',origin_name:'Своя пара',detail:'Тест',street:'river',
 suit:'S2',rank_texture:'one_pair',straight:'connected',
 hero_category:1,hero_hole_use:1,positive_ev_bb:Math.max(0,ev),
 negative_ev_bb:Math.min(0,ev),contribution_bb:ev});
const A={samples:20,ev_bb:0,river_attribution:{rows:[
 record(c,10,1),record(d,10,-1)]}};
const B={samples:20,ev_bb:0,river_attribution:{rows:[
 record(c,10,1),record(d,10,-1)]}};
const count=tree=>[...tree.values()].reduce((a,x)=>a+x.a.count,0);
assert.equal(count(m.tree(A,B)),20);
ctx.riverFilters.sf='SF4';
assert.equal(count(m.tree(A,B)),10);
ctx.riverFilters.sf='all';
ctx.riverFilters.s='S5';
assert.equal(count(m.tree(A,B)),10);
const catalog=JSON.parse(fs.readFileSync('data/postflop_compact16_catalog.json','utf8'));
assert.equal(catalog.rows.length,49);
assert.equal(catalog.rows.reduce((s,r)=>s+r.deals,0),2598960);
const gStart=glossary.indexOf('const shortNames={'),gEnd=glossary.indexOf('function el(',gStart);
assert.ok(gStart>0&&gEnd>gStart);
const gc={};vm.createContext(gc);
vm.runInContext(glossary.slice(gStart,gEnd)+'\nthis.nameOf=boardTitle',gc);
const names=catalog.rows.map(row=>gc.nameOf(row));
assert.equal(new Set(names).size,49,'All 49 board names must be distinct');
assert.match(gc.nameOf(catalog.rows.find(row=>row.id===c)),/Четыре связанных.*Стрит-флеш-дро.*Пара/);
console.log('Board16: 49 classes, 16 facets and EV filters verified');
