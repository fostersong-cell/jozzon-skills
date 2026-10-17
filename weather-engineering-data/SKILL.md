---
name: weather-engineering-data
description: 石油工程 / 钻井井位「未来 2 周」天气看板生成器（数据采集 + 渲染点位页，不含 index）。**现行链路**：① `build_points_data.py` 读 `engineering/kml/all_points_info.md`（含 `点位`/`经度`/`纬度`，可选一二级三级），按 `engineering_ta_map.json`（点位名 → 九章目标区 ta_id）**逐个 ta_id 调 jozzon-mcp（九章雷电网）**取「下一整时起未来 2 周」逐小时预报，每点位写一份独立 JSON；② `render_points_html.py` 离线渲染成可交互中文 HTML 看板。要素：温度 / 体感(UTCI) / 降雨(rain+showers) / 降雪(mm/h) / 均风 / 阵风 / 能见度，并派生降水类型码 降雨/降雪/雨夹雪（结合气温，0℃ 以下按降雪）。**图表口径**：48 小时图＝降水柱+均风/阵风/气温折线合并单图（**不含能见度**）；未来 2 周＝**固定四图 降水(降雨+降雪并列柱) / 气温(含体感虚线) / 阵风·均风 / 能见度**。用于钻井 / 管线等点位的天气风险研判与汇报。
---

## 环境占位符（跨平台 · 首次使用请先确认）

本技能文档中的 `<WORK>` `<SKILLS>` `<BEIDOU>` `<PY>` `<NODE>` `<NODE_MODULES>` `<TMP>` 均为**运行时占位符**，须替换为本机的实际值。文档中不再出现任何某一台机器的固定路径，macOS 与 Windows 通用：

| 占位符 | 含义 | macOS 典型值 | Windows 典型值 |
|---|---|---|---|
| `<WORK>` | 工作区根（其下含 `beidou/`） | `~/Desktop/.../AI/work` | `C:\...\AI\work` |
| `<SKILLS>` | 技能根（本技能所在目录，用户级） | `~/.workbuddy/skills/jozzon/weather-engineering-data` | `%USERPROFILE%\.workbuddy\skills\jozzon\weather-engineering-data` |
| `<BEIDOU>` | 看板根 | `<WORK>/beidou` | 同左 |
| `<PY>` | Python 3 解释器 | 托管 venv `.../bin/python`，或系统 `python3` | 托管 venv `...\Scripts\python.exe`，或 `python` |
| `<NODE>` | Node.js 解释器 | `node` | `node.exe` |
| `<NODE_MODULES>` | Node 模块目录（跑 jsdom 回归脚本用） | `.../node/workspace/node_modules` | 同上（本机任选一个模块目录） |
| `<TMP>` | 系统临时目录 | `/tmp` | `%TEMP%` |

**新机器上先做这 3 步**（否则命令会跑错路径）：
1. 确认 `<WORK>`：其下必须同时存在 `beidou/wutan/data` 与 `beidou/engineering/data`。
2. 确认 `<PY>`：`python3 --version`（Windows 用 `python --version`）。**Python 脚本只用标准库（`urllib`/`ssl`/`json`），通常无需额外安装依赖**；需第三方库时（如给旧脚本补 `requests`）再建 venv 安装。
3. 确认 `<NODE>` 与 `<NODE_MODULES>`：需跑 jsdom 回归脚本时，把 `jsdom` 装进 `<NODE_MODULES>`，并设 `NODE_PATH=<NODE_MODULES>`。

下文命令行体例为 bash（macOS / Linux）；**Windows 等价写法见文末《跨平台执行对照》**。

> ⚠️ **本节及下面《输入模式》《模式一：单点》《采集点模式》描述的是遗留 Open-Meteo 脚本**
> （`build_region_dashboard.py` / `build_weather_dashboard.py`，按 KML / 经纬度输入、**直接抓 Open-Meteo**），
> **与现行「ta_id 点位链路」相互独立**。**石油工程现行主链路**见下方《模式：Markdown 点位表》与
> 《渲染逐点看板》两节（`build_points_data.py` + `render_points_html.py`，走 jozzon-mcp 按 `ta_id` 取数、出无地图点位看板）。
> 遗留脚本仅在「按 KML / 经纬度临时出一张单点或区域图」时使用，**日常钻井点位看板不用它**。

# （遗留）按 KML / 经纬度出「未来 2 周」单点·区域看板（Open-Meteo）

按项目名称 + KML（采集点 / 多边形工区 / 测线）或「名称 + 经纬度」，**逐个坐标**从 Open-Meteo 拉取「下一整时起未来 2 周」逐小时预报，渲染成含地形瓦片底图的交互式 HTML。仅当需要「非 ta_id 点位」的临时区域图时使用；已注册 ta_id 的点位请走下方的点位表链路。

## 输入模式

| 模式 | 输入 | 脚本 | 输出文件名 |
|------|------|------|-----------|
| **采集点（遗留）** | 项目名称 + KML 采集点（多个 `<Placemark><Point>`） | `build_region_dashboard.py` | `{名称}采集点.html`（+ 可选 `.pdf`） |
| **面（工区）** | 项目名称 + KML 多边形 | `build_region_dashboard.py` | `{名称}工区.html`（+ 可选 `.pdf`） |
| **线（测线）** | 项目名称 + KML 线要素 | `build_region_dashboard.py` | `{名称}测线.html`（+ 可选 `.pdf`） |
| **单点** | 项目名称 + 经纬度 | `build_weather_dashboard.py` | `{名称}{日期}.html`（+ 可选 `.pdf`） |
| **Markdown 点位表** | 点位汇总 Markdown（含 `点位`/`经度 (DD)`/`纬度 (DD)` 列） | `build_points_data.py` | `{拼音}.json`（逐点，落 `engineering/data/`，不生成 HTML） |

> 文件名规则：**`{项目名称}{当前日期}.pdf`**（单点）/ **`{项目名称}采集点{当前日期}.pdf`**（采集点）/ **`{项目名称}工区{当前日期}.pdf`**（面）/ **`{项目名称}测线{当前日期}.pdf`**（线）。当前日期取运行当天 `YYYY-MM-DD`。KML 自动识别：含 `<Point>` 且无 Polygon/LineString → 采集点模式；`<Polygon>` → 工区；`<LineString>` → 测线。

---

## 模式一：单点（项目名称 + 坐标）

```bash
<PY> \
  <SKILLS>/weather-engineering-data/scripts/build_weather_dashboard.py \
  --name "大关项目" --lat 27.91 --lon 103.87 --outdir "/您的输出目录"
```

坐标顺序：**纬度在前、经度在后**。输出：
- `{outdir}/大关项目2026-08-12.pdf`   ← 必交付物
- `{outdir}/大关项目.html`            ← 同数据离线 HTML（字体已内嵌，手机可打开）

## 采集点模式（主）：KML 采集点（Point），按点取数

```bash
<PY> \
  <SKILLS>/weather-engineering-data/scripts/build_region_dashboard.py \
  --name "大关项目" \
  --kml "/路径/采集点.kml" \      # KML 含多个 <Placemark><Point>（数据采集点）
  --no-pdf \
  --outdir "/您的输出目录"
```

KML 自动判断类型：
- **Point（采集点，主模式）**：KML 含多个 `<Placemark><Point>`（炮点/检波点等数据采集点），**直接按采集点逐个取数，不做网格采样**。地图为采集点分布的地形图（高程色带 + 山体阴影 + 等高线），每个采集点可点击联动展开该点未来 2 周逐要素曲线/柱状图。采集点名称取自 `<Placemark><name>`（缺省显示「采集点 #N」）。
- **Polygon（面/工区）**：按 `--grid` km 网格过滤落在多边形内的点，并加入质心。地图为多边形区域地形图。
- **LineString（线/测线）**：沿测线按 `--grid` km 等距取点，并加入起终点与测线中点。页眉显示测线名与长度 km。

统一流程：
1. 解析 KML（Point 采集点 / Polygon 边框 / LineString 测线），自动识别类型；计算范围（km）。
2. 采样点：**采集点模式直接用 KML 里的 Point 坐标（不采样）**；面 = 网格过滤 + 质心；线 = 等距采样 + 测线中点。采样密度由 `--grid` 控制（默认 6km，仅面/线生效）；点数超 `--maxpts`（默认 150）时自动加粗间距。
3. 用 Open-Meteo 多坐标接口分批拉取所有采样点预报（12 点/批，批间冷却，缓解 429）；可用 `--model ecmwf_ifs04` 指定 ECMWF 4km 高分辨率。**取数时间：下一整时起未来 2 周**（`start_date`/`end_date`）。每个点同时计算逐日 气温(min/max)/降水/风速/阵风 序列。
4. 按「区域/测线/采集点最坏情况包络」聚合：逐时最低温、最高降水、最大风/阵风；连续降雨窗口取各点逐日最大降水 ≥10mm 的连续段。
5. 极端天气分级（0绿/1黄/2橙/3红）：依据暴雨、8级风、高温、结冰、连续降雨累计等指标；顶部「重点关注」背景版据此变色。
6. 调用 Open-Meteo `/v1/elevation` 按自适应密度网格采样高程（地形大时自动放宽步长），分块请求（60 点/批）+ 退避重试，避免 414/429。
7. 输出交互式 HTML：canvas 地形图（高程色带 + 山体阴影 + 等高线），叠加风险区（红=高风险、橙=注意区），再压采集点/边框/测线/网格/比例尺/指北针；**每个采样点可点击**，点击后地图下方同一卡片内立即展开该点未来 2 周逐要素曲线/柱状图（气温=双线、降水=柱、阵风/均风=双线，要素可勾选叠加）。默认不导出 PDF（`--no-pdf`）。

参数：`--kml`（必填，Point 采集点 / Polygon / LineString）、`--grid`（面/线采样间距 km，默认 6，采集点模式忽略）、`--days`（预报天数，默认 14（未来 2 周），从下一整时起）、`--model`（可选）、`--maxpts`（采样点上限，默认 150，仅面/线生效）、`--no-pdf`（仅出 HTML）、其余 `--outdir/--apikey/--chrome` 同单点版。

---

## 模式：Markdown 点位表（钻井平台 / 管线汇总 → 逐点数据文件）

适用于已有一张「点位汇总表」Markdown（如 `engineering/kml/all_points_info.md`，表头含 `点位`/`经度 (DD)`/`纬度 (DD)`，可选 `一级`/`二级`/`三级` 层级标签）。脚本解析出全部点位坐标，**批量取数后为每个点位写出一份独立 JSON 数据文件**（不生成 HTML，纯数据，供后续看板/分析复用）。

```bash
<PY> \
  <SKILLS>/weather-engineering-data/scripts/build_points_data.py \
  --md "engineering/kml/all_points_info.md" \
  --datadir "engineering/data" \
  --name "石油工程" \
  --days 14
```

说明：
- `--md`：点位汇总 Markdown 路径，默认 `engineering/kml/all_points_info.md`（相对项目根目录 `beidou/`）。表头用子串匹配 `点位`/`经度`/`纬度` 定位列，顺序无要求。
- `--datadir`：逐点 JSON 输出目录，默认 `engineering/data/`（与井位看板 `*_data.json` 同目录，但文件名用拼音且无 `_data` 后缀，互不冲突；渲染时按 `meta.kind=="point"` 过滤，仅取点位表数据）。
- `--days` 默认 14（未来 2 周），默认从**下一整点**起（`--from-today` 从当前整点起）；`timezone=Asia/Shanghai`。
- 文件名用拼音（保留数字/字母，如 `hongye7-5hf.json`）；本次运行内重名自动追加 `-2/-3`。
- 每个 JSON 含：
  - `meta`：`kind:"point"` / 点位名 / **`ta_id`** / 一二级三级层级 / 经纬度 / `region` / `source`(md 文件名) / `generated_at` / `timezone` / `start_date` / `end_date` / **`model:"jozzon-mcp(九章雷电网)"`**。
  - `hourly`（逐小时，**现行要素集**）：`time` / `temperature_2m` / **`rainfall`（= rain+showers）** / `snowfall`（**mm/h**）/ `wind_speed_10m` / `wind_gusts_10m` / **`apparent_temperature`（UTCI 体感）** / **`visibility`（m，取自 `x1_visibility` 的 km×1000；**仅前 162h 有值，其余为 `null`**）** / `ptype`。
  - `daily`：逐日 `tempMin/tempMax`、`rainfall`、`snowfall`、`ptype`、`windMax`、`gustMax`、`apparentMin/apparentMax`、`visMin`。
  - `summary`：`totalRainfall`、`maxGust`、`maxWind`、`minTemp`、`maxTemp`、`minApparent/maxApparent`、`minVis`、`maxRainfallDay`、以及小时级峰值 `pHourMax`/`snowHourMax`/`gustHourMax`（供 index / 汇总套用新分级阈值）。
  ⚠️ **`summary` 里的 maxGust/maxTemp/minTemp/pHourMax/snowHourMax 全是「整窗 14 天」值**，不能直接当「未来 48 小时」用——48h 峰值必须在消费侧按 `hourly[:48]` 现算。
- **点位 → ta_id 映射**：`engineering_ta_map.json`（位于 `engineering/kml/`；由 `<SKILLS>/script/build_ta_maps.py` 生成；可用 `--tamap` 指定）。**没有 ta_id 的点位会被跳过并打印清单**；若一个都没有则直接报错退出。取数走 jozzon-mcp，**不再有 Open-Meteo 配额 / 429 问题**。

### 单点位增量重跑（2026-09-25 新增）

只想刷新**单个点位**（如源表刚给它加了队号）时，`build_points_data.py` **没有 `--only` 参数**——它遍历 md 里的全部点位。此时**不要**跑全量（会重写其余点位、浪费配额），改用「临时 md」把点位缩到 1 个：

```bash
TMP=<TMP>/all_points_one.md
{ head -4 "engineering/kml/all_points_info.md";        # 标题 + 表头行 + 分隔行
  echo "| 中原工程 | 西南钻井分公司 | 70112钻井队 | 元陆36井 | 106.547711 | 31.952829 |";
} > "$TMP"

PY=<PY>
cd "<BEIDOU>"
$PY <SKILLS>/weather-engineering-data/scripts/build_points_data.py \
    --md "$TMP" --datadir engineering/data --days 14            # 只重写这 1 个 JSON，其余 16 个不动
$PY <SKILLS>/weather-engineering-data/scripts/render_points_html.py \
    --datadir engineering/data --htmldir engineering/html --only yuanlu36jing
```

要点：
- 临时 md 必须原样保留原表头前 4 行（表头靠子串匹配 `点位`/`经度`/`纬度`），只替换数据行。
- `render_points_html.py` **有** `--only <slug>`，只重渲染该点位的 HTML。
- index 需**单独**重建（`weather-engineering-index` 的 `build_points_index.py`），渲染器不再顺带生成。
- 只重跑一个点位会造成**窗口不一致**：该点 `meta.start_date` 是重跑当天，其余点位仍是上一次的（如 09-24 起）。如需全部对齐到同一窗口，跑全量 `<SKILLS>/script/rerun_engineering.py`（index 由 `weather-engineering-index` 生成 `engineering/html/index.html`，无独立顶层脚本）。
- 取数前先 probe 配额（见运维要点），避免 429。

---

## 渲染逐点看板（纯数据 JSON → HTML，不含 index）

`build_points_data.py` 产出的是**纯数据 JSON**。若需可查看的看板 HTML，用 `render_points_html.py` 离线渲染（无需再请求网络）：

```bash
<PY> \
  <SKILLS>/weather-engineering-data/scripts/render_points_html.py \
  --datadir "engineering/data" \
  --htmldir "engineering/html"
```
- **页头导航（2026-09-22 新增，2026-09-24 改版为左右分置，与物探完全一致）**：点位页 `.topbar` 为 `display:flex;justify-content:space-between` 的左右两栏，含两个**相互独立**的链接——① 左栏 `.topbar-l`（`flex:1 1 auto`）放 `a#backLink`（"← 返回总览"，`href="index.html"`，仅当 URL 带 `?from=index` 时显示，否则内联 JS 隐藏；**左栏常驻占位，故回链隐藏时右栏不会左移**）；② 右栏 `.topbar-r`（`flex:0 0 auto`）**仅**放 `a.extlink` **高亮外链**（常驻显示，文本"北斗天气风险治理平台 ↗"，`href="https://leidian.wang"`，新窗口打开）。两者不是同一链接，互不影响。回链用 teal 描边药丸样式（与物探 `.backlink` 同款），由 `.topbar .backlink` 覆盖 `.topbar a` 的蓝色。**点位所属单位信息 `{sub}` 不放顶栏**（与北斗按钮同排会挤占行宽、把按钮挤出可视区），改为 `<h1>` 下方独立一行 `.unit`（`.unit:empty{display:none}`）；`.topbar` 加 `flex-wrap:wrap` 兜底。`.unit` 内容是 `sub = " · ".join([l1, l2, l3])` 过滤空值后的结果，**含第三级「队号」**（如"中原工程 · 西南钻井分公司 · 70112钻井队"）；三级为空时该行不显示。
```

产出：
- `engineering/html/{拼音}.html` —— **每个点位一张独立无地图看板**（重点关注横幅·按风险变色 / 关键指标六格 2×3 / 逐日降水柱+气温双线+阵风·均风双线 SVG / 风险面板 / 作业影响建议 / 未来 48 小时逐小时图）。副标题行末尾内联坐标（同字号，小数点后两位），日期区间加粗高亮。风险等级沿用 weather-engineering-html 的 `_sev` 阈值（0绿整体适宜 / 1黄需关注 / 2橙重点关注 / 3红高度警惕）。
- **重点提示横幅：逐要素清单（2026-10-17 用户定，与物探看板同款）**：横幅正文不再是「主要关注：…。建议据此调整作业安排。」这段散文，改为 `.ailist > .ai` 清单 ——
  **一行一个要素**，三栏 `要素 / 等级名 / 数值+单位`（`.ai-v` 靠右、`tabular-nums`），标题行写「未来 48 小时 · <综合等级名>」。
  - **只列 48h 窗口内达 1 级（触发阈值）的要素**，未达阈值的不占行（**不写「未发生/无明显」这类否定式**）；全部未达 → 一行 `.ai-note`「未来 48 小时各要素均未达预警阈值，适宜作业。」
  - 行序 = **级别降序 → 同级按要素序**（降水→降雪→阵风→均风→体感→能见度，`_EL_ORDER_ENG`）。
  - 数值口径与关键指标同源：降水＝48h 最大小时降水 `pHourMax`（mm/h）、降雪＝`snow_hour_max_48()`（mm/h）、阵风/均风＝48h 最大风速（m/s）、体感＝冷热两端**更严重的一侧**（°C）、能见度＝48h 最低值（m）。
  - **远期（第 3~14 天）另起一行 `.far`**（米黄底 `#FFF7E6` + 棕色字），**不再单独占一张红/绿卡**；无远端重大天气时用 `.far.quiet`（白 16% 半透明）保留一句「暂无明显重大极端天气，临近时再提示」。
  - 实现：`alert_items(sNear, hourly48)` 走 `jozzonwx.grade_*` + `RAIN_ALERT_S / SNOW_ALERT_S / GUST_ALERT_S / WIND_ALERT_S / VIS_ALERT_S`、`UTCI_HOT_S/COLD_S`，**本文件不存阈值副本**；原 `alert_desc()` 保留但**页面已不再调用**（`check_rain_eng.py` 仍断言它，别删）。回归断言：按级别降序、只列达阈值要素、全未达返回空、体感取更严重一侧。
- **关键指标六格（2026-10-17 与物探 `#statsBox` 完全对齐，**唯一差别是不挂点名牌**）**：`kpi_stats_html(sNear, hourly48)` → `.stats > .stat × 6`，**2 列 × 3 行**，每格 `标题行 .k`（图标 + 要素名）+ 若干 `.vr` 行（`em` 子要素 / `b` 数值 / `i` 单位）。
  - 顺序与含义（与物探逐格同款）：① 累计降水（降雨 `totalPrecip` mm / 降雪 `h48_snow()` mm）；② 最大降水（降雨 `pHourMax` mm/h / 降雪 `snow_hour_max_48()` mm/h）；③ 最高气温（气温 / **同一小时**体感 `app_at_temp(h,"max")`）；④ 最低气温（气温 / 同时刻体感 `app_at_temp(h,"min")`）；⑤ 最大风速（阵风 / 均风 m/s）；⑥ 最低能见度（单行，无 `em`）。
  - ⚠️ **体感不能用 `appMax/appMin`**：那是整个 48h 窗口的体感极值（可能出现在别的小时），与「最高气温同时刻体感」可差 3~5℃；物探 `appAt()` 也是取 argmax/argmin 温度那一小时的体感，两线必须同法。
  - 图标底色仍走 `lv_rain / lv_temp / lv_gust / grade_vis`（19px 默认档），**无阈值副本**。原 3 列小卡 `.grid/.kpi`（48h降水 / 最大阵风 / 最大均风 / 最低能见度 / 最低体感 / 最高温）整套删除。
- **页头背景图（hero 背景层，2026-09-28 由物探技能移植）**：把 `.topbar` → `h1` → `.unit` → `.sub` → `.tabs` **整片**包进 `<div class="heroarea">`，照片作 `::before` **背景层**（`position:absolute; z-index:-1; isolation:isolate`），**不额外占版面**。
  - 资源 `assets/hero-bg.jpg`（**720×242 / JPEG q82 / 约 13KB**）。**工程侧用「野外钻井」实景图**（钻井井架 + 戈壁远景，**无储罐/油罐**），与物探侧的雪原勘探图**内容不同**；规格一致（720×242、q82、叠白 0.26 淡化，由 1536×1024 生成图裁切缩到 1/2，2026-09-29 定；初版 480×161 因太糊废弃）。`hero_css()` 读图 → base64 data URI，注入 `CSS` 之后（`<style>{CSS}{HERO_CSS}</style>`）。**无图时返回空串、静默降级为原样页头**（打印 `hero bg SKIPPED:`），不报错、不影响其余功能。
  - **`.tabs` 必须让位**：原 `.tabs` 是 `position:sticky; z-index:5; background:#f4f6f8`（不透明底色会盖住背景）。`hero_css()` 里用更高特异性 `.heroarea .tabs{background:transparent;position:static;}` 覆盖，背景才能连续铺到页签底部。
    ⚠️ **只覆盖 `background` 与 `position` 两项，`padding`/`margin` 必须原样保留**：早先版本连 padding 一起清掉（`padding:0;margin:10px 0 12px`），页签底边 195.4 → 183.4（上移 12px），属"引入的背景硬伤"。去掉这两行后页头 7 项布局指标与无背景图时逐像素一致。
  - 可在 `render_points_html.py` 顶部调：`HERO_BLEED`（出血量，现 `14px`，**必须严格等于页面左右内边距**）/ `HERO_POS_Y`（纵向取景）/ `HERO_FADE`（白色渐隐色标 `(位置, 不透明度)`，现 `("0%",".80") ("44%",".40") ("100%",".04")`）。
  - ⚠️ **`HERO_BLEED` 写错会带来横向可拖动（2026-09-28 修）**：原写成 `16px` 而实际内边距是 14px，多伸 2px → 手机端能左右拖 2px。改成 `14px` 后 360/430/768/1000px 溢出全为 0。
  - **改图后必须离线重渲染**才有新图（图是烘进 HTML 的 base64，见下方命令）。
- **气象要素小图标（2026-09-28，与物探侧同一套语义）**：**色块＝风险等级，图形＝要素本身**，一眼同时读出「是什么要素 + 有多危险」。六种内联 SVG：雨云 `rain` / 雪花 `snow` / 风线 `wind` / 温度计 `temp` / 太阳 `heat` / 雾线 `fog`。
  - 实现：`EIC`（path 数据字典）+ `eic(kind, lvl="plain", size="")` 生成 `<span class="eic …"><svg…></span>`；配色 `lv_rain/lv_gust/lv_wind/lv_temp` 分级函数，**阈值与 `RAIN_H`、卡片判据、`jozzonwx.grade_*` 保持一致，不许各写一套**。
    - **阵风 ≠ 均风（2026-10-17）**：同级上阵风风力比均风高两级（阵风八级 17.2 = 均风六级 10.8）。`lv_gust()` = ≥24.5 danger / ≥17.2 warn；`lv_wind()` = ≥17.2 danger / ≥10.8 warn。**不要再用 `lv_wind = lv_gust`**。
  - **`size` 三档及各挂载点的实际取值（2026-09-28 实测定的，别乱改）**：`"xs"` 13px → **作业影响建议每条**（空间最紧）；`"s"` 16px → **风险面板卡标题**、**48h 读数行 `#hval`**；`""` 19px → **关键指标六格 `.stat .k`**、**图表图例**。图标偏大就会撑高行盒或把临界文本挤到下一行（实测：影响建议用 16px 时单条 31→52px、整页 +29px；降到 13px 后手机端整页仅 +1px）。
  - ⚠️ **图标必然占宽，会吃掉行宽**：13px 图标 + 3px 外边距 = 16px，足以让「刚好一行」的长句换成两行（1000px 桌面端影响建议单条 31→51px）。这是引入图标的固有代价、非布局破坏；**手机端（主力场景）实测整页仅 +1px**。若想再压，不要去掉外边距（实测无效），应缩短文案。
  - **两套底色语义勿混**：`.ok/.warn/.danger`＝风险等级（用在 **关键指标六格 `.stat .k`**、**风险面板卡标题**、**作业影响建议每条**、**48h 读数行**）；`.plain` 灰＝只标要素不带风险（用在**图表图例**）。
  - **挂载点 5 处**：① **关键指标六格 `.stat .k` 标题行**（2026-10-17 由「数值行内」改到标题行：新结构每格有 2 行数值，图标画在数值行会重复）；② `risk_cards()` 渲染的 `.rc .rt`，要素由 `card_icon(title)` 按标题关键词映射、等级取卡自身的 `c[0]`；③ `impact_bullets()` 每条前缀，等级按**本条自身判据**独立计算（不跟随卡片口径）；④ 三处 `.legend`（降水类型图例经 `ptype_legend_html()` + 逐日气温图 + 逐日阵风/均风图），一律 `.plain`；⑤ `#hval` 48h 读数行 —— 此处在 `chart_js()` 的 **JS 里**，需另写一份 `EIC_PATH`/`eic()`/`lvR()`/`lvG()`，**随选时实时变色**。
  - ⚠️ **JS 侧写图标的坑**：`chart_js()` 用 Python 单引号拼 JS 字符串，插入的 SVG path **内部只能用双引号**（`d="M20 16.6…"`），否则与 Python 引号冲突；另外 Python 里 `//` 是整除运算符**不是注释**，别往里写 `// 中文说明`（会直接语法错误）——注释请单独成行的 Python `#`。
- **图表交互（2026-09-21 与物探看板对齐；`render_points_html.py`）**：
  - **无独立时间轴**：48 小时页原 `#hslider` 滑块**已整体移除**（连同 CSS 与 `slider.value` 联动）；改为**在 `#hchart` 上点击或拖动**即可选时刻（`pointerdown`/`pointermove` → `drag()` → `update(i)`），图上十字光标与三个要素标记点随动。
  - **⚠️ 48 小时图已去掉「能见度」（2026-10-16）**：图例、折线、`#hval` 读数行、图上 `g.hread` 数值框里的能见度全部移除；48h 只保留 **降水 / 气温 / 阵风 / 均风** 四个要素。能见度只在**未来 2 周**页出现（见 `dchart-vis`）。
  - **⚠️ `chart_js()` 载荷键必须是 `rainfall`（2026-10-16 修真 bug）**：此前载荷键被写成 `precip`，而 JS 全程引用 `CH.rainfall` → `undefined.concat` **TypeError → 整个 48 小时图一块都不画**（同页其它图正常，所以肉眼不易发现）。改键时务必对齐 Python 载荷与 JS 引用两侧。
  - **日期·时间粗体高亮**：`#hval` 内 `.t` 为 900 字重 / 14.5px / `#C0392B` 红字（**全页唯一时间读数**，格式「月-日 时:分」如「09-21 14:00」）。
  - **`#hval` 读数条在图表「上方」（2026-10-17 用户定，两线同款）**：DOM 顺序为 `h2 → .legend → #hval → svg#hchart`，CSS 相应由 `margin-top:8px` 改 `margin:0 0 9px`。改顺序时**不要**动 `chart_js` 里的 `valBox` 引用（按 id 取，与位置无关）。
  - **48 小时页说明行只留降水类型**：原「仅展示未来 48 小时（…起）。点击或拖动图表…（左轴/右轴…）」整段删掉，`.legend` 只剩「柱颜色＝降水类型：降雨 / 降雪 / 雨夹雪」（`ptype_legend_html()`）；**未来 2 周页删掉「点击任意图表选择日期…」那行 `.legend`**（图上点选行为保留，只是不写提示）。
  - **数值一律「深色粗体字 + 同色系浅底 pill」，顺序固定 降水 → 气温 → 阵风 → 均风**：`#hval` 四个要素值 —— 降水 `.pv`(#0D47A1 on #D8E9FA)、气温 `.tv`(#8A4B00 on #FBEAD3)、阵风 `.gv`(#8A2A0E on #FBE0D6)、均风 `.wv`(#0F5B4C on #D9EFE7)。**铁律：浅底 + 深色字，文字永远压在底色之上、不被覆盖**。
  - **图上数值框（2026-09-21 补，与物探 `#hourlyReadout` 对齐）**：仅在**图下方**读数还不够——48 小时图**内部**也画一个数值框：`chart_js()` 里新增 `g.hread`（白底红描边圆角框 `rect` + 4 行「标签 + 值」），每行的值再套一层同色系**浅底 pill**（`HTINT` 映射，**行序固定 降水 → 气温 → 阵风 → 均风**：降水 #D8E9FA / 气温 #FBEAD3 / 阵风 #FBE0D6 / 均风 #D9EFE7，字色 900 加粗）。由 `paintRead(i)` 在 `update(i)` 内每次调用重绘，**随光标实时移动**；位置 `bx = sx+12`，**靠近右边界自动翻到光标左侧**（`bx+bw>CH.right → sx-12-bw`），再夹到 `CH.left`；纵向 `by = CH.top+26`（避开顶部左右轴域标签）。列宽用 `cw()` 逐字估宽（CJK 13.6px / 其余 7.5px）自动计算。**图下 `#hval` 与图上 `g.hread` 同时保留**（物探同样是风险面板读数 + 图上读数框并存），两处数值由同一 `CH` 数据源驱动，**且行序必须同款：降水 → 气温 → 阵风 → 均风**。**「风速」「持续风」已统一更名「均风」**：48 小时图内图例（`txt(lg+134,...,"均风 m/s")`）与两处数值显示的标签均写「均风」；**未来 2 周逐日图亦已统一**（标题「逐日阵风 / 均风（m/s）」、图例与点选读数标签均写「均风」）。
  - **气泡字号（2026-10-17 用户定：两处统一放到 13.5px）**：48 小时图 `g.hread` 与两周图 `DAILY_JS` 的点选数值框，文字 `font-size` 由 `11.5` → **`13.5`**（行高 `lh` 16/15 → **18.5/17.5**，行间距 `pady` 6 → 7，pill 高 15/14.5 → **17.5**，外框 `rx` 6 → 7）。**`cw()` 的字宽估算必须同步放大（11.6/6.4 → 13.6/7.5）**，否则文字会撑出 pill 与外框。改完两处要么对齐、要么一起改，不留一大一小。
  - ⚠️ **改 `chart_js()` 的姿势**：新增/修改这些 JS 行时，**用 Python 脚本按"锚点行定位"插入**（如锚点 `svg.appendChild(cmT); ... cmG);` 之后插入 `g.hread` 定义、锚点 `valBox.innerHTML=` 行之后插入 `paintRead(i);`），且新增 JS **内部只用双引号**（`el("rect",{...})`），就能完全避开 Python 单引号转义坑；插完立即 `py_compile`。
  - **未来 2 周 = 固定四图（2026-10-16 用户定；原先的独立「逐日降雪图」`dchart-snow` 与「逐日体感图」`dchart-app` 已删除）**：
    ① `dchart-precip` 逐日降水（mm）—— **并列分组柱**：`svg_bars(..., extra=[("降雪", snow, "#5DD6E8")])`，同一天画「降雨蓝 + 降雪青」两根柱（`extra` 是本期为「降雪并入降水」新加的入参）；
    ② `dchart-temp` 逐日气温（℃）—— 最高温/最低温两条实线 + **最高体感/最低体感两条虚线且不逐点标值**（`svg_lines` 的系列元组第 4 项传 `{"labels":False,"dash":"6 4"}`；4 条线同时标值会互撞，点选日期时数值框仍给全值）；
    ③ `dchart-wind` 逐日阵风 / 均风（m/s）；
    ④ `dchart-vis` 逐日能见度（m）—— **两周保留能见度**（48 小时图已去掉）。
    **能见度数据源（2026-10-17 修正）**：后端 o1_ 系列**没有**能见度，实际用未文档化的 **`x1_visibility`**（`jozzonwx.FIXED_CODES` 钉死）；
    单位是 **km**（值域 0.68~16.0、上限封顶 16.0），`jozzonwx._num(..., scale=1000)` 统一转 **m**；
    **且只有前 162 小时有值**（第 7 天起为 null）。因此 `hourly.visibility` 与 `daily[].visMin` 无值处一律落 **None**（`build_points_data.var(..., keep_none=True)`），
    `svg_lines()` 遇 None **断开折线、不画点不标值**（`allv` 过滤非数值、分段 polyline），点选气泡显示「—（该日无数据）」；
    **绝不能把 None 落成 0**（会被读成「能见度 0 米」并画出断崖）。48h KPI/文案仍按 `if visMin is not None and >0` 取真实最小值。
    图例与标题：降水图注明「柱颜色＝降水类型」，气温图注明体感为虚线。**反向断言：`dchart-snow` / `dchart-app` 不应再出现在产物中。**
  - **未来 2 周图表可点选日期**：上述四个逐日图（`svg.dchart`）均由服务端预渲染（视觉不变），但把绘图元数据写入 `data-payload`（`kind`/`n`/`x0`/`x1`/`top`/`bot`/`w`/`unit`/`days`/`series`），由新增的 `DAILY_JS` 绑定点击 → 选中最近日期（**再点同处取消**），画红色竖线 + **浅底 pill 数值框**（`tintOf`/`deepOf` 同色系深浅配对），并在**「未来 2 周逐日天气」标题行的末尾内联**显示「已选 日期」黄底标签（2026-09-21 修订：`<span id="dayInfo">` 置于 `h2` 内，**不再单独占用一行**；标签类名 `.day-chip`，`#dayInfo:empty{display:none}` 保证未选日期时完全不占位、不占行高）。与物探侧一致（物探是把「已选」标签内联在 `#explorerInfo` 的点名·风险徽章之后，同样不单占一行）。柱状图索引按 `X(i)=x0+(x1-x0)*(i+0.5)/n` 反解、折线图按 `X(i)=x0+(x1-x0)*i/(n-1)` 反解，两者不可混用。**选日期只重绘竖线与数值框，图表 DOM 完全不重建**（图与界面不动，只换读数）。**系列上下位置固定「大值在上、小值在下」**（2026-09-21 修订）：气温图 `[("最高温",tmax,"#E0822C"),("最低温",tmin,"#2E7DA8")]`、风图 `[("阵风",gmax,"#C0392B"),("均风",wmax,"#7E57C2")]`（**「风速」更名「均风」**）。`svg_lines()` 的 `series` 顺序即 polyline 与圆点/数值标注的绘制顺序，同时写入 `data-payload.series`，故**点选读数框行序自动跟随**（最高温→最低温 / 阵风→均风），无需另改代码；HTML 侧对应标题与 `.legend`（最高温在前、阵风在前）须同步换序。物探侧对应 `ELEM_DEFS` 的 `keys/colors/labels` **三数组必须同时换序**。
  - **降水柱「有无 + 最小可见高度」铁律（2026-09-21 修订）**：`svg_bars()` 的 y 轴**基线恒为 0**——`vmin = 0.0`、`vmax = max(values+[1])*1.15`，**不可再用 `_scale(0, hi)`**：后者会把下界 pad 成负数（≈ -0.15×max），使 **0mm 也被画成约 13px 高的柱子**（用户报「降水为 0 却有个柱子」的根因）。柱体口径：**① `v<=0` 不画**（仅出日期标签）；**② `v>0` 时 `bh = max(y1-Y(v), 3.0)`**，保证小值 3px 最小可见高度；③ 柱顶标注小值保留一位小数（`v>=10` 用 `:.0f`，否则 `:.1f`），**避免 0.3mm 被标成「0」而更像「0 却有柱」**；④ 左侧刻度在小量程（`vmax<10`）用一位小数。48 小时图的降水柱（`chart_js()`，原本已有 `CH.precip[i]>0.05` 排除 0 值）同样补上 `Math.max(CH.bot-yP(...),3)` 的最小可见高度。**⑤ 例外（2026-09-21 起）**：判据放宽为 **`v>0 || ptype`** —— 降雪水当量四舍五入为 0.0mm 的日子仍保留 3px 柱以承载类型图标，柱顶数值标 **`<0.1`**；48 小时页同理 `CH.precip[i]>0.05 || CH.ptype[i]`。
  - **降水类型（降雨 / 降雪 / 雨夹雪）与柱内图标（2026-09-21 新增）**：取数 `HOURLY` 扩充为 `temperature_2m,precipitation,rain,showers,snowfall,wind_speed_10m,wind_gusts_10m`；**`rainfall = rain + showers` 为「降雨」规范口径**（在 `jozzonwx.fetch_hourly` 内合成；`rain` 不含阵雨），`snowfall` **现由 jozzon-mcp 直接给 mm/h**（2026-10-16 起；Open-Meteo 时代是 cm，**不要再做 cm→mm 的 ×10 换算**，代码里已按 mm 口径处理）。类型码 `0=无 / 1=降雨 / 2=降雪 / 3=雨夹雪`，判定 `ptype_of(liq, snow, pr, temp)`：**温度优先——`temp < 0℃` 一律判 2（降雪），液态分量不参与判型；只有 `temp ≥ 0℃` 时才可能判 3（雨夹雪）**；否则 两者兼有→3；仅雪→2；仅液→1；兜底（总量有值但分量皆 0，如冰粒）→1。逐时用该小时气温，逐日复判用「当日有降水时段的最高气温」（`pTempD`）。**（2026-10-16 起）柱高与降雪分列**——逐日降水图改为**并列柱**：第一系列取 `rainfall`（降雨）、第二系列取 `snowfall`（降雪），**不再把降雪折进降水柱**（旧口径 `precipitation` 含降雪水当量，会导致同一天既算进降水、又想单独看降雪而重复）；类型图例仍由 `ptype` 着色。**数据落点**：`build_points_data.py` 的 `hourly.{rainfall,snowfall,ptype}` 与 `daily[].{rainfall,snowfall,ptype}`（`rainfall` 已在脚本内由 `rain+showers` 合成，**不再单列 `rain`/`showers`/`liquid`**）。**渲染组件**（`render_points_html.py`）：`PT_FILL = {1:"#2E86DE"(蓝/降雨), 2:"#5DD6E8"(青/降雪), 3:"#B07CD6"(紫/雨夹雪)}` 与兜底 `PT_FILL_FB="#9DB4C8"`；`ptype_legend_html()` 改为输出**颜色块**图例；所有降水柱 `fill` 取 `PT_FILL[ptype]||PT_FILL_FB`，**不再画柱内图标**（`precip_icon_svg`/`ptype_icon_w`/`precip_icon_in_bar` 与 JS 端 `pIcon`/`pIconInBar` 已弃用）。**按类型着色（取代原柱内图标）**：逐日图 `svg_bars()` 与 48 小时图 `chart_js()` 的降水柱 `fill` 均取 `PT_FILL[ptype]||PT_FILL_FB`（降雨蓝 / 降雪青 / 雨夹雪紫），图标逻辑全移除；图例 `ptype_legend_html()` 输出颜色块。**读数处同步显示类型文字**：`#hval`、图上 `g.hread`（`paintRead`）、未来 2 周点选数值框（`DAILY_JS` 读 `p.ptypes[]`）的降水行都追加「降雨/降雪/雨夹雪」；两处图例（48 小时页 `.legend` + 未来 2 周降水图 `.legend`）追加 `ptype_legend_html()` 三项小图标。**已知限制**：48 小时图横轴铺满 **14 天全部小时（n=336）**，柱宽仅约 **1px**，图标尺寸必然 <3px 而被自动跳过（`if(H<3) return`）——该图的类型信息**只经读数框文字**呈现；逐日图（柱宽约 28px，在 680 宽的 svg_bars 里 `bw=(x1-x0)/n*0.55`）能正常显示三种图标。
- **风险聚焦近 2–3 天（核心口径）**：看板「重点关注」页顶部新增 **「近 3 天风险焦点」卡片**——取 `daily` 前 3 天，用 3 日累计降水 / 3 日最大单日降水 / 3 日最大阵风套用 `sev_of` 同款阈值定级（`sev_of_recent(daily[:3])`），并附一句「远端（第 4 天起）预报不确定性较大，临近时再提示」。`index.html` 顶层新增 **「近 3 天风险」汇总行**（同款等级计数 + 远端临近再提示说明）。**整窗（2 周）极值窗口仅作参考、不再单列为主风险提示**。理由：远端（第 4 天起）预报不确定性大、准确性下降，对外口径不夸大，仅作临近时再提示。
- ⚠️ **本脚本不再生成 `index.html`**。目录总览 index 已拆出为独立技能
  **`weather-engineering-index`**，请在渲染点位页后单独运行其
  `build_points_index.py` 生成 `engineering/html/index.html`。

> 与 weather-engineering-html 的差异：本脚本按 markdown 点位表批量出**无地图单页看板**（不再顺带出 index）；weather-engineering-html 出每井独立看板（其井位地图 index 也已拆到 weather-engineering-index）。两者数据互不依赖。

---

## 未来 2 天风险概要 / 目录总览 index —— 已迁出至 weather-engineering-index

> 「未来 2 天风险」50 字短描述生成（`gen_points_summary.py`）与**目录总览 index**
> （`build_points_index.py`）**已一并迁出到独立技能 `weather-engineering-index`**，
> 本技能不再包含 `gen_points_summary.py`，也不再生成 `index.html`。
> 用法详见该技能的 SKILL.md。
>
> **自动化**：`<SKILLS>/script/rerun_engineering.py` 在「取数 → 渲染点位页」之后，会依次调用
> `weather-engineering-index` 的 `build_points_index.py` 与 `gen_points_summary.py`，
> 生成 `engineering/html/index.html` 与 `engineering/fengxian_2tian_huizong.md`
> （取数沿用默认起始 **下一整点起**、**14 天 / 未来 2 周窗口**；
> 未来 2 天 = 窗口前 2 天，日期以真实窗口为准）。

---

## 校验脚本（2026-09-26 新增，改完必跑）

- `scripts/check_rain_eng.py` —— 小时级短时降水规则回归（纯 Python，直接 import `render_points_html`）：
  **第一组强制断言「阈值真源一致性」`RAIN_H == jozzonwx.RAIN_H == {heavy:3.0,storm:6.0,torrent:15.0}`**（分级集中在 jozzonwx，改阈值只改它）；随后
  降水卡边界（0/1.2/2.0/2.9→安全、3.0/5.0/6.0/9.9/12.0/14.9→注意、15.0/20→预警）、`rain_hour_label()` 四档、
  `sev_of_recent()` 边界（0/0.2→0；1.5/2.9/5.9→1；6.0/14.9→2；15.0/30→3 封顶）、日累计 25/50 旧判据未丢、
  `impact_bullets()` 三条短时条目、`_near_summary()`/`alert_desc()` 带 mm/h、`far_alert` 远端口径未被波及。
  加 `--render <看板.html>` 会再跑一遍页面级字符串断言（含 **48h 载荷键是 `rainfall` 而非 `precip`**、**48h 载荷无 `vis:`（能见度已移除）**、三条阈值线定义、`柱 降水 mm/h` 图例）。
- `scripts/check_rain_eng_page.js` —— jsdom 页面级（用法同物探侧 `test_touch.js`）：
  `NODE_PATH=<NODE_MODULES> <node> scripts/check_rain_eng_page.js <点位看板.html>`。
  断言：原样加载无运行期错误、`#hval` 用 mm/h、48h 载荷键为 **`rainfall`**；**把 48h 降水数组整体抬到 20mm/h**（量程覆盖 3/6/15）后，
  `#hchart` 应画出 **≥3 条** `stroke-dasharray="5 4"` 阈值线及其标签
  「大雨 3 / 暴雨 6 / 大暴雨 15 mm/h」，且选时后读数框仍是 mm/h。

## 工作流（agent 执行步骤）

**现行主链路（钻井点位看板，默认走这条）**：
1. `<SKILLS>/script/rerun_engineering.py` 一条龙：读 `engineering/kml/all_points_info.md` → 按 `engineering_ta_map.json` **逐个 ta_id 调 jozzon-mcp 取数**写 `engineering/data/{拼音}.json` → `render_points_html.py` 渲染 `engineering/html/{拼音}.html` → 调 `weather-engineering-index` 建 `engineering/html/index.html` 并出 2 天风险 md。
2. 只刷**单点**：用「临时 md」把点位缩到 1 个再跑 `build_points_data.py`，接着 `render_points_html.py --only <slug>`（详见上方《单点位增量重跑》）。
3. 交付前校验：`check_rain_eng.py`（Python 规则回归）+ `check_rain_eng_page.js`（jsdom 页面级）；如需浏览器级再用 playwright 截图或物探侧 `validate.py`（**判据：无 JS 报错、无「⚠ 链路预览」合成数据提示条、`body.sevN` 正常**）。
   ⚠️ **旧 schema 的 json 会让 `sev_of` KeyError 崩**（缺 `daily[].rainfall`）——单点重渲染请把目标 json 单独放临时 datadir，别整个 datadir 一起渲。
4. 用 `present_files` 交付 HTML。

**遗留链路（KML / 坐标区域图）**：按上方遗留脚本命令运行；运行后参照遗留说明用 Chrome 无头校验，再 `present_files` 交付。

## 关键实现要点（踩坑记录）
- **中文空白问题**：Chrome 无头模式在本机无法加载/嵌入系统中文字体，直接打印的 PDF 中文全空白。修复 = 用 fonttools 从 `Hiragino Sans GB.ttc` 提取字型，subset 到本页用到的汉字（~120KB），以 `@font-face` data-URI 内嵌进 HTML，字体栈首位 `CJKLocal`。务必保留这一步。
- **窄页**：Chrome DevTools Protocol `Page.printToPDF`，`paperWidth:4.5, paperHeight:11.5`（英寸），等效 Safari 把窗口调到最窄后导出。
- **CDP 连接**：启动 Chrome 加 `--remote-allow-origins=*`，端口 9333，host 优先试 `[::1]`（本机 Chrome 可能绑定 IPv6）。需先 `pkill -f remote-debugging-port` 清掉残留进程，否则端口被占。需 `websocket-client`。
- **代理干扰**：`no_proxy=*` 绕过 localhost 代理，否则 CDP HTTP 请求会被代理拦截返回 502。
- **要素**：现行取数走 **jozzon-mcp（九章雷电网）**，按 `ta_id` 调 `fetch_hourly`，**无 API key、无 Open-Meteo 配额/429 问题**。`timezone=Asia/Shanghai` 保证本地时间正确，页眉不显示时区（按用户要求）。（`--apikey` / `--model` 为 Open-Meteo 时代遗留参数，现无实际作用。）
- **降水字段与类型码（2026-10-16 更新）**：`hourly` 落 `temperature_2m` / **`rainfall`（= rain+showers，脚本内已合成）** / **`snowfall`（mm/h，jozzon-mcp 直接给，不要再做 cm→mm 的 ×10）** / `wind_speed_10m` / `wind_gusts_10m` / **`apparent_temperature`（UTCI 体感）** / **`visibility`（m）** / `ptype`。类型码 `0/1/2/3`＝无/降雨/降雪/雨夹雪（`ptype_of`：has_l、has_s 判分量；**`temp < 0℃` 一律判降雪，`temp ≥ 0℃` 才可能判雨夹雪**）。逐时与逐日都写进 JSON（`hourly.rainfall/snowfall/ptype`、`daily[].rainfall/snowfall/ptype`），渲染端仅做展示、不重新判定。
- **⚠️ `snow_hour_max_48()` 不再 ×10（2026-10-16 修潜在 bug）**：该函数（`render_points_html.py`）曾把 `hourly.snowfall` **乘 10**（Open-Meteo 时代降雪是 cm 的遗留），而现行 jozzon-mcp 的 `snowfall` **已是 mm/h**；×10 会把 0.2mm/h 的雪放大成 2.0 → `grade_snow` 判成 4 级「极强降雪」，**凭空冒出「高度警惕」**。现已改为直接取 `max(snowfall[:48])`，与 index 的 `peaks_48h()["snowHourMax"]`、物探 `build_dashboard` 的 `snowHourMax` **同源同值**。回归断言见 `check_rain_eng.py`（0.5mm/h → 0.5、空 → None）。**判雪前先确认数据量级**：`snowfall` 是 mm/h 不是 cm。
- **风速单位**：`wind_speed_unit=ms`（m/s）。阈值：6级≈10.8m/s、8级≈17.2m/s。
- **极端天气阈值**：高温≥35℃、低温≤0℃、**阵风≥24.5m/s(十级，预警) / ≥17.2m/s(八级，注意)**、持续风≥17.2m/s(八级) / ≥10.8m/s(六级)、日降水≥50mm(暴雨)/≥25mm(大雨)。连续降雨窗口取日降水≥10mm 的连续段。**阵风阈值 2026-10-17 上调两档**（同级比均风高两级风力：13.9/17.2/24.5/32.7），真源在 `jozzonwx._GUST_TH`。
- **小时级短时降水口径（2026-10-16 更新阈值，与物探 `weather-wutan-html` 完全对齐）**：**≥3 mm/h 大雨 / ≥6 mm/h 暴雨 / ≥15 mm/h 大暴雨**（对应标准「大雨预警(3mm/h) / 暴雨预警(6mm/h) / 大暴雨预警(15mm/h)」），**只作用于「未来 48 小时」口径**。常量 `RAIN_H={"heavy":3.0,"storm":6.0,"torrent":15.0}` **由 `weather-common/scripts/jozzonwx.py` 统一定义（全仓库唯一真源），脚本内不许自带阈值副本**；`rain_hour_label(v)`（文案四档：降水/短时大雨/短时暴雨/短时大暴雨）+ `phour_max(hourly48)`（从 `hourly.rainfall[:48]` 现算，上限 48 而非 336）。`main()` 在 `render_point()` 之前算好 `ph` 传入，不要在各个函数里重复算。改动落点：`sev_of_recent()`（`ph>=15` 或日累计≥50→2 级；`ph>=6`/`>=3` 或日累计≥20→1 级）、`risk_cards()`（`ph>=15` 或日累计≥50→预警；`ph>=6` 或日累计≥25→注意；`ph>=3`→「短时大雨 / 泥泞」注意；其余安全）、`impact_bullets()`（三条短时条目）、`recent_desc()`/`alert_desc()`（横幅与风险焦点带 mm/h 峰值）、`chart_js()`（48h 图三条阈值线，量程不够时不画）、48h 图 `#hval` 与图上数值框的降水单位 **mm → mm/h**。**「未来 2 周」逐日图与关键指标不变，仍是日累计 25/50mm，两套口径不许混用。**
- **429 限流（遗留·仅 Open-Meteo 旧脚本相关）**：旧取数路径 `http_get_json()` 曾带退避重试（5 次、指数退避）、预报 12 坐标/批。**现行 jozzon-mcp 取数按 `ta_id` 逐个调 `fetch_hourly`，无坐标批量、无 429**，此条仅存档（`build_region_dashboard.py` / `build_weather_dashboard.py` 等旧脚本仍走 Open-Meteo，保留其批量/退避逻辑）。
- **KML 解析**：Polygon 用射线法判断点在多边形内；LineString 读取 `<Placemark><name>` 作测线名（注意从正确元素取，避免显示"(未命名)"），沿测线按大圆距离等距采样。
- **页眉规范**：显示项目名 + 日期区间 + 生成日期，**不写时区、不写坐标、不写"离线看板"**；测线模式额外显示测线名与长度。
- **⚠️ `h2` 是 flex 容器，内联标签需处理「空占位」（2026-09-21）**：`.card h2 {display:flex; align-items:center; gap:7px;}`，故任何直接子元素（如 `#dayInfo`）都会成为 flex item——**即使内容为空，仍会吃掉一个 `gap:7px` 的间距**。往标题行内联「已选日期」这类可空标签时，必须配 `#dayInfo:empty {display:none;}`（`display:none` 的 flex item 不参与布局、不计 gap），并**不要再给标签加 `margin-left`**（间距已由 h2 的 `gap` 提供，否则与 gap 叠加成 ~16px）。自检：未选日期时 `getComputedStyle(#dayInfo).display === "none"` 且 `childNodes.length === 0`；标题所在节点的 `nextElementSibling` 应直接是 `.legend`（说明没有多出一行）。
- **⚠️ Python 里 `//` 是整除、不是注释（2026-09-28 踩过）**：往 `chart_js()` 的 JS 源码里补中文说明时，**绝不能写成 `'…'\n // 说明`** —— Python 会把 `//` 当整除运算符解析，报语法错误。注释必须另起一行用 `#`，或干脆不写注释。
- **⚠️ `assets/hero-bg.jpg` 是仓库资产，必须随技能一起同步（2026-09-28 踩过）**：漏同步时 `hero_css()` 找不到图会**静默降级**（页头无背景、不报错），肉眼很难判断是图丢了还是本来没做。判定技能是否完整：`weather-engineering-data/` 下应同时有 `assets/hero-bg.jpg` 与 `scripts/*.py`。改完技能跑同步脚本后，用 `git status --short` 确认图片显示为 `create mode`。
- **技能目录同构（2026-09-28 统一）**：两个看板技能均只有 **`SKILL.md` + `assets/` + `scripts/`** 三层，**没有独立的 `data/`**——页头背景图与运行时数据（`weather-wutan-html` 的 `cn_places.json` 地名库）都放 `assets/`，脚本统一用 `os.path.join(dirname(__file__),"..","assets","…")` 定位。工程侧不用地名库（`build_*` 全文无 `places`），故只有图片。别再往技能里新建 `data/`。
- **总览 index 也铺同一张背景（2026-09-28 加）**：`weather-engineering-index` 的 `build_points_index.py` 生成的 `engineering/html/index.html` 把「标题行 + `.sub`」包进 `.heroarea`（`.card`/`.grp` 是白底、**不再往 hero 区里放**，否则会盖住背景），**引用的是本技能的 `assets/hero-bg.jpg`，不另存一份**（三级探测：`BEIDOU_HERO_BG` > 本技能 `assets/` > `../weather-engineering-data/assets/`；找不到静默降级为纯色页头）。所以**只需维护本技能这一张图，index 会自动跟着变**。
  - index 的 `HERO_FADE` 比点位页**更白**（`("0%",".82") ("46%",".50") ("100%",".14")`）：钻井图下半部是深色沙地/钢构，照搬点位页那套底部只留 .04，会把「未来 2 周（14 天）…」那行压得发闷。
- **⚠️ `chart_js()` 内联 JS 字符串的单引号转义坑（2026-09-21 踩过两次）**：`render_points_html.py` 的 `chart_js()` 用 Python 单引号拼接 JS 源码，JS 里**每一处单引号都必须写成 `\'`**（含 `'</span>'`、`'℃</b>'` 这类续接处）。漏写会让 Python 字符串提前闭合，报 `SyntaxError: '(' was never closed`（指向函数首行 `return (`，极易误判）。**改这一段不要用编辑器手写转义**：推荐用 Python 脚本按"整行定位"替换，并用 `JQ = chr(92) + "'"` 显式构造；改完立刻 `python -m py_compile` 验签。

## 通用注意事项
- 数据来自 jozzon-mcp（九章雷电网）目标区预报，不含雷电要素（看板内有雷暴提示卡注明）。
- 山区小气候可能强于模式预报，看板底部建议以现场实测为准。
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
- **无 shell 专属依赖**：所有 Python 脚本只用标准库（`urllib`/`ssl`/`json`/`re` 等），不调用 `open` / `pbcopy` 等系统命令，Windows 上可直接运行。（旧 Open-Meteo 脚本若用到 `requests`，Windows 上按需 `pip install requests`。）
- **临时目录无关**：脚本内的临时文件（如 CDP 用户数据目录）统一走 `tempfile.mkdtemp()`，自动适配系统临时目录。
