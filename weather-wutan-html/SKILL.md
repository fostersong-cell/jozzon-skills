---
name: weather-wutan-html
description: 物探/野外项目2周天气看板「富媒体交互式 HTML」生成器，专注可交互单产物。输入 KML 工区(多边形)或测线(LineString)，自动从 Open-Meteo 拉取「当前日期起 2 周（14天）」逐小时预报（气温/降水/雨/阵雨/降雪/风速/阵风，m/s；并以 rain+showers=liquid 与 snowfall 判定「降雨/降雪/雨夹雪」，在降水柱内以雨滴/雪花/雨夹雪图标标出），生成带在线地形瓦片底图（Web Mercator，支持缩放与拖拽平移）的窄页大字体中文 HTML。三页签：【重点提示】按严重程度绿/黄/橙/红变色，风险口径聚焦**未来 48 小时**（远期第 3~14 天仅在出现重大极端天气时一句话提示）；【未来48小时】地图 + 点击联动逐小时要素合并图（单一图表：降水柱+均风/阵风/气温折线同图，可在图表上点击 / **按住自由滑动选时**、无独立时间轴，窗口 48 小时）；【未来2周】地图 + 滑动联动逐日要素曲线/柱状图（14 天，**图表同样支持按住自由滑动换日**）。无 PDF 依赖，中文字体子集内嵌，浏览器/手机直接打开（地形瓦片需联网加载）。用于野外踏勘、钻井、地震勘探等项目的天气风险研判与汇报。实时数据采集（KML 解析 + Open-Meteo 预报取数）的全部代码保留在脚本中，仅由脚本顶部 `FETCH_ENABLED` 开关控制是否执行，可临时关闭而不删除。
---

## 环境占位符（跨平台 · 首次使用请先确认）

本技能文档中的 `<WORK>` `<SKILLS>` `<BEIDOU>` `<PY>` `<NODE>` `<NODE_MODULES>` `<TMP>` 均为**运行时占位符**，须替换为本机的实际值。文档中不再出现任何某一台机器的固定路径，macOS 与 Windows 通用：

| 占位符 | 含义 | macOS 典型值 | Windows 典型值 |
|---|---|---|---|
| `<WORK>` | 工作区根（其下含 `beidou/`） | `~/Desktop/.../AI/work` | `C:\...\AI\work` |
| `<SKILLS>` | 技能根（本技能所在目录，用户级） | `~/.workbuddy/skills/jozzon/weather-wutan-html` | `%USERPROFILE%\.workbuddy\skills\jozzon\weather-wutan-html` |
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

# 物探项目2周天气看板（富媒体交互式 HTML）

为物探 / 野外作业项目，生成未来2周天气的**富媒体可交互 HTML 看板**（单一交付物，无 PDF）。核心特征：

- **地形图底图（在线地形瓦片）**：地图背景用**在线地形瓦片**（`server.arcgisonline.com/.../MapServer/tile/{z}/{y}/{x}`），Web Mercator 投影、按工区范围自动选 zoom（初始 6~17）、**支持缩放与拖拽平移**（见下方「地图缩放/平移」条）；**地图显示高度固定 280px（CSS `height:280px`，约手机屏 1/3），不随内容上下拉长**，宽度为容器实际宽（canvas 内部尺寸=显示尺寸，避免位图变形），工区/测线/采集点内容等比缩放居中、完整显示在框内。**瓦片铺满整个画布**：以视图中心 `Xc/Yc` 为基准反推墨卡托范围（`mx0=Xc-(W/2)/sc, mx1=Xc+(W/2)/sc, my0=Yc-(Hh/2)/sc, my1=Yc+(Hh/2)/sc`），整个画布都有地形背景（缩放/平移后同样铺满）。范围计算已纳入边框+采样点+附加测线。矢量层（边框/测线/采样点/风险区/指北针/比例尺）用 SVG 承载，避免被异步瓦片覆盖。**需联网加载瓦片**（无网时显示占位底色）；不再抓取 Open-Meteo 高程（省请求、避免 429）。页面不显示底图来源字样。
- **采样点联动（分属两个页签）**：点击任意采样点，**未来48小时页**地图下方显示单一合并风险面板（`#riskReason`）：① 当前小时风险等级徽章 + 当前时刻各要素值（**顺序固定：降水 → 气温 → 阵风 → 均风**，`.rr-valrow` 数值 900 加粗 + **各自浅色底 pill**，深色字叠在浅底之上、文字永不被底色盖住）；② 当前小时各风险要素清单（阵风/降水/高温等 + 处置建议，最高等级高亮，**不单列「主要原因」**以免与清单重复）；③ 四宫格要素级值（气温区间 / 阵风峰值 / 持续风峰值 / 日降水峰值及日期）；④ 若该时刻平静但全期存在更高风险，追加「全期最严重为 X（要素值）@ 时刻 —— 点击图表选时至该时刻可见」提示。地图选中点另显示紧凑标签（风险等级 + 主因值）。风险面板之**下**紧邻**逐小时要素合并图**（`#hourlyCharts`，**单个合并图**：降水柱 + 均风/阵风/气温折线同图，配色对齐石油工程——降水浅蓝分级柱、均风绿、阵风紫、气温蓝，顶部图例 4 项（降水/均风/阵风/气温），窗口＝未来 48 小时；**在图表上按下即选时、按住左右拖动可连续自由滑动选时**（`bindDragPick`，与石油工程 48 小时图同款 pointer 拖动），无需独立时间轴；**图上以 `#hourlyReadout` 数值框直接标出当前小时各要素值**（行序同为 降水 → 气温 → 阵风 → 均风），行内同款浅色底 pill）。选中不同采样点时**界面与文字一律不动**，只有两页要素图的**数据线·柱子**（`svg.chart .geo`）以 `riseIn` **自下而上淡入**重放，让用户一眼看出数据已变（`.ec` 级的整体动画已移除）。**未来2周页**同卡片内另有**逐要素曲线/柱状图**（`#explorerCharts`）：勾选 气温/降水/阵风·均风，绘制该点未来2周逐日 气温区间(线)、日降水(柱)、阵风/均风(线)，含 35°/0°、暴雨/大雨、6级/8级 阈值线；**每张图逐点直接标出数值**（最高温/最低温、阵风/均风、日降水，0mm 亦标「0」）——无需点选即可读数；**系列上下位置固定「大值在上、小值在下」**——气温：每日最高温在上、最低温在下；风：每日最大阵风在上、最大均风在下（`ELEM_DEFS` 的 `keys` 顺序即折线绘制/图例/读数框顺序，`colors`、`labels` 两数组必须同步换序）；**在图表上按下即选日期、按住左右拖动可连续自由滑动换日**（`bindDragPick` + `DAY_PICK`；轻点已选中的那天＝取消，位移 >2px 视为拖动、不触发取消），选中日以红色竖线标记，并在**图上直接显示该日各系列具体数值**（`drawValBox` 数值框，行序＝系列顺序：最高温→最低温、阵风→均风），`#explorerInfo` 追加「已选 日期」黄底标签；**选日期由 `paintDaySel()` 只重绘红色竖线 + 数值框，绝不重建图表**（图与界面完全不动，只换读数）。
- **地图朝向（真北朝上）**：地图**始终真北朝上**（上=北、纬度越高越靠上），**不按测线/工区走势旋转**；y 轴翻转使高纬度映射到画布上方。多边形若南北过长则**纵向压平**避免拉成竖条，但不改变真北朝上。始终带真北箭头：缩小并固定置于地图**右上角不显眼处**（小号红箭头 + 小号 N，克制不抢版面）。
- **地图缩放 / 平移（2026-09-21 新增）**：地图左上角有 `.mapzoom` 控件（＋ / 倍数 / － / ⟲ 复位），并支持**鼠标滚轮缩放**与**拖拽平移**（触屏单指拖动亦可），方便点选采集点。缩放档位 `ZSTEPS=[1,1.25,1.5,2,2.5,3,4,6]`（默认 1×）。实现要点：视图状态按 suffix 记忆于 `VIEW[suffix]={zi,cx,cy}`（`cx/cy`＝视图中心经纬度，`null`＝工区几何中心）；投影改为**以视图中心为原点** `xOf=W/2+(lon2x(lon,z)-Xc)*sc`、`yOf=Hh/2+(lat2y(lat,z)-Yc)*sc`，其中 `sc=scFit*kz`（`scFit`＝内容铺满的基础缩放，与档位无关）。瓦片层级随缩放提升（`z=z0+round(log2(kz))`，上限 17）以保持清晰。每次重绘记录 `PROJ[suffix]={z,sc,W,Hh,Xc,Yc}`；平移 `panBy` 按像素增量经墨卡托反算新中心。重绘会清空 SVG，故收尾调用 `redrawSelRing(suffix)` 补画选中环；拖拽结束置 `svg._justPanned`（80ms）抑制「点击选中最近点」，避免拖动误选。比例尺改固定贴左下（`bx=clamp(ox,8,W-8-barLen)`），高倍缩放时不会跑出画布。
- **点击图表选时（替代独立时间轴）**：未来 48 小时页**不再有滑块时间轴**。选中采样点后，在 `#hourlyCharts` 合并图上**按下即选中最近小时、按住左右拖动可连续自由滑动选时**（`bindDragPick` → `selectHour`；`touchAction:none` 保证触屏拖动不被页面滚动抢走），所有采样点按该小时风险实时重新着色（绿/橙/红），并同步更新风险面板内的**加粗日期·时间**（`.rr-cur .clk`——**全页唯一一处时间显示**，纯粗体红字、无底色框，格式「月-日 时:分」如「09-22 00:00」；**图表内原 `.rr-clock` 与面板重复，已整段删除**），同时刷新图上数值读出框（`#hourlyReadout`）。
- **图表「自由滑动选值」绑定器 `bindDragPick(svg, idxFn, apply, opt)`（2026-09-21 新增，对齐石油工程 48 小时图）**：48 小时图与未来2周的三张图**统一走这一个函数**，替换掉原先各自的 `click` 监听。
  - 事件：`pointerdown` 按下即 `apply(idx)`；`pointermove` 在按住态（或 `ev.buttons` 有值）连续 `apply`；`pointerup`/`pointercancel` 收尾。`pointerdown` 时 `setPointerCapture`（try/catch 包裹，jsdom 无此 API 也不报错）。
  - 触屏：绑定器内统一置 `svg.style.touchAction="none"`，否则手指拖动会被页面滚动/回弹抢走（对应石油工程 `#hchart` 的 `touch-action:none`）。
  - 索引反解 `idxFn(x,w)` 由各图按自身几何给出，**统一用 `getBoundingClientRect()`**（不用 `createSVGPoint`/`getScreenCTM`，一是不必依赖 SVG 矩阵、二是可在 jsdom 里 mock rect 直接测）：48 小时图 `(x/w*HW-HPL)/(HW-HPL-HPR)*(n-1)`；2 周图 `(x/w*W-pl)/(W-pl-pr)*(n-1)`（柱/线同式，因为 `pointBar` 与 `pointLine` 的 `X(i)` 完全一致）。结果 `Math.round` 后 `clamp(0, n-1)`，**拖出画布左右边界也会钳制**。
  - 取消语义（仅选日期用）：`opt.toggle` 为真时，`pointerup` 若**从未位移 >2px** 且**按下前**的选中值就等于按下那一格（`prevSel===startIdx`）→ `opt.cancel()`。**注意必须记录「按下前」的值**：`pointerdown` 里已经 `apply` 过新值，若在 `pointerup` 取当前值比较，则每次轻点都会立刻取消（踩过此坑）。48 小时选时无取消语义（不传 `toggle`）。
  - 拖动过程中**只重绘竖线/数值框、绝不重建图表**（2 周走 `paintDaySel()`；48 小时走 `selectHour` 内的 `updateHourlyMarker/updateHourlyReadout/updateReasonPanel/updatePoints`），因此按住拖动是连续平滑的，不会闪断。
- **要素勾选框默认状态**：地图下方 `.elem-row` 的 降水 / 阵风·均风 / 气温 三项**均默认 `checked`**（模板里 `<input ... checked>`），打开看板即全部显示；无需手动勾选。勾选框**从左到右顺序 = 降水 → 阵风·均风 → 气温**（与下方图表 `ELEM_ORDER` 一致，气温在最右），改模板 `.elem-row` 的 label 顺序即可调整。改动后可用 `--data` 离线重渲染套用新默认。
- **逐要素图表渲染顺序（固定）**：模板 JS 定义 `ELEM_ORDER = ["precip","wind","temp"]`，`selectedElems()` 按此固定顺序过滤勾选项，故图表恒为 **降水（柱）→ 阵风/均风（线）→ 气温（线，最下方）**，与勾选框 DOM 顺序解耦。此前曾用改 HTML 勾选框 DOM 顺序实现、重渲染会被模板还原，故改为模板常量驱动。
- **采样点面板位置**：`#riskReason`（未来48小时页）位于 `.mapbox` **之后**（旧的 `.timebar` 时间轴已移除）；`#elemRowD` + `#explorerCharts`（未来2周页）位于 `.mapbox` **之后**；均为地图下方普通流元素，与地图上下紧邻。
- **单一「重点关注」（未来 48 小时口径）**：顶部仅一个卡片，按**未来 48 小时**的极端天气严重程度 0绿/1黄/2橙/3红 变色（前端用 `DATA.meta.sevNear/sevLabelNear`；Python 侧 `P48` 与整窗 `P` 走同一套阈值函数 `_sev_of`）。描述以近 48 小时为主；**远期（第 3~14 天）只有出现"重大极端天气"才追加一句提示**（单日降水≥50mm 暴雨／阵风≥17.2m/s 8级／最高温≥35℃／最低温≤-5℃），否则以"临近时再提示"带过。
- **三页签布局**：① **重点提示**（重点关注预警 + 关键指标 + 物探作业影响与建议，三块**全部按未来 48 小时口径**，关键指标标注极值所在采样点）；② **未来48小时**（地形图 + 点击联动逐小时要素合并图；图表自由滑动选时、无独立时间轴，同卡片、紧邻）；③ **未来2周**（地形图 + 滑动联动逐日要素曲线/柱状图，14 天，图表可按住滑动换日）。
- **降水阈值分级 + 轴对齐**：降水柱状图阈值线按量级分级——单点最大值 <5mm 时只显示 5mm 参考线（y 轴上限取 5），≥5mm 时显示大雨 10mm 警戒线。横坐标与折线图完全一致（同 `X(i)` 公式 + 同抽稀步长 `ceil(n/7)`），三图底部日期标签对齐。
- **降水柱「有无 + 最小可见高度」铁律（2026-09-21 修订）**：柱高一律以 **零线 `base=Y(0)`** 为基线，**不可用 `Hh-pt-pb`** —— 它比零线小 22px（顶/底偏移之差），旧代码（`y=Y(v); h=Hh-pt-pb-y`）会令**柱高系统性少 22px、柱底悬空**，使量程内 <9mm 的降水全被 `Math.max(h,0.5)` 压成 0.5px 残线而肉眼不可见（用户报「很小的降水值没有柱子」的根因）。现口径：**① `v<=0` 直接 `return`，不画柱**（0mm 不再留 0.5px 残线，基线干净）；**② `v>0` 柱高取 `Math.max(base-Y(v),3)`**，小值也保证 3px 可见高度；③ 柱顶标注位置随之改为 `base-bh-5`。**48 小时页降水柱同口径**：`if(!(v>0))return;` + `h=Math.max(bottom-y,3)`（48h 的 `bottom=HH-HPB` 本就是零线，无上述偏移 bug）。**④ 例外（2026-09-21 起）**：判据放宽为 **`v>0 || ptype`** —— 降雪水当量四舍五入为 0.0mm 的日子（如「降雪 1.1cm但折算不足 0.1mm」）仍保留 3px 柱以承载类型图标，柱顶数值标 **`<0.1`**；48 小时页同理 `if(!(v>0)&&!pt0)return;`。
- **降水类型（降雨 / 降雪 / 雨夹雪）与柱内图标（2026-09-21 新增）**：取数 `HOURLY` 扩充为 `temperature_2m,precipitation,rain,showers,snowfall,wind_speed_10m,wind_gusts_10m`；**`liquid = rain + showers` 为「降雨」规范口径**（`rain` 不含阵雨，故单独相加），`snowfall` 单位是 **cm**（与降水的 mm 不同，仅用于「有无降雪」判定，不参与柱高）。类型码 `0=无 / 1=降雨 / 2=降雪 / 3=雨夹雪`，判定函数 `ptype_of(liquid, snow, precip)`：两者皆有 → 3；仅雪 → 2；仅液 → 1；兜底（总量有值但分量皆 0，如冰粒）→ 1，避免柱子无类型。**数据落点**：逐时 `points[].hx.{liq,snow,pt}`（仅前 48 小时）；逐日 `points[].series.{ptype,liquid,snow}`（当日累计后判定）。**柱高口径不变**——柱子高度仍取 `precipitation`（总降水，含降雪水当量），类型只作标注，这样**降雪日同样有柱**（若改用 liquid 则降雪日柱高为 0，自相矛盾）。**渲染组件**：`PT_FILL = {1:"#2E86DE"(蓝/降雨), 2:"#5DD6E8"(青/降雪), 3:"#B07CD6"(紫/雨夹雪)}` 与兜底 `PT_FILL_FB="#9DB4C8"`（未知类型灰蓝）；`ptLegendHtml()` 改为输出**颜色块**图例（`<i style="background:...">`）。所有降水柱 `fill` 直接取 `PT_FILL[ptype]||PT_FILL_FB`，**不再画柱内图标**；`precipIcon`/`ptypeIconW`/`precipIconInBar` 已弃用。**按类型着色（取代原柱内图标）**：未来48小时合并图与未来2周逐日图的所有降水柱 `fill` 取 `PT_FILL[ptype]||PT_FILL_FB`（降雨蓝 / 降雪青 / 雨夹雪紫），图标绘制逻辑已全部移除；图例 `ptLegendHtml()` 输出颜色块。**微量降雪仍保留柱**：`v>0 || ptype` 即画柱，柱高 `max(base-Y(v),3)`——否则「降雪 1.1cm 但水当量 0.0mm」的日子会因四舍五入丢柱、图标无处可挂；这类柱顶数值标 **`<0.1`**（真正无降水才标「0」浅灰）。**读数处同步显示类型文字**：未来 48 小时 `#hourlyReadout`、未来 2 周 `drawValBox`（`getRows` 里降水行 `降水 12.3 mm 雨夹雪`）；48 小时图与未来 2 周降水图图例都用 `ptLegendHtml()` 颜色块说明三项。**48 小时降水柱增高（2026-09-21）**：合并图降水绘图区占比由 `(bottom-HPT)*0.68` 提到 `*0.85`、轴富余 `pMax*1.15`→`*1.12`，柱更突出。
- **自包含**：中文字体子集内嵌为 data-URI，不依赖外部字体；手机/浏览器直接打开。
- **页头导航（2026-09-22 新增，2026-09-24 改版为左右分置）**：项目页 `<header>` 顶部 `.hdnav` 为 `display:flex;justify-content:space-between` 的左右两栏，含两个**相互独立**的链接——① 左栏 `.hdnav-l`（`flex:1 1 auto`）放 `a#backLink`（"← 返回总览"，`href="index.html"` 指向本类子总览，仅当 URL 带 `?from=index` 时显示，否则内联 JS 隐藏；**左栏常驻占位，故回链隐藏时右栏不会左移**）；② 右栏 `.hdnav-r`（`flex:0 0 auto`）放 `a.extlink` **高亮外链**（常驻显示，文本"北斗天气风险治理平台 ↗"，`href="https://leidian.wang"`，新窗口打开）。两者不是同一链接，互不影响。

## 三种输入模式（本 skill 统一走 region 脚本）

| 模式 | 输入 | 识别方式 | 输出文件名 |
|------|------|----------|-----------|
| **面（工区）** | 项目名称 + KML 多边形 | `<Polygon>` 边框 | `{pinyin}-gongqu.html`（如 `nanzhengsanwei-gongqu.html`） |
| **线（测线）** | 项目名称 + KML 线要素 | `<LineString>`（开放线） | `{pinyin}-cesian.html`（如 `leshanerwei-cesian.html`） |
| **多线（多条测线）** | 项目名称 + KML 含多个 `<Placemark><LineString>` | 多个 `<LineString>` | `{pinyin}-cesian.html` |
| **闭合线工区** | 项目名称 + KML **闭合** `<LineString>`（首尾点相同，如「排列闭合线」） | **自动识别为面**；或显式 `--face` 强制 | `{pinyin}-gongqu.html`（如 `qitaizhuang-sanwei-gongqu.html`） |
| **边框 + 采集点** | 项目名称 + 边框 KML（`--kml`）+ 采集点 KML（`--points`，含多个 `<Placemark><Point>`，如炮点/检波点/预警点） | `--kml` 给 Polygon、`--points` 给 Point | `{pinyin}-gongqu.html`（如 `tongjiang-sanwei-gongqu.html`） |

> **文件名规则（拼音命名）**：统一用**拼音字母**命名（避免中文在 CDP 预览 / 系统间传输的编码问题），格式 `{pinyin}-gongqu.html` / `{pinyin}-cesian.html`（不附加日期，重跑即覆盖同名文件）；配套 `_data.json` 同名前缀：`{pinyin}-gongqu_data.json`。脚本默认输出中文名，需用 `--outfile` 指定拼音名（见下方工作流）。
> **多线合并**：一个 KML 里放多条 `<Placemark><LineString>`（各带 `<name>`），脚本自动识别为「多线」模式，把多条测线**在同一张地图里一起展示**、各自等距采样、各标一条中点；标题与页眉用「+」连接各测线名。单线模式行为完全不变。
> **采样点标签（统一用 KML 名）**：所有模式的**地图采样点文字标签**一律使用 `DATA.points[].loc`（来自 KML 采集点文件中的 `<name>`，如「东线中心点」「西北点」；线/面模式则为程序生成的距中心/距北端/中点描述，如「东线 中点」）。**不再显示 `#1`、`#2` 之类的编号**。风险原因面板（#riskReason 的 `.rr-h`）与逐点曲线标题（#explorerInfo）也统一以 `loc` 为标题，不再带 `#编号` 前缀。改动见 `build_dashboard.py` 的 `renderMap`（地图标签 `lab.textContent = pt.loc || fallback`）、`updateReasonPanel`、`renderExplorer`。
> 单点（仅经纬度、无地图联动）与「纯采集点 KML」（只含 Point、无边框）场景不在本 skill 范围，请使用 `weather-wutan-data` skill。
> **边框 + 采集点（--points）**：边框用 `--kml`（Polygon），采集点 KML 用 `--points` 传入（一个含多个 `<Placemark><Point>` 的 KML 文件）。**采样点直接用采集点坐标取数**（不做面网格采样）；地图同时渲染边框（黑色实线）+ 采集点（可点击，标签显示采集点名）；采集点是真实数据位置、**无「中心」标记**（isCenter 恒为 False）。例：通江三维（`通江三维边框.kml` + `通江三维预警点.kml`）。

## 离线重渲染（--data，不取数）

已抓过数据的看板，只改页面布局/样式时，用 `--data` 直接读取**已抓取的 DATA JSON**，跳过 KML 解析与所有接口调用，秒级重渲染：

```bash
<PY> \
  <SKILLS>/weather-wutan-html/scripts/build_dashboard.py \
  --name "乐山二维" \
  --data "/路径/乐山二维工区_data.json" \   # 由历史 HTML 提取的 DATA（见下）
  --outdir "/您的输出目录"
```

- `--data` 与 `--kml` 二选一：给 `--data` 时 `--kml` 可省略。
- DATA JSON 来源：实时取数（`--kml`）时脚本会**自动另存** `<name>_data.json` 到 `--outdir`（默认开启，可用 `--no-save-data` 关闭）；也可从历史 HTML 中抽取 `const DATA = {...};` 得到。本仓库交付时每份 HTML 都附带对应的 `_data.json`。
- 适用：只调页面布局/交互、不更新天气数据时的快速重渲染，避免重复请求触发 Open-Meteo 429 限流。

## 实时取数开关（FETCH_ENABLED）

数据采集的**全部代码（KML 解析 + Open-Meteo 预报拉取）均保留在 `build_dashboard.py` 中，未被删除**，仅由一个脚本顶部的开关控制是否执行，可随时恢复：

```python
# build_dashboard.py 顶部
FETCH_ENABLED = True    # True=启用实时取数；False=暂时关闭（离线 --data 模式不受影响）
```

- **当前默认 `True`（启用实时取数）**：脚本 `build_dashboard.py` 顶部 `FETCH_ENABLED` 当前为 `True`，可直接 `--kml` 实时拉取。若遇 Open-Meteo 429 限流，可临时改回 `False` 并用已抓取的 `_data.json` 走 `--data` 离线重渲染。
- 运行 `--data <已抓取DATA.json>` 走离线模式，**不受该开关影响**，始终可用。
- 需要恢复实时取数时：把 `FETCH_ENABLED` 改回 `True`，再用 `--kml` 运行即可。若 `FETCH_ENABLED=False` 且未给 `--data`，脚本会打印明确提示并退出，不会静默失败或误触网络。

---

## 用法

```bash
<PY> \
  <SKILLS>/weather-wutan-html/scripts/build_dashboard.py \
  --name "大关项目" \
  --kml "/路径/炮点边框.kml" \     # 多边形 → 工区；LineString → 测线（自动识别）
  --grid 20 \                      # 采样间距 km，默认 20（面/线统一距离间隔；线超 15 点自动均匀取 15）
  --outdir "/您的输出目录"
```

复合工区（边框 + 多条测线，如大关：区块边框 + 北/南/中线）：
```bash
<PY> \
  <SKILLS>/weather-wutan-html/scripts/build_dashboard.py \
  --name "大关项目" \
  --kml "/路径/区块边框.kml" \            # 工区边框（Polygon）
  --lines "/路径/北线.kml,/路径/南线.kml,/路径/中线.kml" \   # 逗号分隔的附加测线
  --outdir "/您的输出目录"
```
> 注：`--kml` 实时取数需脚本顶部 `FETCH_ENABLED=True`；当前默认即为 `True`（可直接实时拉取）。布局/样式调整请用已抓取的 `_data.json` 走 `--data` 离线重渲染。若遇 Open-Meteo 429 限流可将 `FETCH_ENABLED` 临时改回 `False` 离线重渲染。

脚本自动判断 KML 类型：
- **Polygon（面/工区）**：在边框包围盒内按细步长(~G/10)铺细网格筛出所有落在多边形内的候选点，再用**最远点采样**挑出间距≈`--grid`(默认20km)的代表点——先取离质心最近的点，再迭代加入离已选集合最远的候选，直到该最远距离 < 0.75·grid。**每个采样点都严格落在工区内**、间距均匀≈20km；对规则矩形≈网格、对斜向/不规则工区也能均匀覆盖。面采样**不限个数**（不启用 `--maxpts` 上限加粗）。地图采样点标记已放大（圆点 r=9~11、编号字号 13，约一个汉字大小），便于查看。
- **复合工区（边框 + 多条测线）**：主 KML 用 `--kml` 给工区边框（Polygon），其余测线 KML 用 `--lines "a.kml,b.kml,c.kml"`（逗号分隔）传入。地图**同时渲染边框与所有测线**（测线以彩色虚线描边），但**采样点严格只落在边框多边形内**——附加测线仅用于展示、不参与采样（此前测线向东溢出边框导致采样点跑到工区外，已修正）。例：大关项目（区块边框 + 北/南/中线）。
- **⚠️ 外框渲染铁律（`borderSvg()`）**：复合工区（polygon + lines 同时存在）**必须先画 `DATA.polygon` 外框**（真 Polygon 强制加 `Z` 闭合），再处理测线。**严禁**写成 `if(DATA.lines){ 只画 lines; return; }`——这会让外框被整段跳过、地图上只剩测线，外框「消失」（大关的「大关区块边框」曾因此丢失）。测线统一由 `DATA.dataLines` 以彩色虚线渲染；`borderSvg` **仅在 `!DATA.dataLines` 时**（纯测线项目，如藏北天山/羌塘）才代画线骨架，避免同一批线被画两遍。
- **闭合 LineString → 自动按面（工区）处理**：若 KML 是 `<LineString>` 但**首末坐标相同（首尾相连，含 1e-6 容差）**，脚本自动将其当作工区多边形边界，按面采样（如「奇台庄三维」排列闭合线）。也可用 `--face` 显式强制；反之 `--line` 可强制仍按测线处理（绕过闭合识别）。
- **LineString（线/测线）**：沿测线按 `--grid` km **沿弧长等距取点**（跨顶点正确累计：消耗完一段后将 `prev` 推进到该顶点，避免跨段弦长捷径导致间隔不均），包含起点；终点仅在距上一采样点 > 0.4·grid 时才补入（避免尾部过短段）。**测线中点不额外插入**，而是标记距弧长中点最近的已有采样点为「测线中点」（避免与等距点重叠出现 2km 异常）。页眉显示测线名（取自 KML `<Placemark><name>`）与长度 km。；**测线采样点总数封顶 15 个**，若按 20km 间隔算出的点数超过 15，则自动改为全线（含均匀 15 点，间隔随之放宽）。

区域版统一流程：
1. 解析 KML（Polygon 或 LineString），计算工区范围 / 测线长度（km）。
2. 采样点：多边形在边框包围盒内铺细网格筛候选 + **最远点采样**挑间距≈20km 的代表点（严格落在多边形内、均匀≈20km；复合工区的附加测线仅展示、不参与采样）；测线沿弧长等距采样 + 标记最近的已有点为测线中点（不额外插入，避免重叠）。采样间隔由 `--grid` 控制（默认 20km 距离间隔，面/线统一）；**测线点数超过 15 个时自动改为全线均匀取 15 个**；**面（工区）/复合工区按 20km 间隔全区域采样、不限个数，不启用 `--maxpts` 加粗**；仅线在极端情况下点数进一步超过 `--maxpts`（默认 150）时仍会加粗间距兜底。
3. 用 Open-Meteo 多坐标接口分批拉取所有采样点预报（12 个点/批，批间冷却，缓解 429）；可用 `--model ecmwf_ifs04` 指定 ECMWF 4km 高分辨率（失败自动回退默认融合模型）。每个采样点计算逐日 气温(min/max)/降水/风速/阵风 序列（14 天，供「未来2周」页交互查询），并计算**近 48 小时**逐点极值与**逐小时明细（仅保留前 48 小时**，供「未来48小时」页与 t1 重点提示）。
4. 按「区域/测线最坏情况包络」聚合：逐时最低温、最高降水、最大风/阵风；连续降雨窗口取各点逐日最大降水 ≥10mm 的连续段。
5. 极端天气分级（0绿/1黄/2橙/3红）：依据暴雨、8级风、高温、结冰、连续降雨累计等指标；顶部「重点关注」背景版据此变色。
6. （地图底图）地图背景用**在线地形瓦片**（Web Mercator 投影，按工区范围自动选 zoom 6~15，固定视图不缩放；URL `server.arcgisonline.com/.../MapServer/tile/{z}/{y}/{x}`），**需联网加载**；不再抓 Open-Meteo 高程（省请求、避免 429）。
7. 输出交互式 HTML：canvas 瓦片底图 + **SVG 矢量覆盖层**（边框/测线/采样点/径向渐变风险区/比例尺/指北针，矢量全放 SVG 避免被异步瓦片覆盖）；**每个采样点可点击**，点击后地图下方同一卡片内展开该点未来2周逐要素曲线/柱状图。降水图阈值线按量级分级（<5mm 显示 5mm 参考线 / ≥5mm 显示大雨 10mm 警戒线），且横轴与折线图抽稀对齐。

参数：`--kml`（Polygon 或 LineString；与 `--data` 二选一，给 `--data` 时可省略）、`--data`（已抓取 DATA JSON，离线重渲染，跳过取数）、`--grid`（采样间距 km，默认 20，面/线统一距离间隔；测线超 15 点自动均匀取 15）、`--model`（可选，如 `ecmwf_ifs04`）、`--maxpts`（采样点上限，默认 150；**仅对线生效**作兜底，面不启用——面始终 20km 全区域采样、不限个数）、`--outdir/--days/--apikey` 同前。

---

## 工作流（agent 执行步骤）

1. 确认用户给出 `--name` 与 KML 文件（Polygon 或 LineString）。
2. 用上面的命令运行 `build_dashboard.py`，**HTML 输出到 `html/` 子目录**（`<WORK>/html/`）、`_data.json` 归到 `data/` 子目录，并**用拼音命名**（`--outfile`）。示例（南郑三维工区）：

   ```bash
   <PY> \
     <SKILLS>/weather-wutan-html/scripts/build_dashboard.py \
     --name "南郑三维" \
    --kml "/.../南郑三维项目边框.kml" \
    --grid 20 \
     --outdir "<WORK>/html/" \
     --outfile "nanzhengsanwei-gongqu.html"
   ```

   > 工作区根即 Workspace 目录（非同步空间项目子目录，避免云盘缓存回收）。目录约定：HTML 看板（含 `index.html` 总览）放 `html/`，`_data.json` 放 `data/`。**`_data.json` 一律用拼音命名**（如 `tongjiang-sanwei-gongqu_data.json`），便于 `--data` 离线复用。
   > - **实时取数模式（无 `--data`）**：脚本会把 `_data.json` 按中文 `args.name` 写到 `--outdir`（与 HTML 同目录），生成后需 `mv` 到 `data/` 并改名为拼音（覆盖同名原文件）。**切勿让中文名 `_data.json` 留在 `html/`**。
   > - **离线重渲染模式（`--data <已有json>`）**：已修复——**不再落盘 `_data.json`**（输入本身就是数据文件，重复写出会按中文名污染 `html/`）。日常补 UI/模板小改后，用 `--data data/<拼音>_data.json` 重渲染 `html/` 即可，零 API 消耗、不产生中文数据文件。
3. **默认轻量自检（零消耗、必做）**：生成后只做结构校验，**不启动 Chrome / 不跑 CDP**，避免无谓的算力与积分消耗。两步即可：
   - 解析 HTML 内嵌的 `const DATA = {...};` 块为 JSON，确认可解析、且 `meta.name`/`kind`/`start`/`end`/`npts`/`points`/`peaks`/`hourly` 齐全；
   - `grep` 关键符号是否就位：`function selectPoint`、`id="riskReason"`、`id="explorerCharts"`、`id="hourlyCharts"`、`function renderMap`、`ELEM_ORDER`、`class="backlink"`（返回按钮）、`value="wind" checked`（风速默认勾选）、`data-tab="t2">未来48小时`、`data-tab="t3">未来2周`、`peaksNear`（48 小时聚合）、`farAlert`（远期重大天气）。
   两者通过即视为交付合格。**这套检查本机 headless Chrome 在该沙箱内 CDP 不稳（会 `neterror`），故不应作为默认门禁。**

4. **（可选，仅显式要求时跑）重型 Chrome 验证 `validate.py`**：只有在用户明确说"跑一下验证/质量门禁"时才启动无头 Chrome 做 CDP 校验（无 JS 报错、`selectPoint` 联动图渲染、`#riskReason` 的 `.rr-peaks`/`.rr-cur`/`.rr-sev` 就位、`body.sevN` 挂载）。时间轴 / 北箭头等交互可单独验证。注意该脚本依赖本机可用 Chrome，`file://` 路径不要二次 URL 编码。
5. 用 `present_files` 交付 HTML。

## 关键实现要点（踩坑记录）

- **中文空白问题**：本机无头渲染若不内嵌字体，中文会空白。脚本用 fonttools 从 `Hiragino Sans GB.ttc` 提取字型，subset 到本页用到的汉字（~120KB），以 `@font-face` data-URI 内嵌，字体栈首位 `CJKLocal`。务必保留这一步（失败会优雅降级为空 font-face，依赖系统字体）。
- **代理干扰（仅显式跑 validate.py 时相关）**：`validate.py` 内 `no_proxy=*` 绕过 localhost 代理，否则 CDP HTTP 请求被代理拦截返回 502。
- **CDP 连接（仅显式跑 validate.py 时相关）**：`validate.py` 启动 Chrome 加 `--remote-allow-origins=*`，端口 9333，host 优先试 `[::1]`。需先 `pkill -f remote-debugging-port` 清掉残留进程，否则端口被占。
- **要素**：Open-Meteo 免费接口无需 API key（脚本里带了一个做兼容）。`timezone=Asia/Shanghai` 保证本地时间正确，页眉不显示时区。
- **风速单位**：`wind_speed_unit=ms`（m/s）。阈值：6级≈10.8m/s、8级≈17.2m/s。
- **极端天气阈值**（物探参考）：高温≥35℃、低温≤0℃、**小时级短时降水 >2(大雨)/>5(暴雨)/>10mm/h(大暴雨)**、阵风≥17.2m/s(8级)、持续风≥10.8m/s(6级)。连续降雨窗口取日降水≥10mm 的连续段。
- **小时级短时降水规则（2026-09-26 用户定，48 小时口径，勿再退回日累计）**：**>2mm/h 大雨、>5mm/h 暴雨、>10mm/h 大暴雨**。落地位置（两处口径**不得混用**）：
  - **48 小时口径（本规则）**：`RAIN_H={heavy:2,storm:5,torrent:10}`（JS 顶层，Python 侧同名 `RAIN_H`），用于 `riskClassAtHour()`（≥5→danger、≥2→warn）、`riskFactorsAtHour()`（要素名「短时大雨/短时暴雨/短时大暴雨」、单位 `mm/h`）、48h 逐小时图阈值线（**大雨 2 / 暴雨 5 / 大暴雨 10**，原来是日累计 25/50，与纵轴口径不符已改）、48h「影响说明」降水卡片（`PN.pHourMax`）、`_sev_of()` 近 48h 等级（≥10→2 级、≥5→1 级）。
  - **未来 2 周逐日口径（沿用旧规则）**：日累计 ≥25 大雨 / ≥50 暴雨 / ≥80 暴雨量级，用于 `farAlert`、逐日图阈值线（25/50）、2 周关键指标「最大日降水」。
  - `peaksNear.pHourMax / pHourAt / pHourPoint` 由 `points[].hx.precip` 现算，**回填代码必须写在 `if args.data:` / `else:` 两个分支之外**（模块级）——离线模式 payload 来自 `json.load`，写在实时分支里离线重渲染永远没有这个字段。
- **429 限流**：`http_get_json()` 带退避重试（5 次、指数退避）；预报 12 坐标/批，批间 `time.sleep` 冷却（地形瓦片走浏览器端网络，不经此限流）。
- **地形瓦片底图（替换原高程自绘地形）**：地图背景改用在线地形瓦片（ArcGIS World Topo）。投影改 Web Mercator：`xOf=ox+(lon2x(lon,z)-px0)*sc`、**`yOf=oy+(lat2y(lat,z)-py0)*sc`（`py0=lat2y(maxlat,z)` 为北边墨卡托 y，最小）**（`lat2y` 用墨卡托公式 `(1-ln(tan(π/4+φ/2))/π)/2*2^z*256`）；zoom 按工区经度跨度自动选（`z=round(log2(680*0.7/256*360/Δlon))`，限 6~15）。**范围计算要纳入 边框 + DATA.points + DATA.dataLines**（否则复合工区测线/采样点会被裁掉）。**地图显示高度固定 280px（CSS `.mapbox{height:280px}`，约手机屏 1/3），宽度=容器实际宽：`W=Math.round(mapbox.clientWidth)||680`，canvas 内部尺寸与显示一致避免位图变形；内容等比缩放居中（`sc=min((W-2pad)/mw,(Hh-2pad)/mh)`，`ox=(W-DW)/2, oy=(Hh-DH)/2`）**。**地图渲染封装为 `renderMap(suffix)`（suffix=`"2"`=日级概览、`"3"`=小时数据，非 IIFE 自执行）**：两张地图各自初始 `display:none`、容器宽=0，切到对应 Tab 时才调用 `renderMap(suffix)` 按实际宽度重绘；svg 空白点击监听用 `svg._mapClick` 防重复绑定。瓦片 img 用 `new Image()` + `crossOrigin="anonymous"` 异步加载、`drawImage` 到 canvas，**瓦片纵坐标 `sy=oy+(ty*TILE-py0)*sc`（瓦片顶边墨卡托 y=ty*TILE）**；**矢量/风险区全放 SVG 层**（风险区用 SVG `radialGradient`，避免被异步瓦片覆盖）。**测线不强制闭合**：`borderSvg()` 只在多边形/线**本身首尾相同**（容差 1e-6，真闭合如工区边框、闭合线转面）时才追加 `Z`，开放的测线（含「测线+采集点」模式）不闭合起点终点——切勿用 `DATA.isLine` 判断（points 模式下 isLine=False 会误闭合测线）。比例尺 px/km = `256*2^z/(360*111*cos(lat0))*sc`。瓦片需联网，无网显示占位底色；不再抓 Open-Meteo 高程。
- **KML 解析**：Polygon 用射线法判断点在多边形内；LineString 读取 `<Placemark><name>` 作测线名（注意从正确元素取，避免显示"(未命名)"），沿测线按大圆距离等距采样。
- **测线采样间隔不均的坑**：线要素采样若用 `while` 沿顶点推进，当某段 `acc+seg < G` 时**必须把 `prev` 推进到当前顶点再 `i+=1`**；否则下一轮 `distkm(prev, line[i+1])` 会变成跨段弦长捷径，累计出错导致间隔变成 14/9/20km 甚至 2km 的怪异分布。中点锚点**不要额外 `samples.append`**，否则会与等距点重叠出 2km 异常——应标记距弧长中点最近的已有点为 `isCenter`。
- **外框被 lines 短路的坑（2026-09-21）**：`borderSvg()` 若写成 `if(DATA.lines){ 拼 lines; return s; }`，则**复合工区（polygon + lines 并存，如大关）的外框会被彻底跳过**，地图上只剩测线、工区边框「消失」。正确顺序：① 有 `DATA.polygon` 先画外框并强制 `Z`；② 仅当 `DATA.lines && !DATA.dataLines`（纯测线项目）才由边框层画线骨架；③ 其余回落 `poly` 单线骨架。测线一律交给 `DATA.dataLines` 彩色虚线渲染，避免同线画两遍。自检：复合工区地图应含 1 条 `stroke="#1a1a1a"` 且带 `Z` 的闭合路径（大关＝13 顶点）+ N 条彩色虚线（大关＝3 条）。
- **采集点名称来自 `--points` KML 的 `<name>`（写入 `points[].loc`，地图/曲线/面板均显示它）**：`--data` 离线重渲染**不会重读 KML**（脚本内 `if args.points and not args.data`），因此**改了 KML 点名后必须重新取数**（带 `--points`）前台才会显示新名；只离线重渲染会保留旧名（曾出现 KML 已改「东北点」、看板仍显示「P1 (顶部左侧)」）。
- **三 Tab 结构（2026-09-17 重排：48 小时页居中、2 周页后置）**：`重点提示`(t1：重点关注预警 + 关键指标卡 + 物探作业影响与建议，三块均按**未来 48 小时**口径) / `未来48小时`(t2：地图 + `#riskReason` + `#hourlyCharts`) / `未来2周`(t3：地图 + `#elemRowD` + `#explorerCharts`)。**两张地图独立**（t2 用 `mapCanvas2`/`mapOverlay2`，t3 用 `mapCanvas3`/`mapOverlay3`），各自 `renderMap(suffix)`、各自点击联动；`POINT_PX`/`POINT_ELS`/`selRing`/`selLabel` 均带 suffix 后缀避免冲突；`selectPoint` 遍历两图但须 `if(!window["POINT_PX"+suffix]) return;` 守卫（未打开的 Tab 该地图未渲染，直接访问会抛异常导致后续 `renderExplorer()` 不执行）。**未来2周(t3)点选采样点** → `#explorerCharts` 绘制 14 天逐日要素曲线/柱状图（降水柱/阵风·均风线/气温线，固定顺序）；14 天点位密集，`nd>9` 时**日期刻度**自动 `tickEvery=2` 隔天标注；但**数值一律逐点直接标在图上**（2026-09-21 起取消旧的「14 天关闭逐点标值」逻辑 `noPointLabels`）——折线图两条线在同一 x 处上下错开标注（大值线标上方 `y-8`、小值线标下方 `y+16`，各系列用自身颜色、12px/700 加粗）；降水柱标在柱顶、**0mm 也标「0」**（浅灰 #9aa0a4，免得空着被误读成缺数据）。实测 14 天：降水 14 个标值、气温/风各 28 个（14×2），同 x 两标值最小垂直间距 ≈45px、无越界、不重叠。**未来48小时(t2)的 `#riskReason`** 位于 `.mapbox` **之后**（`.timebar` 已移除），集中展示：当前小时风险徽章 + 当前要素值（🕒 时间 ｜ 降水 ｜ 气温 ｜ 阵风 ｜ 均风）+ 四宫格要素级值 + 全期最严重提示（**常驻显示**：判定 `if(wh>=0)`）。`#hourlyCharts` 改为**单个合并图**（降水柱 + 均风/阵风/气温折线同图，配色对齐石油工程——均风绿、阵风紫、气温蓝、降水浅蓝分级柱，顶部图例 4 项：降水/均风/阵风/气温），**窗口恒为 48 小时**（前端 `NEAR_H`）；**在图表上按下即选、按住左右拖动可连续自由滑动选时**（`bindDragPick` → `selectHour`），无独立滑块时间轴，图内以 `#hourlyReadout` 数值框直接标出当前小时各要素值。**时间只在风险面板显示一次**（`.rr-cur .clk`；图表内 `.rr-clock`/`#hourlyClock` 因与面板重复已删除，`updateHourlyClock()` 随之移除）。**加粗数值统一「深色字 + 同色系浅底 pill」**：面板 `.rr-valrow b` 与两处图上读出框（`drawValBox` / `updateHourlyReadout`）的行内 `rect` 均以 `tintOf(color)`（`TINT` 映射）取浅底，保证底色浅、字色深、文字不被覆盖。**未来2周 `#explorerCharts` 同样支持按住自由滑动换日**（`bindDragPick` + `DAY_PICK`/`setDay`/`paintDaySel`/`drawValBox`，全局 `DAY_SEL`；切换采样点时重置；**选日期只重绘竖线+数值框、图表不重建，图完全不动**），选中日红线标记 + 图上数值框。选中采样点时**界面不动**，仅图的几何元素（`svg.chart .geo`＝柱/线/峰值点）以 `riseIn` 自下而上淡入；2 周选日期改由 `paintDaySel()` 只重绘竖线 + 数值框，**不重建图表**（`pointBar`/`pointLine` 仅把 `_pickCtx` 挂在 svg 上供其后重绘用）。重型验证（显式跑时）与轻量自检检查 `#riskReason` 的 `.rr-peaks`(4 格)/`.rr-cur`/`.rr-sev` 与 `#explorerCharts`（t3 点选后）、`#hourlyCharts`（t2 点选后）。
- **48 小时 / 2 周 双窗口数据（2026-09-17）**：取数窗口仍为 **2 周（14 天）**，但**逐点逐小时明细只保留前 48 小时**（Python 侧 `HOURS_48=48` 截断 `hx`，同时显著压缩 HTML 体积）；逐日序列 `series` 与区域 `daily` 保留完整 14 天。payload 新增：`peaksNear`（近 48 小时聚合，与整窗 `peaks` 同结构）、`farAlert`（第 3~14 天重大极端天气清单 `{has, days, text}`）、`meta.sevNear`/`meta.sevLabelNear`（近 48 小时分级）、`meta.nearDays`/`meta.hourlyWindow`，以及每点 `tmax2`/`tmin2`/`gustMax2`/`windMax2`/`pMax2`（近 48 小时逐点极值，供关键指标定位极值点）。前端 `PN`/`FARALERT`/`NEAR_H` 均有兜底（旧 `_data.json` 缺字段时回落整窗数据，不会报错）。
- **日期·时间与要素值显示（2026-09-21 修订）**：时间**只在风险面板出现一次**（`.rr-cur .clk`），为**纯粗体红字、无背景/边框**，格式「月-日 时:分」如「09-22 00:00」（不含年份、不带 emoji）；**图表内的重复时间（`.rr-clock` / `#hourlyClock` / `updateHourlyClock()`）已整段删除**（曾与面板时间重复显示）。其下 `.rr-valrow` **按固定顺序 降水 → 气温 → 阵风 → 均风** 排列，**加粗数值改用「深色字 + 各自浅色底 pill」**：降水 浅蓝底#D8E9FA/字#0D47A1、气温 浅蓝底#DEECF7/字#1A5A87、阵风 浅紫底#EEE1F7/字#5B2A7D、均风 浅绿底#D9EFE7/字#0F5B4C（**「风速」「持续风」已统一更名「均风」**：48 小时图内图例、未来2周逐日图的**标题/图例/勾选框/读出数值**均已写「均风」，两页口径一致）；标签保持常规字重（12.5px / #4A5157）以形成对比。**铁律：一律「浅底 + 深色字」，绝不用深底或与文字同色的底，确保文字颜色永远盖在底色之上、不被覆盖**。旧滑块时钟 `#tlClock`/`.tl-ticks` 已随时间轴一并移除。
- **页眉规范**：显示项目名 + 日期区间 + 生成日期，**不写时区、不写坐标、不写"离线看板"**；测线模式额外显示测线名与长度。
- **地形底图来源**：ArcGIS World Topo Map 在线地形瓦片（`https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}`），自带等高线/地名/道路；**已从脚本移除 Open-Meteo 高程色带/山体阴影/等高线自绘**（不再抓高程接口）。
- **真北朝上（勿镜像 y）**：瓦片底图本身北朝上（Web Mercator 上=北）。`yOf` 必须用 **`oy+(lat2y(lat,z)-py0)*sc`**（`py0=lat2y(maxlat)` 北边最小 y）：纬度越高→lat2y 越小→(lat2y-py0) 越小→y 越小→越靠上。**切勿**写成 `oy+(py1-lat2y(lat))*sc`（py1 是南边大 y）——那会把南北镜像、地图上下颠倒（曾出过此 bug）。瓦片纵坐标同理 `sy=oy+(ty*TILE-py0)*sc`。北箭头固定指向上方（瓦片无旋转）。
- **地图交互三层改造（2026-09-26，试点藏北高原冻土二维 → 推广藏北天山 / 广东广西深反射）**：
  > **已回退、勿再实现**：①**多测线筛选菜单**（`.linetabs#lineTabs` + `LINE_SEL` + 生成侧 `assign_line_idx()` 按坐标落线补 `points[].li`）——用户 2026-09-26 试用后判定「效果不好」，已整体删除；②**短名砍线别前缀**（`东线0km` → `0km`）——随上条一并回退，现 `东线0km` 保持原名。
  1. **行政地名层**（自建，不依赖 Esri 注记——`World_Boundaries_and_Places` 在高原无人区几乎无地名）。地名库 `scripts/../assets/cn_places.json`（技能内只有 `assets/` + `scripts/` 两个子目录，**无独立 `data/`**——运行时数据与页头背景图同放 `assets/`，与石油工程技能同构）（**363 个地级市/州/盟 + 2814 个县/区**，数据源阿里云 DataV GeoAtlas `https://geo.datav.aliyun.com/areas_v3/bound/{adcode}_full.json`——**必须带 `_full`**，否则只拿到该省自身边界）。生成时 `pick_places()` 按工区范围 + 自适应缓冲（`buf=min(4.0, max(0.35, 0.6*span))`）筛出周边地名内嵌进 `payload["places"]`（缓存上限 600；藏北 44 个、广东广西跨省 345 个）。渲染时 `drawPlaces()` 分级显隐（地级 10.5px 粗体、县级 9px）、占位框防压字、**默认就放县级**（2026-09-26 修正：早先默认只放地级，而默认视野只框工区 → 地级全在视野外被裁、县级又被门槛跳过，**结果一个地名都画不出来**），并留「放宽裁剪边距重画一次」的兜底。
  2. **丝滑拖动 + 双指捏合**：离散档位 `ZSTEPS` 已废弃 → `VIEW[suffix].sc` 连续倍率（0.5×~24×）；丝滑靠**两点**：`requestAnimationFrame` 节流 `scheduleRender()`（每帧至多重绘一次）+ `TILE_CACHE`（`url → {img, ok}`，命中同步直绘，拖动不等网络）。`zoomAt()` 做锚点缩放（手指/光标处地理位置不动），`updZL()` 在点击 +/− 时同步刷新倍率数字（原先只等 rAF，数字不即时变）。触屏走**统一 Pointer Events**（见下方「手机端地图手势铁律」）；`_justPanned` 抬手窗口用于防捏合后误触发点选。
  3. **采集点短名 `MAPTAG`**：点名来自 KML `<name>`（如 `XYH2026-SN-01-南端`、`广东-广西深反射0KM`、`东线0km`）。**两级剥离、逐级生效**：①**项目名精确对齐**（`spanName()` 逐字符比对并跳过 `-`/`_`/空格，`stripNm()` → `广东-广西深反射0KM` → `0KM`）；②**年份/子工区名** `PRE=/^([^-]{1,12}?)(19|20)\d{2}-/`（→ `XYH-SN-01-南端`），若撞名则只砍年份保留工区名（藏北 XYH/ZB/QMC 三条子线都有 `SN-01`）。两者都不命中则原样保留（故 `东线0km` 保持原名）。**坑**：年份正则必须写 `(19|20)\d{2}(?=-)`，写成 `(19|20)\d{2}-` 会把分隔符一起删掉变成 `XYHSN-01-南端`。短名统一用于 4 处：地图标签、48 小时风险面板标题、关键指标极值采样点、2 周面板标题（避免地图上短名、面板变回全名）。
  4. **采集点标签配色**：原「深字 + 3px 白描边」→ 改为**半透明白底衬 `rect(rgba(255,255,255,.74))` + 深灰字 #1b2733**，字号 13 → **9.5**（选中标签 12 → 11），白描边在底图上仍会糊。`selLabel` 同类改半透明白描边。
  5. **指北针位置**：固定右上角最边缘（距顶 7px、距右 3px），与左上角的 `＋`/`−` 按钮不冲突。
  6. **手机端地图手势（2026-09-26 修复）**：见下节「手机端地图手势铁律」。
  7. **采集点图标尺寸（2026-09-26 调小）**：常量**三处共用**，必须一起改，否则改色/重绘时大小会跳——`PT_R={ok:6.4,warn:7.2,danger:8.0}`（圆点半径，旧 9/10/11）、`PT_KR=1.5`（白描边，旧 2）、`PT_RING=13`（选中环半径，旧 18）、`CEN_HALF=6.4`（中心点菱形半边长，旧 9）。`renderMap()` 绘制、`updatePoints()` 逐小时改色、`redrawSelRing()`/`redrawSel()` 选中环各引用同一份常量（定义在哪儿都行，但**必须在顶层**，不能放进 `renderMap` 里——`updatePoints` 看不见）。**缩小圆点不影响手机点选**：地图空白处点击会命中最近采样点（`bd<=28`），有效点击半径仍是 28px。校验脚本 `scripts/check_ptsize.js`。

## 手机端地图手势铁律（2026-09-26 修复，勿退回 touch 事件）

现象：桌面鼠标一切正常，手机上「双指放大缩小」和「点采集点看图表」都不管用。根因有三处，全部在地图 `bindMap()`：

1. **单指 `touchstart` 里 `preventDefault()` 会掐掉浏览器随后补发的 `click`**，而选点逻辑绑在 `click` 上（`svg._mapClick`）→ **手机上永远点不到采集点**。
2. **双指捏合被浏览器自身的「页面缩放」抢走**，手势一旦被判成页面缩放，`touchmove` 就不可取消，`preventDefault()` 无效。
3. **`setZoom(suffix, dir)` 只认字符串 `"in"/"out"`，捏合传的是「本次间距/上次间距」数字倍率** → 落进 `else` 分支恒等于 `1/1.6` ⇒ **两指一张开反而缩小，方向是反的**。

现方案（三条一起改，缺一不可）：

- **手势统一走 Pointer Events**：`pointerdown/move/up/cancel` + `Map<pointerId,{x,y}>` 记录活跃指针；`size===1` → 单指平移（4px 阈值区分轻点与拖动），`size>=2` → 双指捏合。**不要再拆成 `mouse*` + `touch*` 两套**。`setPointerCapture` 保证手指移出 svg 仍收得到事件。
- **`touch-action:none` 必须写在 `.mapbox` 容器上**，不要写在 `<svg>` 上——iOS Safari 对 SVG 元素的 `touch-action` 支持不可靠。同时 `.mapbox` 加 `-webkit-touch-callout:none; user-select:none`，免得长按选字。
- **捏合倍率用两指中点做锚点**（中点/间距本身与两指在 Map 里的顺序无关，顺序帧间对调也不会让平移方向翻转）：`setZoom(suffix, d/pd, ...)`，且 **`setZoom` 必须支持数字倍率**（`typeof dir==="number" ? dir : (dir==="in"?1.6:1/1.6)`）。
- **`pointerup` 里自己兜轻点**：`n===1 && mode==="pan" && !moved` → 直接调 `svg._mapClick(ev)`（不能只靠 click）；`moved` 时置 `svg._justPanned=true` 260ms，压住随后补发的 click，免得拖完地图抬手又选中一个点。
- **iOS 私有 `gesturestart/gesturechange`**：只在 `ev.target.closest(".mapbox")` 时 `preventDefault()`，防止捏地图把整页一起放大（地图以外仍可正常双指放大看文字）。
- **回归测试**：`scripts/test_touch.js`（jsdom，模拟 pointer 事件）——覆盖「轻点选点 / 拖动不误选 / 张开放大 / 收拢缩小 / 捏合后不误选 / 鼠标点击仍可用 / ＋按钮 / gesturestart 被拦」共 14 项。用法：
  `NODE_PATH=<NODE_MODULES> <node> scripts/test_touch.js <某个看板.html>`
- **图标尺寸回归**：`scripts/check_ptsize.js`（jsdom，先点 `.tabbtn[data-tab="t2"]` 触发地图渲染再断言）——圆点半径落在 `PT_R` 三档内、无旧值 9/10/11、`updatePoints()` 改色后仍在同一档、无运行期错误。用法同 `test_touch.js`。
- **降水分级回归**：`scripts/check_rain.js <某个看板.html>`（jsdom；把 `peaksNear.pHourMax` 依次改成 0/1.2/2.5/6/12 看「降水 / 短时强降水」卡片等级与文案，再直接喂 `riskClassAtHour()` 0.3/1/2/4.9/5/10 校验 ok→warn→danger 边界）。注意：卡片文案里数值带空格（`最大小时降水 6 mm/h`），断言要用**去空白后的字符串**，否则正则永远不中。

  8. **页头背景图（2026-09-28）**：页头到三个页签这一整片区域铺一张照片作**背景**（base64 内嵌 + 白色渐隐），**不额外占版面**。详见下节「页头背景图（hero 背景层）」。
  9. **气象要素小图标（2026-09-28）**：关键指标、影响建议卡、图表图例、要素勾选行、48h 读数行的要素名前面统一带图标，**图形＝要素、色块底色＝风险程度**。详见下节「气象要素小图标」。

## 页头背景图（hero 背景层，2026-09-28 新增）

从页面顶部到**三个页签下沿**这一整片区域，铺一张**照片背景**（雪山/作业场景）。做法是「base64 内嵌 + 白色渐隐遮罩」，产物仍是**单文件 HTML**（可直接传 S3 / 离线打开，不依赖外链图片）。

- **不是卡片、不占版面**：`<header>` 与 `.tabs` 被包进一个 `.heroarea` 容器，照片挂在 `.heroarea::before`（`position:absolute; z-index:-1`）上，用**负 inset 向外出血**到屏幕两边。因此 `header` 高度、`.tabs` 位置与没有背景图时**逐像素一致**（实测 header 88px、页签底 156px），只是背后多了一张图。
- **图片资源**：`assets/hero-bg.jpg`。当前为雪原勘探场景，**480×161、约 18 KB**（2026-09-28 由 1440×485/112 KB 缩到 1/3，见下「分辨率与体积」）。
- **分辨率与体积（2026-09-28 定）**：图的**制作尺寸是 1440×485**（构图标准），但**落盘尺寸取 1/3 = 480×161、JPEG quality 82**（约 18 KB）。因为它是 `cover` 铺底 + 白色渐隐到 .02~.78 的**背景层**，放大 3 倍显示的观感与全尺寸几乎无差，而 base64 内嵌的代价从 **153 KB 降到 24 KB**（单页 HTML 因此少约 129 KB）。换图时按「先做 1440×485 → `resize(w//3,h//3,LANCZOS)` → q82」两步走。
- **调色（制作原图时做，已固化在现图上）**：原图整体亮度 210–252、近乎全白，**必须先调色**（裁到「雪山+作业面」信息带 + 提对比 1.45 / 提饱和 1.35 / 压亮度 0.84 + `autocontrast`），否则当背景看就是一片白。
- **内嵌方式**：`build_dashboard.py` 的 `hero_css()` 读该文件 → base64 data URI → 替换样式块里的注释占位 `/*__HERO_CSS__*/`。生成时打印 `hero bg: embedded`；文件缺失则打印 `hero bg SKIPPED: ...` 并**静默降级为原样页头**（不报错、不影响其他功能）。
- **可调参数**（都在 `build_dashboard.py` 顶部附近）：
  | 常量 | 作用 | 当前值 |
  |---|---|---|
  | `_HERO_IMG` | 图片路径（相对脚本 `../assets/hero-bg.jpg`） | — |
  | `HERO_BLEED` | 背景向左右的**出血量**（须 **严格等于**页面 `wrap` 的左右内边距，做到满屏宽） | `"14px"` |
  | `HERO_POS_Y` | 照片纵向取景（百分比越大越往下取景） | `"center"` |
  | `HERO_FADE` | 自上而下的白色渐隐色标：顶部较白保证导航/标题清晰，底部几乎全透露出照片 | `.78/0% → .38/42% → .02/100%` |
- **文字可读性兜底**：`hero_css()` 顺带把 `header>.meta` 字色压深到 `#4B545C`、给 `h1`/`.meta` 加极淡白描边（`text-shadow`）——照片变清楚后，12px 小字容易发飘。
- **⚠️ `HERO_BLEED` 必须与实测内边距严格相等（2026-09-28 修）**：原先写成 `"16px"`，而页面左右内边距实测是 **14px** —— 多伸的 2px 让 `documentElement.scrollWidth` 比 `clientWidth` 大 2，**手机端能左右拖动 2px**。改 `"14px"` 后 360/430/768/1000px 四种宽度实测溢出全为 0。改布局内边距时记得同步改这个值。
- **换图**：把新图覆盖 `assets/hero-bg.jpg` 即可；建议先做 1440×485 的原图（含调色），再缩到 1/3（480×161）、JPEG q82 ≈ 18 KB。同时**必须同步替换 `weather-engineering-data/assets/hero-bg.jpg`**（见下条）——两张图现在内容不同，别再当成同一张。
- **改完必须离线重渲染才生效**（模板改动不会被已有 HTML 自动套用）：
  `<PY> <SKILLS>/scripts/build_dashboard.py --name "<中文名>" --data <BEIDOU>/wutan/data/<pin>_data.json --outdir <BEIDOU>/wutan/html --outfile <pin>.html`
- **验证要点**：① 文字可读性（导航按钮、标题、元信息行）；② **版面零位移** —— 渲染后量 `header` 高度与 `.tabs` 底边，应与无背景图时完全一致；③ 地图/图表功能无回归（切 Tab、点采样点出图、48h 图 1 张 / 2 周图 3 张、零 JS 报错）。截图验证用托管 venv 的 playwright（`chromium` 已装），430px 视口即可。
- **石油工程侧已于 2026-09-28 同步此特性**（`weather-engineering-data` 的 `render_points_html.py`，含 hero 背景 + 气象要素小图标，语义与参数同本技能）。**注意两张图内容已不同**：物探＝雪原勘探场景，石油工程＝**钻井井场实景**（井架 + 井场设备 + 戈壁远景）。两边各存一份 `assets/hero-bg.jpg`，规格相同（480×161、q82）。
- **总览 index 也铺同一张背景（2026-09-28 加）**：`weather-wutan-index` 的 `gen_subindex.py` 生成的 `wutan/html/index.html` 把「标题行 + `.sub` + `.summary`」包进 `.heroarea`，**引用的是本技能的 `assets/hero-bg.jpg`，不另存一份**（脚本三级探测：`BEIDOU_HERO_BG` 环境变量 > 本技能 `assets/` > `../weather-wutan-html/assets/`；找不到就静默降级为纯色页头）。所以**只需维护本技能这一张图，index 会自动跟着变**。
- **⚠️ `assets/hero-bg.jpg` 必须随仓库一起同步**：它曾被漏同步到 git（2026-09-28 修），表现是新机安装后页头**静默无背景**、不报错、极难察觉。跑完同步脚本后用 `git status --short` 确认图片显示为 `create mode`。

## 气象要素小图标（2026-09-28 新增）

在**所有出现气象要素的关键位置**，要素名前面带一个 19×19（小号 16×16）的小图标：**图形＝是什么要素，色块底色＝风险程度**。一眼就能看出「这是什么要素 + 严重不严重」，不用读文字。

- **两套底色语义（务必区分，别混用）**：
  | 底色 | 含义 | 用在哪 |
  |---|---|---|
  | `.ok` 绿 / `.warn` 橙 / `.danger` 红 | **风险等级**（与风险区、徽标、地图圆点同一套色） | ①「关键指标」四格 ②「作业天气影响与建议」各卡标题 ③ 48h 读数行（随选时实时变色） |
  | `.plain` 灰 | **不带风险含义**，只标识要素 | 图表图例（`ec-legend`）、逐要素勾选行 |
- **要素图形**（`EIC` 常量，全部 24×24 线性 SVG，`stroke:currentColor`）：`rain` 雨云、`snow` 雪花、`wind` 风线、`temp` 温度计、`heat` 太阳、`fog` 雾（三条横线）。
- **唯一入口**：JS 函数 `eic(kind, lvl, small)` → 返回 `<span class="eic …">` HTML 片段。`lvl` 只认 `ok/warn/danger`，传其他值（含 `undefined`）自动退回 `.plain` —— 防止出现无底色的「隐形图标」。
- **单要素分级辅助函数**：`lvRain` / `lvGust` / `lvWind` / `lvTemp`（就在 `RAIN_H` 定义下方）。**阈值必须与 `riskClassAtHour` 完全一致**，不要各写一套。
- **已覆盖的位置**（改模板时若新增要素展示区，请一并接上 `eic()`）：
  1. `#statsBox` 关键指标四格（最高温 / 最低温 / 最大阵风 / 最大日降水）—— 首行 `.k` 内图标 + 要素名；
  2. `card(level,title,badge,html,icon)` 第 5 个参数＝要素图标，影响建议各卡自动同色；
  3. `ptLegendHtml(ic)` 与 `ELEM_DEFS[*].icon`：48h 合并图、2 周逐要素图的图例；
  4. `#elemRowD` 三个勾选标签（JS 启动时注入，`input` 之后插入，图标与文字成组）；
  5. `#riskReason` 读数行（降水/气温/阵风/均风）—— 图标底色随 `selectHour` 实时变化。
- **flex 容器内不要重复加边距**：`.eic` 默认带 `margin-right:5px`，但 `.imp .h` / `.ec-legend` / `.elem-row label` 自带 `gap`，已用 CSS 规则把这三处的图标外边距清零，否则间距翻倍。
- **改完必须离线重渲染**才生效（同 hero 背景图）：
  `<PY> <SKILLS>/scripts/build_dashboard.py --name "<中文名>" --data <BEIDOU>/wutan/data/<pin>_data.json --outdir <BEIDOU>/wutan/html --outfile <pin>.html`
- **验证要点**：`document.querySelectorAll('.eic').length` 应 ≈ 19~23（4 指标 + 影响卡数 + 图例 + 勾选行）；四格指标里**不允许出现 `class="eic o"` 这类残缺 class**（说明等级值写错了）；跑 `scripts/test_touch.js` 保证地图手势 14 项无回归。
- 石油工程侧（`weather-engineering-data` 的 `render_points_html.py`）**尚未同步此特性**。

## 多项目总览页（index.html）

> **本 skill 仅产出单个项目看板**：`build_dashboard.py` 只生成单个项目的 HTML + `_data.json`，**不生成** `index.html` 总览。多个项目的总览页（点击进入看板、看板可返回的小系统）由独立 skill **`weather-wutan-index`** 负责生成（从全部 `_data.json` 合并），详见该 skill。

## 通用注意事项

- 数据来自 Open-Meteo 公开接口，不含雷电要素（看板不渲染雷电提示，物探影响页聚焦降水/大风/高温/低温/行车）。
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
