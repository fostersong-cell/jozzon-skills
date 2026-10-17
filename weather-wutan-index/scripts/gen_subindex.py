#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""物探项目两周天气看板 · 多项目总览页（index.html）生成器。

从 beidou/{wutan,engineering}/data 下全部 *_data.json 合并生成总览 index.html：
按风险等级降序排列项目卡片，顶部含等级统计行与「未来 2 天（48小时）风险」聚焦描述。
卡片风险评级（高度警惕/重点关注/需关注/整体适宜）与焦点描述均按「未来 48 小时（近 2 天）」口径
（meta.sevNear / peaksNear），与看板 t1「重点提示」横幅保持一致；NEAR_DAYS=2。
第 3 天起的远预报（3-14 天）不纳入本总览，仅在各单项目看板内提示。
"""

import json, os, sys, glob, argparse, base64, re

# ---------- 复用 jozzonwx 共享分级（七要素，与物探看板/石油工程看板零漂移） ----------
# 2026-10-16 改造：本页的分级不再自带阈值字典，统一走 weather-common/jozzonwx.py。
_COMMON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "weather-common", "scripts")
if os.path.isdir(_COMMON):
    sys.path.insert(0, os.path.abspath(_COMMON))
import jozzonwx as JW

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

# ===== 七要素预警标签：统一引用 jozzonwx（JW.RAIN_ALERT / JW.RAIN_ALERT_S / ...）=====
# 2026-10-16 改造：旧的五要素阈值字典与 grading 函数全部删除，改走共享模块，
# 避免本页与物探看板、石油工程看板出现分级漂移。
RAIN_ALERT, RAIN_ALERT_S = JW.RAIN_ALERT, JW.RAIN_ALERT_S
SNOW_ALERT, SNOW_ALERT_S = JW.SNOW_ALERT, JW.SNOW_ALERT_S
GUST_ALERT, GUST_ALERT_S = JW.GUST_ALERT, JW.GUST_ALERT_S
WIND_ALERT, WIND_ALERT_S = JW.WIND_ALERT, JW.WIND_ALERT_S
UTCI_HOT, UTCI_HOT_S     = JW.UTCI_HOT, JW.UTCI_HOT_S
UTCI_COLD, UTCI_COLD_S   = JW.UTCI_COLD, JW.UTCI_COLD_S
VIS_ALERT, VIS_ALERT_S   = JW.VIS_ALERT, JW.VIS_ALERT_S
RAIN_H                   = JW.RAIN_H
rain_alert, snow_alert   = JW.grade_rain, JW.grade_snow
gust_alert, wind_alert   = JW.grade_gust, JW.grade_wind

# 概述排序权重：等级名 → 严重度（数字越小越严重）。用于「只保留最核心 1~2 项」时排序。
# 用户 2026-10-09 要求概述不要面面俱到，故按严重度取前二，其余项在项目页关键指标里看。
# 2026-10-16 补齐新增要素的等级名：均风（狂风十级）、体感（UTCI 冷/热）、能见度。
_FOCUS_RANK = {
    # 极高（lv4/5）
    "大暴雨预警": 1, "暴雪预警": 1, "狂风十级预警": 1, "飓风十二级预警": 1,
    "极热预警": 1, "极寒预警": 1,
    "酷寒预警": 2, "能见度极低预警": 1, "极端高温预警": 1, "高度警惕": 1,
    # 高（lv3）
    "暴雨预警": 3, "大雨预警": 4, "大雪预警": 3, "疾风七级预警": 7, "大风八级预警": 6,
    "酷热预警": 3, "严寒预警": 4, "能见度劣预警": 3,
    # 中（lv2）
    "中雨预警": 6, "中雪预警": 6, "强风六级预警": 4, "炎热预警": 6, "能见度差预警": 6,
    # 低（lv1）
    "小雨预警": 8, "小雪预警": 8, "劲风五级预警": 6, "偏热预警": 8, "寒冷预警": 7,
    "能见度偏低预警": 8,
    # 正常
    "降雨正常": 99, "正常": 99, "阵风正常": 99, "均风正常": 99,
    "温度正常": 99, "能见度正常": 99, "UTCI正常": 99,
}
# ⚠️ 该表仅遗留兼容（工程分支），**新代码别用**：标签在新口径下会跨要素重名——
# 「大风八级预警」既是均风 lv3 也是阵风 lv2（相差一整级），「狂风十级预警」既是均风 lv4
# 也是阵风 lv3。判要素/排严重度一律用 (kind, lv, lbl) 三元组，不靠标签查表。

def alert_items(rain_mmh, snow_mmh, gust, wind, appMax, appMin, visMin, verbose=True, min_lv=1):
    """返回触发的预警文字列表（默认仅 level>=1）。各要素独立判定，可同时多条。
    verbose=False 时只给等级名称、不带任何阈值数值（index 卡片用，避免满屏数字）。
    min_lv：只保留等级 >= min_lv 的要素，默认 1 = 低等级要素（小雨、五级风等）照常写出，
    因为它们是客观事实；用户澄清（2026-10-09）这些低等级**不写反而丢失信息**，
    只是它们**不足以抬高风险等级**——抬级只看「中雨及以上」或「任一 3 级预警」。
    2026-10-16：七要素（降雨/降雪/均风/阵风/体感 UTCI/能见度），plain 温度不再单独预警。"""
    out = []
    r = JW.grade_rain(rain_mmh)
    if r >= min_lv: out.append(JW.RAIN_ALERT[r] if verbose else JW.RAIN_ALERT_S[r])
    s = JW.grade_snow(snow_mmh)
    if s >= min_lv: out.append(JW.SNOW_ALERT[s] if verbose else JW.SNOW_ALERT_S[s])
    g = JW.grade_gust(gust)
    if g >= min_lv: out.append(JW.GUST_ALERT[g] if verbose else JW.GUST_ALERT_S[g])
    w = JW.grade_wind(wind)
    if w >= min_lv: out.append(JW.WIND_ALERT[w] if verbose else JW.WIND_ALERT_S[w])
    ul = 0
    if appMax is not None: ul = max(ul, JW.grade_utci(appMax)[0])
    if appMin is not None: ul = max(ul, JW.grade_utci(appMin)[0])
    if ul >= min_lv:
        if appMax is not None and JW.grade_utci(appMax)[0] >= ul:
            out.append(JW.UTCI_HOT[ul] if verbose else JW.UTCI_HOT_S[ul])
        else:
            out.append(JW.UTCI_COLD[ul] if verbose else JW.UTCI_COLD_S[ul])
    v = JW.grade_vis(visMin) if visMin is not None else 0
    if v >= min_lv: out.append(JW.VIS_ALERT[v] if verbose else JW.VIS_ALERT_S[v])
    return out

def project_alert_tuples(d, is_eng=False):
    """返回项目近 48 小时触发的预警元组 [(kind, level, label_s), ...]（仅 level>=1）。
    label_s 为不含阈值数字的等级名（index 用），与单项目看板 build_dashboard 的
    alert_items 同源、同阈值，保证总览与单页一致。
    物探取 peaksNear 的 48h 峰值（pHourMax/snowMax/gustMax/windMax/appMax/appMin/visMin）；
    工程**必须现算** hourly[:48]（见 peaks_48h_eng），不能用整窗 summary——
    summary 里的极值是 14 天全窗值，会把第 3~14 天的远端大风/高温当成「未来 48 小时」。"""
    if not is_eng:
        p = d.get("peaksNear") or d.get("peaks", {}) or {}
        ph = p.get("pHourMax"); sm = p.get("snowMax"); gm = p.get("gustMax")
        wm = p.get("windMax"); amax = p.get("appMax"); amin = p.get("appMin")
        vmin = p.get("visMin")
    else:
        p = peaks_48h_eng(d)
        ph = p.get("pHourMax"); sm = p.get("snowHourMax"); gm = p.get("gust")
        wm = p.get("wind"); amax = p.get("appMax"); amin = p.get("appMin")
        vmin = p.get("visMin")
    out = []
    r = JW.grade_rain(ph)
    if r: out.append(("rain", r, JW.RAIN_ALERT_S[r]))
    s = JW.grade_snow(sm)
    if s: out.append(("snow", s, JW.SNOW_ALERT_S[s]))
    g = JW.grade_gust(gm)
    if g: out.append(("gust", g, JW.GUST_ALERT_S[g]))
    w = JW.grade_wind(wm)
    if w: out.append(("wind", w, JW.WIND_ALERT_S[w]))
    # 体感温度：炎/冷双向，**必须拆成两个 kind**（2026-10-17）。
    # 原来合用一个 "utci" 并只保留更严重的一侧，导致概述「体感 · 酷热预警」这一行里
    # 混进了体感极寒的项目（藏北藏南都有：白天 10℃、夜里 -33℃），名不副实。
    hot_lv = JW.grade_utci(amax)[0] if amax is not None else 0
    cold_lv = JW.grade_utci(amin)[0] if amin is not None else 0
    if hot_lv:
        out.append(("utci_hot", hot_lv, JW.UTCI_HOT_S[hot_lv]))
    if cold_lv:
        out.append(("utci_cold", cold_lv, JW.UTCI_COLD_S[cold_lv]))
    v = JW.grade_vis(vmin) if vmin is not None else 0
    if v: out.append(("vis", v, JW.VIS_ALERT_S[v]))
    return out

def _distinct_labels(tuples):
    """[(lv,name,lbl)...] → 按等级降序去重后的等级名列表。"""
    seen = {}
    for lv, _, lbl in tuples:
        seen[lbl] = max(seen.get(lbl, 0), lv)
    return [lbl for lbl, _ in sorted(seen.items(), key=lambda kv: -kv[1])]

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

# ---- 概述「按要素分类」用的要素序与名称（2026-10-17 用户要求）----
# 物探概述不再按「谁最严重」写成一句话，而是**逐要素列一行**：
# 每行 = 该要素在所有项目里的最高风险级别 + 触发该要素的项目名，行间按等级从高到低排。
# 顺序固定为 降水→降雪→阵风→均风→体感→能见度（同级时按此序，避免抖动）。
_ELEM_ORDER = {"rain": 0, "snow": 1, "gust": 2, "wind": 3,
               "utci_hot": 4, "utci_cold": 5, "vis": 6}
_ELEM_NAME = {"rain": "降水", "snow": "降雪", "gust": "阵风", "wind": "均风",
              "utci_hot": "体感炎热", "utci_cold": "体感寒冷", "vis": "能见度"}
# 概述行头的配色：3/2 级用与卡片同源的红/橙，1 级压成灰（低等级不是风险，只是客观事实）
_EL_COLOR = {3: "#C0392B", 2: "#E0822C", 1: "#9AA0A6"}
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
    gmax_all = max((g for g in Gd if g is not None), default=0)
    gmax_all_i = Gd.index(gmax_all) if any(g is not None for g in Gd) else 0
    tmin_all = min((t for t in TMd if t is not None), default=99)
    tmin_all_i = TMd.index(tmin_all) if any(t is not None for t in TMd) else 0
    # 48h 窗口内日均降雪合计：用于校验「暴雪预警」是否真在 48h 内（藏北等项目的
    # 暴雪多在 3-14 天远端，peaksNear.snowMax 的逐时尖峰不可靠，须日均佐证才计入 48h 风险）
    snow48 = sum(((x.get("snow") or 0) for x in daily[:wd]))
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
        "snow48": snow48,
        "gust_all": gmax_all,
        "gust_all_i": gmax_all_i,
        "tmin_all": tmin_all,
        "tmin_all_i": tmin_all_i,
    }

def build_near_term_desc(rows, wd=NEAR_DAYS):
    """生成「未来 2 天（48小时）风险」概述：**按「要素 × 级别」分类、等级从高到低**排列。

    2026-10-17 用户要求（替代此前的散文式一段话）：
      · 一行一个「要素 · 等级名」色块 + 该级别对应的全部物探项目，如
        「阵风 · 狂风十级预警 | 藏北高原冻土二维」「阵风 · 大风八级预警 | 通江三维、……」；
      · 行间按级别降序，同级按固定要素序（降水→降雪→阵风→均风→体感炎热→体感寒冷→能见度）；
      · **必须按级别分行**：若只按要素分行（用最高级别当行头、把所有项目都塞进去），
        会把只有「疾风七级」（阵风 lv1）的项目挂在「狂风十级」（lv3）行下，与事实不符。
      · 只列 **2 级及以上**（与卡片口径一致）；1 级（小雨/五级风/偏热）不进概述。
      · 数据与卡片同源（project_alert_tuples 的 48h 七要素等级）。
    3-14 天远端提醒仍只在单项目看板内出现，不纳入本总览。"""
    valid = [r for r in rows if r.get("near") and r["near"]["n"] >= wd]
    if not valid:
        return ""
    ref = next((r for r in valid if r["near"]["dates"]), None)
    dates = ref["near"]["dates"] if ref else []
    start = dates[0][5:] if dates else "?"
    end = dates[wd - 1][5:] if len(dates) >= wd else (dates[-1][5:] if dates else "?")
    head = f'<span class="nt-h">未来 {wd} 天（48小时）风险（{start} ~ {end}）</span>'
    # 逐「要素×级别」聚合：{(kind, lv): {"lbl": 等级名, "projs": [项目名, ...]}}
    # 只收 2 级及以上：概述是「风险」清单，小雨/五级风/偏热这类 1 级事实不占行
    # （1 级只影响操作细节，卡片与项目页里能逐项看到，塞进来会把 12 行冲淡重点）。
    LOW = []
    groups = {}
    for r in valid:
        snow48 = (r.get("near") or {}).get("snow48", 0) or 0
        for kind, lv, lbl in (r.get("alerts") or []):
            if kind not in _ELEM_ORDER:
                continue
            # 降雪须以 48h 日均降雪佐证：否则视为 3-14 天远端尖峰，不列入近端风险
            if kind == "snow" and snow48 <= 0:
                continue
            if lv < 2:
                LOW.append(kind)
                continue
            g = groups.setdefault((kind, lv), {"lbl": lbl, "projs": []})
            g["projs"].append(r["name"])
    if not groups:
        # 无 2 级及以上要素：只表达「天气平稳」，不罗列否定式描述
        tail = ("各项目以小雨、五级风等弱天气为主，无明显强降雨与大风，整体适宜作业"
                if LOW else "各项目天气平稳，无明显强降雨与大风，整体适宜作业")
        return head + f'<div class="elrow"><span class="elp">未来 2 天{tail}</span></div>'
    # 排序：级别降序 →（同级）要素固定序
    ordered = sorted(groups.items(), key=lambda kv: (-kv[0][1], _ELEM_ORDER[kv[0][0]]))
    lines = []
    for (kind, lv), g in ordered:
        names = list(dict.fromkeys(g["projs"]))
        shown = "、".join(names[:8]) + (f" 等 {len(names)} 个" if len(names) > 8 else "")
        col = _EL_COLOR.get(min(lv, 3), "#9AA0A6")
        lines.append(
            '<div class="elrow">'
            f'<span class="elk" style="background:{col}">{_ELEM_NAME[kind]} · {g["lbl"]}</span>'
            f'<span class="elp">{shown}</span></div>'
        )
    return head + "".join(lines)

def peaks_48h_eng(d):
    """工程单点位 _data.json 的「未来 48 小时」七要素峰值（与 weather-engineering-index 的
    gen_points_summary.peaks_48h 及项目页 render_points_html.py 同源同值）：
    **全部取 hourly 前 48 格**，不用 daily[:2]、不用 summary 全窗值。
    summary 里的 maxGust/maxTemp/minTemp/pHourMax/snowHourMax 是整窗 14 天峰值，
    直接用在「未来 48 小时」卡片会把第 3~14 天的远端大风/高温误报进来，故必须现算。

    2026-10-16：新增体感温度(appMax/appMin)与能见度(visMin)；降雪改 mm/h 口径，
    **不再做 ×10 换算**（新数据 snowfall 已是 mm/h）。降雨改读 rainfall(=rain+showers)。
    """
    h = d.get("hourly", {}) or {}
    t = h.get("time", [])
    n = min(48, len(t)) if t else 0
    # 新口径：rainfall = rain + showers；旧数据没有 rainfall 时回退 precipitation
    precip = h.get("rainfall", []) or h.get("precipitation", []) or []
    snow = h.get("snowfall", []) or []
    gusts = h.get("wind_gusts_10m", []) or []
    winds = h.get("wind_speed_10m", []) or []
    temps = h.get("temperature_2m", []) or []
    appr = h.get("apparent_temperature", []) or []
    vis = h.get("visibility", []) or []
    pH = round(max(precip[:n]), 2) if (n and precip) else None
    sH = round(max(snow[:n]), 2) if (n and snow) else None
    vp = [v for v in vis[:n] if v and v > 0]
    if gusts or temps or appr:
        g = round(max(gusts[:n]), 1) if gusts else None
        w = round(max(winds[:n]), 1) if winds else None
        tmax = round(max(temps[:n]), 1) if temps else None
        tmin = round(min(temps[:n]), 1) if temps else None
        appMax = round(max(appr[:n]), 1) if appr else None
        appMin = round(min(appr[:n]), 1) if appr else None
        visMin = round(min(vp), 0) if vp else None
    else:
        # 无 hourly 的极旧数据才退回 daily 前 2 天
        daily = (d.get("daily") or [])[:2]
        g = max((x.get("gustMax", 0) for x in daily), default=0) if daily else None
        w = max((x.get("windMax", 0) for x in daily), default=0) if daily else None
        tmax = max((x.get("tempMax", -99) for x in daily), default=-99) if daily else None
        tmin = min((x.get("tempMin", 99) for x in daily), default=99) if daily else None
        # ⚠️ 体感/能见度缺省必须给 None，不能给 -99/99 哨兵值：
        # 旧数据没有 apparentMax/apparentMin 时，哨兵值会被 grade_utci 判成
        # 「极寒(-99) / 极热(99)」4 级，凭空冒出「极热预警」。没有就是没有。
        _am = [x.get("apparentMax") for x in daily if x.get("apparentMax") is not None]
        _an = [x.get("apparentMin") for x in daily if x.get("apparentMin") is not None]
        appMax = max(_am) if _am else None
        appMin = min(_an) if _an else None
        vv = [x.get("visMin") for x in daily if x.get("visMin")]
        visMin = min(vv) if vv else None
    return {"pHourMax": pH, "snowHourMax": sH, "gust": g, "wind": w,
            "tmax": tmax, "tmin": tmin, "appMax": appMax, "appMin": appMin, "visMin": visMin}


def h48_precip(d):
    """未来 48 小时（起始小时起连续 48 个逐小时）累计降水 mm。

    与单项目看板 build_dashboard.py 的 pSum48 同源同值，保证 index 与项目页数字一致。
    **不能用 daily[:2] 两日之和**：hourly 起点是当日整点，48h 窗口横跨 3 个自然日，
    daily[:2] 会整段漏掉第 3 天。"""
    h = d.get("hourly", {}) or {}
    # 新口径 rainfall = rain + showers；旧数据回退 precipitation
    precip = h.get("rainfall", []) or h.get("precipitation", []) or []
    if precip:
        return round(sum(precip[:48]), 1)
    return round(sum((x.get("precip") or 0) for x in (d.get("daily") or [])[:2]), 1)


def build_focus(d, is_eng=False):
    """卡片概述（单项目一句话）。物探口径（2026-10-17 用户定）：

      · 按**风险级别由高到低**取前 3 个要素，只写 **2 级及以上**的要素（小雨/五级风等低等级不再占位）；
      · 每个要素后点名「达成该等级的最不利作业点」，多作业点项目才有据可查；
      · 降水行顺带给出「最大单点 48h 累计」(>=25mm 才写)，避免另起一条挤掉第 3 个要素。
    等级/标签全部走 project_alert_tuples（与单项目看板 t1 横幅、本页概述行同源同阈值）。
    """
    items = []
    if not is_eng:
        p = d.get("peaksNear") or d.get("peaks", {}) or {}
        wpts = p.get("worstPts") or {}
        def wp(k):
            w = wpts.get(k) or {}
            return w.get("loc") or ""
        # ⚠️ 累计降水 headline 必须用「最大单点 48h 累计」(pSum48Top)，不能用区域包络 pSum48：
        # pSum48 是「各小时取各点最大再累加」，最大可跨点，没有单个作业点真能得到该值，
        # 报包络会严重误导（实测藏北冻土 包络 18.7mm vs 最大单点 5.3mm）。
        _p_top = p.get("pSum48Top")
        if _p_top is None:
            _p_top = p.get("pSum48")
        # 暴雪预警须以「48h 日均降雪合计 > 0」佐证：藏北等项目的暴雪多在 3-14 天远端，
        # peaksNear.snowMax 的逐时尖峰不可靠（与 build_near_term_desc 的 snow48 闸门一致）。
        snow48 = sum(((x.get("snow") or 0) for x in (d.get("daily") or [])[:2]))
        # worstPts 键与要素 kind 对应；走 project_alert_tuples 拿 (kind, lv, lbl)，
        # 不靠「风/雨」子串猜要素（「大风八级预警」「狂风十级预警」在均风/阵风字典里同名，
        # 阵风同级比均风高两级风力，标签重名会张冠李戴，必须走 (kind, lv) 三元组）。
        _WP_OF = {"rain": ("sum48", "hour"), "snow": ("snow", "hour"),
                  "gust": ("gust",), "wind": ("wind",),
                  "utci_hot": ("appMax", "hour"), "utci_cold": ("appMin", "hour"),
                  "vis": ("visMin",)}
        cand = []
        for kind, lv, lbl in project_alert_tuples(d, is_eng=False):
            if lv < 2:                      # 只保留 2 级及以上（用户 2026-10-17）
                continue
            if kind == "snow" and snow48 <= 0:
                continue
            at = ""
            for _k in _WP_OF.get(kind, ()):
                at = wp(_k)
                if at:
                    break
            cand.append((-lv, _ELEM_ORDER.get(kind, 9), lbl, kind, at))
        cand.sort()                                    # 级别降序 →（同级）要素固定序
        for _, _, lbl, kind, at in cand[:3]:           # 前 3 个要素
            txt = lbl + (f"（{at}）" if at else "")
            if kind == "rain" and (_p_top or 0) >= 25:
                txt += f"，48h 累计 {round(_p_top,1)}mm"
            items.append(txt)
    else:
        # 工程数据：统一按 48h 口径现算（hourly[:48]/daily[:2]），不用整窗 summary 的 14 天峰值。
        # 注意：工程 index 由 weather-engineering-index/build_points_index.py 生成，
        # 本分支只为 load_rows 汇总时不报错，不参与本页输出。
        if d.get("hourly") or d.get("daily"):
            pk = peaks_48h_eng(d)
            cum = h48_precip(d)  # 48h 逐小时窗口累加（与项目页同源），不用 daily[:2]
            if cum >= 0.5:  # 显示门槛与项目页一致（>=0.5mm 才写）
                items.append(f"未来 48 小时累计降水 {round(cum,1)}mm")
            items += alert_items(pk.get("pHourMax"), pk.get("snowHourMax"),
                                 pk.get("gust"), pk.get("wind"),
                                 pk.get("appMax"), pk.get("appMin"), pk.get("visMin"),
                                 verbose=False)
        else:
            # 兜底：极旧数据无 hourly/daily，才退回 summary（无风/体感/能见度，传 None）
            s = d.get("summary", {}) or {}
            if s.get("pHourMax") or s.get("snowHourMax") or s.get("maxGust") or s.get("maxTemp") is not None or s.get("minTemp") is not None:
                items += alert_items(s.get("pHourMax"), s.get("snowHourMax"),
                                     s.get("maxGust"), None, None, None, None,
                                     verbose=False)
    if not items:
        # 兜底只表达「天气平稳」，不罗列「无明显降水/无大风」这类否定式描述；
        # 但若有「最需注意」作业点，仍要把该点说出来（它本身就是核心信息）。
        _rp0 = ((d.get("peaksNear") or {}).get("riskPts") or []) if not is_eng else []
        if _rp0:
            return f"{_rp0[0]['label']} 最需注意（{_rp0[0]['why']}）"
        return "未来 2 天天气平稳"
    if not is_eng:
        # 物探：items 已按等级降序截断到 3 条，直接拼即可（不再二次排序/去重）
        return "；".join(items)
    # 工程侧兼容：按 _FOCUS_RANK 取前二（本页不输出工程，仅保持函数可用）
    items.sort(key=lambda t: (0 if "累计降水" in t.split("（")[0]
                              else _FOCUS_RANK.get(t.split("（")[0], 9)))
    return "；".join(items[:2])

def sev_eng_recent(daily2, ph=0.0, cum48=None, el48=None):
    """石油工程数据的风险等级（近 2 天口径）。

    工程 *_data.json 的 meta 里没有 sevNear/sev（物探才有），必须在汇总时现算。
    阈值与 weather-engineering-index 的 sev_of_recent 保持一致，避免两条线的
    卡片评级出现分歧：只取 daily 前 2 天聚合。

    ph = 48h 内最大小时降水（mm/h）。用户规则（2026-10-09）：明显降雨（中雨及以上，
    即 >=1.5mm/h）即至少定为「需关注」；降雪/阵风/高低温仍按各自的等级判定，
    不因这条降雨规则被额外抬级。
    """
    if not daily2:
        return 0
    pmax = max((d.get("precip", 0) for d in daily2), default=0)
    # 风/温取 48h 逐小时窗口极值（el48，见 peaks_48h_eng），不用 daily[:2]、不用全窗 summary
    if el48:
        gust = el48.get("gust") or 0.0
        wind = el48.get("wind") or 0.0
        tmax = el48.get("tmax") if el48.get("tmax") is not None else -99
        tmin = el48.get("tmin") if el48.get("tmin") is not None else 99
    else:
        gust = max((d.get("gustMax", 0) for d in daily2), default=0)
        wind = max((d.get("windMax", 0) for d in daily2), default=0)
        tmax = max((d.get("tempMax", -99) for d in daily2), default=-99)
        tmin = min((d.get("tempMin", 99) for d in daily2), default=99)
    cum = cum48 if cum48 is not None else sum(d.get("precip", 0) for d in daily2)
    # 风的判级一律走 jozzonwx（2026-10-17 起阵风同级比均风高两级风力：
    # 13.9/17.2/24.5/32.7 → lv1..lv4），不在此硬编码 m/s 数值，避免阈值再调时漂移。
    if pmax >= 80 or JW.grade_gust(gust) >= 4 or tmax >= 38 or cum >= 150:
        sev = 3
    elif pmax >= 50 or JW.grade_gust(gust) >= 3 or tmax >= 35 or tmin <= -5 or cum >= 80:
        sev = 2
    elif pmax >= 12 or JW.grade_wind(wind) >= 2 or tmin <= 0 or cum >= 20:
        sev = 1
    else:
        sev = 0
    # 明显降雨（中雨及以上）至少「需关注」
    if JW.grade_rain(ph) >= 2:
        sev = max(sev, 1)
    # 2026-10-16：新增要素（均风 / 体感 UTCI / 能见度 / 降雪）的 48h 等级并入综合风险，
    # 与物探看板、工程 index 共用 jozzonwx 同一套分级，杜绝口径漂移。
    peaks = {"rain": ph or 0.0,
             "snow": (el48 or {}).get("snowHourMax") or 0.0,
             "wind": (el48 or {}).get("wind") or 0.0,
             "gust": (el48 or {}).get("gust") or 0.0,
             "appMax": (el48 or {}).get("appMax"),
             "appMin": (el48 or {}).get("appMin"),
             "visMin": (el48 or {}).get("visMin")}
    sev = max(sev, JW.sev_from_levels(JW.el_levels(peaks)))
    return sev


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
        is_eng = (pattern == "*.json")
        alerts = project_alert_tuples(d, is_eng=is_eng)
        # 风险评级（高度警惕/重点关注/需关注/整体适宜）按「未来 48 小时（近 2 天）」口径，
        # 与看板 t1「重点提示」横幅保持一致；旧数据缺 sevNear 时回退到全周期 sev，避免中断。
        sev = m.get("sevNear", m.get("sev"))
        if sev is None:
            # 旧数据缺 sevNear（2026-10-16 前的产物）：按七要素 48h 峰值现算，
            # 与 build_dashboard 的 _env_sev 同一套 JW 分级，避免沿用旧口径造成漂移。
            if is_eng:
                pk48 = peaks_48h_eng(d)
                sev = sev_eng_recent((d.get("daily") or [])[:2],
                                     (pk48 or {}).get("pHourMax") or 0.0,
                                     cum48=h48_precip(d), el48=pk48)
            else:
                pn = d.get("peaksNear") or d.get("peaks", {}) or {}
                sev = JW.sev_from_levels(JW.el_levels({
                    "rain": pn.get("pHourMax") or 0, "snow": pn.get("snowMax") or 0,
                    "wind": pn.get("windMax") or 0, "gust": pn.get("gustMax") or 0,
                    "appMax": pn.get("appMax"), "appMin": pn.get("appMin"),
                    "visMin": pn.get("visMin"),
                }))
        sev = sev or 0
        # 用户规则（2026-10-09）：有明显降雨（中雨及以上）即至少定为「需关注」；
        # 降雪、阵风、高/低温本身不参与这条抬级，仍按各自风险等级判定。
        rain_lv = max((lv for k, lv, _ in alerts if k == "rain"), default=0)
        max_lv = max((lv for _, lv, _ in alerts), default=0)
        # 兜底一致性：卡片焦点只展示 3 级及以上要素预警，若某项目确实触发了 3 级预警
        # （如十级阵风 24.5m/s、暴雨级降水，旧 _sev_of 只看持续风 windMax 会判不出等级），等级至少给「需关注」，
        # 避免出现「整体适宜」却挂着「狂风十级预警」的自相矛盾。
        # 注意：仅 3 级及以上（暴雨/十级阵风）才抬级——中雨(2 级)本身不足以抬到「需关注」，
        # 否则会出现「需关注」徽章配「未来 2 天天气平稳」描述的矛盾（如南郑 1.5mm/h 中雨）。
        if (rain_lv >= 3 or max_lv >= 3) and sev < 1:
            sev = 1
        rows.append({
            "pin": pin, "short": short, "name": m["name"], "sev": sev,
            "color": SEV_COLOR[sev], "label": SEV_LABEL[sev],
            "focus": build_focus(d, is_eng=is_eng),
            "alerts": alerts,
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
  .near-term .nt-h{{display:block;font-weight:700;color:var(--accent);margin:0 0 7px;}}
  /* 概述按要素分类（2026-10-17）：一行一个要素，行头是「要素 · 等级名」色块，后面跟项目名；
     行序＝该要素最高风险级别降序（同级按固定要素序），所以最严重的永远在第一行。 */
  .elrow{{display:flex;gap:8px;align-items:flex-start;padding:3px 0;}}
  .elrow + .elrow{{border-top:1px dashed rgba(36,42,46,.10);}}
  .elk{{flex:0 0 auto;display:inline-block;font-size:11.5px;font-weight:700;color:#fff;
    border-radius:6px;padding:1.5px 7px;white-space:nowrap;letter-spacing:.2px;}}
  .elp{{flex:1 1 auto;min-width:0;font-size:12.5px;line-height:1.5;color:var(--ink);overflow-wrap:anywhere;}}
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
    # 石油工程侧**不再由本脚本生成**：本脚本的卡片只显示「三级单位+点位名」平铺，
    # 没有按「一级+二级单位」分组折叠（用户 2026-10-09 要求：按单位划分，不要全平铺）。
    # 工程侧 index 由 weather-engineering-index 的 build_points_index.py 生成，
    # 它按 level1+level2 分组折叠。两者写同一个文件，本脚本跑在后面会覆盖掉分组版。
    if args.only == "engineering":
        print("  跳过工程侧：工程 index 请用 weather-engineering-index/build_points_index.py 生成（保留按单位分组）")
    elif args.only is None:
        print("  跳过工程侧 index（如需重建请跑 weather-engineering-index/build_points_index.py，保留按单位分组）")
