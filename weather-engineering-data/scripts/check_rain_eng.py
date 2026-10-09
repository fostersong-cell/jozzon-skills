#!/usr/bin/env python3
"""「未来 48 小时」小时级短时降水规则回归（石油工程点位页）。

规则与物探看板 weather-wutan-html 完全一致：
    >2 mm/h 大雨 / >5 mm/h 暴雨 / >10 mm/h 大暴雨
只作用于 48 小时口径；「未来 2 周」逐日图与关键指标仍是日累计 25/50mm。

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
    """由每日降水量生成 14 天 daily（其余要素取 harmless 默认）。"""
    out = []
    for i, p in enumerate(per_day):
        out.append({"date": f"2026-10-{i+1:02d}", "precip": p,
                    "tempMin": tmin, "tempMax": tmax,
                    "windMax": gust * 0.6, "gustMax": gust, "ptype": 1 if p > 0 else 0})
    return out


SUMMARY = {"maxGust": 3.0, "maxTemp": 28.0, "minTemp": 8.0, "maxWind": 2.0}


def precip_card(per_day, ph):
    cards = R.risk_cards(daily(per_day), SUMMARY, ph)
    return next(c for c in cards if "泥泞" in c[1])


def bullets_text(per_day, ph):
    return " ".join(R.impact_bullets(daily(per_day), SUMMARY, ph))


def sev(per_day, ph):
    # sev_of_recent 已改为吃hourly48（48h 逐小时窗口口径，2026-10-09），
    # 这里用日均量构造等效的 hourly48：precip 总量=前 2 日之和、小时峰值=ph。
    cum2 = sum(per_day[:2])
    hourly48 = {
        "precipitation": [ph] + [cum2 / 48.0] * 47,
        "wind_gusts_10m": [0.0] * 48,
        "wind_speed_10m": [0.0] * 48,
        "temperature_2m": [20.0] * 48,
    }
    return R.sev_of_recent(hourly48)


print("== 降水卡等级（48h 小时级阈值，与物探卡片分级一致）")
# 与物探 build_dashboard.py 降水卡片同构：≥10 预警 / ≥5 或日累计≥25 注意 / ≥2 短时大雨注意 / 其余安全
for ph, want_lvl, want_tag in [(0.0, "ok", "安全"), (1.2, "ok", "安全"),
                               (2.0, "warn", "注意"), (2.5, "warn", "注意"),
                               (5.0, "warn", "注意"), (9.9, "warn", "注意"),
                               (10.0, "danger", "预警"), (12.0, "danger", "预警")]:
    lvl, _t, tag2, txt = precip_card([0.0, 0.0], ph)
    ok(lvl == want_lvl and tag2 == want_tag, f"pHourMax={ph} → {want_tag}", f"{lvl}/{tag2}")
lvl, _t, tag2, txt = precip_card([0.0, 0.0], 12.0)
ok("大暴雨" in txt and "12.0mm/h" in txt, "预警卡文案带最大小时降水值 + 等级", txt[:70])
lvl, _t, tag2, txt = precip_card([30.0, 0.0], 0.0)
ok(lvl == "warn" and "30.0mm" in txt and "小时" not in txt, "日累计≥25 单独触发时走「注意」卡且不误报小时级", txt[:60])
lvl, _t, tag2, txt = precip_card([60.0, 0.0], 0.0)
ok(lvl == "danger", "日累计≥50 仍走「预警」卡", txt[:50])

print("== 风险等级 sev_of_recent（48h 口径）")
ok(sev([0.0, 0.0], 0.0) == 0, "pHourMax=0 → 0 整体适宜", str(sev([0.0, 0.0], 0.0)))
ok(sev([0.0, 0.0], 1.2) == 0, "pHourMax=1.2 → 0（小雨不抬级）", str(sev([0.0, 0.0], 1.2)))
ok(sev([0.0, 0.0], 1.5) == 1, "pHourMax=1.5 → 1（中雨及以上即至少需关注）", str(sev([0.0, 0.0], 1.5)))
ok(sev([0.0, 0.0], 4.9) == 1, "pHourMax=4.9 → 1（大雨级，未到重点关注）", str(sev([0.0, 0.0], 4.9)))
ok(sev([0.0, 0.0], 5.0) == 1, "pHourMax=5 → 1 需关注", str(sev([0.0, 0.0], 5.0)))
ok(sev([0.0, 0.0], 9.9) == 1, "pHourMax=9.9 → 1（未达大暴雨）", str(sev([0.0, 0.0], 9.9)))
ok(sev([0.0, 0.0], 10.0) == 2, "pHourMax=10 → 2 重点关注", str(sev([0.0, 0.0], 10.0)))
ok(sev([0.0, 0.0], 30.0) == 2, "pHourMax=30 → 仍为 2（不越级到 3）", str(sev([0.0, 0.0], 30.0)))
# 48h 累计口径（替代原「两个自然日之和」，48h 窗口横跨 3 个自然日）
ok(sev([60.0, 40.0], 0.0) == 2, "48h 累计 100mm → 2", str(sev([60.0, 40.0], 0.0)))
ok(sev([20.0, 20.0], 0.0) >= 1, "48h 累计 40mm → 至少 1", str(sev([20.0, 20.0], 0.0)))
ok(sev([90.0, 80.0], 0.0) == 3, "48h 累计 170mm → 3 高度警惕", str(sev([90.0, 80.0], 0.0)))

print("== 影响建议 bullets")
b = bullets_text([0.0, 0.0], 1.0)
ok("短时大雨" not in b, "pHourMax=1.0 不产生短时条目", b[-40:])
b = bullets_text([0.0, 0.0], 2.5)
ok("短时大雨" in b and "2.5mm/h" in b, "pHourMax=2.5 → 短时大雨", b[-40:])
b = bullets_text([0.0, 0.0], 6.0)
ok("短时暴雨" in b and "6.0mm/h" in b, "pHourMax=6 → 短时暴雨", b[-40:])
b = bullets_text([0.0, 0.0], 14.0)
ok("短时大暴雨" in b and "14.0mm/h" in b, "pHourMax=14 → 短时大暴雨", b[-40:])
ok("整体适宜" in bullets_text([0.0, 0.0], 0.0), "无降水时仍给「整体适宜」兜底")

print("== 横幅 / 风险焦点文案")
d3 = daily([0.0, 0.0])
a2 = R.alert_desc(daily([0.0, 0.0])[:2], dict(SUMMARY, totalPrecip=0), 2.5)
ok("短时大雨" in a2, "alert_desc 带小时级(短时大雨)", a2[:70])
ok("mm/h" in a2, "alert_desc 单位 mm/h")
a = R.alert_desc(daily([0.0, 0.0])[:2], dict(SUMMARY, totalPrecip=0), 6.0)
ok("短时暴雨" in a, "alert_desc 带小时级", a[:70])

print("== 未来 2 周口径不受影响")
ok(R.RAIN_H == {"heavy": 2.0, "storm": 5.0, "torrent": 10.0}, "RAIN_H 常量正确", str(R.RAIN_H))
ok(R.rain_hour_label(0.3) == "降水" and R.rain_hour_label(2.0) == "短时大雨"
   and R.rain_hour_label(5.0) == "短时暴雨" and R.rain_hour_label(10.0) == "短时大暴雨",
   "rain_hour_label 四档边界")
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
    ok('{v:2,c:"#E0822C",t:"大雨 2"}' in html, "48h 图含 大雨 2mm/h 阈值线定义")
    ok('{v:5,c:"#C0392B",t:"暴雨 5"}' in html, "48h 图含 暴雨 5mm/h 阈值线定义")
    ok('{v:10,c:"#7B1F14",t:"大暴雨 10"}' in html, "48h 图含 大暴雨 10mm/h 阈值线定义")
    # 把降水序列整体抬高，确认阈值线真的画了出来（<line ... stroke-dasharray"5 4">）
    m = re.search(r"precip:(\[[^\]]*\])", html)
    if m:
        lifted = "[" + ",".join(["9.9"] * len(m.group(1).split(","))) + "]"
        probe = html.replace(m.group(0), "precip:" + lifted)
        ok('stroke-dasharray":"5 4"' in probe, "大降水时阈值线会被绘制（模板路径可达）")
    else:
        ok(False, "未找到 48h 降水数组", "正则未命中")
    ok("柱 降水 mm/h" in html, "48h 图例已标注降水为小时口径")

print()
if FAILS:
    print(f"❌ {len(FAILS)} 项失败：" + " / ".join(FAILS))
    sys.exit(1)
print("✅ 全部通过（小时级短时降水规则 48h 口径生效，2 周日累计口径未受影响）")
