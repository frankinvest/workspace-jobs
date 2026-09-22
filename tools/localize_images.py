#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""localize_images.py — 把文章里的红圈图片下载到本站（原图本地化）

背景（Frank 2026-09-22）：文章里的图片是红圈的**7 天签名链接**，过期就 403，
所以要把图片下载进仓库、md 改成站内路径，永久可用。

规则
  - 每篇一个目录：public/images/JJC-<YYYYMMDD>/
  - 文件名按正文出现顺序：img-01.jpg / img-02.png …（扩展名取响应 Content-Type）
  - md 里 `![](https://private.red-ring.cn/...)` 与 `<img src="...">` 都改成站内路径
  - 改完该 md 里 `private.red-ring.cn` 计数必须为 0（硬校验）
  - 幂等：目录文件数已齐 + md 已无外链 → 跳过
  - 进度写 /tmp/img_backfill_progress.json

用法
  python3 tools/localize_images.py --date 20260922                 # 单篇（不推）
  python3 tools/localize_images.py --date 20260922 --push          # 单篇 + 推送
  python3 tools/localize_images.py --since 20260624 --limit 5 --push
  python3 tools/localize_images.py --since 20260624 --push         # 批量
"""
import argparse
import datetime
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests
import urllib.request

try:                                    # CDP 依赖（本地已装 websocket-client）
    import websocket
except Exception:                       # noqa: BLE001
    websocket = None

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
IMG_ROOT = ROOT / "public" / "images"
PUSHER = ROOT / "tools" / "system_api_pusher.py"
PROGRESS = Path("/tmp/img_backfill_progress.json")

UA = "Mozilla/5.0 (FrankPortfolio)"
HEADERS = {"User-Agent": UA, "Referer": "https://www.red-ring.cn/"}
MD_RE = re.compile(r"!\[[^\]]*\]\((https?://private\.red-ring\.cn/[^)\s]+)\)")
HTML_RE = re.compile(r'<img[^>]+src="(https?://private\.red-ring\.cn/[^"]+)"')
EXT = {"image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png",
       "image/webp": ".webp", "image/gif": ".gif"}

CDP = "http://127.0.0.1:18900"
GROUP_URL = "https://www.red-ring.cn/group/27593"


# ── CDP：拿历史帖子的「新签名」图片 URL ─────────────────────────
def _cdp_page():
    tabs = json.loads(urllib.request.urlopen(f"{CDP}/json/list", timeout=5).read())
    for t in tabs:
        if t.get("type") == "page" and "red-ring" in t.get("url", ""):
            return t["webSocketDebuggerUrl"]
    for t in tabs:
        if t.get("type") == "page" and "chrome://" not in t.get("url", ""):
            return t["webSocketDebuggerUrl"]
    raise RuntimeError("找不到可用的红圈标签页")


class Cdp:
    def __init__(self):
        if websocket is None:
            raise RuntimeError("缺少 websocket-client，无法用 CDP")
        self.ws = websocket.create_connection(_cdp_page(), suppress_origin=True, timeout=25)
        self.i = 0

    def ev(self, expr, timeout=25):
        self.i += 1
        self.ws.send(json.dumps({"id": self.i, "method": "Runtime.evaluate",
                                 "params": {"expression": expr, "returnByValue": True}}))
        while True:
            m = json.loads(self.ws.recv())
            if m.get("id") == self.i:
                res = m.get("result", {}).get("result", {}) or {}
                return res.get("value")

    def goto(self, url, wait=6):
        self.ev(f"location.href={json.dumps(url)}")
        time.sleep(wait)

    def scroll_bottom(self, times=1, wait=1.5):
        for _ in range(times):
            self.ev("window.scrollTo(0, document.body.scrollHeight); 'ok'")
            time.sleep(wait)

    def close(self):
        try:
            self.ws.close()
        except Exception:               # noqa: BLE001
            pass


ENTRY_JS = """JSON.stringify([...document.querySelectorAll('a[href*="/post/"]')].map(a => {
  let el = a, label = '';
  for (let i = 0; i < 6 && el; i++) {
    const lines = (el.innerText || '').split('\\n').map(s => s.trim()).filter(Boolean);
    const hit = lines.find(x => /^(今天|昨天|前天|\\d{1,2}\\/\\d{1,2})(\\s+\\d{2}:\\d{2})?$/.test(x));
    if (hit) { label = hit.split(' ')[0]; break; }
    el = el.parentElement;
  }
  return { label: label, href: a.href };
}))"""


def build_post_index(cdp, max_scrolls=120):
    """滚动圈子列表，返回 {'YYYYMMDD': [post_href, ...]}（新→旧）"""
    cdp.goto(GROUP_URL, wait=8)
    seen, order = {}, []
    today = datetime.date.today()
    for _ in range(max_scrolls):
        raw = cdp.ev(ENTRY_JS) or "[]"
        try:
            entries = json.loads(raw)
        except Exception:               # noqa: BLE001
            entries = []
        new = 0
        for e in entries:
            href, label = e.get("href"), e.get("label")
            if not href or not label or href in seen:
                continue
            seen[href] = True
            new += 1
            d = None
            if label == "今天":
                d = today
            elif label == "昨天":
                d = today - datetime.timedelta(days=1)
            elif label == "前天":
                d = today - datetime.timedelta(days=2)
            elif "/" in label:
                mm, dd = label.split("/")
                try:
                    d = datetime.date(today.year, int(mm), int(dd))
                except ValueError:
                    d = None
            if d:
                order.append((d.strftime("%Y%m%d"), href))
        idx = {}
        for date_str, href in order:
            idx.setdefault(date_str, []).append(href)
        if new == 0:                    # 滚不动了
            break
        cdp.scroll_bottom(1, 1.2)
    return idx


POST_IMG_JS = """JSON.stringify([...document.querySelectorAll('.post-body img, main img')].map(i => i.src).filter(Boolean))"""


HOOK_JS = """
window.__cap = [];
(function(){
  const _open = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function(m,u){ this.__u=u; return _open.apply(this, arguments); };
  const _h = XMLHttpRequest.prototype.setRequestHeader;
  XMLHttpRequest.prototype.setRequestHeader = function(k,v){
    if ((this.__u||'').includes('content/list')) window.__cap.push({k:k, v:String(v)});
    return _h.apply(this, arguments);
  };
})();
"""


def api_token(cdp):
    """页面自己请求时带的 access_token（跟 localStorage 里那个不是同一个值，必须抓请求头）"""
    cdp.ev(f"window.__cap = window.__cap || [];")
    cdp.i += 1
    cdp.ws.send(json.dumps({"id": cdp.i, "method": "Page.enable"}))
    cdp.i += 1
    cdp.ws.send(json.dumps({"id": cdp.i, "method": "Page.addScriptToEvaluateOnNewDocument",
                            "params": {"source": HOOK_JS}}))
    cdp.goto(GROUP_URL, wait=12)
    caps = json.loads(cdp.ev("JSON.stringify(window.__cap||[])") or "[]")
    tok = next((c["v"] for c in caps if c.get("k", "").lower() == "access_token"), None)
    return tok


def api_post_index(cdp, token, max_pages=8):
    """用红圈列表 API 拉全部帖子 → {'YYYYMMDD': [post_url, ...]}（新→旧）"""
    idx, tz = {}, datetime.timezone(datetime.timedelta(hours=8))
    last_time = ""
    for page in range(1, max_pages + 1):
        extra = f"&lastTime={last_time}" if last_time else ""
        js = f"""(async () => {{
          const r = await fetch('https://api.redringvip.com/api/content/list/get?gid=27593&plateId=1&type=1&index={page}&pageSize=20{extra}',
            {{credentials:'include', headers:{{'access_token':{json.dumps(token)},'accesstoken':{json.dumps(token)},
              'apiVersion':'11','Accept':'application/json, text/plain, */*'}}}});
          const j = await r.json();
          if (String(j.status) !== '1') return JSON.stringify({{err: String(j.status), info: j.info}});
          const d = JSON.parse(j.data || '{{}}');
          return JSON.stringify({{page: d.page, list: (d.list||[]).map(x => ({{id: x.cid, t: x.time || x.lastTime}}))}});
        }})()"""
        cdp.i += 1
        cdp.ws.send(json.dumps({"id": cdp.i, "method": "Runtime.evaluate",
                                "params": {"expression": js, "awaitPromise": True, "returnByValue": True}}))
        raw = None
        while True:
            m = json.loads(cdp.ws.recv())
            if m.get("id") == cdp.i:
                raw = (m.get("result", {}).get("result", {}) or {}).get("value")
                break
        try:
            data = json.loads(raw or "{}")
        except Exception:               # noqa: BLE001
            log(f"  ! 第 {page} 页返回无法解析: {str(raw)[:120]}")
            break
        if data.get("err"):
            log(f"  ! API 第 {page} 页返回 {data.get('err')} {data.get('info')}")
            break
        items = data.get("list") or []
        if not items:
            break
        log(f"    API 第 {page} 页：{len(items)} 条")
        for it in items:
            if not it.get("id") or not it.get("t"):
                continue
            d = datetime.datetime.fromtimestamp(int(it["t"]), tz).strftime("%Y%m%d")
            idx.setdefault(d, []).append(f"https://www.red-ring.cn/post/27593-{it['id']}")
        last_time = str(items[-1].get("t") or "")
    return idx


def fresh_urls_for_post(cdp, href):
    """打开帖子，返回 {资源路径: 新签名 URL}（资源路径 = 去掉 ?query 的部分）"""
    cdp.goto(href, wait=6)
    urls = json.loads(cdp.ev(POST_IMG_JS) or "[]")
    out = {}
    for u in urls:
        out.setdefault(urlsplit(u).path, u)
    return out


def log(msg):
    print(msg, flush=True)


def load_progress():
    if PROGRESS.exists():
        try:
            return json.loads(PROGRESS.read_text())
        except Exception:
            return {}
    return {}


def save_progress(p):
    PROGRESS.write_text(json.dumps(p, ensure_ascii=False, indent=2))


def ordered_urls(text):
    """按正文出现顺序返回图片 URL（去重后保序）"""
    hits = []
    for m in MD_RE.finditer(text):
        hits.append((m.start(), m.group(1)))
    for m in HTML_RE.finditer(text):
        hits.append((m.start(), m.group(1)))
    hits.sort(key=lambda x: x[0])
    out = []
    for _, u in hits:
        if u not in out:
            out.append(u)
    return out


def download(url, dest_dir, idx, session):
    """下载单张图；返回 (文件名, 字节数, 错误)"""
    last = None
    for attempt in range(3):
        try:
            r = session.get(url, headers=HEADERS, timeout=60)
            if r.status_code == 200 and r.content:
                ext = EXT.get((r.headers.get("Content-Type") or "").split(";")[0].strip().lower(), ".jpg")
                name = f"img-{idx:02d}{ext}"
                (dest_dir / name).write_bytes(r.content)
                return name, len(r.content), None
            last = f"HTTP {r.status_code}"
            if r.status_code in (403, 404):
                break
        except Exception as e:                       # noqa: BLE001
            last = str(e)
        time.sleep(3)
    return None, 0, last


def push_file(rel):
    cp = subprocess.run(
        [sys.executable, str(PUSHER), "--file", rel,
         "--commit-msg", f"chore(images): 本地化 {rel}"],
        cwd=ROOT, capture_output=True, text=True, timeout=180)
    ok = cp.returncode == 0 and "✅" in (cp.stdout or "")
    return ok, (cp.stdout or "") + (cp.stderr or "")


def process(date_str, push=False, dry=False, cdp=None, post_index=None, md_path=None):
    md = Path(md_path) if md_path else next(iter(sorted(DOCS.glob(f"JJC-{date_str}-*.md"))), None)
    if md is None:
        return {"date": date_str, "status": "no_md"}
    # 同一天可能有多篇（001/002…）：目录名带上序号，避免图片互相覆盖
    seq = (re.search(r"JJC-\d{8}-(\d+)", md.name) or [None, "001"])[1]
    dir_name = f"JJC-{date_str}" if seq == "001" else f"JJC-{date_str}-{seq}"
    text = md.read_text(encoding="utf-8")
    urls = ordered_urls(text)
    ext_left = text.count("private.red-ring.cn")
    dest = IMG_ROOT / dir_name

    if not urls and ext_left == 0:
        return {"date": date_str, "status": "already_local", "images": 0}
    if not urls:
        return {"date": date_str, "status": "no_urls", "external_left": ext_left}

    if not dry:
        dest.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    mapping, failed = {}, {}
    for i, u in enumerate(urls, 1):
        if dry:
            log(f"  [dry] {i:02d} {u[:90]}")
            continue
        name, size, err = download(u, dest, i, session)
        if name:
            mapping[u] = f"/images/{dir_name}/{name}"
            log(f"  ✓ {name} {size/1024:.0f}KB")
        else:
            failed[i] = {"url": u, "error": err}
            log(f"  ✗ {i:02d} 失败: {err}")

    # 过期（403）的图：用 CDP 打开对应帖子拿新签名再下
    if failed and cdp is not None and post_index:
        cands = post_index.get(date_str, [])
        best = None
        for href in cands[:4]:
            try:
                fresh = fresh_urls_for_post(cdp, href)
            except Exception as e:      # noqa: BLE001
                log(f"  ! CDP 打开 {href} 失败: {e}")
                continue
            hit = sum(1 for it in failed.values() if urlsplit(it["url"]).path in fresh)
            if hit and (best is None or hit > best[0]):
                best = (hit, fresh, href)
            if best and best[0] == len(failed):
                break
        if best:
            hit, fresh, href = best
            log(f"  ↻ CDP 命中 {hit}/{len(failed)} 张（帖子 {href}）")
            for i, it in list(failed.items()):
                nu = fresh.get(urlsplit(it["url"]).path)
                if not nu:
                    continue
                name, size, err = download(nu, dest, i, session)
                if name:
                    mapping[it["url"]] = f"/images/{dir_name}/{name}"
                    failed.pop(i)
                    log(f"  ✓(新签名) {name} {size/1024:.0f}KB")
                else:
                    it["error"] = f"{err} (新签名也失败)"
        else:
            log("  ! CDP 没能命中这批图片（帖子没找到 / 候选不匹配）")

    if dry:
        return {"date": date_str, "status": "dry_run", "would_download": len(urls)}

    if failed:
        return {"date": date_str, "status": "partial", "images": len(mapping),
                "failed": list(failed.values())}

    new_text = text
    for u, local in mapping.items():
        new_text = new_text.replace(u, local)
    left = new_text.count("private.red-ring.cn")
    if left:
        return {"date": date_str, "status": "rewrite_incomplete", "external_left": left,
                "images": len(mapping)}
    md.write_text(new_text, encoding="utf-8")

    pushed = None
    if push:
        ok_md, out_md = push_file(f"docs/{md.name}")
        pushed = ok_md
        log(f"  push md: {'ok' if ok_md else 'FAIL'}")
        for name in sorted(p.name for p in dest.glob("img-*")):
            ok_img, out_img = push_file(f"public/images/{dir_name}/{name}")
            if not ok_img:
                pushed = False
                log(f"  push {name}: FAIL {out_img[-200:]}")
    return {"date": date_str, "status": "done", "images": len(mapping), "pushed": pushed}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--since")
    ap.add_argument("--until", default="29991231")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--cdp", action="store_true",
                    help="允许用 CDP（登录态）打开历史帖子拿新签名，处理已过期的图片")
    args = ap.parse_args()

    if args.date:
        targets = [(args.date, str(p)) for p in sorted(DOCS.glob(f"JJC-{args.date}-*.md"))] or [(args.date, None)]
    else:
        if not args.since:
            ap.error("需要 --date 或 --since")
        targets = []
        for p in sorted(DOCS.glob("JJC-2026*.md")):
            m = re.search(r"JJC-(\d{8})", p.name)
            if m and args.since <= m.group(1) <= args.until:
                targets.append((m.group(1), str(p)))
        if args.limit:
            targets = targets[: args.limit]

    cdp, post_index = None, None
    if args.cdp:
        cdp = Cdp()
        log("正在读取登录态并拉取帖子索引（API）…")
        token = api_token(cdp)
        if not token:
            log("! 没抓到 access_token，退回 DOM 滚动索引（覆盖范围有限）")
            post_index = build_post_index(cdp)
        else:
            post_index = api_post_index(cdp, token)
        got = sorted(post_index.keys())
        log(f"索引完成：{len(post_index)} 天，{sum(len(v) for v in post_index.values())} 条帖子"
            f"（{got[0] if got else '-'} → {got[-1] if got else '-'}）")

    progress = load_progress()
    ok = fail = 0
    for d, md_path in targets:
        log(f"[{d}] 处理中…")
        res = process(d, push=args.push, dry=args.dry_run, cdp=cdp, post_index=post_index, md_path=md_path)
        res["md"] = Path(md_path).name if md_path else None
        progress[res["md"] or d] = res
        save_progress(progress)
        status = res.get("status")
        log(f"[{d}] → {status} " + json.dumps({k: v for k, v in res.items() if k not in ('status',)}, ensure_ascii=False)[:200])
        if status in ("done", "already_local"):
            ok += 1
        else:
            fail += 1
    log(f"\n合计: 成功 {ok} / 失败 {fail} / 共 {len(targets)}")
    if cdp:
        cdp.close()
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
