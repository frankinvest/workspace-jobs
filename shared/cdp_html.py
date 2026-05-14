#!/usr/bin/env python3
"""Python 直连浏览器 CDP WebSocket"""
import websocket, json, time, threading

WS_URL = "ws://127.0.0.1:18900/devtools/page/DCDBD120E79E4B69E755CAC03E39F11F"
OUT = "/Users/frank_bot/.openclaw/workspace/pipeline_input.html"

results = {}
lock = threading.Lock()

def on_message(ws, msg):
    data = json.loads(msg)
    rid = data.get("id")
    if rid:
        with lock:
            results[rid] = data

def on_error(ws, err):
    print("WS error:", err)

def on_close(ws, *args):
    pass

def on_open(ws):
    JS = r"""
(function(){
  var m = document.querySelector("main");
  if(!m) return "";
  var c=m.cloneNode(true);
  c.querySelectorAll("[class*=comment],[class*=reply],.cmt-item,.py-12,.icon-wrap,[class*=actions],footer,.reply-wrap,.comment-body,.replies,.flex.px-15.bb.mt-12,.px-15.py-9.fz-sm").forEach(function(e){e.remove()});
  return c.innerHTML;
})()
"""
    ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": JS, "returnByValue": True}}))

ws = websocket.WebSocketApp(
    WS_URL,
    on_message=on_message,
    on_error=on_error,
    on_close=on_close
)
t = threading.Thread(target=ws.run_forever)
t.daemon = True
t.start()
time.sleep(3)
ws.close()
t.join(timeout=2)

if 1 in results:
    val = results[1]["result"]["result"]["value"]
    with open(OUT, "w", encoding="utf-8", errors="replace") as f:
        f.write(val)
    print(f"OK: {len(val)} bytes -> {OUT}")
else:
    print("TIMEOUT. Results:", list(results.keys()))
