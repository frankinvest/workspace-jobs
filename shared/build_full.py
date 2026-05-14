#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_full.py — SSOT 渲染引擎
用法:
    python3 build_full.py <innerhtml_file> <date_YYYYMMDD> [output_file] [title]
示例:
    python3 build_full.py /tmp/may13_post.html 20260513
    python3 build_full.py /tmp/may13_post.html 20260513 caijing_20260513.html "财经早餐 20260513"
"""
import re, base64, urllib.request, json, time, sys, os, argparse, html as html_mod

_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent not in sys.path:
    sys.path.insert(0, _parent)
import markdownify as mf
from shared.network import GitHubUploader
from shared.deploy import GitHubPagesTrigger

TOKEN = "${GITHUB_TOKEN}"
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
    ap = argparse.ArgumentParser(description='SSOT 渲染引擎 - 从 innerHTML 生成财经早餐 HTML')
    ap.add_argument('html_file', help='innerHTML 文件路径（来自 cdp_get_innerhtml.py）')
    ap.add_argument('date', help='日期 YYYYMMDD，如 20260513')
    ap.add_argument('output_file', nargs='?', default=None,
                    help='输出 HTML 文件名，如 caijing_20260513.html（默认: caijing_{date}.html）')
    ap.add_argument('--title', '-t', default=None, help='页面标题（默认: 财经早餐 YYYY-MM-DD）')
    args = ap.parse_args()

    result = build(
        html_file=args.html_file,
        date=args.date,
        output_file=args.output_file,
        title=args.title
    )
    print("\n✅ 完成:", json.dumps(result, ensure_ascii=False))

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
