#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
render_points_html.py —— 由 engineering/data/*.json（逐点天气数据）渲染「无地图单页看板」
====================================================================================================
输入：engineering/data/*.json（由 build_points_data.py 生成，meta.kind=="point"，未来 两周 / 14 天窗口）
输出：
  * engineering/html/{拼音}.html —— 每个点位一张独立无地图看板，分 3 个版面（Tab）：
      - 重点关注：重点关注横幅（逐要素清单）+ 关键指标六格（2×3，与物探同款，不点名）+ 作业天气影响与建议（单节，与物探同结构：每要素一卡，风险+建议合并，气温卡含体感）
      - 未来两周：逐日图表（降水柱【降雨 + 降雪并列】/ 气温双线【含体感虚线】/
                  阵风·均风双线 / 能见度单线，服务端预渲染 SVG），
                  **可点击图表选日期**并在图上显示带浅底背景的数值框
      - 未来48小时：逐小时图（**点击 / 拖动图表选时刻**，已无独立时间轴滑块），
                  **图上（g.hread）与图上方（#hval）同时显示该时刻各要素值**，
                  日期·时间粗体高亮、要素值为「深色字 + 浅底 pill」

注意：本脚本【不再生成 index.html】。目录总览 index 已拆出为独立技能
      weather-engineering-index（scripts/build_points_index.py），
      重跑点位数据后如需刷新目录页，请单独运行该技能的 build_points_index.py。
风险等级沿用 weather-engineering-html 的 _sev 阈值（0绿/1黄/2橙/3红）。
"""
import os, json, glob, sys, base64, html as _html

# 共享取数 + 分级模块（jozzon-mcp 九章雷电网）
_COMMON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "weather-common", "scripts")
if os.path.isdir(_COMMON):
    sys.path.insert(0, os.path.abspath(_COMMON))
import jozzonwx as JW

SEV_LABEL = {0: "整体适宜", 1: "需关注", 2: "重点关注", 3: "高度警惕"}
SEV_COLOR = {0: "#2E8B57", 1: "#E0A92C", 2: "#E0822C", 3: "#C0392B"}

# ===========================================================================
# 页头背景图（hero，2026-09-28 由物探技能 weather-wutan-html 移植）
# ---------------------------------------------------------------------------
# 照片以 base64 内嵌到 CSS 背景，作为 .heroarea（顶部 topbar~tabs 整片）的**背景层**，
# **不额外占版面**；顶部白色渐隐保证文字可读。与物探侧同一套资源与参数。
# 资源缺失时 hero_css() 返回空串，页面静默退回纯色页头，不影响其余功能。
# ===========================================================================
_HERO_IMG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "hero-bg.jpg")
HERO_BLEED = "14px"      # 背景左右外扩量 = 页面左右内边距（实测 14px，做满屏出血）。
                         # ⚠️ 必须与实测 padding 严格相等：写成 16px 会多伸 2px →
                         # 手机端出现 2px 横向可拖动（2026-09-28 修）
HERO_POS_Y = "center"    # 照片纵向取景（资源已预裁成「雪山+作业面」信息带）
HERO_FADE = (            # 自上而下的白色渐隐，保证文字可读：(CSS 位置, 白色不透明度)
    ("0%", ".80"), ("44%", ".40"), ("100%", ".04"),
)

def hero_css():
    """读取 assets/hero-bg.jpg 并生成页头背景 CSS；无图时返回空串（静默降级）。"""
    try:
        with open(_HERO_IMG, "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode()
    except Exception as e:
        print("hero bg SKIPPED:", repr(e))
        return ""
    uri = "data:image/jpeg;base64," + b64
    stops = ",".join(f"rgba(255,255,255,{a}) {p}" for p, a in HERO_FADE)
    return (
        "  .heroarea{position:relative;isolation:isolate;}\n"
        "  .heroarea::before{content:\"\";position:absolute;z-index:-1;"
        f"top:-10px;bottom:-14px;left:-{HERO_BLEED};right:-{HERO_BLEED};"
        "border-radius:0 0 12px 12px;background-color:#EEF0F2;"
        "background-image:"
        f"linear-gradient(180deg,{stops}),"
        f'url("{uri}");'
        "background-size:100% 100%,cover;"
        f"background-position:center top,center {HERO_POS_Y};"
        "background-repeat:no-repeat,no-repeat;}\n"
        # 页签只去「底色 + sticky 吸附」两样（不透明底色会盖住背景；吸附时透明背景会把正文透出来），
        # padding / margin 原样保留 → 页签位置与无背景图时逐像素一致，布局零位移
        "  .heroarea .tabs{background:transparent;position:static;}\n"
        # 照片在文字下方，稍加字色加深 + 极淡白描边，保证 12px 小字仍清晰
        "  .heroarea h1,.heroarea .unit,.heroarea .sub{position:relative;z-index:1;"
        "text-shadow:0 1px 0 rgba(255,255,255,.8);}\n"
        "  .heroarea .sub{color:#4B545C;}\n"
        "  .heroarea .topbar .backlink,.heroarea .topbar .extlink{box-shadow:0 1px 3px rgba(0,0,0,.10);}\n"
    )

# ===========================================================================
# 气象要素小图标（2026-09-28 由物探技能 weather-wutan-html 移植）
# ---------------------------------------------------------------------------
# 用法：eic("rain","danger") → 红底雨云；eic("wind") → 灰底风（图例用，不带风险属性）。
# 语义与物探侧一致：**色块＝风险等级，图形＝要素本身**。
# ===========================================================================
EIC = {
    "rain": '<path d="M20 16.6A5 5 0 0 0 18 7h-1.3A8 8 0 1 0 4 15.3"/>'
            '<path d="M8 13.2v7.6M12 15.2v7.6M16 13.2v7.6"/>',
    "snow": '<path d="M12 3.2v17.6M4.2 7.8l15.6 8.4M19.8 7.8 4.2 16.2"/>'
            '<path d="m12 7-2.2-2.3M12 7l2.2-2.3M12 17l-2.2 2.3M12 17l2.2 2.3"/>',
    "wind": '<path d="M3.5 9h10a3 3 0 1 0-3-3"/>'
            '<path d="M4 13.5h11.5a3 3 0 1 1-3 3"/><path d="M4.2 18h5"/>',
    "temp": '<path d="M14 14.8V4.2a2.2 2.2 0 0 0-4.4 0v10.6a4.4 4.4 0 1 0 4.4 0z"/>',
    "heat": '<circle cx="12" cy="12" r="4"/>'
            '<path d="M12 2.6v2.3M12 19.1v2.3M2.6 12h2.3M19.1 12h2.3'
            'M5.4 5.4l1.7 1.7M16.9 16.9l1.7 1.7M18.6 5.4l-1.7 1.7M7.1 16.9l-1.7 1.7"/>',
    "fog":  '<path d="M4 8.4h16M6.6 12h10.8M4 15.6h16"/>',
}

def eic(kind, lvl="plain", size=""):
    """气象要素小图标：色块＝风险等级（绿 ok / 橙 warn / 红 danger），图形＝要素。
    size："" 默认 19px / "s" 16px（读数行、风险卡标题）/ "xs" 13px（作业影响建议每条）。
    lvl 传入未知值（含 None）一律退回 .plain，避免出现无底色的「隐形图标」。"""
    g = EIC.get(kind)
    if not g:
        return ""
    L = lvl if lvl in ("ok", "warn", "danger") else "plain"
    sz = f" {size}" if size in ("s", "xs") else ""
    return (f'<span class="eic {L}{sz}" aria-hidden="true">'
            f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"'
            f' stroke-linecap="round" stroke-linejoin="round">{g}</svg></span>')

def lv_rain(v):
    """小时级降水分级（mm/h）：≥6 暴雨 danger / ≥3 大雨 warn。与 RAIN_H 一致。"""
    if v is None: return "ok"
    return "danger" if v >= RAIN_H["storm"] else ("warn" if v >= RAIN_H["heavy"] else "ok")

def lv_gust(v):
    """阵风分级（m/s，2026-10-17 新口径：同级比均风高两级风力，八级阵风 = 六级均风）：
    ≥24.5（十级 狂风）danger / ≥17.2（八级 大风）warn。"""
    if v is None: return "ok"
    if v >= 24.5: return "danger"
    if v >= 17.2: return "warn"
    return "ok"

def lv_wind(v):
    """均风分级（m/s）：≥17.2（八级）danger / ≥10.8（六级）warn。"""
    if v is None: return "ok"
    if v >= 17.2: return "danger"
    if v >= 10.8: return "warn"
    return "ok"

def lv_temp(v):
    """温度分级（°C）：≥35 danger（高温） / ≤-5 warn（寒冷）。"""
    if v is None: return "ok"
    return "danger" if v >= 35 else ("warn" if v <= -5 else "ok")

def lv2eic(lv):
    """要素等级（0-4，jozzonwx.grade_* 输出）→ eic 风险色（ok/warn/danger）。
    lv1 属「注意」档，与影响卡一致（不再算成绿色）。"""
    return "danger" if lv >= 3 else ("warn" if lv >= 1 else "ok")

def _temp_icon_hot(tmax, appMax):
    """最高气温图标色：体感温度（UTCI）纳入判据，与「作业天气影响与建议」一致——
    plain≥35 或 体感酷热≥38 危险；体感偏热≥32 注意。"""
    if (tmax is not None and tmax >= 35) or (appMax is not None and JW.grade_utci(appMax)[0] >= 3):
        return "danger"
    if appMax is not None and JW.grade_utci(appMax)[0] >= 2:
        return "warn"
    return "ok"

def _temp_icon_cold(tmin, appMin):
    """最低气温图标色：plain≤0 或 体感严寒≤-13 注意；体感极寒≤-27 危险。"""
    if appMin is not None and JW.grade_utci(appMin)[0] >= 3:
        return "danger"
    if (tmin is not None and tmin <= 0) or (appMin is not None and JW.grade_utci(appMin)[0] >= 2):
        return "warn"
    return "ok"

# 要素 kind → eic 图标种类（banner 逐要素清单用）；等级 → eic 风险色（lv0 绿 / lv1~2 橙 / lv3~4 红）
_EIC_KIND = {"rain":"rain", "snow":"snow", "gust":"wind", "wind":"wind", "utci":"temp", "vis":"fog"}
def _lv_eic(lv): return "danger" if lv >= 3 else ("warn" if lv >= 1 else "ok")

# ---------- 天气现象分级标签（与用户给定的标准阈值一致）----------
# 叙述文案用的简短风力标签（**不带「预警」二字**：七级阵风在新口径属正常档，
# 写成「疾风七级预警」会和「无大风风险」自相矛盾）
_GUST_LV_TXT = {0: "7级及以下", 1: "七级", 2: "八级", 3: "十级", 4: "十二级"}
_WIND_LV_TXT = {0: "5级及以下", 1: "五级", 2: "六级", 3: "八级", 4: "十级"}

def gust_lbl(v):
    """阵风等级短标签（m/s，2026-10-17 新口径）：七级 / 八级 / 十级 / 十二级。"""
    if v is None: return _GUST_LV_TXT[0]
    return _GUST_LV_TXT[JW.grade_gust(v)]

def wind_lbl(v):
    """均风等级短标签（m/s）：五级 / 六级 / 八级 / 十级。"""
    if v is None: return _WIND_LV_TXT[0]
    return _WIND_LV_TXT[JW.grade_wind(v)]

def ltemp_lbl(v):
    """低温等级标签（°C）：零下5度寒冷 / 零下15度严寒 / 零下25度极寒。"""
    if v <= -25: return "零下25度极寒预警（零下25度）"
    if v <= -15: return "零下15度严寒预警（零下15度）"
    if v <= -5:  return "零下5度寒冷预警（零下5度）"
    return "温度正常"

def htemp_lbl(v):
    """高温等级标签（°C）：35度高温 / 37度酷热 / 40度极端高温。"""
    if v >= 40: return "40度极端高温预警（40度）"
    if v >= 37: return "37度酷热预警（37度）"
    if v >= 35: return "35度高温预警（35度）"
    return "温度正常"

# ---------- 小时级短时降水阈值（mm/h）----------
# 只作用于「未来 48 小时」口径，与物探看板 weather-wutan-html 的 RAIN_H 完全一致：
#   ≥3 mm/h 大雨 / ≥6 mm/h 暴雨 / ≥15 mm/h 大暴雨
#   （对应标准「大雨预警(3mm/h) / 暴雨预警(6mm/h) / 大暴雨预警(15mm/h)」）
# 「未来 两周」逐日图与关键指标仍按日累计 25/50mm，两套口径不混用。
RAIN_H = {"heavy": 3.0, "storm": 6.0, "torrent": 15.0}

def rain_hour_label(v):
    """小时级降水的等级文案（供卡片 / 影响建议 / 横幅复用）。"""
    if v >= RAIN_H["torrent"]: return "短时大暴雨"
    if v >= RAIN_H["storm"]:   return "短时暴雨"
    if v >= RAIN_H["heavy"]:   return "短时大雨"
    return "降水"

def phour_max(hourly48):
    """近 48 小时最大小时降水（mm/h）。hourly48 为已截断的前 48 小時逐小时数据。"""
    pr = hourly48.get("rainfall") or []
    return round(max(pr) if pr else 0.0, 1)

# ---------- 风险等级（风阈值 2026-10-17 起统一走 jozzonwx.grade_gust/grade_wind） ----------
def sev_of(daily, s):
    pmax = max((d["rainfall"] for d in daily), default=0)
    gust = s["maxGust"]; tmax = s["maxTemp"]; tmin = s["minTemp"]; wind = s["maxWind"]
    focus = sum(d["rainfall"] for d in daily if d["rainfall"] >= 10)
    if pmax >= 80 or JW.grade_gust(gust) >= 4 or tmax >= 38 or focus >= 150: return 3
    if pmax >= 50 or JW.grade_gust(gust) >= 3 or tmax >= 35 or tmin <= -5 or focus >= 80: return 2
    if pmax >= 12 or JW.grade_wind(wind) >= 2 or tmin <= -5 or focus >= 30: return 1
    return 0

def sev_of_recent(daily2, ph=0.0, el48=None, snow_h=None):
    """未来 48 小时风险等级：**全部要素**取 hourly 前 48 格窗口（el48，见 h48_elements），
    仅日累计降水 pmax 仍取 daily 前 2 天（逐日峰值本身不会漏，且与用户习惯的「单日 XXmm」一致）。
    降水同时看「日累计」与「小时级短时降水」——短时 >15mm/h 按大暴雨级给重点关注、
    >6mm/h 按暴雨级给需关注、>3mm/h 按大雨级给需关注，与物探看板 _sev_of 一致。
    **新增要素（均风 / 体感温度 UTCI / 能见度 / 降雪）统一经 jozzonwx.el_levels 计级并入**，
    与 weather-engineering-index / 物探看板共用同一套分级，杜绝两边口径漂移。"""
    pmax = max((d["rainfall"] for d in daily2), default=0)
    cum = sum(d["rainfall"] for d in daily2)
    if el48:
        gust = el48.get("maxGust") or 0.0
        wind = el48.get("maxWind") or 0.0
        tmax = el48.get("tmax") if el48.get("tmax") is not None else 99
        tmin = el48.get("tmin") if el48.get("tmin") is not None else 99
        appMax = el48.get("appMax")
        appMin = el48.get("appMin")
        visMin = el48.get("visMin")
    else:
        gust = max((d["gustMax"] for d in daily2), default=0)
        wind = max((d["windMax"] for d in daily2), default=0)
        tmax = max((d["tempMax"] for d in daily2), default=99)
        tmin = min((d["tempMin"] for d in daily2), default=99)
        appMax = appMin = None
        visMin = None
    if appMax is None:
        appMax = max((d.get("apparentMax", -99) for d in daily2), default=-99)
        appMin = min((d.get("apparentMin", 99) for d in daily2), default=99)
    if visMin is None:
        vp = [d.get("visMin") for d in daily2 if d.get("visMin")]
        visMin = min(vp) if vp else None
    appMax = appMax if (appMax is not None and appMax > -99) else None
    appMin = appMin if (appMin is not None and appMin < 99) else None
    # ph = 48h 内最大小时降水（mm/h）：短时强降水须计入，否则日累计小的井位会被低估
    if pmax >= 80 or JW.grade_gust(gust) >= 4 or tmax >= 38 or cum >= 150: sev = 3
    elif ph >= RAIN_H["torrent"] or pmax >= 50 or JW.grade_gust(gust) >= 3 or tmax >= 35 or tmin <= -5 or cum >= 80: sev = 2
    elif ph >= RAIN_H["storm"] or ph >= RAIN_H["heavy"] or pmax >= 12 or JW.grade_wind(wind) >= 2 or tmin <= -5 or cum >= 20: sev = 1
    else: sev = 0
    #用户规则（2026-10-09）：有明显降雨（中雨及以上，即 >=1.5mm/h）即至少定为「需关注」；
    # 降雪、阵风、高/低温仍按各自等级判定，不因这条降雨规则被额外抬级。
    if ph >= 1.5:
        sev = max(sev, 1)
    # 新增要素（均风/UTCI/能见度/降雪）48h 等级并入综合风险；
    # 同时充当一致性兜底：任一要素达 3 级及以上时，综合等级至少「需关注」。
    peaks = {"rain": ph, "snow": snow_h or 0.0, "wind": wind or 0.0, "gust": gust or 0.0,
             "appMax": appMax, "appMin": appMin, "visMin": visMin}
    sev = max(sev, JW.sev_from_levels(JW.el_levels(peaks)))
    return sev


def snow_hour_max_48(hourly48):
    """未来 48 小时窗口的最大小时降雪量（mm/h），与 index 的
    peaks_48h()["snowHourMax"]、雪卡判据同源同值，供一致性兜底判暴雪等级。

    ⚠️ 2026-10-16 修：jozzon-mcp 返回的 `hourly.snowfall` **已是 mm/h**，
    这里**不再做 ×10（cm→mm）换算**——旧 Open-Meteo 时代降雪是 cm，
    遗留的 ×10 会把 0.2mm/h 的雪放大成 2.0 → grade_snow 判成 4 级「极强降雪」，
    凭空冒出高度警惕。物探 build_dashboard 的 snowHourMax 同样无 ×10。"""
    sf = (hourly48 or {}).get("snowfall") or []
    if not sf:
        return None
    return round(max(sf[:48]), 2)


def _alert_lv_48(daily2, ph, el48, gust, tmax, tmin, snow_h=None):
    """未来 48 小时各要素预警等级（沿用用户 2026-10-09 阈值），供一致性兜底判定。
    与 index 的 rain_alert/gust_alert/snow_alert/thigh_alert/tlow_alert 同一套阈值。
    snow_h：hourly 前 48 格的降雪峰值（**mm/h，无 ×10**，与 index 的 peaks_48h.snowHourMax 同源）；
    传None 时退回 daily 日均降雪（仅无 hourly 的旧数据）。"""
    def _rain(mmh):
        if mmh is None: return 0
        if mmh >= 15: return 5
        if mmh >= 6:  return 4
        if mmh >= 3:  return 3
        if mmh >= 1.5: return 2
        if mmh >= 0.2: return 1
        return 0
    def _snow(mmh):
        if mmh is None: return 0
        if mmh >= 2:return 4
        if mmh >= 1:   return 3
        if mmh >= 0.5: return 2
        if mmh >= 0.1: return 1
        return 0
    def _gust(v):
        # 2026-10-17：阵风阈值上调两档（13.9/17.2/24.5/32.7），直接走共享真源，勿本地复制
        return JW.grade_gust(v)
    def _hi(v):
        if v is None: return 0
        if v >= 40: return 3
        if v >= 37: return 2
        if v >= 35: return 1
        return 0
    def _lo(v):
        if v is None: return 0
        if v <= -25: return 3
        if v <= -15: return 2
        if v <= -5:  return 1
        return 0
    if snow_h is None:
        snow_h = max(((d.get("snowfall") or 0) for d in (daily2 or [])), default=0) or None
    return (_rain(ph), _snow(snow_h), _gust(gust), _hi(tmax), _lo(tmin))

def h48_precip(hourly48):
    """未来 48 小时（起始小时起连续 48 个逐小时）累计降水 mm。
    不用「两个自然日之和」——当日已过去大半，两日累计会明显偏大。"""
    pr = (hourly48.get("rainfall") or [])[:48]
    return round(sum(pr), 1)

def h48_elements(hourly48):
    """未来 48 小时窗口的阵风/持续风/最高温/最低温/体感温度/能见度极值（与 h48_precip 同一时间窗）。

    **一律用 hourly 逐小时窗口，不用 daily[:2]，也不用 summary 全窗值**：
    ① hourly 起点是当日整点，48h 窗口横跨 3 个自然日，daily[:2] 会整段漏掉第 3 天；
    ② summary.maxGust/maxTemp/minTemp 是 14 天全窗极值，会把第 3~14 天的远端
       大风/高温/寒潮当成「未来两天」的风险（实测贵阳东支线阵风 16.3 vs 48h 内 8.8、
       红页7-5HF 最低温全窗 6.7℃ vs 48h 内 15.1℃ → 会误报寒冷/大风预警）。
    hourly 缺失时才退回 daily[:2]。"""
    h = hourly48 or {}
    g48 = h.get("wind_gusts_10m") or []
    w48 = h.get("wind_speed_10m") or []
    t48 = h.get("temperature_2m") or []
    a48 = h.get("apparent_temperature") or []
    v48 = h.get("visibility") or []
    if not (g48 or w48 or t48 or a48 or v48):
        d2 = (h.get("_daily2") or [])
        if not d2:
            return {"maxGust": None, "maxWind": None, "tmax": None, "tmin": None,
                    "appMax": None, "appMin": None, "visMin": None}
        _am48 = [x.get("apparentMax") for x in d2 if x.get("apparentMax") is not None]
        _an48 = [x.get("apparentMin") for x in d2 if x.get("apparentMin") is not None]
        return {"maxGust": round(max((x.get("gustMax", 0) for x in d2), default=0), 1),
                "maxWind": round(max((x.get("windMax", 0) for x in d2), default=0), 1),
                "tmax": round(max((x.get("tempMax", -99) for x in d2), default=-99), 1),
                "tmin": round(min((x.get("tempMin", 99) for x in d2), default=99), 1),
                # ⚠️ 体感缺省必须给 None，不能给 -99/99 哨兵值：旧数据没有
                # apparentMax/apparentMin 时，哨兵值会被 grade_utci 判成
                # 「极寒(-99) / 极热(99)」4 级，凭空冒出「极热预警」。
                "appMax": round(max(_am48), 1) if _am48 else None,
                "appMin": round(min(_an48), 1) if _an48 else None,
                "visMin": round(min((x.get("visMin", 1e9) for x in d2 if x), default=1e9))
                          if any(x and x > 0 for x in (x.get("visMin") for x in d2)) else None}
    def _mx(s): return round(max(s[:48]), 1) if s else None
    def _mn(s): return round(min(s[:48]), 1) if s else None
    vp = [x for x in v48[:48] if x and x > 0]
    return {
        "maxGust": _mx(g48), "maxWind": _mx(w48),
        "tmax": _mx(t48), "tmin": _mn(t48),
        "appMax": _mx(a48), "appMin": _mn(a48),
        "visMin": round(min(vp), 0) if vp else None,
    }

def h48_span(hourly48):
    """未来 48 小时窗口的起止时刻文案（如 `10-09 12 时~10-11 11 时`）。"""
    ts = (hourly48.get("time") or [])[:48]
    if not ts:
        return "未来 48 小时"
    def lab(t):
        d, hm = t.split("T", 1)
        return f"{d[5:]} {int(hm[:2])} 时"
    return f"未来 48 小时（{lab(ts[0])}~{lab(ts[-1])}）"

def alert_desc(daily, s, ph=0.0, hourly48=None):
    """「主要关注」卡片：**全部要素**统一用未来 48 小时逐小时窗口口径
    （风/温不再取 summary 全窗 14 天极值，也不取 daily[:2]）。"""
    parts = []
    cum = h48_precip(hourly48 or {})
    if cum >= 0.5:
        parts.append(f"{h48_span(hourly48 or {})}累计降水 {cum}mm")
    if ph >= RAIN_H["heavy"]:
        parts.append(f"{rain_hour_label(ph)}最大小时降水 {ph}mm/h")
    e = h48_elements(hourly48 or {})
    g, w, tm, tn = e["maxGust"], e["maxWind"], e["tmax"], e["tmin"]
    if g is not None and g >= 17.2:
        parts.append(f"阵风最大 {g}m/s（{gust_lbl(g)}）")
    if tm is not None and tm >= 35:
        parts.append(f"最高温 {tm}°C（{htemp_lbl(tm)}）")
    if tn is not None and tn <= -5:
        parts.append(f"最低温 {tn}°C（{ltemp_lbl(tn)}）")
    if not parts:
        parts.append("未来 48 小时天气整体平稳，无明显极端天气")
    return "主要关注：" + "；".join(parts) + "。建议据此调整作业安排。"

def _near_summary(daily2, ph=0.0, hourly48=None):
    """「重点提示」Tab 的 48h 口径聚合。累计降水与风/温/体感/能见度**全部**取 hourly 前 48 格
    （同h48_precip / h48_elements 口径），不用 daily[:2]、也不用 summary 全窗值。"""
    h = dict(hourly48 or {})
    h["_daily2"] = list(daily2 or [])
    e = h48_elements(h)
    return {
        "totalPrecip": h48_precip(hourly48 or {}),
        "pHourMax": ph,                 # 48h 内最大小时降水（mm/h），与 totalPrecip 并列展示
        "maxGust": e["maxGust"],
        "maxWind": e["maxWind"],
        "maxTemp": e["tmax"],
        "minTemp": e["tmin"],
        "maxApparent": e["appMax"],
        "minApparent": e["appMin"],
        "minVis": e["visMin"],
    }

# ---------- 关键指标六格（2026-10-17 与物探看板 #statsBox 同款结构，只是不点名） ----------
def h48_snow(hourly48):
    """未来 48 小时累计降雪（mm，水当量）——与 h48_precip 同一时间窗。"""
    sf = (hourly48 or {}).get("snowfall") or []
    return round(sum(x for x in sf[:48] if x), 1)

def app_at_temp(hourly48, mode="max"):
    """最高/最低气温**同一小时**的体感温度（与物探 appAt() 同口径）。

    注意不能直接用 appMax/appMin：那是整个 48h 窗口的体感极值，可能出现在
    另一个小时，和「最高气温同时刻体感」不是一回事（两者可差 3~5℃）。"""
    h = hourly48 or {}
    t = h.get("temperature_2m") or []
    a = h.get("apparent_temperature") or []
    n = min(len(t), len(a), 48)
    idx, best = -1, None
    for i in range(n):
        v = t[i]
        if v is None:
            continue
        if best is None or (v > best if mode == "max" else v < best):
            best, idx = v, i
    if idx < 0:
        return None
    av = a[idx]
    return None if av is None else round(av, 1)

def kpi_stats_html(sNear, hourly48=None):
    """重点提示 Tab 的「关键指标」六格：2 列 × 3 行、每格多行「要素 / 数值 / 单位」。

    结构/顺序与物探 build_dashboard 的 #statsBox 完全一致（累计降水 → 最大降水 →
    最高气温 → 最低气温 → 最大风速 → 最低能见度）；**唯一差别是不挂点名牌**——
    工程每个看板本身就是单个井位，点名没有信息量。
    风险色（图标底色）仍走 lv_rain / lv_temp / lv_gust / grade_vis，无阈值副本。"""
    h = hourly48 or {}
    snow_h = snow_hour_max_48(h)
    snow_t = h48_snow(h)
    a_hi = app_at_temp(h, "max")
    a_lo = app_at_temp(h, "min")

    def num(v):
        if v is None:
            return "—"
        r = round(float(v), 1)
        return str(int(r)) if abs(r - int(r)) < 1e-9 else f"{r:.1f}"

    def cell(icon, cls, title, rows):
        body = "".join(
            '<div class="vr">'
            + (f"<em>{k}</em>" if k else "")
            + f"<b>{num(v)}</b>"
            + (f"<i>{u}</i>" if u else "")
            + "</div>"
            for k, v, u in rows)
        return (f'<div class="stat"><div class="k">{eic(icon, cls)}{title}</div>'
                f'<div class="vs">{body}</div></div>')

    vis_lv = JW.grade_vis(sNear["minVis"]) if sNear.get("minVis") is not None else 0
    return "".join([
        cell("rain", lv_rain(sNear.get("pHourMax")), "累计降水",
             [("降雨", sNear.get("totalPrecip"), "mm"), ("降雪", snow_t, "mm")]),
        cell("rain", lv_rain(sNear.get("pHourMax")), "最大降水",
             [("降雨", sNear.get("pHourMax"), "mm/h"), ("降雪", snow_h, "mm/h")]),
        cell("heat", _temp_icon_hot(sNear.get("maxTemp"), a_hi), "最高气温",
             [("气温", sNear.get("maxTemp"), "℃"), ("体感", a_hi, "℃")]),
        cell("temp", _temp_icon_cold(sNear.get("minTemp"), a_lo), "最低气温",
             [("气温", sNear.get("minTemp"), "℃"), ("体感", a_lo, "℃")]),
        cell("wind", lv_gust(sNear.get("maxGust")), "最大风速",
             [("阵风", sNear.get("maxGust"), "m/s"), ("均风", sNear.get("maxWind"), "m/s")]),
        cell("fog", lv2eic(vis_lv), "最低能见度",
             [("", round(sNear["minVis"]) if sNear.get("minVis") is not None else None, "m")]),
    ])

# 「重点提示」横幅正文：逐要素清单（要素序固定：降水→降雪→阵风→均风→体感→能见度）
_EL_ORDER_ENG = (("rain", "降水"), ("snow", "降雪"), ("gust", "阵风"),
                 ("wind", "均风"), ("utci", "体感"), ("vis", "能见度"))
_EL_UNIT_ENG = {"rain": "mm/h", "snow": "mm/h", "gust": "m/s",
                "wind": "m/s", "utci": "°C", "vis": "m"}
_EL_LABEL_ENG = {"rain": JW.RAIN_ALERT_S, "snow": JW.SNOW_ALERT_S,
                 "gust": JW.GUST_ALERT_S, "wind": JW.WIND_ALERT_S,
                 "vis": JW.VIS_ALERT_S}


def alert_items(sNear, hourly48=None):
    """重点提示横幅正文 —— **逐要素清单**（2026-10-17 用户口径，与物探看板同款）。

    每个要素只列「未来 48h 窗口内最高级别」那一条 → 要素 / 等级名 / 数值+单位；
    **只有达 1 级（触发阈值）的要素才占行**，未达阈值的不写（不罗列否定式）。
    数值口径与关键指标同源：降水＝48h 最大小时降水（mm/h）、降雪＝48h 最大小时降雪（mm/h）、
    阵风/均风＝48h 最大风速、体感＝冷热两端里更严重的一侧、能见度＝48h 最低值（m）。
    等级/标签一律来自 jozzonwx，本文件不保存阈值副本。"""
    snow_h = snow_hour_max_48(hourly48 or {})
    cands = [
        ("rain", JW.grade_rain(sNear.get("pHourMax") or 0), sNear.get("pHourMax")),
        ("snow", JW.grade_snow(snow_h or 0), snow_h),
        ("gust", JW.grade_gust(sNear.get("maxGust") or 0), sNear.get("maxGust")),
        ("wind", JW.grade_wind(sNear.get("maxWind") or 0), sNear.get("maxWind")),
    ]
    # 体感：冷、热两端取更严重的一侧（同级时取更极端值），与 grade_utci 双向分级一致
    am, an = sNear.get("maxApparent"), sNear.get("minApparent")
    best_lv, best_v = 0, None
    for v in (an, am):
        if v is None:
            continue
        lv = JW.grade_utci(v)[0]
        if lv > best_lv:
            best_lv, best_v = lv, v
        elif lv == best_lv and lv and best_v is not None:
            if (v < 0 and v < best_v) or (v >= 0 and v > best_v):
                best_v = v
    cands.append(("utci", best_lv, best_v))
    _vis = sNear.get("minVis")
    cands.append(("vis", JW.grade_vis(_vis) if _vis is not None else 0, _vis))

    order = {k: i for i, (k, _n) in enumerate(_EL_ORDER_ENG)}
    disp = dict(_EL_ORDER_ENG)
    out = []
    for kind, lv, val in cands:
        if not lv or val is None:
            continue
        if kind == "utci":
            lbl = (JW.UTCI_HOT_S if val >= 0 else JW.UTCI_COLD_S).get(int(lv), "")
        else:
            lbl = _EL_LABEL_ENG[kind].get(int(lv), "")
        out.append({"kind": kind, "name": disp[kind], "lv": int(lv), "label": lbl,
                    "val": round(float(val), 1), "unit": _EL_UNIT_ENG[kind],
                    "order": order[kind]})
    out.sort(key=lambda x: (-x["lv"], x["order"]))
    return out


def far_alert(daily):
    """未来 2~14 天（第 3 天起，远端）重大极端天气提示：仅当出现「重大」级别才返回文案，否则 None。
    判定阈值与物探看板一致：暴雨≥50mm / 阵风≥24.5m/s（十级） / 高温≥35°C / 严寒≤-5°C。"""
    far = daily[2:]
    if not far:
        return None
    items = []
    big_rain = [d for d in far if d["rainfall"] >= 50]
    if big_rain:
        f0, f1 = big_rain[0]["date"][5:], big_rain[-1]["date"][5:]
        span = f"{f0}~{f1}" if f0 != f1 else f0
        items.append(f"{span} 暴雨（单日最大 {max(d['rainfall'] for d in big_rain)}mm）")
    g = [d for d in far if d["gustMax"] >= 24.5]
    if g:
        items.append(f"阵风最大 {max(d['gustMax'] for d in g)}m/s（{gust_lbl(max(d['gustMax'] for d in g))}）")
    t = [d for d in far if d["tempMax"] >= 35]
    if t:
        items.append(f"高温 {max(d['tempMax'] for d in t)}°C（{htemp_lbl(max(d['tempMax'] for d in t))}）")
    c = [d for d in far if d["tempMin"] <= -5]
    if c:
        items.append(f"低温 {min(d['tempMin'] for d in c)}°C（{ltemp_lbl(min(d['tempMin'] for d in c))}）")
    return "；".join(items) if items else None

def risk_of(daily, s):
    pmax = max((d["rainfall"] for d in daily), default=0)
    if JW.grade_gust(s["maxGust"]) >= 3 or s["maxTemp"] >= 35 or pmax >= 50: return "danger"
    if pmax >= 25 or JW.grade_wind(s["maxWind"]) >= 2 or s["minTemp"] <= 0: return "warn"
    return "ok"

# ---------- SVG 图表（服务端预渲染，无 JS 依赖） ----------
def _scale(lo, hi):
    if lo == hi:
        lo -= 1; hi += 1
    pad = (hi - lo) * 0.15
    return lo - pad, hi + pad

# ---------- 降水类型图标（降雨 / 降雪 / 雨夹雪）----------
# 类型码：0=无 1=降雨 2=降雪 3=雨夹雪（与取数端 build_points_data.ptype_of 一致）
PTYPE_TEXT = {0: "", 1: "降雨", 2: "降雪", 3: "雨夹雪"}

def precip_icon_svg(ptype, cx, cy, H, color):
    """以 (cx,cy) 为中心画一个高约 H 的降水类型图标，返回 SVG 片段。
    降雨=雨滴；降雪=六角雪花；雨夹雪=左小雨滴 + 右小雪花。"""
    if not ptype or H <= 2.5:
        return ""
    parts = []
    def drop(ax, ay, h):
        k = h / 6.75
        d = (f"M{ax:.2f} {ay-k*3.4:.2f} C{ax+k*1.55:.2f} {ay-k*1.35:.2f} "
             f"{ax+k*2.4:.2f} {ay-k*0.25:.2f} {ax+k*2.4:.2f} {ay+k*0.95:.2f} "
             f"A {k*2.4:.2f} {k*2.4:.2f} 0 1 1 {ax-k*2.4:.2f} {ay+k*0.95:.2f} "
             f"C{ax-k*2.4:.2f} {ay-k*0.25:.2f} {ax-k*1.55:.2f} {ay-k*1.35:.2f} "
             f"{ax:.2f} {ay-k*3.4:.2f} Z")
        parts.append(f'<path d="{d}" fill="{color}"/>')
    def snow(ax, ay, h):
        k = h / 6.2
        sw = max(0.9, k * 1.05)
        for v in ((0, -1, 0, 1), (0.866, -0.5, -0.866, 0.5), (0.866, 0.5, -0.866, -0.5)):
            parts.append(f'<line x1="{ax+v[0]*k*3.1:.2f}" y1="{ay+v[1]*k*3.1:.2f}" '
                         f'x2="{ax+v[2]*k*3.1:.2f}" y2="{ay+v[3]*k*3.1:.2f}" '
                         f'stroke="{color}" stroke-width="{sw:.2f}" stroke-linecap="round"/>')
    if ptype == 1:
        drop(cx, cy, H)
    elif ptype == 2:
        snow(cx, cy, H)
    else:
        drop(cx - H * 0.62, cy, H * 0.62)
        snow(cx + H * 0.62, cy, H * 0.48)
    return '<g class="ptico">' + "".join(parts) + '</g>'

# 降水类型配色（与物探看板一致）：降雨=蓝 降雪=青 雨夹雪=紫；未知类型兜底灰蓝
PT_FILL = {1: "#2E86DE", 2: "#5DD6E8", 3: "#B07CD6"}
PT_FILL_FB = "#9DB4C8"

def ptype_icon_w(ptype, H):
    """类型图标的横向占位宽度（雨夹雪最宽），用于判断柱宽是否容得下"""
    return H * 1.25 if ptype == 3 else H * 0.72

def precip_icon_in_bar(ptype, cx, base, bh, bw):
    """按柱宽 / 柱高自动定尺寸画类型图标：柱体够高 → 柱内白色图标；
    柱太矮放不下 → 改画在柱顶上方（深色、不占柱体），保证每根有类型的柱都能标出。
    返回 (svg 片段, 图标高度 H, 是否画在柱上方)；未绘制返回 None。"""
    if not ptype:
        return None
    H = min(bw * 0.95, 11)
    if bh >= H + 5:
        return (precip_icon_svg(ptype, cx, base - bh + H / 2 + 1.5, H, "rgba(255,255,255,.95)"),
                H, False)
    H = min(bw * 0.95, 9)
    if H < 3:
        return None
    if ptype_icon_w(ptype, H) > bw * 0.98:
        H = bw * 0.98 / (1.25 if ptype == 3 else 0.72)
    if H < 3:
        return None
    return (precip_icon_svg(ptype, cx, base - bh - H / 2 - 1.5, H, "rgba(84,110,122,.92)"),
            H, True)

_LEG_C = "#546E7A"
def ptype_legend_html():
    """降水类型图例（颜色块）：降雨=蓝 降雪=青 雨夹雪=紫"""
    sw = lambda c, t: (f'<span style="display:inline-flex;align-items:center;gap:3px;margin-left:9px">'
                       f'<i style="width:12px;height:12px;border-radius:3px;background:{c};display:inline-block"></i>{t}</span>')
    return (eic("rain") + sw(PT_FILL[1], "降雨") + sw(PT_FILL[2], "降雪") + sw(PT_FILL[3], "雨夹雪"))

def svg_bars(dates, values, color, h=160, w=680, sid="", days=None, unit="mm", label="降水",
             ptypes=None, extra=None):
    """服务端预渲染柱状图。extra 为可选的附加柱系列 [(名称, 数值数组, 颜色), ...]，
    与主系列在「同一天内」并排分组绘制——用于把降雪并入降水图（降雨蓝 + 降雪青）。
    extra 为空时行为与旧版完全一致（单系列、按 ptypes 着色）。"""
    left, right, top, bot = 42, 12, 14, 30
    x0, x1, y0, y1 = left, w - right, top, h - bot
    extras = [(nm, list(vs), cl) for nm, vs, cl in (extra or [])]
    series_all = [(label, list(values), color)] + extras
    vmin = 0.0                                     # 基线恒为 0：不再向下 pad 出负值（否则 0mm 也会被画成约 13px 的柱子）
    vmax = max([v for _, vs, _ in series_all for v in vs] + [1]) * 1.15   # 顶部留 15% 余量
    def X(i): return x0 + (x1 - x0) * (i + 0.5) / len(dates)
    def Y(v): return y1 - (v - vmin) / (vmax - vmin) * (y1 - y0)
    groups = len(series_all)
    slot = (x1 - x0) / len(dates)
    bw = slot * (0.55 if groups == 1 else 0.30)
    gap = 0.0 if groups == 1 else slot * 0.05
    payload = {"kind": "bar", "n": len(dates), "x0": x0, "x1": x1, "top": y0, "bot": y1,
               "w": w, "h": h, "unit": unit, "days": days or dates,
               "ptypes": list(ptypes or []),
               "series": [{"name": nm, "color": cl, "vals": vs} for nm, vs, cl in series_all]}
    dp = _html.escape(json.dumps(payload, ensure_ascii=False), quote=True)
    attrs = f'id="{sid}" class="dchart"' if sid else ""
    p = [f'<svg {attrs} data-payload="{dp}" viewBox="0 0 {w} {h}" width="100%" preserveAspectRatio="xMinYMin meet" style="display:block">']
    for g in range(4):
        gv = vmax * g / 3; gy = Y(gv)
        p.append(f'<line x1="{x0}" y1="{gy:.1f}" x2="{x1}" y2="{gy:.1f}" stroke="#ececec"/>')
        glab = f"{gv:.0f}" if vmax >= 10 else f"{gv:.1f}"
        p.append(f'<text x="{x0-5}" y="{gy+3:.1f}" text-anchor="end" font-size="12" fill="#999">{glab}</text>')
    for i, d in enumerate(dates):
        cx = X(i)
        pt = ptypes[i] if (ptypes and i < len(ptypes)) else 0
        group_w = bw * groups + gap * (groups - 1)
        gx = cx - group_w / 2
        for gi, (nm, vs, cl) in enumerate(series_all):
            v = vs[i] if i < len(vs) else 0.0
            bx = gx + gi * (bw + gap)
            # 无降水不画柱；单系列时降雪水当量不足 0.1mm 仍保留最小柱以承载类型着色
            if not (v > 0 or (groups == 1 and pt)):
                continue
            bh = max(y1 - Y(v), 3.0)                 # 小值也保证 3px 可见高度
            bcolor = (PT_FILL.get(pt, PT_FILL_FB) if groups == 1 else cl)
            p.append(f'<rect x="{bx:.1f}" y="{y1-bh:.1f}" width="{bw:.1f}" height="{bh:.1f}" fill="{bcolor}" rx="2"/>')
            # 小值保留一位小数（避免 0.3mm 被标成「0」）；微量降雪折合不足 0.1mm 时标「<0.1」
            lab = (f"{v:.0f}" if v >= 10 else f"{v:.1f}") if v > 0 else "<0.1"
            lab_y = y1 - bh - 4
            p.append(f'<text x="{bx+bw/2:.1f}" y="{lab_y:.1f}" text-anchor="middle" font-size="11" fill="#444">{lab}</text>')
        p.append(f'<text x="{cx:.1f}" y="{h-9}" text-anchor="middle" font-size="11" fill="#888">{d[5:]}</text>')
    p.append('</svg>')
    return "".join(p)

def svg_lines(dates, series, h=160, w=680, sid="", days=None, unit=""):
    """服务端预渲染折线图。series 每项为 (名称, 数值数组, 颜色)，或
    (名称, 数值数组, 颜色, 选项字典)，选项支持：
      labels=False —— 关闭该折线的逐点数值标注（把体感并入气温图时，4 条线逐点标值会互相遮挡，
                      故体感只画虚线不标值；点选日期时数值框仍会给出全部系列的值）
      dash="6 4"   —— 该折线画成虚线
    """
    left, right, top, bot = 42, 12, 14, 30
    x0, x1, y0, y1 = left, w - right, top, h - bot
    norm = []
    for s in series:
        op = s[3] if (len(s) > 3 and isinstance(s[3], dict)) else {}
        norm.append((s[0], list(s[1]), s[2], op))
    allv = [v for _, vals, _, _ in norm for v in vals if isinstance(v, (int, float))] or [0.0]
    vmin, vmax = _scale(min(allv), max(allv))
    def X(i): return x0 + (x1 - x0) * i / max(len(dates) - 1, 1)
    def Y(v): return y1 - (v - vmin) / (vmax - vmin) * (y1 - y0)
    payload = {"kind": "line", "n": len(dates), "x0": x0, "x1": x1, "top": y0, "bot": y1,
               "w": w, "h": h, "unit": unit, "days": days or dates,
               "series": [{"name": nm, "color": cl, "vals": vs} for nm, vs, cl, _ in norm]}
    dp = _html.escape(json.dumps(payload, ensure_ascii=False), quote=True)
    attrs = f'id="{sid}" class="dchart"' if sid else ""
    p = [f'<svg {attrs} data-payload="{dp}" viewBox="0 0 {w} {h}" width="100%" preserveAspectRatio="xMinYMin meet" style="display:block">']
    for g in range(4):
        gv = vmin + (vmax - vmin) * g / 3; gy = Y(gv)
        p.append(f'<line x1="{x0}" y1="{gy:.1f}" x2="{x1}" y2="{gy:.1f}" stroke="#ececec"/>')
        p.append(f'<text x="{x0-5}" y="{gy+3:.1f}" text-anchor="end" font-size="12" fill="#999">{gv:.0f}</text>')
    for name, vals, color, op in norm:
        dash = f''' stroke-dasharray="{op['dash']}"''' if op.get("dash") else ""
        # None = 缺测（能见度 x1_visibility 仅前 162h 有值）：该处断开折线，不画点、不标值
        segs, _cur = [], []
        for i, v in enumerate(vals):
            if isinstance(v, (int, float)):
                _cur.append((i, v))
            else:
                if _cur:
                    segs.append(_cur); _cur = []
        if _cur:
            segs.append(_cur)
        for seg in segs:
            pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in seg)
            if len(seg) > 1:
                p.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2"{dash}/>')
            p.append(f'<circle cx="{X(seg[0][0]):.1f}" cy="{Y(seg[0][1]):.1f}" r="2.6" fill="{color}"/>')
            if len(seg) == 1:
                continue
            for i, v in seg[1:]:
                p.append(f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="2.6" fill="{color}"/>')
        for i, v in enumerate(vals):
            if not isinstance(v, (int, float)):
                continue
            if op.get("labels", True):
                offset_y = -7 if Y(v) < (y0+y1)/2 else 12
                p.append(f'<text x="{X(i):.1f}" y="{Y(v)+offset_y:.1f}" text-anchor="middle" font-size="10" fill="{color}" font-weight="700">{v:.1f}</text>')
    for i, d in enumerate(dates):
        p.append(f'<text x="{X(i):.1f}" y="{h-9}" text-anchor="middle" font-size="11" fill="#888">{d[5:]}</text>')
    return "".join(p)

# ---------- 文案生成 ----------
def impact_bullets(daily, s, ph=0.0, hourly48=None):
    """作业影响与建议。每条前缀「要素小图标（色块＝该条自身的风险等级）＋加粗要素名」，
    图标等级按本条判据独立计算，不受风险卡口径牵连。
    阵风/温度用未来 48 小时窗口口径（同 h48_elements），不用 summary 全窗 14 天极值。"""
    out = []
    focus = [d for d in daily if d["rainfall"] >= 10]
    pmax = max((d["rainfall"] for d in daily), default=0)
    e = h48_elements(hourly48 or {})
    g48 = e["maxGust"] if e["maxGust"] is not None else s["maxGust"]
    w48 = e["maxWind"] if e["maxWind"] is not None else s["maxWind"]
    t48 = e["tmax"] if e["tmax"] is not None else s["maxTemp"]
    n48 = e["tmin"] if e["tmin"] is not None else s["minTemp"]
    aMax = e["appMax"] if e.get("appMax") is not None else s.get("maxApparent")
    aMin = e["appMin"] if e.get("appMin") is not None else s.get("minApparent")
    visMin = e.get("visMin")
    sf = (hourly48 or {}).get("snowfall") or []
    snow_pk = max(sf[:48]) if sf else 0.0
    if focus:
        tot = round(sum(d["rainfall"] for d in focus), 1)
        out.append(f"{eic('rain', lv_rain(ph), size='xs')}<b>降水泥泞</b>：连续降雨累计 {tot}mm，井场 / 管沟道路泥泞、设备基础易沉降，加强排水与铺垫，重型车辆限行。")
    if ph >= RAIN_H["torrent"]:
        out.append(f"{eic('rain','danger', size='xs')}<b>短时大暴雨</b>：最大小时降水 {ph}mm/h（>15mm/h），地面积水快速上涨、管沟与井场排水瞬时超负荷，低洼段设备应提前撤离或垫高，暂停涉水作业。")
    elif ph >= RAIN_H["storm"]:
        out.append(f"{eic('rain','danger', size='xs')}<b>短时暴雨</b>：最大小时降水 {ph}mm/h（>6mm/h），井场局部积水、设备基础可能被冲刷，加强排水、电缆接头包覆防水，重型车辆避开低洼路段。")
    elif ph >= RAIN_H["heavy"]:
        out.append(f"{eic('rain','warn', size='xs')}<b>短时大雨</b>：最大小时降水 {ph}mm/h（>3mm/h），降水强度明显、道路湿滑泥泞，作业面注意防滑防淹，排水沟提前疏通。")
    if g48 >= 17.2 or (w48 or 0) >= 10.8:
        # 2026-10-17 新口径：阵风八级(17.2)/均风六级(10.8) 起才提示；
        # 阵风十级(24.5) 或均风八级(17.2) 才要求停工避风。
        _stop = max(JW.grade_gust(g48), JW.grade_wind(w48 or 0)) >= 3
        _w = f"阵风最大 {g48}m/s（{gust_lbl(g48)}）"
        if w48:
            _w += f"、均风最大 {w48}m/s（{wind_lbl(w48)}）"
        out.append(f"{eic('wind', 'danger' if _stop else 'warn', size='xs')}<b>大风 / 阵风</b>：{_w}，"
                   f"{'吊装与高处作业需停工避风，加固井架、棚架与临时设施。' if _stop else '高处作业注意系挂，零星吊装避开阵风时段。'}")
    # 舒适度由体感温度 UTCI 承担（plain 温度只展示）；冷/热双向
    if aMax is not None and JW.grade_utci(aMax)[0] >= 3:
        out.append(f"{eic('heat','danger', size='xs')}<b>高温 / 体感酷热</b>：体感最高温 {aMax}°C（{JW.UTCI_HOT[JW.grade_utci(aMax)[0]]}），防暑降温、避开正午露天作业、设备过热防护与电池管理。")
    elif aMin is not None and JW.grade_utci(aMin)[0] >= 2:
        out.append(f"{eic('snow','warn', size='xs')}<b>低温 / 体感严寒</b>：体感最低温 {aMin}°C（{JW.UTCI_COLD[JW.grade_utci(aMin)[0]]}），人员保暖、道路与设备防滑、备用电源。")
    if snow_pk >= 0.1:
        slv = JW.grade_snow(snow_pk)
        out.append(f"{eic('snow', 'danger' if slv >= 3 else 'warn', size='xs')}<b>降雪 / 积雪</b>：最大小时降雪 {snow_pk}mm/h（{JW.SNOW_ALERT[slv]}），积雪与道路结冰风险，加强除雪防滑、设备覆雪防护。")
    if visMin is not None and visMin < 1000:
        vl = JW.grade_vis(visMin)
        out.append(f"{eic('fog', 'danger' if vl >= 3 else 'warn', size='xs')}<b>能见度</b>：最低能见度 {int(visMin)}m（{JW.VIS_ALERT[vl]}），谨慎行车、必要时封路、夜间作业加强照明。")
    if pmax >= 25:
        out.append(f"{eic('fog','warn', size='xs')}<b>行车</b>：降雨集中（单日最大 {pmax}mm），山区道路湿滑、能见度下降，谨慎行车、必要时封路。")
    if not out:
        out.append(f"{eic('rain','ok', size='xs')}<b>整体适宜</b>：天气平稳，可按计划推进各项作业；山区小气候仍建议以现场实测为准。")
    return out

def card_icon(title):
    """风险卡标题 → 要素图标种类（图形＝要素，底色＝卡上的风险等级）。"""
    if "大风" in title:                      return "wind"
    if "降水" in title or "泥泞" in title:    return "rain"
    if "高温" in title:                      return "heat"
    if "结冰" in title:                      return "snow"
    if "气温" in title:                      return "temp"
    return "fog"                             # 行车 / 能见度

def risk_cards(daily, s, ph=0.0, hourly48=None):
    """风险卡：风/温用未来 48 小时窗口口径（同 h48_elements），不用全窗 14 天极值。"""
    pmax = max((d["rainfall"] for d in daily), default=0)
    e = h48_elements(hourly48 or {})
    g48 = e["maxGust"] if e["maxGust"] is not None else s["maxGust"]
    w48 = e["maxWind"] if e["maxWind"] is not None else s["maxWind"]
    t48 = e["tmax"] if e["tmax"] is not None else s["maxTemp"]
    n48 = e["tmin"] if e["tmin"] is not None else s["minTemp"]
    cards = []
    # 风卡（2026-10-17 新口径）：阵风十级(24.5)或均风八级(17.2) 预警；
    # 阵风八级(17.2)或均风六级(10.8) 注意。
    _gl, _wl = JW.grade_gust(g48), JW.grade_wind(w48 or 0)
    if _gl >= 3 or _wl >= 3:
        cards.append(("danger", "大风 / 阵风", "预警", f"阵风最大 {g48}m/s（{gust_lbl(g48)}）、均风最大 {w48}m/s，吊装 / 高处作业停工避风。"))
    elif _gl >= 2 or _wl >= 2:
        cards.append(("warn", "大风 / 阵风", "注意", f"阵风最大 {g48}m/s（{gust_lbl(g48)}）、均风最大 {w48}m/s，高处作业系挂、避开阵风时段。"))
    else:
        cards.append(("ok", "大风 / 阵风", "安全", f"阵风最大 {g48}m/s（{gust_lbl(g48)}）、均风最大 {w48}m/s，未达八级大风，无停工风险。"))
    # 降水卡：日累计与小时级短时降水双判据（>3 大雨 / >6 暴雨 / >15 大暴雨，仅 48h 口径），
    # 分级与物探看板 build_dashboard.py 的降水卡片保持完全一致。
    if ph >= RAIN_H["torrent"] or pmax >= 50:
        cards.append(("danger", "降水 / 泥泞", "预警",
            f"单日最大降水 {pmax}mm" + (f"、最大小时降水 {ph}mm/h（{rain_hour_label(ph)}）" if ph >= RAIN_H["heavy"] else "")
            + "，井场泥泞、积水风险高。"))
    elif ph >= RAIN_H["storm"] or pmax >= 25:
        what = (f"最大小时降水 {ph}mm/h（短时暴雨，>6mm/h）" if ph >= RAIN_H["storm"]
                else f"单日最大降水 {pmax}mm（大雨）")
        cards.append(("warn", "降水 / 泥泞", "注意",
            what + "，井场局部积水、排水压力骤增，设备防雨防潮、道路湿滑降速。"))
    elif ph >= RAIN_H["heavy"]:
        cards.append(("warn", "短时大雨 / 泥泞", "注意",
            f"48 小时日累计降雨不大，但出现 {ph}mm/h 的短时大雨（>3mm/h），短时积水与便道湿滑明显。低洼与管沟段注意排水、车辆降速，设备防雨防潮。"))
    else:
        cards.append(("ok", "降水 / 泥泞", "安全",
            f"48 小时无明显短时强降水，最大小时降水 {ph}mm/h，单日最大 {pmax}mm，无明显泥泞风险。"))
    # 降雪卡（48h 最大小时降雪，mm/h）：与物探看板降雪分级一致
    sf = (hourly48 or {}).get("snowfall") or []
    snow_pk = max(sf[:48]) if sf else 0.0
    slv = JW.grade_snow(snow_pk)
    if slv >= 3:
        cards.append(("danger", "降雪 / 积雪", "预警", f"最大小时降雪 {snow_pk}mm/h（{JW.SNOW_ALERT[slv]}），积雪 / 道路结冰、设备覆雪，加强除雪与防滑。"))
    elif slv >= 1:
        cards.append(("warn", "降雪 / 积雪", "注意", f"最大小时降雪 {snow_pk}mm/h（{JW.SNOW_ALERT[slv]}），注意积雪与道路防滑。"))
    # 舒适度卡：plain 温度只展示，舒适度由体感温度 UTCI 判定（冷/热双向）
    aMax = e["appMax"] if e.get("appMax") is not None else s.get("maxApparent")
    aMin = e["appMin"] if e.get("appMin") is not None else s.get("minApparent")
    ulv = 0
    if aMax is not None: ulv = max(ulv, JW.grade_utci(aMax)[0])
    if aMin is not None: ulv = max(ulv, JW.grade_utci(aMin)[0])
    if ulv >= 3:
        if aMax is not None and JW.grade_utci(aMax)[0] >= 3:
            cards.append(("danger", "高温 / 体感酷热", "预警", f"体感最高温 {aMax}°C（{JW.UTCI_HOT[JW.grade_utci(aMax)[0]]}），防暑降温、避开正午露天作业、设备过热防护。"))
        else:
            cards.append(("danger", "低温 / 体感酷寒", "预警", f"体感最低温 {aMin}°C（{JW.UTCI_COLD[JW.grade_utci(aMin)[0]]}），人员保暖、设备与道路防滑防冻、备用电源。"))
    elif ulv >= 2:
        if aMax is not None and JW.grade_utci(aMax)[0] >= 2:
            cards.append(("warn", "体感偏热", "注意", f"体感最高温 {aMax}°C，体感偏热，注意防暑与通风。"))
        else:
            cards.append(("warn", "低温 / 体感严寒", "注意", f"体感最低温 {aMin}°C，体感严寒，人员保暖、设备防冻。"))
    else:
        rng = f"体感 {aMin}~{aMax}°C，" if (aMin is not None and aMax is not None) else ""
        cards.append(("ok", "气温 / 体感", "适宜", f"气温 {n48}~{t48}°C，{rng}体感适宜。"))
    # 能见度卡（48h 最低能见度，m）
    visMin = e.get("visMin")
    if visMin is not None and visMin < 1000:
        vl = JW.grade_vis(visMin)
        cards.append(("danger" if vl >= 3 else "warn", "能见度", "注意",
            f"最低能见度 {int(visMin)}m（{JW.VIS_ALERT[vl]}），谨慎行车、必要时封路、夜间作业加强照明与警示。"))
    else:
        cards.append(("ok", "能见度", "提示", "能见度良好，常规行车注意。"))
    # 行车 / 道路卡（降雨集中导致道路湿滑）
    if pmax >= 25:
        cards.append(("warn", "行车 / 道路", "注意", "降雨集中，山区道路湿滑、便道泥泞，谨慎行车、必要时封路。"))
    else:
        cards.append(("ok", "行车 / 道路", "提示", "道路条件良好，常规行车注意。"))
    return cards

# ---------- 作业天气影响与建议（与物探看板同结构：单节、每要素一卡，风险＋建议合并） ----------
def impact_cards_merged(daily, s, ph=0.0, hourly48=None):
    """「作业天气影响与建议」单节内容：每要素一张卡，风险等级（徽标）＋风险描述＋处置建议合并。
    风/温用未来 48 小时窗口口径（同 h48_elements，不用全窗 14 天极值）。
    **气温卡纳入体感温度（UTCI 冷热双向）**——与物探 48h 横幅判据一致。
    返回 [(level, title, badge_text, desc_html, icon), ...]，level ∈ {danger, warn, ok}。"""
    e = h48_elements(hourly48 or {})
    g48 = e["maxGust"] if e["maxGust"] is not None else s["maxGust"]
    w48 = e["maxWind"] if e["maxWind"] is not None else s["maxWind"]
    t48 = e["tmax"] if e["tmax"] is not None else s["maxTemp"]
    n48 = e["tmin"] if e["tmin"] is not None else s["minTemp"]
    aMax = e["appMax"] if e.get("appMax") is not None else s.get("maxApparent")
    aMin = e["appMin"] if e.get("appMin") is not None else s.get("minApparent")
    visMin = e.get("visMin")
    pmax = max((d["rainfall"] for d in daily), default=0)
    sf = (hourly48 or {}).get("snowfall") or []
    snow_pk = max(sf[:48]) if sf else 0.0
    focus = [d for d in daily if d["rainfall"] >= 10]
    tot = round(sum(d["rainfall"] for d in focus), 1)
    cards = []

    # 降水 / 泥泞
    if ph >= RAIN_H["torrent"] or pmax >= 50:
        cards.append(("danger", "降水 / 短时强降水", "预警",
            f"连续强降雨累计 {tot}mm，单日最大 {pmax}mm（暴雨）"
            + (f"、最大小时降水 {ph}mm/h（{rain_hour_label(ph)}）" if ph >= RAIN_H["heavy"] else "")
            + "。井场/管沟泥泞、积水风险高，低洼与河谷段设备应提前撤离或垫高，暂停涉水作业，雨停后待便道充分干燥再进场。", "rain"))
    elif ph >= RAIN_H["storm"] or pmax >= 25:
        what = (f"最大小时降水 {ph}mm/h（短时暴雨，>6mm/h）" if ph >= RAIN_H["storm"]
                else f"单日最大降水 {pmax}mm（大雨）")
        cards.append(("warn", "降水 / 短时强降水", "注意",
            f"{what}，井场局部积水、排水压力骤增，设备防雨防潮、道路湿滑降速；推迟涉水与陡坡段施工，电缆接头包覆防水。", "rain"))
    elif ph >= RAIN_H["heavy"]:
        cards.append(("warn", "短时大雨 / 泥泞", "注意",
            f"48 小时日累计降雨不大，但出现 {ph}mm/h 的短时大雨（>3mm/h），短时积水与便道湿滑明显；低洼与管沟段注意排水、车辆降速，设备防雨防潮。", "rain"))
    else:
        cards.append(("ok", "降水 / 泥泞", "安全",
            f"未来 48 小时无连续中雨以上降雨，最大小时降水 {ph}mm/h，以间歇小雨为主，常规防雨即可。", "rain"))

    # 大风 / 阵风（2026-10-17 新口径：阵风十级(24.5)/均风八级(17.2) 预警；阵风八级(17.2)/均风六级(10.8) 注意）
    _gl, _wl = JW.grade_gust(g48), JW.grade_wind(w48 or 0)
    if _gl >= 3 or _wl >= 3:
        cards.append(("danger", "大风 / 阵风", "预警",
            f"阵风最大 {g48}m/s（{gust_lbl(g48)}）、均风最大 {w48}m/s，吊装与高处作业需停工避风，加固井架、棚架与临时设施。", "wind"))
    elif _gl >= 2 or _wl >= 2:
        cards.append(("warn", "大风 / 阵风", "注意",
            f"阵风最大 {g48}m/s（{gust_lbl(g48)}）、均风最大 {w48}m/s，高处作业注意系挂，零星吊装避开阵风时段。", "wind"))
    else:
        cards.append(("ok", "大风 / 阵风", "安全",
            f"最大阵风 {g48}m/s（{gust_lbl(g48)}）、均风 {w48}m/s，未达八级大风，不影响吊装与高处作业安全。", "wind"))

    # 气温 / 体感（UTCI 冷热双向：体感温度纳入判据）
    ulv = 0
    if aMax is not None: ulv = max(ulv, JW.grade_utci(aMax)[0])
    if aMin is not None: ulv = max(ulv, JW.grade_utci(aMin)[0])
    if aMax is not None and JW.grade_utci(aMax)[0] >= 3:
        cards.append(("danger", "高温 / 体感酷热", "预警",
            f"体感最高温 {aMax}°C（{JW.UTCI_HOT[JW.grade_utci(aMax)[0]]}），防暑降温、避开正午露天作业、设备过热防护与电池管理。", "heat"))
    elif aMin is not None and JW.grade_utci(aMin)[0] >= 2:
        cards.append(("warn", "低温 / 体感严寒", "注意",
            f"体感最低温 {aMin}°C（{JW.UTCI_COLD[JW.grade_utci(aMin)[0]]}），人员保暖、道路与设备防滑防冻、备用电源。", "snow"))
    elif aMax is not None and JW.grade_utci(aMax)[0] >= 2:
        cards.append(("warn", "体感偏热", "注意",
            f"体感最高温 {aMax}°C，体感偏热，注意防暑与通风。", "heat"))
    else:
        rng = f"体感 {aMin}~{aMax}°C，" if (aMin is not None and aMax is not None) else ""
        cards.append(("ok", "气温 / 体感", "适宜",
            f"气温 {n48}~{t48}°C，{rng}体感适宜；早晚偏凉注意人员保暖与仪器低温启动。", "temp"))

    # 降雪 / 积雪（仅在有降雪时单列；分级与物探看板一致）
    slv = JW.grade_snow(snow_pk)
    if slv >= 3:
        cards.append(("danger", "降雪 / 积雪", "预警",
            f"最大小时降雪 {snow_pk}mm/h（{JW.SNOW_ALERT[slv]}），积雪与道路结冰风险，加强除雪防滑、设备覆雪防护。", "snow"))
    elif slv >= 1:
        cards.append(("warn", "降雪 / 积雪", "注意",
            f"最大小时降雪 {snow_pk}mm/h（{JW.SNOW_ALERT[slv]}），注意积雪与道路防滑。", "snow"))

    # 能见度 / 行车（降雨集中导致道路湿滑 ＋ 低能见度，合并为一卡）
    if visMin is not None and visMin < 1000:
        vl = JW.grade_vis(visMin)
        _road = "降雨集中、山区道路湿滑，" if pmax >= 25 else ""
        cards.append(("danger" if vl >= 3 else "warn", "低能见度 / 行车", "注意",
            f"{_road}最低能见度 {int(visMin)}m（{JW.VIS_ALERT[vl]}），谨慎行车、必要时封路、夜间作业加强照明与警示。", "fog"))
    elif pmax >= 25:
        cards.append(("warn", "行车 / 道路", "注意",
            "降雨集中，山区道路湿滑、便道泥泞，谨慎行车、必要时封路。", "fog"))
    else:
        cards.append(("ok", "低能见度 / 行车", "提示",
            "能见度良好、道路条件正常，常规行车注意；雨后山区多雾、便道湿滑时越野车与设备转运需降速保持车距。", "fog"))
    return cards

def impact_cards_html(daily, s, ph, hourly48):
    """渲染「作业天气影响与建议」单节 HTML（与物探同结构：每要素一张 .imp 卡）。"""
    return "".join(
        f'<div class="imp {c[0]}"><div class="h">'
        + (eic(c[4], c[0], "s") if c[4] else "")
        + f'{c[1]}<span class="badge {c[0]}">{c[2]}</span></div><p>{c[3]}</p></div>'
        for c in impact_cards_merged(daily, s, ph, hourly48))

# ---------- 单点 HTML ----------
CSS = """
* {box-sizing: border-box; margin:0; padding:0;}
body {font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
  background:#f4f6f8; color:#1f2933; line-height:1.55; padding:14px; max-width:720px; margin:0 auto;}
body.sev0 {--sev:#2E8B57;} body.sev1 {--sev:#E0A92C;} body.sev2 {--sev:#E0822C;} body.sev3 {--sev:#C0392B;}
.topbar {display:flex; justify-content:space-between; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:6px; font-size:12px; color:#5b6b7b;}
.topbar a {color:#2E7DA8; text-decoration:none; font-weight:700;}
.topbar-l{display:flex;gap:10px;align-items:center;flex:1 1 auto;min-width:0;}
.topbar-r{display:flex;gap:10px;align-items:center;flex:0 0 auto;}
.topbar .backlink{display:inline-block;margin-bottom:6px;font-size:13px;font-weight:600;color:#1F7A6B;text-decoration:none;border:1px solid #1F7A6B;border-radius:8px;padding:3px 10px;cursor:pointer;transition:background .15s,color .15s;}
.topbar .backlink:hover{background:#1F7A6B;color:#fff;}
.unit{font-size:12px;color:#7b8a99;margin:0 0 2px;}
.unit:empty{display:none;}
.brand{font-size:12.5px;font-weight:700;color:#1f3a4d;text-decoration:none;border:1px solid #cdd6df;border-radius:7px;padding:2px 9px;background:#fff;opacity:.9;transition:background .15s,border-color .15s;}
.brand:hover{opacity:1;background:#eef3f7;border-color:#2E7DA8;}
.topbar .extlink{display:inline-block;background:#2e6da4;color:#fff;padding:4px 10px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:700;}
.topbar .extlink:hover{background:#245f82;transform:translateY(-1px);}
h1 {font-size:19px; margin:2px 0 2px;}
.sub {font-size:12px; color:#7b8a99; margin-bottom:10px;}
.alert {background:var(--sev); color:#fff; border-radius:14px; padding:13px 15px; margin-bottom:12px; box-shadow:0 2px 8px rgba(0,0,0,.08);}
.alert .t {font-size:16px; font-weight:800; display:flex; align-items:center; gap:8px;}
.alert .d {font-size:13px; margin-top:6px; opacity:.97; line-height:1.55;}
/* 2026-10-17 用户口径：横幅正文由「一段散文」改为**逐要素清单**（与物探看板同款）——
   一行一个要素，只列 48h 窗口内最高级别那一条（要素 / 等级名 / 数值）；远期另起一行、米黄底区分。
   未达阈值的要素不占行（不写「未发生」这类否定式）。 */
.alert .ailist {margin-top:9px; display:flex; flex-direction:column; gap:5px;}
.alert .ai {display:flex; align-items:baseline; gap:8px; background:rgba(255,255,255,.16);
  border-radius:8px; padding:6px 10px;}
.alert .ai .eic {margin-right:1px;}  /* 逐要素图标：底色＝该要素等级（绿/橙/红） */
.alert .ai-k {font-weight:800; flex:0 0 auto;}
.alert .ai-lv {font-weight:900; font-size:11.5px; background:rgba(0,0,0,.22);
  padding:1px 7px; border-radius:7px; white-space:nowrap;}
.alert .ai-lv.lv3 {background:#C0392B;} .alert .ai-lv.lv2 {background:#E0822C;}
.alert .ai-lv.lv1 {background:#E0822C;}  /* lv1~2 同属「注意」橙，与影响卡一致 */
.alert .ai-v {font-weight:900; font-variant-numeric:tabular-nums; margin-left:auto;
  flex:0 0 auto; white-space:nowrap;}
.alert .ai-v em {font-style:normal; font-size:10.5px; font-weight:700; opacity:.85; margin-left:2px;}
.alert .ai-note {font-size:12.5px; line-height:1.5; background:rgba(255,255,255,.16);
  border-radius:8px; padding:6px 10px;}
.alert .far {margin-top:9px; background:#FFF7E6; border-radius:9px; padding:7px 11px;
  color:#7A4B00; font-size:12px; line-height:1.5;}
.alert .far b {font-size:11.5px; color:#B36B00; margin-right:5px;}
.alert .far.quiet {background:rgba(255,255,255,.16); color:#fff;}
.alert .far.quiet b {color:#fff; opacity:.9;}
.dot {width:11px; height:11px; border-radius:50%; background:#fff; box-shadow:0 0 0 3px rgba(255,255,255,.35);}
/* 关键指标六格（2026-10-17 与物探 #statsBox 同款：2 列 × 3 行、每格多行「要素/数值/单位」；
   minmax(0,1fr) + min-width:0 防窄屏被内容撑破） */
.stats {display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:9px; margin-bottom:14px;}
.stat {background:#FBFAF7; border:1px solid #eef1f4; border-radius:10px; padding:9px 11px; min-width:0; overflow:hidden;}
.stat .k {font-size:12px; font-weight:600; color:#7b8a99; display:flex; align-items:center; gap:5px;}
.stat .vs {margin-top:5px; display:flex; flex-direction:column; gap:4px; min-width:0;}
.stat .vr {display:flex; flex-wrap:wrap; align-items:baseline; gap:2px 4px; font-variant-numeric:tabular-nums; min-width:0;}
.stat .vr em {font-style:normal; font-size:11.5px; font-weight:700; color:#7b8a99; min-width:25px; flex:0 0 auto;}
.stat .vr b {font-size:17px; font-weight:800; color:#1f2933; line-height:1.15; flex:0 0 auto;}
.stat .vr i {font-style:normal; font-size:11px; color:#7b8a99; flex:0 0 auto;}
.card {background:#fff; border-radius:12px; padding:12px 13px; margin-bottom:12px; box-shadow:0 1px 4px rgba(0,0,0,.06);}
.card h2 {font-size:14px; margin-bottom:8px; display:flex; align-items:center; gap:7px;}
.chart-h {font-size:12px; font-weight:700; color:#46556a; margin:10px 0 2px;}
.legend {font-size:11px; color:#7b8a99; margin:2px 0 6px;}
.legend i {display:inline-block; width:10px; height:3px; vertical-align:middle; margin:0 3px 0 8px;}
/* 页头背景图容器 .heroarea 的样式由 hero_css() 在「有图时」注入，此处不重复定义；
   气象要素小图标：色块＝风险等级（绿 ok / 橙 warn / 红 danger），图形＝要素本身；
   .plain＝不带风险属性（图表图例用），避免与风险等级色混淆 */
.eic{display:inline-flex;align-items:center;justify-content:center;flex:0 0 auto;vertical-align:-4px;
  width:19px;height:19px;border-radius:5px;color:#fff;margin-right:5px;}
.eic svg{width:13px;height:13px;display:block;}
.eic.s{width:16px;height:16px;border-radius:4px;margin-right:4px;vertical-align:-3px;}
.eic.s svg{width:11px;height:11px;}
/* xs：作业影响建议专用（2026-10-17 关键指标六格改用默认 19px）。行内空间紧，图标必须够小才不把文字挤断行 */
.eic.xs{width:13px;height:13px;border-radius:3.5px;margin-right:3px;vertical-align:-2.5px;}
.eic.xs svg{width:9px;height:9px;}
.eic.ok{background:#2E8B57;} .eic.warn{background:#E0822C;} .eic.danger{background:#C0392B;} .eic.plain{background:#98A1A6;}
/* flex 容器（卡片 h2）自带 gap，图标不再另加外边距，避免间距翻倍 */
.card h2 .eic, .legend .eic{margin-right:0;}
/* 列表项 / 读数行不是 flex，图标靠外边距与后文拉开一点，避免贴字 */
ul.adv li .eic, .hval .eic{margin-right:3px;}
.rc {border-left:4px solid #ccc; border-radius:8px; padding:8px 10px; margin-bottom:8px; background:#fafbfc;}
.rc.danger {border-color:#C0392B; background:#fdf3f1;} .rc.warn {border-color:#E0822C; background:#fef6ee;} .rc.ok {border-color:#2E8B57; background:#f1f8f4;}
.rc .rt {font-weight:800; font-size:13px;} .rc .rb {font-size:12px; color:#55636f; margin-top:2px;}
.rc .tag {float:right; font-size:11px; font-weight:700; padding:1px 7px; border-radius:8px; color:#fff;}
.danger .tag{background:#C0392B;} .warn .tag{background:#E0822C;} .ok .tag{background:#2E8B57;}
ul.adv {margin:4px 0 0 2px; padding-left:0; list-style:none;}
ul.adv li {font-size:13px; color:#33414f; padding:5px 0; border-bottom:1px dashed #eef1f4;}
ul.adv li:last-child{border-bottom:none;}
/* 作业天气影响与建议（2026-10-17：与物探看板同结构——单节、每要素一张卡，
   风险等级（徽标）＋风险描述＋处置建议合并在同一张卡内；气温卡纳入体感温度） */
.impbox {margin-top:8px;}
.imp {border-left:4px solid #2E8B57; border-radius:0 10px 10px 0; padding:9px 12px; margin-bottom:9px; background:#FBFAF7;}
.imp.warn {border-left-color:#E0822C;} .imp.danger {border-left-color:#C0392B;}
.imp .h {font-weight:700; font-size:14px; display:flex; align-items:center; gap:7px;}
.badge {font-size:11px; padding:1px 8px; border-radius:999px; font-weight:700; color:#fff; margin-left:auto; white-space:nowrap;}
.badge.ok {background:#2E8B57;} .badge.warn {background:#E0822C;} .badge.danger {background:#C0392B;}
.imp p {margin:5px 0 0; font-size:13.5px; color:#3A4146; line-height:1.55;}
.imp .h .eic {flex:0 0 auto;}
.hval {background:#fff; border:1px solid #eef1f4; border-radius:10px; padding:9px 11px; font-size:12.5px; color:#33414f; box-shadow:0 1px 4px rgba(0,0,0,.06); margin:0 0 9px; line-height:2.0;}  /* 2026-10-17 移到 48h 图表上方，改留底边距 */
/* 日期·时间：粗体高亮（全页唯一时间读数） */
.hval .t {font-weight:900; font-size:14.5px; color:#C0392B; margin-right:9px; font-variant-numeric:tabular-nums; letter-spacing:.2px;}
/* 要素值：深色粗体字 + 同色系浅底 pill（底色浅、字色深，文字永不被盖住） */
.hval b {font-weight:900; font-size:12.5px; display:inline-block; line-height:1.5; padding:1.5px 8px; border-radius:6px;}
.hval b.tv {color:#8A4B00; background:#FBEAD3;}
.hval b.pv {color:#0D47A1; background:#D8E9FA;}
.hval b.wv {color:#0F5B4C; background:#D9EFE7;}
.hval b.gv {color:#8A2A0E; background:#FBE0D6;}
/* 已选日期：行内标签（不单独占一行），内联在「未来 两周逐日天气」标题行末尾 */
#dayInfo:empty {display:none;}   /* 未选日期时完全不占位（连 h2 的 flex gap 也不占） */
.day-chip {display:inline-block; font-weight:900; font-size:12.5px; color:#7a3b12; background:#FFF3D6;
  border:1px solid #E6C877; border-radius:8px; padding:2px 9px; font-variant-numeric:tabular-nums;}
.sub b {font-weight:900; color:#1f2933;}
.foot {font-size:11px; color:#9aa7b4; margin-top:8px; text-align:center;}
.tabs {display:flex; gap:6px; margin-bottom:12px; position:sticky; top:0; z-index:5; padding:6px 0; background:#f4f6f8;}
.tab {flex:1; padding:9px 0; border:none; border-radius:10px; background:#fff; color:#46556a; font-size:13px; font-weight:700; cursor:pointer; box-shadow:0 1px 4px rgba(0,0,0,.06); transition:.15s;}
.tab:hover {color:#2E7DA8;}
.tab.active {background:var(--sev); color:#fff;}
.panel {display:block;}
"""

def chart_js(hourly):
    n = len(hourly["time"])
    return (
        '<script>\n'
        '(function(){\n'
        '  var NS="http://www.w3.org/2000/svg";\n'
        '  var CH={left:50,right:706,top:44,bot:235,w:760,h:340,\n'
        '    times:' + json.dumps(hourly["time"], ensure_ascii=False) + ',\n'
        '    temp:' + json.dumps(hourly["temperature_2m"]) + ',\n'
        '    rainfall:' + json.dumps(hourly["rainfall"]) + ',\n'
        '    ptype:' + json.dumps(hourly.get("ptype") or [0] * n) + ',\n'
        '    wind:' + json.dumps(hourly["wind_speed_10m"]) + ',\n'
        '    gust:' + json.dumps(hourly["wind_gusts_10m"]) + ',\n'
        '    apparent:' + json.dumps(hourly["apparent_temperature"]) + '};\n'
        # ⚠️ 载荷键必须叫 rainfall：下面 JS 全程引用 CH.rainfall（曾误写成 precip 键，
        #    导致 CH.rainfall 为 undefined → 「无法读取 concat」TypeError → 48h 图表整块空白）

        '  var n=CH.times.length;\n'
        '  var svg=document.getElementById("hchart");\n'
        '  function el(t,a){var e=document.createElementNS(NS,t);for(var k in a)e.setAttribute(k,a[k]);return e;}\n'
        '  function txt(x,y,s,anc,col,sz){var e=el("text",{x:x,y:y,"text-anchor":anc||"end","font-size":sz||9,fill:col||"#9aa"});e.textContent=s;return e;}\n'
        '  var PT_TXT={0:"",1:"降雨",2:"降雪",3:"雨夹雪"};\n'
        '  // 气象要素小图标（与物探看板同一套 EIC，色块＝风险等级，图形＝要素）\n'
        '  var EIC_PATH={rain:\'<path d="M20 16.6A5 5 0 0 0 18 7h-1.3A8 8 0 1 0 4 15.3"/><path d="M8 13.2v7.6M12 15.2v7.6M16 13.2v7.6"/>\','
        'snow:\'<path d="M12 3.2v17.6M4.2 7.8l15.6 8.4M19.8 7.8 4.2 16.2"/><path d="m12 7-2.2-2.3M12 7l2.2-2.3M12 17l-2.2 2.3M12 17l2.2 2.3"/>\','
        'wind:\'<path d="M3.5 9h10a3 3 0 1 0-3-3"/><path d="M4 13.5h11.5a3 3 0 1 1-3 3"/><path d="M4.2 18h5"/>\','
        'temp:\'<path d="M14 14.8V4.2a2.2 2.2 0 0 0-4.4 0v10.6a4.4 4.4 0 1 0 4.4 0z"/>\','
        'heat:\'<circle cx="12" cy="12" r="4"/><path d="M12 2.6v2.3M12 19.1v2.3M2.6 12h2.3M19.1 12h2.3M5.4 5.4l1.7 1.7M16.9 16.9l1.7 1.7M18.6 5.4l-1.7 1.7M7.1 16.9l-1.7 1.7"/>\','
        'fog:\'<path d="M4 8.4h16M6.6 12h10.8M4 15.6h16"/>\'};\n'
        '  function eic(kind,lvl){var p=EIC_PATH[kind];if(!p)return "";'
        'var L=(lvl==="ok"||lvl==="warn"||lvl==="danger")?lvl:"plain";'
        'return \'<span class="eic \'+L+\' s" aria-hidden="true">\''
        '+\'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" '
        'stroke-linecap="round" stroke-linejoin="round">\'+p+\'</svg></span>\';}\n'
        '  function lvR(v){return v>=5?"danger":(v>=2?"warn":"ok");}\n'
        '  function lvG(v){return v>=24.5?"danger":(v>=17.2?"warn":"ok");}\n'

        '  var PT_FILL={1:"#2E86DE",2:"#5DD6E8",3:"#B07CD6"}; var PT_FB="#9DB4C8";\n'
        '  var tMax=Math.max.apply(null,CH.temp), tMin=Math.min.apply(null,CH.temp);\n'
        '  var tLo=Math.min(tMin,0)-2, tHi=tMax+2;\n'
        '  var wMax=Math.max.apply(null,CH.wind.concat(CH.gust).concat([1]));\n'
        '  var wHi=wMax*1.15;\n'
        '  var pMax=Math.max.apply(null,CH.rainfall.concat([0.1]));\n'
        '  function x(i){return CH.left+(i/(n-1))*(CH.right-CH.left);}\n'
        '  function yT(v){return CH.bot-(v-tLo)/(tHi-tLo)*(CH.bot-CH.top);}\n'
        '  function yW(v){return CH.bot-(v/wHi)*(CH.bot-CH.top);}\n'
        '  function yP(v){return CH.bot-(v/pMax)*(CH.bot-CH.top)*0.96;}\n'
        '  // 图例：横排放底部\n'
        '  var lg=CH.left+10, ly2=CH.bot+28;\n'
        '  svg.appendChild(el("line",{x1:lg,y1:ly2,x2:lg+28,y2:ly2,stroke:"#E0822C","stroke-width":3}));\n'
'  svg.appendChild(txt(lg+34,ly2+4,"气温 °C","start","#E0822C",12));\n'
'  svg.appendChild(el("line",{x1:lg+100,y1:ly2,x2:lg+128,y2:ly2,stroke:"#0FA87A","stroke-width":2.5}));\n'
'  svg.appendChild(txt(lg+134,ly2+4,"均风 m/s","start","#0FA87A",12));\n'
'  svg.appendChild(el("line",{x1:lg+220,y1:ly2,x2:lg+248,y2:ly2,stroke:"#D84315","stroke-width":2.5,"stroke-dasharray":"7 3"}));\n'
'  svg.appendChild(txt(lg+254,ly2+4,"阵风 m/s","start","#D84315",12));\n'
'  svg.appendChild(el("line",{x1:lg+338,y1:ly2,x2:lg+366,y2:ly2,stroke:"#8E44AD","stroke-width":1.8,"stroke-dasharray":"6 4"}));\n'
'  svg.appendChild(txt(lg+372,ly2+4,"体感 °C","start","#8E44AD",12));\n'
        '  // 网格线\n'
        '  for(var g=0;g<=4;g++){\n'
        '    var tv=tLo+(tHi-tLo)*g/4, yv=yT(tv);\n'
        '    svg.appendChild(el("line",{x1:CH.left,y1:yv,x2:CH.right,y2:yv,stroke:"#eee"}));\n'
        '    svg.appendChild(txt(CH.left-5,yv+3,tv.toFixed(0),"end","#c06",12));\n'
        '    var wv=wHi*g/4;\n'
        '    svg.appendChild(txt(CH.right+5,yv+3,wv.toFixed(0),"start","#8a5cbf",12));\n'
        '  }\n'
        '  // 左右轴域标签\n'
        '  svg.appendChild(txt(CH.left+5,CH.top+18,"气温 °C","start","#E0822C",12));\n'
        '  svg.appendChild(txt(CH.right-5,CH.top+18,"风 m/s","end","#0FA87A",12));\n'
        '  // 中间虚线分隔\n'
        '  var mid=(CH.left+CH.right)/2;\n'
        '  svg.appendChild(el("line",{x1:mid,y1:CH.top,x2:mid,y2:CH.bot,stroke:"#ddd","stroke-width":1,"stroke-dasharray":"3 3"}));\n'
        '  // 降水柱\n'
        '  var bw=(CH.right-CH.left)/n*0.55;\n'
        '  for(var i=0;i<n;i++){ if(CH.rainfall[i]>0.05 || CH.ptype[i]){var bx=x(i)-bw/2, bh=Math.max(CH.bot-yP(CH.rainfall[i]),3); var pcol=(PT_FILL[CH.ptype[i]]||PT_FB); svg.appendChild(el("rect",{x:bx,y:CH.bot-bh,width:bw,height:bh,fill:pcol,rx:1}));} }\n'
        '  // 小时级短时降水阈值线（大雨 3 / 暴雨 6 / 大暴雨 15 mm/h，与物探看板 RAIN_H 一致）\n'
        '  var PTH=[{v:3,c:"#E0822C",t:"大雨 3"},{v:6,c:"#C0392B",t:"暴雨 6"},{v:15,c:"#7B1F14",t:"大暴雨 15"}];\n'
        '  for(var qi=0;qi<PTH.length;qi++){ if(PTH[qi].v>pMax) continue; var py2=yP(PTH[qi].v);\n'
        '    svg.appendChild(el("line",{x1:CH.left,y1:py2,x2:CH.right,y2:py2,stroke:PTH[qi].c,"stroke-width":1.1,"stroke-dasharray":"5 4",opacity:.7}));\n'
        '    svg.appendChild(txt(CH.right-5,py2-4,PTH[qi].t+" mm/h","end",PTH[qi].c,10.5)); }\n'
        '  // 气温线：粗实线 + 数据点\n'
        '  var tPts=""; for(var i=0;i<n;i++) tPts+=x(i).toFixed(1)+","+yT(CH.temp[i]).toFixed(1)+" ";\n'
        '  svg.appendChild(el("polyline",{points:tPts.trim(),fill:"none",stroke:"#E0822C","stroke-width":2.8,"stroke-linejoin":"round"}));\n'
        '  for(var i=0;i<n;i+=6){ svg.appendChild(el("circle",{cx:x(i).toFixed(1),cy:yT(CH.temp[i]).toFixed(1),r:2.2,fill:"#E0822C",stroke:"#fff","stroke-width":1})); }\n'
'  // 体感温度线：虚线（同温度轴，两者均 °C）\n'
'  var aPts=""; for(var i=0;i<n;i++) aPts+=x(i).toFixed(1)+","+yT(CH.apparent[i]).toFixed(1)+" ";\n'
'  svg.appendChild(el("polyline",{points:aPts.trim(),fill:"none",stroke:"#8E44AD","stroke-width":1.8,"stroke-dasharray":"6 4","stroke-linejoin":"round"}));\n'
        '  // 风力带（均风~阵风半透明填充）\n'
        '  var bandPts=""; for(var i=0;i<n;i++) bandPts+=x(i).toFixed(1)+","+yW(CH.wind[i]).toFixed(1)+" ";\n'
        '  for(var i=n-1;i>=0;i--) bandPts+=x(i).toFixed(1)+","+yW(CH.gust[i]).toFixed(1)+" ";\n'
        '  svg.appendChild(el("polygon",{points:bandPts,fill:"rgba(15,168,122,.10)"}));\n'
        '  // 均风线：实线绿\n'
        '  var wPts=""; for(var i=0;i<n;i++) wPts+=x(i).toFixed(1)+","+yW(CH.wind[i]).toFixed(1)+" ";\n'
        '  svg.appendChild(el("polyline",{points:wPts.trim(),fill:"none",stroke:"#0FA87A","stroke-width":2.4,"stroke-linejoin":"round"}));\n'
        '  // 阵风线：虚线红\n'
        '  var gPts=""; for(var i=0;i<n;i++) gPts+=x(i).toFixed(1)+","+yW(CH.gust[i]).toFixed(1)+" ";\n'
        '  svg.appendChild(el("polyline",{points:gPts.trim(),fill:"none",stroke:"#D84315","stroke-width":2,"stroke-dasharray":"7 3","stroke-linejoin":"round"}));\n'
        '  // 日期标记\n'
        '  for(var i=0;i<n;i+=24){ svg.appendChild(txt(x(i),CH.bot+14,CH.times[i].slice(5,10),"middle","#888",12)); }\n'
        '  // 光标\n'
        '  var cur=el("line",{x1:0,y1:CH.top,x2:0,y2:CH.bot,stroke:"#1f2933","stroke-width":1.2,"stroke-dasharray":"4 3"}); svg.appendChild(cur);\n'
        '  var cmT=el("circle",{r:4.5,fill:"#E0822C",stroke:"#fff","stroke-width":1.5}), cmW=el("circle",{r:4.5,fill:"#0FA87A",stroke:"#fff","stroke-width":1.5}), cmG=el("circle",{r:4.5,fill:"#D84315",stroke:"#fff","stroke-width":1.5});\n'
        '  svg.appendChild(cmT); svg.appendChild(cmW); svg.appendChild(cmG);\n'
        '  // 图上数值框：白底描边 + 行内浅底 pill（与物探看板一致，光标随动）\n'
        '  var HTINT={"#8A4B00":"#FBEAD3","#0D47A1":"#D8E9FA","#0F5B4C":"#D9EFE7","#8A2A0E":"#FBE0D6"};\n'
        '  var rbox=el("g",{"class":"hread"}); svg.appendChild(rbox);\n'
        '  function cw(t){var s=0;for(var k=0;k<t.length;k++){s+=(t.charCodeAt(k)>255?13.6:7.5);}return s;}\n'
        '  function paintRead(i){\n'
        '    while(rbox.firstChild) rbox.removeChild(rbox.firstChild);\n'
        '    var ptS=(PT_TXT[CH.ptype[i]]||"");\n'
        '    var rows=[["降水 ",CH.rainfall[i]+" mm/h"+(ptS?" "+ptS:""),"#0D47A1"],["气温 ",CH.temp[i]+" ℃","#8A4B00"],["体感 ",CH.apparent[i]+" ℃","#8E44AD"],["阵风 ",CH.gust[i]+" m/s","#8A2A0E"],["均风 ",CH.wind[i]+" m/s","#0F5B4C"]];\n'
        '    var bw=0,j; for(j=0;j<rows.length;j++){bw=Math.max(bw,cw(rows[j][0])+cw(rows[j][1]));} bw+=24;\n'
        '    var lh=18.5,pady=7,bh=rows.length*lh+pady*2;\n'
        '    var sx=x(i); var bx=sx+12; if(bx+bw>CH.right) bx=sx-12-bw; if(bx<CH.left) bx=CH.left;\n'
        '    var by=CH.top+26;\n'
        '    rbox.appendChild(el("rect",{x:bx,y:by,width:bw,height:bh,rx:7,fill:"rgba(255,255,255,.96)",stroke:"#C0392B","stroke-width":1.2}));\n'
        '    for(j=0;j<rows.length;j++){\n'
        '      var ty=by+pady+14+j*lh;\n'
        '      rbox.appendChild(el("rect",{x:bx+6,y:ty-13,width:cw(rows[j][0])+cw(rows[j][1])+10,height:17.5,rx:5,fill:HTINT[rows[j][2]]||"#EEF2F5"}));\n'
        '      var lb=el("text",{x:bx+11,y:ty,"font-size":13.5,fill:"#3A4146"}); lb.textContent=rows[j][0]; rbox.appendChild(lb);\n'
        '      var vv=el("text",{x:bx+11+cw(rows[j][0]),y:ty,"font-size":13.5,fill:rows[j][2],"font-weight":"900"}); vv.textContent=rows[j][1]; rbox.appendChild(vv);\n'
        '    }\n'
        '  }\n'
        '  var valBox=document.getElementById("hval");\n'
        '  function fmt(t){return t.slice(5,10)+" "+t.slice(11,16);}\n'
        '  function update(i){ i=Math.max(0,Math.min(n-1,Math.round(i))); var xx=x(i);\n'
        '    cur.setAttribute("x1",xx); cur.setAttribute("x2",xx);\n'
        '    cmT.setAttribute("cx",xx); cmT.setAttribute("cy",yT(CH.temp[i]));\n'
        '    cmW.setAttribute("cx",xx); cmW.setAttribute("cy",yW(CH.wind[i]));\n'
        '    cmG.setAttribute("cx",xx); cmG.setAttribute("cy",yW(CH.gust[i]));\n'
        '    var ptS=(PT_TXT[CH.ptype[i]]||"");\n'
        '    valBox.innerHTML=\'<span class="t">\'+fmt(CH.times[i])+\'</span>\'+eic("rain",lvR(CH.rainfall[i]))+\'降水 <b class="pv">\'+CH.rainfall[i]+\' mm/h\'+(ptS?\' \'+ptS:\'\')+\'</b> \'+eic("temp")+\'气温 <b class="tv">\'+CH.temp[i]+\'℃</b> \'+eic("heat")+\'体感 <b style="color:#8E44AD;background:#F3E5F5">\'+CH.apparent[i]+\'℃</b> \'+eic("wind",lvG(CH.gust[i]))+\'阵风 <b class="gv">\'+CH.gust[i]+\' m/s</b> \'+eic("wind")+\'均风 <b class="wv">\'+CH.wind[i]+\' m/s</b>\';\n'
        '    paintRead(i);\n'
        '  }\n'
        '  // 时间轴滑块已移除：改为在图表上点击 / 拖动选时\n'
        '  function drag(e){var r=svg.getBoundingClientRect(); if(!r.width)return; var px=(e.clientX-r.left)/r.width*CH.w; var i=Math.round((px-CH.left)/((CH.right-CH.left)/(n-1))); update(i);}\n'
        '  svg.addEventListener("pointerdown",function(e){drag(e); try{svg.setPointerCapture(e.pointerId);}catch(_){}});\n'
        '  svg.addEventListener("pointermove",function(e){if(e.buttons)drag(e);});\n'
        '  update(0);\n'
        '})();\n'
        '</script>\n'
    )

# 「未来 两周」三个静态图的点选交互：点击选日期 → 红色竖线 + 浅底 pill 数值框（图表 DOM 不重建）
DAILY_JS = r'''<script>
(function(){
  var NS="http://www.w3.org/2000/svg";
  var TINT={"#2E7DA8":"#DEECF7","#E0822C":"#FBEAD3","#7E57C2":"#EAE3F7","#C0392B":"#FADFDB",
            "#4A90D9":"#D8E9FA","#0FA87A":"#D9EFE7","#D84315":"#FBE0D6","#1565C0":"#D8E9FA"};
  var DEEP={"#E0822C":"#8A4B00","#D84315":"#8A2A0E","#C0392B":"#A5261A","#7E57C2":"#4A2C8F",
            "#2E7DA8":"#1A5A87","#4A90D9":"#0D47A1","#0FA87A":"#0F5B4C"};
  function tintOf(c){ return TINT[c] || "#EEF2F5"; }
  function deepOf(c){ return DEEP[c] || c; }
  function el(t,a){ var e=document.createElementNS(NS,t); for(var k in a) e.setAttribute(k,a[k]); return e; }
  function cw(t){ var s=0; for(var i=0;i<t.length;i++){ s+=(t.charCodeAt(i)>255?13.6:7.5); } return s; }
  var DAY_SEL=-1, DAYS=null, charts=[];
  function xOf(p,i){ return p.kind==="bar" ? (p.x0+(p.x1-p.x0)*(i+0.5)/p.n) : (p.x0+(p.x1-p.x0)*i/Math.max(p.n-1,1)); }
  function paint(){
    var info=document.getElementById("dayInfo");
    if(info){ info.innerHTML = (DAY_SEL>=0 && DAYS) ? ('<span class="day-chip">已选 '+DAYS[DAY_SEL]+'</span>') : ""; }
    for(var k=0;k<charts.length;k++){
      var svg=charts[k].svg, p=charts[k].p;
      var old=svg.querySelector("g.daySel"); if(old) old.remove();
      if(DAY_SEL<0 || DAY_SEL>=p.n) continue;
      var g=el("g",{"class":"daySel"});
      var sx=xOf(p,DAY_SEL);
      g.appendChild(el("line",{x1:sx,y1:p.top,x2:sx,y2:p.bot,stroke:"#C0392B","stroke-width":1.6,"stroke-dasharray":"4 3",opacity:.9}));
      var rows=[];
      for(var j=0;j<p.series.length;j++){ var s=p.series[j];
        var rawV=(s.vals && s.vals[DAY_SEL]!==undefined) ? s.vals[DAY_SEL] : null;
        var tTxt=s.name+" "+(rawV===null? "—（该日无数据）" : rawV+" "+p.unit);
        if(p.kind==="bar" && p.ptypes && p.ptypes[DAY_SEL]){ var p2=p.ptypes[DAY_SEL];
          tTxt+=" "+(p2===1?"降雨":p2===2?"降雪":p2===3?"雨夹雪":""); }
        rows.push({t:tTxt, c:s.color}); }
      var bw=0; for(var j2=0;j2<rows.length;j2++){ bw=Math.max(bw,cw(rows[j2].t)); } bw+=22;
      var lh=17.5, pady=7, bh=rows.length*lh+pady*2;
      var bx=sx+10; if(bx+bw>p.x1) bx=sx-10-bw; if(bx<p.x0) bx=p.x0;
      var by=p.top+2;
      g.appendChild(el("rect",{x:bx,y:by,width:bw,height:bh,rx:7,fill:"rgba(255,255,255,.96)",stroke:"#C0392B","stroke-width":1.2}));
      for(var m=0;m<rows.length;m++){
        var ty=by+pady+13+m*lh;
        g.appendChild(el("rect",{x:bx+6,y:ty-13,width:cw(rows[m].t)+12,height:17.5,rx:5,fill:tintOf(rows[m].c)}));
        var tx=el("text",{x:bx+11,y:ty,"font-size":13.5,fill:deepOf(rows[m].c),"font-weight":"900"});
        tx.textContent=rows[m].t; g.appendChild(tx);
      }
      svg.appendChild(g);
    }
  }
  function pick(svg,ev){
    var p; try{ p=JSON.parse(svg.getAttribute("data-payload")); }catch(e){ return; }
    var r=svg.getBoundingClientRect(); if(!r.width) return;
    var vx=(ev.clientX-r.left)/r.width*p.w;
    var i = (p.kind==="bar") ? Math.round((vx-p.x0)/(p.x1-p.x0)*p.n-0.5) : Math.round((vx-p.x0)/(p.x1-p.x0)*(p.n-1));
    i=Math.max(0,Math.min(p.n-1,i));
    DAY_SEL=(DAY_SEL===i)?-1:i;
    paint();
  }
  function bind(){
    charts=[]; DAYS=null;
    var list=document.querySelectorAll("#tab-daily svg.dchart");
    for(var k=0;k<list.length;k++){
      var svg=list[k], p;
      try{ p=JSON.parse(svg.getAttribute("data-payload")); }catch(e){ continue; }
      charts.push({svg:svg,p:p});
      if(!DAYS && p.days) DAYS=p.days;
      if(!svg._bound){ svg._bound=1; svg.style.cursor="crosshair";
        svg.addEventListener("click",(function(s){ return function(ev){ pick(s,ev); }; })(svg)); }
    }
  }
  bind(); paint();
})();
</script>
'''

def render_point(rec, daily, s, sev, risk, hourly, sev3=0, daily3=None, ph=0.0):
    """ph = 近 48 小时最大小时降水（mm/h），由调用方从 hourly[:48] 现算后传入。"""
    name = rec["name"]; l1, l2, l3 = rec["level1"], rec["level2"], rec["level3"]
    dates = [d["date"] for d in daily]
    precip = [d["rainfall"] for d in daily]
    ptypes = [d.get("ptype", 0) for d in daily]        # 0无 / 1降雨 / 2降雪 / 3雨夹雪
    tmin = [d["tempMin"] for d in daily]; tmax = [d["tempMax"] for d in daily]
    wmax = [d["windMax"] for d in daily]; gmax = [d["gustMax"] for d in daily]
    # 降雪水当量（mm）：并入逐日降水图（与降雨并列柱）
    snow = [d.get("snowfall") or 0.0 for d in daily]
    # 体感温度（°C）：并入逐日气温图（虚线）；缺字段时整组不画，避免出现全 0 假曲线
    _appMax = [d.get("apparentMax") for d in daily]
    _appMin = [d.get("apparentMin") for d in daily]
    has_app = any(v is not None for v in _appMax) and any(v is not None for v in _appMin)
    temp_series = [("最高温", tmax, "#E0822C"), ("最低温", tmin, "#2E7DA8")]
    if has_app:
        _aMax = [v if v is not None else 0.0 for v in _appMax]
        _aMin = [v if v is not None else 0.0 for v in _appMin]
        temp_series += [("最高体感", _aMax, "#D84315", {"labels": False, "dash": "6 4"}),
                        ("最低体感", _aMin, "#7E57C2", {"labels": False, "dash": "6 4"})]
    # 逐日最低能见度（m）：缺字段时不画该图
    _visMin = [d.get("visMin") for d in daily]
    has_vis = any(v is not None for v in _visMin)
    visMin = [v for v in _visMin]        # 保留 None（第 7 天起 x1_visibility 无值 → 断线，不画成 0 米）
    chart_precip = svg_bars(dates, precip, "#2E86DE", sid="dchart-precip", days=dates,
                            unit="mm", label="降雨", ptypes=ptypes,
                            extra=[("降雪", snow, "#5DD6E8")])
    # 逐日气温：最高/最低温 + 最高/最低体感（体感并入气温图，2026-10-16 用户定）。
    # 体感画虚线且不逐点标值——4 条线同时标值会互相遮挡；点选日期时数值框仍给出全部系列的值。
    chart_temp = svg_lines(dates, temp_series, sid="dchart-temp", days=dates, unit="℃")
    chart_wind = svg_lines(dates, [("阵风", gmax, "#C0392B"), ("均风", wmax, "#7E57C2")],
                           sid="dchart-wind", days=dates, unit="m/s")
    chart_vis = (svg_lines(dates, [("最低能见度", visMin, "#7E57C2")], sid="dchart-vis", days=dates, unit="m")
                 if has_vis else "")
    # 未来 48 小时逐小时图：仅取前 48 个小时（须先算，_near_summary/文案/风险卡都要用）
    hourly48 = {k: (v[:48] if isinstance(v, list) else v) for k, v in hourly.items()}
    n_hour = len(hourly48.get("time", []))
    # 作业天气影响与建议（与物探同结构：单节、每要素一卡，风险+建议合并；48h 口径，气温含体感）
    imp_html = impact_cards_html(daily, s, ph, hourly48)
    sub = " · ".join([x for x in [l1, l2, l3] if x])
    # 未来 48 小时（近 2 天）口径：重点提示 Tab 的主口径
    near = daily[:2]
    sNear = _near_summary(near, ph, hourly48)
    far = far_alert(daily)
    # 横幅正文：逐要素清单（一行一个要素，只列 48h 内最高级别那一条），远期另起一行
    items = alert_items(sNear, hourly48)
    if items:
        rows_html = "".join(
            f'<div class="ai">{eic(_EIC_KIND[it["kind"]], _lv_eic(it["lv"]), "s")}'
            f'<span class="ai-k">{it["name"]}</span>'
            f'<span class="ai-lv lv{int(it["lv"])}">{it["label"]}</span>'
            f'<span class="ai-v">{it["val"]:g}<em>{it["unit"]}</em></span></div>'
            for it in items)
    else:
        rows_html = ('<div class="ai-note">未来 48 小时各要素均未达预警阈值，适宜作业。</div>')
    if far:
        far_html = (f'<div class="far"><b>远期（第 3~14 天）</b>{far}；'
                    '远端预报不确定性较大，临近时请关注属地最新预警。</div>')
    else:
        far_html = ('<div class="far quiet"><b>远期（第 3~14 天）</b>'
                    '暂无明显重大极端天气，临近时再提示。</div>')
    near_start = near[0]["date"] if near else rec.get("start_date", "")
    HERO_CSS = hero_css()   # 页头背景图 CSS（无图时为空串，静默降级）
    # 两周图版块拼装（降雪已并入降水图、体感已并入气温图；能见度缺数据时整块不出现）
    _tapp_leg = ('<i style="background:#D84315"></i>最高体感<i style="background:#7E57C2"></i>最低体感（虚线；舒适度预警由体感承担）'
                 if has_app else "")
    _vblock = (f'<div class="chart-h">逐日能见度（m）</div>\n'
               f'<div class="legend">当日最低能见度（m），越低越影响行车与吊装；{eic("fog")}低于 1000m 即进入预警</div>{chart_vis}'
               if has_vis else "")
    html = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name} · 天气看板</title><style>{CSS}{HERO_CSS}</style></head>
<body class="sev{sev3}">
<div class="heroarea">
<div class="topbar"><div class="topbar-l"><a href="index.html" class="backlink" id="backLink">&larr; 返回总览</a><script>var b=document.getElementById('backLink');if(new URLSearchParams(location.search).get('from')!=='index'&&b)b.style.display='none';</script></div><div class="topbar-r"><a href="https://leidian.wang" class="extlink" target="_blank" rel="noopener">北斗天气风险治理平台 ↗</a></div></div>
<h1>{name}</h1>
<div class="unit">{sub}</div>
<div class="sub">未来 两周逐小时预报 · <b>{rec['start_date']} ~ {rec['end_date']}</b>　{rec['lon']:.2f}°E {rec['lat']:.2f}°N</div>
<div class="tabs">
<button class="tab active" data-tab="focus">重点提示</button>
<button class="tab" data-tab="hourly">未来48小时</button>
<button class="tab" data-tab="daily">未来两周</button>
</div>
</div>

<div class="panel" id="tab-focus">
<div class="alert"><div class="t"><span class="dot"></span>未来 48 小时 · {SEV_LABEL[sev3]}</div>
<div class="ailist">{rows_html}</div>{far_html}</div>
<div class="stats">{kpi_stats_html(sNear, hourly48)}</div>
<div class="card"><h2><span class="dot" style="background:var(--sev)"></span>作业天气影响与建议</h2>
<div class="impbox">{imp_html}</div></div>
</div>

<div class="panel" id="tab-hourly" style="display:none">
<div class="card"><h2><span class="dot" style="background:var(--sev)"></span>未来 48 小时逐小时</h2>
<div class="legend">柱颜色＝降水类型：{ptype_legend_html()}</div>
<div id="hval" class="hval"></div>
<svg id="hchart" viewBox="0 0 760 340" width="100%" preserveAspectRatio="xMinYMin meet" style="display:block;touch-action:none;cursor:crosshair"></svg>
</div>
</div>

<div class="panel" id="tab-daily" style="display:none">
<div class="card"><h2><span class="dot" style="background:var(--sev)"></span>未来 两周逐日天气<span id="dayInfo"></span></h2>
<div class="chart-h">逐日降水（mm）</div>
<div class="legend">{eic("rain")}<i style="background:#2E86DE"></i>降雨<i style="background:#5DD6E8"></i>降雪（水当量，与降雨并列）</div>{chart_precip}
<div class="chart-h">逐日气温（°C）</div>
<div class="legend">{eic("temp")}<i style="background:#E0822C"></i>最高温<i style="background:#2E7DA8"></i>最低温{_tapp_leg}</div>{chart_temp}
<div class="chart-h">逐日阵风 / 均风（m/s）</div>
<div class="legend">{eic("wind")}<i style="background:#C0392B"></i>阵风（日最大）<i style="background:#7E57C2"></i>均风（日最大）</div>{chart_wind}
{_vblock}
</div>
</div>

<div class="foot">山区小气候可能强于模式预报，建议以现场实测为准。</div>
"""
    html += chart_js(hourly48)
    html += DAILY_JS
    html += """<script>
(function(){
  var tabs=document.querySelectorAll(".tab");
  function show(t){
    tabs.forEach(function(x){x.classList.remove("active");});
    t.classList.add("active");
    document.querySelectorAll(".panel").forEach(function(p){p.style.display="none";});
    document.getElementById("tab-"+t.getAttribute("data-tab")).style.display="block";
  }
  tabs.forEach(function(t){t.addEventListener("click",function(){show(t);});});
})();
</script>"""
    html += '<script async src="//busuanzi.ibruce.info/busuanzi/2.3/busuanzi.pure.mini.js"></script>'
    html += '<div style="margin-top:16px;padding-top:8px;border-top:1px solid rgba(128,128,128,.18);font-size:11px;color:#9aa0a6;text-align:center;opacity:.6;letter-spacing:.3px">访问统计 · 本页阅读 <span id="busuanzi_container_page_pv"><span id="busuanzi_value_page_pv"></span> 次</span> · 全站访客 <span id="busuanzi_container_site_uv"><span id="busuanzi_value_site_uv"></span> 人</span></div>'
    html += "</body></html>"
    return html

# ---------- 主流程 ----------
def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--datadir", default="engineering/data", help="逐点 JSON 数据目录（meta.kind=='point'）")
    ap.add_argument("--htmldir", default="engineering/html", help="看板 HTML 输出目录")
    ap.add_argument("--only", default=None, help="仅渲染指定 slug 的单个点位看板（预览用）")
    args = ap.parse_args()
    datadir = os.path.abspath(args.datadir)
    htmldir = os.path.abspath(args.htmldir)
    if not os.path.isdir(datadir):
        print(f"ERROR: 数据目录不存在: {datadir}")
        sys.exit(1)
    os.makedirs(htmldir, exist_ok=True)

    files = sorted(glob.glob(os.path.join(datadir, "*.json")))
    recs = []
    for fp in files:
        d = json.load(open(fp, encoding="utf-8"))
        m = d.get("meta", {})
        # 仅渲染 Markdown 点位表产出的逐点数据（排除井位看板 *_data.json）
        if m.get("kind") != "point":
            continue
        daily, s, hourly = d["daily"], d["summary"], d["hourly"]
        slug = os.path.splitext(os.path.basename(fp))[0]
        sev = sev_of(daily, s); risk = risk_of(daily, s)
        daily3 = daily[:2]
        # 近 48 小时最大小时降水（mm/h）：只看前 48 个小时，供 48h 口径的等级/卡片/文案使用
        hourly48 = {k: (v[:48] if isinstance(v, list) else v) for k, v in hourly.items()}
        hourly48["_daily2"] = daily[:2]   # hourly 缺失时的风温兜底
        ph = phour_max(hourly48)
        # 48h 等级的风/温同样取逐小时窗口（不用 daily[:2]、不用 summary 全窗值）
        sev3 = sev_of_recent(daily3, ph, el48=h48_elements(hourly48),
                             snow_h=snow_hour_max_48(hourly48))
        recs.append({"name": m["name"], "level1": m["level1"], "level2": m["level2"],
                     "level3": m["level3"], "slug": slug, "file": slug + ".html",
                     "sev": sev, "sev3": sev3, "start": m["start_date"]})
        if args.only and slug != args.only:
            continue  # 预览单点：只写该点位的看板
        html = render_point(m, daily, s, sev, risk, hourly, sev3, daily3, ph)
        out = os.path.join(htmldir, slug + ".html")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        open(out, "w", encoding="utf-8").write(html)
        print(f"  ✓ 看板: {slug}.html  ({m['name']}, {SEV_LABEL[sev]})")

    if not recs:
        print("ERROR: 未找到任何 meta.kind=='point' 的逐点数据文件。")
        sys.exit(1)

    print(f"  ✓ 共渲染 {len(recs)} 个点位看板 → {htmldir}"
          + (f"　[仅预览 {args.only}.html]" if args.only else ""))
    print("  提示：目录总览 index.html 请用 weather-engineering-index 技能的 "
          "build_points_index.py 单独生成")
    print(f"DONE → {htmldir}")

if __name__ == "__main__":
    main()
