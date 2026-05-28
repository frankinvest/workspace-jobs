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

def _resolve_auto_url():
    """从 Chrome CDP 端点获取当前活跃 Tab 的 WebSocket URL"""
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:18900/json", timeout=5) as r:
            tabs = json.loads(r.read())
        for tab in tabs:
            ws_url = tab.get("webSocketDebuggerUrl")
            if ws_url and "chrome://" not in tab.get("url", "") and "newtab" not in tab.get("url", ""):
                print(f"[AUTO]Resolved CDP: {tab.get('title', '')} -> {ws_url}")
                return ws_url
        # fallback: return first tab
        if tabs:
            return tabs[0].get("webSocketDebuggerUrl", "ws://127.0.0.1:18900/devtools/page/9A6EE8344223B1E0D9B178FFA26031EC")
    except Exception as e:
        print(f"[AUTO] resolve warning: {e}")
    return "ws://127.0.0.1:18900/devtools/page/9A6EE8344223B1E0D9B178FFA26031EC"

def _ws_connect(ws_url, timeout=10):
    if ws_url == "AUTO":
        ws_url = _resolve_auto_url()
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
    """Page.navigate 并等待 load 事件；若已在目标 URL 则跳过导航"""
    # 先检查当前 URL，避免在已处于目标页时调用 Page.navigate
    ws.send(json.dumps({"id": 98, "method": "Runtime.evaluate", "params": {"expression": "window.location.href"}}))
    current_url = None
    try:
        raw = ws.recv()
        data = json.loads(raw)
        if data.get("result", {}).get("result", {}).get("type") == "string":
            current_url = data["result"]["result"]["value"]
    except:
        pass
    if current_url == url:
        print(f"[CDP] 已在目标页 ({url})，执行强制刷新...")
        ws.send(json.dumps({"id": 99, "method": "Runtime.evaluate",
                            "params": {"expression": "window.location.reload();", "returnByValue": True}}))
        time.sleep(3)
        # 等待刷新完成
        deadline = time.time() + timeout
        while time.time() < deadline:
            ws.send(json.dumps({"id": 97, "method": "Runtime.evaluate",
                                "params": {"expression": "document.readyState"}}))
            try:
                raw = ws.recv()
                data = json.loads(raw)
                state = data.get("result", {}).get("result", {}).get("value", "")
                if state == "complete":
                    return
            except:
                pass
            time.sleep(0.5)
        raise Exception("Page.reload timeout")
    ws.send(json.dumps({
        "id": 99,
        "method": "Page.navigate",
        "params": {"url": url}
    }))
    # 等待 Page.loadEventFired
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            raw = ws.recv()
            data = json.loads(raw)
            if data.get("method") == "Page.loadEventFired":
                break  # 初始 HTML 加载完成，继续等 SPA ready
        except:
            pass
        time.sleep(0.3)
    # SPA 可能还在渲染，继续等 readyState === 'complete'（最多再等 timeout 秒）
    deadline = time.time() + timeout
    while time.time() < deadline:
        ws.send(json.dumps({"id": 96, "method": "Runtime.evaluate",
                            "params": {"expression": "document.readyState"}}))
        try:
            raw = ws.recv()
            data = json.loads(raw)
            state = data.get("result", {}).get("result", {}).get("value", "")
            if state == "complete":
                return
        except:
            pass
        time.sleep(0.5)
    raise Exception("Page.navigate timeout")

# ── 自动找帖（--auto-latest 核心逻辑）────────────────────────────

def get_today_date_str():
    """返回 'YYYY-MM-DD' 格式的今日日期字符串（北京时间）"""
    import datetime
    # 北京时间 = UTC+8
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
    return now.strftime("%Y-%m-%d")

def auto_find_latest_post(ws_url, group_url, timeout=30):
    """
    通过 CDP 导航到圈子页面，自动解析今日财经早餐帖子 URL。
    返回 (target_post_url, ws_url) — WS URL 不变（还是当前 tab）
    日期不匹配时触发熔断（exit 3）。
    """
    print(f"[AUTO] 连接 CDP: {ws_url}")
    ws = _ws_connect(ws_url, timeout=10)
    try:
        print(f"[AUTO] 导航到圈子页面: {group_url}")
        _navigate(ws, group_url, timeout=20)
        time.sleep(2)  # 等待帖子列表渲染

        # 深度循环滚动：懒加载帖子可能压在首屏以下
        print("[AUTO] 执行深度滚动以加载更多隐藏帖子...")
        for i in range(4):
            _eval(ws, 997 + i, "window.scrollBy(0, 1000);", timeout=10)
            time.sleep(1)
        _eval(ws, 996, "window.scrollTo(0, 0);", timeout=10)  # 回顶
        time.sleep(1)

        # 在页面中执行 JS：收集所有帖子链接 + 日期，找到今日最早那条
        # 使用健壮的内联文本扫描（不受 CSS 类名变化影响）
        find_js = r"""
        (function(){
            var today = arguments[0];
            var results = [];
            var seen = {};
            var main = document.querySelector('main');
            if (!main) return JSON.stringify({today: today, posts: []});

            main.querySelectorAll('a[href*="/post/"]').forEach(function(a){
                var href = a.href;
                if (seen[href]) return;
                seen[href] = 1;

                // 提取标题（链接文本本身）
                var titleText = a.innerText ? a.innerText.trim().replace(/\s+/g, ' ') : '';

                // 在父级容器中搜索时间（内联文本扫描，比 CSS 选择器更健壮）
                var el = a.parentElement;
                var timeText = '';
                for (var i = 0; i < 6; i++) {
                    if (!el) break;
                    var lines = (el.innerText || '').split('\n');
                    for (var j = 0; j < lines.length; j++) {
                        var t = lines[j].trim();
                        // 匹配时间格式："今天 HH:mm"、"昨天 HH:mm"、"小时前"、"分钟前"、"刚刚"、"MM-DD HH:mm"、"2026-MM-DD HH:mm"
                        if ((t.match(/^\d{2}:\d{2}$/) && t.length == 5) ||
                            (t.includes('今天') || t.includes('昨天')) ||
                            t.includes('小时前') || t.includes('分钟前') || t.includes('刚刚') ||
                            t.match(/^\d{4}-\d{2}-\d{2}/) ||
                            t.match(/^\d{2}-\d{2}/)) {
                            if (t.length < 30) { timeText = t; break; }
                        }
                    }
                    if (timeText) break;
                    el = el.parentElement;
                }

                results.push({time: timeText, title: titleText, href: href});
            });

            return JSON.stringify({today: today, posts: results.slice(0, 30)});
        })('%s')
        """ % get_today_date_str()

        data = _eval(ws, 2, find_js, timeout=20)
        raw = data["result"]["result"]["value"]
        parsed = json.loads(raw)

        today = parsed["today"]
        posts = parsed.get("posts", [])
        print(f"[AUTO] 今日日期: {today}，发现 {len(posts)} 条帖子")

        # 打印前几条用于调试
        for p in posts[:10]:
            print(f"       [{p['time']}] {p['href']}")

        # 找今日的帖子（时间包含 "今天" 或日期匹配 today）
        # 由于标题在列表页可能为空，先收集所有今日帖子，再逐个验证
        # 收集今日或昨天的候选帖子（兼容作者深夜提前发帖的情况）
        today_candidates = []
        for p in posts:
            tt = p['time']
            # "今天"、"昨天"、或精确日期匹配都纳入
            if ('今天' in tt or '昨天' in tt or today in tt):
                today_candidates.append(p)

        if not today_candidates:
            print(f"[AUTO] ❌ 今日（{today}）未找到任何帖子，触发熔断！")
            sys.exit(3)   # ← 熔断退出码

        # 取 ID 最大的今日帖子作为主帖（ID 越大越新）
        def post_id_from_url(url):
            m = re.search(r'/post/\d+-(\d+)', url)
            return int(m.group(1)) if m else 0

        today_candidates.sort(key=lambda p: post_id_from_url(p['href']), reverse=True)
        target = today_candidates[0]
        print(f"[AUTO] 今日候选 {len(today_candidates)} 条，选定最新主帖: {target['href']}")

        # 导航到目标帖子
        print(f"[AUTO] 导航到目标帖子 ...")
        _navigate(ws, target['href'], timeout=20)
        time.sleep(2)

        return ws, target['href']

    finally:
        ws.close()

# ── innerHTML 提取 ───────────────────────────────────────────────

EXTRACT_JS = r"""
(function() {
  var sel = arguments[0];
  var el = sel ? document.querySelector(sel) : null;
  if (!el) el = document.querySelector('.post-body,.ql-view,[class*=post-body],main,article,body');
  if (!el) el = document.body;
  return JSON.stringify({
    html: 'POST_START' + el.innerHTML + 'POST_END',
    commentCount: document.querySelectorAll('.py-12.flex.bt').length,
    scrollHeight: document.body.scrollHeight,
    innerHeight: window.innerHeight
  });
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
        ws, post_url = auto_find_latest_post(ws_url, group_url)
        # 重新连接来执行提取
        ws2 = _ws_connect(ws_url if ws_url != "AUTO" else ws_url, timeout=10)
        try:
            print(f"[CDP] 提取 innerHTML ...")
            js = EXTRACT_JS % {"selector": json.dumps(selector)}
            data = _eval(ws2, 1, js, timeout=20)
        finally:
            ws2.close()
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
            js = EXTRACT_JS
            data = _eval(ws, 1, js % json.dumps(selector), timeout=20)
        finally:
            ws.close()

    try:
        raw = data["result"]["result"]["value"]
    except (KeyError, TypeError) as e:
        # 打印原始响应以便诊断
        print(f"[CDP] ⚠️ 提取响应结构异常: {e}, data={str(data)[:500]}")
        raise RuntimeError(f"[CDP] innerHTML 提取失败，响应异常: {str(data)[:200]}")
    parsed = json.loads(raw)
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
