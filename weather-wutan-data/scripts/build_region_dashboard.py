# -*- coding: utf-8 -*-
"""
物探采集点/区域2周天气看板生成器 —— 区域版（可交互 HTML，默认不导 PDF）

与单点版区别:
  - 输入 KML 自动识别三种类型：采集点(多个 <Placemark><Point>，按点直接取数、不采样) /
    多边形边框(面，按 --grid km 网格采样 + 质心) / 线要素(测线，等距采样 + 中点)
  - 用 Open-Meteo 多坐标接口分批拉取所有采样点「下一整时起未来 2 周（14天）」逐小时预报（可选 --model ecmwf_ifs04 高分辨率）
  - 输出以"区域"为单位: 最坏情况包络(逐时最低温/最高降水/最大风)、连续降雨窗口；并为每个采样点计算逐日序列供交互查询
  - 看板内含 canvas 地形图(Open-Meteo 高程接口 + 高程色带 + 山体阴影 + 等高线，计曲线加粗) + 参考网格 + 采样点 + 风险区(径向渐变红/橙光斑)
  - 顶部仅保留一个"重点关注"卡片，按极端天气严重程度(0绿/1黄/2橙/3红)变色；其下依次是关键指标、地图与联动图表、物探作业影响与建议
  - 富媒体交互：点击地图任意采样点，地图下方同一卡片内立即展开该点未来2周逐要素曲线/柱状图(气温/降水/风速可勾选叠加)；降水图阈值动态取 max(10mm, niceCeil(数据最大值))
  - 默认仅出交互式 HTML（--no-pdf）；如需 PDF 去掉该开关，Chrome 无头导出窄页大字体含中文 PDF，文件名 {项目名}采集点/工区/测线{日期}.pdf

用法:
  python build_region_dashboard.py --name "大关项目" --kml "采集点.kml" --no-pdf --outdir "."

"""
import argparse, json, subprocess, os, sys, time, base64, io, urllib.request, urllib.parse, math
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET

def http_get_json(url, timeout=60, retries=5, sleep0=2.0):
    """带退避重试的 GET，缓解 Open-Meteo 429/5xx 限流。"""
    import urllib.error
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

ap = argparse.ArgumentParser()
ap.add_argument("--name", required=True, help="项目名称，如 大关项目")
ap.add_argument("--kml", required=True, help="工区边框 KML 文件路径")
ap.add_argument("--outdir", default=".", help="输出目录")
ap.add_argument("--grid", type=float, default=6.0, help="网格间距 km，默认 6（越细采样点越多，贴合 EC 分辨率）")
ap.add_argument("--days", type=int, default=14, help="预报天数，默认 14（未来 2 周，从下一整时起）")
ap.add_argument("--apikey", default="6aiF2mXsB3K7YcjT")
ap.add_argument("--chrome", default="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
ap.add_argument("--model", default="", help="Open-Meteo 模型，如 ecmwf_ifs04（ECMWF 4km 高分辨率）；留空用默认融合模型")
ap.add_argument("--maxpts", type=int, default=150, help="采样点数量上限，超过则自动加大间隔，避免报文体量过大/接口限流")
ap.add_argument("--no-pdf", action="store_true", help="仅生成交互式 HTML，不导出 PDF")
args = ap.parse_args()

_now = datetime.now()
today = _now.strftime("%Y-%m-%d")
# 取数窗口起点：默认「下一整点」开始（跳过当前小时剩余分钟），覆盖 --days 个自然日。
_anchor = _now + timedelta(hours=1)
_start = _anchor.replace(minute=0, second=0, microsecond=0)
_end = _start + timedelta(days=args.days - 1)
START_DATE = _start.strftime("%Y-%m-%d")
END_DATE = _end.strftime("%Y-%m-%d")
START_HOUR = _start.strftime("%Y-%m-%dT%H:00")
END_HOUR = _end.strftime("%Y-%m-%dT23:00")
base = os.path.abspath(args.outdir)
os.makedirs(base, exist_ok=True)

# ---------- 1. 解析 KML（支持 Point 采集点 / Polygon 边框 / LineString 测线） ----------
KNS = "{http://www.opengis.net/kml/2.2}"
tree = ET.parse(args.kml); root = tree.getroot()
poly = []; line = []; line_name = ""
for pm in root.iter(KNS + "Polygon"):
    ring = pm.find(KNS + "outerBoundaryIs/" + KNS + "LinearRing")
    txt = ring.find(KNS + "coordinates").text.strip()
    for part in txt.split():
        lon, lat, *_ = part.split(",")
        poly.append((float(lon), float(lat)))
if poly:
    if poly[0] != poly[-1]:
        poly.append(poly[0])
    print(f"KML 多边形顶点数: {len(poly)-1}")
for pm in root.iter(KNS + "Placemark"):
    ls = pm.find(KNS + "LineString")
    if ls is None:
        continue
    nm = pm.find(KNS + "name")
    if nm is not None and nm.text:
        line_name = nm.text.strip()
    txt = ls.find(KNS + "coordinates").text.strip()
    for part in txt.split():
        lon, lat, *_ = part.split(",")
        line.append((float(lon), float(lat)))
    print(f"KML 线要素顶点数: {len(line)} 名称: {line_name or '(未命名)'}")

is_line = bool(line) and not bool(poly)

# 采集点(Point)：KML 由多个 <Placemark><Point> 构成（如炮点/检波点等数据采集点）
pts = []; pt_names = []
for pm in root.iter(KNS + "Placemark"):
    pt = pm.find(KNS + "Point")
    if pt is None:
        continue
    c = pt.find(KNS + "coordinates")
    if c is None or not c.text or not c.text.strip():
        continue
    lon, lat, *_ = c.text.strip().split(",")
    nm = pm.find(KNS + "name")
    pts.append((float(lon), float(lat)))
    pt_names.append(nm.text.strip() if (nm is not None and nm.text) else "")
if pts:
    print(f"KML 采集点(Point)数量: {len(pts)}")
is_points = bool(pts) and not bool(poly) and not bool(line)
is_line = bool(line) and not bool(poly) and not is_points

def inside(x, y, poly):
    n = len(poly); c = False; j = n - 1
    for i in range(n):
        xi, yi = poly[i]; xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            c = not c
        j = i
    return c

def distkm(a, b):
    dlat = (b[1] - a[1]) * 111.0
    dlon = (b[0] - a[0]) * 111.0 * math.cos(math.radians((a[1] + b[1]) / 2))
    return math.hypot(dlat, dlon)

def compass_dir(dx_km, dy_km):
    """dx_km 向东为正, dy_km 向北为正 → 8 方位中文(用于面/多边形采样点相对工区中心的方向)。"""
    if abs(dx_km) < 1e-6 and abs(dy_km) < 1e-6:
        return ""
    ang = math.degrees(math.atan2(dx_km, dy_km))  # 0=北, 90=东
    if ang < 0:
        ang += 360
    COMPASS = ["北", "东北", "东", "东南", "南", "西南", "西", "西北"]
    return COMPASS[int((ang + 22.5) // 45) % 8]

verts = line if is_line else (pts if is_points else poly)
lons = [p[0] for p in verts]; lats = [p[1] for p in verts]
minlon, maxlon, minlat, maxlat = min(lons), max(lons), min(lats), max(lats)
lat0 = (minlat + maxlat) / 2
lonkm = (maxlon - minlon) * 111.0 * math.cos(math.radians(lat0))
latkm = (maxlat - minlat) * 111.0
if is_points:
    print(f"采集点范围 约 {lonkm:.1f}km(东西) x {latkm:.1f}km(南北)，共 {len(pts)} 个采集点")
elif is_line:
    total_km = sum(distkm(line[i-1], line[i]) for i in range(1, len(line)))
    print(f"测线长度 约 {total_km:.1f} km")
else:
    print(f"工区范围 约 {lonkm:.1f}km(东西) x {latkm:.1f}km(南北)")

# 采样间距自动保护：超过 maxpts 则自动加粗，避免报文体量过大/接口限流
def _estimate_pts(grid):
    if is_points:
        return len(pts)
    if is_line:
        return max(2, int(total_km / grid) + 2)
    return max(1, int((lonkm / grid) * (latkm / grid) * 0.6) + 1)
G = args.grid
_est0 = _estimate_pts(G)
if not is_points and _est0 > args.maxpts:
    G = G * math.sqrt(_est0 / args.maxpts)
    print(f"采样点估算 {_est0} > 上限 {args.maxpts}，网格自动加粗至 {G:.1f} km")
grid_used = round(G, 1)

# 文件名：采集点 / 测线 / 工区
suffix = "采集点" if is_points else ("测线" if is_line else "工区")
html_path = os.path.join(base, f"{args.name}{suffix}.html")
pdf_path = os.path.join(base, f"{args.name}{suffix}{today}.pdf")

# ---------- 1.5 高程采样(地形图底图用) ----------
area_km2 = lonkm * latkm
E_STEP_KM = max(2.0, math.sqrt(area_km2 / 900.0))
edlon = E_STEP_KM / (111.0 * math.cos(math.radians(lat0)))
edlat = E_STEP_KM / 111.0
print(f"高程网格步长 {E_STEP_KM:.2f} km (~{int(area_km2/(E_STEP_KM*E_STEP_KM))} 点)")
e_cols = int((maxlon - minlon) / edlon) + 1
e_rows = int((maxlat - minlat) / edlat) + 1
e_lats, e_lons = [], []
for i in range(e_rows):
    for j in range(e_cols):
        e_lats.append(round(minlat + edlat * i, 5))
        e_lons.append(round(minlon + edlon * j, 5))
print(f"Fetching elevation grid {e_cols}x{e_rows} = {e_cols*e_rows} pts (chunked)")
elevGrid = None
try:
    elevs = []
    B = 60  # 每批坐标数，避免 URL 过长 414
    for s in range(0, len(e_lats), B):
        la = e_lats[s:s+B]; lo = e_lons[s:s+B]
        u = ("https://api.open-meteo.com/v1/elevation?latitude="
             + ",".join(str(v) for v in la) + "&longitude="
             + ",".join(str(v) for v in lo))
        ed = http_get_json(u, timeout=60)
        elevs.extend(float(v) if isinstance(v, (int, float)) else 0.0 for v in ed["elevation"])
        time.sleep(1.2)  # 礼貌限速，避免 429
    minE, maxE = min(elevs), max(elevs)
    print(f"高程范围 {minE:.0f} ~ {maxE:.0f} m")
    elevGrid = {"cols": e_cols, "rows": e_rows, "minlon": minlon, "maxlon": maxlon,
                "minlat": minlat, "maxlat": maxlat, "stepLon": edlon, "stepLat": edlat,
                "values": [round(v, 1) for v in elevs], "minE": round(minE, 1), "maxE": round(maxE, 1)}
except Exception as e:
    print("elevation fetch FAILED (降级为无地形底图):", repr(e))

# 采样点
samples = []
cum = []          # 仅线模式：各采样点距 line[0] 的沿线累计 km
if is_points:
    # 采集点模式：直接用 KML 里的 Point 坐标，不做网格采样
    samples = [(round(x, 4), round(y, 4)) for x, y in pts]
    cum = [0.0] * len(samples)
elif is_line:
    # 沿测线按 ~grid km 等距取点，并包含起终点
    prev = list(line[0])
    samples.append((round(prev[0], 4), round(prev[1], 4)))
    cum.append(0.0)
    acc = 0.0; i = 1
    while i < len(line):
        cur = line[i]; seg = distkm(prev, cur)
        if seg < 1e-9:
            i += 1; continue
        if acc + seg >= G:
            step = G - acc
            f = step / seg
            np_ = (prev[0] + (cur[0] - prev[0]) * f, prev[1] + (cur[1] - prev[1]) * f)
            samples.append((round(np_[0], 4), round(np_[1], 4)))
            cum.append(round(cum[-1] + step, 3))
            prev = np_; acc = 0.0
        else:
            acc += seg; i += 1
    if distkm(prev, line[-1]) > G * 0.4:
        samples.append((round(line[-1][0], 4), round(line[-1][1], 4)))
        cum.append(round(total_km, 3))
    # 测线中点作为中心锚点
    mid_d = total_km / 2.0; acc = 0.0; mid = line[0]; mid_cum = 0.0
    for i in range(1, len(line)):
        acc += distkm(line[i-1], line[i])
        if acc >= mid_d:
            mid = line[i]; mid_cum = round(acc, 3); break
    samples.append((round(mid[0], 4), round(mid[1], 4)))
    cum.append(mid_cum)
    north_is_start = line[0][1] >= line[-1][1]   # 北端 = 纬度较大一端
else:
    # 网格采样(落在多边形内)
    dlat = G / 111.0
    dlon = G / (111.0 * math.cos(math.radians(lat0)))
    x = minlon
    while x <= maxlon + 1e-9:
        y = minlat
        while y <= maxlat + 1e-9:
            if inside(x, y, poly):
                samples.append((round(x, 4), round(y, 4)))
            y += dlat
        x += dlon
    # 质心(工区中心锚点)
    cx = sum(lons) / len(lons); cy = sum(lats) / len(lats)
    samples.append((round(cx, 4), round(cy, 4)))
    cum = [0.0] * len(samples)   # 多边形模式不使用
print(f"采样点(含中心/中点): {len(samples)}")

# ---------- 2. 多坐标批量拉取 ----------
# precipitation=总降水(mm) / rain=雨(mm) / showers=阵雨(mm) / snowfall=降雪(cm)
# liquid=rain+showers 为「降雨」规范口径；ptype=降水类型码（0无/1降雨/2降雪/3雨夹雪）
HOURLY = ("temperature_2m,precipitation,rain,showers,snowfall,"
          "wind_speed_10m,wind_gusts_10m")
BASE = "https://api.open-meteo.com/v1/forecast"
locs = []
CH = 12  # 每批坐标数，批间冷却，缓解 429
time.sleep(12)  # 高程请求后冷却，避免触发预报接口限流
if args.model:
    print(f"使用模型: {args.model}（失败自动回退默认融合模型）")
for s0 in range(0, len(samples), CH):
    chunk = samples[s0:s0+CH]
    lats_s = ",".join(str(s[1]) for s in chunk)
    lons_s = ",".join(str(s[0]) for s in chunk)
    base_params = (f"latitude={lats_s}&longitude={lons_s}"
              f"&hourly={HOURLY}"
              f"&start_date={START_DATE}&end_date={END_DATE}&start_hour={START_HOUR}&end_hour={END_HOUR}"
              f"&wind_speed_unit=ms"
              f"&timezone=Asia%2FShanghai&apikey={args.apikey}")
    url = f"{BASE}?{base_params}" + (f"&models={args.model}" if args.model else "")
    print(f"Fetching 采样点 {s0+1}-{s0+len(chunk)}/{len(samples)} ...")
    try:
        d = http_get_json(url, timeout=90)
    except Exception as e:
        if args.model:
            print(f"  模型 {args.model} 请求失败，回退默认融合模型: {repr(e)}")
            d = http_get_json(f"{BASE}?{base_params}", timeout=90)
        else:
            raise
    if isinstance(d, dict):
        d = [d]
    locs.extend(d)
    time.sleep(4.0)  # 批间冷却
print(f"返回地点数: {len(locs)}")

times = [str(t) for t in locs[0]["hourly"]["time"]]
n = len(times)

def var(loc, key):
    return [float(v) if isinstance(v, (int, float)) else 0.0 for v in loc["hourly"][key]]

# 每点各要素序列
per = {k: [var(loc, k) for loc in locs] for k in
       ("temperature_2m", "precipitation", "rain", "showers", "snowfall",
        "wind_speed_10m", "wind_gusts_10m")}
# 「降雨」规范口径 = 雨 + 阵雨
per["liquid"] = [[round(r + s, 2) for r, s in zip(per["rain"][p], per["showers"][p])]
                 for p in range(len(locs))]

def ptype_of(liq, snow, pr):
    """降水类型码：0=无 1=降雨 2=降雪 3=雨夹雪（snowfall 单位 cm，仅以 >0 判有无）"""
    has_l, has_s = liq > 0.05, snow > 0.01
    if has_l and has_s: return 3
    if has_s: return 2
    if has_l: return 1
    return 1 if pr > 0.05 else 0

per["ptype"] = [[ptype_of(per["liquid"][p][t], per["snowfall"][p][t],
                          per["precipitation"][p][t]) for t in range(n)]
                for p in range(len(locs))]

# 区域逐时包络
def envelope(arrs, agg):
    return [agg(arrs[p][t] for p in range(len(arrs))) for t in range(n)]
temp_min = envelope(per["temperature_2m"], min)
temp_max = envelope(per["temperature_2m"], max)
precip_max = envelope(per["precipitation"], max)
rain_max = envelope(per["rain"], max)
shower_max = envelope(per["showers"], max)        # 阵雨包络（mm）
snow_max = envelope(per["snowfall"], max)         # 降雪包络（cm）
liquid_max = envelope(per["liquid"], max)         # 降雨包络 = rain + showers（mm）
wind_max = envelope(per["wind_speed_10m"], max)
gust_max = envelope(per["wind_gusts_10m"], max)

# 逐点日降水 + 峰值
from collections import defaultdict
daily_per_point = []
peaks_per_point = []
for p in range(len(locs)):
    d = defaultdict(float)
    for t, v in zip(times, per["precipitation"][p]):
        d[t[:10]] += v
    daily = sorted(d.items())
    daily_per_point.append(daily)
    tmax = max(per["temperature_2m"][p]); tmin = min(per["temperature_2m"][p])
    gmax = max(per["wind_gusts_10m"][p]); wmax = max(per["wind_speed_10m"][p])
    pmax_day = max(daily, key=lambda x: x[1])[0] if daily else None
    pmax = max((v for _, v in daily), default=0)
    peaks_per_point.append(dict(tmax=tmax, tmin=tmin, gustMax=gmax, windMax=wmax,
                                pMax=round(pmax, 1), pMaxDay=pmax_day))

# 每点逐日序列（交互式「逐要素查询」用）
dailyDates = sorted({t[:10] for t in times})
def point_daily(p):
    tMinD, tMaxD, pD, lD, sD, wD, gD = {}, {}, {}, {}, {}, {}, {}
    for t, tv, pv, lv, sv, wv, gv in zip(times,
            per["temperature_2m"][p], per["precipitation"][p], per["liquid"][p],
            per["snowfall"][p], per["wind_speed_10m"][p], per["wind_gusts_10m"][p]):
        d = t[:10]
        (tMinD.setdefault(d, [])).append(tv)
        (tMaxD.setdefault(d, [])).append(tv)
        pD[d] = pD.get(d, 0.0) + max(pv, 0.0)
        lD[d] = lD.get(d, 0.0) + max(lv, 0.0)     # 每日降雨（rain+showers）
        sD[d] = sD.get(d, 0.0) + max(sv, 0.0)     # 每日降雪（cm）
        (wD.setdefault(d, [])).append(wv)
        (gD.setdefault(d, [])).append(gv)
    return {
        "tempMin": [round(min(tMinD[d]), 1) for d in dailyDates],
        "tempMax": [round(max(tMaxD[d]), 1) for d in dailyDates],
        "precip":  [round(pD.get(d, 0.0), 1) for d in dailyDates],
        "ptype":   [ptype_of(lD.get(d, 0.0), sD.get(d, 0.0), pD.get(d, 0.0))
                    for d in dailyDates],
        "liquid":  [round(lD.get(d, 0.0), 1) for d in dailyDates],
        "snow":    [round(sD.get(d, 0.0), 1) for d in dailyDates],
        "windMax": [round(max(wD[d]), 1) for d in dailyDates],
        "gustMax": [round(max(gD[d]), 1) for d in dailyDates],
    }
point_series = [point_daily(p) for p in range(len(locs))]

# 区域日降水(各点逐日最大值再取区最大) + 区域峰值
daily_dates = [t[:10] for t in times[:n:24]]  # 近似日列表
# 更准确的逐日: 用第一点时间取整
day_set = sorted({t[:10] for t in times})
region_daily = []
for day in day_set:
    v = max((dict(daily_per_point[p]).get(day, 0.0) for p in range(len(locs))), default=0.0)
    region_daily.append({"date": day, "p": round(v, 1)})
focus_days = [x for x in region_daily if x["p"] >= 10]
focus_total = round(sum(x["p"] for x in focus_days), 1)
peak = max(focus_days, key=lambda x: x["p"]) if focus_days else None

P = {
    "tmax": max(pp["tmax"] for pp in peaks_per_point),
    "tmin": min(pp["tmin"] for pp in peaks_per_point),
    "gustMax": max(pp["gustMax"] for pp in peaks_per_point),
    "windMax": max(pp["windMax"] for pp in peaks_per_point),
    "pHourMax": max(envelope(per["precipitation"], max)),
    "pMaxDay": peak["date"] if peak else None,
    "pMax": peak["p"] if peak else 0,
    "focusTotal": focus_total,
    "focusStart": focus_days[0]["date"] if focus_days else None,
    "focusEnd": focus_days[-1]["date"] if focus_days else None,
}

# 极端天气分级（"重点关注"背景版变色依据）：0绿 1黄 2橙 3红
def _sev():
    if P["pMax"] >= 80 or P["gustMax"] >= 20.8 or P["tmax"] >= 38 or P["focusTotal"] >= 150:
        return 3
    if P["pMax"] >= 50 or P["gustMax"] >= 17.2 or P["tmax"] >= 35 or P["tmin"] <= -5 or P["focusTotal"] >= 80:
        return 2
    if P["pMax"] >= 25 or P["windMax"] >= 10.8 or P["tmin"] <= 0 or P["focusTotal"] >= 30:
        return 1
    return 0
SEV = _sev()
SEV_LABEL = {0: "整体适宜", 1: "需关注", 2: "重点关注", 3: "高度警惕"}[SEV]

# 风险点(按各点自身判定)
def risk_of(pp):
    # 风速单位 m/s：8级≈17.2, 6级≈10.8
    if pp["gustMax"] >= 17.2 or pp["tmax"] >= 35 or pp["pMax"] >= 50:
        return "danger"
    if pp["pMax"] >= 25 or pp["windMax"] >= 10.8 or pp["tmin"] <= 0:
        return "warn"
    return "ok"
points_out = []
for i, s in enumerate(samples):
    pp = peaks_per_point[i]
    # 大致位置标注
    if is_points:
        loc = pt_names[i] if (i < len(pt_names) and pt_names[i]) else f"采集点 #{i+1}"
    elif i == len(samples) - 1:
        loc = "测线中点" if is_line else "工区中心"
    elif is_line:
        dnorth = cum[i] if north_is_start else (total_km - cum[i])
        loc = f"距北端 {dnorth:.0f}km"
    else:
        dx = (s[0] - cx) * 111.0 * math.cos(math.radians(lat0))
        dy = (s[1] - cy) * 111.0
        d = math.hypot(dx, dy)
        comp = compass_dir(dx, dy)
        loc = (comp + f"方向 · 距中心 {d:.0f}km") if comp else f"工区中心附近 {d:.0f}km"
    points_out.append({
        "idx": i, "lon": s[0], "lat": s[1],
        "isCenter": (False if is_points else (i == len(samples) - 1)),
        "risk": risk_of(pp), "loc": loc,
        "tmax": round(pp["tmax"], 1), "tmin": round(pp["tmin"], 1),
        "gustMax": round(pp["gustMax"], 1), "windMax": round(pp["windMax"], 1),
        "pMax": pp["pMax"], "pMaxDay": pp["pMaxDay"],
        "series": point_series[i],
    })

# 采集点模式：地图范围用采集点包围盒矩形（HTML 据此计算范围，但不画边框）
if is_points:
    _poly_out = [[round(x, 4), round(y, 4)] for x, y in
                 [(minlon, minlat), (maxlon, minlat), (maxlon, maxlat), (minlon, maxlat), (minlon, minlat)]]
else:
    _poly_out = [[round(x, 4), round(y, 4)] for x, y in poly]

payload = {
    "meta": {"name": args.name, "gridKm": grid_used, "lonkm": round(lonkm, 1),
             "latkm": round(latkm, 1), "npts": len(samples),
             "kind": "points" if is_points else ("line" if is_line else "polygon"),
             "lineKm": round(total_km, 1) if is_line else None,
             "lineName": line_name if is_line else "",
             "start": times[0][:10], "end": times[-1][:10], "gen": today,
             "sev": SEV, "sevLabel": SEV_LABEL,
             "model": args.model or "open-meteo 默认融合模型",
             "dailyDates": dailyDates},
    "polygon": _poly_out,
    "line": [[round(x, 4), round(y, 4)] for x, y in line],
    "isLine": is_line,
    "points": points_out,
    "elevGrid": elevGrid,
    "hourly": {"time": times, "tempMin": temp_min, "tempMax": temp_max,
               "precipMax": precip_max, "rainMax": rain_max,
               "showerMax": shower_max, "snowMax": snow_max, "liquidMax": liquid_max,
               "windMax": wind_max, "gustMax": gust_max},
    "daily": region_daily,
    "peaks": P,
}
DATA_JSON = json.dumps(payload, ensure_ascii=False)

# ---------- 3. HTML 模板(区域版) ----------
TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>__TITLE__</title>
<style>
  /*__FONT_FACE__*/
  :root{
    --bg:#F6F4F0; --card:#FFFFFF; --line:#EAE6DF;
    --ink:#242A2E; --sub:#6B7378;
    --teal:#1F7A6B; --amber:#E0822C; --danger:#C0392B; --ok:#2E8B57;
    --shadow:0 1px 3px rgba(0,0,0,.06),0 6px 16px rgba(0,0,0,.05);
  }
  *{box-sizing:border-box;-webkit-tap-highlight-color:transparent;}
  html,body{margin:0;padding:0;}
  body{
    font-family:"CJKLocal",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif;
    background:var(--bg); color:var(--ink); line-height:1.5; font-size:16px;
    padding:14px 14px calc(28px + env(safe-area-inset-bottom));
    max-width:430px; margin:0 auto;
  }
  header{margin-bottom:12px;}
  header h1{font-size:19px;margin:0 0 2px;font-weight:700;}
  header .meta{font-size:12px;color:var(--sub);}
  .card{background:var(--card);border:1px solid var(--line);border-radius:14px;
    padding:14px;margin-bottom:12px;box-shadow:var(--shadow);}
  .card h2{font-size:16px;margin:0 0 10px;font-weight:700;display:flex;align-items:center;gap:8px;}
  .card h2 .dot{width:9px;height:9px;border-radius:50%;background:var(--teal);}
  .alert{border-radius:14px;padding:14px;margin-bottom:12px;color:#fff;}
  .alert.ok{background:linear-gradient(135deg,#2E8B57,#1F7A6B);}
  .alert.warn{background:linear-gradient(135deg,#E0822C,#C0392B);}
  .alert .t{font-size:15px;font-weight:700;display:flex;align-items:center;gap:8px;}
  .alert .d{font-size:13px;margin-top:6px;opacity:.96;}
  .alert .big{font-size:24px;font-weight:800;margin-top:4px;}
  .stats{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;}
  .stat{background:#FBFAF7;border:1px solid var(--line);border-radius:10px;padding:10px 12px;}
  .stat .k{font-size:12px;color:var(--sub);}
  .stat .v{font-size:22px;font-weight:700;margin-top:2px;}
  .stat .v small{font-size:12px;font-weight:500;color:var(--sub);}
  .chart-wrap{width:100%;overflow:hidden;}
  svg.chart{width:100%;height:auto;display:block;}
  .mapbox{position:relative;width:100%;aspect-ratio:680/1210;background:#ECE7DF;border-radius:10px;overflow:hidden;}
  .mapbox canvas,.mapbox svg{position:absolute;inset:0;width:100%;height:100%;}
  .elevbar{display:inline-block;width:84px;height:10px;border-radius:3px;vertical-align:middle;
    background:linear-gradient(90deg,#2f6b3a,#6fae5a,#c8be82,#b07a44,#8a5a30,#cdbfa0);}
  .legend{display:flex;flex-wrap:wrap;gap:10px;font-size:12px;color:var(--sub);margin-top:8px;}
  .legend i{display:inline-block;width:14px;height:4px;border-radius:2px;vertical-align:middle;margin-right:5px;}
  .imp{border-left:4px solid var(--teal);border-radius:0 10px 10px 0;padding:10px 12px;margin-bottom:10px;background:#FBFAF7;}
  .imp.warn{border-left-color:var(--amber);}
  .imp.danger{border-left-color:var(--danger);}
  .imp .h{font-weight:700;font-size:14px;display:flex;align-items:center;gap:8px;}
  .badge{font-size:11px;padding:2px 8px;border-radius:999px;font-weight:700;color:#fff;}
  .badge.ok{background:var(--ok);} .badge.warn{background:var(--amber);} .badge.danger{background:var(--danger);}
  .imp p{margin:6px 0 0;font-size:14px;color:#3A4146;}
  .srcnote{font-size:12px;color:var(--sub);margin:0 0 9px;}
  @page{size:430px 1100px;margin:7mm;}
  /* 重点关注背景版（单一，按严重程度变色） */
  body.sev0{--sev:#2E8B57;} body.sev1{--sev:#E0A92C;} body.sev2{--sev:#E0822C;} body.sev3{--sev:#C0392B;}
  .alert.sevbox{background:var(--sev,#2E8B57);color:#fff;border-radius:14px;padding:13px 15px;margin-bottom:12px;box-shadow:var(--shadow);}
  .alert.sevbox .t{font-size:16px;font-weight:800;display:flex;align-items:center;gap:8px;}
  .alert.sevbox .d{font-size:13px;margin-top:6px;opacity:.97;line-height:1.55;}
  .sev-dot{width:11px;height:11px;border-radius:50%;background:#fff;box-shadow:0 0 0 3px rgba(255,255,255,.35);}
  .mapbox{cursor:crosshair;}
  .pt-hint{font-size:12px;color:var(--sub);margin:-2px 0 8px;}
  /* 逐要素查询 */
  .elem-row{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px;}
  .elem-row label{display:flex;align-items:center;gap:6px;font-size:13px;background:#FBFAF7;border:1px solid var(--line);
    border-radius:999px;padding:6px 12px;cursor:pointer;user-select:none;}
  .elem-row input{margin:0;accent-color:var(--teal);}
  .explorer-info{font-size:13px;color:var(--ink);margin-bottom:8px;}
  .explorer-info b{font-size:15px;}
  #explorerCharts .ec{margin-bottom:4px;}
  #explorerCharts .ec-h{font-size:13px;font-weight:700;margin:8px 0 2px;}
  .empty-tip{font-size:13px;color:var(--sub);text-align:center;padding:22px 0;}
</style>
</head>
<body>
<header>
  <h1 id="titleH1">工区两周天气看板</h1>
  <div class="meta" id="metaLine"></div>
</header>

<div id="alertBox" class="alert sevbox"></div>

<div class="card">
  <h2><span class="dot"></span><span id="tStats">关键指标（工区 14 天最坏情况）</span></h2>
  <div class="stats" id="statsBox"></div>
</div>

<div class="card">
  <h2><span class="dot"></span><span id="tMap">工区地形图与风险分布</span></h2>
  <div class="mapbox">
    <canvas id="mapCanvas" width="680" height="1210"></canvas>
    <svg id="mapOverlay" viewBox="0 0 680 1210" preserveAspectRatio="xMidYMid meet"></svg>
  </div>
  <div class="legend">
    <span><i style="background:#C0392B;width:16px;height:11px;border-radius:3px"></i>高风险区（暴雨/8级风）</span>
    <span><i style="background:#E0822C;width:16px;height:11px;border-radius:3px"></i>注意区（大雨/大风）</span>
    <span style="align-items:center">海拔 <span class="elevbar"></span> <span id="elevTxt"></span></span>
  </div>
  <div class="legend" style="margin-top:5px">
    <span style="align-items:center"><i style="display:inline-block;width:16px;height:0;border-top:2px solid #5a4a2d;margin-right:5px;vertical-align:middle"></i>等高线（计曲线加粗，标注等高距）</span>
    <span><i style="background:#1F7A6B;width:12px;height:12px;border-radius:50%"></i>编号＝采样点</span>
    <span><i style="background:#111;width:11px;height:11px;transform:rotate(45deg)"></i><span id="centerLegend">◈＝工区中心</span></span>
  </div>
  <div class="pt-hint">提示：点击地图上任意采样点，下方立即显示该点未来两周逐要素曲线 / 柱状图。</div>
  <div class="srcnote" style="margin-top:10px">勾选下方要素（可多选），再点击地图任意采样点，下方将绘制该点未来两周曲线 / 柱状图。</div>
  <div class="elem-row">
    <label><input type="checkbox" value="temp" checked> 气温</label>
    <label><input type="checkbox" value="precip" checked> 降水</label>
    <label><input type="checkbox" value="wind"> 风速 / 阵风</label>
  </div>
  <div id="explorerInfo" class="explorer-info"></div>
  <div id="explorerCharts"></div>
</div>

<div class="card">
  <h2><span class="dot"></span><span id="tImpact">工区物探作业天气影响与建议</span></h2>
  <div id="impactBox"></div>
</div>

<script>
const DATA = __DATA__;
const NS = "http://www.w3.org/2000/svg";
const ISPTS = DATA.meta.kind === "points";
const LBL = DATA.meta.kind === "line" ? "测线" : (ISPTS ? "采集点" : "工区");
document.getElementById("titleH1").textContent = DATA.meta.name + (DATA.meta.kind === "line"
  ? " · " + (DATA.meta.lineName || "测线") + "2周天气看板"
  : (ISPTS ? " · 采集点2周天气看板" : " · 工区2周天气看板"));
document.getElementById("tMap").textContent = LBL + "地形图与风险分布";
document.getElementById("tStats").textContent = "关键指标（" + LBL + " 2 周最坏情况）";
document.getElementById("tImpact").textContent = LBL + "物探作业天气影响与建议";
document.getElementById("centerLegend").textContent = ISPTS ? "●＝采集点" : (DATA.isLine ? "◈＝测线中点" : "◈＝工区中心");
const P = DATA.peaks, H = DATA.hourly;

function el(tag, attrs){ const e=document.createElementNS(NS,tag); for(const k in attrs) e.setAttribute(k,attrs[k]); return e; }

// ---- 工区地形图 + 风险区 ----
(function(){
  const eg = DATA.elevGrid;
  let contourInterval = 500;   // 等高距(m)，绘制等高线时自适应重算
  const poly = DATA.isLine ? DATA.line : DATA.polygon;
  const lons = poly.map(p=>p[0]), lats = poly.map(p=>p[1]);
  const minlon=Math.min(...lons), maxlon=Math.max(...lons);
  const minlat=Math.min(...lats), maxlat=Math.max(...lats);
  const lat0=(minlat+maxlat)/2;
  const lonkm=(maxlon-minlon)*111*Math.cos(lat0*Math.PI/180);
  const latkm=(maxlat-minlat)*111;
  const W=680, Hh=1210, pad=34, iW=W-2*pad, iH=Hh-2*pad;
  const sc = Math.min(iW/lonkm, iH/latkm);          // px per km（等比例，避免拉伸）
  const drawW=lonkm*sc, drawH=latkm*sc;
  const ox=pad+(iW-drawW)/2, oy=pad+(iH-drawH)/2;
  const xOf=lon=> ox + (lon-minlon)/(maxlon-minlon)*drawW;
  const yOf=lat=> oy + (1-(lat-minlat)/(maxlat-minlat))*drawH;
  function polyPath(ctx){ ctx.beginPath();
    ctx.moveTo(xOf(poly[0][0]),yOf(poly[0][1]));
    for(let i=1;i<poly.length;i++) ctx.lineTo(xOf(poly[i][0]),yOf(poly[i][1]));
    if(!DATA.isLine && !ISPTS) ctx.closePath();
  }
  function borderSvg(){ let s="M"+xOf(poly[0][0]).toFixed(1)+" "+yOf(poly[0][1]).toFixed(1);
    for(let i=1;i<poly.length;i++) s+=" L"+xOf(poly[i][0]).toFixed(1)+" "+yOf(poly[i][1]).toFixed(1);
    return s + (DATA.isLine?"":" Z");
  }

  const cv=document.getElementById("mapCanvas"), ctx=cv.getContext("2d");
  ctx.fillStyle="#ECE7DF"; ctx.fillRect(0,0,W,Hh);

  function elevAt(lon,lat){
    if(!eg) return 0;
    let gx=(lon-eg.minlon)/eg.stepLon, gy=(lat-eg.minlat)/eg.stepLat;
    if(gx<0)gx=0; if(gx>eg.cols-1)gx=eg.cols-1;
    if(gy<0)gy=0; if(gy>eg.rows-1)gy=eg.rows-1;
    const x0=Math.floor(gx), y0=Math.floor(gy);
    const x1=Math.min(x0+1,eg.cols-1), y1=Math.min(y0+1,eg.rows-1);
    const fx=gx-x0, fy=gy-y0;
    const v00=eg.values[y0*eg.cols+x0], v10=eg.values[y0*eg.cols+x1];
    const v01=eg.values[y1*eg.cols+x0], v11=eg.values[y1*eg.cols+x1];
    return v00*(1-fx)*(1-fy)+v10*fx*(1-fy)+v01*(1-fx)*fy+v11*fx*fy;
  }
  const RAMP=[[0.0,[47,107,58]],[0.22,[111,174,90]],[0.45,[200,190,130]],
              [0.65,[176,122,68]],[0.82,[138,90,48]],[1.0,[205,191,160]]];
  function hyps(e,minE,maxE){
    let t=(e-minE)/(maxE-minE); if(t<0)t=0; if(t>1)t=1;
    for(let i=1;i<RAMP.length;i++){
      if(t<=RAMP[i][0]){ const a=RAMP[i-1],b=RAMP[i],f=(t-a[0])/(b[0]-a[0]);
        return [a[1][0]+(b[1][0]-a[1][0])*f, a[1][1]+(b[1][1]-a[1][1])*f, a[1][2]+(b[1][2]-a[1][2])*f]; }
    }
    return RAMP[RAMP.length-1][1];
  }
  const E=new Float32Array(W*Hh);
  for(let py=0;py<Hh;py++){ const lat=minlat+(1-(py-oy)/drawH)*(maxlat-minlat);
    for(let px=0;px<W;px++){ const lon=minlon+((px-ox)/drawW)*(maxlon-minlon); E[py*W+px]=elevAt(lon,lat); }
  }
  const mPx=1000.0/sc, off=2, zf=2.4;
  const az=315*Math.PI/180, alt=45*Math.PI/180;
  const Lx=Math.cos(alt)*Math.sin(az), Ly=Math.cos(alt)*Math.cos(az), Lz=Math.sin(alt);
  const rc=document.createElement("canvas"); rc.width=W; rc.height=Hh;
  const rctx=rc.getContext("2d"); const img=rctx.createImageData(W,Hh);
  const minE=eg?eg.minE:0, maxE=eg?eg.maxE:1000;
  for(let py=0;py<Hh;py++){ const up=Math.max(py-off,0), dn=Math.min(py+off,Hh-1);
    for(let px=0;px<W;px++){ const lf=Math.max(px-off,0), rt=Math.min(px+off,W-1);
      const e=E[py*W+px]; const col=eg?hyps(e,minE,maxE):[236,231,223];
      const eR=E[py*W+rt], eL=E[py*W+lf], eN=E[up*W+px], eS=E[dn*W+px];
      const dxm=(eR-eL)/(2*off*mPx), dym=(eN-eS)/(2*off*mPx);
      const nlen=Math.sqrt(dxm*dxm*zf*zf+dym*dym*zf*zf+1);
      const Nx=-dxm*zf/nlen, Ny=-dym*zf/nlen, Nz=1/nlen;
      let dot=Nx*Lx+Ny*Ly+Nz*Lz; if(dot<0)dot=0;
      const sh=0.5+0.7*dot, k=(py*W+px)*4;
      img.data[k]=Math.min(255,col[0]*sh); img.data[k+1]=Math.min(255,col[1]*sh);
      img.data[k+2]=Math.min(255,col[2]*sh); img.data[k+3]=255;
    }
  }
  rctx.putImageData(img,0,0);
  if(!DATA.isLine && !ISPTS){ ctx.save(); polyPath(ctx); ctx.clip(); }
  ctx.drawImage(rc,0,0);
  if(!DATA.isLine && !ISPTS) ctx.restore();
  // ---- 等高线(地形图核心：比二维地图直观，比卫星图清晰) ----
  if(eg){
    const cols=eg.cols, rows=eg.rows, vals=eg.values;
    const ER=eg.maxE-eg.minE;
    contourInterval = ER<250?50 : ER<600?100 : ER<1500?200 : ER<4500?500 : 1000;
    const cbase=Math.ceil(eg.minE/contourInterval)*contourInterval;
    const pxA=new Float32Array(cols*rows), pyA=new Float32Array(cols*rows);
    for(let j=0;j<rows;j++){ const Y=yOf(eg.minlat+eg.stepLat*j);
      for(let i=0;i<cols;i++){ pxA[j*cols+i]=xOf(eg.minlon+eg.stepLon*i); pyA[j*cols+i]=Y; } }
    const vAt=(i,j)=>vals[j*cols+i];
    ctx.save();
    if(!DATA.isLine && !ISPTS){ polyPath(ctx); ctx.clip(); }
    ctx.lineJoin="round"; ctx.lineCap="round";
    for(let lv=cbase; lv<eg.maxE-1e-6; lv+=contourInterval){
      const isIdx=(Math.round(lv/contourInterval)%5===0);
      ctx.strokeStyle=isIdx?"rgba(42,28,12,0.78)":"rgba(68,52,30,0.45)";
      ctx.lineWidth=isIdx?1.8:0.85;
      ctx.beginPath();
      for(let j=0;j<rows-1;j++){
        for(let i=0;i<cols-1;i++){
          const vTL=vAt(i,j+1), vTR=vAt(i+1,j+1), vBL=vAt(i,j), vBR=vAt(i+1,j);
          let c=0; if(vTL>lv)c|=8; if(vTR>lv)c|=4; if(vBR>lv)c|=2; if(vBL>lv)c|=1;
          if(c===0||c===15) continue;
          const xTL=pxA[(j+1)*cols+i], yTL=pyA[(j+1)*cols+i];
          const xTR=pxA[(j+1)*cols+i+1], yTR=pyA[(j+1)*cols+i+1];
          const xBL=pxA[j*cols+i], yBL=pyA[j*cols+i];
          const xBR=pxA[j*cols+i+1], yBR=pyA[j*cols+i+1];
          const top=[xTL+(xTR-xTL)*((lv-vTL)/(vTR-vTL)), yTL+(yTR-yTL)*((lv-vTL)/(vTR-vTL))];
          const bot=[xBL+(xBR-xBL)*((lv-vBL)/(vBR-vBL)), yBL+(yBR-yBL)*((lv-vBL)/(vBR-vBL))];
          const lft=[xTL+(xBL-xTL)*((lv-vTL)/(vBL-vTL)), yTL+(yBL-yTL)*((lv-vTL)/(vBL-vTL))];
          const rgt=[xTR+(xBR-xTR)*((lv-vTR)/(vBR-vTR)), yTR+(yBR-yTR)*((lv-vTR)/(vBR-vTR))];
          switch(c){
            case 1: ctx.moveTo(bot[0],bot[1]); ctx.lineTo(lft[0],lft[1]); break;
            case 2: ctx.moveTo(bot[0],bot[1]); ctx.lineTo(rgt[0],rgt[1]); break;
            case 3: ctx.moveTo(lft[0],lft[1]); ctx.lineTo(rgt[0],rgt[1]); break;
            case 4: ctx.moveTo(top[0],top[1]); ctx.lineTo(rgt[0],rgt[1]); break;
            case 5: ctx.moveTo(top[0],top[1]); ctx.lineTo(lft[0],lft[1]); ctx.moveTo(bot[0],bot[1]); ctx.lineTo(rgt[0],rgt[1]); break;
            case 6: ctx.moveTo(top[0],top[1]); ctx.lineTo(bot[0],bot[1]); break;
            case 7: ctx.moveTo(top[0],top[1]); ctx.lineTo(lft[0],lft[1]); break;
            case 8: ctx.moveTo(top[0],top[1]); ctx.lineTo(lft[0],lft[1]); break;
            case 9: ctx.moveTo(top[0],top[1]); ctx.lineTo(bot[0],bot[1]); break;
            case 10: ctx.moveTo(top[0],top[1]); ctx.lineTo(rgt[0],rgt[1]); ctx.moveTo(bot[0],bot[1]); ctx.lineTo(lft[0],lft[1]); break;
            case 11: ctx.moveTo(top[0],top[1]); ctx.lineTo(rgt[0],rgt[1]); break;
            case 12: ctx.moveTo(lft[0],lft[1]); ctx.lineTo(rgt[0],rgt[1]); break;
            case 13: ctx.moveTo(bot[0],bot[1]); ctx.lineTo(rgt[0],rgt[1]); break;
            case 14: ctx.moveTo(bot[0],bot[1]); ctx.lineTo(lft[0],lft[1]); break;
          }
        }
      }
      ctx.stroke();
    }
    ctx.restore();
  }
  // 风险区(局地径向渐变，半径 5/7 km，px = rkm*sc)
  ctx.save(); if(!DATA.isLine && !ISPTS){ polyPath(ctx); ctx.clip(); }
  DATA.points.forEach(pt=>{
    if(pt.risk==="ok") return;
    const cx=xOf(pt.lon), cy=yOf(pt.lat);
    const rkm= pt.risk==="danger"?7:5;
    const R=rkm*sc;
    const c= pt.risk==="danger"?"192,57,43":"224,130,44";
    const g=ctx.createRadialGradient(cx,cy,0,cx,cy,R);
    g.addColorStop(0,`rgba(${c},0.45)`); g.addColorStop(0.55,`rgba(${c},0.22)`); g.addColorStop(1,`rgba(${c},0)`);
    ctx.fillStyle=g; ctx.beginPath(); ctx.arc(cx,cy,R,0,Math.PI*2); ctx.fill();
    ctx.strokeStyle=`rgba(${c},0.55)`; ctx.lineWidth=1.3;
    ctx.beginPath(); ctx.arc(cx,cy,R,0,Math.PI*2); ctx.stroke();
  });
  ctx.restore();
  // 矢量覆盖层
  const svg=document.getElementById("mapOverlay"); svg.innerHTML="";
  const gkm=DATA.meta.gridKm, dlon=gkm/(111*Math.cos(lat0*Math.PI/180)), dlat=gkm/111;
  for(let lon=minlon; lon<=maxlon+1e-9; lon+=dlon)
    svg.appendChild(el("line",{x1:xOf(lon),y1:oy,x2:xOf(lon),y2:oy+drawH,stroke:"rgba(255,255,255,.30)",["stroke-width"]:1}));
  for(let lat=minlat; lat<=maxlat+1e-9; lat+=dlat)
    svg.appendChild(el("line",{x1:ox,y1:yOf(lat),x2:ox+drawW,y2:yOf(lat),stroke:"rgba(255,255,255,.30)",["stroke-width"]:1}));
  if(!ISPTS) svg.appendChild(el("path",{d:borderSvg(),fill:"none",stroke:"#1a1a1a",["stroke-width"]:3,["stroke-linejoin"]:"round",["stroke-linecap"]:"round"}));
  const colmap={ok:"#1F7A6B",warn:"#E0822C",danger:"#C0392B"};
  window.POINT_PX = [];
  DATA.points.forEach(pt=>{
    const c=colmap[pt.risk], cx=xOf(pt.lon), cy=yOf(pt.lat);
    if(pt.isCenter) svg.appendChild(el("rect",{x:cx-7,y:cy-7,width:14,height:14,fill:"#fff",stroke:"#111",["stroke-width"]:2.5,transform:`rotate(45 ${cx} ${cy})`}));
    const circ=el("circle",{cx:cx,cy:cy,r:pt.risk==="ok"?6:(pt.risk==="warn"?7:8),fill:c,stroke:"#fff",["stroke-width"]:2});
    circ.style.cursor="pointer"; circ.addEventListener("click",()=>selectPoint(pt.idx));
    svg.appendChild(circ);
    const lab=el("text",{x:cx,y:cy-11,["text-anchor"]:"middle","font-size":11,fill:"#111",["font-weight"]:"700",stroke:"#fff",["stroke-width"]:3,["paint-order"]:"stroke"});
    lab.textContent=(pt.isCenter?(DATA.isLine?"中点":"中心"):("#"+(pt.idx+1)));
    lab.style.cursor="pointer"; lab.addEventListener("click",()=>selectPoint(pt.idx));
    svg.appendChild(lab);
    window.POINT_PX.push({x:cx,y:cy,idx:pt.idx});
  });
  const barLen=gkm*sc, bx=ox, by=oy+drawH+16;
  svg.appendChild(el("line",{x1:bx,y1:by,x2:bx+barLen,y2:by,stroke:"#222",["stroke-width"]:3}));
  const bt=el("text",{x:bx+barLen/2,y:by-5,["text-anchor"]:"middle","font-size":11,fill:"#222",["font-weight"]:"700"}); bt.textContent=gkm+" km"; svg.appendChild(bt);
  svg.appendChild(el("path",{d:`M${W-pad-10} ${pad+6} l6 16 l-12 0 Z`,fill:"#222"}));
  const nt=el("text",{x:W-pad-10,y:pad-2,["text-anchor"]:"middle","font-size":11,fill:"#222",["font-weight"]:"700"}); nt.textContent="N"; svg.appendChild(nt);
  // 地图空白处点击 → 命中最近采样点
  svg.style.cursor="crosshair";
  svg.addEventListener("click", function(ev){
    const ptN = svg.createSVGPoint(); ptN.x=ev.clientX; ptN.y=ev.clientY;
    const loc = ptN.matrixTransform(svg.getScreenCTM().inverse());
    let best=-1, bd=1e9;
    window.POINT_PX.forEach(p=>{ const d=Math.hypot(p.x-loc.x, p.y-loc.y); if(d<bd){bd=d; best=p.idx;} });
    if(best>=0 && bd<=28) selectPoint(best);
  });
  if(eg) document.getElementById("elevTxt").textContent=` ${Math.round(eg.minE)}~${Math.round(eg.maxE)} m · 等高距 ${contourInterval}m`;
})();

document.getElementById("metaLine").textContent = ISPTS
  ? `采集点 ${DATA.meta.npts} 个 · ${DATA.meta.start} ~ ${DATA.meta.end} · 数据 ${DATA.meta.gen} 生成`
  : (DATA.meta.kind === "line"
    ? `测线「${DATA.meta.lineName}」长度 约 ${DATA.meta.lineKm}km · 网格 ${DATA.meta.gridKm}km · ${DATA.meta.npts} 个采样点 · ${DATA.meta.start} ~ ${DATA.meta.end} · 数据 ${DATA.meta.gen} 生成`
    : `工区范围 约 ${DATA.meta.lonkm}×${DATA.meta.latkm}km · 网格 ${DATA.meta.gridKm}km · ${DATA.meta.npts} 个采样点 · ${DATA.meta.start} ~ ${DATA.meta.end} · 数据 ${DATA.meta.gen} 生成`);

// ============ 重点关注（单一，按严重程度变色） ============
(function(){
  const SEV=DATA.meta.sev, LBL2=DATA.meta.sevLabel;
  document.body.classList.add("sev"+SEV);
  const nRisk = DATA.points.filter(p=>p.risk!=="ok").length;
  const th=[];
  if(P.gustMax>=17.2) th.push(`最大阵风 ${P.gustMax} m/s（≥8级）`);
  if(P.tmax>=35) th.push(`最高气温 ${P.tmax}°C（高温）`);
  if(P.tmin<=0) th.push(`最低气温 ${P.tmin}°C（结冰/霜冻）`);
  if(P.pMax>=50) th.push(`${P.pMaxDay.slice(5)} 单日降水 ${P.pMax}mm（暴雨）`);
  else if(P.pMax>=25) th.push(`${P.pMaxDay.slice(5)} 单日降水 ${P.pMax}mm（大雨）`);
  if(P.focusStart) th.push(`${P.focusStart.slice(5)}~${P.focusEnd.slice(5)} 连续降雨累计 ${P.focusTotal}mm`);
  const desc = th.length
    ? ("主要关注：" + th.join("；") + `。图中共 ${nRisk} 个采样点存在降雨/大风风险，建议据此调整野外作业安排。`)
    : "本期未触发极端天气预警阈值，整体有利于野外作业。";
  const box=document.getElementById("alertBox");
  box.className="alert sevbox";
  box.innerHTML=`<div class="t"><span class="sev-dot"></span>${LBL2}</div><div class="d">${desc}</div>`;
})();

// ---- 指标（副标题标注极值所在采样点的大致位置） ----
const argmax = key => DATA.points.reduce((b,p)=> (b===null || p[key] > b[key]) ? p : b, null);
const argmin = key => DATA.points.reduce((b,p)=> (b===null || p[key] < b[key]) ? p : b, null);
const locStr = p => p ? ((p.isCenter ? (DATA.isLine ? "测线中点" : "工区中心") : p.loc) + " 采样点") : "";
const tmaxP = argmax("tmax"), tminP = argmin("tmin"), gustP = argmax("gustMax"), pmaxP = argmax("pMax");
const stats=[
  [LBL+"最高温", P.tmax+"°C", (P.tmax>=35?"高温预警":"无高温预警")+" · "+locStr(tmaxP)],
  [LBL+"最低温", P.tmin+"°C", (P.tmin<=0?"注意霜冻/结冰":"无霜冻/结冰")+" · "+locStr(tminP)],
  ["最大阵风", P.gustMax+"<small> m/s</small>", (P.gustMax>=17.2?"≥8级，需停工":(P.gustMax>=10.8?"≥6级，加固":"约5级，不影响"))+" · "+locStr(gustP)],
  ["最大日降水", (P.pMax||0)+"<small> mm</small>", (P.pMaxDay?(P.pMax>=50?"暴雨 "+P.pMaxDay.slice(5):(P.pMax>=25?"大雨 "+P.pMaxDay.slice(5):"中雨 "+P.pMaxDay.slice(5))):"—")+" · "+locStr(pmaxP)],
];
document.getElementById("statsBox").innerHTML = stats.map(s=>
  `<div class="stat"><div class="k">${s[0]}</div><div class="v">${s[1]}</div><div class="k">${s[2]}</div></div>`).join("");

// ---- 影响说明（中间三张区域图已移除，改由地图点击联动展示） ----
const ib=document.getElementById("impactBox");
function card(level,title,badge,html){
  const cls = level==="danger"?"imp danger":(level==="warn"?"imp warn":"imp");
  return `<div class="${cls}"><div class="h">${title} <span class="badge ${badge.cls}">${badge.t}</span></div><p>${html}</p></div>`;
}
let out="";
if(P.pMax>=25){ out+=card("warn","降水 / 泥泞",{cls:"warn",t:"注意"},
  `${LBL} ${P.focusStart.slice(5)} ~ ${P.focusEnd.slice(5)} 连续降雨，逐日最大累计 <b>${P.focusTotal}mm</b>，其中 ${P.pMaxDay.slice(5)} 达 <b>${P.pMax}mm（大雨）</b>。低洼与河谷炮点、山区便道易泥泞、车辆通行困难；坡面含水升高，<b>滑坡/泥石流风险上升</b>；钻井与地震排列设备需做好防雨防潮。建议：推迟涉水与陡坡段施工，雨停后待便道稍干再进场，电缆接头包覆防水。`); }
else { out+=card("ok","降水 / 泥泞",{cls:"ok",t:"安全"},
  `预报期内${LBL}日降水均 ≤25mm，以零星小雨为主，对便道与设备影响有限，常规防雨即可。`); }
if(P.gustMax>=17.2){ out+=card("danger","大风 / 阵风",{cls:"danger",t:"预警"},
  `${LBL}阵风达 ${P.gustMax} m/s（≥8级），钻机塔架、重力仪/磁力仪天线与帐篷稳定性受严重影响，高处作业必须停工。`); }
else if(P.windMax>=10.8){ out+=card("warn","大风 / 阵风",{cls:"warn",t:"注意"},
  `${LBL}持续风速达 ${P.windMax} m/s（≥6级），钻机与高空设备需加固，谨慎安排吊装/高处作业。`); }
else { out+=card("ok","大风 / 阵风",{cls:"ok",t:"安全"},
  `${LBL}最大阵风 ${P.gustMax} m/s（约5级及以下），不影响钻机、天线及帐篷，常规作业即可。`); }
if(P.tmax>=35){ out+=card("danger","高温",{cls:"danger",t:"预警"},`${LBL}最高气温 ${P.tmax}°C，人员易中暑、设备过热电池衰减，避开正午高强度作业、配备降温与补水。`); }
else if(P.tmin<=0){ out+=card("warn","低温 / 结冰",{cls:"warn",t:"注意"},`${LBL}最低气温 ${P.tmin}°C，高海拔段可能结冰，人员保暖、电池效能下降需备用电源。`); }
else { out+=card("ok","气温",{cls:"ok",t:"适宜"},`${LBL}气温区间 ${P.tmin}~${P.tmax}°C，体感适宜；高海拔早晚偏凉，注意人员保暖与仪器低温启动。`); }
out+=card("warn","雷暴（注：预报未含雷电要素）",{cls:"warn",t:"提示"},
  `连续降雨过程常伴雷暴。山区孤立高地、金属设备（地震检波器串、测杆、钻塔）雷击风险高。遇雷雨立即停工，人员撤离至车内或低洼安全区，远离孤立树木与金属物体。`);
out+=card("ok","低能见度 / 行车",{cls:"ok",t:"提示"},
  `雨后山区多雾、便道湿滑，越野车与设备转运需降速、保持车距；进场前确认便道承载力。`);
ib.innerHTML=out;

// ============ 交互：采样点逐要素查询 ============
const EXPLORER = document.getElementById("explorerCharts");
const ELEM_DEFS = {
  temp:  {name:"气温", unit:"°C", type:"line2", keys:["tempMin","tempMax"], colors:["#2E7DA8","#E0822C"], labels:["最低温","最高温"],
          thr:[{v:35,color:"#C0392B",label:"高温35°"},{v:0,color:"#2E7DA8",label:"0°"}]},
  precip:{name:"降水", unit:"mm", type:"bar", keys:["precip"], colors:["#7FB3D5"],
          thr:[{v:50,color:"#C0392B",label:"暴雨50"},{v:25,color:"#E0822C",label:"大雨25"}]},
  wind:  {name:"风速/阵风", unit:"m/s", type:"line2", keys:["windMax","gustMax"], colors:["#1F7A6B","#8E44AD"], labels:["持续风","阵风"],
          thr:[{v:10.8,color:"#E0822C",label:"6级10.8"},{v:17.2,color:"#C0392B",label:"8级17.2"}]},
};
let SEL = -1;
function selectedElems(){ return Array.from(document.querySelectorAll('.elem-row input:checked')).map(c=>c.value); }

function pointLine(svg, labels, series, opt){
  const W=680,Hh=230,pl=40,pr=12,pt=14,pb=24; svg.setAttribute("viewBox",`0 0 ${W} ${Hh}`); svg.innerHTML="";
  const n=labels.length;
  let lo=Infinity,hi=-Infinity;
  series.forEach(s=>s.data.forEach(v=>{ if(v<lo)lo=v; if(v>hi)hi=v; }));
  if(!isFinite(lo)){lo=0;hi=1;}
  const pad=(hi-lo)*0.15||1; lo-=pad; hi+=pad;
  const X=i=> pl+(W-pl-pr)*(n<=1?0.5:i/(n-1));
  const Y=v=> pt+(Hh-pt-pb)*(1-(v-lo)/(hi-lo));
  [lo,(lo+hi)/2,hi].forEach(tv=>{ svg.appendChild(el("line",{x1:pl,y1:Y(tv),x2:W-pr,y2:Y(tv),stroke:"#EEE",["stroke-width"]:1}));
    const tx=el("text",{x:pl-5,y:Y(tv)+3,["text-anchor"]:"end","font-size":10,fill:"#9aa0a4"}); tx.textContent=Math.round(tv); svg.appendChild(tx); });
  (opt.thresholds||[]).forEach(th=>{ if(th.v<lo||th.v>hi)return;
    svg.appendChild(el("line",{x1:pl,y1:Y(th.v),x2:W-pr,y2:Y(th.v),stroke:th.color,["stroke-width"]:1.4,["stroke-dasharray"]:"5 4",opacity:.85}));
    const tx=el("text",{x:W-pr,y:Y(th.v)-4,["text-anchor"]:"end","font-size":10,fill:th.color,["font-weight"]:"700"}); tx.textContent=th.label; svg.appendChild(tx); });
  const step=Math.max(1,Math.ceil(n/7));
  for(let i=0;i<n;i+=step){ const tx=el("text",{x:X(i),y:Hh-8,["text-anchor"]:"middle","font-size":10,fill:"#9aa0a4"}); tx.textContent=labels[i]; svg.appendChild(tx); }
  series.forEach(s=>{ let pts=""; s.data.forEach((v,i)=>{ const x=X(i),y=Y(v); pts+=(i?"L":"M")+x.toFixed(1)+" "+y.toFixed(1)+" "; });
    svg.appendChild(el("path",{d:pts,fill:"none",stroke:s.color,["stroke-width"]:2,["stroke-linejoin"]:"round",["stroke-linecap"]:"round"}));
    const mi=s.data.indexOf(Math.max(...s.data)); svg.appendChild(el("circle",{cx:X(mi),cy:Y(s.data[mi]),r:3,fill:s.color,stroke:"#fff",["stroke-width"]:1.5})); });
}
function pointBar(svg, labels, vals, opt){
  const W=680,Hh=230,pl=40,pr=12,pt=14,pb=24; svg.setAttribute("viewBox",`0 0 ${W} ${Hh}`); svg.innerHTML="";
  const n=labels.length, yMax=opt.yMax, bw=(W-pl-pr)/n; const Y=v=> pt+(Hh-pt-pb)*(1-v/yMax);
  [0,yMax/2,yMax].forEach(tv=>{ svg.appendChild(el("line",{x1:pl,y1:Y(tv),x2:W-pr,y2:Y(tv),stroke:"#EEE",["stroke-width"]:1}));
    const tx=el("text",{x:pl-5,y:Y(tv)+3,["text-anchor"]:"end","font-size":10,fill:"#9aa0a4"}); tx.textContent=Math.round(tv); svg.appendChild(tx); });
  (opt.thresholds||[]).forEach(th=>{ if(th.v>yMax)return;
    svg.appendChild(el("line",{x1:pl,y1:Y(th.v),x2:W-pr,y2:Y(th.v),stroke:th.color,["stroke-width"]:1.4,["stroke-dasharray"]:"5 4",opacity:.85}));
    const tx=el("text",{x:W-pr,y:Y(th.v)-4,["text-anchor"]:"end","font-size":10,fill:th.color,["font-weight"]:"700"}); tx.textContent=th.label; svg.appendChild(tx); });
  vals.forEach((v,i)=>{ const x=pl+bw*i+bw*0.2, w=bw*0.6, y=Y(v), h=Hh-pt-pb-y;
    const color=v>=50?"#C0392B":(v>=25?"#E0822C":(v>=10?"#7FB3D5":"#BCD7E8"));
    svg.appendChild(el("rect",{x:x,y:y,width:w,height:Math.max(h,0.5),rx:3,fill:color}));
    if(v>0){ const tx=el("text",{x:x+w/2,y:y-4,["text-anchor"]:"middle","font-size":9.5,fill:"#7a8086"}); tx.textContent=v; svg.appendChild(tx); }
    const tx=el("text",{x:x+w/2,y:Hh-9,["text-anchor"]:"middle","font-size":9,fill:"#9aa0a4"}); tx.textContent=labels[i]; svg.appendChild(tx); });
}
function renderExplorer(){
  if(SEL<0){ EXPLORER.innerHTML='<div class="empty-tip">点击上方地图任意采样点，这里将显示该点未来两周的逐要素曲线 / 柱状图。</div>';
    document.getElementById("explorerInfo").innerHTML=''; return; }
  const pt=DATA.points[SEL];
  const riskTxt={ok:"低风险",warn:"注意",danger:"高风险"}[pt.risk];
  const riskCls={ok:"ok",warn:"warn",danger:"danger"}[pt.risk];
  document.getElementById("explorerInfo").innerHTML =
     `<b>#${pt.idx+1}${pt.isCenter?(DATA.isLine?" 测线中点":" 工区中心"):""}</b> · ${pt.loc} · <span class="badge ${riskCls}">${riskTxt}</span>`
     + ` ｜ 气温 ${pt.tmin}~${pt.tmax}°C · 阵风 ${pt.gustMax} m/s · 日降水峰值 ${pt.pMax}mm`;
  EXPLORER.innerHTML="";
  const labs=DATA.meta.dailyDates.map(d=>d.slice(5));
  const sel=selectedElems();
  if(sel.length===0){ EXPLORER.innerHTML='<div class="empty-tip">请在上方勾选至少一个要素。</div>'; return; }
  sel.forEach(k=>{
    const def=ELEM_DEFS[k];
    const box=document.createElement("div"); box.className="ec";
    const h=document.createElement("div"); h.className="ec-h"; h.textContent=`${def.name}（${def.unit}）`;
    const svg=document.createElementNS(NS,"svg"); svg.setAttribute("class","chart"); svg.setAttribute("preserveAspectRatio","none");
    box.appendChild(h); box.appendChild(svg); EXPLORER.appendChild(box);
    if(def.type==="bar"){
      const vals=pt.series[def.keys[0]];
      const dmax=Math.max(...vals,0);
      const steps=[10,20,30,50,100,200,500,1000];
      let thr=10; for(const s of steps){ if(dmax<=s){thr=s;break;} thr=s; }
      pointBar(svg, labs, vals, {yMax:thr*1.08, thresholds:[{v:thr,color:"#C0392B",label:"阈值 "+thr+"mm"}]});
    } else {
      const series=def.keys.map((kk,i)=>({name:def.labels[i],color:def.colors[i],data:pt.series[kk]}));
      pointLine(svg, labs, series, {thresholds:def.thr});
    }
  });
}
function selectPoint(i){
  SEL=i;
  const svg=document.getElementById("mapOverlay");
  let ring=document.getElementById("selRing");
  if(!ring){ ring=document.createElementNS(NS,"circle"); ring.setAttribute("id","selRing"); ring.setAttribute("fill","none"); ring.setAttribute("stroke","#111"); ring.setAttribute("stroke-width","3"); svg.appendChild(ring); }
  const px=window.POINT_PX[i];
  ring.setAttribute("cx",px.x); ring.setAttribute("cy",px.y); ring.setAttribute("r",16);
  renderExplorer();
}
document.querySelectorAll('.elem-row input').forEach(c=>c.addEventListener("change", renderExplorer));
renderExplorer();
</script>
</body>
</html>
"""

_suffix_cn = "采集点" if is_points else ("测线" if is_line else "工区")
html = TEMPLATE.replace("__DATA__", DATA_JSON).replace("__TITLE__", f"{args.name} · {_suffix_cn}2周天气看板")

# 内嵌中文字体子集
try:
    from fontTools.ttLib import TTFont
    from fontTools import subset as ftsubset
    fnt = TTFont("/System/Library/Fonts/Hiragino Sans GB.ttc", fontNumber=0)
    chars = "".join(sorted(set(html)))
    ss = ftsubset.Subsetter(); ss.populate(text=chars); ss.subset(fnt)
    buf = io.BytesIO(); fnt.save(buf)
    b64 = base64.b64encode(buf.getvalue()).decode()
    font_css = ("@font-face{font-family:'CJKLocal';src:url('data:font/ttf;base64," + b64 + "') format('truetype');font-display:swap;}")
    html = html.replace("/*__FONT_FACE__*/", font_css)
    print("embedded CJK font:", len(buf.getvalue()), "bytes")
except Exception as e:
    print("font embed FAILED:", repr(e)); html = html.replace("/*__FONT_FACE__*/", "")

with open(html_path, "w", encoding="utf-8") as f:
    f.write(html)
print("HTML written:", html_path, len(html), "bytes")

# ---------- 4. Chrome CDP 窄页 PDF（可跳过） ----------
if args.no_pdf:
    print("跳过 PDF 导出（--no-pdf），仅保留交互式 HTML")
else:
    import websocket
    os.environ["no_proxy"] = "*"; os.environ["NO_PROXY"] = "*"
    urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))
    port = 9333; profile = "<TMP>/cdp_profile_wb"
    proc = subprocess.Popen(
        [args.chrome, "--headless", "--disable-gpu", "--no-sandbox", "--no-first-run",
         "--remote-allow-origins=*", f"--remote-debugging-port={port}", f"--user-data-dir={profile}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(3)
        raw=None; host="[::1]"
        for hh in ("[::1]","127.0.0.1","localhost"):
            for ep in (f"http://{hh}:{port}/json/list", f"http://{hh}:{port}/json/version"):
                try: raw=urllib.request.urlopen(ep,timeout=5).read(); host=hh; break
                except Exception: pass
            if raw: break
        targets=json.loads(raw)
        if isinstance(targets,dict): targets=[{"type":"page","webSocketDebuggerUrl":targets.get("webSocketDebuggerUrl")}]
        ws_url=None
        for t in targets:
            if t.get("type")=="page" and t.get("webSocketDebuggerUrl"): ws_url=t["webSocketDebuggerUrl"]; break
        ws=websocket.create_connection(ws_url,timeout=30)
        def send(mid,method,params=None): ws.send(json.dumps({"id":mid,"method":method,"params":params or {}}))
        def recv_until(mid):
            while True:
                m=json.loads(ws.recv())
                if m.get("id")==mid and "result" in m: return m
        send(1,"Page.enable")
        file_url="file://"+urllib.parse.quote(html_path)
        send(2,"Page.navigate",{"url":file_url}); time.sleep(4)
        send(3,"Page.printToPDF",{"paperWidth":4.5,"paperHeight":11.5,
            "marginTop":0.12,"marginBottom":0.12,"marginLeft":0.12,"marginRight":0.12,
            "printBackground":True,"preferCSSPageSize":False,"headerTemplate":"","footerTemplate":""})
        res=recv_until(3)
        with open(pdf_path,"wb") as f: f.write(base64.b64decode(res["result"]["data"]))
        ws.close()
        print("PDF written:", pdf_path, os.path.getsize(pdf_path), "bytes")
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except Exception: proc.kill()
print("DONE")
