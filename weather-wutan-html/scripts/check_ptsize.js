// 校验：渲染后采集点圆点半径确实变小（≤8），且 updatePoints 改色时半径不跳
const fs=require("fs");
const {JSDOM}=require("jsdom");
const f=process.argv[2];
const html=fs.readFileSync(f,"utf8");
const dom=new JSDOM(html,{runScripts:"dangerously",pretendToBeVisual:true,url:"https://x.test/"});
const w=dom.window, d=w.document;
const errs=[]; w.addEventListener("error",e=>errs.push(String(e.error||e.message)));
w.HTMLCanvasElement.prototype.getContext=()=>({fillRect(){},drawImage(){},clearRect(){},beginPath(){},arc(){},fill(){},stroke(){},save(){},restore(){},setTransform(){},measureText:()=>({width:20})});
setTimeout(()=>{
  // 地图是 Tab 首次激活时才渲染的（与 test_touch.js 同）
  const t2=d.querySelector('.tabbtn[data-tab="t2"]');
  if(t2) t2.dispatchEvent(new w.Event("click",{bubbles:true}));
  const o=d.getElementById("mapOverlay2");
  const circles=Array.from(o.querySelectorAll("circle")).filter(c=>c.getAttribute("r")&&+c.getAttribute("r")<=12);
  // 采集点圆点：有 cursor:pointer 的
  const dots=Array.from(o.querySelectorAll("circle")).filter(c=>c.style.cursor==="pointer");
  const rs=[...new Set(dots.map(c=>+c.getAttribute("r")))].sort((a,b)=>a-b);
  const ring=o.querySelector("circle[id^='selRing']");
  // 触发 updatePoints 逐小时改色：半径只能落在 PT_R 三档内（旧值 9/10/11 属回归）
  w.eval("updatePoints(6,'2')");
  const after=dots.map(c=>+c.getAttribute("r"));
  const jump=after.some(v=>![6.4,7.2,8.0].includes(v));
  let P=0,F=0;
  const ok=(n,c,extra)=>{ P++; if(c) console.log("  OK   "+n+(extra?"   ["+extra+"]":"")); else {F++; console.log("  BAD  "+n+(extra?"   ["+extra+"]":"")); } };
  ok("无运行期错误", errs.length===0, errs.join("|"));
  ok("采集点圆点已画出", dots.length>0, dots.length+" 个");
  ok("圆点半径已缩小（最大 ≤8）", rs.length>0 && Math.max(...rs)<=8, "半径档位 "+JSON.stringify(rs));
  ok("半径不再有旧值 9/10/11", !rs.some(v=>v>=9), JSON.stringify(rs));
  // 中心点菱形（只有带 isCenter 的项目才有，如通江三维/乐山二维；藏北天山这类纯测线项目本就没有）
  const rects=Array.from(o.querySelectorAll("rect")).filter(r=>+r.getAttribute("width")<=14);
  const hasC=w.eval("DATA.points.some(p=>p.isCenter)");
  if(hasC) ok("中心点菱形已缩小（宽 ≤14）", rects.length>0, rects.length+" 个");
  else console.log("  --   中心点菱形：本项目无 isCenter 采集点，跳过");
  ok("updatePoints 改色后半径仍在 PT_R 三档内", !jump, "实际 " + JSON.stringify([...new Set(after)]));
  console.log("\n  合计 "+P+" 项，失败 "+F+"\n");
  process.exit(F?1:0);
},900);
