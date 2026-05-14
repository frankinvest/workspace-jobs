#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shared/deploy/github_pages.py

GitHub Pages 构建触发器 + 状态轮询

使用方式:
    from shared.deploy import GitHubPagesTrigger

    trigger = GitHubPagesTrigger(
        token="ghp_xxx",
        repo="owner/repo"
    )
    trigger.build()                    # 触发构建
    success = trigger.wait_built()     # 等待完成
"""

import time
import urllib.request
import urllib.error
import json
from typing import Optional


class GitHubPagesTrigger:
    """
    GitHub Pages 构建触发器
    
    能力:
    1. 触发构建（POST /repos/{owner}/{repo}/pages/builds）
    2. 查询最新构建状态（GET /repos/{owner}/{repo}/pages/builds/latest）
    3. 等待构建完成（带超时）
    4. 获取 Pages 访问地址
    """

    BUILD_TIMEOUT = 90  # 最大等待秒数
    BUILD_INTERVAL = 5  # 轮询间隔秒数

    def __init__(self, token: str, repo: str):
        self.token = token
        self.repo = repo
        self.api_pages = f"https://api.github.com/repos/{repo}/pages"
        self.api_builds = f"https://api.github.com/repos/{repo}/pages/builds"
        self.headers = {
            "Authorization": "token " + token,
            "Accept": "application/vnd.github+json"
        }

    def _request(self, url: str, method: str = "GET", data: dict = None) -> dict:
        body = json.dumps(data or {}).encode("utf-8") if data else None
        req = urllib.request.Request(
            url,
            data=body,
            headers=self.headers,
            method=method
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())

    def build(self) -> dict:
        """
        触发 GitHub Pages 构建
        
        Returns:
            {"status": "queued", "url": "...", ...}
        """
        result = self._request(self.api_builds, method="POST")
        print(f"[GitHubPages] 构建已触发: {result.get('url')}")
        return result

    def get_status(self) -> Optional[dict]:
        """
        获取最新构建状态
        
        Returns:
            None (无可用构建记录)
            或 {"status": "built"|"building"|"queued"|"errored", ...}
        """
        try:
            return self._request(self.api_builds + "/latest")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise

    def wait_built(self, timeout: int = None, interval: int = None) -> bool:
        """
        等待构建完成（阻塞）
        
        Args:
            timeout: 超时秒数（默认 BUILD_TIMEOUT=90）
            interval: 轮询间隔秒数（默认 BUILD_INTERVAL=5）
            
        Returns:
            True  = 构建成功 (status == "built")
            False = 超时或错误 (status == "errored")
        """
        timeout = timeout or self.BUILD_TIMEOUT
        interval = interval or self.BUILD_INTERVAL
        start = time.time()

        while time.time() - start < timeout:
            status = self.get_status()
            if status:
                s = status.get("status")
                print(f"[GitHubPages] 状态: {s}")
                if s == "built":
                    return True
                if s == "errored":
                    error_msg = status.get("error", {}).get("message", "未知错误")
                    print(f"[GitHubPages] 构建错误: {error_msg}")
                    return False
            time.sleep(interval)

        print(f"[GitHubPages] 构建超时（>{timeout}s）")
        return False

    def get_pages_url(self) -> str:
        """
        获取 GitHub Pages 访问地址
        
        Returns:
            https://{username}.github.io/{repo}/
        """
        # 从仓库信息获取
        api_repo = f"https://api.github.com/repos/{self.repo}"
        repo_info = self._request(api_repo)
        owner = repo_info.get("owner", {}).get("login", "")
        name = repo_info.get("name", "")
        
        # Pages URL 格式
        if repo_info.get("has_pages"):
            return f"https://{owner.lower()}.github.io/{name}/"
        return f"https://{owner.lower()}.github.io/{name}/"

    def trigger_and_wait(self) -> bool:
        """
        一键触发 + 等待（最常用组合）
        
        Returns:
            True = 构建成功，False = 超时/失败
        """
        self.build()
        ok = self.wait_built()
        if ok:
            print(f"[GitHubPages] ✅ 构建成功！")
            print(f"       访问: {self.get_pages_url()}")
        else:
            print(f"[GitHubPages] ❌ 构建失败或超时")
        return ok
