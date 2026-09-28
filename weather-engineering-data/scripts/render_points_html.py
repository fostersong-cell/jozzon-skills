#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
render_points_html.py —— 由 engineering/data/*.json（逐点天气数据）渲染「无地图单页看板」
====================================================================================================
输入：engineering/data/*.json（由 build_points_data.py 生成，meta.kind=="point"，未来 2 周 / 14 天窗口）
输出：
  * engineering/html/{拼音}.html —— 每个点位一张独立无地图看板，分 3 个版面（Tab）：
      - 重点关注：重点关注横幅 + 关键指标四宫格 + 风险面板 + 作业影响建议
      - 未来2周：3 个逐日图表（降水柱 / 气温双线 / 阵风·均风双线，服务端预渲染 SVG），
                  **可点击图表选日期**并在图上显示带浅底背景的数值框
      - 未来48小时：逐小时图（**点击 / 拖动图表选时刻**，已无独立时间轴滑块），
                  **图上（g.hread）与图下（#hval）同时显示该时刻各要素值**，
                  日期·时间粗体高亮、要素值为「深色字 + 浅底 pill」

注意：本脚本【不再生成 index.html】。目录总览 index 已拆出为独立技能
      weather-engineering-index（scripts/build_points_index.py），
      重跑点位数据后如需刷新目录页，请单独运行该技能的 build_points_index.py。
风险等级沿用 weather-engineering-html 的 _sev 阈值（0绿/1黄/2橙/3红）。
"""
import os, json, glob, sys, html as _html

SEV_LABEL = {0: "整体适宜", 1: "需关注", 2: "重点关注", 3: "高度警惕"}
SEV_COLOR = {0: "#2E8B57", 1: "#E0A92C", 2: "#E0822C", 3: "#C0392B"}

# ---------- 小时级短时降水阈值（mm/h）----------
# 只作用于「未来 48 小时」口径，与物探看板 weather-wutan-html 的 RAIN_H 完全一致：
#   >2 mm/h 大雨 / >5 mm/h 暴雨 / >10 mm/h 大暴雨
# 「未来 2 周」逐日图与关键指标仍按日累计 25/50mm，两套口径不混用。
RAIN_H = {"heavy": 2.0, "storm": 5.0, "torrent": 10.0}

def rain_hour_label(v):
    """小时级降水的等级文案（供卡片 / 影响建议 / 横幅复用）。"""
    if v >= RAIN_H["torrent"]: return "短时大暴雨"
    if v >= RAIN_H["storm"]:   return "短时暴雨"
    if v >= RAIN_H["heavy"]:   return "短时大雨"
    return "降水"

def phour_max(hourly48):
    """近 48 小时最大小时降水（mm/h）。hourly48 为已截断的前 48 小時逐小时数据。"""
    pr = hourly48.get("precipitation") or []
    return round(max(pr) if pr else 0.0, 1)

# ---------- 风险等级（沿用 weather-engineering-html 的 _sev 阈值） ----------
def sev_of(daily, s):
    pmax = max((d["precip"] for d in daily), default=0)
    gust = s["maxGust"]; tmax = s["maxTemp"]; tmin = s["minTemp"]; wind = s["maxWind"]
    focus = sum(d["precip"] for d in daily if d["precip"] >= 10)
    if pmax >= 80 or gust >= 20.8 or tmax >= 38 or focus >= 150: return 3
    if pmax >= 50 or gust >= 17.2 or tmax >= 35 or tmin <= -5 or focus >= 80: return 2
    if pmax >= 12 or wind >= 10.8 or tmin <= 0 or focus >= 30: return 1
    return 0

def sev_of_recent(daily2, ph=0.0):
    """未来 48 小时风险等级：仅取 daily 前 2 天聚合，套用与 sev_of 相同阈值。
    降水同时看「日累计」与「小时级短时降水」——短时 >10mm/h 按暴雨级给重点关注、>5mm/h 按大雨级给需关注，
    与物探看板 _sev_of 一致。远端（第 3 天起）不作主风险提示。"""
    pmax = max((d["precip"] for d in daily2), default=0)
    gust = max((d["gustMax"] for d in daily2), default=0)
    wind = max((d["windMax"] for d in daily2), default=0)
    tmax = max((d["tempMax"] for d in daily2), default=99)
    tmin = min((d["tempMin"] for d in daily2), default=99)
    cum = sum(d["precip"] for d in daily2)
    if pmax >= 80 or gust >= 20.8 or tmax >= 38 or cum >= 150: return 3
    if ph >= 10 or pmax >= 50 or gust >= 17.2 or tmax >= 35 or tmin <= -5 or cum >= 80: return 2
    if ph >= 5 or pmax >= 12 or wind >= 10.8 or tmin <= 0 or cum >= 20: return 1
    return 0

def recent_desc(daily3, ph=0.0):
    d0, d2 = daily3[0]["date"][5:], daily3[-1]["date"][5:]
    cum = round(sum(d["precip"] for d in daily3), 1)
    pmax = max((d["precip"] for d in daily3), default=0)
    gust = max((d["gustMax"] for d in daily3), default=0)
    parts = [f"{d0}~{d2} 累计降水 {cum}mm（单日最大 {pmax}mm）"]
    if ph > 0:
        parts.append(f"最大小时降水 {ph}mm/h（{rain_hour_label(ph)}）")
    if gust >= 10.8:
        parts.append(f"阵风最大 {gust}m/s")
    return "；".join(parts) + "。远端（第 3 天起）预报不确定性较大，临近时再提示。"

def _near_summary(daily2, ph=0.0):
    """由 daily 前 2 天（=未来 48 小时窗口）聚合出 summary 字段，供「重点提示」Tab 使用。"""
    return {
        "totalPrecip": round(sum(d["precip"] for d in daily2), 1),
        "pHourMax": ph,                 # 48h 内最大小时降水（mm/h），与 totalPrecip 并列展示
        "maxGust": round(max(d["gustMax"] for d in daily2), 1),
        "maxTemp": round(max(d["tempMax"] for d in daily2), 1),
        "minTemp": round(min(d["tempMin"] for d in daily2), 1),
        "maxWind": round(max(d["windMax"] for d in daily2), 1),
    }

def far_alert(daily):
    """未来 2~14 天（第 3 天起，远端）重大极端天气提示：仅当出现「重大」级别才返回文案，否则 None。
    判定阈值与物探看板一致：暴雨≥50mm / 阵风≥17.2m/s（≥8 级） / 高温≥35°C / 严寒≤-5°C。"""
    far = daily[2:]
    if not far:
        return None
    items = []
    big_rain = [d for d in far if d["precip"] >= 50]
    if big_rain:
        f0, f1 = big_rain[0]["date"][5:], big_rain[-1]["date"][5:]
        span = f"{f0}~{f1}" if f0 != f1 else f0
        items.append(f"{span} 暴雨（单日最大 {max(d['precip'] for d in big_rain)}mm）")
    g = [d for d in far if d["gustMax"] >= 17.2]
    if g:
        items.append(f"阵风最大 {max(d['gustMax'] for d in g)}m/s（≥8 级）")
    t = [d for d in far if d["tempMax"] >= 35]
    if t:
        items.append(f"高温 {max(d['tempMax'] for d in t)}°C")
    c = [d for d in far if d["tempMin"] <= -5]
    if c:
        items.append(f"严寒 {min(d['tempMin'] for d in c)}°C")
    return "；".join(items) if items else None

def risk_of(daily, s):
    pmax = max((d["precip"] for d in daily), default=0)
    if s["maxGust"] >= 17.2 or s["maxTemp"] >= 35 or pmax >= 50: return "danger"
    if pmax >= 25 or s["maxWind"] >= 10.8 or s["minTemp"] <= 0: return "warn"
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
    return sw(PT_FILL[1], "降雨") + sw(PT_FILL[2], "降雪") + sw(PT_FILL[3], "雨夹雪")

def svg_bars(dates, values, color, h=160, w=680, sid="", days=None, unit="mm", label="降水", ptypes=None):
    left, right, top, bot = 42, 12, 14, 30
    x0, x1, y0, y1 = left, w - right, top, h - bot
    vmin = 0.0                                     # 基线恒为 0：不再向下 pad 出负值（否则 0mm 也会被画成约 13px 的柱子）
    vmax = max(values + [1]) * 1.15                # 顶部留 15% 余量，便于柱顶数值标注
    def X(i): return x0 + (x1 - x0) * (i + 0.5) / len(dates)
    def Y(v): return y1 - (v - vmin) / (vmax - vmin) * (y1 - y0)
    bw = (x1 - x0) / len(dates) * 0.55
    payload = {"kind": "bar", "n": len(dates), "x0": x0, "x1": x1, "top": y0, "bot": y1,
               "w": w, "h": h, "unit": unit, "days": days or dates,
               "ptypes": list(ptypes or []),
               "series": [{"name": label, "color": color, "vals": values}]}
    dp = _html.escape(json.dumps(payload, ensure_ascii=False), quote=True)
    attrs = f'id="{sid}" class="dchart"' if sid else ""
    p = [f'<svg {attrs} data-payload="{dp}" viewBox="0 0 {w} {h}" width="100%" preserveAspectRatio="xMinYMin meet" style="display:block">']
    for g in range(4):
        gv = vmax * g / 3; gy = Y(gv)
        p.append(f'<line x1="{x0}" y1="{gy:.1f}" x2="{x1}" y2="{gy:.1f}" stroke="#ececec"/>')
        glab = f"{gv:.0f}" if vmax >= 10 else f"{gv:.1f}"
        p.append(f'<text x="{x0-5}" y="{gy+3:.1f}" text-anchor="end" font-size="12" fill="#999">{glab}</text>')
    for i, (d, v) in enumerate(zip(dates, values)):
        bx = X(i) - bw / 2
        pt = ptypes[i] if (ptypes and i < len(ptypes)) else 0
        if v > 0 or pt:                                 # 无降水不画柱；降雪水当量不足 0.1mm 时保留最小柱以承载类型图标
            bh = max(y1 - Y(v), 3.0)                     # 小值也保证 3px 可见高度
            bcolor = PT_FILL.get(pt, PT_FILL_FB)         # 按降水类型着色：降雨蓝 / 降雪青 / 雨夹雪紫
            p.append(f'<rect x="{bx:.1f}" y="{y1-bh:.1f}" width="{bw:.1f}" height="{bh:.1f}" fill="{bcolor}" rx="2"/>')
            # 小值保留一位小数（避免 0.3mm 被标成「0」）；微量降雪折合不足 0.1mm 时标「<0.1」
            lab = (f"{v:.0f}" if v >= 10 else f"{v:.1f}") if v > 0 else "<0.1"
            lab_y = y1 - bh - 4
            p.append(f'<text x="{X(i):.1f}" y="{lab_y:.1f}" text-anchor="middle" font-size="11" fill="#444">{lab}</text>')
        p.append(f'<text x="{X(i):.1f}" y="{h-9}" text-anchor="middle" font-size="11" fill="#888">{d[5:]}</text>')
    p.append('</svg>')
    return "".join(p)

def svg_lines(dates, series, h=160, w=680, sid="", days=None, unit=""):
    left, right, top, bot = 42, 12, 14, 30
    x0, x1, y0, y1 = left, w - right, top, h - bot
    allv = [v for _, vals, _ in series for v in vals]
    vmin, vmax = _scale(min(allv), max(allv))
    def X(i): return x0 + (x1 - x0) * i / max(len(dates) - 1, 1)
    def Y(v): return y1 - (v - vmin) / (vmax - vmin) * (y1 - y0)
    payload = {"kind": "line", "n": len(dates), "x0": x0, "x1": x1, "top": y0, "bot": y1,
               "w": w, "h": h, "unit": unit, "days": days or dates,
               "series": [{"name": nm, "color": cl, "vals": vs} for nm, vs, cl in series]}
    dp = _html.escape(json.dumps(payload, ensure_ascii=False), quote=True)
    attrs = f'id="{sid}" class="dchart"' if sid else ""
    p = [f'<svg {attrs} data-payload="{dp}" viewBox="0 0 {w} {h}" width="100%" preserveAspectRatio="xMinYMin meet" style="display:block">']
    for g in range(4):
        gv = vmin + (vmax - vmin) * g / 3; gy = Y(gv)
        p.append(f'<line x1="{x0}" y1="{gy:.1f}" x2="{x1}" y2="{gy:.1f}" stroke="#ececec"/>')
        p.append(f'<text x="{x0-5}" y="{gy+3:.1f}" text-anchor="end" font-size="12" fill="#999">{gv:.0f}</text>')
    for name, vals, color in series:
        pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(vals))
        p.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2"/>')
        for i, v in enumerate(vals):
            p.append(f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="2.6" fill="{color}"/>')
            offset_y = -7 if Y(v) < (y0+y1)/2 else 12
            p.append(f'<text x="{X(i):.1f}" y="{Y(v)+offset_y:.1f}" text-anchor="middle" font-size="10" fill="{color}" font-weight="700">{v:.1f}</text>')
    for i, d in enumerate(dates):
        p.append(f'<text x="{X(i):.1f}" y="{h-9}" text-anchor="middle" font-size="11" fill="#888">{d[5:]}</text>')
    return "".join(p)

# ---------- 文案生成 ----------
def alert_desc(daily, s, ph=0.0):
    parts = []
    focus = [d for d in daily if d["precip"] >= 10]
    if focus:
        f0, f1 = focus[0]["date"][5:], focus[-1]["date"][5:]
        tot = round(sum(d["precip"] for d in focus), 1)
        span = f"{f0}~{f1}" if f0 != f1 else f0
        parts.append(f"{span} 连续降雨（累计 {tot}mm）")
    if ph >= RAIN_H["heavy"]:
        parts.append(f"{rain_hour_label(ph)}最大小时降水 {ph}mm/h")
    if s["maxGust"] >= 10.8:
        parts.append(f"阵风最大 {s['maxGust']}m/s")
    if s["maxTemp"] >= 32:
        parts.append(f"最高温 {s['maxTemp']}°C")
    if s["minTemp"] <= 0:
        parts.append(f"最低温 {s['minTemp']}°C（结冰风险）")
    if not parts:
        parts.append("未来 48 小时天气整体平稳，无明显极端天气")
    return "主要关注：" + "；".join(parts) + "。建议据此调整作业安排。"

def impact_bullets(daily, s, ph=0.0):
    out = []
    focus = [d for d in daily if d["precip"] >= 10]
    pmax = max((d["precip"] for d in daily), default=0)
    if focus:
        tot = round(sum(d["precip"] for d in focus), 1)
        out.append(f"<b>降水泥泞</b>：连续降雨累计 {tot}mm，井场 / 管沟道路泥泞、设备基础易沉降，加强排水与铺垫，重型车辆限行。")
    if ph >= RAIN_H["torrent"]:
        out.append(f"<b>短时大暴雨</b>：最大小时降水 {ph}mm/h（>10mm/h），地面积水快速上涨、管沟与井场排水瞬时超负荷，低洼段设备应提前撤离或垫高，暂停涉水作业。")
    elif ph >= RAIN_H["storm"]:
        out.append(f"<b>短时暴雨</b>：最大小时降水 {ph}mm/h（>5mm/h），井场局部积水、设备基础可能被冲刷，加强排水、电缆接头包覆防水，重型车辆避开低洼路段。")
    elif ph >= RAIN_H["heavy"]:
        out.append(f"<b>短时大雨</b>：最大小时降水 {ph}mm/h（>2mm/h），降水强度明显、道路湿滑泥泞，作业面注意防滑防淹，排水沟提前疏通。")
    if s["maxGust"] >= 17.2:
        out.append(f"<b>大风 / 阵风</b>：阵风最大 {s['maxGust']}m/s（≥8 级），吊装与高处作业需停工避风，加固井架、棚架与临时设施。")
    elif s["maxGust"] >= 10.8 or s["maxWind"] >= 10.8:
        out.append(f"<b>大风 / 阵风</b>：阵风最大 {s['maxGust']}m/s，高处作业注意系挂，零星吊装避开阵风时段。")
    if s["maxTemp"] >= 35:
        out.append(f"<b>高温</b>：最高温 {s['maxTemp']}°C，防暑降温、避开正午露天作业、设备过热防护与电池管理。")
    elif s["minTemp"] <= 0:
        out.append(f"<b>低温 / 结冰</b>：最低温 {s['minTemp']}°C，人员保暖、道路与设备防滑、备用电源。")
    if pmax >= 25:
        out.append(f"<b>行车</b>：降雨集中（单日最大 {pmax}mm），山区道路湿滑、能见度下降，谨慎行车、必要时封路。")
    if not out:
        out.append("<b>整体适宜</b>：天气平稳，可按计划推进各项作业；山区小气候仍建议以现场实测为准。")
    return out

def risk_cards(daily, s, ph=0.0):
    pmax = max((d["precip"] for d in daily), default=0)
    cards = []
    if s["maxGust"] >= 17.2:
        cards.append(("danger", "大风 / 阵风", "预警", f"阵风最大 {s['maxGust']}m/s（≥8 级），吊装 / 高处作业停工避风。"))
    elif s["maxGust"] >= 10.8 or s["maxWind"] >= 10.8:
        cards.append(("warn", "大风 / 阵风", "注意", f"阵风最大 {s['maxGust']}m/s，高处作业系挂、避开阵风时段。"))
    else:
        cards.append(("ok", "大风 / 阵风", "安全", f"阵风最大 {s['maxGust']}m/s，无大风风险。"))
    # 降水卡：日累计与小时级短时降水双判据（>2 大雨 / >5 暴雨 / >10 大暴雨，仅 48h 口径），
    # 分级与物探看板 build_dashboard.py 的降水卡片保持完全一致。
    if ph >= RAIN_H["torrent"] or pmax >= 50:
        cards.append(("danger", "降水 / 泥泞", "预警",
            f"单日最大降水 {pmax}mm" + (f"、最大小时降水 {ph}mm/h（{rain_hour_label(ph)}）" if ph >= RAIN_H["heavy"] else "")
            + "，井场泥泞、积水风险高。"))
    elif ph >= RAIN_H["storm"] or pmax >= 25:
        what = (f"最大小时降水 {ph}mm/h（短时暴雨，>5mm/h）" if ph >= RAIN_H["storm"]
                else f"单日最大降水 {pmax}mm（大雨）")
        cards.append(("warn", "降水 / 泥泞", "注意",
            what + "，井场局部积水、排水压力骤增，设备防雨防潮、道路湿滑降速。"))
    elif ph >= RAIN_H["heavy"]:
        cards.append(("warn", "短时大雨 / 泥泞", "注意",
            f"48 小时日累计降雨不大，但出现 {ph}mm/h 的短时大雨（>2mm/h），短时积水与便道湿滑明显。低洼与管沟段注意排水、车辆降速，设备防雨防潮。"))
    else:
        cards.append(("ok", "降水 / 泥泞", "安全",
            f"48 小时无明显短时强降水，最大小时降水 {ph}mm/h，单日最大 {pmax}mm，无明显泥泞风险。"))
    if s["maxTemp"] >= 35:
        cards.append(("danger", "高温", "预警", f"最高温 {s['maxTemp']}°C，防暑降温。"))
    elif s["minTemp"] <= 0:
        cards.append(("warn", "低温 / 结冰", "注意", f"最低温 {s['minTemp']}°C，结冰 / 霜冻风险。"))
    else:
        cards.append(("ok", "气温", "适宜", f"气温区间 {s['minTemp']}~{s['maxTemp']}°C，体感适宜。"))
    if pmax >= 25:
        cards.append(("warn", "行车 / 能见度", "注意", "降雨集中，山区道路湿滑、能见度下降。"))
    else:
        cards.append(("ok", "行车 / 能见度", "提示", "道路条件良好，常规行车注意。"))
    return cards

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
.hval {background:#fff; border:1px solid #eef1f4; border-radius:10px; padding:9px 11px; font-size:12.5px; color:#33414f; box-shadow:0 1px 4px rgba(0,0,0,.06); margin-top:8px; line-height:2.0;}
/* 日期·时间：粗体高亮（全页唯一时间读数） */
.hval .t {font-weight:900; font-size:14.5px; color:#C0392B; margin-right:9px; font-variant-numeric:tabular-nums; letter-spacing:.2px;}
/* 要素值：深色粗体字 + 同色系浅底 pill（底色浅、字色深，文字永不被盖住） */
.hval b {font-weight:900; font-size:12.5px; display:inline-block; line-height:1.5; padding:1.5px 8px; border-radius:6px;}
.hval b.tv {color:#8A4B00; background:#FBEAD3;}
.hval b.pv {color:#0D47A1; background:#D8E9FA;}
.hval b.wv {color:#0F5B4C; background:#D9EFE7;}
.hval b.gv {color:#8A2A0E; background:#FBE0D6;}
/* 已选日期：行内标签（不单独占一行），内联在「未来 2 周逐日天气」标题行末尾 */
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
        '    precip:' + json.dumps(hourly["precipitation"]) + ',\n'
        '    ptype:' + json.dumps(hourly.get("ptype") or [0] * n) + ',\n'
        '    wind:' + json.dumps(hourly["wind_speed_10m"]) + ',\n'
        '    gust:' + json.dumps(hourly["wind_gusts_10m"]) + '};\n'
        '  var n=CH.times.length;\n'
        '  var svg=document.getElementById("hchart");\n'
        '  function el(t,a){var e=document.createElementNS(NS,t);for(var k in a)e.setAttribute(k,a[k]);return e;}\n'
        '  function txt(x,y,s,anc,col,sz){var e=el("text",{x:x,y:y,"text-anchor":anc||"end","font-size":sz||9,fill:col||"#9aa"});e.textContent=s;return e;}\n'
        '  var PT_TXT={0:"",1:"降雨",2:"降雪",3:"雨夹雪"};\n'
        '  var PT_FILL={1:"#2E86DE",2:"#5DD6E8",3:"#B07CD6"}; var PT_FB="#9DB4C8";\n'
        '  var tMax=Math.max.apply(null,CH.temp), tMin=Math.min.apply(null,CH.temp);\n'
        '  var tLo=Math.min(tMin,0)-2, tHi=tMax+2;\n'
        '  var wMax=Math.max.apply(null,CH.wind.concat(CH.gust).concat([1]));\n'
        '  var wHi=wMax*1.15;\n'
        '  var pMax=Math.max.apply(null,CH.precip.concat([0.1]));\n'
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
        '  for(var i=0;i<n;i++){ if(CH.precip[i]>0.05 || CH.ptype[i]){var bx=x(i)-bw/2, bh=Math.max(CH.bot-yP(CH.precip[i]),3); var pcol=(PT_FILL[CH.ptype[i]]||PT_FB); svg.appendChild(el("rect",{x:bx,y:CH.bot-bh,width:bw,height:bh,fill:pcol,rx:1}));} }\n'
        '  // 小时级短时降水阈值线（大雨 2 / 暴雨 5 / 大暴雨 10 mm/h，与物探看板 RAIN_H 一致）\n'
        '  var PTH=[{v:2,c:"#E0822C",t:"大雨 2"},{v:5,c:"#C0392B",t:"暴雨 5"},{v:10,c:"#7B1F14",t:"大暴雨 10"}];\n'
        '  for(var qi=0;qi<PTH.length;qi++){ if(PTH[qi].v>pMax) continue; var py2=yP(PTH[qi].v);\n'
        '    svg.appendChild(el("line",{x1:CH.left,y1:py2,x2:CH.right,y2:py2,stroke:PTH[qi].c,"stroke-width":1.1,"stroke-dasharray":"5 4",opacity:.7}));\n'
        '    svg.appendChild(txt(CH.right-5,py2-4,PTH[qi].t+" mm/h","end",PTH[qi].c,10.5)); }\n'
        '  // 气温线：粗实线 + 数据点\n'
        '  var tPts=""; for(var i=0;i<n;i++) tPts+=x(i).toFixed(1)+","+yT(CH.temp[i]).toFixed(1)+" ";\n'
        '  svg.appendChild(el("polyline",{points:tPts.trim(),fill:"none",stroke:"#E0822C","stroke-width":2.8,"stroke-linejoin":"round"}));\n'
        '  for(var i=0;i<n;i+=6){ svg.appendChild(el("circle",{cx:x(i).toFixed(1),cy:yT(CH.temp[i]).toFixed(1),r:2.2,fill:"#E0822C",stroke:"#fff","stroke-width":1})); }\n'
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
        '  function cw(t){var s=0;for(var k=0;k<t.length;k++){s+=(t.charCodeAt(k)>255?11.6:6.4);}return s;}\n'
        '  function paintRead(i){\n'
        '    while(rbox.firstChild) rbox.removeChild(rbox.firstChild);\n'
        '    var ptS=(PT_TXT[CH.ptype[i]]||"");\n'
        '    var rows=[["降水 ",CH.precip[i]+" mm/h"+(ptS?" "+ptS:""),"#0D47A1"],["气温 ",CH.temp[i]+" ℃","#8A4B00"],["阵风 ",CH.gust[i]+" m/s","#8A2A0E"],["均风 ",CH.wind[i]+" m/s","#0F5B4C"]];\n'
        '    var bw=0,j; for(j=0;j<rows.length;j++){bw=Math.max(bw,cw(rows[j][0])+cw(rows[j][1]));} bw+=22;\n'
        '    var lh=16,pady=6,bh=rows.length*lh+pady*2;\n'
        '    var sx=x(i); var bx=sx+12; if(bx+bw>CH.right) bx=sx-12-bw; if(bx<CH.left) bx=CH.left;\n'
        '    var by=CH.top+26;\n'
        '    rbox.appendChild(el("rect",{x:bx,y:by,width:bw,height:bh,rx:6,fill:"rgba(255,255,255,.96)",stroke:"#C0392B","stroke-width":1.2}));\n'
        '    for(j=0;j<rows.length;j++){\n'
        '      var ty=by+pady+12+j*lh;\n'
        '      rbox.appendChild(el("rect",{x:bx+6,y:ty-11,width:cw(rows[j][0])+cw(rows[j][1])+8,height:15,rx:5,fill:HTINT[rows[j][2]]||"#EEF2F5"}));\n'
        '      var lb=el("text",{x:bx+10,y:ty,"font-size":11.5,fill:"#3A4146"}); lb.textContent=rows[j][0]; rbox.appendChild(lb);\n'
        '      var vv=el("text",{x:bx+10+cw(rows[j][0]),y:ty,"font-size":11.5,fill:rows[j][2],"font-weight":"900"}); vv.textContent=rows[j][1]; rbox.appendChild(vv);\n'
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
        '    valBox.innerHTML=\'<span class="t">\'+fmt(CH.times[i])+\'</span>降水 <b class="pv">\'+CH.precip[i]+\' mm/h\'+(ptS?\' \'+ptS:\'\')+\'</b> 气温 <b class="tv">\'+CH.temp[i]+\'℃</b> 阵风 <b class="gv">\'+CH.gust[i]+\' m/s</b> 均风 <b class="wv">\'+CH.wind[i]+\' m/s</b>\';\n'
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

# 「未来 2 周」三个静态图的点选交互：点击选日期 → 红色竖线 + 浅底 pill 数值框（图表 DOM 不重建）
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
  function cw(t){ var s=0; for(var i=0;i<t.length;i++){ s+=(t.charCodeAt(i)>255?11.6:6.4); } return s; }
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
      for(var j=0;j<p.series.length;j++){ var s=p.series[j], tTxt=s.name+" "+s.vals[DAY_SEL]+" "+p.unit;
        if(p.kind==="bar" && p.ptypes && p.ptypes[DAY_SEL]){ var p2=p.ptypes[DAY_SEL];
          tTxt+=" "+(p2===1?"降雨":p2===2?"降雪":p2===3?"雨夹雪":""); }
        rows.push({t:tTxt, c:s.color}); }
      var bw=0; for(var j2=0;j2<rows.length;j2++){ bw=Math.max(bw,cw(rows[j2].t)); } bw+=20;
      var lh=15, pady=6, bh=rows.length*lh+pady*2;
      var bx=sx+10; if(bx+bw>p.x1) bx=sx-10-bw; if(bx<p.x0) bx=p.x0;
      var by=p.top+2;
      g.appendChild(el("rect",{x:bx,y:by,width:bw,height:bh,rx:6,fill:"rgba(255,255,255,.96)",stroke:"#C0392B","stroke-width":1.2}));
      for(var m=0;m<rows.length;m++){
        var ty=by+pady+11+m*lh;
        g.appendChild(el("rect",{x:bx+6,y:ty-11,width:cw(rows[m].t)+10,height:14.5,rx:5,fill:tintOf(rows[m].c)}));
        var tx=el("text",{x:bx+11,y:ty,"font-size":11.5,fill:deepOf(rows[m].c),"font-weight":"900"});
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
    precip = [d["precip"] for d in daily]
    ptypes = [d.get("ptype", 0) for d in daily]        # 0无 / 1降雨 / 2降雪 / 3雨夹雪
    tmin = [d["tempMin"] for d in daily]; tmax = [d["tempMax"] for d in daily]
    wmax = [d["windMax"] for d in daily]; gmax = [d["gustMax"] for d in daily]
    chart_precip = svg_bars(dates, precip, "#4A90D9", sid="dchart-precip", days=dates,
                            unit="mm", label="降水", ptypes=ptypes)
    chart_temp = svg_lines(dates, [("最高温", tmax, "#E0822C"), ("最低温", tmin, "#2E7DA8")],
                           sid="dchart-temp", days=dates, unit="℃")
    chart_wind = svg_lines(dates, [("阵风", gmax, "#C0392B"), ("均风", wmax, "#7E57C2")],
                           sid="dchart-wind", days=dates, unit="m/s")
    cards = risk_cards(daily, s, ph)
    cards_html = "".join(
        f'<div class="rc {c[0]}"><span class="tag">{c[2]}'
        + (f"（{rain_hour_label(ph)}）" if "泥泞" in c[1] and ph >= RAIN_H["heavy"] else "")
        + f'</span>'
        f'<div class="rt">{c[1]}</div><div class="rb">{c[3]}</div></div>' for c in cards)
    adv = "".join(f"<li>{b}</li>" for b in impact_bullets(daily, s, ph))
    sub = " · ".join([x for x in [l1, l2, l3] if x])
    # 未来 48 小时（近 2 天）口径：重点提示 Tab 的主口径
    near = daily[:2]
    sNear = _near_summary(near, ph)
    far = far_alert(daily)
    if far:
        far_html = (f'<div class="card" style="border-left:4px solid #C0392B;margin-bottom:12px">'
                    f'<div class="chart-h" style="margin:0 0 6px;color:#C0392B">未来 2~14 天重大极端天气提示</div>'
                    f'<div class="rc danger"><div class="rb">{far}。远端预报不确定性较大，临近时请关注属地最新预警。</div></div></div>')
    else:
        far_html = ('<div class="card" style="border-left:4px solid #2E8B57;margin-bottom:12px">'
                    '<div class="rc ok"><div class="rb">未来 2~14 天暂无明显重大极端天气'
                    '（暴雨≥50mm / 阵风≥17.2 / 高温≥35 / 严寒≤-5），临近时再提示。</div></div></div>')
    # 未来 48 小时逐小时图：仅取前 48 个小时
    hourly48 = {k: (v[:48] if isinstance(v, list) else v) for k, v in hourly.items()}
    n_hour = len(hourly48.get("time", []))
    near_start = near[0]["date"] if near else rec.get("start_date", "")
    html = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name} · 天气看板</title><style>{CSS}</style></head>
<body class="sev{sev3}">
<div class="topbar"><div class="topbar-l"><a href="index.html" class="backlink" id="backLink">&larr; 返回总览</a><script>var b=document.getElementById('backLink');if(new URLSearchParams(location.search).get('from')!=='index'&&b)b.style.display='none';</script></div><div class="topbar-r"><a href="https://leidian.wang" class="extlink" target="_blank" rel="noopener">北斗天气风险治理平台 ↗</a></div></div>
<h1>{name}</h1>
<div class="unit">{sub}</div>
<div class="sub">未来 2 周逐小时预报 · <b>{rec['start_date']} ~ {rec['end_date']}</b>　{rec['lon']:.2f}°E {rec['lat']:.2f}°N</div>
<div class="tabs">
<button class="tab active" data-tab="focus">重点提示</button>
<button class="tab" data-tab="hourly">未来48小时</button>
<button class="tab" data-tab="daily">未来2周</button>
</div>

<div class="panel" id="tab-focus">
<div class="alert"><div class="t"><span class="dot"></span>{SEV_LABEL[sev3]}</div>
<div class="d">{alert_desc(near, sNear, ph)}</div></div>
<div class="card" style="border-left:4px solid {SEV_COLOR[sev3]};margin-bottom:12px">
<div class="chart-h" style="margin:0 0 6px;color:{SEV_COLOR[sev3]}">未来 48 小时风险焦点</div>
<div class="rc {'danger' if sev3>=3 else 'warn' if sev3>=1 else 'ok'}"><div class="rb">{recent_desc(daily3, ph) if daily3 else ''}</div></div>
</div>
{far_html}
<div class="grid">
<div class="kpi"><div class="v">{sNear['totalPrecip']}</div><div class="l">48h降水 mm</div></div>
<div class="kpi"><div class="v">{sNear['maxGust']}</div><div class="l">48h最大阵风 m/s</div></div>
<div class="kpi"><div class="v">{sNear['maxTemp']}</div><div class="l">48h最高温 °C</div></div>
<div class="kpi"><div class="v">{sNear['minTemp']}</div><div class="l">48h最低温 °C</div></div>
</div>
<div class="card"><h2><span class="dot" style="background:var(--sev)"></span>风险面板</h2>{cards_html}</div>
<div class="card"><h2><span class="dot" style="background:var(--sev)"></span>作业影响与建议</h2>
<ul class="adv">{adv}</ul></div>
</div>

<div class="panel" id="tab-hourly" style="display:none">
<div class="card"><h2><span class="dot" style="background:var(--sev)"></span>未来 48 小时逐小时</h2>
<div class="legend">仅展示未来 48 小时（{near_start} 起）。<b>点击或拖动图表</b>任意位置选择时刻，即时显示该时刻各要素数值（左轴 气温°C / 右轴 风 m/s，柱 降水 mm/h；无独立时间轴）。柱颜色＝降水类型：{ptype_legend_html()}</div>
<svg id="hchart" viewBox="0 0 760 340" width="100%" preserveAspectRatio="xMinYMin meet" style="display:block;touch-action:none;cursor:crosshair"></svg>
<div id="hval" class="hval"></div>
</div>
</div>

<div class="panel" id="tab-daily" style="display:none">
<div class="card"><h2><span class="dot" style="background:var(--sev)"></span>未来 2 周逐日天气<span id="dayInfo"></span></h2>
<div class="legend"><b>点击任意图表选择日期</b>，图上即时显示该日各要素具体数值（再点同处取消；图表本身不动）</div>
<div class="chart-h">逐日降水（mm）</div>
<div class="legend">柱颜色＝降水类型：{ptype_legend_html()}</div>{chart_precip}
<div class="chart-h">逐日气温（°C）</div>
<div class="legend"><i style="background:#E0822C"></i>最高温<i style="background:#2E7DA8"></i>最低温</div>{chart_temp}
<div class="chart-h">逐日阵风 / 均风（m/s）</div>
<div class="legend"><i style="background:#C0392B"></i>阵风（日最大）<i style="background:#7E57C2"></i>均风（日最大）</div>{chart_wind}
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
        ph = phour_max(hourly48)
        sev3 = sev_of_recent(daily3, ph)
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
