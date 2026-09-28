#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""物探项目2周天气看板 · 多项目总览页（index.html）生成器。

从 beidou/{wutan,engineering}/data 下全部 *_data.json 合并生成总览 index.html：
按风险等级降序排列项目卡片，顶部含等级统计行与「未来 2 天（48小时）风险」聚焦描述。
卡片风险评级（高度警惕/重点关注/需关注/整体适宜）与焦点描述均按「未来 48 小时（近 2 天）」口径
（meta.sevNear / peaksNear），与看板 t1「重点提示」横幅保持一致；NEAR_DAYS=2，
超出该窗口的远预报仅以「临近时再提示」一句话点出，不作主风险。
"""

import json, os, glob, argparse

# 项目根目录（其下含 beidou/{wutan,engineering}/{data,html}）。
# 可用 --base 覆盖，使本脚本可复用于其它工作区，而非硬编码单一项目路径。
DEFAULT_BASE = "<WORK>"
BASE = DEFAULT_BASE
BEIDOU = os.path.join(BASE, "beidou")
DATA_WT = os.path.join(BEIDOU, "wutan", "data")
DATA_ZJ = os.path.join(BEIDOU, "engineering", "data")

SEV_COLOR = {3: "#C0392B", 2: "#E0822C", 1: "#E0A92C", 0: "#2E8B57"}
SEV_LABEL = {3: "高度警惕", 2: "重点关注", 1: "需关注", 0: "整体适宜"}
SEV_ORDER = (3, 2, 1, 0)
def short_pin(pin):
    """子目录短名：去掉工区/测线后缀（-gongqu / -cexian / -cesian），如
    tongjiang-sanwei-gongqu -> tongjiang-sanwei、cangbeitianshan-cesian -> cangbeitianshan。
    工程类数据文件名本无此后缀，原样返回。"""
    s = pin
    for suf in ("-gongqu", "-cexian", "-cesian"):
        if s.endswith(suf):
            return s[: -len(suf)]
    return s


NEAR_DAYS = 2  # 风险汇报聚焦近 2 天（48小时）；超出窗口的远预报不可靠，仅一句话"临近再提示"

def mmdd(s):
    return s[5:] if s else s

def _day_arrays(d):
    """逐日（全窗口）跨采集点聚合：降水、阵风、持续风、最低/最高气温。"""
    daily = d.get("daily", []) or []
    n = len(daily)
    P = [(x.get("p") or 0) for x in daily]
    Gd = [None] * n; Wd = [None] * n; TMd = [None] * n; TXd = [None] * n
    for p in d.get("points", []):
        s = p.get("series", {}) or {}
        gm = s.get("gustMax"); wm = s.get("windMax"); tm = s.get("tempMin"); tx = s.get("tempMax")
        if not gm:
            continue
        for i in range(min(n, len(gm))):
            if Gd[i] is None or gm[i] > Gd[i]: Gd[i] = gm[i]
            if Wd[i] is None or wm[i] > Wd[i]: Wd[i] = wm[i]
            if TMd[i] is None or tm[i] < TMd[i]: TMd[i] = tm[i]
            if TXd[i] is None or tx[i] > TXd[i]: TXd[i] = tx[i]
    return daily, P, Gd, Wd, TMd, TXd

def project_near(d, wd=NEAR_DAYS):
    """返回项目近 wd 天 + 全窗口极值及对应日序号（用于判断远预报是否超出窗口）。"""
    daily, P, Gd, Wd_, TMd, TXd = _day_arrays(d)
    n = len(daily)
    near_p = [x for x in P[:wd] if x is not None]
    near_g = [x for x in Gd[:wd] if x is not None]
    near_w = [x for x in Wd_[:wd] if x is not None]
    near_tm = [x for x in TMd[:wd] if x is not None]
    near_tx = [x for x in TXd[:wd] if x is not None]
    pmax_all = max(P) if P else 0
    pmax_all_i = P.index(pmax_all) if P else 0
    gmax_all = max((g for g in Gd if g is not None), default=0)
    gmax_all_i = Gd.index(gmax_all) if any(g is not None for g in Gd) else 0
    tmin_all = min((t for t in TMd if t is not None), default=99)
    tmin_all_i = TMd.index(tmin_all) if any(t is not None for t in TMd) else 0
    return {
        "n": n,
        "dates": [x.get("date", "") for x in daily],
        "psum": round(sum(near_p), 1) if near_p else 0,
        "pmax": max(near_p) if near_p else 0,
        "pmax_i": (P[:wd].index(max(P[:wd])) if near_p else 0),
        "gust": max(near_g) if near_g else 0,
        "wind": max(near_w) if near_w else 0,
        "tmin": min(near_tm) if near_tm else 99,
        "tmax": max(near_tx) if near_tx else -99,
        "pmax_all": pmax_all,
        "pmax_all_i": pmax_all_i,
        "gust_all": gmax_all,
        "gust_all_i": gmax_all_i,
        "tmin_all": tmin_all,
        "tmin_all_i": tmin_all_i,
    }

def build_near_term_desc(rows, wd=NEAR_DAYS):
    """生成「未来 2 天（48小时）风险」聚焦描述（仅基于 _data.json 前 wd 天，不取远预报为主风险）。"""
    valid = [r for r in rows if r.get("near") and r["near"]["n"] >= wd]
    if not valid:
        return ""
    ref = next((r for r in valid if r["near"]["dates"]), None)
    dates = ref["near"]["dates"] if ref else []
    start = dates[0][5:] if dates else "?"
    end = dates[wd - 1][5:] if len(dates) >= wd else (dates[-1][5:] if dates else "?")
    # 远预报极端（超出近 wd 天窗口的暴雨，仅一句话点出）
    far = []
    for r in valid:
        nr = r["near"]
        if nr["pmax_all_i"] >= wd and nr["pmax_all"] >= 50 and nr["dates"]:
            dstr = nr["dates"][nr["pmax_all_i"]][5:]
            far.append((nr["pmax_all"], f"{r['name']} {dstr} 单日{nr['pmax_all']:.0f}mm（暴雨）"))
    far.sort(reverse=True)
    far_txt = ""
    if far:
        ex = "、".join(t for _, t in far[:3])
        far_txt = f"周中后期极端暴雨（如 {ex}）已超出可靠预报范围，暂不纳入，临近时再提示。"
    # 近 wd 天内的高影响项目
    rain = [r for r in valid if r["near"]["pmax"] >= 25 and r["near"]["pmax_i"] < wd]
    cold = [r for r in valid if r["near"]["gust"] >= 17.2 or r["near"]["tmin"] <= 0]
    rain.sort(key=lambda r: -r["near"]["psum"])
    cold.sort(key=lambda r: -r["near"]["gust"])
    parts = ["整体以分散性降水为主"]
    if cold:
        cl = []
        for r in cold[:4]:
            nr = r["near"]; bits = []
            if nr["gust"] >= 17.2: bits.append(f"阵风 {nr['gust']:.1f}m/s")
            if nr["tmin"] <= 0: bits.append(f"最低 {nr['tmin']:.1f}℃")
            cl.append(f"{r['name']}（{'、'.join(bits)}）")
        parts.append("最需关注高原/高海拔测线大风低温——" + "、".join(cl) + "，做好防风保暖与设备加固")
    if rain:
        rl = []
        for r in rain[:4]:
            nr = r["near"]
            lvl = "暴雨" if nr["pmax"] >= 50 else "大雨"
            dstr = nr["dates"][nr["pmax_i"]][5:] if nr["dates"] else ""
            rl.append(f"{r['name']} {dstr} 单日{nr['pmax']:.1f}mm（{lvl}）")
        parts.append("、".join(rl) + " 等需防范山洪、泥水淹泡与进场道路中断")
    body = "；".join(parts) + "。"
    if far_txt:
        # 先说未来 2 天（近 wd 天）风险，周中后期（远预报）情况放后面，仅一句话点出。
        body = body + " " + far_txt
    return f'<span class="nt-h">未来 {wd} 天风险（{start} ~ {end}）</span>{body}'

def build_focus(d):
    # 焦点描述按「未来 48 小时（近 2 天）」口径，与前端 t1「重点提示」及风险评级保持一致；
    # 旧数据缺 peaksNear 时回退到全周期 peaks，避免中断。
    p = d.get("peaksNear") or d.get("peaks", {}) or {}
    items = []
    if p.get("focusTotal") and p.get("focusStart"):
        items.append(f"{mmdd(p['focusStart'])}~{mmdd(p['focusEnd'])} 连续降雨累计 {round(p['focusTotal'],1)}mm")
    if p.get("pMax") is not None and p.get("pMaxDay"):
        pm = p["pMax"]; lvl = "暴雨" if pm >= 50 else ("大雨" if pm >= 25 else None)
        if lvl:
            items.append(f"{mmdd(p['pMaxDay'])} 单日降水 {round(pm,1)}mm（{lvl}）")
    if p.get("tmax") is not None and p["tmax"] >= 35:
        items.append(f"最高气温 {round(p['tmax'],1)}°C（高温）")
    if p.get("tmin") is not None and p["tmin"] <= 0:
        items.append(f"最低气温 {round(p['tmin'],1)}°C（结冰/霜冻）")
    if p.get("gustMax") is not None and p["gustMax"] >= 17.2:
        items.append(f"最大阵风 {round(p['gustMax'],1)} m/s（≥8级）")
    if p.get("windMax") is not None and p["windMax"] >= 10.8:
        items.append(f"最大持续风 {round(p['windMax'],1)} m/s（≥6级）")
    if not items:
        return "本期未触发极端天气预警阈值，整体适宜作业"
    return "；".join(items[:3])

def load_rows(dd, group, badge):
    rows = []
    for f in sorted(glob.glob(os.path.join(dd, "*_data.json"))):
        d = json.load(open(f, encoding="utf-8"))
        m = d["meta"]
        pin = os.path.basename(f).replace("_data.json", "")
        is_line = bool(d.get("isLine"))
        short = short_pin(pin)
        # 风险评级（高度警惕/重点关注/需关注/整体适宜）按「未来 48 小时（近 2 天）」口径，
        # 与看板 t1「重点提示」横幅保持一致；旧数据缺 sevNear 时回退到全周期 sev，避免中断。
        sev = m.get("sevNear", m.get("sev"))
        rows.append({
            "pin": pin, "short": short, "name": m["name"], "sev": sev,
            "color": SEV_COLOR[sev], "label": SEV_LABEL[sev],
            "focus": build_focus(d),
            "kind": "测线" if is_line else "工区",
            "start": mmdd(m["start"]), "end": mmdd(m["end"]),
            "npts": m["npts"], "group": group, "badge": badge,
            "ndays": len(d.get("daily") or []),
            "near": project_near(d, NEAR_DAYS) if (d.get("daily") and d.get("points")) else None,
        })
    rows.sort(key=lambda r: (-r["sev"], r["name"]))
    return rows

def summary_line(label, n, rows):
    dist = {s: sum(1 for r in rows if r["sev"] == s) for s in SEV_ORDER}
    parts = [f'<span style="color:{SEV_COLOR[s]};font-weight:700">{SEV_LABEL[s]} {dist[s]}</span>'
             for s in SEV_ORDER if dist[s] > 0]
    return f'<b>{label}</b> {n} 个项目 ｜ ' + " · ".join(parts)

def card(r):
    # 子目录内链接走相对路径（仅文件名）
    return f'''        <a class="card" href="{r['short']}.html?from=index" style="--sev:{r['color']}">
          <span class="bar"></span>
          <div class="head"><span class="name">{r['name']}</span><span class="tag">{r['label']}</span><span class="ptype">{r['badge']}</span></div>
          <div class="focus">{r['focus']}</div>
          <div class="meta"><span>{r['kind']}</span><span>{r['start']} ~ {r['end']}</span><span>采样点 {r['npts']}</span></div>
          <span class="arrow">&rsaquo;</span>
        </a>'''

def page(title, sub_title, label, rows, out_path):
    # 空数据保护：换机器时某一类（如只有物探、没有石油工程）可能一个 *_data.json 都没有，
    # 此时不能崩，输出一张「暂无数据」空页即可（rows 为空会让 min()/max() 抛 ValueError）。
    if not rows:
        html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  :root{{--bg:#F6F4F0; --card:#FFFFFF; --line:#EAE6DF; --ink:#242A2E; --sub:#6B7378; --accent:#1F7A6B;}}
  body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 "PingFang SC","Microsoft YaHei",system-ui,sans-serif;}}
  .wrap{{max-width:1080px;margin:0 auto;padding:24px 16px;}}
  .empty{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:28px;text-align:center;color:var(--sub);}}
</style></head>
<body><div class="wrap"><h1>{title}</h1>
<div class="empty">暂无数据：未在 <code>{out_path}</code> 对应的 data 目录中找到 *_data.json。<br>
请先跑数据脚本生成看板数据。</div>
</div></body></html>'''
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(html)
        print(f"  · 空数据 → 已生成空页 {out_path}")
        return
    cards = "\n".join(card(r) for r in rows)
    summ = summary_line(label, len(rows), rows)
    near_desc = build_near_term_desc(rows, NEAR_DAYS)
    near_html = f'<div class="near-term">{near_desc}</div>' if near_desc else ""
    start = min(r["start"] for r in rows)
    end = max(r["end"] for r in rows)
    # 预报天数按实际数据跨度动态显示：2周=14天；若数据仍为 7 天则如实显示，避免错标成 2 周。
    ndays = max((r.get("ndays") or 0) for r in rows)
    span = f"未来 2 周（{ndays} 天）" if ndays >= 13 else (f"未来 {ndays} 天" if ndays else "未来 2 周")
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  :root{{
    --bg:#F6F4F0; --card:#FFFFFF; --line:#EAE6DF; --ink:#242A2E; --sub:#6B7378;
    --accent:#1F7A6B; --shadow:0 1px 3px rgba(0,0,0,.06),0 6px 16px rgba(0,0,0,.05);
  }}
  *{{box-sizing:border-box;-webkit-tap-highlight-color:transparent;}}
  html,body{{margin:0;padding:0;}}
  body{{
    font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
    background:var(--bg); color:var(--ink); line-height:1.5; font-size:15px;
    padding:22px 16px 48px;
  }}
  .wrap{{max-width:1080px;margin:0 auto;}}
  h1{{font-size:19px;margin:0 0 5px;font-weight:700;}}
  .sub{{font-size:13px;color:var(--sub);margin-bottom:6px;}}
  .summary{{font-size:13px;color:var(--ink);margin:16px 0 4px;display:flex;gap:10px;flex-wrap:wrap;align-items:center;}}
  .summary b{{font-weight:700;}}
  .near-term{{font-size:13px;line-height:1.55;color:var(--ink);background:rgba(31,122,107,.06);border-left:3px solid var(--accent);border-radius:8px;padding:10px 13px;margin:6px 0 2px;}}
  .near-term .nt-h{{font-weight:700;color:var(--accent);margin-right:6px;}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:12px;margin-top:8px;}}
  a.card{{
    display:block;text-decoration:none;color:inherit;background:var(--card);border:1px solid var(--line);
    border-radius:14px;padding:13px 38px 13px 14px;box-shadow:var(--shadow);position:relative;overflow:hidden;
    transition:transform .12s ease, box-shadow .12s ease;
  }}
  a.card:hover{{transform:translateY(-2px);box-shadow:0 4px 8px rgba(0,0,0,.08),0 12px 24px rgba(0,0,0,.08);}}
  a.card .bar{{position:absolute;left:0;top:0;bottom:0;width:5px;background:var(--sev);}}
  a.card .head{{display:flex;align-items:center;gap:8px;}}
  a.card .name{{font-size:16px;font-weight:700;}}
  a.card .tag{{font-size:10.5px;font-weight:600;color:#fff;background:var(--sev);border-radius:20px;padding:2px 8px;white-space:nowrap;}}
  a.card .ptype{{font-size:10px;font-weight:600;border-radius:6px;padding:2px 6px;white-space:nowrap;background:rgba(31,122,107,.12);color:var(--accent);}}
  a.card .focus{{font-size:12.5px;margin-top:8px;color:var(--ink);line-height:1.45;}}
  a.card .meta{{font-size:11.5px;color:var(--sub);margin-top:9px;display:flex;gap:9px;flex-wrap:wrap;}}
  a.card .arrow{{position:absolute;right:13px;top:50%;transform:translateY(-50%);color:var(--sub);font-size:19px;font-weight:600;}}
  .legend{{margin-top:28px;font-size:12px;color:var(--sub);display:flex;gap:14px;flex-wrap:wrap;}}
  .legend i{{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px;vertical-align:-1px;}}
  .extlink{{display:inline-flex;align-items:center;gap:4px;font-size:13px;font-weight:700;color:#fff;background:var(--accent);padding:7px 14px;border-radius:20px;text-decoration:none;box-shadow:0 2px 6px rgba(31,122,107,.3);}}
  .extlink:hover{{background:#176254;transform:translateY(-1px);}}
</style>
</head>
<body>
<div class="wrap">
  <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:6px"><h1 style="margin:0">{title}</h1><a class="extlink" href="https://leidian.wang" target="_blank" rel="noopener">北斗天气风险治理平台 ↗</a></div>
  <div class="sub">{span}（{start} ~ {end}）· 点击卡片进入对应项目看板</div>
  <div class="summary">{summ}</div>
  {near_html}
  <div class="grid">
{cards}
  </div>
  <div class="legend">
    <span><i style="background:#C0392B"></i>高度警惕</span>
    <span><i style="background:#E0822C"></i>重点关注</span>
    <span><i style="background:#E0A92C"></i>需关注</span>
    <span><i style="background:#2E8B57"></i>整体适宜</span>
  </div>
</div>
</body>
</html>
'''
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    print("generated:", out_path, "| rows:", len(rows))

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="物探项目2周天气看板 · 多项目总览页（index.html）生成器")
    ap.add_argument("--base", default=DEFAULT_BASE,
                    help="项目根目录（其下含 beidou/{wutan,engineering}/data），默认当前工作区")
    ap.add_argument("--only", choices=["wutan", "engineering"], default=None,
                    help="只重建指定分类的子总览（默认两者都重建）")
    args = ap.parse_args()

    BASE = args.base
    BEIDOU = os.path.join(BASE, "beidou")
    DATA_WT = os.path.join(BEIDOU, "wutan", "data")
    DATA_ZJ = os.path.join(BEIDOU, "engineering", "data")

    wt = load_rows(DATA_WT, "物探", "物探")
    zj = load_rows(DATA_ZJ, "石油工程", "石油工程")

    if args.only in (None, "wutan"):
        page(
            title="中石化北斗运营中心 · 物探项目天气看板",
            sub_title=f"物探 {len(wt)} 个项目",
            label="物探",
            rows=wt,
            out_path=os.path.join(BEIDOU, "wutan", "html", "index.html"),
        )
    if args.only in (None, "engineering"):
        page(
            title="中石化北斗运营中心 · 石油工程项目天气看板",
            sub_title=f"石油工程 {len(zj)} 个项目",
            label="石油工程",
            rows=zj,
            out_path=os.path.join(BEIDOU, "engineering", "html", "index.html"),
        )
