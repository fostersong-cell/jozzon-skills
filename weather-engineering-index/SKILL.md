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
| 采集/刷新点位天气数据（Open-Meteo 取数，未来 2 周） | `weather-engineering-data` |
| 渲染单个点位的天气看板 HTML | `weather-engineering-data` |
| **生成/重建点位目录总览 index.html（point）** | **本技能 `weather-engineering-index`**（`build_points_index.py`） |
| **生成井位地图 index.html（well）** | **本技能 `weather-engineering-index`**（`build_wells_index.py`） |
| **生成「未来 2 天风险」Markdown 汇总** | **本技能 `weather-engineering-index`** |
| 井位（well）看板 HTML | `weather-engineering-html` |

## 目录与数据流

```
engineering/kml/all_points_info.md      ← 唯一数据源（2026-09-17 起不再使用任何 KML）
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
| `--no-short` | 不生成「未来 2 天风险」短描述块 |

**产出的 index.html 结构**

0. 顶部右上角：醒目按钮式外链「北斗天气风险治理平台 ↗」（`https://leidian.wang`，新窗口打开），右对齐
1. 标题栏 + 窗口说明：`未来 2 周（<开始日> ~ <结束日>）· 组内按风险等级降序`
2. 全窗风险等级分布：红/橙/黄/绿 四级计数（等级用全窗 14 天的 `sev_of` 判定）
3. 「未来 2 天风险」短描述块（橙色卡片，平实口吻、不罗列等级）：除点明**主风险工区与区域**外，还会**点名最需要关注的井位**（按 48h 风险等级 + 累计降水降序取前 3，超量用「等 N 口井」收尾）
4. 主体：按「一级 + 二级」分组的可折叠卡片，组内「三级 + 点位」按风险等级降序，
   点击条目跳转到该点位的独立看板 html

**页头背景图（hero 背景层，2026-09-28 加）**

「标题行 + 第 1 条的窗口说明」两行被包进 `.heroarea`，照片挂在 `.heroarea::before`（`position:absolute; z-index:-1; isolation:isolate`）上，用**负 inset 向左右出血**；**背景层不参与布局**（`.heroarea` 高度 = 两行内容高度：桌面 59px、430px 手机 100px）。

- **图不在本技能里、也不另存一份**：`hero_css()` 三级探测引用 ——
  `BEIDOU_HERO_BG`（环境变量）> 本技能 `assets/hero-bg.jpg` > 兄弟技能 `../weather-engineering-data/assets/hero-bg.jpg`。
  **日常走第三条**：图归 `weather-engineering-data` 维护，本技能自动跟随，**不会出现两张图各自更新后不一致**。三级全找不到 → 打印一行提示并**静默降级为纯色页头**，不报错、不中断生成。
- **工程侧用的是「钻井井场」实景图**（井架 + 黄色井场设备 + 戈壁远景），**与物探侧的雪原勘探图内容不同**。规格同为 480×161 / JPEG q82（工程图细节多，约 21 KB）。
- **`HERO_FADE` 比点位页更白**：`("0%",".82") ("46%",".50") ("100%",".14")`。钻井图下半部是深色沙地/钢构，照搬点位页那套（底部只留 .04）会把「未来 2 周（14 天）…」那行压得发闷；`.sub` 另加了白色光晕 `text-shadow` 兜底。
- **哪些块不能进 hero 区**：第 2 项的等级分布 `.card`、第 3 项的未来 2 天风险卡、第 4 项的 `.grp` 分组卡**全是白底，必须留在外面**——有底色的块进去会盖住照片。想改 hero 范围时照此判断。
- **`HERO_BLEED = "14px"`** = 页面左右内边距（`body` 的 padding）。**必须与实测值严格相等**：多 2px 就会让 `scrollWidth > clientWidth`，手机端能左右拖动（点位页曾因写成 16px 而实际 14px 踩过）。
- 改完必须重跑 `build_points_index.py` 才生效（图是烘进 HTML 的 base64）。

**只重建 index（不取数、不重渲染点位页）**——这是拆分的主要收益：

```bash
python3 build_points_index.py --datadir engineering/data --htmldir engineering/html
```

## 脚本二：gen_points_summary.py —— 未来 2 天风险汇总

生成面向领导/客户的**约 50 字、平实口吻、不罗列等级**的「未来 2 天（48 小时）风险」
短描述，同时写入 Markdown 文件，并被 `build_points_index.py` 复用于 index 顶部。

```bash
python3 gen_points_summary.py \
  --datadir <engineering/data> \
  --out <engineering/fengxian_2tian_huizong.md> \
  --days 2
```

- `--days` 默认 **2**（聚焦未来 2 天 / 48 小时），**不随取数窗口改成 14 天**——
  远端预报准确性下降，风险汇报口径始终只看近 2 天。
- 主风险工区取「未来 2 天累计雨量最大」或「近 2 天等级最高」的工区；
  若整体无风险，输出「未来 2 天整体风险可控…」。
- 短描述除区域外，会点名最需要关注的井位（按 48h 风险等级 + 累计降水降序，前 3 名；
  超 3 个则用「等 N 口井」收尾），例如「其中马401-4H井、马401-2H井需关注，注意…」。

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

| 等级 | 含义 | 触发（任一） |
|---|---|---|
| 0 绿 | 整体适宜 | — |
| 1 黄 | 需关注 | 日降水 ≥12mm / 风速 ≥10.8 / 最低温 ≤0 / 2 天累计 ≥20mm |
| 2 橙 | 重点关注 | 日降水 ≥50mm / 阵风 ≥17.2 / 最高温 ≥35 / 最低温 ≤-5 / 2 天累计 ≥80mm |
| 3 红 | 高度警惕 | 日降水 ≥80mm / 阵风 ≥20.8 / 最高温 ≥38 / 2 天累计 ≥150mm |

## 注意事项

- 只处理 `meta.kind == "point"` 的 JSON；井位看板（`kind == "well"`）会被忽略。
- 点位名称、工区（gongqu）取自 JSON 的 `meta.name`，工区取名称前缀连续中文。
- 若 `gen_points_summary` 导入失败，index 仍会生成，只是缺少「未来 2 天风险」块。

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
