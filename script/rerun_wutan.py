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
# 2026-10-19：几何(边界/测线/作业点)与 ta_id 统一来自 ta_map（KML 已整体废弃）。
# 固定注入绝对路径，使脚本在任意 CWD 下都能定位 ta_map（否则按 cwd 找不到即静默失败）。
TA_MAP = os.path.join(KML, "wutan_ta_map.json")

# (中文名, 拼音pin) —— 几何/作业点/ta_id 全部在 wutan/kml/wutan_ta_map.json 中按「中文名」检索
projs = [
    ("通江三维", "tongjiang-sanwei-gongqu"),
    ("南郑三维", "nanzhengsanwei-gongqu"),
    ("藏北天山", "cangbeitianshan-cesian"),
    ("资阳三维", "ziyang-sanwei-gongqu"),
    ("华亭静宁二维", "huatingjingan-gongqu"),
    ("宁蒗-万马场二维", "ninglangwanmachang-gongqu"),
    ("藏北高原冻土二维", "cangbeigaoyuandongtu-cexian"),
    ("准中2027二维", "zhunzhong2027erwei-cexian"),
    ("云南大关", "daguan-xiangmu-gongqu-cexian"),
    ("煤层气勘查三维", "meicengqikanchasanwei-gongqu"),
]

if not os.path.exists(TA_MAP):
    print(f"⚠️ 未找到 ta_map: {TA_MAP}（几何/ta_id 来源缺失，将全部失败）", flush=True)

env = dict(os.environ)
env["WUTAN_TA_MAP"] = TA_MAP

ok, fail = [], []
for name, pin in projs:
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
        "--grid", "20",
        "--outdir", HTML,
        "--outfile", f"{short}.html",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300, env=env)
    except subprocess.TimeoutExpired:
        print("  ❌ 超时", flush=True); fail.append(pin); continue
    if r.stdout.strip():
        print("STDOUT:", r.stdout.strip()[-600:], flush=True)
    if r.returncode != 0:
        # 2026-10-18 修复：退出码非 0 = 硬失败，绝不再用磁盘上残留的旧 html/data 冒充成功
        if r.stderr.strip():
            print("STDERR:", r.stderr.strip()[-800:], flush=True)
        print(f"  ❌ build_dashboard 失败（returncode={r.returncode}）", flush=True)
        fail.append(pin); continue
    # 中文名 _data.json -> 拼音 data/
    src = os.path.join(HTML, f"{name}_data.json")
    dst = os.path.join(DATA, f"{pin}_data.json")
    if os.path.exists(src):
        shutil.move(src, dst)
        print(f"  ✓ moved data -> {os.path.basename(dst)}", flush=True)
    elif os.path.exists(dst):
        print(f"  ✓ data 已就位: {os.path.basename(dst)}", flush=True)
    else:
        print(f"  ⚠️ 未生成 {name}_data.json（returncode=0 但无数据，判失败）", flush=True)
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
                       capture_output=True, text=True, timeout=120, env=env)
    if s.stdout.strip(): print(s.stdout.strip()[-500:], flush=True)
    if s.returncode != 0 and s.stderr.strip(): print("STDERR:", s.stderr.strip()[-500:], flush=True)
    if s.returncode == 0:
        print("  ✓ wutan/html/index.html 已重建（含未来2天风险描述）", flush=True)
except Exception as e:
    print("子总览重建异常:", e, flush=True)
