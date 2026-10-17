# -*- coding: utf-8 -*-
"""
物探工区(区域)两周天气看板生成器 —— 富媒体交互式 HTML 版

数据源（2026-10-16 起）:
  - **作业点与取数一律走 jozzon-mcp（九章雷电网）目标区 ta_id**：读 `wutan/kml/wutan_ta_map.json`
    本项目下的 `points[]`（name/lon/lat/ta_id），逐个 ta_id 调 `get_hourly_weather`。
  - **KML 只用于地图几何展示**（边框 Polygon / 测线 LineString / 采集点标记），不再用于采样或取数。
  - 未配置 ta_id 直接报错退出（不再回退到 Open-Meteo 网格采样）。

能力:
  - 输入 KML 边框(工区多边形 / 测线 LineString)，自动识别类型，渲染为地图几何
  - 逐作业点取未来两周（14 天 / 336 小时）逐小时预报，并按「区域最坏情况包络」聚合
    (逐时最低温 / 最高降水 / 最大风 / 最大阵风)，同时为每个点算逐日序列供交互查询
  - 富媒体交互式 HTML：在线地形瓦片底图 + SVG 矢量覆盖层（边框/测线/作业点/风险区/比例尺/指北针）
  - 顶部「重点提示」卡片按 48 小时口径定级(0绿/1黄/2橙/3红)；其下关键指标、地图与联动图表
  - 三个页签：① 重点提示 ② 未来48小时（逐小时合并图，**不含能见度**）
    ③ 未来2周（**固定四图：降水(含降雪) / 气温(含体感) / 阵风·均风 / 能见度**，
    地图选点后直接出图，原有「要素勾选框」已移除）
  - 仅输出可交互 HTML（无 PDF 依赖），中文字体子集内嵌，手机/浏览器直接打开

用法:
  python build_dashboard.py --name "云南大关" --kml "工区.kml" --points "采集点.kml" \
      --outdir "wutan/html" --outfile "daguan-xiangmu-gongqu.html"
  （须在 beidou 目录下运行，load_ta_map 才能找到 wutan/kml/wutan_ta_map.json）

"""
import argparse, json, os, sys, time, base64, io, urllib.request, urllib.parse, math
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET

# ======================================================================
# 共享取数 + 分级模块（jozzon-mcp / 九章雷电网）
#   本模块统一经 jozzon-mcp 按目标区 ta_id 取逐小时天气，并集中管理七要素分级阈值，
#   避免物探 / 石油工程两套 skill 分级漂移。脚本把 weather-common/scripts 加入 sys.path。
# ======================================================================
_COMMON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "weather-common", "scripts")
if _COMMON_DIR not in sys.path:
    sys.path.insert(0, _COMMON_DIR)
import jozzonwx as JW

def load_ta_map(name):
    """读取 wutan/kml/wutan_ta_map.json 中本项目对应的作业点列表（按序号对应）。
    返回 [{ta_id, lon, lat, label}, ...]；未配置 / 文件缺失返回 []。
    搜索顺序：env WUTAN_TA_MAP → 当前目录 wutan/kml/wutan_ta_map.json。
    新结构：项目 → {"points":[{name,lon,lat,ta_id}...], "lines":[...], "polygons":[...]}；
    旧结构：项目 → [{ta_id,lon,lat,label}...]（仍兼容）。"""
    cand = []
    if os.environ.get("WUTAN_TA_MAP"):
        cand.append(os.environ["WUTAN_TA_MAP"])
    cand.append(os.path.join(os.getcwd(), "wutan", "kml", "wutan_ta_map.json"))   # ta_map 已移至 kml/
    for p in cand:
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as fh:
                    m = json.load(fh)
                val = m.get(name)
                if isinstance(val, dict):        # 新结构：取作业点列表
                    entries = val.get("points") or []
                elif isinstance(val, list):      # 旧结构
                    entries = val
                else:
                    entries = []
                out = []
                for i, e in enumerate(entries):
                    out.append({"ta_id": e.get("ta_id"),
                                "lon": e.get("lon"), "lat": e.get("lat"),
                                "label": e.get("label") or e.get("name") or f"作业点#{i+1}"})
                return out
            except Exception as e:
                print("  ⚠️ ta_map 读取失败:", repr(e))
    return []

# ======================================================================
# 实时数据采集总开关（TEMPORARY TOGGLE）
#   True  : 启用实时取数 —— 解析 KML + 调用 Open-Meteo 拉取预报与高程。
#   False : 暂时关闭实时取数（离线模式）。数据采集的【全部代码均保留】，
#           仅由本开关控制是否执行；恢复时把此处改回 True 即可。
# 现状：本项目当前以「已抓取的历史 DATA」离线重渲染为主（--data），
#       避免重复请求 Open-Meteo 触发 429 限流，故默认关闭实时取数。
# ======================================================================
FETCH_ENABLED = True

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

# ---------------- 页头背景图（hero 背景层）----------------
# 模板样式块里预留注释占位 `/*__HERO_CSS__*/`，生成时替换为下方 CSS。
# 图片以 base64 data URI 内嵌，保证产物仍是**单文件 HTML**（可直接传 S3 / 离线打开）。
# 资源缺失时静默降级为原样页头（不报错、不影响其他功能）。
# 实现要点：背景铺在 `.heroarea`（包住 <header> 与三个页签）的 ::before 伪元素上，
# 用负 inset 向四周外扩做「全出血」，因此**不占任何额外版面**，内容位置与无图时完全一致。
_HERO_IMG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "hero-bg.jpg")
HERO_BLEED = "14px"          # 背景左右外扩量 = wrap 左右内边距（实测 14px，做满屏出血）。
                             # ⚠️ 必须与实测 padding 严格相等：写成 16px 会多伸 2px →
                             # documentElement.scrollWidth 比 clientWidth 大 2 → 手机端可左右拖动（2026-09-28 修）
HERO_POS_Y = "center"        # 照片纵向取景（资源已预裁成「雪山+作业面」信息带，居中即可）
HERO_FADE = (                # 自上而下的白色渐隐，保证文字可读：(CSS 位置, 白色不透明度)
    ("0%", ".78"), ("42%", ".38"), ("100%", ".02"),
)

def hero_css():
    """读取 assets/hero-bg.jpg 并生成页头背景 CSS；无图时返回空串。"""
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
        # 抹掉原 header 卡片样式，避免与背景层叠出多余边框/圆角/阴影
        "  header{position:relative;margin:0 0 12px;background:none;border:0;"
        "border-radius:0;box-shadow:none;padding:0;min-height:0;}\n"
        # 照片在文字下方，稍加字色加深 + 极淡白描边，保证 12px 小字仍清晰
        "  header>h1,header>.meta{position:relative;z-index:1;"
        "text-shadow:0 1px 0 rgba(255,255,255,.8);}\n"
        "  header>.meta{color:#4B545C;}\n"
        "  header .backlink,header .extlink{box-shadow:0 1px 3px rgba(0,0,0,.10);}\n"
    )

# ---------------- 行政地名点位（地图叠加中文地名）----------------
# 数据源：阿里云 DataV GeoAtlas（地级市/州/盟 363 + 县级 2814），一次性落盘，生成时离线筛选。
# 坐标为 GCJ-02，与底图/作业点所用 WGS84 偏差 <1km，在地图尺度（1px≈0.5~2km）不可见。
_PLACES_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "cn_places.json")

def pick_places(minlon, maxlon, minlat, maxlat, limit=600):
    """按工区范围 + 缓冲挑出周边行政驻地，供地图上叠加中文地名（1=地级市/州/盟，2=县/区）。"""
    try:
        with open(_PLACES_DB, encoding="utf-8") as fh:
            db = json.load(fh)
    except Exception as e:
        print(f"  [places] 未加载地名库（{e}），跳过行政名称层")
        return []
    span = max(maxlon - minlon, maxlat - minlat)
    buf = min(4.0, max(0.35, 0.6 * span))          # 缓冲随工区尺寸自适应，保证缩小后仍能看到周边地名
    lo0, lo1 = minlon - buf, maxlon + buf
    la0, la1 = minlat - buf, maxlat + buf
    out = []
    for nm, lo, la, lv in db.get("cities", []):
        if lo0 <= lo <= lo1 and la0 <= la <= la1:
            out.append([nm, lo, la, 1])
    for nm, lo, la in db.get("counties", []):
        if lo0 <= lo <= lo1 and la0 <= la <= la1:
            out.append([nm, lo, la, 2])
    out.sort(key=lambda p: p[3])                    # 地级市在前（屏幕上优先占位，避免被县级挤掉）
    return out[:limit]

ap = argparse.ArgumentParser()
ap.add_argument("--name", required=True, help="项目名称，如 大关项目")
ap.add_argument("--kml", required=False, help="工区边框 KML 文件路径（使用 --data 离线重渲染时可省略）")
ap.add_argument("--data", default="", help="离线模式：直接读取已抓取的 DATA JSON 文件，跳过 KML 解析与接口调用")
ap.add_argument("--outdir", default=".", help="输出目录")
ap.add_argument("--grid", type=float, default=20.0, help="作业点距离间隔 km，默认 20（面/线统一按此距离严格等距采样；线点数超过15自动均匀取15）")
ap.add_argument("--days", type=int, default=14, help="预报天数，默认 14（两周，从下一整时起）")
ap.add_argument("--from-today", action="store_true", help="从当前整点开始（默认从下一整点开始，跳过当前小时剩余时间）")
ap.add_argument("--outfile", default="", help="自定义输出文件名（含 .html，可用拼音/字母/数字），默认 {name}工区/测线.html")
ap.add_argument("--apikey", default="6aiF2mXsB3K7YcjT")
ap.add_argument("--model", default="", help="Open-Meteo 模型，如 ecmwf_ifs04（ECMWF 4km 高分辨率）；留空用默认融合模型")
ap.add_argument("--maxpts", type=int, default=150, help="作业点数量上限（仅线模式二次兜底），面/复合工区按 --grid 距离全区域采样、不限个数")
ap.add_argument("--lines", default="", help="附加测线 KML 路径（逗号分隔），与 --kml 边框共同渲染并参与「总区域」采样（复合工区模式，如大关：边框+北/南/中线）")
ap.add_argument("--points", default="", help="附加数据作业点 KML（含多个 <Placemark><Point>，如炮点/检波点/预警点），逗号分隔；给出时**按作业点直接取数（不面/线采样）**，与 --kml 边框/测线共同渲染（作业点模式）")
ap.add_argument("--face", action="store_true", default=False,
                help="强制按工区(面/多边形)处理：即便 KML 是 LineString 也当作闭合边界采样（用于闭合线工区）")
ap.add_argument("--line", action="store_true", default=False,
                help="强制按测线(线)处理：即便 LineString 首尾闭合也按线采样（覆盖闭合线自动识别为面）")
ap.add_argument("--save-data", dest="save_data", action="store_true", default=True,
                help="实时取数后，将数据包另存为 <name>_data.json（默认开启），便于以后 --data 离线复用")
ap.add_argument("--no-save-data", dest="save_data", action="store_false",
                help="关闭自动保存 _data.json")
args = ap.parse_args()

_now = datetime.now()
today = _now.strftime("%Y-%m-%d")
# 取数窗口起点：默认从「下一整点」开始（跳过当前小时剩余分钟）；
# --from-today 则从「当前整点」开始。覆盖 --days 个自然日。
_anchor = _now if args.from_today else (_now + timedelta(hours=1))
_start = _anchor.replace(minute=0, second=0, microsecond=0)
_end = _start + timedelta(days=args.days - 1)
START_DATE = _start.strftime("%Y-%m-%d")
END_DATE = _end.strftime("%Y-%m-%d")
START_HOUR = _start.strftime("%Y-%m-%dT%H:00")
END_HOUR = _end.strftime("%Y-%m-%dT23:00")
base = os.path.abspath(args.outdir)
os.makedirs(base, exist_ok=True)

if args.data:
    with open(args.data, encoding="utf-8") as _fh:
        payload = json.load(_fh)
    is_line = bool(payload.get("isLine"))
    suffix = "测线" if is_line else "工区"
    html_path = os.path.join(base, args.outfile if args.outfile else f"{args.name}{suffix}.html")
else:
    if not FETCH_ENABLED:
        print("⚠️ 实时数据采集已暂时关闭（脚本顶部 FETCH_ENABLED = False）。")
        print("   • 离线重渲染：用 --data <已抓取DATA.json> 读取历史数据直接出图。")
        print("   • 恢复实时取数：将脚本顶部 FETCH_ENABLED 改回 True 后，再用 --kml 运行。")
        sys.exit(0)
    # ---------- 1. 解析 KML（支持 Polygon 边框 / LineString 测线） ----------
    KNS = "{http://www.opengis.net/kml/2.2}"
    tree = ET.parse(args.kml); root = tree.getroot()
    poly = []; line = []; line_name = ""
    lines = []   # 多线支持：每条 LineString 独立 {name, coords}
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
        nmval = nm.text.strip() if (nm is not None and nm.text) else ""
        coords = []
        txt = ls.find(KNS + "coordinates").text.strip()
        for part in txt.split():
            lon, lat, *_ = part.split(",")
            coords.append((float(lon), float(lat)))
        lines.append({"name": nmval, "coords": coords})
        print(f"KML 线要素顶点数: {len(coords)} 名称: {nmval or '(未命名)'}")

    def _parse_line_kml(path):
        """解析单个 KML 的首个 LineString，返回 {name, coords}"""
        t = ET.parse(path); r = t.getroot()
        for pm in r.iter(KNS + "Placemark"):
            ls = pm.find(KNS + "LineString")
            if ls is None:
                continue
            nm = pm.find(KNS + "name")
            nmval = nm.text.strip() if (nm is not None and nm.text) else ""
            coords = [(float(p.split(",")[0]), float(p.split(",")[1]))
                      for p in ls.find(KNS + "coordinates").text.strip().split()]
            return {"name": nmval, "coords": coords}
        return None

    extra_lines = []  # 复合工区：附加测线（与边框共同渲染 + 参与总区域采样）
    if args.lines:
        for lp in [x.strip() for x in args.lines.split(",") if x.strip()]:
            try:
                lt = _parse_line_kml(lp)
                if lt:
                    extra_lines.append(lt)
                    print(f"附加测线 KML: {lp} → 顶点数 {len(lt['coords'])} 名称 {lt['name'] or '(未命名)'}")
            except Exception as e:
                print(f"⚠️ 附加测线解析失败 {lp}: {repr(e)}")

    is_line = bool(lines) and not bool(poly)
    multi = is_line and len(lines) > 1
    line = lines[0]["coords"] if lines else []
    line_name = lines[0]["name"] if lines else ""

    # 闭合线（首末点相同，含 1e-6 容差）→ 视为工区多边形边界，按面处理
    # 例：奇台庄三维「排列闭合线」首尾相连，应作工区而非测线
    if (not poly) and len(lines) == 1 and not args.line:
        c0 = lines[0]["coords"]
        if len(c0) >= 4:
            a, b = c0[0], c0[-1]
            if abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) < 1e-6:
                poly = list(c0)
                if poly[0] != poly[-1]:
                    poly.append(poly[0])
                print(f"检测到闭合线「{lines[0]['name'] or '未命名'}」，按工区多边形(面)处理")
                lines = []
    # 命令行显式覆盖
    if args.face and lines and not poly:
        poly = list(lines[0]["coords"])
        if poly[0] != poly[-1]:
            poly.append(poly[0])
        print(f"--face 强制：将 LineString 当作工区多边形(面)处理")
        lines = []
    is_line = bool(lines) and not bool(poly)
    multi = is_line and len(lines) > 1
    line = lines[0]["coords"] if lines else []
    line_name = lines[0]["name"] if lines else ""

    # 附加作业点(--points)：KML 里多个 <Placemark><Point>（如炮点/检波点/预警点），
    # 给出时【按作业点直接取数，不面/线采样】，与 --kml 边框/测线共同渲染（作业点模式）
    pts = []; pt_names = []
    if args.points and not args.data:
        for pk in args.points.split(","):
            pk = pk.strip()
            if not pk:
                continue
            try:
                proot = ET.parse(pk).getroot()
            except Exception as e:
                print(f"⚠️ 作业点 KML 解析失败 {pk}: {repr(e)}")
                continue
            for pm in proot.iter(KNS + "Placemark"):
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
            print(f"附加作业点(Point): {len(pts)} 个（按作业点直接取数）")
    is_points = bool(pts)
    is_line = is_line and not is_points
    multi = is_line and len(lines) > 1

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

    def seg_dist_km(px, py, a, b):
        """点(px,py)到线段 ab 的最短距离 (km)"""
        ax, ay = a; bx, by = b
        dx = bx - ax; dy = by - ay
        if dx == 0 and dy == 0:
            return distkm((px, py), a)
        t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
        t = max(0.0, min(1.0, t))
        return distkm((px, py), (ax + t * dx, ay + t * dy))

    def _near_line(px, py, buf):
        """(px,py) 是否落在任一附加测线 buf km 缓冲带内"""
        if not extra_lines:
            return False
        for ln in extra_lines:
            c = ln["coords"]
            for k in range(1, len(c)):
                if seg_dist_km(px, py, c[k - 1], c[k]) <= buf:
                    return True
        return False

    def compass_dir(dx_km, dy_km):
        """dx_km 向东为正, dy_km 向北为正 → 8 方位中文(用于面/多边形作业点相对工区中心的方向)。"""
        if abs(dx_km) < 1e-6 and abs(dy_km) < 1e-6:
            return ""
        ang = math.degrees(math.atan2(dx_km, dy_km))  # 0=北, 90=东
        if ang < 0:
            ang += 360
        COMPASS = ["北", "东北", "东", "东南", "南", "西南", "西", "西北"]
        return COMPASS[int((ang + 22.5) // 45) % 8]

    if is_line:
        all_coords = [c for ln in lines for c in ln["coords"]]
        total_km = sum(sum(distkm(ln["coords"][i-1], ln["coords"][i]) for i in range(1, len(ln["coords"]))) for ln in lines)
    else:
        # 作业点模式：有边框用边框范围，无边框用作业点范围
        all_coords = poly if (poly or not is_points) else pts
    verts = all_coords
    lons = [p[0] for p in verts]; lats = [p[1] for p in verts]
    minlon, maxlon, minlat, maxlat = min(lons), max(lons), min(lats), max(lats)
    lat0 = (minlat + maxlat) / 2
    lonkm = (maxlon - minlon) * 111.0 * math.cos(math.radians(lat0))
    latkm = (maxlat - minlat) * 111.0
    if is_line:
        print(f"测线总长(共{len(lines)}条) 约 {total_km:.1f} km")
    else:
        print(f"工区范围 约 {lonkm:.1f}km(东西) x {latkm:.1f}km(南北)")

    # 采样间距：面/线统一按距离间隔采样，默认 20km
    # 线规则：默认 20km 间隔；若点数会超过 LINE_MAX_PTS(15)，则改为全线均匀取 15 个点
    # 面规则：整个工区按 G(默认20km) 间隔均匀网格采样，落在多边形内的点全部保留，**不限个数**
    #         （不使用 --maxpts 上限加粗；大工区点数偏多时由分批取数/冷却与接口限流兜底）
    LINE_MAX_PTS = 15
    G = args.grid
    if is_line:
        _est_n = int(total_km / G) + 1
        if _est_n > LINE_MAX_PTS:
            G = total_km / (LINE_MAX_PTS - 1)
            print(f"测线总长 {total_km:.0f}km，按 {args.grid:.0f}km 间隔约 {_est_n} 点 > {LINE_MAX_PTS}，改为全线均匀取 {LINE_MAX_PTS} 个作业点（间隔 {G:.1f}km）")
    def _estimate_pts(grid):
        if is_line:
            return max(2, int(total_km / grid) + 2)
        return max(1, int((lonkm / grid) * (latkm / grid)) + 1)
    _est0 = _estimate_pts(G)
    if is_line and _est0 > args.maxpts:  # 仅线启用 maxpts 二次兜底；面不启用（保持 20km 全区域采样）
        G = G * math.sqrt(_est0 / args.maxpts)
        print(f"作业点估算 {_est0} > 上限 {args.maxpts}，网格自动加粗至 {G:.1f} km")
    grid_used = round(G, 1)

    # 文件名：线状用「测线」、多边形用「工区」；--outfile 可指定拼音/字母数字文件名
    suffix = "测线" if is_line else "工区"
    html_path = os.path.join(base, args.outfile if args.outfile else f"{args.name}{suffix}.html")

    # ---------- 1.5 地形底图：Esri World Topo Map 在线瓦片（HTML 端加载，不再抓 Open-Meteo 高程，省请求避免 429） ----------
    elevGrid = None

    # 作业点
    samples = []
    cum = []            # 仅线模式：各作业点沿主线累计 km（兼容旧逻辑）
    line_idx_of = []    # 多线：该点所属测线索引
    line_name_of = []   # 多线：该点所属测线名
    cumkm_of = []       # 多线：该点距所属测线起点累计 km
    linekm_of = []      # 多线：该点所属测线总长 km
    north_of = []       # 多线：该点所属测线「北端是否在起点」
    center_idxs = set() # 中点/中心索引集合
    if is_points:
        # 作业点模式：直接用 KML 里的 Point 坐标，不做面/线采样
        samples = [(round(x, 4), round(y, 4)) for x, y in pts]
        cum = [0.0] * len(samples)
        # 作业点是真实数据采集位置（炮点/检波点/预警点），无「中心」概念，不标记中心
        cx = sum(lons) / len(lons); cy = sum(lats) / len(lats)
    elif is_line:
        if not multi:
            prev = (round(line[0][0], 4), round(line[0][1], 4))
            samples.append(prev); cum.append(0.0)
            line_idx_of.append(0); line_name_of.append(line_name); cumkm_of.append(0.0); linekm_of.append(total_km); north_of.append(line[0][1] >= line[-1][1])
            acc = 0.0; i = 1
            while i < len(line):
                cur = line[i]; seg = distkm(prev, cur)
                if seg < 1e-9:
                    i += 1; continue
                if acc + seg >= G:
                    step = G - acc; f = step / seg
                    np_ = (prev[0] + (cur[0] - prev[0]) * f, prev[1] + (cur[1] - prev[1]) * f)
                    samples.append((round(np_[0], 4), round(np_[1], 4))); cum.append(round(cum[-1] + step, 3))
                    line_idx_of.append(0); line_name_of.append(line_name); cumkm_of.append(round(cum[-1], 3)); linekm_of.append(total_km); north_of.append(line[0][1] >= line[-1][1])
                    prev = np_; acc = 0.0
                else:
                    acc += seg; prev = (cur[0], cur[1]); i += 1
            if distkm(prev, line[-1]) > G * 0.4:
                samples.append((round(line[-1][0], 4), round(line[-1][1], 4))); cum.append(round(total_km, 3))
                line_idx_of.append(0); line_name_of.append(line_name); cumkm_of.append(round(total_km, 3)); linekm_of.append(total_km); north_of.append(line[0][1] >= line[-1][1])
            mid_d = total_km / 2.0; center_idx = 0; bestd = 1e9
            for ci, cv in enumerate(cum):
                dv = abs(cv - mid_d)
                if dv < bestd: bestd = dv; center_idx = ci
            center_idxs.add(center_idx)
        else:
            total_km_sofar = 0.0; gi = 0
            for li, ln in enumerate(lines):
                coords = ln["coords"]; name = ln["name"] or f"测线{li+1}"
                total_this = sum(distkm(coords[i-1], coords[i]) for i in range(1, len(coords)))
                north = coords[0][1] >= coords[-1][1]
                prev = (round(coords[0][0], 4), round(coords[0][1], 4))
                ls_ = [prev]; lc_ = [0.0]; acc = 0.0; i = 1
                while i < len(coords):
                    cur = coords[i]; seg = distkm(prev, cur)
                    if seg < 1e-9:
                        i += 1; continue
                    if acc + seg >= G:
                        step = G - acc; f = step / seg
                        np_ = (prev[0] + (cur[0] - prev[0]) * f, prev[1] + (cur[1] - prev[1]) * f)
                        ls_.append((round(np_[0], 4), round(np_[1], 4))); lc_.append(round(lc_[-1] + step, 3))
                        prev = np_; acc = 0.0
                    else:
                        acc += seg; prev = (cur[0], cur[1]); i += 1
                if distkm(prev, coords[-1]) > G * 0.4:
                    ls_.append((round(coords[-1][0], 4), round(coords[-1][1], 4))); lc_.append(round(total_this, 3))
                mid_d = total_this / 2.0; cmidx = 0; bestd = 1e9
                for ci, cv in enumerate(lc_):
                    dv = abs(cv - mid_d)
                    if dv < bestd: bestd = dv; cmidx = ci
                center_idxs.add(gi + cmidx)
                for k in range(len(ls_)):
                    samples.append(ls_[k]); cum.append(round(total_km_sofar + lc_[k], 3))
                    line_idx_of.append(li); line_name_of.append(name); cumkm_of.append(lc_[k]); linekm_of.append(total_this); north_of.append(north)
                gi += len(ls_); total_km_sofar += total_this
    else:
        # 面采样：作业点【严格落在边框多边形内部】。复合工区的附加测线仅用于「展示」，
        # 不参与采样（此前测线向东溢出边框，导致作业点跑到工区外，已移除）。
        # 做法：①在边框包围盒内按细步长(~G/10)铺细网格，筛出所有 inside() 在区内的候选点，
        #      用半格偏移避免候选点恰落在边界顶点上；②「最远点采样」从候选中挑出间距≈G
        #      (默认20km)的代表点：先取离质心最近的点，再迭代加入离已选集合最远的候选，
        #      直到该最远距离 < 0.75*G。对规则矩形≈网格、对斜向/不规则工区也能均匀覆盖，
        #      且保证每个作业点都在工区内、间距均匀≈G。
        uminlon, umaxlon = minlon, maxlon
        uminlat, umaxlat = minlat, maxlat
        ulat0 = (uminlat + umaxlat) / 2.0
        pcx = sum(lons) / len(lons); pcy = sum(lats) / len(lats)
        fstep = max(1.0, G / 10.0)
        fdlon = fstep / (111.0 * math.cos(math.radians(ulat0)))
        fdlat = fstep / 111.0
        cand = []
        fx = minlon + fdlon / 2.0
        while fx <= maxlon - 1e-9:
            fy = minlat + fdlat / 2.0
            while fy <= maxlat - 1e-9:
                if inside(fx, fy, poly):
                    cand.append((fx, fy))
                fy += fdlat
            fx += fdlon
        if not cand:
            cand = [(pcx, pcy)]
        start = min(cand, key=lambda p: (p[0] - pcx) ** 2 + (p[1] - pcy) ** 2)
        sel = [start]
        remaining = [p for p in cand if p != start]
        while remaining:
            far = max(remaining, key=lambda p: min(distkm(p, s) for s in sel))
            d = min(distkm(far, s) for s in sel)
            if d < 0.75 * G:
                break
            sel.append(far)
            remaining.remove(far)
        samples = [(round(x, 4), round(y, 4)) for x, y in sel]
        # 中心 = 距多边形质心最近的作业点
        best = 0; bd = 1e9
        for k, (x, y) in enumerate(samples):
            d = (x - pcx) ** 2 + (y - pcy) ** 2
            if d < bd:
                bd = d; best = k
        center_idxs.add(best)
        cx, cy = pcx, pcy
        lat0 = ulat0
        lonkm = (umaxlon - uminlon) * 111 * math.cos(math.radians(lat0))
        latkm = (umaxlat - uminlat) * 111.0
        cum = [0.0] * len(samples)
        grid_used = round(G, 1)
    print(f"作业点(含中心): {len(samples)} (目标间距 {args.grid:.0f}km)")

    # ---------- 2. 按目标区 ta_id 从 jozzon-mcp 批量取数 ----------
    # 数据源切换（2026-10-16）：Open-Meteo → jozzon-mcp（九章雷电网）。
    # 作业点 = wutan/kml/wutan_ta_map.json 里本项目注册的目标区（列表顺序对应作业点序号）；
    # KML 仅用于地图几何展示（边框 / 测线），不再用于采样取数。
    ta_entries = load_ta_map(args.name)
    if ta_entries and all(e.get("ta_id") is not None for e in ta_entries):
        # 用 ta_map 目标区覆盖 KML 采样得到的作业点（KML 仅保留几何）
        samples = [(round(float(e["lon"]), 4), round(float(e["lat"]), 4)) for e in ta_entries]
        pt_names = [e.get("label") or f"作业点#{i+1}" for i, e in enumerate(ta_entries)]
        is_points = True          # 作业点即显式命名目标区，标签走 pt_names
        center_idxs = set()       # 目标区无「中心」概念
        ta_ids = [int(e["ta_id"]) for e in ta_entries]
    else:
        raise RuntimeError(
            f"项目「{args.name}」未配置可用的 jozzon-mcp 目标区（wutan/kml/wutan_ta_map.json 缺失或 ta_id 为 null）。"
            f"请先在九章注册目标区并填入 ta_id，再运行取数。")
    print(f"作业点(目标区): {len(samples)} （jozzon-mcp 取数）")

    locs = JW.fetch_region(ta_ids, forecast_hours=args.days * 24, past_hours=0,
                           time_zone="Asia/Shanghai")
    print(f"返回地点数: {len(locs)}")

    times = [str(t) for t in (locs[0].get("time") or [])]
    n = len(times)

    def var(loc, key):
        return list(loc.get(key) or [])

    # 每点各要素序列（新口径：jozzon-mcp 统一返回，降雪已是 mm/h，不再做 cm→mm 换算）
    per = {k: [var(loc, k) for loc in locs] for k in
           ("rain", "showers", "snowfall", "wind_speed_10m", "wind_gusts_10m",
            "temperature_2m", "apparent_temperature", "visibility")}
    # 「降雨」规范口径 = rain + showers（mm/h）
    per["rainfall"] = [[round(a + b, 2) for a, b in zip(per["rain"][p], per["showers"][p])]
                       for p in range(len(locs))]

    # 降水类型码：0=无 / 1=降雨 / 2=降雪 / 3=雨夹雪（图表柱内图标用）
    # 温度规则（2026-10-08 起）：气温 < 0℃ 一律判「降雪」（液态分量不参与判型）；
    # 只有气温 ≥ 0℃ 时才可能出现「雨夹雪」（雨雪同现）。temp=None 时退化为纯分量判定。
    def ptype_of(liquid, snow, precip=0.0, temp=None):
        has_l, has_s = liquid > 0.05, snow > 0.01
        if temp is not None and temp < 0.0:
            return 2 if (has_l or has_s or precip > 0.05) else 0
        if has_l and has_s: return 3
        if has_s: return 2
        if has_l: return 1
        # 兜底：总量有值但雨/阵雨/雪分量皆 0（冰粒等）→ 仍按「降雨」呈现，避免柱子无类型
        return 1 if precip > 0.05 else 0

    per["ptype"] = [[ptype_of(per["rainfall"][p][t], per["snowfall"][p][t],
                              per["rainfall"][p][t], per["temperature_2m"][p][t])
                     for t in range(n)]
                    for p in range(len(locs))]

    # ===== 七要素分级（集中到 jozzonwx，避免两套 skill 漂移；文本严格按用户 2026-10-16 口径）=====
    RAIN_ALERT  = JW.RAIN_ALERT
    SNOW_ALERT  = JW.SNOW_ALERT
    WIND_ALERT  = JW.WIND_ALERT
    GUST_ALERT  = JW.GUST_ALERT
    UTCI_HOT    = JW.UTCI_HOT
    UTCI_COLD   = JW.UTCI_COLD
    VIS_ALERT   = JW.VIS_ALERT
    RAIN_H      = JW.RAIN_H

    def rain_alert(mmh):  return JW.grade_rain(mmh)
    def snow_alert(mmh):  return JW.grade_snow(mmh)
    def gust_alert(mps):  return JW.grade_gust(mps)
    def wind_alert(mps):  return JW.grade_wind(mps)

    def alert_items(rain_mmh, snow_mmh, wind, gust, appMax, appMin, visMin):
        """返回触发的预警文字列表（仅 level>=1）。七要素独立判定，可同时多条。
        体感温度取 appMax/appMin 中较极端者（冷/热双向）；plain 温度仅展示、不单独预警。"""
        app = appMax if (appMax is not None) else appMin
        return JW.alert_items(rain_mmh, snow_mmh, wind, gust, app, visMin)

    # 区域逐时包络
    def envelope(arrs, agg):
        return [agg(arrs[p][t] for p in range(len(arrs))) for t in range(n)]
    temp_min = envelope(per["temperature_2m"], min)
    temp_max = envelope(per["temperature_2m"], max)
    precip_max = envelope(per["rainfall"], max)
    rain_max = envelope(per["rain"], max)
    wind_max = envelope(per["wind_speed_10m"], max)
    gust_max = envelope(per["wind_gusts_10m"], max)

    # 逐点日降水 + 峰值
    from collections import defaultdict
    daily_per_point = []
    peaks_per_point = []
    for p in range(len(locs)):
        d = defaultdict(float)
        for t, v in zip(times, per["rainfall"][p]):
            d[t[:10]] += v
        daily = sorted(d.items())
        daily_per_point.append(daily)
        tmax = max(per["temperature_2m"][p]); tmin = min(per["temperature_2m"][p])
        gmax = max(per["wind_gusts_10m"][p]); wmax = max(per["wind_speed_10m"][p])
        pmax_day = max(daily, key=lambda x: x[1])[0] if daily else None
        pmax = max((v for _, v in daily), default=0)
        # 降雪小时峰值（mm/h；jozzon-mcp 已是统一 mm 口径，不再 ×10）
        snow_max_mmh = max(per["snowfall"][p])
        amax = max(per["apparent_temperature"][p]); amin = min(per["apparent_temperature"][p])
        vmin = min((v for v in per["visibility"][p] if v and v > 0), default=None)
        peaks_per_point.append(dict(tmax=tmax, tmin=tmin, gustMax=gmax, windMax=wmax,
                                    pMax=round(pmax, 1), pMaxDay=pmax_day,
                                    snowMax=round(snow_max_mmh, 2),
                                    pHourMax=round(max(per["rainfall"][p]), 2),
                                    appMax=round(amax, 1), appMin=round(amin, 1),
                                    visMin=vmin))

    # 每点逐日序列（交互式「逐要素查询」用）
    dailyDates = sorted({t[:10] for t in times})
    def point_daily(p):
        tMinD, tMaxD, pD, lD, sD, wD, gD, aMinD, aMaxD, vD = {}, {}, {}, {}, {}, {}, {}, {}, {}, {}
        pTempD = {}   # 当日「有降水时段」的最高气温，用于按温度判降水类型
        for t, tv, pv, lv, sv, wv, gv, av, vv in zip(times,
                per["temperature_2m"][p], per["rainfall"][p], per["rainfall"][p],
                per["snowfall"][p], per["wind_speed_10m"][p], per["wind_gusts_10m"][p],
                per["apparent_temperature"][p], per["visibility"][p]):
            d = t[:10]
            (tMinD.setdefault(d, [])).append(tv)
            (tMaxD.setdefault(d, [])).append(tv)
            pD[d] = pD.get(d, 0.0) + max(pv, 0.0)
            lD[d] = lD.get(d, 0.0) + max(lv, 0.0)          # 每日降雨合计（rain+showers）
            sD[d] = sD.get(d, 0.0) + max(sv, 0.0)          # 每日降雪合计（mm）
            if pv > 0.05 or lv > 0.05 or sv > 0.01:        # 该时有降水 → 记录气温（取最高）
                pTempD[d] = max(pTempD.get(d, -999.0), tv)
            (wD.setdefault(d, [])).append(wv)
            (gD.setdefault(d, [])).append(gv)
            (aMinD.setdefault(d, [])).append(av); (aMaxD.setdefault(d, [])).append(av)
            if vv and vv > 0:
                vD[d] = min(vD.get(d, 1e9), vv)
        return {
            "tempMin": [round(min(tMinD[d]), 1) for d in dailyDates],
            "tempMax": [round(max(tMaxD[d]), 1) for d in dailyDates],
            "precip":  [round(pD.get(d, 0.0), 1) for d in dailyDates],
            # 每日降水类型（柱内图标）：以当日累计 liquid / snowfall + 降水时段气温判定
            "ptype":   [ptype_of(lD.get(d, 0.0), sD.get(d, 0.0), pD.get(d, 0.0),
                                 pTempD.get(d))
                        for d in dailyDates],
            "liquid":  [round(lD.get(d, 0.0), 1) for d in dailyDates],
            "snow":    [round(sD.get(d, 0.0), 1) for d in dailyDates],
            "windMax": [round(max(wD[d]), 1) for d in dailyDates],
            "gustMax": [round(max(gD[d]), 1) for d in dailyDates],
            # 体感温度（UTCI，冷/热双向）与能见度（m，越低越差）逐日序列：供新增图表
            "appMin":  [round(min(aMinD[d]), 1) for d in dailyDates],
            "appMax":  [round(max(aMaxD[d]), 1) for d in dailyDates],
            # 能见度（m）：x1_visibility 只有前 162h 有值，无值的日必须留 None，
            # 不能填 10000 哨兵（会在两周图上画出一条假的「10 公里」平线）
            "visMin":  [round(vD[d]) if d in vD else None for d in dailyDates],
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
        "pHourMax": max(envelope(per["rainfall"], max)),
        "snowMax": max(pp["snowMax"] for pp in peaks_per_point),
        "appMax": max(pp["appMax"] for pp in peaks_per_point),
        "appMin": min(pp["appMin"] for pp in peaks_per_point),
        "visMin": min((pp["visMin"] for pp in peaks_per_point if pp["visMin"] is not None), default=None),
        "pMaxDay": peak["date"] if peak else None,
        "pMax": peak["p"] if peak else 0,
        "focusTotal": focus_total,
        "focusStart": focus_days[0]["date"] if focus_days else None,
        "focusEnd": focus_days[-1]["date"] if focus_days else None,
    }

    # ---- 未来 48 小时（近 2 天）聚合：t1「重点提示」以此为主口径 ----
    HOURS_48 = 48        # 「未来 48 小时」页保留的逐小时明细长度
    NEAR_DAYS = 2        # 「重点提示」聚焦的未来天数（=48 小时）
    # ---- 小时级短时降水分级（mm/h，2026-10-09 用户定）：>3 大雨 / >6 暴雨 / >15 大暴雨 ----
    # 只作用于「未来 48 小时」口径：逐小时风险判定、风险要素、48h 图阈值线、48h 影响卡片、48h 重点关注等级。
    # 未来 两周逐日页仍按「日累计」口径（≥25 大雨 / ≥50 暴雨），两套口径不得混用（变量名也刻意区分）。
    RAIN_H = {"heavy": 3.0, "storm": 6.0, "torrent": 15.0}
    n2 = max(1, min(NEAR_DAYS, len(dailyDates)))
    region_near = region_daily[:n2]
    near_focus = [x for x in region_near if x["p"] >= 10]
    near_peak = max(region_near, key=lambda x: x["p"]) if region_near else None
    # ---------- 各要素「最恶劣作业点」定位（回答"这数值是哪个点的"） ----------
    # 物探一个项目有几十个作业点，index/项目页的累计降水、阵风等级都是**区域包络**
    # （各点取最恶劣），不说是哪个点就无法现场核查。故每个要素都记录
    # 达成该极值的作业点标签+位置，写进 P48供文案引用。
    def pt_label(i):
        """作业点 i 的可读标签：优先 KML 名→ 测线名+里程 → 坐标。"""
        if is_points and i < len(pt_names) and pt_names[i]:
            return pt_names[i]
        if line_name_of:
            ln = line_name_of[i] if i < len(line_name_of) else ""
            km = cumkm_of[i] if i < len(cumkm_of) else None
            if ln and km is not None:
                return f"{ln} {km:g}km 处"
            if km is not None:
                return f"{km:g}km 处"
        lon, lat = samples[i] if i < len(samples) else (0, 0)
        return f"{lat:.3f}N {lon:.3f}E"

    def worst_point(values, mode="max"):
        """values: 每个作业点一个标量；返回 (值, 作业点索引)。"""
        if not values:
            return (None, 0)
        pick = max if mode == "max" else min
        return (pick(values), values.index(pick(values)))

    def p48_vals():
        """未来 48h 各作业点的窗口聚合值（与 P48 的取数窗口完全一致）。"""
        appMaxL = [round(max(per["apparent_temperature"][p][:HOURS_48]), 1) for p in range(len(locs))]
        appMinL = [round(min(per["apparent_temperature"][p][:HOURS_48]), 1) for p in range(len(locs))]
        visMinL = [min((v for v in per["visibility"][p][:HOURS_48] if v and v > 0), default=None)
                   for p in range(len(locs))]
        return {
            "pSum48": [round(sum(per["rainfall"][p][:HOURS_48]), 1) for p in range(len(locs))],
            "pHourMax": [round(max(per["rainfall"][p][:HOURS_48]), 2) for p in range(len(locs))],
            "snowHourMax": [round(max(per["snowfall"][p][:HOURS_48]), 2) for p in range(len(locs))],
            "gustMax": [round(max(per["wind_gusts_10m"][p][:HOURS_48]), 1) for p in range(len(locs))],
            "windMax": [round(max(per["wind_speed_10m"][p][:HOURS_48]), 1) for p in range(len(locs))],
            "tmax": [round(max(per["temperature_2m"][p][:HOURS_48]), 1) for p in range(len(locs))],
            "tmin": [round(min(per["temperature_2m"][p][:HOURS_48]), 1) for p in range(len(locs))],
            "appMax": appMaxL, "appMin": appMinL, "visMin": visMinL,
        }

    _pv = p48_vals()
    _w_sum, _i_sum = worst_point(_pv["pSum48"], "max")
    _w_ph, _i_ph = worst_point(_pv["pHourMax"], "max")
    _w_g, _i_g = worst_point(_pv["gustMax"], "max")
    _w_hi, _i_hi = worst_point(_pv["tmax"], "max")
    _w_lo, _i_lo = worst_point(_pv["tmin"], "min")
    # 极值作业点是否同一个（同点则只说一次，最常见）
    _idxs = {i for i in (_i_sum, _i_ph, _i_g, _i_hi, _i_lo) if _pv["pSum48"]}

    # ---- 逐作业点独立判级，列出「哪些点有问题」----
    # 区域包络只回答"最差的那个点有多差"，但现场真正要的是"哪几个点不能去、为什么"。
    # 故对每个作业点按同一套48h 阈值独立判级（阈值与 _sev_of / index 五要素一致），
    # 输出问题点清单（含等级、首要原因、关键数值），页面与 index 都要点名。
    def _pt_sev(i):
        """单个作业点的 48h 风险等级（0 适宜 / 1 需关注 / 2 重点关注 / 3 高度警惕）。
        统一走 jozzonwx 七要素分级，与 index / 页面横幅一致。"""
        pk = {
            "rain": _pv["pHourMax"][i],
            "snow": _pv.get("snowHourMax", [0.0] * len(locs))[i],
            "wind": _pv["windMax"][i],
            "gust": _pv["gustMax"][i],
            "appMax": _pv["appMax"][i], "appMin": _pv["appMin"][i],
            "visMin": _pv["visMin"][i],
        }
        return JW.sev_from_levels(JW.el_levels(pk))

    def _pt_reasons(i):
        """该作业点触发的主要因素（挑等级最高的 2 项），用用户标准标签。"""
        pk = {
            "rain": _pv["pHourMax"][i],
            "snow": _pv.get("snowHourMax", [0.0] * len(locs))[i],
            "wind": _pv["windMax"][i],
            "gust": _pv["gustMax"][i],
            "appMax": _pv["appMax"][i], "appMin": _pv["appMin"][i],
            "visMin": _pv["visMin"][i],
        }
        lv = JW.el_levels(pk)
        cands = []
        if lv["rain"]: cands.append((lv["rain"], JW.RAIN_ALERT[lv["rain"]]))
        if lv["snow"]: cands.append((lv["snow"], JW.SNOW_ALERT[lv["snow"]]))
        if lv["wind"]: cands.append((lv["wind"], "均风 · " + JW.WIND_ALERT[lv["wind"]]))
        if lv["gust"]: cands.append((lv["gust"], "阵风 · " + JW.GUST_ALERT[lv["gust"]]))
        _uv = pk["appMin"] if (pk["appMin"] is not None and (pk["appMin"] < 0 or pk["appMax"] is None)) else pk["appMax"]
        _ul, _lbl = JW.grade_utci(_uv)
        if _ul: cands.append((_ul, _lbl))
        if lv["vis"]: cands.append((lv["vis"], JW.VIS_ALERT[lv["vis"]]))
        cands.sort(key=lambda t: -t[0])
        return [t[1] for t in cands[:2]]

    _PT_SEV_LABELS = {0: "整体适宜", 1: "需关注", 2: "重点关注", 3: "高度警惕"}
    _risk_pts = []
    for _i in range(len(locs)):
        _sv = _pt_sev(_i)
        if _sv <= 0:
            continue
        _rs = _pt_reasons(_i)
        _risk_pts.append({
            "idx": _i, "label": pt_label(_i), "sev": _sv,
            "sevLabel": _PT_SEV_LABELS[_sv],
            "why": "、".join(_rs) if _rs else "降雨/大风",
            "pSum48": _pv["pSum48"][_i], "gust": _pv["gustMax"][_i],
            "tmax": _pv["tmax"][_i], "tmin": _pv["tmin"][_i],
        })
    _risk_pts.sort(key=lambda r: (-r["sev"], -r["pSum48"]))

    P48 = {
        "days": n2,
        # 温度/风：**取未来 48h 逐小时窗口极值**（与降水 pSum48 同一时间窗），
        # 不用 daily[:n2] 前两个自然日——hourly 起点是当日整点，48h 窗口横跨 3 个自然日，
        # daily[:2] 会整段漏掉第 3 天；也不用全窗 14 天极值（会把远端寒潮/大风当成 48h 风险）。
        "tmax": round(max((max(per["temperature_2m"][p][:HOURS_48]) for p in range(len(locs))), default=0), 1),
        "tmin": round(min((min(per["temperature_2m"][p][:HOURS_48]) for p in range(len(locs))), default=0), 1),
        "gustMax": round(max((max(per["wind_gusts_10m"][p][:HOURS_48]) for p in range(len(locs))), default=0), 1),
        "windMax": round(max((max(per["wind_speed_10m"][p][:HOURS_48]) for p in range(len(locs))), default=0), 1),
        # 近窗口小时级峰值：降水/降雪取未来 48h 内各点逐时最大值（mm/h）
        "pHourMax": round(max((max(per["rainfall"][p][:HOURS_48]) for p in range(len(locs))), default=0), 2),
        "snowMax": round(max((max(per["snowfall"][p][:HOURS_48]) for p in range(len(locs))), default=0), 2),
        # 体感温度（UTCI，冷/热双向）与能见度（m，越低越差）48h 区域包络
        "appMax": round(max(_pv["appMax"]), 1) if _pv["appMax"] else None,
        "appMin": round(min(_pv["appMin"]), 1) if _pv["appMin"] else None,
        "visMin": min((v for v in _pv["visMin"] if v is not None), default=None),
        "pMax": round(near_peak["p"], 1) if near_peak else 0,
        "pMaxDay": near_peak["date"] if near_peak else None,
        # 未来 48 小时真实累计：逐小时窗口（起始小时起 48 个小时）之和，
        # 不用「两个自然日之和」——当日已过去大半，两日累计会明显偏大。
        "pSum48": round(sum(precip_max[:HOURS_48]), 1),
        "h48Start": times[0] if len(times) >= 1 else None,
        "h48End": times[HOURS_48 - 1] if len(times) >= HOURS_48 else None,
        "focusTotal": round(sum(x["p"] for x in near_focus), 1),
        "focusStart": near_focus[0]["date"] if near_focus else None,
        "focusEnd": near_focus[-1]["date"] if near_focus else None,
        # ---- 各要素的最恶劣作业点（供文案说明「是哪���作业点」）----
        # 取最恶劣的那个点（同点合并），附带该作业点自身的 48h 累计，
        # 便于现场直接核对「这个点未来两天到底下多少」。
        "worstPts": {
            "sum48": {"idx": _i_sum, "label": pt_label(_i_sum), "val": _w_sum},
            "hour":  {"idx": _i_ph, "label": pt_label(_i_ph), "val": _w_ph},
            "gust":  {"idx": _i_g, "label": pt_label(_i_g), "val": _w_g},
            "hi":    {"idx": _i_hi, "label": pt_label(_i_hi), "val": _w_hi},
            "lo":    {"idx": _i_lo, "label": pt_label(_i_lo), "val": _w_lo},
        },
        # 触发各要素极值的作业点是否唯一；唯一时文案用「其中 XX 最恶劣」而非逐条重复
        "worstUnique": len(_idxs) == 1,
        "worstLabel": (pt_label(next(iter(_idxs))) if len(_idxs) == 1 else None),
        "nPts": len(locs),
        # 逐作业点独立判级的问题点清单（等级降序）：现场要知道「哪几个点有问题、为什么」，
        # 区域包络只回答"最差的有多差"。页面横幅与 index 卡片都会点名列出。
        "riskPts": _risk_pts[:12],
        "riskPtCount": len(_risk_pts),
    }

    # ---- 远期（第 3 天 ~ 第 14 天）重大极端天气：只有达到"重大"量级才提示，其余以"临近时再提示"带过 ----
    far_items = []
    for di in range(n2, len(dailyDates)):
        day = dailyDates[di]
        gp = region_daily[di]["p"] if di < len(region_daily) else 0.0
        gg = max(ps["gustMax"][di] for ps in point_series)
        gx = max(ps["tempMax"][di] for ps in point_series)
        gn = min(ps["tempMin"][di] for ps in point_series)
        tags = []
        if gp >= 50:  tags.append(f"单日降水 {round(gp,1)}mm（暴雨）")
        if gg >= 24.5: tags.append(f"阵风 {round(gg,1)} m/s（≥10级）")
        if gx >= 35:  tags.append(f"最高气温 {round(gx,1)}℃（高温）")
        if gn <= -5:  tags.append(f"最低气温 {round(gn,1)}℃（严寒）")
        if tags: far_items.append({"date": day, "text": "、".join(tags)})
    FAR = {"has": bool(far_items), "days": far_items[:2],
           "text": "；".join(f"{x['date'][5:]} {x['text']}" for x in far_items[:2])}

    # 极端天气分级（"重点关注"背景版变色依据）：0绿 1黄 2橙 3红
    # 统一走 jozzonwx 七要素分级（各要素取逐时峰值；48h 窗口口径）。
    def _sev_of(pp):
        pk = {
            "rain": pp.get("pHourMax") or 0,
            "snow": pp.get("snowMax") or 0,
            "wind": pp.get("windMax") or 0,
            "gust": pp.get("gustMax") or 0,
            "appMax": pp.get("appMax"),
            "appMin": pp.get("appMin"),
            "visMin": pp.get("visMin"),
        }
        return JW.sev_from_levels(JW.el_levels(pk))
    _SEV_LABELS = {0: "整体适宜", 1: "需关注", 2: "重点关注", 3: "高度警惕"}
    SEV = _sev_of(P)
    SEV_LABEL = _SEV_LABELS[SEV]
    SEV_NEAR = _sev_of(P48)                 # 未来 48 小时分级（t1 重点提示用）
    # 整体近 48h 评级不得低于最严重作业点的评级——否则会出现「整体适宜，但 8 个点都六级风需关注」
    # 这类自相矛盾（整体用区域包络判、逐点用各作业点独立判，二者风场字段/窗口可能不同步）。
    # 直接以「最差作业点」封底，保证整体评级与风险点清单口径一致。
    _max_pt_sev = max((r["sev"] for r in _risk_pts), default=0)
    if SEV_NEAR < _max_pt_sev:
        SEV_NEAR = _max_pt_sev
    SEV_LABEL_NEAR = _SEV_LABELS[SEV_NEAR]

    # 风险点(按各点自身判定)
    def risk_of(pp):
        # 七要素统一分级：danger=高度警惕(3) / warn=需关注·重点关注(1,2) / ok=整体适宜(0)
        pk = {
            "rain": pp.get("pHourMax") or 0,
            "snow": pp.get("snowMax") or 0,
            "wind": pp.get("windMax") or 0,
            "gust": pp.get("gustMax") or 0,
            "appMax": pp.get("appMax"), "appMin": pp.get("appMin"),
            "visMin": pp.get("visMin"),
        }
        sev = JW.sev_from_levels(JW.el_levels(pk))
        return {0: "ok", 1: "warn", 2: "warn", 3: "danger"}.get(sev, "ok")
    points_out = []
    for i, s in enumerate(samples):
        pp = peaks_per_point[i]
        # 大致位置标注
        if is_points:
            loc = pt_names[i] if (i < len(pt_names) and pt_names[i]) else f"作业点 #{i+1}"
        elif i in center_idxs:
            loc = (line_name_of[i] + " 中点") if (multi and line_name_of[i]) else ("测线中点" if is_line else "工区中心")
        elif is_line:
            dnorth = cumkm_of[i] if north_of[i] else (linekm_of[i] - cumkm_of[i])
            loc = (f"{line_name_of[i]} · 距北端 {dnorth:.0f}km") if (multi and line_name_of[i]) else f"距北端 {dnorth:.0f}km"
        else:
            dx = (s[0] - cx) * 111.0 * math.cos(math.radians(lat0))
            dy = (s[1] - cy) * 111.0
            d = math.hypot(dx, dy)
            comp = compass_dir(dx, dy)
            loc = (comp + f"方向 · 距中心 {d:.0f}km") if comp else f"工区中心附近 {d:.0f}km"
        # 逐点逐小时明细（供时间轴按小时着色 / 风险原因判定）：只保留「未来 48 小时」，控制体积
        hx = None
        if len(locs) <= 80:
            hx = {
                "temp":   [round(v, 1) for v in per["temperature_2m"][i][:HOURS_48]],
                "precip": [round(v, 1) for v in per["rainfall"][i][:HOURS_48]],  # 降雨(rain+showers, mm/h)
                "liq":    [round(v, 1) for v in per["rainfall"][i][:HOURS_48]],  # 降雨(同 precip，兼容旧字段名)
                "snow":   [round(v, 1) for v in per["snowfall"][i][:HOURS_48]],  # 降雪(mm/h)
                "pt":     list(per["ptype"][i][:HOURS_48]),                       # 降水类型码
                "wind":   [round(v, 1) for v in per["wind_speed_10m"][i][:HOURS_48]],
                "gust":   [round(v, 1) for v in per["wind_gusts_10m"][i][:HOURS_48]],
                "apparent": [round(v, 1) for v in per["apparent_temperature"][i][:HOURS_48]],
                "vis":    [round(v, 1) if v is not None else None
                           for v in per["visibility"][i][:HOURS_48]],
            }
        _ps = point_series[i]
        _p2 = _ps["precip"][:n2]
        points_out.append({
            "idx": i, "lon": s[0], "lat": s[1],
            # 溯源：逐点落九章目标区 ID（2026-10-16 补；与 wutan_ta_map.json 对应）
            "ta_id": (ta_ids[i] if i < len(ta_ids) else None),
            # 该点是否有真实能见度数据（2026-10-16 补）：九章后端当前没有 visibility 要素，
            # 逐时全 0 → point_daily 会把 series.visMin 填满哨兵 10000（假「能见度 10km」）。
            # 前端据此决定「未来2周·能见度图」画不画，避免展示编造值。
            "hasVis": any((v or 0) > 0 for v in per["visibility"][i]),
            "isCenter": (i in center_idxs),
            "lineIdx": line_idx_of[i] if multi else 0,
            "lineName": line_name_of[i] if multi else "",
            "risk": risk_of(pp), "loc": loc,
            "tmax": round(pp["tmax"], 1), "tmin": round(pp["tmin"], 1),
            "gustMax": round(pp["gustMax"], 1), "windMax": round(pp["windMax"], 1),
            "pMax": pp["pMax"], "pMaxDay": pp["pMaxDay"],
            # 每点逐日序列（未来2周逐要素图表用）：务必随数据落盘，否则离线重渲染时
            # HTML 的 renderExplorer 读 pt.series 会 undefined → 图表整体不渲染（"没图表"根因）。
            # point_series[i] 已在上方 line 963 计算好（含 tempMax/tempMin/precip/ptype/windMax/gustMax）。
            "series": point_series[i],
            # 近 48 小时逐点极值：供 t1「关键指标」标注极值所在作业点。
            # **必须取逐小时窗口 [:HOURS_48]**，不能用 _ps 的 daily[:n2]（=daily[:2]）——
            # hourly 起点是当日整点，48h 窗口横跨 3 个自然日，daily[:2] 会漏掉第 3 天，
            # 导致「页面标注的作业点」实际并没有那个极值（对不上号）。
            "tmax2": round(max(per["temperature_2m"][i][:HOURS_48]), 1) if HOURS_48 else None,
            "tmin2": round(min(per["temperature_2m"][i][:HOURS_48]), 1) if HOURS_48 else None,
            "gustMax2": round(max(per["wind_gusts_10m"][i][:HOURS_48]), 1) if HOURS_48 else None,
            "windMax2": round(max(per["wind_speed_10m"][i][:HOURS_48]), 1) if HOURS_48 else None,
            "pMax2": round(max(_p2), 1) if _p2 else 0.0,
            # 该作业点自身的 48h 窗口累计降水（区域包络 pSum48 取的就是它的 max）
            "pSum48": _pv["pSum48"][i] if i < len(_pv["pSum48"]) else 0.0,
            # 该作业点自身的 48h 窗口累计降雪（mm，水当量）——2026-10-17 关键指标「累计降水」分降雨/降雪两行
            "snowSum48": round(sum(per["snowfall"][i][:HOURS_48]), 1),
            # 该作业点自身的 48h 最大小时降水（mm/h），供 index/页面点名"哪个点雨最强"
            "pHour2": _pv["pHourMax"][i] if i < len(_pv["pHourMax"]) else 0.0,
            "hx": hx,
        })

    payload = {
        "meta": {"name": args.name, "gridKm": grid_used, "lonkm": round(lonkm, 1),
                 "latkm": round(latkm, 1), "npts": len(samples),
                 "hasHX": (len(locs) <= 80),
                 "kind": "points" if is_points else ("line" if is_line else "polygon"),
                 "lineKm": round(total_km, 1) if is_line else None,
                 "lineName": line_name if (is_line and not multi) else "",
                 "multi": multi,
                 "lines": [{"name": (ln["name"] or f"测线{i+1}"),
                            "km": round(sum(distkm(ln["coords"][j-1], ln["coords"][j]) for j in range(1, len(ln["coords"]))), 1)}
                           for i, ln in enumerate(lines)] if multi else None,
                 "start": times[0][:10], "end": times[-1][:10], "gen": today,
                 "sev": SEV, "sevLabel": SEV_LABEL,
                 "sevNear": SEV_NEAR, "sevLabelNear": SEV_LABEL_NEAR,
                 "nearDays": NEAR_DAYS, "hourlyWindow": HOURS_48,
                 # 数据源已于 2026-10-16 切换为 jozzon-mcp（九章雷电网）目标区取数；
                 # 与石油工程侧 build_points_data.py 的 meta.model 保持同一表述。
                 "model": args.model or "jozzon-mcp(九章雷电网)",
                 "dailyDates": dailyDates},
        "polygon": [[round(x, 4), round(y, 4)] for x, y in poly],
        "line": [[round(x, 4), round(y, 4)] for x, y in line],
        "lines": [[[round(x, 4), round(y, 4)] for x, y in ln["coords"]] for ln in lines] if (multi or extra_lines or (is_points and len(lines) > 1)) else None,
        # dataLines：复合工区里的测线（--lines 附加 或 主 KML 面模式下的 LineString，如大关：边框+北/中/南线），地图上彩色虚线同屏渲染
        "dataLines": [[[round(x, 4), round(y, 4)] for x, y in ln["coords"]] for ln in (extra_lines or (lines if poly else []))] if (extra_lines or (lines and poly)) else None,
        "isLine": is_line,
        "points": points_out,
        "elevGrid": elevGrid,
        "hourly": {"time": times, "tempMin": temp_min, "tempMax": temp_max,
                   "precipMax": precip_max, "rainMax": rain_max,
                   "windMax": wind_max, "gustMax": gust_max},
        "daily": region_daily,
        "peaks": P,
        "peaksNear": P48,
        "farAlert": FAR,
    }
# ---- 行政地名层：把工区（+缓冲）范围内的地名点位内嵌到本页，供地图叠加中文行政名称 ----
_geo = []
for _k in ("polygon", "line"):
    for _p in (payload.get(_k) or []):
        _geo.append(_p)
for _k in ("lines", "dataLines"):
    for _seg in (payload.get(_k) or []):
        _geo.extend(_seg)
for _p in payload["points"]:
    _geo.append([_p["lon"], _p["lat"]])
if _geo:
    _lo = [p[0] for p in _geo]
    _la = [p[1] for p in _geo]
    payload["places"] = pick_places(min(_lo), max(_lo), min(_la), max(_la))
    print(f"  行政地名层: 内嵌 {len(payload['places'])} 个点位（工区周边）")
else:
    payload["places"] = []

# 近 48 小时「小时级短时降水」峰值（mm/h）：从 points[].hx.precip 现算。
# **必须放在 if/else 两个分支之外**（模块级）：离线模式 --data 时 payload 来自 json.load，
# 上面那段 payload={...} 只在实时取数分支里执行，写在那里离线重渲染永远拿不到这个字段。
_ph_h, _ph_i, _ph_pt = 0.0, None, None
for _p in payload["points"]:
    _hx = _p.get("hx") or {}
    # 只取前 48 小时；这里写死 48 而不是 HOURS_48——后者只在实时取数分支里有定义，离线模式会 NameError
    for _ih, _vv in enumerate((_hx.get("precip") or [])[:48]):
        if _vv > _ph_h:
            _ph_h, _ph_i, _ph_pt = round(_vv, 1), _ih, (_p.get("loc") or None)
payload["peaksNear"]["pHourMax"] = _ph_h      # 48h 内各作业点逐小时降水最大值（mm/h）
payload["peaksNear"]["pHourAt"] = _ph_i       # 该峰值出现的小时索引（相对 48h 窗口）
payload["peaksNear"]["pHourPoint"] = _ph_pt   # 所在作业点的大致位置文案

# ---- 各要素极值的作业点归属（供 index/项目页文案点名用）----
# 物探一个项目几十个作业点，「累计降水 Xmm」「疾风七级」都是区域包络（各点最恶劣），
# 不说是哪个点就无从查证。这里在模块级统一算一遍（实时/离线两种模式都适用），
# 输出 worstPts={要素: {idx, loc}}；loc 用每个点已有的 loc 字段（KML名/测线里程/坐标）。
_payload_pts = payload.get("points") or []

def _pt_h48_precip(p):
    """该作业点 48h 窗口累计降水：优先现成字段；否则用 hx.precip 前 48 格累加
    （旧版离线数据没有 pSum48，但 hx 逐小时序列一直在）。"""
    if p.get("pSum48") is not None:
        return p.get("pSum48")
    hx = p.get("hx") or {}
    pr = (hx.get("precip") or [])[:48]
    return round(sum(pr), 1) if pr else 0.0

def _pt_h48_hour(p):
    """该作业点 48h 最大小时降水 mm/h。"""
    if p.get("pHour2") is not None:
        return p.get("pHour2")
    hx = p.get("hx") or {}
    pr = (hx.get("precip") or [])[:48]
    return round(max(pr), 2) if pr else 0.0

_wp = {}
if _payload_pts:
    # 逐作业点独立判级的问题点清单（48h 窗口，与页面横幅/index 同一套阈值）。
    # 离线数据可能缺 pSum48/gustMax2 等新字段，故缺则从 hx 的逐时序列现算。
    # **hx 的字段名是简写**：temp(温度) / precip(降水) / gust(阵风) / wind(持续风) / snow(降雪)
    def _hx(p, *keys, fn=max):
        """取 hx 里第一个存在的序列（兼容不同版本的字段名）。"""
        hxx = p.get("hx") or {}
        for k in keys:
            seq = (hxx.get(k) or [])[:48]
            if seq:
                return round(fn(seq), 1)
        return None

    def _pt48(p):
        ps = p.get("pSum48")
        if ps is None: ps = _hx(p, "precip", "prcp", fn=sum) or 0.0
        ph = p.get("pHour2")
        if ph is None:
            v = _hx(p, "precip", "prcp", fn=max)
            ph = round(v, 2) if v else 0.0
        g = p.get("gustMax2") or _hx(p, "gust", "wind_gusts", "wind_gust") or 0.0
        w = p.get("windMax2") or _hx(p, "wind", "wind_speed", "wind_speed_10m") or 0.0
        tmax = p.get("tmax2") or _hx(p, "temp", "temperature") or 0.0
        tmin = p.get("tmin2") or _hx(p, "temp", "temperature", fn=min) or 0.0
        snow = p.get("snowHour2") or _hx(p, "snow", "snowfall") or 0.0
        appMax = p.get("appMax2") or _hx(p, "apparent", "apparent_temperature") or None
        appMin = p.get("appMin2") or _hx(p, "apparent", "apparent_temperature", fn=min) or None
        visMin = p.get("visMin2") or _hx(p, "vis", "visibility", fn=min) or None
        return ps, ph, g, w, tmax, tmin, snow, appMax, appMin, visMin

    _PT_SEV_LABELS = {0: "整体适宜", 1: "需关注", 2: "重点关注", 3: "高度警惕"}
    _risk_pts = []
    for _p in _payload_pts:
        _ps, _ph, _g, _w, _hi, _lo, _sn, _amx, _amn, _vm = _pt48(_p)
        _pk = {"rain": _ph, "snow": _sn, "wind": _w, "gust": _g,
               "appMax": _amx, "appMin": _amn, "visMin": _vm}
        _sv = JW.sev_from_levels(JW.el_levels(_pk))
        if _sv == 0:
            continue
        _lv = JW.el_levels(_pk)
        _why = []
        if _lv["rain"]: _why.append(JW.RAIN_ALERT[_lv["rain"]])
        if _lv["snow"]: _why.append(JW.SNOW_ALERT[_lv["snow"]])
        if _lv["wind"]: _why.append("均风 · " + JW.WIND_ALERT[_lv["wind"]])
        if _lv["gust"]: _why.append("阵风 · " + JW.GUST_ALERT[_lv["gust"]])
        _uv = _amn if (_amn is not None and (_amn < 0 or _amx is None)) else _amx
        _ul, _lbl = JW.grade_utci(_uv)
        if _ul: _why.append(_lbl)
        if _lv["vis"]: _why.append(JW.VIS_ALERT[_lv["vis"]])
        _risk_pts.append({
            "idx": _p.get("idx"), "label": _p.get("loc") or f"作业点 #{((_p.get('idx') or 0)+1)}",
            "sev": _sv, "sevLabel": _PT_SEV_LABELS[_sv],
            "why": "、".join(_why[:2]) or "降雨/大风",
            "pSum48": _ps, "gust": _g, "wind": _w, "tmax": _hi, "tmin": _lo,
            "snow": _sn, "appMax": _amx, "appMin": _amn, "visMin": _vm,
        })
    _risk_pts.sort(key=lambda r: (-r["sev"], -r["pSum48"]))
    payload["peaksNear"]["riskPts"] = _risk_pts[:12]
    payload["peaksNear"]["riskPtCount"] = len(_risk_pts)
    # 离线模式整体评级封底：离线重渲染时 meta.sevNear 是从数据文件原样读入的，
    # 首次取数按「区域包络 + 平均风」判级，会与逐点「阵风」判级矛盾（如整体适宜却列 8 个六级风点）。
    # 这里以「最严重作业点」封底，保证整体评级与风险点清单口径一致。
    # 离线模式整体评级：以「当前数据权威重算」，不沿用数据文件里可能过时的旧值
    # （旧版首次取数按「区域包络 + 平均风」判级，会把中雨 1.5mm/h、轻量风等抬成需关注，
    # 或漏判六级阵风）。整体评级 = max(区域包络评级, 最严重作业点评级)，与在线 _sev_of
    # 同一套阈值（风按阵风 gustMax、降水按大雨 3.0mm/h 起抬级），杜绝「整体适宜却列多个
    # 六级风点」或「需关注徽章配天气平稳」等矛盾（如华亭 / 南郑）。
    _pn = payload.get("peaksNear") or {}
    _pk = {
        "rain": _pn.get("pHourMax") or 0,
        "snow": _pn.get("snowMax") or 0,
        "wind": _pn.get("windMax") or 0,
        "gust": _pn.get("gustMax") or 0,
        "appMax": _pn.get("appMax"), "appMin": _pn.get("appMin"),
        "visMin": _pn.get("visMin"),
    }
    _env_sev = JW.sev_from_levels(JW.el_levels(_pk))
    _max_pt_sev = max((r["sev"] for r in _risk_pts), default=0)
    _mn = payload.get("meta") or {}
    _mn["sevNear"] = max(_env_sev, _max_pt_sev)
    _mn["sevLabelNear"] = _PT_SEV_LABELS.get(_mn["sevNear"], "整体适宜")
    payload["meta"] = _mn

    def _worst(valfn, mode="max"):
        vals = [(valfn(p), p) for p in _payload_pts]
        pick = max if mode == "max" else min
        v, p = pick(vals, key=lambda t: (t[0] if t[0] is not None else (-999 if mode == "max" else 999)))
        return {"idx": p.get("idx"), "loc": p.get("loc") or f"作业点 #{((p.get('idx') or 0)+1)}",
                "val": v}
    _wp = {
        "sum48": _worst(_pt_h48_precip),          # 48h 累计降水最多的点
        "hour":  _worst(_pt_h48_hour),            # 48h 最大小时降水最强的点
        "gust":  _worst(lambda p: p.get("gustMax2")), # 48h 最大阵风的点
        "wind":  _worst(lambda p: p.get("windMax2")), # 48h 最大均风的点
        "snow":  _worst(lambda p: _pt48(p)[6]),   # 48h 最大小时降雪的点
        "snow48":_worst(lambda p: (p.get("snowSum48") if p.get("snowSum48") is not None
                                   else _hx(p, "snow", "snowfall", fn=sum))),  # 48h 累计降雪最多的点
        "hi":    _worst(lambda p: p.get("tmax2")),    # 48h 最高温的点
        "lo":    _worst(lambda p: p.get("tmin2"), "min"),  # 48h 最低温的点
        "appMax":_worst(lambda p: _pt48(p)[7]),   # 48h 最热体感的点
        "appMin":_worst(lambda p: _pt48(p)[8], "min"),   # 48h 最冷体感的点
        "visMin":_worst(lambda p: _pt48(p)[9], "min"),   # 48h 最低能见度的点
    }
    _locs = {w["loc"] for w in _wp.values()}
    _wp["unique"] = (len(_locs) == 1)
    _wp["label"] = (_wp["sum48"]["loc"] if len(_locs) == 1 else None)
payload.setdefault("peaksNear", {})["worstPts"] = _wp

# ======================================================================
# 近 48 小时「逐要素最高级别风险」清单（2026-10-17 用户定）
#   供「重点提示」逐条列出：每要素取**最严重的那个作业点**，给出等级名 / 数值 / 点位。
#   分级一律走 jozzonwx.grade_*（与横幅、index、逐点清单同一套阈值），前端不再自带阈值。
#   放在模块级（不放进取数分支），离线 --data 重渲染同样能算出来。
# ======================================================================
_EL_ORDER = [("rain", "降雨", 1), ("snow", "降雪", 2), ("gust", "阵风", 3),
             ("wind", "均风", 4), ("utci", "体感", 5), ("vis", "能见度", 6)]
_EL_UNIT = {"rain": "mm/h", "snow": "mm/h", "gust": "m/s", "wind": "m/s",
            "utci": "℃", "vis": "m"}
_EL_LABELS = {"rain": JW.RAIN_ALERT, "snow": JW.SNOW_ALERT, "gust": JW.GUST_ALERT,
              "wind": JW.WIND_ALERT, "vis": JW.VIS_ALERT}


def _utci_worst(app_min, app_max):
    """体感取「冷/热中更严重的一侧」，返回 (level, value, mode)。"""
    best_lv, best_v, mode = 0, None, "max"
    for v, m in ((app_max, "max"), (app_min, "min")):
        if v is None:
            continue
        lv = JW.grade_utci(v)[0]
        if lv == 0:
            continue
        if lv > best_lv:
            best_lv, best_v, mode = lv, v, m
        elif lv == best_lv and best_v is not None:
            # 同级取更极端：热端取大、冷端取小
            if (v < 0 and v < best_v) or (v >= 0 and v > best_v):
                best_v, mode = v, m
    return best_lv, best_v, mode


if not _payload_pts:          # 没有作业点时给个空实现，避免下面取数时 NameError
    def _pt48(p):
        return (0, 0, 0, 0, 0, 0, 0, None, None, None)

_near_rows = []
for _p in (_payload_pts if _payload_pts else []):
    _ps, _ph, _g, _w, _hi, _lo, _sn, _amx, _amn, _vm = _pt48(_p)
    _ul, _uv, _um = _utci_worst(_amn, _amx)
    _near_rows.append({
        "idx": _p.get("idx"), "rain": _ph or 0, "snow": _sn or 0,
        "gust": _g or 0, "wind": _w or 0,
        "utci": (JW.grade_utci(_uv)[1] if _uv is not None else ""),
        "vis": _vm,
        "_pk": {"rain": _ph, "snow": _sn,
                "gust": _g, "wind": _w,
                "utci": (_ul, _uv, _um),
                "vis": _vm},
    })


def _el_pick(kind):
    """该要素最严重的作业点 → (level, value, row, label)。"""
    best = None
    for r in _near_rows:
        if kind == "utci":
            lv, v, mode = r["_pk"]["utci"]
            lbl = JW.grade_utci(v)[1] if v is not None else ""
        elif kind == "vis":
            v = r["vis"]
            lv = JW.grade_vis(v) if v is not None else 0
            mode, lbl = "min", (_EL_LABELS["vis"].get(lv, "") if lv else "")
        else:
            v = r[kind]
            lv = {"rain": JW.grade_rain, "snow": JW.grade_snow,
                  "gust": JW.grade_gust, "wind": JW.grade_wind}[kind](v)
            mode, lbl = "max", (_EL_LABELS[kind].get(lv, "") if lv else "")
        if not lv or v is None:
            continue
        if best is None or lv > best[0]:
            best = (lv, v, r, lbl)
        elif lv == best[0]:
            # 同级取更极端值（热端/雨雪风取大，冷端/能见度取小）
            better = (v < best[1]) if mode == "min" else (v > best[1])
            if better:
                best = (lv, v, r, lbl)
    return best


_near_items = []
for _kind, _name, _ord in _EL_ORDER:
    _hit = _el_pick(_kind)
    if not _hit:
        continue
    _lv, _v, _row, _lbl = _hit
    _lbl = (_lbl or "").split("(")[0].split("（")[0].strip() or f"{_name}{_lv}级"
    _near_items.append({"kind": _kind, "name": _name, "order": _ord, "lv": int(_lv),
                        "label": _lbl, "val": round(float(_v), 1),
                        "unit": _EL_UNIT[_kind], "idx": _row["idx"]})
_near_items.sort(key=lambda x: (-x["lv"], x["order"]))
payload.setdefault("peaksNear", {})["nearItems"] = _near_items

DATA_JSON = json.dumps(payload, ensure_ascii=False)

# 实时取数后，将数据包落盘，便于以后--data 离线复用（不重复请求接口）。
# 离线模式（--data）下把**补充字段就地回写输入文件**（新增的 worstPts 作业点归属、
# pSum48/pHour2 等 48h 窗口字段需要持久化，否则下次离线重渲染读旧 json 会丢，
# index 卡片就点不出具体是哪个作业点）。就地覆盖而非写到 --outdir，避免生成中文名副本。
if args.save_data:
    if args.data:
        try:
            with open(args.data, "w", encoding="utf-8") as _df:
                _df.write(DATA_JSON)
            print("DATA updated (in place):", args.data)
        except Exception as e:
            print(f"⚠️ 离线数据回写失败（不影响 HTML 生成）: {e!r}")
    else:
        data_path = os.path.join(base, f"{args.name}_data.json")
        with open(data_path, "w", encoding="utf-8") as _df:
            _df.write(DATA_JSON)
        print("DATA saved:", data_path)

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
  .backlink{display:inline-block;margin-bottom:6px;font-size:13px;font-weight:600;color:var(--teal);text-decoration:none;border:1px solid var(--teal);border-radius:8px;padding:3px 10px;cursor:pointer;transition:background .15s,color .15s;}
  .backlink:hover{background:var(--teal);color:#fff;}
  .hdnav{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:6px;}
  .hdnav-l{flex:1 1 auto;min-width:0;}
  .hdnav-r{flex:0 0 auto;display:flex;align-items:center;gap:10px;}
  .brand{display:inline-block;margin-bottom:6px;font-size:12.5px;font-weight:600;color:var(--ink);text-decoration:none;border:1px solid #EAE6DF;border-radius:8px;padding:3px 10px;background:#fff;opacity:.85;transition:background .15s,border-color .15s;}
  .brand:hover{opacity:1;background:#f1f5f7;border-color:#1F7A6B;}
  .extlink{display:inline-block;background:#2e6da4;color:#fff;padding:4px 10px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:600;}
  .extlink:hover{background:#245f82;transform:translateY(-1px);}
  /*__HERO_CSS__*/
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
  /* 2026-10-17：minmax(0,1fr) + min-width:0 —— 否则点名牌（nowrap）的 min-content 会把
     两列网格撑破（窄屏 390px 时整页横向溢出，实测 scrollWidth 470） */
  .stats{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;}
  .stat{background:#FBFAF7;border:1px solid var(--line);border-radius:10px;padding:10px 12px;
    min-width:0;overflow:hidden;}
  .stat .k{font-size:12px;color:var(--sub);display:flex;align-items:center;}
  .stat .v{font-size:22px;font-weight:700;margin-top:2px;}
  .stat .v small{font-size:12px;font-weight:500;color:var(--sub);}
  /* 关键指标（2026-10-17 重排）：每格多行「要素 / 数值 / 点名牌」，点名牌右对齐且可省略 */
  .stat .vs{margin-top:5px;display:flex;flex-direction:column;gap:4px;min-width:0;}
  /* flex-wrap：点名牌放不下时**自动折到下一行**（右对齐），而不是把名字截断或把数字挤变形。
     名字本身 nowrap（「XYH-SN-01-南端」不该从中间断开），整行放不下才换行。 */
  .stat .vr{display:flex;flex-wrap:wrap;align-items:baseline;gap:2px 4px;font-variant-numeric:tabular-nums;min-width:0;}
  .stat .vr em{font-style:normal;font-size:11.5px;font-weight:700;color:var(--sub);min-width:25px;flex:0 0 auto;}
  .stat .vr b{font-size:17px;font-weight:800;line-height:1.15;flex:0 0 auto;}
  .stat .vr i{font-style:normal;font-size:11px;color:var(--sub);flex:0 0 auto;}
  .stat .vr .pp{margin-left:auto;flex:0 1 auto;min-width:0;max-width:100%;font-size:9.5px;font-weight:700;
    color:#7a3b12;background:#FFF3D6;border-radius:6px;padding:1px 6px;
    white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
  .stat .vr .pp.na{color:#a6adb3;background:transparent;padding:1px 0;}
  /* 重点提示逐要素清单（2026-10-17）：一条一行，末列点名牌右对齐 */
  .alert.sevbox .ailist{margin-top:9px;display:flex;flex-direction:column;gap:5px;}
  .alert.sevbox .ai{display:flex;align-items:baseline;gap:7px;background:rgba(255,255,255,.16);
    border-radius:8px;padding:5px 9px;font-size:12.5px;line-height:1.4;}
  .alert.sevbox .ai .eic{margin-right:1px;}  /* 逐要素图标：底色＝该要素等级（绿/橙/红） */
  .alert.sevbox .ai-k{font-weight:800;flex:0 0 auto;}
  .alert.sevbox .ai-lv{font-weight:900;font-size:11.5px;background:rgba(0,0,0,.22);
    border-radius:999px;padding:1px 8px;flex:0 0 auto;}
  .alert.sevbox .ai-lv.lv3{background:#C0392B;} .alert.sevbox .ai-lv.lv2{background:#E0822C;}
  .alert.sevbox .ai-lv.lv1{background:#E0822C;}  /* lv1~2 同属「注意」橙，与影响卡一致 */
  .alert.sevbox .ai-v{font-weight:900;font-variant-numeric:tabular-nums;flex:0 0 auto;}
  .alert.sevbox .ai-v em{font-style:normal;font-size:10.5px;font-weight:700;opacity:.85;margin-left:2px;}
  .alert.sevbox .ai-p{margin-left:auto;flex:0 1 auto;min-width:0;font-weight:800;font-size:11.5px;
    background:rgba(0,0,0,.20);border-radius:6px;padding:1px 7px;
    white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
  .alert.sevbox .ai-note{margin-top:8px;font-size:12px;opacity:.95;line-height:1.5;}
  /* 远期描述：另起一行、不同底色（2026-10-17 用户要求）——米黄底 + 深棕字，
     与上方彩色（按等级变色的）48 小时内文明显区分 */
  .alert.sevbox .far{margin-top:9px;background:#FFF7E6;border-radius:9px;padding:7px 11px;
    font-size:12.5px;line-height:1.55;color:#6b4a18;border-left:3px solid #E0A92C;}
  .alert.sevbox .far b{font-size:11.5px;color:#B36B00;margin-right:5px;}
  .chart-wrap{width:100%;overflow:hidden;}
  svg.chart{width:100%;height:auto;display:block;}
  /* 2026-10-17 用户要求：地图横向缩为原 5/6、纵向缩为原 3/4（100%→83.333%，280px→210px），
     居中显示；横向缩小后单屏能同时看到地图与下方图表，纵向压低减少留白。 */
  .mapbox{position:relative;width:83.333%;height:210px;margin:0 auto;background:#ECE7DF;border-radius:10px;overflow:hidden;
    touch-action:none;-webkit-touch-callout:none;-webkit-user-select:none;user-select:none;}  /* 高度固定，不随内容上下拉长 */
  .mapbox canvas,.mapbox svg{position:absolute;inset:0;width:100%;height:100%;}
  /* 手机上单指拖图 / 双指缩放不被页面滚动抢走 —— touch-action 必须写在 .mapbox 容器上：
     iOS Safari 对 SVG 元素自身的 touch-action 支持不可靠，写在 <svg> 上经常被忽略。 */
  .elevbar{display:inline-block;width:84px;height:10px;border-radius:3px;vertical-align:middle;
    background:linear-gradient(90deg,#2f6b3a,#6fae5a,#c8be82,#b07a44,#8a5a30,#cdbfa0);}
  .legend{display:flex;flex-wrap:wrap;gap:10px;font-size:12px;color:var(--sub);margin-top:8px;}
  .legend i{display:inline-block;width:14px;height:4px;border-radius:2px;vertical-align:middle;margin-right:5px;}
  /* 气象要素小图标（2026-09-28）：色块＝风险等级（绿 ok / 橙 warn / 红 danger），图形＝要素本身；
     .plain＝不带风险属性（图表图例、要素勾选行用），避免与风险等级色混淆 */
  .eic{display:inline-flex;align-items:center;justify-content:center;flex:0 0 auto;vertical-align:-4px;
    width:19px;height:19px;border-radius:5px;color:#fff;margin-right:5px;}
  .eic svg{width:13px;height:13px;display:block;}
  .eic.s{width:16px;height:16px;border-radius:4px;margin-right:4px;vertical-align:-3px;}
  .eic.s svg{width:11px;height:11px;}
  .eic.ok{background:#2E8B57;} .eic.warn{background:#E0822C;} .eic.danger{background:#C0392B;} .eic.plain{background:#98A1A6;}
  /* flex 容器（卡片标题 / 图例 / 勾选标签）自带 gap，图标不再另加外边距，避免间距翻倍 */
  .imp .h .eic, .ec-legend .eic, .elem-row label .eic{margin-right:0;}
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
  /* 逐要素查询 */
  .explorer-info{font-size:13px;color:var(--ink);margin-bottom:8px;}
  .explorer-info b{font-size:15px;}
  .empty-tip{font-size:13px;color:var(--sub);text-align:center;padding:22px 0;}
  /* 逐要素曲线 / 柱状图（地图选中点后展示，位于风险面板下方） */
  .elem-row{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0 6px;}
  .elem-row label{display:flex;align-items:center;gap:6px;font-size:13px;background:#FBFAF7;border:1px solid var(--line);
    border-radius:999px;padding:6px 12px;cursor:pointer;user-select:none;}
  .elem-row input{margin:0;accent-color:var(--teal);}
  #explorerCharts .ec, #hourlyCharts .ec{margin-bottom:4px;}
  #explorerCharts .ec-h, #hourlyCharts .ec-h{font-size:14px;font-weight:700;margin:10px 0 2px;}
  .ec-legend{display:flex;flex-wrap:wrap;gap:14px;font-size:12.5px;color:var(--ink);margin:2px 0 6px;font-weight:600;}
  .ec-legend .lg{display:inline-flex;align-items:center;gap:6px;}
  .ec-legend i{display:inline-block;width:12px;height:12px;border-radius:3px;}
  /* 48 小时图图例（2026-10-17 移到图表下方并放大字号，不再干扰绘图区） */
  #hourlyCharts .hleg{display:flex;flex-wrap:wrap;gap:6px 12px;margin:9px 2px 2px;
    font-size:13px;font-weight:700;color:#33414f;line-height:1.6;}
  #hourlyCharts .hleg .hl{display:inline-flex;align-items:center;gap:6px;}
  #hourlyCharts .hleg i.ln{display:inline-block;width:22px;height:3px;border-radius:2px;flex:0 0 auto;}
  #hourlyCharts .hleg i.ln.dash{height:0;border-top:3px dashed;border-radius:0;}
  /* 图表说明行（2026-10-17 与石油工程同款口径文字） */
  .ec-note{font-size:12px;color:#5a6672;line-height:1.75;margin:8px 0 6px;}
  .ec-note b{font-weight:800;color:#1f2933;}
  .ec-note .lg{display:inline-flex;align-items:center;gap:5px;margin-left:2px;}
  .ec-note .lg i{display:inline-block;width:12px;height:12px;border-radius:3px;}
  /* 48 小时读数条（工程 .hval 同款；2026-10-17 移到图表**上方**，故留底边距） */
  #hourlyCharts .hval{background:#fff;border:1px solid #eef1f4;border-radius:10px;padding:9px 11px;
    font-size:12.5px;color:#33414f;box-shadow:0 1px 4px rgba(0,0,0,.06);margin:0 0 9px;line-height:2.0;}
  #hourlyCharts .hval .t{font-weight:900;font-size:14.5px;color:#C0392B;margin-right:9px;
    font-variant-numeric:tabular-nums;letter-spacing:.2px;}
  /* 点位名（2026-10-17：地图下方要素说明面板删除后，点位信息并入这条读数条） */
  #hourlyCharts .hval .pn{font-weight:900;font-size:13.5px;color:#1f2933;background:#E8EDF2;
    border-radius:6px;padding:1.5px 8px;margin-right:7px;display:inline-block;line-height:1.5;}
  #hourlyCharts .hval b{font-weight:900;font-size:12.5px;display:inline-block;line-height:1.5;
    padding:1.5px 8px;border-radius:6px;}
  #hourlyCharts .hval b.tv{color:#8A4B00;background:#FBEAD3;}
  #hourlyCharts .hval b.pv{color:#0D47A1;background:#D8E9FA;}
  #hourlyCharts .hval b.wv{color:#0F5B4C;background:#D9EFE7;}
  #hourlyCharts .hval b.gv{color:#8A2A0E;background:#FBE0D6;}
  /* 图表 SVG 等比缩放（工程 preserveAspectRatio="xMinYMin meet" 同款，避免拉伸变形） */
  #explorerCharts svg.chart, #hourlyCharts svg.chart{width:100%;display:block;}
  /* 三页签 */
  .tabs{display:flex;gap:6px;margin:2px 0 12px;}
  .tabbtn{flex:1;padding:11px 4px;border:1px solid var(--line);background:#fff;border-radius:10px;
    font-size:13px;font-weight:700;color:var(--sub);cursor:pointer;transition:background .15s;}
  .tabbtn.active{background:var(--teal);color:#fff;border-color:var(--teal);}
  .tabpane{display:none;}
  .tabpane.active{display:block;}
  .mapnote{position:absolute;left:8px;bottom:8px;top:auto;background:rgba(255,255,255,.85);border-radius:8px;
    padding:5px 9px;font-size:11px;color:#3A4146;line-height:1.45;max-width:64%;pointer-events:none;}
  /* 日期·时间只在风险面板出现一次（图表内已删除，不再重复）；要素值＝深色粗体字 + 各自浅色底（字色在底色之上，不被盖住） */
  .rr-cur .clk{font-weight:900;color:#C0392B;background:none;padding:0;font-size:13.5px;
    font-variant-numeric:tabular-nums;letter-spacing:.2px;}
  .rr-cur b{font-weight:900;font-size:13.5px;color:#C0392B;}
  .rr-valrow{font-weight:400;font-size:12.5px;color:#4A5157;margin:0 0 8px;font-variant-numeric:tabular-nums;}
  .rr-valrow b{font-weight:900;font-size:13.5px;display:inline-block;line-height:1.5;padding:1.5px 8px;border-radius:6px;}
  .rr-valrow .pv{color:#0D47A1;background:#D8E9FA;}
  .rr-valrow .wv{color:#0F5B4C;background:#D9EFE7;}
  .rr-valrow .gv{color:#5B2A7D;background:#EEE1F7;}
  .rr-valrow .tv{color:#1A5A87;background:#DEECF7;}
  .day-read{display:inline-block;font-weight:900;font-size:13px;color:#7a3b12;background:#FFF3D6;
    border:1px solid #E6C877;border-radius:8px;padding:2px 9px;margin-left:8px;font-variant-numeric:tabular-nums;}
  /* 地图缩放控件（左上角） */
  .mapzoom{position:absolute;top:8px;left:8px;display:flex;flex-direction:column;gap:5px;z-index:6;}
  .mapzoom button{width:30px;height:30px;border-radius:8px;border:1px solid rgba(0,0,0,.22);
    background:rgba(255,255,255,.94);color:#222;font-size:16px;font-weight:900;line-height:1;cursor:pointer;
    box-shadow:0 2px 5px rgba(0,0,0,.16);padding:0;}
  .mapzoom button:active{background:#eaeaea;}
  .mapzoom .zl{width:30px;text-align:center;font-size:10.5px;font-weight:800;color:#333;
    background:rgba(255,255,255,.94);border:1px solid rgba(0,0,0,.18);border-radius:7px;padding:2px 0;}
  /* 选点/换点时只让「数据线·柱子」自下而上淡入，文字/图例/界面一律不动（transform 不影响布局） */
  @keyframes riseIn{from{opacity:0;transform:translateY(22px);}to{opacity:1;transform:none;}}
  svg.chart .geo{animation:riseIn .5s cubic-bezier(.22,.61,.36,1) both;}
  /* 地图下方的风险信息面板（单一合并面板） */
  .risk-reason{margin:12px 0 4px;background:rgba(255,255,255,.97);
    border:1px solid var(--line);border-left:4px solid var(--danger);border-radius:9px;
    box-shadow:0 6px 18px rgba(0,0,0,.12);padding:10px 14px;font-size:12.5px;color:var(--ink);line-height:1.55;}
  .risk-reason .rr-h{font-weight:800;font-size:13.5px;margin-bottom:3px;}
  .risk-reason .rr-time{font-size:12px;color:#3A4146;margin-bottom:4px;font-variant-numeric:tabular-nums;}
  .risk-reason .rr-sev{display:inline-block;margin-bottom:6px;}
  .risk-reason .rr-cur{font-size:12px;color:#2A2F33;margin-bottom:6px;font-variant-numeric:tabular-nums;}
  .risk-reason .rr-cur b{color:#C0392B;}
  .risk-reason .rr-list{font-size:11.5px;color:#5b6166;}
  .risk-reason .rr-item{padding:1px 0;}
  .risk-reason .rr-item.d{color:#C0392B;}
  .risk-reason .rr-item.w{color:#E0822C;}
  .risk-reason .rr-ok{color:#1F7A6B;font-weight:600;}
  .risk-reason .rr-peaks{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:8px 0 2px;}
  .risk-reason .rr-pc{background:#FBFAF7;border:1px solid var(--line);border-radius:8px;padding:6px 9px;}
  .risk-reason .rr-pc .k{font-size:11px;color:var(--sub);margin-bottom:2px;}
  .risk-reason .rr-pc .v{font-size:15px;font-weight:800;color:var(--ink);font-variant-numeric:tabular-nums;}
  .risk-reason .rr-pc .s{font-size:10.5px;color:#8a9097;margin-top:2px;}
  .risk-reason .rr-worst{margin-top:8px;padding-top:7px;border-top:1px dashed var(--line);font-size:11.5px;color:#7a3b12;}
  .risk-reason .rr-worst b{color:#C0392B;}
  .maptab .card{position:relative;}
</style>
</head>
<body>
<div class="heroarea">
<header>
  <div class="hdnav">
    <span class="hdnav-l"><a class="backlink" id="backLink" href="index.html">← 返回总览</a><script>var b=document.getElementById('backLink');if(new URLSearchParams(location.search).get('from')!=='index'&&b)b.style.display='none';</script></span>
    <span class="hdnav-r"><a class="extlink" href="https://leidian.wang" target="_blank" rel="noopener">北斗天气风险治理平台 ↗</a></span>
  </div>
  <h1 id="titleH1">工区两周天气看板</h1>
  <div class="meta" id="metaLine"></div>
</header>

<div class="tabs">
  <button class="tabbtn active" data-tab="t1">重点提示</button>
  <button class="tabbtn" data-tab="t2">未来48小时</button>
  <button class="tabbtn" data-tab="t3">未来两周</button>
</div>
</div>

<div id="t1" class="tabpane active">
  <div id="alertBox" class="alert sevbox"></div>
  <div class="card">
    <h2><span class="dot"></span><span id="tStats">关键指标（两周最坏情况）</span></h2>
    <div class="stats" id="statsBox"></div>
  </div>
  <div class="card">
    <h2><span class="dot"></span><span id="tImpact">物探作业天气影响与建议</span></h2>
    <div id="impactBox"></div>
  </div>
</div>

<div id="t2" class="tabpane maptab">
  <div class="card">
    <h2><span class="dot"></span><span id="tMap2">未来48小时（逐小时风险）</span></h2>
    <div class="legend">
      <span><i style="background:#C0392B;width:16px;height:11px;border-radius:3px"></i>高风险区（暴雨/8级风）</span>
      <span><i style="background:#E0822C;width:16px;height:11px;border-radius:3px"></i>注意区（大雨/大风）</span>
    </div>
    <div class="mapbox" id="mapbox2">
      <canvas id="mapCanvas2" width="680" height="520"></canvas>
      <svg id="mapOverlay2" viewBox="0 0 680 520" preserveAspectRatio="xMidYMid meet"></svg>
      <div class="mapzoom" id="mapzoom2">
        <button type="button" data-z="in" title="放大">＋</button>
        <div class="zl" id="zl2">1×</div>
        <button type="button" data-z="out" title="缩小">－</button>
        <button type="button" data-z="reset" title="复位">⟲</button>
      </div>
      <div class="mapnote" id="mapnote2"></div>
    </div>
    <div id="hourlyCharts"></div>
  </div>
</div>

<div id="t3" class="tabpane maptab">
  <div class="card">
    <h2><span class="dot"></span><span id="tMap3">未来两周（逐日要素）</span></h2>
    <div class="legend">
      <span><i style="background:#C0392B;width:16px;height:11px;border-radius:3px"></i>高风险区（暴雨/8级风）</span>
      <span><i style="background:#E0822C;width:16px;height:11px;border-radius:3px"></i>注意区（大雨/大风）</span>
    </div>
    <div class="mapbox" id="mapbox3">
      <canvas id="mapCanvas3" width="680" height="520"></canvas>
      <svg id="mapOverlay3" viewBox="0 0 680 520" preserveAspectRatio="xMidYMid meet"></svg>
      <div class="mapzoom" id="mapzoom3">
        <button type="button" data-z="in" title="放大">＋</button>
        <div class="zl" id="zl3">1×</div>
        <button type="button" data-z="out" title="缩小">－</button>
        <button type="button" data-z="reset" title="复位">⟲</button>
      </div>
      <div class="mapnote" id="mapnote3"></div>
    </div>
    <div id="explorerInfo" class="explorer-info"></div>
    <div id="explorerCharts"></div>
  </div>
</div>

<script>
const DATA = __DATA__;
const NS = "http://www.w3.org/2000/svg";
const LBL = DATA.meta.kind === "line" ? "测线" : (DATA.meta.kind === "points" ? "作业点" : "工区");
// 作业点「短名」：去掉名称里的项目名与年份前缀（广东-广西深反射0KM → 0KM；XYH2026-SN-01-南端 → SN-01-南端），让地图标签短；
// 若去掉后同一页面出现重名（不同子工区都叫 SN-01），该组退一档只去掉年份（XYH-SN-01-南端），避免撞名。
const MAPTAG = (function(){
  const PL = DATA.points || [], cnt = {};
  const PRE = /^([^-]{1,12}?)(19|20)\d{2}-/;          // 形如 XYH2026- / 大关项目2026-
  const base = s => s.replace(PRE, "");
  // 项目名前缀：逐字符与项目名对齐（跳过连字符/下划线），把「广东-广西深反射0KM」→「0KM」
  const NM = (DATA.meta.name || "").replace(/[-_\s·]+/g, "");
  const spanName = (s, nm) => { let i=0, j=0;
    while(i < s.length && j < nm.length){
      if(s[i] === nm[j]){ i++; j++; }
      else if(s[i]==="-"||s[i]==="_"||s[i]===" "||s[i]==="·") i++;
      else return -1;                       // 该项目名不在这段名称里，原样返回
    }
    return j < nm.length ? -1 : i; };
  const stripNm = s => { if(!NM || s.length <= NM.length) return s;
    const k = spanName(s, NM); if(k <= 0) return s;
    const rest = s.slice(k).replace(/^[-_\s·]+/, ""); return rest || s; };
  PL.forEach(p => { const t = base(p.loc || ""); if(t) cnt[t] = (cnt[t] || 0) + 1; });
  return PL.map(p => {
    const full = p.loc || "";
    if(!full) return "#" + (p.idx + 1);
    const t = stripNm(full) || full;        // ① 项目名前缀命中 → 剥掉即用（广东-广西深反射0KM → 0KM）
    if(t !== full) return t;
    const t0 = base(full);                  // ② 年份 / 子工区名剥离
    if(!t0) return full;
    if(cnt[t0] > 1){ const mid = full.replace(/(19|20)\d{2}(?=-)/, ""); return mid || full; }   // 保留分隔符 → XYH-SN-01-南端
    return t0;
  });
})();
function ptTag(i){ const p = (DATA.points || [])[i]; if(!p) return "";
  return MAPTAG[i] !== undefined ? MAPTAG[i] : (p.loc || ("#" + (i + 1))); }
let SEL = -1;  // 当前选中作业点；提前声明，供时间轴初始化时调用
const VIEW = {};          // 各地图视图状态：{sc 连续缩放倍率(1=适配画布), cx, cy 视图中心}
const PROJ = {};          // 各地图最近投影参数：{z, sc, scFit, W, Hh, Xc, Yc}（供平移/缩放换算）
const ZMIN = 0.5, ZMAX = 24;               // 缩放倍率区间
const TILE_CACHE = new Map();              // 瓦片缓存 url -> {img, ok}：拖动时同步直绘，不再等网络
let _tileTimer = 0;
function queueTileDraw(suffix){            // 新瓦片到位后合并触发一次重绘（60ms 窗口）
  if(_tileTimer) return;
  _tileTimer = setTimeout(()=>{ _tileTimer = 0; renderMap(suffix); }, 60);
}
const _rafPend = {};
function scheduleRender(suffix){           // 拖动/缩放时每帧至多重绘一次（rAF 节流＝丝滑的关键）
  if(_rafPend[suffix]) return;
  _rafPend[suffix] = requestAnimationFrame(()=>{ _rafPend[suffix] = 0; renderMap(suffix); updZL(suffix); });
}
const _txtW = (t,fs) => t.split("").reduce((a,ch)=>a+(ch.charCodeAt(0)>255?fs:fs*0.56),0);
let DAY_SEL = -1;         // 「未来两周」图表点选的日期索引（-1 未选）
const _ln = (DATA.meta.multi && DATA.meta.lines) ? DATA.meta.lines.map(l=>l.name).join(" + ") : (DATA.meta.lineName || "测线");
document.getElementById("titleH1").textContent = DATA.meta.name + (DATA.meta.kind === "line"
  ? " · " + _ln + "两周天气看板"
  : (DATA.meta.kind === "points" ? " · 作业点两周天气看板" : " · 工区两周天气看板"));
document.getElementById("tMap2").textContent = LBL + "未来 48 小时（逐小时风险）";
document.getElementById("tMap3").textContent = LBL + "未来 两周（逐日要素）";
document.getElementById("tImpact").textContent = "物探作业天气影响与建议";
document.getElementById("tStats").textContent = "关键指标（" + LBL + " 未来 48 小时）";
const _cl=document.getElementById("centerLegend"); if(_cl) _cl.textContent = DATA.meta.kind === "points" ? "◈＝作业点中心" : (DATA.isLine ? "◈＝测线中点" : "◈＝工区中心");
const P = DATA.peaks, H = DATA.hourly;
// PN＝未来 48 小时（近 2 天）聚合，供 t1「重点提示」；FARALERT＝第 3~14 天的重大极端天气（仅重大才提示）
const PN = DATA.peaksNear || DATA.peaks;
const FARALERT = DATA.farAlert || {has:false, days:[], text:""};
const NEAR_H = Math.min((DATA.meta && DATA.meta.hourlyWindow) || 48, (DATA.hourly && DATA.hourly.time) ? DATA.hourly.time.length : 48);

function el(tag, attrs){ const e=document.createElementNS(NS,tag); for(const k in attrs) e.setAttribute(k,attrs[k]); return e; }

// ============ 降水类型图标（降雨 / 降雪 / 雨夹雪）============
// 类型码：0=无 1=降雨 2=降雪 3=雨夹雪（与取数端 ptype_of() 一致）
const PTYPE_TEXT = {0:"", 1:"降雨", 2:"降雪", 3:"雨夹雪"};
function ptypeText(pt){ return PTYPE_TEXT[pt] || ""; }
// 降水柱按「类型」着色（不再画柱内图标）：降雨=蓝 降雪=青 雨夹雪=紫；未知类型兜底灰蓝
const PT_FILL = {1:"#2E86DE", 2:"#5DD6E8", 3:"#B07CD6"};
const PT_FILL_FB = "#9DB4C8";
// 在 parent 上以 (cx,cy) 为中心画一个「高约 H」的类型图标；color 为图标颜色（柱内建议 "#fff"）
function precipIcon(parent, ptype, cx, cy, H, color){
  if(!ptype || !(H>2.5)) return null;
  const g=el("g",{"class":"ptico"});
  const drop=(ax,ay,h)=>{ const k=h/6.75;
    g.appendChild(el("path",{d:`M${ax} ${ay-k*3.4} C${ax+k*1.55} ${ay-k*1.35} ${ax+k*2.4} ${ay-k*0.25} `
      +`${ax+k*2.4} ${ay+k*0.95} A ${k*2.4} ${k*2.4} 0 1 1 ${ax-k*2.4} ${ay+k*0.95} `
      +`C${ax-k*2.4} ${ay-k*0.25} ${ax-k*1.55} ${ay-k*1.35} ${ax} ${ay-k*3.4} Z`, fill:color})); };
  const snow=(ax,ay,h)=>{ const k=h/6.2, sw=Math.max(0.9,k*1.05);
    [[0,-1,0,1],[0.866,-0.5,-0.866,0.5],[0.866,0.5,-0.866,-0.5]].forEach(v=>{
      g.appendChild(el("line",{x1:ax+v[0]*k*3.1,y1:ay+v[1]*k*3.1,x2:ax+v[2]*k*3.1,y2:ay+v[3]*k*3.1,
        stroke:color,["stroke-width"]:sw,["stroke-linecap"]:"round"})); }); };
  if(ptype===1) drop(cx,cy,H);
  else if(ptype===2) snow(cx,cy,H);
  else { drop(cx-H*0.62, cy, H*0.62); snow(cx+H*0.62, cy, H*0.48); }   // 雨夹雪：左雨滴 + 右雪花
  parent.appendChild(g);
  return g;
}
// 类型图标的横向占位宽度（雨夹雪最宽），用于判断柱宽是否容得下
function ptypeIconW(ptype, H){ return ptype===3 ? H*1.25 : H*0.72; }
// 在柱内靠顶画类型图标；柱太矮（放不下）时改画在柱顶上方并用深色 + 半透明。
// 返回 {H, above} 供数值标注避让；未绘制返回 null。
function precipIconInBar(parent, ptype, cx, base, bh, bw){
  if(!ptype) return null;
  let H=Math.min(bw*0.95, 11);
  if(bh >= H + 5){                                  // 柱体够高 → 柱内顶部（白色图标）
    const gi=precipIcon(parent, ptype, cx, base-bh+H/2+1.5, H, "rgba(255,255,255,.95)");
    return gi ? {H:H, above:false, g:gi} : null;
  }
  H=Math.min(bw*0.95, 9);                           // 柱太矮 → 柱顶上方（深色、不占柱体）
  if(H<3) return null;
  if(ptypeIconW(ptype,H) > bw*0.98) H=bw*0.98/(ptype===3?1.25:0.72);
  if(H<3) return null;
  const gi=precipIcon(parent, ptype, cx, base-bh-H/2-1.5, H, "rgba(84,110,122,.92)");
  return gi ? {H:H, above:true, g:gi} : null;
}

// ---- 工区地形图（Esri World Topo 瓦片底图）+ 风险区 ----
function renderMap(suffix){
  let poly = DATA.isLine ? DATA.line : DATA.polygon;
  // 回退：测线+作业点模式 isLine=False 且 polygon 为空（测线项目无 Polygon），用 DATA.line 作为骨架
  if((!poly || !poly.length) && DATA.line && DATA.line.length) poly = DATA.line;
  if(DATA.isLine && DATA.lines){ const all=[]; DATA.lines.forEach(L=>L.forEach(p=>all.push(p))); poly=all; }
  const lons = poly.map(p=>p[0]), lats = poly.map(p=>p[1]);
  DATA.points.forEach(p=>{ lons.push(p.lon); lats.push(p.lat); });
  if(DATA.dataLines) DATA.dataLines.forEach(L=>L.forEach(p=>{ lons.push(p[0]); lats.push(p[1]); }));
  if(DATA.lines) DATA.lines.forEach(L=>L.forEach(p=>{ lons.push(p[0]); lats.push(p[1]); }));
  const minlon=Math.min(...lons), maxlon=Math.max(...lons);
  const minlat=Math.min(...lats), maxlat=Math.max(...lats);
  const lat0=(minlat+maxlat)/2;
  // ---- Web Mercator 投影 + Esri World Topo Map 瓦片底图（支持缩放 / 平移） ----
  const mb=document.getElementById("mapbox"+suffix);
  let W=Math.round((mb?mb.clientWidth:0)||680), pad=30, Hh=210;   // W=容器实际宽度（避免位图变形），Hh 固定＝CSS .mapbox 高度（210px，原 280 的 3/4）
  const lon2x=(lon,z)=>(lon+180)/360*256*Math.pow(2,z);
  const lat2y=(lat,z)=>{const r=lat*Math.PI/180; return (1-Math.log(Math.tan(Math.PI/4+r/2))/Math.PI)/2*256*Math.pow(2,z);};
  // 视图状态（缩放档位 + 中心点）：按 suffix 记忆，切 Tab / 重绘后保留
  const VV=(VIEW[suffix] || (VIEW[suffix]={sc:1,cx:null,cy:null}));
  const kz=VV.sc;                                   // 连续缩放倍率（1=工区适配画布）
  const vcx=(VV.cx===null? (minlon+maxlon)/2 : VV.cx);
  const vcy=(VV.cy===null? (minlat+maxlat)/2 : VV.cy);
  const spanLon=Math.max(maxlon-minlon,1e-6);
  // 瓦片层级：基础层级按工区跨度自适应；缩放按「整档」抬升层级（避免连续缩放时瓦片反复重拉），
  // 档内余数由 sc 承担 —— 于是内容大小随手指连续变化，而瓦片始终以接近 1:1 的清晰度显示。
  const lz=Math.max(-2,Math.min(5,Math.round(Math.log2(kz))));
  let z=Math.round(Math.log2((W*0.7/256)*(360/spanLon)));
  z=Math.max(6,Math.min(z+lz,18));
  const px0=lon2x(minlon,z), px1=lon2x(maxlon,z), py0=lat2y(maxlat,z), py1=lat2y(minlat,z);
  const mw=Math.max(px1-px0,1e-6), mh=Math.max(py1-py0,1e-6);
  // 基础缩放（内容铺满并留 pad）；实际缩放 = 基础缩放 × 缩放档位 kz
  let scFit=Math.min((W-2*pad)/mw,(Hh-2*pad)/mh);
  if(!isFinite(scFit)||scFit<=0) scFit=1;
  const sc=scFit*kz;
  const Xc=lon2x(vcx,z), Yc=lat2y(vcy,z);          // 视图中心（墨卡托像素）
  const ox=W/2+(px0-Xc)*sc, oy=Hh/2+(py0-Yc)*sc;   // 内容左上角在画布中的位置
  const xOf=(lon,lat)=> W/2+(lon2x(lon,z)-Xc)*sc;
  const yOf=(lon,lat)=> Hh/2+(lat2y(lat,z)-Yc)*sc;   // 真北朝上：纬度越高 → lat2y 越小 → y 越小（越靠上）
  const cv=document.getElementById("mapCanvas"+suffix), ctx=cv.getContext("2d");
  cv.width=W; cv.height=Hh;
  ctx.fillStyle="#ECE7DF"; ctx.fillRect(0,0,W,Hh);
  const svg=document.getElementById("mapOverlay"+suffix); svg.setAttribute("viewBox","0 0 "+W+" "+Hh);
  // ---- Esri World Topo Map 瓦片底图（带缓存：拖动时已加载瓦片同步直绘，不再等待网络） ----
  const TILE=256;
  // 瓦片铺满整个画布：按画布像素反推墨卡托范围
  const mx0=Xc-(W/2)/sc, mx1=Xc+(W/2)/sc, my0=Yc-(Hh/2)/sc, my1=Yc+(Hh/2)/sc;
  const tx0=Math.floor(mx0/TILE), tx1=Math.floor(mx1/TILE);
  const ty0=Math.floor(my0/TILE), ty1=Math.floor(my1/TILE);
  for(let ty=ty0;ty<=ty1;ty++) for(let tx=tx0;tx<=tx1;tx++){
    const sx=W/2+(tx*TILE-Xc)*sc, sy=Hh/2+(ty*TILE-Yc)*sc, sw=TILE*sc, sh=TILE*sc;
    const url=`https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/${z}/${ty}/${tx}`;
    const en=TILE_CACHE.get(url);
    if(en){ if(en.ok) ctx.drawImage(en.img,sx,sy,sw,sh); }    // 命中缓存 → 同步直绘（拖动丝滑的关键）
    else{
      const img=new Image(); img.crossOrigin="anonymous";
      const ent={img:img, ok:false};
      img.onload=()=>{ ent.ok=true; queueTileDraw(suffix); }; // 新瓦片到位 → 合并触发一次重绘
      img.onerror=()=>{ ent.err=true; };
      img.src=url;
      if(TILE_CACHE.size>800) TILE_CACHE.clear();
      TILE_CACHE.set(url, ent);
    }
  }
  function borderSvg(){
    let s="";
    // ① 工区外框（Polygon）：复合工区（如大关＝区块边框＋北/中/南线）**必须先画外框**，
    //    不能因为有 DATA.lines 就整段跳过——否则外框消失、只剩测线。
    const pg=(DATA.polygon && DATA.polygon.length)?DATA.polygon:null;
    if(pg){
      s+="M"+xOf(pg[0][0],pg[0][1]).toFixed(1)+" "+yOf(pg[0][0],pg[0][1]).toFixed(1);
      for(let i=1;i<pg.length;i++) s+=" L"+xOf(pg[i][0],pg[i][1]).toFixed(1)+" "+yOf(pg[i][0],pg[i][1]).toFixed(1);
      s+=" Z";   // 真 Polygon 边框，强制闭合
    }
    // ② 测线骨架：仅当没有 dataLines 会去渲染它们时才在这里画，避免同一批线被画两遍
    //    （纯测线项目：无 polygon、dataLines 为 None → 由边框层画线）
    if(DATA.lines && !DATA.dataLines){
      DATA.lines.forEach(L=>{
        s+=" M"+xOf(L[0][0],L[0][1]).toFixed(1)+" "+yOf(L[0][0],L[0][1]).toFixed(1);
        for(let i=1;i<L.length;i++) s+=" L"+xOf(L[i][0],L[i][1]).toFixed(1)+" "+yOf(L[i][0],L[i][1]).toFixed(1); });
    }
    // ③ 兜底：既无 polygon 也无 lines（单线骨架），沿用原逻辑
    if(!s && poly && poly.length){
      s+="M"+xOf(poly[0][0],poly[0][1]).toFixed(1)+" "+yOf(poly[0][0],poly[0][1]).toFixed(1);
      for(let i=1;i<poly.length;i++) s+=" L"+xOf(poly[i][0],poly[i][1]).toFixed(1)+" "+yOf(poly[i][0],poly[i][1]).toFixed(1);
      // 仅当首尾相同（真闭合）才加 Z；测线不强制闭合起点终点
      const _cl = poly.length>2 && Math.abs(poly[0][0]-poly[poly.length-1][0])<1e-6 && Math.abs(poly[0][1]-poly[poly.length-1][1])<1e-6;
      s+=(_cl?" Z":"");
    }
    return s;
  }
  // ---- 矢量覆盖层（含风险区，全 SVG，避免被异步瓦片覆盖） ----
  svg.innerHTML="";
  for(let gx=(ox%64+64)%64; gx<W; gx+=64)
    svg.appendChild(el("line",{x1:gx,y1:0,x2:gx,y2:Hh,stroke:"rgba(255,255,255,.28)",["stroke-width"]:1}));
  for(let gy=(oy%64+64)%64; gy<Hh; gy+=64)
    svg.appendChild(el("line",{x1:0,y1:gy,x2:W,y2:gy,stroke:"rgba(255,255,255,.28)",["stroke-width"]:1}));
  // ---- 行政地名层（中文，按当前视野裁剪；缩小看全局时只留地级市，放大后才出县级） ----
  // 注意：默认视图只框住工区，周边地级市往往全在视野外；此时必须放县级，否则一个地名都画不出来
  (function drawPlaces(){
    const PL=DATA.places||[];
    if(!PL.length) return;
    const pass=(showC,margin)=>{
      const boxes=[];                     // 已占位框，防止地名互相压字
      let n=0;
      PL.forEach(p=>{
        const lv=p[3];
        if(lv!==1 && !showC) return;
        const x=xOf(p[1],p[2]), y=yOf(p[1],p[2]);
        if(x<-margin||x>W+margin||y<-margin||y>Hh+margin) return;
        let nm = lv===1 ? p[0].replace(/[市盟]$/,"").replace(/地区$/,"") : p[0].replace(/[县区]$/,"");
        if(lv===1 && nm.length>4) nm=nm.slice(0,4);      // 自治州等长名截断，避免压图
        if(!nm) return;
        const fs = lv===1?10.5:9, w=_txtW(nm,fs);
        const bx=[x-w/2-2, y-fs, x+w/2+2, y+3];
        for(let i=0;i<boxes.length;i++){ const b=boxes[i];
          if(!(bx[2]<b[0]||bx[0]>b[2]||bx[3]<b[1]||bx[1]>b[3])) return; }
        boxes.push(bx);
        const t=el("text",{x:x,y:y,["text-anchor"]:"middle",["font-size"]:fs,
          ["font-weight"]:lv===1?700:500, fill:lv===1?"#2b3641":"#4d5b67",
          stroke:"rgba(255,255,255,.93)",["stroke-width"]:lv===1?2.6:2.1,["paint-order"]:"stroke",
          ["pointer-events"]:"none"});
        t.textContent=nm; svg.appendChild(t); n++;
      });
      return n;
    };
    // 第一遍：常规规则（缩小看全局时只留地级市）；视野内一个都没有 → 放宽裁剪再画一次
    pass(kz>=1 || (PL.length<=30 && kz>=0.85), 30);
    if(svg.querySelectorAll("text[font-size='10.5'],text[font-size='9']").length===0) pass(true, 120);
  })();
  svg.appendChild(el("path",{d:borderSvg(),fill:"none",stroke:"#1a1a1a",["stroke-width"]:3,["stroke-linejoin"]:"round",["stroke-linecap"]:"round"}));
  if(DATA.dataLines){
    const lcol=["#1565C0","#6A1B9A","#00838F","#AD1457","#EF6C00"];
    DATA.dataLines.forEach((lc,di)=>{
      let dd="M"+lc.map(p=>xOf(p[0],p[1]).toFixed(1)+" "+yOf(p[0],p[1]).toFixed(1)).join(" L");
      svg.appendChild(el("path",{d:dd,fill:"none",stroke:lcol[di%lcol.length],["stroke-width"]:2.6,["stroke-linejoin"]:"round",["stroke-linecap"]:"round",["stroke-dasharray"]:"7 4",opacity:0.95}));
    });
  }
  // 风险区（SVG 径向渐变，半径 5/7 km，px 按墨卡托局部尺度）；id 加 suffix 避免双地图 defs 冲突
  const pxKm=256*Math.pow(2,z)/(360*111*Math.cos(lat0*Math.PI/180))*sc;
  const defs=el("defs",{}); svg.appendChild(defs);
  DATA.points.forEach((pt,i)=>{
    if(pt.risk==="ok") return;
    const id="rg"+suffix+i, rcx=xOf(pt.lon,pt.lat), rcy=yOf(pt.lon,pt.lat);
    const R=(pt.risk==="danger"?7:5)*pxKm;
    const c=pt.risk==="danger"?"192,57,43":"224,130,44";
    const grad=el("radialGradient",{id});
    grad.appendChild(el("stop",{offset:"0%","stop-color":`rgba(${c},0.45)`}));
    grad.appendChild(el("stop",{offset:"55%","stop-color":`rgba(${c},0.22)`}));
    grad.appendChild(el("stop",{offset:"100%","stop-color":`rgba(${c},0)`}));
    defs.appendChild(grad);
    svg.appendChild(el("circle",{cx:rcx,cy:rcy,r:R,fill:`url(#${id})`,stroke:`rgba(${c},0.55)`,"stroke-width":1.3}));
  });
  const colmap={ok:"#1F7A6B",warn:"#E0822C",danger:"#C0392B"};
  const PX=[]; const ELS=[];
  DATA.points.forEach(pt=>{
    const c=colmap[pt.risk], cx2=xOf(pt.lon,pt.lat), cy2=yOf(pt.lon,pt.lat);
    if(pt.isCenter) svg.appendChild(el("rect",{x:cx2-CEN_HALF,y:cy2-CEN_HALF,width:CEN_HALF*2,height:CEN_HALF*2,fill:"#fff",stroke:"#111",["stroke-width"]:1.8,transform:`rotate(45 ${cx2} ${cy2})`}));
    const circ=el("circle",{cx:cx2,cy:cy2,r:PT_R[pt.risk]||PT_R.ok,fill:c,stroke:"#fff",["stroke-width"]:PT_KR});
    circ.style.cursor="pointer"; circ.addEventListener("click",()=>selectPoint(pt.idx));
    svg.appendChild(circ);
    // 作业点名称：深色字 + 半透明白底衬（不再用白字/白描边，避免与底图混在一起），字号调小
    const lt = ptTag(pt.idx);
    const LFS=9.5, ltw=_txtW(lt,LFS);
    svg.appendChild(el("rect",{x:cx2-ltw/2-3,y:cy2-13-LFS-1.5,width:ltw+6,height:LFS+4.2,rx:3.5,
      fill:"rgba(255,255,255,.74)",["pointer-events"]:"none"}));
    const lab=el("text",{x:cx2,y:cy2-13,["text-anchor"]:"middle","font-size":LFS,fill:"#1b2733",["font-weight"]:"600"});
    lab.textContent = lt;
    lab.style.cursor="pointer"; lab.addEventListener("click",()=>selectPoint(pt.idx));
    svg.appendChild(lab);
    PX.push({x:cx2,y:cy2,idx:pt.idx});
    ELS.push({idx:pt.idx, circ, lab, x:cx2, y:cy2});
  });
  let selLabel=document.getElementById("selLabel"+suffix);
  if(!selLabel){ selLabel=el("text",{id:"selLabel"+suffix,["text-anchor"]:"middle","font-size":11,["font-weight"]:"800",stroke:"rgba(255,255,255,.95)",["stroke-width"]:2.8,["paint-order"]:"stroke",style:"display:none"}); svg.appendChild(selLabel); }
  // 比例尺（按墨卡托 px/km，约束不超画布）
  const gkm=DATA.meta.gridKm;
  let barLen=Math.min(gkm*pxKm, W-40), bx=Math.min(Math.max(ox,8), W-8-barLen), by=Hh-12;
  svg.appendChild(el("line",{x1:bx,y1:by,x2:bx+barLen,y2:by,stroke:"#222",["stroke-width"]:3}));
  const bt=el("text",{x:bx+barLen/2,y:by-5,["text-anchor"]:"middle","font-size":11,fill:"#222",["font-weight"]:"700"}); bt.textContent=gkm+" km"; svg.appendChild(bt);
  // 真北箭头（瓦片底图北朝上，固定指向上方；贴右上角最边缘，左上角让给 ＋/－ 按钮）
  const na_bx=W-12, na_by=16, L=11, ah=5, aw=Math.PI/6.5;
  const tipx=na_bx, tipy=na_by-L;
  svg.appendChild(el("circle",{cx:na_bx,cy:na_by,r:9,fill:"rgba(255,255,255,.7)",stroke:"#9a9a9a",["stroke-width"]:1}));
  svg.appendChild(el("line",{x1:na_bx,y1:na_by+4,x2:tipx,y2:tipy,stroke:"#444",["stroke-width"]:1.8,["stroke-linecap"]:"round"}));
  const a1x=tipx-ah*Math.cos(Math.PI/2-aw), a1y=tipy+ah*Math.sin(Math.PI/2-aw);
  const a2x=tipx+ah*Math.cos(Math.PI/2-aw), a2y=tipy+ah*Math.sin(Math.PI/2-aw);
  svg.appendChild(el("path",{d:`M${tipx.toFixed(1)} ${tipy.toFixed(1)} L${a1x.toFixed(1)} ${a1y.toFixed(1)} L${a2x.toFixed(1)} ${a2y.toFixed(1)} Z`,fill:"#C0392B",["stroke-width"]:0}));
  const nt=el("text",{x:na_bx,y:na_by+L+5,["text-anchor"]:"middle","font-size":9,fill:"#C0392B",["font-weight"]:"800"}); nt.textContent="N"; svg.appendChild(nt);
  window["POINT_PX"+suffix]=PX; window["POINT_ELS"+suffix]=ELS;
  PROJ[suffix]={z:z, sc:sc, scFit:scFit, W:W, Hh:Hh, Xc:Xc, Yc:Yc};   // 记录投影参数，供拖拽/缩放换算
  redrawSelRing(suffix);                                  // 重绘后补画选中环
  // 地图空白处点击 → 命中最近作业点（拖拽平移后不触发）
  svg.style.cursor="crosshair";
  if(!svg._mapClick){ svg._mapClick=function(ev){
    if(svg._justPanned) return;
    const ptN = svg.createSVGPoint(); ptN.x=ev.clientX; ptN.y=ev.clientY;
    const loc = ptN.matrixTransform(svg.getScreenCTM().inverse());
    let best=-1, bd=1e9;
    (window["POINT_PX"+suffix]||[]).forEach(p=>{ const d=Math.hypot(p.x-loc.x, p.y-loc.y); if(d<bd){bd=d; best=p.idx;} });
    if(best>=0 && bd<=28) selectPoint(best);
  }; svg.addEventListener("click", svg._mapClick); }   // 防重复绑定
}

// ============ 地图缩放 / 平移（滚轮·按钮·双指捏合 + 拖拽平移，全部连续缩放） ============
function updZL(suffix){
  const zl=document.getElementById("zl"+suffix); if(!zl) return;
  const V=VIEW[suffix]||(VIEW[suffix]={sc:1,cx:null,cy:null});
  zl.textContent = (V.sc<1 ? V.sc.toFixed(2) : V.sc.toFixed(1)) + "×";
}
// 以画布坐标 (ax,ay) 为锚点把缩放倍率乘以 f —— 锚点处的地理位置在缩放前后保持不动
function zoomAt(suffix, f, ax, ay){
  const V=VIEW[suffix]||(VIEW[suffix]={sc:1,cx:null,cy:null});
  const p=PROJ[suffix];
  const nsc=Math.max(ZMIN, Math.min(ZMAX, V.sc*f));
  if(Math.abs(nsc-V.sc)<1e-6) return;
  if(p && p.scFit){
    // 反推「与层级无关」的常数 K = sc·2^z / 缩放倍率，再据新倍率与新层级算新 sc
    const lzOld=Math.max(-2,Math.min(5,Math.round(Math.log2(V.sc))));
    const zNew=Math.max(6,Math.min(p.z-lzOld+Math.max(-2,Math.min(5,Math.round(Math.log2(nsc)))),18));
    const scNew=p.sc*Math.pow(2,p.z-zNew)*(nsc/V.sc);
    const s0=256*Math.pow(2,p.z);                                     // 旧层级下的墨卡托总像素
    const Xa=p.Xc+(ax-p.W/2)/p.sc, Ya=p.Yc+(ay-p.Hh/2)/p.sc;          // 锚点当前墨卡托像素
    const Xc1=Xa-(ax-p.W/2)/scNew, Yc1=Ya-(ay-p.Hh/2)/scNew;
    V.cx=Xc1/s0*360-180;
    V.cy=(2*Math.atan(Math.exp((1-2*Yc1/s0)*Math.PI))-Math.PI/2)*180/Math.PI;
  }
  V.sc=nsc;
}
function setZoom(suffix, dir, ax, ay){
  const V=VIEW[suffix]||(VIEW[suffix]={sc:1,cx:null,cy:null});
  if(dir==="reset"){ V.sc=1; V.cx=null; V.cy=null; renderMap(suffix); updZL(suffix); return; }
  const mb=document.getElementById("mapbox"+suffix);
  const W=(mb?mb.clientWidth:680)||680, Hh=210;
  if(ax===undefined||ax===null||ay===undefined||ay===null){ ax=W/2; ay=Hh/2; }
  // dir 可以是字符串("in"/"out"，按钮) 也可以是数字倍率(双指捏合：本次间距/上次间距)。
  // 以前只认字符串，导致捏合恒走 1/1.6＝「一张开就缩小」—— 方向是反的。
  const f = (typeof dir==="number") ? dir : (dir==="in"?1.6:1/1.6);
  zoomAt(suffix, f, ax, ay);
  updZL(suffix);            // 同步刷新倍率数字，不等 rAF（按钮手感）
  scheduleRender(suffix);
}
function panBy(suffix, dx, dy){
  const p=PROJ[suffix]; if(!p) return;
  const V=VIEW[suffix]||(VIEW[suffix]={sc:1,cx:null,cy:null});
  const s=256*Math.pow(2,p.z);
  const Xc=p.Xc - dx/p.sc, Yc=p.Yc - dy/p.sc;
  V.cx = Xc/s*360-180;
  V.cy = (2*Math.atan(Math.exp((1-2*Yc/s)*Math.PI))-Math.PI/2)*180/Math.PI;
}
// 作业点图标几何（全局唯一来源）：renderMap 绘制、updatePoints 逐小时改色、redrawSel 选中环
// 三处必须引用同一套数，否则「按小时改色」或「切 Tab 重绘」时圆点大小会跳变。
const PT_R={ok:6.4,warn:7.2,danger:8.0};   // 圆点半径（旧 9/10/11 → 约 0.73 倍）
const PT_KR=1.5;                            // 白描边宽度（旧 2）
const PT_RING=13;                           // 选中环半径（比最大圆点大 5px；旧 18 配旧大点）
const CEN_HALF=6.4;                         // 中心点菱形半边长（旧 9）
function redrawSelRing(suffix){
  if(SEL<0 || !window["POINT_PX"+suffix]) return;
  const svg=document.getElementById("mapOverlay"+suffix); if(!svg) return;
  let ring=document.getElementById("selRing"+suffix);
  if(!ring){ ring=document.createElementNS(NS,"circle"); ring.setAttribute("id","selRing"+suffix);
    ring.setAttribute("fill","none"); ring.setAttribute("stroke","#111"); ring.setAttribute("stroke-width","3"); }
  // 测线筛选后点集换了（POINT_PX 只含该测线的点），原 SEL 的全局序号可能已越界 —— 必须守卫
  const px=window["POINT_PX"+suffix][SEL];
  if(!px){ ring.setAttribute("r",0); return; }
  ring.setAttribute("cx",px.x); ring.setAttribute("cy",px.y); ring.setAttribute("r",PT_RING);
  svg.appendChild(ring);
  updateSelLabel(suffix);
}
function bindMap(suffix){
  const svg=document.getElementById("mapOverlay"+suffix); if(!svg) return;
  // 画布坐标 ← 客户端坐标（viewBox 与 CSS 尺寸通常 1:1，仍做换算以防缩放/DPR 差异）
  const toCv=(cx,cy)=>{ const r=svg.getBoundingClientRect();
    const kx=(svg.viewBox.baseVal.width||r.width)/(r.width||1);
    const ky=(svg.viewBox.baseVal.height||r.height)/(r.height||1);
    return [(cx-r.left)*kx, (cy-r.top)*ky]; };
  const zx=document.getElementById("mapzoom"+suffix);
  if(zx) zx.querySelectorAll("button").forEach(b=>b.addEventListener("click",(ev)=>{ ev.stopPropagation(); setZoom(suffix, b.dataset.z); }));
  svg.addEventListener("wheel",(ev)=>{ ev.preventDefault();
    const a=toCv(ev.clientX,ev.clientY); setZoom(suffix, ev.deltaY<0?"in":"out", a[0], a[1]); },{passive:false});
  // ---- 统一指针手势：鼠标 / 触摸 / 触控笔走同一套 Pointer Events（手机端可用性的关键）----
  // 旧实现拆成 mouse* + touch*，两个在手机上都会坏：
  //   ① 单指 touchstart 里 preventDefault() 会掐掉浏览器随后补发的 click，而选点是绑在 click 上的
  //      → 手机上点作业点永远没反应（电脑有鼠标，click 正常，所以只在手机上暴露）。
  //   ② 双指捏合被浏览器自身的「页面缩放」抢走，touchmove 一旦被判定为页面缩放就不可取消，preventDefault 无效。
  // 改用 Pointer Events + touch-action:none（见 .mapbox 的 CSS）后，两处都通，且桌面端行为不变。
  let act=new Map();          // pointerId -> {x,y}；size>=2 即双指
  let mode=null;              // "pan" | "pinch"
  let moved=false, last=null, pd=0, pmx=0, pmy=0;
  const two=()=>{ const v=[...act.values()]; return v.length>=2?[v[0],v[1]]:null; };
  svg.addEventListener("pointerdown",(ev)=>{
    if(ev.pointerType==="mouse" && ev.button!==0) return;
    try{ if(svg.setPointerCapture) svg.setPointerCapture(ev.pointerId); }catch(_){}
    act.set(ev.pointerId,{x:ev.clientX,y:ev.clientY});
    if(act.size===1){ mode="pan"; moved=false; last={x:ev.clientX,y:ev.clientY}; }
    else if(act.size===2){ mode="pinch"; moved=true;                 // 双指落下即算「拖过」，抬手不选点
      const t=two();
      pd=Math.hypot(t[0].x-t[1].x, t[0].y-t[1].y);
      pmx=(t[0].x+t[1].x)/2; pmy=(t[0].y+t[1].y)/2; }
  });
  svg.addEventListener("pointermove",(ev)=>{
    if(!act.has(ev.pointerId)) return;
    act.set(ev.pointerId,{x:ev.clientX,y:ev.clientY});
    const t=two();
    if(mode==="pinch" && t){
      // 用两指中点做锚点：即使两指的 Map 顺序帧间对调，中点/间距仍然稳定，平移方向不会翻
      const d=Math.hypot(t[0].x-t[1].x, t[0].y-t[1].y);
      const mx=(t[0].x+t[1].x)/2, my=(t[0].y+t[1].y)/2;
      if(pd>0 && d>0){ const an=toCv(mx,my); setZoom(suffix, d/pd, an[0], an[1]); }   // 张开 → d/pd>1 → 放大
      if(pmx) panBy(suffix, mx-pmx, my-pmy);                                          // 双指整体位移 → 平移
      pd=d; pmx=mx; pmy=my;
      scheduleRender(suffix);
    } else if(mode==="pan" && act.size===1 && last){
      if(!moved && Math.hypot(ev.clientX-last.x, ev.clientY-last.y)<4) return;        // 4px 阈值：轻点别被吃掉
      moved=true;
      panBy(suffix, ev.clientX-last.x, ev.clientY-last.y);
      last={x:ev.clientX,y:ev.clientY};
      scheduleRender(suffix);
    }
  });
  const up=(ev)=>{
    if(!act.has(ev.pointerId)) return;
    const n=act.size; act.delete(ev.pointerId);
    if(n===1 && mode==="pan" && !moved){          // 没拖动＝轻点：手机上 click 不可靠，这里自己兜
      svg._justPanned=false;
      if(svg._mapClick) svg._mapClick(ev);
    } else if(n===1 && mode==="pan" && moved){    // 拖过：压住随后补发的 click，免得抬手又选中一个点
      svg._justPanned=true; setTimeout(()=>svg._justPanned=false,260);
    }
    if(!act.size){ mode=null; moved=false; last=null; }
    else if(act.size===1){                        // 双指抬掉一根 → 无缝续成单指平移
      const t=[...act.values()][0]; mode="pan"; moved=true; last={x:t.x,y:t.y};
    }
  };
  svg.addEventListener("pointerup", up);
  svg.addEventListener("pointercancel",(ev)=>{ act.delete(ev.pointerId);
    if(!act.size){ mode=null; moved=false; last=null; } });
}
// 浅色底映射：加粗数值一律「深色字 + 同色系浅底」，底色浅、字色深，文字永不被盖住
const TINT={"#0D47A1":"#D8E9FA","#1565C0":"#D8E9FA","#1A5A87":"#DEECF7","#2E7DA8":"#DEECF7",
  "#0F5B4C":"#D9EFE7","#1F7A6B":"#D9EFE7","#5B2A7D":"#EEE1F7","#8E44AD":"#EEE1F7",
  "#E0822C":"#FBEAD3","#C0392B":"#FADFDB","#7FB3D5":"#E4EFF8"};
const tintOf=c=>TINT[c]||"#EEF2F5";
// 图表内「选中时间」数值读出框（白底描边 + 彩色加粗文本行，行内带浅色底）
function drawValBox(svg, x, rows, geo){
  if(!rows || !rows.length) return;
  const W=geo.W, pl=geo.pl, pr=geo.pr, pt=geo.pt;
  const cw=t=>t.split("").reduce((a,ch)=>a+(ch.charCodeAt(0)>255?13.6:7.5),0);
  const bw=Math.max(96, Math.min(Math.max(...rows.map(r=>cw(r.t)))+22, W-2*pl));
  const lh=17.5, pady=7, bh=rows.length*lh+pady*2;
  let bx=x+10; if(bx+bw>W-pr) bx=x-10-bw; if(bx<pl) bx=pl;
  const by=pt+2;
  svg.appendChild(el("rect",{x:bx,y:by,width:bw,height:bh,rx:7,fill:"rgba(255,255,255,.96)",stroke:"#C0392B",["stroke-width"]:1.2}));
  rows.forEach((r,i)=>{ const ty=by+pady+13+i*lh;
    svg.appendChild(el("rect",{x:bx+6,y:ty-13,width:cw(r.t)+12,height:17.5,rx:5,fill:tintOf(r.c)}));
    const tx=el("text",{x:bx+11,y:ty,"font-size":13.5,fill:r.c,["font-weight"]:"900"});
    tx.textContent=r.t; svg.appendChild(tx); });
}
// ============ 气象要素小图标（2026-09-28）：色块＝风险等级，图形＝要素 ============
// 用法：eic("rain","danger") → 红底雨云；eic("wind") → 灰底风（图例/勾选行，不带风险属性）
const EIC = {
  rain:'<path d="M20 16.6A5 5 0 0 0 18 7h-1.3A8 8 0 1 0 4 15.3"/><path d="M8 13.2v7.6M12 15.2v7.6M16 13.2v7.6"/>',
  snow:'<path d="M12 3.2v17.6M4.2 7.8l15.6 8.4M19.8 7.8 4.2 16.2"/><path d="m12 7-2.2-2.3M12 7l2.2-2.3M12 17l-2.2 2.3M12 17l2.2 2.3"/>',
  wind:'<path d="M3.5 9h10a3 3 0 1 0-3-3"/><path d="M4 13.5h11.5a3 3 0 1 1-3 3"/><path d="M4.2 18h5"/>',
  temp:'<path d="M14 14.8V4.2a2.2 2.2 0 0 0-4.4 0v10.6a4.4 4.4 0 1 0 4.4 0z"/>',
  heat:'<circle cx="12" cy="12" r="4"/><path d="M12 2.6v2.3M12 19.1v2.3M2.6 12h2.3M19.1 12h2.3M5.4 5.4l1.7 1.7M16.9 16.9l1.7 1.7M18.6 5.4l-1.7 1.7M7.1 16.9l-1.7 1.7"/>',
  fog:'<path d="M4 8.4h16M6.6 12h10.8M4 15.6h16"/>',
};
function eic(kind, lvl, small){
  const g = EIC[kind]; if(!g) return "";
  // 等级只有三档；传入未知值（含 undefined）一律退回 .plain，避免出现无底色的「隐形图标」
  const L = (lvl==="ok"||lvl==="warn"||lvl==="danger") ? lvl : "plain";
  return `<span class="eic ${L}${small?" s":""}" aria-hidden="true">`
       + `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"`
       + ` stroke-linecap="round" stroke-linejoin="round">${g}</svg></span>`;
}

// ============ 时间轴：逐小时风险着色 + 作业点风险原因 ============
const COLMAP = {ok:"#1F7A6B", warn:"#E0822C", danger:"#C0392B"};
let CUR_HOUR = 0;
function updateSelLabel(suffix){
  const lab=document.getElementById("selLabel"+suffix);
  if(SEL<0 || !lab || !window["POINT_PX"+suffix]) return;
  const pt=DATA.points[SEL], h=CUR_HOUR;
  const rc=riskClassAtHour(pt,h);
  const txt={ok:"低风险",warn:"注意",danger:"高风险"}[rc];
  let extra="";
  if(pt.hx){
    const f=riskFactorsAtHour(pt,h)||[];
    if(f.length){ const m=f.reduce((a,b)=>b.level>a.level?b:a); extra=" "+m.name+m.val+m.unit; }
  }
  lab.textContent=txt+extra;
  const px=window["POINT_PX"+suffix][SEL];
  lab.setAttribute("x",px.x); lab.setAttribute("y",px.y-26);
  lab.setAttribute("fill", rc==="ok"?"#111":"#C0392B");
  lab.style.display="";
}

// 小时级短时降水分级（mm/h）：>3 大雨 / >6 暴雨 / >15 大暴雨 —— 48 小时口径统一使用（Python 侧同名 RAIN_H，2026-10-09 用户定）
const RAIN_H={heavy:3, storm:6, torrent:15};
// 单要素风险等级（供读数行的小图标着色；阈值与 riskClassAtHour 完全一致，勿各写一套）
const lvRain = v => v>=RAIN_H.storm ? "danger" : (v>=RAIN_H.heavy ? "warn" : "ok");
// 阵风 2026-10-17 新口径：同级比均风高两级风力（阵风八级 17.2 = 均风六级 10.8）
// → 阵风 danger 取 10 级 24.5（lv3）、warn 取 8 级 17.2（lv2）；均风仍 danger 17.2 / warn 10.8。
const lvGust = v => v>=24.5 ? "danger" : (v>=17.2 ? "warn" : "ok");
const lvWind = v => v>=17.2 ? "danger" : (v>=10.8 ? "warn" : "ok");
const lvTemp = v => v>=35 ? "danger" : (v<=0 ? "warn" : "ok");
// 某作业点在第 h 小时的风险等级（ok/warn/danger）
// 降水走「小时级短时降水」口径：≥5mm/h（暴雨，含 ≥10 大暴雨）即高风险，≥2mm/h（大雨）即注意；
// 风/气温：阵风按新口径（danger ≥24.5 = 十级，warn ≥17.2 = 八级），高温 35℃、低温 0℃。
function riskClassAtHour(pt, h){
  if(!pt.hx) return pt.risk;
  const g=pt.hx.gust[h]||0, p=pt.hx.precip[h]||0, t=pt.hx.temp[h]||0;
  const sn=pt.hx.snow? pt.hx.snow[h]||0 : 0;
  const ap=pt.hx.apparent? pt.hx.apparent[h]||0 : 0;
  const vs=pt.hx.vis? pt.hx.vis[h]||0 : 0;
  // 七要素：降水(暴雨≥6/大雨≥3) / 阵风(24.5/17.2) / 气温(≥35/≤0) /
  // 降雪(暴雪≥2/中雪≥0.5) / 体感(酷热≥38·酷寒≤-27 / 炎热≥32·严寒≤-13) / 能见度(<100m/<500m)
  if(g>=24.5 || t>=35 || p>=RAIN_H.storm || sn>=2 || (vs>0&&vs<100) || ap>=38 || ap<=-27) return "danger";
  if(g>=17.2 || t<=0 || p>=RAIN_H.heavy || sn>=0.5 || (vs>0&&vs<500) || ap>=32 || ap<=-13) return "warn";
  return "ok";
}
// 按当前小时重绘所有作业点颜色
function updatePoints(h, suffix){
  const ELS=window["POINT_ELS"+suffix];
  if(!ELS) return;
  ELS.forEach(o=>{
    const pt=DATA.points[o.idx];
    const rc=riskClassAtHour(pt,h);
    o.circ.setAttribute("fill", COLMAP[rc]);
    o.circ.setAttribute("r", PT_R[rc]||PT_R.ok);
    o.lab.setAttribute("fill", rc==="ok"?"#111":"#fff");
  });
}
// 该点在该小时各风险要素及主要原因
function riskFactorsAtHour(pt, h){
  if(!pt.hx) return null;
  const g=pt.hx.gust[h]||0, w=pt.hx.wind[h]||0, p=pt.hx.precip[h]||0, t=pt.hx.temp[h]||0;
  const f=[];
  if(g>=17.2) f.push({name:"阵风", val:g.toFixed(1), unit:"m/s", level:g>=24.5?3:2,
    advice:g>=24.5?"≥10级，钻机塔架/天线/帐篷须停工避风":"8~9级，设备与帐篷需加固、避开阵风时段"});
  if(w>=10.8) f.push({name:"持续风", val:w.toFixed(1), unit:"m/s", level:w>=17.2?3:2,
    advice:w>=17.2?"≥8级，井架/天线须加固，高处作业停工":"≥6级，注意高空作业与帐篷"});
  // 降水：小时级短时降水分级 —— >3 大雨 / >6 暴雨 / >15 大暴雨（暴雨及以上算高风险，2026-10-09 用户定）
  if(p>=RAIN_H.heavy){
    const nm = p>=RAIN_H.torrent ? "短时大暴雨" : (p>=RAIN_H.storm ? "短时暴雨" : "短时大雨");
    f.push({name:nm, val:p.toFixed(1), unit:"mm/h", level:p>=RAIN_H.storm?3:2,
      advice: p>=RAIN_H.torrent ? "大暴雨，短时积水极快、河谷与低洼段须立即撤人停工"
            : (p>=RAIN_H.storm ? "暴雨，低洼/河谷短时积水、便道泥泞，设备撤离低洼并包覆防水"
                                : "大雨，便道湿滑、坡面含水升高，注意落石与防雨防潮")});
  } else if(p>0) f.push({name:"降水", val:p.toFixed(1), unit:"mm/h", level:1, advice:"小雨/间歇降雨，设备注意防雨防潮"});
  if(t>=35) f.push({name:"高温", val:t.toFixed(1), unit:"°C", level:3, advice:"高温，防暑降温、避开正午露天作业"});
  else if(t<=0) f.push({name:"低温/结冰", val:t.toFixed(1), unit:"°C", level:3, advice:"结冰/霜冻，道路与设备防滑"});
  else if(t>=32) f.push({name:"高温", val:t.toFixed(1), unit:"°C", level:1, advice:"偏热，注意防暑"});
  // 体感温度（UTCI 双向）：≥26 偏热 / ≥32 闷热 / ≥38 酷热；≤0 偏冷 / ≤-13 严寒 / ≤-27 极寒
  const ap=(pt.hx.apparent||[])[h]||0;
  if(ap>=26){
    if(ap>=38) f.push({name:"体感酷热", val:ap.toFixed(1), unit:"°C", level:3, advice:"体感酷热，防暑降温、避开正午露天作业"});
    else if(ap>=32) f.push({name:"体感闷热", val:ap.toFixed(1), unit:"°C", level:2, advice:"体感闷热，注意防暑补水"});
    else f.push({name:"体感偏热", val:ap.toFixed(1), unit:"°C", level:1, advice:"偏热，注意通风"});
  } else if(ap<=0){
    if(ap<=-27) f.push({name:"体感极寒", val:ap.toFixed(1), unit:"°C", level:3, advice:"体感极寒，户外作业严防冻伤、设备防冻"});
    else if(ap<=-13) f.push({name:"体感严寒", val:ap.toFixed(1), unit:"°C", level:2, advice:"体感严寒，人员保暖与仪器低温启动"});
    else f.push({name:"体感偏冷", val:ap.toFixed(1), unit:"°C", level:1, advice:"偏冷，注意人员保暖"});
  }
  // 能见度（m）：越低越危险，<1000 起即提示
  const vs=(pt.hx.vis||[])[h]||0;
  if(vs>0 && vs<1000){
    const lv = vs<100?4 : vs<200?3 : vs<500?2 : 1;
    const adv = vs<200?"能见度极低，暂停野外行车与吊装" : (vs<500?"能见度差，减速行车、避免吊装":"能见度偏低，行车谨慎");
    f.push({name:"低能见度", val:Math.round(vs), unit:"m", level:lv, advice:adv});
  }
  return f;
}
function updateReasonPanel(){
  // 2026-10-17 用户要求：地图下方的「各要素值说明」面板删除，
  // 点位信息合并到 48 小时图表最底部的读数条 #hval 里（见 updateHourlyReadout）。
}
// 时间轴已移除：改由点击 48 小时图表任意位置选时（见 selectHour）


document.getElementById("metaLine").textContent = DATA.meta.kind === "points"
  ? `作业点 ${DATA.meta.npts} 个 · ${DATA.meta.start} ~ ${DATA.meta.end} · 数据 ${DATA.meta.gen} 生成`
  : (DATA.meta.kind === "line"
    ? (DATA.meta.multi && DATA.meta.lines
      ? `测线「${DATA.meta.lines.map(l=>l.name+"("+l.km+"km)").join(" + ")}」共 ${DATA.meta.lineKm}km · 网格 ${DATA.meta.gridKm}km · ${DATA.meta.npts} 个作业点 · ${DATA.meta.start} ~ ${DATA.meta.end} · 数据 ${DATA.meta.gen} 生成`
      : `测线「${DATA.meta.lineName}」长度 约 ${DATA.meta.lineKm}km · 网格 ${DATA.meta.gridKm}km · ${DATA.meta.npts} 个作业点 · ${DATA.meta.start} ~ ${DATA.meta.end} · 数据 ${DATA.meta.gen} 生成`)
    : `工区范围 约 ${DATA.meta.lonkm}×${DATA.meta.latkm}km · 网格 ${DATA.meta.gridKm}km · ${DATA.meta.npts} 个作业点 · ${DATA.meta.start} ~ ${DATA.meta.end} · 数据 ${DATA.meta.gen} 生成`);

// ============ 重点关注（未来 48 小时为主口径；远期仅"重大极端天气"才追加提示） ============
// 要素 kind → eic 图标种类（banner 逐要素清单用）；等级 → eic 风险色（lv0 绿 / lv1~2 橙「注意」/ lv3~4 红「预警」，与影响卡一致）
const EIC_KIND = {rain:"rain", snow:"snow", gust:"wind", wind:"wind", utci:"temp", vis:"fog"};
function lvEic(lv){ return (lv>=3) ? "danger" : (lv>=1 ? "warn" : "ok"); }
// 2026-10-17 用户口径：正文改成**逐要素清单**——每个要素只列「最高级别风险」的那一条，
// 给出「要素 / 等级名 / 数值 / 点位」；远期（第 3~14 天）描述另起一行、用不同底色区分。
(function(){
  const SEV=(DATA.meta.sevNear!==undefined?DATA.meta.sevNear:DATA.meta.sev);
  const LBL2=DATA.meta.sevLabelNear||DATA.meta.sevLabel;
  document.body.classList.add("sev"+SEV);
  // 逐要素最高级别风险（Python 侧用 jozzonwx.grade_* 算好，前端不再各写一套阈值）
  const items = (PN.nearItems || []).filter(x => x && x.lv >= 1);
  const fmtV = it => (it.kind === "vis" ? Math.round(it.val) : it.val);
  const rows = items.map(it =>
      `<div class="ai">${eic(EIC_KIND[it.kind], lvEic(it.lv), true)}`
    + `<span class="ai-k">${it.name}</span>`
    + `<span class="ai-lv lv${it.lv}">${it.label}</span>`
    + `<span class="ai-v">${fmtV(it)}<em>${it.unit}</em></span>`
    + `<span class="ai-p">${ptTag(it.idx) || ("#" + ((it.idx||0) + 1))}</span></div>`).join("");
  // 远期（第 3~14 天）另起一行、不同底色
  const far = FARALERT.has
    ? `<div class="far"><b>远期（第 3~14 天）</b>另有 ${FARALERT.text}</div>` : "";
  const empty = `<div class="ai"><span class="ai-k">天气平稳</span>`
    + `<span class="ai-v">未来 48 小时各要素均未达预警阈值，适宜作业</span></div>`;
  const box=document.getElementById("alertBox");
  box.className="alert sevbox";
  box.innerHTML=`<div class="t"><span class="sev-dot"></span>未来 48 小时 · ${LBL2}</div>`
    + `<div class="ailist">${rows || empty}</div>${far}`;
})();

// ---- 关键指标（未来 48 小时；2 列 × 3 行，每格都点名极值所在作业点） ----
// 2026-10-17 用户定版 + 修正：每个要素各自独立取极值所在作业点（可能同点也可能不同点），
// 不得把配对要素锁在同一最值点。例如 气温找最热点、体感找最闷热点；均风找最大均风点、阵风找最大阵风点；
// 降雨找最大降水点、降雪找最大降雪点。
//   第一排  累计降水（降雨 / 降雪）   ｜ 最大降水（降雨 / 降雪）
//   第二排  最高温度（含对应体感）     ｜ 最低温度（含对应最低体感）
//   第三排  最大风速（阵风 / 均风）   ｜ 能见度
// 极值点取 peaksNear.worstPts（Python 侧按 48h 逐小时窗口算好）；体感点由前端独立扫 hx.apparent 全局最值。
const WP = PN.worstPts || {};
const wpVal = k => (WP[k] && WP[k].val !== null && WP[k].val !== undefined) ? WP[k].val : null;
const wpPt  = k => (WP[k] && WP[k].idx !== null && WP[k].idx !== undefined) ? ptTag(WP[k].idx) : "";
// 要素等级（决定图标底色）：直接复用「逐要素最高级别风险」清单里的 level，避免两套阈值
const lvOf  = k => { const it=(PN.nearItems||[]).find(x=>x.kind===k); return it ? it.lv : 0; };
const lvCls = k => { const l=lvOf(k); return l>=3 ? "danger" : (l>=2 ? "warn" : "ok"); };
const tempCls = v => (v>=35 ? "danger" : (v<=0 ? "warn" : "ok"));
const visCls  = v => ((v===null||v===undefined) ? "ok" : (v<200 ? "danger" : (v<500 ? "warn" : "ok")));
// 降水图标色：与「作业天气影响与建议」降水卡同口径（RAIN_H：>3mm/h 注意 / >15mm/h 预警），
// 不再走 grade_rain 的 lv（避免 lv1 中雨被算成绿色，与影响卡橙色不一致）
function rainCls(v){ if(v==null) return "ok"; return (v>=RAIN_H.torrent) ? "danger" : (v>=RAIN_H.heavy ? "warn" : "ok"); }
// 气温图标色：体感温度（UTCI）纳入判据，与影响卡一致——高温(plain≥35 / 体感酷热≥38) 危险，
// 体感偏热≥32 / 低温≤0 / 体感严寒≤-13 注意；分冷热两侧
function tempHotCls(tmax, appMax){ const gA=(appMax!=null)?gradeUtci(appMax):0;
  if((tmax!=null&&tmax>=35) || gA>=3) return "danger"; if(gA>=2) return "warn"; return "ok"; }
function tempColdCls(tmin, appMin){ const gI=(appMin!=null)?gradeUtci(appMin):0;
  if(gI>=3) return "danger"; if((tmin!=null&&tmin<=0) || gI>=2) return "warn"; return "ok"; }
// 体感温度独立取极值所在作业点（2026-10-17 修正）：体感「最闷热 / 最冷体感」与气温最值点是
// 两个独立的最值，必须各自取 hx.apparent 的全局最值点（可能同点也可能不同点），不得共用气温点。
function appPtIdx(mode){ // mode 'max' | 'min' → 体感最值所在作业点索引
  const pts=DATA.points||[]; let bi=-1, bv=(mode==="max"?-Infinity:Infinity);
  for(let i=0;i<pts.length;i++){
    const a=pts[i]&&pts[i].hx&&pts[i].hx.apparent;
    if(!a||!a.length) continue;
    for(const v of a){ if(v===null||v===undefined) continue;
      if(mode==="max" ? v>bv : v<bv){ bv=v; bi=i; } }
  }
  return bi;
}
const appHiPt = (()=>{ const i=appPtIdx("max"); return i>=0 ? ptTag(i) : ""; })();  // 最闷热点
const appLoPt = (()=>{ const i=appPtIdx("min"); return i>=0 ? ptTag(i) : ""; })();  // 最冷体感点
const f1 = v => (v===null||v===undefined) ? "—" : (Math.round(v*10)/10);
// 降雨/降雪累计为 0 时不点名牌（否则会出现「降雪 0.0mm · 某点」这种无意义的点名）
const ptPos = (k, v) => (v > 0 ? wpPt(k) : "");
// 单格：标题 + 若干行（要素 / 数值 / 点名牌）
function statCell(icon, cls, title, rows){
  const body = rows.map(r=>{
    const num = (r.v===null||r.v===undefined) ? "—" : r.v;
    const pt  = r.p ? `<span class="pp">${r.p}</span>` : `<span class="pp na">—</span>`;
    return `<div class="vr">${r.k?`<em>${r.k}</em>`:""}<b>${num}</b>`
         + `${r.u?`<i>${r.u}</i>`:""}${pt}</div>`;
  }).join("");
  return `<div class="stat"><div class="k">${eic(icon,cls)}${title}</div><div class="vs">${body}</div></div>`;
}
const statsHtml = [
  // ① 累计降水：48h 逐小时累加（降雨 = rain+showers，降雪 = snowfall 水当量）
  //    降雨取「累计降水最值点」(sum48)、降雪取「累计降雪最值点」(snow48) —— 各要素独立取极值所在作业点
  statCell("rain", rainCls(PN.pHourMax), "累计降水", [
    {k:"降雨", v:f1(wpVal("sum48")),  u:"mm", p:ptPos("sum48", wpVal("sum48"))},
    {k:"降雪", v:f1(wpVal("snow48")), u:"mm", p:ptPos("snow48", wpVal("snow48"))},
  ]),
  // ② 最大降水：48h 内最强的那一个小时（mm/h，风险分级用的就是这个量）
  //    降雨取「小时降水最值点」(hour)、降雪取「小时降雪最值点」(snow) —— 各要素独立取极值所在作业点
  statCell("rain", rainCls(PN.pHourMax), "最大降水", [
    {k:"降雨", v:f1(wpVal("hour")), u:"mm/h", p:ptPos("hour", wpVal("hour"))},
    {k:"降雪", v:f1(wpVal("snow")), u:"mm/h", p:ptPos("snow", wpVal("snow"))},
  ]),
  // ③ 最高温度 + 体感：气温取最热点(hi)、体感取「最闷热点」(hx.apparent 全局最值点) —— 两个要素独立取极值
  statCell("temp", tempHotCls(PN.tmax, PN.appMax), "最高温度", [
    {k:"气温", v:f1(PN.tmax), u:"℃", p:wpPt("hi")},
    {k:"体感", v:f1(PN.appMax), u:"℃", p:appHiPt},
  ]),
  // ④ 最低温度 + 体感：气温取最冷点(lo)、体感取「最冷体感点」(hx.apparent 全局最值点) —— 两个要素独立取极值
  statCell("temp", tempColdCls(PN.tmin, PN.appMin), "最低温度", [
    {k:"气温", v:f1(PN.tmin), u:"℃", p:wpPt("lo")},
    {k:"体感", v:f1(PN.appMin), u:"℃", p:appLoPt},
  ]),
  // ⑤ 最大风速：阵风取阵风最值点(gust)、均风取均风最值点(wind) —— 两个要素独立取极值
  statCell("wind", lvCls("gust"), "最大风速", [
    {k:"阵风", v:f1(wpVal("gust")),  u:"m/s", p:wpPt("gust")},
    {k:"均风", v:f1(wpVal("wind")), u:"m/s", p:wpPt("wind")},
  ]),
  // ⑥ 能见度（48h 最低值；x1_visibility 缺测则为 —）
  statCell("fog", visCls(PN.visMin), "最低能见度", [
    {k:"", v:(PN.visMin===null||PN.visMin===undefined) ? null : Math.round(PN.visMin), u:"m", p:wpPt("visMin")},
  ]),
].join("");
document.getElementById("statsBox").innerHTML = statsHtml;

// ---- 影响说明（未来 48 小时口径；地图点击联动展示逐小时/逐日明细） ----
// 物探作业影响与建议（2026-09-04）：建议针对整个项目，不要再说"作业点"——
// points 模式下用项目名替代 LBL 里的"作业点"，其他模式沿用 LBL（工区/测线）
// LBL_IMPACT 定义已移除：影响段不再使用前缀（2026-09-04）
const ib=document.getElementById("impactBox");
// icon＝要素图标种类；图标底色沿用当前卡片的 level（预警红 / 注意橙 / 安全绿），与右侧徽标同色
function card(level,title,badge,html,icon){
  const cls = level==="danger"?"imp danger":(level==="warn"?"imp warn":"imp");
  const ic = icon ? eic(icon, level, true) : "";
  return `<div class="${cls}"><div class="h">${ic}${title} <span class="badge ${badge.cls}">${badge.t}</span></div><p>${html}</p></div>`;
}
// 体感温度 UTCI 双向分级（与 weather-common/jozzonwx.grade_utci 完全一致）：返回 level∈0..4，冷/热取较严重一侧
function gradeUtci(v){
  if(v==null) return 0;
  let cold=0;
  if(v<-40) cold=4; else if(v<-27) cold=3; else if(v<-13) cold=2; else if(v<0) cold=1;
  let hot=0;
  if(v>46) hot=4; else if(v>38) hot=3; else if(v>32) hot=2; else if(v>26) hot=1;
  return Math.max(hot,cold);
}
const UTCI_HOT_L=["UTCI正常","低风险偏热预警(>26)","中风险炎热预警(>32)","高风险酷热预警(>38)","极高风险极热预警(>46)"];
const UTCI_COLD_L=["UTCI正常","低风险寒冷预警(<0)","中风险严寒预警(<-13)","高风险酷寒预警(<-27)","极高风险极寒预警(<-40)"];
const daySpan = pp => pp.focusStart ? `${pp.focusStart.slice(5)}~${pp.focusEnd.slice(5)} ` : "";
let out="";
// 降水判据=「小时级短时降水」（>3 大雨 / >6 暴雨 / >15 大暴雨）+ 日累计连续降雨，两者取重
// phS 把小时级峰值写进文案，避免只报日累计、漏掉短时强降水
const pH=PN.pHourMax||0;
const phS = pH>0 ? `；最大小时降水 <b>${pH} mm/h</b>${PN.pHourPoint?"（"+PN.pHourPoint+"）":""}` : "";
if(pH>=RAIN_H.torrent || PN.pMax>=50 || PN.focusTotal>=80){ out+=card("danger","降水 / 短时强降水",{cls:"danger",t:"预警"},
  `${daySpan(PN)}连续强降雨累计 <b>${PN.focusTotal}mm</b>，单日最大 <b>${PN.pMax}mm（暴雨）</b>${phS}${pH>=RAIN_H.torrent?"（大暴雨）":""}。低洼与河谷炮点、山区便道严重泥泞、易陷车；坡面含水饱和，<b>滑坡/泥石流高风险</b>；钻井与地震排列设备需全面防雨防潮。建议：暂停涉水、陡坡及河谷段施工，人员设备撤离高风险斜坡，雨停后待便道充分干燥再进场。`, "rain"); }
else if(pH>=RAIN_H.storm || PN.pMax>=25 || PN.focusTotal>=30){ out+=card("warn","降水 / 短时强降水",{cls:"warn",t:"注意"},
  `${daySpan(PN)}连续降雨累计 <b>${PN.focusTotal}mm</b>，单日最大 <b>${PN.pMax}mm（${PN.pMax>=25?'大雨':'中雨'}）</b>${phS}${pH>=RAIN_H.storm?"（暴雨）":""}。低洼与河谷炮点、山区便道易泥泞、车辆通行困难；坡面含水升高，<b>滑坡/泥石流风险上升</b>；钻井与地震排列设备需做好防雨防潮。建议：推迟涉水与陡坡段施工，雨停后待便道稍干再进场，电缆接头包覆防水。`, "rain"); }
else if(pH>=RAIN_H.heavy){ out+=card("warn","短时大雨 / 泥泞",{cls:"warn",t:"注意"},
  `未来 48 小时日累计降雨量不大，但出现 <b>${pH} mm/h</b> 的短时大雨（${PN.pHourPoint||""}），短时积水与便道湿滑明显。低洼与河谷段注意排水、车辆降速；设备做好防雨防潮，电缆接头包覆防水。`, "rain"); }
else { out+=card("ok","降水 / 泥泞",{cls:"ok",t:"安全"},
  `未来 48 小时无连续中雨以上降雨，最大小时降水 ${pH||0} mm/h，以间歇小雨为主，对便道与设备影响有限，常规防雨即可。`, "rain"); }
if(PN.gustMax>=24.5){ out+=card("danger","大风 / 阵风",{cls:"danger",t:"预警"},
  `阵风达 ${PN.gustMax} m/s（≥10级 狂风），钻机塔架、重力仪/磁力仪天线与帐篷稳定性受严重影响，高处作业必须停工。`, "wind"); }
else if(PN.gustMax>=17.2){ out+=card("warn","大风 / 阵风",{cls:"warn",t:"注意"},
  `阵风达 ${PN.gustMax} m/s（8~9级），钻机与高空设备需加固，谨慎安排吊装/高处作业。`, "wind"); }
else if(PN.windMax>=10.8){ out+=card("warn","大风 / 阵风",{cls:"warn",t:"注意"},
  `均风达 ${PN.windMax} m/s（≥6级），阵风 ${PN.gustMax} m/s，钻机与高空设备需加固，谨慎安排吊装/高处作业。`, "wind"); }
else { out+=card("ok","大风 / 阵风",{cls:"ok",t:"安全"},
  `最大阵风 ${PN.gustMax} m/s（7级及以下）、均风 ${PN.windMax} m/s，不影响钻机、天线及帐篷，常规作业即可。`, "wind"); }
// 气温 / 体感（UTCI 冷热双向：体感温度纳入判据，与石油工程「作业天气影响与建议」一致）
const aMax=PN.appMax, aMin=PN.appMin, _gA=aMax!=null?gradeUtci(aMax):0, _gI=aMin!=null?gradeUtci(aMin):0;
if(aMax!=null && _gA>=3){ out+=card("danger","高温 / 体感酷热",{cls:"danger",t:"预警"},`体感最高温 <b>${aMax}°C</b>（${UTCI_HOT_L[_gA]}），野外作业人员易中暑、设备过热电池衰减，避开正午高强度露天作业、配备降温与补水。`, "heat"); }
else if(aMin!=null && _gI>=2){ out+=card("warn","低温 / 体感严寒",{cls:"warn",t:"注意"},`体感最低温 <b>${aMin}°C</b>（${UTCI_COLD_L[_gI]}），高海拔段可能结冰，人员保暖、电池效能下降需备用电源、设备防冻。`, "snow"); }
else if(aMax!=null && _gA>=2){ out+=card("warn","体感偏热",{cls:"warn",t:"注意"},`体感最高温 <b>${aMax}°C</b>，体感偏热，注意防暑与通风。`, "heat"); }
else { const rng=(aMin!=null&&aMax!=null)?`体感 ${aMin}~${aMax}°C，`:""; out+=card("ok","气温 / 体感",{cls:"ok",t:"适宜"},`气温 ${PN.tmin}~${PN.tmax}°C，${rng}体感适宜；高海拔早晚偏凉，注意人员保暖与仪器低温启动。`, "temp"); }
out+=card("ok","低能见度 / 行车",{cls:"ok",t:"提示"},
  `雨后山区多雾、便道湿滑，越野车与设备转运需降速、保持车距；进场前确认便道承载力。`, "fog");
ib.innerHTML=out;

// 降水类型图例（HTML 版小图标，供降水图表图例使用）
// ic＝可选要素图标（降水图标带在「降水：」文字前，一眼分辨色块对应哪个要素）
function ptLegendHtml(ic){
  const sw=(c,t)=>`<span class="lg"><i style="background:${c}"></i>${t}</span>`;
  return (ic? eic(ic,"plain",true) : "")
       + `<span class="lg" style="font-weight:700">降水：</span>`
       + sw(PT_FILL[1],"降雨") + sw(PT_FILL[2],"降雪") + sw(PT_FILL[3],"雨夹雪");
}
// 选中作业点的逐要素曲线 / 柱状图 ============
const EXPLORER = document.getElementById("explorerCharts");
// 2026-10-17：图表标题 / 系列名 / 图例文案 / 配色 / 几何参数全部与石油工程对齐，
// 阈值线整套去掉（工程两周图不画阈值线，只保留点选数值）。
const ELEM_DEFS = {
  temp:  {name:"逐日气温", unit:"°C", icon:"temp", type:"line2", keys:["tempMax","tempMin"], colors:["#E0822C","#2E7DA8"], labels:["最高温","最低温"]},
  precip:{name:"逐日降水", unit:"mm", icon:"rain", type:"bar", keys:["liquid"], colors:["#2E86DE"], labels:["降雨"]},
  snow:  {name:"逐日降雪", unit:"mm", icon:"snow", type:"bar", keys:["snow"], colors:["#5DD6E8"], labels:["降雪"]},
  wind:  {name:"逐日阵风 / 均风", unit:"m/s", icon:"wind", type:"line2", keys:["gustMax","windMax"], colors:["#C0392B","#7E57C2"], labels:["阵风（日最大）","均风（日最大）"]},
  apparent:{name:"逐日体感温度", unit:"°C", icon:"temp", type:"line2", keys:["appMax","appMin"], colors:["#D84315","#7E57C2"], labels:["最高体感","最低体感"]},
  vis:   {name:"逐日能见度", unit:"m", icon:"fog", type:"line", keys:["visMin"], colors:["#7E57C2"], labels:["当日最低能见度"]},
};
// 「未来两周」固定四图（与石油工程一致）：降水（含降雪并列柱）→ 气温（含体感虚线）→ 阵风·均风 → 能见度
const EXP_CHARTS = ["precip","temp","wind","vis"];
// ============ 图表「自由滑动选值」绑定器（与石油工程 48 小时图一致的 pointer 拖动） ============
// pointerdown 即选中最近一格；按住左右拖动连续跟随（pointermove + 按键态）；轻点同一格再点一次＝取消。
// idxFn(x,w) 由各图表按自身 W/pl/pr/n 反解索引；opt.getSel/cancel/toggle 仅「选日期」用（48 小时选时不需要）。
function bindDragPick(svg, idxFn, apply, opt){
  opt=opt||{};
  let down=false, moved=false, startIdx=-1, prevSel=-1, sx=0;
  const idxAt=(ev)=>{
    const r=svg.getBoundingClientRect(); if(!r.width) return -1;
    const v=idxFn(ev.clientX-r.left, r.width);
    if(v===null||v===undefined||isNaN(v)) return -1;
    return Math.max(0, Math.min((opt.n||1)-1, Math.round(v)));
  };
  svg.style.cursor="crosshair";
  svg.style.touchAction="none";                       // 触屏拖动不被页面滚动抢走
  svg.addEventListener("pointerdown",(ev)=>{
    const i=idxAt(ev); if(i<0) return;
    down=true; moved=false; startIdx=i; sx=ev.clientX;
    prevSel = (opt.getSel? opt.getSel() : -1);      // 记录「按下前」的选中值（不能取按下后的值，否则每次轻点都会取消）
    try{ if(svg.setPointerCapture) svg.setPointerCapture(ev.pointerId); }catch(_){}
    apply(i);
  });
  svg.addEventListener("pointermove",(ev)=>{
    if(!down) return;
    if(!moved && Math.abs(ev.clientX-sx)>2) moved=true;   // 位移 >2px 记为「拖动」
    if(!moved && !ev.buttons) return;
    const i=idxAt(ev); if(i<0) return;
    apply(i);
  });
  const up=()=>{
    if(!down) return; down=false;
    if(!moved && opt.toggle && prevSel===startIdx && opt.cancel) opt.cancel();   // 未拖动且按下的本就是已选那一格 → 取消（再点一次取消）
  };
  svg.addEventListener("pointerup", up);
  svg.addEventListener("pointercancel",()=>{ down=false; });
}
// ============================================================================
// 两周折线图（2026-10-17 与石油工程 render_points_html.svg_lines 完全对齐）
//   viewBox 680×160 / 边距 42·12·14·30 / 4 条网格 / 刻度 12px #999
//   折线 stroke-width 2 / 每点 r=2.6 / 数值 10px（按点位于上半或下半自动 -7 / +12）
//   横轴日期 11px #888，逐日全标（与工程一致）
//   data 里的 null 视为缺测：断开折线、不画点、不标值（能见度后 7 天即此情况）
// ============================================================================
function pointLine(svg, labels, series, opt){
  opt=opt||{};
  const W=680,Hh=160,pl=42,pr=12,pt=14,pb=30;
  svg.setAttribute("viewBox",`0 0 ${W} ${Hh}`); svg.innerHTML="";
  const n=labels.length;
  let lo=Infinity,hi=-Infinity;
  series.forEach(s=>(s.data||[]).forEach(v=>{ if(v===null||v===undefined)return; if(v<lo)lo=v; if(v>hi)hi=v; }));
  if(!isFinite(lo)){ lo=0; hi=1; }
  if(lo===hi){ lo-=1; hi+=1; }
  const pad=(hi-lo)*0.15; lo-=pad; hi+=pad;          // 与工程 _scale 同口径
  const X=i=> pl+(W-pl-pr)*i/Math.max(n-1,1);
  const Y=v=> pt+(Hh-pt-pb)*(1-(v-lo)/(hi-lo));
  const midY=pt+(Hh-pt-pb)/2;
  for(let g=0; g<4; g++){                             // 工程 4 条网格（0,1/3,2/3,1）
    const tv=lo+(hi-lo)*g/3, yv=Y(tv);
    svg.appendChild(el("line",{x1:pl,y1:yv.toFixed(1),x2:W-pr,y2:yv.toFixed(1),stroke:"#ececec"}));
    const tx=el("text",{x:pl-5,y:(yv+3).toFixed(1),["text-anchor"]:"end","font-size":12,fill:"#999"});
    tx.textContent=Math.round(tv); svg.appendChild(tx);
  }
  series.forEach(s=>{
    let d="", pen=false;
    (s.data||[]).forEach((v,i)=>{ if(v===null||v===undefined) return;
      d+=((pen?"L":"M")+X(i).toFixed(1)+" "+Y(v).toFixed(1)+" "); pen=true; });
    if(!d) return;
    const a={"class":"geo",d:d.trim(),fill:"none",stroke:s.color,["stroke-width"]:2,
             ["stroke-linejoin"]:"round",["stroke-linecap"]:"round"};
    if(s.dash) a["stroke-dasharray"]=s.dash;
    svg.appendChild(el("path",a));
    (s.data||[]).forEach((v,i)=>{ if(v===null||v===undefined) return;
      svg.appendChild(el("circle",{"class":"geo",cx:X(i).toFixed(1),cy:Y(v).toFixed(1),r:2.6,fill:s.color}));
      if(s.nolabel) return;
      const ty=Y(v)<midY? -7 : 12;                    // 上半标上方、下半标下方（避免压线）
      const tx=el("text",{x:X(i).toFixed(1),y:(Y(v)+ty).toFixed(1),["text-anchor"]:"middle",
                          "font-size":10,fill:s.color,["font-weight"]:"700"});
      tx.textContent=v.toFixed(1); svg.appendChild(tx);
    });
  });
  for(let i=0;i<n;i++){ if(!labels[i]) continue;
    const tx=el("text",{x:X(i).toFixed(1),y:Hh-9,["text-anchor"]:"middle","font-size":11,fill:"#888"});
    tx.textContent=labels[i]; svg.appendChild(tx); }
  if(opt.pick) bindDragPick(svg, (x,w)=>(x/w*W-pl)/(W-pl-pr)*(n-1), opt.pick.apply,
      {n:n, toggle:opt.pick.toggle, getSel:opt.pick.getSel, cancel:opt.pick.cancel});
  if(opt.pick) svg._pickCtx={n:n, X:X, pt:pt, pb:pb, Hh:Hh, W:W, pl:pl, pr:pr, getRows:opt.getRows};
}
// ============================================================================
// 两周柱状图（与石油工程 svg_bars 完全对齐）
//   基线恒 0 / vmax = max*1.15 / 4 网格 / 柱宽 slot*0.55（单）·0.30（并列）
//   rx=2 / 柱顶数值 11px #444（≥10 取整、否则 1 位小数、无降水单系列标 <0.1）
// ============================================================================
function pointBar(svg, labels, vals, opt){
  opt=opt||{};
  const W=680,Hh=160,pl=42,pr=12,pt=14,pb=30;
  svg.setAttribute("viewBox",`0 0 ${W} ${Hh}`); svg.innerHTML="";
  const n=labels.length;
  const extras=(opt.extra||[]);
  const groups=1+extras.length;
  const seriesList=[{name:opt.label||"降雨", vals:vals, color:opt.color||"#2E86DE"}].concat(extras);
  const allv=[];
  seriesList.forEach(s=>(s.vals||[]).forEach(v=>{ if(typeof v==="number") allv.push(v); }));
  const yMax=(opt.yMax && opt.yMax>0) ? opt.yMax : Math.max(...allv,1)*1.15;
  const X=i=> pl+(W-pl-pr)*(i+0.5)/n;
  const Y=v=> pt+(Hh-pt-pb)*(1-v/yMax);
  for(let g=0; g<4; g++){
    const tv=yMax*g/3, yv=Y(tv);
    svg.appendChild(el("line",{x1:pl,y1:yv.toFixed(1),x2:W-pr,y2:yv.toFixed(1),stroke:"#ececec"}));
    const tx=el("text",{x:pl-5,y:(yv+3).toFixed(1),["text-anchor"]:"end","font-size":12,fill:"#999"});
    tx.textContent=(yMax>=10? Math.round(tv).toString() : (Math.round(tv*10)/10).toString()); svg.appendChild(tx);
  }
  const slot=(W-pl-pr)/n;
  const bw=slot*(groups===1?0.55:0.30);
  const gap=groups===1?0:slot*0.05;
  const base=Y(0);
  for(let i=0;i<n;i++){
    const cx=X(i), gw=bw*groups+gap*(groups-1), gx=cx-gw/2;
    const pt0=(opt.ptypes||[])[i]||0;
    for(let gi=0;gi<groups;gi++){
      const s=seriesList[gi], v=(s.vals&&s.vals[i]!==undefined&&s.vals[i]!==null)? s.vals[i] : 0;
      const bx=gx+gi*(bw+gap);
      if(!(v>0 || (groups===1 && pt0))) continue;     // 无降水不画柱
      const bh=Math.max(base-Y(v),3);
      const color = groups===1 ? (PT_FILL[pt0]||PT_FILL_FB) : s.color;
      svg.appendChild(el("rect",{"class":"geo",x:bx.toFixed(1),y:(base-bh).toFixed(1),
                                 width:bw.toFixed(1),height:bh.toFixed(1),rx:2,fill:color}));
      const lab=(v>=10? Math.round(v).toString() : v.toFixed(1));
      const tx=el("text",{x:(bx+bw/2).toFixed(1),y:(base-bh-4).toFixed(1),["text-anchor"]:"middle","font-size":11,fill:"#444"});
      tx.textContent=lab; svg.appendChild(tx);
    }
    const tx=el("text",{x:cx.toFixed(1),y:Hh-9,["text-anchor"]:"middle","font-size":11,fill:"#888"});
    tx.textContent=labels[i]; svg.appendChild(tx);
  }
  if(opt.pick) bindDragPick(svg, (x,w)=>(x/w*W-pl)/(W-pl-pr)*(n-1), opt.pick.apply,
      {n:n, toggle:opt.pick.toggle, getSel:opt.pick.getSel, cancel:opt.pick.cancel});
  if(opt.pick) svg._pickCtx={n:n, X:X, pt:pt, pb:pb, Hh:Hh, W:W, pl:pl, pr:pr, getRows:opt.getRows};
}
function updateExplorerInfo(){
  const box=document.getElementById("explorerInfo"); if(!box) return;
  if(SEL<0){ box.innerHTML=""; return; }
  const pt=DATA.points[SEL];
  const riskTxt={ok:"低风险",warn:"注意",danger:"高风险"}[pt.risk];
  const riskCls={ok:"ok",warn:"warn",danger:"danger"}[pt.risk];
  box.innerHTML = `<b>${ptTag(pt.idx)}</b> · <span class="badge ${riskCls}">${riskTxt}</span>`
     + (DAY_SEL>=0 && DATA.meta.dailyDates[DAY_SEL] ? `<span class="day-read">已选 ${DATA.meta.dailyDates[DAY_SEL]}</span>` : "");
}
// 「未来两周」选日期：只重绘红色竖线 + 数值框，不重建图表（图形位置与界面保持不动）
function paintDaySel(){
  EXPLORER.querySelectorAll("svg.chart").forEach(sv=>{
    const old=sv.querySelector("g.daySel"); if(old) old.remove();
    const c=sv._pickCtx; if(!c || DAY_SEL<0 || DAY_SEL>=c.n) return;
    const g=document.createElementNS(NS,"g"); g.setAttribute("class","daySel");
    const sx=c.X(DAY_SEL);
    g.appendChild(el("line",{x1:sx,y1:c.pt,x2:sx,y2:c.Hh-c.pb,stroke:"#C0392B","stroke-width":1.6,"stroke-dasharray":"4 3",opacity:.9}));
    drawValBox(g, sx, (c.getRows?c.getRows(DAY_SEL):[]), {W:c.W,Hh:c.Hh,pl:c.pl,pr:c.pr,pt:c.pt,pb:c.pb});
    sv.appendChild(g);
  });
}
function renderExplorer(){
  if(SEL<0){ EXPLORER.innerHTML='<div class="empty-tip">点击上方地图任意作业点，这里将显示该点未来两周的逐要素曲线 / 柱状图。</div>';
    document.getElementById("explorerInfo").innerHTML=''; return; }
  const pt=DATA.points[SEL];
  // 防御：若数据缺少逐日序列（series），给出明确提示而非整段报错导致图表全无。
  if(!pt.series){
    updateExplorerInfo();
    EXPLORER.innerHTML='<div class="empty-tip">该作业点缺少逐日序列数据（series），无法绘制未来两周图表。请用最新版脚本（已修复 series 落盘）重新生成数据。</div>';
    return;
  }
  updateExplorerInfo();
  EXPLORER.innerHTML="";
  const labs=DATA.meta.dailyDates.map(d=>d.slice(5));
  const nd=labs.length;
  const fmtD=v=>String(Math.round(v*10)/10);
  // 说明行「点击任意图表选择日期…」已删除（2026-10-17 用户要求）
  // 选日期：拖动/点击直接设置（不做逐格 toggle，避免拖动时反复闪断）；
  // 「再点同一日取消」由 bindDragPick 的 toggle 逻辑在 pointerup（未拖动）时处理
  const setDay=i=>{ DAY_SEL=i; paintDaySel(); updateExplorerInfo(); };
  const DAY_PICK={ toggle:true, getSel:()=>DAY_SEL, cancel:()=>setDay(-1), apply:i=>setDay(i) };
  // 固定四图（与石油工程完全一致）：降水（降雪并列柱）→ 气温（体感虚线）→ 阵风·均风 → 能见度
  // 横轴逐日全标（工程口径，不再隔天抽稀）
  EXP_CHARTS.forEach(k=>{
    const def=ELEM_DEFS[k];
    // 能见度：数据驱动 —— 该点逐日 visMin 全为 null 时不画（x1_visibility 仅前 162h 有值）
    if(k==="vis" && !(pt.series.visMin||[]).some(v=>v!==null&&v!==undefined)) return;
    // 缺该要素的逐日序列时不画这一图（避免整段报错导致四图全无）
    if(def.type!=="bar" && def.keys.some(kk=>!Array.isArray(pt.series[kk]))) return;
    const box=document.createElement("div"); box.className="ec";
    const h=document.createElement("div"); h.className="ec-h"; h.textContent=`${def.name}（${def.unit}）`;
    const svg=document.createElementNS(NS,"svg"); svg.setAttribute("class","chart");
    svg.setAttribute("preserveAspectRatio","xMinYMin meet");   // 与工程同款：等比缩放不变形
    box.appendChild(h);
    const leg=document.createElement("div"); leg.className="ec-legend";
    box.appendChild(leg);
    box.appendChild(svg); EXPLORER.appendChild(box);
    if(def.type==="bar"){
      // 降水图：降雨与降雪（水当量）同一天内并列两根柱
      const rain=((pt.series[def.keys[0]] || pt.series.precip)||[]).map(v=>v||0);
      const snow=(pt.series.snow||[]).map(v=>v||0);
      const ptypes=pt.series.ptype||[];
      leg.innerHTML=eic(def.icon,"plain",true)
        +`<span class="lg"><i style="background:#2E86DE"></i>降雨</span>`
        +`<span class="lg"><i style="background:#5DD6E8"></i>降雪（水当量，与降雨并列）</span>`;
      pointBar(svg, labs, rain, {ptypes:ptypes,
        label:"降雨", color:"#2E86DE", extra:[{name:"降雪", vals:snow, color:"#5DD6E8"}],
        pick:DAY_PICK,
        getRows:i=>[{t:`降雨 ${fmtD(rain[i])} mm${ptypes[i]? " "+ptypeText(ptypes[i]) : ""}`, c:"#2E86DE"},
                    {t:`降雪 ${fmtD(snow[i])} mm`, c:"#5DD6E8"}]});
    } else {
      let series=def.keys.map((kk,i)=>({name:def.labels[i],color:def.colors[i],data:pt.series[kk]}));
      // 气温图并入体感：虚线且不逐点标值（4 条线同时标值会互相遮挡；点选日期时数值框仍给全值）
      if(k==="temp" && Array.isArray(pt.series.appMax) && Array.isArray(pt.series.appMin)){
        series=series.concat([
          {name:"最高体感",color:"#D84315",data:pt.series.appMax,nolabel:true,dash:"6 4"},
          {name:"最低体感",color:"#7E57C2",data:pt.series.appMin,nolabel:true,dash:"6 4"}]);
      }
      leg.innerHTML=eic(def.icon,"plain",true)
        + series.map(s=>`<span class="lg"><i style="background:${s.color}"></i>${s.name}</span>`).join("")
        + (k==="temp"? `<span class="lg" style="color:#7a8086">虚线＝体感，舒适度预警由体感承担</span>` : "")
        + (k==="vis"? `<span class="lg" style="color:#7a8086">越低越影响行车与吊装；低于 1000m 即进入预警</span>` : "");
      // 能见度缺测（null）在 pointLine 里自动断开折线、不画点不标值
      pointLine(svg, labs, series, {pick:DAY_PICK,
        getRows:i=>series.map(s=>{
          const v=s.data[i];
          return {t:`${s.name} ${(v===null||v===undefined)? "—（该日无数据）" : fmtD(v)+" "+def.unit}`, c:s.color};
        })});
    }
  });
  paintDaySel();
}
// 未来两周页已改为「固定四图」，不再有要素勾选行（原先的 #elemRowD 初始化代码已随之删除）
renderExplorer();

// ============ 选中作业点的「未来 48 小时」逐小时要素合并图（降水柱 + 均风/阵风/气温折线；配色对齐石油工程；可点击图表选时） ============
const H_EXPLORER = document.getElementById("hourlyCharts");
let HOURLY_SVG = null, HOURLY_MARKER = null, HOURLY_N = 0;
let HOURLY_CTX = null;      // 48h 图绘制上下文（轴/序列/数值框 group），供读数更新复用
// 工程 48 小时图几何（2026-10-17 对齐 render_points_html.chart_js）：760×268，
// 绘图区 left 50 / right 706 / top 44 / bot 235
// 图例已从图内移到图下方（HTML），故 HH 由 340 收到 268，去掉底部空档
const HW=760, HH=268, HPL=50, HPR=706, HPT=44, HPB=235;
function hxOf(i){ return HPL+(i/Math.max(HOURLY_N-1,1))*(HPR-HPL); }
function renderHourlyExplorer(){
  H_EXPLORER.innerHTML="";
  if(SEL<0){ H_EXPLORER.innerHTML='<div class="empty-tip">点击上方地图选择作业点，下方显示该点未来 48 小时要素合并图。</div>';
    HOURLY_N=0; HOURLY_SVG=null; HOURLY_MARKER=null; HOURLY_CTX=null; return; }
  const pt=DATA.points[SEL];
  if(!pt.hx){
    H_EXPLORER.innerHTML='<div class="empty-tip">该工区作业点较多，逐小时明细未嵌入；请见「未来 两周」页的逐日要素图表。</div>';
    HOURLY_N=0; HOURLY_SVG=null; HOURLY_MARKER=null; HOURLY_CTX=null; return;
  }
  // 说明行：**只保留降水类型图例**（2026-10-17 用户要求删掉「仅展示未来 48 小时…」整段文字）
  const _hn=document.createElement("div"); _hn.className="ec-note";
  _hn.innerHTML="柱颜色 "+ptLegendHtml("rain");
  H_EXPLORER.appendChild(_hn);
  const box=document.createElement("div"); box.className="ec"; H_EXPLORER.appendChild(box);
  const n=Math.min(pt.hx.temp.length, NEAR_H); HOURLY_N=n;
  const precip=pt.hx.precip.slice(0,n), wind=pt.hx.wind.slice(0,n),
        gust=pt.hx.gust.slice(0,n), temp=pt.hx.temp.slice(0,n);
  const apparent=(pt.hx.apparent||[]).slice(0,n);
  const ptypes=(pt.hx.pt||[]).slice(0,n);
  // —— 三轴范围（工程 chart_js 口径）——
  const tMin=Math.min(...temp), tMax=Math.max(...temp);
  const tLo=Math.min(tMin,0)-2, tHi=tMax+2;
  const wHi=Math.max(...wind.concat(gust).concat([1]))*1.15;
  const pMax=Math.max(...precip.concat([0.1]));
  const yT=v=>HPB-(v-tLo)/(tHi-tLo)*(HPB-HPT);
  const yW=v=>HPB-(v/wHi)*(HPB-HPT);
  const yP=v=>HPB-(v/pMax)*(HPB-HPT)*0.96;
  const svg=document.createElementNS(NS,"svg"); svg.setAttribute("class","chart");
  svg.setAttribute("viewBox",`0 0 ${HW} ${HH}`); svg.setAttribute("preserveAspectRatio","xMinYMin meet");
  box.appendChild(svg);
  // 图例（2026-10-17）：**移出图表**、放到图下方并放大字号，不再占绘图区、也不遮挡图形
  const hleg=document.createElement("div"); hleg.className="hleg";
  const lnItem=(col,txt,dash)=>`<span class="hl"><i class="ln${dash?" dash":""}" style="color:${col};background:${dash?"none":col}"></i>${txt}</span>`;
  hleg.innerHTML = lnItem("#E0822C","气温 °C") + lnItem("#0FA87A","均风 m/s")
    + lnItem("#D84315","阵风 m/s",true) + lnItem("#8E44AD","体感 °C",true);
  box.appendChild(hleg);
  // 网格 + 左（气温）/右（风）双轴刻度
  for(let g=0;g<=4;g++){
    const tv=tLo+(tHi-tLo)*g/4, yv=yT(tv);
    svg.appendChild(el("line",{x1:HPL,y1:yv,x2:HPR,y2:yv,stroke:"#eee"}));
    const t1=el("text",{x:HPL-5,y:yv+3,["text-anchor"]:"end","font-size":12,fill:"#c06"});
    t1.textContent=tv.toFixed(0); svg.appendChild(t1);
    const t2=el("text",{x:HPR+5,y:yv+3,["text-anchor"]:"start","font-size":12,fill:"#8a5cbf"});
    t2.textContent=(wHi*g/4).toFixed(0); svg.appendChild(t2);
  }
  // 轴域标签已去掉（2026-10-17）：图例移到图下方后已标明「气温 ℃ / 均风 m/s」，
  // 图内再写一次会压在曲线与数值框上（图高只有 ~130px，字挤在一起）。
  // 只保留中间分隔虚线。
  const midX=(HPL+HPR)/2;
  svg.appendChild(el("line",{x1:midX,y1:HPT,x2:midX,y2:HPB,stroke:"#ddd",["stroke-width"]:1,["stroke-dasharray"]:"3 3"}));
  // 降水柱（按降水类型着色）
  const bw=(HPR-HPL)/n*0.55;
  for(let i=0;i<n;i++){
    if(!(precip[i]>0.05) && !ptypes[i]) continue;
    const bh=Math.max(HPB-yP(precip[i]),3);
    svg.appendChild(el("rect",{"class":"geo",x:(hxOf(i)-bw/2).toFixed(1),y:(HPB-bh).toFixed(1),
      width:bw.toFixed(1),height:bh.toFixed(1),rx:1,fill:(PT_FILL[ptypes[i]]||PT_FILL_FB)}));
  }
  // 小时级降水阈值线（大雨 3 / 暴雨 6 / 大暴雨 15 mm/h）
  [{v:RAIN_H.heavy,c:"#E0822C",t:"大雨 3"},{v:RAIN_H.storm,c:"#C0392B",t:"暴雨 6"},
   {v:RAIN_H.torrent,c:"#7B1F14",t:"大暴雨 15"}].forEach(th=>{
    if(th.v>pMax) return;
    const y=yP(th.v);
    svg.appendChild(el("line",{x1:HPL,y1:y,x2:HPR,y2:y,stroke:th.c,["stroke-width"]:1.1,["stroke-dasharray"]:"5 4",opacity:.7}));
    const tx=el("text",{x:HPR-5,y:y-4,["text-anchor"]:"end","font-size":10.5,fill:th.c});
    tx.textContent=th.t+" mm/h"; svg.appendChild(tx);
  });
  // 气温实线 + 每 6 小时圆点
  let tP=""; for(let i=0;i<n;i++) tP+=hxOf(i).toFixed(1)+","+yT(temp[i]).toFixed(1)+" ";
  svg.appendChild(el("polyline",{points:tP.trim(),fill:"none",stroke:"#E0822C",["stroke-width"]:2.8,["stroke-linejoin"]:"round"}));
  for(let i=0;i<n;i+=6) svg.appendChild(el("circle",{cx:hxOf(i).toFixed(1),cy:yT(temp[i]).toFixed(1),
    r:2.2,fill:"#E0822C",stroke:"#fff",["stroke-width"]:1}));
  // 体感虚线（共用气温轴）
  let aP=""; for(let i=0;i<n;i++) aP+=hxOf(i).toFixed(1)+","+yT(apparent[i]).toFixed(1)+" ";
  svg.appendChild(el("polyline",{points:aP.trim(),fill:"none",stroke:"#8E44AD",["stroke-width"]:1.8,
    ["stroke-dasharray"]:"6 4",["stroke-linejoin"]:"round"}));
  // 风力带（均风~阵风 半透明填充）
  let band=""; for(let i=0;i<n;i++) band+=hxOf(i).toFixed(1)+","+yW(wind[i]).toFixed(1)+" ";
  for(let i=n-1;i>=0;i--) band+=hxOf(i).toFixed(1)+","+yW(gust[i]).toFixed(1)+" ";
  svg.appendChild(el("polygon",{points:band,fill:"rgba(15,168,122,.10)"}));
  // 均风实线（绿）/ 阵风虚线（红）
  let wP=""; for(let i=0;i<n;i++) wP+=hxOf(i).toFixed(1)+","+yW(wind[i]).toFixed(1)+" ";
  svg.appendChild(el("polyline",{points:wP.trim(),fill:"none",stroke:"#0FA87A",["stroke-width"]:2.4,["stroke-linejoin"]:"round"}));
  let gP=""; for(let i=0;i<n;i++) gP+=hxOf(i).toFixed(1)+","+yW(gust[i]).toFixed(1)+" ";
  svg.appendChild(el("polyline",{points:gP.trim(),fill:"none",stroke:"#D84315",["stroke-width"]:2,
    ["stroke-dasharray"]:"7 3",["stroke-linejoin"]:"round"}));
  // 日期刻度（每 24 小时）
  for(let i=0;i<n;i+=24){
    const t=((DATA.hourly&&DATA.hourly.time)||[])[i]||""; if(!t) continue;
    const tx=el("text",{x:hxOf(i).toFixed(1),y:HPB+14,["text-anchor"]:"middle","font-size":12,fill:"#888"});
    tx.textContent=t.slice(5,10); svg.appendChild(tx);
  }
  // 光标 + 三个圆点 + 图内数值框（13.5px，与工程一致）
  const cur=el("line",{x1:0,y1:HPT,x2:0,y2:HPB,stroke:"#1f2933",["stroke-width"]:1.2,["stroke-dasharray"]:"4 3"});
  svg.appendChild(cur);
  const cmT=el("circle",{r:4.5,fill:"#E0822C",stroke:"#fff",["stroke-width"]:1.5});
  const cmW=el("circle",{r:4.5,fill:"#0FA87A",stroke:"#fff",["stroke-width"]:1.5});
  const cmG=el("circle",{r:4.5,fill:"#D84315",stroke:"#fff",["stroke-width"]:1.5});
  svg.appendChild(cmT); svg.appendChild(cmW); svg.appendChild(cmG);
  const rbox=el("g",{"class":"hread"}); svg.appendChild(rbox);
  HOURLY_SVG=svg; HOURLY_MARKER=cur;
  HOURLY_CTX={cur,cmT,cmW,cmG,rbox,n,precip,temp,apparent,gust,wind,ptypes,yT,yW};
  // 自由滑动选时：按下即选、按住左右拖动连续跟随
  bindDragPick(svg, (x,w)=>(x/w*HW-HPL)/(HPR-HPL)*(HOURLY_N-1), selectHour, {n:HOURLY_N});
  // 读数条（工程 .hval 样式）——2026-10-17 移到图表**上方**：先建节点再插到 svg 前面
  let hval=document.getElementById("hval");
  if(!hval){ hval=document.createElement("div"); hval.id="hval"; hval.className="hval"; }
  if(hval.parentNode!==box || hval.nextSibling!==svg) box.insertBefore(hval, svg);
  updateHourlyMarker();
  updateHourlyReadout();
}
// 在 48 小时图上直接标出「当前选中小时」的具体数值（工程 paintRead + #hval 同款）
function updateHourlyReadout(){
  const C=HOURLY_CTX; if(!C || !C.n) return;
  const h=Math.max(0,Math.min(C.n-1,CUR_HOUR));
  const ptS=ptypeText(C.ptypes[h]||0);
  const cw=t=>{ let s=0; for(let i=0;i<t.length;i++) s+=(t.charCodeAt(i)>255?13.6:7.5); return s; };
  const rows=[["降水 ",C.precip[h].toFixed(1)+" mm/h"+(ptS?" "+ptS:""),"#0D47A1"],
              ["气温 ",C.temp[h].toFixed(1)+" ℃","#8A4B00"],
              ["体感 ",C.apparent[h].toFixed(1)+" ℃","#8E44AD"],
              ["阵风 ",C.gust[h].toFixed(1)+" m/s","#8A2A0E"],
              ["均风 ",C.wind[h].toFixed(1)+" m/s","#0F5B4C"]];
  // —— 图内数值框 ——
  const g=C.rbox; while(g.firstChild) g.removeChild(g.firstChild);
  let bw=0; rows.forEach(r=>{ bw=Math.max(bw, cw(r[0])+cw(r[1])); }); bw+=24;
  const lh=18.5, pady=7, bh=rows.length*lh+pady*2;
  const sx=hxOf(h);
  let bx=sx+12; if(bx+bw>HPR) bx=sx-12-bw; if(bx<HPL) bx=HPL;
  const by=HPT+26;
  g.appendChild(el("rect",{x:bx,y:by,width:bw,height:bh,rx:7,fill:"rgba(255,255,255,.96)",
    stroke:"#C0392B","stroke-width":1.2}));
  const HT={"#8A4B00":"#FBEAD3","#0D47A1":"#D8E9FA","#0F5B4C":"#D9EFE7","#8A2A0E":"#FBE0D6"};
  rows.forEach((r,i)=>{
    const ty=by+pady+14+i*lh;
    g.appendChild(el("rect",{x:bx+6,y:ty-13,width:cw(r[0])+cw(r[1])+10,height:17.5,rx:5,
      fill:HT[r[2]]||"#EEF2F5"}));
    const lb=el("text",{x:bx+11,y:ty,"font-size":13.5,fill:"#3A4146"});
    lb.textContent=r[0]; g.appendChild(lb);
    const vv=el("text",{x:bx+11+cw(r[0]),y:ty,"font-size":13.5,fill:r[2],["font-weight"]:"900"});
    vv.textContent=r[1]; g.appendChild(vv);
  });
  // —— 底部读数条（.hval）——
  const hval=document.getElementById("hval");
  if(hval){
    const t=(DATA.hourly.time||[])[h]||"";
    const pn=(SEL>=0 && DATA.points[SEL]) ? ptTag(SEL) : "";
    const lvR=v=>v>=5?"danger":(v>=2?"warn":"ok");
    const lvG=v=>v>=24.5?"danger":(v>=17.2?"warn":"ok");   // 阵风：8级(17.2)起注意、10级(24.5)起预警
    const lvW=v=>v>=17.2?"danger":(v>=10.8?"warn":"ok");   // 均风：6级(10.8)起注意、8级(17.2)起预警
    hval.innerHTML=(pn?'<span class="pn">'+pn+'</span>':'')
      + '<span class="t">'+(t.slice(5,10)+" "+t.slice(11,16))+'</span>'
      + eic("rain",lvR(C.precip[h]))+'降水 <b class="pv">'+C.precip[h].toFixed(1)+' mm/h'+(ptS?" "+ptS:"")+'</b> '
      + eic("temp")+'气温 <b class="tv">'+C.temp[h].toFixed(1)+'℃</b> '
      + eic("heat")+'体感 <b style="color:#8E44AD;background:#F3E5F5">'+C.apparent[h].toFixed(1)+'℃</b> '
      + eic("wind",lvG(C.gust[h]))+'阵风 <b class="gv">'+C.gust[h].toFixed(1)+' m/s</b> '
      + eic("wind",lvW(C.wind[h]))+'均风 <b class="wv">'+C.wind[h].toFixed(1)+' m/s</b>';
  }
}
// 点击 48 小时图表任意位置 → 选中最近小时（替代独立滑块时间轴）
function selectHour(i){
  CUR_HOUR=i;
  updateHourlyMarker();
  updateHourlyReadout();
  updateReasonPanel();
  updatePoints(CUR_HOUR,"2");
  updateSelLabel("2");
}
// 当前小时竖线（点击图表移动）
function updateHourlyMarker(){
  if(!HOURLY_MARKER || !HOURLY_N) return;
  const x=hxOf(CUR_HOUR);
  HOURLY_MARKER.setAttribute("x1",x); HOURLY_MARKER.setAttribute("x2",x);
}

function selectPoint(i){
  SEL=i; DAY_SEL=-1;
  ["2","3"].forEach(suffix=>{
    if(!window["POINT_PX"+suffix]) return;   // 该地图尚未渲染（对应 Tab 未打开过）则跳过，避免 undefined 抛异常
    const svg=document.getElementById("mapOverlay"+suffix);
    let ring=document.getElementById("selRing"+suffix);
    if(!ring){ ring=document.createElementNS(NS,"circle"); ring.setAttribute("id","selRing"+suffix); ring.setAttribute("fill","none"); ring.setAttribute("stroke","#111"); ring.setAttribute("stroke-width","3"); svg.appendChild(ring); }
    const px=window["POINT_PX"+suffix][i];
    if(!px) return;                          // 测线筛选后该点不在当前地图上（如从别处选了一个被筛掉的点）
    ring.setAttribute("cx",px.x); ring.setAttribute("cy",px.y); ring.setAttribute("r",PT_RING);
    updateSelLabel(suffix);
  });
  updateReasonPanel();
  renderExplorer();
  renderHourlyExplorer();
}
// ---- 三页签切换 ----
function showTab(id){ document.querySelectorAll('.tabpane').forEach(p=>p.classList.toggle('active',p.id===id));
  document.querySelectorAll('.tabbtn').forEach(b=>b.classList.toggle('active',b.dataset.tab===id)); }
document.querySelectorAll('.tabbtn').forEach(b=>b.addEventListener('click',()=>{
  showTab(b.dataset.tab);
  if(b.dataset.tab==='t2'){ renderMap("2"); updatePoints(CUR_HOUR,"2"); if(SEL>=0) selectPoint(SEL); }   // 未来48小时：按实际容器宽度重绘地图，并按当前小时着色
  if(b.dataset.tab==='t3'){ renderMap("3"); if(SEL>=0) selectPoint(SEL); }   // 未来两周：重绘地图（整窗风险着色），并已选点则补画选中环
}));
// 地图缩放/平移初始化（每个地图各绑一份）
["2","3"].forEach(s=>{ if(document.getElementById("mapbox"+s)){ bindMap(s); updZL(s); } });
// iOS Safari 私有的双指手势事件：捏地图时别把「整页」一起放大。
// 只在地图区域内拦，地图以外的页面照常可双指放大看文字（不影响无障碍）。
["gesturestart","gesturechange"].forEach(t=>document.addEventListener(t,(ev)=>{
  const tg=ev.target; if(tg && tg.closest && tg.closest(".mapbox")) ev.preventDefault();
},{passive:false}));
</script>
<script async src="//busuanzi.ibruce.info/busuanzi/2.3/busuanzi.pure.mini.js"></script>
<div style="margin-top:16px;padding-top:8px;border-top:1px solid rgba(128,128,128,.18);font-size:11px;color:#9aa0a6;text-align:center;opacity:.6;letter-spacing:.3px">访问统计 · 本页阅读 <span id="busuanzi_container_page_pv"><span id="busuanzi_value_page_pv"></span> 次</span> · 全站访客 <span id="busuanzi_container_site_uv"><span id="busuanzi_value_site_uv"></span> 人</span></div>
</body>
</html>
"""

html = (TEMPLATE.replace("__DATA__", DATA_JSON)
        .replace("__TITLE__", f"{args.name} · 工区两周天气看板"))

# 内嵌页头背景图（assets/hero-bg.jpg → CSS 背景）
hc = hero_css()
html = html.replace("/*__HERO_CSS__*/", hc)
print("hero bg:", ("embedded" if hc else "skipped"))

# 内嵌中文字体子集（跨平台：自动按操作系统挑选系统中文字体，macOS↔Windows↔Linux 迁移无需改路径）
def _cjk_font_candidates():
    sp = sys.platform
    if sp.startswith("win") or os.name == "nt":
        return [
            (r"C:\Windows\Fonts\msyh.ttc", 0),   # 微软雅黑
            (r"C:\Windows\Fonts\msyh.ttc", 1),
            (r"C:\Windows\Fonts\simsun.ttc", 0),  # 宋体
            (r"C:\Windows\Fonts\msjh.ttc", 0),    # 微軟正黑體
            (r"C:\Windows\Fonts\simhei.ttf", 0),  # 黑体
        ]
    if sp == "darwin":
        return [
            ("/System/Library/Fonts/Hiragino Sans GB.ttc", 0),
            ("/System/Library/Fonts/STHeiti Light.ttc", 0),
            ("/System/Library/Fonts/PingFang.ttc", 0),
            ("/Library/Fonts/Arial Unicode.ttf", 0),
        ]
    # Linux / 其它：常见开源 CJK 字体
    return [
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/arphic/uming.ttc",
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    ]

try:
    from fontTools.ttLib import TTFont
    from fontTools import subset as ftsubset
    _fnt = None
    for _fp, _fn in _cjk_font_candidates():
        if os.path.exists(_fp):
            try:
                _fnt = TTFont(_fp, fontNumber=_fn)
                print("CJK font source:", _fp, "fontNumber=", _fn)
                break
            except Exception:
                _fnt = None
    if _fnt is None:
        raise RuntimeError("no CJK system font found on this platform")
    fnt = _fnt
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
print("DONE")
