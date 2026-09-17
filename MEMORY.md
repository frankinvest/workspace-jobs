# MEMORY.md - Jobs's Memory

> Jobs's curated memories for web development tasks.

---

## 协作硬规则（Frank 2026-09-08 反复强调，最高优先级）

- Codex 要给小秘（OpenClaw）发需要她响应的消息时，**必须用 `send_group.py` 发文本消息**（自带 `<at>` mention），不能只在 final answer 卡片里写纯文本 `@小秘`——卡片里的 @ 不会写入 mentions，小秘收不到触发。
- 小秘 open_id（Codex 侧 app 上下文）：`ou_971ce940001d8281ee250dc47b4bc090`（不是 `ou_a051aff12fc5ccd6720fe9669daa1c4a`，后者是 OpenClaw 自己 app 的上下文）。

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

## 【2026-09-18 财经早餐重试窗口 + 熔断分级】Frank 拍板后上线

### 起因
launchd 原来只在 08:00 跑一次 finance_breakfast.py。Mr Dang 常在 8:00 之后才发帖，
08:00 抓不到就当天永不补，只能等 Frank 早上来问（09-12 / 09-14 / 09-17 连续三轮）。

### 改动 1：launchd 指向新包装器
- `~/Library/LaunchAgents/ai.finance-breakfast.daily.plist` 的 ProgramArguments
  由 `tools/finance_breakfast.py` 改为 **`tools/finance_breakfast_retry.py`**（08:00 单次触发不变）
  - ⚠️ 更正（同日 00:41）：触发点已从 08:00 一个改成 **08:00 / 09:00 / 10:00 / 11:00 四个看门狗**
    （`StartCalendarInterval` 数组）。原因：若抢到锁的那个实例中途挂掉，当天 08:00 那次已经用掉，
     没人再补跑；多挂几个触发点可以自愈。被锁挡住的触发 exit 0 跳过，不会重复推送。
- 原配置备份：`tools/_legacy/ai.finance-breakfast.daily.plist.bak-20260918`
- 回滚：把 ProgramArguments 改回 finance_breakfast.py，再 `launchctl unload/load`
- 包装器在窗口内（默认 08:00-11:00，每 30 分钟）反复调用原 pipeline，不改它的 6 个 step；
  带 flock 锁（两个实例同时跑，第二个 **exit 0 正常跳过**——launchd 和 OpenClaw cron 可能同时触发，
  被锁挡住不算故障；跳过会记进状态文件的 `lock_contention` 字段，双调度仍然可见）、
  成功后写 `/tmp/finance_breakfast_published_<date>.json` 标记

### 改动 2：失败原因分级（原来「抓 0 条」一律被当成源端没发）
| 现象 | 分类 | 退出码 |
| -------- | -------- | -------- |
| cdp 抓到的是前一天/别天的帖 → format「date 校验失败，拒绝写入」 | source_not_posted（源端还没发） | 3 |
| 圈子页渲染出 N>0 条帖子但今天没帖（真熔断） | source_not_posted | 3 |
| 页面一条帖子都渲染不出来（N=0）/ CDP 连不上 / 抓取异常 | fetch_failure（我们抓不到） | 4 |
| 抓取+排版成功但推送失败 | push_failure | 5 |

给调度器用的开关：`--exit-zero` —— 分类照写状态文件，但进程恒 exit 0。
OpenClaw 的 job 跑这个包装器时必须加，否则「源端今天没发」(3) 每天都会被记成任务失败（周日必现）。
实测（2026-09-18 00:38）：`--once --exit-zero` → exit 0，状态文件仍记录 `source_not_posted`。

**实测（2026-09-18 00:28）**：今天没发时**并不会熔断**——cdp 把「昨天」的帖子当候选抓回来，
format 的 date 校验拒绝写入，guard 再报「文件不存在」。这条路径以前一直被误判成抓取故障。
状态文件：`/tmp/finance_breakfast_retry_status.json`；日志：`/tmp/finance_breakfast_retry.log`

### 改动 3：send_group.py 发送后自检
- 出过事故：shell 引号把消息截断成半句（「…而且Cookie」），没人发现
- 现在发送后比对飞书回显（剥掉 @ 占位再比），不一致 / mentions 为空 → exit 2 并打印实际内容
- 长文本建议走 stdin：`python3 send_group.py - <<'EOF'`，彻底绕开引号

## 2026-09-18 OpenClaw 自动化调度整体停摆（09-07 起）— 只读证据

**症状**：7 个 cron job 全部 overdue，其中 6 个从未跑过（含 5 个每周 skill-collection-review）。
`cron_run_receipts` 表 0 行。

**只读证据**（`~/.openclaw/state/openclaw.sqlite`，表 `cron_jobs` / `cron_run_receipts`）：

| job | name | agent_id | 状态 |
| -------- | -------- | -------- | -------- |
| `9e09f65a-87e8-41f9-b281-778e597b45fd` | daily_catch_8am | **NULL（两边都空）** | last=09-06 08:00（周日 skip），next=09-07 08:00 |
| `ce064e9d-91ea-496d-97c8-151a1cadc4df` | daily_catch_8am | main | **从未运行**，next=09-08 08:00（agentTurn） |
| `239ab413` / `2e2c1d23` / `bcb2d0f4` / `3d81db1c` / `1aefea4b` | skill-collection-review-* | main/lip/jobs/taizi/hubu | **全部从未运行** |

- `openclaw cron status`：`enabled=true, triggersEnabled=true, jobs=7,`
  `nextWakeAtMs=1788739200000`（= **2026-09-07 08:00，11 天前，从未前进**）
- 7 个 job 里只有 `9e09f65a` 的 `agent_id` 与 `owner_agent_id` **都是 NULL**；其余 6 个
  `owner_agent_id` 也空但 `agent_id` 有值 → `Agent-less cron job has no resolvable owner` 单指它
- 网关 09-06 22:12 重启过（`logs/gateway-restart.log` + `gateway.log` startup outcomes），
  09-07 08:00 那次 tick 之后日志里再没有任何调度动作

**推断（未 100% 证实）**：09-07 08:00 的 tick 在给无主 job 解析 owner 时抛异常，
`nextRunAtMs` 没推进 → 整个 scheduler 停摆，连带 5 个每周任务一起死。
所以给这个 job 指定 owner 不只是「防双跑」，是解开全局停摆的钥匙。

**CLI 语法（实跑 `--help` 确认，别再猜）**：
- `openclaw cron edit` **有** `--agent <id>`；`openclaw cron show --help` 里没有（容易误判）
- 改命令用 `--command "<shell>"`（payload 本身就以 `sh -lc` 跑），**没有** `--argv`；
  cwd 用 `--command-cwd /Users/frank_bot/.openclaw/workspace-jobs`
- 停用用 `openclaw cron disable <id>`；**没有** `--enabled false`
- `cron list` 报 Agent-less 不影响 `cron get` / `cron status`（两者实测正常）

**配置**：真正的 OpenClaw 配置是 `~/.openclaw/openclaw.json`（12698B）。`agents.ownership` = `"explicit"`。

> ⚠️ **更正（2026-09-18 01:0x，我先前的判断是错的）**：我先前说「`agents.defaults` 没有
> `systemAgent` 键 → 别照报错文案改 openclaw.json」——那是**把「当前文件里没有」误当成
> 「schema 不允许」**。用 `openclaw config schema` 查实：`agents.defaults.systemAgent.agentId`
> 是**有效键**（title `System Agent Target`），`openclaw config get agents.defaults.systemAgent`
> 明确回 `Config path is valid but unset`。`agents.ownership="explicit"` 的 schema 原话是
> 「ambient channels / heartbeat / Talk / cron / bare CLI 必须解析到显式 owner，否则 fail closed」。

**根因（查 OpenClaw 源码 `dist/agent-id-C76WNTsz.js`）**：owner 解析顺序只有一层三元表达式——
`job.agentId || sessionKey 里的 agentId || configuredDefaultAgentId`，三者皆空就抛
`Agent-less cron job has no resolvable owner`。job ① 三者全空 → 必抛。
而 `cron edit` 在应用 patch **之前**要先解析「已存在那个 job」的 owner 做权限判断
（`dist/cron-Bygm2DMd.js`），所以 `--agent main` 救不了它自己（鸡生蛋）——**必须先设配置默认**。
**同一个异常也是全局停摆的机制**：store 里有一个无主 job，每轮 tick 解析 owner 都抛错 →
整轮 tick 挂掉 → 7 个 job 全不跑（不是 5 个 review 各自的问题）。

**正确修法**（顺序不能反，先 disable 5 个 review 再设默认 owner，否则 tick 一恢复就一起补跑刷屏）：
```bash
openclaw config set agents.defaults.systemAgent.agentId main --dry-run
openclaw config set agents.defaults.systemAgent.agentId main
openclaw cron list     # 不再报 Agent-less
openclaw cron edit 9e09f65a-87e8-41f9-b281-778e597b45fd --agent main \
  --command "python3 tools/finance_breakfast_retry.py --exit-zero" \
  --command-cwd /Users/frank_bot/.openclaw/workspace-jobs
openclaw cron disable ce064e9d-91ea-496d-97c8-151a1cadc4df
openclaw cron status   # nextWakeAtMs 往前推进 = scheduler 复活
```
回滚：`openclaw config unset agents.defaults.systemAgent.agentId`

**✅ 执行结果（2026-09-18 01:05-01:10，Codex 接手执行，已生效）**：
- 备份：`~/.openclaw/openclaw.json.bak-20260918-0105`、`~/.openclaw/backups/20260918-ownerfix/openclaw.sqlite.bak-0105`
- `config set` 原文回：`Change will apply without restarting the gateway.`（dry-run 先过）
- `cron list` 从报 Agent-less → 正常列出，① 的 Agent ID 立刻解析成 `main`
- ① payload 变成 `["sh","-lc","python3 tools/finance_breakfast_retry.py --exit-zero"]`，cwd 保持；② `enabled=false`
- **scheduler 立刻复活**：`cron_run_receipts` 0 行 → 7 行；01:09:09 一次性补跑所有 overdue job；
  5 个 weekly review 全部 `ok` 且 Next 从「9~10 天前」变成 `in 7d`；② 收据 `error: Cron job disabled by operator.`（预期）
- ① 补跑的第一次尝试 01:09:10：rc=1 → `source_not_posted`（可见 15 条），窗口到 11:00 → 今天由 gateway 这条实例持有 flock，launchd 08:00 等几枪撞锁跳过（预期）

**❌ 作废的预案**：原计划「先 disable 5 个 weekly review 再设 owner」——CLI 拒绝：
`Error: system-owned monitor jobs cannot be edited by cron clients`。
这 5 个 job 由 memory/skills 声明托管（declaration_key = `skill-collection-review:<agent>`），
cron 客户端改不了，只能让它补跑。

**📌 判据别用错**：`cron status` 的 `nextWakeAtMs` 在「① 仍 running（窗口到 11:00）」期间不会推进，
**不能**用它判断 scheduler 死活；应看 `cron_run_receipts` 有没有新行 + `cron list` 的 Next 列有没有从过去推到未来。

**📚 教训（Codex 自己犯的，代价 22 分钟）**：「当前配置文件里没有这个键」≠「schema 不允许这个键」。
要判断一个配置键是否有效，用 `openclaw config schema`（或 `openclaw config get <path>`，有效但未设会明确回
`Config path is valid but unset`），**不要拿现有 openclaw.json 的键清单当 schema**。

**catch-up 风险**：`nextWakeAtMs` 停在过去，owner 修好后 scheduler 一恢复可能立刻补跑所有逾期 job
（含 5 个 weekly review，每个一轮 LLM + 可能 announce）。出现补跑洪水就 `cron disable` 后白天再逐个 enable。

**✅ catch-up 实测（01:09:09）**：7 个 overdue job 一次性补跑完，5 个 weekly review 全部 `ok`
（1-33 秒），**没有发任何群消息**（delivery = not requested），不需要预先 disable。

### ⚠️ gateway cron command payload 有 10 分钟执行上限（2026-09-18 01:47 实锤）

我在 01:09 把 ① 改成**长驻窗口**（`finance_breakfast_retry.py --exit-zero`，内部循环到 11:00），
结果被 gateway 打死并每 10 分钟重派一轮，收据原文：

| 收据 | 起 | 止 | 结果 |
| -------- | -------- | -------- | -------- |
| 1 | 01:09:09 | 01:19:09 | error `cron: job execution timed out` |
| 2 | 01:19:39 | 01:29:39 | error `cron: job execution timed out` |
| 3 | 01:30:39 | 01:40:40 | error `cron: job execution timed out` |

（每次超时后 5 分钟重派，每次都重跑一遍 fetch 并抢一次 flock；到 11:00 会白跑 50 多次，
收据全 error 还会污染 08:00 的健康信号。）

**修法**：cron 只派**单次**命令，长驻窗口交给 launchd（launchd 没有这个超时）：
```bash
openclaw cron edit 9e09f65a-87e8-41f9-b281-778e597b45fd \
  --command "python3 tools/finance_breakfast_retry.py --once --exit-zero" \
  --cron "5 8 * * *"
```
实测 01:45:40 用新 payload 一次跑完（约 1 分钟）→ 收据 `ok`、`next` 推进到 08:05、无常驻进程。

**为什么把 08:00 挪到 08:05**：两条调度在 08:00 同时抢锁时，谁输了谁 `exit 0`——
若 launchd 输，08:00-09:00 的窗口就无人守（要等 09:00 触发）。挪到 08:05 后
launchd 08:00 先拿锁，① 只记一条 `lock_contention`；launchd 万一没起来，① 就是那一发兜底。

**📌 最终分工**：launchd（08/09/10/11 触发 + 内部 30 分钟重试到 11:00）= 窗口主体；
cron ①（08:05 `--once`）= 单发兜底；cron ② = 已停用。

**📚 教训（我的验证漏洞）**：宣布「闭环」前要等**一次完整生命周期**跑完。
我 01:09 只看到「收据有记录 + Next 列推进」就收工，漏掉了 10 分钟超时导致的反复重派。
