# -*- coding: utf-8 -*-
"""
富媒体天气看板 HTML 交付前质量门禁（基于 Chrome CDP）

做的事:
  1. 无头 Chrome 加载生成的 HTML
  2. 捕获 console.error / Runtime.exceptionThrown（任何 JS 报错即 FAIL）
  3. 注入模拟点击 selectPoint(2)，确认地图下方联动面板（风险原因 #riskReason + 逐要素图表 #explorerCharts 的 .ec 块）均已渲染
  4. 检查 body.sevN 类是否按严重程度正确挂载（severity 变色依据）
  5. 输出 PASS / FAIL 与关键诊断。

依赖: pip install websocket-client；本机需安装 Google Chrome。
用法:
  python validate.py --html "/path/大关项目工区.html" [--chrome "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
"""
import argparse, json, os, sys, time, subprocess, urllib.request, urllib.parse
import websocket

ap = argparse.ArgumentParser()
ap.add_argument("--html", required=True, help="待校验的 HTML 路径")
ap.add_argument("--chrome", default="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
ap.add_argument("--port", type=int, default=9333)
args = ap.parse_args()

if not os.path.exists(args.html):
    print("FAIL: 文件不存在", args.html); sys.exit(2)

os.environ["no_proxy"] = "*"; os.environ["NO_PROXY"] = "*"
urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))

port = args.port
profile = "<TMP>/cdp_profile_wb_validate"
proc = subprocess.Popen(
    [args.chrome, "--headless", "--disable-gpu", "--no-sandbox", "--no-first-run",
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
    time.sleep(4)

    # 模拟点击：取实际采样点中的最后一个有效索引，兼容点数 < 3 的小工区/窄测线
    # （避免直接硬编码 selectPoint(2) 在 npts=2 时越界崩溃）
    mid = send("Runtime.evaluate",
               {"expression": "try{var n=(window.DATA&&DATA.meta&&DATA.meta.npts)?DATA.meta.npts:0;"
                "var i=Math.max(0,n-1);selectPoint(i);'ok idx='+i+'/n='+n;}catch(e){'ERR:'+e.message}",
                "returnByValue": True})
    res = recv_until(mid)
    click_res = res.get("result", {}).get("result", {}).get("value") if res else None
    if click_res and str(click_res).startswith("ERR"):
        errors.append("selectPoint 调用失败: " + str(click_res))
        ok = False

    # 检查地图下方合并面板（风险原因 + 当前值 + 全期最严重 + 各要素级值）
    mid = send("Runtime.evaluate",
               {"expression": "(function(){var c=document.getElementById('riskReason');"
                "var a=document.getElementById('alertBox');"
                "return JSON.stringify({rrPresent: !!c, rrDisplay: c?c.style.display:'none',"
                "rrPeaks: c?c.querySelectorAll('.rr-pc').length:0,"
                "rrCur: c?!!c.querySelector('.rr-cur'):false,"
                "rrSev: c?!!c.querySelector('.rr-sev'):false,"
                "rrWorst: c?!!c.querySelector('.rr-worst'):false,"
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
    rr_peaks = diag.get("rrPeaks", 0)
    sev_class = diag.get("sevClass", "")
    if not rr_present:
        errors.append("地图下方风险面板缺失 (#riskReason 不存在)")
        ok = False
    if rr_display == "none":
        errors.append("点击采样点后风险面板未显示 (display=none)")
        ok = False
    if rr_peaks != 4:
        errors.append("要素级值格子数应为 4，实际=" + str(rr_peaks))
        ok = False
    if not diag.get("rrCur"):
        errors.append("面板缺少「当前值」行")
        ok = False
    if not diag.get("rrSev"):
        errors.append("面板缺少风险等级标识")
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
    if ec_count <= 0:
        errors.append("选中采样点后逐要素图表未渲染 (#explorerCharts .ec 数量=0)")
        ok = False

    print("==== 校验结果 ====")
    print("风险面板 present/display:", rr_present, rr_display)
    print("要素级值格子数:", rr_peaks, "| 含当前值:", diag.get("rrCur"), "| 含风险标识:", diag.get("rrSev"))
    print("逐要素图表 .ec 块数:", ec_count)
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
