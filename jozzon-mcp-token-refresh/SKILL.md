---
name: jozzon-mcp-token-refresh
description: 刷新 jozzon-mcp 连接器的 access token（带有效期预检：剩余不足 30 分钟才刷新，否则跳过）。jozzon-mcp 是全局 MCP 连接器（配置在 ~/.workbuddy/mcp.json），其 Authorization 使用的是 leidian.wang 下发的短时效 JWT（约 10 小时），过期后 MCP 调用会 401。本技能无头登录 https://leidian.wang，从 localStorage 取最新 access 并写回 mcp.json。当用户说“刷新 jozzon-mcp token / 更新 jozzon-mcp token / jozzon-mcp 报 401 / 更新 leidian token”时使用。凭据在技能目录 config.json（权限 600，缺失时回退 weather-common/config.json），登录方式为密码登录、无 MFA。
---

# 刷新 jozzon-mcp 的 access token

`jozzon-mcp` 的 `headers.Authorization` 用的是 `https://leidian.wang` 下发的 JWT access token，**短时效（约 10 小时）**，过期后 MCP 调用返回 401。本技能自动用浏览器登录 leidian.wang，从 `localStorage` 的 `access` 键取最新 token，写回 `~/.workbuddy/mcp.json`。

## 一键运行（推荐）

```bash
bash ~/.workbuddy/skills/jozzon/jozzon-mcp-token-refresh/refresh.sh
```

**有效期预检（2026-10-19 起）**：运行后先解码 mcp.json 里当前 token 的 `exp`：
- 剩余 **≥ 30 分钟** → 打印「token 仍有效…跳过刷新」并**以退出码 0 结束**（不打开浏览器、不登录）；
- 剩余 **< 30 分钟**（含已过期）→ 执行刷新；
- token 缺失 / 无法解析 → 执行刷新。

因此可安全放入高频自动化（如每小时跑一次）：有效即跳过，绝不浪费登录。

```bash
bash refresh.sh --force     # 强制刷新（跳过有效期检查）
REFRESH_MIN_REMAIN=600 bash refresh.sh   # 自定义阈值为 10 分钟（默认 1800 秒）
```

刷新流程：打开 leidian.wang（无头）→ 密码登录（凭据读 `config.json`）→ 读 `localStorage.access` → 写回 `mcp.json` → 解码校验 exp → 关闭浏览器 → 打印新 token 的北京时间过期时刻与剩余时长。退出码 0 成功、非 0 失败。

## 手动分步（agent 执行，仅当脚本不可用）

1. 确认 agent-browser 已装：托管 node workspace 下 `~/.workbuddy/binaries/node/workspace/node_modules/.bin/agent-browser`；未装则 `cd ~/.workbuddy/binaries/node/workspace && npm install agent-browser && ./node_modules/.bin/agent-browser install`。
2. 从 `config.json` 读取 `username` / `password`。
3. `agent-browser open https://leidian.wang` → `wait --load load` → `snapshot -i`，定位 “账号”/“密码” 文本框与 “登录” 按钮（ref 如 `e18`）。
4. `type <ref> <账号>`、`type <ref> <密码>`、`click <登录ref>`；等跳转。
5. `agent-browser eval "localStorage.getItem('access')"` 取 token（含引号，需去掉）。
6. 用 python 安全更新 json：`d["mcpServers"]["jozzon-mcp"]["headers"]["Authorization"] = "Bearer " + token`，`json.dump(..., indent=2)`，再补一个换行。
7. 解码 payload 校验 `exp` 晚于当前时间；关闭浏览器。

## 凭据与安全

- 凭据**仅**存于 `config.json`，权限 `600`，不写入对话 / 记忆 / 其他文件，且被镜像仓库 `.gitignore` + rsync `--exclude` 双拦截（绝不上 GitHub）。
- 读取顺序：技能目录 `config.json` → 缺失时回退 `~/.workbuddy/skills/jozzon/weather-common/config.json`（2026-10-19 起 token 自动刷新能力也内置于 `weather-common/scripts/jozzonwx.py` 的 `ensure_token()`，两个取数脚本主流程最前面会调用；同一份口令勿存两处）。
- 改账号密码直接编辑 `config.json` 即可。
- agent-browser 默认无头运行，无需显示器，可在锁屏/无人值守下执行。

## 注意

- 更新 `mcp.json` 后，WorkBuddy 里**已建立的 jozzon-mcp 连接可能仍缓存旧 token**，需在连接器菜单重连/重启该连接器才能生效（物探/工程重跑脚本直接读 mcp.json，不受影响）。
- token 约 10 小时失效；因脚本自带有效期预检，建议配周期自动化定期执行（有效即跳过，无需掐点）。
- 若 leidian.wang 登录页元素改动导致定位失败，脚本会报错退出（退出码非 0），不会破坏现有 token。
- **跨平台可移植**：脚本不硬编码本机用户名 / node 版本号，运行时通过 `$HOME/.workbuddy`（可用环境变量 `WB_HOME` 覆盖）与 `PATH` 动态定位 `mcp.json`、`python3`、`agent-browser`、`npm`。Windows 下需 Git Bash / WSL 这类 bash 环境，并装好 node 与 python3（agent-browser 仍可用）。移植到另一台机器只需把整个技能目录复制过去，并自备 `config.json`（或依赖 weather-common 的那份）。
