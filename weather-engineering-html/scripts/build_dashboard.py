#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
weather-engineering-html —— 钻井工程井位天气看板生成器（未来 2 周 / 14 天）
=============================================
与物探(weather-wutan-html)完全不同的生成模式：
  * 输入：井位点 KML（多个 <Placemark><Point>，如钻井平台/油气井）
  * 每个井位生成【独立 html 看板】，但【不显示地图】；
    保留"其它所有内容"：重点关注、关键指标、逐要素曲线/柱状图、风险面板、作业影响与建议。
  * 取数窗口：默认从下一日 0 时起【未来 2 周 / 14 天】（--days，可覆盖）。

注意：本脚本【不再生成 index.html】。井位地图 index 已拆出为独立技能
      weather-engineering-index（scripts/build_wells_index.py），
      生成井位页后如需刷新目录页，请单独运行该技能的 build_wells_index.py。
数据来自 Open-Meteo（免费接口，无需 key；本机带 key 仅做兼容）。
中文字体子集内嵌（fontTools + Hiragino Sans GB），手机/浏览器直接打开。
"""
import os, sys, json, time, math, argparse, io, base64, datetime, re
from collections import defaultdict
import urllib.request, urllib.error
import xml.etree.ElementTree as ET

FETCH_ENABLED = True
KNS = "{http://www.opengis.net/kml/2.2}"

# ---------- pinyin 文件名（避免中文在 CDP/系统间传输的编码问题） ----------
try:
    from pypinyin import pinyin, Style
    HAVE_PY = True
except Exception:
    HAVE_PY = False

_CJK = re.compile(r"[\u4e00-\u9fff]")
def slug(name):
    parts = []
    if HAVE_PY:
        for ch in name:
            if _CJK.match(ch):
                ps = pinyin(ch, style=Style.NORMAL, errors="ignore")
                if ps and ps[0]:
                    parts.append(ps[0][0])
            elif ch.isalnum() or ch in "-_":
                parts.append(ch)
    else:
        parts = [ch for ch in name if ch.isalnum() or ch in "-_"]
    return ("".join(parts).lower() or "well").strip("-_")

# ---------- 带退避重试的 GET（缓解 Open-Meteo 429） ----------
def http_get_json(url, timeout=60, retries=5, sleep0=2.0):
    last = None
    for attempt in range(retries):
        try:
            rq = urllib.request.Request(url, headers={"User-Agent": "workbuddy-weather/1.0"})
            with urllib.request.urlopen(rq, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            last = e
            print(f"  HTTP 重试 {attempt+1}/{retries}: {repr(e)}")
            time.sleep(sleep0 * (2 ** attempt))
    raise last

# ---------- 极端天气分级（0绿 1黄 2橙 3红，沿用物探阈值） ----------
def _sev(P):
    if P["pMax"] >= 80 or P["gustMax"] >= 20.8 or P["tmax"] >= 38 or P["focusTotal"] >= 150:
        return 3
    if P["pMax"] >= 50 or P["gustMax"] >= 17.2 or P["tmax"] >= 35 or P["tmin"] <= -5 or P["focusTotal"] >= 80:
        return 2
    if P["pMax"] >= 25 or P["windMax"] >= 10.8 or P["tmin"] <= 0 or P["focusTotal"] >= 30:
        return 1
    return 0
SEV_LABEL = {0: "整体适宜", 1: "需关注", 2: "重点关注", 3: "高度警惕"}

def risk_of(pp):
    if pp["gustMax"] >= 17.2 or pp["tmax"] >= 35 or pp["pMax"] >= 50:
        return "danger"
    if pp["pMax"] >= 25 or pp["windMax"] >= 10.8 or pp["tmin"] <= 0:
        return "warn"
    return "ok"

# ---------- KML 井位点解析 ----------
def parse_wells_kml(path):
    root = ET.parse(path).getroot()
    doc = root.find(KNS + "Document/" + KNS + "name")
    project = (doc.text.strip() if (doc is not None and doc.text) else
               os.path.splitext(os.path.basename(path))[0])
    wells = []
    for pm in root.iter(KNS + "Placemark"):
        pt = pm.find(KNS + "Point")
        if pt is None:
            continue
        c = pt.find(KNS + "coordinates")
        if c is None or not c.text or not c.text.strip():
            continue
        lon, lat, *_ = c.text.strip().split(",")
        nm = pm.find(KNS + "name")
        name = (nm.text.strip() if (nm is not None and nm.text) else "")
        wells.append({"lon": float(lon), "lat": float(lat),
                      "name": name, "project": project})
    return project, wells

# ======================================================================
#  单井位 payload 计算
# ======================================================================
def build_well_payload(i, w, loc, times, dailyDates, start, end, gen, model):
    temp   = [float(v) for v in loc["hourly"]["temperature_2m"]]
    precip = [float(v) for v in loc["hourly"]["precipitation"]]
    rain   = [float(v) for v in loc["hourly"]["rain"]]
    wind   = [float(v) for v in loc["hourly"]["wind_speed_10m"]]
    gust   = [float(v) for v in loc["hourly"]["wind_gusts_10m"]]

    dprecip = defaultdict(float)
    for t, v in zip(times, precip):
        dprecip[t[:10]] += v
    daily = sorted(dprecip.items())
    tMinD, tMaxD, pD, wD, gD = {}, {}, {}, {}, {}
    for t, tv, pv, wv, gv in zip(times, temp, precip, wind, gust):
        d = t[:10]
        tMinD.setdefault(d, []).append(tv); tMaxD.setdefault(d, []).append(tv)
        pD[d] = pD.get(d, 0.0) + max(pv, 0.0)
        wD.setdefault(d, []).append(wv); gD.setdefault(d, []).append(gv)
    tempMin = [round(min(tMinD[d]), 1) for d in dailyDates]
    tempMax = [round(max(tMaxD[d]), 1) for d in dailyDates]
    pser    = [round(pD.get(d, 0.0), 1) for d in dailyDates]
    windMax = [round(max(wD[d]), 1) for d in dailyDates]
    gustMax = [round(max(gD[d]), 1) for d in dailyDates]
    tmax = round(max(temp), 1); tmin = round(min(temp), 1)
    gmax = round(max(gust), 1); wmax = round(max(wind), 1)
    pmax_day = max(daily, key=lambda x: x[1])[0] if daily else None
    pmax = round(max((v for _, v in daily), default=0), 1)
    focus = [(d, v) for d, v in daily if v >= 10]
    P = {
        "tmax": tmax, "tmin": tmin, "gustMax": gmax, "windMax": wmax,
        "pHourMax": round(max(precip), 1),
        "pMax": pmax, "pMaxDay": pmax_day,
        "focusTotal": round(sum(v for _, v in focus), 1),
        "focusStart": (focus[0][0] if focus else None),
        "focusEnd":   (focus[-1][0] if focus else None),
    }
    SEV = _sev(P)
    risk = risk_of({"gustMax": gmax, "tmax": tmax, "pMax": pmax, "windMax": wmax, "tmin": tmin})
    hx = {"temp": [round(v, 1) for v in temp], "precip": [round(v, 1) for v in precip],
          "wind": [round(v, 1) for v in wind], "gust": [round(v, 1) for v in gust]}
    series = {"tempMin": tempMin, "tempMax": tempMax, "precip": pser,
              "windMax": windMax, "gustMax": gustMax}
    point = {"idx": 0, "lon": w["lon"], "lat": w["lat"], "isCenter": True,
             "lineIdx": 0, "lineName": "", "risk": risk, "loc": w["name"],
             "tmax": tmax, "tmin": tmin, "gustMax": gmax, "windMax": wmax,
             "pMax": pmax, "pMaxDay": pmax_day, "series": series, "hx": hx,
             "project": w["project"]}
    payload = {
        "meta": {"name": w["name"], "kind": "well", "npts": 1, "hasHX": True,
                 "gridKm": 0, "lonkm": 0, "latkm": 0, "start": start, "end": end,
                 "gen": gen, "sev": SEV, "sevLabel": SEV_LABEL[SEV],
                 "model": model, "dailyDates": dailyDates,
                 "project": w["project"]},
        "polygon": [], "line": [], "lines": None, "dataLines": None, "isLine": False,
        "points": [point], "elevGrid": None,
        "hourly": {"time": times, "tempMin": temp, "tempMax": temp,
                   "precipMax": precip, "rainMax": rain, "windMax": wind, "gustMax": gust},
        "daily": [{"date": d, "p": round(v, 1)} for d, v in daily],
        "peaks": P, "project": w["project"],
    }
    return payload, point, SEV, SEV_LABEL[SEV]

# ======================================================================
#  HTML 模板：单井位页面（无地图）
# ======================================================================
WELL_TEMPLATE = r"""<!DOCTYPE html>
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
    padding:14px 14px calc(28px + env(safe-area-inset-bottom));max-width:430px;margin:0 auto;}
  header{margin-bottom:12px;}
  header h1{font-size:19px;margin:0 0 2px;font-weight:700;}
  header .meta{font-size:12px;color:var(--sub);}
  .backlink{display:inline-block;margin-bottom:6px;font-size:13px;font-weight:600;color:var(--teal);text-decoration:none;
    border:1px solid var(--teal);border-radius:8px;padding:3px 10px;cursor:pointer;transition:background .15s,color .15s;}
  .backlink:hover{background:var(--teal);color:#fff;}
  .card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px;margin-bottom:12px;box-shadow:var(--shadow);}
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
  .imp{border-left:4px solid var(--teal);border-radius:0 10px 10px 0;padding:10px 12px;margin-bottom:10px;background:#FBFAF7;}
  .imp.warn{border-left-color:var(--amber);}
  .imp.danger{border-left-color:var(--danger);}
  .imp .h{font-weight:700;font-size:14px;display:flex;align-items:center;gap:8px;}
  .badge{font-size:11px;padding:2px 8px;border-radius:999px;font-weight:700;color:#fff;}
  .badge.ok{background:var(--ok);} .badge.warn{background:var(--amber);} .badge.danger{background:var(--danger);}
  .imp p{margin:6px 0 0;font-size:14px;color:#3A4146;}
  .srcnote{font-size:12px;color:var(--sub);margin:0 0 9px;}
  @page{size:430px 1100px;margin:7mm;}
  body.sev0{--sev:#2E8B57;} body.sev1{--sev:#E0A92C;} body.sev2{--sev:#E0822C;} body.sev3{--sev:#C0392B;}
  .alert.sevbox{background:var(--sev,#2E8B57);color:#fff;border-radius:14px;padding:13px 15px;margin-bottom:12px;box-shadow:var(--shadow);}
  .alert.sevbox .t{font-size:16px;font-weight:800;display:flex;align-items:center;gap:8px;}
  .alert.sevbox .d{font-size:13px;margin-top:6px;opacity:.97;line-height:1.55;}
  .sev-dot{width:11px;height:11px;border-radius:50%;background:#fff;box-shadow:0 0 0 3px rgba(255,255,255,.35);}
  .explorer-info{font-size:13px;color:var(--ink);margin-bottom:8px;}
  .explorer-info b{font-size:15px;}
  .empty-tip{font-size:13px;color:var(--sub);text-align:center;padding:22px 0;}
  .elem-row{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0 6px;}
  .elem-row label{display:flex;align-items:center;gap:6px;font-size:13px;background:#FBFAF7;border:1px solid var(--line);
    border-radius:999px;padding:6px 12px;cursor:pointer;user-select:none;}
  .elem-row input{margin:0;accent-color:var(--teal);}
  #explorerCharts .ec{margin-bottom:4px;}
  #explorerCharts .ec-h{font-size:13px;font-weight:700;margin:8px 0 2px;}
  .risk-reason{margin:12px 0 4px;background:rgba(255,255,255,.97);border:1px solid var(--line);
    border-left:4px solid var(--danger);border-radius:9px;box-shadow:0 6px 18px rgba(0,0,0,.12);
    padding:10px 14px;font-size:12.5px;color:var(--ink);line-height:1.55;}
  .risk-reason .rr-h{font-weight:800;font-size:13.5px;margin-bottom:3px;}
  .risk-reason .rr-time{font-size:12px;color:#3A4146;margin-bottom:4px;font-variant-numeric:tabular-nums;}
  .risk-reason .rr-sev{display:inline-block;margin-bottom:6px;}
  .risk-reason .rr-cur{font-size:12px;color:#2A2F33;margin-bottom:6px;font-variant-numeric:tabular-nums;}
  .risk-reason .rr-cur b{color:#C0392B;}
  .risk-reason .rr-list{font-size:11.5px;color:#5b6166;}
  .risk-reason .rr-item{padding:1px 0;}
  .risk-reason .rr-item.d{color:#C0392B;}
  .risk-reason .rr-item.w{color:#E0822C;}
  .risk-reason .rr-ok{color:#1F7A6B;font-weight:600;}
  .risk-reason .rr-peaks{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:8px 0 2px;}
  .risk-reason .rr-pc{background:#FBFAF7;border:1px solid var(--line);border-radius:8px;padding:6px 9px;}
  .risk-reason .rr-pc .k{font-size:11px;color:var(--sub);margin-bottom:2px;}
  .risk-reason .rr-pc .v{font-size:15px;font-weight:800;color:var(--ink);font-variant-numeric:tabular-nums;}
  .risk-reason .rr-pc .s{font-size:10.5px;color:#8a9097;margin-top:2px;}
  .risk-reason .rr-worst{margin-top:8px;padding-top:7px;border-top:1px dashed var(--line);font-size:11.5px;color:#7a3b12;}
  .risk-reason .rr-worst b{color:#C0392B;}
  .tabs{display:flex;gap:6px;margin:2px 0 12px;}
  .tabbtn{flex:1;padding:11px 4px;border:1px solid var(--line);background:#fff;border-radius:10px;
    font-size:13px;font-weight:700;color:var(--sub);cursor:pointer;transition:background .15s;}
  .tabbtn.active{background:var(--teal);color:#fff;border-color:var(--teal);}
  .tabpane{display:none;}
  .tabpane.active{display:block;}
</style>
</head>
<body>
<header>
  <a class="backlink" href="index.html">← 返回总览</a>
  <h1 id="titleH1">钻井井位天气看板</h1>
  <div class="meta" id="metaLine"></div>
</header>

<div class="tabs">
  <button class="tabbtn active" data-tab="t1">重点提示·指标</button>
  <button class="tabbtn" data-tab="t2">井位天气详情</button>
  <button class="tabbtn" data-tab="t3">作业建议</button>
</div>

<div id="t1" class="tabpane active">
  <div id="alertBox" class="alert sevbox"></div>
  <div class="card">
    <h2><span class="dot"></span><span id="tStats">关键指标（井位 7 天最坏情况）</span></h2>
    <div class="stats" id="statsBox"></div>
  </div>
</div>

<div id="t2" class="tabpane">
  <div class="card">
    <h2><span class="dot"></span><span id="tMap">井位天气详情</span></h2>
    <div class="risk-reason" id="riskReason" style="display:none"></div>
    <div class="elem-row">
      <label><input type="checkbox" value="precip" checked> 降水</label>
      <label><input type="checkbox" value="wind" checked> 风速 / 阵风</label>
      <label><input type="checkbox" value="temp" checked> 气温</label>
    </div>
    <div id="explorerInfo" class="explorer-info"></div>
    <div id="explorerCharts"></div>
  </div>
</div>

<div id="t3" class="tabpane">
  <div class="card">
    <h2><span class="dot"></span><span id="tImpact">钻井作业天气影响与建议</span></h2>
    <div id="impactBox"></div>
  </div>
</div>

<script>
const DATA = __DATA__;
const NS = "http://www.w3.org/2000/svg";
const LBL = "井位";
const HAS_MAP = false;
let SEL = -1;
document.getElementById("titleH1").textContent = DATA.meta.name + " · 钻井井位天气看板";
document.getElementById("tMap").textContent = "井位天气详情";
document.getElementById("tStats").textContent = "关键指标（井位 7 天最坏情况）";
document.getElementById("tImpact").textContent = "钻井作业天气影响与建议";
document.getElementById("metaLine").textContent =
  `钻井井位 · ${DATA.meta.start} ~ ${DATA.meta.end} · 数据 ${DATA.meta.gen} 生成`;
const P = DATA.peaks, H = DATA.hourly;
function el(tag, attrs){ const e=document.createElementNS(NS,tag); for(const k in attrs) e.setAttribute(k,attrs[k]); return e; }

// ============ 重点关注（单一，按严重程度变色） ============
(function(){
  const SEV=DATA.meta.sev, LBL2=DATA.meta.sevLabel;
  document.body.classList.add("sev"+SEV);
  const nRisk = DATA.points.filter(p=>p.risk!=="ok").length;
  const th=[];
  if(P.gustMax>=17.2) th.push(`最大阵风 ${P.gustMax} m/s（≥8级）`);
  if(P.tmax>=35) th.push(`最高气温 ${P.tmax}°C（高温）`);
  if(P.tmin<=0) th.push(`最低气温 ${P.tmin}°C（结冰/霜冻）`);
  if(P.pMax>=50) th.push(`${P.pMaxDay.slice(5)} 单日降水 ${P.pMax}mm（暴雨）`);
  else if(P.pMax>=25) th.push(`${P.pMaxDay.slice(5)} 单日降水 ${P.pMax}mm（大雨）`);
  if(P.focusStart) th.push(`${P.focusStart.slice(5)}~${P.focusEnd.slice(5)} 连续降雨累计 ${P.focusTotal}mm`);
  const desc = th.length
    ? ("主要关注：" + th.join("；") + `。该井位存在降雨/大风风险，建议据此调整钻井作业安排。`)
    : "本期未触发极端天气预警阈值，整体有利于钻井作业。";
  const box=document.getElementById("alertBox");
  box.className="alert sevbox";
  box.innerHTML=`<div class="t"><span class="sev-dot"></span>${LBL2}</div><div class="d">${desc}</div>`;
})();

// ---- 指标 ----
const argmax = key => DATA.points.reduce((b,p)=> (b===null || p[key] > b[key]) ? p : b, null);
const argmin = key => DATA.points.reduce((b,p)=> (b===null || p[key] < b[key]) ? p : b, null);
const tmaxP = argmax("tmax"), tminP = argmin("tmin"), gustP = argmax("gustMax"), pmaxP = argmax("pMax");
const stats=[
  [LBL+"最高温", P.tmax+"°C", (P.tmax>=35?"高温预警":"无高温预警")],
  [LBL+"最低温", P.tmin+"°C", (P.tmin<=0?"注意霜冻/结冰":"无霜冻/结冰")],
  ["最大阵风", P.gustMax+"<small> m/s</small>", (P.gustMax>=17.2?"≥8级，需停工":(P.gustMax>=10.8?"6~7级，加固":"约5级，不影响"))],
  ["最大日降水", (P.pMax||0)+"<small> mm</small>", (P.pMaxDay?(P.pMax>=50?"暴雨 "+P.pMaxDay.slice(5):(P.pMax>=25?"大雨 "+P.pMaxDay.slice(5):"中雨 "+P.pMaxDay.slice(5))):"—")],
];
document.getElementById("statsBox").innerHTML = stats.map(s=>
  `<div class="stat"><div class="k">${s[0]}</div><div class="v">${s[1]}</div><div class="k">${s[2]}</div></div>`).join("");

// ---- 影响说明 ----
const ib=document.getElementById("impactBox");
function card(level,title,badge,html){
  const cls = level==="danger"?"imp danger":(level==="warn"?"imp warn":"imp");
  return `<div class="${cls}"><div class="h">${title} <span class="badge ${badge.cls}">${badge.t}</span></div><p>${html}</p></div>`;
}
let out="";
if(P.pMax>=50 || P.focusTotal>=80){ out+=card("danger","降水 / 泥泞",{cls:"danger",t:"预警"},
  `该井位 ${P.focusStart.slice(5)}~${P.focusEnd.slice(5)} 连续强降雨累计 <b>${P.focusTotal}mm</b>，单日最大 <b>${P.pMax}mm（暴雨）</b>。井场与进场道路严重泥泞、易陷车；坡面含水饱和，<b>滑坡/泥石流高风险</b>；钻井设备需全面防雨防潮。建议：暂停涉水、陡坡及河谷段作业，人员设备撤离高风险斜坡，雨停后待道路充分干燥再进场。`); }
else if(P.pMax>=25 || P.focusTotal>=30){ out+=card("warn","降水 / 泥泞",{cls:"warn",t:"注意"},
  `该井位 ${P.focusStart.slice(5)}~${P.focusEnd.slice(5)} 连续降雨累计 <b>${P.focusTotal}mm</b>，单日最大 <b>${P.pMax}mm（${P.pMax>=25?'大雨':'中雨'}）</b>。井场与进场道路易泥泞、车辆通行困难；坡面含水升高，<b>滑坡/泥石流风险上升</b>；钻井设备需做好防雨防潮。建议：推迟涉水与陡坡段作业，雨停后待道路稍干再进场，电缆接头包覆防水。`); }
else { out+=card("ok","降水 / 泥泞",{cls:"ok",t:"安全"},
  `该井位预报期无连续中雨以上降雨，以间歇小雨为主，对道路与设备影响有限，常规防雨即可。`); }
if(P.gustMax>=17.2){ out+=card("danger","大风 / 阵风",{cls:"danger",t:"预警"},
  `该井位阵风达 ${P.gustMax} m/s（≥8级），钻机塔架、井架天线与帐篷稳定性受严重影响，高处作业必须停工。`); }
else if(P.gustMax>=10.8 || P.windMax>=10.8){ out+=card("warn","大风 / 阵风",{cls:"warn",t:"注意"},
  `该井位阵风达 ${P.gustMax} m/s（6~7级），钻机与高空设备需加固，谨慎安排吊装/高处作业。`); }
else { out+=card("ok","大风 / 阵风",{cls:"ok",t:"安全"},
  `该井位最大阵风 ${P.gustMax} m/s（约5级及以下），不影响钻机、天线及帐篷，常规作业即可。`); }
if(P.tmax>=35){ out+=card("danger","高温",{cls:"danger",t:"预警"},`该井位最高气温 ${P.tmax}°C，人员易中暑、设备过热电池衰减，避开正午高强度作业、配备降温与补水。`); }
else if(P.tmin<=0){ out+=card("warn","低温 / 结冰",{cls:"warn",t:"注意"},`该井位最低气温 ${P.tmin}°C，高海拔段可能结冰，人员保暖、电池效能下降需备用电源。`); }
else { out+=card("ok","气温",{cls:"ok",t:"适宜"},`该井位气温区间 ${P.tmin}~${P.tmax}°C，体感适宜；高海拔早晚偏凉，注意人员保暖与仪器低温启动。`); }
out+=card("ok","低能见度 / 行车",{cls:"ok",t:"提示"},
  `雨后山区多雾、道路湿滑，转运车辆需降速、保持车距；进场前确认道路承载力。`);
ib.innerHTML=out;

// ============ 风险面板 + 逐要素曲线（单井位，默认直接展示） ============
const COLMAP = {ok:"#1F7A6B", warn:"#E0822C", danger:"#C0392B"};
const RR = document.getElementById("riskReason");
function riskClassAtHour(pt, h){
  if(!pt.hx) return pt.risk;
  const g=pt.hx.gust[h]||0, p=pt.hx.precip[h]||0, t=pt.hx.temp[h]||0;
  if(g>=17.2 || t>=35 || p>=8) return "danger";
  if(g>=10.8 || t<=0 || p>=3) return "warn";
  return "ok";
}
function riskFactorsAtHour(pt, h){
  if(!pt.hx) return null;
  const g=pt.hx.gust[h]||0, w=pt.hx.wind[h]||0, p=pt.hx.precip[h]||0, t=pt.hx.temp[h]||0;
  const f=[];
  if(g>=10.8) f.push({name:"阵风", val:g.toFixed(1), unit:"m/s", level:g>=17.2?3:2,
    advice:g>=17.2?"≥8级，井架/天线/帐篷须停工":"6~7级，设备与帐篷需加固"});
  if(w>=10.8) f.push({name:"持续风", val:w.toFixed(1), unit:"m/s", level:2, advice:"≥6级，注意高空作业与帐篷"});
  if(p>=3) f.push({name:"小时降水", val:p.toFixed(1), unit:"mm", level:p>=8?3:2,
    advice:p>=8?"短时强降水，低洼易积水、道路泥泞":"降雨，设备注意防雨防潮"});
  if(t>=35) f.push({name:"高温", val:t.toFixed(1), unit:"°C", level:3, advice:"高温，防暑降温、避开正午露天作业"});
  else if(t<=0) f.push({name:"低温/结冰", val:t.toFixed(1), unit:"°C", level:3, advice:"结冰/霜冻，道路与设备防滑"});
  else if(t>=32) f.push({name:"高温", val:t.toFixed(1), unit:"°C", level:1, advice:"偏热，注意防暑"});
  return f;
}
function updateReasonPanel(){
  if(SEL<0 || !RR){ RR.style.display="none"; return; }
  const pt=DATA.points[SEL], h=0;
  const rc=riskClassAtHour(pt,h), factors=riskFactorsAtHour(pt,h);
  const lvlTxt={ok:"低风险",warn:"注意",danger:"高风险"}[rc];
  const lvlCls={ok:"ok",warn:"warn",danger:"danger"}[rc];
  let html=`<div class="rr-h"><b>井位中心</b> ${pt.loc}</div>`;
  html+=`<div class="rr-sev badge ${lvlCls}">当前风险：${lvlTxt}</div>`;
  if(!factors || factors.length===0){
    html+=`<div class="rr-ok">该井位各要素均在安全范围内，无主要风险。</div>`;
  } else {
    html+=`<div class="rr-list">`+factors.map(f=>`<div class="rr-item ${f.level>=3?'d':(f.level>=2?'w':'')}">· ${f.name} ${f.val}${f.unit} — ${f.advice}</div>`).join("")+`</div>`;
  }
  if(pt.hx){
    html+=`<div class="rr-cur">当前值：气温 <b>${pt.hx.temp[0].toFixed(1)}℃</b> · 持续风 <b>${pt.hx.wind[0].toFixed(1)} m/s</b> · 阵风 <b>${pt.hx.gust[0].toFixed(1)} m/s</b> · 小时降水 <b>${pt.hx.precip[0].toFixed(1)} mm</b></div>`;
  }
  html+=`<div class="rr-peaks">`
    +`<div class="rr-pc"><div class="k">气温区间</div><div class="v">${pt.tmin}~${pt.tmax}°C</div></div>`
    +`<div class="rr-pc"><div class="k">阵风峰值</div><div class="v">${pt.gustMax} m/s</div></div>`
    +`<div class="rr-pc"><div class="k">持续风峰值</div><div class="v">${pt.windMax} m/s</div></div>`
    +`<div class="rr-pc"><div class="k">日降水峰值</div><div class="v">${pt.pMax} mm</div><div class="s">${pt.pMaxDay?pt.pMaxDay.slice(5):""}</div></div>`
    +`</div>`;
  RR.innerHTML=html; RR.style.display="block";
}

const EXPLORER = document.getElementById("explorerCharts");
const ELEM_DEFS = {
  temp:  {name:"气温", unit:"°C", type:"line2", keys:["tempMin","tempMax"], colors:["#2E7DA8","#E0822C"], labels:["最低温","最高温"],
          thr:[{v:35,color:"#C0392B",label:"高温35°"},{v:0,color:"#2E7DA8",label:"0°"}]},
  precip:{name:"降水", unit:"mm", type:"bar", keys:["precip"], colors:["#7FB3D5"],
          thr:[{v:50,color:"#C0392B",label:"暴雨50"},{v:25,color:"#E0822C",label:"大雨25"}]},
  wind:  {name:"风速/阵风", unit:"m/s", type:"line2", keys:["windMax","gustMax"], colors:["#1F7A6B","#8E44AD"], labels:["持续风","阵风"],
          thr:[{v:10.8,color:"#E0822C",label:"6级10.8"},{v:17.2,color:"#C0392B",label:"8级17.2"}]},
};
const ELEM_ORDER = ["precip","wind","temp"];
function selectedElems(){
  const checked = Array.from(document.querySelectorAll('.elem-row input:checked')).map(c=>c.value);
  return ELEM_ORDER.filter(k=>checked.includes(k));
}
function pointLine(svg, labels, series, opt){
  const W=680,Hh=230,pl=40,pr=12,pt=14,pb=24; svg.setAttribute("viewBox",`0 0 ${W} ${Hh}`); svg.innerHTML="";
  const n=labels.length;
  let lo=Infinity,hi=-Infinity;
  series.forEach(s=>s.data.forEach(v=>{ if(v<lo)lo=v; if(v>hi)hi=v; }));
  if(!isFinite(lo)){lo=0;hi=1;}
  const pad=(hi-lo)*0.15||1; lo-=pad; hi+=pad;
  const X=i=> pl+(W-pl-pr)*(n<=1?0.5:i/(n-1));
  const Y=v=> pt+(Hh-pt-pb)*(1-(v-lo)/(hi-lo));
  [lo,(lo+hi)/2,hi].forEach(tv=>{ svg.appendChild(el("line",{x1:pl,y1:Y(tv),x2:W-pr,y2:Y(tv),stroke:"#EEE",["stroke-width"]:1}));
    const tx=el("text",{x:pl-5,y:Y(tv)+3,["text-anchor"]:"end","font-size":10,fill:"#9aa0a4"}); tx.textContent=Math.round(tv); svg.appendChild(tx); });
  (opt.thresholds||[]).forEach(th=>{ if(th.v<lo||th.v>hi)return;
    svg.appendChild(el("line",{x1:pl,y1:Y(th.v),x2:W-pr,y2:Y(th.v),stroke:th.color,["stroke-width"]:1.4,["stroke-dasharray"]:"5 4",opacity:.85}));
    const tx=el("text",{x:W-pr,y:Y(th.v)-4,["text-anchor"]:"end","font-size":10,fill:th.color,["font-weight"]:"700"}); tx.textContent=th.label; svg.appendChild(tx); });
  const step=Math.max(1,Math.ceil(n/7));
  for(let i=0;i<n;i+=step){ const tx=el("text",{x:X(i),y:Hh-8,["text-anchor"]:"middle","font-size":10,fill:"#9aa0a4"}); tx.textContent=labels[i]; svg.appendChild(tx); }
  series.forEach(s=>{ let pts=""; s.data.forEach((v,i)=>{ const x=X(i),y=Y(v); pts+=(i?"L":"M")+x.toFixed(1)+" "+y.toFixed(1)+" "; });
    svg.appendChild(el("path",{d:pts,fill:"none",stroke:s.color,["stroke-width"]:2,["stroke-linejoin"]:"round",["stroke-linecap"]:"round"}));
    const mi=s.data.indexOf(Math.max(...s.data)); svg.appendChild(el("circle",{cx:X(mi),cy:Y(s.data[mi]),r:3,fill:s.color,stroke:"#fff",["stroke-width"]:1.5})); });
}
function pointBar(svg, labels, vals, opt){
  const W=680,Hh=230,pl=40,pr=12,pt=14,pb=24; svg.setAttribute("viewBox",`0 0 ${W} ${Hh}`); svg.innerHTML="";
  const n=labels.length, yMax=opt.yMax;
  const X=i=> pl+(W-pl-pr)*(n<=1?0.5:i/(n-1));
  const Y=v=> pt+(Hh-pt-pb)*(1-v/yMax);
  [0,yMax/2,yMax].forEach(tv=>{ svg.appendChild(el("line",{x1:pl,y1:Y(tv),x2:W-pr,y2:Y(tv),stroke:"#EEE",["stroke-width"]:1}));
    const tx=el("text",{x:pl-5,y:Y(tv)+3,["text-anchor"]:"end","font-size":10,fill:"#9aa0a4"}); tx.textContent=Math.round(tv); svg.appendChild(tx); });
  (opt.thresholds||[]).forEach(th=>{ if(th.v>yMax)return;
    svg.appendChild(el("line",{x1:pl,y1:Y(th.v),x2:W-pr,y2:Y(th.v),stroke:th.color,["stroke-width"]:1.4,["stroke-dasharray"]:"5 4",opacity:.85}));
    const tx=el("text",{x:W-pr,y:Y(th.v)-4,["text-anchor"]:"end","font-size":10,fill:th.color,["font-weight"]:"700"}); tx.textContent=th.label; svg.appendChild(tx); });
  const step=Math.max(1,Math.ceil(n/7));
  const bw=((W-pl-pr)/n)*0.62;
  vals.forEach((v,i)=>{ const x=X(i), y=Y(v), h=Hh-pt-pb-y;
    const color=v>=50?"#C0392B":(v>=25?"#E0822C":(v>=10?"#7FB3D5":"#BCD7E8"));
    svg.appendChild(el("rect",{x:x-bw/2,y:y,width:bw,height:Math.max(h,0.5),rx:3,fill:color}));
    if(v>0 && i%step===0){ const tx=el("text",{x:x,y:y-4,["text-anchor"]:"middle","font-size":9.5,fill:"#7a8086"}); tx.textContent=v; svg.appendChild(tx); } });
  for(let i=0;i<n;i+=step){ const tx=el("text",{x:X(i),y:Hh-9,["text-anchor"]:"middle","font-size":10,fill:"#9aa0a4"}); tx.textContent=labels[i]; svg.appendChild(tx); }
}
function renderExplorer(){
  if(SEL<0){ EXPLORER.innerHTML='<div class="empty-tip">暂无选中井位。</div>'; document.getElementById("explorerInfo").innerHTML=''; return; }
  const pt=DATA.points[SEL];
  const riskTxt={ok:"低风险",warn:"注意",danger:"高风险"}[pt.risk];
  const riskCls={ok:"ok",warn:"warn",danger:"danger"}[pt.risk];
  document.getElementById("explorerInfo").innerHTML =
     `<b>井位中心</b> · ${pt.loc} · <span class="badge ${riskCls}">${riskTxt}</span>`;
  EXPLORER.innerHTML="";
  const labs=DATA.meta.dailyDates.map(d=>d.slice(5));
  const sel=selectedElems();
  if(sel.length===0){ EXPLORER.innerHTML='<div class="empty-tip">请在上方勾选至少一个要素。</div>'; return; }
  sel.forEach(k=>{
    const def=ELEM_DEFS[k];
    const box=document.createElement("div"); box.className="ec";
    const h=document.createElement("div"); h.className="ec-h"; h.textContent=`${def.name}（${def.unit}）`;
    const svg=document.createElementNS(NS,"svg"); svg.setAttribute("class","chart"); svg.setAttribute("preserveAspectRatio","none");
    box.appendChild(h); box.appendChild(svg); EXPLORER.appendChild(box);
    if(def.type==="bar"){
      const vals=pt.series[def.keys[0]];
      const dmax=Math.max(...vals,0);
      let yMax, thresholds;
      if(dmax < 5){ yMax=5; thresholds=[{v:5,color:"#7FB3D5",label:"5mm"}]; }
      else { yMax=Math.max(10, Math.ceil((dmax*1.1)/5)*5); thresholds=[{v:10,color:"#C0392B",label:"大雨 10mm"}]; }
      pointBar(svg, labs, vals, {yMax:yMax, thresholds:thresholds});
    } else {
      const series=def.keys.map((kk,i)=>({name:def.labels[i],color:def.colors[i],data:pt.series[kk]}));
      pointLine(svg, labs, series, {thresholds:def.thr});
    }
  });
}
document.querySelectorAll('.elem-row input').forEach(c=>c.addEventListener("change", renderExplorer));

// ============ 单井位：默认直接展示该井曲线 + 风险面板（无地图） ============
SEL = 0;
renderExplorer();
updateReasonPanel();

// ---- 三页签切换 ----
function showTab(id){ document.querySelectorAll('.tabpane').forEach(p=>p.classList.toggle('active',p.id===id));
  document.querySelectorAll('.tabbtn').forEach(b=>b.classList.toggle('active',b.dataset.tab===id)); }
document.querySelectorAll('.tabbtn').forEach(b=>b.addEventListener('click',()=>showTab(b.dataset.tab)));
</script>
</body>
</html>
"""

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
#  主流程
# ======================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="钻井工程/区域名称，如 钻井工程")
    ap.add_argument("--wells", default="", help="井位点 KML（含多个 <Placemark><Point>），逗号分隔可传多个项目 KML")
    ap.add_argument("--data", default="", help="离线模式：读取单个井位 _data.json 重渲染无地图井位页")
    ap.add_argument("--outdir", default=".", help="井位 html 输出目录")
    ap.add_argument("--datadir", default="", help="_data.json 落盘目录（默认=outdir）")
    ap.add_argument("--days", type=int, default=14, help="预报天数，默认 14（未来 2 周）")
    ap.add_argument("--from-today", action="store_true", help="从今天 0 时开始（默认从明天 0 时开始）")
    ap.add_argument("--apikey", default="6aiF2mXsB3K7YcjT")
    ap.add_argument("--model", default="")
    ap.add_argument("--save-data", dest="save_data", action="store_true", default=True)
    ap.add_argument("--no-save-data", dest="save_data", action="store_false")
    args = ap.parse_args()

    base = os.path.abspath(args.outdir)
    os.makedirs(base, exist_ok=True)
    datadir = os.path.abspath(args.datadir) if args.datadir else base
    os.makedirs(datadir, exist_ok=True)
    _now = datetime.datetime.now()
    today = _now.strftime("%Y-%m-%d")
    _start_day = _now if args.from_today else (_now + datetime.timedelta(days=1))
    _end_day = _start_day + datetime.timedelta(days=args.days - 1)
    START_DATE = _start_day.strftime("%Y-%m-%d")
    END_DATE = _end_day.strftime("%Y-%m-%d")

    DEFAULT_KEY = "6aiF2mXsB3K7YcjT"
    APIKEY_ARG = args.apikey if args.apikey and args.apikey != DEFAULT_KEY else ""
    key_suffix = f"&apikey={APIKEY_ARG}" if APIKEY_ARG else ""
    HOURLY = "temperature_2m,precipitation,rain,wind_speed_10m,wind_gusts_10m"

    # ---------- 离线：单个井位重渲染 ----------
    if args.data:
        if not os.path.exists(args.data):
            print("⚠️ --data 文件不存在:", args.data); sys.exit(1)
        payload = json.load(open(args.data, encoding="utf-8"))
        DATA_JSON = json.dumps(payload, ensure_ascii=False)
        html = WELL_TEMPLATE.replace("__DATA__", DATA_JSON).replace("__TITLE__", f"{payload['meta']['name']} · 钻井井位天气看板")
        html = embed_font(html)
        out = os.path.join(base, args.name + ".html") if args.name.endswith(".html") else os.path.join(base, (args.name or payload["meta"]["name"]) + ".html")
        with open(out, "w", encoding="utf-8") as f: f.write(html)
        print("HTML written (offline):", out, len(html), "bytes"); print("DONE"); return

    # ---------- 在线：解析井位点 + 取数 + 生成 ----------
    # 注：井位地图 index.html 已拆出为独立技能 weather-engineering-index
    #     （scripts/build_wells_index.py），本脚本不再生成 index。
    if not args.wells:
        print("⚠️ 需提供 --wells <井位点KML> 或 --data"); sys.exit(1)
    if not FETCH_ENABLED:
        print("⚠️ 实时数据采集已关闭（FETCH_ENABLED=False），请用 --data。"); sys.exit(1)

    wells = []
    for wk in args.wells.split(","):
        wk = wk.strip()
        if not wk: continue
        _, ws = parse_wells_kml(wk)
        print(f"井位点 KML: {wk} → {len(ws)} 个井位")
        wells += ws
    if not wells:
        print("⚠️ 未解析到任何井位点"); sys.exit(1)

    # 一次性批量取数（Open-Meteo 多坐标）
    coords = [(w["lon"], w["lat"]) for w in wells]
    lats_s = ",".join(str(c[1]) for c in coords)
    lons_s = ",".join(str(c[0]) for c in coords)
    date_params = (f"&forecast_days={args.days}" if args.from_today
                   else f"&start_date={START_DATE}&end_date={END_DATE}")
    base_params = (f"latitude={lats_s}&longitude={lons_s}"
                   f"&hourly={HOURLY}{date_params}"
                   f"&wind_speed_unit=ms"
                   f"&timezone=Asia%2FShanghai{key_suffix}")
    url = f"https://api.open-meteo.com/v1/forecast?{base_params}" + (f"&models={args.model}" if args.model else "")
    print(f"Fetching 井位 {len(coords)} 个 ...")
    d = http_get_json(url, timeout=90)
    locs = d if isinstance(d, list) else [d]
    if len(locs) != len(coords):
        print(f"⚠️ 返回坐标数 {len(locs)} ≠ 请求 {len(coords)}，尝试逐个补取")
    times = [str(t) for t in locs[0]["hourly"]["time"]]
    dailyDates = sorted({t[:10] for t in times})

    generated = []
    used_names = set()
    for i, w in enumerate(wells):
        loc = locs[i] if i < len(locs) else None
        if loc is None:
            print(f"  ⚠️ 井位 {w['name']} 无预报数据，跳过"); continue
        payload, point, SEV, SEVL = build_well_payload(i, w, loc, times, dailyDates,
                                                        START_DATE, END_DATE, today,
                                                        args.model or "open-meteo 默认融合模型")
        DATA_JSON = json.dumps(payload, ensure_ascii=False)
        pin = slug(w["name"])
        # 仅针对本次运行内的井位集合去重；刷新时直接覆盖旧文件，不追加 -N 后缀
        cand = pin; k = 2
        while cand in used_names:
            cand = f"{pin}-{k}"; k += 1
        used_names.add(cand)
        html_name = cand + ".html"
        html = WELL_TEMPLATE.replace("__DATA__", DATA_JSON).replace("__TITLE__", f"{w['name']} · 钻井井位天气看板")
        html = embed_font(html)
        with open(os.path.join(base, html_name), "w", encoding="utf-8") as f: f.write(html)
        print(f"  ✓ 井位 html: {html_name} (sev={SEVL})")
        if args.save_data:
            dp = os.path.join(datadir, cand + "_data.json")
            with open(dp, "w", encoding="utf-8") as f: f.write(DATA_JSON)
            print(f"  ✓ data: {os.path.basename(dp)}")
        generated.append((w, html_name, payload, point, SEV, SEVL))

    print(f"  ✓ 共生成 {len(generated)} 个井位看板 → {base}")
    print("  提示：井位地图 index.html 请用 weather-engineering-index 技能的 "
          "build_wells_index.py 单独生成")
    print("DONE")

if __name__ == "__main__":
    main()
