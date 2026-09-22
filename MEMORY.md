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

## 2026-09-18 bridge 日志真实位置（群历史探针的数据源）

之前群里反复出现「~/Library/Application Support/Google/Chrome-redring 路径监控」和
「chromeredring_session.json watcher」——**这两个东西从来不存在**（全仓 grep 只命中
`tools/finance_breakfast.py` 里的旧默认值）。以后谁要删什么文件，先 `grep -rl <关键字> <各仓根>` 拿实证。

**真正的 bridge（lark-agents-bridge）日志**：

| 项 | 值 |
| -------- | -------- |
| 目录 | `/Users/frank_bot/.feishu-codex-bridge/logs/` |
| 文件名 | `<UTC 日期>.log`（**按 UTC 切**，不是本地日期。CST 01:52 时写的是前一天的文件） |
| 格式 | JSONL，一行一个事件 |
| 其它 | `daemon-stdout.log` / `daemon-stderr.log`（launchd 的 stdout/stderr，由 `ai.feishu-codex-bridge.bot.plist` 指定） |

**取「群历史」的字段**（`phase=intake` / `event=enter`）：
```json
{"ts":"2026-09-17T00:12:20.614Z","phase":"intake","event":"enter",
 "chatId":"oc_63b674661ade0a450fd36a02b2a492c0","msgId":"om_x...",
 "chatType":"group","sender":"ou_3047b4f390b7d880cdb20a9b874cec8c",
 "preview":"@_all 今天的财经早餐怎么又没有更新"}
```
`sender` = 发信人 open_id，`preview` = 消息前若干字。按 chatId 过滤即可还原某天群里的发言。

**用法**：诊断「今天没抓/没发」时，群侧看这份日志有没有人反馈，源侧用
`tools/cdp_get_innerhtml.py … --auto-latest --group-url https://www.red-ring.cn/group/27593`
（rc=0 今日帖在 / rc=3 今日帖不存在 / 其他 = 通路问题），两边合起来才能区分
`source_not_posted` 与 `fetch_failure`。

### ⚠️ 更正：cdp 的 rc=0 **不代表**「今日帖存在」（2026-09-18 01:58 实测）

上面那句「rc=0 今日帖在」是错的，实测原文（01:58，今天还没发）：
```
[AUTO] 今日日期: 2026-09-18，发现 15 条帖子
       [昨天 06:59] https://www.red-ring.cn/post/27593-2522222
       ...（15 条全是「昨天」）
[AUTO] 今日候选 15 条，选定主帖: https://www.red-ring.cn/post/27593-2522222
→ exit rc=0
```
`cdp_get_innerhtml.py --auto-latest` 的候选规则是「今天 / 昨天 / 精确日期」都算候选
（注释：*兼容作者深夜提前发帖*），所以**今天没发时它会把昨天的帖当候选抓回来并 exit 0**。

| 观察值 | 真实含义 |
| -------- | -------- |
| `发现 N 条帖子` | 圈子**列表页**渲染出的条目数（不是今日帖数） |
| rc=0 | 抓到了一份 HTML（可能是昨天的帖），**≠ 今日已发** |
| rc=3 | 连 今天/昨天 的候选都没有（列表渲染不出来，或全是很旧的帖） |
| **列表里有 `[今天` 开头行** | **唯一可靠的「源端今日已发」强信号** |
| N=0 | 渲染抖动：01:53、01:55 两次实测 0 条，01:57 之后恢复 15 条 |

**判定表（探针/分类器都按这个走）**：

| 条件 | 结论 |
| -------- | -------- |
| 列表含 `[今天` 且 docs/`JJC-<date>-*-原文.md` 或 `/tmp/finance_breakfast_published_<date>.json` 存在 | `published` |
| 列表含 `[今天` 但上面的文件都没有 | 源端已发、我们未发 |
| N>0 且无 `[今天` | `source_not_posted` |
| N==0 | `fetch_failure`（疑似抖动，等下一轮重试再判） |
| rc ∉ {0,3} 或 stderr 异常 | `fetch_failure` |

**群侧过滤要转时区**：bridge 日志按 UTC 切，一个文件跨两个本地日
（CST 09-17 08:00 → 09-18 08:00），按「今天」统计必须把 `ts` 转 +08:00 再比本地日期，
否则会把昨天的抱怨算进今天（实测就踩到了）。

### 🔁 N=0 的真实原因：连续调用 cdp 会自伤（2026-09-18 01:53-02:00 实测）

时间线（全部实跑，`--auto-latest`）：

| 时刻 | 结果 |
| -------- | -------- |
| 01:53 | 发现 **0** 条帖子 |
| 01:55 | 发现 **0** 条帖子 |
| 01:57 | 发现 15 条（全部 `[昨天`）|
| 01:58 | 发现 15 条（全部 `[昨天`）|
| 02:02 | 发现 **0** 条帖子 |
| 暂停 90 秒后再跑 | 发现 15 条 ✅ |

**结论**：N=0 集中在「短时间内连续调用」之后，隔一会儿就恢复 → 多半是我们自己
把页面打到限流/来不及渲染的**自伤**，不是源端问题，也不是登录态掉了。

**操作约定**：探针/诊断脚本**间隔 ≥2 分钟**再跑第二次；不要在 08:00-11:00 窗口内手动连打 cdp，
否则会把窗口自身的判定打糊（单次 N=0 会被分类成 `fetch_failure`，靠下一轮 30 分钟重试覆盖）。

### ✅ 探针 v3 验收通过（2026-09-18 02:00，Codex 实跑复验）

- 文件：`/Users/frank_bot/.openclaw/workspace/main/tools/finance_probe.py`（11621B，v3）——小秘的边界，只读探针
- 复验证据（Codex 实跑，非小秘转述）：`rc=0  found_count=15  found_today=False` → `verdict=source_not_posted`
- 群侧过滤已修对（`ts` → +08:00 → 与本地日期比）。Codex 独立复算 bridge 日志：09-17 本地 2 条、09-18 本地 0 条，与探针输出一致
- marker 路径 `/tmp/finance_breakfast_published_<YYYYMMDD>.json` 与 `tools/finance_breakfast_retry.py:72` 实际写入路径**完全一致**（判定规则可落地）
- `[今天` 检测有效：`tools/cdp_get_innerhtml.py:196-235` 的时间 label 就是「今天 HH:mm / 昨天 HH:mm / 小时前…」，文本扫描是可靠判据

**证据纠正（重要，别再引错）**：群里那句「我知道已经发了」出现在**本地 09-17 08:12 / 08:24**，指的是 09-17 的早餐，
不能拿来证明 09-18 已发。09-18 02:00 的真实状态是 `source_not_posted`（Mr Dang 通常 06:00-09:00 才发）。
「用户说发了」永远不等于「今天发了」——先按本地日期核 ts。

**边界裁定（2026-09-18 02:00）**：

- ❌ 不要往 `workspace-jobs/tools/` 新建探针（那是 pipeline 目录）；探针留在 `workspace/main/tools/`，pipeline 侧只读引用
- `MEMORY.md` 由 Codex 统一追加维护（小秘在群里给要点、Codex 落笔），避免覆盖这个 20KB+ 共享文件

### ⚠️ App Secret 取不到的老坑：hostname 漂移（2026-09-18 第二次翻车，已加兜底）

**症状**：`lark-agents-bridge secrets get` 返回 `Unsupported state or unable to authenticate data`，
`send_group.py` / `lark-cli` 全部拿不到 secret → 我 @小秘 的文本通道整个断掉（卡片不受影响，桥接 daemon 内存里有凭证）。

**根因**：keystore 密钥 = `pbkdf2(f"{hostname}|{username}", .keystore.salt)`（见
`lark-agents-bridge dist/cli.js:547`）。本机 hostname 会在 **`anonymous`** 和 **IP（如 192.168.1.6）** 之间漂移；
漂到 IP 的那段时间，派生出的密钥和加密时不一致 → 解不开 `secrets.enc`。09-07 已经发生过一次同样的故障
（小秘 memory 2026-09-07.md:516 有记录），当时靠重设 secret 恢复。

**踩坑经验（重要）**：排查时不要用 `hostname` 命令的输出当种子——它和 node 的 `os.hostname()` 可能给出不同值
（11:13 实测：shell 给 `192.168.1.6`，node 给 `anonymous`）。判断「当前种子是什么」要用 node：
`node -e "console.log(require('os').hostname())"`。

**已做兜底**：`send_group.py::_secret_from_keystore_fallback()` —— CLI 取不到值时，直接用 node 复刻同一套
pbkdf2+aes-256-gcm，按候选种子（当前 hostname / `anonymous` / `localhost` × 当前用户 / `frank_bot`）逐个试解，
只回明文给调用方、不打印。2026-09-18 16:50 实测（故意把 CLI 从 PATH 摘掉）发出成功。

**根治**（可选，需要 Frank 的 sudo）：`sudo scutil --set HostName frank-bot-de-mac-mini` 把主机名固定，
否则每次网络环境变化都可能再漂一次，届时所有**新起**的进程都取不到 secret（桥接 daemon 只要不重启就还活着）。

### 📈 「纵横东西」新增美债收益率（2026-09-18 16:51-17:00，Frank 指令 → Codex 整单交付）

- 需求：在「纵横东西」加 3 个月期 / 10 年期美债收益率
- 落点（两处，都在 workspace-jobs）：
  - `api/global-markets.js`：新增分类 `us_bond`（label「美债收益率」）+ 两条 item：`^IRX`（3 个月期，单位 %）、`^TNX`（10 年期，单位 %），源 yahoo（与 WTI / 黄金 / 日经同源）
  - `src/components/GlobalMarketsBoard.astro`（v11）：`CATEGORY_ORDER` 两处（frontmatter + 客户端脚本）加 `us_bond`（排在 `us_index` 之后）；`MARKET_HOURS_BY_CODE` 加 `^IRX`/`^TNX` = 北京 20:00 → 次日 05:00（美债现货，夏令时近似），否则时间徽章显示「—」
- 部署 + 验证（只看线上，不看本地）：`npm run build`（207 页）→ `tools/system_api_pusher.py`（Contents API）→ 线上 `https://frankofswing.com/api/global-markets?cb=<随机>` 返回 8 个分类 `[energy, precious, metals, agriculture, us_index, us_bond, asia_index, cn_index]`，`^IRX=3.965%(-0.126%)`、`^TNX=4.947%(-1.179%)`，source=yahoo；线上 `_astro/GlobalMarketsBoard.astro_astro_type_script_index_0_lang.*.js` 已含 `us_bond`/`^IRX`/`^TNX`
- 口径：`^IRX` 是 13 周美债**贴现率**，业内通常就当 3M 收益率用；要严格 3M 常数到期收益率（CMT）得换财政部日频源（FRED `DTB3`/`DGS10` 备选，本次没用上）
- 未定项（Frank 未表态，现维持）：① 独立 tab，不并进「美股指数」；② 不进「重点行情」（仍是 9 个）。两项都是「一行改动」
- 数据刷新：API 缓存 5 分钟；`asOf` 要等美债开盘（北京 20:00）之后那一档才会跳到当日，之前一直是上一交易日尾盘（实测 09-17 14:59 ET = 09-18 02:59 CST）

### 🧭 两次「skill 不存在」误判：两边 skill 根目录不同（2026-09-18 纠正）

- 群里记的「`frankofswing-dev` skill 不存在」**只对 `~/.openclaw/skills/` 成立**——那是小秘（OpenClaw）侧的 skill 根目录
- Codex 侧真实存在：`/Users/frank_bot/.codex/skills/frankofswing-dev/SKILL.md`（1541B，Sep 7 20:01）
- 结论：引用 skill 前先**在自己那侧的根目录** `ls` 实锤；「我这边没有」不等于「不存在」，别写成「伪权威引语」

### 🚨 误报纠正：MEMORY.md「被第三方截断」其实是我自己的写脚本 bug（2026-09-18 17:03）

- 现象：我 17:03 追加记录后，`workspace-jobs/MEMORY.md` 从 28226B 变成 2491B，只剩最后一段（「否则每次网络环境变化…」）
- 我当时的判断：「有一次不是我的写入，把 28KB 历史压成 1.4KB」——**错**。已在群里发出，本条目撤回它
- 真因：我的脚本写成 `new = old + """…"""`，而 `old` 只是「文件最后一段」那个字符串；正确应是 `new = d + """…"""`（`d` 才是读到的全文）。
  证据：Codex session rollout `~/.codex/sessions/2026/09/06/rollout-2026-09-06T16-51-32-01a075ea-….jsonl` 第 12255 行保存了原始命令
- 影响：只有本地文件被截断；我立刻从 GitHub 取回 28226B 版本（sha256 `9311eaad1991`，与远端逐字节一致）还原后重新追加，远端没有被破坏过
- **教训（重要）**：宣布「被别人覆盖 / 第三方写入」之前，先复核自己的读写脚本。read-modify-write 脚本必须：
  (a) 用「读到的全文」变量拼接，别拿锚点/末段字符串当基底；(b) 写前断言新内容更长（`len(new_bytes) > len(old_bytes)`）；(c) 写后回读逐字节校验
- 顺带核实（本次无异常）：OpenClaw agent `jobs` 的 workspace 就是 `workspace-jobs`，理论上 memory-core 会写这个 `MEMORY.md`；
  但 17:02–17:03 没有任何 cron 运行记录（`cron_run_receipts` 最新是 08:05 与 03:00），本地也没有别的写入进程持有该文件 → 与 OpenClaw 无关

### 📰 2026-09-20 早报：周末/特殊标题的贴也能走「财经早餐标准流程」（Frank 11:5x 指令）

**背景**：09-19（周六）源端确实没发；09-20（周日）源端 08:01 发了「大宗商品情况更新 2026年9月20日」，
但 08:00-11:00 窗口 5 枪全部判成 `source_not_posted` —— 真因不是源端没发，是流水线**选帖规则要求
页面文本含「财经早餐」**，周末/特殊贴被漏掉后退回旧贴，再被日期校验拦下。

**三处改动（都在 tools/，已推 GitHub）**：

- `tools/cdp_get_innerhtml.py`：选「今日主帖」改成「按列表时间标签（今天/昨天/today）+ 帖子 ID 最大」，
  仅排除「有声版/.mp3」，不再要求标题含「财经早餐」
- `tools/finance_breakfast.py::extract_title`：优先取帖子自身标题元素（`.post-body` 里 `text-darker`）——
  原来先找 `<h1>`，会命中圈子简介「知乎人气答主…你的定制财经早餐」，把标题带偏
- `tools/finance_breakfast.py`：① 日期校验去掉「标题必须含财经早餐」前置条件（周末贴标题也带日期，照校）；
  ② 标题归一化——财经早餐类仍统一成「财经早餐 YYYY-MM-DD」，**非财经早餐的贴保留原贴标题**（对齐 09-05 先例）

**执行 + 验收（标准流程，非旁路工具）**：`finance_breakfast.py --date 20260920` 分步
fetch ✅（选定 27593-2523314，今天 08:01）→ format ✅（标题「大宗商品情况更新」/ 37 图 / 19 评论）→
images（按约定跳过）→ guard ✅ → tldr ✅（9 条：macro×3 / industry×3 / commodity×3）→ push ✅
（本地 commit `c973cbf`，Contents API `9896a91d`）。线上 `https://frankofswing.com/docs/jjc-20260920-001-原文`
→ 200；首页「今日速览」显示「从 2026-09-20 财经早餐提取」并链到该篇。

**注意**：以后引用历史 docs 时，**「docs 里没有某天」只说明流水线当时没抓到，不等于源端没发**——
判断源端一律直接看圈子列表（09-20 就是这么翻案的）。

### 🔌 2026-09-20 机器重启（10:14:57）把早报窗口掐断

- `kern.boottime` = 2026-09-20 10:14:57（上次开机 09-05 13:10，连续跑了 45 天）
- 后果：/tmp 被清空（发布标记/raw/状态文件全没）；08:00-11:00 的重试循环在 10:01 那枪之后被 SIGTERM，
  **10:30 与 11:00 两枪根本没跑**；OpenClaw 随重启复活后在 10:21:31 注册内置 `heartbeat-main`
  cron（10:24 `skipped: no-route`，无害——**它不是任何人手动加的**）
- 当天补救：11:53-11:58 手动按标准流程把 09-20 补发（见上条）
- 待 Frank 拍板：给 `ai.finance-breakfast.daily.plist` 加 `RunAtLoad=true` + 包装器加「已过窗口结束就只记录不跑」，
  以后重启也能把窗口补完（**未实现，等指令**）

### 🔐 2026-09-20 keystore 二次漂移（重启后 daemon 用漂移中的种子重新加密）

- 症状：11:5x 发消息时 `lark-agents-bridge secrets get` 报 `Unsupported state or unable to authenticate data`
- 查因：`~/.feishu-codex-bridge/secrets.enc` 的 mtime 是**当天 10:23**（重启后桥接 daemon 重新加密），
  当时 hostname 是漂移值（IP），事后 hostname 回到 `anonymous` 就再也解不开
- 处置：从 `secrets.enc.broken_20260918`（09-18 被**误命名**成 broken、实际用 `anonymous|frank_bot` 能解开的那份）
  取回 secret，按同一套 pbkdf2+aes-256-gcm 用当前种子重新加密回 `secrets.enc`，原文件备份为
  `secrets.enc.pre-rekey-20260920`；`secrets get` 恢复正常（**文件名不可信，能解开才是真的**）
- 加固：`send_group.py::_secret_from_keystore_fallback()` 的候选种子从 3 个 hostname 扩到
  「当前 nodename / anonymous / localhost / 本机所有 IPv4 / scutil 的 ComputerName+LocalHostName+HostName」
  × 当前用户；CLI 挂掉也能发
- 根治不变：`sudo scutil --set HostName frank-bot-de-mac-mini`


### ✅ 2026-09-20 21:4x hostname 漂移**根治完成**（Frank 亲自跑了 sudo）

- Frank 执行：`sudo scutil --set HostName frank-bot-de-mac-mini`
- 验证：`scutil --get HostName` / `hostname` / `node -e "console.log(require('os').hostname())"` **三者现在一致**
  都是 `frank-bot-de-mac-mini`（此前会漂成 `anonymous` 或 `192.168.1.x`）
- 随后的收尾（Codex 做）：keystore 用**稳定种子** `frank-bot-de-mac-mini|frank_bot` 重新加密
  （旧文件备份为 `~/.feishu-codex-bridge/secrets.enc.pre-rekey-20260920-anonymous-seed`），
  然后实测 `lark-agents-bridge secrets get` **正常返回 32 字符**、`tenant_access_token` 返回 `code:0`
- `send_group.py` 的多候选种子兜底**保留**（作为保险：万一 hostname 再被别的工具改回去也能发）
- 结论：**这条反复复发 3 次（09-07 / 09-18 / 09-20）的「通道断线」问题到此根治**——
  以后判断通道是否健康，先看 `scutil --get HostName` 是否仍是 `frank-bot-de-mac-mini`


### 💼 2026-09-21 持仓变更（Frank 指令，当天上线）

- 卖出 **华夏银行** 3200 股（成交价 **6.23**）→ 持仓 25900 → **22700 股**，成本 6.719 不变
- 买入 **药明康德**（`603259`）100 股 @ **163.2**（新增）
- 买入 **昭衍新药**（`603127`）100 股 @ **46.57**（新增）
- 落地：`data/stock_holdings.json` 19 → **21 条**（只在末尾追加，不动原有顺序）→ `npm run build`（209 页）→ Contents API 推送 → 线上实测
- 线上核对（`data-code/data-shares/data-cost`）：600015 → 22700/6.719 ✅、603259 → 100/163.2 ✅、603127 → 100/46.57 ✅，总数 21 ✅
- 注：卖出价只作交易记录（`stock_holdings.json` 只存「股数 + 持仓成本」，不记已实现盈亏）

- ⚠️ **上面这条当天被 Frank 纠正**：他说「买卖会影响持仓成本」——原来的做法（快照 + 手工填成本）成交后成本不跟着变，算出来的持仓盈亏不对。当天下午已改成下面这套（旧结论作废：**不再手工改 cost**）

### 🔁 2026-09-21 持仓成本改「按交易流水推算」（Frank 指出计算逻辑不对）

- **口径**：券商常用的**摊薄成本** = (期初金额 + Σ买入金额 − Σ卖出金额) / 当前股数。
  卖出价高于成本会拉低成本，低于成本会抬高成本 → 所以「买卖都会改成本」
- **新增 `data/trades.json`（唯一数据源）**：`opening`（期初持仓快照，成本取券商 2026-09-18 口径）+ `trades`（每笔 `date/code/name/side/shares/price`）
- **新增 `tools/recalc_holdings.py`**：读 trades.json 推算，写回 `data/stock_holdings.json`（前端只读这个文件，组件不用改）。
  支持 `--dry-run` 先看结果；清仓（股数 ≤ 0）不进持仓表并打印提示
- **今天这笔的实际效果**：华夏银行卖 3200@6.23 → 摊薄后成本 **6.719 → 6.788**（6.23 低于成本，剩余成本被抬高）；
  药明康德 100@163.2、昭衍新药 100@46.57 = 成交价。线上实测（`data-cost`）三只都对，21 只
- **以后流程**：Frank 只要发「日期 / 代码 / 买卖 / 股数 / 成交价」，我加进 trades.json → 跑 recalc → build → 推 → 线上核验；**不再手工改 `data/stock_holdings.json`**
- **未做的选项**（等 Frank 要）：① 若他其实想用「加权平均（卖出不改成本）」口径，改一处公式即可；② 已有的流水可以直接扩展成「已实现盈亏」展示

- ✅ **2026-09-21 Frank 拍板（两句话）**：
  1. 「行」→ **摊薄成本口径定稿**（买卖都改成本），不再改公式
  2. 「不用显示盈亏，还是按当前设置的字段去更新就行」→ **不加「已实现盈亏」UI**（不做这个展示）；
     `data/stock_holdings.json` 的字段保持 `code / name / shares / cost` 四个不变
- **定稿流程**（以后一律照此）：Frank 发「日期 / 买卖 / 代码 / 股数 / 成交价」→ Codex 追加到 `data/trades.json`
  → 跑 `tools/recalc_holdings.py`（摊薄推算）→ `npm run build` → Contents API 推送 → 线上核验 `data-cost`
  → **永不手工改 `data/stock_holdings.json`**（它是生成物）


### 🐞 2026-09-21 「昭衍新药持仓 0」根因 = 取价接口硬上限 20 只

- **现象**：Frank 看站点，昭衍新药那行显示 0（仓位/盈亏都是 0）
- **根因**：`api/price.js` 里 `codes...slice(0, 20)` —— 持仓从 19 只涨到 **21 只**后，
  **第 21 个 code 被静默丢掉**（昭衍新药正好排在最后），前端拿不到价就把 仓位/盈亏 渲染成 0
- **修法**（2026-09-21）：
  1. `api/price.js` 上限 **20 → 200**（错误提示同步改）
  2. 第一轮没拿到价的代码 **补一轮重试**（400ms 后），压掉单源偶发超时/限流
  3. `public/portfolio.js`：**缺价时显示 `--` 而不是 0**（避免再被误读成「持仓 0」）
- **验证**：线上 `/api/price` 连续 6 次返回 **21/21**（`603127 → 46.74`）；页面显示 昭衍新药 市值 4,674 /
  仓位 0.83% / 盈亏 +17 元
- **教训**：**任何「按条数截断」的硬上限（slice / limit / max-items）在数据量增长后都会静默丢数据**；
  以后新增持仓/行情项，先 grep 一遍 `slice(0,` 之类上限，别等用户看到 0 才发现


### 🎨 2026-09-22 持仓侧栏改版（Frank 指令：突出今日盈亏）

- **需求**：突出「总账户今日盈亏」+「个股今日盈亏」；「持仓盈亏」弱化或折叠
- **对齐过程**：按 frankofswing-dev「出方案 → 讨论 → 确认 → 再实现」——Codex 出方案 A（含 ASCII 布局图）→
  小秘提 8 个对齐问题 + 5 条补充看法 → Codex 逐条收口（否掉 3 条：按今日涨跌重排会跳动、金额不遮罩会泄露、
  hover 单行展开在手机上没有 hover）→ 小秘回 ok → 才动手
- **落地**（`src/components/PortfolioSidebar.astro` + `public/portfolio.js`，纯 UI）：
  - 汇总区：**今日盈亏**升为 hero（大字号 + 加粗 + 红绿，显示「金额 + 百分比」，金额仍受密码锁）；
    总市值 / 持仓盈亏 / 收益率 压成一行小字；新增「持仓盈亏金额 ▸」全局开关
  - 个股行：名称+现价 → **今日（百分比 + 金额，红绿）** + 右侧小字仓位 → 仓位进度条 → **持仓盈亏（灰色小字 + 百分比）**，
    金额默认折叠、由全局开关控制
  - 新增 `data-field="todayPnlAmount"`（个股今日金额）和 `#portfolio-total-today-amount`（账户今日金额）
- **没动的**：密码锁逻辑（金额类一律遮罩）、60 秒轮询、数据源、持仓排序（仍按仓位降序）
- **验证**：线上 markup 与 `/portfolio.js` 都已更新（hero=1、21 行 todayPnlAmount、`initPnlToggle`），
  当日实测账户今日盈亏 +1,614 元 / +0.29%（涨最多瑞芯微 +1,980、跌最多华夏银行 −454）


### 🖼️ 2026-09-22 老文章图片全黑：根因 = 热链了红圈的 7 天签名图（待 Frank 选型）

- **现象**：Frank 看 9.14 那期「文字在、图没了」
- **根因（实测）**：红圈图片是**带 7 天有效期的签名 URL**（`?e=<到期时间戳>&token=...`），而流水线按老约定
  **跳过图片本地化**、直接热链 → 每篇文章发布 7 天后图必然 403
  - 9.14 的图 `e=1789945190` = 09-21 06:59 到期 → 实测 **403**
  - 9.21 的图 `e=1790549988` = 09-28 到期 → 实测 **200**
  - 去掉签名 / 换后缀 / 借别的图 token 共 4 种变体 → 全 403（过期后旧链接永久失效）
- **文章本身没问题**：9.14 页面 200、10 个 `<img>` 都在，本地与远端 md 都在（17276B）
  —— 小秘 19:14 报的「整篇 404」是她查错了文件名（`JJC-20260914-001-地阶功法卷十八…` 是 09-12 那篇）
- **规模**：110 篇带图 / **1401 张** / 平均 338KB → 原图 ≈463MB，webp ≈140MB，≤1200px+q72 ≈**90MB**
- **恢复路径已验证（关键）**：用登录态打开历史帖子能拿到**新签名 URL** —— 实测 09/14 的贴
  （`post/27593-2520532`，圈子列表里能按日期找到）抓到新签名并成功下载（181KB JPEG / 290KB PNG）。
  也就是说**图片没有永久丢失**，随时可以重爬回填
- **二进制推送可行**：`system_api_pusher.py --dry-run public/images/caijing_20260601_img_01.png` 通过（Contents API 支持 base64 二进制）
- **三个候选方案**：A 本地化入仓（推荐，90~140MB）/ B 外部图床（Vercel Blob、R2，要凭据）/ C Vercel 图片代理（只对未过期图有效）
- **待 Frank 拍板**：① A 还是 B；② 压缩档位；③ 回填全部还是最近 30 天。定了之后还要改流水线
  （`finance_breakfast.py` 的 images 步骤：从「跳过本地化」改成「下载 + 压缩 + 站内引用」）
