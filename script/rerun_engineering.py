import subprocess, os

# 本脚本位于 <技能根>/script/，故父目录两级即技能根（与安装位置无关，便于拷贝移植）
SKILLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENV = os.path.expanduser("~/.workbuddy/binaries/python/envs/default/bin/python")
BASE = os.environ.get("BEIDOU", "/Users/zhijunsong/Desktop/同步空间/jozzon/1.个人资料/AI/work/beidou")

# 唯一数据源：all_points_info.md（2026-09-17 起不再使用任何 KML，如 all-wells-points.kml）
MD = os.path.join(BASE, "engineering", "kml", "all_points_info.md")

# 技能脚本（2026-09-17 起：窗口改为未来 2 周 / 14 天，index 生成已拆出为独立技能）
DATA_SKILL = os.path.join(SKILLS, "weather-engineering-data", "scripts", "build_points_data.py")
RENDER_SKILL = os.path.join(SKILLS, "weather-engineering-data", "scripts", "render_points_html.py")
INDEX_SKILL = os.path.join(SKILLS, "weather-engineering-index", "scripts", "build_points_index.py")
SUMMARY_SKILL = os.path.join(SKILLS, "weather-engineering-index", "scripts", "gen_points_summary.py")

DATA = os.path.join(BASE, "engineering", "data")
HTML = os.path.join(BASE, "engineering", "html")
SUMMARY_OUT = os.path.join(BASE, "engineering", "script", "fengxian_2tian_huizong.md")

DAYS = "14"  # 未来 2 周

print("===== 石油工程：从 all_points_info.md 取数(未来2周) + 渲染点位页 + 生成 index + 未来2天风险汇总（不使用 KML）=====", flush=True)


def run(tag, cmd, timeout, fatal=True):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    print(r.stdout.strip()[-1500:], flush=True)
    if r.returncode != 0:
        print("STDERR:", r.stderr.strip()[-800:], flush=True)
        if fatal:
            print(f"❌ 石油工程{tag}失败")
            raise SystemExit(1)
        print(f"⚠️ {tag}失败（不影响已产出的数据与 HTML）")
        return False
    print(f"✅ {tag}完成")
    return True


# 1) 取数：解析 md 中 17 个管线/平台点位，向 Open-Meteo 取逐小时预报
#    （默认从明天 0 时起，未来 2 周 / 14 天窗口）
run("取数", [VENV, DATA_SKILL, "--md", MD, "--datadir", DATA, "--days", DAYS], timeout=540)

# 2) 渲染：17 点位 HTML（不再顺带生成 index）
run("渲染点位页", [VENV, RENDER_SKILL, "--datadir", DATA, "--htmldir", HTML], timeout=300)

# 3) 生成目录总览 index.html（独立技能 weather-engineering-index，零取数）
run("生成 index", [VENV, INDEX_SKILL, "--datadir", DATA, "--htmldir", HTML], timeout=180)

# 4) 未来 2 天（48 小时）风险叙事汇总（面向领导/客户的 Markdown 文本）
run("未来2天风险汇总",
    [VENV, SUMMARY_SKILL, "--datadir", DATA, "--out", SUMMARY_OUT],
    timeout=120, fatal=False)

print("✅ 石油工程：17 点位【数据(未来2周) + 点位页 + index(含未来2天风险) + 未来2天风险汇总】"
      "已从 all_points_info.md 重跑完成（全程未使用 KML）")
