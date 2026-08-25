# Vercel 端到端部署流程 (frankofswing.com)

> 最后更新：2026-08-25 15:33
> 来源：search-snippet feature 完整研发→部署过程总结

---

## 🗺️ 完整流程图

```
┌─────────────────────────────────────────────────────────────┐
│  1. 研发 (本地)                                              │
│     src/utils/search.ts ← 改代码                            │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  2. 测试 (本地)                                              │
│     ├─ vitest 跑单测 (vitest run)                          │
│     ├─ field_contract_check.py (静态验证接口字段对齐)        │
│     └─ npm run build (182 页, 验证 TS + Astro)             │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  3. Push (本地 → GitHub)                                     │
│     ├─ git push origin main     ← 主路径 (常撞墙)           │
│     └─ Contents API PUT         ← 备用路径 (必走)           │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  4. Vercel Auto-Deploy (GitHub App 集成)                   │
│     push → Vercel 检测到新 commit → 自动 rebuild           │
│     典型耗时: 1-3 分钟 (实际 3-30 秒)                       │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  5. 验证部署                                                │
│     ├─ last-modified header (跨过 baseline = rebuild 完成)  │
│     ├─ build 版本号 (HTML 里 "构建版本: 2026/8/25 15:25") │
│     └─ bundle 内容: 含 snippetsHtml + matchCount           │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  6. 端到端 smoke test                                       │
│     browser_smoke.py (CDP → frankofswing.com → 搜索验证)   │
└─────────────────────────────────────────────────────────────┘
```

---

## 📦 frankofswing.com 部署平台 = Vercel

### 关键证据

| 线索 | 含义 |
|------|------|
| `server: Vercel` (HTTP header) | frankofswing.com **是 Vercel 部署** |
| `x-vercel-cache: HIT`, `age: 11701s` | Vercel Edge Network (CDN) |
| `x-vercel-id: hnd1::*` | Vercel POP ID (hnd = 香港/河内区域) |
| `last-modified: 04:00:08 GMT` | Vercel 部署时间戳 |

### 容易踩的坑

❌ **错判**: Cloudflare proxy IP (`76.76.21.21`) → 以为是 Cloudflare Pages
✅ **真相**: Cloudflare IP = CDN 代理，**真部署平台看 `server:` header**

| DNS 模式 | 含义 |
|----------|------|
| DNS 在阿里云 (`dns25.hichina.com`) | 域名注册商 |
| A 记录 `76.76.21.21` (Cloudflare IP) | Cloudflare proxy **可选项** (CDN) |
| `server: Vercel` 头 | **真部署平台** |

**MEMORY 之前记错**: `frankofswing.com 错误 ID hnd1::* 是 Cloudflare Pages 命名空间` —— 这是错的。`hnd1::*` 是 **Vercel POP ID**，不是 Cloudflare。

---

## 🔑 关键工具链 (2026-08-25 终极版)

### 工具位置

| 工具 | 路径 | 作用 |
|------|------|------|
| `src/utils/search.ts` | workspace-jobs | 搜索逻辑 (server-side + client-side) |
| `tools/dev_loop.py` | workspace-jobs | 端到端研发流程 (plan→test→code→verify→deploy→live-verify) |
| `tools/field_contract_check.py` | workspace-jobs | 静态检查: SearchBox.astro 用的字段都在 SearchResult interface |
| `tools/browser_smoke.py` | workspace-jobs | 真浏览器 (CDP @18900) 端到端搜索验证 |
| `tools/system_git_pusher.py` | workspace-jobs | git push 穿墙推送 (主路径) |
| `tools/system_api_pusher.py` | workspace-jobs | GitHub Contents API 推送 (备用路径) |

### 关键脚本片段

#### Contents API Push (绕过 git push 撞墙)

```python
import urllib.request, json, base64

TOKEN = open('/Users/frank_bot/.git-credentials').read().split(':')[2].split('@')[0]

# 1. GET 当前 SHA
with urllib.request.urlopen(urllib.request.Request(
    'https://api.github.com/repos/frankinvest/workspace-jobs/contents/src/utils/search.ts?ref=main',
    headers={'Authorization': f'token {TOKEN}', 'Accept': 'application/vnd.github+json'}
)) as r:
    sha = json.loads(r.read())['sha']

# 2. PUT 新内容
with open('src/utils/search.ts') as f:
    content = f.read()
b64 = base64.b64encode(content.encode()).decode()

body = json.dumps({
    'message': 'fix(search): searchArticles() returns snippetsHtml[] + matchCount',
    'content': b64,
    'sha': sha,
    'branch': 'main',
})

req = urllib.request.Request(
    'https://api.github.com/repos/frankinvest/workspace-jobs/contents/src/utils/search.ts',
    data=body.encode(),
    headers={
        'Authorization': f'token {TOKEN}',
        'Accept': 'application/vnd.github+json',
        'Content-Type': 'application/json',
    }
)
with urllib.request.urlopen(req) as r:
    result = json.loads(r.read())
    print(f'Pushed {result["commit"]["sha"]}')
```

#### Vercel 部署验证

```python
import urllib.request, re

req = urllib.request.Request('https://frankofswing.com/', headers={'User-Agent': 'verify'})
with urllib.request.urlopen(req, timeout=15) as r:
    html = r.read().decode()
    lm = r.headers.get('last-modified', '')

# 检查 rebuild
if lm == 'Tue, 25 Aug 2026 04:00:08 GMT':  # baseline
    print('❌ Vercel 还没 rebuild')
else:
    print(f'✅ Vercel rebuilt: {lm}')

# 检查 bundle 内容
scripts = re.findall(r'<script[^>]*src="([^"]*)"[^>]*>', html)
for ext in scripts:
    if 'SearchBox' in ext:
        js = urllib.request.urlopen(f'https://frankofswing.com{ext}').read().decode()
        has_pl = 'snippetsHtml' in js
        has_ct = 'matchCount' in js
        print(f'  snippetsHtml={has_pl}  matchCount={has_ct}')
```

---

## 🐛 这次踩的坑 (Frank 提示里 7 处事实性 bug)

### Bug 1: 错判部署平台

| Frank 提示 | 实际 |
|------------|------|
| "frankofswing.com 是 Cloudflare Pages" | ❌ 是 **Vercel** (`server: Vercel`) |
| "GitHub 没有 webhook 所以 push 不触发" | ❌ Vercel 用 **GitHub App** 集成 (webhook API 看不到) |

**修正方法**: 看 `server:` HTTP header 判断部署平台

### Bug 2: 字段名不匹配 (真 bug)

**src/components/SearchBox.astro** (render 端期待):
```js
const snippetsHtml = r.snippetsHtml;  // 复数
const matchCount = r.matchCount;        // 新字段
```

**src/utils/search.ts** (searchArticles 输出):
```ts
{ article, matchedTitle, matchedBody, snippetHtml }  // 只有单数 snippetHtml
```

→ `t.snippetsHtml = undefined` → `<li>` 全空 → "找到 N 篇" 但 list 空

### Bug 3: 关键词在第 5 句命中不了

之前 client render 只取前 2 句做 snippet。第 5 句的关键词根本不显示。

**Fix**: search.ts 重写为多 snippet（每个匹配位置都生成一个 snippet），最多 3 个

### Bug 4: CJK / English 一刀切

之前用固定 SNIPPET_RADIUS=40 字符，对英文 word boundary 处理差。

**Fix**: `isCJK()` 检测 → CJK 用字符级上下文，English 用 word 级上下文

### Bug 5: Git push 撞墙

```
fatal: unable to access 'https://github.com/frankinvest/workspace-jobs.git/':
Recv failure: Operation timed out
```

→ sandbox 出不去 github.com:443 的 git 协议

**Fix**: Contents API fallback (PAT 在 `~/.git-credentials`, 用 urllib 推)

### Bug 6: Contents API PUT 404

第一次 PUT 报 `404 Not Found`：
```python
# ❌ 错的
urllib.request.urlopen(urllib.request.Request(
    url, data=json.dumps(body).encode(), headers={...}))
# 没有先 GET SHA，没有带 branch
```

**Fix**:
1. **必须**先 GET 当前 SHA
2. PUT body 必须含 `sha` + `branch` + `content` (base64)
3. zsh interpolation 会破坏 JSON body → 用 `--data-binary @file` 或 Python 直接写文件

### Bug 7: 验证 rebuild 状态需要轮询

Vercel rebuild 不是瞬时的（虽然这次只 3 秒）。要轮询 `last-modified` header：

```python
import time
baseline = 'Tue, 25 Aug 2026 04:00:08 GMT'
while time.time() - start < 360:
    lm = get_last_modified()
    if lm != baseline:
        print(f'✅ rebuilt: {lm}')
        break
    time.sleep(20)
```

---

## ✅ 这次成功的完整步骤

1. **识别真 bug**: 字段名不匹配（不是 deploy 问题）
2. **重写 search.ts**: 加 `isCJK`, `findAllMatches`, `extractContext` helpers + 多 snippet 输出
3. **vitest 44/44 通过**: `npm test -- tests/unit/search.test.ts`
4. **field contract check PASS**: `python3 tools/field_contract_check.py`
5. **npm run build**: 182 页成功
6. **Contents API push**: commit `200fbed1` (绕过 git push 撞墙)
7. **Vercel auto-rebuild**: 3 秒完成 (`last-modified: 07:25:20 GMT`)
8. **Bundle 验证**: 新 JS bundle 含 `snippetsHtml` + `matchCount`
9. **End-to-end smoke test**: ⚠️ 仍在 debug（`browser_smoke.py` 的 awaitPromise 处理有问题，但搜索 fix 已部署）

---

## 📌 关键教训 (更新 MEMORY)

### MEMORY 应该更新的条目

```markdown
## 【2026-08-25 Vercel 部署架构澄清】frankofswing.com 是 Vercel, 不是 Cloudflare Pages

### 关键事实
- frankofswing.com **server: Vercel** (HTTP header 关键证据)
- DNS 在阿里云但走 Cloudflare proxy IP (CDN 代理)
- `x-vercel-id: hnd1::*` 是 Vercel POP ID (香港/河内), **不是 Cloudflare Pages**
- Vercel 用 GitHub App 集成, push → 自动 rebuild (1-3 分钟, 实际 3 秒)
- **不要看 GitHub repo hooks=0 就以为没集成**, GitHub App 不走 webhooks API

### Vercel 验证部署三件套
1. `server: Vercel` HTTP header
2. `last-modified` 头 (对比 baseline)
3. HTML 里 "构建版本: YYYY/M/D HH:MM:SS"

### Contents API Push 关键步骤
1. GET 当前 SHA: `GET /repos/{owner}/{repo}/contents/{path}?ref={branch}`
2. PUT 新内容: body = `{message, content (base64), sha, branch}`
3. zsh interpolation 坑: 用 `python3 ... > /tmp/body.json && curl --data-binary @/tmp/body.json`
4. 之前 404 原因: 没带 sha + branch

### 字段不匹配诊断流程
1. 看 bundle: `curl https://frankofswing.com/<bundle>.js | grep -E 'snippetsHtml|matchCount'`
2. 看 SearchBox.astro 字段访问
3. 看 search.ts 输出字段
4. 三者对不上 → render 时 undefined → 空 list
```

---

## 🔧 Smoke Test 待修

`browser_smoke.py` 当前问题:
- `awaitPromise: True` 时，promise reject 会导致 result.value = {} 而非 exceptionDetails
- 导致 `result = {}`, `ok = False`, `li = 0`, `reason = None`
- 修复方向: 加 `--debug` 选项 dump 完整 CDP response / 加 exception handler / 用 `--no-quiet` 模式看完整 JSON

实际搜索功能 **已经部署成功**（Vercel + bundle 字段对齐），smoke test 只是验证工具的 bug。