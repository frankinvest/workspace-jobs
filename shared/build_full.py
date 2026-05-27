#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import re, base64, urllib.request, json, time, sys, os, argparse, html as html_mod

_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent not in sys.path:
    sys.path.insert(0, _parent)
import markdownify as mf
from shared.network import GitHubUploader
from shared.deploy import GitHubPagesTrigger

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
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    # 精准定位正文容器，绝不波及外围 UI
    content_div = soup.find('div', class_=lambda x: x and 'ql-view' in x)
    if not content_div:
        content_div = soup.find('div', class_=lambda x: x and 'post-body' in x)

    if content_div:
        # 物理超度：砍掉所有可能误入正文的交互控件
        for unwanted in content_div.find_all(['input', 'button', 'svg', 'form']):
            unwanted.decompose()
        # 仅返回干净的正文内部 HTML
        return "".join(str(item) for item in content_div.contents)
    return ''

def extract_comments(html):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    comments = []
    # 寻找所有的顶级评论块
    comment_blocks = soup.find_all('div', class_=lambda x: x and 'py-12' in x and 'flex' in x and 'bt' in x)

    for block in comment_blocks:
        user_el = block.find('span', class_=lambda x: x and 'cup' in x and 'mr-5' in x)
        if not user_el: continue
        user = user_el.get_text(strip=True)

        time_el = block.find('span', class_=lambda x: x and 'dark-9' in x and 'fz-sm' in x)
        time_str = time_el.get_text(strip=True) if time_el else ''

        wpws = block.find_all('span', class_='wpw')
        if not wpws: continue
        # 顶级评论正文通常是第一个 wpw
        text = wpws[0].get_text(strip=True)
        if '查看图片' in block.get_text():
            text = '[图片] ' + text

        item = {'user': user, 'time': time_str, 'content': text, 'replies': []}

        # 提取楼中楼回复
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

def extract_post_body(html):
    m = re.search(r'<div class="[^"]*ql-view[^"]*">(.*?)</div>\s*<!---->', html, re.DOTALL)
    if m and len(m.group(1)) > 100: return m.group(1)
    m = re.search(r'<div class="post-body[^"]*">(.*?)</div>\s*<!---->', html, re.DOTALL)
    if m: return m.group(1)
    return ''

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
        print("[build] ❌ 致命错误：正文提取为空！触发硬熔断，拒绝将脏数据混入系统。")
        sys.exit(1)

    post_images = extract_post_images(post_body_html)
    comments = extract_comments(full_html)
    print(f"[build] innerHTML: {len(full_html)} chars | body: {len(post_body_html)} chars")

    # ── 图片处理：先清洗私有 CDN URL，再上传 ──
    # 规则：只有成功下载并上传到 GitHub 的图片才允许保留引用
    # 失败 → 替换为 [图片已失效] 占位符，严禁死链混入系统
    if post_images:
        # 第一步：脱掉 private.red-ring.cn 的 img 标签，替换为占位符
        # 这样 markdownify 不会把死链带进 Markdown
        def kill_private_img(m):
            return '[![图片已失效](https://img.shields.io/badge/图片-已失效-red?style=flat-square)]
(http://invalid/image-not-available)'
        clean_html = re.sub(
            r'<img[^>]+src="https://private\.red-ring\.cn/[^"]+"[^>]*>',
            kill_private_img,
            post_body_html,
            flags=re.IGNORECASE
        )
        print(f"[build] 私有CDN图片已替换为占位符")
    else:
        clean_html = post_body_html

    gh = GitHubUploader(token=TOKEN, repo=REPO)
    mapping = upload_images(post_images, date_str, gh) if post_images else {}

    # 只有成功上传的 URL 才做替换（替换占位符中的占位 URL）
    post_md = mf.markdownify(clean_html, heading_style="atx", link_style="inlined")
    for old_url, new_url in mapping.items():
        post_md = post_md.replace(old_url, new_url)
    if title is None: title = f"财经早餐 {display_date}"
    final_html = md_to_html_with_comments(post_md, title=title, comments=comments)
    if output_file is None: output_file = f"caijing_{date_str}.html"
    b64 = base64.b64encode(final_html.encode('utf-8')).decode('ascii')
    result = gh_put(output_file, b64, f"发布 {display_date} 财经早餐 (SSOT build)")
    print(f"[build] HTML 上传成功。")
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
        cdp_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cdp_get_innerhtml.py')
        cdp_cmd = ['python3', cdp_script, tmp_path, args.cdp_ws_url, '--auto-latest', '--group-url', args.group_url, '--selector', 'main']
        cp = subprocess.run(cdp_cmd, capture_output=True, text=True, timeout=180)
        if cp.returncode == 3: sys.exit(3)
        if cp.returncode != 0: sys.exit(1)
        args.html_file = tmp_path
        try:
            with open(tmp_path, encoding='utf-8', errors='replace') as f: content = f.read()
            s, e = content.find('POST_START'), content.find('POST_END')
            if s != -1 and e != -1: content = content[s+10:e]
            m = re.search(r'(\d{4})[年\-/:](\d{1,2})[月\-/:](\d{1,2})', content)
            if m: args.date = f"{m.group(1)}{m.group(2).zfill(2)}{m.group(3).zfill(2)}"
        except: pass
    result = build(args.html_file, args.date, args.output_file, args.title)
    print("\n✅ 完成:", json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
