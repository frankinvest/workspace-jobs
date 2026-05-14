# shared/__init__.py
"""
shared/ - 通用积木库

所有模块均可独立使用，也可通过 shared 统一导入。

子模块:
    auth      - 鉴权与会话管理
    network   - 网络上传队列
    render    - HTML 生成引擎
    deploy    - 部署触发器
    utils     - 通用工具

快速使用:
    from shared.auth import HeadlessAuthSession
    from shared.network import github_batch_uploader
    from shared.render import HtmlGenerator
    from shared.deploy import GitHubPagesTrigger
"""

from shared.build_full import build

__all__ = ['build']

__path__ = __import__('pkgutil').extend_path(__path__, __name__)
