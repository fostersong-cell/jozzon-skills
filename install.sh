#!/usr/bin/env bash
# jozzon-skills 安装脚本：把仓库里的 7 个技能复制到目标工作区的 .workbuddy/skills/jozzon/ 下，
# 使 WorkBuddy 技能加载器能扫描到（加载器递归扫描 ≤5 层）。
#
# 用法：
#   bash install.sh <目标工作区路径>      # 目标工作区 = 含 beidou/ 的那一层（如 AI/work）
#   TARGET_WORK=<路径> bash install.sh
#   bash install.sh --dry-run              # 只打印计划，不写盘
#
# Windows 请用 PowerShell 版：powershell -File install.ps1 <目标工作区路径>
#   （Git Bash / WSL 下本脚本同样可用）
#
# 兼容 macOS 自带 bash 3.2（不使用 mapfile / nameref 等新特性）。
set -eu

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_NAME="jozzon"
TARGET_WORK="${TARGET_WORK:-}"
DRY_RUN=0

for arg in "$@"; do
  if [ "$arg" = "--dry-run" ]; then DRY_RUN=1; fi
  case "$arg" in
    --*) ;;
    *) TARGET_WORK="$arg" ;;
  esac
done

# 未指定时：从仓库位置向上找含 beidou/ 的目录
if [ -z "$TARGET_WORK" ]; then
  d="$REPO_DIR"
  i=0
  while [ "$i" -lt 6 ]; do
    if [ -d "$d/beidou" ]; then TARGET_WORK="$d"; break; fi
    d="$(dirname "$d")"
    i=$((i + 1))
  done
fi

if [ -z "$TARGET_WORK" ]; then
  echo "用法: bash install.sh <目标工作区路径>   （目标工作区 = 含 beidou/ 的目录）"
  echo "   或: TARGET_WORK=<路径> bash install.sh"
  exit 1
fi

if [ ! -d "$TARGET_WORK" ]; then
  echo "✗ 目标工作区不存在：$TARGET_WORK"
  exit 1
fi

DEST="$TARGET_WORK/.workbuddy/skills/$SKILLS_NAME"
mkdir -p "$DEST"

printf '%s\n' "仓库：$REPO_DIR"
printf '%s\n' "目标：$DEST"
if [ "$DRY_RUN" = "1" ]; then printf '%s\n' "（dry-run，不写盘）"; fi

copied=0
backed=0

for skill in "$REPO_DIR"/*/; do
  [ -d "$skill" ] || continue
  name="$(basename "$skill")"
  if [ "$name" = ".git" ]; then continue; fi
  src_files="$(find "$skill" -type f -not -path '*/__pycache__/*' -not -name '*.pyc' | wc -l | tr -d ' ')"
  dst="$DEST/$name"

  if [ -e "$dst" ]; then
    # 先清掉上一次的旧备份，避免多次重装后堆积
    for old in "$dst".bak-*; do
      if [ -e "$old" ]; then rm -rf "$old"; fi
    done
    stamp="$(date +%Y%m%d-%H%M%S)"
    if [ "$DRY_RUN" = "0" ]; then
      mv "$dst" "$dst.bak-$stamp"
    fi
    backed=$((backed + 1))
    printf '%s\n' "· $name 已存在 → 旧目录备份为 $name.bak-$stamp"
  fi

  if [ "$DRY_RUN" = "0" ]; then
    cp -R "$skill" "$dst"
  fi
  printf '%s\n' "  [OK] $name  $src_files files"
  copied=$((copied + 1))
done

printf '\n'
printf '%s\n' "完成：新装 $copied 个技能，备份 $backed 个同名旧目录。"
printf '%s\n' "重启 WorkBuddy 后技能即可识别。"
