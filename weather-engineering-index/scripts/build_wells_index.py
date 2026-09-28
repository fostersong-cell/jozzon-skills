#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_wells_index.py —— 石油工程「井位地图」index.html 生成器（未来 2 周窗口）
==========================================================================
本脚本从 weather-engineering-html 技能中拆出，专门负责「生成 index」这一件事。

原由 weather-engineering-html 的 build_dashboard.py 通过 --build-index /
--with-index 顺带产出，现已拆出为独立技能，便于「只重建井位地图目录页」。

输入：<datadir>/*.json（井位看板数据，由 weather-engineering-html 生成，
      meta.kind=="well"，取数窗口为未来 2 周 / 14 天）
输出：<outdir>/index.html —— 把所有井位点标在同一张地形图上，按风险配色，
      点击井位跳转到该井位的独立看板 html。

注意：index 显示的是未来 2 周窗口；井位页与 index 的等级均按 _sev 阈值（0绿/1黄/2橙/3红）。
"""
import os, sys, json, argparse, io, base64, datetime, re

# ======================================================================
#  内嵌中文字体子集（从 weather-engineering-html 一并迁入）
# ======================================================================
# ======================================================================
#  内嵌中文字体子集
# ======================================================================
def embed_font(html):
    try:
        from fontTools.ttLib import TTFont
        from fontTools import subset as ftsubset
        fnt = TTFont("/System/Library/Fonts/Hiragino Sans GB.ttc", fontNumber=0)
        chars = "".join(sorted(set(html)))
        ss = ftsubset.Subsetter(); ss.populate(text=chars); ss.subset(fnt)
        buf = io.BytesIO(); fnt.save(buf)
        b64 = base64.b64encode(buf.getvalue()).decode()
        font_css = ("@font-face{font-family:'CJKLocal';src:url('data:font/ttf;base64," + b64 + "') format('truetype');font-display:swap;}")
        html = html.replace("/*__FONT_FACE__*/", font_css)
        print("embedded CJK font:", len(buf.getvalue()), "bytes")
    except Exception as e:
        print("font embed FAILED:", repr(e)); html = html.replace("/*__FONT_FACE__*/", "")
    return html

# ======================================================================
#  HTML 模板：井位地图 index（汇总所有井位点）
# ======================================================================
INDEX_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>__TITLE__</title>
<style>
  /*__FONT_FACE__*/
  :root{
    --bg:#F6F4F0; --card:#FFFFFF; --line:#EAE6DF;
    --ink:#242A2E; --sub:#6B7378;
    --teal:#1F7A6B; --amber:#E0822C; --danger:#C0392B; --ok:#2E8B57;
    --shadow:0 1px 3px rgba(0,0,0,.06),0 6px 16px rgba(0,0,0,.05);
  }
  *{box-sizing:border-box;-webkit-tap-highlight-color:transparent;}
  html,body{margin:0;padding:0;}
  body{font-family:"CJKLocal",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif;
    background:var(--bg);color:var(--ink);line-height:1.5;font-size:16px;
    padding:14px 14px calc(28px + env(safe-area-inset-bottom));max-width:680px;margin:0 auto;}
  header{margin-bottom:12px;}
  header h1{font-size:19px;margin:0 0 2px;font-weight:700;}
  header .meta{font-size:12px;color:var(--sub);}
  .backlink{display:inline-block;margin-bottom:6px;font-size:13px;font-weight:600;color:var(--teal);text-decoration:none;
    border:1px solid var(--teal);border-radius:8px;padding:3px 10px;cursor:pointer;transition:background .15s,color .15s;}
  .backlink:hover{background:var(--teal);color:#fff;}
  .card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px;margin-bottom:12px;box-shadow:var(--shadow);}
  .card h2{font-size:16px;margin:0 0 10px;font-weight:700;display:flex;align-items:center;gap:8px;}
  .card h2 .dot{width:9px;height:9px;border-radius:50%;background:var(--teal);}
  .mapbox{position:relative;width:100%;height:360px;background:#ECE7DF;border-radius:10px;overflow:hidden;}
  .mapbox canvas,.mapbox svg{position:absolute;inset:0;width:100%;height:100%;}
  .mapbox{cursor:pointer;}
  .legend{display:flex;flex-wrap:wrap;gap:10px;font-size:12px;color:var(--sub);margin-top:8px;}
  .legend i{display:inline-block;width:14px;height:14px;border-radius:50%;vertical-align:middle;margin-right:5px;}
  .mapnote{position:absolute;left:8px;bottom:8px;background:rgba(255,255,255,.85);border-radius:8px;
    padding:5px 9px;font-size:11px;color:#3A4146;line-height:1.45;max-width:64%;pointer-events:none;}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px;}
  .wc{background:#FBFAF7;border:1px solid var(--line);border-radius:10px;padding:10px 12px;display:block;text-decoration:none;color:var(--ink);transition:border-color .15s;}
  .wc:hover{border-color:var(--teal);}
  .wc .nm{font-weight:700;font-size:14px;display:flex;align-items:center;gap:6px;}
  .wc .pr{font-size:11px;color:var(--sub);margin-top:2px;}
  .wc .sv{margin-top:6px;}
  .badge{font-size:11px;padding:2px 8px;border-radius:999px;font-weight:700;color:#fff;}
  .badge.ok{background:var(--ok);} .badge.warn{background:var(--amber);} .badge.danger{background:var(--danger);}
  .dotc{width:10px;height:10px;border-radius:50%;display:inline-block;}
</style>
</head>
<body>
<header>
  <a class="backlink" href="index.html">← 返回总览</a>
  <h1 id="titleH1">钻井工程井位天气看板</h1>
  <div class="meta" id="metaLine"></div>
</header>

<div class="card">
  <h2><span class="dot"></span>井位分布与风险</h2>
  <div class="legend">
    <span><i class="dotc" style="background:#C0392B"></i>高度警惕/重点关注</span>
    <span><i class="dotc" style="background:#E0822C"></i>需关注</span>
    <span><i class="dotc" style="background:#1F7A6B"></i>整体适宜</span>
    <span style="color:#6B7378">点击井位标记可进入该井位天气看板</span>
  </div>
  <div class="mapbox">
    <canvas id="mapCanvas" width="680" height="520"></canvas>
    <svg id="mapOverlay" viewBox="0 0 680 520" preserveAspectRatio="xMidYMid meet"></svg>
    <div class="mapnote" id="mapnote">共 __N__ 个井位 · 按风险着色</div>
  </div>
</div>

<div class="card">
  <h2><span class="dot"></span>所有井位点</h2>
  <div class="grid" id="wellGrid"></div>
</div>

<script>
const DATA = __DATA__;
const NS = "http://www.w3.org/2000/svg";
const INDEX_MODE = true;
const COLMAP = {ok:"#1F7A6B", warn:"#E0822C", danger:"#C0392B"};
document.getElementById("titleH1").textContent = DATA.meta.name + " · 井位天气看板";
document.getElementById("metaLine").textContent =
  `钻井工程 · 共 ${DATA.points.length} 个井位 · ${DATA.meta.start} ~ ${DATA.meta.end} · 数据 ${DATA.meta.gen} 生成`;
function el(tag, attrs){ const e=document.createElementNS(NS,tag); for(const k in attrs) e.setAttribute(k,attrs[k]); return e; }

function renderMap(){
  const lons=[], lats=[];
  DATA.points.forEach(p=>{ lons.push(p.lon); lats.push(p.lat); });
  if(!lons.length) return;
  const minlon=Math.min(...lons), maxlon=Math.max(...lons);
  const minlat=Math.min(...lats), maxlat=Math.max(...lats);
  const lat0=(minlat+maxlat)/2;
  const mb=document.querySelector(".mapbox");
  let W=Math.round((mb?mb.clientWidth:0)||680), pad=30, Hh=360;
  const lon2x=(lon,z)=>(lon+180)/360*256*Math.pow(2,z);
  const lat2y=(lat,z)=>{const r=lat*Math.PI/180; return (1-Math.log(Math.tan(Math.PI/4+r/2))/Math.PI)/2*256*Math.pow(2,z);};
  const spanLon=Math.max(maxlon-minlon,1e-6);
  let z=Math.round(Math.log2((W*0.7/256)*(360/spanLon)));
  z=Math.max(6,Math.min(z,15));
  const px0=lon2x(minlon,z), px1=lon2x(maxlon,z), py0=lat2y(maxlat,z), py1=lat2y(minlat,z);
  const mw=px1-px0, mh=py1-py0;
  let sc=Math.min((W-2*pad)/mw,(Hh-2*pad)/mh);
  if(!isFinite(sc)||sc<=0) sc=1;
  let DW=mw*sc, DH=mh*sc;
  const ox=(W-DW)/2, oy=(Hh-DH)/2;
  const xOf=(lon,lat)=>ox+(lon2x(lon,z)-px0)*sc;
  const yOf=(lon,lat)=>oy+(lat2y(lat,z)-py0)*sc;
  const cv=document.getElementById("mapCanvas"), ctx=cv.getContext("2d");
  cv.width=W; cv.height=Hh;
  ctx.fillStyle="#ECE7DF"; ctx.fillRect(0,0,W,Hh);
  const svg=document.getElementById("mapOverlay"); svg.setAttribute("viewBox","0 0 "+W+" "+Hh);
  const TILE=256;
  const mx0=px0-ox/sc, mx1=px0+(W-ox)/sc, my0=py0-oy/sc, my1=py0+(Hh-oy)/sc;
  const tx0=Math.floor(mx0/TILE), tx1=Math.floor(mx1/TILE);
  const ty0=Math.floor(my0/TILE), ty1=Math.floor(my1/TILE);
  for(let ty=ty0;ty<=ty1;ty++) for(let tx=tx0;tx<=tx1;tx++){
    const img=new Image(); img.crossOrigin="anonymous";
    img.src=`https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/${z}/${ty}/${tx}`;
    const sx=ox+(tx*TILE-px0)*sc, sy=oy+(ty*TILE-py0)*sc, sw=TILE*sc, sh=TILE*sc;
    img.onload=()=>{ ctx.drawImage(img,sx,sy,sw,sh); };
    img.onerror=()=>{ ctx.fillStyle="rgba(205,210,215,0.6)"; ctx.fillRect(sx,sy,sw,sh); };
  }
  svg.innerHTML="";
  for(let gx=(ox%64+64)%64; gx<W; gx+=64)
    svg.appendChild(el("line",{x1:gx,y1:0,x2:gx,y2:Hh,stroke:"rgba(255,255,255,.28)",["stroke-width"]:1}));
  for(let gy=(oy%64+64)%64; gy<Hh; gy+=64)
    svg.appendChild(el("line",{x1:0,y1:gy,x2:W,y2:gy,stroke:"rgba(255,255,255,.28)",["stroke-width"]:1}));
  window.POINT_PX=[]; window.POINT_ELS=[]; window.POINT_DATA=DATA.points;
  DATA.points.forEach((pt,i)=>{
    const c=COLMAP[pt.risk], cx2=xOf(pt.lon,pt.lat), cy2=yOf(pt.lon,pt.lat);
    const circ=el("circle",{cx:cx2,cy:cy2,r:pt.risk==="ok"?9:(pt.risk==="warn"?10:11),fill:c,stroke:"#fff",["stroke-width"]:2});
    circ.style.cursor="pointer";
    circ.addEventListener("click",()=>{ if(INDEX_MODE && pt.href) location.href=pt.href; else selectPoint(i); });
    svg.appendChild(circ);
    const lab=el("text",{x:cx2,y:cy2-15,["text-anchor"]:"middle","font-size":13,fill:"#111",["font-weight"]:"700",
      stroke:"#fff",["stroke-width"]:3,["paint-order"]:"stroke"});
    lab.textContent=pt.loc||("井位"+(i+1));
    lab.style.cursor="pointer";
    lab.addEventListener("click",()=>{ if(INDEX_MODE && pt.href) location.href=pt.href; else selectPoint(i); });
    svg.appendChild(lab);
    window.POINT_PX.push({x:cx2,y:cy2,idx:i});
    window.POINT_ELS.push({idx:i, circ, lab, x:cx2, y:cy2});
  });
  const gkm=DATA.meta.gridKm||20;
  const pxKm=256*Math.pow(2,z)/(360*111*Math.cos(lat0*Math.PI/180))*sc;
  let barLen=Math.min(gkm*pxKm, W-ox-20), bx=ox, by=Hh-12;
  svg.appendChild(el("line",{x1:bx,y1:by,x2:bx+barLen,y2:by,stroke:"#222",["stroke-width"]:3}));
  const bt=el("text",{x:bx+barLen/2,y:by-5,["text-anchor"]:"middle","font-size":11,fill:"#222",["font-weight"]:"700"}); bt.textContent=gkm+" km"; svg.appendChild(bt);
  const na_bx=W-pad-36, na_by=pad+60, L=32, ah=16, aw=Math.PI/6.5;
  const tipx=na_bx, tipy=na_by-L;
  svg.appendChild(el("circle",{cx:na_bx,cy:na_by,r:20,fill:"rgba(255,255,255,.85)",stroke:"#333",["stroke-width"]:1.5}));
  svg.appendChild(el("line",{x1:na_bx,y1:na_by+7,x2:tipx,y2:tipy,stroke:"#222",["stroke-width"]:4.5,["stroke-linecap"]:"round"}));
  const a1x=tipx-ah*Math.cos(Math.PI/2-aw), a1y=tipy+ah*Math.sin(Math.PI/2-aw);
  const a2x=tipx+ah*Math.cos(Math.PI/2-aw), a2y=tipy+ah*Math.sin(Math.PI/2-aw);
  svg.appendChild(el("path",{d:`M${tipx.toFixed(1)} ${tipy.toFixed(1)} L${a1x.toFixed(1)} ${a1y.toFixed(1)} L${a2x.toFixed(1)} ${a2y.toFixed(1)} Z`,fill:"#C0392B",stroke:"#7a1f17",["stroke-width"]:1}));
  const nt=el("text",{x:na_bx,y:na_by-L-13,["text-anchor"]:"middle","font-size":16,fill:"#C0392B",["font-weight"]:"800"}); nt.textContent="N"; svg.appendChild(nt);
  svg.style.cursor="pointer";
  if(!svg._mapClick){ svg._mapClick=function(ev){
    const ptN=svg.createSVGPoint(); ptN.x=ev.clientX; ptN.y=ev.clientY;
    const loc=ptN.matrixTransform(svg.getScreenCTM().inverse());
    let best=-1, bd=1e9;
    window.POINT_PX.forEach(p=>{ const d=Math.hypot(p.x-loc.x,p.y-loc.y); if(d<bd){bd=d; best=p.idx;} });
    if(best>=0 && bd<=28){ if(INDEX_MODE && window.POINT_DATA[best].href) location.href=window.POINT_DATA[best].href; else selectPoint(best); }
  }; svg.addEventListener("click", svg._mapClick); }
}
function selectPoint(i){ const p=DATA.points[i]; if(p && p.href) location.href=p.href; }
// 井位列表
(function(){
  const grid=document.getElementById("wellGrid");
  grid.innerHTML = DATA.wells.map(w=>{
    const col={ok:"#1F7A6B",warn:"#E0822C",danger:"#C0392B"}[w.sevCls];
    return `<a class="wc" href="${w.href}">
      <div class="nm"><span class="dotc" style="background:${col}"></span>${w.name}</div>
      <div class="pr">${w.project||""}</div>
      <div class="sv"><span class="badge ${w.sevCls}">${w.sevLabel}</span></div></a>`;
  }).join("");
})();
renderMap();
</script>
</body>
</html>
"""


# ======================================================================
#  主流程：由井位 *_data.json 重建井位地图 index.html（离线，不取数）
# ======================================================================
def main():
    ap = argparse.ArgumentParser(
        description="由井位 JSON 生成「井位地图」index.html（未来 2 周窗口）")
    ap.add_argument("--datadir", required=True, help="井位 *_data.json 所在目录")
    ap.add_argument("--outdir", default="", help="index.html 输出目录（默认=datadir）")
    ap.add_argument("--name", default="钻井工程", help="标题中的项目/区域名称")
    ap.add_argument("--start", default="", help="窗口开始日（默认取数据 meta.start）")
    ap.add_argument("--end", default="", help="窗口结束日（默认取数据 meta.end）")
    args = ap.parse_args()

    dj = os.path.abspath(args.datadir)
    outdir = os.path.abspath(args.outdir) if args.outdir else dj
    if not os.path.isdir(dj):
        print("⚠️ 数据目录不存在:", dj); sys.exit(1)
    os.makedirs(outdir, exist_ok=True)

    today = datetime.datetime.now().strftime("%Y-%m-%d")
    wells_meta = []
    for fn in sorted(os.listdir(dj)):
        if not fn.endswith("_data.json"):
            continue
        d = json.load(open(os.path.join(dj, fn), encoding="utf-8"))
        p = d["points"][0]
        wells_meta.append({
            "idx": len(wells_meta), "lon": p["lon"], "lat": p["lat"],
            "isCenter": False, "risk": p["risk"], "loc": d["meta"]["name"],
            "href": fn.replace("_data.json", ".html"),
            "sev": d["meta"]["sev"], "sevLabel": d["meta"]["sevLabel"],
            "project": d.get("project", ""),
        })
    if not wells_meta:
        print("⚠️ 在", dj, "未发现井位 *_data.json"); sys.exit(1)

    # 窗口起止：优先命令行，其次取任一份数据的 meta
    START_DATE, END_DATE = args.start, args.end
    if not (START_DATE and END_DATE):
        try:
            any_fn = sorted(f for f in os.listdir(dj) if f.endswith("_data.json"))[0]
            anyd = json.load(open(os.path.join(dj, any_fn), encoding="utf-8"))
            START_DATE = START_DATE or anyd["meta"].get("start", "")
            END_DATE = END_DATE or anyd["meta"].get("end", "")
        except Exception:
            pass

    index_payload = {
        "meta": {"name": args.name, "kind": "wellmap", "npts": len(wells_meta),
                 "gridKm": 20, "start": START_DATE, "end": END_DATE, "gen": today,
                 "model": "open-meteo 默认融合模型", "dailyDates": []},
        "polygon": [], "line": [], "lines": None, "dataLines": None, "isLine": False,
        "points": wells_meta, "elevGrid": None,
        "hourly": {"time": [], "tempMin": [], "tempMax": [], "precipMax": [],
                   "rainMax": [], "windMax": [], "gustMax": []},
        "daily": [], "peaks": {},
        "wells": [{"name": w["loc"], "project": w["project"], "href": w["href"],
                   "sev": w["sev"], "sevLabel": w["sevLabel"],
                   "sevCls": {0: "ok", 1: "warn", 2: "danger", 3: "danger"}[w["sev"]]}
                  for w in wells_meta],
    }
    DATA_JSON = json.dumps(index_payload, ensure_ascii=False)
    html = INDEX_TEMPLATE.replace("__DATA__", DATA_JSON).replace("__TITLE__", f"{args.name} · 井位天气看板")
    html = html.replace("__N__", str(len(wells_meta)))
    html = embed_font(html)
    out = os.path.join(outdir, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  ✓ index.html（井位地图，共 {len(wells_meta)} 个井位，窗口 {START_DATE} ~ {END_DATE}）")
    print("INDEX written:", out, len(html), "bytes")
    print("DONE")


if __name__ == "__main__":
    main()
