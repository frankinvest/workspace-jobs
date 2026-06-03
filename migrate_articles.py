#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
migrate_articles.py — workspace-jobs 专用文章迁移脚本
功能：
  1. 滚动加载圈子页面，收集所有历史帖子 URL
  2. 对每篇帖子执行：提取 innerHTML → 脱壳清洗 → 上传图片 → 写入 docs/
  3. 每篇独立 git commit + push
用法：
  python3 migrate_articles.py --start 20260501 --end 20260526 --cdp-ws ws://127.0.0.1:18900/devtools/page/XXXX
"""
import re, base64, urllib.request, json, time, sys, os, argparse

WORKSPACE_REPO = "frankinvest/workspace-jobs"
IMG_DIR = "images"
DOCS_DIR = "docs"
GIT_TOKEN_PATH = os.path.expanduser("~/.ssh/id_github_token")

# ── GitHub Token ────────────────────────────────────────────────
def load_token():
    if os.path.exists(GIT_TOKEN_PATH):
        with open(GIT_TOKEN_PATH) as f:
            t = f.read().strip()
        if t:
            return t
    t = os.environ.get("GITHUB_TOKEN", "").strip()
    if t:
        return t
    raise ValueError("No GitHub token found")

TOKEN = load_token()

# ── 脱壳清洗 ────────────────────────────────────────────────
def strip_shell(html):
    """删除 <style>/<script>/行内 background+color，保留纯净 HTML 结构"""
    # 1. 删除所有 <style>...</style> 块
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
    # 2. 删除所有 <script>...</script> 块
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    # 3. 删除行内 style 中的 background 和 color
    def clean_style(match):
        styles = match.group(1)
        keep = []
        for s in styles.split(';'):
            s = s.strip().lower()
            if s and 'background' not in s and 'color:' not in s and not s.startswith('color '):
                keep.append(s)
        val = ';'.join(keep)
        return ('style="' + val + '"') if val else ''
    html = re.sub(r'style="([^"]*)"', clean_style, html)
    # 4. 删除 <!DOCTYPE> / <html> / <head> 残留
    html = re.sub(r'<!DOCTYPE[^>]*>', '', html, flags=re.IGNORECASE)
    html = re.sub(r'<html[^>]*>', '', html, flags=re.IGNORECASE)
    html = re.sub(r'</html[^>]*>', '', html, flags=re.IGNORECASE)
    html = re.sub(r'<head[^>]*>.*?</head>', '', html, flags=re.DOTALL | re.IGNORECASE)
    # 5. 清理空行
    html = re.sub(r'\n{3,}', '\n\n', html).strip()
    return html

# ── GitHub API helpers ───────────────────────────────────────
def gh_get(path, repo):
    url = f"https://api.github.com/{path}"
    req = urllib.request.Request(url, headers={"Authorization": "token " + TOKEN})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def gh_put_file(repo, path, content_b64, msg, branch="main"):
    api = f"https://api.github.com/repos/{repo}/contents/{path}"
    payload = {"message": msg, "content": content_b64, "branch": branch}
    try:
        greq = urllib.request.Request(api + "?ref=" + branch, headers={"Authorization": "token " + TOKEN})
        with urllib.request.urlopen(greq, timeout=8) as r:
            existing = json.loads(r.read())
            if existing.get('sha'):
                payload["sha"] = existing['sha']
    except:
        pass
    req = urllib.request.Request(api, data=json.dumps(payload).encode(),
        headers={"Authorization": "token " + TOKEN, "Content-Type": "application/json"}, method="PUT")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

def gh_create_commit(repo, msg, files, branch="main"):
    """files: dict{path: content_str}"""
    from urllib.parse import quote
    api = f"https://api.github.com/repos/{repo}/contents/"
    commits_api = f"https://api.github.com/repos/{repo}/git/trees"
    # Get current commit SHA
    ref = json.loads(urllib.request.urlopen(
        f"https://api.github.com/repos/{repo}/git/refs/heads/{branch}",
        headers={"Authorization": "token " + TOKEN}, timeout=10
    ).read())
    base_sha = ref['object']['sha']
    # Get current tree
    base_tree = json.loads(urllib.request.urlopen(
        f"https://api.github.com/repos/{repo}/git/commits/{base_sha}",
        headers={"Authorization": "token " + TOKEN}, timeout=10
    ).read())['tree']['sha']
    # Create new tree
    tree = [{"path": p, "mode": "100644", "type": "blob", "content": c}
            for p, c in files.items()]
    new_tree_req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/git/trees",
        data=json.dumps({"base_tree": base_tree, "tree": tree}).encode(),
        headers={"Authorization": "token " + TOKEN, "Content-Type": "application/json"},
        method="POST"
    )
    new_tree = json.loads(urllib.request.urlopen(new_tree_req, timeout=10).read())
    # Create commit
    commit_req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/git/commits",
        data=json.dumps({"message": msg, "tree": new_tree["sha"], "parents": [base_sha]}).encode(),
        headers={"Authorization": "token " + TOKEN, "Content-Type": "application/json"},
        method="POST"
    )
    new_commit = json.loads(urllib.request.urlopen(commit_req, timeout=10).read())
    # Update ref
    update_req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/git/refs/heads/{branch}",
        data=json.dumps({"sha": new_commit["sha"]}).encode(),
        headers={"Authorization": "token " + TOKEN, "Content-Type": "application/json"},
        method="POST"
    )
    urllib.request.urlopen(update_req, timeout=10)
    return new_commit

# ── 图片上传 ─────────────────────────────────────────────────
def upload_image(img_url, date_str, idx):
    """下载图片并上传到 workspace-jobs repo，返回公开 URL"""
    try:
        req = urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read()
        ext = r.headers.get('Content-Type', '').split('/')[-1]
        if not ext or ext == 'jpeg': ext = 'jpg'
        fname = f"caijing_{date_str}_img_{idx:02d}.{ext}"
        b64 = base64.b64encode(data).decode('ascii')
        path = f"{IMG_DIR}/{fname}"
        gh_put_file(WORKSPACE_REPO, path, b64, f"upload image {fname}")
        return f"https://raw.githubusercontent.com/{WORKSPACE_REPO}/main/{IMG_DIR}/{fname}"
    except Exception as e:
        print(f"  [IMG] 上传失败 {img_url}: {e}")
        return img_url  # 降级：保留原始 URL

# ── 提取 HTML 中的图片 ───────────────────────────────────────
def extract_images(html):
    return re.findall(r'<img[^>]+src="([^"]+)"', html)

# ── 主逻辑 ─────────────────────────────────────────────────
def process_article(post_url, cdp_ws_url):
    """抓取单篇文章，脱壳后写入 docs/"""
    import websocket, json as _json

    date_match = re.search(r'/post/\d+-(\d{10})', post_url)
    if not date_match:
        print(f"[SKIP] 无法从 URL 提取日期: {post_url}")
        return None
    ts = date_match.group(1)
    date_str = str(int(ts))  # 实际是10位时间戳
    # 从时间戳转日期
    import datetime
    d = datetime.datetime.fromtimestamp(int(ts))
    date_fmt = d.strftime('%Y%m%d')

    print(f"\n[PROC] {post_url} → {date_fmt}")

    # 连接 CDP
    try:
        ws = websocket.create_connection(cdp_ws_url, suppress_origin=True, timeout=15)
    except Exception as e:
        print(f"  [CDP] 连接失败: {e}")
        return None

    # 导航到帖子
    ws.send(_json.dumps({"id": 1, "method": "Page.navigate",
                          "params": {"url": post_url}}))
    ws.recv()
    time.sleep(3)

    # 提取 innerHTML
    ws.send(_json.dumps({
        "id": 2, "method": "Runtime.evaluate",
        "params": {"expression": """
            (function() {
                var el = document.querySelector('main') || document.body;
                return el.innerHTML;
            })()
        """, "returnByValue": True}
    }))
    resp = _json.loads(ws.recv())
    raw_html = resp['result']['result']['value']
    ws.close()

    if not raw_html or len(raw_html) < 100:
        print(f"  [SKIP] HTML 太短，可能是空帖")
        return None

    # 提取正文（取 <div class="post-body"> 或整个 main）
    body_match = re.search(r'<div[^>]+post-body[^>]*>(.*)</div>\s*<div[^>]+cmt',
                           raw_html, re.DOTALL)
    if body_match:
        post_body = body_match.group(1)
    else:
        # 去掉评论区
        cmt_idx = raw_html.find('class="cmt"')
        post_body = raw_html[:cmt_idx] if cmt_idx != -1 else raw_html

    # 上传图片并替换 URL
    imgs = extract_images(post_body)
    url_map = {}
    for i, url in enumerate(imgs):
        if url.startswith('https://private.red-ring.cn/') or \
           url.startswith('https://public.red-ring.cn/'):
            new_url = upload_image(url, date_fmt, i + 1)
            url_map[url] = new_url
            print(f"  [IMG] {i+1}: {url[:60]} → {new_url[:60]}")

    # 替换图片 URL
    for old, new in url_map.items():
        post_body = post_body.replace(f'src="{old}"', f'src="{new}"')

    # 脱壳
    clean = strip_shell(post_body)
    if not clean or len(clean) < 50:
        print(f"  [SKIP] 脱壳后内容太短")
        return None

    # 写入文件
    fname = f"caijing-{date_fmt}.html"
    out_path = f"/tmp/workspace-jobs/{DOCS_DIR}/{fname}"
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(clean)
    print(f"  [WRITE] {out_path} ({len(clean)} chars)")

    # Git commit + push（调用 git 命令）
    import subprocess
    repo = "/tmp/workspace-jobs"
    try:
        subprocess.run(["git", "add", f"{DOCS_DIR}/{fname}"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m",
                       f"docs: 财经早餐 {date_fmt[:4]}-{date_fmt[4:6]}-{date_fmt[6:8]}"],
                      cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=repo, check=True,
                      capture_output=True, timeout=20)
        print(f"  [GIT] Pushed ✅")
    except subprocess.CalledProcessError as e:
        print(f"  [GIT] Error: {e.stderr.decode() if e.stderr else e}")
        return None

    return date_fmt

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description='workspace-jobs 文章迁移流水线')
    ap.add_argument('--start', default='20260501', help='开始日期 YYYYMMDD')
    ap.add_argument('--end', default='20260526', help='结束日期 YYYYMMDD')
    ap.add_argument('--cdp-ws', required=True, help='CDP WebSocket URL')
    args = ap.parse_args()

    print(f"[MIGRATE] 开始迁移 {args.start} → {args.end}")
    print(f"[CDP] {args.cdp_ws}")
    print(f"[TARGET] /tmp/workspace-jobs/{DOCS_DIR}/")
