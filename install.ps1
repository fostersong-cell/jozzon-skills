# jozzon-skills 安装脚本（Windows / PowerShell 版，与 install.sh 等价）
#
# 默认装到**用户级** $HOME\.workbuddy\skills\jozzon\ —— 这是 WorkBuddy 唯一保证会扫描的位置
# （工作区级 <工作区>\.workbuddy\skills\ 在当前版本不会被技能列表收录，别装那儿）。
#
# 用法：
#   powershell -File install.ps1                        # 装到用户级（推荐）
#   powershell -File install.ps1 -User                  # 同上，显式写法
#   powershell -File install.ps1 -Project [路径]         # 装到 <工作区>\.workbuddy\skills\jozzon
#   powershell -File install.ps1 -TargetWork <路径>      # 等价于 -Project <路径>（兼容旧用法）
#   powershell -File install.ps1 -DryRun                # 只打印计划，不写盘
#
# 说明：
#   - 同名旧目录会先备份为 <name>.bak-<时间戳>，并清掉上一次的旧备份，避免堆积。
#   - 会跳过 __pycache__ 与 *.pyc（平台产物的脏数据）。
#   - 装完重启 WorkBuddy，技能加载器即可扫描到（加载器递归扫描 ≤5 层）。

param(
  [string]$TargetWork,
  [switch]$User,
  [switch]$Project,
  [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$REPO = Split-Path -Parent $MyInvocation.MyCommand.Path
$SKILLS_NAME = 'jozzon'

# 默认用户级；给路径或 -Project/-TargetWork 则走工作区级
$MODE = 'user'
if ($Project) { $MODE = 'project' }
if ($TargetWork) { $MODE = 'project' }
if ($User) { $MODE = 'user' }   # -User 显式指定时优先级最高

if ($MODE -eq 'user') {
  $DEST = Join-Path (Join-Path $HOME '.workbuddy') (Join-Path 'skills' $SKILLS_NAME)
} else {
  # 未指定目标时：从仓库位置逐级上溯，找含 beidou\ 的目录
  if (-not $TargetWork) {
    $d = $REPO
    for ($i = 0; $i -lt 6; $i++) {
      if (Test-Path (Join-Path $d 'beidou')) { $TargetWork = $d; break }
      $d = Split-Path -Parent $d
    }
  }
  if (-not $TargetWork) {
    Write-Host '用法: powershell -File install.ps1 -Project <目标工作区路径>   （目标工作区 = 含 beidou\ 的目录）'
    Write-Host '  或: powershell -File install.ps1                          （装到用户级，推荐）'
    exit 1
  }
  if (-not (Test-Path $TargetWork)) {
    Write-Host "错误：目标工作区不存在 -> $TargetWork"
    exit 1
  }
  $DEST = Join-Path (Join-Path $TargetWork '.workbuddy') (Join-Path 'skills' $SKILLS_NAME)
}

if (-not $DryRun) {
  New-Item -ItemType Directory -Force -Path $DEST | Out-Null
}

if ($MODE -eq 'user') { Write-Host '模式：用户级（所有工作区可见）' } else { Write-Host '模式：工作区级（仅该工作区可见）' }
Write-Host "仓库：$REPO"
Write-Host "目标：$DEST"
if ($DryRun) { Write-Host '(dry-run，不写盘)' }

# 用户级模式下，若同名技能已平铺在 ~\.workbuddy\skills\<技能名>，会与分组目录里的重复
if ($MODE -eq 'user') {
  $dup = @()
  Get-ChildItem -Path $REPO -Directory | ForEach-Object {
    if ($_.Name -ne '.git' -and (Test-Path (Join-Path (Join-Path $HOME '.workbuddy\skills') $_.Name))) { $dup += $_.Name }
  }
  if ($dup.Count -gt 0) {
    Write-Host ''
    Write-Host "注意：用户级已平铺存在同名技能，会与 $SKILLS_NAME\ 下的重复，建议先移走："
    $dup | ForEach-Object { Write-Host "   Remove-Item -Recurse -Force `$HOME\.workbuddy\skills\$_" }
    Write-Host ''
  }
}

$copied = 0
$backed = 0

# 旧版本备份的存放位置，必须**在技能扫描目录之外**（与 install.sh 同策略，2026-09-28 修复）。
# 备份若留在 $DEST 里，WorkBuddy 递归扫描 jozzon/ 会把里面的 SKILL.md 当成技能，
# 于是多出 N 个叫「xxx.bak-2026…」的假技能。
$envBak = if ($env:JOZZON_BAK) { $env:JOZZON_BAK } else { Join-Path $env:USERPROFILE ".workbuddy\skills-backup" }
if (-not $DryRun) { New-Item -ItemType Directory -Path $envBak -Force | Out-Null }

Get-ChildItem -Path $REPO -Directory | ForEach-Object {
  $name = $_.Name
  if ($name -eq '.git') { return }
  $dst = Join-Path $DEST $name
  $all = Get-ChildItem -Path $_.FullName -File -Recurse
  $srcFiles = @($all | Where-Object { $_.FullName -notmatch '__pycache__' -and $_.Extension -ne '.pyc' }).Count

  if (Test-Path $dst) {
    if (-not $DryRun) {
      # 先清掉上一次的旧备份，避免多次重装后堆积
      Remove-Item -Path (Join-Path $envBak "$name.bak-*") -Recurse -Force -ErrorAction SilentlyContinue
      $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
      Move-Item -Path $dst -Destination (Join-Path $envBak "$name.bak-$stamp") -Force
    }
    $backed = $backed + 1
    Write-Host "· $name 已存在 -> 旧目录备份到 $envBak\$name.bak"
  }

  if (-not $DryRun) { Copy-Item -Path $_.FullName -Destination $DEST -Recurse -Force }
  Write-Host "  [OK] $name  $srcFiles files"
  $copied = $copied + 1
}

Write-Host ''
Write-Host "完成：新装 $copied 个技能，备份 $backed 个同名旧目录。"
Write-Host '重启 WorkBuddy 后技能即可识别。'
