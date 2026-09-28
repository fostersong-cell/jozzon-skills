# -*- coding: utf-8 -*-
"""
物探工区(区域)2周天气看板生成器 —— 富媒体交互式 HTML 版

能力:
  - 输入一个 KML 边框(工区多边形 / 测线 LineString)，自动识别类型
  - 按 --grid km 网格采样(默认 6km，越细点越多，贴合 EC 分辨率；超过 --maxpts 自动加粗)，并加入质心/测线中点
  - 用 Open-Meteo 多坐标接口分批拉取所有采样点未来2周（14天）逐小时预报（可选 --model ecmwf_ifs04 高分辨率）
  - 输出以"区域"为单位: 最坏情况包络(逐时最低温/最高降水/最大风)、连续降雨窗口；并为每个采样点计算逐日序列供交互查询
  - 富媒体交互式 HTML：canvas 地形图(Open-Meteo 高程接口 + 高程色带 + 山体阴影 + 等高线，计曲线加粗) + 参考网格 + 采样点 + 风险区(径向渐变红/橙光斑)
  - 顶部仅一个"重点关注"卡片，按极端天气严重程度(0绿/1黄/2橙/3红)变色；其下依次是关键指标、地图与联动图表、物探作业影响与建议
  - 点击地图任意采样点，地图下方同一卡片内立即展开该点未来2周逐要素曲线/柱状图(气温/降水/阵风·均风可勾选叠加)；降水图阈值动态取 max(10mm, niceCeil(数据最大值))
  - 仅输出可交互 HTML（无 PDF 依赖），中文字体子集内嵌，手机/浏览器直接打开

用法:
  python build_dashboard.py --name "大关项目" --kml "炮点边框.kml" --grid 4 --outdir "."

"""
import argparse, json, os, sys, time, base64, io, urllib.request, urllib.parse, math
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET

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
HERO_BLEED = "16px"          # 背景左右/上下的外扩量（与 body padding 14px 对齐，做满屏出血）
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
# 坐标为 GCJ-02，与底图/采集点所用 WGS84 偏差 <1km，在地图尺度（1px≈0.5~2km）不可见。
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
ap.add_argument("--grid", type=float, default=20.0, help="采样点距离间隔 km，默认 20（面/线统一按此距离严格等距采样；线点数超过15自动均匀取15）")
ap.add_argument("--days", type=int, default=14, help="预报天数，默认 14（2周，从下一整时起）")
ap.add_argument("--from-today", action="store_true", help="从当前整点开始（默认从下一整点开始，跳过当前小时剩余时间）")
ap.add_argument("--outfile", default="", help="自定义输出文件名（含 .html，可用拼音/字母/数字），默认 {name}工区/测线.html")
ap.add_argument("--apikey", default="6aiF2mXsB3K7YcjT")
ap.add_argument("--model", default="", help="Open-Meteo 模型，如 ecmwf_ifs04（ECMWF 4km 高分辨率）；留空用默认融合模型")
ap.add_argument("--maxpts", type=int, default=150, help="采样点数量上限（仅线模式二次兜底），面/复合工区按 --grid 距离全区域采样、不限个数")
ap.add_argument("--lines", default="", help="附加测线 KML 路径（逗号分隔），与 --kml 边框共同渲染并参与「总区域」采样（复合工区模式，如大关：边框+北/南/中线）")
ap.add_argument("--points", default="", help="附加数据采集点 KML（含多个 <Placemark><Point>，如炮点/检波点/预警点），逗号分隔；给出时**按采集点直接取数（不面/线采样）**，与 --kml 边框/测线共同渲染（采集点模式）")
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

    # 附加采集点(--points)：KML 里多个 <Placemark><Point>（如炮点/检波点/预警点），
    # 给出时【按采集点直接取数，不面/线采样】，与 --kml 边框/测线共同渲染（采集点模式）
    pts = []; pt_names = []
    if args.points and not args.data:
        for pk in args.points.split(","):
            pk = pk.strip()
            if not pk:
                continue
            try:
                proot = ET.parse(pk).getroot()
            except Exception as e:
                print(f"⚠️ 采集点 KML 解析失败 {pk}: {repr(e)}")
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
            print(f"附加采集点(Point): {len(pts)} 个（按采集点直接取数）")
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
        """dx_km 向东为正, dy_km 向北为正 → 8 方位中文(用于面/多边形采样点相对工区中心的方向)。"""
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
        # 采集点模式：有边框用边框范围，无边框用采集点范围
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
            print(f"测线总长 {total_km:.0f}km，按 {args.grid:.0f}km 间隔约 {_est_n} 点 > {LINE_MAX_PTS}，改为全线均匀取 {LINE_MAX_PTS} 个采样点（间隔 {G:.1f}km）")
    def _estimate_pts(grid):
        if is_line:
            return max(2, int(total_km / grid) + 2)
        return max(1, int((lonkm / grid) * (latkm / grid)) + 1)
    _est0 = _estimate_pts(G)
    if is_line and _est0 > args.maxpts:  # 仅线启用 maxpts 二次兜底；面不启用（保持 20km 全区域采样）
        G = G * math.sqrt(_est0 / args.maxpts)
        print(f"采样点估算 {_est0} > 上限 {args.maxpts}，网格自动加粗至 {G:.1f} km")
    grid_used = round(G, 1)

    # 文件名：线状用「测线」、多边形用「工区」；--outfile 可指定拼音/字母数字文件名
    suffix = "测线" if is_line else "工区"
    html_path = os.path.join(base, args.outfile if args.outfile else f"{args.name}{suffix}.html")

    # ---------- 1.5 地形底图：Esri World Topo Map 在线瓦片（HTML 端加载，不再抓 Open-Meteo 高程，省请求避免 429） ----------
    elevGrid = None

    # 采样点
    samples = []
    cum = []            # 仅线模式：各采样点沿主线累计 km（兼容旧逻辑）
    line_idx_of = []    # 多线：该点所属测线索引
    line_name_of = []   # 多线：该点所属测线名
    cumkm_of = []       # 多线：该点距所属测线起点累计 km
    linekm_of = []      # 多线：该点所属测线总长 km
    north_of = []       # 多线：该点所属测线「北端是否在起点」
    center_idxs = set() # 中点/中心索引集合
    if is_points:
        # 采集点模式：直接用 KML 里的 Point 坐标，不做面/线采样
        samples = [(round(x, 4), round(y, 4)) for x, y in pts]
        cum = [0.0] * len(samples)
        # 采集点是真实数据采集位置（炮点/检波点/预警点），无「中心」概念，不标记中心
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
        # 面采样：采样点【严格落在边框多边形内部】。复合工区的附加测线仅用于「展示」，
        # 不参与采样（此前测线向东溢出边框，导致采样点跑到工区外，已移除）。
        # 做法：①在边框包围盒内按细步长(~G/10)铺细网格，筛出所有 inside() 在区内的候选点，
        #      用半格偏移避免候选点恰落在边界顶点上；②「最远点采样」从候选中挑出间距≈G
        #      (默认20km)的代表点：先取离质心最近的点，再迭代加入离已选集合最远的候选，
        #      直到该最远距离 < 0.75*G。对规则矩形≈网格、对斜向/不规则工区也能均匀覆盖，
        #      且保证每个采样点都在工区内、间距均匀≈G。
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
        # 中心 = 距多边形质心最近的采样点
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
    print(f"采样点(含中心): {len(samples)} (目标间距 {args.grid:.0f}km)")

    # ---------- 2. 多坐标批量拉取 ----------
    # precipitation=总降水(mm，含液态与降雪水当量) / rain=雨(mm) / showers=阵雨(mm)
    # / snowfall=降雪(cm，注意单位与降水量不同) → liquid=rain+showers 为「降雨」规范口径
    HOURLY = ("temperature_2m,precipitation,rain,showers,snowfall,"
              "wind_speed_10m,wind_gusts_10m")
    BASE = "https://api.open-meteo.com/v1/forecast"
    # Open-Meteo 免费接口无需 apikey；仅当用户显式提供真实 key 时才附加，
    # 否则带默认占位 key 会被当作 licensed 请求而造成 429。
    DEFAULT_KEY = "6aiF2mXsB3K7YcjT"
    APIKEY_ARG = args.apikey if args.apikey and args.apikey != DEFAULT_KEY else ""
    key_suffix = f"&apikey={APIKEY_ARG}" if APIKEY_ARG else ""
    locs = []
    CH = 12  # 每批坐标数，批间冷却，缓解 429
    time.sleep(12)  # 高程请求后冷却，避免触发预报接口限流
    if args.model:
        print(f"使用模型: {args.model}（失败自动回退默认融合模型）")
    for s0 in range(0, len(samples), CH):
        chunk = samples[s0:s0+CH]
        lats_s = ",".join(str(s[1]) for s in chunk)
        lons_s = ",".join(str(s[0]) for s in chunk)
        date_params = f"&start_date={START_DATE}&end_date={END_DATE}&start_hour={START_HOUR}&end_hour={END_HOUR}"
        base_params = (f"latitude={lats_s}&longitude={lons_s}"
                  f"&hourly={HOURLY}{date_params}"
                  f"&wind_speed_unit=ms"
                  f"&timezone=Asia%2FShanghai{key_suffix}")
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
    # 「降雨」规范口径 = 雨 + 阵雨（liquid）；降雪单独看 snowfall（单位 cm，仅以 >0 判定有无）
    per["liquid"] = [[round(r + s, 2) for r, s in
                      zip(per["rain"][p], per["showers"][p])] for p in range(len(locs))]

    # 降水类型码：0=无 / 1=降雨 / 2=降雪 / 3=雨夹雪（图表柱内图标用）
    def ptype_of(liquid, snow, precip=0.0):
        has_l, has_s = liquid > 0.05, snow > 0.01
        if has_l and has_s: return 3
        if has_s: return 2
        if has_l: return 1
        # 兜底：总量有值但雨/阵雨/雪分量皆 0（冰粒等）→ 仍按「降雨」呈现，避免柱子无类型
        return 1 if precip > 0.05 else 0

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
            lD[d] = lD.get(d, 0.0) + max(lv, 0.0)          # 每日降雨合计（rain+showers）
            sD[d] = sD.get(d, 0.0) + max(sv, 0.0)          # 每日降雪合计（cm）
            (wD.setdefault(d, [])).append(wv)
            (gD.setdefault(d, [])).append(gv)
        return {
            "tempMin": [round(min(tMinD[d]), 1) for d in dailyDates],
            "tempMax": [round(max(tMaxD[d]), 1) for d in dailyDates],
            "precip":  [round(pD.get(d, 0.0), 1) for d in dailyDates],
            # 每日降水类型（柱内图标）：以当日累计 liquid / snowfall 判定
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

    # ---- 未来 48 小时（近 2 天）聚合：t1「重点提示」以此为主口径 ----
    HOURS_48 = 48        # 「未来 48 小时」页保留的逐小时明细长度
    NEAR_DAYS = 2        # 「重点提示」聚焦的未来天数（=48 小时）
    # ---- 小时级短时降水分级（mm/h，2026-09-26 用户定）：>2 大雨 / >5 暴雨 / >10 大暴雨 ----
    # 只作用于「未来 48 小时」口径：逐小时风险判定、风险要素、48h 图阈值线、48h 影响卡片、48h 重点关注等级。
    # 未来 2 周逐日页仍按「日累计」口径（≥25 大雨 / ≥50 暴雨），两套口径不得混用（变量名也刻意区分）。
    RAIN_H = {"heavy": 2.0, "storm": 5.0, "torrent": 10.0}
    n2 = max(1, min(NEAR_DAYS, len(dailyDates)))
    region_near = region_daily[:n2]
    near_focus = [x for x in region_near if x["p"] >= 10]
    near_peak = max(region_near, key=lambda x: x["p"]) if region_near else None
    P48 = {
        "days": n2,
        "tmax": round(max((max(ps["tempMax"][:n2]) for ps in point_series), default=0), 1),
        "tmin": round(min((min(ps["tempMin"][:n2]) for ps in point_series), default=0), 1),
        "gustMax": round(max((max(ps["gustMax"][:n2]) for ps in point_series), default=0), 1),
        "windMax": round(max((max(ps["windMax"][:n2]) for ps in point_series), default=0), 1),
        "pMax": round(near_peak["p"], 1) if near_peak else 0,
        "pMaxDay": near_peak["date"] if near_peak else None,
        "focusTotal": round(sum(x["p"] for x in near_focus), 1),
        "focusStart": near_focus[0]["date"] if near_focus else None,
        "focusEnd": near_focus[-1]["date"] if near_focus else None,
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
        if gg >= 17.2: tags.append(f"阵风 {round(gg,1)} m/s（≥8级）")
        if gx >= 35:  tags.append(f"最高气温 {round(gx,1)}℃（高温）")
        if gn <= -5:  tags.append(f"最低气温 {round(gn,1)}℃（严寒）")
        if tags: far_items.append({"date": day, "text": "、".join(tags)})
    FAR = {"has": bool(far_items), "days": far_items[:2],
           "text": "；".join(f"{x['date'][5:]} {x['text']}" for x in far_items[:2])}

    # 极端天气分级（"重点关注"背景版变色依据）：0绿 1黄 2橙 3红
    # 近 48 小时「小时级短时降水」并入：≥10mm/h（大暴雨）→ 2 级、≥5mm/h（暴雨）→ 1 级（日累计 25/50 口径不变）
    def _sev_of(pp):
        _ph = pp.get("pHourMax") or 0
        if pp["pMax"] >= 80 or _ph >= 20 or pp["gustMax"] >= 20.8 or pp["tmax"] >= 38 or pp["focusTotal"] >= 150:
            return 3
        if pp["pMax"] >= 50 or _ph >= RAIN_H["torrent"] or pp["gustMax"] >= 17.2 or pp["tmax"] >= 35 or pp["tmin"] <= -5 or pp["focusTotal"] >= 80:
            return 2
        if pp["pMax"] >= 25 or _ph >= RAIN_H["storm"] or pp["windMax"] >= 10.8 or pp["tmin"] <= 0 or pp["focusTotal"] >= 30:
            return 1
        return 0
    _SEV_LABELS = {0: "整体适宜", 1: "需关注", 2: "重点关注", 3: "高度警惕"}
    SEV = _sev_of(P)
    SEV_LABEL = _SEV_LABELS[SEV]
    SEV_NEAR = _sev_of(P48)                 # 未来 48 小时分级（t1 重点提示用）
    SEV_LABEL_NEAR = _SEV_LABELS[SEV_NEAR]

    # 风险点(按各点自身判定)
    def risk_of(pp):
        # 风单位 m/s：8级≈17.2, 6级≈10.8
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
                "precip": [round(v, 1) for v in per["precipitation"][i][:HOURS_48]],
                "liq":    [round(v, 1) for v in per["liquid"][i][:HOURS_48]],      # 降雨(rain+showers)
                "snow":   [round(v, 1) for v in per["snowfall"][i][:HOURS_48]],    # 降雪(cm)
                "pt":     list(per["ptype"][i][:HOURS_48]),                        # 降水类型码
                "wind":   [round(v, 1) for v in per["wind_speed_10m"][i][:HOURS_48]],
                "gust":   [round(v, 1) for v in per["wind_gusts_10m"][i][:HOURS_48]],
            }
        _ps = point_series[i]
        _p2 = _ps["precip"][:n2]
        points_out.append({
            "idx": i, "lon": s[0], "lat": s[1],
            "isCenter": (i in center_idxs),
            "lineIdx": line_idx_of[i] if multi else 0,
            "lineName": line_name_of[i] if multi else "",
            "risk": risk_of(pp), "loc": loc,
            "tmax": round(pp["tmax"], 1), "tmin": round(pp["tmin"], 1),
            "gustMax": round(pp["gustMax"], 1), "windMax": round(pp["windMax"], 1),
            "pMax": pp["pMax"], "pMaxDay": pp["pMaxDay"],
            # 近 48 小时（近 2 天）逐点极值：供 t1「关键指标」标注极值所在采样点
            "tmax2": round(max(_ps["tempMax"][:n2]), 1) if n2 else None,
            "tmin2": round(min(_ps["tempMin"][:n2]), 1) if n2 else None,
            "gustMax2": round(max(_ps["gustMax"][:n2]), 1) if n2 else None,
            "windMax2": round(max(_ps["windMax"][:n2]), 1) if n2 else None,
            "pMax2": round(max(_p2), 1) if _p2 else 0.0,
            "series": _ps,
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
                 "model": args.model or "open-meteo 默认融合模型",
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
payload["peaksNear"]["pHourMax"] = _ph_h      # 48h 内各采样点逐小时降水最大值（mm/h）
payload["peaksNear"]["pHourAt"] = _ph_i       # 该峰值出现的小时索引（相对 48h 窗口）
payload["peaksNear"]["pHourPoint"] = _ph_pt   # 所在采样点的大致位置文案

DATA_JSON = json.dumps(payload, ensure_ascii=False)

# 实时取数后，将数据包落盘，便于以后 --data 离线复用（不重复请求接口）
# 离线模式（--data）下输入本身就是数据文件，无需再落盘，否则会按中文 args.name
# 在 --outdir 写出一份中文名 _data.json（与 data/ 拼音文件重复且污染产物目录）。
if args.save_data and not args.data:
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
  .stats{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;}
  .stat{background:#FBFAF7;border:1px solid var(--line);border-radius:10px;padding:10px 12px;}
  .stat .k{font-size:12px;color:var(--sub);}
  .stat .v{font-size:22px;font-weight:700;margin-top:2px;}
  .stat .v small{font-size:12px;font-weight:500;color:var(--sub);}
  .chart-wrap{width:100%;overflow:hidden;}
  svg.chart{width:100%;height:auto;display:block;}
  .mapbox{position:relative;width:100%;height:280px;background:#ECE7DF;border-radius:10px;overflow:hidden;
    touch-action:none;-webkit-touch-callout:none;-webkit-user-select:none;user-select:none;}  /* 地图显示高度固定约手机屏 1/3，不随内容上下拉长 */
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
  <h1 id="titleH1">工区2周天气看板</h1>
  <div class="meta" id="metaLine"></div>
</header>

<div class="tabs">
  <button class="tabbtn active" data-tab="t1">重点提示</button>
  <button class="tabbtn" data-tab="t2">未来48小时</button>
  <button class="tabbtn" data-tab="t3">未来2周</button>
</div>
</div>

<div id="t1" class="tabpane active">
  <div id="alertBox" class="alert sevbox"></div>
  <div class="card">
    <h2><span class="dot"></span><span id="tStats">关键指标（2 周最坏情况）</span></h2>
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
    <div class="risk-reason" id="riskReason" style="display:none"></div>
    <div id="hourlyCharts"></div>
  </div>
</div>

<div id="t3" class="tabpane maptab">
  <div class="card">
    <h2><span class="dot"></span><span id="tMap3">未来2周（逐日要素）</span></h2>
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
    <div class="elem-row" id="elemRowD">
      <label><input type="checkbox" value="precip" checked> 降水</label>
      <label><input type="checkbox" value="wind" checked> 阵风 / 均风</label>
      <label><input type="checkbox" value="temp" checked> 气温</label>
    </div>
    <div id="explorerInfo" class="explorer-info"></div>
    <div id="explorerCharts"></div>
  </div>
</div>

<script>
const DATA = __DATA__;
const NS = "http://www.w3.org/2000/svg";
const LBL = DATA.meta.kind === "line" ? "测线" : (DATA.meta.kind === "points" ? "采集点" : "工区");
// 采集点「短名」：去掉名称里的项目名与年份前缀（广东-广西深反射0KM → 0KM；XYH2026-SN-01-南端 → SN-01-南端），让地图标签短；
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
let SEL = -1;  // 当前选中采样点；提前声明，供时间轴初始化时调用
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
let DAY_SEL = -1;         // 「未来2周」图表点选的日期索引（-1 未选）
const _ln = (DATA.meta.multi && DATA.meta.lines) ? DATA.meta.lines.map(l=>l.name).join(" + ") : (DATA.meta.lineName || "测线");
document.getElementById("titleH1").textContent = DATA.meta.name + (DATA.meta.kind === "line"
  ? " · " + _ln + "2周天气看板"
  : (DATA.meta.kind === "points" ? " · 采集点2周天气看板" : " · 工区2周天气看板"));
document.getElementById("tMap2").textContent = LBL + "未来 48 小时（逐小时风险）";
document.getElementById("tMap3").textContent = LBL + "未来 2 周（逐日要素）";
document.getElementById("tImpact").textContent = "物探作业天气影响与建议";
document.getElementById("tStats").textContent = "关键指标（" + LBL + " 未来 48 小时）";
const _cl=document.getElementById("centerLegend"); if(_cl) _cl.textContent = DATA.meta.kind === "points" ? "◈＝采集点中心" : (DATA.isLine ? "◈＝测线中点" : "◈＝工区中心");
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
  // 回退：测线+采集点模式 isLine=False 且 polygon 为空（测线项目无 Polygon），用 DATA.line 作为骨架
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
  let W=Math.round((mb?mb.clientWidth:0)||680), pad=30, Hh=280;   // W=容器实际宽度（避免位图变形），Hh 固定约手机屏 1/3
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
    // 采集点名称：深色字 + 半透明白底衬（不再用白字/白描边，避免与底图混在一起），字号调小
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
  // 地图空白处点击 → 命中最近采样点（拖拽平移后不触发）
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
  const W=(mb?mb.clientWidth:680)||680, Hh=280;
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
// 采集点图标几何（全局唯一来源）：renderMap 绘制、updatePoints 逐小时改色、redrawSel 选中环
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
  //      → 手机上点采集点永远没反应（电脑有鼠标，click 正常，所以只在手机上暴露）。
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
  const cw=t=>t.split("").reduce((a,ch)=>a+(ch.charCodeAt(0)>255?11.6:6.4),0);
  const bw=Math.max(96, Math.min(Math.max(...rows.map(r=>cw(r.t)))+18, W-2*pl));
  const lh=15, pady=6, bh=rows.length*lh+pady*2;
  let bx=x+10; if(bx+bw>W-pr) bx=x-10-bw; if(bx<pl) bx=pl;
  const by=pt+4;
  svg.appendChild(el("rect",{x:bx,y:by,width:bw,height:bh,rx:6,fill:"rgba(255,255,255,.96)",stroke:"#C0392B",["stroke-width"]:1.2}));
  rows.forEach((r,i)=>{ const ty=by+pady+11+i*lh;
    svg.appendChild(el("rect",{x:bx+6,y:ty-11,width:cw(r.t)+10,height:14.5,rx:5,fill:tintOf(r.c)}));
    const tx=el("text",{x:bx+11,y:ty,"font-size":11.5,fill:r.c,["font-weight"]:"900"});
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

// ============ 时间轴：逐小时风险着色 + 采样点风险原因 ============
const COLMAP = {ok:"#1F7A6B", warn:"#E0822C", danger:"#C0392B"};
const RR = document.getElementById("riskReason");
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

// 小时级短时降水分级（mm/h）：>2 大雨 / >5 暴雨 / >10 大暴雨 —— 48 小时口径统一使用（Python 侧同名 RAIN_H）
const RAIN_H={heavy:2, storm:5, torrent:10};
// 单要素风险等级（供读数行的小图标着色；阈值与 riskClassAtHour 完全一致，勿各写一套）
const lvRain = v => v>=RAIN_H.storm ? "danger" : (v>=RAIN_H.heavy ? "warn" : "ok");
const lvGust = v => v>=17.2 ? "danger" : (v>=10.8 ? "warn" : "ok");
const lvWind = lvGust;
const lvTemp = v => v>=35 ? "danger" : (v<=0 ? "warn" : "ok");
// 某采样点在第 h 小时的风险等级（ok/warn/danger）
// 降水走「小时级短时降水」口径：≥5mm/h（暴雨，含 ≥10 大暴雨）即高风险，≥2mm/h（大雨）即注意；
// 风/气温沿用原阈值（阵风 17.2 / 10.8 m/s，高温 35℃、低温 0℃）。
function riskClassAtHour(pt, h){
  if(!pt.hx) return pt.risk;
  const g=pt.hx.gust[h]||0, p=pt.hx.precip[h]||0, t=pt.hx.temp[h]||0;
  if(g>=17.2 || t>=35 || p>=RAIN_H.storm) return "danger";   // 暴雨及以上
  if(g>=10.8 || t<=0 || p>=RAIN_H.heavy) return "warn";      // 大雨
  return "ok";
}
// 按当前小时重绘所有采样点颜色
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
  if(g>=10.8) f.push({name:"阵风", val:g.toFixed(1), unit:"m/s", level:g>=17.2?3:2,
    advice:g>=17.2?"≥8级，钻机塔架/天线/帐篷须停工":"6~7级，设备与帐篷需加固"});
  if(w>=10.8) f.push({name:"持续风", val:w.toFixed(1), unit:"m/s", level:2, advice:"≥6级，注意高空作业与帐篷"});
  // 降水：小时级短时降水分级 —— >2 大雨 / >5 暴雨 / >10 大暴雨（暴雨及以上算高风险）
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
  return f;
}
function updateReasonPanel(){
  if(SEL<0 || !RR){ RR.style.display="none"; return; }
  const pt=DATA.points[SEL], h=CUR_HOUR;
  const tm=(DATA.hourly.time[h]||"").slice(5,16).replace("T"," ");
  let html=`<div class="rr-h"><b>${ptTag(pt.idx)}</b></div>`;
  if(pt.hx){
    html+=`<div class="rr-cur">🕒 <b class="clk">${tm}</b></div>`;
    // 每个要素前置小图标：图标底色＝该要素在当前小时的风险等级（选时后随图表实时变化）
    const _p=pt.hx.precip[h], _t=pt.hx.temp[h], _g=pt.hx.gust[h], _w=pt.hx.wind[h];
    html+=`<div class="rr-valrow">${eic("rain",lvRain(_p),true)}降水 <b class="pv">${_p.toFixed(1)} mm</b> ｜ `
        + `${eic("temp",lvTemp(_t),true)}气温 <b class="tv">${_t.toFixed(1)} ℃</b> ｜ `
        + `${eic("wind",lvGust(_g),true)}阵风 <b class="gv">${_g.toFixed(1)} m/s</b> ｜ `
        + `${eic("wind",lvWind(_w),true)}均风 <b class="wv">${_w.toFixed(1)} m/s</b></div>`;
  } else {
    html+=`<div class="rr-cur">🕒 <b class="clk">${tm}</b></div>`;
  }
  RR.innerHTML=html; RR.style.display="block";
}
// 时间轴已移除：改由点击 48 小时图表任意位置选时（见 selectHour）


document.getElementById("metaLine").textContent = DATA.meta.kind === "points"
  ? `采集点 ${DATA.meta.npts} 个 · ${DATA.meta.start} ~ ${DATA.meta.end} · 数据 ${DATA.meta.gen} 生成`
  : (DATA.meta.kind === "line"
    ? (DATA.meta.multi && DATA.meta.lines
      ? `测线「${DATA.meta.lines.map(l=>l.name+"("+l.km+"km)").join(" + ")}」共 ${DATA.meta.lineKm}km · 网格 ${DATA.meta.gridKm}km · ${DATA.meta.npts} 个采样点 · ${DATA.meta.start} ~ ${DATA.meta.end} · 数据 ${DATA.meta.gen} 生成`
      : `测线「${DATA.meta.lineName}」长度 约 ${DATA.meta.lineKm}km · 网格 ${DATA.meta.gridKm}km · ${DATA.meta.npts} 个采样点 · ${DATA.meta.start} ~ ${DATA.meta.end} · 数据 ${DATA.meta.gen} 生成`)
    : `工区范围 约 ${DATA.meta.lonkm}×${DATA.meta.latkm}km · 网格 ${DATA.meta.gridKm}km · ${DATA.meta.npts} 个采样点 · ${DATA.meta.start} ~ ${DATA.meta.end} · 数据 ${DATA.meta.gen} 生成`);

// ============ 重点关注（未来 48 小时为主口径；远期仅"重大极端天气"才追加提示） ============
(function(){
  const SEV=(DATA.meta.sevNear!==undefined?DATA.meta.sevNear:DATA.meta.sev);
  const LBL2=DATA.meta.sevLabelNear||DATA.meta.sevLabel;
  document.body.classList.add("sev"+SEV);
  const nRisk = DATA.points.filter(p=>p.risk!=="ok").length;
  const th=[];
  if(PN.gustMax>=17.2) th.push(`最大阵风 ${PN.gustMax} m/s（≥8级）`);
  if(PN.tmax>=35) th.push(`最高气温 ${PN.tmax}°C（高温）`);
  if(PN.tmin<=0) th.push(`最低气温 ${PN.tmin}°C（结冰/霜冻）`);
  if(PN.pMax>=50) th.push(`${PN.pMaxDay.slice(5)} 单日降水 ${PN.pMax}mm（暴雨）`);
  else if(PN.pMax>=25) th.push(`${PN.pMaxDay.slice(5)} 单日降水 ${PN.pMax}mm（大雨）`);
  if(PN.focusStart) th.push(`${PN.focusStart.slice(5)}~${PN.focusEnd.slice(5)} 连续降雨累计 ${PN.focusTotal}mm`);
  let desc = th.length
    ? ("近 48 小时主要关注：" + th.join("；") + `。图中共 ${nRisk} 个采样点存在降雨/大风风险，建议据此调整野外作业安排。`)
    : "近 48 小时未触发极端天气预警阈值，整体有利于野外作业。";
  if(FARALERT.has) desc += ` 远期（第 3~14 天）另有 ${FARALERT.text}，已超出可靠预报窗口，临近时再提示。`;
  const box=document.getElementById("alertBox");
  box.className="alert sevbox";
  box.innerHTML=`<div class="t"><span class="sev-dot"></span>未来 48 小时 · ${LBL2}</div><div class="d">${desc}</div>`;
})();

// ---- 关键指标（未来 48 小时；副标题标注极值所在采样点的大致位置） ----
const argmax = key => DATA.points.reduce((b,p)=> (b===null || (p[key]??-Infinity) > (b[key]??-Infinity)) ? p : b, null);
const argmin = key => DATA.points.reduce((b,p)=> (b===null || (p[key]??Infinity) < (b[key]??Infinity)) ? p : b, null);
const locStr = p => p ? ((p.isCenter ? ((DATA.meta.kind==="points" ? "采集点中心" : (DATA.isLine ? "测线中点" : "工区中心"))) : ptTag(p.idx)) + " 采样点") : "";
const tmaxP = argmax("tmax2"), tminP = argmin("tmin2"), gustP = argmax("gustMax2"), pmaxP = argmax("pMax2");
// 每格＝[要素图标, 风险等级(决定图标底色), 指标名, 数值, 说明]；图标底色一眼看出风险程度
const PH0 = PN.pHourMax||0;   // 48h 最大小时降水（mm/h），关键指标与影响卡共用
// 日累计 与 小时级短时降水 取重（与下方影响卡同一套阈值，避免两处口径不一致）
const statRain = (PN.pMax>=50 || PH0>=RAIN_H.torrent) ? "danger"
               : ((PN.pMax>=25 || PH0>=RAIN_H.storm) ? "warn" : "ok");
const stats=[
  ["temp", PN.tmax>=35?"danger":"ok", LBL+"最高温", PN.tmax+"°C", (PN.tmax>=35?"高温预警":"无高温预警")+" · "+locStr(tmaxP)],
  ["temp", PN.tmin<=0?"warn":"ok", LBL+"最低温", PN.tmin+"°C", (PN.tmin<=0?"注意霜冻/结冰":"无霜冻/结冰")+" · "+locStr(tminP)],
  ["wind", PN.gustMax>=17.2?"danger":(PN.gustMax>=10.8?"warn":"ok"), "最大阵风", PN.gustMax+"<small> m/s</small>",
    (PN.gustMax>=17.2?"≥8级，需停工":(PN.gustMax>=10.8?"6~7级，加固":"约5级，不影响"))+" · "+locStr(gustP)],
  ["rain", statRain, "最大日降水", (PN.pMax||0)+"<small> mm</small>",
    (PN.pMaxDay?(PN.pMax>=50?"暴雨 "+PN.pMaxDay.slice(5):(PN.pMax>=25?"大雨 "+PN.pMaxDay.slice(5):"中雨 "+PN.pMaxDay.slice(5))):"—")+" · "+locStr(pmaxP)],
];
document.getElementById("statsBox").innerHTML = stats.map(s=>
  `<div class="stat"><div class="k">${eic(s[0],s[1])}${s[2]}</div><div class="v">${s[3]}</div><div class="k">${s[4]}</div></div>`).join("");

// ---- 影响说明（未来 48 小时口径；地图点击联动展示逐小时/逐日明细） ----
// 物探作业影响与建议（2026-09-04）：建议针对整个项目，不要再说"采集点"——
// points 模式下用项目名替代 LBL 里的"采集点"，其他模式沿用 LBL（工区/测线）
// LBL_IMPACT 定义已移除：影响段不再使用前缀（2026-09-04）
const ib=document.getElementById("impactBox");
// icon＝要素图标种类；图标底色沿用当前卡片的 level（预警红 / 注意橙 / 安全绿），与右侧徽标同色
function card(level,title,badge,html,icon){
  const cls = level==="danger"?"imp danger":(level==="warn"?"imp warn":"imp");
  const ic = icon ? eic(icon, level, true) : "";
  return `<div class="${cls}"><div class="h">${ic}${title} <span class="badge ${badge.cls}">${badge.t}</span></div><p>${html}</p></div>`;
}
const daySpan = pp => pp.focusStart ? `${pp.focusStart.slice(5)}~${pp.focusEnd.slice(5)} ` : "";
let out="";
// 降水判据=「小时级短时降水」（>2 大雨 / >5 暴雨 / >10 大暴雨）+ 日累计连续降雨，两者取重
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
if(PN.gustMax>=17.2){ out+=card("danger","大风 / 阵风",{cls:"danger",t:"预警"},
  `阵风达 ${PN.gustMax} m/s（≥8级），钻机塔架、重力仪/磁力仪天线与帐篷稳定性受严重影响，高处作业必须停工。`, "wind"); }
else if(PN.gustMax>=10.8 || PN.windMax>=10.8){ out+=card("warn","大风 / 阵风",{cls:"warn",t:"注意"},
  `阵风达 ${PN.gustMax} m/s（6~7级），钻机与高空设备需加固，谨慎安排吊装/高处作业。`, "wind"); }
else { out+=card("ok","大风 / 阵风",{cls:"ok",t:"安全"},
  `最大阵风 ${PN.gustMax} m/s（约5级及以下），不影响钻机、天线及帐篷，常规作业即可。`, "wind"); }
if(PN.tmax>=35){ out+=card("danger","高温",{cls:"danger",t:"预警"},`最高气温 ${PN.tmax}°C，人员易中暑、设备过热电池衰减，避开正午高强度作业、配备降温与补水。`, "heat"); }
else if(PN.tmin<=0){ out+=card("warn","低温 / 结冰",{cls:"warn",t:"注意"},`最低气温 ${PN.tmin}°C，高海拔段可能结冰，人员保暖、电池效能下降需备用电源。`, "snow"); }
else { out+=card("ok","气温",{cls:"ok",t:"适宜"},`气温区间 ${PN.tmin}~${PN.tmax}°C，体感适宜；高海拔早晚偏凉，注意人员保暖与仪器低温启动。`, "temp"); }
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
// 选中采样点的逐要素曲线 / 柱状图 ============
const EXPLORER = document.getElementById("explorerCharts");
const ELEM_DEFS = {
  temp:  {name:"气温", unit:"°C", icon:"temp", type:"line2", keys:["tempMax","tempMin"], colors:["#E0822C","#2E7DA8"], labels:["每日最高温","每日最低温"],
          thr:[{v:35,color:"#C0392B",label:"高温35°"},{v:0,color:"#2E7DA8",label:"0°"}]},
  precip:{name:"降水", unit:"mm", icon:"rain", type:"bar", keys:["precip"], colors:["#2E86DE"],
          thr:[{v:50,color:"#C0392B",label:"暴雨50"},{v:25,color:"#E0822C",label:"大雨25"}]},
  wind:  {name:"阵风/均风", unit:"m/s", icon:"wind", type:"line2", keys:["gustMax","windMax"], colors:["#8E44AD","#1F7A6B"], labels:["每日最大阵风","每日最大均风"],
          thr:[{v:10.8,color:"#E0822C",label:"6级10.8"},{v:17.2,color:"#C0392B",label:"8级17.2"}]},
};
const ELEM_ORDER = ["precip","wind","temp"];  // 图表渲染顺序：降水 → 阵风/均风 → 气温（气温线图固定最下方）
function selectedElems(){
  const checked = Array.from(document.querySelectorAll('.elem-row input:checked')).map(c=>c.value);
  return ELEM_ORDER.filter(k=>checked.includes(k));   // 按固定顺序过滤，不受勾选框 DOM 顺序影响
}
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
function pointLine(svg, labels, series, opt){
  const W=680,Hh=252,pl=44,pr=14,pt=22,pb=30; svg.setAttribute("viewBox",`0 0 ${W} ${Hh}`); svg.innerHTML="";
  const n=labels.length;
  let lo=Infinity,hi=-Infinity;
  series.forEach(s=>s.data.forEach(v=>{ if(v<lo)lo=v; if(v>hi)hi=v; }));
  if(!isFinite(lo)){lo=0;hi=1;}
  const pad=(hi-lo)*0.18||1; lo-=pad; hi+=pad;
  const X=i=> pl+(W-pl-pr)*(n<=1?0.5:i/(n-1));
  const Y=v=> pt+(Hh-pt-pb)*(1-(v-lo)/(hi-lo));
  const fmt=v=>(Math.round(v*10)/10).toString();
  [lo,(lo+hi)/2,hi].forEach(tv=>{ svg.appendChild(el("line",{x1:pl,y1:Y(tv),x2:W-pr,y2:Y(tv),stroke:"#EEE",["stroke-width"]:1}));
    const tx=el("text",{x:pl-6,y:Y(tv)+4,["text-anchor"]:"end","font-size":13,fill:"#7a8086"}); tx.textContent=Math.round(tv); svg.appendChild(tx); });
  (opt.thresholds||[]).forEach(th=>{ if(th.v<lo||th.v>hi)return;
    svg.appendChild(el("line",{x1:pl,y1:Y(th.v),x2:W-pr,y2:Y(th.v),stroke:th.color,["stroke-width"]:1.4,["stroke-dasharray"]:"5 4",opacity:.85}));
    const tx=el("text",{x:W-pr,y:Y(th.v)-5,["text-anchor"]:"end","font-size":12,fill:th.color,["font-weight"]:"700"}); tx.textContent=th.label; svg.appendChild(tx); });
  const tk = opt.tickEvery||1;
  for(let i=0;i<n;i+=tk){ if(!labels[i]) continue; const tx=el("text",{x:X(i),y:Hh-10,["text-anchor"]:"middle","font-size":13,fill:"#6B7378"}); tx.textContent=labels[i]; svg.appendChild(tx); }
  series.forEach((s,si)=>{ let pts=""; s.data.forEach((v,i)=>{ const x=X(i),y=Y(v); pts+=(i?"L":"M")+x.toFixed(1)+" "+y.toFixed(1)+" "; });
    svg.appendChild(el("path",{"class":"geo",d:pts,fill:"none",stroke:s.color,["stroke-width"]:2.4,["stroke-linejoin"]:"round",["stroke-linecap"]:"round"}));
    const mi=s.data.indexOf(Math.max(...s.data)); svg.appendChild(el("circle",{"class":"geo",cx:X(mi),cy:Y(s.data[mi]),r:3.4,fill:s.color,stroke:"#fff",["stroke-width"]:1.5}));
    // 每个每日点直接标注数值（未来2周 14 天同样标注，不再关闭）：系列已按「大值在上、小值在下」排序
    // （气温=最高温/最低温，风=阵风/均风），故第一条线（最高温/阵风）标在上方（y-6）、
    // 第二条线（最低温/均风）标在下方（y+14），两条线在同一 x 处上下错开、互不遮挡；
    // 仅在 opt.noPointLabels（如有）为真时跳过
    if(!opt.noPointLabels){ s.data.forEach((v,i)=>{ const x=X(i),y=Y(v);
      const ty=(si===0)? y-8 : y+16;      // 上排（大值）标在上方、下排（小值）标在下方，与峰值圆点/折线留出间隙
      const tx=el("text",{x:x,y:ty,["text-anchor"]:"middle","font-size":12,fill:s.color,["font-weight"]:"700"});
      tx.textContent=fmt(v); svg.appendChild(tx); }); }
  });
  // 选日期（与 48 小时图一致）：点击即选、按住左右拖动可连续换日（自由滑动）
  if(opt.pick) bindDragPick(svg, (x,w)=>(x/w*W-pl)/(W-pl-pr)*(n-1), opt.pick.apply,
      {n:n, toggle:opt.pick.toggle, getSel:opt.pick.getSel, cancel:opt.pick.cancel});
  if(opt.pick) svg._pickCtx={n:n, X:X, pt:pt, pb:pb, Hh:Hh, W:W, pl:pl, pr:pr, getRows:opt.getRows};
}
function pointBar(svg, labels, vals, opt){
  const W=680,Hh=252,pl=44,pr=14,pt=22,pb=30; svg.setAttribute("viewBox",`0 0 ${W} ${Hh}`); svg.innerHTML="";
  const n=labels.length, yMax=opt.yMax;
  const fmt=v=>(Math.round(v*10)/10).toString();
  const X=i=> pl+(W-pl-pr)*(n<=1?0.5:i/(n-1));      // 与折线图完全一致的横坐标
  const Y=v=> pt+(Hh-pt-pb)*(1-v/yMax);
  [0,yMax/2,yMax].forEach(tv=>{ svg.appendChild(el("line",{x1:pl,y1:Y(tv),x2:W-pr,y2:Y(tv),stroke:"#EEE",["stroke-width"]:1}));
    const tx=el("text",{x:pl-6,y:Y(tv)+4,["text-anchor"]:"end","font-size":13,fill:"#7a8086"}); tx.textContent=Math.round(tv); svg.appendChild(tx); });
  (opt.thresholds||[]).forEach(th=>{ if(th.v>yMax)return;
    svg.appendChild(el("line",{x1:pl,y1:Y(th.v),x2:W-pr,y2:Y(th.v),stroke:th.color,["stroke-width"]:1.4,["stroke-dasharray"]:"5 4",opacity:.85}));
    const tx=el("text",{x:W-pr,y:Y(th.v)-5,["text-anchor"]:"end","font-size":12,fill:th.color,["font-weight"]:"700"}); tx.textContent=th.label; svg.appendChild(tx); });
  const bw=((W-pl-pr)/n)*0.62;
  const base=Y(0);                           // 基线＝零线（旧代码误用 Hh-pt-pb，令柱高系统性少 22px、柱底悬空）
  vals.forEach((v,i)=>{ const x=X(i);
    const pt0=(opt.ptypes||[])[i]||0;         // 降水类型：0无 1降雨 2降雪 3雨夹雪
    let bh=0;
    if(v>0 || pt0){                           // 图内无降水不画柱；降雪水当量不足 0.1mm 时仍保留最小柱以承载类型着色
      bh=Math.max(base-Y(v),3);                // 小值也保证 3px 可见高度（不再被大量程压成亚像素）
      const color=PT_FILL[pt0]||PT_FILL_FB;    // 按降水类型着色：降雨蓝 / 降雪青 / 雨夹雪紫
      svg.appendChild(el("rect",{"class":"geo",x:x-bw/2,y:base-bh,width:bw,height:bh,rx:3,fill:color}));
    }
    // 柱顶直接标出数值；微量（折合不足 0.1mm 但确有降雪）标「<0.1」，真正无降水标「0」（浅灰）
    if(!opt.noPointLabels){ const lab=(v>0 ? fmt(v) : (pt0 ? "<0.1" : "0"));
      const ly=bh ? base-bh-5 : base-6;
      const tx=el("text",{x:x,y:ly,["text-anchor"]:"middle","font-size":12,fill:(v>0?"#5b6166":"#9aa0a4"),["font-weight"]:"700"});
      tx.textContent=lab; svg.appendChild(tx); } });
  const tk = opt.tickEvery||1;
  for(let i=0;i<n;i+=tk){ if(!labels[i]) continue; const tx=el("text",{x:X(i),y:Hh-10,["text-anchor"]:"middle","font-size":13,fill:"#6B7378"}); tx.textContent=labels[i]; svg.appendChild(tx); }
  // 选日期（与 48 小时图一致）：点击即选、按住左右拖动可连续换日（自由滑动）
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
// 「未来2周」选日期：只重绘红色竖线 + 数值框，不重建图表（图形位置与界面保持不动）
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
  if(SEL<0){ EXPLORER.innerHTML='<div class="empty-tip">点击上方地图任意采样点，这里将显示该点未来2周的逐要素曲线 / 柱状图。</div>';
    document.getElementById("explorerInfo").innerHTML=''; return; }
  const pt=DATA.points[SEL];
  updateExplorerInfo();
  EXPLORER.innerHTML="";
  const labs=DATA.meta.dailyDates.map(d=>d.slice(5));
  const nd=labs.length;
  const fmtD=v=>String(Math.round(v*10)/10);
  // 选日期：拖动/点击直接设置（不做逐格 toggle，避免拖动时反复闪断）；
  // 「再点同一日取消」由 bindDragPick 的 toggle 逻辑在 pointerup（未拖动）时处理
  const setDay=i=>{ DAY_SEL=i; paintDaySel(); updateExplorerInfo(); };
  const DAY_PICK={ toggle:true, getSel:()=>DAY_SEL, cancel:()=>setDay(-1), apply:i=>setDay(i) };
  // 2 周（14 天）横轴点位密集：日期刻度隔天标注；数值一律「逐点直接标在图上」（2026-09-21 起，
  // 不再因 14 天而关闭标值——用户要求各图直接显示数值，免去点选才能看读数）
  const xopt={tickEvery: nd>9?2:1};
  const sel=selectedElems();
  if(sel.length===0){ EXPLORER.innerHTML='<div class="empty-tip">请在上方勾选至少一个要素。</div>'; return; }
  sel.forEach(k=>{
    const def=ELEM_DEFS[k];
    const box=document.createElement("div"); box.className="ec";
    const h=document.createElement("div"); h.className="ec-h"; h.textContent=`${def.name}（${def.unit}）`;
    const svg=document.createElementNS(NS,"svg"); svg.setAttribute("class","chart"); svg.setAttribute("preserveAspectRatio","none");
    box.appendChild(h);
    // 图例：标明各系列为「每日」聚合（最高/最低温、最大阵风/均风、降水）
    const leg=document.createElement("div"); leg.className="ec-legend";
    if(def.type==="bar"){
      leg.innerHTML=eic(def.icon,"plain",true)+ptLegendHtml(def.icon);
    } else {
      leg.innerHTML=eic(def.icon,"plain",true)
        + def.labels.map((lb,i)=>`<span class="lg"><i style="background:${def.colors[i]}"></i>${lb}</span>`).join("");
    }
    box.appendChild(leg);
    box.appendChild(svg); EXPLORER.appendChild(box);
    if(def.type==="bar"){
      const vals=pt.series[def.keys[0]];
      const dmax=Math.max(...vals,0);
      let yMax, thresholds;
      if(dmax < 5){            // 量小：仅显示 5mm 参考线，y 轴上限取 5
        yMax=5; thresholds=[{v:5,color:"#7FB3D5",label:"5mm"}];
      } else {                 // 量大：显示大雨 10mm 警戒线
        yMax=Math.max(10, Math.ceil((dmax*1.1)/5)*5);
        thresholds=[{v:10,color:"#C0392B",label:"大雨 10mm"}];
      }
      const ptypes=pt.series.ptype||[];
      pointBar(svg, labs, vals, Object.assign({yMax:yMax, thresholds:thresholds, ptypes:ptypes,
        pick:DAY_PICK,
        getRows:i=>[{t:`降水 ${fmtD(vals[i])} mm ${ptypeText(ptypes[i])}`.replace(/\s+$/,""),
                    c:"#1565C0"}]}, xopt));
    } else {
      const series=def.keys.map((kk,i)=>({name:def.labels[i],color:def.colors[i],data:pt.series[kk]}));
      pointLine(svg, labs, series, Object.assign({thresholds:def.thr,
        pick:DAY_PICK,
        getRows:i=>series.map(s=>({t:`${s.name} ${fmtD(s.data[i])} ${def.unit}`, c:s.color}))}, xopt));
    }
  });
  paintDaySel();
}
// 要素勾选行补小图标（底色 .plain＝不带风险含义，与风险等级色区分）；勾选行为 flex 容器，图标与文字间距走父级 gap
document.querySelectorAll('#elemRowD label').forEach(lb=>{
  const inp=lb.querySelector("input"); if(!inp) return;
  const def=ELEM_DEFS[inp.value]; if(!def || !def.icon) return;
  inp.insertAdjacentHTML("afterend", eic(def.icon, "plain", true));   // 图标紧贴复选框之后，与文字成组
});
document.querySelectorAll('#elemRowD input').forEach(c=>c.addEventListener("change", renderExplorer));
renderExplorer();

// ============ 选中采样点的「未来 48 小时」逐小时要素合并图（降水柱 + 均风/阵风/气温折线；配色对齐石油工程；可点击图表选时） ============
const H_EXPLORER = document.getElementById("hourlyCharts");
let HOURLY_SVG = null, HOURLY_MARKER = null, HOURLY_N = 0;
const HW=680, HH=300, HPL=44, HPR=52, HPT=24, HPB=30;
function hxOf(i){ return HPL+(HW-HPL-HPR)*(HOURLY_N<=1?0.5:i/(HOURLY_N-1)); }
function renderHourlyExplorer(){
  H_EXPLORER.innerHTML="";
  if(SEL<0){ H_EXPLORER.innerHTML='<div class="empty-tip">点击上方地图选择采样点，下方显示该点未来 48 小时要素合并图。</div>';
    HOURLY_N=0; HOURLY_SVG=null; HOURLY_MARKER=null; return; }
  const pt=DATA.points[SEL];
  if(!pt.hx){
    H_EXPLORER.innerHTML='<div class="empty-tip">该工区采样点较多，逐小时明细未嵌入；请见「未来 2 周」页的逐日要素图表。</div>';
    HOURLY_N=0; HOURLY_SVG=null; HOURLY_MARKER=null; return;
  }
  const box=document.createElement("div"); box.className="ec"; H_EXPLORER.appendChild(box);
  const n=Math.min(pt.hx.temp.length, NEAR_H); HOURLY_N=n;
  const precip=pt.hx.precip.slice(0,n), wind=pt.hx.wind.slice(0,n), gust=pt.hx.gust.slice(0,n), temp=pt.hx.temp.slice(0,n);
  const bottom=HH-HPB;
  // 图例（配色 / 文字对齐石油工程）
  const leg=document.createElement("div"); leg.className="ec-legend";
  leg.innerHTML= ptLegendHtml("rain")
    +`<span class="lg">${eic("wind","plain",true)}<i style="background:#1F7A6B"></i>均风(m/s)</span>`
    +`<span class="lg">${eic("wind","plain",true)}<i style="background:#8E44AD"></i>阵风(m/s)</span>`
    +`<span class="lg">${eic("temp","plain",true)}<i style="background:#2E7DA8"></i>气温(℃)</span>`;
  box.appendChild(leg);
  const svg=document.createElementNS(NS,"svg"); svg.setAttribute("class","chart"); svg.setAttribute("viewBox",`0 0 ${HW} ${HH}`); svg.setAttribute("preserveAspectRatio","none");
  box.appendChild(svg);
  // 自由滑动选时（与石油工程 48 小时图完全一致）：按下即选、按住左右拖动连续跟随
  bindDragPick(svg, (x,w)=>(x/w*HW-HPL)/(HW-HPL-HPR)*(HOURLY_N-1), selectHour, {n:HOURLY_N});
  // 左轴：降水(mm)，柱占绘图区 85% 高（加高以更突出）
  const pMax=Math.max(...precip,0.1);
  const precipAxis=Math.max(pMax*1.12,10);
  const barRegion=(bottom-HPT)*0.85;
  const Yp=v=> bottom-(v/precipAxis)*barRegion;
  // 右轴：风 / 阵风 / 气温（m/s、℃ 共用绘图高度）
  const wMax=Math.max(...gust,1)*1.12, wMin=0;
  const tMax=Math.max(...temp,1)+3, tMin=Math.min(...temp,-1)-3;
  const Yw=v=> bottom-((v-wMin)/(wMax-wMin))*(bottom-HPT);
  const Yt=v=> bottom-((v-tMin)/(tMax-tMin))*(bottom-HPT);
  // 背景网格
  for(let g=0;g<=4;g++){const y=HPT+(bottom-HPT)*g/4; svg.appendChild(el("line",{x1:HPL,y1:y,x2:HW-HPR,y2:y,stroke:"#EFEFEF",["stroke-width"]:1}));}
  // 左轴降水刻度
  [0,precipAxis/2,precipAxis].forEach(v=>{const y=Yp(v);const tx=el("text",{x:HPL-6,y:y+3,["text-anchor"]:"end","font-size":10,fill:"#7a8086"});tx.textContent=Math.round(v);svg.appendChild(tx);});
  // 右轴风刻度
  [0,wMax/2,wMax].forEach(v=>{const y=Yw(v);const tx=el("text",{x:HW-HPR+6,y:y+3,["text-anchor"]:"start","font-size":10,fill:"#7a8086"});tx.textContent=Math.round(v);svg.appendChild(tx);});
  // 降水柱（分级着色，对齐石油工程；柱内标注降水类型图标：降雨 / 降雪 / 雨夹雪）
  const bw=((HW-HPL-HPR)/n)*0.6;
  const ptypes=pt.hx.pt||[];
  precip.forEach((v,i)=>{const pt0=ptypes[i]||0; if(!(v>0)&&!pt0)return;const x=hxOf(i),y=Yp(v),h=Math.max(bottom-y,3);const color=PT_FILL[pt0]||PT_FILL_FB;svg.appendChild(el("rect",{"class":"geo",x:x-bw/2,y:bottom-h,width:bw,height:h,rx:2,fill:color}));});
  // 降水阈值线：小时级短时降水口径（大雨 2 / 暴雨 5 / 大暴雨 10 mm/h）
  // 注意：这里**不是**日累计 25/50 —— 本图纵轴是逐小时降水，画 25/50 会与轴口径不符
  [{v:RAIN_H.heavy,c:"#E0822C",t:"大雨 2"},{v:RAIN_H.storm,c:"#C0392B",t:"暴雨 5"},{v:RAIN_H.torrent,c:"#7B1B12",t:"大暴雨 10"}].forEach(th=>{if(th.v>precipAxis)return;const y=Yp(th.v);svg.appendChild(el("line",{x1:HPL,y1:y,x2:HW-HPR,y2:y,stroke:th.c,["stroke-width"]:1.2,["stroke-dasharray"]:"5 4",opacity:.75}));const tx=el("text",{x:HPL+3,y:y-4,["text-anchor"]:"start","font-size":10.5,fill:th.c,["font-weight"]:"700"});tx.textContent=th.t;svg.appendChild(tx);});
  // 风阈值线（6级10.8 / 8级17.2）
  [{v:10.8,c:"#E0822C",t:"6级"},{v:17.2,c:"#C0392B",t:"8级"}].forEach(th=>{if(th.v>wMax)return;const y=Yw(th.v);svg.appendChild(el("line",{x1:HPL,y1:y,x2:HW-HPR,y2:y,stroke:th.c,["stroke-width"]:1.1,["stroke-dasharray"]:"5 4",opacity:.7}));const tx=el("text",{x:HW-HPR,y:y-4,["text-anchor"]:"end","font-size":10.5,fill:th.c,["font-weight"]:"700"});tx.textContent=th.t;svg.appendChild(tx);});
  // 气温阈值线（高温35 / 0°）
  [{v:35,c:"#C0392B",t:"35°"},{v:0,c:"#2E7DA8",t:"0°"}].forEach(th=>{if(th.v<tMin||th.v>tMax)return;const y=Yt(th.v);svg.appendChild(el("line",{x1:HPL,y1:y,x2:HW-HPR,y2:y,stroke:th.c,["stroke-width"]:1.1,["stroke-dasharray"]:"5 4",opacity:.7}));const tx=el("text",{x:HW-HPR,y:y-4,["text-anchor"]:"end","font-size":10.5,fill:th.c,["font-weight"]:"700"});tx.textContent=th.t;svg.appendChild(tx);});
  // 折线：均风（绿实线）、阵风（紫虚线，对齐石油工程）、气温（蓝实线）
  const drawLine=(data,Yc,color,dash)=>{let p="";data.forEach((v,i)=>{const x=hxOf(i),y=Yc(v);p+=(i?"L":"M")+x.toFixed(1)+" "+y.toFixed(1)+" ";});const a={"class":"geo",d:p,fill:"none",stroke:color,["stroke-width"]:2.2,["stroke-linejoin"]:"round",["stroke-linecap"]:"round"};if(dash)a["stroke-dasharray"]=dash;svg.appendChild(el("path",a));};
  drawLine(wind,Yw,"#1F7A6B");
  drawLine(gust,Yw,"#8E44AD","6 4");
  drawLine(temp,Yt,"#2E7DA8");
  // X 轴日期
  for(let i=0;i<n;i+=24){const t=DATA.hourly.time[i]||"";if(!t)continue;const tx=el("text",{x:hxOf(i),y:HH-9,["text-anchor"]:"middle","font-size":11,fill:"#6B7378"});tx.textContent=t.slice(5,10);svg.appendChild(tx);}
  // 当前小时竖线（点击图表移动）
  const marker=el("line",{x1:0,y1:HPT,x2:0,y2:bottom,stroke:"#C0392B","stroke-width":1.5,["stroke-dasharray"]:"4 3",opacity:.85});
  svg.appendChild(marker); HOURLY_SVG=svg; HOURLY_MARKER=marker;
  updateHourlyMarker();
  updateHourlyReadout();
}
// 在 48 小时图上直接标出「当前选中小时」的具体数值
function updateHourlyReadout(){
  if(!HOURLY_SVG || HOURLY_N<=0) return;
  let g=document.getElementById("hourlyReadout");
  if(!g){ g=document.createElementNS(NS,"g"); g.setAttribute("id","hourlyReadout"); }
  HOURLY_SVG.appendChild(g); g.innerHTML="";
  const pt=DATA.points[SEL]; if(!pt || !pt.hx) return;
  const h=CUR_HOUR;
  const ptype=(pt.hx.pt||[])[h]||0;
  const pLabel=ptypeText(ptype);
  const rows=[["降水 ", pt.hx.precip[h].toFixed(1)+" mm/h"+(pLabel?" "+pLabel:""), "#0D47A1"],
              ["气温 ", pt.hx.temp[h].toFixed(1)+" ℃", "#1A5A87"],
              ["阵风 ", pt.hx.gust[h].toFixed(1)+" m/s", "#5B2A7D"],
              ["均风 ", pt.hx.wind[h].toFixed(1)+" m/s", "#0F5B4C"]];
  const x=hxOf(h);
  const cw=t=>t.split("").reduce((a,ch)=>a+(ch.charCodeAt(0)>255?11.6:6.4),0);
  const bw=Math.max(...rows.map(r=>cw(r[0])+cw(r[1])))+20;
  const lh=15, pady=6, bh=rows.length*lh+pady*2;
  let bx=x+10; if(bx+bw>HW-HPR) bx=x-10-bw; if(bx<HPL) bx=HPL;
  const by=HPT+4;
  g.appendChild(el("rect",{x:bx,y:by,width:bw,height:bh,rx:6,fill:"rgba(255,255,255,.96)",stroke:"#C0392B","stroke-width":1.2}));
  rows.forEach((r,i)=>{ const ty=by+pady+11+i*lh;
    g.appendChild(el("rect",{x:bx+5,y:ty-11,width:cw(r[0])+cw(r[1])+8,height:14.5,rx:5,fill:tintOf(r[2])}));
    const lb=el("text",{x:bx+9,y:ty,"font-size":11.5,fill:"#3A4146"});
    lb.textContent=r[0]; g.appendChild(lb);
    const vv=el("text",{x:bx+9+cw(r[0]),y:ty,"font-size":11.5,fill:r[2],["font-weight"]:"900"});
    vv.textContent=r[1]; g.appendChild(vv); });
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
  if(b.dataset.tab==='t3'){ renderMap("3"); if(SEL>=0) selectPoint(SEL); }   // 未来2周：重绘地图（整窗风险着色），并已选点则补画选中环
}));
// 地图缩放/平移初始化（每个地图各绑一份）
["2","3"].forEach(s=>{ if(document.getElementById("mapbox"+s)){ bindMap(s); updZL(s); } });
// iOS Safari 私有的双指手势事件：捏地图时别把「整页」一起放大。
// 只在地图区域内拦，地图以外的页面照常可双指放大看文字（不影响无障碍）。
["gesturestart","gesturechange"].forEach(t=>document.addEventListener(t,(ev)=>{
  const tg=ev.target; if(tg && tg.closest && tg.closest(".mapbox")) ev.preventDefault();
},{passive:false}));
</script>
</body>
</html>
"""

html = (TEMPLATE.replace("__DATA__", DATA_JSON)
        .replace("__TITLE__", f"{args.name} · 工区2周天气看板"))

# 内嵌页头背景图（assets/hero-bg.jpg → CSS 背景）
hc = hero_css()
html = html.replace("/*__HERO_CSS__*/", hc)
print("hero bg:", ("embedded" if hc else "skipped"))

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
print("DONE")
