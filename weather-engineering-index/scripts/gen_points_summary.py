#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_points_summary.py —— 石油工程点位「未来 2 天（48小时）风险汇总」叙事生成器
========================================================================
读取 engineering/data 下所有 meta.kind=="point" 的 JSON（由 build_points_data.py
从 all_points_info.md 生成），按未来 2 天（daily[:2]，即 48 小时）聚合，自动产出一段
约 50 字、平实口吻的「未来 2 天风险」短描述（不罗列等级，与人工口径一致，可一键复制到汇报）。

字段约定（与 build_points_data.py 输出一致）：
  daily[i] = {date, tempMin, tempMax, precip, windMax, gustMax}
定级阈值（与 render_points_html.py 的 sev_of_recent 完全一致）：
  3 高度警惕 : 单日降水>=80 或 阵风>=20.8 或 最高温>=38 或 2日累计>=150
  2 重点关注 : 单日降水>=50 或 阵风>=17.2 或 最高温>=35 或 最低温<=-5 或 2日累计>=80
  1 需关注   : 单日降水>=12 或 最大风>=10.8 或 最低温<=0 或 2日累计>=20
  0 整体适宜 : 其余

口径说明（2026-09-17 固化，同日修订为未来 2 天/48小时）：聚焦「未来 2 天（48小时）可靠预报窗口」，
不把整周（7 天）远期极端值列为主风险；第 3 天起若仍有较高风险，仅一句话「临近时再提示」。
"""
import os, sys, json, argparse, glob, datetime

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

def alert_items(rain_mmh, snow_mmh, gust, tmax, tmin):
    out = []
    r = rain_alert(rain_mmh)
    if r: out.append(RAIN_ALERT[r])
    s = snow_alert(snow_mmh)
    if s: out.append(SNOW_ALERT[s])
    g = gust_alert(gust)
    if g: out.append(GUST_ALERT[g])
    h = thigh_alert(tmax)
    if h: out.append(THIGH_ALERT[h])
    l = tlow_alert(tmin)
    if l: out.append(TLOW_ALERT[l])
    return out


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
    """从单点位 _data.json 取「未来 48 小时（hourly 前 48 个逐时）」峰值，供 48h 风险判定。
    与物探 peaksNear 同源：只用近 48h 窗口，不含第 3 天起的远端预报。
    summary 里的 maxGust/maxTemp/minTemp/pHourMax/snowHourMax 是整窗 14 天峰值，
    不能直接用于「未来 2 天」叙述，否则会把远端大风/高温当成 48h 风险。
    返回 dict：pHourMax / snowHourMax（mm/h）/ gust / tmax / tmin。"""
    h = d.get("hourly", {}) or {}
    t = h.get("time", [])
    n = min(48, len(t)) if t else 0
    precip = h.get("precipitation", []) or []
    snow = h.get("snowfall", []) or []
    pH = round(max(precip[:n]), 2) if (n and precip) else None
    sH = round(max(snow[:n]) * 10.0, 2) if (n and snow) else None
    # 阵风/温度用 daily 前 2 天（与 load_points 的 p['gust'] 口径一致）
    daily = (d.get("daily") or [])[:2]
    g = max((x.get("gustMax", 0) for x in daily), default=0) if daily else None
    tmax = max((x.get("tempMax", -99) for x in daily), default=-99) if daily else None
    tmin = min((x.get("tempMin", 99) for x in daily), default=99) if daily else None
    return {"pHourMax": pH, "snowHourMax": sH, "gust": g, "tmax": tmax, "tmin": tmin}


def sev_of_recent(days, ph=0.0):
    cum = sum((d.get("precip") or 0) for d in days)
    pmax = max((d.get("precip") or 0) for d in days)
    gust = max((d.get("gustMax") or 0) for d in days)
    wind = max((d.get("windMax") or 0) for d in days)
    tmax = max((d.get("tempMax", -99) or -99) for d in days)
    tmin = min((d.get("tempMin", 99) or 99) for d in days)
    # ph = 48h 内最大小时降水（mm/h）：短时强降水须计入，否则日累计小的井位会被误判为无风险
    if pmax >= 80 or gust >= 20.8 or tmax >= 38 or cum >= 150:
        sev = 3
    elif ph >= 10 or pmax >= 50 or gust >= 17.2 or tmax >= 35 or tmin <= -5 or cum >= 80:
        sev = 2
    elif ph >= 5 or pmax >= 12 or wind >= 10.8 or tmin <= 0 or cum >= 20:
        sev = 1
    else:
        sev = 0
    # 用户规则（2026-10-09）：有明显降雨（中雨及以上，即 >=1.5mm/h）即至少定为「需关注」；
    # 降雪、阵风、高/低温仍按各自等级判定，不因这条降雨规则被额外抬级。
    if rain_alert(ph) >= 2:
        sev = max(sev, 1)
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
        cum = sum((x.get("precip") or 0) for x in d3)
        pmax = max((x.get("precip") or 0) for x in d3)
        gust = max((x.get("gustMax") or 0) for x in d3)
        wind = max((x.get("windMax") or 0) for x in d3)
        tmax = max((x.get("tempMax", -99) or -99) for x in d3)
        tmin = min((x.get("tempMin", 99) or 99) for x in d3)
        pk = max(d3, key=lambda x: (x.get("precip") or 0))
        # 48h 峰值：从 hourly[:48] / daily[:2] 现算，绝不用整窗 summary（maxGust 等是 14 天峰值）
        pk48 = peaks_48h(d)
        phm = pk48.get("pHourMax") or 0.0
        sev = sev_of_recent(d3, phm)
        pts.append({
            "name": m.get("name", f),
            "gq": gongqu(m.get("name", "")),
            "l1": m.get("level1", ""), "l2": m.get("level2", ""), "l3": m.get("level3", ""),
            "cum": round(cum, 1), "pmax": round(pmax, 1),
            "gust": round(gust, 1), "wind": round(wind, 1),
            "tmax": round(tmax, 1), "tmin": round(tmin, 1),
            "pkdate": pk.get("date"), "pkp": round(pk.get("precip") or 0, 1),
            "sev": sev,
            # 48h 峰值（hourly[:48] / daily[:2]），供五要素预警判定；不使用整窗 summary 的远端峰值
            "pHourMax": pk48.get("pHourMax"),
            "snowHourMax": pk48.get("snowHourMax"),
            "maxGust": pk48.get("gust"),
            "maxTemp": pk48.get("tmax"),
            "minTemp": pk48.get("tmin"),
            "start": m.get("start_date"),
        })
    return pts


def top_risk_wells(pts, k=3):
    """返回最需要关注的井位名串：按 48h 风险等级 + 累计降水降序取前 k；
    超过 k 个时用「等 N 口井」收尾。无任何风险点（sev>=1）时返回空串。"""
    risky = [p for p in pts if p.get("sev", 0) >= 1]
    if not risky:
        return ""
    risky.sort(key=lambda x: (-x["sev"], -x["cum"]))
    names = [p["name"] for p in risky[:k]]
    if len(risky) > k:
        return "、".join(names) + f"等{len(risky)}口井"
    return "、".join(names)


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
                   or (p.get("gust") or 0) or (p.get("tmax") is not None) or (p.get("tmin") is not None)
                   for p in pts)
    if not risky and not any_risk:
        return f"未来 {n} 天各工区整体平稳，无明显强降雨、大风或极端温度，保持常态监测即可。"

    # 五要素 48h 等级（pHourMax/snowHourMax/gust/tmax/tmin 均为 48h 峰值，非整窗 summary）
    r  = max((rain_alert(p.get("pHourMax"))   for p in pts), default=0)
    sn = max((snow_alert(p.get("snowHourMax")) for p in pts), default=0)
    g  = max((gust_alert(p.get("gust"))        for p in pts), default=0)
    th = max((thigh_alert(p.get("tmax"))       for p in pts), default=0)
    tl = max((tlow_alert(p.get("tmin"))         for p in pts), default=0)

    # 需重点关注井位（前 3，超出用「等 N 口井」）
    wells = top_risk_wells(pts, k=3)

    # ①结论句：简单明了——主要风险类型 + 需重点关注的井位（不再堆叠工区/区域，避免绕口）
    # 概述只呈现 3 级及以上要素（与物探 index 概述口径一致，小雨、五级风不再提醒）；
    # 降雨按用户规则放宽到中雨及以上（>=2）——中雨即严重影响作业，必须特别说明。
    kinds = []
    if r >= 2:  kinds.append("降雨")
    if sn >= 3: kinds.append("降雪")
    if g >= 3:  kinds.append("大风")
    if th >= 3: kinds.append("高温")
    if tl >= 3: kinds.append("低温")
    kind_txt = "、".join(kinds) if kinds else "无明显灾害性天气"
    if wells:
        head = f"未来 {n} 天主要风险为{kind_txt}，{wells}需重点关注"
    else:
        head = f"未来 {n} 天各工区天气总体平稳，{kind_txt}，暂无需重点关注的井位"

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
    # —— 大风（3 级及以上才提醒，五级风不提醒）——
    if g >= 3:
        glv = {1: "5级左右", 2: "6级左右", 3: "7级左右", 4: "8级及以上"}[g]
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
    # —— 高温（3 级及以上）——
    if th >= 3:
        ttxt = {1: "35℃上下", 2: "37℃上下", 3: "40℃上下"}[th]
        clauses.append(f"高温（{ttxt}），注意防暑降温与设备散热")
    # —— 低温（3 级及以上）——
    if tl >= 3:
        ttxt = {1: "零下5℃上下", 2: "零下15℃上下", 3: "零下25℃上下"}[tl]
        clauses.append(f"低温（{ttxt}），注意人员防寒与设备防冻保温")

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
> 数据源：engineering/kml/all_points_info.md → Open-Meteo

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
