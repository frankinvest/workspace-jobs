#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
migrate_batch.py — workspace-jobs 历史文章迁移
CDP 直接抓取 → 脱壳清洗 → 上传图片到 workspace-jobs → 写 docs/ → git push

单篇用法：
  python3 migrate_batch.py \
    --post https://www.red-ring.cn/post/27593-2190349 \
    --cdp-ws ws://127.0.0.1:18900/devtools/page/9A6EE8344223B1E0D9B178FFA26031EC
"""
import sys, os, re, base64, time, datetime, json, argparse, html as html_mod
import subprocess, urllib.request, websocket

WORKSPACE_DIR = "/tmp/workspace-jobs"
DOCS_DIR = "docs"

# ── Token & Cookies ──────────────────────────────────────────────
def load_token():
    p = "/Users/frank_bot/.openclaw/workspace/shared/auth/github_token.txt"
    if os.path.exists(p):
        t = open(p).read().strip()
        if t: return t
    t = os.environ.get("GITHUB_TOKEN", "").strip()
    if t: return t
    raise ValueError("No GitHub token")

def load_redring_cookies():
    p = "/Users/frank_bot/.openclaw/workspace/shared/auth/redring_cookies.json"
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return {}

TOKEN = load_token()
RR_COOKIES = load_redring_cookies()
IMG_HEADERS = {
    "User-Agent": RR_COOKIES.get("User-Agent", "Mozilla/5.0"),
    "Cookie": RR_COOKIES.get("Cookie", ""),
    "Referer": RR_COOKIES.get("Referer", "https://www.red-ring.cn/"),
}

# ── 脱壳清洗 ──────────────────────────────────────────────
def strip_shell(html):
    """彻底剥离 style/script/background/color，保留纯净结构"""
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL|re.IGNORECASE)
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL|re.IGNORECASE)
    def clean_style(m):
        keep = [s.strip() for s in m.group(1).split(';')
                if (s.strip().lower()
                    and 'background' not in s.lower()
                    and 'color:' not in s.lower()
                    and not s.lower().strip().startswith('color'))]
        v = ';'.join(keep)
        return ('style="' + v + '"') if v else ''
    html = re.sub(r'style="([^"]*)"', clean_style, html)
    html = re.sub(r'<!DOCTYPE[^>]*>', '', html, flags=re.IGNORECASE)
    html = re.sub(r'<html[^>]*>', '', html, flags=re.IGNORECASE)
    html = re.sub(r'</html[^>]*>', '', html, flags=re.IGNORECASE)
    html = re.sub(r'<head[^>]*>.*?</head>', '', html, flags=re.DOTALL|re.IGNORECASE)
    html = re.sub(r'\n{3,}', '\n\n', html).strip()
    return html

# ── 日期提取 ──────────────────────────────────────────────
def extract_date(html):
    m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', html)
    if m:
        return f"{m.group(1)}{int(m.group(2)):02d}{int(m.group(3)):02d}"
    return None

# ── 图片上传到 workspace-jobs ─────────────────────────────────
def gh_put_file(repo, path, content_b64, msg):
    api = f"https://api.github.com/repos/{repo}/contents/{path}"
    payload = {"message": msg, "content": content_b64, "branch": "main"}
    try:
        greq = urllib.request.Request(api + "?ref=main",
            headers={"Authorization": "token " + TOKEN})
        with urllib.request.urlopen(greq, timeout=8) as r:
            existing = json.loads(r.read())
            if existing.get('sha'):
                payload["sha"] = existing['sha']
    except:
        pass
    req = urllib.request.Request(api, data=json.dumps(payload).encode(),
        headers={"Authorization": "token " + TOKEN, "Content-Type": "application/json"},
        method="PUT")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

def upload_img(img_url, date_str, idx):
    try:
        req = urllib.request.Request(img_url, headers=IMG_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read()
        ct = r.headers.get('Content-Type', '')
        ext = ct.split('/')[-1].split(';')[0]
        if ext == 'jpeg': ext = 'jpg'
        fname = f"caijing_{date_str}_img_{idx:02d}.{ext}"
        b64 = base64.b64encode(data).decode('ascii')
        gh_put_file("frankinvest/workspace-jobs", f"images/{fname}", b64,
                     f"upload {fname}")
        new_url = f"https://raw.githubusercontent.com/frankinvest/workspace-jobs/main/images/{fname}"
        print(f"    {idx}: {img_url[:60]}... → {new_url[:60]}...")
        return new_url
    except Exception as e:
        print(f"    [IMG] 上传失败 [{img_url[:60]}]: {e}")
        return img_url

# ── Git push ──────────────────────────────────────────────
def git_push(date_str):
    try:
        sub = lambda cmd: subprocess.run(cmd, cwd=WORKSPACE_DIR,
                                        check=True, capture_output=True, timeout=30)
        sub(["git", "add", f"{DOCS_DIR}/caijing-{date_str}.html"])
        date_fmt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        sub(["git", "commit", "-m", f"docs: 财经早餐 {date_fmt}"])
        # 先 pull --rebase 避免远程冲突
        try:
            subprocess.run(["git", "pull", "--rebase", "origin", "main"],
                          cwd=WORKSPACE_DIR, capture_output=True, timeout=30)
        except:
            pass
        r = subprocess.run(["git", "push", "origin", "main"],
                          cwd=WORKSPACE_DIR, capture_output=True, timeout=30)
        if r.returncode != 0:
            print(f"  [GIT] Push 失败: {r.stderr.decode()[:100]}")
            return False
        return True
    except subprocess.CalledProcessError as e:
        print(f"  [GIT] Error: {e.stderr.decode() if e.stderr else e}")
        return False

# ── CDP 提取 ──────────────────────────────────────────────
def fetch_via_cdp(post_url, cdp_ws_url):
    """用 CDP 直接抓取帖子 HTML"""
    try:
        ws = websocket.create_connection(cdp_ws_url, suppress_origin=True, timeout=15)
    except Exception as e:
        print(f"  [CDP] 连接失败: {e}")
        return None

    try:
        ws.send(json.dumps({"id": 1, "method": "Page.navigate",
                          "params": {"url": post_url}}))
        ws.recv()
        time.sleep(3)

        ws.send(json.dumps({"id": 2, "method": "Runtime.evaluate",
                          "params": {"expression": """
            (function(){
                var main = document.querySelector('main') || document.body;
                return main.innerHTML;
            })()
          """, "returnByValue": True}}))
        resp = json.loads(ws.recv())
        html = resp.get('result', {}).get('result', {}).get('value', '') or ''
    finally:
        ws.close()

    return html if html and len(html) > 200 else None

# ── 主处理函数 ──────────────────────────────────────────────
def process_one(post_url, cdp_ws_url):
    print(f"\n[PROC] {post_url}")

    # 1. CDP 抓取
    html = fetch_via_cdp(post_url, cdp_ws_url)
    if not html:
        print(f"  [FAIL] CDP 抓取失败")
        return None

    print(f"  [CDP] 获取 {len(html)} chars")

    # 2. 提取日期
    date_str = extract_date(html)
    if not date_str:
        print(f"  [FAIL] 无法从 HTML 提取日期")
        return None
    date_fmt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    print(f"  [DATE] {date_fmt}")

    # 3. HTML entity 解码（&amp; → &，使 URL 可被 urllib 正确识别）
    html = html_mod.unescape(html)

    # 4. 替换私有图片 URL
    private_imgs = re.findall(r'<img[^>]+src="(https://private\.red-ring\.cn/[^\s"]+)"', html)
    public_imgs = re.findall(r'<img[^>]+src="(https://public\.red-ring\.cn/[^\s"]+)"', html)
    all_imgs = private_imgs + public_imgs
    print(f"  [IMG] 私有图片 {len(private_imgs)} 张，公共图片 {len(public_imgs)} 张")

    url_map = {}
    for i, url in enumerate(all_imgs):
        new_url = upload_img(url, date_str, i + 1)
        if new_url != url:
            print(f"    {i+1}: 替换 {url[:50]}...")
            html = html.replace(f'src="{url}"', f'src="{new_url}"')

    # 4. 脱壳
    clean_html = strip_shell(html)
    if not clean_html or len(clean_html) < 50:
        print(f"  [SKIP] 脱壳后内容太短")
        return None
    print(f"  [STRIP] 剩余 {len(clean_html)} chars")

    # 5. 写入 docs/
    out_path = f"{WORKSPACE_DIR}/{DOCS_DIR}/caijing-{date_str}.html"
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(clean_html)
    print(f"  [WRITE] → {out_path}")

    # 6. Git push
    ok = git_push(date_str)
    if ok:
        print(f"  [DONE] ✅ {date_fmt}")
    else:
        print(f"  [FAIL] ❌ {date_fmt}")
    return date_str if ok else None

# ── 入口 ─────────────────────────────────────────────────────
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description='workspace-jobs 历史文章迁移')
    ap.add_argument('--post', required=True, help='帖子 URL')
    ap.add_argument('--cdp-ws', required=True, dest='ws_url', help='CDP WebSocket URL')
    args = ap.parse_args()

    result = process_one(args.post, args.ws_url)
    if result:
        print(f"\n🎉 完成: {result}")
    else:
        print(f"\n❌ 失败")
        sys.exit(1)
