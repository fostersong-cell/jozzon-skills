---
name: weather-wutan-data
description: 物探/野外项目2周天气看板生成器：输入由数据采集点构成的 KML（多个 <Placemark><Point>，如炮点/检波点），按采集点逐个从 Open-Meteo 拉取「下一整时起未来 2 周（14天）」逐小时预报（气温/降水/雨/阵雨/降雪/风速/阵风，m/s；并派生 liquid=rain+showers 与降水类型码 降雨/降雪/雨夹雪），生成关键指标 + 可点击地形图（采集点可联动展开未来2周逐要素曲线/柱状图）+ 物探作业影响建议的可交互中文 HTML（默认仅出 HTML）。兼容 KML 多边形边框（工区）与线要素（测线）。用于野外踏勘、钻井、地震勘探等项目的天气风险研判与汇报。
---

## 环境占位符（跨平台 · 首次使用请先确认）

本技能文档中的 `<WORK>` `<SKILLS>` `<BEIDOU>` `<PY>` `<NODE>` `<NODE_MODULES>` `<TMP>` 均为**运行时占位符**，须替换为本机的实际值。文档中不再出现任何某一台机器的固定路径，macOS 与 Windows 通用：

| 占位符 | 含义 | macOS 典型值 | Windows 典型值 |
|---|---|---|---|
| `<WORK>` | 工作区根（其下含 `beidou/`） | `~/Desktop/.../AI/work` | `C:\...\AI\work` |
| `<SKILLS>` | 技能根（本技能所在目录） | `<WORK>/.workbuddy/skills/jozzon/weather-wutan-data` | 同左 |
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

# 物探项目2周天气看板生成器（采集点版）

为物探 / 野外作业项目，生成未来**2周**天气看板（默认出**可交互 HTML**，窄页大字体、含中文、地形图着色），突出连续降雨窗口与极端天气，并给出物探作业影响与建议。核心模式为**采集点（Point）**：输入由数据采集点构成的 KML（多个 `<Placemark><Point>`，如炮点/检波点），**按采集点逐个**从 Open-Meteo 拉取「下一整时起未来 2 周（14天）」逐小时预报，不做网格采样。地图上的每个采集点可点击，地图下方同一卡片内立即展开该点未来2周的逐要素曲线/柱状图（要素可勾选叠加）。顶部仅保留一个「重点关注」卡片并按严重程度绿/黄/橙/红变色；随后是关键指标，最后是物探作业影响与建议。脚本兼容 KML 多边形边框（工区）与线要素（测线）两种旧模式。

## 输入模式

| 模式 | 输入 | 脚本 | 输出文件名 |
|------|------|------|-----------|
| **采集点（主）** | 项目名称 + KML 采集点（多个 `<Placemark><Point>`） | `build_region_dashboard.py` | `{名称}采集点.html`（+ 可选 `.pdf`） |
| **面（工区）** | 项目名称 + KML 多边形 | `build_region_dashboard.py` | `{名称}工区.html`（+ 可选 `.pdf`） |
| **线（测线）** | 项目名称 + KML 线要素 | `build_region_dashboard.py` | `{名称}测线.html`（+ 可选 `.pdf`） |
| **单点** | 项目名称 + 经纬度 | `build_weather_dashboard.py` | `{名称}{日期}.html`（+ 可选 `.pdf`） |

> 文件名规则：**`{项目名称}{当前日期}.pdf`**（单点）/ **`{项目名称}采集点{当前日期}.pdf`**（采集点）/ **`{项目名称}工区{当前日期}.pdf`**（面）/ **`{项目名称}测线{当前日期}.pdf`**（线）。当前日期取运行当天 `YYYY-MM-DD`。KML 自动识别：含 `<Point>` 且无 Polygon/LineString → 采集点模式；`<Polygon>` → 工区；`<LineString>` → 测线。

---

## 模式一：单点（项目名称 + 坐标）

```bash
<PY> \
  <SKILLS>/weather-wutan-data/scripts/build_weather_dashboard.py \
  --name "大关项目" --lat 27.91 --lon 103.87 --outdir "/您的输出目录"
```

坐标顺序：**纬度在前、经度在后**。输出：
- `{outdir}/大关项目2026-08-12.pdf`   ← 必交付物
- `{outdir}/大关项目.html`            ← 同数据离线 HTML（字体已内嵌，手机可打开）

## 采集点模式（主）：KML 采集点（Point），按点取数

```bash
<PY> \
  <SKILLS>/weather-wutan-data/scripts/build_region_dashboard.py \
  --name "大关项目" \
  --kml "/路径/采集点.kml" \      # KML 含多个 <Placemark><Point>（数据采集点）
  --no-pdf \
  --outdir "/您的输出目录"
```

KML 自动判断类型：
- **Point（采集点，主模式）**：KML 含多个 `<Placemark><Point>`（炮点/检波点等数据采集点），**直接按采集点逐个取数，不做网格采样**。地图为采集点分布的地形图（高程色带 + 山体阴影 + 等高线），每个采集点可点击联动展开该点未来2周逐要素曲线/柱状图。采集点名称取自 `<Placemark><name>`（缺省显示「采集点 #N」）。
- **Polygon（面/工区）**：按 `--grid` km 网格过滤落在多边形内的点，并加入质心。地图为多边形区域地形图。
- **LineString（线/测线）**：沿测线按 `--grid` km 等距取点，并加入起终点与测线中点。页眉显示测线名与长度 km。

统一流程：
1. 解析 KML（Point 采集点 / Polygon 边框 / LineString 测线），自动识别类型；计算范围（km）。
2. 采样点：**采集点模式直接用 KML 里的 Point 坐标（不采样）**；面 = 网格过滤 + 质心；线 = 等距采样 + 测线中点。采样密度由 `--grid` 控制（默认 6km，仅面/线生效）；点数超 `--maxpts`（默认 150）时自动加粗间距。
3. 用 Open-Meteo 多坐标接口分批拉取所有采样点预报（12 点/批，批间冷却，缓解 429）；可用 `--model ecmwf_ifs04` 指定 ECMWF 4km 高分辨率。**取数时间：下一整时起未来 2 周（14天）**（`start_date`/`end_date`）。每个点同时计算逐日 气温(min/max)/降水/风速/阵风 序列。
4. 按「区域/测线/采集点最坏情况包络」聚合：逐时最低温、最高降水、最大风/阵风；连续降雨窗口取各点逐日最大降水 ≥10mm 的连续段。
5. 极端天气分级（0绿/1黄/2橙/3红）：依据暴雨、8级风、高温、结冰、连续降雨累计等指标；顶部「重点关注」背景版据此变色。
6. 调用 Open-Meteo `/v1/elevation` 按自适应密度网格采样高程（地形大时自动放宽步长），分块请求（60 点/批）+ 退避重试，避免 414/429。
7. 输出交互式 HTML：canvas 地形图（高程色带 + 山体阴影 + 等高线），叠加风险区（红=高风险、橙=注意区），再压采集点/边框/测线/网格/比例尺/指北针；**每个采样点可点击**，点击后地图下方同一卡片内立即展开该点未来2周逐要素曲线/柱状图（气温=双线、降水=柱、风速/阵风=双线，要素可勾选叠加）。默认不导出 PDF（`--no-pdf`）。

参数：`--kml`（必填，Point 采集点 / Polygon / LineString）、`--grid`（面/线采样间距 km，默认 6，采集点模式忽略）、`--days`（预报天数，默认 14（未来 2 周），从下一整时起）、`--model`（可选）、`--maxpts`（采样点上限，默认 150，仅面/线生效）、`--no-pdf`（仅出 HTML）、其余 `--outdir/--apikey/--chrome` 同单点版。

---

## 工作流（agent 执行步骤）
1. 确认用户给出 `--name` 与（坐标 或 KML 文件）。坐标模式注意顺序 lat,lon。
2. 用上面的命令运行对应脚本（输出目录默认当前工作目录，可用 `--outdir` 指定）。
3. 运行后用 Chrome 无头加载生成的 HTML，捕获 console / `Runtime.exceptionThrown`，确认无 JS 报错；并用 `Runtime.evaluate` 模拟 `selectPoint(2)` 验证地图下方同一卡片内交互图能正常渲染（children 数 >0）。若 JS 报错，先用 `node --check` 抽出 `<script>` 定位语法错误。
4. 用 `present_files` 交付 HTML（默认）；如需 PDF，去掉 `--no-pdf` 重跑后一并交付。

## 关键实现要点（踩坑记录）
- **中文空白问题**：Chrome 无头模式在本机无法加载/嵌入系统中文字体，直接打印的 PDF 中文全空白。修复 = 用 fonttools 从 `Hiragino Sans GB.ttc` 提取字型，subset 到本页用到的汉字（~120KB），以 `@font-face` data-URI 内嵌进 HTML，字体栈首位 `CJKLocal`。务必保留这一步。
- **窄页**：Chrome DevTools Protocol `Page.printToPDF`，`paperWidth:4.5, paperHeight:11.5`（英寸），等效 Safari 把窗口调到最窄后导出。
- **CDP 连接**：启动 Chrome 加 `--remote-allow-origins=*`，端口 9333，host 优先试 `[::1]`（本机 Chrome 可能绑定 IPv6）。需先 `pkill -f remote-debugging-port` 清掉残留进程，否则端口被占。需 `websocket-client`。
- **代理干扰**：`no_proxy=*` 绕过 localhost 代理，否则 CDP HTTP 请求会被代理拦截返回 502。
- **要素**：Open-Meteo 免费接口无需 API key（脚本里带了一个做兼容）。`timezone=Asia/Shanghai` 保证本地时间正确，页眉不显示时区（按用户要求）。
- **降水字段与类型码（2026-09-21 扩充）**：`HOURLY` 取 `temperature_2m,precipitation,rain,showers,snowfall,wind_speed_10m,wind_gusts_10m`。语义：`precipitation`＝总降水(mm，含液态与降雪水当量)、`rain`＝雨(mm，**不含阵雨**)、`showers`＝阵雨(mm)、`snowfall`＝降雪(**cm**，与 mm 不同量纲，仅用于「有无降雪」判定)。**`liquid = rain + showers` 是「降雨」的规范口径**（两者单位同为 mm 可直接相加）。派生类型码 `0=无 / 1=降雨 / 2=降雪 / 3=雨夹雪`（`ptype_of(liq, snow, pr)`：has_l= liq>0.05、has_s= snow>0.01；两者兼有→3，仅雪→2，仅液→1，兜底总量>0.05→1）。两个脚本都已写入输出：`build_weather_dashboard.py` 的 `payload.hourly.{rain,showers,snowfall,liquid,ptype}`；`build_region_dashboard.py` 的 `per["liquid"]/per["ptype"]` 与逐日 `point_daily()["ptype"/"liquid"/"snow"]`。看板柱子类型图标由 `weather-wutan-html` skill 渲染。
- **风速单位**：`wind_speed_unit=ms`（m/s）。阈值：6级≈10.8m/s、8级≈17.2m/s。
- **极端天气阈值**（物探参考）：高温≥35℃、低温≤0℃、小时降水≥20mm、日降水≥50mm(暴雨)/≥25mm(大雨)、阵风≥17.2m/s(8级)、持续风≥10.8m/s(6级)。连续降雨窗口取日降水≥10mm 的连续段。
- **429 限流**：`http_get_json()` 带退避重试（5 次、指数退避）；预报 12 坐标/批、高程 60 点/批，批间 `time.sleep` 冷却。
- **KML 解析**：Polygon 用射线法判断点在多边形内；LineString 读取 `<Placemark><name>` 作测线名（注意从正确元素取，避免显示"(未命名)"），沿测线按大圆距离等距采样。
- **页眉规范**：显示项目名 + 日期区间 + 生成日期，**不写时区、不写坐标、不写"离线看板"**；测线模式额外显示测线名与长度。

## 通用注意事项
- 数据来自 Open-Meteo 公开接口，不含雷电要素（看板内有雷暴提示卡注明）。
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
- **无 shell 专属依赖**：所有 Python 脚本只用标准库 + `requests`，不调用 `open` / `pbcopy` 等系统命令，Windows 上可直接运行。
- **临时目录无关**：脚本内的临时文件（如 CDP 用户数据目录）统一走 `tempfile.mkdtemp()`，自动适配系统临时目录。
