# LEARNINGS.md - Jobs's Learnings

> Corrections, knowledge gaps, and best practices discovered while working with Frank.

---

## Corrections

_(记录用户的纠正)_

---

## Knowledge Gaps

_(记录知识更新)_

---

## Best Practices

_(记录发现的最佳实践)_

---

*Auto-managed by self-improving-agent skill*

---

## GitHub Token 两个版本 + Contents API 正确 token (2026-08-13 验证)

### 两个 token 的区别

| 来源 | Token | 用途 |
|------|-------|------|
| `.git-credentials` | `ghp_***REDACTED***` | ❌ 过期/无效 |
| `git remote origin` URL | `ghp_***REDACTED***` | ✅ 有效 |

### `system_api_pusher.py` token bug

- 当前从 `~/.git-credentials` 读 → 拿到无效 token → Contents API 401
- **修复**: 从 `git remote get-url origin` 解析 token（URL 格式: `https://frank-bot:<TOKEN>@github.com/...`）

### Mac mini 网络限制

- `api.github.com`: ✅ 可访问
- `github.com` (git push): ❌ 超时 hang
- `raw.githubusercontent.com`: ❌ 超时 hang

**影响**: 所有走 git 协议的 push 会 hang；Contents API 走 HTTPS 正常。

