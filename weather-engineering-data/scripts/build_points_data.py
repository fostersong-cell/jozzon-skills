#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
weather-engineering-data —— Markdown 点位表 → 逐点天气数据文件（未来 2 周 / 14 天）
=================================================================================
2026-10-16 改造：取数源由 Open-Meteo 改为 jozzon-mcp（九章雷电网），按目标区 ta_id 取数。

输入：
  - all_points_info.md（点位 / 经度 / 纬度）
  - engineering_ta_map.json（位于 engineering/kml/；点位名 → 九章目标区 ta_id；含 all_points_info 全字段，
    由用户侧在九章注册后回填 ta_id；兼容旧名 ta_map.json）
动作：解析所有点位 → 按 ta_id 调 jozzon-mcp 拉「未来 2 周 / 14 天」逐小时天气
      → 为每个点位写出独立 JSON 数据文件（拼音文件名，与旧 *_data.json 同目录互不冲突）。
要素（2026-10-16 新定）：
  降雨 rainfall(=rain+showers) / 降雪 snowfall / 阵风 wind_gusts_10m / 均风 wind_speed_10m
  / 温度 temperature_2m / 体感温度 apparent_temperature(UTCI) / 能见度 visibility
分级阈值集中在 weather-common/scripts/jozzonwx.py（本脚本只产出序列与峰值，分级在渲染/汇总侧做）。
"""
import os, sys, json, time, math, argparse, datetime, re

# 共享取数 + 分级模块
_COMMON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "weather-common", "scripts")
if os.path.isdir(_COMMON):
    sys.path.insert(0, os.path.abspath(_COMMON))
import jozzonwx as JW

try:
    from pypinyin import pinyin, Style
    HAVE_PY = True
except Exception:
    HAVE_PY = False

# ---------- 拼音文件名 ----------
_CJK = re.compile(r"[\u4e00-\u9fff]")
def slug(name):
    parts = []
    if HAVE_PY:
        for ch in name:
            if _CJK.match(ch):
                ps = pinyin(ch, style=Style.NORMAL, errors="ignore")
                if ps and ps[0]:
                    parts.append(ps[0][0])
            elif ch.isalnum() or ch in "-_":
                parts.append(ch)
    else:
        parts = [ch for ch in name if ch.isalnum() or ch in "-_"]
    return ("".join(parts).lower() or "point").strip("-_")

# ---------- 解析 Markdown 点位表 ----------
def parse_md_points(path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    header = None
    for line in lines:
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if all(re.fullmatch(r":?-+:?", c) for c in cells if c):
            continue
        if header is None:
            idx = {}
            for i, c in enumerate(cells):
                if "点位" in c: idx["name"] = i
                elif "经度" in c: idx["lon"] = i
                elif "纬度" in c: idx["lat"] = i
                elif "一级" in c: idx["l1"] = i
                elif "二级" in c: idx["l2"] = i
                elif "三级" in c: idx["l3"] = i
            if "name" in idx and "lon" in idx and "lat" in idx:
                header = idx
            continue
        try:
            name = cells[header["name"]]
            lon = float(cells[header["lon"]])
            lat = float(cells[header["lat"]])
        except (IndexError, ValueError):
            continue
        if not name:
            continue
        rows.append({"name": name, "lon": lon, "lat": lat,
                     "level1": cells[header["l1"]] if "l1" in header and len(cells) > header["l1"] else "",
                     "level2": cells[header["l2"]] if "l2" in header and len(cells) > header["l2"] else "",
                     "level3": cells[header["l3"]] if "l3" in header and len(cells) > header["l3"] else ""})
    return rows

def load_ta_map(path):
    """返回 {点位名: ta_id}。兼容两种结构：
    新：{"points":[{..., "点位": .., "ta_id": ..}, ...]}（engineering_ta_map.json）；
    旧：{"井名": ta_id, ...}（ta_map.json）。缺失/无有效返回 {}。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:
        print(f"  ⚠️ ta_map 读取失败（将只处理有 ta_id 的点位）: {repr(e)}")
        return {}
    if isinstance(d, dict) and isinstance(d.get("points"), list):
        out = {}
        for e in d["points"]:
            nm = e.get("点位") or e.get("name")
            if nm:
                out[nm] = e.get("ta_id")
        return out
    return {k: v for k, v in d.items() if not k.startswith("_")}

# ---------- 降水类型码（0无/1降雨/2降雪/3雨夹雪）----------
def ptype_of(rainfall, snowfall, temp=None):
    has_l, has_s = rainfall > 0.05, snowfall > 0.01
    if temp is not None and temp < 0.0:
        return 2 if (has_l or has_s) else 0
    if has_l and has_s: return 3
    if has_s: return 2
    if has_l: return 1
    return 0

# ---------- 主流程 ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", default="engineering/kml/all_points_info.md",
                    help="点位汇总 Markdown 表路径（含 点位/经度/纬度 列）")
    ap.add_argument("--datadir", default="engineering/data",
                    help="逐点 JSON 数据文件输出目录（默认 engineering/data）")
    ap.add_argument("--tamap", default=None,
                    help="点位→ta_id 映射 json；默认 <datadir>/../engineering_ta_map.json（兼容旧名 ta_map.json）")
    ap.add_argument("--name", default="钻井工程", help="区域/项目标签，写入 meta")
    ap.add_argument("--days", type=int, default=14, help="预报天数，默认 14（未来 2 周）")
    ap.add_argument("--from-today", action="store_true", help="从当前整点开始（默认从下一整点开始）")
    ap.add_argument("--timezone", default="Asia/Shanghai")
    args = ap.parse_args()

    if args.tamap is None:
        base = os.path.dirname(os.path.abspath(args.datadir))
        args.tamap = os.path.join(base, "kml", "engineering_ta_map.json")   # ta_map 已移至 kml/

    if not os.path.exists(args.md):
        print(f"ERROR: Markdown 文件不存在: {args.md}")
        sys.exit(1)

    points = parse_md_points(args.md)
    if not points:
        print("ERROR: 未能从 Markdown 解析出任何点位。")
        sys.exit(1)
    print(f"解析到点位 {len(points)} 个，来源: {args.md}")

    ta_map = load_ta_map(args.tamap)
    print(f"ta_map: {len(ta_map)} 条映射，来自 {args.tamap}")

    # 仅处理有 ta_id 的点位（jozzon-mcp 按目标区取数）
    ready, skipped = [], []
    for p in points:
        tid = ta_map.get(p["name"])
        if tid is None:
            skipped.append(p["name"])
            continue
        p2 = dict(p); p2["ta_id"] = int(tid)
        ready.append(p2)
    if skipped:
        print(f"  跳过（无 ta_id，待九章注册后填 ta_map）: {', '.join(skipped)}")
    if not ready:
        print("ERROR: 没有任何点位具备 ta_id，无法取数。请先在九章注册目标区并填入 engineering_ta_map.json。")
        sys.exit(1)
    print(f"可取数点位: {len(ready)} 个")

    forecast_hours = min(args.days * 24, 336)
    past_hours = 0
    print(f"取数窗口: 未来 {forecast_hours} 小时（{args.timezone}），来源 jozzon-mcp")

    # 批量取数（按目标区，jozzon-mcp 无坐标批量接口）
    locs = JW.fetch_region([p["ta_id"] for p in ready],
                           forecast_hours=forecast_hours, past_hours=past_hours,
                           time_zone=args.timezone)
    print(f"返回地点数: {len(locs)}")
    times = [str(t) for t in locs[0]["time"]]
    dailyDates = sorted({t[:10] for t in times})

    def var(loc, key, keep_none=False):
        # keep_none：能见度用 —— x1_visibility 只有前 162h 有值（之后为 null），
        # 落 0 会被误读成「能见度 0 m」，故保留 None（下游一律 `if v and v > 0` 过滤）
        if keep_none:
            return [float(v) if isinstance(v, (int, float)) else None for v in loc.get(key, [])]
        return [float(v) if isinstance(v, (int, float)) else 0.0 for v in loc.get(key, [])]

    def daily_for(t, rf, sn, w, g, apr, vs):
        tMinD, tMaxD, rD, sD, wD, gD, aMinD, aMaxD, vD, pTempD = ({}, {}, {}, {}, {}, {}, {}, {}, {}, {})
        for tt, tv, rv, sv, wv, gv, av, vv in zip(times, t, rf, sn, w, g, apr, vs):
            d = tt[:10]
            (tMinD.setdefault(d, [])).append(tv)
            (tMaxD.setdefault(d, [])).append(tv)
            rD[d] = rD.get(d, 0.0) + max(rv, 0.0)          # 每日降雨（rain+showers）
            sD[d] = sD.get(d, 0.0) + max(sv, 0.0)          # 每日降雪（mm）
            if rv > 0.05 or sv > 0.01:
                pTempD[d] = max(pTempD.get(d, -999.0), tv)
            (wD.setdefault(d, [])).append(wv)
            (gD.setdefault(d, [])).append(gv)
            (aMinD.setdefault(d, [])).append(av)
            (aMaxD.setdefault(d, [])).append(av)
            vD[d] = min(vD.get(d, 1e9), vv) if vv and vv > 0 else vD.get(d, 1e9)
        return [
            {"date": d,
             "tempMin": round(min(tMinD[d]), 1), "tempMax": round(max(tMaxD[d]), 1),
             "rainfall": round(rD.get(d, 0.0), 1), "snowfall": round(sD.get(d, 0.0), 1),
             "ptype": ptype_of(rD.get(d, 0.0), sD.get(d, 0.0), pTempD.get(d)),
             "windMax": round(max(wD[d]), 1), "gustMax": round(max(gD[d]), 1),
             "apparentMin": round(min(aMinD[d]), 1), "apparentMax": round(max(aMaxD[d]), 1),
             "visMin": (round(vD[d]) if vD.get(d, 1e9) < 1e9 else None)}
            for d in dailyDates
        ]

    outdir = os.path.abspath(args.datadir)
    os.makedirs(outdir, exist_ok=True)
    used = {}
    generated = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    start_date = times[0][:10] if times else None
    end_date = times[-1][:10] if times else None

    for p, loc in zip(ready, locs):
        t = var(loc, "temperature_2m")
        rf = var(loc, "rainfall")
        sn = var(loc, "snowfall")
        w = var(loc, "wind_speed_10m")
        g = var(loc, "wind_gusts_10m")
        apr = var(loc, "apparent_temperature")
        vs = var(loc, "visibility", keep_none=True)
        daily = daily_for(t, rf, sn, w, g, apr, vs)
        # 降雪小时峰值（mm/h，jozzon-mcp 已统一 mm 口径）
        snow_h = max(sn) if sn else 0.0
        # 能见度最小（m）
        vis_min = min((v for v in vs if v and v > 0), default=None)
        summary = {
            "totalRainfall": round(sum(max(v, 0.0) for v in rf), 1),
            "maxGust": round(max(g), 1),
            "maxWind": round(max(w), 1),
            "minTemp": round(min(t), 1),
            "maxTemp": round(max(t), 1),
            "minApparent": round(min(apr), 1) if apr else None,
            "maxApparent": round(max(apr), 1) if apr else None,
            "minVis": round(vis_min) if vis_min is not None else None,
            "maxRainfallDay": max(daily, key=lambda x: x["rainfall"])["date"] if daily else None,
            # 小时级峰值（mm/h 或 m/s 或 m）：供 index/summary 套用新分级阈值
            "pHourMax": round(max(rf), 2) if rf else 0.0,
            "snowHourMax": round(snow_h, 2),
            "gustHourMax": round(max(g), 1) if g else 0.0,
        }
        base_slug = slug(p["name"])
        fn = base_slug
        if fn in used:
            used[fn] += 1
            fn = f"{base_slug}-{used[fn]}"
        else:
            used[fn] = 1
        path = os.path.join(outdir, fn + ".json")
        obj = {
            "meta": {
                "kind": "point",
                "name": p["name"],
                "ta_id": p["ta_id"],
                "level1": p["level1"], "level2": p["level2"], "level3": p["level3"],
                "lat": p["lat"], "lon": p["lon"],
                "region": args.name,
                "source": os.path.basename(args.md),
                "generated_at": generated,
                "timezone": args.timezone,
                "start_date": start_date, "end_date": end_date,
                "model": "jozzon-mcp(九章雷电网)",
            },
            "hourly": {
                "time": times,
                "temperature_2m": [round(v, 1) for v in t],
                "rainfall": [round(v, 1) for v in rf],
                "snowfall": [round(v, 1) for v in sn],
                "wind_speed_10m": [round(v, 1) for v in w],
                "wind_gusts_10m": [round(v, 1) for v in g],
                "apparent_temperature": [round(v, 1) for v in apr],
                "visibility": [round(v, 1) if v is not None else None for v in vs],
                "ptype": [ptype_of(rv, sv, tv) for rv, sv, tv in zip(rf, sn, t)],
            },
            "daily": daily,
            "summary": summary,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        print(f"  ✓ 数据文件: {fn}.json  ({p['name']}, ta_id={p['ta_id']}, 降雨合计 {summary['totalRainfall']}mm, 阵风 {summary['maxGust']}m/s)")
    print(f"DONE → {outdir}（共 {len(ready)} 个数据文件；跳过 {len(skipped)} 个无 ta_id 点位）")

if __name__ == "__main__":
    main()
