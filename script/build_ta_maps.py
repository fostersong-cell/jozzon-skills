# -*- coding: utf-8 -*-
"""【已停用 · 历史一次性脚本，请勿运行】生成 wutan_ta_map.json 与 engineering_ta_map.json。

2026-10-19 起：本脚本的两路输入（物探 KML 目录、石油工程 all_points_info.md）已整体删除，
两个 ta_map json 现为**自包含的唯一数据源**，点位增删改请直接编辑 json。
主链路改用：<SKILLS>/script/rerun_wutan.py 与 <SKILLS>/script/rerun_engineering.py。
保留本文件仅供追溯 ta_id 继承逻辑（按 (名称, 经纬度) 从旧 json 继承已回填的 ta_id）。

2026-10-16 改造：**保留已回填的 ta_id**（按 (名称, 经纬度) 从现有 json 里继承），
避免重跑把九章目标区 ID 抹成 null。原版硬编码 null，放在 /tmp 容易误跑丢数据。
"""
import xml.etree.ElementTree as ET
import os, json, datetime

# BEIDOU 可经环境变量覆盖（拷贝到其它电脑时指向该机的 beidou 工作目录）；缺省为本机路径
BASE = os.environ.get("BEIDOU", "/Users/zhijunsong/Desktop/同步空间/jozzon/1.个人资料/AI/work/beidou")
WKML = os.path.join(BASE, "wutan", "kml")
EKML = os.path.join(BASE, "engineering", "kml")
WP = os.path.join(BASE, "wutan", "kml", "wutan_ta_map.json")
EP = os.path.join(BASE, "engineering", "kml", "engineering_ta_map.json")
KNS = "{http://www.opengis.net/kml/2.2}"

# ---------- 停用守卫（2026-10-19）----------
# 输入已删：物探 KML 与 all_points_info.md 均不在 beidou 目录，硬跑只会报 FileNotFoundError。
# 这里给出明确指引后直接退出，避免被误当成「主链路」使用。
_REQUIRED = [os.path.join(EKML, "all_points_info.md")]
_missing = [p for p in _REQUIRED if not os.path.exists(p)]
if _missing:
    raise SystemExit(
        "本脚本已停用（2026-10-19）：all_points_info.md / 物探 KML 已整体移除，\n"
        "  wutan_ta_map.json 与 engineering_ta_map.json 现为自包含的唯一数据源。\n"
        "  日常取数请用：<SKILLS>/script/rerun_wutan.py、<SKILLS>/script/rerun_engineering.py\n"
        "  缺失输入：\n    " + "\n    ".join(_missing)
    )

# (中文名, pin, 边框kml, 采集点kml) —— 与 rerun_wutan.py 保持一致
PROJS = [
    ("通江三维", "tongjiang-sanwei-gongqu", "tongjiang-sanwei-gongqu.kml", "tongjiang-sanwei-gongqu_points.kml"),
    ("南郑三维", "nanzhengsanwei-gongqu", "nanzhengsanwei-gongqu.kml", "nanzhengsanwei-gongqu_points.kml"),
    ("藏北天山", "cangbeitianshan-cesian", "cangbeitianshan-cesian.kml", "cangbeitianshan-cesian_points.kml"),
    # 2026-10-19：广东广西深反射项目已结束，从物探移除
    ("资阳三维", "ziyang-sanwei-gongqu", "ziyang-sanwei-gongqu.kml", "ziyang-sanwei-gongqu-points.kml"),
    ("华亭静宁二维", "huatingjingan-gongqu", "huatingjingan-gongqu.kml", "huatingjingan-gongqu-points.kml"),
    ("宁蒗-万马场二维", "ninglangwanmachang-gongqu", "ninglangwanmachang-gongqu.kml", "ninglangwanmachang-gongqu-points.kml"),
    ("藏北高原冻土二维", "cangbeigaoyuandongtu-cexian", "cangbeigaoyuandongtu-cexian.kml", "cangbeigaoyuandongtu-cexian-points.kml"),
    ("准中2027二维", "zhunzhong2027erwei-cexian", "zhunzhong2027erwei-cexian.kml", "zhunzhong2027erwei-cexian-points.kml"),
    ("云南大关", "daguan-xiangmu-gongqu-cexian", "daguan-xiangmu-gongqu-cexian.kml", "daguan-xiangmu-gongqu-cexian-points.kml"),
    ("煤层气勘查三维", "meicengqikanchasanwei-gongqu", "meicengqikanchasanwei-gongqu.kml", "meicengqikanchasanwei-gongqu-points.kml"),
]

WUTAN_NOTE = ("ta_id 于 2026-10-16 回填（87/87）。云南大关 P1~P6 为 KML 占位名，按方位对应九章点："
              "P1顶部左=西北点50708、P2顶部右=东北点50712、P3中部左=西点50706、P4中部右=中心点50707、"
              "P5底部左=西南点50716、P6底部右=东南点50710。藏北冻土 ZB2026-SN-02 中间点取 51783"
              "（与北端51779/南端51781 同批注册；九章另有旧名 51732「ZB2026-SN-02-中间」未采用）。")
ENG_NOTE = ("ta_id 于 2026-10-16 回填（17/17）。马401-4H井 与 马401-2H井 同址（相距约 150m），"
            "九章仅注册一个 51654「马401H井」，两口井共用该 ID。")


def load_prev_points(path, key_field, coord_keys=("lon", "lat")):
    """从现有 json 读取已完成映射：{(名称, lon, lat): ta_id}。"""
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return {}
    out = {}
    if isinstance(d.get("points"), list):          # 工程：扁平 points
        rows = d["points"]
    else:                                          # 物探：项目 → {points:[...]}
        rows = [p for v in d.values() if isinstance(v, dict) for p in v.get("points", [])]
    for p in rows:
        nm = p.get(key_field)
        if nm is None or p.get("ta_id") is None:
            continue
        out[(nm, p.get(coord_keys[0]), p.get(coord_keys[1]))] = p["ta_id"]
    return out


def coords_of(text):
    """'lon,lat,alt lon,lat,alt' → [[lon,lat], ...]"""
    out = []
    for tok in (text or "").split():
        parts = tok.split(",")
        if len(parts) >= 2:
            try:
                out.append([round(float(parts[0]), 6), round(float(parts[1]), 6)])
            except ValueError:
                pass
    return out


def parse_kml(fp):
    """返回 [{'name','type','coordinates'}]，覆盖 Point / LineString / Polygon。"""
    r = ET.parse(fp).getroot()
    items = []
    for pm in r.iter(KNS + "Placemark"):
        nm = (pm.findtext(KNS + "name") or "").strip()
        for typ in ("Point", "LineString", "Polygon"):
            for g in pm.iter(KNS + typ):
                if typ == "Point":
                    c = g.findtext(KNS + "coordinates") or ""
                else:
                    c = g.findtext(".//" + KNS + "coordinates") or ""
                items.append({"name": nm, "type": typ, "coordinates": coords_of(c)})
    return items


# ---------------- 保留已回填的 ta_id ----------------
prev_w = load_prev_points(WP, "name")
prev_e = load_prev_points(EP, "点位")
kept = [0]

def ta_of(prev, nm, lon, lat):
    tid = prev.get((nm, lon, lat))
    if tid is not None:
        kept[0] += 1
    return tid

# ---------------- 1. 物探 ----------------
w_map = {
    "_schema": ("物探项目 → 作业点(采集点) + 几何。字段：pin=拼音短名；kml=来源文件名；"
                "points=作业点列表(名称/经纬度/ta_id，按序号对应 build_dashboard 作业点)；"
                "lines=测线(LineString)名称与坐标；polygons=工区边界(Polygon)名称与坐标。"
                "ta_id=九章目标区ID，未注册时为 null（作业点必须填 ta_id 才能取数）。坐标顺序 [经度, 纬度]。"),
    "_updated": datetime.date.today().isoformat(),
    "_note": WUTAN_NOTE,
}
summary = []
for name, pin, bk, pk in PROJS:
    bpath, ppath = os.path.join(WKML, bk), os.path.join(WKML, pk)
    bitems = parse_kml(bpath) if os.path.exists(bpath) else []
    pitems = parse_kml(ppath) if os.path.exists(ppath) else []
    points = []
    for it in pitems:
        if it["type"] == "Point" and it["coordinates"]:
            lon, lat = it["coordinates"][0]
            points.append({"name": it["name"] or f"作业点#{len(points)+1}", "lon": lon, "lat": lat,
                           "ta_id": ta_of(prev_w, it["name"] or f"作业点#{len(points)+1}", lon, lat)})
    lines = [{"name": it["name"], "coordinates": it["coordinates"]} for it in bitems if it["type"] == "LineString"]
    polys = [{"name": it["name"], "coordinates": it["coordinates"]} for it in bitems if it["type"] == "Polygon"]
    # 少数项目边框 KML 里也混有 Point（并入作业点）
    for it in bitems:
        if it["type"] == "Point" and it["coordinates"]:
            lon, lat = it["coordinates"][0]
            points.append({"name": it["name"] or f"作业点#{len(points)+1}", "lon": lon, "lat": lat,
                           "ta_id": ta_of(prev_w, it["name"] or f"作业点#{len(points)+1}", lon, lat)})
    w_map[name] = {"pin": pin, "kml": {"border": bk, "points": pk},
                   "points": points, "lines": lines, "polygons": polys}
    summary.append((name, len(points), len(lines), len(polys)))

# ---------------- 2. 石油工程 ----------------
md = open(os.path.join(EKML, "all_points_info.md"), encoding="utf-8").read()
rows = []
for line in md.splitlines():
    line = line.strip()
    if not line.startswith("|"):
        continue
    cells = [c.strip() for c in line.strip("|").split("|")]
    if len(cells) < 6 or cells[0] in ("一级",) or set(cells[0]) <= set(":-"):
        continue
    try:
        lon, lat = float(cells[4]), float(cells[5])
    except ValueError:
        continue
    rows.append({"一级": cells[0], "二级": cells[1], "三级": cells[2], "点位": cells[3],
                 "lon": lon, "lat": lat, "ta_id": ta_of(prev_e, cells[3], lon, lat)})
e_map = {
    "_schema": ("石油工程井位/管线点位 → 九章目标区。自包含（2026-10-19 起不再依赖任何 md/KML）："
                "每项含 一级/二级/三级/点位 + 经纬度 + ta_id（未注册为 null）。"
                "build_points_data.py 直接读取本文件全部字段与 ta_id 取数。"),
    "_updated": datetime.date.today().isoformat(),
    "_note": ENG_NOTE,
    "points": rows,
}


def pretty(v, indent=0):
    """紧凑美化：扁平 dict / 纯数值列表 / 坐标对列表 全部内联到一行，其余按层展开。"""
    pad = "  " * indent
    if isinstance(v, dict):
        if not v:
            return "{}"
        if all(not isinstance(x, (dict, list)) for x in v.values()):
            return "{" + ", ".join(f'{json.dumps(k, ensure_ascii=False)}: {json.dumps(x, ensure_ascii=False)}'
                                   for k, x in v.items()) + "}"
        items = [f'{pad}  {json.dumps(k, ensure_ascii=False)}: {pretty(x, indent + 1)}' for k, x in v.items()]
        return "{\n" + ",\n".join(items) + f"\n{pad}}}"
    if isinstance(v, list):
        if not v:
            return "[]"
        if all(not isinstance(x, (dict, list)) for x in v):
            return "[" + ", ".join(json.dumps(x, ensure_ascii=False) for x in v) + "]"
        if all(isinstance(x, list) and all(not isinstance(y, (dict, list)) for y in x) for x in v):
            return "[" + ", ".join("[" + ", ".join(json.dumps(y, ensure_ascii=False) for y in x) + "]" for x in v) + "]"
        parts = [f"{pad}  {pretty(x, indent + 1)}" for x in v]
        return "[\n" + ",\n".join(parts) + f"\n{pad}]"
    return json.dumps(v, ensure_ascii=False)


with open(WP, "w", encoding="utf-8") as f:
    f.write(pretty(w_map) + "\n")
with open(EP, "w", encoding="utf-8") as f:
    f.write(pretty(e_map) + "\n")

print("== wutan_ta_map.json ==")
for name, np_, nl, npo in summary:
    print(f"  {name:16s} 点 {np_:2d} · 线 {nl:2d} · 边界 {npo}")
print(f"  合计 {len(summary)} 个项目，{sum(s[1] for s in summary)} 个作业点，继承 ta_id {kept[0]} 个")
print("== engineering_ta_map.json ===")
print(f"  {len(rows)} 个点位")
for r in rows:
    print(f"  {r['点位']:12s} {r['一级']}/{r['二级']}/{r['三级']}  ({r['lon']},{r['lat']})  ta_id={r['ta_id']}")
print("written:", WP)
print("written:", EP)
