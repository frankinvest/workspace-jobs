# MEMORY.md - Jobs's Memory

> Jobs's curated memories for web development tasks.

---

## About Frank

- Telegram: lick789
- 北京时区（GMT+8），晚上效率最高
- 职业：自动驾驶算法工程师
- 副业：投资理财
- 沟通偏好：详细风格，实时优先
- 关键要求：绝对避免事实性错误

## Frank 的网站项目需求

### 网站目标
- **用途**: 财经信息展示网站
- **内容**: 财经信息、宏观新闻、股票分析
- **更新频率**: 每日自动更新

### 技术要求
- 开发过程简单
- 不容易出错
- 不需要美观，使用为主
- 成本最低
- 以后由 Jobs 全权维护

---

## 项目进度

### 2026-03-26
- [x] 市场数据接入
  - 使用腾讯行情 API 获取数据（绕过 VPN 拦截）
  - 大盘指数：上证、深证、创业板、科创50
  - 热门个股：茅台、平安银行、招商银行、中国平安、五粮液
  - 市场概况：涨停/跌停数量
- [x] 创建 MarketBoard 组件展示指数
- [x] 创建 StockList 组件展示个股
- [x] 设置每日定时更新 cron（每天 08:00）
- **主站地址**: https://workspace-jobs.vercel.app
- [ ] 内容源接入（待 Frank 提供）

### 2026-03-13
- [x] 技术方案：静态网站（Astro）
- [x] 框架搭建完成
- [x] Vercel 部署成功
- [x] 界面优化完成（金色渐变、卡片布局、动画效果）

---

**决定**: 放弃 frank-invest-blog（GitHub Pages），只维护 workspace-jobs.vercel.app

## 【2026-06-26 frankofswing.com 部署平台 + Astro filter】

### frankofswing.com 是 Cloudflare Pages (不是 Vercel)
- 错误 ID `hnd1::*` 是 Cloudflare Pages 命名空间
- workspace-jobs.vercel.app 仍存在, 是冗余 Vercel 部署
- 推送 GitHub → Cloudflare Pages 自动 build (git push 触发)

### Astro 首页 filter 规则 (index.astro 第 77 行)
- tag 判定写死, 命中任一即 '财经早餐' section:
  ```js
  if (doc.id.includes('财经早餐分析') || doc.id.includes('年报') || doc.id.includes('原文') || doc.id.endsWith('.html')) {
  ```
- 不满足 → tag='其他' → 首页 filter 掉 (但详情页 `/docs/<id>/` 仍可访问)

### MR Dang 精华贴命名规范 (新)
- 跟 JJC-20260330-001-天阶功法卷八-原文.md 一致
- 格式: `JJC-YYYYMMDD-NNN-<主题>-原文.md`
- NNN 序号: 早餐是 001, MR Dang 精华用 002/003/...
- 标题: 用 frontmatter `title: "..."` (真正显示的标题)

### publish_mr_dang_post.py 待优化
- 当前生成 `mr_dang_<category>_<date>.md` 格式, Astro filter 不识别
- 待加 --astro-slug 选项, 默认走 JJC-YYYYMMDD-NNN-<title>-原文.md
- 待加 frontmatter title 自动提取 og:title (避免 fallback 字符串)

## 【2026-06-29 publish_mr_dang_post.py v2 修复】bs4+markdownify 渲染（跟 finance_breakfast 一致）

### Frank 反馈
"我看到了，但是抓取流程肯定不对，没有按照目前定时的财经早餐的抓取方式，因为我看到文字排版和图片插入方式都是错的"

### 根因
- 旧版 `parse_redring_post()` 用 `content_div.get_text("\n", strip=True)` 把 HTML 标签全剥
- 图片单独收集丢到末尾 "### 配图" 区块，丢失原位置
- 文字不连贯，红色/字号等样式全丢
- 跟 `finance_breakfast.py` 的 `markdownify(body_html, heading_style="atx")` 渲染方式完全不一致

### 修复 (commit ad001159)
- `parse_redring_post()` 改用 `bs4` 保留 `ql-view` 容器内的 HTML 字符串 (`body_html`)
- `render_markdown()` 用 `mf.markdownify(body_html, heading_style="atx", link_style="inlined")` 转换
- 去掉末尾"### 配图"区块（图片自然嵌在原段落）
- 加 `--title` 参数：精华贴常常无 h1，需手动指定真正标题
- 加 `--date YYYYMMDD` 参数：抓历史贴必填（默认 shanghai_today_str()）
- import: 加 `import markdownify as mf` + `import html as html_mod`

### 验证
- 5.16 帖子: `JJC-20260516-001-地阶功法卷十二宏观研判-原文.md`
- 旧版 11717 字符 → 新版 12400 字符（多出来是 markdownify 展开的段落/图片 markdown 标记）
- 排版跟财经早餐 100% 一致: 段落分隔 + **粗体标题** + `[链接](url)` + `![](图片)` 内联

### Frank 抓单篇帖子的新规范
1. 走 `publish_mr_dang_post.py --url <post_url> --title "<真标题>" --date <YYYYMMDD> --slug <slug>`
2. Slug 沿用 `JJC-YYYYMMDD-NNN-<主题>-原文.md` 命中 frankofswing.com 首页 filter
3. 精华贴（如《地阶功法卷X》）真标题需手动传 `--title`，因为页面上常常只有正文首段

## 【2026-08-10 daily_catch.py 永不抓有声版】周日 breakfast race condition 修复

### 事故
- 2026-08-10 周日 8AM Mr Dang 只发了"有声版"（post 27593-2499301 + 2498515），**没发文字版财经早餐**（评论里都在喊"审核中""文章被删了""7:42 了早报还没放出来"）
- daily_catch.py 8AM 抓 list 候选只有 2 条"有声版"，**退化到 candidates[0]** 抓了 2499301 有声版推送
- 9AM Mr Dang **补发了文字版**（post 27593-2499300）—— 但 8AM cron 已错过

### Frank 反馈（11:19 GMT+8）
"今天的财经早餐怎么回事，怎么收集了有声版？每天都会有两条，一条是原文也就是文字版，一条是有声版，你需要同步的是原文，不需要同步有声版"

### Frank 实际认知有误（需要沉淀）
- Frank 说"每天都会有两条"→ 实际**不每天都有**，有时 Mr Dang 只发音频版（8/10 周日）有时只发文字版
- 真正规律：**"财经早餐"文字版是主要同步目标**，有声版是音频附件不抓
- 之前代码把"无早餐候选时退化到第一条"是错的，应该**直接跳过**

### 修复（commit 7a6fa9158f3c）
- daily_catch.py 第 237 行 else 分支加 `audio_only = all('有声版' in title for c in candidates)`
- 如果 audio_only=True → 返回 None 跳过整个任务（不发任何东西）
- 配合 today_only 防护：今天只有有声版 → 跳过；今天只有文字版 → 抓；两个都有 → 抓文字版

### 顺手修复
- is_today_time 函数扩展支持"X 分钟前"/"X 小时前"相对时间（之前只认"今天 XX:XX"硬前缀，导致 8AM 第一次跑报"今日暂无帖子"）
- 7/18 race condition 跟今天同根因——list 加载时机跟发帖时点冲突

### 9AM backup cron 新增（ad966ba6-66a8-4e7a-b86f-38c19f35d70d）
- `daily_catch_9am_backup`: `0 9 * * *` Asia/Shanghai
- 适用场景：Mr Dang 8AM 时只发有声版, 9AM 才补文字版
- 先检查 docs/JJC-<today>-001-原文.md 是否已存在 → 已存在则 exit 0
- 不存在则走完整 daily_catch.py 流程
- delivery: announce → feishu:ou_8fab5d81798938a771ad4be7bb04593c

### 手动补跑今天 8/10 流程
1. cdp 抓 post 27593-2499300 全文（29736 chars，含就业数据 + CPI 数据 + 评论 19 条）
2. 写 raw cache 到 /tmp/finance_breakfast_raw_20260810.html
3. finance_breakfast.py --date 20260810 --step all 跑通 fetch/format/images/guard
4. push 步骤 system_git_pusher.py 超时（git push 撞墙老问题）
5. Contents API 兜底推 docs/JJC-20260810-001-原文.md → commit 2a44ca6843c9
6. Contents API 删错的 JJC-20260810-001-2026年8月10日有声版-原文.md → commit b320985549c8
7. Contents API 推更新的 daily_catch.py → commit 7a6fa9158f3c

### ⚠️ .git-credentials token 过期 (重要隐患)
- .git-credentials 一直存的是 8/7 Frank revoke 的旧 token `ghp_s9yB...aJej`
- 8/7 补推 8/6+8/7 时 Frank 给的新 token `ghp_Oyx4...8PiF` 我只写在内存里，没回写 .git-credentials
- 今天 9:19 用 Contents API 第一次发现 401 Bad credentials 才暴露
- **已更新**: `sed -i '' "s|ghp_s9y…aJej|ghp_Oyx4…8PiF|" ~/.git-credentials && chmod 600`
- **以后新 token 必须同步写 .git-credentials**, 不只是 sed 即时替换

### finance_breakfast.py git push 超时老问题（再次发生）
- 9:22 finance_breakfast.py push 步骤 system_git_pusher.py 超时 120s
- Contents API fallback 救场成功
- 建议: finance_breakfast.py step_push 默认改成 Contents API, 不要 git push 失败才 fallback
