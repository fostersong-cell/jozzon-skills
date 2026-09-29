---
name: weather-wutan-index
description: 物探项目2周天气看板「多项目总览页 index.html」生成器（由各项目看板 _data.json 合并汇总，不取数、零 API 消耗）。扫描 beidou/{wutan,engineering}/data 下全部 *_data.json，按风险等级降序生成可点击进入各项目看板的总览卡片页（sev 徽章 + 重点提示 + 类型/日期/采样点），顶部含等级统计行与「未来 2 天（48小时）风险」聚焦描述（NEAR_DAYS=2，近 2 天风险先说、周中后期远预报情况置后、仅一句话「临近时再提示」、不作主风险）。卡片风险评级与重点提示均按「未来 48 小时（近 2 天）」口径（meta.sevNear / peaksNear），与看板 t1「重点提示」横幅一致。用于多项目并行时的天气风险总览与汇报；与 weather-wutan-html（单项目 2 周看板）配套使用。
---

## 环境占位符（跨平台 · 首次使用请先确认）

本技能文档中的 `<WORK>` `<SKILLS>` `<BEIDOU>` `<PY>` `<NODE>` `<NODE_MODULES>` `<TMP>` 均为**运行时占位符**，须替换为本机的实际值。文档中不再出现任何某一台机器的固定路径，macOS 与 Windows 通用：

| 占位符 | 含义 | macOS 典型值 | Windows 典型值 |
|---|---|---|---|
| `<WORK>` | 工作区根（其下含 `beidou/`） | `~/Desktop/.../AI/work` | `C:\...\AI\work` |
| `<SKILLS>` | 技能根（本技能所在目录，用户级） | `~/.workbuddy/skills/jozzon/weather-wutan-index` | `%USERPROFILE%\.workbuddy\skills\jozzon\weather-wutan-index` |
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

# 物探项目2周天气看板 · 多项目总览页（index.html）生成器

把多个**单项目看板**（由 `weather-wutan-html` / `weather-wutan-data` 生成的 `_data.json`）合并成一张**总览页 `index.html`**，做成「点击进入看板、看板可返回」的小系统。

**本 skill 只做总览聚合，不请求任何天气接口**（纯读 `_data.json`，离线、零 API 消耗、不会触发 Open-Meteo 429）。

## 职责边界

- ✅ 本 skill 负责：多项目总览页 `index.html`（含等级统计 + 未来 2 天风险描述）。
- ❌ 不属于本 skill：单个项目看板 HTML 与 `_data.json` 的生成 —— 那是 `weather-wutan-html`（工区/测线，2 周）与 `weather-wutan-data`（采集点，2 周）的职责。
- 各项目看板模板已内置 `← 返回总览` 链接（`.backlink`，指向同目录 `index.html`），由 `weather-wutan-html` 的模板固化生成，本 skill 无需处理。

## 页面构成

| 区块 | 内容 |
|------|------|
| 标题 + 副标题 | 标题为「中石化北斗运营中心 · 物探项目天气看板」；副标题显示 **预报跨度 + 日期区间 + 点击提示** |
| 顶部右上角外链 | 醒目按钮「北斗天气风险治理平台 ↗」指向 `https://leidian.wang`（新窗口打开） |
| 等级统计行 | `物探 N 个项目 ｜ 高度警惕 a · 重点关注 b · 需关注 c · 整体适宜 d`（按 **48 小时评级 sevNear** 着色） |
| **未来 2 天风险** | `.near-term` 聚焦描述块（见下），左侧 accent 边线；**先说近 2 天风险，周中后期远预报情况置后** |
| 项目卡片网格 | 按 **48 小时风险评级（sevNear）** 降序（红→橙→黄→绿），每卡 = 项目名 + sev 徽章 + 重点提示 + 类型/日期/采样点，`<a href="{pin}.html">` 进入看板 |
| 图例 | 四级风险色说明 |
| 页头背景图 | 标题行 + 副标题 + 等级统计行背后铺一张**雪原勘探照片**（base64 内嵌，白色渐隐），**不占版面**（见下） |

### 页头背景图（hero 背景层，2026-09-28 加）

「标题行 + `.sub` + `.summary`」三行被包进 `.heroarea`，照片挂在 `.heroarea::before`（`position:absolute; z-index:-1; isolation:isolate`）上，用**负 inset 向左右出血**到屏幕两边。`.heroarea` 高度 = 三行内容高度（桌面 95px、430px 手机 135px），**背景层不参与布局**，加了图页面位置一点不变。

- **图不在本技能里、也不另存一份**：`gen_subindex.py` 的 `hero_css()` 三级探测引用 ——
  `BEIDOU_HERO_BG`（环境变量，换图应急）> 本技能 `assets/hero-bg.jpg` > 兄弟技能 `../weather-wutan-html/assets/hero-bg.jpg`。
  **日常走第三条**：图归 `weather-wutan-html` 维护，本技能自动跟随，**绝不会出现两张图各自更新后不一致**。三级全找不到 → 打印一行提示并**静默降级为纯色页头**，不报错、不中断生成。
- **规格**：720×242 / JPEG q82 / 约 32 KB（与看板页同一张、同一规格，叠白 0.26 淡化）。base64 内嵌后 index 约 52 KB。
- **`HERO_BLEED = "16px"`** = 页面左右内边距。**必须与实测内边距严格相等**：多 2px 就会让 `scrollWidth > clientWidth`，手机端能左右拖动（看板页曾因写成 16px 而实际 14px 踩过，见 `weather-wutan-html` 的 SKILL.md）。
- **`HERO_FADE`**（自上而下白纱）：`.78/0% → .38/46% → .03/100%`。物探图是雪原、本身亮，底部可以直接透到 .03。
- **哪些块不能进 hero 区**：`.near-term`（未来 2 天风险，淡绿底）与 `a.card`（白底卡片）**留在外面**——有底色的块进去会盖住照片。想改 hero 范围时照此判断。
- **改完必须离线重生 index** 才生效：`<PY> <SKILLS>/weather-wutan-index/scripts/gen_subindex.py --only wutan`。

### 未来 2 天（48 小时）风险描述

- 模块常量 `NEAR_DAYS = 2`：只统计每个 `_data.json` 的 `daily` 前 2 天与逐点 `series` 前 2 天的降水 / 阵风 / 低温极值。
- **超出该 2 天窗口的极端暴雨，仅以「周中后期极端暴雨（如 …）已超出可靠预报范围，暂不纳入，临近时再提示」一句话点出，置于近 2 天风险描述之后，不作为当前主风险。** 理由：远预报不可靠（用户 2026-09-15 明确口径）。
- **排序约定（2026-09-19）**：`build_near_term_desc()` 输出顺序为「近 2 天风险详情（标题 + 大风低温 + 强降水处置）」先行，「周中后期远预报一句话」置后；切忌把远预报放在近 2 天风险之前。
- 近窗口内的主风险按「大风低温（阵风 ≥17.2m/s 或最低温 ≤0℃）」与「强降水（单日 ≥25mm）」两类归纳，并给出处置提示。
- 文案由 `build_near_term_desc()` 自动生成，随数据重算，无需手写。

### 预报跨度标签（动态，避免错标）

副标题的预报天数**按数据实际跨度动态显示**：`daily` 长度 ≥13 天显示「未来 2 周（14 天）」，否则如实显示「未来 N 天」。
> 这样在单项目尚未按 2 周重跑、数据仍是 7 天时，总览页不会错误地标成「2 周」。重跑后自动变为「未来 2 周（14 天）」。

## 用法

```bash
<PY> \
  <SKILLS>/weather-wutan-index/scripts/gen_subindex.py \
  --only wutan
```

- `--only wutan`：只重建物探总览 `beidou/wutan/html/index.html`（**日常最常用**）。
- `--only engineering`：只重建石油工程总览 `beidou/engineering/html/index.html`。**默认不推荐**——石油工程总览平时由 `weather-engineering-index` 的 `build_points_index.py` 生成（带 7 个一级分组和未来 2 天风险短描述），本脚本生成的是**简化版**（无分组、无风险短描述），跑一次会把它覆盖掉。只在确实需要重排时才用。
- 省略 `--only`：两者都重建（同上，会覆盖已由 `build_points_index.py` 生成的工程总览）。
- `--base <工作区根>`：指定工作区根目录（其下需含 `beidou/{wutan,engineering}/data`）。**默认自动解析**（环境变量 `BEIDOU_WORK` > 从脚本位置逐级上溯找含 `beidou/wutan/data` 的目录），一般无需传；换工作区时才用。
- **两类数据文件名约定不同，勿混用**：物探是 `<pin>_data.json`（脚本默认 glob），石油工程是 `<slug>.json` 且 `meta.kind=="point"`（须传 `pattern="*.json"`）。写错会读不到数据并**误判成「空数据」而生成空页覆盖已有总览**。

## 工作流（agent 执行步骤）

1. 确认各项目 `_data.json` 已生成且为最新（即先跑过 `weather-wutan-html` 的取数或「重跑」）。
2. 运行上面的命令（离线，不取数）。
3. 校验产物：
   - `grep` 卡片数量与 `class="near-term"`（未来 2 天风险块）是否就位；
   - 抽查副标题的预报跨度与日期区间是否与数据窗口一致；
   - 抽查卡片聚焦文案（如「09-21 单日降水 90.3mm（暴雨）」）是否由数据自动生成。
4. 用 `present_files` 交付 `index.html`。

## 关键实现要点

- **数据来源**：只读 `*_data.json` 的 `meta`(name/sev/sevLabel/**sevNear**/sevLabelNear/start/end/npts/kind) + `peaksNear`(gustMax/tmax/tmin/pMax/pMaxDay/focusStart/focusEnd/focusTotal，缺则回退 `peaks`) + `daily`(逐日降水) + `points[].series`(逐日风/温)。
- **风险评级口径**：卡片徽章/颜色/排序所用的「高度警惕」等评级取自 `meta.sevNear`（**未来 48 小时 / 近 2 天**口径），与看板 t1「重点提示」横幅保持一致；旧数据缺 `sevNear` 时回退到全周期 `sev`。`build_near_term_desc()` 与之同源（NEAR_DAYS=2）。
- **重点提示复现**：`build_focus()` 重建看板顶部的「主要关注」文本，阈值 gustMax≥17.2(≥8级)、tmax≥35(高温)、tmin≤0(结冰)、pMax≥50(暴雨)/≥25(大雨)、focusStart(连续降雨累计)；无则「本期未触发极端天气预警阈值，整体适宜作业」。最多 3 条。**该文本同样取自 `peaksNear`（48 小时口径）**，与评级一致，不再用全周期 peaks。
- **排序**：`rows.sort(key=lambda r: (-r["sev"], r["name"]))`，其中 `r["sev"]` 即 48 小时评级 sevNear，同级按名称。
- **链接相对路径**：卡片链接只写文件名（`{pin}.html`），因 `index.html` 与各看板 HTML 同目录。
- **sev 配色**：0=#2E8B57（整体适宜）/ 1=#E0A92C（需关注）/ 2=#E0822C（重点关注）/ 3=#C0392B（高度警惕）。
- **数字格式化**：去尾零（-0.0→0）；`focusStart == focusEnd` 时只显示单日。
- **字体**：总览页用系统字体栈（不内嵌子集），与各看板的专用字体子集解耦。
- **命名**：输出固定为 `index.html`（英文，符合拼音命名规范）。

## 与「重跑」的关系

项目约定（2026-09-17）：说「重跑」即把物探的 **数据 + HTML + index + 2 天风险汇总** 一次性全部刷新。
该流程由 `beidou/rerun_wutan.py` 编排 —— 它依次调用 10 个项目的取数，末尾**自动调用本 skill 的 `gen_subindex.py --only wutan`** 重建总览。因此日常无需单独手工重建 index；只有在**项目清单变更**（新增/改名项目）或**单独要求同步总览**时才直接运行本 skill。

## 通用注意事项

- 本 skill 不联网、不取数，因此总览展示的风险完全取决于各 `_data.json` 的新鲜度；若单项目未重跑，总览也会是旧数据。
- 远预报（超出 2 天窗口）仅作「临近再提示」，不展开、不作为当前处置依据。

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
