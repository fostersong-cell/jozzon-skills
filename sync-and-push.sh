#!/usr/bin/env bash
# 技能「修改 → 上 GitHub」一键脚本。
#
# 做什么：
#   1. 把运行态技能目录 <WORK>/.workbuddy/skills/jozzon/ 同步到本仓库 <WORK>/jozzon-skills/
#   2. git add -A / commit / push（没有改动时会跳过 commit 并提示）
#
# 用法（在工作区任意位置执行均可）：
#   bash <工作区>/jozzon-skills/sync-and-push.sh "改动说明"
#   MSG="改动说明" bash <工作区>/jozzon-skills/sync-and-push.sh
#   COMMIT_MSG="改动说明" bash <工作区>/jozzon-skills/sync-and-push.sh   # 等价写法
#   bash <工作区>/jozzon-skills/sync-and-push.sh --no-push   # 只提交不推送，用于先本地核对
#
# 说明：
#   - 同步用 rsync -a（**不加 --delete**）：仓库里的 .git / install.sh / README.md 等必须保留。
#   - 会跳过 __pycache__ / *.pyc / *.bak-* 备份目录。
#   - 兼容 macOS 自带 bash 3.2（不用 mapfile / nameref）。
set -eu

# 定位工作区：优先环境变量，其次从脚本位置向上找含 beidou/ 的目录
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

if [ -z "$WORK" ] || [ ! -d "$WORK" ]; then
  echo "✗ 找不到工作区（需含 beidou/ 的那一层）。请用 WORK=<路径> bash $0 指定。"
  exit 1
fi

SKILLS="$WORK/.workbuddy/skills/jozzon"
REPO="$WORK/jozzon-skills"

if [ ! -d "$SKILLS" ]; then
  echo "✗ 技能目录不存在：$SKILLS"
  exit 1
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
