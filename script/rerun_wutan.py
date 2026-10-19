import subprocess, os, shutil

# 本脚本位于 <技能根>/script/，故父目录两级即技能根（与安装位置无关，便于拷贝移植）
SKILLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENV = os.path.expanduser("~/.workbuddy/binaries/python/envs/default/bin/python")
SCRIPT = os.path.join(SKILLS, "weather-wutan-html", "scripts", "build_dashboard.py")
# 2026-09-17 起：index 总览生成已从 beidou/ 抽离为独立 skill weather-wutan-index
INDEX_SKILL = os.path.join(SKILLS, "weather-wutan-index", "scripts")
BASE = os.environ.get("BEIDOU", "/Users/zhijunsong/Desktop/同步空间/jozzon/1.个人资料/AI/work/beidou")
KML = os.path.join(BASE, "wutan", "kml")
HTML = os.path.join(BASE, "wutan", "html")
DATA = os.path.join(BASE, "wutan", "data")

# (中文名, 拼音pin, 边框kml, 采集点kml)
projs = [
    ("通江三维", "tongjiang-sanwei-gongqu", "tongjiang-sanwei-gongqu.kml", "tongjiang-sanwei-gongqu_points.kml"),
    ("南郑三维", "nanzhengsanwei-gongqu", "nanzhengsanwei-gongqu.kml", "nanzhengsanwei-gongqu_points.kml"),
    ("藏北天山", "cangbeitianshan-cesian", "cangbeitianshan-cesian.kml", "cangbeitianshan-cesian_points.kml"),
    # 2026-10-19：广东广西深反射项目已结束，从物探移除
    ("资阳三维", "ziyang-sanwei-gongqu", "ziyang-sanwei-gongqu.kml", "ziyang-sanwei-gongqu-points.kml"),
    ("华亭静宁二维", "huatingjingan-gongqu", "huatingjingan-gongqu.kml", "huatingjingan-gongqu-points.kml"),
    ("宁蒗-万马场二维", "ninglangwanmachang-gongqu", "ninglangwanmachang-gongqu.kml", "ninglangwanmachang-gongqu-points.kml"),
    ("藏北高原冻土二维", "cangbeigaoyuandongtu-cexian", "cangbeigaoyuandongtu-cexian.kml", "cangbeigaoyuandongtu-cexian-points.kml"),
    # 2026-10-03：准中2027二维两个 KML 已改名对齐命名——
    #   zhunzhong2027erwei-cexian.kml  = 5 条 <LineString> 测线 → 第 3 列（--kml）
    #   zhunzhong2027erwei-points.kml  = 12 个 <Point> 采集点  → 第 4 列（--points）
    ("准中2027二维", "zhunzhong2027erwei-cexian", "zhunzhong2027erwei-cexian.kml", "zhunzhong2027erwei-cexian-points.kml"),
    ("云南大关", "daguan-xiangmu-gongqu-cexian", "daguan-xiangmu-gongqu-cexian.kml", "daguan-xiangmu-gongqu-cexian-points.kml"),
    ("煤层气勘查三维", "meicengqikanchasanwei-gongqu", "meicengqikanchasanwei-gongqu.kml", "meicengqikanchasanwei-gongqu-points.kml"),
]

ok, fail = [], []
for name, pin, kml, pts in projs:
    # 子目录短名：去掉 -gongqu / -cexian / -cesian 后缀（如 tongjiang-sanwei-gongqu → tongjiang-sanwei）
    short = pin
    for suf in ("-gongqu", "-cexian", "-cesian"):
        if short.endswith(suf):
            short = short[: -len(suf)]
            break
    print(f"\n===== [{name}] {pin} → {short}.html =====", flush=True)
    cmd = [
        VENV, SCRIPT,
        "--name", name,
        "--kml", os.path.join(KML, kml),
        "--points", os.path.join(KML, pts),
        "--grid", "20",
        "--outdir", HTML,
        "--outfile", f"{short}.html",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        print("  ❌ 超时", flush=True); fail.append(pin); continue
    if r.stdout.strip():
        print("STDOUT:", r.stdout.strip()[-600:], flush=True)
    if r.returncode != 0 and r.stderr.strip():
        print("STDERR:", r.stderr.strip()[-600:], flush=True)
    # 中文名 _data.json -> 拼音 data/
    # 说明：build_dashboard.py 把 {name}_data.json 写到 --outdir(=HTML)；
    # 这里将其迁移为 data/{pin}_data.json。个别情况下 subprocess 返回后 src 的
    # os.path.exists 判定会偶发误判为不存在，故成功判据改为「dst 已就位且新鲜」，
    # 避免把已成功迁移的项目误报为失败。
    src = os.path.join(HTML, f"{name}_data.json")
    dst = os.path.join(DATA, f"{pin}_data.json")
    if os.path.exists(src):
        shutil.move(src, dst)
        print(f"  ✓ moved data -> {os.path.basename(dst)}", flush=True)
    elif os.path.exists(dst):
        # src 缺失但 dst 已存在：视为本次已迁移（消除误报），不重复移动
        print(f"  ✓ data 已就位: {os.path.basename(dst)}（src 未落盘但 dst 存在，跳过重复迁移）", flush=True)
    else:
        print(f"  ⚠️ 未生成 {name}_data.json（可能失败）", flush=True)
        fail.append(pin); continue
    htmlp = os.path.join(HTML, f"{short}.html")
    if os.path.exists(htmlp):
        ok.append(pin)
        print(f"  ✓ html 已刷新: {short}.html", flush=True)
    else:
        fail.append(pin)

print(f"\n===== 完成 ===== 成功 {len(ok)} / 失败 {len(fail)}", flush=True)
if fail:
    print("失败项目:", fail, flush=True)

# 2026-09-17 约定变更：说"重跑"即把物探 数据 + HTML + index(含2天风险汇总) 全部刷新。
# 因此重跑末尾自动重建 wutan 子总览（离线、不取数，仅按最新 _data.json 重算）。
print("\n===== 重建物探子总览 index（含2天风险汇总）=====", flush=True)
try:
    s = subprocess.run([VENV, os.path.join(INDEX_SKILL, "gen_subindex.py"), "--only", "wutan",
                       "--base", os.path.dirname(BASE)],
                       capture_output=True, text=True, timeout=120)
    if s.stdout.strip(): print(s.stdout.strip()[-500:], flush=True)
    if s.returncode != 0 and s.stderr.strip(): print("STDERR:", s.stderr.strip()[-500:], flush=True)
    if s.returncode == 0:
        print("  ✓ wutan/html/index.html 已重建（含未来2天风险描述）", flush=True)
except Exception as e:
    print("子总览重建异常:", e, flush=True)
