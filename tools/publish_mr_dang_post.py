#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
publish_mr_dang_post.py - 把小红圈里 MR Dang 的单篇帖子抓下来发到网站

🎯 用途: 抓 MR Dang 单篇特定文章 (收盘复盘 / 周末闲聊 / 假期见闻 等),
         生成 .md 并推 GitHub。
   与 finance_breakfast.py 不同: finance_breakfast.py 走 --auto-latest 抓最新"财经早餐";
                       publish_mr_dang_post.py 走 --url 抓指定 URL。

⚠️ 历史: cdp_get_innerhtml.py 在 MEMORY.md 已被标记"不要用" (旧 caijing-daily 时代工具)。
   本脚本是新写独立工具, 不再依赖 cdp_get_innerhtml.py。

依赖: 本机 Chrome 在 18900 端口 (openclaw profile), Frank 浏览器已登录红圈。

用法:
  python3 tools/publish_mr_dang_post.py --url https://www.red-ring.cn/post/27593-2354190
  python3 tools/publish_mr_dang_post.py --url ... --slug mr_dang_close_20260618
  python3 tools/publish_mr_dang_post.py --url ... --dry-run

输出: docs/<slug>.md (YAML frontmatter + 原文 + 评论区)
      推送后 commit message 由脚本动态生成 (标题 + 图片数 + 评论数)
"""
import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
import websocket
from bs4 import BeautifulSoup
import markdownify as mf
import html as html_mod

WORKSPACE_JOBS = Path.home() / ".openclaw" / "workspace-jobs"
DOCS_DIR = WORKSPACE_JOBS / "docs"
PUSHER = WORKSPACE_JOBS / "tools" / "system_api_pusher.py"
CDP_HTTP = "http://127.0.0.1:18900"


def shanghai_today_str():
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).strftime("%Y%m%d")


def shanghai_now_iso():
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S GMT+8")


def cdp_fetch_main_html(target_url_substring: str) -> str:
    """通过 CDP HTTP + WebSocket 拿 main.outerHTML

    1. GET /json 找含 target_url_substring 的 tab
    2. WebSocket Runtime.evaluate 拿 main.outerHTML
    """
    r = requests.get(f"{CDP_HTTP}/json", timeout=5)
    r.raise_for_status()
    tabs = r.json()
    target = None
    for t in tabs:
        url = t.get("url", "")
        if target_url_substring in url and t.get("type") == "page":
            target = t
            break
    if not target:
        raise RuntimeError(f"CDP tab not found for url substring: {target_url_substring}")

    ws_url = target["webSocketDebuggerUrl"]
    # suppress_origin=True 抑制 Origin header, 绕开 Chrome 的 --remote-allow-origins 检查
    ws = websocket.create_connection(ws_url, timeout=30, suppress_origin=True)
    ws.send(json.dumps({
        "id": 1,
        "method": "Runtime.evaluate",
        "params": {
            "expression": "document.querySelector('main').outerHTML",
            "returnByValue": True
        }
    }))
    result = json.loads(ws.recv())
    ws.close()

    if "result" not in result or "result" not in result["result"]:
        raise RuntimeError(f"CDP Runtime.evaluate 失败: {result}")
    return result["result"]["result"]["value"]


def parse_redring_post(main_html: str) -> dict:
    """从 main.outerHTML 解析标题、正文、评论、作者、发布时间

    Returns:
      dict with keys: title, body, images, comments, author, time_str
    """
    soup = BeautifulSoup(main_html, "html.parser")

    # 作者 + 发布时间
    author = ""
    time_str = ""
    author_span = soup.find("span", class_="fwm")
    if author_span:
        author = author_span.get_text(strip=True)
    # 第一个 dark-9 fz-sm (发布时间的样式)
    all_time_spans = soup.find_all("span", class_="dark-9 fz-sm")
    if all_time_spans:
        time_str = all_time_spans[0].get_text(strip=True)

    # 正文 (跟 finance_breakfast.py 一致: 保留 HTML 容器 ql-view/post-body)
    # 不再用 get_text() 剥成纯文本 + 末尾堆"配图"区, 那样会让图片丢失位置、文字不连贯
    # 改用 bs4 保留 ql-view 容器里的 HTML 块, 让 markdownify 自然转 (图片、段落、链接、表格都在原位)
    post_body = soup.find("div", class_="post-body")
    if not post_body:
        raise RuntimeError("post-body not found in mainHTML")
    content_div = post_body.find("div", class_=lambda c: c and "ql-view" in c.split())
    if not content_div:
        content_div = post_body.find("div", class_="fzx-2")
    if not content_div:
        raise RuntimeError("ql-view / fzx-2 content div not found in post-body")

    # 移除噪音 (input/button/svg/form), 跟 finance_breakfast.extract_post_body 保持一致
    for unwanted in content_div.find_all(["input", "button", "svg", "form"]):
        unwanted.decompose()

    # 保留 HTML 字符串 (markdownify 负责后续转换)
    body_html = "".join(str(item) for item in content_div.contents)

    # 标题 (默认从 H1 或首段拿; 后续 main() 会用 --title 参数覆盖)
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)
    else:
        # 精华贴常无 h1, fallback 用正文首段
        first_text = content_div.get_text("\n", strip=True)
        first_para = first_text.split("\n")[0].strip() if first_text else ""
        title = first_para[:60] + ("..." if len(first_para) > 60 else "")

    # 图片仅用于统计数量 + guard 报告 (不再单独追加到 .md 末尾)
    images = []
    for img in post_body.find_all("img"):
        for attr in ("data-src", "data-original", "src"):
            url = img.get(attr)
            if url and url.startswith("http") and "red-ring" in url:
                if url not in images:
                    images.append(url)
                break

    # 评论 (por px-15 容器里, div.py-12.flex 是顶级评论)
    cmt_container = soup.find("div", class_="por px-15")
    comments = []
    if cmt_container:
        # 顶级评论 div 都有 class="py-12 flex" 或 "py-12 flex bt"
        # 排除输入框 (输入框还有 "aic" class)
        all_cmts = cmt_container.find_all("div", class_="py-12")
        top_cmts = [d for d in all_cmts
                    if "flex" in (d.get("class") or [])
                    and "aic" not in (d.get("class") or [])]
        # 去重 (find_all 可能因为 nested div 把同一条评论算多次, 这里用 id 锚点去重)
        seen = set()
        unique_top = []
        for c in top_cmts:
            key = id(c)
            if key in seen:
                continue
            seen.add(key)
            unique_top.append(c)
        top_cmts = unique_top

        for cmt in top_cmts:
            user_span = cmt.find("span", class_="cup", recursive=True)
            # 优先用 mr-5 的 span (那是用户名)
            user_span = cmt.find("span", class_=lambda c: c and "cup" in c.split() and "mr-5" in c.split())
            if not user_span:
                continue
            user = user_span.get_text(strip=True)
            time_s = cmt.find("span", class_="dark-9 fz-sm", recursive=True)
            time_t = time_s.get_text(strip=True) if time_s else ""

            # 顶级内容: mb-7 tools-v-trigger pr-60 por > span.wpw
            content_p = cmt.find("div", class_="mb-7")
            if not content_p:
                continue
            content_span = content_p.find("span", class_="wpw")
            if not content_span:
                continue
            content = content_span.get_text(strip=True)
            if not content:
                continue

            item = {"user": user, "time": time_t, "content": content, "replies": []}

            # 回复容器: bgc-body px-9 py-5
            reply_container = cmt.find("div", class_="bgc-body")
            if reply_container:
                for reply in reply_container.find_all("div", class_="my-5"):
                    ru = reply.find("span", class_="c-primary", recursive=False)
                    if not ru:
                        continue
                    rt = reply.find("span", class_="wpw", recursive=False)
                    if not rt:
                        continue
                    r_user = ru.get_text(strip=True)
                    r_text = rt.get_text(strip=True)
                    if r_user and r_text:
                        item["replies"].append({"user": r_user, "content": r_text})

            comments.append(item)

    return {
        "title": title,
        "author": author,
        "time_str": time_str,
        "body_html": body_html,
        "images": images,
        "comments": comments,
    }


def render_markdown(post: dict, post_url: str, slug: str, date_str: str, override_title: str = None) -> str:
    """生成 .md 内容 (YAML frontmatter + 原文 + 评论区)

    与 finance_breakfast.py 保持一致:
    - body 用 markdownify 转 HTML, 图片/段落/链接在原位
    - 不再末尾堆"### 配图"区
    """
    title = override_title or post["title"]
    body_html = post["body_html"]
    images = post["images"]
    comments = post["comments"]
    author = post["author"]
    time_str = post["time_str"]

    # HTML 实体反转义 (跟 finance_breakfast 一样)
    body_html = html_mod.unescape(body_html)

    # markdownify 转换: heading_style="atx" 用 # 风格标题, link_style="inlined" 用 []() 内联
    post_md = mf.markdownify(body_html, heading_style="atx", link_style="inlined")

    display_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"

    md = "---\n"
    md += f'title: "{title}"\n'
    md += f'date: "{display_date}"\n'
    md += f'author: "{author}"\n'
    md += f'source: "{post_url}"\n'
    md += "---\n\n"
    md += f"# {title}\n\n"
    md += f"> 自动抓取于 {shanghai_now_iso()}\n"
    md += f"> 作者: {author} | 发布时间: {time_str}\n"
    md += f"> 来源: 小红圈 (red-ring.cn) | 圈子: 红运Dang投 (ID: 27593)\n"
    md += f"> 原文链接: {post_url}\n\n"
    md += "---\n\n"
    md += "## 原文\n\n"
    md += post_md.strip() + "\n\n"

    md += "---\n\n"
    md += f"## 💬 评论区 ({len(comments)} 条)\n\n"
    if not comments:
        md += "*暂无评论*\n"
    else:
        for c in comments:
            time_part = f" *({c['time']})*" if c['time'] else ""
            md += f"- **{c['user']}**{time_part}: {c['content']}\n"
            for r in c['replies']:
                md += f"  - ↳ **{r['user']}**: {r['content']}\n"

    return md


def main():
    ap = argparse.ArgumentParser(description="MR Dang 单篇帖子发布工具")
    ap.add_argument("--url", required=True, help="红圈 post URL (如 https://www.red-ring.cn/post/27593-2354190)")
    ap.add_argument("--slug", help="文件名 slug (默认: mr_dang_post_<post_id>)")
    ap.add_argument("--title", help="覆盖抓取的标题 (精华贴常常无 h1, 需手动指定真正标题)")
    ap.add_argument("--date", help="覆盖日期 YYYYMMDD (默认: 今天; 抓历史贴时必填)")
    ap.add_argument("--dry-run", action="store_true", help="不实际推送")
    args = ap.parse_args()

    post_url = args.url
    m = re.search(r"/post/(\d+)-(\d+)", post_url)
    if not m:
        raise ValueError(f"无法从 URL 提取 post ID: {post_url}")
    post_id = f"{m.group(1)}-{m.group(2)}"

    slug = args.slug or f"mr_dang_post_{post_id.replace('-', '_')}"
    date_str = args.date or shanghai_today_str()
    out_path = DOCS_DIR / f"{slug}.md"

    print(f"[publish] URL: {post_url}")
    print(f"[publish] Slug: {slug}")
    print(f"[publish] 输出: {out_path}")
    print()

    # 1. CDP 抓 mainHTML
    print("[step 1/3] CDP 抓 mainHTML...")
    main_html = cdp_fetch_main_html(post_url)
    print(f"  ✅ 拿到 mainHTML ({len(main_html)} 字符)")

    # 2. 解析
    print("[step 2/3] 解析 mainHTML...")
    post = parse_redring_post(main_html)
    print(f"  ✅ 标题: {post['title']}")
    print(f"  ✅ 作者: {post['author']} (发布于 {post['time_str']})")
    print(f"  ✅ 正文: {len(post['body_html'])} 字符 (HTML)")
    print(f"  ✅ 图片: {len(post['images'])} 张")
    print(f"  ✅ 评论: {len(post['comments'])} 条")

    if len(post['comments']) < 3:
        print(f"  ⚠️ 评论数过少 ({len(post['comments'])} < 3), 仍继续")

    # 3. 生成 .md
    print("[step 3/3] 生成 .md...")
    md_content = render_markdown(post, post_url, slug, date_str, override_title=args.title)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md_content, encoding="utf-8")
    print(f"  ✅ 写入 {out_path} ({len(md_content)} 字符)")

    if args.dry_run:
        print(f"\n[dry-run] 跳过实际推送")
        return 0

    # 4. 推 GitHub
    print(f"\n[step 4/4] 推 GitHub Contents API...")
    title = args.title or post['title']
    n_cmt = len(post['comments'])
    n_img = len(post['images'])
    commit_msg = (
        f"feat: MR Dang 单篇《{title}》({n_img} images, {n_cmt} comments)\n\n"
        f"自动抓取于 {shanghai_now_iso()}\n"
        f"Co-Authored-By: OpenClaw <noreply@openclaw.ai>"
    )
    # 截短 commit msg 标题 (避免超长)
    if len(title) > 40:
        title = title[:40] + "..."

    repo_path = str(out_path.relative_to(WORKSPACE_JOBS))
    push_cmd = [
        sys.executable, str(PUSHER),
        "--file", repo_path,
        "--commit-msg", commit_msg,
    ]
    print(f"  → subprocess: pusher --file {repo_path}")
    cp = subprocess.run(push_cmd, cwd=WORKSPACE_JOBS, capture_output=True, text=True, timeout=60)
    if cp.stdout:
        for line in cp.stdout.split("\n"):
            if line.strip():
                print(f"  [pusher] {line}")
    if cp.returncode != 0:
        print(f"  ❌ pusher 失败 rc={cp.returncode}")
        if cp.stderr:
            print(f"  [pusher stderr] {cp.stderr[:500]}")
        return 1
    print(f"  ✅ 推送成功")
    print(f"\n[publish] 🎉 完成: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
