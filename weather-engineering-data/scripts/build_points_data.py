#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
weather-engineering-data —— Markdown 点位表 → 逐点天气数据文件（未来 2 周 / 14 天）
===========================================================
输入：钻井平台 / 管线点位汇总 Markdown 表（如 all_points_info.md），
      表头含「点位 / 经度 (DD) / 纬度 (DD)」（可选 一级/二级/三级 作为层级标签）。
动作：解析所有点位坐标 → 一次性批量从 Open-Meteo 拉取「下一整时起未来 2 周 / 14 天」
      逐小时预报（气温/降水/降雨/风速/阵风）→ 为每个点位写出**独立 JSON 数据文件**
      （文件名用拼音，保留数字/字母，如 hongye7-5hf.json）。
输出目录默认 engineering/data/（与井位看板的 *_data.json 同目录，但文件名用拼音且无 _data 后缀，互不冲突；渲染时按 meta.kind=="point" 过滤）。
数据来自 Open-Meteo（免费接口，无需 key；本机带 key 仅做兼容）。timezone=Asia/Shanghai。
"""
import os, sys, json, time, math, argparse, datetime, re
from collections import defaultdict

try:
    from pypinyin import pinyin, Style
    HAVE_PY = True
except Exception:
    HAVE_PY = False

# ---------- 带退避重试的 GET（缓解 Open-Meteo 429） ----------
def http_get_json(url, timeout=60, retries=5, sleep0=2.0):
    import urllib.request, urllib.error
    last = None
    for attempt in range(retries):
        try:
            rq = urllib.request.Request(url, headers={"User-Agent": "workbuddy-weather/1.0"})
            with urllib.request.urlopen(rq, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            last = e
            print(f"  HTTP 重试 {attempt+1}/{retries}: {repr(e)}")
            time.sleep(sleep0 * (2 ** attempt))
    raise last

# ---------- 拼音文件名（避免中文在 CDP/系统间编码问题） ----------
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
    """返回 list[dict]，每项含 name/lon/lat/level1/level2/level3。"""
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    header = None
    for line in lines:
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        # 分隔行（|---|---|）跳过
        if all(re.fullmatch(r":?-+:?", c) for c in cells if c):
            continue
        if header is None:
            # 识别列索引
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
        # 数据行
        try:
            name = cells[header["name"]]
            lon = float(cells[header["lon"]])
            lat = float(cells[header["lat"]])
        except (IndexError, ValueError):
            continue
        if not name:
            continue
        rec = {"name": name, "lon": lon, "lat": lat,
               "level1": cells[header["l1"]] if "l1" in header and len(cells) > header["l1"] else "",
               "level2": cells[header["l2"]] if "l2" in header and len(cells) > header["l2"] else "",
               "level3": cells[header["l3"]] if "l3" in header and len(cells) > header["l3"] else ""}
        rows.append(rec)
    return rows

# ---------- 主流程 ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", default="engineering/kml/all_points_info.md",
                    help="点位汇总 Markdown 表路径（含 点位/经度/纬度 列）")
    ap.add_argument("--datadir", default="engineering/data",
                    help="逐点 JSON 数据文件输出目录（默认 engineering/data）")
    ap.add_argument("--name", default="钻井工程", help="区域/项目标签，写入 meta")
    ap.add_argument("--days", type=int, default=14, help="预报天数，默认 14（未来 2 周，从下一整时起）")
    ap.add_argument("--from-today", action="store_true", help="从当前整点开始（默认从下一整点开始，跳过当前小时剩余时间）")
    ap.add_argument("--apikey", default="6aiF2mXsB3K7YcjT")
    ap.add_argument("--model", default="", help="Open-Meteo 模型，如 ecmwf_ifs04；留空用默认融合模型")
    args = ap.parse_args()

    if not os.path.exists(args.md):
        print(f"ERROR: Markdown 文件不存在: {args.md}")
        sys.exit(1)

    points = parse_md_points(args.md)
    if not points:
        print("ERROR: 未能从 Markdown 解析出任何点位（请检查表头是否含「点位/经度/纬度」）。")
        sys.exit(1)
    print(f"解析到点位 {len(points)} 个，来源: {args.md}")

    # 取数窗口起点：默认「下一整点」开始（跳过当前小时剩余分钟）；
    # --from-today 则从「当前整点」开始。覆盖 --days 个自然日。
    _now = datetime.datetime.now()
    _anchor = _now if args.from_today else (_now + datetime.timedelta(hours=1))
    _start = _anchor.replace(minute=0, second=0, microsecond=0)
    _end = _start + datetime.timedelta(days=args.days - 1)
    START = _start.strftime("%Y-%m-%d")
    END = _end.strftime("%Y-%m-%d")
    START_HOUR = _start.strftime("%Y-%m-%dT%H:00")
    END_HOUR = _end.strftime("%Y-%m-%dT23:00")
    print(f"取数区间: {START} ~ {END}（从 {START_HOUR} 起，timezone=Asia/Shanghai）")

    # 批量取数（12 坐标/批，批间冷却，缓解 429）
    # precipitation=总降水(mm) / rain=雨(mm) / showers=阵雨(mm) / snowfall=降雪(cm)
    # liquid=rain+showers 为「降雨」规范口径；ptype=降水类型码（0无/1降雨/2降雪/3雨夹雪）
    HOURLY = ("temperature_2m,precipitation,rain,showers,snowfall,"
              "wind_speed_10m,wind_gusts_10m")
    BASE = "https://api.open-meteo.com/v1/forecast"
    CH = 12
    locs = []
    for s0 in range(0, len(points), CH):
        chunk = points[s0:s0 + CH]
        lats_s = ",".join(str(p["lat"]) for p in chunk)
        lons_s = ",".join(str(p["lon"]) for p in chunk)
        base_params = (f"latitude={lats_s}&longitude={lons_s}"
                       f"&hourly={HOURLY}"
                       f"&start_date={START}&end_date={END}&start_hour={START_HOUR}&end_hour={END_HOUR}"
                       f"&wind_speed_unit=ms"
                       f"&timezone=Asia%2FShanghai&apikey={args.apikey}")
        url = f"{BASE}?{base_params}" + (f"&models={args.model}" if args.model else "")
        print(f"Fetching 点位 {s0+1}-{s0+len(chunk)}/{len(points)} ...")
        try:
            d = http_get_json(url, timeout=90)
        except Exception as e:
            if args.model:
                print(f"  模型 {args.model} 失败，回退默认融合模型: {repr(e)}")
                d = http_get_json(f"{BASE}?{base_params}", timeout=90)
            else:
                raise
        if isinstance(d, dict):
            d = [d]
        locs.extend(d)
        time.sleep(4.0)
    print(f"返回地点数: {len(locs)}")

    times = [str(t) for t in locs[0]["hourly"]["time"]]
    dailyDates = sorted({t[:10] for t in times})

    def var(loc, key):
        return [float(v) if isinstance(v, (int, float)) else 0.0 for v in loc["hourly"][key]]

    def ptype_of(liq, snow, pr, temp=None):
        """降水类型码：0=无 1=降雨 2=降雪 3=雨夹雪（snowfall 单位 cm，仅以 >0 判有无）
        温度规则（2026-10-08 起）：气温 < 0℃ 一律判「降雪」（液态分量不参与判型）；
        只有气温 ≥ 0℃ 时才可能出现「雨夹雪」（雨雪同现）。temp=None 时退化为纯分量判定。"""
        has_l, has_s = liq > 0.05, snow > 0.01
        if temp is not None and temp < 0.0:
            return 2 if (has_l or has_s or pr > 0.05) else 0
        if has_l and has_s: return 3
        if has_s: return 2
        if has_l: return 1
        return 1 if pr > 0.05 else 0

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

    def daily_for(series_t, series_p, series_l, series_s, series_w, series_g):
        tMinD, tMaxD, pD, lD, sD, wD, gD = {}, {}, {}, {}, {}, {}, {}
        pTempD = {}   # 当日「有降水时段」的最高气温，用于按温度判降水类型
        for t, tv, pv, lv, sv, wv, gv in zip(times, series_t, series_p, series_l,
                                             series_s, series_w, series_g):
            d = t[:10]
            tMinD.setdefault(d, []).append(tv)
            tMaxD.setdefault(d, []).append(tv)
            pD[d] = pD.get(d, 0.0) + max(pv, 0.0)
            lD[d] = lD.get(d, 0.0) + max(lv, 0.0)      # 每日降雨（rain+showers）
            sD[d] = sD.get(d, 0.0) + max(sv, 0.0)      # 每日降雪（cm）
            if pv > 0.05 or lv > 0.05 or sv > 0.01:    # 该时有降水 → 记录气温（取最高）
                pTempD[d] = max(pTempD.get(d, -999.0), tv)
            wD.setdefault(d, []).append(wv)
            gD.setdefault(d, []).append(gv)
        return [
            {"date": d,
             "tempMin": round(min(tMinD[d]), 1),
             "tempMax": round(max(tMaxD[d]), 1),
             "precip": round(pD.get(d, 0.0), 1),
             "liquid": round(lD.get(d, 0.0), 1),
             "snow": round(sD.get(d, 0.0), 1),
             "ptype": ptype_of(lD.get(d, 0.0), sD.get(d, 0.0), pD.get(d, 0.0),
                               pTempD.get(d)),
             "windMax": round(max(wD[d]), 1),
             "gustMax": round(max(gD[d]), 1)}
            for d in dailyDates
        ]

    # 写出逐点 JSON 数据文件
    outdir = os.path.abspath(args.datadir)
    os.makedirs(outdir, exist_ok=True)
    used = {}
    generated = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    for p, loc in zip(points, locs):
        t = var(loc, "temperature_2m")
        pr = var(loc, "precipitation")
        ra = var(loc, "rain")
        sh = var(loc, "showers")
        sn = var(loc, "snowfall")
        liq = [round(a + b, 2) for a, b in zip(ra, sh)]      # 降雨 = 雨 + 阵雨
        w = var(loc, "wind_speed_10m")
        g = var(loc, "wind_gusts_10m")
        daily = daily_for(t, pr, liq, sn, w, g)
        total_precip = round(sum(max(v, 0.0) for v in pr), 1)
        summary = {
            "totalPrecip": total_precip,
            "maxGust": round(max(g), 1),
            "maxWind": round(max(w), 1),
            "minTemp": round(min(t), 1),
            "maxTemp": round(max(t), 1),
            "maxPrecipDay": max(daily, key=lambda x: x["precip"])["date"] if daily else None,
            # 小时级峰值（mm/h）：供 index/summary 套用 2026-10-09 用户定的五要素阈值
            "pHourMax": round(max(pr), 2),                 # 逐小时降水峰值 mm/h
            "snowHourMax": round(max(sn) * 10.0, 2),       # 逐小时降雪峰值 cm/h → mm/h
        }
        # 拼音文件名（本次运行内去重）
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
                "level1": p["level1"], "level2": p["level2"], "level3": p["level3"],
                "lat": p["lat"], "lon": p["lon"],
                "region": args.name,
                "source": os.path.basename(args.md),
                "generated_at": generated,
                "timezone": "Asia/Shanghai",
                "start_date": START, "end_date": END,
                "model": (args.model or "open-meteo 默认融合模型"),
            },
            "hourly": {
                "time": times,
                "temperature_2m": [round(v, 1) for v in t],
                "precipitation": [round(v, 1) for v in pr],
                "rain": [round(v, 1) for v in ra],
                "showers": [round(v, 1) for v in sh],
                "snowfall": [round(v, 1) for v in sn],
                "liquid": [round(v, 1) for v in liq],
                "ptype": [ptype_of(l, s, p, tv) for l, s, p, tv in zip(liq, sn, pr, t)],
                "wind_speed_10m": [round(v, 1) for v in w],
                "wind_gusts_10m": [round(v, 1) for v in g],
            },
            "daily": daily,
            "summary": summary,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        print(f"  ✓ 数据文件: {fn}.json  ({p['name']}, 降水合计 {total_precip}mm, 阵风 {summary['maxGust']}m/s)")
    print(f"DONE → {outdir}（共 {len(points)} 个数据文件）")

if __name__ == "__main__":
    main()
