#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shared/auth/session_manager.py

通用无头浏览器会话管理器
封装扫码登录、Token提取、会话持久化的完整流程

适用于：微信扫码登录、钉钉、企业微信等一切扫码认证场景

使用方式:
    from shared.auth import HeadlessAuthSession

    auth = HeadlessAuthSession(
        login_url="https://example.com/login",
        screenshot_upload_config={...}
    )
    qr_url = auth.get_qrcode_stream()
    session = auth.wait_scan_and_extract(timeout=120)
    auth.save_session("my-session")
"""

import os
import json
import time
import base64
import urllib.request
import urllib.error
import urllib.parse

# ========== 可配置项 ==========

DEFAULT_SESSION_DIR = os.path.expanduser("~/.openclaw/sessions")


class HeadlessAuthSession:
    """
    远程无头浏览器会话管理器
    
    核心能力:
    1. 获取二维码（截图 + 上传 → 公网URL）
    2. 等待扫码登录完成
    3. 提取完整认证凭证（cookies + localStorage）
    4. 会话持久化（保存/恢复）
    """

    def __init__(
        self,
        login_url: str,
        session_name: str = None,
        session_dir: str = DEFAULT_SESSION_DIR,
        screenshot_upload_config: dict = None,
        browser_target_id: str = None
    ):
        """
        Args:
            login_url: 登录页面 URL
            session_name: 会话名称（用于持久化文件名）
            session_dir: 会话存储目录
            screenshot_upload_config: 截图上传配置
                {
                    "github_token": "ghp_xxx",
                    "github_repo": "owner/repo",
                    "upload_path": "sessions/"  # 上传到仓库的路径
                }
            browser_target_id: Playwright 浏览器 tab target ID
        """
        self.login_url = login_url
        self.session_name = session_name or self._generate_session_name()
        self.session_dir = session_dir
        self.screenshot_upload_config = screenshot_upload_config
        self.browser_target_id = browser_target_id
        
        # 运行时会填充
        self._session_data = None

    def _generate_session_name(self) -> str:
        import uuid
        return f"session_{int(time.time())}_{uuid.uuid4().hex[:6]}"

    # ---- Token 提取（供 Browser 调用后解析结果）----

    @staticmethod
    def parse_session_from_browser(evaluate_result: str) -> dict:
        """
        解析 Browser evaluate 返回的 JSON 字符串
        Args:
            evaluate_result: TokenExtractor.extractSessionToken() 的 JSON 字符串
        Returns:
            session dict: { cookies, localStorage, userAgent, extractedAt }
        """
        try:
            return json.loads(evaluate_result)
        except json.JSONDecodeError as e:
            raise ValueError(f"TokenExtractor 返回格式错误: {e}")

    # ---- 会话持久化 ----

    def save_session(self, session_data: dict = None) -> str:
        """
        保存会话到本地文件
        
        Args:
            session_data: 要保存的会话数据，若为 None 则使用内存中的数据
        Returns:
            保存的文件路径
        """
        if session_data is None:
            session_data = self._session_data

        if session_data is None:
            raise ValueError("没有可保存的会话数据")

        os.makedirs(self.session_dir, exist_ok=True)
        filepath = os.path.join(self.session_dir, f"{self.session_name}.json")

        payload = {
            "name": self.session_name,
            "login_url": self.login_url,
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            "session": session_data
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        return filepath

    @classmethod
    def restore_session(
        cls,
        session_name: str,
        session_dir: str = DEFAULT_SESSION_DIR
    ) -> "HeadlessAuthSession":
        """
        从本地文件恢复会话
        
        Args:
            session_name: 会话名称
            session_dir: 会话存储目录
        Returns:
            恢复的 HeadlessAuthSession 实例（不含 browser_target_id）
        """
        filepath = os.path.join(session_dir, f"{session_name}.json")
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"会话文件不存在: {filepath}")

        with open(filepath, 'r', encoding='utf-8') as f:
            payload = json.load(f)

        session_obj = cls(
            login_url=payload["login_url"],
            session_name=payload["name"],
            session_dir=session_dir
        )
        session_obj._session_data = payload["session"]
        return session_obj

    def is_valid(self) -> bool:
        """检查会话是否仍然有效（localStorage 非空）"""
        if self._session_data is None:
            return False
        local_storage = self._session_data.get("localStorage", {})
        return bool(local_storage)

    def get_cookies(self) -> str:
        return self._session_data.get("cookies", "") if self._session_data else ""

    def get_local_storage(self) -> dict:
        return self._session_data.get("localStorage", {}) if self._session_data else {}

    def get_session_dict(self) -> dict:
        """获取完整会话字典（供外部使用）"""
        return self._session_data or {}

    # ---- GitHub 上传（截图用）----

    @staticmethod
    def upload_to_github(
        filepath_or_content: str,
        filename: str,
        github_token: str,
        github_repo: str,
        upload_path: str = ""
    ) -> str:
        """
        上传文件到 GitHub 仓库

        Args:
            filepath_or_content: 文件路径 或 base64 编码内容（以 "base64:" 开头）
            filename: 保存到仓库的文件名
            github_token: GitHub Personal Access Token
            github_repo: 仓库名（owner/repo）
            upload_path: 仓库内的子路径，如 "sessions/"

        Returns:
            公网访问 URL
        """
        import urllib.request
        import urllib.parse

        if filepath_or_content.startswith("base64:"):
            content_b64 = filepath_or_content[7:]
        else:
            with open(filepath_or_content, 'rb') as f:
                content_b64 = base64.b64encode(f.read()).decode('ascii')

        api = f"https://api.github.com/repos/{github_repo}/contents/{upload_path.rstrip('/')}/{filename}"
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
            "message": f"Upload {filename}",
            "content": content_b64,
            "branch": "main"
        }
        if sha:
            body["sha"] = sha

        body_enc = json.dumps(body).encode('utf-8')
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

    def upload_session_avatar(
        self,
        image_content_b64: str,
        filename: str = None
    ) -> str:
        """
        上传会话头像/二维码图片到 GitHub
        
        Args:
            image_content_b64: 图片的 base64 内容（不含 "data:..." 前缀）
            filename: 可选文件名
            
        Returns:
            公网 URL
        """
        if not self.screenshot_upload_config:
            raise ValueError("未配置 screenshot_upload_config")

        cfg = self.screenshot_upload_config
        filename = filename or f"auth_qr_{int(time.time())}.png"

        return self.upload_to_github(
            filepath_or_content="base64:" + image_content_b64,
            filename=filename,
            github_token=cfg["github_token"],
            github_repo=cfg["github_repo"],
            upload_path=cfg.get("upload_path", "sessions/")
        )

    # ---- 便捷工厂方法 ----

    @classmethod
    def quick_start(
        cls,
        login_url: str,
        github_token: str,
        github_repo: str,
        upload_path: str = "sessions/",
        session_name: str = None
    ) -> "HeadlessAuthSession":
        """
        快速初始化（一步到位配置所有参数）
        
        Usage:
            auth = HeadlessAuthSession.quick_start(
                login_url="https://example.com/login",
                github_token="ghp_xxx",
                github_repo="owner/repo"
            )
        """
        return cls(
            login_url=login_url,
            session_name=session_name,
            screenshot_upload_config={
                "github_token": github_token,
                "github_repo": github_repo,
                "upload_path": upload_path
            }
        )

    def __repr__(self):
        return (f"<HeadlessAuthSession "
                f"login_url={self.login_url} "
                f"session_name={self.session_name} "
                f"valid={self.is_valid()}>")
