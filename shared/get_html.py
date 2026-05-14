#!/usr/bin/env python3
import websocket, json, time

WS_URL = "ws://127.0.0.1:18900/devtools/page/DCDBD120E79E4B69E755CAC03E39F11F"
OUT = "/Users/frank_bot/.openclaw/workspace/pipeline_input.html"

js = """
(function(){
  var m = document.querySelector("main");
  if (!m) return "";
  var c = m.cloneNode(true);
  c.querySelectorAll("[class*=comment],[class*=reply],.cmt-item,.py-12,.icon-wrap,[class*=actions],footer,.reply-wrap,.comment-body,.replies")
    .forEach(function(e){ e.remove(); });
  return c.innerHTML;
})()
"""

try:
    ws = websocket.WebSocket()
    ws.connect(WS_URL, suppress_origin=True)
    ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": js, "returnByValue": True}}))
    time.sleep(2)
    ws.close()
    # Read result from WebSocket
    # Reconnect to get result
    ws2 = websocket.WebSocket()
    ws2.connect(WS_URL, suppress_origin=True)
    ws2.send(json.dumps({"id": 2, "method": "Runtime.evaluate", "params": {"expression": "window._lastResult", "returnByValue": True}}))
    time.sleep(0.5)
    ws2.close()
except Exception as e:
    print("CDP error:", e)
    # Fallback: use requests with browser cookies
    pass

# If CDP didn't work, use requests with session cookies
import urllib.request, http.cookiejar

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

# Add cookies from known session
import sys
sys.path.insert(0, "/Users/frank_bot/.openclaw/workspace")

# Try to load cookies from session manager if available
cookies = {}
cookie_file = "/Users/frank_bot/.openclaw/workspace/red-ring-cookies.json"
try:
    import json
    with open(cookie_file) as f:
        cookies = json.load(f)
except:
    pass

url = "https://www.red-ring.cn/post/27593-2120574"
req = urllib.request.Request(url, headers={
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    "Cookie": "Hm_lvt_1c9949e59fafcdf8f7cd363b452f1837=1778115791,1778500926; HMACCOUNT=77046ED79FB0AFED; Hm_lpvt_1c9949e59fafcdf8f7cd363b452f1837=1778653122"
})
try:
    with opener.open(req, timeout=10) as resp:
        html = resp.read().decode("utf-8", errors="replace")
        with open(OUT, "w", encoding="utf-8", errors="replace") as f:
            f.write(html)
        print(len(html), "bytes (requests fallback)")
except Exception as e:
    print("Requests fallback error:", e)
