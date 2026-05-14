#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cdp_get_innerhtml.py — 稳定版（v10）

设计原则：
  Chrome 对含 scrollBy 的长 evaluate 有 30s 硬超时，极不稳定。
  改为纯提取策略：用户通过正常使用（浏览帖子）预加载评论，
  本脚本只负责提取当前 DOM，不主动滚动。

用法:
    python3 cdp_get_innerhtml.py <output_html_file> [cdp_ws_url]
"""
import websocket, json, time, sys, os, argparse

DEFAULT_WS = "ws://127.0.0.1:18900/devtools/page/DCDBD120E79E4B69E755CAC03E39F11F"
DEFAULT_SELECTOR = "main"

EXTRACT_JS = r"""
(function() {
  if (!window.__dd) window.__dd = {};
  var el = document.querySelector(%(selector)r);
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

def _eval(ws_url, msg_id, js, timeout=15):
    ws = websocket.create_connection(ws_url, suppress_origin=True, timeout=10)
    try:
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
            time.sleep(0.2)
        raise Exception(f"CDP timeout after {timeout}s")
    finally:
        ws.close()

def fetch_innerhtml(ws_url, selector=DEFAULT_SELECTOR):
    print(f"[CDP] 提取 innerHTML ...")
    js = EXTRACT_JS % {"selector": json.dumps(selector)}
    data = _eval(ws_url, 1, js, timeout=20)
    raw = data["result"]["result"]["value"]
    parsed = json.loads(raw)
    html = parsed["html"]
    cnt = parsed.get("commentCount", 0)
    scroll_h = parsed.get("scrollHeight", 0)
    inner_h = parsed.get("innerHeight", 0)
    print(f"[CDP] 提取完成: comments={cnt}, scrollHeight={scroll_h}, innerHeight={inner_h}")
    return html

def main():
    ap = argparse.ArgumentParser(description='CDP innerHTML 提取工具（稳定版 v10）')
    ap.add_argument('output_file', help='输出 HTML 文件路径')
    ap.add_argument('cdp_ws_url', nargs='?', default=DEFAULT_WS, help='CDP WebSocket URL')
    ap.add_argument('--selector', '-s', default=DEFAULT_SELECTOR, help='CSS 选择器')
    args = ap.parse_args()
    print(f"[CDP] Output: {args.output_file} | Selector: {args.selector}")
    try:
        html = fetch_innerhtml(args.cdp_ws_url, args.selector)
    except Exception as e:
        print(f"[CDP] Failed: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)
    os.makedirs(os.path.dirname(args.output_file) or '.', exist_ok=True)
    with open(args.output_file, "w", encoding="utf-8", errors="replace") as f:
        f.write(html)
    print(f"[CDP] ✅ {len(html)} bytes → {args.output_file}")

if __name__ == "__main__":
    main()
