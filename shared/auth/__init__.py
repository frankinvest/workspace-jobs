# shared/auth/__init__.py
"""
通用鉴权模块

核心组件:
- session_manager.py: HeadlessAuthSession 通用会话管理器
- token_extractor.js: 浏览器端 Token 提取脚本

快速使用:
    from shared.auth import HeadlessAuthSession

    # 初始化
    auth = HeadlessAuthSession.quick_start(
        login_url="https://example.com/login",
        github_token="ghp_xxx",
        github_repo="owner/repo"
    )

    # 恢复已有会话
    auth = HeadlessAuthSession.restore_session("my-session")

    # 获取认证凭证
    session = auth.get_session_dict()
"""

from .session_manager import HeadlessAuthSession

__all__ = ['HeadlessAuthSession']
