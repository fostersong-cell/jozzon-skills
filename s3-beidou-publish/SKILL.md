---
name: s3-beidou-publish
description: 北斗物探/石油工程看板「发布到 AWS S3」专用上传工具。upload 子命令把本地 beidou/wutan/html/ 物探 与 beidou/engineering/html/ 石油工程 下的 *.html 上传到指定 S3 前缀（默认 jln-reports，cn-northwest-1 区域）。默认全量上传（--mode all，物探+石油工程一起传）；上传时设置 Content-Type: text/html 并过滤 .DS_Store。用于把生成的天气看板交付/同步到 S3 发布桶。凭证与区域取自本机 ~/.aws（default profile，cn-northwest-1）。
---

## 环境占位符（跨平台 · 首次使用请先确认）

本技能文档中的 `<WORK>` `<SKILLS>` `<BEIDOU>` `<PY>` `<NODE>` `<NODE_MODULES>` `<TMP>` 均为**运行时占位符**，须替换为本机的实际值。文档中不再出现任何某一台机器的固定路径，macOS 与 Windows 通用：

| 占位符 | 含义 | macOS 典型值 | Windows 典型值 |
|---|---|---|---|
| `<WORK>` | 工作区根（其下含 `beidou/`） | `~/Desktop/.../AI/work` | `C:\...\AI\work` |
| `<SKILLS>` | 技能根（本技能所在目录，用户级） | `~/.workbuddy/skills/jozzon/s3-beidou-publish` | `%USERPROFILE%\.workbuddy\skills\jozzon\s3-beidou-publish` |
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

# 北斗看板发布到 AWS S3（上传）

把本机 `beidou/wutan/html/`（物探）与 `beidou/engineering/html/`（石油工程）看板同步到 S3 发布桶。核心约定：

- **默认全量上传**：`--mode` 默认 `all`，即物探 + 石油工程 一起上传。也可单独指定 `wutan`（仅物探）或 `engineering`（仅石油工程）。
- **上传规范**：只传 `*.html`，过滤 `.DS_Store` 等系统文件；每个对象设 `ContentType: text/html; charset=utf-8` 与 `CacheControl: max-age=300`，浏览器可直接渲染。

## 规范路径（默认，可被参数覆盖）

| 类别 | 本地目录 | S3 前缀（桶 `jln-reports`） |
|------|----------|------------------------------|
| 物探 wutan | `beidou/wutan/html/` | `publish/sinopec-beidou-center/standard-service-widget/html/` |
| 石油工程 engineering | `beidou/engineering/html/` | `publish/sinopec-beidou-center/standard-service-widget/engineering/html/` |

## 环境依赖

- **本机未装 AWS CLI**，统一用隔离 venv 里的 `boto3` 直连。
  - macOS（用户常驻机）：`<PY>`
  - Windows：托管 venv 的 `<PY>`，如 `...\Scripts\python.exe`（实际值以本机为准，不必照抄）。
- 若 venv 缺 boto3：`Scripts/pip.exe install boto3`（Windows）/ `bin/pip install boto3`（macOS）。
- 凭证：`~/.aws/credentials`（default profile，含 access/secret）、`~/.aws/config`（region=`cn-northwest-1`）。boto3 自动读取，无需在脚本里硬编码密钥。

## 用法（upload 子命令）

### 0) 环境（Python 解释器）
- macOS（用户常驻机）：`<PY>`
- Windows：托管 venv 的 `<PY>`，如 `...\Scripts\python.exe`（实际值以本机为准，不必照抄）。
- 脚本统一记为 `<PY>`；若 venv 缺 boto3：`Scripts/pip.exe install boto3`（Windows）/ `bin/pip install boto3`（macOS）。

> `--local-base` **是 `beidou/` 目录本身**（其下直接含 `wutan/` 与 `engineering/`），不是它的父目录。默认 `./beidou`。

### 1) 全量上传（默认，物探 + 石油工程）
```bash
<PY> <SKILLS>/s3-beidou-publish/scripts/publish.py upload \
  --local-base "<BEIDOU>"
```
等价于 `--mode all`（默认即全量，可不写）。

### 2) 只上传物探
```bash
<PY> .../publish.py upload --mode wutan \
  --local-base "/path/to/work/beidou"
```

### 3) 只上传石油工程
```bash
<PY> .../publish.py upload --mode engineering \
  --local-base "/path/to/work/beidou"
```

### 4) 先预演（不改动 S3）
```bash
<PY> .../publish.py upload --dry-run        # 只列出将上传的文件
```

## 参数速查（upload 子命令）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--mode` | `all` | `all`（默认，物探+石油工程）/ `wutan`（仅物探） / `engineering`（仅石油工程） |
| `--local-base` | `./beidou` | `beidou/` 目录本身（其下含 `wutan/`、`engineering/`） |
| `--bucket` | `jln-reports` | 目标桶 |
| `--wutan-prefix` | `publish/.../standard-service-widget/html/` | 物探上传前缀 |
| `--eng-prefix` | `publish/.../standard-service-widget/engineering/html/` | 石油工程上传前缀 |
| `--dry-run` | 关 | 只列出将上传的文件，不改动 S3 |

## 工作流（agent 执行步骤）

1. 默认全量发布（`--mode all`）；除非用户明确只要物探或只要石油工程，否则直接 `upload` 即可。
2. 确认 `--local-base` 指向 `<BEIDOU>` 目录本身（不是它的父目录）。
3. 用 `publish.py upload ...` 运行，观察输出：每个 html 的 OK/ERR、跳过的非 html 文件。
4. 上传后用 S3 控制台或 `list_objects_v2` 复核对象数与大小是否一致。

## 关键实现要点（踩坑记录）

- **默认全量上传**：`upload` 的 `--mode` 默认 `all`，物探与石油工程看板一起推（用户明确：没有「未说明不跑 engineering」的约定，全量即可）。
- **过滤系统文件**：上传前用 `f.endswith(".html")` 过滤，`.DS_Store`（macOS）不会被推到 S3 污染发布目录。
- **Content-Type 必须显式设 text/html**：否则 S3 默认 `application/octet-stream`，浏览器会下载而非渲染看板。
- **local-base 语义**：是 `beidou/` 目录本身（其下直接含 `wutan/`、`engineering/`），不是它的父目录；脚本按 `base/wutan/html`、`base/engineering/html` 拼接。
- **凭证不落脚本**：依赖 `~/.aws` 的 default profile，脚本里不写 access/secret；区域由 config 决定（cn-northwest-1）。
- **区域注意**：桶在 `cn-northwest-1`（宁夏），部分资源在 `cn-north-1`；列表/上传若报 Region 错，检查 config 的 region。

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
