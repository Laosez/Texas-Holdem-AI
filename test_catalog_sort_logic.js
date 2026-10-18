'use strict';
/* Exercises the real catalogue sort helpers extracted from Plan HTML.
   No duplicate reimplementation of ranking logic in these tests. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync('replit_ui/plan.html','utf8');
const declarations=html.match(/let catalogSortColumn=[\s\S]*?\n\];/);
assert.ok(declarations,'catalog sorting registry must exist');
const begin=html.indexOf('function catalogSortFields(compare){');
const end=html.indexOf('function renderCatalogLedger(root,a,b,compare){',begin);
assert.ok(begin>0&&end>begin,'catalogue sorting helpers must exist');
const context={renderHandDecomposition:()=>{context.renders=(context.renders||0)+1}};
vm.createContext(context);
vm.runInContext(declarations[0]+'\n'+html.slice(begin,end)+
 '\nthis.sort=(rows)=>rows.sort(catalogCompareRows).map(row=>row.key);'+
 '\nthis.configure=(key,direction)=>{catalogSortColumn=key;catalogSortDirection=direction};'+
 '\nthis.state=()=>[catalogSortColumn,catalogSortDirection];'+
 '\nthis.sortValue=catalogSortValue;'+
 '\nthis.change=changeCatalogSort;'+
 '\nthis.fields=catalogSortFields;',context);
const samples=[
 {key:'F|a',label:'Альфа',a:{count:10,positive_ev_bb:0.6,negative_ev_bb:-0.4,contribution_bb:0.2},b:{count:40,positive_ev_bb:0.2,negative_ev_bb:-0.3,contribution_bb:-0.1}},
 {key:'F|b',label:'Бета',a:{count:30,positive_ev_bb:0.3,negative_ev_bb:-0.7,contribution_bb:-0.4},b:{count:20,positive_ev_bb:0.4,negative_ev_bb:-0.2,contribution_bb:0.2}},
 {key:'F|c',label:'Гамма',a:{count:20,positive_ev_bb:0.4,negative_ev_bb:-0.2,contribution_bb:0.2},b:{count:10,positive_ev_bb:0.3,negative_ev_bb:-0.2,contribution_bb:0.1}},
];
function check(metric,direction,expected){
 context.configure(metric,direction);
 assert.deepEqual([...context.sort(samples.slice())],expected,metric+' '+direction);
}
check('count:a','desc',['F|b','F|c','F|a']);
check('count:b','desc',['F|a','F|b','F|c']);
check('positive_ev_bb:a','desc',['F|a','F|c','F|b']);
check('negative_ev_bb:a','asc',['F|b','F|a','F|c']);
check('contribution_bb:b','desc',['F|b','F|c','F|a']);
check('delta','desc',['F|b','F|c','F|a']);
check('delta','asc',['F|a','F|c','F|b']);
check('label','asc',['F|a','F|b','F|c']);
const onlyA={key:'F|a',label:'Только A',a:{count:2,contribution_bb:-0.25}};
assert.equal(context.sortValue(onlyA,'count:b'),0);
assert.equal(context.sortValue(onlyA,'delta'),0.25);
assert.deepEqual(Array.from(context.fields(false),x=>x.key),
 ['label','count:a','positive_ev_bb:a','negative_ev_bb:a','contribution_bb:a']);
assert.equal(context.fields(true).length,10);
context.configure('count:a','desc');
context.change('count:a');
assert.deepEqual([...context.state()],['count:a','asc']);
context.change('negative_ev_bb:a');
assert.deepEqual([...context.state()],['negative_ev_bb:a','asc']);
assert.equal(context.renders,2);
console.log('Catalogue report sorting: 11 behavioral checks OK');
