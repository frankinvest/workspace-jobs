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
