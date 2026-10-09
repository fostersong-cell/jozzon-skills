# -*- coding: utf-8 -*-
"""
物探项目两周天气看板生成器（单文件版）

用法:
  python build_weather_dashboard.py --name "大关项目" --lat 27.91 --lon 103.87 --outdir "."

输出:
  {outdir}/{name}{today}.pdf        (窄页 ~114mm 宽、大字体、含中文的 PDF)
  {outdir}/{name}.html              (同数据中文字体已内嵌的可离线 HTML)

说明:
  - 从 Open-Meteo 拉取「当前日期起 14 天」逐小时预报
  - 要素: 气温(2m)、降水(雨+阵雨+雪)、降雨、风速(10m)、阵风(10m)
  - 自动识别连续降雨窗口、极端天气阈值(高温/低温/暴雨/大风)
  - 输出物探作业影响与建议卡片
  - 用本机 Google Chrome 无头模式导出窄页 PDF，并内嵌中文字体子集(解决无头模式中文空白问题)
依赖(managed venv): openpyxl(可选, 本脚本不写 excel), fonttools, websocket-client
"""
import argparse, json, subprocess, os, sys, time, base64, io, urllib.request, urllib.parse
from datetime import datetime
from collections import defaultdict

# ---------- 参数 ----------
ap = argparse.ArgumentParser()
ap.add_argument("--name", required=True, help="项目名称，如 大关项目")
ap.add_argument("--lat", required=True, type=float, help="纬度")
ap.add_argument("--lon", required=True, type=float, help="经度")
ap.add_argument("--outdir", default=".", help="输出目录，默认当前目录")
ap.add_argument("--days", type=int, default=14, help="预报天数，默认 14")
ap.add_argument("--apikey", default="6aiF2mXsB3K7YcjT", help="Open-Meteo API key(免费接口可不填)")
ap.add_argument("--chrome", default="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                help="Chrome 可执行文件路径")
args = ap.parse_args()

today = datetime.now().strftime("%Y-%m-%d")
base = os.path.abspath(args.outdir)
os.makedirs(base, exist_ok=True)
html_path = os.path.join(base, f"{args.name}.html")
pdf_path = os.path.join(base, f"{args.name}{today}.pdf")

# ---------- 1. 拉取预报 ----------
# precipitation=总降水(mm) / rain=雨(mm) / showers=阵雨(mm) / snowfall=降雪(cm)
# liquid=rain+showers 为「降雨」规范口径；ptype=降水类型码（0无/1降雨/2降雪/3雨夹雪）
HOURLY = ("temperature_2m,precipitation,rain,showers,snowfall,"
          "wind_speed_10m,wind_gusts_10m")
BASE = "https://api.open-meteo.com/v1/forecast"
params = (f"latitude={args.lat}&longitude={args.lon}"
          f"&hourly={HOURLY}&forecast_days={args.days}"
          f"&wind_speed_unit=ms"
          f"&timezone=Asia%2FShanghai&apikey={args.apikey}")
url = f"{BASE}?{params}"
print("Fetching:", url)
req = urllib.request.Request(url, headers={"User-Agent": "workbuddy-weather/1.0"})
with urllib.request.urlopen(req, timeout=60) as resp:
    data = json.loads(resp.read().decode("utf-8"))
h = data["hourly"]
times = [str(x) for x in h["time"]]
def col(k):
    return [ (float(v) if isinstance(v, (int, float)) else 0.0) for v in h[k] ]
temp = col("temperature_2m"); precip = col("precipitation")
rain = col("rain"); wind = col("wind_speed_10m"); gust = col("wind_gusts_10m")
showers = col("showers"); snowfall = col("snowfall")
liquid = [round(r + s, 2) for r, s in zip(rain, showers)]     # 降雨 = 雨 + 阵雨

def ptype_of(liq, snow, pr, temp=None):
    """降水类型码：0=无 1=降雨 2=降雪 3=雨夹雪（snowfall 单位 cm，仅以 >0 判有无）
    温度规则（2026-10-08 起）：temp < 0℃ 一律判降雪；temp ≥ 0℃ 且雨雪同现才判雨夹雪。"""
    has_l, has_s = liq > 0.05, snow > 0.01
    if temp is not None and temp < 0.0:
        return 2 if (has_l or has_s or pr > 0.05) else 0
    if has_l and has_s: return 3
    if has_s: return 2
    if has_l: return 1
    return 1 if pr > 0.05 else 0

ptype = [ptype_of(l, s, p, tv) for l, s, p, tv in zip(liquid, snowfall, precip, temp)]
print(f"Got {len(times)} hourly rows")

# 日降水聚合
d = defaultdict(float)
for t, p in zip(times, precip):
    d[t[:10]] += p
daily = [{"date": k, "p": round(v, 1)} for k, v in sorted(d.items())]
focus_days = [x for x in daily if x["p"] >= 10]
focus_total = round(sum(x["p"] for x in focus_days), 1)
peak = max(focus_days, key=lambda x: x["p"]) if focus_days else None

payload = {
    "meta": {"name": args.name, "lat": args.lat, "lon": args.lon,
             "start": times[0][:10], "end": times[-1][:10], "gen": today},
    "hourly": {"time": times, "temp": temp, "precip": precip,
               "rain": rain, "showers": showers, "snowfall": snowfall,
               "liquid": liquid, "ptype": ptype,
               "wind": wind, "gust": gust},
    "daily": daily,
    "peaks": {
        "tmax": max(temp), "tmin": min(temp),
        "gustMax": max(gust), "windMax": max(wind),
        "pHourMax": max(precip),
        "pMaxDay": peak["date"] if peak else None,
        "pMax": peak["p"] if peak else 0,
        "focusTotal": focus_total,
        "focusStart": focus_days[0]["date"] if focus_days else None,
        "focusEnd": focus_days[-1]["date"] if focus_days else None,
    },
}
DATA_JSON = json.dumps(payload, ensure_ascii=False)

# ---------- 2. HTML 模板 ----------
TEMPLATE = r"""<!DOCTYPE html>
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
  body{
    font-family:"CJKLocal",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif;
    background:var(--bg); color:var(--ink); line-height:1.5; font-size:16px;
    padding:14px 14px calc(28px + env(safe-area-inset-bottom));
    max-width:430px; margin:0 auto;
  }
  header{margin-bottom:12px;}
  header h1{font-size:19px;margin:0 0 2px;font-weight:700;}
  header .meta{font-size:12px;color:var(--sub);}
  .card{background:var(--card);border:1px solid var(--line);border-radius:14px;
    padding:14px;margin-bottom:12px;box-shadow:var(--shadow);}
  .card h2{font-size:16px;margin:0 0 10px;font-weight:700;display:flex;align-items:center;gap:8px;}
  .card h2 .dot{width:9px;height:9px;border-radius:50%;background:var(--teal);}
  .alert{border-radius:14px;padding:14px;margin-bottom:12px;color:#fff;}
  .alert.ok{background:linear-gradient(135deg,#2E8B57,#1F7A6B);}
  .alert.warn{background:linear-gradient(135deg,#E0822C,#C0392B);}
  .alert .t{font-size:15px;font-weight:700;display:flex;align-items:center;gap:8px;}
  .alert .d{font-size:13px;margin-top:6px;opacity:.96;}
  .alert .big{font-size:24px;font-weight:800;margin-top:4px;}
  .stats{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;}
  .stat{background:#FBFAF7;border:1px solid var(--line);border-radius:10px;padding:10px 12px;}
  .stat .k{font-size:12px;color:var(--sub);}
  .stat .v{font-size:22px;font-weight:700;margin-top:2px;}
  .stat .v small{font-size:12px;font-weight:500;color:var(--sub);}
  .chart-wrap{width:100%;overflow:hidden;}
  svg.chart{width:100%;height:auto;display:block;}
  .legend{display:flex;flex-wrap:wrap;gap:12px;font-size:12px;color:var(--sub);margin-top:8px;}
  .legend i{display:inline-block;width:14px;height:4px;border-radius:2px;vertical-align:middle;margin-right:5px;}
  .imp{border-left:4px solid var(--teal);border-radius:0 10px 10px 0;padding:10px 12px;margin-bottom:10px;background:#FBFAF7;}
  .imp.warn{border-left-color:var(--amber);}
  .imp.danger{border-left-color:var(--danger);}
  .imp .h{font-weight:700;font-size:14px;display:flex;align-items:center;gap:8px;}
  .badge{font-size:11px;padding:2px 8px;border-radius:999px;font-weight:700;color:#fff;}
  .badge.ok{background:var(--ok);} .badge.warn{background:var(--amber);} .badge.danger{background:var(--danger);}
  .imp p{margin:6px 0 0;font-size:14px;color:#3A4146;}
  @page{size:430px 1100px;margin:7mm;}
  .pill{display:inline-block;background:#FCEFD8;color:#9a5a12;border-radius:8px;padding:2px 8px;font-size:12px;font-weight:600;}
</style>
</head>
<body>
<header>
  <h1 id="titleH1">两周天气看板</h1>
  <div class="meta" id="metaLine"></div>
</header>

<div id="alertBox"></div>

<div class="card">
  <h2><span class="dot"></span>关键指标（14 天峰值）</h2>
  <div class="stats" id="statsBox"></div>
</div>

<div class="card">
  <h2><span class="dot"></span>气温趋势（2 m）</h2>
  <div class="chart-wrap"><svg class="chart" id="tempChart" viewBox="0 0 680 220" preserveAspectRatio="none"></svg></div>
  <div class="legend"><span><i style="background:#E0822C"></i>气温 °C</span>
    <span><i style="background:#C0392B"></i>高温线 35°C</span>
    <span><i style="background:#2E7DA8"></i>低温线 0°C</span></div>
</div>

<div class="card">
  <h2><span class="dot"></span>降水分布（逐日总量）</h2>
  <div class="chart-wrap"><svg class="chart" id="precipChart" viewBox="0 0 680 240" preserveAspectRatio="none"></svg></div>
  <div class="legend"><span><i style="background:#7FB3D5"></i>小雨/中雨</span>
    <span><i style="background:#E0822C"></i>大雨 ≥25mm</span>
    <span><i style="background:#C0392B"></i>暴雨线 50mm</span></div>
</div>

<div class="card">
  <h2><span class="dot"></span>风速 / 阵风（10 m）</h2>
  <div class="chart-wrap"><svg class="chart" id="windChart" viewBox="0 0 680 220" preserveAspectRatio="none"></svg></div>
  <div class="legend"><span><i style="background:#1F7A6B"></i>持续风速</span>
    <span><i style="background:#8E44AD"></i>阵风</span>
    <span><i style="background:#E0822C"></i>6级 10.8m/s</span>
    <span><i style="background:#C0392B"></i>8级 17.2m/s</span></div>
</div>

<div class="card">
  <h2><span class="dot"></span>物探作业天气影响与建议</h2>
  <div id="impactBox"></div>
</div>

<script>
const DATA = __DATA__;
const NS = "http://www.w3.org/2000/svg";
document.getElementById("titleH1").textContent = DATA.meta.name + " · 两周天气看板";

function el(tag, attrs){ const e=document.createElementNS(NS,tag); for(const k in attrs) e.setAttribute(k,attrs[k]); return e; }

function lineChart(svg, series, opt){
  const W=680,H=220,pl=38,pr=10,pt=14,pb=26;
  svg.innerHTML="";
  const n=series[0].data.length;
  const yMin=opt.yMin, yMax=opt.yMax;
  const X=i=> pl+(W-pl-pr)*(n<=1?0.5:i/(n-1));
  const Y=v=> pt+(H-pt-pb)*(1-(v-yMin)/(yMax-yMin));
  const ticks=[yMin,(yMin+yMax)/2,yMax];
  ticks.forEach(tv=>{
    svg.appendChild(el("line",{x1:pl,y1:Y(tv),x2:W-pr,y2:Y(tv),stroke:"#EEE",["stroke-width"]:1}));
    const tx=el("text",{x:pl-5,y:Y(tv)+3,["text-anchor"]:"end","font-size":10,fill:"#9aa0a4"}); tx.textContent=Math.round(tv); svg.appendChild(tx);
  });
  (opt.thresholds||[]).forEach(th=>{
    if(th.v<yMin||th.v>yMax) return;
    svg.appendChild(el("line",{x1:pl,y1:Y(th.v),x2:W-pr,y2:Y(th.v),stroke:th.color,["stroke-width"]:1.4,["stroke-dasharray"]:"5 4",opacity:.8}));
    const tx=el("text",{x:W-pr,y:Y(th.v)-4,["text-anchor"]:"end","font-size":10,fill:th.color,["font-weight"]:"700"}); tx.textContent=th.label; svg.appendChild(tx);
  });
  const idxs=[0,Math.floor((n-1)/4),Math.floor((n-1)/2),Math.floor(3*(n-1)/4),n-1];
  const seen=new Set();
  idxs.forEach(i=>{
    const lab=opt.xLabel(i);
    if(seen.has(lab)) return; seen.add(lab);
    const tx=el("text",{x:X(i),y:H-8,["text-anchor"]:"middle","font-size":10,fill:"#9aa0a4"}); tx.textContent=lab; svg.appendChild(tx);
  });
  series.forEach(s=>{
    let pts="", area="";
    s.data.forEach((v,i)=>{ const x=X(i),y=Y(v==null?yMin:v); pts+=(i?"L":"M")+x.toFixed(1)+" "+y.toFixed(1)+" "; });
    if(s.fill){
      area="M"+X(0).toFixed(1)+" "+Y(yMin).toFixed(1)+" "+pts.replace(/^M/,"L")+" L"+X(n-1).toFixed(1)+" "+Y(yMin).toFixed(1)+" Z";
      const gp=el("path",{d:area,fill:s.fill,opacity:.18}); svg.appendChild(gp);
    }
    svg.appendChild(el("path",{d:pts,fill:"none",stroke:s.color,["stroke-width"]:2,["stroke-linejoin"]:"round",["stroke-linecap"]:"round"}));
    if(s.markMax){ let mi=s.data.indexOf(Math.max(...s.data)); const c=el("circle",{cx:X(mi),cy:Y(s.data[mi]),r:3.5,fill:s.color,stroke:"#fff",["stroke-width"]:1.5}); svg.appendChild(c);
      const tx=el("text",{x:X(mi),y:Y(s.data[mi])-8,["text-anchor"]:"middle","font-size":10,fill:s.color,["font-weight"]:"700"}); tx.textContent=Math.round(s.data[mi]); svg.appendChild(tx); }
  });
}

function barChart(svg, items, opt){
  const W=680,H=240,pl=36,pr=10,pt=14,pb=28;
  svg.innerHTML="";
  const n=items.length, yMax=opt.yMax;
  const bw=(W-pl-pr)/n;
  const Y=v=> pt+(H-pt-pb)*(1-v/yMax);
  [0,yMax/2,yMax].forEach(tv=>{ svg.appendChild(el("line",{x1:pl,y1:Y(tv),x2:W-pr,y2:Y(tv),stroke:"#EEE",["stroke-width"]:1}));
    const tx=el("text",{x:pl-5,y:Y(tv)+3,["text-anchor"]:"end","font-size":10,fill:"#9aa0a4"}); tx.textContent=Math.round(tv); svg.appendChild(tx); });
  (opt.thresholds||[]).forEach(th=>{ if(th.v>yMax)return;
    svg.appendChild(el("line",{x1:pl,y1:Y(th.v),x2:W-pr,y2:Y(th.v),stroke:th.color,["stroke-width"]:1.4,["stroke-dasharray"]:"5 4",opacity:.85}));
    const tx=el("text",{x:W-pr,y:Y(th.v)-4,["text-anchor"]:"end","font-size":10,fill:th.color,["font-weight"]:"700"}); tx.textContent=th.label; svg.appendChild(tx); });
  items.forEach((it,i)=>{
    const x=pl+bw*i+bw*0.18, w=bw*0.64, v=it.p, y=Y(v), h=H-pt-pb-y;
    let color=it.p>=25?"#E0822C":(it.p>=10?"#7FB3D5":"#Bcd7e8");
    if(it.focus) color="#E0822C";
    svg.appendChild(el("rect",{x:x,y:y,width:w,height:Math.max(h,0.5),rx:3,fill:color}));
    if(v>0){ const tx=el("text",{x:x+w/2,y:y-4,["text-anchor"]:"middle","font-size":9.5,fill:it.focus?"#9a5a12":"#7a8086",["font-weight"]:it.focus?"700":"400"}); tx.textContent=v; svg.appendChild(tx); }
    const lab=it.date.slice(5);
    const tx=el("text",{x:x+w/2,y:H-9,["text-anchor"]:"middle","font-size":9,fill:"#9aa0a4"}); tx.textContent=lab; svg.appendChild(tx);
  });
}

const P=DATA.peaks, H=DATA.hourly;
document.getElementById("metaLine").textContent =
  `${DATA.meta.start} ~ ${DATA.meta.end} · 数据 ${DATA.meta.gen} 生成`;

const alertBox=document.getElementById("alertBox");
const hasExtreme = (P.tmax>=35)||(P.tmin<=0)||(P.pHourMax>=20)||(P.pMax>=50)||(P.gustMax>=17.2)||(P.windMax>=10.8);
if(!hasExtreme){
  const a=document.createElement("div");
  a.className="alert ok";
  a.innerHTML=`<div class="t">✓ 本期未触发极端天气预警阈值</div>
    <div class="d">气温 ${P.tmin}~${P.tmax}°C · 最大阵风 ${P.gustMax} m/s · 无短时强降水、无暴雨日。整体有利于野外作业。</div>`;
  alertBox.appendChild(a);
}
if(P.focusStart){
  const a=document.createElement("div");
  a.className="alert warn";
  a.innerHTML=`<div class="t">⚠ 重点关注：${P.focusStart.slice(5)} ~ ${P.focusEnd.slice(5)} 连续降雨</div>
    <div class="d">累计降水 <span class="big">${P.focusTotal} mm</span>，峰值 ${P.pMaxDay.slice(5)} 单日 ${P.pMax}mm（大雨）。山区需防便道泥泞、滑坡与设备防雨。</div>`;
  alertBox.appendChild(a);
}

const stats=[
  ["最高气温", P.tmax+"°C", P.tmax>=35?"高温预警":"无高温预警"],
  ["最低气温", P.tmin+"°C", P.tmin<=0?"注意霜冻/结冰":"无霜冻/结冰"],
  ["最大阵风", P.gustMax+"<small> m/s</small>", P.gustMax>=17.2?"≥8级，需停工":(P.gustMax>=10.8?"≥6级，加固":"约5级，不影响")],
  ["最大日降水", (P.pMax||0)+"<small> mm</small>", P.pMaxDay?(P.pMax>=50?"暴雨 "+P.pMaxDay.slice(5):(P.pMax>=25?"大雨 "+P.pMaxDay.slice(5):"中雨 "+P.pMaxDay.slice(5))):"—"],
];
document.getElementById("statsBox").innerHTML = stats.map(s=>
  `<div class="stat"><div class="k">${s[0]}</div><div class="v">${s[1]}</div><div class="k">${s[2]}</div></div>`).join("");

const tMinAll=Math.min(...H.temp), tMaxAll=Math.max(...H.temp);
let tYMin=Math.floor((tMinAll-3)/5)*5, tYMax=Math.ceil((tMaxAll+3)/5)*5;
if(tYMin>0) tYMin=0;
lineChart(document.getElementById("tempChart"),
  [{data:H.temp,color:"#E0822C",fill:true,markMax:true}],
  {yMin:tYMin,yMax:tYMax,thresholds:[{v:35,color:"#C0392B",label:"高温35°"},{v:0,color:"#2E7DA8",label:"0°"}],
   xLabel:i=>H.time[i].slice(5,10)});

const focusSet=new Set();
if(P.focusStart){ let d=DATA.daily; d.forEach(x=>{ if(x.date>=P.focusStart&&x.date<=P.focusEnd) focusSet.add(x.date); }); }
barChart(document.getElementById("precipChart"),
  DATA.daily.map(x=>({date:x.date,p:x.p,focus:focusSet.has(x.date)})),
  {yMax:60,thresholds:[{v:50,color:"#C0392B",label:"暴雨50mm"},{v:25,color:"#E0822C",label:"大雨25mm"}]});

const wMaxAll=Math.max(...H.gust, ...H.wind);
const wYMax=Math.max(24, Math.ceil(wMaxAll/4)*4 + 4);
lineChart(document.getElementById("windChart"),
  [{data:H.wind,color:"#1F7A6B",fill:false},{data:H.gust,color:"#8E44AD",fill:false,markMax:true}],
  {yMin:0,yMax:wYMax,thresholds:[{v:10.8,color:"#E0822C",label:"6级10.8"},{v:17.2,color:"#C0392B",label:"8级17.2"}],
   xLabel:i=>H.time[i].slice(5,10)});

const ib=document.getElementById("impactBox");
function card(level,title,badge,html){
  const cls = level==="danger"?"imp danger":(level==="warn"?"imp warn":"imp");
  return `<div class="${cls}"><div class="h">${title} <span class="badge ${badge.cls}">${badge.t}</span></div><p>${html}</p></div>`;
}
let out="";
if(P.pMax>=25){ out+=card("warn","降水 / 泥泞",{cls:"warn",t:"注意"},
  `${P.focusStart.slice(5)} ~ ${P.focusEnd.slice(5)} 连续降雨累计 <b>${P.focusTotal}mm</b>，其中 ${P.pMaxDay.slice(5)} 达 <b>${P.pMax}mm（大雨）</b>。山区便道易泥泞、车辆通行困难；坡面含水升高，<b>滑坡/泥石流风险上升</b>；钻井与地震排列设备需做好防雨防潮。建议：推迟涉水与陡坡段施工，雨停后待便道稍干再进场，电缆接头包覆防水。`); }
else { out+=card("ok","降水 / 泥泞",{cls:"ok",t:"安全"},
  `预报期内日降水均 ≤25mm，以零星小雨为主，对便道与设备影响有限，常规防雨即可。`); }
if(P.gustMax>=17.2){ out+=card("danger","大风 / 阵风",{cls:"danger",t:"预警"},
  `阵风达 ${P.gustMax} m/s（≥8级），钻机塔架、重力仪/磁力仪天线与帐篷稳定性受严重影响，高处作业必须停工。`); }
else if(P.windMax>=10.8){ out+=card("warn","大风 / 阵风",{cls:"warn",t:"注意"},
  `持续风速达 ${P.windMax} m/s（≥6级），钻机与高空设备需加固，谨慎安排吊装/高处作业。`); }
else { out+=card("ok","大风 / 阵风",{cls:"ok",t:"安全"},
  `最大阵风 ${P.gustMax} m/s（约5级及以下），不影响钻机、天线及帐篷，常规作业即可。`); }
if(P.tmax>=35){ out+=card("danger","高温",{cls:"danger",t:"预警"},`最高气温 ${P.tmax}°C，人员易中暑、设备过热电池衰减，避开正午高强度作业、配备降温与补水。`); }
else if(P.tmin<=0){ out+=card("warn","低温 / 结冰",{cls:"warn",t:"注意"},`最低气温 ${P.tmin}°C，高海拔段可能结冰，人员保暖、电池效能下降需备用电源。`); }
else { out+=card("ok","气温",{cls:"ok",t:"适宜"},`气温区间 ${P.tmin}~${P.tmax}°C，体感适宜；高海拔早晚偏凉，注意人员保暖与仪器低温启动。`); }
out+=card("warn","雷暴（注：预报未含雷电要素）",{cls:"warn",t:"提示"},
  `连续降雨过程常伴雷暴。山区孤立高地、金属设备（地震检波器串、测杆、钻塔）雷击风险高。遇雷雨立即停工，人员撤离至车内或低洼安全区，远离孤立树木与金属物体。`);
out+=card("ok","低能见度 / 行车",{cls:"ok",t:"提示"},
  `雨后山区多雾、便道湿滑，越野车与设备转运需降速、保持车距；进场前确认便道承载力。`);
ib.innerHTML=out;
</script>
</body>
</html>
"""

html = TEMPLATE.replace("__DATA__", DATA_JSON).replace("__TITLE__", f"{args.name} · 两周天气看板")

# 内嵌中文字体子集(解决 Chrome 无头模式中文空白问题)
try:
    from fontTools.ttLib import TTFont
    from fontTools import subset as ftsubset
    fnt = TTFont("/System/Library/Fonts/Hiragino Sans GB.ttc", fontNumber=0)
    chars = "".join(sorted(set(html)))
    ss = ftsubset.Subsetter()
    ss.populate(text=chars)
    ss.subset(fnt)
    buf = io.BytesIO()
    fnt.save(buf)
    b64 = base64.b64encode(buf.getvalue()).decode()
    font_css = ("@font-face{font-family:'CJKLocal';src:url('data:font/ttf;base64,"
                + b64 + "') format('truetype');font-display:swap;}")
    html = html.replace("/*__FONT_FACE__*/", font_css)
    print("embedded CJK font:", len(buf.getvalue()), "bytes")
except Exception as e:
    print("font embed FAILED:", repr(e))
    html = html.replace("/*__FONT_FACE__*/", "")

with open(html_path, "w", encoding="utf-8") as f:
    f.write(html)
print("HTML written:", html_path, len(html), "bytes")

# ---------- 3. 用 Chrome CDP 导出窄页 PDF ----------
import websocket
os.environ["no_proxy"] = "*"; os.environ["NO_PROXY"] = "*"
urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))
port = 9333
profile = "<TMP>/cdp_profile_wb"
proc = subprocess.Popen(
    [args.chrome, "--headless", "--disable-gpu", "--no-sandbox", "--no-first-run",
     "--remote-allow-origins=*", f"--remote-debugging-port={port}", f"--user-data-dir={profile}"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
try:
    time.sleep(3)
    raw = None; host = "[::1]"
    for hh in ("[::1]", "127.0.0.1", "localhost"):
        for ep in (f"http://{hh}:{port}/json/list", f"http://{hh}:{port}/json/version"):
            try:
                raw = urllib.request.urlopen(ep, timeout=5).read(); host = hh; break
            except Exception:
                pass
        if raw:
            break
    targets = json.loads(raw)
    if isinstance(targets, dict):
        targets = [{"type": "page", "webSocketDebuggerUrl": targets.get("webSocketDebuggerUrl")}]
    ws_url = None
    for t in targets:
        if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
            ws_url = t["webSocketDebuggerUrl"]; break
    if not ws_url:
        raise RuntimeError("no websocket target")
    ws = websocket.create_connection(ws_url, timeout=30)
    def send(mid, method, params=None):
        ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
    def recv_until(mid):
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == mid and "result" in msg:
                return msg
    send(1, "Page.enable")
    file_url = "file://" + urllib.parse.quote(html_path)
    send(2, "Page.navigate", {"url": file_url})
    time.sleep(4)
    send(3, "Page.printToPDF", {
        "paperWidth": 4.5, "paperHeight": 11.5,
        "marginTop": 0.12, "marginBottom": 0.12,
        "marginLeft": 0.12, "marginRight": 0.12,
        "printBackground": True, "preferCSSPageSize": False,
        "headerTemplate": "", "footerTemplate": "",
    })
    res = recv_until(3)
    with open(pdf_path, "wb") as f:
        f.write(base64.b64decode(res["result"]["data"]))
    ws.close()
    print("PDF written:", pdf_path, os.path.getsize(pdf_path), "bytes")
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
print("DONE")
