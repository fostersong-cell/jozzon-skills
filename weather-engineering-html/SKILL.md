---
name: weather-engineering-html
description: 钻井工程井位天气看板生成器（与物探 weather-wutan-html 完全不同的生成模式）。输入井位点 KML（多个 <Placemark><Point>，如钻井平台/油气井），用 Open-Meteo 拉取「下一日 0 时起**未来 2 周 / 14 天**」逐小时预报，为每个井位生成【独立 html 看板】（无地图，但保留重点关注/关键指标/逐要素曲线柱状图/风险面板/作业建议）。本技能**不再生成 index.html**——井位地图 index 已拆出为独立技能 `weather-engineering-index`（`scripts/build_wells_index.py`）。用于钻井/石油工程项目的井位级天气风险研判。中文字体子集内嵌，手机/浏览器直接打开。
---

## 环境占位符（跨平台 · 首次使用请先确认）

本技能文档中的 `<WORK>` `<SKILLS>` `<BEIDOU>` `<PY>` `<NODE>` `<NODE_MODULES>` `<TMP>` 均为**运行时占位符**，须替换为本机的实际值。文档中不再出现任何某一台机器的固定路径，macOS 与 Windows 通用：

| 占位符 | 含义 | macOS 典型值 | Windows 典型值 |
|---|---|---|---|
| `<WORK>` | 工作区根（其下含 `beidou/`） | `~/Desktop/.../AI/work` | `C:\...\AI\work` |
| `<SKILLS>` | 技能根（本技能所在目录） | `<WORK>/.workbuddy/skills/jozzon/weather-engineering-html` | 同左 |
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

# 钻井工程井位天气看板（独立 skill）

与物探 skill（一个工区一张含地图的多采样点看板）**生成模式完全不同**：

- **输入**：井位点 KML（`--wells`，含多个 `<Placemark><Point>`，如红页钻井平台、马306-2H井）。可逗号分隔传入多个项目 KML，一次性汇总所有井位。
- **每个井位 → 一张独立 html 看板**：
  - **不显示地图**（钻井井位是单点，地图无意义）；
  - **保留"其它所有内容"**：顶部单一「重点关注」（按严重程度变色）、关键指标四宫格、逐要素曲线/柱状图（降水柱 / 风速·阵风线 / 气温线，默认全勾选、ELEM_ORDER 固定 降水→风速→气温）、风险面板（当前值 + 要素级值 + 全期最严重）、钻井作业影响与建议（降水泥泞 / 大风 / 高温 / 低温 / 行车）。
  - 页眉带「← 返回总览」链接（`../../index.html`）。
- **井位地图 index.html（已迁出到独立技能）**：原为本 skill 的可选交付，现已拆出到
  **`weather-engineering-index`**（`scripts/build_wells_index.py`）。需要汇总所有井位点的
  地图目录页时，在生成井位页后单独运行：
  `python3 build_wells_index.py --datadir <engineering/data> --outdir <engineering/html>`
  地图把所有井位点标在同一张 Esri World Topo 地形图上，按风险绿/橙/红配色，点击井位 → 跳转到该井位独立 html。

## 用法

```bash
<PY> \
  <SKILLS>/weather-engineering-html/scripts/build_dashboard.py \
  --name "钻井工程" \
  --wells "engineering/kml/hongye-wells-points.kml,engineering/kml/sichuan-wells-points.kml" \
  --outdir "engineering/html" \
  --datadir "engineering/data" \
  --days 14
```

- `--name`：钻井工程/区域名（用于 index 标题，如 `钻井工程`）。
- `--wells`：井位点 KML，逗号分隔可传多个项目（如红页 + 四川）。每个 KML 的 `<Document><name>` 作为项目标签展示在井位列表。
- `--outdir`：井位 html 输出目录（通常 `beidou/engineering/html`）。
- `--datadir`：`_data.json` 落盘目录（通常 `beidou/engineering/data`），文件名自动转拼音（pinyin，保留数字/字母，如 `hongye7pingtai_data.json`）。
- `--days` 默认 14（未来 2 周），默认从**明天 0 时**起（`--from-today` 从今天起）。
- Open-Meteo 免费接口无需 key（脚本内带占位 key 仅做兼容）；`timezone=Asia/Shanghai`。

## 两种运行模式

| 模式 | 参数 | 说明 |
|------|------|------|
| 在线生成（井位页） | `--wells <kml[,kml]>` | 解析井位点 → 一次性批量取数（Open-Meteo 多坐标）→ **每个井位一张无地图 html**（不再生成 index.html） |
| 离线单井重渲染 | `--data <x_data.json>` | 读取单个井位 `_data.json` 重渲染其无地图 html（不取数、不生成 index） |

> **index 生成已独立（2026-09-17 拆分）**：本 skill 只负责**井位页**。井位地图 index.html
> 由 `weather-engineering-index` 技能的 `build_wells_index.py` 生成（零取数，仅合并已有 `*_data.json`）。
> - 日常刷新：`--wells` 一条命令只刷新井位页，**不**动 index.html。
> - 需更新井位地图目录页时：
>   `python3 <SKILLS>/weather-engineering-index/scripts/build_wells_index.py --datadir <datadir> --outdir <htmldir>`

## 与物探 skill 的差异（关键）

- 物探：一个工区一张含地图的多采样点看板；钻井：**每个井位一张独立无地图看板**（汇总地图 index 由 `weather-engineering-index` 单独生成）。
- 钻井单井页去掉了物探的 `mapbox` / `timebar`（无地图、无逐小时地图着色）；逐要素曲线直接展示该井位（默认 SEL=0），风险面板默认显示。
- 文件名用拼音（保留数字/字母，避免中文在 CDP/系统间编码问题）；`_data.json` 落 `datadir` 拼音名，html 落 `outdir` 拼音名。

## 轻量自检（默认，零消耗）

生成后只做结构校验，**不启动 Chrome / 不跑 CDP**：
- 单井页：`const DATA` 可解析、`meta.kind=="well"`、`points` 长度为 1、`series` 与 `hx` 齐全；且 `id="mapCanvas"` 不存在（确认无地图）、`id="explorerCharts"` 与 `id="riskReason"` 存在（内容保留）、`../../index.html` 返回链接存在。
- index（由 `weather-engineering-index` 产出）：`const DATA` 可解析、`id="mapCanvas"` 存在、`points`/`wells` 数量 = 井位数、各 `wells[].href` 对应 html 文件均存在。

## 注意

- 当前钻井井位点 KML：`beidou/engineering/kml/hongye-wells-points.kml`（红页3口）、`sichuan-wells-points.kml`（四川2口）。注意 `*-wells.kml` 是作业区**边框多边形**，不是井位点。
- 山区小气候可能强于模式预报，建议以现场实测为准。
- 不预填真实隐私数据，部署/分享安全。

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
