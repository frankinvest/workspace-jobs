---
name: red-ring-scraper
description: >
  抓取小红圈帖子（财经早餐）并发布到 GitHub Pages。
  触发条件：用户说"抓取财经早餐"、"提取小红圈帖子"、"下载 red-ring 图片"。
  本 Skill 是纯编排器，所有脏活由 shared/ 积木执行。
---

> ⚠️ **强制前置声明（Tool Intent）**
>
> 本 Skill 属于**高风险复合写操作**，涉及浏览器操作、文件写入、第三方 API 调用以及 GitHub Pages 发布，**绝对不适用"低风险免声明"的例外条款**。
>
> **执行任何 Step 之前**，必须先向用户输出以下标准块：
>
> \`\`\`markdown
> 🛠️ **Tool Intent**
> - 拟用工具/模块：[列出本轮将要调用的所有工具名称]
> - 核心入参：[展示关键参数，如目标 URL、日期、输出路径]
> - 预期目的：[简述本次调用的目的]
> \`\`\`
>
> **豁免边界**：纯截图查看（不写文件、不发布）属于低风险，仅需口头说明"先截个图看看"即可。
> 一旦涉及 `exec`、`file_write`、`build_full.py` 等写操作，立即触发声明义务。

> ⚠️ **强制规则**：所有截图任务必须使用 `shot2__capture_page` MCP 工具，禁止用 `browser(action=screenshot)` 替代。

# red-ring-scraper — 编排器规范（v11 熔断版）

**核心原则（SSOT）**：
- Skill **永远不**凭记忆填入 `post_id` 或历史日期
- "获取最新 ID" 是 `cdp_get_innerhtml.py --auto-latest` 的内置职责，脚本自身完成日期熔断
- Skill 只负责任务编排，不做 DOM 嗅探

---

## 🚫 绝对禁区 (Hard Boundaries)

1. **严禁干预基础设施**：本 Skill 的最终发布出口 **100% 且唯一只能依赖 Git Push 触发 GitHub/Vercel 流水线**。在任何情况下（即使遭遇网络超时或 000 报错），**绝对禁止**调用 `vercel` 相关的任何 CLI 命令（如 `vercel --prod`, `vercel alias`）。
2. **严禁擅自降级**：当 `cdp_get_innerhtml.py` 或 `build_full.py` 抛出非零退出码或异常时，Skill 必须立刻停止运行并向我汇报。**绝对禁止**擅自改用 `browser.evaluate` 或其他备用抓取脚本绕过既定的"脱壳"流水线。

---

## 架构图

User → Skill (编排器，只负责调用)
 │
 └── Step 1: exec build_full.py --auto-latest
 │
 ├── cdp_get_innerhtml.py --auto-latest
 │ ├── 导航到圈子页面
 │ ├── 解析所有帖子 → 定位今日财经早餐
 │ ├── 【熔断】今日帖子不存在 → exit 3，停止一切
 │ └── 提取 innerHTML → /tmp/<date>_post.html
 │
 ├── build_full.py（读取 HTML）
 │ ├── 上传图片 → GitHub
 │ ├── 渲染 HTML
 │ └── 触发 GitHub Pages
 │
 └── Step 2: 上报结果

---

## 日常抓取流程（auto-latest 模式）

> 🛠️ **本步声明**：调用 `exec`（build_full.py --auto-latest），**高风险写操作**，必须声明。
> 特别注意：禁止在本步的 Tool Intent 中凭记忆填入 `post_id` 或旧日期参数。

**执行命令（唯一正确方式）**：
```bash
python3 /Users/frank_bot/.openclaw/workspace/shared/build_full.py \
    AUTO \
    $(date +%Y%m%d) \
    --auto-latest \
    --output caijing_$(date +%Y%m%d).html
```

---

## shared/ 积木清单（SSOT）

| 模块 | 职责 | 接口 |
|------|------|------|
| `shared/cdp_get_innerhtml.py` | 自动找帖 → CDP 提取 | CLI: `<out> AUTO --auto-latest [--group-url]` |
| `shared/build_full.py` | 渲染 + 上传 + 部署 | CLI: `AUTO <date> --auto-latest [--output]` |
| `shared/network/batch_uploader.py` | 图片批量上传 | `GitHubUploader(token, repo).upload(path, b64)` |
| `shared/deploy/github_pages.py` | GitHub Pages 触发 | `GitHubPagesTrigger(token, repo).trigger_and_wait()` |

---

## 思想钢印（违反者视为系统性故障）

1. **禁止凭记忆填 post_id**：任何时候都不得在 Tool Intent 中写死历史 post_id
2. **今日帖子熔断**：auto-latest 找不到今日帖子时，脚本 exit 3，Skill 必须停止并通知用户
3. **日期来源优先级**：HTML 标题内日期 > 脚本自动推断 > 命令行传入参数
4. **禁止跳过熔断做猜测**：熔断发生后，Skill **不得**自行判断"也许明天发"而继续执行
