'use strict';
/* Regression: Shadow is readable and its filters sort only paired aggregates. */
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const page = fs.readFileSync('replit_ui/index.html','utf8');
for(const marker of [
 'id="gto5ShadowPanel"', 'id="gto5ShadowRows"', 'id="gto5ShadowStatus"',
 'id="shadowPercent"', 'Independent River Auditor',
 'id="gto30TraceDepth"', 'Последние 100', 'gto30-trace-exact',
 'GTO 5.1 · СТАРШИНСТВО', 'Показать точный расчёт Any Two', 'href="#gto5ShadowPanel"', 'shadow-kpis',
 'shadow-tabs', 'shadow-overview-grid', 'shadow-hand-list',
 'GTO 5.0.5', 'GTO 5.1.5', 'function renderIndependentAuditor(', 'data.comparisons', 'Independent River Auditor · реальные исходы',
 'gto5-shadow-decision?decision=', 'gto5-shadow-decisions?',
 'shadowCardTokens(row.hole', 'Точный аудит Any Two',
 'function shadowSortedRows(', 'function shadowTable(',
 'function renderGTO5Shadow()', 'function loadGTO5Shadow(id)'
]) assert.ok(page.includes(marker),'missing Shadow marker: '+marker);

for(const marker of ['id="gto5ShadowPanel"', 'id="gto5ShadowRows"'])
 assert.equal(page.split(marker).length-1,1,'duplicate id '+marker);

assert.ok(page.indexOf('id="gto5ShadowPanel"')>page.indexOf('class="panel resultsPanel"'),
  'Shadow panel must be beside full-width tournament results');
assert.ok(page.indexOf('id="gto5ShadowPanel"')<page.indexOf('id="analysis"'),
  'Shadow panel should precede detailed tournament analytics');
assert.ok(!page.includes('function makeTable(heading,rows)'),
  'old ten-table wall must not be shipped');

// Check syntax for the actual inline browser script without running its API calls.
const scriptStart=page.indexOf('<script>'),scriptEnd=page.lastIndexOf('</script>');
assert.ok(scriptStart>0&&scriptEnd>scriptStart);
const script=page.slice(scriptStart+8,scriptEnd);
new vm.Script(script,{filename:'shadow-ui-inline.js'});

const begin=script.indexOf('const SHADOW_NAV=');
const end=script.indexOf("let gto30TraceSession=",begin);
assert.ok(begin>=0&&end>begin);
const ctx={};vm.createContext(ctx);
vm.runInContext(script.slice(begin,end)+
  '\nthis.shadowTest={sort:shadowSortedRows,readable:shadowReadable,format:shadowFormat,nav:SHADOW_NAV};',ctx);
const m=ctx.shadowTest;
assert.equal(m.nav.length,7);
assert.ok(page.includes("shadow_reference:'independent_river'"),'fixed independent audit config missing');
assert.ok(!page.includes('id="shadowReference"'),'legacy reference selector must be absent');
assert.ok(!page.includes('<option value="gto41">'),'legacy 4.1 cannot be selectable as Shadow reference');
assert.ok(page.includes("pairs.find(x=>x.key===shadowComparison)"),'report pair selector missing');
assert.match(m.readable('flop | 2'),/Флоп.*2 оппонента/);
assert.match(m.readable('P0'),/без пары/);

const sample=[
 {label:'flop',n:8939,mean_regret_bb:.30,total_regret_bb:2650.99,mismatch_pct:35.92},
 {label:'river',n:2833,mean_regret_bb:.65,total_regret_bb:1854.72,mismatch_pct:28.94},
 {label:'turn',n:4195,mean_regret_bb:.37,total_regret_bb:1570.15,mismatch_pct:32.04},
 {label:'P3',n:10,mean_regret_bb:5,total_regret_bb:99,mismatch_pct:90},
];
const byTotal=m.sort(sample,'total_regret_bb','',true,true);
assert.equal(byTotal.length,3,'low sample excluded by default');
assert.equal(byTotal[0].label,'flop','total regret must order flop first');
const byMean=m.sort(sample,'mean_regret_bb','',true,true);
assert.equal(byMean[0].label,'river','mean regret must order river first');
assert.equal(m.sort(sample,'total_regret_bb','river',true,true)[0].label,'river');
assert.equal(m.sort(sample,'total_regret_bb','',false,true).length,4);
assert.equal(m.format(.35),'0,35');
console.log('Shadow dashboard: real inline JS parses, 7 tabs, responsive sections, sample filters and sorting verified');

// The expensive-decisions view is fully visible, without per-card spoilers.
const inline=page.slice(page.indexOf('function shadowPaintDecision('),
                        page.indexOf('async function loadGTO5Shadow(id)'));
assert.ok(inline.includes('shadowPrefetchHands(records.filter'),
  'Top 20 should load automatically without user click');
assert.ok(inline.includes('SHADOW-СОПОСТАВЛЕНИЯ'),
  'paired EV must be visible inline');
assert.ok(!inline.includes("el('details'"),
  'no nested expanders allowed in inline costly errors');
assert.ok(page.includes('id="gto30TracePanel" open'),
  'recent street logs should open by default');
assert.ok(page.includes('id="storageBreakdownRows"'),
  'storage audit must show largest files in the UI');


// All twenty costly-decision cards must occupy one full-width column.
const singleColumnCss = page.match(/\.shadow-hand-list\{[^}]+\}/);
assert.ok(singleColumnCss, 'Top-20 list must have a CSS grid rule');
assert.match(singleColumnCss[0], /grid-template-columns:minmax\(0,1fr\)/,
  'Top-20 must use exactly one column, including wide desktops');
assert.doesNotMatch(singleColumnCss[0], /repeat\(2,/,
  'Top-20 must not split hands across two columns');
assert.ok(page.includes('grid-template-columns:minmax(0,1fr);gap:9px;min-width:0;max-width:100%'),
  'Each expanded hand must constrain its internal grid to avoid horizontal overflow');
