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
#   - 运行态技能目录固定为 ~/.workbuddy/skills/jozzon（WorkBuddy 唯一扫描位置）；可用 SKILLS=<路径> 强制指定。
#   - 同步用 rsync -a（**不加 --delete**）：仓库里的 .git / install.sh / README.md 等必须保留。
#   - 会跳过 __pycache__ / *.pyc / *.bak-* 备份目录。
#   - 兼容 macOS 自带 bash 3.2（不用 mapfile / nameref）。
set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 仓库就在脚本所在目录
REPO="$SCRIPT_DIR"

# 运行态技能目录：固定用户级（WorkBuddy 唯一扫描位置）
SKILLS="${SKILLS:-$HOME/.workbuddy/skills/jozzon}"
if [ ! -d "$SKILLS" ]; then
  echo "✗ 技能目录不存在：$SKILLS。请先执行 install.sh 安装，或用 SKILLS=<路径> bash $0 指定。"
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
