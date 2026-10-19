#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_points_index.py —— 石油工程「未来 两周」点位看板 index.html 生成器
=====================================================================
本脚本从 weather-engineering-data 技能中拆出，专门负责「生成 index」这一件事，
不再由渲染单个点位看板的脚本顺带产出。

输入：engineering/data/*.json（由 weather-engineering-data 的 build_points_data.py
      生成，meta.kind=="point"，取数窗口为「下一日 0 时起未来 两周 / 14 天」）
输出：engineering/html/index.html
      * 顶部：未来 两周窗口说明 + 全窗风险等级分布（红/橙/黄/绿计数）
      * 未来 2 天（48 小时）风险概述块：按「要素 × 级别」分行
        （gen_points_summary.overview_elems，只列 2 级及以上，一行一个「要素 · 等级」+
        达成该级别的点位名；级别从高到低，与物探 index 同款）
      * 主体：按「一级 + 二级」分组的可折叠卡片，组内「三级 + 点位」按风险等级降序，
        点击条目跳转到该点位的独立看板 html

风险等级沿用 _sev 阈值（0 绿 整体适宜 / 1 黄 需关注 / 2 橙 重点关注 / 3 红 高度警惕）。
"""
import os, sys, json, glob, argparse, base64

# ---------- 复用 gen_points_summary 的「未来 2 天风险」概述与单点位信息（同目录） ----------
_HERE = os.path.dirname(os.path.abspath(__file__))
try:
    if _HERE not in sys.path:
        sys.path.insert(0, _HERE)
    from gen_points_summary import (point_focus, h48_snow, gongqu,
                                    peaks_48h, overview_elems)
except Exception:
    point_focus = None
    h48_snow = None
    overview_elems = None

    def gongqu(name):
        run = []
        for ch in name:
            if "一" <= ch <= "鿿":
                run.append(ch)
            else:
                break
        return "".join(run) or name


# ---------- 复用 jozzonwx 共享分级（七要素，与单点位看板/物探看板零漂移） ----------
_COMMON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "weather-common", "scripts")
if os.path.isdir(_COMMON):
    sys.path.insert(0, os.path.abspath(_COMMON))
import jozzonwx as JW


# ---------- 页头背景图 ----------
# 工程侧用「钻井井场」实景图（物探侧用高原勘探图），各存于自己看板技能的 assets/ 下。
# 本技能只引用、不另存一份：探测顺序 = 环境变量 BEIDOU_HERO_BG > 本技能 assets/
# > 兄弟技能 weather-engineering-data/assets/。全找不到时静默降级（不注入 CSS，
# 页头回到纯色底），不报错、不中断生成。
_HERO_CANDIDATES = (
    os.environ.get("BEIDOU_HERO_BG") or "",
    os.path.join(_HERE, "..", "assets", "hero-bg.jpg"),
    os.path.join(_HERE, "..", "..", "weather-engineering-data", "assets", "hero-bg.jpg"),
)
HERO_BLEED = "14px"          # 与 body 左右 padding 一致 → 背景正好贴到内容区边缘
# 白纱强度按图分别调：工程用的是钻井井场实景，下半部是深色沙地/钢构，
# 若照搬物探那套（底部只剩 .04）会把「未来 两周…」那行压得发闷，故底部保留 .14。
HERO_FADE = (("0%", ".82"), ("46%", ".50"), ("100%", ".14"),)


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
        ".heroarea {position:relative; isolation:isolate;}\n"
        ".heroarea::before {content:\"\"; position:absolute; z-index:-1;"
        f"top:-8px; bottom:-10px; left:-{bleed}; right:-{bleed};"
        "border-radius:0 0 12px 12px; background-color:#EEF0F2;"
        f'background-image:linear-gradient(180deg,{stops}),url("{uri}");'
        "background-size:100% 100%,cover; background-position:center top,center center;"
        "background-repeat:no-repeat,no-repeat;}\n"
        ".heroarea h1, .heroarea .sub {position:relative; z-index:1; text-shadow:0 1px 0 rgba(255,255,255,.85);}\n"
        ".heroarea .sub {color:#42505A; text-shadow:0 0 7px rgba(255,255,255,.95), 0 1px 0 rgba(255,255,255,.9);}\n"
        ".heroarea .extlink {box-shadow:0 2px 8px rgba(46,125,168,.34);}\n"
    )


SEV_LABEL = {0: "整体适宜", 1: "需关注", 2: "重点关注", 3: "高度警惕"}
SEV_COLOR = {0: "#2E8B57", 1: "#E0A92C", 2: "#E0822C", 3: "#C0392B"}

# ===== 七要素预警标签：统一引用 jozzonwx（JW.RAIN_ALERT / JW.RAIN_ALERT_S / ...）=====
# 文本严格按用户 2026-10-16 口径，已在共享模块集中定义，避免两端漂移。
# 2026-10-17：本文件原先的 alert_items()（把七要素拼成「未来48h累计降水…；降雨·小雨…」长串）
# 已删除——卡片与概述改走 gen_points_summary.point_focus / overview_elems，
# 只报最高等级那一档、要素名自带阈值，不再逐条罗列低等级要素。

# ---------- 风险等级（沿用 _sev 阈值） ----------
def sev_of(daily, s):
    pmax = max((d["rainfall"] for d in daily), default=0)
    gust = s["maxGust"]; tmax = s["maxTemp"]; tmin = s["minTemp"]; wind = s["maxWind"]
    focus = sum(d["rainfall"] for d in daily if d["rainfall"] >= 10)
    # 风阈值统一走 jozzonwx（2026-10-17：阵风 13.9/17.2/24.5/32.7，同级比均风高两级风力）
    if pmax >= 80 or JW.grade_gust(gust) >= 4 or tmax >= 38 or focus >= 150: return 3
    if pmax >= 50 or JW.grade_gust(gust) >= 3 or tmax >= 35 or tmin <= -5 or focus >= 80: return 2
    if pmax >= 12 or JW.grade_wind(wind) >= 2 or tmin <= 0 or focus >= 30: return 1
    return 0


def h48_precip(d):
    """未来 48 小时（起始小时起连续 48 个逐小时）累计降水 mm。

    与单点位看板 weather-engineering-data/render_points_html.py 的 h48_precip() 完全同源同值，
    保证 index 与项目页「累计降水」数字一致。
    **不能用 daily[:2] 两个自然日之和**：hourly 起点是当日整点（如 18 时起），48h 窗口会横跨
    3 个自然日（10-09/10-10/10-11），daily[:2] 会整段漏掉第 3 天（实测马401 井漏掉 20.2mm，
    4.8 vs 24.4）。故一律取 hourly 前 48 格累加。
    无 hourly 的极旧数据才退回 daily[:2]。"""
    h = d.get("hourly", {}) or {}
    rain = h.get("rainfall", []) or []
    if rain:
        return round(sum(rain[:48]), 1)
    return round(sum((x.get("rainfall") or 0) for x in (d.get("daily") or [])[:2]), 1)


def sev_of_recent(daily3, ph=0.0, cum48=None, el48=None):
    """未来 2 天（48 小时）风险等级，套用与 sev_of 相同阈值。
    ph = 48h 内最大小时降水（mm/h），短时强降水须计入，否则日累计小的井位会被低估。
    cum48 = 未来 48 小时逐小时窗口累计降水（见 h48_precip），与展示数字同源；
    el48 = 未来 48 小时窗口的阵风/持续风/最高温/最低温（见 peaks_48h），
    **不用 daily[:2]、也不用 summary 全窗 14 天极值**（否则会把第 3~14 天的远端
    大风/高温/寒潮当成「未来两天」的风险）。
    单日降水峰值 pmax 仍取 daily 前 2 天（逐日峰值不会漏，与「单日 XXmm」表述一致）。
    cum48/el48 传 None 时退回 daily[:2]（仅兼容无 hourly 的极旧数据）。
    远端（第 3 天起）预报不确定性大、准确性下降，不作为当前主风险提示。"""
    pmax = max((d["rainfall"] for d in daily3), default=0)
    if el48:
        gust = el48.get("gust") or 0.0
        wind = el48.get("wind") or 0.0
        tmax = el48.get("tmax") if el48.get("tmax") is not None else 99
        tmin = el48.get("tmin") if el48.get("tmin") is not None else 99
    else:
        gust = max((d["gustMax"] for d in daily3), default=0)
        wind = max((d["windMax"] for d in daily3), default=0)
        tmax = max((d["tempMax"] for d in daily3), default=99)
        tmin = min((d["tempMin"] for d in daily3), default=99)
    cum = cum48 if cum48 is not None else sum(d["rainfall"] for d in daily3)
    if pmax >= 80 or JW.grade_gust(gust) >= 4 or tmax >= 38 or cum >= 150: sev = 3
    elif ph >= 10 or pmax >= 50 or JW.grade_gust(gust) >= 3 or tmax >= 35 or tmin <= -5 or cum >= 80: sev = 2
    elif ph >= 5 or pmax >= 12 or JW.grade_wind(wind) >= 2 or tmin <= 0 or cum >= 20: sev = 1
    else: sev = 0
    # 用户规则（2026-10-09）：有明显降雨（中雨及以上，>=1.5mm/h）即至少定为「需关注」；
    # 降雪、阵风、高/低温仍按各自等级判定，不因这条降雨规则被额外抬级。
    if ph >= 1.5:
        sev = max(sev, 1)
    # 新增要素（均风 / 体感温度 UTCI / 能见度 / 降雪）48h 等级并入综合风险，
    # 与单点位看板、物探看板共用 jozzonwx 同一套分级，杜绝口径漂移。
    peaks = {"rain": ph,
             "snow": el48.get("snowHourMax") if el48 else 0.0,
             "wind": wind or 0.0, "gust": gust or 0.0,
             "appMax": el48.get("appMax") if el48 else None,
             "appMin": el48.get("appMin") if el48 else None,
             "visMin": el48.get("visMin") if el48 else None}
    sev = max(sev, JW.sev_from_levels(JW.el_levels(peaks)))
    return sev


CSS = """
* {box-sizing: border-box; margin:0; padding:0;}
body {font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
  background:#f4f6f8; color:#1f2933; line-height:1.55; padding:14px; max-width:720px; margin:0 auto;}
body.sev0 {--sev:#2E8B57;} body.sev1 {--sev:#E0A92C;} body.sev2 {--sev:#E0822C;} body.sev3 {--sev:#C0392B;}
.topbar {display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; font-size:12px; color:#5b6b7b;}
.topbar a {color:#2E7DA8; text-decoration:none; font-weight:700;}
h1 {font-size:19px; margin:2px 0 2px;}
.sub {font-size:12px; color:#7b8a99; margin-bottom:10px;}
.alert {background:var(--sev); color:#fff; border-radius:14px; padding:13px 15px; margin-bottom:12px; box-shadow:0 2px 8px rgba(0,0,0,.08);}
.alert .t {font-size:16px; font-weight:800; display:flex; align-items:center; gap:8px;}
.alert .d {font-size:13px; margin-top:6px; opacity:.97; line-height:1.55;}
.dot {width:11px; height:11px; border-radius:50%; background:#fff; box-shadow:0 0 0 3px rgba(255,255,255,.35);}
.grid {display:grid; grid-template-columns:repeat(4,1fr); gap:8px; margin-bottom:14px;}
.kpi {background:#fff; border-radius:12px; padding:10px 8px; text-align:center; box-shadow:0 1px 4px rgba(0,0,0,.06);}
.kpi .v {font-size:19px; font-weight:800; color:#1f2933;}
.kpi .l {font-size:11px; color:#7b8a99; margin-top:2px;}
.card {background:#fff; border-radius:12px; padding:12px 13px; margin-bottom:12px; box-shadow:0 1px 4px rgba(0,0,0,.06);}
.card h2 {font-size:14px; margin-bottom:8px; display:flex; align-items:center; gap:7px;}
.chart-h {font-size:12px; font-weight:700; color:#46556a; margin:10px 0 2px;}
.legend {font-size:11px; color:#7b8a99; margin:2px 0 6px;}
.legend i {display:inline-block; width:10px; height:3px; vertical-align:middle; margin:0 3px 0 8px;}
.rc {border-left:4px solid #ccc; border-radius:8px; padding:8px 10px; margin-bottom:8px; background:#fafbfc;}
.rc.danger {border-color:#C0392B; background:#fdf3f1;} .rc.warn {border-color:#E0822C; background:#fef6ee;} .rc.ok {border-color:#2E8B57; background:#f1f8f4;}
.rc .rt {font-weight:800; font-size:13px;} .rc .rb {font-size:12px; color:#55636f; margin-top:2px;}
.rc .tag {float:right; font-size:11px; font-weight:700; padding:1px 7px; border-radius:8px; color:#fff;}
.danger .tag{background:#C0392B;} .warn .tag{background:#E0822C;} .ok .tag{background:#2E8B57;}
ul.adv {margin:4px 0 0 2px; padding-left:0; list-style:none;}
ul.adv li {font-size:13px; color:#33414f; padding:5px 0; border-bottom:1px dashed #eef1f4;}
ul.adv li:last-child{border-bottom:none;}
.hval {background:#fff; border:1px solid #eef1f4; border-radius:10px; padding:9px 11px; font-size:13px; color:#33414f; box-shadow:0 1px 4px rgba(0,0,0,.06); margin-top:8px; line-height:1.7;}
.hval b {color:#1f2933;} .hval .t {font-weight:800; color:#2E7DA8; margin-right:4px;}
#hslider {width:100%; margin-top:8px; accent-color:#2E7DA8;}
.foot {font-size:11px; color:#9aa7b4; margin-top:8px; text-align:center;}
.tabs {display:flex; gap:6px; margin-bottom:12px; position:sticky; top:0; z-index:5; padding:6px 0; background:#f4f6f8;}
.tab {flex:1; padding:9px 0; border:none; border-radius:10px; background:#fff; color:#46556a; font-size:13px; font-weight:700; cursor:pointer; box-shadow:0 1px 4px rgba(0,0,0,.06); transition:.15s;}
.tab:hover {color:#2E7DA8;}
.tab.active {background:var(--sev); color:#fff;}
.panel {display:block;}
"""


# ---------- 「未来 2 天（48 小时）风险」概述块（按「要素 × 级别」分行） ----------
def near_term_html(rows, w0="", w1=""):
    """一行一个「要素 · 等级」+ 达成该级别的点位名（与物探 index 同款，2026-10-17 用户口径）。
    rows 由 gen_points_summary.overview_elems() 产出（已按级别降序、只含 2 级及以上）。
    无 2 级及以上要素时给一句「天气平稳」，不罗列「无明显降水/无大风」这类否定式描述。"""
    win = f"（{w0} ~ {w1}）" if w0 and w1 else ""
    head = f'<div class="nt-h">未来 2 天（48 小时）风险{win}</div>'
    if not rows:
        return ('<div class="near">' + head +
                '<div class="elrow"><span class="elp">各点位天气平稳，无明显强降雨与大风，'
                '整体适宜作业</span></div></div>')
    body = []
    for r in rows:
        col = "#C0392B" if r["lv"] >= 3 else "#E0822C"
        shown = "、".join(
            f'<a class="elink" href="{f}?from=index">{n}</a>' for n, f in r["names"]
        )
        if r["more"]:
            shown += f" 等 {len(r['names']) + r['more']} 口井"
        body.append('<div class="elrow">'
                    f'<span class="elk" style="background:{col}">{r["name"]} · {r["head"]}</span>'
                    f'<span class="elp">{shown}</span></div>')
    return '<div class="near">' + head + "".join(body) + '</div>'


# ---------- 总览 index（按 level1+level2 分组，组内按风险等级降序） ----------
def render_index(groups, counts, start_label, end_label=None, near_html=None, ndays=0):
    parts = []
    parts.append("""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>中石化北斗运营中心 · 石油工程天气看板</title><style>""" + CSS + """
.grp {background:#fff; border-radius:12px; padding:0 13px; margin-bottom:12px; box-shadow:0 1px 4px rgba(0,0,0,.06); overflow:hidden;}
.grp h2 {font-size:15px; padding:12px 0; cursor:pointer; display:flex; align-items:center; gap:8px; flex-wrap:wrap; row-gap:3px; user-select:none; transition:background .15s;}
.grp h2:hover {background:#f5f7f9;}
.grp h2 .gname {flex:1 1 auto; min-width:0;}
/* 2026-10-17 用户口径：单位名在左，右侧按「高度警惕/重点关注/需关注/整体适宜」分等级给出数量 */
.grp h2 .gmeta {margin-left:auto; display:inline-flex; align-items:center; gap:9px; font-size:11px; font-weight:800; color:#7b8a99; white-space:nowrap;}
.grp h2 .gmeta .gc {display:inline-flex; align-items:center; gap:4px;}
.grp h2 .gmeta .dot {width:8px; height:8px; box-shadow:none;}
.grp h2 .arr {font-size:12px; font-weight:400; color:#8a98a6; transition:transform .2s; margin-left:2px;}
.grp.open h2 .arr {transform:rotate(90deg);}
.grp-body {display:none; padding-bottom:10px;}
.grp.open .grp-body {display:block;}
.item {display:flex; align-items:center; gap:10px; padding:9px 11px; border-radius:9px; text-decoration:none; color:#1f2933; background:#fafbfc; margin-bottom:7px; border:1px solid #eef1f4;}
.item:hover {background:#f3f7fb;}
.item .nm {font-weight:700; font-size:14px;}
.item .lv {font-size:11px; color:#8a98a6; min-width:60px;}
.item .badge {margin-left:auto; font-size:11px; font-weight:700; color:#fff; padding:3px 10px; border-radius:9px;}
.extlink {display:inline-flex; align-items:center; gap:4px; font-size:13px; font-weight:700; color:#fff; background:#2E7DA8; padding:7px 14px; border-radius:20px; text-decoration:none; box-shadow:0 2px 6px rgba(46,125,168,.3);}
.extlink:hover {background:#245f82; transform:translateY(-1px);}
/* 「未来 2 天（48 小时）风险」概述：按「要素 × 级别」分行（2026-10-17 用户口径，与物探 index 同款）。
   行头 = 要素 · 等级 色块（3 级及以上红 / 2 级橙），后面跟达成该级别的点位名；
   行序 = 级别降序 → 同级按 降水→降雪→阵风→均风→体感→能见度。 */
.near {background:#fff; border-radius:12px; padding:11px 13px; margin-bottom:12px;
  box-shadow:0 1px 4px rgba(0,0,0,.06); border-left:4px solid #2E7DA8;}
.near .nt-h {font-size:12.5px; font-weight:800; color:#2E7DA8; margin-bottom:7px; letter-spacing:.2px;}
.near .elrow {display:flex; gap:8px; align-items:flex-start; padding:3.5px 0;}
.near .elrow + .elrow {border-top:1px dashed #eef1f4;}
.near .elk {flex:0 0 auto; display:inline-block; font-size:11px; font-weight:700; color:#fff;
  border-radius:6px; padding:1.5px 7px; white-space:nowrap; letter-spacing:.2px;}
.near .elp {flex:1 1 auto; min-width:0; font-size:12.5px; line-height:1.5; color:#33414f; overflow-wrap:anywhere;}
.near .elp a.elink {color:#2E7DA8; text-decoration:none; font-weight:600;}
.near .elp a.elink:hover {text-decoration:underline;}
""" + hero_css() + """</style></head><body>""")
    parts.append('<div class="heroarea">')
    parts.append('<div style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:6px">'
                 '<h1 style="margin:0">中石化北斗运营中心 · 石油工程天气看板</h1>'
                 '<a class="extlink" href="https://leidian.wang" target="_blank" rel="noopener">北斗天气风险治理平台 ↗</a>'
                 '</div>')
    # 跨度标签按实际 daily 长度动态显示：避免 7 天旧数据被错标成“未来 两周”
    dates = f"{start_label} ~ {end_label}" if end_label else start_label
    if ndays >= 13:
        span = f"未来 两周（14 天）· {dates}"
    elif ndays > 0:
        span = f"未来 {ndays} 天（{dates}）"
    else:
        span = f"未来 两周（{dates}）"
    span += " · 组内按风险等级降序"
    parts.append(f'<div class="sub">{span}</div>')
    parts.append('</div>')          # 结束 .heroarea（页头背景区：标题 + 窗口说明）
    # 等级分布：每档用 nowrap 的独立 span + flex 间距，避免「整体适宜」与数字被折到两行
    summ = "".join(
        f'<span style="white-space:nowrap"><span style="color:{SEV_COLOR[i]}">●</span> '
        f'{SEV_LABEL[i]} {counts[i]}</span>'
        for i in (3, 2, 1, 0))
    parts.append(f'<div class="card" style="font-size:13px;display:flex;flex-wrap:wrap;gap:6px 14px">{summ}</div>')
    if near_html:
        parts.append(near_html)
    for idx_g, ((l1, l2), _gsev, items) in enumerate(groups):
        # 组标题 = 单位名（一级 · 二级）+ 右侧「各等级点位数」（高度警惕 → 整体适宜，只列非 0 的档）
        cnts = {0: 0, 1: 0, 2: 0, 3: 0}
        for r in items:
            cnts[r["sev2"]] = cnts.get(r["sev2"], 0) + 1
        chips = "".join(
            f'<span class="gc"><span class="dot" style="background:{SEV_COLOR[lv]}"></span>{cnts[lv]}</span>'
            for lv in (3, 2, 1, 0) if cnts[lv])
        parts.append('<div class="grp">')
        parts.append(
            f'<h2 onclick="this.parentElement.classList.toggle(\'open\')">'
            f'<span class="gname">{l1} · {l2}</span>'
            f'<span class="gmeta">{chips}<span class="arr">▸</span></span></h2>')
        parts.append('<div class="grp-body">')
        for r in items:
            parts.append(
                f'<a class="item" href="{r["file"]}?from=index">'
                f'<span class="lv">{r["level3"]}</span>'
                f'<span class="nm">{r["name"]}</span>'
                f'<span class="badge" style="background:{SEV_COLOR[r["sev2"]]}">{SEV_LABEL[r["sev2"]]}</span></a>'
                f'<div style="font-size:11px;color:#7b8a99;padding:0 11px 9px;margin-top:-4px">{r["focus"]}</div>')
        parts.append('</div></div>')
    parts.append('<div class="foot">数据来源 九章雷电网（jozzon-mcp）· 山区小气候可能强于模式预报</div>')
    parts.append('<script async src="//busuanzi.ibruce.info/busuanzi/2.3/busuanzi.pure.mini.js"></script>')
    parts.append('<div style="margin-top:16px;padding-top:8px;border-top:1px solid rgba(128,128,128,.18);font-size:11px;color:#9aa0a6;text-align:center;opacity:.6;letter-spacing:.3px">访问统计 · 本页阅读 <span id="busuanzi_container_page_pv"><span id="busuanzi_value_page_pv"></span> 次</span> · 全站访客 <span id="busuanzi_container_site_uv"><span id="busuanzi_value_site_uv"></span> 人</span></div>')
    parts.append('</body></html>')
    return "".join(parts)


def main():
    ap = argparse.ArgumentParser(
        description="由逐点天气 JSON 生成石油工程「未来 两周」看板 index.html")
    ap.add_argument("--datadir", default="engineering/data",
                    help="逐点 JSON 数据目录（meta.kind=='point'）")
    ap.add_argument("--htmldir", default="engineering/html", help="index.html 输出目录")
    ap.add_argument("--outdir", default="", help="（可选）index.html 单独输出目录，默认=htmldir")
    ap.add_argument("--no-short", action="store_true", help="不生成「未来 2 天（48 小时）风险」概述块")
    args = ap.parse_args()

    datadir = os.path.abspath(args.datadir)
    outdir = os.path.abspath(args.outdir) if args.outdir else os.path.abspath(args.htmldir)
    if not os.path.isdir(datadir):
        print(f"ERROR: 数据目录不存在: {datadir}")
        sys.exit(1)
    os.makedirs(outdir, exist_ok=True)

    files = sorted(glob.glob(os.path.join(datadir, "*.json")))
    recs = []
    ndays = 0  # 实际预报跨度（按 daily 长度），用于动态显示「未来 两周 / 未来 N 天」
    summary_pts = []  # 供 build_short 生成「未来 2 天风险」短描述
    win48 = None      # 48h 窗口起止日（MM-DD），概述标题用；取首份数据的 hourly 前 48 格
    for fp in files:
        d = json.load(open(fp, encoding="utf-8"))
        m = d.get("meta", {})
        # 仅统计 Markdown 点位表产出的逐点数据（排除井位看板 *_data.json）
        if m.get("kind") != "point":
            continue
        daily, s = d["daily"], d["summary"]
        ndays = max(ndays, len(daily))
        # 48h 窗口起止日（MM-DD）：hourly 起点是当日整点，48 格会横跨 3 个自然日
        if win48 is None:
            _ht = (d.get("hourly") or {}).get("time") or []
            if _ht:
                win48 = (_ht[0][5:10], _ht[min(47, len(_ht) - 1)][5:10])
            elif daily:
                win48 = (daily[0].get("date", "")[5:],
                         daily[min(1, len(daily) - 1)].get("date", "")[5:])
        slug = os.path.splitext(os.path.basename(fp))[0]
        sev = sev_of(daily, s)
        daily2 = daily[:2]
        # 48h 峰值：五要素一律取 hourly[:48]（风/温不用 daily[:2]、不用全窗 summary）
        pk48 = peaks_48h(d)
        # 48h 累计降水：取 hourly 前 48 格累加（与单点位看板 h48_precip 同源同值），
        # 不能用 daily[:2] 两日之和——48h 窗口横跨 3 个自然日，会整段漏掉第 3 天。
        cum48 = h48_precip(d)
        # 48h 评级与 build_short/卡片焦点保持同一口径：纳入小时级短时降水 + 48h 窗口风温
        sev2 = sev_of_recent(daily2, pk48.get("pHourMax") or 0.0, cum48=cum48, el48=pk48)
        # 各要素等级：仅用于下方「等级抬级」兜底（中雨及以上或任一 3 级才抬级）
        a_r = JW.grade_rain(pk48.get("pHourMax") or 0)
        a_g = JW.grade_gust(pk48.get("gust") or 0)
        a_s = JW.grade_snow(pk48.get("snowHourMax") or 0)
        a_w = JW.grade_wind(pk48.get("wind") or 0)
        a_u = 0
        if pk48.get("appMax") is not None: a_u = max(a_u, JW.grade_utci(pk48["appMax"])[0])
        if pk48.get("appMin") is not None: a_u = max(a_u, JW.grade_utci(pk48["appMin"])[0])
        a_v = JW.grade_vis(pk48.get("visMin")) if pk48.get("visMin") is not None else 0
        a_max = max(a_r, a_s, a_g, a_w, a_u, a_v)
        # 卡片信息（2026-10-17 用户口径）：只报最高等级那一档的要素（有 4 级就不提 3 级），
        # 同级最多 2 个、要素名自带阈值；48h 累计降水 >20mm / 累计降雪 >10mm 才提，
        # 低量级流水账（0.8mm 小雨等）一律不再罗列。
        snow48 = h48_snow(d) if h48_snow else 0.0
        focus = (point_focus({**pk48, "cum": cum48, "snow48": snow48})
                 if point_focus else "")
        # 一致性兜底：明显降雨（中雨及以上）或任一 3 级预警 → 等级至少「需关注」，
        # 避免出现「整体适宜」却挂着「狂风十级预警」的自相矛盾
        if (a_r >= 2 or a_max >= 3) and sev2 < 1:
            sev2 = 1
        recs.append({"name": m["name"], "level1": m["level1"], "level2": m["level2"],
                     "level3": m["level3"], "slug": slug, "file": slug + ".html",
                     "sev": sev, "sev2": sev2, "focus": focus,
                     "start": m.get("start_date", ""), "end": m.get("end_date", "")})
        cum2 = cum48  # 48h 累计（hourly[:48] 累加），与卡片焦点文案、评级、汇总表完全同源
        pk2 = max(daily2, key=lambda x: x.get("rainfall", 0)) if daily2 else {"rainfall": 0, "date": ""}
        summary_pts.append({
            "name": m["name"], "gq": gongqu(m["name"]), "file": slug + ".html",
            "cum": round(cum2, 1), "pkp": round(pk2.get("rainfall", 0), 1), "pkdate": pk2.get("date"),
            "snow48": round(snow48, 1),
            # 风/温也统一取 48h 逐小时窗口极值（与卡片焦点、评级、项目页同源）
            "gust": pk48.get("gust"),
            "tmax": pk48.get("tmax"),
            "tmin": pk48.get("tmin"),
            "wind": pk48.get("wind"),
            # 体感温度(UTCI)与能见度 48h 峰值：供 build_short 套用舒适度/能见度预警（非整窗 summary）
            "appMax": pk48.get("appMax"), "appMin": pk48.get("appMin"), "visMin": pk48.get("visMin"),
            # 48h 峰值（七要素均 hourly[:48]），供 build_short 套用七要素预警阈值（非整窗 summary）
            "pHourMax": pk48.get("pHourMax"), "snowHourMax": pk48.get("snowHourMax"),
            "maxGust": pk48.get("gust"), "maxTemp": pk48.get("tmax"), "minTemp": pk48.get("tmin"),
            "sev": sev2, "start": m.get("start_date", ""),
        })

    if not recs:
        print("ERROR: 未找到任何 meta.kind=='point' 的逐点数据文件。")
        sys.exit(1)

    # 分组：一级+二级，组内按 sev 降序、再按 name
    groups = {}
    for r in recs:
        groups.setdefault((r["level1"], r["level2"]), []).append(r)
    glist = []
    for key, items in groups.items():
        items.sort(key=lambda x: (-x["sev2"], x["name"]))
        gsev = max(x["sev2"] for x in items)
        glist.append((key, gsev, items))
    glist.sort(key=lambda g: (-g[1], g[0][0], g[0][1]))

    counts = {0: 0, 1: 0, 2: 0, 3: 0}
    for r in recs:
        counts[r["sev2"]] += 1

    # 「未来 2 天（48 小时）风险」概述：按「要素 × 级别」分行，只列 2 级及以上
    # （2026-10-17 用户口径，与物探 index 同款；原散文式 build_overview 仍保留给 md 汇总用）
    near_html = None
    if not args.no_short:
        rows = overview_elems(summary_pts) if overview_elems else []
        near_html = near_term_html(rows, *(win48 or ("", "")))

    start_label = recs[0]["start"]
    end_label = recs[0].get("end", "")
    idx = render_index(glist, counts, start_label, end_label, near_html, ndays)
    out = os.path.join(outdir, "index.html")
    open(out, "w", encoding="utf-8").write(idx)
    print(f"  ✓ index.html（{len(recs)} 个点位，{len(glist)} 个分组）→ {out}")
    print(f"DONE → {outdir}")


if __name__ == "__main__":
    main()
