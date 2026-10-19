---
name: weather-engineering-index
description: 石油工程（钻井/管线点位）天气看板「未来 2 周」index.html 生成器。从 weather-engineering-data / weather-engineering-html 两个技能中拆分出来，专门负责生成目录总览 index：① 点位目录总览 index.html（分组卡片 + 风险等级分布 + 未来 2 天风险短描述）；② 井位地图 index.html（所有井位点标在同一张地形图上，按风险配色）；③ 面向领导/客户的「未来 2 天风险」Markdown 汇总。输入为 engineering/data/*.json（取数窗口为下一日 0 时起未来 2 周 / 14 天），输出 index.html 与 fengxian_2tian_huizong.md。当用户要「重建/刷新石油工程 index」「生成点位总览」「重跑后刷新目录页」「生成未来 2 天风险汇总」时使用本技能；点位数据采集与单个点位看板渲染请使用 weather-engineering-data，井位（well）看板请使用 weather-engineering-html。
---

## 环境占位符（跨平台 · 首次使用请先确认）

本技能文档中的 `<WORK>` `<SKILLS>` `<BEIDOU>` `<PY>` `<NODE>` `<NODE_MODULES>` `<TMP>` 均为**运行时占位符**，须替换为本机的实际值。文档中不再出现任何某一台机器的固定路径，macOS 与 Windows 通用：

| 占位符 | 含义 | macOS 典型值 | Windows 典型值 |
|---|---|---|---|
| `<WORK>` | 工作区根（其下含 `beidou/`） | `~/Desktop/.../AI/work` | `C:\...\AI\work` |
| `<SKILLS>` | 技能根（本技能所在目录，用户级） | `~/.workbuddy/skills/jozzon/weather-engineering-index` | `%USERPROFILE%\.workbuddy\skills\jozzon\weather-engineering-index` |
| `<BEIDOU>` | 看板根 | `<WORK>/beidou` | 同左 |
| `<PY>` | Python 3 解释器 | 托管 venv `.../bin/python`，或系统 `python3` | 托管 venv `...\Scripts\python.exe`，或 `python` |
| `<NODE>` | Node.js 解释器 | `node` | `node.exe` |
| `<NODE_MODULES>` | Node 模块目录（跑 jsdom 回归脚本用） | `.../node/workspace/node_modules` | 同上（本机任选一个模块目录） |
| `<TMP>` | 系统临时目录 | `/tmp` | `%TEMP%` |

**新机器上先做这 3 步**（否则命令会跑错路径）：
1. 确认 `<WORK>`：其下必须同时存在 `beidou/wutan/data` 与 `beidou/engineering/data`。
2. 确认 `<PY>`：`python3 --version`（Windows 用 `python --version`）；若缺依赖（`requests` 等），先建 venv 并安装。
3. 确认 `<NODE>` 与 `<NODE_MODULES>`：需跑 jsdom 回归脚本时，把 `jsdom` 装进 `<NODE_MODULES>`，并设 `NODE_PATH=<NODE_MODULES>`。

下文命令行体例为 bash（macOS / Linux）；**Windows 等价写法见文末《跨平台执行对照》**。

# 石油工程天气看板 · 「未来 2 周」index 生成器（拆分自 data 技能）

> 本技能**只做一件事：生成 index**。原先 index 由 `weather-engineering-data` 的
> `render_points_html.py` 在渲染点位看板时顺带产出，现已拆出为独立技能，
> 便于「只重建目录页、不重跑数据、不重渲染点位页」。

## 何时用哪个技能

| 需求 | 用哪个技能 |
|---|---|
| 采集/刷新点位天气数据（按 `ta_id` 调 jozzon-mcp 取数，未来 2 周） | `weather-engineering-data` |
| 渲染单个点位的天气看板 HTML | `weather-engineering-data` |
| **生成/重建点位目录总览 index.html（point）** | **本技能 `weather-engineering-index`**（`build_points_index.py`） |
| **生成井位地图 index.html（well）** | **本技能 `weather-engineering-index`**（`build_wells_index.py`） |
| **生成「未来 2 天风险」Markdown 汇总** | **本技能 `weather-engineering-index`** |
| 井位（well）看板 HTML | `weather-engineering-html` |

## 目录与数据流

```
engineering/kml/engineering_ta_map.json ← 唯一数据源（一级/二级/三级/点位/lon/lat/ta_id；2026-10-19 起不再使用任何 md 或 KML）
        │
        │ weather-engineering-data / build_points_data.py   （取数，未来 2 周 / 14 天）
        ▼
engineering/data/<pinyin>.json          ← meta.kind=="point"
        │
        ├─ weather-engineering-data / render_points_html.py  → engineering/html/<pinyin>.html（逐点位看板）
        │
        └─ 本技能 / build_points_index.py                          → engineering/html/index.html（点位目录总览）
           本技能 / gen_points_summary.py                          → engineering/fengxian_2tian_huizong.md

井位（well）线：weather-engineering-html / build_dashboard.py → engineering/data/*_data.json(kind=well)
        └─ 本技能 / build_wells_index.py                           → engineering/html/index.html（井位地图）
```

## 脚本一：build_points_index.py —— 生成 index.html

**用法**

```bash
<PY> \
  <SKILLS>/weather-engineering-index/scripts/build_points_index.py \
  --datadir <engineering/data> \
  --htmldir <engineering/html>
```

**参数**

| 参数 | 说明 |
|---|---|
| `--datadir` | 逐点 JSON 数据目录，默认 `engineering/data` |
| `--htmldir` | index.html 输出目录，默认 `engineering/html` |
| `--outdir` | （可选）index.html 单独输出目录，默认等同 `--htmldir` |
| `--no-short` | 不生成「未来 2 天（48 小时）风险」概述块 |

**产出的 index.html 结构**

0. 顶部右上角：醒目按钮式外链「北斗天气风险治理平台 ↗」（`https://leidian.wang`，新窗口打开），右对齐
1. 标题栏 + 窗口说明：`未来 2 周（<开始日> ~ <结束日>）· 组内按风险等级降序`
2. 全窗风险等级分布：红/橙/黄/绿 四级计数（等级用全窗 14 天的 `sev_of` 判定）
3. 「未来 2 天（48 小时）风险」概述块（白底卡 + 蓝色左边线，`.near`）：**按「要素 × 级别」分行**，
   **一行 = 一个级别**（行头是「要素 · 等级」色块：3 级及以上红、2 级橙；后面跟达成**该级别**的点位名），
   行序 = 级别降序 → 同级按 降水→降雪→阵风→均风→体感→能见度；**只列 2 级及以上**，
   标题带 48h 窗口日期（`10-17 ~ 10-19`，由 hourly 前 48 格算出）。与物探 index 同款（2026-10-17 用户定，
   取代原先的散文式一段话）。详见下节《文案口径》
4. 主体：按「一级 + 二级」分组的可折叠卡片，组内「三级 + 点位」按风险等级降序，
   点击条目跳转到该点位的独立看板 html；每条下面的小字为**单点位信息**（口径见下节）。
   组标题排版（2026-10-17 用户定）：**单位名（一级 · 二级）在左，右侧只放「色点 + 数字」**（`●2 ●2 ▸`，
   **不写「重点关注」等文字**）；等级序 高度警惕→重点关注→需关注→整体适宜，**只列非 0 的档**，
   顺序与页头等级分布卡一致（色点即图例）。色点不再放在单位名前面；390px 手机端仍单行不折行。

**页头背景图（hero 背景层，2026-09-28 加）**

「标题行 + 第 1 条的窗口说明」两行被包进 `.heroarea`，照片挂在 `.heroarea::before`（`position:absolute; z-index:-1; isolation:isolate`）上，用**负 inset 向左右出血**；**背景层不参与布局**（`.heroarea` 高度 = 两行内容高度：桌面 59px、430px 手机 100px）。

- **图不在本技能里、也不另存一份**：`hero_css()` 三级探测引用 ——
  `BEIDOU_HERO_BG`（环境变量）> 本技能 `assets/hero-bg.jpg` > 兄弟技能 `../weather-engineering-data/assets/hero-bg.jpg`。
  **日常走第三条**：图归 `weather-engineering-data` 维护，本技能自动跟随，**不会出现两张图各自更新后不一致**。三级全找不到 → 打印一行提示并**静默降级为纯色页头**，不报错、不中断生成。
- **工程侧用的是「野外钻井」实景图**（钻井井架 + 戈壁远景，无储罐/油罐），**与物探侧的雪原勘探图内容不同**。规格同为 720×242 / JPEG q82（约 13 KB，叠白 0.26 淡化；2026-09-29 由 480×161 退回 1/2 分辨率——太糊看不清）。
- **`HERO_FADE` 比点位页更白**：`("0%",".82") ("46%",".50") ("100%",".14")`。钻井图下半部是深色沙地/钢构，照搬点位页那套（底部只留 .04）会把「未来 2 周（14 天）…」那行压得发闷；`.sub` 另加了白色光晕 `text-shadow` 兜底。
- **哪些块不能进 hero 区**：第 2 项的等级分布 `.card`、第 3 项的 `.near` 概述卡、第 4 项的 `.grp` 分组卡**全是白底，必须留在外面**——有底色的块进去会盖住照片。想改 hero 范围时照此判断。
- **`HERO_BLEED = "14px"`** = 页面左右内边距（`body` 的 padding）。**必须与实测值严格相等**：多 2px 就会让 `scrollWidth > clientWidth`，手机端能左右拖动（点位页曾因写成 16px 而实际 14px 踩过）。
- 改完必须重跑 `build_points_index.py` 才生效（图是烘进 HTML 的 base64）。

**只重建 index（不取数、不重渲染点位页）**——这是拆分的主要收益：

```bash
python3 build_points_index.py --datadir engineering/data --htmldir engineering/html
```

## 脚本二：gen_points_summary.py —— 未来 2 天风险汇总

本脚本提供**两套文案**，共用同一套 48h 峰值与 `jozzonwx` 分级：

| 函数 | 用在哪 | 口径 |
|---|---|---|
| `overview_elems(pts)` | **index 顶部「未来 2 天（48 小时）风险」块**（`build_points_index.py` 的 `near_term_html()` 渲染） | 按「要素 × 级别」分组，返回行数据；见下《文案口径》 |
| `build_short(pts, 2)` | **`fengxian_2tian_huizong.md`** 的正文段落 | 量级 + 集中时段 + 处置建议的完整叙述 |
| `build_overview(pts, 200)` | **已停用**（散文式一段话，保留作参考 / 口播稿） | 见下《文案口径》的旧口径 |

```bash
python3 gen_points_summary.py \
  --datadir <engineering/data> \
  --out <engineering/fengxian_2tian_huizong.md> \
  --days 2
```

- `--days` 默认 **2**（聚焦未来 2 天 / 48 小时），**不随取数窗口改成 14 天**——
  远端预报准确性下降，风险汇报口径始终只看近 2 天。
- `build_short` 的结论句**只点名 `sev==2`（徽章真为「重点关注」）的井位**，不再用
  「…等 N 口井需重点关注」——旧写法把 `sev>=1` 全算进去，与徽章同名不同义（2026-10-17 用户指正）。

## 文案口径（2026-10-17 用户定，两条线通用）

**index 概述 `overview_elems()`（2026-10-17 晚改为「按要素列」，与物探 index 同款）**

1. **一行一个「要素 · 等级」**，行头是色块（3 级及以上红 `#C0392B`、2 级橙 `#E0822C`），
   后面跟达成**该级别**的点位名（超过 8 个 → 前 8 个 + 「等 N 口井」）。
2. **必须按级别分行**：一行只放同一级别的点位。若只按要素分行、用该要素最高级别当行头，
   会把只有八级阵风的点位挂到「十级阵风」行下，与事实不符。
3. 行序 = **级别降序 → 同级按 降水→降雪→阵风→均风→体感→能见度**（`_ELEM_ORDER`）。
4. **只列 2 级及以上**；1 级（小雨 / 六级风 / 偏热）不入概述（卡片与点位页里能看到）。
   一条 2 级都没有 → 一句「各点位天气平稳，无明显强降雨与大风，整体适宜作业」。
5. 降雪须有 **48h 累计 >0** 佐证，否则视为 3~14 天远端尖峰，不计入近端风险。
6. 行头文案由 `elem_chip()` 生成：去掉与要素名重复的部分（`八级阵风（≥17.2m/s）` → 行头
   「阵风 · 八级（≥17.2m/s）」），避免「阵风 · 八级阵风」这种叠字。

**旧散文版 `build_overview()`（已停用，仅备查）**

1. 所有井位的风险按**要素等级 4 → 2** 排，先高后低；**只要有 3 级及以上，就不再罗列 2 级**（"灵活掌握"）。
2. 每个要素都要**点名到具体井位**——"暴雨""八级阵风"是谁出现的，是最关键的信息，不能只说类型。
3. 同一要素的同级井位合并成一句，最多点 3 个（其余用「等 N 口井」），按量级降序取前 3。
4. **总字数（含标点）≤200**；超了先砍处置建议、再砍末尾低优先级句子。
5. 正文**不重复「未来 2 天」**（外层标签已有），也不用「N 口井需重点关注」。

**单点位信息 `point_focus()`**

1. **2 级及以上的要素全部列出，不限制个数**（有几个写几个）；排序：等级高者在前 → 同级按 **降雨 → 降雪 → 阵风 → 均风 → 体感 → 能见度**。
2. 要素名后**必须带阈值**：`暴雨（≥6mm/h）`、`八级阵风（≥17.2m/s）`、`十级阵风（≥24.5m/s）`、`炎热（体感>32℃）`…（阵风同级比均风高两级风力，见 `_ELEM_TEXT`）
3. **48h 累计降水 >20mm 才写、累计降雪 >10mm 才写**，否则不提；低量级流水账（0.8mm 小雨等）一律不列。
4. 一条 2 级及以上要素都没有 → `未来 2 天无明显高影响天气`。

> 实现：`_ELEM_TEXT`（要素+等级 → 带阈值短语）、`_ELEM_ORDER`（同级排序）、`_ELEM_ADVICE`（处置建议）；
> 等级一律来自 `jozzonwx.grade_*`，本技能**不再保存任何阈值副本**。

## 脚本三：build_wells_index.py —— 井位地图 index.html

从 `weather-engineering-html` 拆出。把所有井位点标在**同一张地形图**上，按风险配色，
点击井位标记或列表 → 跳转到该井位的独立看板 html。**离线运行，不取数**。

```bash
python3 <SKILLS>/weather-engineering-index/scripts/build_wells_index.py \
  --datadir <engineering/data> \
  --outdir  <engineering/html> \
  --name "钻井工程"
```

| 参数 | 说明 |
|---|---|
| `--datadir` | **必填**。井位 `*_data.json` 所在目录 |
| `--outdir` | index.html 输出目录，默认 = `--datadir` |
| `--name` | 标题中的项目/区域名，默认 `钻井工程` |
| `--start` / `--end` | 窗口起止日；留空则取数据 `meta.start` / `meta.end` |

> 说明：`weather-engineering-html` 的 `build_dashboard.py` 已**移除** `--build-index`
> 与 `--with-index`，不再产出 index；需要井位地图目录页时统一用本脚本。

---

## 风险分级口径（沿用 _sev 阈值）

**两套窗口，不许混用**（与 `weather-engineering-data` 单点位看板同源）：

- **全窗 14 天**（`sev_of(daily, summary)`）——只用于 index 顶部的**等级分布计数**。「累计」口径为 `focus = Σ(日降水≥10mm 的日子)`（连续降雨累计）。
- **未来 48 小时**（`sev_of_recent(daily2, ph, cum48, el48)`）——用于「未来 2 天风险」短描述与点名井位。`ph`＝48h 内最大小时降水（mm/h）、`cum48`＝48h 逐小时累计（`h48_precip`）、`el48`＝48h 窗口的阵风/均风/最高温/最低温（`peaks_48h`，**不是 summary 的 14 天极值**）。

| 等级 | 含义 | 全窗 14 天触发（任一） | 48h 触发（任一） |
|---|---|---|---|
| 0 绿 | 整体适宜 | — | — |
| 1 黄 | 需关注 | 日降水 ≥12mm / 均风 ≥10.8 / 最低温 ≤0 / 连续累计 ≥30mm | 小时降水 ≥5mm/h / 日降水 ≥12mm / 均风 ≥10.8 / 最低温 ≤0 / 48h 累计 ≥20mm |
| 2 橙 | 重点关注 | 日降水 ≥50mm / 阵风 ≥24.5（十级） / 最高温 ≥35 / 最低温 ≤-5 / 连续累计 ≥80mm | 小时降水 ≥10mm/h / 日降水 ≥50mm / 阵风 ≥24.5（十级） / 最高温 ≥35 / 最低温 ≤-5 / 48h 累计 ≥80mm |
| 3 红 | 高度警惕 | 日降水 ≥80mm / 阵风 ≥32.7（十二级） / 最高温 ≥38 / 连续累计 ≥150mm | 日降水 ≥80mm / 阵风 ≥32.7（十二级） / 最高温 ≥38 / 48h 累计 ≥150mm |

> **阵风阈值 2026-10-17 上调（用户定：同级比均风高两级风力，阵风八级 17.2 = 均风六级 10.8）**：阵风 1~4 级 = 13.9 / 17.2 / 24.5 / 32.7 m/s。上表橙/红档的阵风门槛相应由 17.2 / 20.8 改为 **24.5 / 32.7**；代码里一律调 `JW.grade_gust()`，不再写 m/s 字面量。

> **抬级与并级（2026-10-09 / 2026-10-16）**：① 48h 有明显降雨（≥1.5mm/h）即至少「需关注」；② 新增要素（降雪 / 均风 / 体感 UTCI / 能见度）48h 等级经 `jozzonwx.el_levels()` + `sev_from_levels()` 并入综合等级，与单点位看板、物探看板共用 `jozzonwx` 同一套分级，杜绝口径漂移。

## 注意事项

- 只处理 `meta.kind == "point"` 的 JSON；井位看板（`kind == "well"`）会被忽略。
- 点位名称、工区（gongqu）取自 JSON 的 `meta.name`，工区取名称前缀连续中文。
- 若 `gen_points_summary` 导入失败，index 仍会生成，只是缺少「未来 2 天（48 小时）风险」块。

---

## 跨平台执行对照（macOS / Linux ↔ Windows）

下文命令行体例为 bash。在 Windows 上按此表改写即可：

| bash（本文体例） | PowerShell（Windows） |
|---|---|
| `VAR=x <cmd>` | `$env:X="x"; <cmd>` |
| 行尾 `\` 续行 | 行尾 `` ` `` 续行，或写成一行 |
| `$PY a.py --k v \` | `$PY a.py --k v` |
| `cd /d 目录` | `cd "目录"` |
| `/tmp/foo` | `%TEMP%\foo`（或 `$TMP`） |
| `open 文件` | `start "" 文件`（CMD）/ `Invoke-Item 文件`（PowerShell） |
| `chmod +x x.sh` | 不需要（Windows 不看可执行位） |

- **路径分隔符无关**：脚本内部一律用 `os.path.join` / `pathlib`，不依赖 `/` 或 `\`；文档中 `<WORK>/beidou` 在 Windows 上按 `<WORK>\beidou` 理解。
- **无 shell 专属依赖**：所有 Python 脚本只用标准库 + `requests`，不调用 `open` / `pbcopy` 等系统命令，Windows 上可直接运行。
- **临时目录无关**：脚本内的临时文件（如 CDP 用户数据目录）统一走 `tempfile.mkdtemp()`，自动适配系统临时目录。
