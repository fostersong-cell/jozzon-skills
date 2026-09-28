# jozzon-skills

物探 / 石油工程天气看板相关的工作区技能集，7 个技能，跨机器通过 GitHub 同步。

| 技能 | 作用 | 分类 |
| --- | --- | --- |
| `weather-wutan-data` | 物探取数：KML 工区/测线 → Open-Meteo 逐小时/逐日数据 | 物探 |
| `weather-wutan-html` | 物探看板渲染：生成富媒体交互 HTML（三页签） | 物探 |
| `weather-wutan-index` | 物探子总览页 `index.html`（数据驱动） | 物探 |
| `weather-engineering-data` | 石油工程取数 + 井位看板渲染 | 石油工程 |
| `weather-engineering-html` | 石油工程看板 HTML 模板与离线重渲染 | 石油工程 |
| `weather-engineering-index` | 井位总览页 + 近 2 天风险汇总 md | 石油工程 |
| `s3-beidou-publish` | 看板产物上传到 S3（`jln-reports`） | 发布 |

## 同步方式

### 场景一：两台机器都能上网（推荐，最省事）

```bash
# 首次：克隆到任意目录
git clone https://github.com/fostersong-cell/jozzon-skills.git

# 安装到某台电脑的工作区（目标工作区 = 含 beidou/ 的那一层）
cd jozzon-skills
bash install.sh /path/to/work     # 省略参数时会自动上溯查找含 beidou/ 的目录
bash install.sh --dry-run         # 只打印计划，不写盘

# 日常更新
git pull && bash install.sh /path/to/work
```

**上传（A 机改完技能后）** —— 一键脚本，把 `<WORK>/.workbuddy/skills/jozzon/`
同步进仓库并 push：

```bash
bash <工作区>/jozzon-skills/sync-and-push.sh "改了什么，一句话说明"
bash <工作区>/jozzon-skills/sync-and-push.sh --no-push   # 只同步+提交，不推送
```

没有改动说明时会自动用时间戳兜底；仓库无变化则跳过 commit。

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
git pull                    # 确保是远端最新版（A 机 push 后的完整副本，通常已是最新）
bash install.sh <B机工作区路径>
```

若 B 机也要改技能，在 U 盘这份里改完再拷回去：
`git add -A && git commit -m "..." && git push`，然后把更新后的目录拷回 U 盘。

> 只拷 `install.sh` / `install.ps1` 和技能文件夹、不带 `.git` 也能用（见「改动回传」），
> 但那样就没有版本追溯了，建议整目录拷贝。

**Windows**：用 PowerShell 版，用法等价：

```powershell
powershell -File install.ps1 C:\path\to\work     # 省略参数时会自动上溯查找含 beidou\ 的目录
powershell -File install.ps1 -DryRun
```

Git Bash / WSL 下 `install.sh` 同样可用。两个脚本都会跳过 `__pycache__` 与 `*.pyc`，
并把同名旧技能备份为 `<技能名>.bak-<时间戳>`（先清掉上一次的旧备份，不堆积）。

安装脚本会把 7 个技能复制到 `<目标工作区>/.workbuddy/skills/jozzon/` 下。
**技能加载器递归扫描该目录 ≤5 层**，所以 `jozzon/` 这一层分组不影响识别；
安装后重启 WorkBuddy 即可看到技能。

若目标工作区里已存在同名技能，旧目录会自动备份，不会直接覆盖。

## 路径占位符（跨平台 · macOS / Windows 通用）

SKILL.md 里的命令刻意不含任何某一台机器的绝对路径，全部改成占位符，**在两台机器上都不用改文档、不用改脚本**：

| 占位符 | 含义 | macOS 典型值 | Windows 典型值 |
| --- | --- | --- | --- |
| `<WORK>` | 工作区根（含 `beidou/`） | `~/Desktop/.../AI/work` | `C:\...\AI\work` |
| `<SKILLS>` | 本技能所在目录 | `<WORK>/.workbuddy/skills/jozzon/<技能名>/` | 同左 |
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

1. 先跑一遍确认功能正常（例如 `bash install.sh --dry-run` 或直接执行脚本）。
2. A 机：改的是**运行态**技能目录 `<WORK>/.workbuddy/skills/jozzon/`，
   然后 `bash <工作区>/jozzon-skills/sync-and-push.sh "说明"`；
   或手工在仓库目录 `git add -A && git commit -m "说明" && git push`。
3. B 机：`git pull && bash install.sh <工作区路径>`。

> 注意：WorkBuddy 只加载 `<工作区>/.workbuddy/skills/jozzon/` 下那份，
> `<工作区>/jozzon-skills/` 只是仓库副本，**改技能要改前者再同步**，顺序反了会白改。

## 约定速查

- 取数默认窗口 14 天（「2 周」），起点为运行时刻的**下一整点**（`--from-today` 表示从当前整点起）。
- 数据源 Open-Meteo（免费层按 UTC 日历日限额，跑前建议探测配额，遇 429 约北京时间 08:00 恢复）。
- 看板页脚统一口径：山区小气候可能强于模式预报，以现场实测为准；页头外链指向 `https://leidian.wang`。
- 产物命名一律拼音，HTML 放 `html/`，`_data.json` 放 `data/`。
- 校验方式：`py_compile` / `node --check` 查语法，jsdom 脚本回归内联 JS。
