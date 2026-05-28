#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shared/network/batch_uploader.py

通用分批上传队列
将大量文件稳妥分批推送到云端（GitHub / Gitea / 阿里OSS / S3）

核心铁律:
1. 每批最多 5 个文件
2. 批次之间强制等待 1 秒
3. fetch 验证可访问性，失败则跳过并记录
4. 指数退避重试（遇到 429/503 时）

使用方式:
    from shared.network import BatchUploader

    # 定义单个文件上传函数
    def github_put(filename: str, content_b64: str) -> str:
        return github_upload(filename, b64)["content"]["download_url"]

    # 上传 50 张图片
    uploader = BatchUploader(uploader=github_put, batch_size=5, delay_ms=1000)
    result = uploader.upload_all(files)
    print(f"成功 {result['success']} 张，失败 {result['failed']} 张")
"""

import time
import asyncio
import base64
import urllib.request
import urllib.error
import json
from typing import Callable, Optional

# ---- 标准 Base64 编码（处理大文件不爆栈）----

def base64_encode(data: bytes) -> str:
    """标准 Base64 编码，支持任意大小文件"""
    binary = []
    for i in range(0, len(data), 8192):
        chunk = data[i:i + 8192]
        binary.append(chunk)
    return base64.b64encode(b''.join(binary)).decode('ascii')


# ---- GitHub 专用上传器（开箱即用）----

class GitHubUploader:
    """
    GitHub 仓库文件上传器（可作为 BatchUploader 的 uploader 参数）
    
    Usage:
        uploader = GitHubUploader(
            token="ghp_xxx",
            repo="owner/repo"
        )
        url = uploader.upload("caijing_20260513_img_01.jpg", image_b64)
    """

    def __init__(
        self,
        token: str,
        repo: str,
        branch: str = "main",
        author_name: str = "openclaw",
        author_email: str = "agent@openclaw.ai"
    ):
        self.token = token
        self.repo = repo
        self.branch = branch
        self.api = f"https://api.github.com/repos/{repo}/contents"
        self.headers = {
            "Authorization": "token " + token,
            "Content-Type": "application/json",
            "Accept": "application/vnd.github+json"
        }
        self.author = {"name": author_name, "email": author_email}

    def _get_sha(self, path: str) -> Optional[str]:
        """获取文件 SHA（更新时必须）"""
        req = urllib.request.Request(
            self.api + "/" + path + f"?ref={self.branch}",
            headers=self.headers
        )
        try:
            with urllib.request.urlopen(req, timeout=2) as r:
                return json.loads(r.read()).get("sha")
        except Exception:
            return None

    def upload(self, filename: str, content_b64: str, message: str = None) -> str:
        """
        上传单个文件到 GitHub 仓库
        
        Args:
            filename: 仓库内路径（含文件名）
            content_b64: 文件内容的 base64 编码
            message: 提交消息
            
        Returns:
            download_url
        """
        sha = self._get_sha(filename)
        body = {
            "message": message or f"Upload {filename}",
            "content": content_b64,
            "branch": self.branch,
            "author": self.author
        }
        if sha:
            body["sha"] = sha

        body_enc = json.dumps(body).encode('utf-8')
        req = urllib.request.Request(
            self.api + "/" + filename,
            data=body_enc,
            headers=self.headers,
            method="PUT"
        )

        with urllib.request.urlopen(req, timeout=15) as r:
            result = json.loads(r.read())
            return result["content"]["download_url"]


# ---- 分批上传队列核心类 ----

class BatchUploader:
    """
    分批上传队列
    
    解决核心问题:
    - 大量文件并发上传 → API 超时/限流
    - 单次 evaluate 60s 上限 → 大文件无法在浏览器内完成
    - 网络波动导致部分失败 → 自动重试
    
    铁律:
    - 每批不超过 batch_size 个文件（默认 5）
    - 批次之间强制等待 delay_ms 毫秒（默认 1000）
    - fetch 验证 URL 可访问性，失败跳过
    - 429/503 触发指数退避重试
    """

class BatchUploader:
    """
    分批上传队列
    
    解决核心问题:
    - 大量文件并发上传 → API 超时/限流
    - 单次 evaluate 60s 上限 → 大文件无法在浏览器内完成
    - 网络波动导致部分失败 → 自动重试
    - 防盗链/鉴权下载 → 403错误页被当成图片上传
    
    铁律:
    - 每批不超过 batch_size 个文件（默认 5）
    - 批次之间强制等待 delay_ms 毫秒（默认 1000）
    - fetch 验证可访问性，失败跳过
    - 下载时强制携带防盗链 headers（Cookie/UA/Referer）
    - 内容校验：文件 > 2KB 且非 HTML 错误页
    """

    def __init__(
        self,
        uploader: Callable[[str, str], str],
        # uploader(filename: str, content_b64: str) -> download_url
        batch_size: int = 5,
        delay_ms: int = 1000,
        max_retries: int = 3,
        download_headers: dict = None,
        # 下载时的 HTTP Headers（防盗链必需）
        # 示例: {"Cookie": "Hm_lvt_xxx=...", "User-Agent": "Mozilla/5.0...", "Referer": "https://example.com/"}
        min_file_size: int = 2048,
        # 文件小于此字节数视为无效（防盗链错误页）
    ):
        self.uploader = uploader
        self.batch_size = batch_size
        self.delay_ms = delay_ms
        self.max_retries = max_retries
        self.download_headers = download_headers or {}
        self.min_file_size = min_file_size

    def _sleep_ms(self, ms: int):
        time.sleep(ms / 1000)

    def _retry_with_backoff(self, fn, *args, **kwargs):
        """指数退避重试"""
        last_error = None
        for attempt in range(self.max_retries):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                last_error = e
                wait_ms = (2 ** attempt) * 500  # 500, 1000, 2000ms
                if "429" in str(e) or "503" in str(e):
                    self._sleep_ms(wait_ms)
                    continue
                raise
        raise last_error

    async def upload_all(self, files: list, *, progress_callback=None) -> dict:
        """
        分批上传所有文件
        
        Args:
            files: 文件列表
                [
                    {"url": "https://private.site.com/img1.jpg", "filename": "img_01.jpg"},
                    {"url": "https://private.site.com/img2.jpg", "filename": "img_02.jpg", "ext": "png"},
                    ...
                ]
            progress_callback: 可选，进度回调 (completed, total, last_result)
        
        Returns:
            {
                "total": 13,
                "success": 12,
                "failed": 1,
                "mapping": {"原始URL": "上传后URL", ...},
                "errors": [{"url": "...", "error": "..."}, ...]
            }
        """
        results = {
            "total": len(files),
            "success": 0,
            "failed": 0,
            "mapping": {},
            "errors": []
        }

        for batch_start in range(0, len(files), self.batch_size):
            batch = files[batch_start:batch_start + self.batch_size]

            for i, f in enumerate(batch):
                idx = batch_start + i + 1
                url = f["url"]
                filename = f["filename"]
                ext = f.get("ext") or ("png" if ".png" in url else "jpg")

                try:
                    # fetch 验证可访问性（携带防盗链 Headers）
                    import urllib.request
                    req = urllib.request.Request(url, headers=self.download_headers)
                    with urllib.request.urlopen(req, timeout=2) as resp:
                        if resp.status != 200:
                            raise Exception(f"HTTP {resp.status}")

                    # 读取内容
                    content = resp.read()

                    # 🔒 内容校验：小于 min_file_size 或 HTML 错误页 → 抛异常
                    if len(content) < self.min_file_size:
                        # 可能是防盗链 403/401 错误页
                        raise Exception(f"文件过小({len(content)}B)，疑似防盗链拒绝")
                    # 检查是否为 HTML 错误页（防盗链常返回错误页而非真实图片）
                    content_head = content[:100].decode('utf-8', errors='ignore').strip().lower()
                    if any(x in content_head for x in ['<!doctype', '<html', '<body', '<?xml', '<!doctype html']):
                        raise Exception(f"下载到 HTML 错误页({len(content)}B)，防盗链拒绝")
                    # 可选：Content-Type 校验
                    ctype = resp.headers.get('Content-Type', '').lower()
                    if ctype and not any(x in ctype for x in ['image/', 'application/octet']):
                        # 非图片 Content-Type，但不阻断，仅警告
                        print(f"  WARN {idx}/{len(files)} Content-Type: {ctype}")

                    b64 = base64_encode(content)

                    # 上传（带重试）
                    download_url = self._retry_with_backoff(
                        self.uploader, filename, b64
                    )

                    results["mapping"][url] = download_url
                    results["success"] += 1
                    print(f"  OK   {idx}/{len(files)} {filename} ({len(content)//1024}KB)")

                except Exception as e:
                    results["failed"] += 1
                    results["errors"].append({"url": url, "filename": filename, "error": str(e)})
                    print(f"  FAIL {idx}/{len(files)} {filename}: {e}")

                if progress_callback:
                    progress_callback(results["success"] + results["failed"], len(files), f)

            # 批次间延迟
            if batch_start + self.batch_size < len(files):
                self._sleep_ms(self.delay_ms)

        return results

    # ---- 同步封装（兼容非 async 环境）----

    def upload_all_sync(self, files: list, progress_callback=None) -> dict:
        """同步版本（供传统 Python 脚本调用）"""
        return asyncio.run(self.upload_all(files, progress_callback=progress_callback))


# ---- 便捷工厂：GitHub 分批上传器 ----

def github_batch_uploader(
    github_token: str,
    github_repo: str,
    batch_size: int = 5,
    delay_ms: int = 1000,
    download_headers: dict = None
) -> BatchUploader:
    """
    创建 GitHub 专用分批上传器
    
    Usage:
        uploader = github_batch_uploader(
            github_token="ghp_xxx",
            github_repo="owner/repo",
            download_headers={
                "Cookie": "Hm_lvt_xxx=...",
                "User-Agent": "Mozilla/5.0 ...",
                "Referer": "https://example.com/"
            }
        )
        result = uploader.upload_all_sync([
            {"url": "https://private.site/1.jpg", "filename": "1.jpg"},
            {"url": "https://private.site/2.jpg", "filename": "2.jpg"},
        ])
    """
    gh = GitHubUploader(token=github_token, repo=github_repo)
    return BatchUploader(
        uploader=gh.upload,
        batch_size=batch_size,
        delay_ms=delay_ms,
        download_headers=download_headers or {}
    )
