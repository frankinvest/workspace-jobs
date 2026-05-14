---
name: red-ring-scraper
description: >
  抓取小红圈帖子（财经早餐）并发布到 GitHub Pages。
  触发条件：用户说"抓取财经早餐"、"提取小红圈帖子"、"下载 red-ring 图片"。
  本 Skill 是纯编排器，所有脏活由 shared/ 积木执行。
---

> ⚠️ **强制规则**：所有截图任务必须使用 `screenshot-master__capture_page` MCP 工具，禁止用 `browser(action=screenshot)` 替代。

# red-ring-scraper — 编排器规范

**核心原则（SSOT）**：Skill 永远不硬编码 DOM 选择器、正则公式或渲染逻辑。所有提取和渲染逻辑下沉到 `shared/` 模块，Skill 只负责编排调用顺序和传递参数。

---

## 架构图

```
User → Skill (Orchestrator)
         │
         ├── Step 1: Browser — 导航 + 滚动加载评论
         │              ↓
         ├── Step 2: exec cdp_get_innerhtml.py — 通过 CDP 提取 innerHTML → /tmp/<date>_post.html
         │              ↓
         ├── Step 3: exec build_full.py — 读取 HTML → 上传图片 → markdownify 渲染 → GitHub Pages
         │              ↓
         └── Step 4: 向用户报告最终 URL
```

---

## Step 1 — Browser：定位最新文字帖子（过滤纯音频）

**目标**：在圈子页面找到最新一期**含图文正文**的帖子，跳过纯音频贴（.mp3 无正文）。

**嗅探算法**：
1. 导航到圈子页面，滚动加载所有帖子链接
2. 按 ID 倒序（最新优先）遍历每个候选链接
3. 对每个候选链接执行**快速 DOM 检测**（不需要等页面完全加载）：

```javascript
// 在候选帖子页面执行，快速判断是否为图文帖
(function(){
  // 图文帖特征：.ql-view 或 .post-body 内有文字段落
  var ql = document.querySelector('.ql-view, .post-body');
  if (!ql) return 'NO_BODY';
  var text = ql.textContent || '';
  // 过滤过短内容（可能是评论区片段）
  if (text.trim().length < 50) return 'TOO_SHORT';
  // 图文帖通常有多个 <p> 标签
  var paras = ql.querySelectorAll('p');
  if (paras.length < 2) return 'NOT_TEXT_POST';
  // 有图片更确认为图文帖
  var imgs = ql.querySelectorAll('img[src*=private]');
  return 'TEXT_POST|' + paras.length + '|' + imgs.length + '|' + text.trim().substring(0,60);
})()
```

**返回结果含义**：
- `TEXT_POST|<p数>|<图片数>|<摘要>` → 这是目标帖子，停止嗅探
- `NO_BODY` / `TOO_SHORT` / `NOT_TEXT_POST` → 纯音频/短帖，跳过，继续下一个

**从页面标题或 URL 提取日期**：
```javascript
// 获取帖子标题中的日期
document.querySelector('.ql-view, .post-body, h1, [class*=title]')?.textContent?.match(/\d{4}[-/]\d{2}[-/]\d{2}/)?.[0]
// 或从 URL 提取（精确到日期）：取当前日期字符串
var now = new Date(); var y = now.getFullYear(); var m = String(now.getMonth()+1).padStart(2,'0'); var d = String(now.getDate()).padStart(2,'0'); y + m + d
```
日期格式统一转为 `YYYYMMDD`（如 `20260513`）。

**导航 + 滚动加载评论**（在确认为目标帖子后）：
```
browser action=navigate targetId=<当前targetId> url=<目标帖子URL>
```

滚动加载评论（可重复 2-3 次）：
```
browser action=act targetId=<当前targetId> request={"kind":"evaluate","fn":"function(){window.scrollTo(0,document.body.scrollHeight)}"}
```

---

## Step 2 — CDP 提取 innerHTML

**目的**：通过浏览器 CDP 协议将页面正文 innerHTML 写入本地文件，供 Step 3 的 Python 消费。

**CDP WebSocket URL**：从当前浏览器 session 状态获取。
默认：`ws://127.0.0.1:18900/devtools/page/DCDBD120E79E4B69E755CAC03E39F11F`
（每次 gateway 重启后可能变化，以实际 browser status 为准）

**执行命令**：
```bash
python3 /Users/frank_bot/.openclaw/workspace/shared/cdp_get_innerhtml.py \
    /tmp/<date>_post.html \
    ws://127.0.0.1:18900/devtools/page/<TARGET_ID> \
    --selector main
```

**预期输出**：
```
[CDP] WS: ws://...
[CDP] Selector: main
[CDP] Output: /tmp/20260513_post.html
[CDP] ✅ 7080 bytes → /tmp/20260513_post.html
```

**失败处理**：如果 CDP 连接失败，降级使用 browser evaluate 直接获取（见下方应急方案）。

---

## Step 3 — build_full.py：渲染 + 上传 + 部署

**目的**：读取 `/tmp/<date>_post.html`，自动完成：
1. 提取正文 / 评论 / 图片 URL
2. 下载私有图片 → 上传 GitHub
3. markdownify 无损渲染（图片位置原位保留）
4. 上传 HTML 到 GitHub 仓库
5. 触发 GitHub Pages 构建

**执行命令**：
```bash
python3 /Users/frank_bot/.openclaw/workspace/shared/build_full.py \
    /tmp/<date>_post.html \
    <date_YYYYMMDD> \
    caijing_<date_YYYYMMDD>.html \
    "财经早餐 <date_YYYY-MM-DD>"
```

**参数说明**：
| 参数 | 示例 | 说明 |
|------|------|------|
| `<date>_post.html` | `/tmp/20260513_post.html` | Step 2 输出的文件路径 |
| `<date_YYYYMMDD>` | `20260513` | 日期，用于图片文件命名 |
| `caijing_*.html` | `caijing_20260513.html` | GitHub 仓库中的输出文件名 |
| `title` | `"财经早餐 2026-05-13"` | 页面标题 |

**预期输出**：
```
[build] innerHTML: 7080 chars | body: 6657 chars
[build] 正文图片: 10 张 | 评论: 8 条
  [OK] 1/10 caijing_20260513_img_01.jpg (165KB)
  ...
  [OK] 10/10 caijing_20260513_img_10.jpg (860KB)
[build] 图片映射: 10/10 成功
[build] 最终 HTML: 8923 bytes | GitHub 图片: 10 张
[build] HTML 上传: https://raw.githubusercontent.com/...
[build] GitHub Pages: OK https://frankinvest.github.io/caijing-daily/caijing_20260513.html

✅ 完成: {"html_file": "caijing_20260513.html", "images": 10, "comments": 8, "url": "..."}
```

---

## Step 4 — 上报结果

将 Step 3 返回的 `url` 字段以富文本形式发给用户，包含：
- 访问地址（GitHub Pages）
- 源文件地址（GitHub repo）
- 完成情况摘要（图片张数、评论条数）

---

## 应急方案

### CDP 连接失败时的降级策略

如果 `cdp_get_innerhtml.py` 报错（浏览器 gateway 重启等），改用 `browser evaluate` 直接获取 innerHTML：

```javascript
// 在 browser tool 中执行
(function(){
  var el = document.querySelector('main') || document.querySelector('.post-body') || document.body;
  var c = el.cloneNode(true);
  // ⚠️ 禁止删除任何节点！必须完整保留正文 + 评论区，供 build_full.py 提取评论
  return 'POST_START' + c.innerHTML + 'POST_END';
})()
```

将返回值手动写入文件：
```bash
# 在 exec 中执行
cat > /tmp/<date>_post.html << 'ENDHTML'
<粘贴 innerHTML 内容>
ENDHTML
```

然后继续 Step 3（`build_full.py`）。

---

## shared/ 积木清单（SSOT）

| 模块 | 职责 | 接口 |
|------|------|------|
| `shared/cdp_get_innerhtml.py` | CDP 提取 innerHTML → 文件 | CLI: `<output_file> [ws_url] [--selector]` |
| `shared/build_full.py` | 渲染 + 上传 + 部署 | CLI: `<html_file> <date> [output] [--title]` |
| `shared/deploy/github_pages.py` | GitHub Pages 触发 | `GitHubPagesTrigger(token, repo).trigger_and_wait()` |
| `shared/network/batch_uploader.py` | 图片批量上传 | `GitHubUploader(token, repo).upload(path, b64)` |

---

## 注意事项

1. **日期确定**：优先从帖子标题提取（如"2026年5月13日财经早餐"），格式化为 `YYYYMMDD`
2. **CDP WebSocket**：每次 gateway 重启后 browser status 会给出新的 CDP URL，注意更新
3. **输出文件**：永远是 `/tmp/<date>_post.html`，build_full.py 读取此文件
4. **GitHub Pages 延迟**：构建约需 30 秒，发布后可等待再截图验证
