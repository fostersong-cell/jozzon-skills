# -*- coding: utf-8 -*-
"""
富媒体天气看板 HTML 交付前质量门禁（基于 Chrome CDP）

做的事:
  1. 无头 Chrome 加载生成的 HTML
  2. 捕获 console.error / Runtime.exceptionThrown（任何 JS 报错即 FAIL）
  3. 注入模拟点击（取最后一个有效作业点索引），确认地图下方联动面板已渲染
  4. 检查 body.sevN 类是否按严重程度正确挂载（severity 变色依据）
  5. 输出 PASS / FAIL 与关键诊断。

⚠️ 断言口径已于 2026-10-16 同步到当前 DOM / 图表口径（此前会误报 FAIL，勿再退回旧断言）：
  - `#riskReason` 面板现行结构是 `.rr-h` + **`.rr-cur`（当前时刻）** + **`.rr-valrow`（降水/气温/阵风/均风 四个 `<b>` 值）**；
    **旧的 `.rr-pc`×4（要素级值四宫格）与 `.rr-sev`（面板内风险徽章）已不再输出**（CSS 尚存但 DOM 不生成，
    风险等级改由顶部 `#alertBox` 与 `body.sevN` 承担）→ 故不再断言 `.rr-pc` / `.rr-sev`。
  - `#explorerCharts` 现在是**固定四图**（`EXP_CHARTS=["precip","temp","wind","vis"]`），`.ec` 数量应为 **3~4**：
    **九章后端当前没有 `visibility` 要素**（`meta.data_source` 侧 `hasVis=false`），能见度图按 `pt.hasVis` 守卫正确省略，
    故实测常为 **3**。只有当后端补齐能见度后才会回到 4。断言据此放宽为 `3 <= ec <= 4`，**不是**模板缺图。

依赖: pip install websocket-client；本机需安装 Google Chrome。
用法:
  python validate.py --html "/path/大关项目工区.html" [--chrome "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
"""
import argparse, json, os, sys, time, subprocess, tempfile, shutil, urllib.request, urllib.parse
import websocket

ap = argparse.ArgumentParser()
ap.add_argument("--html", required=True, help="待校验的 HTML 路径")
ap.add_argument("--chrome", default=None, help="Chrome 可执行文件路径；未指定时按操作系统自动探测")
ap.add_argument("--port", type=int, default=9333)
args = ap.parse_args()

# ⚠️ 必须转绝对路径：`file://` 只接受绝对路径，传相对路径会拼出 `file://wutan/...`
#    这种非法 URL → Chrome 落到 `neterror` 错误页 → 整页假 FAIL（曾误判模板有病）。
args.html = os.path.abspath(os.path.expanduser(args.html))

if not os.path.exists(args.html):
    print("FAIL: 文件不存在", args.html); sys.exit(2)

os.environ["no_proxy"] = "*"; os.environ["NO_PROXY"] = "*"
urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))

port = args.port
# ⚠️ 不要写字面量 "<TMP>/…"（那是文档占位符）——会在当前工作目录建一个名为 "<TMP>" 的垃圾目录。
#    按跨平台约定统一走 tempfile.mkdtemp()，收尾在 finally 里清理。
profile = tempfile.mkdtemp(prefix="cdp_profile_wb_validate_")

def _resolve_chrome(explicit=None):
    """返回 Chrome 可执行路径；未指定时按操作系统自动探测，找不到返回 None。"""
    import shutil
    if explicit and os.path.exists(explicit):
        return explicit
    cands = []
    if sys.platform.startswith("win") or os.name == "nt":
        cands = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]
    elif sys.platform == "darwin":
        cands = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    else:
        cands = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]
    for c in cands:
        if not c:
            continue
        if os.path.sep in c or c.startswith("~"):
            p = os.path.expanduser(c)
            if os.path.exists(p):
                return p
        else:
            found = shutil.which(c)
            if found:
                return found
    return None

chrome = _resolve_chrome(args.chrome)
if not chrome:
    print("FAIL: 未找到 Chrome，请通过 --chrome 指定路径，或安装 Google Chrome")
    sys.exit(2)

proc = subprocess.Popen(
    # ⚠️ 用 --headless=new：新版 Chrome 已移除旧 headless（写 --headless 会静默退化/加载不出页面，
    #    表现为「#riskReason 不存在 + body.className 为空」的整页假 FAIL）。
    [chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run",
     "--allow-file-access-from-files",
     "--remote-allow-origins=*", f"--remote-debugging-port={port}", f"--user-data-dir={profile}"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
errors = []
ok = True

try:
    # 轮询等待 Chrome CDP 就绪（冷启动新建 profile 可能 >3s，一次性 sleep(3) 会连不上）
    ws_url = None
    for _attempt in range(25):
        if _attempt:
            time.sleep(1)
        raw = None
        for hh in ("[::1]", "127.0.0.1", "localhost"):
            for ep in (f"http://{hh}:{port}/json/list", f"http://{hh}:{port}/json/version"):
                try:
                    raw = urllib.request.urlopen(ep, timeout=3).read(); break
                except Exception:
                    pass
            if raw:
                break
        if raw:
            targets = json.loads(raw)
            if isinstance(targets, dict):
                targets = [{"type": "page", "webSocketDebuggerUrl": targets.get("webSocketDebuggerUrl")}]
            ws_url = next((t["webSocketDebuggerUrl"] for t in targets
                           if t.get("type") == "page" and t.get("webSocketDebuggerUrl")), None)
            if ws_url:
                break
    if not ws_url:
        print("FAIL: 无法连接 Chrome CDP"); ok = False; raise SystemExit(1)

    ws = websocket.create_connection(ws_url, timeout=30)
    _id = [0]
    def send(method, params=None):
        _id[0] += 1
        ws.send(json.dumps({"id": _id[0], "method": method, "params": params or {}}))
        return _id[0]
    def recv_until(mid, timeout=20):
        t0 = time.time()
        while time.time() - t0 < timeout:
            m = json.loads(ws.recv())
            if m.get("id") == mid:
                return m
        return None

    send("Runtime.enable")
    send("Log.enable")
    # JS 报错捕获
    def on_message(msg):
        try:
            d = json.loads(msg)
        except Exception:
            return
        if d.get("method") == "Runtime.exceptionThrown":
            exc = d["params"]["exceptionDetails"]
            errors.append("JS异常: " + exc.get("text", "") + " @ " +
                          str(exc.get("lineNumber", "?")))
        elif d.get("method") == "Log.entryAdded":
            e = d["params"]["entry"]
            if e.get("level") in ("error", "warning"):
                errors.append(f"{e.get('level')}: {e.get('text','')}")
    ws.settimeout(10)
    send("Page.enable")
    file_url = "file://" + urllib.parse.quote(args.html, safe="/")
    send("Page.navigate", {"url": file_url})

    # 轮询等待页面脚本就绪：够长的页内 JSON + 内嵌字体会让加载明显慢于固定 sleep(4)。
    # ⚠️ 注意 `const DATA` 是全局**词法绑定**，**不挂 window** → 判就绪必须写 `typeof DATA`，
    #    写 `window.DATA` 会永远为 undefined（会误选作业点 0）。
    ready = False
    for _ in range(20):
        time.sleep(1)
        mid = send("Runtime.evaluate",
                   {"expression": "typeof DATA!=='undefined' && !!DATA.meta && !!DATA.points",
                    "returnByValue": True})
        res = recv_until(mid, timeout=10)
        if res and res.get("result", {}).get("result", {}).get("value") is True:
            ready = True
            break
    if not ready:
        errors.append("页面脚本 20s 内未就绪（DATA 未定义）——可能加载失败或模板有语法错误")
        ok = False

    # 模拟点击：取实际采样点中的最后一个有效索引，兼容点数 < 3 的小工区/窄测线
    # （避免直接硬编码 selectPoint(2) 在 npts=2 时越界崩溃）
    mid = send("Runtime.evaluate",
               {"expression": "try{var n=(typeof DATA!=='undefined'&&DATA.meta&&DATA.meta.npts)?DATA.meta.npts:0;"
                "var i=Math.max(0,n-1);selectPoint(i);'ok idx='+i+'/n='+n;}catch(e){'ERR:'+e.message}",
                "returnByValue": True})
    res = recv_until(mid)
    click_res = res.get("result", {}).get("result", {}).get("value") if res else None
    if click_res and str(click_res).startswith("ERR"):
        errors.append("selectPoint 调用失败: " + str(click_res))
        ok = False

    # 检查地图下方面板（当前时刻 .rr-cur + 四值行 .rr-valrow）
    mid = send("Runtime.evaluate",
               {"expression": "(function(){var c=document.getElementById('riskReason');"
                "var a=document.getElementById('alertBox');"
                "var vr=c?c.querySelector('.rr-valrow'):null;"
                "return JSON.stringify({rrPresent: !!c, rrDisplay: c?c.style.display:'none',"
                "rrCur: c?!!c.querySelector('.rr-cur'):false,"
                "rrValrow: !!vr,"
                "rrVals: vr?vr.querySelectorAll('b').length:0,"
                "alertText: a?a.textContent.slice(0,40):'',"
                "sevClass: document.body.className});})()",
                "returnByValue": True})
    res = recv_until(mid)
    diag = {}
    if res:
        rv = res.get("result", {}).get("result", {}).get("value")
        try:
            diag = json.loads(rv)
        except Exception:
            pass
    # 收集 ws 期间所有控制台/异常消息
    try:
        while True:
            m = ws.recv()
            on_message(m)
    except websocket.WebSocketTimeoutException:
        pass
    except Exception:
        pass

    rr_present = diag.get("rrPresent", False)
    rr_display = diag.get("rrDisplay", "none")
    rr_vals = diag.get("rrVals", 0)
    sev_class = diag.get("sevClass", "")
    if not rr_present:
        errors.append("地图下方风险面板缺失 (#riskReason 不存在)")
        ok = False
    if rr_display == "none":
        errors.append("点击采样点后风险面板未显示 (display=none)")
        ok = False
    if not diag.get("rrCur"):
        errors.append("面板缺少「当前时刻」行 (.rr-cur)")
        ok = False
    if not diag.get("rrValrow"):
        errors.append("面板缺少四值行 (.rr-valrow)")
        ok = False
    elif rr_vals != 4:
        errors.append("四值行内数值应为 4 个（降水/气温/阵风/均风），实际=" + str(rr_vals))
        ok = False
    if "sev" not in sev_class:
        errors.append("severity 着色类未挂载 (body.className=" + sev_class + ")")
        ok = False

    # 检查地图下方逐要素图表（选中点后应渲染 .ec 块）
    mid = send("Runtime.evaluate",
               {"expression": "(function(){var e=document.getElementById('explorerCharts');"
                "return JSON.stringify({ec: e?e.querySelectorAll('.ec').length:0});})()",
                "returnByValue": True})
    res = recv_until(mid)
    ec_diag = {}
    if res:
        try: ec_diag = json.loads(res.get("result", {}).get("result", {}).get("value", "{}"))
        except Exception: pass
    ec_count = ec_diag.get("ec", 0)
    # 固定四图中「能见度」在九章后端缺该要素时会被 `pt.hasVis` 守卫正确省略 → 允许 3~4。
    if not (3 <= ec_count <= 4):
        errors.append(f"未来2周图应为固定四图（降水/气温/阵风·均风/能见度），实际 .ec 数量={ec_count}（<3 说明模板缺图）")
        ok = False
    elif ec_count == 3:
        print("提示: .ec=3 —— 能见度图因后端无 visibility 要素被守卫省略（正常，非缺图）")

    print("==== 校验结果 ====")
    print("风险面板 present/display:", rr_present, rr_display)
    print("当前时刻行 .rr-cur:", diag.get("rrCur"), "| 四值行 .rr-valrow:", diag.get("rrValrow"), "| 数值个数:", rr_vals)
    print("未来2周固定四图 .ec 块数:", ec_count)
    print("重点关注文本:", diag.get("alertText", ""))
    print("body 类名:", sev_class)
    if errors:
        print("发现以下问题:")
        for e in errors:
            print("  -", e)
    if ok and not errors:
        print("PASS ✅ 无 JS 报错，点击联动与 severity 变色均正常。")
        sys.exit(0)
    else:
        print("FAIL ❌")
        sys.exit(1)
finally:
    try:
        ws.close()
    except Exception:
        pass
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    # 清理临时 Chrome profile（mkdtemp 建的）
    try:
        shutil.rmtree(profile, ignore_errors=True)
    except Exception:
        pass
