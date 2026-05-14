#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shared/pipeline.py
富文本无损流水线：HTML(in) → Markdown → 图片URL替换 → HTML(out)
"""
import sys, os, re, base64, time, urllib.request, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.network import GitHubUploader
from shared.deploy import GitHubPagesTrigger

try:
    import markdownify as mf
    HAS_MF = True
except ImportError:
    HAS_MF = False

TOKEN = "${GITHUB_TOKEN}"
REPO = "frankinvest/caijing-daily"
REF_URL = "https://www.red-ring.cn/post/27593-2120574"
HEADERS = {
    "Cookie": "Hm_lvt_1c9949e59fafcdf8f7cd363b452f1837=1778115791,1778500926; HMACCOUNT=77046ED79FB0AFED; Hm_lpvt_1c9949e59fafcdf8f7cd363b452f1837=1778653122",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    "Referer": REF_URL
}

def html_to_markdown(html):
    if HAS_MF:
        return mf.markdownify(html, heading_style="atx", link_style="inlined")
    # 降级正则方案
    t = re.sub(r'<br\s*/?>', '\n', html)
    t = re.sub(r'<p[^>]*>', '\n\n', t)
    t = re.sub(r'<[^>]+>', '', t)
    t = re.sub(r'\n{3,}', '\n\n', t)
    return t.strip()

def extract_md_images(md):
    urls = []
    for m in re.finditer(r'!\[([^\]]*)\]\(([^)]+)', md):
        u = m.group(2)
        if u not in urls:
            urls.append(u)
    return urls

def replace_md_urls(md, old_new):
    for o, n in old_new.items():
        md = md.replace(o, n)
    return md

def md_to_html(md, title=""):
    def img_replace(m):
        alt = m.group(1) or ""
        url = m.group(2)
        return f'<img src="{url}" alt="{alt}" style="max-width:100%;border-radius:4px;margin:8px 0;display:block">'
    body = re.sub(r'!\[([^\]]*)\]\((.+?)\)', img_replace, md)
    body = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', body)
    paras = []
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith('<img ') or line.startswith('<blockquote'):
            paras.append(line)
        else:
            paras.append(f'<p>{line}</p>')
    post_body = '\n'.join(paras)
    return (
        '<!DOCTYPE html>\n<html lang="zh">\n<head>\n'
        '<meta charset="UTF-8">\n'
        '<title>' + title + '</title>\n'
        '<style>\n'
        'body{font-family:-apple-system;font-size:14px;max-width:720px;margin:0 auto;padding:16px;background:#fafafa;line-height:1.7;color:#333}\n'
        '.post{background:white;border-radius:8px;padding:20px;margin-bottom:16px}\n'
        'img{max-width:100%;border-radius:4px;margin:8px 0}\n'
        'strong{color:#c00}\n'
        '.footer{text-align:center;color:#999;font-size:.8em;padding:20px 0;border-top:1px solid #eee;margin-top:30px}\n'
        '</style>\n'
        '</head>\n<body>\n<div class="post">\n' + post_body + '\n</div>\n'
        '<div class="footer">\n<p>来源：小红圈 · 红运Dang投 · MR Dang<br>MCP-RedRing 自动生成</p>\n'
        '</div>\n</body>\n</html>'
    )

def download_and_upload_imgs(urls, date, gh):
    mapping = {}
    total = len(urls)
    for i, url in enumerate(urls, 1):
        ext = 'png' if '.png' in url else ('webp' if 'webp' in url else 'jpg')
        fname = f"caijing_{date}_img_{i:02d}.{ext}"
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=10) as r:
                if r.status != 200:
                    raise Exception(f"HTTP {r.status}")
                data = r.read()
                if len(data) < 2048:
                    raise Exception(f"文件过小({len(data)}B防盗链拒绝")
                if b'<!DOCTYPE' in data[:50]:
                    raise Exception("HTML错误页")
            b64 = base64.b64encode(data).decode('ascii')
            gurl = gh.upload(fname, b64)
            mapping[url] = gurl
            print(f"  OK {i}/{total} {fname} ({len(data)//1024}KB)")
        except Exception as e:
            print(f"  FAIL {i}/{total} {url[:60]}: {e}")
        if i < total:
            time.sleep(0.5)
    return mapping

def main():
    date = sys.argv[1] if len(sys.argv) > 1 else "20260512"
    html_path = sys.argv[2] if len(sys.argv) > 2 else None

    if not html_path or not os.path.exists(html_path):
        print("用法: python pipeline.py YYYYMMDD html_file")
        sys.exit(1)

    with open(html_path, encoding='utf-8') as f:
        raw_html = f.read()
    print(f"读入 HTML: {len(raw_html)} bytes")

    md = html_to_markdown(raw_html)
    print(f"Markdown: {len(md)} chars")

    imgs = extract_md_images(md)
    print(f"图片: {len(imgs)} 张")

    gh = GitHubUploader(token=TOKEN, repo=REPO)
    mapping = {}
    if imgs:
        mapping = download_and_upload_imgs(imgs, date, gh)
        md = replace_md_urls(md, mapping)

    final_html = md_to_html(md, title=f"财经早餐 {date}")
    gh_count = final_html.count('raw.githubusercontent.com')
    print(f"生成 HTML: {len(final_html)} bytes, GitHub图: {gh_count} 张")

    path = f"caijing_{date}.html"
    b64 = base64.b64encode(final_html.encode('utf-8')).decode('ascii')
    api = f"https://api.github.com/repos/{REPO}/contents/{path}"
    greq = urllib.request.Request(api + "?ref=main", headers={"Authorization": "token " + TOKEN})
    sha = None
    try:
        with urllib.request.urlopen(greq, timeout=10) as r:
            sha = json.loads(r.read()).get('sha')
    except Exception:
        pass
    body = {"message": f"Update {path}", "content": b64, "branch": "main"}
    if sha:
        body["sha"] = sha
    req2 = urllib.request.Request(
        api, data=json.dumps(body).encode('utf-8'),
        headers={"Authorization": "token " + TOKEN, "Content-Type": "application/json"},
        method="PUT"
    )
    with urllib.request.urlopen(req2, timeout=15) as r:
        res = json.loads(r.read())
    print("上传:", res.get('content', {}).get('download_url', '')[:80])

    ok = GitHubPagesTrigger(token=TOKEN, repo=REPO).trigger_and_wait()
    print("完成" if ok else "超时",
          f"https://frankinvest.github.io/caijing-daily/{path}")

if __name__ == "__main__":
    main()
