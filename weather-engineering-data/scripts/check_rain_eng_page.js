/* 页面级校验：石油工程点位看板的小时级短时降水（jsdom）
 * 用法：NODE_PATH=... node check_rain_eng_page.js <点位看板.html>
 * 1) 原样加载：无运行期错误、读数框用 mm/h
 * 2) 把 48h 降水序列整体抬到 9.9mm/h：图上应画出 3 条阈值线 + 标签
 */
const fs = require("fs");
const { JSDOM } = require("jsdom");

const f = process.argv[2];
const base = fs.readFileSync(f, "utf8");
let fails = 0;
const ok = (c, n, d) => {
  console.log((c ? "  ✅ " : "  ❌ ") + n + (d ? "　— " + d : ""));
  if (!c) fails++;
};

function boot(html) {
  const errs = [];
  const dom = new JSDOM(html, { runScripts: "dangerously", pretendToBeVisual: true, url: "http://localhost/" });
  const w = dom.window, d = w.document;
  w.addEventListener("error", e => errs.push(e.message));
  const mockCtx = new Proxy({}, {
    get: (t, k) => (k === "canvas" ? { width: 680, height: 280 }
      : k === "measureText" ? () => ({ width: 30 }) : () => {}),
    set: () => true
  });
  w.HTMLCanvasElement.prototype.getContext = () => mockCtx;
  Object.defineProperty(w.Element.prototype, "clientWidth", { get() { return 680; }, configurable: true });
  Object.defineProperty(w.Element.prototype, "clientHeight", { get() { return 280; }, configurable: true });
  w.Element.prototype.getBoundingClientRect = function () {
    return { left: 0, top: 0, width: 680, height: 280, right: 680, bottom: 280, x: 0, y: 0 };
  };
  w.SVGElement.prototype.createSVGPoint = function () {
    return { x: 0, y: 0, matrixTransform() { return { x: this.x, y: this.y }; } };
  };
  w.SVGElement.prototype.getScreenCTM = function () {
    return { inverse() { return { a: 1, b: 0, c: 0, d: 1, e: 0, f: 0 }; } };
  };
  if (!w.SVGElement.prototype.setPointerCapture) w.SVGElement.prototype.setPointerCapture = function () {};
  return { w, d, errs };
}

console.log("== 原样加载：" + require("path").basename(f));
let r = boot(base);
setTimeout(() => {
  ok(r.errs.length === 0, "无运行期错误", r.errs.join(" | ").slice(0, 120));
  const vb = r.d.getElementById("hval");
  ok(vb && /mm\/h/.test(vb.textContent), "读数框降水单位 mm/h", vb ? vb.textContent.trim().slice(0, 60) : "null");

  console.log("== 抬到 12mm/h（48h 逐小时图，量程覆盖到 10mm/h 阈值）");
  // 只改 precip 数组的数值（保留长度），并把 ptype 置 0
  const m = base.match(/precip:(\[[0-9.,\s]+\])/);
  ok(!!m, "找到 48h 降水数组");
  if (m) {
    const n = m[1].split(",").length;
    const lifted = "precip:[" + Array(n).fill("12").join(", ") + "]";
    const html2 = base.replace(m[0], lifted);
    let r2 = boot(html2);
    setTimeout(() => {
      ok(r2.errs.length === 0, "抬值后无运行期错误", r2.errs.join(" | ").slice(0, 120));
      const svg = r2.d.getElementById("hchart");
      const lines = Array.from(svg.querySelectorAll("line")).filter(l => l.getAttribute("stroke-dasharray") === "5 4");
      ok(lines.length >= 3, "画出 3 条阈值线", lines.length + " 条");
      const txts = Array.from(svg.querySelectorAll("text")).map(t => t.textContent);
      ["大雨 2 mm/h", "暴雨 5 mm/h", "大暴雨 10 mm/h"].forEach(t =>
        ok(txts.indexOf(t) >= 0, "阈值线标签 " + t, ""));
      // 触发拖动/点击选时，读数框仍为 mm/h
      const ev = new r2.w.MouseEvent("pointerdown", { clientX: 300, clientY: 100, bubbles: true });
      svg.dispatchEvent(ev);
      const vb2 = r2.d.getElementById("hval");
      ok(vb2 && /mm\/h/.test(vb2.textContent), "选时后读数框仍 mm/h", vb2 ? vb2.textContent.trim().slice(0, 60) : "null");

      console.log();
      console.log(fails ? "❌ " + fails + " 项失败" : "✅ 页面级全部通过");
      process.exit(fails ? 1 : 0);
    }, 500);
  } else { process.exit(1); }
}, 500);
