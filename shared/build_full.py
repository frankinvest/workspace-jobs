#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import re, base64, urllib.request, json, time, sys, os, argparse, html as html_mod

_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent not in sys.path:
    sys.path.insert(0, _parent)
import markdownify as mf
from shared.network import GitHubUploader
from shared.deploy import GitHubPagesTrigger
from bs4 import BeautifulSoup

_GH_TOKEN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'auth', 'github_token.txt')

def _load_github_token():
    if os.path.exists(_GH_TOKEN_PATH):
        with open(_GH_TOKEN_PATH, 'r', encoding='utf-8') as f:
            token = f.read().strip()
            if token: return token
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token: return token
    raise ValueError("[AUTH] FAIL: 找不到 GitHub Token。")

TOKEN = _load_github_token()
REPO = "frankinvest/caijing-daily"
_AUTH_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'auth', 'redring_cookies.json')

def get_headers():
    if not os.path.exists(_AUTH_PATH): raise FileNotFoundError(f"[AUTH] FAIL: 鉴权文件不存在: {_AUTH_PATH}")
    with open(_AUTH_PATH, encoding='utf-8') as f: cfg = json.load(f)
    if not cfg.get('Cookie'): raise ValueError("[AUTH] FAIL: Cookie为空")
    return {k: cfg[k] for k in ('Cookie', 'User-Agent', 'Referer', 'Accept', 'Accept-Language') if cfg.get(k)}

def extract_post_body(html):
    soup = BeautifulSoup(html, 'html.parser')
    content_div = soup.find('div', class_=lambda x: x and 'ql-view' in x)
    if not content_div:
        content_div = soup.find('div', class_=lambda x: x and 'post-body' in x)
    if content_div:
        for unwanted in content_div.find_all(['input', 'button', 'svg', 'form']):
            unwanted.decompose()
        return "".join(str(item) for item in content_div.contents)
    return ''

def extract_comments(html):
    soup = BeautifulSoup(html, 'html.parser')
    comments = []
    comment_blocks = soup.find_all('div', class_=lambda x: x and 'py-12' in x and 'flex' in x and 'bt' in x)
    for block in comment_blocks:
        user_el = block.find('span', class_=lambda x: x and 'cup' in x and 'mr-5' in x)
        if not user_el: continue
        user = user_el.get_text(strip=True)
        time_el = block.find('span', class_=lambda x: x and 'dark-9' in x and 'fz-sm' in x)
        time_str = time_el.get_text(strip=True) if time_el else ''
        wpws = block.find_all('span', class_='wpw')
        if not wpws: continue
        text = wpws[0].get_text(strip=True)
        if '查看图片' in block.get_text():
            text = '[图片] ' + text
        item = {'user': user, 'time': time_str, 'content': text, 'replies': []}
        bgc = block.find('div', class_=lambda x: x and 'bgc-body' in x)
        if bgc:
            for reply_div in bgc.find_all('div', class_=lambda x: x and 'tools-v-trigger' in x):
                r_user = reply_div.find('span', class_=lambda x: x and 'c-primary' in x and 'cup' in x)
                r_text = reply_div.find('span', class_='wpw')
                if r_user and r_text:
                    item['replies'].append({
                        'user': r_user.get_text(strip=True),
                        'content': r_text.get_text(strip=True)
                    })
        comments.append(item)
    return comments

def extract_post_images(post_html):
    seen, imgs = set(), []
    for m in re.finditer(r'<img[^>]+src="([^"]+)"', post_html):
        url = m.group(1)
        if 'private.red-ring.cn' in url and url not in seen:
            seen.add(url)
            imgs.append(url)
    return imgs

def upload_images(urls, date, gh):
    mapping, total = {}, len(urls)
    for i, url in enumerate(urls, 1):
        ext = 'png' if '.png' in url else ('webp' if 'webp' in url else 'jpg')
        fname = f"caijing_{date}_img_{i:02d}.{ext}"
        gh_path = f"images/{date}/{fname}"
        try:
            req = urllib.request.Request(url, headers=get_headers())
            with urllib.request.urlopen(req, timeout=15) as r:
                if r.status != 200: raise Exception(f"HTTP {r.status}")
                data = r.read()
                if len(data) < 2048: raise Exception("Too small")
                b64 = base64.b64encode(data).decode('ascii')
                mapping[url] = gh.upload(gh_path, b64)
                print(f"  [OK] {i}/{total} {fname}")
        except Exception as e:
            print(f"  [FAIL] {i}/{total} {url[:60]} -> {e}")
        time.sleep(0.5)
    return mapping

def _render_comments_html(comments):
    if not comments: return '<p style="color:#999;text-align:center">暂无评论</p>'
    parts = []
    for c in comments:
        reply_parts = ['<div class="r"><span class="u">' + r['user'] + '</span>' + r['content'] + '</div>' for r in c.get('replies', [])]
        parts.append('<div class="cmt-item"><div><span class="u">' + c['user'] + '</span> <span class="t">' + c['time'] + '</span></div><div style="margin-top:4px">' + c['content'] + '</div>' + ''.join(reply_parts) + '</div>')
    return '\n'.join(parts)

def md_to_html_with_comments(md_str, title, comments):
    def img_replace(m):
        src, alt = m.group(2), m.group(1)
        return f'<img src="{src}" alt="{alt}" loading="lazy">'
    body = re.sub(r'!\[([^\]]*)\]\((.+?)\)', img_replace, md_str)
    body = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', body)
    paras = []
    for line in body.splitlines():
        line = line.strip()
        if not line: continue
        if line.startswith('<img ') or line.startswith('<blockquote'): paras.append(line)
        elif line.startswith('---') or line.startswith('<hr'): paras.append('<hr class="divider">')
        else: paras.append(f'<p>{line}</p>')
    post_body_html = '\n'.join(paras)
    cmt_html = _render_comments_html(comments)
    import re as regex
    clean_post = regex.sub(r'\s*style="[^"]*"', '', post_body_html)
    clean_cmt = regex.sub(r'\s*style="[^"]*"', '', cmt_html)
    return f'<div class="post">\n{clean_post}\n</div>\n<div class="cmt-wrap">\n<h2>💬 评论区</h2>\n{clean_cmt}\n</div>\n'

def gh_put(path, content_b64, msg, branch="main"):
    api = f"https://api.github.com/repos/{REPO}/contents/{path}"
    payload = {"message": msg, "content": content_b64, "branch": branch}
    try:
        greq = urllib.request.Request(api + "?ref=" + branch, headers={"Authorization": "token " + TOKEN})
        with urllib.request.urlopen(greq, timeout=8) as r:
            payload["sha"] = json.loads(r.read()).get('sha')
    except: pass
    req = urllib.request.Request(api, data=json.dumps(payload).encode(), headers={"Authorization": "token " + TOKEN, "Content-Type": "application/json"}, method="PUT")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

def build(html_file, date, output_file=None, title=None):
    date_str = date
    display_date = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    with open(html_file, encoding='utf-8', errors='replace') as f: full_html = f.read()
    s, e = full_html.find('POST_START'), full_html.find('POST_END')
    if s != -1 and e != -1: full_html = full_html[s+10:e]
    full_html = html_mod.unescape(full_html)
    post_body_html = extract_post_body(full_html)

    if not post_body_html.strip():
        print("[build] \u274c \u5373\u65f6\u505c\u6b62\uff1a\u6b63\u6587\u63d0\u53d6\u4e3a\u7a7a\uff01\u89e6\u53d1\u786c\u7106\u65ad\uff0c\u62d2\u7edd\u5c06\u810f\u6570\u636e\u6df7\u5165\u7cfb\u7edf\u3002")
        sys.exit(1)

    post_images = extract_post_images(post_body_html)
    comments = extract_comments(full_html)
    print(f"[build] innerHTML: {len(full_html)} chars | body: {len(post_body_html)} chars")
    gh = GitHubUploader(token=TOKEN, repo=REPO)
    mapping = upload_images(post_images, date_str, gh) if post_images else {}
    post_md = mf.markdownify(post_body_html, heading_style="atx", link_style="inlined")
    for old_url, new_url in mapping.items(): post_md = post_md.replace(old_url, new_url)
    if title is None: title = f"\u8d22\u7ecf\u65e9\u9910 {display_date}"
    final_html = md_to_html_with_comments(post_md, title=title, comments=comments)
    if output_file is None: output_file = f"caijing_{date_str}.html"
    b64 = base64.b64encode(final_html.encode('utf-8')).decode('ascii')
    result = gh_put(output_file, b64, f"\u53d1\u5e03 {display_date} \u8d22\u7ecf\u65e9\u9910 (SSOT build)")
    print(f"[build] HTML \u4e0a\u4f20\u6210\u529f\u3002")
    return {"html_file": output_file, "images": len(mapping), "comments": len(comments)}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('html_file')
    ap.add_argument('date', nargs='?', default=None)
    ap.add_argument('output_file', nargs='?', default=None)
    ap.add_argument('--title', '-t', default=None)
    ap.add_argument('--auto-latest', action='store_true')
    ap.add_argument('--group-url', default='https://www.red-ring.cn/group/27593')
    ap.add_argument('--cdp-ws-url', default='AUTO')
    args = ap.parse_args()
    if args.html_file == 'AUTO' or args.auto_latest:
        import subprocess, tempfile
        tmp_path = tempfile.NamedTemporaryFile(suffix='_post.html', delete=False, mode='w').name
        cdp_cmd = ['python3', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cdp_get_innerhtml.py'), tmp_path, args.cdp_ws_url, '--auto-latest', '--group-url', args.group_url, '--selector', 'main']
        cp = subprocess.run(cdp_cmd, capture_output=True, text=True, timeout=180)
        if cp.returncode == 3: sys.exit(3)
        if cp.returncode != 0: sys.exit(1)
        args.html_file = tmp_path
        try:
            with open(tmp_path, encoding='utf-8', errors='replace') as f: content = f.read()[f.read().find('POST_START')+10:f.read().find('POST_END')]
            m = re.search(r'(\d{4})[年\-/:](\d{1,2})[月\-/:](\d{1,2})', content)
            if m: args.date = f"{m.group(1)}{m.group(2).zfill(2)}{m.group(3).zfill(2)}"
        except: pass
    result = build(args.html_file, args.date, args.output_file, args.title)
    print("\n\u2705 \u5b8c\u6210:", json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
