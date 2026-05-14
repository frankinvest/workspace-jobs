# shared/network/__init__.py
"""
通用网络模块

核心组件:
- batch_uploader.py: 分批上传队列 + GitHubUploader 开箱即用

快速使用:
    from shared.network import github_batch_uploader

    uploader = github_batch_uploader(
        github_token="ghp_xxx",
        github_repo="owner/repo"
    )
    result = uploader.upload_all_sync([
        {"url": "https://private.site/1.jpg", "filename": "1.jpg"},
    ])
    print(f"成功 {result['success']} 张")
"""

from .batch_uploader import (
    BatchUploader,
    GitHubUploader,
    github_batch_uploader,
    base64_encode
)

__all__ = ['BatchUploader', 'GitHubUploader', 'github_batch_uploader', 'base64_encode']
