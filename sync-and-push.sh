#!/usr/bin/env bash
# 技能「修改 → 上 GitHub」一键脚本。
#
# 做什么：
#   1. 把运行态技能目录 ~/.workbuddy/skills/jozzon/ 同步到本仓库
#   2. git add -A / commit / push（没有改动时会跳过 commit 并提示）
#
# 用法（在任意位置执行均可，仓库路径即脚本所在目录）：
#   bash <仓库>/sync-and-push.sh "改动说明"   # 仓库即本文件所在目录（jozzon-skills/）
#   bash <仓库>/sync-and-push.sh "改动说明"
#   MSG="改动说明" bash <仓库>/sync-and-push.sh
#   COMMIT_MSG="改动说明" bash <仓库>/sync-and-push.sh   # 等价写法
#   bash <仓库>/sync-and-push.sh --no-push   # 只提交不推送，用于先本地核对
#
# 说明：
#   - 运行态目录默认取 ~/.workbuddy/skills/jozzon；找不到时回退工作区级 <WORK>/.workbuddy/skills/jozzon。
#     可用 SKILLS=<路径> 强制指定。
#   - 同步用 rsync -a（**不加 --delete**）：仓库里的 .git / install.sh / README.md 等必须保留。
#   - 会跳过 __pycache__ / *.pyc / *.bak-* 备份目录。
#   - 兼容 macOS 自带 bash 3.2（不用 mapfile / nameref）。
set -eu

# 定位工作区（仅用于回退工作区级布局）：优先环境变量，其次从脚本位置向上找含 beidou/ 的目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="${WORK:-}"
if [ -z "$WORK" ]; then
  d="$SCRIPT_DIR"
  i=0
  while [ "$i" -lt 6 ]; do
    if [ -d "$d/beidou" ]; then WORK="$d"; break; fi
    d="$(dirname "$d")"
    i=$((i + 1))
  done
fi

# 仓库就在脚本所在目录
REPO="$SCRIPT_DIR"

# 运行态技能目录：优先用户级（WorkBuddy 真正扫描的位置），回退工作区级（旧布局）
SKILLS="${SKILLS:-$HOME/.workbuddy/skills/jozzon}"
if [ ! -d "$SKILLS" ]; then
  if [ -n "$WORK" ] && [ -d "$WORK/.workbuddy/skills/jozzon" ]; then
    SKILLS="$WORK/.workbuddy/skills/jozzon"
    printf '%s\n' "（未找到用户级技能目录，回退到工作区级：$SKILLS）"
  else
    echo "✗ 技能目录不存在。请先执行 install.sh 安装，或用 SKILLS=<路径> bash $0 指定。"
    exit 1
  fi
fi

if [ ! -d "$REPO/.git" ]; then
  echo "✗ 仓库目录不像 git 仓库：$REPO"
  exit 1
fi

NO_PUSH=0
MSG="${MSG:-${COMMIT_MSG:-}}"
for arg in "$@"; do
  case "$arg" in
    --no-push) NO_PUSH=1 ;;
    *) MSG="$arg" ;;
  esac
done

printf '%s\n' "技能源：$SKILLS"
printf '%s\n' "仓库  ：$REPO"
if [ "$NO_PUSH" = "1" ]; then printf '%s\n' "（--no-push：只提交不推送）"; fi
printf '\n'

echo "[1/4] 同步技能文件到仓库…"
rsync -a \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude '*.bak-*' \
  "$SKILLS/" "$REPO/"

cd "$REPO"

echo "[2/4] 暂存改动…"
git add -A

if git diff --cached --quiet; then
  echo "      仓库内没有检测到改动，跳过 commit。"
  CHANGED=0
else
  CHANGED=1
fi

if [ "$CHANGED" = "1" ]; then
  if [ -z "$MSG" ]; then
    echo "      （未给改动说明，用当前时间作为提交信息）"
    MSG="chore: update skills $(date +%Y-%m-%d\ %H:%M)"
  fi
  echo "[3/4] 提交：$MSG"
  git commit -m "$MSG" | sed 's/^/      /'
else
  echo "[3/4] 无需提交。"
fi

if [ "$NO_PUSH" = "1" ]; then
  echo "[4/4] 已跳过 push。"
else
  echo "[4/4] 推送到 GitHub…"
  git pull --rebase --quiet || true
  git push --quiet
fi

printf '\n'
git log --oneline -1 | sed 's/^/最新提交：/'
printf '%s\n' "完成。另一台机器执行：git pull && bash install.sh"
