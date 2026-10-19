#!/usr/bin/env bash
# jozzon-mcp-token-refresh
# 无头登录 https://leidian.wang，从 localStorage 取最新 access，写回 WorkBuddy 的 mcp.json
# 跨平台可移植：不硬编码用户名 / node 版本号，运行时动态定位 WorkBuddy 目录与二进制。
# 前置依赖（Windows 需 Git Bash / WSL 这类 bash 环境，并装好 node 与 python3）：
#   - node + agent-browser（无头浏览器）
#   - python3
# 用法：
#   bash refresh.sh              # 先检查有效期：剩余 < 30 分钟才刷新，否则跳过（退出码 0）
#   bash refresh.sh --force      # 强制刷新（跳过有效期检查）
# 环境变量：
#   REFRESH_MIN_REMAIN           # 刷新阈值（秒），默认 1800（30 分钟）
#   WB_HOME                      # WorkBuddy 的 .workbuddy 目录，默认 ~/.workbuddy
set -u
export LC_ALL=C

# WorkBuddy 用户目录：默认 ~/.workbuddy，可用 WB_HOME 环境变量覆盖（便于非标准安装）
WB_HOME="${WB_HOME:-$HOME/.workbuddy}"
MCP="$WB_HOME/mcp.json"
SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG="$SKILL_DIR/config.json"

# 刷新阈值：token 剩余有效期不足该值（秒）才刷新；默认 30 分钟
REFRESH_MIN_REMAIN="${REFRESH_MIN_REMAIN:-1800}"

log() { echo "[token-refresh $(date '+%H:%M:%S')] $*"; }

# ---- 定位 python3（优先 PATH，回退托管 venv：WB_HOME 与真实 ~/.workbuddy 都试）----
PY="$(command -v python3 2>/dev/null || command -v python 2>/dev/null)"
if [ -z "$PY" ]; then
  for ROOT in "$WB_HOME" "$HOME/.workbuddy"; do
    if [ -x "$ROOT/binaries/python/envs/default/bin/python" ]; then
      PY="$ROOT/binaries/python/envs/default/bin/python"; break
    fi
  done
fi
if [ -z "$PY" ]; then
  log "ERROR: 找不到 python3，请确认已安装 Python，或用 WB_HOME 指向正确的 WorkBuddy 目录" >&2
  exit 1
fi

# ---- 参数解析：--force 强制刷新（跳过有效期检查）----
FORCE=0
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    *) log "WARN: 忽略未知参数 $arg（用法: refresh.sh [--force]）" ;;
  esac
done

# ---- 0) 有效期预检：剩余 >= 阈值则跳过刷新（2026-10-19 用户要求）----
# 判定：VALID=仍有效（跳过，退出码 0）；REFRESH=将过期/已过期（继续刷新）；
#       BAD=token 缺失或无法解析（继续刷新）。
if [ "$FORCE" != "1" ]; then
  if [ ! -f "$MCP" ]; then
    log "未找到 $MCP，直接进入刷新流程"
  else
    VERDICT=$("$PY" - "$MCP" "$REFRESH_MIN_REMAIN" <<'PYEOF'
import json, sys, base64, time
f, min_remain = sys.argv[1], int(sys.argv[2])
try:
    d = json.load(open(f))
    hdr = (d.get("mcpServers", {}).get("jozzon-mcp", {})
           .get("headers", {}).get("Authorization", ""))
    tok = hdr.split(" ", 1)[-1] if hdr else ""
    if not tok or tok.count(".") != 2:
        print("BAD - -"); sys.exit(0)
    p = tok.split(".")[1]; p += "=" * (-len(p) % 4)
    exp = int(json.loads(base64.urlsafe_b64decode(p))["exp"])
    remain = exp - int(time.time())
    bt = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(exp))
    if remain >= min_remain:
        print(f"VALID {remain} {bt}")
    else:
        print(f"REFRESH {remain} {bt}")
except Exception:
    print("BAD - -")
PYEOF
)
    read -r ST REMAIN EXPS <<< "$VERDICT"
    if [ "$ST" = "VALID" ]; then
      log "token 仍有效（至 ${EXPS}，剩余 $((REMAIN / 3600)) 小时 $((REMAIN % 3600 / 60)) 分 ≥ 阈值 ${REFRESH_MIN_REMAIN}s），跳过刷新"
      exit 0
    elif [ "$ST" = "REFRESH" ]; then
      log "token 剩余 ${REMAIN}s（< 阈值 ${REFRESH_MIN_REMAIN}s，至 ${EXPS}），执行刷新"
    else
      log "token 缺失或无法解析，执行刷新"
    fi
  fi
else
  log "--force：跳过有效期检查，强制刷新"
fi

# ---- 定位 agent-browser（PATH → WB_HOME / 真实 ~/.workbuddy 的 node workspace / 各版本 bin）----
AB="$(command -v agent-browser 2>/dev/null)"
if [ -z "$AB" ]; then
  for ROOT in "$WB_HOME" "$HOME/.workbuddy"; do
    [ -d "$ROOT" ] || continue
    AB="$(ls "$ROOT"/binaries/node/workspace/node_modules/.bin/agent-browser 2>/dev/null | head -1)"
    [ -n "$AB" ] && break
    AB="$(ls "$ROOT"/binaries/node/versions/*/bin/agent-browser 2>/dev/null | head -1)"
    [ -n "$AB" ] && break
  done
fi

# ---- 定位 npm / node workspace（用于按需安装 agent-browser；同样两个 root 都试）----
NPM="$(command -v npm 2>/dev/null)"
if [ -z "$NPM" ]; then
  for ROOT in "$WB_HOME" "$HOME/.workbuddy"; do
    [ -d "$ROOT" ] || continue
    NPM="$(ls "$ROOT"/binaries/node/versions/*/bin/npm 2>/dev/null | head -1)"
    [ -n "$NPM" ] && break
  done
fi
NODE_WS=""
for ROOT in "$WB_HOME" "$HOME/.workbuddy"; do
  if [ -d "$ROOT/binaries/node/workspace" ]; then NODE_WS="$ROOT/binaries/node/workspace"; break; fi
done

# 1) 读取凭据（优先技能目录 config.json；缺失回退 weather-common/config.json，
#    避免同一份口令存在两处、改密码要同步两个文件）
if [ ! -f "$CONFIG" ]; then
  FALLBACK="$(dirname "$SKILL_DIR")/weather-common/config.json"
  if [ -f "$FALLBACK" ]; then
    CONFIG="$FALLBACK"
    log "技能目录无 config.json，回退凭据: $CONFIG"
  fi
fi
if [ ! -f "$CONFIG" ]; then
  log "ERROR: 找不到凭据文件 $CONFIG" >&2
  log "请在该目录创建 config.json：{\"username\":\"...\",\"password\":\"...\"}" >&2
  exit 1
fi
USER=$("$PY" -c "import json;print(json.load(open('$CONFIG'))['username'])")
PASS=$("$PY" -c "import json;print(json.load(open('$CONFIG'))['password'])")

# 2) 确保 agent-browser 可用（缺失则尝试安装）
if [ -z "$AB" ] || [ ! -x "$AB" ]; then
  if [ -n "$NPM" ] && [ -d "$NODE_WS" ]; then
    log "agent-browser 未安装，尝试安装..."
    (cd "$NODE_WS" && "$NPM" install agent-browser && "$NODE_WS/node_modules/.bin/agent-browser" install) \
      || { log "ERROR: 安装失败" >&2; exit 1; }
    AB="$(ls "$NODE_WS"/node_modules/.bin/agent-browser 2>/dev/null | head -1)"
  else
    log "ERROR: 未找到 agent-browser，且无法自动安装（缺少 npm 或 node workspace）" >&2
    exit 1
  fi
fi

# 3) 打开站点（默认无头）
log "打开 https://leidian.wang"
"$AB" open https://leidian.wang >/dev/null 2>&1
"$AB" wait --load load >/dev/null 2>&1

# 4) 检查是否需要登录（不依赖中文匹配：按 textbox 顺序取账号/密码，button 取登录）
SNAP=$("$AB" snapshot -i 2>/dev/null | tr -d '\r')
if echo "$SNAP" | grep -q 'textbox '; then
  TEXTBOXES=$(echo "$SNAP" | grep -oE 'textbox [^[]*\[ref=[a-z0-9]+\]')
  ACC=$(echo "$TEXTBOXES" | sed -n '1p' | grep -oE 'ref=[a-z0-9]+' | sed 's/ref=//')
  PWD=$(echo "$TEXTBOXES" | sed -n '2p' | grep -oE 'ref=[a-z0-9]+' | sed 's/ref=//')
  BTN=$(echo "$SNAP" | grep -oE 'button [^[]*\[ref=[a-z0-9]+\]' | grep -oE 'ref=[a-z0-9]+' | sed 's/ref=//')
  if [ -z "$ACC" ] || [ -z "$PWD" ] || [ -z "$BTN" ]; then
    log "ERROR: 未能从登录页定位 账号/密码/登录按钮" >&2
    echo "$SNAP" >&2
    "$AB" close >/dev/null 2>&1; exit 1
  fi
  log "填写凭据并点击登录"
  "$AB" type "$ACC" "$USER" >/dev/null 2>&1
  "$AB" type "$PWD" "$PASS" >/dev/null 2>&1
  "$AB" click "$BTN" >/dev/null 2>&1
  "$AB" wait --load load >/dev/null 2>&1
else
  log "未检测到登录表单，假定已登录，直接取 token"
fi

# 5) 读取 token（带重试）
TOKEN=""
for i in 1 2 3 4 5; do
  RAW=$("$AB" eval "localStorage.getItem('access')" 2>/dev/null | tr -d '\r')
  TOKEN=$(echo "$RAW" | sed -E 's/^"//; s/"$//; s/^[[:space:]]+//; s/[[:space:]]+$//')
  if [ -n "$TOKEN" ] && echo "$TOKEN" | grep -qE '^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$'; then
    break
  fi
  sleep 2
done

if [ -z "$TOKEN" ] || [ "$TOKEN" = "null" ] || [ "$TOKEN" = "undefined" ]; then
  log "ERROR: 未能从 localStorage 取到有效的 access token（token=$TOKEN）" >&2
  "$AB" close >/dev/null 2>&1; exit 1
fi

# 6) 写回 mcp.json 并校验（mcp.json 路径通过参数传入，不硬编码）
log "写入 mcp.json 并校验"
"$PY" - "$TOKEN" "$MCP" <<'PYEOF'
import json, sys, base64, time
tok = sys.argv[1]; f = sys.argv[2]
d = json.load(open(f))
d["mcpServers"]["jozzon-mcp"]["headers"]["Authorization"] = "Bearer " + tok
json.dump(d, open(f, "w"), ensure_ascii=False, indent=2)
open(f, "a").write("\n")
p = tok.split(".")[1]; p += "=" * (-len(p) % 4)
claim = json.loads(base64.urlsafe_b64decode(p))
exp = claim["exp"]; now = int(time.time())
bt = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(exp))
print("OK 新token已写入。exp(北京时间)=%s  剩余=%d小时%02d分  有效=%s" % (
    bt, (exp-now)//3600, ((exp-now)%3600)//60, "YES" if now < exp else "NO"))
if now >= exp:
    print("WARN: token 已过期！"); sys.exit(2)
PYEOF
RC=$?

# 7) 关闭浏览器
"$AB" close >/dev/null 2>&1
log "完成 (rc=$RC)"
exit $RC
