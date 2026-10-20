'use strict';
const assert=require('assert');
const fs=require('fs');
const vm=require('vm');
const html=fs.readFileSync('replit_ui/plan.html','utf8');
const begin=html.indexOf('const fixedSeatOpponentHistory=new Map();');
const end=html.indexOf('function normalizeFixedSeats(){',begin);
assert(begin>=0&&end>begin,'Missing persistent settings helpers');
const script=html.slice(begin,end);
const positions=['9','8','7','6','5','4','3','SB','BB'];
const values={
 heroProfile:'saved:1234abcd5678@v1',heroPosition:'9',
 heroScenario:'rfi',heroPostflop:'lag',simStack:'80',trials:'4000'
};
const store=new Map();
const storage={
 getItem:k=>store.has(k)?store.get(k):null,
 setItem:(k,v)=>store.set(k,v),
 removeItem:k=>store.delete(k)
};
const context=vm.createContext({
 FIXED_TABLE_POSITIONS:positions,localStorage:storage,
 $:id=>({value:values[id]}),
 opponents:[
  {position:'8',profile:'builtin:a17_v5',scenario:'rfi',
   postflop:'tag',selector:'active',entry_mode:'range',entry_pct:100},
  {position:'BB',profile:'builtin:pc_gto_80bb',scenario:'vs_open',
   postflop:'gto',selector:'threebet',entry_mode:'never',entry_pct:0}
 ],
 meta:{builtins:[]},msg:()=>{},
 SCENARIOS:{rfi:'RFI',vs_open:'vs_open',vs_threebet:'3bet'},
 ACTIONS:{fold:'Fold',open:'Raise',threebet:'3-bet',call:'Call'}
});
vm.runInContext(script,context);
const evalJs=x=>vm.runInContext(x,context);
assert.equal(evalJs('defaultPlanSettings().seats.length'),9);
assert.equal(evalJs('defaultPlanSettings().seats.find(x=>x.position==="BB").scenario'),'vs_open');
assert.equal(evalJs('defaultPlanSettings().seats.every(x=>x.entry_mode==="range")'),true);
assert.equal(evalJs('defaultPlanSettings().postflop'),'gto');
assert.equal(evalJs('defaultPlanSettings().profile'),'builtin:pc_gto_80bb');
assert.equal(evalJs('defaultPlanSettings().simStack'),'20');
assert.equal(evalJs('defaultPlanSettings().trials'),'1000');
vm.runInContext("fixedSeatOpponentHistory.set('SB',{...defaultPlanSeat('SB'),profile:'builtin:a17_legacy'})",context);
assert.equal(evalJs('readPlanSettings()'),null);
evalJs('persistPlanSettings()');
assert.equal(evalJs('readPlanSettings()'),null,'Do not save during initialization');
evalJs('planSettingsReady=true; persistPlanSettings()');
const saved=JSON.parse(store.get('skachkov_plan_settings_v1'));
assert.equal(saved.profile,'saved:1234abcd5678@v1');
assert.equal(saved.postflop,'lag');
assert.equal(saved.position,'9');
assert.equal(saved.simStack,'80');
assert.equal(saved.trials,'4000');
assert.equal(saved.seats.length,9);
assert.equal(saved.seats.find(x=>x.position==='BB').entry_mode,'never');
assert.equal(saved.seats.find(x=>x.position==='BB').selector,'threebet');
assert.equal(saved.seats.find(x=>x.position==='SB').profile,'builtin:a17_legacy');
assert.equal(saved.seats.find(x=>x.position==='8').postflop,'tag');
assert.equal(saved.seats.find(x=>x.position==='BB').scenario,'vs_open');
assert.equal(evalJs('readPlanSettings().profile'),saved.profile);
store.set('skachkov_plan_settings_v1','not valid JSON');
assert.equal(evalJs('readPlanSettings()'),null,'Corrupt configuration falls back to defaults');
assert(html.includes('id="resetPlanSettings"'));
assert(html.includes('await connect({resetToDefaults:true})'));
assert(html.includes('document.addEventListener(\'change\','));
assert(html.includes('const stored=resetToDefaults?null:readPlanSettings()'));
assert(!script.includes('POKER_RUNNER_KEY'),'Never persist management token');
console.log('Persistent Plan setup, nine seats, reset and baseline: PASS');
