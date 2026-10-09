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
      * 未来 2 天（48 小时）风险短描述块（由 gen_points_summary.build_short 生成，约 50 字）
      * 主体：按「一级 + 二级」分组的可折叠卡片，组内「三级 + 点位」按风险等级降序，
        点击条目跳转到该点位的独立看板 html

风险等级沿用 _sev 阈值（0 绿 整体适宜 / 1 黄 需关注 / 2 橙 重点关注 / 3 红 高度警惕）。
"""
import os, sys, json, glob, argparse, base64

# ---------- 复用 gen_points_summary 的「未来 2 天风险」短描述（同目录） ----------
_HERE = os.path.dirname(os.path.abspath(__file__))
try:
    if _HERE not in sys.path:
        sys.path.insert(0, _HERE)
    from gen_points_summary import build_short, gongqu, peaks_48h
except Exception:
    build_short = None

    def gongqu(name):
        run = []
        for ch in name:
            if "一" <= ch <= "鿿":
                run.append(ch)
            else:
                break
        return "".join(run) or name


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

# ===== 五要素预警阈值（2026-10-09 用户定；降水/降雪=mm/h 小时级，阵风 m/s，温度 ℃）=====
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

def alert_items(rain_mmh, snow_mmh, gust, tmax, tmin, verbose=True, min_lv=1):
    """各要素独立判定，可同时多条。verbose=False 只给等级名、不带阈值数字。
    min_lv：只保留等级 >= min_lv 的要素，默认 1 = 低等级要素（小雨、五级风等）照常写出，
    因为它们是客观事实；用户澄清（2026-10-09）这些低等级**不写反而丢失信息**，
    只是它们**不足以抬高风险等级**——抬级只看「中雨及以上」或「任一 3 级预警」。"""
    out = []
    r = rain_alert(rain_mmh)
    if r >= min_lv: out.append(RAIN_ALERT[r] if verbose else RAIN_ALERT_S[r])
    s = snow_alert(snow_mmh)
    if s >= min_lv: out.append(SNOW_ALERT[s] if verbose else SNOW_ALERT_S[s])
    g = gust_alert(gust)
    if g >= min_lv: out.append(GUST_ALERT[g] if verbose else GUST_ALERT_S[g])
    h = thigh_alert(tmax)
    if h >= min_lv: out.append(THIGH_ALERT[h] if verbose else THIGH_ALERT_S[h])
    l = tlow_alert(tmin)
    if l >= min_lv: out.append(TLOW_ALERT[l] if verbose else TLOW_ALERT_S[l])
    return out

# ---------- 风险等级（沿用 _sev 阈值） ----------
def sev_of(daily, s):
    pmax = max((d["precip"] for d in daily), default=0)
    gust = s["maxGust"]; tmax = s["maxTemp"]; tmin = s["minTemp"]; wind = s["maxWind"]
    focus = sum(d["precip"] for d in daily if d["precip"] >= 10)
    if pmax >= 80 or gust >= 20.8 or tmax >= 38 or focus >= 150: return 3
    if pmax >= 50 or gust >= 17.2 or tmax >= 35 or tmin <= -5 or focus >= 80: return 2
    if pmax >= 12 or wind >= 10.8 or tmin <= 0 or focus >= 30: return 1
    return 0


def sev_of_recent(pk):
    """未来 2 天（48 小时）风险等级：全部要素取自 peaks_48h()（hourly[:48] 逐小时窗口）。
    ⚠️ 不再读 daily[:2] 的两个自然日聚合——48h 窗口从当前整时起算横跨 3 个自然日，
    daily 口径会漏掉第 3 天上午那段降水/阵风/高温。
    用户规则（2026-10-09）：中雨及以上（≥1.5mm/h）即至少「需关注」。"""
    pk = pk or {}
    ph   = pk.get("pHourMax") or 0.0
    cum  = pk.get("pSum48") or 0.0
    gust = pk.get("gust") or 0.0
    wind = pk.get("wind") or 0.0
    tmax = pk.get("tmax")
    tmin = pk.get("tmin")
    if gust >= 20.8 or (tmax is not None and tmax >= 38) or cum >= 150: sev = 3
    elif (ph >= 10 or gust >= 17.2 or (tmax is not None and tmax >= 35)
          or (tmin is not None and tmin <= -5) or cum >= 80): sev = 2
    elif ph >= 5 or wind >= 10.8 or gust >= 13.9 or (tmin is not None and tmin <= 0) or cum >= 20: sev = 1
    else: sev = 0
    if ph >= 1.5:
        sev = max(sev, 1)
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


# ---------- 总览 index（按 level1+level2 分组，组内按风险等级降序） ----------
def render_index(groups, counts, start_label, end_label=None, short2=None, ndays=0):
    parts = []
    parts.append("""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>中石化北斗运营中心 · 石油工程天气看板</title><style>""" + CSS + """
.grp {background:#fff; border-radius:12px; padding:0 13px; margin-bottom:12px; box-shadow:0 1px 4px rgba(0,0,0,.06); overflow:hidden;}
.grp h2 {font-size:15px; padding:12px 0; cursor:pointer; display:flex; align-items:center; gap:8px; user-select:none; transition:background .15s;}
.grp h2:hover {background:#f5f7f9;}
.grp h2 .arr {margin-left:auto; font-size:12px; color:#8a98a6; transition:transform .2s;}
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
    summ = " · ".join(f'<span style="color:{SEV_COLOR[i]}">●</span> {SEV_LABEL[i]} {counts[i]}'
                      for i in (3, 2, 1, 0))
    parts.append(f'<div class="card" style="font-size:13px">{summ}</div>')
    if short2:
        parts.append(
            f'<div class="card" style="font-size:13px;background:#fff8f0;border-left:4px solid #E0822C">'
            f'<b>未来 2 天风险</b>：{short2}</div>')
    for idx_g, ((l1, l2), gsev, items) in enumerate(groups):
        parts.append('<div class="grp">')
        parts.append(f'<h2 onclick="this.parentElement.classList.toggle(\'open\')"><span class="dot" style="background:{SEV_COLOR[gsev]}"></span>{l1} · {l2}<span class="arr">▸</span></h2>')
        parts.append('<div class="grp-body">')
        for r in items:
            parts.append(
                f'<a class="item" href="{r["file"]}?from=index">'
                f'<span class="lv">{r["level3"]}</span>'
                f'<span class="nm">{r["name"]}</span>'
                f'<span class="badge" style="background:{SEV_COLOR[r["sev2"]]}">{SEV_LABEL[r["sev2"]]}</span></a>'
                f'<div style="font-size:11px;color:#7b8a99;padding:0 11px 9px;margin-top:-4px">{r["focus"]}</div>')
        parts.append('</div></div>')
    parts.append('<div class="foot">数据来源 Open-Meteo · 山区小气候可能强于模式预报</div>')
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
    ap.add_argument("--no-short", action="store_true", help="不生成「未来 2 天风险」短描述块")
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
    for fp in files:
        d = json.load(open(fp, encoding="utf-8"))
        m = d.get("meta", {})
        # 仅统计 Markdown 点位表产出的逐点数据（排除井位看板 *_data.json）
        if m.get("kind") != "point":
            continue
        daily, s = d["daily"], d["summary"]
        ndays = max(ndays, len(daily))
        slug = os.path.splitext(os.path.basename(fp))[0]
        sev = sev_of(daily, s)
        daily2 = daily[:2]
        # 48h 峰值：从 hourly[:48] / daily[:2] 现算，绝不用整窗 summary（maxGust 等是 14 天峰值）
        pk48 = peaks_48h(d)
        # 48h 评级与 build_short/卡片焦点保持同一口径：纳入小时级短时降水
        sev2 = sev_of_recent(pk48)
        # 五要素预警焦点文字（仅 48h 峰值 → 用户 2026-10-09 阈值）
        # 各要素等级：用于下方「等级抬级」判定（小雨/五级风不抬级，中雨或任一3级才抬）
        a_r = rain_alert(pk48.get("pHourMax"))
        a_g = gust_alert(pk48.get("gust"))
        a_max = max(a_r, snow_alert(pk48.get("snowHourMax")), a_g,
                    thigh_alert(pk48.get("tmax")), tlow_alert(pk48.get("tmin")))
        # 卡片照常写全各要素的客观事实——小雨、五级风等低等级要素也要写出来；
        # 只是它们不足以抬高风险等级（等级抬级只看 中雨及以上 或任一 3 级预警）。
        # 故此处 min_lv 保持默认 1，不做等级过滤。
        cum48 = pk48.get("pSum48") or 0.0
        _bits = []
        # 用户规则（2026-10-09）：48h 累计 < 2mm 不提——量级太小，不算什么事
        if cum48 >= 2:
            _bits.append(f"未来 48 小时累计降水 {round(cum48,1)}mm")
        _bits += alert_items(pk48.get("pHourMax"), pk48.get("snowHourMax"),
                             pk48.get("gust"), pk48.get("tmax"), pk48.get("tmin"),
                             verbose=False)
        focus = "；".join(_bits) or "未来 2 天天气平稳"
        # 一致性兜底：明显降雨（中雨及以上）或任一 3 级预警 → 等级至少「需关注」，
        # 避免出现「整体适宜」却挂着「疾风七级预警」的自相矛盾
        if (a_r >= 2 or a_max >= 3) and sev2 < 1:
            sev2 = 1
        recs.append({"name": m["name"], "level1": m["level1"], "level2": m["level2"],
                     "level3": m["level3"], "slug": slug, "file": slug + ".html",
                     "sev": sev, "sev2": sev2, "focus": focus,
                     "start": m.get("start_date", ""), "end": m.get("end_date", "")})
        cum2 = pk48.get("pSum48") or 0.0
        pk2 = max(daily2, key=lambda x: x.get("precip", 0)) if daily2 else {"precip": 0, "date": ""}
        summary_pts.append({
            "name": m["name"], "gq": gongqu(m["name"]),
            "cum": round(cum2, 1), "pkp": round(pk2.get("precip", 0), 1), "pkdate": pk2.get("date"),
            "gust": round(max(x.get("gustMax", 0) for x in daily2), 1),
            "tmax": round(max(x.get("tempMax", -99) for x in daily2), 1),
            "tmin": round(min(x.get("tempMin", 99) for x in daily2), 1),
            # 48h 峰值（hourly[:48] / daily[:2]），供 build_short 套用五要素预警阈值（非整窗 summary）
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

    # 「未来 2 天风险」短描述（约 50 字、不列等级）；build_short 不可用时回退为空
    short2 = None
    if not args.no_short and build_short:
        short2 = build_short(summary_pts, 2)

    start_label = recs[0]["start"]
    end_label = recs[0].get("end", "")
    idx = render_index(glist, counts, start_label, end_label, short2, ndays)
    out = os.path.join(outdir, "index.html")
    open(out, "w", encoding="utf-8").write(idx)
    print(f"  ✓ index.html（{len(recs)} 个点位，{len(glist)} 个分组）→ {out}")
    print(f"DONE → {outdir}")


if __name__ == "__main__":
    main()
