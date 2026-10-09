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


def sev_of_recent(days, ph=0.0):
    cum = sum((d.get("precip") or 0) for d in days)
    pmax = max((d.get("precip") or 0) for d in days)
    gust = max((d.get("gustMax") or 0) for d in days)
    wind = max((d.get("windMax") or 0) for d in days)
    tmax = max((d.get("tempMax", -99) or -99) for d in days)
    tmin = min((d.get("tempMin", 99) or 99) for d in days)
    # ph = 48h 内最大小时降水（mm/h）：短时强降水须计入，否则日累计小的井位会被误判为无风险
    if pmax >= 80 or gust >= 20.8 or tmax >= 38 or cum >= 150:
        return 3
    if ph >= 10 or pmax >= 50 or gust >= 17.2 or tmax >= 35 or tmin <= -5 or cum >= 80:
        return 2
    if ph >= 5 or pmax >= 12 or wind >= 10.8 or tmin <= 0 or cum >= 20:
        return 1
    return 0


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
        phm = s.get("pHourMax") or 0.0
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
            # 小时级峰值（mm/h），供五要素预警判定（旧数据缺时回退 None → 该要素不触发）
            "pHourMax": s.get("pHourMax"),
            "snowHourMax": s.get("snowHourMax"),
            "maxGust": s.get("maxGust"),
            "maxTemp": s.get("maxTemp"),
            "minTemp": s.get("minTemp"),
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
    """生成「未来 N 天风险」叙述：点名主要风险井位，并逐类说明具体风险（区域、量级、影响）。
    预警判定严格套用 2026-10-09 用户定的五要素阈值，但对外只给定性严重度
    （大雨量级、6-7级大风等），不罗列 mm/h、m/s、℃ 等原始阈值数字。"""
    if not pts:
        return "暂无点位数据，暂无法评估。"
    # 主风险工区：需关注点位最多，其次累计降水最高
    gq_map = {}
    for p in pts:
        gq_map.setdefault(p["gq"], {"pts": [], "n_sev1": 0, "cum": 0.0, "gust": 0.0})
        e = gq_map[p["gq"]]
        e["pts"].append(p)
        if p["sev"] >= 1:
            e["n_sev1"] += 1
        e["cum"] += p["cum"]
        e["gust"] = max(e["gust"], p["gust"])
    main_gq = max(gq_map, key=lambda g: (gq_map[g]["n_sev1"], gq_map[g]["cum"]))
    top = max(gq_map[main_gq]["pts"], key=lambda x: x["cum"])
    gq = main_gq
    area = AREA_MAP.get(gq, "")
    area_txt = f"（{area}）" if area else ""
    cum = top["cum"]
    pkdate = top["pkdate"]
    pkdate_md = md_label(pkdate) if pkdate else ""
    # 最需要关注的井位（按 48h 风险等级 + 累计降水降序）
    wells = top_risk_wells(pts, k=3)
    # 五要素预警等级（用于判定风险类型与严重度，不写阈值数字）
    r  = max((rain_alert(p.get("pHourMax"))   for p in pts), default=0)
    sn = max((snow_alert(p.get("snowHourMax")) for p in pts), default=0)
    g  = max((gust_alert(p.get("maxGust"))    for p in pts), default=0)
    th = max((thigh_alert(p.get("maxTemp"))   for p in pts), default=0)
    tl = max((tlow_alert(p.get("minTemp"))    for p in pts), default=0)

    # 无任何风险：简短收尾
    if not wells and r == 0 and sn == 0 and g == 0 and th == 0 and tl == 0:
        return f"未来 {n} 天各工区整体平稳，无明显强降雨、大风或极端温度，保持常态监测即可。"

    # 首句：点名主要风险井位
    if wells:
        max_sev = max(p["sev"] for p in pts if p.get("sev", 0) >= 1)
        verb = "需重点关注" if max_sev >= 2 else "需关注"
        head = f"未来 {n} 天主要风险在{wells}{verb}"
    else:
        head = f"未来 {n} 天整体风险可控，但个别井位仍需注意"

    # 中段：逐类描述具体风险（定性严重度 + 影响），不写原始阈值
    clauses = []
    # —— 降雨 ——
    if r or cum >= 10:
        if cum >= 50 or r >= 4:
            rl = "暴雨量级"
        elif cum >= 25 or r >= 3:
            rl = "大雨量级"
        elif cum >= 10 or r >= 1:
            rl = "小到中雨"
        else:
            rl = "弱降雨"
        rain_c = f"{gq}工区{area_txt}未来 {n} 天累计降雨可达{rl}"
        if pkdate_md:
            rain_c += f"（{pkdate_md}前后最集中）"
        rain_c += "，山区井场需防范井场积涝、道路湿滑与运输受阻"
        clauses.append(rain_c)
    # —— 大风 ——
    if g:
        glv = {1: "5级左右", 2: "6级左右", 3: "7级左右", 4: "8级及以上"}[g]
        wind_c = f"阵风可达{glv}大风"
        if g >= 2:
            wind_c += "，需加固井架、临时设施与高空作业防风"
        else:
            wind_c += "，注意临边与高空作业防风"
        clauses.append(wind_c)
    # —— 降雪 ——
    if sn:
        clauses.append("高海拔井位有降雪，注意道路结冰与设备防冻")
    # —— 高温 ——
    if th:
        ttxt = {1: "35℃上下", 2: "37℃上下", 3: "40℃上下"}[th]
        clauses.append(f"高温（{ttxt}），注意防暑降温与设备散热")
    # —— 低温 ——
    if tl:
        ttxt = {1: "零下5℃上下", 2: "零下15℃上下", 3: "零下25℃上下"}[tl]
        clauses.append(f"低温（{ttxt}），注意人员防寒与设备防冻保温")

    body = "；".join(clauses)
    return f"{head}：{body}。"


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
