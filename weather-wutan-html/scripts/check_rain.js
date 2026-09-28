// 校验「小时级短时降水」规则：>2 大雨 / >5 暴雨 / >10 大暴雨 是否真的驱动 48h 风险判定与影响卡片
// 做法：把产物里的 peaksNear.pHourMax 改成指定值，看 48h「降水 / 短时强降水」卡片文案与等级是否跟着变
const fs=require("fs");
const {JSDOM}=require("jsdom");
const src=process.argv[2];
const cases=[
  {ph:0.0,  want:"ok"},
  {ph:1.2,  want:"ok"},
  {ph:2.5,  want:"warn"},
  {ph:6.0,  want:"danger-card"},
  {ph:12.0, want:"torrent-card"},
];
const base=fs.readFileSync(src,"utf8");
const m=base.match(/("peaksNear":\s*\{[^}]*\})/);
if(!m){ console.log("  找不到 peaksNear"); process.exit(1); }
let P=0,F=0;
const ok=(n,c,extra)=>{P++; if(c) console.log("  OK   "+n+(extra?"   ["+extra+"]":"")); else {F++; console.log("  BAD  "+n+(extra?"   ["+extra+"]":"")); }};

function run(ph){
  const html=base.replace(m[1], m[1].replace(/("pHourMax":\s*)[0-9.]+/, `$1${ph}`));
  return new Promise(res=>{
    const dom=new JSDOM(html,{runScripts:"dangerously",pretendToBeVisual:true,url:"http://localhost/"});
    const w=dom.window,d=w.document;
    const errs=[]; w.addEventListener("error",e=>errs.push(String(e.error||e.message)));
    const mockCtx=new Proxy({},{get:(t,k)=>{ if(k==="canvas")return{width:680,height:280}; if(k==="measureText")return()=>({width:30}); return()=>{};},set:()=>true});
    w.HTMLCanvasElement.prototype.getContext=()=>mockCtx;
    Object.defineProperty(w.Element.prototype,"clientWidth",{get(){return 680;},configurable:true});
    Object.defineProperty(w.Element.prototype,"clientHeight",{get(){return 280;},configurable:true});
    w.Element.prototype.getBoundingClientRect=function(){return{left:0,top:0,width:680,height:280,right:680,bottom:280,x:0,y:0};};
    const sp=w.SVGElement.prototype;
    sp.createSVGPoint=function(){return{x:0,y:0,matrixTransform(){return{x:this.x,y:this.y};}};};
    sp.getScreenCTM=function(){return{inverse(){return{a:1,b:0,c:0,d:1,e:0,f:0};}};};
    setTimeout(()=>{
      const box=d.getElementById("impactBox");
      // 找「降水 / 短时强降水」那张卡
      let card=null;
      Array.from(box.querySelectorAll(".imp")).forEach(c=>{ if(/降水|短时大雨/.test(c.querySelector(".h").textContent)) card=c; });
      res({errs, card, ph: w.eval("PN.pHourMax"), sev: w.document.body.className});
    },800);
  });
}
(async()=>{
  for(const c of cases){
    const r=await run(c.ph);
    const t=r.card? r.card.textContent.replace(/\s+/g,"") : "(无卡片)";
    const cls=r.card? (r.card.className.match(/danger|warn/)||["ok"])[0] : "none";
    let good=false;
    if(c.want==="ok") good = cls==="ok" && /间歇小雨/.test(t);
    if(c.want==="warn") good = cls==="warn" && /短时大雨/.test(r.card.textContent);
    if(c.want==="danger-card") good = cls==="warn" && /最大小时降水6mm\/h/.test(t) && /暴雨/.test(t);
    if(c.want==="torrent-card") good = cls==="danger" && /12mm\/h/.test(t) && /大暴雨/.test(t);
    ok(`pHourMax=${c.ph} → ${c.want}`, good && r.errs.length===0, cls+" | "+t.slice(0,58)+" | errs="+JSON.stringify(r.errs).slice(0,120));
  }
  // 逐小时风险分级：直接调 riskClassAtHour 造数
  const html=base.replace(m[1], m[1].replace(/("pHourMax":\s*)[0-9.]+/, '$16.0'));
  const dom=new JSDOM(html,{runScripts:"dangerously",pretendToBeVisual:true,url:"http://localhost/"});
  const w=dom.window;
  const mockCtx=new Proxy({},{get:(t,k)=>{ if(k==="canvas")return{width:680,height:280}; if(k==="measureText")return()=>({width:30}); return()=>{};},set:()=>true});
  w.HTMLCanvasElement.prototype.getContext=()=>mockCtx;
  Object.defineProperty(w.Element.prototype,"clientWidth",{get(){return 680;},configurable:true});
  Object.defineProperty(w.Element.prototype,"clientHeight",{get(){return 280;},configurable:true});
  w.Element.prototype.getBoundingClientRect=function(){return{left:0,top:0,width:680,height:280,right:680,bottom:280,x:0,y:0};};
  w.SVGElement.prototype.createSVGPoint=function(){return{x:0,y:0,matrixTransform(){return{x:this.x,y:this.y};}};};
  w.SVGElement.prototype.getScreenCTM=function(){return{inverse(){return{a:1,b:0,c:0,d:1,e:0,f:0};}};};
  await new Promise(r=>setTimeout(r,700));
  const pt=w.eval("DATA.points.find(p=>p.hx)");
  const fake=JSON.parse(JSON.stringify(pt));
  const probe=v=>{ const p=JSON.parse(JSON.stringify(pt)); delete p.hx; p.hx={precip:[v],gust:[0],temp:[20],wind:[0]}; return w.eval("riskClassAtHour")(p,0); };
  const f2=(()=>{ const p=JSON.parse(JSON.stringify(pt)); delete p.hx; p.hx={precip:[0],gust:[0],temp:[20],wind:[0]}; return w.eval("riskFactorsAtHour")(p,0); })();
  ok("1.0mm/h → ok", probe(1.0)==="ok", probe(1.0));
  ok("2.0mm/h（≥大雨）→ warn", probe(2.0)==="warn", probe(2.0));
  ok("4.9mm/h → warn", probe(4.9)==="warn", probe(4.9));
  ok("5.0mm/h（≥暴雨）→ danger", probe(5.0)==="danger", probe(5.0));
  ok("10mm/h（大暴雨）→ danger", probe(10)==="danger", probe(10));
  const p7=JSON.parse(JSON.stringify(pt)); delete p7.hx; p7.hx={precip:[7],gust:[0],temp:[20],wind:[0]};
  const f7=w.eval("riskFactorsAtHour")(p7,0);
  ok("7mm/h 要素名＝短时暴雨", f7.some(x=>x.name==="短时暴雨"&&x.unit==="mm/h"), f7.map(x=>x.name+"/"+x.unit).join(","));
  const p12=JSON.parse(JSON.stringify(pt)); delete p12.hx; p12.hx={precip:[12],gust:[0],temp:[20],wind:[0]};
  const f12=w.eval("riskFactorsAtHour")(p12,0);
  ok("12mm/h 要素名＝短时大暴雨", f12.some(x=>x.name==="短时大暴雨"), f12.map(x=>x.name).join(","));
  const p03=JSON.parse(JSON.stringify(pt)); delete p03.hx; p03.hx={precip:[0.3],gust:[0],temp:[20],wind:[0]};
  const f03=w.eval("riskFactorsAtHour")(p03,0);
  ok("0.3mm/h → 小雨要素", f03.some(x=>x.name==="降水"), f03.map(x=>x.name).join(","));
  console.log("\n  合计 "+P+" 项，失败 "+F+"\n");
  process.exit(F?1:0);
})();
