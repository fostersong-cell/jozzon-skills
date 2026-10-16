#!/usr/bin/env python3
"""「未来 48 小时」小时级短时降水规则回归（石油工程点位页）。

规则与物探看板 weather-wutan-html 完全一致，阈值真源是 weather-common/scripts/jozzonwx.py：
    >3 mm/h 短时大雨 / >6 mm/h 短时暴雨 / >15 mm/h 短时大暴雨
只作用于 48 小时口径；「未来 2 周」逐日图与关键指标仍是日累计 25/50mm。

⚠️ 2026-10-16 修订：旧版沿用 >2/>5/>10 三档与 `daily[].precip` 键、`recent_desc()` 函数，
    均已随七要素改造下线（现为 3/6/15 三档、`daily[].rainfall`、`_near_summary()`），
    不修会整片误报（此前已实际发生）。改阈值只需改 jozzonwx，本脚本第一组断言会强制对齐。

用法：
    <python> scripts/check_rain_eng.py
    <python> scripts/check_rain_eng.py --render <某个点位看板.html>   # 顺带跑页面级检查

退出码非 0 表示有断言失败。
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import render_points_html as R  # noqa: E402

FAILS = []


def ok(cond, name, detail=""):
    print(("  ✅ " if cond else "  ❌ ") + name + (f"　— {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def daily(per_day, gust=3.0, tmax=28.0, tmin=8.0):
    """由每日降水量生成 14 天 daily（其余要素取 harmless 默认）。

    ⚠️ 键名须与 build_points_data.py 现行 schema 一致：`rainfall`（= rain+showers），
    不是 Open-Meteo 时代的 `precip`（2026-10-16 改；渲染侧读 d["rainfall"]）。
    """
    out = []
    for i, p in enumerate(per_day):
        out.append({"date": f"2026-10-{i+1:02d}", "rainfall": p, "snowfall": 0.0,
                    "tempMin": tmin, "tempMax": tmax,
                    "apparentMin": tmin - 2.0, "apparentMax": tmax + 2.0, "visMin": None,
                    "windMax": gust * 0.6, "gustMax": gust, "ptype": 1 if p > 0 else 0})
    return out


SUMMARY = {"maxGust": 3.0, "maxTemp": 28.0, "minTemp": 8.0, "maxWind": 2.0}


def precip_card(per_day, ph):
    cards = R.risk_cards(daily(per_day), SUMMARY, ph)
    return next(c for c in cards if "泥泞" in c[1])


def bullets_text(per_day, ph):
    return " ".join(R.impact_bullets(daily(per_day), SUMMARY, ph))


def sev(per_day, ph):
    return R.sev_of_recent(daily(per_day)[:2], ph)


print("== 阈值真源一致性（分级集中在 jozzonwx，禁止在渲染侧另立一套）")
ok(R.RAIN_H == R.JW.RAIN_H == {"heavy": 3.0, "storm": 6.0, "torrent": 15.0},
   "RAIN_H 三档 = 3/6/15 且与 jozzonwx 同源", str(R.RAIN_H))
ok(R.rain_hour_label(2.9) == "降水" and R.rain_hour_label(3.0) == "短时大雨"
   and R.rain_hour_label(6.0) == "短时暴雨" and R.rain_hour_label(15.0) == "短时大暴雨",
   "rain_hour_label 四档边界（3/6/15）")

print("== 降雪口径（jozzon-mcp 已返回 mm/h，禁止 ×10 换算）")
# 2026-10-16 修：旧版遗留 ×10（Open-Meteo 时代降雪是 cm），会把 0.2mm/h 放大成 2.0 → 假暴雪。
ok(R.snow_hour_max_48({"snowfall": [0.5] * 48}) == 0.5,
   "snow_hour_max_48 不做 ×10（0.5mm/h 仍是 0.5，非 5.0）",
   str(R.snow_hour_max_48({"snowfall": [0.5] * 48})))
ok(R.snow_hour_max_48({"snowfall": [0.0] * 48}) == 0.0, "无雪 → 0.0")
ok(R.snow_hour_max_48({}) is None, "无 snowfall 字段 → None（不误报）")

print("== 降水卡等级（48h 小时级阈值，与物探卡片同构）")
# 与物探 build_dashboard.py 降水卡片同构：≥15 大暴雨预警 / ≥6 暴雨注意 / ≥3 短时大雨注意 / 日累计≥50 预警、≥25 注意
for ph, want_lvl, want_tag in [(0.0, "ok", "安全"), (1.2, "ok", "安全"),
                               (2.0, "ok", "安全"), (2.9, "ok", "安全"),
                               (3.0, "warn", "注意"), (5.0, "warn", "注意"),
                               (6.0, "warn", "注意"), (9.9, "warn", "注意"),
                               (12.0, "warn", "注意"), (14.9, "warn", "注意"),
                               (15.0, "danger", "预警"), (20.0, "danger", "预警")]:
    lvl, _t, tag2, txt = precip_card([0.0, 0.0], ph)
    ok(lvl == want_lvl and tag2 == want_tag, f"pHourMax={ph} → {want_tag}", f"{lvl}/{tag2}")
lvl, _t, tag2, txt = precip_card([0.0, 0.0], 15.0)
ok("大暴雨" in txt and "15.0mm/h" in txt, "预警卡文案带最大小时降水值 + 等级", txt[:80])
lvl, _t, tag2, txt = precip_card([30.0, 0.0], 0.0)
ok(lvl == "warn" and "30.0mm" in txt and "小时" not in txt, "日累计≥25 单独触发时走「注意」卡且不误报小时级", txt[:60])
lvl, _t, tag2, txt = precip_card([60.0, 0.0], 0.0)
ok(lvl == "danger", "日累计≥50 仍走「预警」卡", txt[:50])

print("== 风险等级 sev_of_recent（48h 口径，与 jozzonwx._LV2SEV['rain'] 同源）")
ok(sev([0.0, 0.0], 0.0) == 0, "pHourMax=0 → 0 整体适宜", str(sev([0.0, 0.0], 0.0)))
ok(sev([0.0, 0.0], 0.2) == 0, "pHourMax=0.2（小雨）→ 0", str(sev([0.0, 0.0], 0.2)))
ok(sev([0.0, 0.0], 1.5) == 1, "pHourMax=1.5（中雨）→ 1 需关注", str(sev([0.0, 0.0], 1.5)))
ok(sev([0.0, 0.0], 2.9) == 1, "pHourMax=2.9 → 1", str(sev([0.0, 0.0], 2.9)))
ok(sev([0.0, 0.0], 5.9) == 1, "pHourMax=5.9（大雨）→ 1", str(sev([0.0, 0.0], 5.9)))
ok(sev([0.0, 0.0], 6.0) == 2, "pHourMax=6.0（暴雨）→ 2 重点关注", str(sev([0.0, 0.0], 6.0)))
ok(sev([0.0, 0.0], 14.9) == 2, "pHourMax=14.9 → 2", str(sev([0.0, 0.0], 14.9)))
ok(sev([0.0, 0.0], 15.0) == 3, "pHourMax=15.0（大暴雨）→ 3 高度警惕", str(sev([0.0, 0.0], 15.0)))
ok(sev([0.0, 0.0], 30.0) == 3, "pHourMax=30 → 3 封顶", str(sev([0.0, 0.0], 30.0)))
# 原日累计判据不被破坏
ok(sev([60.0, 40.0], 0.0) == 2, "日累计 60mm（旧判据）→ 2", str(sev([60.0, 40.0], 0.0)))
ok(sev([0.0, 0.0], 0.0) == 0 and sev([20.0, 20.0], 0.0) >= 1,
   "旧日累计 12mm 判据仍在", str(sev([20.0, 20.0], 0.0)))

print("== 影响建议 bullets")
b = bullets_text([0.0, 0.0], 1.2)
ok("短时大雨" not in b and "短时暴雨" not in b, "pHourMax=1.2 不产生短时条目", b[-30:])
b = bullets_text([0.0, 0.0], 3.0)
ok("短时大雨" in b and "3.0mm/h" in b, "pHourMax=3.0 → 短时大雨", b[-40:])
b = bullets_text([0.0, 0.0], 6.0)
ok("短时暴雨" in b and "6.0mm/h" in b, "pHourMax=6.0 → 短时暴雨", b[-40:])
b = bullets_text([0.0, 0.0], 15.0)
ok("短时大暴雨" in b and "15.0mm/h" in b, "pHourMax=15.0 → 短时大暴雨", b[-40:])
ok("整体适宜" in bullets_text([0.0, 0.0], 0.0), "无降水时仍给「整体适宜」兜底")

print("== 横幅 / 风险焦点文案")
ns = R._near_summary(daily([0.0, 0.0])[:2], 6.0)
ok(ns["pHourMax"] == 6.0 and ns["totalPrecip"] == 0,
   "_near_summary 沿用 48h 小时级峰值（取代已下线的 recent_desc）", str(ns["pHourMax"]))
a = R.alert_desc(daily([0.0, 0.0])[:2], dict(SUMMARY, totalPrecip=0), 6.0)
ok("短时暴雨" in a, "alert_desc 带小时级", a[:70])

print("== 未来 2 周口径不受影响")
far = R.far_alert(daily([0.0] * 12))       # 全 0 也不该误报
ok(far is None, "far_alert 远端口径未被改动")
far2 = R.far_alert(daily([0.0, 0, 60] + [0.0] * 10))
ok(far2 and "暴雨" in far2, "far_alert 日累计≥50mm 仍报暴雨", str(far2))

# ---------- 页面级：注入不同 pHourMax，看 48h 图阈值线与读数框 ----------
if "--render" in sys.argv:
    path = sys.argv[sys.argv.index("--render") + 1]
    print(f"== 页面级检查：{os.path.basename(path)}")
    html = open(path, encoding="utf-8").read()
    ok("mm/h" in html, "48h 读数框 / legend 已用 mm/h 口径")
    ok('{v:3,c:"#E0822C",t:"大雨 3"}' in html, "48h 图含 大雨 3mm/h 阈值线定义")
    ok('{v:6,c:"#C0392B",t:"暴雨 6"}' in html, "48h 图含 暴雨 6mm/h 阈值线定义")
    ok('{v:15,c:"#7B1F14",t:"大暴雨 15"}' in html, "48h 图含 大暴雨 15mm/h 阈值线定义")
    # 48h 载荷键必须是 rainfall；写成 precip 会让 JS 的 CH.rainfall 变 undefined → 整图空白（2026-10-16 修）
    ok("rainfall:" in html and "precip:" not in html,
       "48h 载荷键为 rainfall（非 precip，否则整块空白）")
    # 48h 不再含能见度（2026-10-16 用户定）
    ok("vis:" not in html, "48h 载荷已移除能见度（vis:）")
    # 把降水序列整体抬高，确认阈值线真的画了出来（<line ... stroke-dasharray"5 4">）
    m = re.search(r"rainfall:(\[[^\]]*\])", html)
    if m:
        lifted = "[" + ",".join(["20.0"] * len(m.group(1).split(","))) + "]"
        probe = html.replace(m.group(0), "rainfall:" + lifted)
        ok('stroke-dasharray":"5 4"' in probe, "大降水时阈值线会被绘制（模板路径可达）")
    else:
        ok(False, "未找到 48h 降水数组", "正则未命中")
    ok("柱 降水 mm/h" in html, "48h 图例已标注降水为小时口径")

print()
if FAILS:
    print(f"❌ {len(FAILS)} 项失败：" + " / ".join(FAILS))
    sys.exit(1)
print("✅ 全部通过（小时级短时降水 3/6/15 三档 48h 口径生效，2 周日累计口径未受影响）")
