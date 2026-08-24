# ERRORS.md - Jobs's Errors

> Command failures, exceptions, and issues encountered.

---

## Command Errors

_(记录命令/操作失败)_

---

## API/External Tool Errors

_(记录外部 API 或工具失败)_

---

## Bug Records

_(记录代码 bug 和修复)_

---

*Auto-managed by self-improving-agent skill*

---

## 2026-08-13 Contents API push - 401 + token 混淆

**症状**: `system_api_pusher.py` 推送到 GitHub 报 HTTP 401 "Bad credentials"

**根因**: 
- `.git-credentials` 里存的 token 是 `ghp_***REDACTED***`（过期/无效）
- git remote origin 的 URL 里嵌的 token 是 `ghp_***REDACTED***`（才是真正能用的）
- `system_api_pusher.py` 从 `.git-credentials` 读 token，所以 Contents API 一直 401

**修复**: `system_api_pusher.py` 应该从 `git remote get-url origin` 解析出真正的 token，而不是读 `.git-credentials`

**影响**: 2026-08-13 财经早餐（commit 4920fb04）是通过手动调 Contents API 推送成功的

