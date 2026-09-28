#!/usr/bin/env bash
# jozzon-skills 安装脚本：把仓库里的 7 个技能装到 WorkBuddy 的技能目录。
#
# 默认装到**用户级** ~/.workbuddy/skills/jozzon/ —— 这是 WorkBuddy 唯一保证会扫描的位置
# （工作区级 <工作区>/.workbuddy/skills/ 在当前版本不会被技能列表收录，别装那儿）。
#
# 用法：
#   bash install.sh                     # 装到用户级 ~/.workbuddy/skills/jozzon（推荐，跨机器无需知道工作区路径）
#   bash install.sh --user              # 同上，显式写法
#   bash install.sh --project [路径]     # 装到 <工作区>/.workbuddy/skills/jozzon（路径省略时自动上溯找含 beidou/ 的目录）
#   bash install.sh <工作区路径>          # 等价于 --project <路径>（兼容旧用法）
#   bash install.sh --dry-run            # 只打印计划，不写盘
#   TARGET_WORK=<路径> bash install.sh    # 等价于 --project <路径>
#
# Windows 请用 PowerShell 版：powershell -File install.ps1
#   （Git Bash / WSL 下本脚本同样可用）
#
# 兼容 macOS 自带 bash 3.2（不使用 mapfile / nameref 等新特性）。
set -eu

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_NAME="jozzon"
DRY_RUN=0
MODE="user"
TARGET_WORK="${TARGET_WORK:-}"

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --user) MODE="user" ;;
    --project) MODE="project" ;;
    --*) ;;
    *) MODE="project"; TARGET_WORK="$arg" ;;
  esac
done

if [ -n "$TARGET_WORK" ]; then MODE="project"; fi

if [ "$MODE" = "user" ]; then
  DEST="$HOME/.workbuddy/skills/$SKILLS_NAME"
else
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
    echo "用法: bash install.sh --project <目标工作区路径>   （目标工作区 = 含 beidou/ 的目录）"
    echo "   或: bash install.sh                              （装到用户级，推荐）"
    exit 1
  fi
  if [ ! -d "$TARGET_WORK" ]; then
    echo "✗ 目标工作区不存在：$TARGET_WORK"
    exit 1
  fi
  DEST="$TARGET_WORK/.workbuddy/skills/$SKILLS_NAME"
fi

if [ "$DRY_RUN" = "0" ]; then
  mkdir -p "$DEST"
fi

if [ "$MODE" = "user" ]; then
  printf '%s\n' "模式：用户级（所有工作区可见）"
else
  printf '%s\n' "模式：工作区级（仅该工作区可见）"
fi
printf '%s\n' "仓库：$REPO_DIR"
printf '%s\n' "目标：$DEST"
if [ "$DRY_RUN" = "1" ]; then printf '%s\n' "（dry-run，不写盘）"; fi

# 用户级模式下，若同名技能已平铺在 ~/.workbuddy/skills/<技能名>，会与分组目录里的重复
if [ "$MODE" = "user" ]; then
  dup=""
  for skill in "$REPO_DIR"/*/; do
    [ -d "$skill" ] || continue
    n="$(basename "$skill")"
    if [ "$n" != ".git" ] && [ -e "$HOME/.workbuddy/skills/$n" ]; then dup="$dup $n"; fi
  done
  if [ -n "$dup" ]; then
    printf '\n%s\n' "⚠ 检测到用户级已平铺存在同名技能，会与 $SKILLS_NAME/ 下的重复，建议先移走："
    for n in $dup; do printf '   rm -rf ~/.workbuddy/skills/%s\n' "$n"; done
    printf '\n'
  fi
fi

copied=0
backed=0

for skill in "$REPO_DIR"/*/; do
  [ -d "$skill" ] || continue
  name="$(basename "$skill")"
  if [ "$name" = ".git" ]; then continue; fi
  src_files="$(find "$skill" -type f -not -path '*/__pycache__/*' -not -name '*.pyc' | wc -l | tr -d ' ')"
  dst="$DEST/$name"

  if [ -e "$dst" ]; then
    # 先清掉上一次的旧备份，避免多次重装后堆积（dry-run 时也必须跳过，不能真删）
    if [ "$DRY_RUN" = "0" ]; then
      for old in "$dst".bak-*; do
        if [ -e "$old" ]; then rm -rf "$old"; fi
      done
    fi
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
