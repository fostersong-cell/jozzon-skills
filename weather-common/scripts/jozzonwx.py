# -*- coding: utf-8 -*-
"""
jozzonwx —— 物探 / 石油工程天气看板「共享取数 + 分级」模块
=================================================================
2026-10-16 改造核心：把两套 skill 的取数从 Open-Meteo 切换到 jozzon-mcp（九章雷电网）。

取数（jozzon-mcp）
-----------------
jozzon-mcp 是 MCP 工具，按「目标区 ta_id」拉逐小时天气，不是 urllib 能直连的 REST。
本模块用 MCP Streamable-HTTP(JSON-RPC) 直连 https://mcp.jozzon.com/mcp，
带 mcp.json 里的 JWT，提供：
  - list_metrics()        查当前可用要素编码（get_weather_metrics）
  - resolve_codes()       把本模块要素名映射到 o1_ 编码
  - fetch_hourly(ta_id)   单个目标区逐小时天气（get_hourly_weather）
  - fetch_region(ta_ids)  批量（多目标区）

token 自动维护（2026-10-19 起；原独立 skill jozzon-mcp-token-refresh 已并入本模块并删除）
--------------------------------------------------------------------------------
mcp.json 里的 JWT 约 10 小时过期，过期后 MCP 调用 401 / 后端拒绝。
  - ensure_token()        取数前自检：过期（或剩余 < REFRESH_MARGIN=15min）时无头登录
                          https://leidian.wang 取新 access 写回 mcp.json；未过期直接放行。
                          两个取数 skill（weather-wutan-html / weather-engineering-data）
                          在主流程最前面调用。凭据：weather-common/config.json（600，git 忽略）。
  - token_info()          解码当前 token 的 exp / 剩余时长（只读，不刷新）。

要素与口径（2026-10-16 用户新定）
-------------------------------
  降雨 rainfall  = rain + showers 合并（mm/h）
  降雪 snowfall  = snowfall（mm/h，原 cm 口径统一转 mm）
  阵风 gust      = wind_gusts_10m（m/s）
  均风 wind      = wind_speed_10m（m/s，新增）
  温度 temp      = temperature_2m（℃，仅展示、不单独预警）
  体感温度 utci  = apparent_temperature -> 后端实际编码 o1_utci（℃，冷/热双向预警）
  能见度 vis     = visibility -> 后端实际编码 x1_visibility（**km，本模块统一 ×1000 转 m**）

⚠️ 能见度（2026-10-17 用户指出 + 实测）：get_weather_metrics 只列 o1_ 系列（51 个），
   **不含能见度**；但 get_hourly_weather 支持未文档化的 `x1_visibility`，值域 0.68~16.0，
   上限封顶 16.0 → 单位是 km。且只有**前 162 小时**有值，之后全是 null
   （o1_ 系要素 336h 齐全），故 48h 图完整、两周图只能覆盖前 7 天。
   故 x1_visibility 保留 None（不落 0），避免被当成「能见度 0 m」。

移除旧的 precipitation 总降水口径（不再作为独立要素）。

分级阈值（2026-10-16 用户新定；文本严格按用户口径）
---------------------------------------------------
  降雨 / 降雪：与旧阈值相同（沿用）。
  均风 / 能见度 / 体感温度(冷·热)：本次新增。
  阵风（2026-10-17 用户定）：**同级比均风高两级风力**，即
        「阵风八级 = 均风六级」，故阵风 1~4 级阈值 = 13.9 / 17.2 / 24.5 / 32.7 m/s
        （疾风七级 / 大风八级 / 狂风十级 / 飓风十二级）。
  plain 温度：仅展示，不单独预警（舒适度预警改由 体感温度 UTCI 承担）。

⚠️ o1_ 具体编码与 get_hourly_weather 返回结构在 jozzon-mcp 后端恢复前无法核实，
   相关解析均标 TBD，待 get_weather_metrics 正常后以 selfcheck 校准。
"""
import os
import sys
import json
import re
import glob
import shutil
import base64
import tempfile
import subprocess
import urllib.request
import urllib.error
import time

try:
    import fcntl                      # POSIX 文件锁（并行刷新去重）；Windows 缺席时退化为无锁
except ImportError:
    fcntl = None

# ===========================================================================
# 0. 路径与 token
# ===========================================================================
_HERE = os.path.dirname(os.path.abspath(__file__))
# 消费方脚本把本目录加入 sys.path 即可 `import jozzonwx`
COMMON_DIR = _HERE

MCP_URL = "https://mcp.jozzon.com/mcp"

def _mcp_json_path():
    """定位 ~/.workbuddy/mcp.json（兼容 WB_HOME 覆盖）。"""
    home = os.environ.get("WB_HOME") or os.path.expanduser("~")
    return os.path.join(home, ".workbuddy", "mcp.json")

def get_token():
    """JWT 来源优先级：env JOZZON_MCP_TOKEN > mcp.json[jozzon-mcp].headers.Authorization。"""
    env = os.environ.get("JOZZON_MCP_TOKEN")
    if env:
        return env if env.startswith("Bearer ") else "Bearer " + env
    try:
        with open(_mcp_json_path(), "r", encoding="utf-8") as f:
            cfg = json.load(f)
        hdr = (cfg.get("mcpServers", {}).get("jozzon-mcp", {})
               .get("headers", {}).get("Authorization", ""))
        if hdr:
            return hdr if hdr.startswith("Bearer ") else "Bearer " + hdr
    except Exception:
        pass
    raise RuntimeError("未找到 jozzon-mcp token：请设置 JOZZON_MCP_TOKEN 或检查 mcp.json")

# ===========================================================================
# 0.x token 过期自检 + 自动刷新（2026-10-19 由独立 skill jozzon-mcp-token-refresh 并入）
# ---------------------------------------------------------------------------
# mcp.json 的 JWT 约 10 小时过期；过期后 MCP 调用 401 / 后端拒绝。
# ensure_token()：解码 exp 检查有效期，过期（或剩余不足 REFRESH_MARGIN）时
# 无头登录 https://leidian.wang 取新 access 写回 mcp.json；未过期直接放行。
# 两个取数 skill 在主流程最前面调用；刷新失败返回 False，调用方应终止
# （避免带着坏 token 取数，把后端故障误报成「200 非 JSON」类灵异问题）。
# 凭据文件搜索顺序：env JOZZON_REFRESH_CONFIG > weather-common/config.json
#   > 旧 skill 路径（兼容过渡）。config.json 权限须 600，且已被 .gitignore 拦截。
# ===========================================================================
REFRESH_MARGIN = int(os.environ.get("JOZZON_TOKEN_MARGIN", "900"))   # 剩余 <15min 即主动刷新
LEIDIAN_URL = "https://leidian.wang"
_LOCK_PATH = os.path.join(tempfile.gettempdir(), "jozzon_token_refresh.lock")

def _credentials_path():
    """定位 leidian.wang 登录凭据 config.json。"""
    cands = []
    if os.environ.get("JOZZON_REFRESH_CONFIG"):
        cands.append(os.environ["JOZZON_REFRESH_CONFIG"])
    cands.append(os.path.join(os.path.dirname(_HERE), "config.json"))   # weather-common/config.json
    cands.append(os.path.expanduser("~/.workbuddy/skills/jozzon/jozzon-mcp-token-refresh/config.json"))
    for p in cands:
        if p and os.path.exists(p):
            return p
    return None

def _b64url_json(seg):
    seg += "=" * (-len(seg) % 4)
    return json.loads(base64.urlsafe_b64decode(seg))

def token_info():
    """解码当前 token 的 exp。返回 {ok, exp, remain, detail}；解析失败 ok=False（只读）。"""
    try:
        tok = get_token()
    except Exception as e:
        return {"ok": False, "exp": None, "remain": None, "detail": str(e)}
    try:
        payload = tok.split(" ", 1)[-1].split(".")[1]
        exp = int(_b64url_json(payload)["exp"])
        return {"ok": True, "exp": exp, "remain": exp - int(time.time()),
                "detail": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(exp))}
    except Exception as e:
        return {"ok": False, "exp": None, "remain": None, "detail": f"token 解析失败: {e}"}

def _fmt_remain(remain):
    return f"{remain // 3600} 小时 {remain % 3600 // 60} 分"

def _find_agent_browser():
    """定位 agent-browser CLI：PATH → 各候选 root 的 node workspace / versions bin。
    候选 root：env WB_HOME 与 $HOME/.workbuddy（两者语义不同都试，取到即用）。"""
    p = shutil.which("agent-browser")
    if p:
        return p
    roots = []
    if os.environ.get("WB_HOME"):
        roots.append(os.environ["WB_HOME"])
    roots.append(os.path.join(os.path.expanduser("~"), ".workbuddy"))
    for root in roots:
        ws = os.path.join(root, "binaries", "node", "workspace",
                          "node_modules", ".bin", "agent-browser")
        if os.path.exists(ws):
            return ws
        vers = sorted(glob.glob(os.path.join(
            root, "binaries", "node", "versions", "*", "bin", "agent-browser")), reverse=True)
        if vers:
            return vers[0]
    return None

def _ensure_agent_browser():
    """找到 agent-browser；缺失则尝试在托管 node workspace 安装（需 npm）。"""
    ab = _find_agent_browser()
    if ab:
        return ab
    ws = os.path.join(os.path.expanduser("~"), ".workbuddy", "binaries", "node", "workspace")
    npm = shutil.which("npm")
    if not npm:
        for cand in sorted(glob.glob(os.path.join(
                os.path.expanduser("~"), ".workbuddy", "binaries", "node", "versions", "*", "bin", "npm")),
                reverse=True):
            if os.path.exists(cand):
                npm = cand
                break
    if npm and os.path.isdir(ws):
        try:
            subprocess.run([npm, "install", "agent-browser"], cwd=ws,
                           capture_output=True, text=True, timeout=600)
            binp = os.path.join(ws, "node_modules", ".bin", "agent-browser")
            if os.path.exists(binp):
                subprocess.run([binp, "install"], capture_output=True, text=True, timeout=600)
                return binp
        except Exception as e:
            raise RuntimeError(f"agent-browser 自动安装失败: {e}")
    raise RuntimeError("未找到 agent-browser，且无法自动安装（需 npm 与 node workspace）")

def _ab_run(ab, args, timeout=120):
    """跑一条 agent-browser 命令（LC_ALL=C 稳定输出解析）。"""
    env = dict(os.environ)
    env["LC_ALL"] = "C"
    return subprocess.run([ab] + args, capture_output=True, text=True,
                          timeout=timeout, env=env)

def _write_token(tok):
    """把新 token 写回 mcp.json（仅改 jozzon-mcp 的 Authorization，其余原样保留），并校验 exp。"""
    path = _mcp_json_path()
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    d.setdefault("mcpServers", {}).setdefault("jozzon-mcp", {}) \
        .setdefault("headers", {})["Authorization"] = "Bearer " + tok
    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
        f.write("\n")
    info = token_info()
    if not info["ok"] or info["remain"] <= 0:
        raise RuntimeError("新 token 写入后校验失败（仍过期或解析失败）")
    return info

def _refresh_via_browser(verbose=True):
    """无头登录 leidian.wang → 读 localStorage.access → 写回 mcp.json。返回新 token_info。"""
    ab = _ensure_agent_browser()
    cred = _credentials_path()
    if not cred:
        raise RuntimeError("未找到刷新凭据 config.json（weather-common/config.json 或 env JOZZON_REFRESH_CONFIG）")
    with open(cred, encoding="utf-8") as f:
        c = json.load(f)
    user, pw = c.get("username"), c.get("password")
    if not user or not pw:
        raise RuntimeError(f"凭据文件缺少 username/password: {cred}")
    try:
        _ab_run(ab, ["open", LEIDIAN_URL], timeout=120)
        _ab_run(ab, ["wait", "--load", "load"], timeout=120)
        snap = _ab_run(ab, ["snapshot", "-i"], timeout=60)
        out = snap.stdout or ""
        tbs = re.findall(r"textbox [^\[]*\[ref=([a-z0-9]+)\]", out)
        bts = re.findall(r"button [^\[]*\[ref=([a-z0-9]+)\]", out)
        if tbs and bts:
            if verbose:
                print("  [token-refresh] 检测到登录页，填写凭据并登录…")
            _ab_run(ab, ["type", tbs[0], user], timeout=60)
            if len(tbs) > 1:
                _ab_run(ab, ["type", tbs[1], pw], timeout=60)
            _ab_run(ab, ["click", bts[0]], timeout=60)
            _ab_run(ab, ["wait", "--load", "load"], timeout=120)
        tok = ""
        for _ in range(5):
            raw = _ab_run(ab, ["eval", "localStorage.getItem('access')"], timeout=60)
            m = re.search(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", raw.stdout or "")
            if m:
                tok = m.group(0)
                break
            time.sleep(2)
        if not tok:
            raise RuntimeError("未能从 localStorage 取到有效 access token")
        return _write_token(tok)
    finally:
        try:
            _ab_run(ab, ["close"], timeout=30)
        except Exception:
            pass

def ensure_token(force=False, margin=None, verbose=True):
    """取数前 token 自检 + 按需刷新。返回 True=token 可用；失败返回 False（调用方应终止）。
    force=True 无视有效期强制刷新。并行流水线用文件锁去重（只刷新一次，其余复检放行）。"""
    margin = REFRESH_MARGIN if margin is None else margin
    info = token_info()
    if info["ok"] and info["remain"] > margin and not force:
        if verbose:
            print(f"[jozzon-mcp] token 有效（至 {info['detail']}，剩余 {_fmt_remain(info['remain'])}），无需刷新")
        return True
    if force:
        why = "强制刷新"
    elif info["ok"] and info["remain"] <= 0:
        why = "token 已过期"
    elif info["ok"]:
        why = f"token 即将过期（剩余 {_fmt_remain(info['remain'])}）"
    else:
        why = info["detail"]
    if verbose:
        print(f"[jozzon-mcp] {why}，开始自动刷新 token…")
    lockf = None
    try:
        if fcntl is not None:
            lockf = open(_LOCK_PATH, "w")
            fcntl.flock(lockf, fcntl.LOCK_EX)     # 等锁期间可能已被其它进程刷新
            info2 = token_info()
            if info2["ok"] and info2["remain"] > margin and not force:
                if verbose:
                    print(f"[jozzon-mcp] 其它进程已刷新，token 有效（至 {info2['detail']}）")
                return True
        info = _refresh_via_browser(verbose=verbose)
        if verbose:
            print(f"[jozzon-mcp] token 刷新成功（至 {info['detail']}，剩余 {_fmt_remain(info['remain'])}）")
        return True
    except Exception as e:
        print(f"[jozzon-mcp] token 刷新失败: {e}")
        return False
    finally:
        if lockf is not None:
            try:
                fcntl.flock(lockf, fcntl.LOCK_UN)
            except Exception:
                pass
            lockf.close()

# ===========================================================================
# 1. MCP JSON-RPC 客户端（Streamable HTTP）
# ===========================================================================
_PROTOCOL = "2025-06-18"   # 与 mcp.jozzon.com 协商；initialize 后服务端可能回更低版本
_session = {"id": None, "initialized": False}

def _post(payload, session_id=None):
    """POST 一个 JSON-RPC 请求，兼容 JSON 与 text/event-stream(SSE) 响应。
    返回解析后的 JSON 对象（可能是 result 或 error）。"""
    token = get_token()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Authorization": token,
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(MCP_URL, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8")
            sid = resp.headers.get("Mcp-Session-Id") or resp.headers.get("mcp-session-id")
            if sid:
                _session["id"] = sid
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"MCP HTTP {e.code}: {body[:500]}")
    # SSE：多行 `data: {json}`；取最后一个含 result/error 的 data 帧
    if "text/event-stream" in (resp.headers.get("Content-Type", "") if 'resp' in dir() else ""):
        pass
    if body.lstrip().startswith("event:") or "data:" in body[:200]:
        last = None
        for line in body.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                chunk = line[len("data:"):].strip()
                if not chunk or chunk == "[DONE]":
                    continue
                try:
                    last = json.loads(chunk)
                except Exception:
                    continue
        if last is not None:
            return last
    try:
        return json.loads(body)
    except Exception:
        raise RuntimeError(f"MCP 响应非 JSON（状态码应为 200 但体为 HTML/其他）：\n{body[:300]}")

def _ensure_initialized():
    if _session["initialized"]:
        return
    init = _post({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": _PROTOCOL,
            "capabilities": {},
            "clientInfo": {"name": "workbuddy-weather", "version": "1.0"},
        },
    })
    if "error" in init:
        raise RuntimeError(f"MCP initialize 失败: {init['error']}")
    # 发送 initialized 通知（无 id）
    note = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
    try:
        _post(note, _session["id"])
    except Exception:
        pass
    _session["initialized"] = True

def mcp_call(tool, arguments):
    """调用一个 MCP 工具，返回工具的「业务结果」（已剥掉 jsonrpc 外壳）。
    约定：get_weather_metrics / get_hourly_weather 的结果为 {success, reply, data|error}。"""
    _ensure_initialized()
    msg = {
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }
    r = _post(msg, _session["id"])
    if "error" in r:
        raise RuntimeError(f"MCP tools/call {tool} 失败: {r['error']}")
    res = r.get("result", {})
    # 结果通常在 content[].text（JSON 字符串）或 result 本身就是业务结构
    content = res.get("content")
    if isinstance(content, list):
        for blk in content:
            if isinstance(blk, dict) and blk.get("type") == "text":
                txt = blk.get("text", "")
                try:
                    return json.loads(txt)
                except Exception:
                    return {"success": True, "reply": txt, "data": None}
    # 某些实现直接把结构化结果放在 result 下
    if "success" in res or "data" in res:
        return res
    return res

# ===========================================================================
# 2. 要素 → jozzon-mcp 编码 解析
# ===========================================================================
# 本模块使用的要素键（与消费方 schema 一致）
ELEMENTS = ["rain", "showers", "snowfall", "wind_speed_10m",
            "wind_gusts_10m", "temperature_2m", "apparent_temperature", "visibility"]

# 编码猜测提示（后端恢复后由真实 metrics 校准；匹配 code/name 小写包含任一关键词）
METRIC_HINTS = {
    "rain":                 ["rain", "precip_rain"],
    "showers":              ["shower", "rain_shower"],
    "snowfall":             ["snow"],
    "wind_speed_10m":       ["wind_speed", "wind_mean", "mean_wind", "wind_10m", "u10"],
    "wind_gusts_10m":       ["gust", "wind_gust", "gusts_10m"],
    "temperature_2m":       ["temperature_2m", "temp_2m", "temperature", "t2m"],
    "apparent_temperature": ["apparent", "utci", "feels_like", "feels"],
    "visibility":           ["x1_visibility", "visibility", "vis"],
}

# 钉死编码（2026-10-17）：get_weather_metrics 只列 o1_ 系列，能见度不在其中，
# 但 get_hourly_weather 实测支持未文档化的 x1_visibility（单位 km）。
# 关键词猜测对 visibility 无效（o1_ 里没有该要素，会被静默丢弃），故在此钉死。
FIXED_CODES = {
    "visibility": "x1_visibility",
}

# 单位换算：后端 x1_visibility 为 km → 内部统一 m
UNIT_SCALE = {
    "visibility": 1000.0,
}

# 用户可把已确认的编码钉死在 resolved_codes.json（同目录），优先级高于关键词猜测
_RESOLVED_PATH = os.path.join(_HERE, "resolved_codes.json")

def list_metrics():
    """返回 get_weather_metrics 的 data（要素列表，每项含 code/name/...）。"""
    out = mcp_call("get_weather_metrics", {})
    if not out.get("success", False):
        raise RuntimeError(f"get_weather_metrics 失败: {out.get('reply')} {out.get('error')}")
    return out.get("data", [])

def load_resolved_override():
    try:
        with open(_RESOLVED_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_resolved_override(mapping):
    with open(_RESOLVED_PATH, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)

def resolve_codes(metrics=None, save=True):
    """把 ELEMENTS 各要素映射到 jozzon-mcp 的 o1_ 编码。
    metrics 省略时自动 list_metrics()；命中 resolved_codes.json 则优先用钉死值。"""
    override = load_resolved_override()
    if metrics is None:
        metrics = list_metrics()
    # 建索引：code 与 name 小写
    idx = []
    for m in metrics:
        code = (m.get("code") or "").lower()
        name = (m.get("name") or m.get("description") or "").lower()
        idx.append((code, name, m.get("code")))
    out = {}
    for el in ELEMENTS:
        if el in override:
            out[el] = override[el]
            continue
        if el in FIXED_CODES:                 # 2026-10-17：钉死编码优先（能见度走 x1_）
            out[el] = FIXED_CODES[el]
            continue
        hints = METRIC_HINTS.get(el, [el])
        hit = None
        for code, name, orig in idx:
            if any(h in code or h in name for h in hints):
                hit = orig
                break
        if hit:
            out[el] = hit
        else:
            # TBD：未匹配到，给一个可后续替换的占位编码并告警
            out[el] = f"o1_{el}"
            print(f"  ⚠️ 未匹配到要素 {el} 的 o1_ 编码，暂用占位 {out[el]}（后端恢复后请 selfcheck 校准）")
    if save:
        # 仅保存真实命中（非占位）以免把占位写死
        real = {k: v for k, v in out.items() if not v.startswith("o1_")}
        if real:
            save_resolved_override({**override, **real})
    return out

# ===========================================================================
# 3. 逐小时取数
# ===========================================================================
# get_hourly_weather 返回结构在核实前按多种可能形态解析：
#   A) {"time":[...], "<code>":[...], ...}                —— 扁平：时间列 + 每要素一列
#   B) {"<code>": {"time":[...], "value":[...]}}          —— 每要素一个对象
#   C) [{"time":..., "<code>":v, ...}, ...]               —— 记录数组（pivot）
#   D) {"coords":{"valid_time":{"data":[ISO...]}},
#       "data_vars":{"<code>":{"data":[...]}}, ...}       —— xarray 风格（2026-10-16 起后端现行格式）
# 解析后统一为 {code: [values]} 与共享 times。

def _extract_series(data):
    """返回 (times, {code: [values]})。兼容 A/B/C/D 四种形态。"""
    if isinstance(data, dict) and "data_vars" in data and "coords" in data:
        # 形态 D：xarray 风格（现行）
        coords = data.get("coords") or {}
        times = []
        for key in ("valid_time", "time", "datetime", "date"):
            obj = coords.get(key)
            if isinstance(obj, dict) and isinstance(obj.get("data"), list):
                times = obj["data"]
                break
        if not times:                     # 退路：任一坐标的 data 为字符串序列即视为时间轴
            for obj in coords.values():
                vals = (obj or {}).get("data") if isinstance(obj, dict) else None
                if isinstance(vals, list) and vals and isinstance(vals[0], str):
                    times = vals
                    break
        series = {}
        for code, obj in (data.get("data_vars") or {}).items():
            vals = (obj or {}).get("data") if isinstance(obj, dict) else None
            if isinstance(vals, list):
                series[code] = vals
        if times or series:
            return times, series
    if isinstance(data, list):
        # 形态 C
        times = [r.get("time") for r in data]
        codes = set()
        for r in data:
            for k in r:
                if k != "time":
                    codes.add(k)
        series = {c: [r.get(c) for r in data] for c in codes}
        return times, series
    if isinstance(data, dict):
        if "time" in data and any(isinstance(v, list) for kk, v in data.items() if kk != "time"):
            # 形态 A
            times = data.get("time") or []
            series = {k: v for k, v in data.items() if k != "time" and isinstance(v, list)}
            return times, series
        # 形态 B
        times = None
        series = {}
        for c, obj in data.items():
            if isinstance(obj, dict) and "value" in obj:
                series[c] = obj.get("value") or []
                if times is None:
                    times = obj.get("time") or []
        if times is not None:
            return times, series
    raise RuntimeError(f"无法解析 get_hourly_weather 返回结构：{str(data)[:200]}")

def fetch_hourly(ta_id, codes=None, forecast_hours=336, past_hours=0,
                 time_zone="Asia/Shanghai"):
    """单个目标区逐小时天气 → 归一化逐时序列字典（要素键见 ELEMENTS + rainfall）。
    codes 省略时自动 resolve_codes()。返回:
      {"ta_id":, "time":[ISO], "rain":[], "showers":[], "snowfall":[],
       "wind_speed_10m":[], "wind_gusts_10m":[], "temperature_2m":[],
       "apparent_temperature":[], "visibility":[], "rainfall":[rain+showers]}
    """
    if codes is None:
        codes = resolve_codes()
    # 只取本模块需要的编码（去重保序）
    need = list(dict.fromkeys(codes.get(el) for el in ELEMENTS if codes.get(el)))
    out = mcp_call("get_hourly_weather", {
        "ta_id": int(ta_id),
        "metric_code": need,
        "forecast_hours": int(forecast_hours),
        "past_hours": int(past_hours),
        "time_zone": time_zone,
    })
    if not out.get("success", False):
        raise RuntimeError(f"get_hourly_weather(ta_id={ta_id}) 失败: {out.get('reply')} {out.get('error')}")
    times, series = _extract_series(out.get("data", {}))
    # 反查每个要素对应的真实返回 code（允许返回 code 与请求 code 大小写/后缀不同）
    def pick(el):
        want = codes.get(el)
        if want in series:
            return series.get(want)
        # 模糊匹配：返回 code 含要素提示
        for h in METRIC_HINTS.get(el, [el]):
            for c, vals in series.items():
                if h in c.lower():
                    return vals
        return [0.0] * len(times) if times else []
    res = {
        "ta_id": int(ta_id),
        "time": times,
        "rain": _num(pick("rain")),
        "showers": _num(pick("showers")),
        "snowfall": _num(pick("snowfall")),
        "wind_speed_10m": _num(pick("wind_speed_10m")),
        "wind_gusts_10m": _num(pick("wind_gusts_10m")),
        "temperature_2m": _num(pick("temperature_2m")),
        "apparent_temperature": _num(pick("apparent_temperature")),
        # 能见度：km → m；保留 None（x1_visibility 只有前 162h 有值，
        # 落 0 会被误读成「能见度 0 m / 极差」，下游一律按 `is not None and >0` 取最小值）
        "visibility": _num(pick("visibility"),
                           keep_none=True, scale=UNIT_SCALE.get("visibility", 1.0)),
    }
    res["rainfall"] = [round(a + b, 2) for a, b in zip(res["rain"], res["showers"])]
    return res

def fetch_region(ta_ids, forecast_hours=336, past_hours=0, time_zone="Asia/Shanghai"):
    """批量：每个 ta_id 一次 get_hourly_weather（jozzon-mcp 按目标区取数，无批量接口）。
    返回 list[归一化逐时序列]。"""
    codes = resolve_codes()
    res = []
    for tid in ta_ids:
        res.append(fetch_hourly(tid, codes, forecast_hours, past_hours, time_zone))
        time.sleep(0.3)  # 轻量冷却，避免触发限流
    return res

def _num(seq, keep_none=False, scale=1.0):
    """把可能为 None/字符串的序列规整为 float 列表。
    keep_none=True 时保留缺失为 None（供能见度等「缺测 ≠ 0」的要素使用）；
    scale 为单位换算系数（能见度 km→m 用 1000）。"""
    out = []
    for v in (seq or []):
        if v is None or v == "":
            out.append(None if keep_none else 0.0)
        else:
            try:
                out.append(round(float(v) * scale, 2))
            except Exception:
                out.append(None if keep_none else 0.0)
    return out

# ===========================================================================
# 4. 分级阈值（2026-10-16 用户新定）
# ===========================================================================
# 降雨（mm/h）：与旧 RAIN_ALERT 相同（沿用）
RAIN_ALERT = {0: "降雨正常", 1: "小雨预警(0.2mm/h)", 2: "中雨预警(1.5mm/h)",
              3: "大雨预警(3mm/h)", 4: "暴雨预警(6mm/h)", 5: "大暴雨预警(15mm/h)"}
# 降雪（mm/h）：与旧 SNOW_ALERT 相同（沿用）
SNOW_ALERT = {0: "正常", 1: "小雪预警(>0.1mm/h)", 2: "中雪预警(>0.5mm/h)",
              3: "大雪预警(>1mm/h)", 4: "暴雪预警(>2mm/h)"}
# 均风（m/s，新增）
WIND_ALERT = {0: "正常均风", 1: "劲风五级预警(8.0m/s)", 2: "强风六级预警(10.8m/s)",
              3: "大风八级预警(17.2m/s)", 4: "狂风十级预警(24.5m/s)"}
# 体感温度 UTCI（冷，℃）
UTCI_COLD = {0: "UTCI正常", 1: "低风险寒冷预警(<0)", 2: "中风险严寒预警(<-13)",
             3: "高风险酷寒预警(<-27)", 4: "极高风险极寒预警(<-40)"}
# 体感温度 UTCI（热，℃）
UTCI_HOT = {0: "UTCI正常", 1: "低风险偏热预警(>26)", 2: "中风险炎热预警(>32)",
            3: "高风险酷热预警(>38)", 4: "极高风险极热预警(>46)"}
# 能见度（m）
VIS_ALERT = {0: "正常能见度", 1: "能见度小于1公里预警(<1000m)", 2: "能见度小于500米预警(<500m)",
             3: "能见度小于200米预警(<200m)", 4: "能见度小于100米预警(<100m)"}
# 阵风（m/s）：同级比均风高两级风力 —— 阵风八级(17.2) = 均风六级(10.8)。
# 2026-10-17 用户定：1~4 级 = 疾风七级 / 大风八级 / 狂风十级 / 飓风十二级。
GUST_ALERT = {0: "阵风正常", 1: "疾风七级预警(13.9m/s)", 2: "大风八级预警(17.2m/s)",
              3: "狂风十级预警(24.5m/s)", 4: "飓风十二级预警(32.7m/s)"}

# 短标签（去掉阈值数字，供卡片/列表紧凑展示；与上面的完整标签同源）
RAIN_ALERT_S  = {0: "降雨正常", 1: "小雨预警", 2: "中雨预警", 3: "大雨预警", 4: "暴雨预警", 5: "大暴雨预警"}
SNOW_ALERT_S  = {0: "正常", 1: "小雪预警", 2: "中雪预警", 3: "大雪预警", 4: "暴雪预警"}
WIND_ALERT_S  = {0: "均风正常", 1: "劲风五级预警", 2: "强风六级预警", 3: "大风八级预警", 4: "狂风十级预警"}
GUST_ALERT_S  = {0: "阵风正常", 1: "疾风七级预警", 2: "大风八级预警", 3: "狂风十级预警", 4: "飓风十二级预警"}
UTCI_HOT_S   = {0: "温度正常", 1: "偏热预警", 2: "炎热预警", 3: "酷热预警", 4: "极热预警"}
UTCI_COLD_S  = {0: "温度正常", 1: "寒冷预警", 2: "严寒预警", 3: "酷寒预警", 4: "极寒预警"}
VIS_ALERT_S  = {0: "能见度正常", 1: "能见度偏低预警", 2: "能见度差预警", 3: "能见度劣预警", 4: "能见度极低预警"}

# 阈值数值（分级函数用）
_RAIN_TH = [(15, 5), (6, 4), (3, 3), (1.5, 2), (0.2, 1)]
_SNOW_TH = [(2, 4), (1, 3), (0.5, 2), (0.1, 1)]
_WIND_TH = [(24.5, 4), (17.2, 3), (10.8, 2), (8.0, 1)]
# 阵风：同级比均风高两级风力（八级阵风 17.2 = 六级均风 10.8）→ 阈值整体上移两档
_GUST_TH = [(32.7, 4), (24.5, 3), (17.2, 2), (13.9, 1)]
_VIS_TH = [(100, 4), (200, 3), (500, 2), (1000, 1)]   # 值越小越严重

def _lv(thresholds, v, reverse=False):
    """thresholds: [(边界值, 等级), ...] 降序；reverse=True 时边界越小越严重（能见度）。"""
    if v is None:
        return 0
    for bound, lv in thresholds:
        if reverse:
            if v < bound:
                return lv
        else:
            if v >= bound:
                return lv
    return 0

def grade_rain(mmh):       return _lv(_RAIN_TH, mmh)
def grade_snow(mmh):       return _lv(_SNOW_TH, mmh)
def grade_wind(mps):       return _lv(_WIND_TH, mps)
def grade_gust(mps):       return _lv(_GUST_TH, mps)
def grade_vis(m):          return _lv(_VIS_TH, m, reverse=True)

def grade_utci(v):
    """体感温度 UTCI 双向分级：返回 (level, label)。冷/热取较严重一侧。"""
    if v is None:
        return 0, UTCI_COLD[0]
    cold = 0
    if v < -40: cold = 4
    elif v < -27: cold = 3
    elif v < -13: cold = 2
    elif v < 0: cold = 1
    hot = 0
    if v > 46: hot = 4
    elif v > 38: hot = 3
    elif v > 32: hot = 2
    elif v > 26: hot = 1
    if hot >= cold:
        return hot, UTCI_HOT[hot]
    return cold, UTCI_COLD[cold]

def utci_dir(v):
    """返回 'cold' / 'hot' / 'normal'，指示 UTCI 触发方向（供渲染着色）。"""
    if v is None:
        return "normal"
    if v < 0:
        return "cold"
    if v > 26:
        return "hot"
    return "normal"

def alert_items(rain_mmh, snow_mmh, wind, gust, apparent, vis):
    """返回触发的预警文字列表（仅 level>=1）。各要素独立判定，可同时多条。
    与旧 alert_items 区别：降雨=降雨、降雪、均风、阵风、UTCI(冷+热)、能见度；
    plain 温度不再单独预警（由 UTCI 承担）。"""
    out = []
    r = grade_rain(rain_mmh)
    if r: out.append(RAIN_ALERT[r])
    s = grade_snow(snow_mmh)
    if s: out.append(SNOW_ALERT[s])
    w = grade_wind(wind)
    if w: out.append(WIND_ALERT[w])
    g = grade_gust(gust)
    if g: out.append(GUST_ALERT[g])
    lv, lbl = grade_utci(apparent)
    if lv: out.append(lbl)
    v = grade_vis(vis)
    if v: out.append(VIS_ALERT[v])
    return out

# 48h 小时级短时降水阈值（与旧 RAIN_H 一致，仅供渲染/一致性兜底复用）
RAIN_H = {"heavy": 3.0, "storm": 6.0, "torrent": 15.0}

# ===========================================================================
# 4.x 48h 峰值 + 综合风险等级（两套 skill 统一复用，避免分级漂移）
# ---------------------------------------------------------------------------
# 各要素等级 → 综合风险等级（0整体适宜/1需关注/2重点关注/3高度警惕）。
# 阵风（2026-10-17）：阈值已上移两档，同级与均风等价（阵风八级 = 均风六级），
# 故 gust 的映射与 wind 完全一致，不再压平。
# 降雨 大暴雨(lv5)=高度警惕；其余要素 lv4=高度警惕、lv3=重点关注、lv2=需关注。
# ===========================================================================
_LV2SEV = {
    "rain":  {0: 0, 1: 0, 2: 1, 3: 1, 4: 2, 5: 3},
    "snow":  {0: 0, 1: 0, 2: 1, 3: 2, 4: 3},
    "wind":  {0: 0, 1: 0, 2: 1, 3: 2, 4: 3},
    "gust":  {0: 0, 1: 0, 2: 1, 3: 2, 4: 3},
    "utci":  {0: 0, 1: 0, 2: 1, 3: 2, 4: 3},
    "vis":   {0: 0, 1: 0, 2: 1, 3: 2, 4: 3},
}

def peaks_48h(hourly):
    """从逐小时序列计算各要素 48h 峰值（自动取前 48 格；传入的已是窗口亦可）。
    返回 dict：rain/snow(mm/h)，wind/gust(m/s)，tmax/tmin/appMax/appMin(℃)，
    visMin(m，仅取正能见度最小值)。"""
    def arr(key):
        v = (hourly or {}).get(key) or []
        return list(v[:48])
    rain = arr("rainfall"); snow = arr("snowfall")
    wind = arr("wind_speed_10m"); gust = arr("wind_gusts_10m")
    temp = arr("temperature_2m"); appr = arr("apparent_temperature"); vis = arr("visibility")
    def mx(s): return max(s) if s else 0.0
    def mn(s): return min(s) if s else 0.0
    vis_pos = [v for v in vis if v and v > 0]
    return {
        "rain": mx(rain), "snow": mx(snow),
        "wind": mx(wind), "gust": mx(gust),
        "tmax": mx(temp), "tmin": mn(temp),
        "appMax": mx(appr), "appMin": mn(appr),
        "visMin": min(vis_pos) if vis_pos else None,
    }

def el_levels(p):
    """各要素 48h 等级（新口径，统一用本模块 grade_*）。
    p 字段：rain/snow/wind/gust(数值) 或 appMin/appMax/visMin(可为 None)。"""
    utci = 0
    if p.get("appMin") is not None:
        utci = max(utci, grade_utci(p["appMin"])[0])
    if p.get("appMax") is not None:
        utci = max(utci, grade_utci(p["appMax"])[0])
    return {
        "rain": grade_rain(p.get("rain", 0.0)),
        "snow": grade_snow(p.get("snow", 0.0)),
        "wind": grade_wind(p.get("wind", 0.0)),
        "gust": grade_gust(p.get("gust", 0.0)),
        "utci": utci,
        "vis": grade_vis(p["visMin"]) if p.get("visMin") is not None else 0,
    }

def sev_from_levels(lv):
    """综合风险等级 0-3：取各要素等级映射后的最大值。"""
    s = 0
    for k, v in lv.items():
        s = max(s, _LV2SEV.get(k, {}).get(v, 0))
    return s

# ===========================================================================
# 5. 自检（后端恢复后运行：python jozzonwx.py selfcheck）
# ===========================================================================
def selfcheck():
    print("== jozzonwx selfcheck ==")
    info = token_info()
    if info["ok"]:
        print(f"token: OK（exp(北京时间)= {info['detail']}，剩余 {_fmt_remain(info['remain'])}）")
    else:
        print("token: 不可用 -", info["detail"])
        print("提示：运行 `python jozzonwx.py ensure-token` 可自动刷新")
    try:
        ms = list_metrics()
        print(f"可用要素数: {len(ms)}")
        for m in ms[:30]:
            print("  ", m.get("code"), "-", m.get("name") or m.get("description"))
    except Exception as e:
        print("list_metrics 失败:", repr(e))
        return
    try:
        codes = resolve_codes(ms)
        print("解析到的要素编码:")
        for el, c in codes.items():
            print(f"  {el:20s} -> {c}")
    except Exception as e:
        print("resolve_codes 失败:", repr(e))

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "selfcheck":
        selfcheck()
    elif cmd == "token-status":
        info = token_info()
        if info["ok"]:
            print(f"token exp(北京时间)= {info['detail']}  剩余= {_fmt_remain(info['remain'])}  "
                  f"有效= {'YES' if info['remain'] > 0 else 'NO'}")
            sys.exit(0 if info["remain"] > 0 else 2)
        print("token 不可用:", info["detail"])
        sys.exit(2)
    elif cmd == "ensure-token":
        sys.exit(0 if ensure_token(force="--force" in sys.argv[2:]) else 1)
    else:
        print("用法: python jozzonwx.py selfcheck | token-status | ensure-token [--force]")
