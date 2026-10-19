'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync('replit_ui/plan.html','utf8');
const start=html.indexOf('const STRATEGY_RUN_CACHE_KEY=');
const declarations=html.slice(start,html.indexOf('const HAND_RESULT_METRICS=',start));
const helperStart=html.indexOf('// A calculation belongs to a particular saved/builtin preflop document');
const helpers=html.slice(helperStart,html.indexOf('function invalidateEquity(',helperStart));
assert.ok(start>0&&helperStart>0);
const script=declarations+'\n'+helpers+
 '\nthis.methods={key:strategyRunKey,load:loadStrategyRunCache,save:stashStrategyRun,'+
 'restore:restoreStrategyRun,entries:()=>[...strategyRunCache.entries()]};';
const backing=new Map();
const storage={getItem:key=>backing.get(key)||null,
 setItem:(key,value)=>{backing.set(key,value)},removeItem:key=>{backing.delete(key)}};
function harness(){
 const el={
  trials:{value:'1000',options:[250,500,1000,2000,4000].map(v=>({value:String(v)}))},
  simStack:{value:'20',options:[10,20,40,80].map(v=>({value:String(v)}))},
  heroPostflop:{value:'gto2',options:['gto2','gto3','tag'].map(value=>({value}))},
  handDecompHandB:{value:'-',options:['-','=','AQs'].map(value=>({value}))},
  handDecompProfileB:{value:'gto3',options:['gto2','gto3','tag'].map(value=>({value}))},
  handDecompOpponentCount:{value:'all',options:['all','1','2'].map(value=>({value}))},
  handDecompReportVariant:{value:'bdr',options:['bdr','river','catalog'].map(value=>({value}))},
  handDecompReportMode:{textContent:'БДР'},viewOpponent:{value:'0',options:Array.from({length:8},(_,i)=>({value:String(i)}))},
  strategyRunCacheStatus:{textContent:''}
 };
 const ctx={sessionStorage:storage,$:id=>{assert.ok(el[id],id);return el[id]},
  HANDS:['AQs','AA'],copy:x=>JSON.parse(JSON.stringify(x)),
  refreshHeroPostflopChoice:()=>{},
  hero:{ref:'pre:A',position:'3',scenario:'rfi',players:9},selected:'AQs',
  opponents:[{profile:'villain:A',position:'9'},...Array.from({length:7},(_,i)=>({profile:'noop',position:String(i+1)}))],
  equityResults:{filter:{equity:{AQs:55},ev_bb:{AQs:1.25}},actual:null,any:null},
  matrixContextKey:'',handWriteSeq:3,handWritebacks:new Map(),
  handDecompResult:{hand:'AQs',ev_bb:1.25},
  handDecompByOpponents:[{opponents:1,samples:200}],handDecompSignature:'',
  handDecompBResult:null,handDecompBByOpponents:null,handDecompBSignature:'',
  handDecompPairedComparison:null,handDecompPairedSignature:'',
  handDecompPreflopStats:{hero_rfi:50},decompReportMode:'bdr'};
 ctx.postflopMatrixContext=()=>JSON.stringify([ctx.hero.position,el.heroPostflop.value,ctx.opponents]);
 ctx.decompSideSignature=side=>side==='a'?
  JSON.stringify([ctx.hero.ref,ctx.hero.position,el.heroPostflop.value,el.trials.value,ctx.opponents]):'off';
 ctx.decompRequestSignature=()=>JSON.stringify([ctx.decompSideSignature('a'),ctx.decompSideSignature('b')]);
 vm.createContext(ctx);vm.runInContext(script,ctx);
 return {ctx,el,m:ctx.methods};
}
let {ctx,el,m}=harness();m.load();
const A=m.key('pre:A','gto2','3','rfi'),B=m.key('pre:B','tag','3','rfi');
assert.equal(m.restore(A),false);
ctx.matrixContextKey=ctx.postflopMatrixContext();
ctx.handDecompSignature=ctx.decompSideSignature('a');
m.save();
assert.ok(backing.size>0,'sessionStorage persists cached records');
ctx.hero={ref:'pre:B',position:'3',scenario:'rfi',players:9};
el.heroPostflop.value='tag';el.trials.value='2000';el.simStack.value='80';
ctx.opponents[0].profile='villain:B';ctx.selected='AA';
ctx.equityResults={filter:{equity:{AA:72},ev_bb:{AA:2.5}},actual:null,any:null};
ctx.matrixContextKey=ctx.postflopMatrixContext();
ctx.handDecompResult={hand:'AA',ev_bb:2.5};
ctx.handDecompSignature=ctx.decompSideSignature('a');
assert.equal(m.restore(B),false);m.save();
assert.equal(m.entries().length,2);
ctx.hero={ref:'pre:A',position:'3',scenario:'rfi',players:9};
assert.equal(m.restore(A),true);
assert.equal(el.trials.value,'1000');assert.equal(el.simStack.value,'20');
assert.equal(el.heroPostflop.value,'gto2');
assert.equal(ctx.opponents[0].profile,'villain:A');
assert.equal(ctx.selected,'AQs');
assert.equal(ctx.equityResults.filter.ev_bb.AQs,1.25);
assert.equal(ctx.handDecompResult.ev_bb,1.25);
assert.equal(ctx.handDecompPreflopStats.hero_rfi,50);
ctx.hero={ref:'pre:B',position:'3',scenario:'rfi',players:9};
assert.equal(m.restore(B),true);
assert.equal(el.trials.value,'2000');assert.equal(el.simStack.value,'80');
assert.equal(el.heroPostflop.value,'tag');
assert.equal(ctx.opponents[0].profile,'villain:B');
assert.equal(ctx.equityResults.filter.ev_bb.AA,2.5);
ctx.hero={ref:'pre:A',position:'3',scenario:'rfi',players:9};
const C=m.key('pre:A','gto3','3','rfi');
assert.equal(m.restore(C),false,'another policy is a different cache slot');
({ctx,el,m}=harness());m.load();
ctx.hero={ref:'pre:A',position:'3',scenario:'rfi',players:9};
assert.equal(m.restore(A),true);
assert.equal(ctx.equityResults.filter.ev_bb.AQs,1.25);
assert.equal(ctx.selected,'AQs');
const damaged=m.entries().find(([key])=>key===A)[1];
damaged.results.matrixContextKey='different-opponents';
ctx.equityResults={filter:null,actual:null,any:null};
assert.equal(m.restore(A),true);
assert.equal(ctx.equityResults.filter,null,'invalid matrix signature cannot be restored');
assert.match(html,/const previousKey=activeStrategyRunKey;\s*stashStrategyRun\(\)/);
assert.match(html,/const restored=chooseStrategyRun\(profile,/);
assert.match(html,/if\(!matrix\|\|!acceptCompleteMatrixResult\(matrix,startedAt,context\)\)return;\s*stashStrategyRun\(\)/);
assert.match(html,/const line=\$\('heroPostflop'\)\.value;\s*stashStrategyRun\(\)/);
assert.match(html,/function invalidateEquity\(\{refresh=true\}=\{\}\)/);
assert.match(html,/id="strategyRunCacheStatus"/);
console.log('Preflop cache: A/B restores, policy isolation, parameter persistence, reload and stale signature all verified');
