#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_points_summary.py —— 石油工程点位「未来 2 天（48小时）风险汇总」叙事生成器
========================================================================
读取 engineering/data 下所有 meta.kind=="point" 的 JSON（由 build_points_data.py
从 engineering_ta_map.json 生成），按未来 2 天（daily[:2]，即 48 小时）聚合，自动产出一段
约 50 字、平实口吻的「未来 2 天风险」短描述（不罗列等级，与人工口径一致，可一键复制到汇报）。

字段约定（与 build_points_data.py 输出一致）：
  daily[i] = {date, tempMin, tempMax, precip, windMax, gustMax}
定级阈值（与 render_points_html.py 的 sev_of_recent 完全一致；风阈值统一走 jozzonwx.grade_gust/grade_wind）：
  3 高度警惕 : 单日降水>=80 或 阵风>=32.7(十二级) 或 最高温>=38 或 2日累计>=150
  2 重点关注 : 单日降水>=50 或 阵风>=24.5(十级) 或 最高温>=35 或 最低温<=-5 或 2日累计>=80
  1 需关注   : 单日降水>=12 或 最大风>=10.8(六级均风) 或 最低温<=0 或 2日累计>=20
  0 整体适宜 : 其余

口径说明（2026-09-17 固化，同日修订为未来 2 天/48小时）：聚焦「未来 2 天（48小时）可靠预报窗口」，
不把整周（7 天）远期极端值列为主风险；第 3 天起若仍有较高风险，仅一句话「临近时再提示」。
"""
import os, sys, json, argparse, glob, datetime

# 共享取数 + 分级模块（jozzon-mcp 九章雷电网）
_COMMON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "weather-common", "scripts")
if os.path.isdir(_COMMON):
    sys.path.insert(0, os.path.abspath(_COMMON))
import jozzonwx as JW

SEV_LABEL = {0: "整体适宜", 1: "需关注", 2: "重点关注", 3: "高度警惕"}

# 工区(点位名前缀) → 地理区域描述（可在此按需维护）
AREA_MAP = {
    "红页": "重庆石柱、利川一带",
    "兴页": "重庆忠县、丰都一带",
    "焦页": "重庆涪陵一带",
    "綦陆页": "重庆綦江一带",
    "悦来": "重庆梁平、忠县一带",
    "马": "四川宣汉、开江一带",
    "元陆": "四川宣汉、达州一带",
    "预警点": "贵州贵阳东支线一带",
    "流溪村": "川东管道（湖北恩施一带）",
    "紫台村": "川东管道（湖北恩施一带）",
}

# ===== 要素显示文本（含阈值，2026-10-17 用户要求「把阈值放上去」）=====
# 等级一律来自 jozzonwx.grade_*（本文件不再保存任何阈值副本，杜绝口径漂移）。
# 键 = (要素, 等级)；文本 = 对外展示用短语，括号内为触发阈值。
_ELEM_TEXT = {
    ("rain", 2): "中雨（≥1.5mm/h）", ("rain", 3): "大雨（≥3mm/h）",
    ("rain", 4): "暴雨（≥6mm/h）", ("rain", 5): "大暴雨（≥15mm/h）",
    ("snow", 2): "中雪（≥0.5mm/h）", ("snow", 3): "大雪（≥1mm/h）",
    ("snow", 4): "暴雪（≥2mm/h）",
    ("gust", 1): "七级阵风（≥13.9m/s）",
    ("gust", 2): "八级阵风（≥17.2m/s）", ("gust", 3): "十级阵风（≥24.5m/s）",
    ("gust", 4): "十二级阵风（≥32.7m/s）",
    ("wind", 2): "六级均风（≥10.8m/s）", ("wind", 3): "八级均风（≥17.2m/s）",
    ("wind", 4): "十级均风（≥24.5m/s）",
    ("hot", 1): "偏热（体感>26℃）", ("hot", 2): "炎热（体感>32℃）",
    ("hot", 3): "酷热（体感>38℃）", ("hot", 4): "极热（体感>46℃）",
    ("cold", 1): "寒冷（体感<0℃）", ("cold", 2): "严寒（体感<-13℃）",
    ("cold", 3): "酷寒（体感<-27℃）", ("cold", 4): "极寒（体感<-40℃）",
    ("vis", 1): "能见度<1000m", ("vis", 2): "能见度<500m",
    ("vis", 3): "能见度<200m", ("vis", 4): "能见度<100m",
}
# 同级要素的先后顺序（数字越小越靠前）：降雨 → 降雪 → 阵风 → 均风 → 体感 → 能见度
_ELEM_ORDER = {"rain": 0, "snow": 1, "gust": 2, "wind": 3, "hot": 4, "cold": 5, "vis": 6}
# index 概述行头用的要素名（hot/cold 都用「体感」，等级词自身已区分冷热：
# 「体感 · 酷热」「体感 · 极寒」；若写成「体感炎热 · 偏热」会自相矛盾）
_ELEM_DISP = {"rain": "降水", "snow": "降雪", "gust": "阵风", "wind": "均风",
              "hot": "体感", "cold": "体感", "vis": "能见度"}

# 处置建议（按触发的最高级要素给一句，避免堆砌）
_ELEM_ADVICE = {
    "rain": "中雨及以上严重影响作业，需防井场积涝、道路湿滑与运输受阻",
    "snow": "降雪注意道路结冰与设备防冻",
    "gust": "八级及以上阵风需停止高空与吊装作业、加固井架",
    "wind": "均风偏大注意高空作业与临时设施加固",
    "hot": "体感酷热注意防暑降温与设备散热",
    "cold": "体感酷寒注意人员防寒与设备防冻保温",
    "vis": "能见度低谨慎行车、必要时暂停运输",
}


def _elems_of(p):
    """从 48h 峰值字典/点位记录里取出各要素等级。
    入参需含：pHourMax / snowHourMax / gust / wind / appMax / appMin / visMin。
    返回 [(等级, 要素序, 要素, 排序值)]，仅含等级 >= 1 的要素；排序值为该要素的原始量级
    （用于同级内「谁更严重」排序；冷侧取负值使其降序=越冷越前）。"""
    out = []
    lr = JW.grade_rain(p.get("pHourMax") or 0)
    if lr: out.append((lr, "rain", p.get("cum") or 0))
    ls = JW.grade_snow(p.get("snowHourMax") or 0)
    if ls: out.append((ls, "snow", p.get("snow48") or p.get("snowHourMax") or 0))
    lg = JW.grade_gust(p.get("gust") or 0)
    if lg: out.append((lg, "gust", p.get("gust") or 0))
    lw = JW.grade_wind(p.get("wind") or 0)
    if lw: out.append((lw, "wind", p.get("wind") or 0))
    if p.get("appMax") is not None:
        lh = JW.grade_utci(p["appMax"])[0]
        if lh: out.append((lh, "hot", p["appMax"]))
    if p.get("appMin") is not None:
        lc = JW.grade_utci(p["appMin"])[0]
        if lc: out.append((lc, "cold", -p["appMin"]))
    if p.get("visMin") is not None:
        lv = JW.grade_vis(p["visMin"])
        if lv: out.append((lv, "vis", -p["visMin"]))
    return [(lv, _ELEM_ORDER[k], k, val) for lv, k, val in out]


def point_focus(p, max_elems=None):
    """单点位卡片信息（2026-10-17 用户口径，与总概述同源）：
    ① **2 级及以上的要素全部列出**（不限制个数），排序：等级高的在前 → 同级按
       「降雨→降雪→阵风→均风→体感→能见度」；
    ② 要素名后必须带阈值，如「暴雨（≥6mm/h）」；
    ③ 48h 累计降水 >20mm 才写、累计降雪 >10mm 才写，否则不提（用户明确删掉低量级流水账）。
    入参 p 需含 48h 峰值键（同 _elems_of）与 cum / snow48。"""
    els = [e for e in _elems_of(p) if e[0] >= 2]
    bits = []
    cum = p.get("cum") or 0
    sn = p.get("snow48") or 0
    if cum > 20:
        bits.append(f"48h 累计降水 {round(cum, 1)}mm")
    if sn > 10:
        bits.append(f"48h 累计降雪 {round(sn, 1)}mm")
    if els:
        sel = sorted(els, key=lambda e: (-e[0], e[1], -e[3]))
        if max_elems:
            sel = sel[:max_elems]
        for lv, _o, kind, _v in sel:
            bits.append(_ELEM_TEXT.get((kind, lv), f"{kind}{lv}级"))
    return "；".join(bits) or "未来 2 天无明显高影响天气"


def build_overview(pts, max_chars=200):
    """【已停用，保留作散文版参考】index 页「未来 2 天风险」总概述。

    2026-10-17 晚间：用户要求工程 index 概述「和物探一样按要素列」，index 已改用
    `overview_elems()` + `build_points_index.near_term_html()` 的分行清单（一行一个
    「要素 · 等级」+ 点位名），本函数的散文式一段话不再被 index 调用；
    若日后需要「一段话」形式（如微信推送、汇报口播），仍可直接调用，逻辑与阈值未变。

    口径：① 不再重复「未来 2 天」字样（外层标签已有），也不再用「N 口井需重点关注」这类
    与页面徽章同名却含义不同的说法——直接点名「哪个点 + 哪个要素 + 阈值」；
    ② 全部井位按要素等级从 4 级往 2 级排，先高后低；**只要有 3 级及以上，就不再罗列 2 级**；
    ③ 同一要素的同级点位合并成一句，最多点 3 个（其余「等 N 口井」），按量级降序取前 3；
    ④ 总字数（含标点）不超过 max_chars，超了先砍处置建议、再砍末尾低优先级的句子。"""
    if not pts:
        return "暂无点位数据，暂无法评估。"
    buckets = {}          # (等级, 要素) -> [(排序值, 点位名)]
    for p in pts:
        nm = p.get("name") or ""
        for lv, _order, kind, val in _elems_of(p):
            if lv >= 2:
                buckets.setdefault((lv, kind), []).append((val, nm))
    if not buckets:
        return "各工区无 2 级及以上要素预警，天气总体平稳，保持常态监测即可。"

    top = max(k[0] for k in buckets)
    floor = 3 if top >= 3 else 2          # 有 3 级及以上就不再提 2 级
    keys = [k for k in buckets if k[0] >= floor]
    keys.sort(key=lambda k: (-k[0], _ELEM_ORDER[k[1]]))

    clauses, hit, seen_sets = [], set(), {}
    for lv, kind in keys:
        rows = sorted(buckets[(lv, kind)], key=lambda x: -x[0])
        names = []
        for _v, nm in rows:
            if nm not in names:
                names.append(nm)
        txt = _ELEM_TEXT.get((kind, lv), kind)
        hit.add(kind)
        sig = tuple(sorted(names))
        # 同一批井命中多个要素时合并成一句，避免「同一串井名反复出现」把 200 字耗尽
        if sig in seen_sets:
            clauses[seen_sets[sig]]["texts"].append(txt)
        else:
            seen_sets[sig] = len(clauses)
            clauses.append({"names": names, "texts": [txt]})

    _cl = []
    for g in clauses:
        shown = g["names"][:3]
        tail = f"等{len(g['names'])}口井" if len(g["names"]) > 3 else ""
        _cl.append(f"{'、'.join(shown)}{tail} 有{'、'.join(g['texts'])}")
    clauses = _cl

    advice = [_ELEM_ADVICE[k] for k in ("rain", "snow", "gust", "wind", "hot", "cold", "vis")
              if k in hit]

    def _join(cl, adv):
        s = "；".join(cl)
        if adv:
            s += ("。" if s else "") + "；".join(adv)
        return s if s.endswith("。") else s + "。"

    txt = _join(clauses, advice)
    while len(txt) > max_chars and advice:
        advice.pop()
        txt = _join(clauses, advice)
    while len(txt) > max_chars and len(clauses) > 1:
        clauses.pop()
        txt = _join(clauses, advice)
    if len(txt) > max_chars:
        txt = txt[:max_chars - 1] + "…"
    return txt


def elem_chip(kind, lv):
    """概述行头的等级短语：去掉与要素名重复的部分，避免「阵风 · 八级阵风」这种叠字。
    「八级阵风（≥17.2m/s）」→「八级（≥17.2m/s）」；「能见度<200m」→「<200m」；
    「酷热（体感>38℃）」不含要素名 → 原样保留。"""
    t = _ELEM_TEXT.get((kind, lv), f"{lv}级")
    nm = _ELEM_DISP.get(kind, "")
    head = t.split("（")[0]
    if nm and nm in head:
        t = t.replace(nm, "", 1)
    return t


def overview_elems(pts, max_show=8):
    """index「未来 2 天（48 小时）风险」概述 —— 按「要素 × 级别」分组（2026-10-17 用户口径，
    与物探 index 完全一致，替代原先的散文式一段话）：

      · 一行一个「要素 · 等级」+ 达成该级别的全部点位名；
      · 行序 = 级别降序 → 同级按固定要素序（降水→降雪→阵风→均风→体感→能见度）；
      · **必须按级别分行**：若只按要素分行、用该要素最高级别当行头，会把只有八级阵风的
        点位挂到「十级阵风」行下，与事实不符；
      · 只列 **2 级及以上**（1 级的小雨/六级风/偏热不入概述，卡片与点位页里能看到）；
      · 降雪须有 48h 累计 >0 佐证，否则视为 3~14 天远端尖峰，不计入近端风险。

    返回 [{"kind","lv","head","names":[...],"more":超出未展示条数}]；无 2 级要素时返回 []，
    由调用方给「天气平稳」兜底。数据与卡片同源（_elems_of → jozzonwx.grade_*）。"""
    buckets = {}
    for p in pts:
        for lv, _order, kind, val in _elems_of(p):
            if lv < 2:
                continue
            if kind == "snow" and (p.get("snow48") or 0) <= 0:
                continue
            buckets.setdefault((kind, lv), []).append((val, p.get("name") or "", p.get("file") or ""))
    if not buckets:
        return []
    rows = []
    for kind, lv in sorted(buckets, key=lambda k: (-k[1], _ELEM_ORDER.get(k[0], 9))):
        rows_ = sorted(buckets[(kind, lv)], key=lambda x: -x[0])
        names = list(dict.fromkeys((n, f) for _v, n, f in rows_ if n))
        rows.append({"kind": kind, "lv": lv, "name": _ELEM_DISP.get(kind, kind),
                     "head": elem_chip(kind, lv),
                     "names": names[:max_show], "more": max(0, len(names) - max_show)})
    return rows


def gongqu(name):
    """取点位名的工区前缀（连续中文字符，遇数字/字母截断）。"""
    run = []
    for ch in name:
        if "一" <= ch <= "鿿":
            run.append(ch)
        else:
            break
    return "".join(run) or name


def peaks_48h(d):
    """从单点位 _data.json 取「未来 48 小时（hourly 前 48 个逐时）」各要素峰值，供 48h 风险判定。
    与单点位看板 render_points_html.py 的 h48_elements/h48_precip 同源同值。

    **七要素一律取 hourly 前 48 格**，不用 daily[:2]、也不用 summary 全窗值：
    - hourly 起点是当日整点，48h 窗口横跨 3 个自然日（10-09/10-10/10-11），
      daily[:2] 会整段漏掉第 3 天；
    - summary.maxGust/maxTemp/minTemp 是 14 天全窗极值，会把第 3~14 天的远端大风/高温/寒潮
      当成「未来两天」的风险（实测贵阳东支线阵风全窗 16.3 vs 48h 内 8.8m/s；
      红页7-5HF 最低温全窗 6.7℃ vs 48h 内 15.1℃ → 误报大风/寒冷预警）。
    返回 dict：pHourMax / snowHourMax（mm/h）/ gust / wind / tmax / tmin / appMax / appMin / visMin。
    分级统一走 jozzonwx（降雨/降雪/阵风/均风/UTCI/能见度），两端零漂移。"""
    h = d.get("hourly", {}) or {}
    t = h.get("time", [])
    n = min(48, len(t)) if t else 0
    rain = h.get("rainfall", []) or []
    snow = h.get("snowfall", []) or []
    gusts = h.get("wind_gusts_10m", []) or []
    winds = h.get("wind_speed_10m", []) or []
    temps = h.get("temperature_2m", []) or []
    appr = h.get("apparent_temperature", []) or []
    vis = h.get("visibility", []) or []
    def _mx(s): return round(max(s[:n]), 2) if (n and s) else None
    def _mn(s): return round(min(s[:n]), 2) if (n and s) else None
    pH = _mx(rain)
    sH = _mx(snow)
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
        # 无hourly 的极旧数据才退回 daily 前 2 天
        daily = (d.get("daily") or [])[:2]
        g = max((x.get("gustMax", 0) for x in daily), default=0) if daily else None
        w = max((x.get("windMax", 0) for x in daily), default=0) if daily else None
        tmax = max((x.get("tempMax", -99) for x in daily), default=-99) if daily else None
        tmin = min((x.get("tempMin", 99) for x in daily), default=99) if daily else None
        # ⚠️ 体感缺省必须给 None，不能给 -99/99 哨兵值：旧数据没有 apparentMax/apparentMin 时，
        # 哨兵值会被 grade_utci 判成「极寒(-99) / 极热(99)」4 级，凭空冒出「极热预警」。
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

    与单点位看板 render_points_html.py 的 h48_precip() 及 build_points_index.py 同源同值，
    保证汇总表/index/项目页三处「累计降水」数字完全一致。
    **不能用 daily[:2] 两日之和**：hourly 起点是当日整点，48h 窗口横跨 3 个自然日，
    daily[:2] 会整段漏掉第 3 天（实测马401 井 4.8 vs 24.4mm）。"""
    h = d.get("hourly", {}) or {}
    rain = h.get("rainfall", []) or []
    if rain:
        return round(sum(rain[:48]), 1)
    return round(sum((x.get("rainfall") or 0) for x in (d.get("daily") or [])[:2]), 1)


def h48_snow(d):
    """未来 48 小时累计降雪 mm（hourly 前 48 格 snowfall 累加；snowfall 单位已是 mm/h）。
    用户 2026-10-17 口径：累计降雪 >10mm 才在卡片/概述里提，否则不提。"""
    h = d.get("hourly", {}) or {}
    snow = h.get("snowfall", []) or []
    if snow:
        return round(sum(snow[:48]), 1)
    return round(sum((x.get("snow") or 0) for x in (d.get("daily") or [])[:2]), 1)


def sev_of_recent(days, ph=0.0, cum48=None, el48=None):
    """未来 48 小时风险等级：累计降水 cum48、阵风/持续风/温度 el48 均取 hourly 前 48 格
    窗口（见 h48_precip / peaks_48h）；单日降水峰值 pmax 仍取 daily 前 2 天
    （逐日峰值不会漏，且与用户习惯的「单日 XXmm」表述一致）。
    **新增要素（均风 / 体感温度 UTCI / 能见度 / 降雪）统一经 jozzonwx.el_levels 计级并入**，
    与单点位看板、物探看板共用同一套分级，杜绝两边口径漂移。"""
    cum = cum48 if cum48 is not None else sum((d.get("rainfall") or 0) for d in days)
    pmax = max((d.get("rainfall") or 0) for d in days)
    if el48:
        gust = el48.get("gust") or 0.0
        wind = el48.get("wind") or 0.0
        tmax = el48.get("tmax") if el48.get("tmax") is not None else -99
        tmin = el48.get("tmin") if el48.get("tmin") is not None else 99
    else:
        gust = max((d.get("gustMax", 0) for d in days), default=0)
        wind = max((d.get("windMax", 0) for d in days), default=0)
        tmax = max((d.get("tempMax", -99) or -99) for d in days)
        tmin = min((d.get("tempMin", 99) or 99) for d in days)
    # ph = 48h 内最大小时降水（mm/h）：短时强降水须计入，否则日累计小的井位会被误判为无风险
    # 风的判级一律走 jozzonwx（2026-10-17：阵风同级比均风高两级风力，13.9/17.2/24.5/32.7）
    if pmax >= 80 or JW.grade_gust(gust) >= 4 or tmax >= 38 or cum >= 150:
        sev = 3
    elif ph >= 10 or pmax >= 50 or JW.grade_gust(gust) >= 3 or tmax >= 35 or tmin <= -5 or cum >= 80:
        sev = 2
    elif ph >= 5 or pmax >= 12 or JW.grade_wind(wind) >= 2 or tmin <= 0 or cum >= 20:
        sev = 1
    else:
        sev = 0
    # 用户规则（2026-10-09）：有明显降雨（中雨及以上，即 >=1.5mm/h）即至少定为「需关注」；
    # 降雪、阵风、高/低温仍按各自等级判定，不因这条降雨规则被额外抬级。
    # 新增要素 48h 等级一并并入综合风险（同为一致性兜底来源）。
    peaks = {"rain": ph,
             "snow": el48.get("snowHourMax") if el48 else 0.0,
             "wind": wind or 0.0, "gust": gust or 0.0,
             "appMax": el48.get("appMax") if el48 else None,
             "appMin": el48.get("appMin") if el48 else None,
             "visMin": el48.get("visMin") if el48 else None}
    sev = max(sev, JW.sev_from_levels(JW.el_levels(peaks)))
    return sev


def md_label(d):
    """把 2026-09-17 转成 9月17日。"""
    try:
        y, m, day = map(int, d.split("-"))
        return f"{m}月{day}日"
    except Exception:
        return d


def rain_level(p):
    if p >= 100:
        return "大暴雨级"
    if p >= 50:
        return "暴雨级"
    if p >= 25:
        return "大雨级"
    if p >= 10:
        return "中雨"
    return "小雨"


def load_points(datadir, n=2):
    pts = []
    for f in sorted(glob.glob(os.path.join(datadir, "*.json"))):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        m = d.get("meta", {})
        if m.get("kind") != "point":
            continue
        daily = d.get("daily", [])
        d3 = daily[:n]
        if not d3:
            continue
        s = d.get("summary", {}) or {}
        # 48h 累计降水：hourly[:48] 累加（与项目页/index 同源），不用 daily[:n] 两日之和
        cum = h48_precip(d)
        snow48 = h48_snow(d)
        pmax = max((x.get("rainfall") or 0) for x in d3)
        pk = max(d3, key=lambda x: (x.get("rainfall") or 0))
        # 48h 峰值：七要素一律取 hourly[:48]（风/温/体感/能见度不用 daily[:2]、不用全窗 summary）
        pk48 = peaks_48h(d)
        gust = pk48.get("gust")
        wind = pk48.get("wind")
        tmax = pk48.get("tmax")
        tmin = pk48.get("tmin")
        phm = pk48.get("pHourMax") or 0.0
        sev = sev_of_recent(d3, phm, cum48=cum, el48=pk48)
        pts.append({
            "name": m.get("name", f),
            "gq": gongqu(m.get("name", "")),
            "l1": m.get("level1", ""), "l2": m.get("level2", ""), "l3": m.get("level3", ""),
            "cum": round(cum, 1), "pmax": round(pmax, 1), "snow48": round(snow48, 1),
            "gust": round(gust, 1), "wind": round(wind, 1),
            "tmax": round(tmax, 1), "tmin": round(tmin, 1),
            "appMax": pk48.get("appMax"), "appMin": pk48.get("appMin"),
            "visMin": pk48.get("visMin"),
            "pkdate": pk.get("date"), "pkp": round(pk.get("rainfall") or 0, 1),
            "sev": sev,
            # 48h 峰值（hourly[:48]），供七要素预警判定；不使用整窗 summary 的远端峰值
            "pHourMax": pk48.get("pHourMax"),
            "snowHourMax": pk48.get("snowHourMax"),
            "maxGust": pk48.get("gust"),
            "maxTemp": pk48.get("tmax"),
            "minTemp": pk48.get("tmin"),
            "start": m.get("start_date"),
        })
    return pts


def build_short(pts, n=2):
    """生成「未来 N 天风险」概述（2026-10-09 用户要求：简单明了说清主要项目的风险）。
    结构：①结论句——主要风险类型 + 需重点关注的井位；②按要素分述——量级、集中时段、影响与处置。
    降雨达中雨及以上必须特别说明「严重影响作业」（用户明确要求）。
    所有判定严格基于未来 48 小时（daily[:2] / hourly[:48]），不含第 3 天起的远端预报；
    预警等级按 2026-10-09 五要素阈值，对外只给定性严重度（大雨量级、7级左右大风等），
    不列 mm/h、m/s、℃ 原始阈值数字。"""
    if not pts:
        return "暂无点位数据，暂无法评估。"
    # 48h 内需关注井位（sev>=1）
    risky = [p for p in pts if p.get("sev", 0) >= 1]
    any_risk = any((p.get("pHourMax") or 0) or (p.get("snowHourMax") or 0)
                   or (p.get("gust") or 0) or (p.get("wind") or 0)
                   or (p.get("tmax") is not None) or (p.get("tmin") is not None)
                   or (p.get("visMin") is not None)
                   for p in pts)
    if not risky and not any_risk:
        return f"未来 {n} 天各工区整体平稳，无明显强降雨、大风或极端温度，保持常态监测即可。"

    # 七要素 48h 等级（均为 48h 峰值，非整窗 summary）；统一走 jozzonwx 分级
    r  = max((JW.grade_rain(p.get("pHourMax") or 0) for p in pts), default=0)
    sn = max((JW.grade_snow(p.get("snowHourMax") or 0) for p in pts), default=0)
    g  = max((JW.grade_gust(p.get("gust") or 0) for p in pts), default=0)
    wn = max((JW.grade_wind(p.get("wind") or 0) for p in pts), default=0)
    # 舒适度由体感温度 UTCI 承担（plain 温度只展示）：热侧取 appMax/tmax 较大、冷侧取 appMin/tmin 较小
    th = 0; tl = 0
    for p in pts:
        aM = p.get("appMax"); aM = aM if aM is not None else p.get("tmax")
        aN = p.get("appMin"); aN = aN if aN is not None else p.get("tmin")
        if aM is not None: th = max(th, JW.grade_utci(aM)[0])
        if aN is not None: tl = max(tl, JW.grade_utci(aN)[0])
    vis = max((JW.grade_vis(p.get("visMin")) for p in pts if p.get("visMin") is not None), default=0)

    # 头部点名的井位（2026-10-17 用户口径修正）：
    # 旧写法「红页6HF、悦来1井…等16口井需重点关注」把 sev>=1 全算进来，与页面徽章
    # 「重点关注」（仅 sev==2）同名不同义，用户指出紫台村等被误列入。
    # 现在只点名 sev==2 的井（即徽章真为「重点关注」的那几口）；没有 2 级才退到 1 级取证。
    hi = sorted([p for p in pts if p.get("sev") == 2], key=lambda x: -x["cum"])
    mid = sorted([p for p in pts if p.get("sev") == 1], key=lambda x: -x["cum"])

    # ①结论句：简单明了——主要风险类型 + 需重点关注的井位（不再堆叠工区/区域，避免绕口）
    # 概述只呈现 3 级及以上要素（与物探 index 概述口径一致，小雨、五级风不再提醒）；
    # 降雨按用户规则放宽到中雨及以上（>=2）——中雨即严重影响作业，必须特别说明。
    kinds = []
    if r >= 2:  kinds.append("降雨")
    if sn >= 3: kinds.append("降雪")
    if g >= 3:  kinds.append("大风")
    if wn >= 3: kinds.append("持续大风")
    if th >= 3: kinds.append("高温")
    if tl >= 3: kinds.append("低温")
    if vis >= 3: kinds.append("低能见度")
    kind_txt = "、".join(kinds) if kinds else "无明显灾害性天气"
    # 结论句：只点名徽章真为「重点关注」（sev==2）的井，避免与页面徽章同名不同义
    if hi:
        names = [p["name"] for p in hi[:4]]
        tail = f"等{len(hi)}口井" if len(hi) > 4 else ""
        head = f"未来 {n} 天主要风险为{kind_txt}，其中{'、'.join(names)}{tail}风险最高"
    elif mid:
        names = [p["name"] for p in mid[:3]]
        tail = f"等{len(mid)}口井" if len(mid) > 3 else ""
        head = f"未来 {n} 天主要风险为{kind_txt}，{'、'.join(names)}{tail}相对明显"
    else:
        head = f"未来 {n} 天各工区天气总体平稳，{kind_txt}，暂无高影响天气"

    # ②逐类具体描述：量级 + 集中时段 + 影响与处置，不写原始阈值
    clauses = []
    # —— 降雨（中雨及以上即严重影响作业，须特别说明）——
    cum_max = max(p["cum"] for p in pts)
    if r >= 2 or cum_max >= 10:
        if r >= 4 or cum_max >= 50:
            rl = "暴雨量级"
        elif r >= 3 or cum_max >= 25:
            rl = "大雨量级"
        elif r >= 2 or cum_max >= 10:
            rl = "中雨量级"
        elif r >= 1:
            rl = "小雨"
        else:
            rl = "弱降雨"
        pk = max(pts, key=lambda x: x["cum"])
        pkdate_md = md_label(pk["pkdate"]) if pk.get("pkdate") else ""
        c = f"降雨达{rl}"
        if pkdate_md:
            c += f"（{pkdate_md}前后最集中）"
        if r >= 2:
            # 中雨及以上：明确点出严重影响作业（用户 2026-10-09 规则）
            c += "，中雨及以上将严重影响作业，需防范井场积涝、道路湿滑与运输受阻"
        else:
            c += "，注意井场泥泞与道路湿滑"
        clauses.append(c)
    # —— 大风（3 级及以上才提醒）——
    # 阵风 2026-10-17 新口径：同级比均风高两级风力 → lv1 七级 / lv2 八级 / lv3 十级 / lv4 十二级
    if g >= 3:
        glv = {1: "7级左右", 2: "8级左右", 3: "10级左右", 4: "12级及以上"}[g]
        c = f"阵风{glv}大风"
        if g >= 3:
            c += "，需停止高空与吊装作业，并加固井架、临时设施"
        elif g >= 2:
            c += "，需加固井架、临时设施与高空作业防风"
        else:
            c += "，注意临边与高空作业防风"
        clauses.append(c)
    # —— 降雪（3 级及以上）——
    if sn >= 3:
        clauses.append("高海拔井位有降雪，注意道路结冰与设备防冻")
    # —— 高温（3 级及以上；UTCI 热侧）——
    if th >= 3:
        ttxt = {3: "40℃上下", 4: "46℃上下"}.get(th, "极高温度")
        clauses.append(f"高温（{ttxt}），注意防暑降温与设备散热")
    # —— 低温（3 级及以上；UTCI 冷侧）——
    if tl >= 3:
        ttxt = {3: "零下25℃上下", 4: "零下40℃上下"}.get(tl, "极低温度")
        clauses.append(f"低温（{ttxt}），注意人员防寒与设备防冻保温")
    # —— 均风（3 级及以上，即大风八级 / 17.2m/s 左右）——
    if wn >= 3:
        clauses.append("均风达大风八级左右，注意高空与吊装作业防风、井架与临时设施加固")
    # —— 能见度（3 级及以上，即 <200m）——
    if vis >= 3:
        clauses.append("能见度低于200m，谨慎行车、必要时封路、夜间作业加强照明")

    body = "；".join(clauses)
    if not body:
        return f"{head}。"
    return f"{head}。{body}。"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--datadir", default="engineering/data")
    ap.add_argument("--out", default="")
    ap.add_argument("--days", type=int, default=2, help="汇总天数，默认 2（未来2天/48小时）")
    args = ap.parse_args()

    pts = load_points(args.datadir, args.days)
    if not pts:
        print("ERROR: 未找到任何 kind==point 的 JSON。")
        sys.exit(1)

    short = build_short(pts, args.days)
    start = pts[0].get("start", "")
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    block = f"""# 石油工程点位 · 未来{args.days}天风险概要

> 数据窗口：{start} 起未来 {args.days} 天（Asia/Shanghai）｜生成时间：{now}
> 数据源：engineering/kml/engineering_ta_map.json → jozzon-mcp（九章雷电网）

{short}

## 各点位近 {args.days} 天数据（累计降水 / 单日峰值 / 最大阵风）

| 点位 | 工区 | 累计降水(mm) | 单日峰值(mm/日期) | 最大阵风(m/s) |
| :--- | :--- | :--- | :--- | :--- |
"""
    for p in sorted(pts, key=lambda x: (-x["cum"], x["name"])):
        block += (f"| {p['name']} | {p['gq']} | {p['cum']:.1f} | "
                  f"{p['pkp']:.0f}/{md_label(p['pkdate'])} | {p['gust']:.1f} |\n")

    block += "\n*注：山区微气候可能导致实测与预报偏差，现场以实时观测为准。*\n"

    out = args.out or os.path.join(os.path.dirname(os.path.abspath(args.datadir)), "fengxian_2tian_huizong.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(block)
    print(short)
    print(f"\n[已写出汇总文件] {out}")


if __name__ == "__main__":
    main()
