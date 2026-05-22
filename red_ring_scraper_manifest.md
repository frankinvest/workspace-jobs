# 小红圈抓取流线全量资产报告

> 生成时间：2026-05-22 15:22 GMT+8
> 资产版本：SSOT v11 熔断版
> 维护者：OpenClaw Agent (main session)

---

## 1. 目录拓扑结构

```
~/.openclaw/workspace/
├── skills/
│   └── red-ring-scraper/
│       ├── SKILL.md                    ← Skill 编排层（核心规范文档）
│       └── references/                 ← 外部参考文档（空目录，保留占位）
└── shared/                             ← 标准库积木（强依赖）
    ├── build_full.py                   ← 渲染引擎（SSOT 核心）
    ├── cdp_get_innerhtml.py            ← CDP 提取工具（v11 熔断版）
    ├── network/
    │   └── batch_uploader.py           ← GitHub 分批上传队列
    └── deploy/
        └── github_pages.py             ← GitHub Pages 构建触发器
```

---

## 2. 核心文件源码全辑

---

## 2.1 Skill 编排层

**路径：** `~/.openclaw/workspace/skills/red-ring-scraper/SKILL.md`

```python
---
name: red-ring-scraper
description: >
  抓取小红圈帖子（财经早餐）并发布到 GitHub Pages。
  触发条件：用户说"抓取财经早餐"、"提取小红圈帖子"、"下载 red-ring 图片"。
  本 Skill 是纯编排器，所有脏活由 shared/ 积木执行。
---

> ⚠️ **强制前置声明（Tool Intent）**
>
> 本 Skill 属于**高风险复合写操作**，涉及浏览器操作、文件写入、第三方 API 调用以及 GitHub Pages 发布，**绝对不适用"低风险免声明"的例外条款**。
>
> **执行任何 Step 之前**，必须先向用户输出以下标准块：
>
> \`\`\`markdown
> 🛠️ **Tool Intent**
> - 拟用工具/模块：[列出本轮将要调用的所有工具名称]
> - 核心入参：[展示关键参数，如目标 URL、日期、输出路径]
> - 预期目的：[简述本次调用的目的]
> \`\`\`
>
> **豁免边界**：纯截图查看（不写文件、不发布）属于低风险，仅需口头说明"先截个图看看"即可。
> 一旦涉及 `exec`、`file_write`、`build_full.py` 等写操作，立即触发声明义务。

> ⚠️ **强制规则**：所有截图任务必须使用 `shot2__capture_page` MCP 工具，禁止用 `browser(action=screenshot)` 替代。

# red-ring-scraper — 编排器规范（v11 熔断版）

**核心原则（SSOT）**：
- Skill **永远不**凭记忆填入 `post_id` 或历史日期
- "获取最新 ID" 是 `cdp_get_innerhtml.py --auto-latest` 的内置职责，脚本自身完成日期熔断
- Skill 只负责任务编排，不做 DOM 嗅探

---

## 架构图

```
User → Skill (编排器，只负责调用)
         │
         └── Step 1: exec build_full.py --auto-latest
                        │
                        ├── cdp_get_innerhtml.py --auto-latest
                        │     ├── 导航到圈子页面
                        │     ├── 解析所有帖子 → 定位今日财经早餐
                        │     ├── 【熔断】今日帖子不存在 → exit 3，停止一切
                        │     └── 提取 innerHTML → /tmp/<date>_post.html
                        │
                        ├── build_full.py（读取 HTML）
                        │     ├── 上传图片 → GitHub
                        │     ├── 渲染 HTML
                        │     └── 触发 GitHub Pages
                        │
                        └── Step 2: 上报结果
```

---

## 日常抓取流程（auto-latest 模式）

> 🛠️ **本步声明**：调用 `exec`（build_full.py --auto-latest），**高风险写操作**，必须声明。
> 特别注意：禁止在本步的 Tool Intent 中凭记忆填入 `post_id` 或旧日期参数。

**执行命令（唯一正确方式）**：
```bash
python3 /Users/frank_bot/.openclaw/workspace/shared/build_full.py \
    AUTO \
    $(date +%Y%m%d) \
    --auto-latest \
    --output caijing_$(date +%Y%m%d).html
```

**参数说明**：
| 参数 | 值 | 说明 |
|------|-----|------|
| `AUTO` | 固定值 | 告诉 build_full.py 启用自动找帖模式 |
| `$(date +%Y%m%d)` | 如 `20260519` | 仅作初始占位，会被 HTML 内标题覆盖 |
| `--auto-latest` | 标志 | 启用 cdp_get_innerhtml.py 的自动找帖+熔断 |
| `--output` | 如 `caijing_20260519.html` | GitHub 仓库输出文件名 |

**日期熔断机制**（cdp_get_innerhtml.py 内置）：
```
[CDP] 今日日期: 2026-05-19
[CDP] 发现 N 条帖子
[CDP] 今日帖子: /post/27593-2155333 （05/19 06:59）  ← 校验通过
       ↓
[CDP] ✅ 今日帖子: /post/27593-2155333 （05/19 06:59）

# 如果今日帖子不存在：
[CDP] ❌ 今日（2026-05-19）未找到财经早餐帖子，触发熔断！
# exit 3，脚本终止，不执行任何文件写入或上传
```

**预期输出**：
```
[build] AUTO模式: python3 .../cdp_get_innerhtml.py /tmp/xxx_post.html AUTO --auto-latest ...
[AUTO] 今日日期: 2026-05-19
[AUTO] ✅ 今日帖子: https://www.red-ring.cn/post/27593-2155333
[CDP] 提取完成: comments=45, scrollHeight=...
[CDP] ✅ 45678 bytes → /tmp/20260519_post.html
[build] innerHTML: 45678 chars | body: 32000 chars
[build] 正文图片: 16 张 | 评论: 45 条
  [OK] 1/16 caijing_20260519_img_01.jpg (43KB)
  ...
[build] 图片映射: 16/16 成功
[build] 最终 HTML: 8923 bytes | GitHub 图片: 16 张
[build] HTML 上传: https://raw.githubusercontent.com/...
[build] GitHub Pages: OK https://frankinvest.github.io/caijing-daily/caijing_20260519.html

✅ 完成: {"html_file": "caijing_20260519.html", "images": 16, "comments": 45, "url": "..."}
```

**熔断退出码**：
| 退出码 | 含义 | Skill 行为 |
|--------|------|-----------|
| `0` | 成功 | 向用户报告 URL |
| `3` | 日期熔断（今日帖子不存在） | 通知用户"今日帖子尚未发布"，停止 |
| `1` | 参数错误或网络失败 | 重试一次，仍失败则报告错误 |

---

## 手动指定日期（可选，用于补抓历史帖子）

> 🛠️ **本步声明**：仅在用户明确要求补抓某日帖子时使用。日常抓取**禁止**传入旧日期。

**补抓命令格式**：
```bash
python3 /Users/frank_bot/.openclaw/workspace/shared/build_full.py \
    /tmp/20260513_post.html \
    20260513 \
    caijing_20260513.html \
    --title "财经早餐 2026-05-13"
```

⚠️ **警告**：此模式绕过熔断，适用于补抓历史帖子。新帖抓取**必须**用 `--auto-latest`。

---

## 特殊情况处理

### CDP 连接失败（gateway 重启等）

build_full.py 会自动降级：
```
[CDP] WebSocket 连接失败: [Errno 111] Connection refused
       URL 可能已失效（gateway 重启后会变化）。
       请从 browser status 中获取新的 CDP WebSocket URL。
```

**操作**：获取新 CDP URL，更新 `~/.openclaw/workspace/shared/cdp_get_innerhtml.py` 中的 `DEFAULT_WS`，或通过 `--cdp-ws-url` 参数传入。

### build_full.py 识别不了 HTML 日期

`_extract_date_from_html()` 使用正则 `YYYY年MM月DD日` 或 `YYYY-MM-DD` 匹配。
若帖子标题格式变化导致识别失败，脚本会报错并退出：
```
[build] ❌ 无法从 HTML 推断日期，且未传入 date 参数
```
此时需要手动指定日期（补抓模式）并尽快更新正则。

---

## shared/ 积木清单（SSOT）

| 模块 | 职责 | 接口 |
|------|------|------|
| `shared/cdp_get_innerhtml.py` | 自动找帖 → CDP 提取 | CLI: `<out> AUTO --auto-latest [--group-url]` |
| `shared/build_full.py` | 渲染 + 上传 + 部署 | CLI: `AUTO <date> --auto-latest [--output]` |
| `shared/network/batch_uploader.py` | 图片批量上传 | `GitHubUploader(token, repo).upload(path, b64)` |
| `shared/deploy/github_pages.py` | GitHub Pages 触发 | `GitHubPagesTrigger(token, repo).trigger_and_wait()` |

---

## 思想钢印（违反者视为系统性故障）

1. **禁止凭记忆填 post_id**：任何时候都不得在 Tool Intent 中写死历史 post_id
2. **今日帖子熔断**：auto-latest 找不到今日帖子时，脚本 exit 3，Skill 必须停止并通知用户
3. **日期来源优先级**：HTML 标题内日期 > 脚本自动推断 > 命令行传入参数
4. **禁止跳过熔断做猜测**：熔断发生后，Skill **不得**自行判断"也许明天发"而继续执行

```

---

## 2.2 CDP 提取工具

**路径：** `~/.openclaw/workspace/shared/cdp_get_innerhtml.py`

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cdp_get_innerhtml.py — v11（熔断版）

新增 --auto-latest 模式：
  当未传入 post_id（cdp_ws_url 为空或 "AUTO"）时，脚本自动：
    1. 导航到圈子页面
    2. 解析所有帖子，定位今日财经早餐
    3. 日期熔断：若今日帖子不存在，程序直接退出（exit 3），绝不继续
    4. 导航到目标帖子页面，提取 innerHTML

用法:
    # 手动模式（指定 CDP URL）
    python3 cdp_get_innerhtml.py /tmp/20260519_post.html \
        ws://127.0.0.1:18900/devtools/page/XXXX --selector main

    # 自动模式（脚本全权负责找帖）
    python3 cdp_get_innerhtml.py /tmp/20260519_post.html AUTO \
        --auto-latest --group-url https://www.red-ring.cn/group/27593
"""
import websocket
import json
import time
import sys
import os
import re
import argparse

DEFAULT_WS = "AUTO"          # "AUTO" 表示启用自动找帖模式
DEFAULT_SELECTOR = "main"
GROUP_URL = "https://www.red-ring.cn/group/27593"

# ── CDP 底层通信 ────────────────────────────────────────────────

def _ws_connect(ws_url, timeout=10):
    return websocket.create_connection(ws_url, suppress_origin=True, timeout=timeout)

def _eval(ws, msg_id, js, timeout=15):
    """向 CDP 发送一条 JS，阻塞等待结果"""
    ws.settimeout(timeout + 5)
    ws.send(json.dumps({"id": msg_id, "method": "Runtime.evaluate",
                        "params": {"expression": js, "returnByValue": True}}))
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            raw = ws.recv()
            data = json.loads(raw)
            if data.get("id") == msg_id:
                return data
        except:
            pass
        time.sleep(0.1)
    raise Exception(f"CDP eval timeout after {timeout}s")

def _navigate(ws, url, timeout=20):
    """通过 window.location 导航并等待页面加载完成（避免 CDP Page.navigate 超时问题）"""
    ws.send(json.dumps({"id": 98, "method": "Runtime.evaluate",
                        "params": {"expression": "window.location.href", "returnByValue": True}}))
    current_url = None
    try:
        raw = ws.recv()
        data = json.loads(raw)
        if data.get("result", {}).get("result", {}).get("type") == "string":
            current_url = data["result"]["result"]["value"]
    except:
        pass

    if current_url == url:
        print(f"[CDP] 已在目标页 ({url})，跳过导航")
    else:
        print(f"[CDP] 导航到 {url} (window.location) ...")
        nav_js = 'window.location.href = "%s"; "navigating"' % url
        ws.send(json.dumps({"id": 99, "method": "Runtime.evaluate",
                           "params": {"expression": nav_js, "returnByValue": True}}))
        try:
            raw = ws.recv()  # 接收导航命令的返回值
        except:
            pass

    # 等待页面 readyState == complete
    deadline = time.time() + timeout
    while time.time() < deadline:
        ws.settimeout(2)
        try:
            ws.send(json.dumps({"id": 97, "method": "Runtime.evaluate",
                               "params": {"expression": 'window.location.href + "|" + document.readyState', "returnByValue": True}}))
            raw = ws.recv()
            data = json.loads(raw)
            if data.get("id") == 97:
                val = data.get("result", {}).get("result", {}).get("value", "")
                if "|" in val:
                    cur_url, state = val.rsplit("|", 1)
                    if state == "complete":
                        print(f"[CDP] 页面加载完成: {cur_url}")
                        return
        except:
            pass
        time.sleep(1)
    raise Exception("Page.load timeout")

# ── 自动找帖（--auto-latest 核心逻辑）────────────────────────────

def get_today_date_str():
    """返回 'YYYY-MM-DD' 格式的今日日期字符串（北京时间）"""
    import datetime
    # 北京时间 = UTC+8
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
    return now.strftime("%Y-%m-%d")

def _check_login_and_scroll(ws, group_url, timeout=30):
    """
    升级版 auto_find_latest_post：
    1. 登录状态硬校验 → exit 2
    2. 强制等待 + 滚动渲染
    3. 扫描前 5 个帖子（含 "财经早餐"）
    4. 放宽日期匹配（支持多种格式）
    5. 追踪真正的文字帖链接（排除纯音频帖）
    返回 (post_url, ws) — 与旧签名兼容，但 ws 会在 fetch_innerhtml 中被重用
    """
    print(f"[AUTO] 连接 CDP: {ws}")
    ws_conn = _ws_connect(ws, timeout=10)
    print(f"[AUTO] 导航到圈子页面: {group_url}")
    _navigate(ws_conn, group_url, timeout=20)

    # ── 升级 1：登录状态硬校验 ────────────────────────────────
    login_check_js = r"""
    (function(){
        // 已登录标识：头像/.nickname/.fwm 或 HMACCOUNT cookie
        var hasAvatar = !!(document.querySelector('.avatar,.user-avatar,[class*=avatar],[class*=nickname]'));
        var hasCookie = document.cookie.includes('HMACCOUNT');
        var hasMask = !!(document.querySelector('[class*=login-modal],[class*=login-mask],[class*=unauth]'));
        // 找圈子名称（登录后在右侧边栏显示用户名）
        var sidebarUser = document.querySelector('.sidebar [class*=name], .user-name, .nickname');
        var usernameEl = sidebarUser ? sidebarUser.textContent.trim() : null;
        return JSON.stringify({
            loggedIn: hasAvatar || hasCookie,
            hasLoginMask: hasMask,
            hasCookie: hasCookie,
            username: usernameEl
        });
    })()
    """
    data = _eval(ws_conn, 998, login_check_js, timeout=15)
    login_info = json.loads(data['result']['result']['value'])
    print(f"[AUTO] 登录状态: loggedIn={login_info['loggedIn']}, hasMask={login_info['hasLoginMask']}, username={login_info['username']}")
    if not login_info['loggedIn'] or login_info['hasLoginMask']:
        print("[AUTO] ❌ 未登录或登录已失效，触发熔断！请重新扫码登录。 (exit 2)")
        ws_conn.close()
        sys.exit(2)   # 登录失效退出码

    # ── 升级 3：强制等待 + 滚动加载（防 AJAX 延迟）────────────
    print("[AUTO] 等待帖子列表渲染 (3s) ...")
    time.sleep(3)

    # 滚动一次触发懒加载
    scroll_js = """
    (function(){
        window.scrollBy(0, 300);
        return window.scrollY;
    })()
    """
    _eval(ws_conn, 997, scroll_js, timeout=10)
    time.sleep(1.5)
    print("[AUTO] 滚动完成，收集帖子列表 ...")

    # ── 升级 2 + 4：正确 selector + 扫描所有帖子 + 放宽日期匹配 ───────
    find_js = r"""
    (function(){
        var todayStr = arguments[0];
        // 正确 selector: a[href*="/post/27593-"] 向上最近的 .panel 容器
        var allLinks = document.querySelectorAll('a[href*="/post/27593-"]');
        var results = [];
        var seen = {};

        allLinks.forEach(function(a){
            var href = a.href.split('?')[0];
            if (!href || seen[href]) return;
            seen[href] = true;

            // 向上找 .panel 容器（帖子主结构）
            var panel = a.closest('.panel');
            var text = panel ? panel.textContent.replace(/\s+/g, ' ').substring(0, 200) : '';

            // 时间标签
            var timeEl = panel ? panel.querySelector('.dark-9.fz-sm') : null;
            var timeText = timeEl ? timeEl.textContent.trim() : '';

            // 判断今日（优先"今天"字样）
            var isToday = timeText.includes('今天');
            if (!isToday) return;

            // 排除纯音频帖
            var isCaijing = text.includes('财经早餐');
            var isAudioLink = href.includes('.mp3');

            if (isAudioLink) return;  // 跳过 mp3 附件链接

            results.push({
                href: href,
                timeText: timeText,
                isToday: isToday,
                isCaijing: isCaijing,
                text: text.substring(0, 100)
            });
        });

        return JSON.stringify({
            today: todayStr,
            posts: results.slice(0, 8)
        });
    })('%s')
    """ % get_today_date_str()

    data = _eval(ws_conn, 2, find_js, timeout=20)
    raw = data['result']['result']['value']
    parsed = json.loads(raw)

    today = parsed['today']
    posts = parsed.get('posts', [])
    print(f"[AUTO] 今日日期: {today}，发现 {len(posts)} 条相关帖子")

    for i, p in enumerate(posts[:8]):
        tag = '📝' if p.get('isCaijing') else '·'
        print(f"       [{i}] {tag} [{p.get('timeText','')}] {p['href'][-40:]}")
        print(f"           {p.get('text','')}")

    # 找今日财经早餐
    caijing_candidates = [p for p in posts if p.get('isCaijing')]

    if not caijing_candidates:
        print(f"[AUTO] ❌ 今日（{today}）未找到财经早餐帖子，触发熔断！")
        ws_conn.close()
        sys.exit(3)   # 日期熔断退出码

    # 取第一条
    target = caijing_candidates[0]
    print(f"[AUTO] ✅ 今日财经早餐: {target['href']} [{target.get('timeText','')}]")

    # 不导航页面，直接返回 post_url；由 browser 工具负责导航
    return target['href'], ws_conn


def auto_find_latest_post(ws_url, group_url, timeout=30):
    """兼容旧签名，返回 (href, ws_url)"""
    href, ws_conn = _check_login_and_scroll(ws_url, group_url, timeout)
    return href, ws_conn

# ── innerHTML 提取 ───────────────────────────────────────────────

EXTRACT_JS = r"""
(function() {
  try {
    var el = document.querySelector(%(selector)s);
    if (!el) el = document.querySelector('.post-body,.ql-view,[class*=post-body],main,article,body');
    if (!el) el = document.body;
    var html = el ? el.innerHTML : '';
    var cnt = document.querySelectorAll ? document.querySelectorAll('.py-12.flex.bt').length : 0;
    return JSON.stringify({
      html: 'POST_START' + html + 'POST_END',
      commentCount: cnt,
      scrollHeight: document.body ? document.body.scrollHeight : 0,
      innerHeight: window.innerHeight
    });
  } catch(e) {
    return JSON.stringify({error: e.message, stack: e.stack});
  }
})()
"""

def fetch_innerhtml(ws_url, selector=DEFAULT_SELECTOR, auto_latest=False,
                     group_url=None):
    """
    提取 innerHTML。
    若 ws_url == "AUTO" 或 auto_latest=True，进入自动找帖模式。
    """
    if auto_latest or ws_url == "AUTO":
        group_url = group_url or GROUP_URL
        post_url, ws_conn = _check_login_and_scroll(ws_url, group_url)
        # 导航到目标帖子（用 window.location 避免 CDP Page.navigate 超时）
        print(f"[CDP] 导航到帖子页面 ...")
        nav_js = 'window.location.href = "%s"; "navigating"' % post_url
        _eval(ws_conn, 97, nav_js, timeout=10)
        # 等待 readyState == complete
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                ws_conn.settimeout(2)
                ws_conn.send(json.dumps({'id': 98, 'method': 'Runtime.evaluate',
                                        'params': {'expression': 'window.location.href + "|" + document.readyState', 'returnByValue': True}}))
                raw = ws_conn.recv()
                data = json.loads(raw)
                if data.get('id') == 98:
                    val = data['result']['result']['value']
                    new_url, state = val.rsplit('|', 1)
                    if new_url == post_url and state == 'complete':
                        print(f"[CDP] 导航完成")
                        break
            except:
                pass
            time.sleep(1)
        time.sleep(2)
        # 提取 innerHTML
        try:
            print(f"[CDP] 提取 innerHTML ...")
            js = EXTRACT_JS % {"selector": json.dumps(selector)}
            data = _eval(ws_conn, 1, js, timeout=30)
        finally:
            ws_conn.close()
    else:
        # 手动模式：直接提取
        print(f"[CDP] 提取 innerHTML ...")
        try:
            ws = _ws_connect(ws_url, timeout=10)
            ws.close()
            print(f"[CDP] WebSocket 连接验证: OK")
        except Exception as e:
            raise RuntimeError(
                f"[CDP] WebSocket 连接失败: {e}\n"
                f"       URL 可能已失效（gateway 重启后会变化）。\n"
                f"       请从 browser status 中获取新的 CDP WebSocket URL。"
            )
        ws = _ws_connect(ws_url, timeout=10)
        try:
            js = EXTRACT_JS % {"selector": json.dumps(selector)}
            data = _eval(ws, 1, js, timeout=20)
        finally:
            ws.close()

    # 解析提取结果
    result_obj = data.get("result", {})
    inner_result = result_obj.get("result", {})
    if "value" not in inner_result:
        # 检查是否有异常
        exc = result_obj.get("exceptionDetails", {})
        exc_msg = exc.get("exception", {}).get("description", str(result_obj))
        raise RuntimeError(f"[CDP] 提取 JavaScript 执行失败: {exc_msg}")
    raw = inner_result["value"]
    parsed = json.loads(raw)
    if "error" in parsed:
        raise RuntimeError(f"[CDP] 提取内部错误: {parsed['error']}")
    html = parsed["html"]
    cnt = parsed.get("commentCount", 0)
    scroll_h = parsed.get("scrollHeight", 0)
    inner_h = parsed.get("innerHeight", 0)
    print(f"[CDP] 提取完成: comments={cnt}, scrollHeight={scroll_h}, innerHeight={inner_h}")
    return html

# ── CLI 入口 ────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description='CDP innerHTML 提取工具（v11 熔断版）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 手动模式（指定 CDP URL）
  python3 cdp_get_innerhtml.py /tmp/20260519_post.html \\
      ws://127.0.0.1:18900/devtools/page/XXXX --selector main

  # 自动模式（脚本自动找今日帖子，日期熔断）
  python3 cdp_get_innerhtml.py /tmp/20260519_post.html AUTO \\
      --auto-latest --group-url https://www.red-ring.cn/group/27593

退出码:
  0  成功
  1  参数错误或提取失败
  3  日期熔断（今日帖子不存在）
        """
    )
    ap.add_argument('output_file', help='输出 HTML 文件路径')
    ap.add_argument('cdp_ws_url', nargs='?', default=DEFAULT_WS,
                    help='CDP WebSocket URL（填 AUTO 启用自动找帖）')
    ap.add_argument('--selector', '-s', default=DEFAULT_SELECTOR,
                    help='CSS 选择器（默认: main）')
    ap.add_argument('--auto-latest', action='store_true',
                    help='自动访问圈子页面，定位今日财经早餐帖子并熔断校验')
    ap.add_argument('--group-url', default=GROUP_URL,
                    help='圈子页面 URL（auto-latest 模式使用）')
    args = ap.parse_args()

    auto_mode = args.auto_latest or args.cdp_ws_url == "AUTO"
    print(f"[CDP] Output: {args.output_file} | Selector: {args.selector} | "
          f"Mode: {'AUTO' if auto_mode else 'MANUAL'}")

    try:
        html = fetch_innerhtml(
            ws_url=args.cdp_ws_url,
            selector=args.selector,
            auto_latest=auto_mode,
            group_url=args.group_url
        )
    except SystemExit as e:
        raise e
    except Exception as e:
        print(f"[CDP] Failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    os.makedirs(os.path.dirname(args.output_file) or '.', exist_ok=True)
    with open(args.output_file, "w", encoding="utf-8", errors="replace") as f:
        f.write(html)
    print(f"[CDP] ✅ {len(html)} bytes → {args.output_file}")

if __name__ == "__main__":
    main()

```

---

## 2.3 渲染引擎（SSOT 核心）

**路径：** `~/.openclaw/workspace/shared/build_full.py`

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_full.py — SSOT 渲染引擎（v11 熔断版）

新增 --auto-latest 模式：
  传入 --auto-latest 时，脚本自动调用 cdp_get_innerhtml.py --auto-latest
  完成"找帖→日期校验→提取"流水线，无需手动传 post_id。

  重要：date 参数在 auto-latest 模式下会被 HTML 内的标题日期覆盖，
  旧日期参数只作初始占位，脚本发现不匹配时会自动校正并报告。

用法（手动模式）:
    python3 build_full.py <innerhtml_file> <date_YYYYMMDD> [output_file] [title]
    python3 build_full.py /tmp/20260519_post.html 20260519 caijing_20260519.html "财经早餐 2026-05-19"

用法（自动模式）:
    python3 build_full.py AUTO <date_YYYYMMDD> --auto-latest
    python3 build_full.py AUTO 20260519 --auto-latest --output caijing_20260519.html
"""
import re, base64, urllib.request, json, time, sys, os, argparse, html as html_mod

_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent not in sys.path:
    sys.path.insert(0, _parent)
import markdownify as mf
from shared.network import GitHubUploader
from shared.deploy import GitHubPagesTrigger

# ── GitHub Token：本地密钥库优先，环境变量降级 ─────────────────────
_GH_TOKEN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'auth', 'github_token.txt')

def _load_github_token():
    """优先读本地密钥库 github_token.txt；其次读环境变量。"""
    # ① 本地密钥库
    if os.path.exists(_GH_TOKEN_PATH):
        with open(_GH_TOKEN_PATH, 'r', encoding='utf-8') as f:
            token = f.read().strip()
        if token:
            print(f"[AUTH] OK: GitHub Token 从本地密钥库加载 ({len(token)} chars)")
            return token
    # ② 环境变量降级
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        print("[AUTH] OK: GitHub Token 从环境变量加载")
        return token
    # ③ 皆无
    raise ValueError(
        "[AUTH] FAIL: 找不到 GitHub Token。\n"
        f"  ① 创建密钥库: shared/auth/github_token.txt\n"
        "  ② 或设置环境变量: export GITHUB_TOKEN=ghp_xxx"
    )

TOKEN = _load_github_token()
REPO = "frankinvest/caijing-daily"
REF_URL = "https://www.red-ring.cn/post/27593-2120574"
# ── 鉴权：动态加载 Cookie（禁止硬编码） ──────────────────────────────
_AUTH_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'auth', 'redring_cookies.json')

def load_redring_auth():
    """从 auth.json 动态加载请求头。文件不存在则抛出异常。"""
    if not os.path.exists(_AUTH_PATH):
        raise FileNotFoundError(
            f"[AUTH] FAIL: 鉴权文件不存在: {_AUTH_PATH}\n"
            f"       请在 shared/auth/redring_cookies.json 中配置 Cookie。"
        )
    with open(_AUTH_PATH, encoding='utf-8') as f:
        cfg = json.load(f)
    if not cfg.get('Cookie'):
        raise ValueError("[AUTH] FAIL: 鉴权文件缺少 'Cookie' 字段")
    # 只保留合法的 HTTP Header 字段（不含注释等杂项）
    HEADER_KEYS = ('Cookie', 'User-Agent', 'Referer', 'Accept', 'Accept-Language')
    headers = {k: cfg[k] for k in HEADER_KEYS if cfg.get(k)}
    if not headers.get('Cookie'):
        raise ValueError("[AUTH] FAIL: Cookie 为空")
    print(f"[AUTH] OK: loaded {len(headers['Cookie'])} chars from redring_cookies.json")
    return headers

_HEADERS = None  # lazy load

def get_headers():
    global _HEADERS
    if _HEADERS is None:
        _HEADERS = load_redring_auth()
    return _HEADERS


# ═══════════════════════════════════════════════════════════════
# 数据提取层（正文 / 评论 / 图片）
# ═══════════════════════════════════════════════════════════════

def _clean(html_str):
    """清理 HTML 片段中的标签和实体"""
    return re.sub(r'<[^>]+>', '', html_str).strip() \
        .replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>')

def _extract_replies(reply_html):
    """
    从 bgc-body px-9 py-5 HTML 片段提取所有子回复。

    使用 BeautifulSoup 解析，保证 DOM 顺序与发言人对应关系绝对正确。
    每个子回复 = <div class="my-5 tools-v-trigger por pr-60">，
    其中第一个 <span class="c-primary cup"> 是发言人，
    第一个 <span class="wpw"> 是内容。
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(reply_html, 'html.parser')
    replies = []
    for div in soup.find_all('div', class_='my-5 tools-v-trigger por pr-60'):
        cups = div.find_all('span', class_='c-primary cup')
        wpws = div.find_all('span', class_='wpw')
        user = cups[0].get_text(strip=True) if cups else ''
        text = _clean(wpws[0].get_text()) if wpws else ''
        replies.append({'user': user, 'content': text})
    return replies


def extract_comments(html):
    """
    从完整 innerHTML 提取所有评论（含嵌套子回复）。
    
    DOM 结构：
      <div class="py-12 flex bt">           — 主评论容器
        <span class="cup mr-5">用户名</span>
        <span class="dark-9 fz-sm">时间</span>
        <span class="wpw">主评论正文</span>
        <div class="cup fz-sm ml-9 c-primary"> 回复 </div>          — 分隔符
        <div class="bgc-body px-9 py-5">   — 子回复容器
          <span class="c-primary cup">子回复用户名</span>
          <span class="wpw">子回复正文</span>
          ...
    """
    comments = []
    top_pat = re.compile(
        r'<div class="py-12 flex bt">(.*?)(?=<div class="py-12 flex bt">|<div class="py-24"></div>)',
        re.DOTALL
    )
    for m in top_pat.finditer(html):
        block = m.group(1)

        # 主评论用户名
        um = re.search(r'<span class="cup mr-5">([^<]+)</span>', block)
        if not um:
            continue
        user = um.group(1).strip()

        # 主评论时间
        tm = re.search(r'<span class="dark-9 fz-sm">([^<]+)</span>', block)
        time_str = tm.group(1).strip() if tm else ''

        # 主评论正文：截取到 " 回复 " 分隔符为止，取第一个 <span class="wpw">
        divider_idx = block.find('"> 回复 <')
        main_block = block[:divider_idx] if divider_idx >= 0 else block
        wpm = re.search(r'<span class="wpw">(.+?)</span>', main_block, re.DOTALL)
        if not wpm:
            continue
        text = _clean(wpm.group(1))
        if not text:
            continue
        if '查看图片' in block:
            text = '[图片] ' + text
        if '[图片' in text and '图片评论' not in text:
            text = '[图片] ' + text

        item = {'user': user, 'time': time_str, 'content': text, 'replies': []}

        # 子回复：提取 bgc-body px-9 py-5 片段
        bgc_m = re.search(r'<div class="bgc-body px-9 py-5">(.*)', block, re.DOTALL)
        if bgc_m:
            item['replies'] = _extract_replies(bgc_m.group(1))

        comments.append(item)

    return comments

def extract_post_images(post_html):
    """提取正文中的私有图片 URL（去重）"""
    seen, imgs = set(), []
    for m in re.finditer(r'<img[^>]+src="([^"]+)"', post_html):
        url = m.group(1)
        if 'private.red-ring.cn' in url and url not in seen:
            seen.add(url)
            imgs.append(url)
    return imgs

def extract_post_body(html):
    """
    提取正文 HTML。
    innerHTML 来源有两个版本：
    1. CDP 提取（ql-view）：<div class="fzx-2 wwb ql-view ql-ring">...
    2. 备用（legacy）：<div class="post-body ...">...
    """
    # CDP 版本（主要）
    m = re.search(r'<div class="[^"]*ql-view[^"]*">(.*?)</div>\s*<!---->', html, re.DOTALL)
    if m and len(m.group(1)) > 100:
        return m.group(1)
    # Legacy 版本（降级）
    m = re.search(r'<div class="post-body[^"]*">(.*?)</div>\s*<!---->', html, re.DOTALL)
    if m:
        return m.group(1)
    return ''

# ═══════════════════════════════════════════════════════════════
# 图片上传层
# ═══════════════════════════════════════════════════════════════

def upload_images(urls, date, gh):
    """
    下载私有图片 → 上传 GitHub → 返回 {私有URL: GitHub_URL} 映射
    文件命名: caijing_{date}_img_{NN}.{ext}
    """
    mapping, total = {}, len(urls)
    for i, url in enumerate(urls, 1):
        ext = 'png' if '.png' in url else ('webp' if 'webp' in url else 'jpg')
        fname = f"caijing_{date}_img_{i:02d}.{ext}"
        gh_path = f"images/{date}/{fname}"
        try:
            req = urllib.request.Request(url, headers=get_headers())
            with urllib.request.urlopen(req, timeout=15) as r:
                if r.status != 200:
                    raise Exception(f"HTTP {r.status}")
                data = r.read()
                if len(data) < 2048:
                    raise Exception(f"Too small ({len(data)}B)")
                if b'<!DOCTYPE' in data[:50]:
                    raise Exception("HTML error page")
            b64 = base64.b64encode(data).decode('ascii')
            gurl = gh.upload(gh_path, b64)
            mapping[url] = gurl
            print(f"  [OK] {i}/{total} {fname} ({len(data)//1024}KB)")
        except Exception as e:
            print(f"  [FAIL] {i}/{total} {url[:60]} → {e}")
        if i < total:
            time.sleep(0.5)
    return mapping

# ═══════════════════════════════════════════════════════════════
# Markdown → HTML 渲染层（使用 (.+?) 非贪婪正则）
# ═══════════════════════════════════════════════════════════════

def md_to_html_with_comments(md_str, title, comments):
    """
    将 Markdown（含正文 + 评论）渲染为完整 HTML
    - 图片: ![alt](url) → <img src="url" ...>
    - 强调: **text** → <strong>text</strong>
    - 分割: --- → <hr>
    """
    def img_replace(m):
        src, alt = m.group(2), m.group(1)
        return (
            f'<img src="{src}" alt="{alt}" '
            f'loading="lazy" style="max-width:100%;border-radius:4px;margin:8px 0;display:block">'
        )

    # ⚠️ 必须用 (.+?) 非贪婪匹配，[^)]+ 会在 URL 第一个 ) 处截断
    body = re.sub(r'!\[([^\]]*)\]\((.+?)\)', img_replace, md_str)
    body = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', body)

    paras = []
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith('<img ') or line.startswith('<blockquote'):
            paras.append(line)
        elif line.startswith('---') or line.startswith('<hr'):
            paras.append('<hr class="divider">')
        else:
            paras.append(f'<p>{line}</p>')
    post_body_html = '\n'.join(paras)
    cmt_html = _render_comments_html(comments)

    CSS = """
    body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
         font-size:14px;max-width:720px;margin:0 auto;padding:16px;
         background:#fafafa;line-height:1.7;color:#333}
    .post{background:white;border-radius:8px;padding:20px;margin-bottom:16px;
          box-shadow:0 1px 3px rgba(0,0,0,.08)}
    .cmt-wrap{background:white;border-radius:8px;padding:20;margin-bottom:16px;
              box-shadow:0 1px 3px rgba(0,0,0,.08)}
    img{max-width:100%;border-radius:4px;margin:8px 0;display:block}
    strong{color:#c00}
    .cmt-item{background:#f9f9f9;border-radius:6px;padding:12px;margin-bottom:10px}
    .u{color:#1a73e8;font-weight:600}
    .t{color:#999;font-size:.8em}
    .r{margin-top:6px;padding:6px 10px 6px 14px;background:#f5f5f5;border-radius:4px;font-size:.88em;color:#555;border-left:3px solid #bdbdbd}
    .footer{text-align:center;color:#999;font-size:.8em;padding:20px 0;
            border-top:1px solid #eee;margin-top:30px}
    p{margin:.5em 0}
    .divider{border:none;border-top:1px solid #eee;margin:24px 0}
    h2{font-size:1.1em;margin-top:0;padding-bottom:8px;border-bottom:1px solid #eee}
    """

    return (
        '<!DOCTYPE html>\n<html lang="zh">\n<head>\n'
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f'<title>{title}</title>\n'
        '<style>\n' + CSS + '\n</style>\n'
        '</head>\n<body>\n'
        f'<div class="post">\n{post_body_html}\n</div>\n'
        '<div class="cmt-wrap">\n<h2>💬 评论区</h2>\n' + cmt_html + '\n</div>\n'
        '<div class="footer"><p>来源：小红圈 · 红运Dang投 · MR Dang<br>'
        'MCP-RedRing · SSOT 架构自动生成</p></div>\n'
        '</body>\n</html>'
    )

def _render_comments_html(comments):
    """评论数组 → HTML 片段（含嵌套子回复）"""
    if not comments:
        return '<p style="color:#999;text-align:center">暂无评论</p>'
    parts = []
    for c in comments:
        reply_parts = []
        for r in c.get('replies', []):
            reply_parts.append(
                '<div class="r"><span class="u">' + r['user'] + '</span>' + r['content'] + '</div>'
            )
        replies_html = ''.join(reply_parts)
        parts.append(
            '<div class="cmt-item">'
            '<div><span class="u">' + c['user'] + '</span> '
            '<span class="t">' + c['time'] + '</span></div>'
            '<div style="margin-top:4px">' + c['content'] + '</div>'
            + replies_html +
            '</div>'
        )
    return '\n'.join(parts)



def gh_put(path, content_b64, msg, branch="main"):
    """PUT file to GitHub repo, handles existing file SHA"""
    api = f"https://api.github.com/repos/{REPO}/contents/{path}"
    payload = {"message": msg, "content": content_b64, "branch": branch}
    # get existing SHA
    try:
        greq = urllib.request.Request(
            api + "?ref=" + branch,
            headers={"Authorization": "token " + TOKEN}
        )
        with urllib.request.urlopen(greq, timeout=8) as r:
            existing = json.loads(r.read())
            if existing.get('sha'):
                payload["sha"] = existing['sha']
    except:
        pass
    req = urllib.request.Request(
        api, data=json.dumps(payload).encode(),
        headers={"Authorization": "token " + TOKEN, "Content-Type": "application/json"},
        method="PUT"
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

# ═══════════════════════════════════════════════════════════════
# 主入口（CLI）
# ═══════════════════════════════════════════════════════════════

def build(html_file, date, output_file=None, title=None):
    """
    SSOT 构建流水线
    1. 读取 innerHTML 文件
    2. 提取正文 / 评论 / 图片
    3. 上传图片到 GitHub
    4. markdownify 无损渲染
    5. 上传 HTML + 触发 GitHub Pages
    """
    date_str = date  # YYYYMMDD
    display_date = f"{date[:4]}-{date[4:6]}-{date[6:]}"

    with open(html_file, encoding='utf-8', errors='replace') as f:
        full_html = f.read()

    # 裁切 POST_START / POST_END 标记
    s = full_html.find('POST_START')
    e = full_html.find('POST_END')
    if s != -1 and e != -1:
        full_html = full_html[s + 10:e]

    # HTML entity 解码（&amp; → &），图片 URL 必须解码后才能正确匹配
    full_html = html_mod.unescape(full_html)

    post_body_html = extract_post_body(full_html)
    post_images = extract_post_images(post_body_html)
    comments = extract_comments(full_html)

    # 如果正文提取为空，尝试直接用完整 innerHTML（去掉 POST_START/POST_END）
    if not post_body_html.strip():
        print("[build] WARN: post-body 为空，直接使用完整 innerHTML")
        post_body_html = full_html

    print(f"[build] innerHTML: {len(full_html)} chars | body: {len(post_body_html)} chars")
    print(f"[build] 正文图片: {len(post_images)} 张 | 评论: {len(comments)} 条")

    # 上传图片
    gh = GitHubUploader(token=TOKEN, repo=REPO)
    mapping = upload_images(post_images, date_str, gh) if post_images else {}
    print(f"[build] 图片映射: {len(mapping)}/{len(post_images)} 成功")

    # markdownify 无损转换
    post_md = mf.markdownify(post_body_html, heading_style="atx", link_style="inlined")
    for old_url, new_url in mapping.items():
        post_md = post_md.replace(old_url, new_url)

    if title is None:
        title = f"财经早餐 {display_date}"
    final_html = md_to_html_with_comments(post_md, title=title, comments=comments)

    gh_img_count = final_html.count('raw.githubusercontent.com')
    print(f"[build] 最终 HTML: {len(final_html)} bytes | GitHub 图片: {gh_img_count} 张")

    # 上传 HTML
    if output_file is None:
        output_file = f"caijing_{date_str}.html"
    b64 = base64.b64encode(final_html.encode('utf-8')).decode('ascii')
    result = gh_put(output_file, b64, f"发布 {display_date} 财经早餐 (SSOT build)")
    print(f"[build] HTML 上传: {result.get('content', {}).get('download_url', '')[:80]}")

    # 触发 GitHub Pages
    pages_url = f"https://frankinvest.github.io/caijing-daily/{output_file}"
    try:
        ok = GitHubPagesTrigger(token=TOKEN, repo=REPO).trigger_and_wait()
        print(f"[build] GitHub Pages: {'OK' if ok else 'TIMEOUT'} {pages_url}")
    except Exception as e:
        print(f"[build] GitHub Pages 触发异常: {e}")
        print(f"[build] 直接访问: {pages_url}")

    return {
        "html_file": output_file,
        "images": len(mapping),
        "comments": len(comments),
        "url": pages_url
    }

def main():
    ap = argparse.ArgumentParser(
        description='SSOT 渲染引擎 - 从 innerHTML 生成财经早餐 HTML（v11 熔断版）',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument('html_file',
                    help='innerHTML 文件路径（来自 cdp_get_innerhtml.py），或填 AUTO 启用自动模式')
    ap.add_argument('date', nargs='?', default=None,
                    help='日期 YYYYMMDD（auto-latest 模式下只作初始占位，会被 HTML 内标题覆盖）')
    ap.add_argument('output_file', nargs='?', default=None,
                    help='输出 HTML 文件名，如 caijing_20260513.html（默认: caijing_{date}.html）')
    ap.add_argument('--title', '-t', default=None, help='页面标题（默认: 财经早餐 YYYY-MM-DD）')
    ap.add_argument('--auto-latest', action='store_true',
                    help='自动调用 cdp_get_innerhtml.py --auto-latest，完成找帖+日期熔断+提取全流程')
    ap.add_argument('--group-url',
                    default='https://www.red-ring.cn/group/27593',
                    help='圈子页面 URL（auto-latest 模式使用）')
    ap.add_argument('--cdp-ws-url', default='AUTO',
                    help='CDP WebSocket URL（默认 AUTO）')
    args = ap.parse_args()

    auto_mode = args.html_file == 'AUTO' or args.auto_latest

    if auto_mode:
        import subprocess, tempfile, os as _os
        _parent = _os.path.dirname(_os.path.abspath(__file__))
        cdp_script = _os.path.join(_parent, 'cdp_get_innerhtml.py')
        tmp_file = tempfile.NamedTemporaryFile(suffix='_post.html', delete=False, mode='w')
        tmp_path = tmp_file.name
        tmp_file.close()

        cdp_cmd = [
            'python3', cdp_script, tmp_path,
            args.cdp_ws_url,
            '--auto-latest',
            '--group-url', args.group_url,
            '--selector', 'main'
        ]
        print(f"[build] AUTO模式: {' '.join(cdp_cmd[:3])} ...")
        cp = subprocess.run(cdp_cmd, capture_output=True, text=True, timeout=60)
        print(cp.stdout)
        if cp.stderr:
            print(cp.stderr, file=sys.stderr)
        if cp.returncode == 3:
            print("[build] ❌ 日期熔断：今日帖子不存在或未发布，退出。")
            sys.exit(3)
        if cp.returncode != 0:
            print(f"[build] ❌ cdp_get_innerhtml 失败 (exit {cp.returncode})")
            sys.exit(1)
        args.html_file = tmp_path
        # 从 HTML 内容提取真实日期
        discovered = _extract_date_from_html(tmp_path)
        if discovered:
            print("[build] INFO: discovered date from HTML:", discovered, "| original:", args.date or "none")
            if args.date and args.date != discovered:
                print("[build] WARNING: date mismatch, auto-corrected to", discovered)
            args.date = discovered
        if not args.date:
            print("[build] ❌ 无法从 HTML 推断日期，且未传入 date 参数")
            sys.exit(1)

    result = build(
        html_file=args.html_file,
        date=args.date,
        output_file=args.output_file,
        title=args.title
    )
    print("\n✅ 完成:", json.dumps(result, ensure_ascii=False))


def _extract_date_from_html(html_file):
    """从 HTML 内容提取帖子标题中的日期，返回 YYYYMMDD 或 None"""
    import re
    try:
        with open(html_file, encoding='utf-8', errors='replace') as f:
            content = f.read()
        s = content.find('POST_START')
        e = content.find('POST_END')
        if s != -1 and e != -1:
            content = content[s+10:e]
        # 匹配标题中的日期：2026年5月19日、2026-05-19、2026/05/19
        m = re.search(r'(\d{4})[年\-/:](\d{1,2})[月\-/:](\d{1,2})', content)
        if m:
            y, mo, d = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
            return f"{y}{mo}{d}"
    except:
        pass
    return None


if __name__ == "__main__":
    main()
def _render_comments_html(comments):
    """评论数组 → HTML 片段（含嵌套子回复）"""
    if not comments:
        return '<p style="color:#999;text-align:center">暂无评论</p>'
    parts = []
    for c in comments:
        reply_html = ''
        for r in c.get('replies', []):
            reply_html += (
                '<div class="r">'
                '<span class="u">' + r['user'] + '</span>' + r['content'] +
                '</div>'
            )
        parts.append(
            '<div class="cmt-item">'
            '<div><span class="u">' + c['user'] + '</span> '
            '<span class="t">' + c['time'] + '</span></div>'
            '<div style="margin-top:4px">' + c['content'] + '</div>'
            + reply_html +
            '</div>'
        )
    return '\n'.join(parts)

```

---

## 2.4 GitHub 分批上传队列

**路径：** `~/.openclaw/workspace/shared/network/batch_uploader.py`

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shared/network/batch_uploader.py

通用分批上传队列
将大量文件稳妥分批推送到云端（GitHub / Gitea / 阿里OSS / S3）

核心铁律:
1. 每批最多 5 个文件
2. 批次之间强制等待 1 秒
3. fetch 验证可访问性，失败则跳过并记录
4. 指数退避重试（遇到 429/503 时）

使用方式:
    from shared.network import BatchUploader

    # 定义单个文件上传函数
    def github_put(filename: str, content_b64: str) -> str:
        return github_upload(filename, b64)["content"]["download_url"]

    # 上传 50 张图片
    uploader = BatchUploader(uploader=github_put, batch_size=5, delay_ms=1000)
    result = uploader.upload_all(files)
    print(f"成功 {result['success']} 张，失败 {result['failed']} 张")
"""

import time
import asyncio
import base64
import urllib.request
import urllib.error
import json
from typing import Callable, Optional

# ---- 标准 Base64 编码（处理大文件不爆栈）----

def base64_encode(data: bytes) -> str:
    """标准 Base64 编码，支持任意大小文件"""
    binary = []
    for i in range(0, len(data), 8192):
        chunk = data[i:i + 8192]
        binary.append(chunk)
    return base64.b64encode(b''.join(binary)).decode('ascii')


# ---- GitHub 专用上传器（开箱即用）----

class GitHubUploader:
    """
    GitHub 仓库文件上传器（可作为 BatchUploader 的 uploader 参数）
    
    Usage:
        uploader = GitHubUploader(
            token="ghp_xxx",
            repo="owner/repo"
        )
        url = uploader.upload("caijing_20260513_img_01.jpg", image_b64)
    """

    def __init__(
        self,
        token: str,
        repo: str,
        branch: str = "main",
        author_name: str = "openclaw",
        author_email: str = "agent@openclaw.ai"
    ):
        self.token = token
        self.repo = repo
        self.branch = branch
        self.api = f"https://api.github.com/repos/{repo}/contents"
        self.headers = {
            "Authorization": "token " + token,
            "Content-Type": "application/json",
            "Accept": "application/vnd.github+json"
        }
        self.author = {"name": author_name, "email": author_email}

    def _get_sha(self, path: str) -> Optional[str]:
        """获取文件 SHA（更新时必须）"""
        req = urllib.request.Request(
            self.api + "/" + path + f"?ref={self.branch}",
            headers=self.headers
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read()).get("sha")
        except Exception:
            return None

    def upload(self, filename: str, content_b64: str, message: str = None) -> str:
        """
        上传单个文件到 GitHub 仓库
        
        Args:
            filename: 仓库内路径（含文件名）
            content_b64: 文件内容的 base64 编码
            message: 提交消息
            
        Returns:
            download_url
        """
        sha = self._get_sha(filename)
        body = {
            "message": message or f"Upload {filename}",
            "content": content_b64,
            "branch": self.branch,
            "author": self.author
        }
        if sha:
            body["sha"] = sha

        body_enc = json.dumps(body).encode('utf-8')
        req = urllib.request.Request(
            self.api + "/" + filename,
            data=body_enc,
            headers=self.headers,
            method="PUT"
        )

        with urllib.request.urlopen(req, timeout=15) as r:
            result = json.loads(r.read())
            return result["content"]["download_url"]


# ---- 分批上传队列核心类 ----

class BatchUploader:
    """
    分批上传队列
    
    解决核心问题:
    - 大量文件并发上传 → API 超时/限流
    - 单次 evaluate 60s 上限 → 大文件无法在浏览器内完成
    - 网络波动导致部分失败 → 自动重试
    
    铁律:
    - 每批不超过 batch_size 个文件（默认 5）
    - 批次之间强制等待 delay_ms 毫秒（默认 1000）
    - fetch 验证 URL 可访问性，失败跳过
    - 429/503 触发指数退避重试
    """

class BatchUploader:
    """
    分批上传队列
    
    解决核心问题:
    - 大量文件并发上传 → API 超时/限流
    - 单次 evaluate 60s 上限 → 大文件无法在浏览器内完成
    - 网络波动导致部分失败 → 自动重试
    - 防盗链/鉴权下载 → 403错误页被当成图片上传
    
    铁律:
    - 每批不超过 batch_size 个文件（默认 5）
    - 批次之间强制等待 delay_ms 毫秒（默认 1000）
    - fetch 验证可访问性，失败跳过
    - 下载时强制携带防盗链 headers（Cookie/UA/Referer）
    - 内容校验：文件 > 2KB 且非 HTML 错误页
    """

    def __init__(
        self,
        uploader: Callable[[str, str], str],
        # uploader(filename: str, content_b64: str) -> download_url
        batch_size: int = 5,
        delay_ms: int = 1000,
        max_retries: int = 3,
        download_headers: dict = None,
        # 下载时的 HTTP Headers（防盗链必需）
        # 示例: {"Cookie": "Hm_lvt_xxx=...", "User-Agent": "Mozilla/5.0...", "Referer": "https://example.com/"}
        min_file_size: int = 2048,
        # 文件小于此字节数视为无效（防盗链错误页）
    ):
        self.uploader = uploader
        self.batch_size = batch_size
        self.delay_ms = delay_ms
        self.max_retries = max_retries
        self.download_headers = download_headers or {}
        self.min_file_size = min_file_size

    def _sleep_ms(self, ms: int):
        time.sleep(ms / 1000)

    def _retry_with_backoff(self, fn, *args, **kwargs):
        """指数退避重试"""
        last_error = None
        for attempt in range(self.max_retries):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                last_error = e
                wait_ms = (2 ** attempt) * 500  # 500, 1000, 2000ms
                if "429" in str(e) or "503" in str(e):
                    self._sleep_ms(wait_ms)
                    continue
                raise
        raise last_error

    async def upload_all(self, files: list, *, progress_callback=None) -> dict:
        """
        分批上传所有文件
        
        Args:
            files: 文件列表
                [
                    {"url": "https://private.site.com/img1.jpg", "filename": "img_01.jpg"},
                    {"url": "https://private.site.com/img2.jpg", "filename": "img_02.jpg", "ext": "png"},
                    ...
                ]
            progress_callback: 可选，进度回调 (completed, total, last_result)
        
        Returns:
            {
                "total": 13,
                "success": 12,
                "failed": 1,
                "mapping": {"原始URL": "上传后URL", ...},
                "errors": [{"url": "...", "error": "..."}, ...]
            }
        """
        results = {
            "total": len(files),
            "success": 0,
            "failed": 0,
            "mapping": {},
            "errors": []
        }

        for batch_start in range(0, len(files), self.batch_size):
            batch = files[batch_start:batch_start + self.batch_size]

            for i, f in enumerate(batch):
                idx = batch_start + i + 1
                url = f["url"]
                filename = f["filename"]
                ext = f.get("ext") or ("png" if ".png" in url else "jpg")

                try:
                    # fetch 验证可访问性（携带防盗链 Headers）
                    import urllib.request
                    req = urllib.request.Request(url, headers=self.download_headers)
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        if resp.status != 200:
                            raise Exception(f"HTTP {resp.status}")

                    # 读取内容
                    content = resp.read()

                    # 🔒 内容校验：小于 min_file_size 或 HTML 错误页 → 抛异常
                    if len(content) < self.min_file_size:
                        # 可能是防盗链 403/401 错误页
                        raise Exception(f"文件过小({len(content)}B)，疑似防盗链拒绝")
                    # 检查是否为 HTML 错误页（防盗链常返回错误页而非真实图片）
                    content_head = content[:100].decode('utf-8', errors='ignore').strip().lower()
                    if any(x in content_head for x in ['<!doctype', '<html', '<body', '<?xml', '<!doctype html']):
                        raise Exception(f"下载到 HTML 错误页({len(content)}B)，防盗链拒绝")
                    # 可选：Content-Type 校验
                    ctype = resp.headers.get('Content-Type', '').lower()
                    if ctype and not any(x in ctype for x in ['image/', 'application/octet']):
                        # 非图片 Content-Type，但不阻断，仅警告
                        print(f"  WARN {idx}/{len(files)} Content-Type: {ctype}")

                    b64 = base64_encode(content)

                    # 上传（带重试）
                    download_url = self._retry_with_backoff(
                        self.uploader, filename, b64
                    )

                    results["mapping"][url] = download_url
                    results["success"] += 1
                    print(f"  OK   {idx}/{len(files)} {filename} ({len(content)//1024}KB)")

                except Exception as e:
                    results["failed"] += 1
                    results["errors"].append({"url": url, "filename": filename, "error": str(e)})
                    print(f"  FAIL {idx}/{len(files)} {filename}: {e}")

                if progress_callback:
                    progress_callback(results["success"] + results["failed"], len(files), f)

            # 批次间延迟
            if batch_start + self.batch_size < len(files):
                self._sleep_ms(self.delay_ms)

        return results

    # ---- 同步封装（兼容非 async 环境）----

    def upload_all_sync(self, files: list, progress_callback=None) -> dict:
        """同步版本（供传统 Python 脚本调用）"""
        return asyncio.run(self.upload_all(files, progress_callback=progress_callback))


# ---- 便捷工厂：GitHub 分批上传器 ----

def github_batch_uploader(
    github_token: str,
    github_repo: str,
    batch_size: int = 5,
    delay_ms: int = 1000,
    download_headers: dict = None
) -> BatchUploader:
    """
    创建 GitHub 专用分批上传器
    
    Usage:
        uploader = github_batch_uploader(
            github_token="ghp_xxx",
            github_repo="owner/repo",
            download_headers={
                "Cookie": "Hm_lvt_xxx=...",
                "User-Agent": "Mozilla/5.0 ...",
                "Referer": "https://example.com/"
            }
        )
        result = uploader.upload_all_sync([
            {"url": "https://private.site/1.jpg", "filename": "1.jpg"},
            {"url": "https://private.site/2.jpg", "filename": "2.jpg"},
        ])
    """
    gh = GitHubUploader(token=github_token, repo=github_repo)
    return BatchUploader(
        uploader=gh.upload,
        batch_size=batch_size,
        delay_ms=delay_ms,
        download_headers=download_headers or {}
    )

```

---

## 2.5 GitHub Pages 构建触发器

**路径：** `~/.openclaw/workspace/shared/deploy/github_pages.py`

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shared/deploy/github_pages.py

GitHub Pages 构建触发器 + 状态轮询

使用方式:
    from shared.deploy import GitHubPagesTrigger

    trigger = GitHubPagesTrigger(
        token="ghp_xxx",
        repo="owner/repo"
    )
    trigger.build()                    # 触发构建
    success = trigger.wait_built()     # 等待完成
"""

import time
import urllib.request
import urllib.error
import json
from typing import Optional


class GitHubPagesTrigger:
    """
    GitHub Pages 构建触发器
    
    能力:
    1. 触发构建（POST /repos/{owner}/{repo}/pages/builds）
    2. 查询最新构建状态（GET /repos/{owner}/{repo}/pages/builds/latest）
    3. 等待构建完成（带超时）
    4. 获取 Pages 访问地址
    """

    BUILD_TIMEOUT = 90  # 最大等待秒数
    BUILD_INTERVAL = 5  # 轮询间隔秒数

    def __init__(self, token: str, repo: str):
        self.token = token
        self.repo = repo
        self.api_pages = f"https://api.github.com/repos/{repo}/pages"
        self.api_builds = f"https://api.github.com/repos/{repo}/pages/builds"
        self.headers = {
            "Authorization": "token " + token,
            "Accept": "application/vnd.github+json"
        }

    def _request(self, url: str, method: str = "GET", data: dict = None) -> dict:
        body = json.dumps(data or {}).encode("utf-8") if data else None
        req = urllib.request.Request(
            url,
            data=body,
            headers=self.headers,
            method=method
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())

    def build(self) -> dict:
        """
        触发 GitHub Pages 构建
        
        Returns:
            {"status": "queued", "url": "...", ...}
        """
        result = self._request(self.api_builds, method="POST")
        print(f"[GitHubPages] 构建已触发: {result.get('url')}")
        return result

    def get_status(self) -> Optional[dict]:
        """
        获取最新构建状态
        
        Returns:
            None (无可用构建记录)
            或 {"status": "built"|"building"|"queued"|"errored", ...}
        """
        try:
            return self._request(self.api_builds + "/latest")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise

    def wait_built(self, timeout: int = None, interval: int = None) -> bool:
        """
        等待构建完成（阻塞）
        
        Args:
            timeout: 超时秒数（默认 BUILD_TIMEOUT=90）
            interval: 轮询间隔秒数（默认 BUILD_INTERVAL=5）
            
        Returns:
            True  = 构建成功 (status == "built")
            False = 超时或错误 (status == "errored")
        """
        timeout = timeout or self.BUILD_TIMEOUT
        interval = interval or self.BUILD_INTERVAL
        start = time.time()

        while time.time() - start < timeout:
            status = self.get_status()
            if status:
                s = status.get("status")
                print(f"[GitHubPages] 状态: {s}")
                if s == "built":
                    return True
                if s == "errored":
                    error_msg = status.get("error", {}).get("message", "未知错误")
                    print(f"[GitHubPages] 构建错误: {error_msg}")
                    return False
            time.sleep(interval)

        print(f"[GitHubPages] 构建超时（>{timeout}s）")
        return False

    def get_pages_url(self) -> str:
        """
        获取 GitHub Pages 访问地址
        
        Returns:
            https://{username}.github.io/{repo}/
        """
        # 从仓库信息获取
        api_repo = f"https://api.github.com/repos/{self.repo}"
        repo_info = self._request(api_repo)
        owner = repo_info.get("owner", {}).get("login", "")
        name = repo_info.get("name", "")
        
        # Pages URL 格式
        if repo_info.get("has_pages"):
            return f"https://{owner.lower()}.github.io/{name}/"
        return f"https://{owner.lower()}.github.io/{name}/"

    def trigger_and_wait(self) -> bool:
        """
        一键触发 + 等待（最常用组合）
        
        Returns:
            True = 构建成功，False = 超时/失败
        """
        self.build()
        ok = self.wait_built()
        if ok:
            print(f"[GitHubPages] ✅ 构建成功！")
            print(f"       访问: {self.get_pages_url()}")
        else:
            print(f"[GitHubPages] ❌ 构建失败或超时")
        return ok

```
