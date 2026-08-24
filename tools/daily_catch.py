#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
daily_catch.py — 每日红圈文章抓取与发布（统一入口）

🎯 逻辑（替代 finance_breakfast.py 单点调用）:
  1. 抓 list 主页 main.innerHTML (走 cdp, 不 navigate 到 post)
  2. 解析 list 找最新一条 post URL (按发布时间倒序, 排除置顶帖)
  3. navigate 到 post URL, 抓 main.innerHTML (POST_START/POST_END 包装)
  4. 判断 post 是否是"财经早餐":
     - 含 "财经早餐" → 调 finance_breakfast.py 完整流程 (raw cache 命中跳过 fetch)
     - 不含         → 调 publish_mr_dang_post.py 单篇抓取
  5. push (Contents API fallback, 绕开 git push 撞墙)
  6. 简报输出

依赖:
  - 本机 Chrome 在 18900 端口 (frank_bot profile, 已登录红圈)
  - cdp_get_innerhtml.py (复用 _ws_connect / _eval / _navigate / EXTRACT_JS)
  - finance_breakfast.py / publish_mr_dang_post.py / system_api_pusher.py

用法:
  python3 tools/daily_catch.py                          # 跑全流程 (今天)
  python3 tools/daily_catch.py --date 20260703         # 指定日期
  python3 tools/daily_catch.py --dry-run               # 不实际推送

退出码:
  0 - 成功 (抓取 + 推送) 或 跳过 (周日 / 今日未发)
  1 - 失败 (CDP 异常 / 抓取异常 / 推送失败)
"""
import sys
import json
import time
import re
import subprocess
import traceback
import argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta

from bs4 import BeautifulSoup

# 复用 cdp_get_innerhtml.py 的 cdp 通信函数
sys.path.insert(0, str(Path(__file__).parent))
from cdp_get_innerhtml import (
    _ws_connect, _eval, _navigate, _resolve_auto_url, EXTRACT_JS,
)

WORKSPACE_JOBS = Path.home() / ".openclaw" / "workspace-jobs"
TOOLS_DIR = WORKSPACE_JOBS / "tools"
DOCS_DIR = WORKSPACE_JOBS / "docs"
RAW_DIR = Path("/tmp")
PUSHER_API = TOOLS_DIR / "system_api_pusher.py"
FB_SCRIPT = TOOLS_DIR / "finance_breakfast.py"
PUB_SCRIPT = TOOLS_DIR / "publish_mr_dang_post.py"
DEPLOY_PRO_SCRIPT = TOOLS_DIR / "site_deploy_pro.py"  # frankofswing.com deploy loop

GROUP_URL = "https://www.red-ring.cn/group/27593"
PINNED_POST_IDS = {'19492', '1949299', '27593-1949299'}

LOG_FILE = "/tmp/daily_catch.log"


# ── 日志 ────────────────────────────────────────────────

def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def shanghai_today_str():
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).strftime("%Y%m%d")


def shanghai_now_iso():
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S GMT+8")


def shanghai_weekday():
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).weekday()


def sh(cmd, cwd=None, timeout=600):
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout)


# ── 抓 list 主页 (扩展 cdp_get_innerhtml.py) ───────────────────

# 复刻 cdp_get_innerhtml.py 的 find_js, 不带 today 限制, 找最新一条
LIST_JS = r"""
(function(){
    var main = document.querySelector('main');
    if (!main) return JSON.stringify({posts: [], err: 'no main'});
    var seen = {};
    var results = [];
    // ⚠️ 红圈 list 页 DOM 坑: 真正的标题 div 是 <div onClick> 而不是 <a>,
    //    只有 "查看所有评论" 链接才是 <a href="/post/...">.
    //    策略: 从 "查看所有评论" 链接往父级找到帖子卡片 div, 然后从卡片文本中拆出标题.
    main.querySelectorAll('a[href*="/post/"]').forEach(function(a){
        var href = a.href;
        if (seen[href]) return;
        var txt = (a.innerText || a.textContent || '').trim();
        // 只从 "查看所有评论" / "查看 N 条评论" 链接入手
        if (!txt.startsWith('查看')) return;
        seen[href] = 1;
        // 向上找帖子卡片: 包含 "MR Dang" + 时间字样的 div
        var card = a;
        for (var i = 0; i < 10; i++) {
            if (!card.parentElement) break;
            card = card.parentElement;
            var ct = (card.innerText || '');
            if (ct.indexOf('MR Dang') >= 0 &&
                (ct.indexOf('今天') >= 0 || ct.indexOf('昨天') >= 0 ||
                 ct.indexOf('小时前') >= 0 || ct.indexOf('分钟前') >= 0 ||
                 /\d{2}\/\d{2}/.test(ct))) {
                break;
            }
        }
        // 从卡片文本行里解析: 跳过作者/时间/点赞/评论/查看 等行, 找到标题行
        var lines = (card.innerText || '').split('\n').map(function(s){return s.trim();}).filter(function(s){return s.length > 0;});
        var title = '';
        var timeText = '';
        for (var i = 0; i < lines.length; i++) {
            var line = lines[i];
            // 时间行
            if (/^(今天|昨天)(\s+\d{2}:\d{2})?$/.test(line) ||
                /^\d{1,2}\/\d{1,2}(\s+\d{2}:\d{2})?$/.test(line) ||
                /^\d{2}:\d{2}$/.test(line) ||
                /^\d{4}-\d{1,2}-\d{1,2}/.test(line) ||
                /(分钟前|小时前|刚刚)$/.test(line)) {
                if (!timeText) timeText = line;
                continue;
            }
            // 作者行
            if (line === 'MR Dang' || line.indexOf('MR Dang') === 0) continue;
            // 杂项
            if (line === '置顶' || line === '精华' || line === '回复' || line.indexOf('查看') === 0 ||
                /^\d+$/.test(line) || /^\d+ 分钟前/.test(line) ||
                line.indexOf('赞') === 0 || /^\d+$/.test(line)) continue;
            // 找到标题 (默认第一条满足条件的行)
            title = line.slice(0, 80);
            break;
        }
        results.push({time: timeText, title: title, href: href});
    });
    return JSON.stringify({posts: results.slice(0, 30)});
})()
"""


def fetch_list_latest_post():
    """抓 list 主页 (不 navigate 到 post), 返回最新一条 (post_url, time_str)

    None = 列表为空
    """
    ws_url = _resolve_auto_url()
    log(f"[list] Resolved CDP: ...{ws_url[-30:]}")
    ws = _ws_connect(ws_url)
    try:
        log(f"[list] navigate to {GROUP_URL}")
        _navigate(ws, GROUP_URL)
        time.sleep(2)
        # 滚动加载更多
        for i in range(4):
            _eval(ws, 900 + i, "window.scrollBy(0, 1500); window.scrollY")
            time.sleep(1)
        _eval(ws, 905, "window.scrollTo(0, 0)")
        time.sleep(1)

        data = _eval(ws, 910, LIST_JS)
        raw = data["result"]["result"]["value"]
        parsed = json.loads(raw)
        posts = parsed.get("posts", [])
        log(f"[list] 找到 {len(posts)} 条候选帖子")

        if not posts:
            return None

        # 过滤置顶帖
        candidates = []
        for p in posts:
            href = p.get('href', '') or ''
            is_pinned = any(pid in href for pid in PINNED_POST_IDS)
            if is_pinned:
                log(f"[list] 跳过置顶帖: {href}")
                continue
            candidates.append(p)

        if not candidates:
            log("[list] 过滤置顶帖后无候选")
            return None

        # 调试: 列出所有候选 (title + time + href)
        for i, c in enumerate(candidates[:6]):
            log(f"[list]   候选 {i}: title={c.get('title','')!r} time={c.get('time','')!r} href={c.get('href','')}")

        # ⚠️ race condition 防护: cron 8AM 准点跑时, Mr Dang 当天新帖可能刚发未及时进 list,
        #    此时 list 里第一条仍是昨天的"财经早餐" (如 2026-07-18 8AM cron 抓到 7/17 早餐 post 2468150,
        #    finance_breakfast.py 强制用 7/18 日期写错文件 JJC-20260718-001-原文.md 事故)
        # ✅ 修复: candidates 先**只保留 "今天" 发布的帖子**, "昨天"/"前天"/具体日期 都不算今天
        #    如果 today_only 为空, 直接返回 None, 跳过整个任务 (避免误抓昨天)
        # "今天" 前缀 或 相对时间("X 分钟前"/"X 小时前") 都视为今天的帖子
        def is_today_time(time_str):
            ts = time_str or ''
            if ts.startswith('今天'):
                return True
            # "51 分钟前" / "2 小时前" 等相对时间, 发生在几分钟~几小时内, 必然是今天
            if re.match(r'^\d+ ?[时分]钟?前$', ts):
                return True
            return False

        today_only = [c for c in candidates if is_today_time(c.get('time', ''))]
        if not today_only:
            # ⚠️ Fallback: candidates[0].time='' (懒加载 race condition)
            #    2026-08-11 8AM 抓 list 时, 今天的新帖时间标签未渲染 (time=''),
            #    其他候选都有时间标签 ("昨天"/具体日期).
            #    列表第一条按倒序 = 最新帖子, 兜底视为今天候选继续流程.
            #    双保险: finance_breakfast.py 的 date 校验 (commit 95001d70) 拒绝日期不匹配的写入.
            if candidates and not candidates[0].get('time', ''):
                log(f"[list] ⚠️ today_only 空, 但 candidates[0].time='' (懒加载 race condition)")
                log(f"[list] 取 candidates[0] 作兜底: {candidates[0].get('title', '')[:60]!r}")
                today_only = [candidates[0]]
            else:
                sample_times = [c.get('time', '') for c in candidates[:3]]
                log(f"[list] ⚠️ 今日暂无帖子 (候选时间样例: {sample_times})")
                log(f"[list] 可能是 race condition (Mr Dang 准点 8AM 发帖, list 还未刷新) 或今天真的没发")
                log(f"[list] 跳过任务, 不抓任何 post")
                return None
        if len(today_only) < len(candidates):
            log(f"[list] today_only 过滤: {len(candidates)} → {len(today_only)} (剔除昨天/前天)")
        candidates = today_only

        # ⚠️ 同分钟双帖坑: 红圈偶尔会在同一分钟同时发"财经早餐"和"有声版"音频版
        # (如 2026-07-06 06:59 同时有 post 2449788 早餐 + 2449789 有声版),
        # DOM 顺序不可靠, audio 版有时排在 breakfast 前面。
        # ✅ 修复: 候选中**优先选 title 含"财经早餐"** 的 post; 找不到才退到第一条。
        bf_candidates = [c for c in candidates if '财经早餐' in (c.get('title', '') or '')]
        if bf_candidates:
            if len(bf_candidates) > 1:
                log(f"[list] ⚠️ 多个候选含'财经早餐' ({len(bf_candidates)} 条), 取第一条")
            latest = bf_candidates[0]
            log(f"[list] 选中财经早餐候选: title={latest.get('title','')!r} href={latest.get('href','')}")
        else:
            # 🔴 Frank 要求: 永远不抓"有声版", 没有文字版就跳过
            audio_only = all('有声版' in (c.get('title', '') or '') for c in candidates)
            if audio_only:
                log(f"[list] 🔴 今天只有有声版, 无财经早餐文字版, 按 Frank 要求跳过任务")
                return None
            latest = candidates[0]
            log(f"[list] 无财经早餐候选, 退回到第一条: time={latest.get('time','')!r} href={latest.get('href','')}")
        return latest.get('href'), latest.get('time', '')

    finally:
        ws.close()


# ── 抓 post 详情页 ────────────────────────────────────────────

def fetch_post_html(post_url):
    """navigate 到 post URL, 抓 main.innerHTML (POST_START/POST_END 包装)

    智能等待: 等 .ql-view 元素出现 + post-body > 1000 字符, 避免 Vue 渲染未完成时抓空。
    最坏情况 fallback 到原始硬等待。
    """
    ws_url = _resolve_auto_url()
    log(f"[post] Resolved CDP: ...{ws_url[-30:]}")
    ws = _ws_connect(ws_url)
    try:
        log(f"[post] navigate to {post_url}")
        _navigate(ws, post_url)
        time.sleep(2)

        # 智能等待: 等 post-body > 1000 chars 或 .ql-view 元素出现 (Vue 异步渲染标志)
        for retry in range(3):
            js_check = """
(function(){
    var pb = document.querySelector('.post-body');
    var qv = document.querySelector('.ql-view, .fzx-2');
    return JSON.stringify({
        pbLen: pb ? pb.innerHTML.length : 0,
        hasQlView: !!qv,
        qvLen: qv ? qv.innerHTML.length : 0,
    });
})()
"""
            data = _eval(ws, 700 + retry, js_check)
            try:
                state = json.loads(data["result"]["result"]["value"])
                if state.get("pbLen", 0) > 1000 or state.get("hasQlView"):
                    log(f"[post] Vue 已渲染 (pbLen={state['pbLen']}, qv={state['qvLen']}), retry={retry}")
                    break
            except Exception:
                pass
            log(f"[post] post-body 还未渲染 (pbLen={state.get('pbLen',0)}), 等待 3s 后重试 (retry={retry})")
            time.sleep(3)

        # 触发懒加载评论 (反复 scroll cmtList 容器)
        for i in range(5):
            js_scroll = (
                "var c = document.querySelector('.cmtList, [class*=cmt]');"
                "if (c && c.scrollTo) { c.scrollTo(0, 99999); } else { window.scrollBy(0, 1500); }"
            )
            _eval(ws, 800 + i, js_scroll)
            time.sleep(1.5)
        _eval(ws, 806, "window.scrollTo(0, 0)")
        time.sleep(1)

        # 抓 main.innerHTML (POST_START/POST_END 包装)
        js = EXTRACT_JS  # arguments[0]=undefined, fallback 到 main
        data = _eval(ws, 1, js)
        raw = data["result"]["result"]["value"]
        parsed = json.loads(raw)
        html = parsed.get("html", "")
        comment_count = parsed.get("commentCount", 0)
        log(f"[post] 抓取成功: html={len(html)} chars, comments={comment_count}")
        if len(html) < 2000:
            log(f"[post] ⚠️ html 长度异常短 ({len(html)}), 可能 Vue 渲染失败或 post 不存在")
        return html
    finally:
        ws.close()


# ── 标题/类型判断 ─────────────────────────────────────────────

def detect_post_type(html):
    """判断 HTML 是财经早餐还是非早餐

    返回 (is_breakfast, title, source)
      is_breakfast: True/False
      title: 提取的标题
      source: 'h1' / 'fz-lg' (财经早餐专属标题样式) / 'body' (正文含"财经早餐") / 'no_match'

    ⚠️ 重要: 排除页脚"Mr Dang 个人介绍"里的"财经早餐"字样干扰。
       个人介绍文本含: "知乎人气答主Mr Dang", "后花园", "财经作家", "价值投资功法"
    """
    soup = BeautifulSoup(html, 'html.parser')

    # 1) 优先找 h1
    h1 = soup.find('h1')
    title = h1.get_text(strip=True) if h1 else ''

    # 1.5) 找 og:title (Mr Dang 精华贴常无 h1, 但有 og:title, 例 6/26 地阶功法卷六)
    if not title:
        og = soup.find('meta', attrs={'property': 'og:title'})
        if og and og.get('content'):
            og_title = og['content'].strip()
            # 去掉" - 红运Dang投" 等站点后缀
            og_title = re.sub(r'\s*[-—|]\s*红运Dang投.*$', '', og_title).strip()
            if og_title and 4 < len(og_title) < 80:
                title = og_title

    # 2) h1/og 都没拿到, fallback 找 class="fz-lg" 的 div (财经早餐专属标题样式)
    #    7/3 早餐验证: div.fz-lg "2026年7月3日财经早餐" (长度 13)
    #    非早餐: 6/18 收盘复盘没有这个 div
    if not title:
        for elem in soup.find_all('div', class_='fz-lg'):
            txt = elem.get_text(strip=True)
            if '财经早餐' in txt and 5 < len(txt) < 50:
                title = txt
                break

    # 3) 判断是否早餐
    if title and '财经早餐' in title:
        return True, title, 'fz-lg' if not h1 else 'h1'

    # 4) fallback: 看 post-body 内是否有"财经早餐" (排除页脚签名干扰)
    pb = soup.find('div', class_='post-body')
    if pb:
        pb_text = pb.get_text()[:2000]
        if re.search(r'\d{1,2}月\d{1,2}日.*财经早餐|财经早餐.*\d{1,2}月\d{1,2}日', pb_text):
            return True, title or '财经早餐', 'body'

    # 5) 终极 fallback: 取 post-body 首段作为标题 (7/4 精华贴 "打新招股说明书怎么看" 验证)
    #    截前 60 字符, 跳过空行/MR Dang 介绍段
    if not title and pb:
        for p in pb.find_all(['p', 'div']):
            txt = p.get_text(strip=True)
            # 跳过空 / 链接 / 短段
            if not txt or len(txt) < 6:
                continue
            # 跳过页脚介绍 (含特定关键词)
            if any(kw in txt for kw in ['知乎人气答主', '后花园', '财经作家', '价值投资功法', '喜欢保护韭菜']):
                continue
            # 截到第一个句号/问号
            m = re.match(r'^(.{4,60}?[。！？?!])', txt)
            if m:
                title = m.group(1).strip()
            else:
                title = txt[:60]
            break

    return False, title or 'MR Dang 文章', 'first_para' if (not h1 and title and title != 'MR Dang 文章') else 'no_match'


# ── 路由 ─────────────────────────────────────────────────────

def write_raw_cache(date_str, html):
    """写 raw HTML 到 finance_breakfast.py 期望的路径, 让 fetch step 缓存命中跳过"""
    raw_file = RAW_DIR / f"finance_breakfast_raw_{date_str}.html"
    raw_file.write_text(html, encoding='utf-8')
    log(f"[cache] 写 raw 缓存: {raw_file} ({len(html)} chars)")


def route_to_finance_breakfast(date_str):
    """走 finance_breakfast.py 完整流程 (fetch step 缓存命中 → format/guard/push)"""
    log(f"[route→FB] finance_breakfast.py --date {date_str} --step all")
    cp = sh(['python3', str(FB_SCRIPT),
             '--date', date_str, '--step', 'all'],
            cwd=str(WORKSPACE_JOBS), timeout=600)
    log(f"[route→FB] rc={cp.returncode}")
    for line in cp.stdout.split('\n')[-15:]:
        if line.strip():
            log(f"  {line}")
    return cp.returncode


def route_to_publish_mr_dang(post_url, date_str, title):
    """走 publish_mr_dang_post.py 单篇抓取流程"""
    log(f"[route→PUB] publish_mr_dang_post.py url={post_url} date={date_str}")

    # slug: JJC-<date>-001-<title>-原文 (假设当天没早餐, 占 001)
    safe_title = re.sub(r'[\\/:*?"<>|\s]+', '-', title)[:40].strip('-') or 'mr_dang_post'
    slug = f"JJC-{date_str}-001-{safe_title}-原文"
    md_relpath = f"docs/{slug}.md"

    cp = sh(['python3', str(PUB_SCRIPT),
             '--url', post_url,
             '--date', date_str,
             '--slug', slug,
             '--title', title],
            cwd=str(WORKSPACE_JOBS), timeout=300)
    log(f"[route→PUB] rc={cp.returncode}")
    for line in cp.stdout.split('\n')[-15:]:
        if line.strip():
            log(f"  {line}")
    return cp.returncode


def push_to_github(file_relpath, commit_msg):
    """用 system_api_pusher.py 推单文件到 GitHub (绕开 git push 撞墙)"""
    log(f"[push] {file_relpath}")
    log(f"      msg: {commit_msg[:100]}")
    cp = sh(['python3', str(PUSHER_API),
             '--file', file_relpath,
             '--commit-msg', commit_msg],
            cwd=str(WORKSPACE_JOBS), timeout=60)
    log(f"[push] stdout: {cp.stdout.strip()[:500]}")
    if cp.stderr.strip():
        log(f"[push] stderr: {cp.stderr.strip()[:300]}")
    return cp.returncode


# ── 主流程 ─────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="每日红圈文章抓取与发布（财经早餐优先，否则抓最新非早餐）")
    ap.add_argument("--date", default=shanghai_today_str(), help="日期 YYYYMMDD (默认今天)")
    ap.add_argument("--url", default=None, help="直接指定 post URL (跳过 list 步骤, 便于测试非早餐路径)")
    ap.add_argument("--dry-run", action="store_true", help="不实际推送")
    ap.add_argument("--skip-sync", action="store_true", help="跳过 frankofswing.com deploy 验证 (默认 push 成功后自动跑)")
    args = ap.parse_args()
    date_str = args.date
    dry_run = args.dry_run
    direct_url = args.url
    skip_sync = args.skip_sync

    log("=" * 60)
    log(f"daily_catch.py v1 — date={date_str} dry_run={dry_run}")
    log("=" * 60)

    # 周日跳过 (历史规律: Mr Dang 周日不发 8AM 财经早餐)
    wd = shanghai_weekday()
    if wd == 6:
        log(f"[skip] 今天周日 (weekday={wd}), Mr Dang 不发 8AM 早餐, 跳过任务")
        log(f"[done] rc=0")
        return 0

    # Step 1: 抓 list 找最新一条 post URL (除非 --url 指定)
    if direct_url:
        log(f"[plan] --url 指定, 跳过 list 抓取: {direct_url}")
        post_url, post_time = direct_url, '(direct url)'
    else:
        try:
            result = fetch_list_latest_post()
        except Exception as e:
            log(f"[ERR] fetch_list_latest_post 失败: {type(e).__name__}: {e}")
            log(traceback.format_exc())
            return 1

        if not result:
            log("[skip] 红圈列表无新帖子 (周一至周五通常有, 可能今天没发)")
            log("[done] rc=0")
            return 0

        post_url, post_time = result
    log(f"[plan] 目标帖子: {post_url}")
    log(f"[plan] 发布时间: {post_time}")

    # Step 2: 抓 post innerHTML
    try:
        html = fetch_post_html(post_url)
    except Exception as e:
        log(f"[ERR] fetch_post_html 失败: {type(e).__name__}: {e}")
        log(traceback.format_exc())
        return 1

    # Step 3: 判断是早餐还是非早餐
    is_bf, title, source = detect_post_type(html)
    log(f"[detect] is_breakfast={is_bf} source={source}")
    log(f"[detect] title={title!r}")

    # Step 4: 写 raw cache (即使非早餐也写, 方便后续 debug)
    write_raw_cache(date_str, html)

    if dry_run:
        log(f"[dry-run] 跳过推送, 路由: {'FB' if is_bf else 'PUB'}")
        log(f"[done] rc=0")
        return 0

    # Step 5: 路由
    if is_bf:
        rc = route_to_finance_breakfast(date_str)
        log(f"[summary] type=财经早餐, route=finance_breakfast.py, rc={rc}")
        # ⚠️ 2026-07-06 修: finance_breakfast.py 的 push 走 system_git_pusher.py (git push),
        #    远端领先本地时 ('fetch first' 错误) 会撞墙. 这里加 Contents API fallback,
        #    避免 8AM cron 死在这个环节。
        if rc != 0:
            md_relpath = f"docs/JJC-{date_str}-001-原文.md"
            md_abs = WORKSPACE_JOBS / md_relpath
            if md_abs.exists():
                log(f"[fallback] finance_breakfast.py rc={rc}, 走 Contents API 兑底推 {md_relpath}")
                commit_msg = f"feat: {date_str[:4]}年{date_str[4:6]}月{date_str[6:8]}日财经早餐 (Contents API fallback)"
                fb_rc = push_to_github(md_relpath, commit_msg)
                log(f"[fallback] Contents API push rc={fb_rc}")
                rc = fb_rc  # 覆盖返回码
            else:
                log(f"[fallback] ⚠️ {md_relpath} 不存在, 无法兑底推送")
    else:
        rc = route_to_publish_mr_dang(post_url, date_str, title)
        log(f"[summary] type=非早餐, route=publish_mr_dang_post.py, rc={rc}")

    # ── Step 6: 同步到 frankofswing.com (Vercel deploy loop) ──
    if rc != 0:
        log(f"[sync] push rc={rc}, 跳过 sync")
    elif dry_run:
        log(f"[sync] dry-run, 跳过 sync")
    elif skip_sync:
        log(f"[sync] --skip-sync, 跳过 sync")
    else:
        # 算 sync 文件路径 (跟 route 同步)
        if is_bf:
            sync_md_relpath = f"docs/JJC-{date_str}-001-原文.md"
        else:
            safe_title = re.sub(r'[\\/:*?"<>|\s]+', '-', title)[:40].strip('-') or 'mr_dang_post'
            sync_md_relpath = f"docs/JJC-{date_str}-001-{safe_title}-原文.md"
        sync_abs = WORKSPACE_JOBS / sync_md_relpath
        if not sync_abs.exists():
            log(f"[sync] ⚠️ {sync_md_relpath} 不存在, 跳过")
        elif not DEPLOY_PRO_SCRIPT.exists():
            log(f"[sync] ⚠️ {DEPLOY_PRO_SCRIPT.name} 不存在, 跳过 (手动跑 deploy)", "WARN")
        else:
            log(f"[sync] 触发 site_deploy_pro.py {sync_md_relpath}")
            sync_cp = sh(['python3', str(DEPLOY_PRO_SCRIPT),
                          '--date', date_str,
                          '--file', sync_md_relpath,
                          '--max-seconds', '180',
                          '--poll-interval', '25'],
                         cwd=str(WORKSPACE_JOBS), timeout=240)
            log(f"[sync] deploy_loop rc={sync_cp.returncode}")
            for line in sync_cp.stdout.split('\n')[-15:]:
                if line.strip():
                    log(f"  sync: {line}")

    log("=" * 60)
    log(f"[done] rc={rc} | date={date_str} | is_breakfast={is_bf} | title={title}")
    log("=" * 60)
    return rc


if __name__ == "__main__":
    sys.exit(main())