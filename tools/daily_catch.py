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
    main.querySelectorAll('a[href*="/post/"]').forEach(function(a){
        var href = a.href;
        if (seen[href]) return;
        seen[href] = 1;
        var el = a.parentElement;
        var timeText = '';
        for (var i = 0; i < 8; i++) {
            if (!el) break;
            var lines = (el.innerText || '').split('\n');
            for (var j = 0; j < lines.length; j++) {
                var t = lines[j].trim();
                if ((t.match(/^\d{2}:\d{2}$/) && t.length == 5) ||
                    (t.includes('今天') || t.includes('昨天')) ||
                    t.includes('小时前') || t.includes('分钟前') || t.includes('刚刚') ||
                    t.match(/^\d{4}-\d{2}-\d{2}/) ||
                    t.match(/^\d{2}-\d{2}/)) {
                    if (t.length < 30) { timeText = t; break; }
                }
            }
            if (timeText) break;
            el = el.parentElement;
        }
        results.push({time: timeText, title: '', href: href});
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

        # 取第一条 (最新一条, 红圈按时间倒序)
        latest = candidates[0]
        log(f"[list] 最新帖子: time={latest.get('time','')!r} href={latest.get('href','')}")
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

    # 2) h1 没拿到, fallback 找 class="fz-lg" 的 div (财经早餐专属标题样式)
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
        import re
        if re.search(r'\d{1,2}月\d{1,2}日.*财经早餐|财经早餐.*\d{1,2}月\d{1,2}日', pb_text):
            return True, title or '财经早餐', 'body'

    return False, title or 'MR Dang 文章', 'no_match'


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
    args = ap.parse_args()
    date_str = args.date
    dry_run = args.dry_run
    direct_url = args.url

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
    else:
        rc = route_to_publish_mr_dang(post_url, date_str, title)
        log(f"[summary] type=非早餐, route=publish_mr_dang_post.py, rc={rc}")

    log("=" * 60)
    log(f"[done] rc={rc} | date={date_str} | is_breakfast={is_bf} | title={title}")
    log("=" * 60)
    return rc


if __name__ == "__main__":
    sys.exit(main())