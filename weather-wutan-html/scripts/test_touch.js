// jsdom 触摸/指针手势回归测试：验证「手机上单指轻点选点 + 双指捏合放大」可用
// 重点：模拟 pointerdown/pointermove/pointerup（iPhone/Android 现代浏览器都走 Pointer Events）
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

// 自动定位一个物探看板：从本脚本位置逐级上溯，取 <工作区>/beidou/wutan/html 下第一个 .html。
// 也可显式指定：<NODE> test_touch.js <某个看板.html>
function autoBoard() {
  let d = __dirname;
  for (let i = 0; i < 8; i++) {
    const c = path.join(d, "beidou", "wutan", "html");
    if (fs.existsSync(c)) {
      const names = fs.readdirSync(c).filter(n => n.endsWith(".html")).sort();
      if (names.length) return path.join(c, names[0]);
    }
    d = path.dirname(d);
  }
  return "";
}
const file = process.argv[2] || autoBoard();
if (!file || !fs.existsSync(file)) {
  console.error("未找到看板文件。请显式传入：<NODE> test_touch.js <某个看板.html>");
  process.exit(1);
}
const html = fs.readFileSync(file, "utf8");
const dom = new JSDOM(html, { runScripts: "dangerously", pretendToBeVisual: true, url: "http://localhost/" });
const w = dom.window, d = w.document;
const errs = [];
w.addEventListener("error", e => errs.push("window.error: " + e.message));
const origErr = w.console.error;
w.console.error = (...a) => { errs.push("console.error: " + a.join(" ")); origErr.apply(w.console, a); };

// ---- mock：canvas / 布局 / SVG 几何 ----
const mockCtx = new Proxy({}, { get: (t, k) => {
  if (k === "canvas") return { width: 680, height: 280 };
  if (k === "measureText") return () => ({ width: 30 });
  if (k === "createLinearGradient" || k === "createPattern") return () => ({ addColorStop(){} });
  if (k === "getImageData") return () => ({ data: new Uint8ClampedArray(4) });
  return () => {};
}, set: () => true });
w.HTMLCanvasElement.prototype.getContext = () => mockCtx;
Object.defineProperty(w.Element.prototype, "clientWidth", { get(){ return 680; }, configurable: true });
Object.defineProperty(w.Element.prototype, "clientHeight", { get(){ return 280; }, configurable: true });
w.Element.prototype.getBoundingClientRect = function(){ return { left:0, top:0, width:680, height:280, right:680, bottom:280, x:0, y:0 }; };

// SVG 需要的最小几何 API
const svgProto = w.SVGElement.prototype;
svgProto.createSVGPoint = function(){ const self=this; return { x:0, y:0, matrixTransform(m){ return { x:this.x, y:this.y }; } }; };
svgProto.getScreenCTM = function(){ return { inverse(){ const s=this; return { a:1,b:0,c:0,d:1,e:0,f:0 }; } }; };
if(!svgProto.setPointerCapture) svgProto.setPointerCapture = function(){};
if(!svgProto.releasePointerCapture) svgProto.releasePointerCapture = function(){};

// jsdom 没有 PointerEvent 构造器 —— 用普通 Event 带上指针字段
function pev(el, type, x, y, id, extra){
  const e = new w.Event(type, { bubbles:true, cancelable:true });
  e.clientX = x; e.clientY = y; e.pointerId = id === undefined ? 1 : id;
  e.pointerType = (extra && extra.pointerType) || "touch";
  e.button = 0; e.buttons = 1;
  if (extra) Object.keys(extra).forEach(k => { e[k] = extra[k]; });
  el.dispatchEvent(e);
  return e;
}
function tap(x, y){ const svg = d.getElementById("mapOverlay2");
  pev(svg,"pointerdown",x,y,1); pev(svg,"pointerup",x,y,1); }
function swipe(x0,y0,x1,y1){ const svg = d.getElementById("mapOverlay2");
  pev(svg,"pointerdown",x0,y0,1,{pointerType:"touch"});
  const n=6; for(let i=1;i<=n;i++){ const t=i/n;
    pev(svg,"pointermove",x0+(x1-x0)*t, y0+(y1-y0)*t, 1, {pointerType:"touch"}); }
  pev(svg,"pointerup",x1,y1,1,{pointerType:"touch"}); }
// 双指捏合：两指从 (mx-d/2, my) 展开到 (mx+d/2, my)，moves 步推进
function pinch(mx, my, d0, d1, moves){
  const svg = d.getElementById("mapOverlay2"); moves = moves || 8;
  const y = my;
  pev(svg,"pointerdown",mx-d0/2,y,1,{pointerType:"touch"});
  pev(svg,"pointerdown",mx+d0/2,y,2,{pointerType:"touch"});
  for(let i=1;i<=moves;i++){ const dd=d0+(d1-d0)*i/moves;
    pev(svg,"pointermove",mx-dd/2,y,1,{pointerType:"touch"});
    pev(svg,"pointermove",mx+dd/2,y,2,{pointerType:"touch"}); }
  pev(svg,"pointerup",mx-d1/2,y,1,{pointerType:"touch"});
  pev(svg,"pointerup",mx+d1/2,y,2,{pointerType:"touch"});
}

// 打开「未来48小时」页 → 渲染地图2
const t2 = d.querySelector('.tabbtn[data-tab="t2"]');
if (t2) t2.dispatchEvent(new w.Event("click", { bubbles:true }));

const R = [];
const ok = (name, cond, info) => R.push([cond ? "OK  " : "FAIL", name, info === undefined ? "" : String(info)]);

const svg2 = d.getElementById("mapOverlay2");
ok("地图2 已渲染", !!svg2 && svg2.childNodes.length > 5, svg2 && svg2.childNodes.length);
ok("touch-action 在 .mapbox 上", w.getComputedStyle(d.querySelector(".mapbox")).touchAction === "none",
   w.getComputedStyle(d.querySelector(".mapbox")).touchAction);

const px = w.POINT_PX2;
ok("POINT_PX2 采集点坐标就绪", Array.isArray(px) && px.length > 0, px && px.length);
const before = w.eval("SEL");
const p0 = px[0];
tap(p0.x, p0.y);
const afterTap = w.eval("SEL");
ok("单指轻点 → 选中采集点（手机选点可用）", afterTap >= 0 && afterTap !== before, "SEL=" + afterTap);
ok("选中环已画出", !!d.getElementById("selRing2"));
ok("风险面板已显示", d.getElementById("riskReason") && d.getElementById("riskReason").style.display !== "none");

// 复位
w.eval("selectPoint(-1)");
// 拖动：不应触发选点
swipe(100,140,260,200);
const afterDrag = w.eval("SEL");
ok("单指拖动 → 不误选点", afterDrag < 0, "SEL=" + afterDrag);
const V1 = JSON.stringify(w.eval("VIEW[2]"));
swipe(100,140,300,100);   // 再拖一次确认可连续平移
const V2 = JSON.stringify(w.eval("VIEW[2]"));
ok("单指拖动 → 视图中心改变（平移可用）", V1 !== V2, V1 + " -> " + V2);

// 双指张开 → 放大（这里最容易反向）
const sc0 = w.eval("VIEW[2].sc");
pinch(340, 140, 80, 240);
const sc1 = w.eval("VIEW[2].sc");
ok("双指张开 → 放大（倍率上升）", sc1 > sc0 * 1.2, sc0.toFixed(4) + " -> " + sc1.toFixed(4));

// 双指收拢 → 缩小
pinch(340, 140, 240, 60);
const sc2 = w.eval("VIEW[2].sc");
ok("双指收拢 → 缩小（倍率下降）", sc2 < sc1 * 0.9, sc1.toFixed(4) + " -> " + sc2.toFixed(4));

// 捏合后抬指不应误选
w.eval("selectPoint(-1)");
pinch(300, 120, 100, 260);
ok("捏合抬手 → 不误选点", w.eval("SEL") < 0, "SEL=" + w.eval("SEL"));

// 桌面鼠标路径仍可用
w.eval("selectPoint(-1)");
pev(svg2,"pointerdown",px[1].x,px[1].y,9,{pointerType:"mouse"});
pev(svg2,"pointerup",px[1].x,px[1].y,9,{pointerType:"mouse"});
ok("鼠标点击仍能选点（桌面不回归）", w.eval("SEL") === px[1].idx, "SEL=" + w.eval("SEL") + " expect=" + px[1].idx);

// 缩放按钮
const zoomIn = d.querySelector('#mapzoom2 button[data-z="in"]');
const s0 = w.eval("VIEW[2].sc");
zoomIn.dispatchEvent(new w.Event("click", { bubbles:true }));
ok("＋ 按钮放大", w.eval("VIEW[2].sc") > s0, s0.toFixed(3) + " -> " + w.eval("VIEW[2].sc").toFixed(3));

// iOS 手势拦截
let prevented = false;
const g = new w.Event("gesturestart", { bubbles:true, cancelable:true });
d.querySelector(".mapbox").dispatchEvent(g);
prevented = g.defaultPrevented;
ok("iOS gesturestart 在地图内被拦（整页不放大）", prevented);

console.log("");
console.log("  " + R.map(r => r[0] + "  " + r[1] + (r[2] ? "   [" + r[2] + "]" : "")).join("\n  "));
console.log("");
if (errs.length) { console.log("  运行期错误:"); errs.forEach(e => console.log("   - " + e)); }
const bad = R.filter(r => r[0] !== "OK  ").length;
console.log("  合计 " + R.length + " 项，失败 " + bad + "；运行期错误 " + errs.length);
process.exit(bad || errs.length ? 1 : 0);
