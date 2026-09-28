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


def gongqu(name):
    """取点位名的工区前缀（连续中文字符，遇数字/字母截断）。"""
    run = []
    for ch in name:
        if "一" <= ch <= "鿿":
            run.append(ch)
        else:
            break
    return "".join(run) or name


def sev_of_recent(days):
    cum = sum((d.get("precip") or 0) for d in days)
    pmax = max((d.get("precip") or 0) for d in days)
    gust = max((d.get("gustMax") or 0) for d in days)
    wind = max((d.get("windMax") or 0) for d in days)
    tmax = max((d.get("tempMax", -99) or -99) for d in days)
    tmin = min((d.get("tempMin", 99) or 99) for d in days)
    if pmax >= 80 or gust >= 20.8 or tmax >= 38 or cum >= 150:
        return 3
    if pmax >= 50 or gust >= 17.2 or tmax >= 35 or tmin <= -5 or cum >= 80:
        return 2
    if pmax >= 12 or wind >= 10.8 or tmin <= 0 or cum >= 20:
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
        cum = sum((x.get("precip") or 0) for x in d3)
        pmax = max((x.get("precip") or 0) for x in d3)
        gust = max((x.get("gustMax") or 0) for x in d3)
        wind = max((x.get("windMax") or 0) for x in d3)
        tmax = max((x.get("tempMax", -99) or -99) for x in d3)
        tmin = min((x.get("tempMin", 99) or 99) for x in d3)
        pk = max(d3, key=lambda x: (x.get("precip") or 0))
        sev = sev_of_recent(d3)
        pts.append({
            "name": m.get("name", f),
            "gq": gongqu(m.get("name", "")),
            "l1": m.get("level1", ""), "l2": m.get("level2", ""), "l3": m.get("level3", ""),
            "cum": round(cum, 1), "pmax": round(pmax, 1),
            "gust": round(gust, 1), "wind": round(wind, 1),
            "tmax": round(tmax, 1), "tmin": round(tmin, 1),
            "pkdate": pk.get("date"), "pkp": round(pk.get("precip") or 0, 1),
            "sev": sev,
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
    """生成「未来 N 天风险」短描述：除说明主风险区域外，点名最需要关注的井位。"""
    if not pts:
        return "暂无点位数据，暂无法评估。"
    # 主风险工区：需关注点位最多，其次累计降水最高（不对外列等级）
    gq_map = {}
    for p in pts:
        g = p["gq"]
        if g not in gq_map:
            gq_map[g] = {"pts": [], "n_sev1": 0, "cum": 0}
        gq_map[g]["pts"].append(p)
        if p["sev"] >= 1:
            gq_map[g]["n_sev1"] += 1
        gq_map[g]["cum"] += p["cum"]
    main_gq = max(gq_map, key=lambda g: (gq_map[g]["n_sev1"], gq_map[g]["cum"]))
    top = max(gq_map[main_gq]["pts"], key=lambda x: x["cum"])
    gq = main_gq
    area = AREA_MAP.get(gq, "")
    area_txt = f"（{area}）" if area else ""
    cum = top["cum"]
    pkp = top["pkp"]
    pkdate = top["pkdate"]
    # 远端日（第 n+1 天起）
    far = None
    for p in pts:
        if p.get("start"):
            try:
                dt = datetime.datetime.strptime(p["start"], "%Y-%m-%d") + datetime.timedelta(days=n)
                far = dt.strftime("%Y-%m-%d")
            except Exception:
                pass
            break
    far_lbl = (md_label(far) + "以后") if far else f"第 {n+1} 天起"
    # 显著程度判定（仅用于措辞，不对外列等级）
    gmax_gust = max(p["gust"] for p in pts)
    gmax_tmax = max(p["tmax"] for p in pts)
    if cum < 10 and gmax_gust < 10.8 and gmax_tmax < 35:
        return f"未来 {n} 天各工区整体风险可控，无明显强降雨与大风，保持常态监测即可。"
    if cum >= 50:
        rl = "较强降雨"
    elif cum >= 25:
        rl = "中到大雨"
    elif cum >= 10:
        rl = "小到中雨"
    else:
        rl = ""
    if rl:
        hazard = f"{gq}工区{area_txt}有{rl}（约{cum:.0f}毫米、{md_label(pkdate)}最集中）"
    else:
        hazard = "天气整体平稳"
    # 处置建议：兼顾降水与大风/高温，避免与井位提示自相矛盾
    if cum >= 25:
        rec = "注意井场积水与道路防滑，合理安排作业与运输"
    elif cum >= 10:
        rec = "注意道路湿滑，合理安排出行"
    elif gmax_gust >= 10.8:
        rec = "注意大风防范，加固临时设施"
    elif gmax_tmax >= 35:
        rec = "注意防暑降温与设备散热"
    else:
        rec = "保持常态监测"
    # 最需要关注的井位（按 48h 风险等级 + 累计降水降序）
    wells = top_risk_wells(pts, k=3)
    if wells:
        max_sev = max(p["sev"] for p in pts if p.get("sev", 0) >= 1)
        verb = "需重点关注" if max_sev >= 2 else "需关注"
        well_part = f"其中{wells}{verb}，{rec}"
    else:
        well_part = rec
    return f"未来 {n} 天整体风险可控；{hazard}，{well_part}；{far_lbl}风险视临近预报另行提示。"


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
