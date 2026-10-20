'use strict';
const assert=require('assert');
const fs=require('fs');
const vm=require('vm');
const source=fs.readFileSync('replit_ui/plan.html','utf8');
function extract(start,end){
 const a=source.indexOf(start),b=source.indexOf(end,a+start.length);
 assert(a>=0&&b>a,'Graph function not found: '+start);
 return source.slice(a,b);
}
function node(tag){
 return {tag,attrs:{},children:[],textContent:'',classList:{toggle(){}},
  setAttribute(k,v){this.attrs[k]=String(v)},
  append(...children){this.children.push(...children)},
  replaceChildren(...children){this.children=[...children]}};
}
const chart=node('div'),legend=node('div'),note=node('p');
const document={
 createElementNS:(ns,tag)=>node(tag),
 querySelector:()=>note,
};
const ctx={
 document,
 $:id=>id==='handDecompChartAB'?chart:legend,
 el:(tag,cls,text)=>{const x=node(tag);x.textContent=text;return x},
 decompSideRequest:()=>null,
};
const functions=[
 extract('function renderFlatShowdownEvChart(', 'function renderFlatBoard150('),
 extract('function opponentEvChartPoints(', 'function renderHandDecomposition(')
].join('\n');
vm.runInNewContext(functions,ctx);
const elements=(parent,tag)=>parent.children.flatMap(x=>x.tag==='svg'?x.children:[]).filter(x=>x.tag===tag);
const plotlines=()=>elements(chart,'line').filter(x=>x.attrs.stroke==='#8dc5f4'||x.attrs.stroke==='#cfb3f2');
const dots=()=>elements(chart,'circle');
const row=(k,n,net)=>({dims:['river','board',null,null,k,'W1'],a:{n,net},b:{n:0,net:0}});
ctx.renderFlatShowdownEvChart([row(0,10,5),row(1,12,-4),row(3,11,1)],false,'all');
assert.equal(dots().length,3,'Three measured showdown buckets must render three markers');
assert.equal(plotlines().length,2,'Three measured buckets must be joined by two visible strokes');
assert.equal(plotlines()[1].attrs['stroke-dasharray'],'5 5','Missing bucket must be dashed');
assert.equal(plotlines()[0].attrs['stroke-dasharray'],undefined,'Adjacent observations are solid');
const aBuckets=[1,2,3,4].map((opponents,i)=>({opponents,samples:40,ev_bb:[.3,-.2,.4,.1][i]}));
ctx.renderOpponentEvComparison({buckets:aBuckets},null);
assert.equal(dots().length,4,'Four real EV points');
assert.equal(plotlines().length,3,'Four continuous EV points must connect');
ctx.renderOpponentEvComparison({buckets:[aBuckets[0],aBuckets[2]]},null);
assert.equal(dots().length,2,'Sparse EV retains two points');
assert.equal(plotlines().length,1,'Sparse EV connects the two measured points');
assert.equal(plotlines()[0].attrs['stroke-dasharray'],'5 5','Sparse categories must show dashed bridge');
console.log('Plan EV point-and-line chart behavioral tests: PASS');
