#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shared/render/html_generator.py

通用 HTML 生成引擎
将结构化数据（正文、评论、图片URL）渲染为完整静态 HTML

特性:
- 模板与数据完全分离
- 内置默认 CSS（移动端友好）
- 评论嵌套结构自动构建
- 多主题支持（通过 CSS 注入）

使用方式:
    from shared.render import HtmlGenerator

    gen = HtmlGenerator(
        title="财经早餐 20260513",
        author="MR Dang"
    )
    gen.set_content(post_html)      # 正文章节（含 img 标签）
    gen.set_comments(comments)     # 评论列表
    html = gen.render()             # 完整 HTML 字符串
    uploader.upload("caijing_20260513.html", base64.b64encode(html))
"""

import base64
import json
import re
import urllib.request
import urllib.error
from typing import Optional, Callable


# ---- 内置 CSS 主题 ----

THEMES = {
    "default": """
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;font-size:14px;max-width:720px;margin:0 auto;padding:16px;background:#fafafa;line-height:1.7;color:#333}
.post{background:white;border-radius:8px;padding:20px;margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
h2{font-size:1.05em;margin-top:1.5em;padding:8px 14px;background:#f0f4ff;border-left:4px solid #1a73e8;border-radius:0 4px 4px 0}
p{margin:.6em 0}
img{max-width:100%;height:auto;border-radius:4px;margin:8px 0;display:block}
strong{color:#c00}
.cmt{background:#fafafa;padding:12px;border-radius:8px;font-size:.9em;margin-top:20px}
.cmt-item{background:white;border-radius:6px;padding:14px;margin-bottom:10px;box-shadow:0 1px 2px rgba(0,0,0,.06)}
.u{color:#1a73e8;font-weight:600}
.t{color:#999;font-size:.8em;margin-left:8px}
.r{margin-top:8px;padding:8px 12px;background:#f5f5f5;border-radius:4px;font-size:.88em;color:#555;line-height:1.6}
.footer{text-align:center;color:#999;font-size:.8em;padding:20px 0;border-top:1px solid #eee;margin-top:30px}
    """,
    "dark": """
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;font-size:14px;max-width:720px;margin:0 auto;padding:16px;background:#1a1a1a;line-height:1.7;color:#e0e0e0}
.post{background:#2a2a2a;border-radius:8px;padding:20px;margin-bottom:16px}
h2{font-size:1.05em;margin-top:1.5em;padding:8px 14px;background:#1a3a5a;border-left:4px solid #4a9eff;border-radius:0 4px 4px 0}
p{margin:.6em 0}
img{max-width:100%;height:auto;border-radius:4px;margin:8px 0;display:block}
strong{color:#ff6b6b}
.cmt{background:#222;padding:12px;border-radius:8px;font-size:.9em;margin-top:20px}
.cmt-item{background:#2a2a2a;border-radius:6px;padding:14px;margin-bottom:10px;border:1px solid #333}
.u{color:#4a9eff;font-weight:600}
.t{color:#888;font-size:.8em;margin-left:8px}
.r{margin-top:8px;padding:8px 12px;background:#333;border-radius:4px;font-size:.88em;color:#bbb;line-height:1.6}
.footer{text-align:center;color:#666;font-size:.8em;padding:20px 0;border-top:1px solid #333;margin-top:30px}
    """
}


# ---- HTML 生成器核心类 ----

class HtmlGenerator:
    """
    通用 HTML 生成器
    
    使用流程:
        gen = HtmlGenerator(title="...", author="...")
        gen.set_content(post_html_with_img_tags)
        gen.set_comments(comment_list)
        html = gen.render()
    """

    def __init__(
        self,
        title: str,
        author: str = None,
        theme: str = "default",
        lang: str = "zh",
        custom_css: str = None,
        footer_text: str = None
    ):
        self.title = title
        self.author = author
        self.lang = lang
        self.theme = theme
        self.custom_css = custom_css
        self.footer_text = footer_text or f"本页面由 MCP-RedRing 自动生成"
        
        self._content = ""
        self._comments = []
        self._mixed_mode = False  # 是否使用图文混排模式

    def set_content(self, html_content: str):
        """设置正文章节 HTML（应包含 <h2> 分节和 <img> 标签）"""
        self._content = html_content
        self._mixed_mode = False

    def set_mixed_content(
        self,
        mixed_text: str,
        github_token: str = None,
        github_repo: str = None,
        upload_path: str = "images/",
        uploader: Callable = None
    ):
        """
        图文混排模式：处理 DomScraper.extractMixedContent() 的输出。

        处理流程：
          1. 用正则 `![img](url)` 提取所有图片 URL
          2. 批量上传到 GitHub（调用 uploader 函数或 shared/network/batch_uploader）
          3. 用映射字典将原 URL 替换为 GitHub Raw URL
          4. 将 `![img](url)` 替换为 <img src="...">

        Args:
            mixed_text: DomScraper.extractMixedContent() 输出的图文混排字符串
            github_token: GitHub Token（若传 uploader 则可不传）
            github_repo: 仓库名（若传 uploader 则可不传）
            upload_path: GitHub 上传路径
            uploader: 可选，自定义上传函数 fn(url: str, filename: str) -> str
        """
        self._mixed_mode = True

        # Step 1: 提取所有图片 URL（保持出现顺序）
        img_pattern = re.compile(r'!\[img\]\((https?://[^)]+)\)')
        raw_urls = img_pattern.findall(mixed_text)
        if not raw_urls:
            # 没有图片，降级为纯文本
            self._content = self._paragraphize(mixed_text)
            return

        # Step 2: 构建上传文件列表（去重但保持顺序）
        seen = set()
        upload_list = []
        for url in raw_urls:
            if url not in seen:
                seen.add(url)
                ext = 'png' if '.png' in url else 'jpg'
                idx = len(upload_list) + 1
                upload_list.append({
                    'url': url,
                    'filename': f'img_{idx:03d}.{ext}'
                })

        # Step 3: 批量上传
        if uploader:
            # 使用自定义上传函数
            mapping = {}
            for item in upload_list:
                try:
                    gh_url = uploader(item['url'], item['filename'])
                    mapping[item['url']] = gh_url
                except Exception as e:
                    print(f'[HtmlGenerator] 上传失败 {item["filename"]}: {e}')
                    mapping[item['url']] = item['url']  # 降级：保留原 URL
        else:
            # 使用 shared/network/batch_uploader
            try:
                import sys, os
                # 尝试导入 shared.network（运行时注入路径）
                workspace = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                sys.path.insert(0, workspace)
                from shared.network import GitHubUploader, BatchUploader

                gh = GitHubUploader(token=github_token, repo=github_repo)
                batch = BatchUploader(uploader=gh.upload, batch_size=5, delay_ms=1000)

                # 构造 files 格式
                files = [{'url': item['url'], 'filename': item['filename']}
                          for item in upload_list]
                result = batch.upload_all_sync(files)
                mapping = result.get('mapping', {})
                print(f'[HtmlGenerator] 批量上传完成: {result["success"]}/{result["total"]} 张')
            except Exception as e:
                print(f'[HtmlGenerator] 批量上传异常，降级保留原URL: {e}')
                mapping = {item['url']: item['url'] for item in upload_list}


        # Step 4: URL 替换 + 标签转换
        def replace_img(m):
            original = m.group(1)
            gh_url = mapping.get(original, original)
            return f'<img src="{gh_url}" style="max-width:100%;display:block;margin:8px 0;border-radius:4px">'

        html_content = img_pattern.sub(replace_img, mixed_text)

        # Step 5: 将剩余文本转为 <p> 段落
        self._content = self._paragraphize(html_content)

    @staticmethod
    def _paragraphize(text: str) -> str:
        """将换行分隔的文本转为 HTML <p> 段落，保留 <img> 标签原位"""
        blocks = re.split(r'\n{2,}', text)
        html_parts = []
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            if block.startswith('<img ') or block.startswith('<h') or block == '---':
                # 整块是标签或分割线，原样保留
                html_parts.append(block)
            else:
                # 普通文本：转为 <p>
                lines = re.split(r'\n', block)
                html_lines = []
                for line in lines:
                    line = line.strip()
                    if line:
                        html_lines.append('<p>' + line + '</p>')
                html_parts.append('\n'.join(html_lines))
        return '\n'.join(html_parts)

    def set_comments(self, comments: list):
        """
        设置评论列表
        
        comments 格式:
        [
            {
                "user": "用户名",
                "time": "今天 07:01",
                "content": "评论正文",
                "replies": ["子回复1", "子回复2"]  # 可选
            },
            ...
        ]
        """
        self._comments = comments or []

    def _build_comments_html(self) -> str:
        """构建评论区块 HTML"""
        if not self._comments:
            return ""

        items = []
        for c in self._comments:
            replies_html = ""
            if c.get("replies"):
                replies = []
                for r in c["replies"]:
                    if "：" in r:
                        parts = r.split("：", 1)
                        replies.append(
                            "<strong>" + parts[0] + "：</strong> " + parts[1]
                        )
                    elif ":" in r:
                        parts = r.split(":", 1)
                        replies.append(
                            "<strong>" + parts[0] + ":</strong> " + parts[1]
                        )
                    else:
                        replies.append(r)
                replies_html = '<div class="r">' + "<br>".join(replies) + "</div>"

            content = c["content"].replace("\n", "<br>")
            items.append(
                '<div class="cmt-item">'
                + '<span class="u">' + c["user"] + '</span> '
                + '<span class="t">' + c["time"] + '</span>'
                + "<p>" + content + "</p>"
                + replies_html
                + "</div>"
            )

        return (
            '<div class="cmt">\n'
            + f"<h2>评论区 ({len(self._comments)} 条)</h2>\n"
            + "\n".join(items)
            + "\n</div>"
        )

    def render(self) -> str:
        """
        渲染完整 HTML 文档

        Returns:
            完整 HTML 字符串
        """
        css = self.custom_css or THEMES.get(self.theme, THEMES["default"])

        footer_parts = [self.footer_text]
        if self.author:
            footer_parts.insert(0, f"作者：{self.author}")

        html = (
            '<!DOCTYPE html>\n'
            '<html lang="' + self.lang + '">\n'
            "<head>\n"
            '<meta charset="UTF-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            "<title>" + self.title + "</title>\n"
            "<style>\n" + css + "\n</style>\n"
            "</head>\n"
            "<body>\n"
            '<div class="post">\n'
            + self._content + "\n"
            "</div>\n"
            + self._build_comments_html() + "\n"
            '<div class="footer">\n'
            + "<p>" + " · ".join(footer_parts) + "</p>\n"
            "</div>\n"
            "</body>\n"
            "</html>"
        )
        return html

    def upload_to_github(
        self,
        github_token: str,
        github_repo: str,
        filepath: str,
        message: str = None
    ) -> str:
        """
        直接上传到 GitHub 仓库
        
        Returns:
            download_url
        """
        html = self.render()
        b64 = base64.b64encode(html.encode("utf-8")).decode("ascii")

        api = f"https://api.github.com/repos/{github_repo}/contents/{filepath}"
        get_req = urllib.request.Request(
            api + "?ref=main",
            headers={"Authorization": "token " + github_token}
        )

        sha = None
        try:
            with urllib.request.urlopen(get_req, timeout=10) as r:
                sha = json.loads(r.read()).get("sha")
        except Exception:
            pass

        body = {
            "message": message or f"Update {filepath}",
            "content": b64,
            "branch": "main"
        }
        if sha:
            body["sha"] = sha

        body_enc = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            api,
            data=body_enc,
            headers={
                "Authorization": "token " + github_token,
                "Content-Type": "application/json"
            },
            method="PUT"
        )

        with urllib.request.urlopen(req, timeout=15) as r:
            result = json.loads(r.read())
            return result["content"]["download_url"]
