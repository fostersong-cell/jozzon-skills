# jozzon-skills

物探 / 石油工程天气看板相关技能集，7 个技能，跨机器通过 GitHub 同步。

| 技能 | 作用 | 分类 |
| --- | --- | --- |
| `weather-wutan-data` | 物探取数：KML 工区/测线 → Open-Meteo 逐小时/逐日数据 | 物探 |
| `weather-wutan-html` | 物探看板渲染：生成富媒体交互 HTML（三页签） | 物探 |
| `weather-wutan-index` | 物探子总览页 `index.html`（数据驱动） | 物探 |
| `weather-engineering-data` | 石油工程取数 + 井位看板渲染 | 石油工程 |
| `weather-engineering-html` | 石油工程看板 HTML 模板与离线重渲染 | 石油工程 |
| `weather-engineering-index` | 井位总览页 + 近 2 天风险汇总 md | 石油工程 |
| `s3-beidou-publish` | 看板产物上传到 S3（`jln-reports`） | 发布 |

## 技能装在哪（先看这条，踩过坑）

| 位置 | 是否被 WorkBuddy 扫描到 | 说明 |
| --- | --- | --- |
| **`~/.workbuddy/skills/jozzon/`** | ✅ **是** | **默认安装位置**，用户级，所有工作区都可见 |
| `<工作区>/.workbuddy/skills/jozzon/` | ❌ 否 | 实测技能列表不收录，别装这儿 |

判断依据：WorkBuddy 的技能列表由 `~/.workbuddy/.skill-list-cache.json` 驱动，
它的 `scopeKey` / `watch.dirs` 只登记用户级目录（`~/.workbuddy/skills`、`connectors/skills`、内置插件目录），
**不包含工作区的 `.workbuddy/skills`**；缓存 `results` 里的 `source` 也只有 `userSettings` / `plugin` 两种。
所以放在工作区里的技能不会出现在技能列表中，虽然文件在那里，但模型看不到。

技能加载器对子目录是递归的（≤5 层），所以 `jozzon/` 这一层分组不影响识别。

> 换机器 / 重装后**必须重启 WorkBuddy**，缓存才会重扫。

## 同步方式

### 首次安装（另一台机器）

```bash
git clone https://github.com/fostersong-cell/jozzon-skills.git
cd jozzon-skills
bash install.sh          # 装到 ~/.workbuddy/skills/jozzon/
```

Windows：

```powershell
powershell -File install.ps1
```

装完重启 WorkBuddy。若该机器上还残留**旧版本**技能，先清掉再装（见下节）。

### 日常：远端有新版，本机更新

```bash
cd jozzon-skills
git pull
bash install.sh
```

### 上传：本机改了技能，推到 GitHub

```bash
bash <仓库>/sync-and-push.sh "改了什么，一句话说明"
bash <仓库>/sync-and-push.sh --no-push   # 只同步+提交，不推送，用于先本地核对
```

没有改动说明时自动用时间戳兜底；仓库无变化则跳过 commit。

### 另一台机器上已经有旧版本技能

旧版本技能大概率散在这些位置（早期是直接铺在用户级的）：

```bash
~/.workbuddy/skills/<技能名>/              # 用户级，平铺
<工作区>/.workbuddy/skills/                # 工作区级（当前版本不生效）
<其它项目目录>/.workbuddy/skills/
```

**同一批技能名存在两处时加载结果不确定，先清旧再装。** `install.sh` 会自动检测
用户级是否已平铺同名技能并给出提示。

```bash
cd <工作区>
git clone https://github.com/fostersong-cell/jozzon-skills.git

bash jozzon-skills/install.sh --dry-run   # 预演：应列出 7 个技能
bash jozzon-skills/install.sh             # 正式安装（用户级）
```

**Windows**：用 `powershell -File install.ps1`，或 Git Bash / WSL 下跑 `install.sh`。
Git for Windows 安装向导里勾上 **Enable UTF-8 action names**，工作区路径含中文时更稳。

**装完必做**

1. **重启 WorkBuddy**，否则加载器不会重新扫描。
2. 确认 7 个技能都在，且没有 `xxx.bak-<时间戳>` 残留目录。
3. 确认 `<PY>` / `<NODE>` 在本机的实际值（各 SKILL.md 开头有对照表，一般不用改），
   冒烟跑一次只读命令确认可用。

### 场景二：只能通过 U 盘 / 移动硬盘手工拷贝

远端始终是唯一权威版本，U 盘只负责搬运，不会造成两台机器各改各的。

**A 机（改完技能后）**

```bash
cd <工作区>/jozzon-skills                 # 即本机仓库，含 .git
git add -A && git commit -m "说明" && git push
cp -R <工作区>/jozzon-skills /Volumes/<U盘盘符>/   # 整个目录连 .git 一起拷
```

**B 机（插上 U 盘）**

```bash
cd /Volumes/<U盘盘符>/jozzon-skills
git pull                    # 确保是远端最新版
bash install.sh             # 装到用户级
```

若 B 机也要改技能，在 U 盘这份里改完再拷回去：
`git add -A && git commit -m "..." && git push`，然后把更新后的目录拷回 U 盘。

## 路径占位符（跨平台 · macOS / Windows 通用）

SKILL.md 里的命令刻意不含任何某一台机器的绝对路径，全部改成占位符，**在两台机器上都不用改文档、不用改脚本**：

| 占位符 | 含义 | macOS 典型值 | Windows 典型值 |
| --- | --- | --- | --- |
| `<WORK>` | 工作区根（含 `beidou/`） | `~/Desktop/.../AI/work` | `C:\...\AI\work` |
| `<SKILLS>` | 本技能所在目录 | `~/.workbuddy/skills/jozzon/<技能名>/` | 同左 |
| `<BEIDOU>` | 看板根 | `<WORK>/beidou` | 同左 |
| `<PY>` | Python 3 解释器 | 托管 venv `.../bin/python`，或 `python3` | 托管 venv `...\Scripts\python.exe`，或 `python` |
| `<NODE>` | Node 解释器 | `node` | `node.exe` |
| `<NODE_MODULES>` | Node 模块目录（跑 jsdom 回归用） | `.../node/workspace/node_modules` | 本机任选一个模块目录 |
| `<TMP>` | 系统临时目录 | `/tmp` | `%TEMP%` |

换机器只需**确认**这几项的实际值（各 SKILL.md 开头都有同一张表），不必改任何脚本：

- `gen_subindex.py` 的工作区根：环境变量 `BEIDOU_WORK` > `--base` > 从脚本位置自动上溯到含 `beidou/wutan/data` 的目录 —— 实测把脚本拷到任意中文/英文路径下无参数也能跑。
- `test_touch.js` 的看板路径：命令行参数 > 从脚本位置自动解析 `<工作区>/beidou/wutan/html/*.html`。
- 临时文件（CDP 用户数据目录等）：统一走 `tempfile.mkdtemp()`，自动适配系统临时目录，不再写死 `/tmp/...`。

### 跨平台保证

- 所有 Python 脚本只用标准库 + `requests`，不调用 `open` / `pbcopy` 等系统命令，Windows 可直接运行。
- 路径一律 `os.path.join` / `pathlib`，不依赖 `/` 或 `\`。
- 文档命令体例为 bash；每份 SKILL.md 文末附有 **bash ↔ PowerShell 对照表**。
- 数据目录为空时（换机器只放了其中一类数据）不再崩溃：`gen_subindex.py` 输出「暂无数据」空页，工程侧三个脚本给出明确提示并以 0 退出。

## 改动回传（在 A 机改了技能后）

1. 先跑一遍确认功能正常。
2. 改的是**运行态**目录 `~/.workbuddy/skills/jozzon/`（WorkBuddy 加载的就是它），
   然后 `bash <仓库>/sync-and-push.sh "说明"`；
   或手工在仓库目录 `git add -A && git commit -m "说明" && git push`。
3. 在 B 机：`git pull && bash install.sh`。

> 顺序别反：改运行态 → 同步到仓库 → push。
> 直接改仓库里的副本不会生效，因为加载器读的是运行态那份。

## 约定速查

- 取数默认窗口 14 天（「2 周」），起点为运行时刻的**下一整点**（`--from-today` 表示从当前整点起）。
- 数据源 Open-Meteo（免费层按 UTC 日历日限额，跑前建议探测配额，遇 429 约北京时间 08:00 恢复）。
- 看板页脚统一口径：山区小气候可能强于模式预报，以现场实测为准；页头外链指向 `https://leidian.wang`。
- 产物命名一律拼音，HTML 放 `html/`，`_data.json` 放 `data/`。
- 索引分工：物探总览 ← `gen_subindex.py --only wutan`；石油工程总览 ← `build_points_index.py`。
- 校验方式：`py_compile` / `node --check` 查语法，jsdom 脚本回归内联 JS。
