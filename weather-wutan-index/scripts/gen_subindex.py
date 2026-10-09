#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""物探项目两周天气看板 · 多项目总览页（index.html）生成器。

从 beidou/{wutan,engineering}/data 下全部 *_data.json 合并生成总览 index.html：
按风险等级降序排列项目卡片，顶部含等级统计行与「未来 2 天（48小时）风险」聚焦描述。
卡片风险评级（高度警惕/重点关注/需关注/整体适宜）与焦点描述均按「未来 48 小时（近 2 天）」口径
（meta.sevNear / peaksNear），与看板 t1「重点提示」横幅保持一致；NEAR_DAYS=2，
超出该窗口的远预报仅以「临近时再提示」一句话点出，不作主风险。
"""

import json, os, glob, argparse, base64, re

# 项目根目录（其下含 beidou/{wutan,engineering}/{data,html}）。
# 三级回退，顺序：环境变量 BEIDOU_WORK > --base > 从脚本位置自动上溯。
# （绝不使用形如 "<WORK>" 的字面量占位符——那会让默认路径永远指向不存在的目录。）
def _detect_base():
    here = os.path.dirname(os.path.abspath(__file__))
    d = here
    while True:
        if os.path.isdir(os.path.join(d, "beidou")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return here  # 上溯失败：退回脚本所在目录，由调用方显式 --base
        d = parent

DEFAULT_BASE = os.environ.get("BEIDOU_WORK") or _detect_base()
BASE = DEFAULT_BASE
BEIDOU = os.path.join(BASE, "beidou")
DATA_WT = os.path.join(BEIDOU, "wutan", "data")
DATA_ZJ = os.path.join(BEIDOU, "engineering", "data")

# ---------- 页头背景图 ----------
# 图存在「看板技能」里（weather-wutan-html/assets/hero-bg.jpg），本技能只负责引用，
# 不另存一份（避免两张图各自更新后不一致）。三级探测，顺序：
#   环境变量 BEIDOU_HERO_BG > 本技能 assets/ > 兄弟技能 weather-wutan-html/assets/
# 全找不到时静默降级（不注入 CSS，页头回到纯色底），不报错、不中断生成。
_HERE = os.path.dirname(os.path.abspath(__file__))
_HERO_CANDIDATES = (
    os.environ.get("BEIDOU_HERO_BG") or "",
    os.path.join(_HERE, "..", "assets", "hero-bg.jpg"),
    os.path.join(_HERE, "..", "..", "weather-wutan-html", "assets", "hero-bg.jpg"),
)
HERO_BLEED = "16px"          # 与 body 左右 padding 一致 → 背景正好贴到视口边
HERO_FADE = (("0%", ".78"), ("46%", ".38"), ("100%", ".03"),)

# ===== 五要素预警阈值（2026-10-09 用户定；降水/降雪=mm/h 小时级，阵风 m/s，温度 ℃）=====
# 文本严格按用户口径；原字典笔误已修正：阵风 0 级「阵风阵风」→「阵风正常」；
# 高温 40 度原误写成 key=2（与 37 度重复），更正为 key=3。
RAIN_ALERT  = {0: "降雨正常", 1: "小雨预警(0.2mm/h)", 2: "中雨预警(1.5mm/h)",
               3: "大雨预警(3mm/h)", 4: "暴雨预警(6mm/h)", 5: "大暴雨预警(15mm/h)"}
SNOW_ALERT  = {0: "正常", 1: "小雪预警(>0.1mm/h)", 2: "中雪预警(>0.5mm/h)",
               3: "大雪预警(>1mm/h)", 4: "暴雪预警(>2mm/h)"}
GUST_ALERT  = {0: "阵风正常", 1: "劲风五级预警(8.0m/s)", 2: "强风六级预警(10.8m/s)",
               3: "疾风七级预警(13.9m/s)", 4: "大风八级预警(17.2m/s)"}
THIGH_ALERT = {0: "温度正常", 1: "35度高温预警（35度）", 2: "37度酷热预警（37度）",
               3: "40度极端高温预警（40度）"}
TLOW_ALERT  = {0: "温度正常", 1: "零下5度寒冷预警（零下5度）",
               2: "零下15度严寒预警（零下15度）", 3: "零下25度极寒预警（零下25度）"}
# index 卡片专用：只留等级名，去掉 6mm/h、13.9m/s、35度 这类阈值数字
RAIN_ALERT_S  = {0: "降雨正常", 1: "小雨预警", 2: "中雨预警",
               3: "大雨预警", 4: "暴雨预警", 5: "大暴雨预警"}
SNOW_ALERT_S  = {0: "正常", 1: "小雪预警", 2: "中雪预警",
               3: "大雪预警", 4: "暴雪预警"}
GUST_ALERT_S  = {0: "阵风正常", 1: "劲风五级预警", 2: "强风六级预警",
               3: "疾风七级预警", 4: "大风八级预警"}
THIGH_ALERT_S = {0: "温度正常", 1: "高温预警", 2: "酷热预警", 3: "极端高温预警"}
TLOW_ALERT_S  = {0: "温度正常", 1: "寒冷预警", 2: "严寒预警", 3: "极寒预警"}

def rain_alert(mmh):
    if mmh is None: return 0
    if mmh >= 15: return 5
    if mmh >= 6:  return 4
    if mmh >= 3:  return 3
    if mmh >= 1.5: return 2
    if mmh >= 0.2: return 1
    return 0

def snow_alert(mmh):
    if mmh is None: return 0
    if mmh >= 2:   return 4
    if mmh >= 1:   return 3
    if mmh >= 0.5: return 2
    if mmh >= 0.1: return 1
    return 0

def gust_alert(mps):
    if mps is None: return 0
    if mps >= 17.2: return 4
    if mps >= 13.9: return 3
    if mps >= 10.8: return 2
    if mps >= 8.0:  return 1
    return 0

def thigh_alert(t):
    if t is None: return 0
    if t >= 40: return 3
    if t >= 37: return 2
    if t >= 35: return 1
    return 0

def tlow_alert(t):
    if t is None: return 0
    if t <= -25: return 3
    if t <= -15: return 2
    if t <= -5:  return 1
    return 0

def alert_items(rain_mmh, snow_mmh, gust, tmax, tmin, verbose=True):
    """返回触发的预警文字列表（仅 level>=1）。各要素独立判定，可同时多条。
    verbose=False 时只给等级名称、不带任何阈值数值（index 卡片用，避免满屏数字）。"""
    out = []
    r = rain_alert(rain_mmh)
    if r: out.append(RAIN_ALERT[r] if verbose else RAIN_ALERT_S[r])
    s = snow_alert(snow_mmh)
    if s: out.append(SNOW_ALERT[s] if verbose else SNOW_ALERT_S[s])
    g = gust_alert(gust)
    if g: out.append(GUST_ALERT[g] if verbose else GUST_ALERT_S[g])
    h = thigh_alert(tmax)
    if h: out.append(THIGH_ALERT[h] if verbose else THIGH_ALERT_S[h])
    l = tlow_alert(tmin)
    if l: out.append(TLOW_ALERT[l] if verbose else TLOW_ALERT_S[l])
    return out

def _find_hero():
    for p in _HERO_CANDIDATES:
        if p and os.path.exists(p):
            return p
    return None

def hero_css(bleed=HERO_BLEED):
    """生成页头背景 CSS；无图时返回空串（静默降级，页面照常生成）。"""
    img = _find_hero()
    if not img:
        print("  · hero bg: 未找到 hero-bg.jpg → 页头用纯色底")
        return ""
    try:
        with open(img, "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode()
    except Exception as e:
        print("  · hero bg SKIPPED:", repr(e))
        return ""
    uri = "data:image/jpeg;base64," + b64
    stops = ",".join(f"rgba(255,255,255,{a}) {p}" for p, a in HERO_FADE)
    return (
        "  .heroarea{position:relative;isolation:isolate;}\n"
        "  .heroarea::before{content:\"\";position:absolute;z-index:-1;"
        f"top:-10px;bottom:-10px;left:-{bleed};right:-{bleed};"
        "border-radius:0 0 12px 12px;background-color:#EEF0F2;"
        f'background-image:linear-gradient(180deg,{stops}),url("{uri}");'
        "background-size:100% 100%,cover;background-position:center top,center center;"
        "background-repeat:no-repeat,no-repeat;}\n"
        "  .heroarea h1,.heroarea .sub,.heroarea .summary{position:relative;z-index:1;"
        "text-shadow:0 1px 0 rgba(255,255,255,.85);}\n"
        "  .heroarea .sub{color:#42505A;text-shadow:0 0 7px rgba(255,255,255,.95),0 1px 0 rgba(255,255,255,.9);}\n"
        "  .heroarea .extlink{box-shadow:0 2px 8px rgba(31,122,107,.34);}\n"
    )

SEV_COLOR = {3: "#C0392B", 2: "#E0822C", 1: "#E0A92C", 0: "#2E8B57"}
SEV_LABEL = {3: "高度警惕", 2: "重点关注", 1: "需关注", 0: "整体适宜"}
SEV_ORDER = (3, 2, 1, 0)
def short_pin(pin):
    """子目录短名：去掉工区/测线后缀（-gongqu / -cexian / -cesian），如
    tongjiang-sanwei-gongqu -> tongjiang-sanwei、cangbeitianshan-cesian -> cangbeitianshan。
    工程类数据文件名本无此后缀，原样返回。"""
    s = pin
    for suf in ("-gongqu", "-cexian", "-cesian"):
        if s.endswith(suf):
            return s[: -len(suf)]
    return s


NEAR_DAYS = 2  # 风险汇报聚焦近 2 天（48小时）；超出窗口的远预报不可靠，仅一句话"临近再提示"

def mmdd(s):
    return s[5:] if s else s

def _day_arrays(d):
    """逐日（全窗口）跨作业点聚合：降水、阵风、持续风、最低/最高气温。"""
    daily = d.get("daily", []) or []
    n = len(daily)
    P = [(x.get("p") or 0) for x in daily]
    Gd = [None] * n; Wd = [None] * n; TMd = [None] * n; TXd = [None] * n
    for p in d.get("points", []):
        s = p.get("series", {}) or {}
        gm = s.get("gustMax"); wm = s.get("windMax"); tm = s.get("tempMin"); tx = s.get("tempMax")
        if not gm:
            continue
        for i in range(min(n, len(gm))):
            if Gd[i] is None or gm[i] > Gd[i]: Gd[i] = gm[i]
            if Wd[i] is None or wm[i] > Wd[i]: Wd[i] = wm[i]
            if TMd[i] is None or tm[i] < TMd[i]: TMd[i] = tm[i]
            if TXd[i] is None or tx[i] > TXd[i]: TXd[i] = tx[i]
    return daily, P, Gd, Wd, TMd, TXd

def project_near(d, wd=NEAR_DAYS):
    """返回项目近 wd 天 + 全窗口极值及对应日序号（用于判断远预报是否超出窗口）。"""
    daily, P, Gd, Wd_, TMd, TXd = _day_arrays(d)
    n = len(daily)
    near_p = [x for x in P[:wd] if x is not None]
    near_g = [x for x in Gd[:wd] if x is not None]
    near_w = [x for x in Wd_[:wd] if x is not None]
    near_tm = [x for x in TMd[:wd] if x is not None]
    near_tx = [x for x in TXd[:wd] if x is not None]
    pmax_all = max(P) if P else 0
    pmax_all_i = P.index(pmax_all) if P else 0
    gmax_all = max((g for g in Gd if g is not None), default=0)
    gmax_all_i = Gd.index(gmax_all) if any(g is not None for g in Gd) else 0
    tmin_all = min((t for t in TMd if t is not None), default=99)
    tmin_all_i = TMd.index(tmin_all) if any(t is not None for t in TMd) else 0
    return {
        "n": n,
        "dates": [x.get("date", "") for x in daily],
        "psum": round(sum(near_p), 1) if near_p else 0,
        "pmax": max(near_p) if near_p else 0,
        "pmax_i": (P[:wd].index(max(P[:wd])) if near_p else 0),
        "gust": max(near_g) if near_g else 0,
        "wind": max(near_w) if near_w else 0,
        "tmin": min(near_tm) if near_tm else 99,
        "tmax": max(near_tx) if near_tx else -99,
        "pmax_all": pmax_all,
        "pmax_all_i": pmax_all_i,
        "gust_all": gmax_all,
        "gust_all_i": gmax_all_i,
        "tmin_all": tmin_all,
        "tmin_all_i": tmin_all_i,
    }

def build_near_term_desc(rows, wd=NEAR_DAYS):
    """生成「未来 2 天（48小时）风险」聚焦描述（仅基于 _data.json 前 wd 天，不取远预报为主风险）。"""
    valid = [r for r in rows if r.get("near") and r["near"]["n"] >= wd]
    if not valid:
        return ""
    ref = next((r for r in valid if r["near"]["dates"]), None)
    dates = ref["near"]["dates"] if ref else []
    start = dates[0][5:] if dates else "?"
    end = dates[wd - 1][5:] if len(dates) >= wd else (dates[-1][5:] if dates else "?")
    # 远预报极端（超出近 wd 天窗口的暴雨，仅一句话点出）
    far = []
    for r in valid:
        nr = r["near"]
        if nr["pmax_all_i"] >= wd and nr["pmax_all"] >= 50 and nr["dates"]:
            dstr = nr["dates"][nr["pmax_all_i"]][5:]
            far.append((nr["pmax_all"], f"{r['name']} {dstr} 单日{nr['pmax_all']:.0f}mm（暴雨）"))
    far.sort(reverse=True)
    far_txt = ""
    if far:
        ex = "、".join(t for _, t in far[:3])
        far_txt = f"周中后期极端暴雨（如 {ex}）已超出可靠预报范围，暂不纳入，临近时再提示。"
    # 近 wd 天内的高影响项目
    rain = [r for r in valid if r["near"]["pmax"] >= 25 and r["near"]["pmax_i"] < wd]
    cold = [r for r in valid if r["near"]["gust"] >= 17.2 or r["near"]["tmin"] <= 0]
    rain.sort(key=lambda r: -r["near"]["psum"])
    cold.sort(key=lambda r: -r["near"]["gust"])
    parts = ["整体以分散性降水为主"]
    if cold:
        cl = []
        for r in cold[:4]:
            nr = r["near"]; bits = []
            if nr["gust"] >= 8.0: bits.append(GUST_ALERT_S[gust_alert(nr["gust"])])
            if nr["tmin"] <= -5: bits.append(TLOW_ALERT_S[tlow_alert(nr["tmin"])])
            elif nr["tmin"] <= 0: bits.append(TLOW_ALERT_S[1] + "（结冰/霜冻）")
            cl.append(f"{r['name']}（{'、'.join(bits)}）")
        parts.append("最需关注高原/高海拔测线大风低温——" + "、".join(cl) + "，做好防风保暖与设备加固")
    if rain:
        rl = []
        for r in rain[:4]:
            nr = r["near"]
            lvl = "暴雨" if nr["pmax"] >= 50 else "大雨"
            dstr = nr["dates"][nr["pmax_i"]][5:] if nr["dates"] else ""
            rl.append(f"{r['name']} {dstr} 单日{nr['pmax']:.1f}mm（{lvl}）")
        parts.append("、".join(rl) + " 等需防范山洪、泥水淹泡与进场道路中断")
    body = "；".join(parts) + "。"
    if far_txt:
        # 先说未来 2 天（近 wd 天）风险，周中后期（远预报）情况放后面，仅一句话点出。
        body = body + " " + far_txt
    return f'<span class="nt-h">未来 {wd} 天风险（{start} ~ {end}）</span>{body}'

def build_focus(d, is_eng=False):
    # 焦点描述按「未来 48 小时（近 2 天）」口径，与前端 t1「重点提示」及风险评级保持一致；
    # 预警文字严格套用 2026-10-09 用户定的五要素阈值（mm/h 小时级降水/降雪、m/s 阵风、℃ 温度）。
    # 旧数据缺 peaksNear 时回退到全周期 peaks，避免中断。
    items = []
    if not is_eng:
        p = d.get("peaksNear") or d.get("peaks", {}) or {}
        # 累计降水优先用未来 48 小时逐小时窗口真实累计（pSum48），不用两日 focusTotal
        if p.get("pSum48"):
            items.append(f"未来 48 小时累计降水 {round(p['pSum48'],1)}mm")
        # 五要素预警：降水/降雪取小时峰值(mm/h)，阵风/温度取极值
        # index 汇总文字只报等级名（不带 mm/h、m/s、℃ 阈值数值，避免一眼全是数字）
        items += alert_items(p.get("pHourMax"), p.get("snowMax"),
                             p.get("gustMax"), p.get("tmax"), p.get("tmin"),
                             verbose=False)
    else:
        # 工程数据：从 summary 取小时级峰值（pHourMax/snowHourMax 由 build_points_data 现算）
        s = d.get("summary", {}) or {}
        if s.get("pHourMax") or s.get("snowHourMax") or s.get("maxGust") or s.get("maxTemp") is not None or s.get("minTemp") is not None:
            items += alert_items(s.get("pHourMax"), s.get("snowHourMax"),
                                 s.get("maxGust"), s.get("maxTemp"), s.get("minTemp"))
        if not items:
            # 兜底：缺 summary 时用 daily 前 2 天现算
            d2 = (d.get("daily") or [])[:2]
            if d2:
                cum = sum(x.get("precip", 0) for x in d2)
                gust = max((x.get("gustMax", 0) for x in d2), default=0)
                tmin = min((x.get("tempMin", 99) for x in d2), default=99)
                tmax = max((x.get("tempMax", -99) for x in d2), default=-99)
                e = []
                if cum >= 1:
                    e.append(f"累计降水 {round(cum,1)}mm")
                if gust >= 8.0:
                    e.append(GUST_ALERT[gust_alert(gust)])
                if tmin <= -5:
                    e.append(TLOW_ALERT[tlow_alert(tmin)])
                if tmax >= 35:
                    e.append(THIGH_ALERT[thigh_alert(tmax)])
                items = e or ["未来 2 天无明显强降雨与大风，整体适宜作业"]
    if not items:
        return "本期未触发极端天气预警阈值，整体适宜作业"
    return "；".join(items[:4])

def sev_eng_recent(daily2):
    """石油工程数据的风险等级（近 2 天口径）。

    工程 *_data.json 的 meta 里没有 sevNear/sev（物探才有），必须在汇总时现算。
    阈值与 weather-engineering-index 的 sev_of_recent 保持一致，避免两条线的
    卡片评级出现分歧：只取 daily 前 2 天聚合。
    """
    if not daily2:
        return 0
    pmax = max((d.get("precip", 0) for d in daily2), default=0)
    gust = max((d.get("gustMax", 0) for d in daily2), default=0)
    wind = max((d.get("windMax", 0) for d in daily2), default=0)
    tmax = max((d.get("tempMax", -99) for d in daily2), default=-99)
    tmin = min((d.get("tempMin", 99) for d in daily2), default=99)
    cum = sum(d.get("precip", 0) for d in daily2)
    if pmax >= 80 or gust >= 20.8 or tmax >= 38 or cum >= 150:
        return 3
    if pmax >= 50 or gust >= 17.2 or tmax >= 35 or tmin <= -5 or cum >= 80:
        return 2
    if pmax >= 12 or wind >= 10.8 or tmin <= 0 or cum >= 20:
        return 1
    return 0


def load_rows(dd, group, badge, pattern="*_data.json"):
    """扫描一个 data 目录并汇总成卡片行。

    两类数据的文件名约定不同，必须分别传 pattern，否则会读不到并误判为「空数据」：
      · 物探   beidou/wutan/data/*_data.json       （ pattern="*_data.json" 默认）
      · 石油工程 beidou/engineering/data/*.json     （ pattern="*.json" ）
    工程侧同时跳过 kind != point 的井位看板数据。
    """
    rows = []
    for f in sorted(glob.glob(os.path.join(dd, pattern))):
        d = json.load(open(f, encoding="utf-8"))
        m = d["meta"]
        if pattern == "*.json" and m.get("kind") != "point":
            continue
        pin = os.path.splitext(os.path.basename(f))[0]
        if pin.endswith("_data"):
            pin = pin[: -len("_data")]
        is_line = bool(d.get("isLine"))
        short = short_pin(pin)
        # 风险评级（高度警惕/重点关注/需关注/整体适宜）按「未来 48 小时（近 2 天）」口径，
        # 与看板 t1「重点提示」横幅保持一致；旧数据缺 sevNear 时回退到全周期 sev，避免中断。
        sev = m.get("sevNear", m.get("sev"))
        if sev is None:
            sev = sev_eng_recent((d.get("daily") or [])[:2]) if pattern == "*.json" else 0
        sev = sev or 0
        rows.append({
            "pin": pin, "short": short, "name": m["name"], "sev": sev,
            "color": SEV_COLOR[sev], "label": SEV_LABEL[sev],
            "focus": build_focus(d, is_eng=(pattern == "*.json")),
            "kind": "测线" if is_line else ("工区" if pattern == "*_data.json" else "点位"),
            # 工程数据的 meta 用 start_date/end_date，物探用 start/end；npts 工程也没有
            "start": mmdd(m.get("start") or m.get("start_date", "")),
            "end": mmdd(m.get("end") or m.get("end_date", "")),
            "npts": m.get("npts", len(d.get("points") or [])),
            "group": group, "badge": badge,
            "ndays": len(d.get("daily") or []),
            "near": project_near(d, NEAR_DAYS) if (d.get("daily") and d.get("points")) else None,
        })
    rows.sort(key=lambda r: (-r["sev"], r["name"]))
    return rows

def summary_line(label, n, rows):
    dist = {s: sum(1 for r in rows if r["sev"] == s) for s in SEV_ORDER}
    parts = [f'<span style="color:{SEV_COLOR[s]};font-weight:700">{SEV_LABEL[s]} {dist[s]}</span>'
             for s in SEV_ORDER if dist[s] > 0]
    return f'<b>{label}</b> {n} 个项目 ｜ ' + " · ".join(parts)

def card(r):
    # 子目录内链接走相对路径（仅文件名）
    return f'''        <a class="card" href="{r['short']}.html?from=index" style="--sev:{r['color']}">
          <span class="bar"></span>
          <div class="head"><span class="name">{r['name']}</span><span class="tag">{r['label']}</span><span class="ptype">{r['badge']}</span></div>
          <div class="focus">{r['focus']}</div>
          <div class="meta"><span>{r['kind']}</span><span>{r['start']} ~ {r['end']}</span><span>作业点 {r['npts']}</span></div>
          <span class="arrow">&rsaquo;</span>
        </a>'''

def page(title, sub_title, label, rows, out_path):
    hero = hero_css()          # 页头背景图 CSS；无图时为空串（静默降级）
    # 空数据保护：换机器时某一类（如只有物探、没有石油工程）可能一个 *_data.json 都没有，
    # 此时不能崩，输出一张「暂无数据」空页即可（rows 为空会让 min()/max() 抛 ValueError）。
    if not rows:
        html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  :root{{--bg:#F6F4F0; --card:#FFFFFF; --line:#EAE6DF; --ink:#242A2E; --sub:#6B7378; --accent:#1F7A6B;}}
  body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 "PingFang SC","Microsoft YaHei",system-ui,sans-serif;}}
  .wrap{{max-width:1080px;margin:0 auto;padding:24px 16px;}}
  .empty{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:28px;text-align:center;color:var(--sub);}}
{hero}</style></head>
<body><div class="wrap"><div class="heroarea"><h1>{title}</h1></div>
<div class="empty">暂无数据：未在 <code>{out_path}</code> 对应的 data 目录中找到 *_data.json。<br>
请先跑数据脚本生成看板数据。</div>
</div></body></html>'''
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(html)
        print(f"  · 空数据 → 已生成空页 {out_path}")
        return
    cards = "\n".join(card(r) for r in rows)
    summ = summary_line(label, len(rows), rows)
    near_desc = build_near_term_desc(rows, NEAR_DAYS)
    near_html = f'<div class="near-term">{near_desc}</div>' if near_desc else ""
    start = min(r["start"] for r in rows)
    end = max(r["end"] for r in rows)
    # 预报天数按实际数据跨度动态显示：两周=14天；若数据仍为 7 天则如实显示，避免错标成 两周。
    ndays = max((r.get("ndays") or 0) for r in rows)
    span = f"未来两周（{ndays} 天）" if ndays >= 13 else (f"未来 {ndays} 天" if ndays else "未来两周")
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  :root{{
    --bg:#F6F4F0; --card:#FFFFFF; --line:#EAE6DF; --ink:#242A2E; --sub:#6B7378;
    --accent:#1F7A6B; --shadow:0 1px 3px rgba(0,0,0,.06),0 6px 16px rgba(0,0,0,.05);
  }}
  *{{box-sizing:border-box;-webkit-tap-highlight-color:transparent;}}
  html,body{{margin:0;padding:0;}}
  body{{
    font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
    background:var(--bg); color:var(--ink); line-height:1.5; font-size:15px;
    padding:22px 16px 48px;
  }}
  .wrap{{max-width:1080px;margin:0 auto;}}
  h1{{font-size:19px;margin:0 0 5px;font-weight:700;}}
  .sub{{font-size:13px;color:var(--sub);margin-bottom:6px;}}
  .summary{{font-size:13px;color:var(--ink);margin:16px 0 4px;display:flex;gap:10px;flex-wrap:wrap;align-items:center;}}
  .summary b{{font-weight:700;}}
  .near-term{{font-size:13px;line-height:1.55;color:var(--ink);background:rgba(31,122,107,.06);border-left:3px solid var(--accent);border-radius:8px;padding:10px 13px;margin:6px 0 2px;}}
  .near-term .nt-h{{font-weight:700;color:var(--accent);margin-right:6px;}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:12px;margin-top:8px;}}
  a.card{{
    display:block;text-decoration:none;color:inherit;background:var(--card);border:1px solid var(--line);
    border-radius:14px;padding:13px 38px 13px 14px;box-shadow:var(--shadow);position:relative;overflow:hidden;
    transition:transform .12s ease, box-shadow .12s ease;
  }}
  a.card:hover{{transform:translateY(-2px);box-shadow:0 4px 8px rgba(0,0,0,.08),0 12px 24px rgba(0,0,0,.08);}}
  a.card .bar{{position:absolute;left:0;top:0;bottom:0;width:5px;background:var(--sev);}}
  a.card .head{{display:flex;align-items:center;gap:8px;}}
  a.card .name{{font-size:16px;font-weight:700;}}
  a.card .tag{{font-size:10.5px;font-weight:600;color:#fff;background:var(--sev);border-radius:20px;padding:2px 8px;white-space:nowrap;}}
  a.card .ptype{{font-size:10px;font-weight:600;border-radius:6px;padding:2px 6px;white-space:nowrap;background:rgba(31,122,107,.12);color:var(--accent);}}
  a.card .focus{{font-size:12.5px;margin-top:8px;color:var(--ink);line-height:1.45;}}
  a.card .meta{{font-size:11.5px;color:var(--sub);margin-top:9px;display:flex;gap:9px;flex-wrap:wrap;}}
  a.card .arrow{{position:absolute;right:13px;top:50%;transform:translateY(-50%);color:var(--sub);font-size:19px;font-weight:600;}}
  .legend{{margin-top:28px;font-size:12px;color:var(--sub);display:flex;gap:14px;flex-wrap:wrap;}}
  .legend i{{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px;vertical-align:-1px;}}
  .extlink{{display:inline-flex;align-items:center;gap:4px;font-size:13px;font-weight:700;color:#fff;background:var(--accent);padding:7px 14px;border-radius:20px;text-decoration:none;box-shadow:0 2px 6px rgba(31,122,107,.3);}}
  .extlink:hover{{background:#176254;transform:translateY(-1px);}}
{hero}</style>
</head>
<body>
<div class="wrap">
  <div class="heroarea">
  <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:6px"><h1 style="margin:0">{title}</h1><a class="extlink" href="https://leidian.wang" target="_blank" rel="noopener">北斗天气风险治理平台 ↗</a></div>
  <div class="sub">{span}（{start} ~ {end}）· 点击卡片进入对应项目看板</div>
  <div class="summary">{summ}</div>
  </div>
  {near_html}
  <div class="grid">
{cards}
  </div>
  <div class="legend">
    <span><i style="background:#C0392B"></i>高度警惕</span>
    <span><i style="background:#E0822C"></i>重点关注</span>
    <span><i style="background:#E0A92C"></i>需关注</span>
    <span><i style="background:#2E8B57"></i>整体适宜</span>
  </div>
</div>
<script async src="//busuanzi.ibruce.info/busuanzi/2.3/busuanzi.pure.mini.js"></script>
<div style="margin-top:16px;padding-top:8px;border-top:1px solid rgba(128,128,128,.18);font-size:11px;color:#9aa0a6;text-align:center;opacity:.6;letter-spacing:.3px">访问统计 · 本页阅读 <span id="busuanzi_container_page_pv"><span id="busuanzi_value_page_pv"></span> 次</span> · 全站访客 <span id="busuanzi_container_site_uv"><span id="busuanzi_value_site_uv"></span> 人</span></div>
</body>
</html>
'''
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    print("generated:", out_path, "| rows:", len(rows))

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="物探项目两周天气看板 · 多项目总览页（index.html）生成器")
    ap.add_argument("--base", default=DEFAULT_BASE,
                    help="项目根目录（其下含 beidou/{wutan,engineering}/data），默认当前工作区")
    ap.add_argument("--only", choices=["wutan", "engineering"], default=None,
                    help="只重建指定分类的子总览（默认两者都重建）")
    args = ap.parse_args()

    # 注意：这里必须用新的局部名，不能重新赋值全局 DATA_WT/DATA_ZJ——
    # 模块级下的「重新赋值」不会作用于 load_rows 读取的默认值；
    # 同理也不要在此处写 global 声明（模块级 global 会导致语法错误）。
    BASE = args.base
    BEIDOU = os.path.join(BASE, "beidou")
    print(f"  base = {BASE}")

    wt = load_rows(os.path.join(BEIDOU, "wutan", "data"), "物探", "物探")
    zj = load_rows(os.path.join(BEIDOU, "engineering", "data"), "石油工程", "石油工程",
                   pattern="*.json")

    if args.only in (None, "wutan"):
        page(
            title="中石化北斗运营中心 · 物探项目天气看板",
            sub_title=f"物探 {len(wt)} 个项目",
            label="物探",
            rows=wt,
            out_path=os.path.join(BEIDOU, "wutan", "html", "index.html"),
        )
    if args.only in (None, "engineering"):
        page(
            title="中石化北斗运营中心 · 石油工程项目天气看板",
            sub_title=f"石油工程 {len(zj)} 个项目",
            label="石油工程",
            rows=zj,
            out_path=os.path.join(BEIDOU, "engineering", "html", "index.html"),
        )
