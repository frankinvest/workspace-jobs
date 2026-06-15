#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
finance_breakfast.py - 财经早餐发布主流程 (支持单步可重入) — v2 真实实现版

🎯 5 个独立 step:
  1. fetch    - subprocess 调 cdp_get_innerhtml.py 抓 innerHTML (走本机 Chrome 18900 登录态)
  2. format   - 用 bs4 + markdownify + build_comments.py 核心逻辑, 渲染 .md 含评论区
  3. images   - 跳过 (按 MEMORY.md 约定: 图片直接引用红圈原 URL, 不下载到本地)
  4. guard    - 用真实数据审计 (图片数 / 评论数 / 标题 / 数据提取时间)
  5. push     - 调 system_git_pusher.py 穿墙推送 (commit message 由脚本动态生成)

用法:
  python3 tools/finance_breakfast.py                            # 跑全流程
  python3 tools/finance_breakfast.py --step fetch_only          # 只跑抓取
  python3 tools/finance_breakfast.py --step format_only         # 只跑排版
  python3 tools/finance_breakfast.py --step images_only         # 只跑图片 (skip)
  python3 tools/finance_breakfast.py --step guard_only          # 只跑审计
  python3 tools/finance_breakfast.py --step push_only           # 只跑推送
  python3 tools/finance_breakfast.py --date 20260604            # 指定日期
  python3 tools/finance_breakfast.py --dry-run                  # 不实际执行

每个 step 退出码:
  0 - 成功
  1 - 失败
  2 - 跳过 (前置条件不满足)
"""
import argparse
import subprocess
import sys
import os
import json
import time
import re
import html as html_mod
from datetime import datetime, timezone, timedelta
from pathlib import Path

# BeautifulSoup + markdownify 用于正文解析 + markdown 渲染
from bs4 import BeautifulSoup
import markdownify as mf

WORKSPACE_JOBS = Path.home() / ".openclaw" / "workspace-jobs"
DOCS_DIR = WORKSPACE_JOBS / "docs"
TOOLS_DIR = WORKSPACE_JOBS / "tools"
RAW_DIR = Path("/tmp")  # innerHTML 暂存 /tmp
STATE_FILE = Path("/tmp/finance_breakfast_state.json")
LOG_FILE = "/tmp/finance_breakfast.log"
CDP_SCRIPT = TOOLS_DIR / "cdp_get_innerhtml.py"
BUILD_COMMENTS_SCRIPT = TOOLS_DIR / "build_comments.py"
PUSHER = TOOLS_DIR / "system_git_pusher.py"

GROUP_URL = "https://www.red-ring.cn/group/27593"  # 红运Dang投圈子

STEP_NAMES = ["fetch", "format", "images", "guard", "push"]
STEP_DESC = {
    "fetch":  "subprocess 调 cdp_get_innerhtml.py 抓 innerHTML",
    "format": "用 bs4 + markdownify 渲染 .md (含评论区)",
    "images": "跳过 (图片引用红圈原 URL, 不本地化)",
    "guard":  "用真实数据审计 (图片数/评论数/标题/时间)",
    "push":   "调 system_git_pusher.py 穿墙推送",
}


def log(msg, also_print=True):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    if also_print:
        print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def shanghai_today_str():
    """返回上海时区今天的 YYYYMMDD 字符串"""
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).strftime("%Y%m%d")


def shanghai_now_iso():
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S GMT+8")


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


# ── Step 1: fetch ────────────────────────────────────────────────

def step_fetch(date_str, dry_run=False):
    """Step 1: subprocess 调 cdp_get_innerhtml.py 抓 innerHTML
    
    输入: cdp_get_innerhtml.py /tmp/finance_breakfast_raw_<date>.html AUTO --auto-latest
    输出: /tmp/finance_breakfast_raw_<date>.html
    """
    log(f"[fetch] 抓取 {date_str} 帖子")
    
    if dry_run:
        log("  [dry-run] 跳过")
        return 0
    
    output_file = RAW_DIR / f"finance_breakfast_raw_{date_str}.html"
    if output_file.exists() and output_file.stat().st_size > 1000:
        log(f"  ✅ 已有缓存: {output_file} ({output_file.stat().st_size} bytes)")
        return 0
    
    if not CDP_SCRIPT.exists():
        log(f"  ❌ 缺少抓取脚本: {CDP_SCRIPT}")
        return 1
    
    cmd = [
        sys.executable, str(CDP_SCRIPT),
        str(output_file), "AUTO",
        "--auto-latest",
        "--group-url", GROUP_URL,
        "--selector", "main",
    ]
    log(f"  → {' '.join(cmd)}")
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if cp.stdout:
            log("  [cdp stdout] " + cp.stdout.replace("\n", "\n  [cdp stdout] ")[:500])
        if cp.stderr:
            log("  [cdp stderr] " + cp.stderr.replace("\n", "\n  [cdp stderr] ")[:500])
        if cp.returncode == 3:
            log("  ❌ 日期熔断: 今日帖子不存在")
            return 1
        if cp.returncode != 0:
            log(f"  ❌ cdp_get_innerhtml.py 失败 rc={cp.returncode}")
            return 1
        if not output_file.exists() or output_file.stat().st_size < 1000:
            log(f"  ❌ 输出文件异常: {output_file}")
            return 1
        log(f"  ✅ 抓取成功: {output_file} ({output_file.stat().st_size} bytes)")
        return 0
    except subprocess.TimeoutExpired:
        log(f"  ❌ 抓取超时 (>180s)")
        return 1
    except Exception as e:
        log(f"  ❌ 抓取异常: {type(e).__name__}: {e}")
        return 1


# ── Step 2: format ───────────────────────────────────────────────

def extract_post_body(html):
    """提取帖子正文 (从 main 容器内的 post-body / ql-view 容器)
    返回 HTML 字符串
    """
    soup = BeautifulSoup(html, 'html.parser')
    content_div = soup.find('div', class_=lambda x: x and 'ql-view' in x)
    if not content_div:
        content_div = soup.find('div', class_=lambda x: x and 'post-body' in x)
    if not content_div:
        return ""
    # 移除噪音 (input/button/svg/form)
    for unwanted in content_div.find_all(['input', 'button', 'svg', 'form']):
        unwanted.decompose()
    return "".join(str(item) for item in content_div.contents)


def extract_post_images(post_html):
    """提取正文中所有图片 URL
    返回 list[str]
    """
    soup = BeautifulSoup(post_html, 'html.parser')
    urls = []
    for img in soup.find_all('img'):
        for attr in ('data-src', 'data-original', 'src'):
            url = img.get(attr)
            if url and url.startswith('http') and 'red-ring' in url:
                urls.append(url)
                break
    return urls


def extract_title(html):
    """从 HTML 提取帖子标题
    """
    soup = BeautifulSoup(html, 'html.parser')
    # 优先找带特定 class 的标题
    h1 = soup.find('h1')
    if h1:
        return h1.get_text(strip=True)
    # 找带 财经早餐 字样的元素
    for elem in soup.find_all(['h1', 'h2', 'h3', 'div', 'span']):
        txt = elem.get_text(strip=True)
        if '财经早餐' in txt and len(txt) < 50:
            return txt
    return ""


def extract_comments_from_html(html):
    """从 innerHTML 提取评论 (用 build_comments.py 的 regex 逻辑)
    返回 list[dict] {user, time, content, replies}
    """
    # 评论区起点
    cmt_start = html.find('class="por px-15"')
    if cmt_start == -1:
        return []
    cmt_html = html[cmt_start:]
    
    # 顶级评论: <div class="py-12 flex bt">
    top_cmt_pat = re.compile(
        r'<div class="py-12 flex bt">(.*?)(?=<div class="py-12 flex bt"|</div>\s*</div>\s*</div>\s*<div class="por px-15"|\Z)',
        re.DOTALL
    )
    # 回复 (在 bgc-body 容器内): <span class="c-primary cup">...</span>...<span class="wpw">...</span>
    reply_pat = re.compile(
        r'<span class="c-primary cup">([^<]+)</span>.*?<span class="wpw">([^<]*(?:<[^>]+>[^<]*</[^>]+>)*[^<]*)</span>',
        re.DOTALL
    )
    # 顶级用户/时间/正文
    top_user_pat = re.compile(r'<span class="cup mr-5">([^<]+)</span>')
    top_time_pat = re.compile(r'<span class="dark-9 fz-sm">([^<]+)</span>')
    top_text_pat = re.compile(r'<span class="wpw">([^<]*(?:<[^>]+>[^<]*</[^>]+>)*[^<]*)</span>', re.DOTALL)
    
    comments = []
    for m in top_cmt_pat.finditer(cmt_html):
        block = m.group(1)
        u_m = top_user_pat.search(block)
        t_m = top_time_pat.search(block)
        w_m = re.search(r'<span class="wpw">(.+?)</span>', block, re.DOTALL)
        if not u_m or not w_m:
            continue
        u = u_m.group(1).strip()
        t = t_m.group(1).strip() if t_m else ""
        txt = re.sub(r'<[^>]+>', '', w_m.group(1)).strip()
        txt = txt.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>')
        if not txt:
            # 可能是图片评论
            if '查看图片' in block:
                txt = '[图片评论]'
            else:
                continue
        item = {'user': u, 'time': t, 'content': txt, 'replies': []}
        # 回复
        reply_section = re.search(r'<div class="bgc-body px-9 py-5">(.*?)</div>\s*</div>\s*</div>\s*</div>', block, re.DOTALL)
        if reply_section:
            reply_block = reply_section.group(1)
            for rm in reply_pat.finditer(reply_block):
                ru = rm.group(1).strip()
                rt = re.sub(r'<[^>]+>', '', rm.group(2)).strip()
                rt = rt.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>')
                if ru and rt:
                    item['replies'].append({'user': ru, 'content': rt})
        comments.append(item)
    return comments


def render_comments_md(comments):
    """把评论列表渲染为 markdown
    """
    if not comments:
        return "*暂无评论*"
    lines = []
    for c in comments:
        time_str = f" *({c['time']})*" if c['time'] else ""
        lines.append(f"- **{c['user']}**{time_str}: {c['content']}")
        for r in c['replies']:
            lines.append(f"  - ↳ **{r['user']}**: {r['content']}")
    return "\n".join(lines)


def step_format(date_str, dry_run=False):
    """Step 2: 用 bs4 + markdownify 渲染 .md (含评论区)
    
    输入: /tmp/finance_breakfast_raw_<date>.html
    输出: docs/JJC-<date>-001-原文.md
    """
    log(f"[format] 排版 {date_str} .md")
    
    md_file = DOCS_DIR / f"JJC-{date_str}-001-原文.md"
    if md_file.exists() and not dry_run:
        log(f"  ✅ 已有文件: {md_file}")
        return 0
    
    raw_file = RAW_DIR / f"finance_breakfast_raw_{date_str}.html"
    if not raw_file.exists():
        log(f"  ❌ 缺少 innerHTML: {raw_file}")
        log(f"  请先跑 --step fetch_only")
        return 1
    
    if dry_run:
        log("  [dry-run] 跳过")
        return 0
    
    try:
        html = raw_file.read_text(encoding="utf-8", errors="replace")
        # 截取 POST_START/POST_END 之间 (兼容旧 cdp 工具的输出)
        s, e = html.find("POST_START"), html.find("POST_END")
        if s != -1 and e != -1:
            html = html[s+10:e]
        html = html_mod.unescape(html)
        
        # 提取标题
        title = extract_title(html) or f"财经早餐 {date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
        
        # 提取正文
        body_html = extract_post_body(html)
        if not body_html.strip():
            log("  ❌ 正文提取为空 (触发硬熔断)")
            return 1
        
        # 提取图片
        images = extract_post_images(body_html)
        
        # 提取评论
        comments = extract_comments_from_html(html)
        
        # 渲染为 markdown
        post_md = mf.markdownify(body_html, heading_style="atx", link_style="inlined")
        comments_md = render_comments_md(comments)
        
        # 输出 .md
        display_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
        normalized_title = f"财经早餐 {display_date}"  # Frank 拍板的标题格式 (Vercel 首页列靠这个识别)
        # ⚠️ 重要: 顶部必须严格 YAML frontmatter (Astro 首页靠 title 字段识别，不能出现"原文"等文件后缀)
        full_md = "---\n"
        full_md += f'title: "{normalized_title}"\n'
        full_md += f'date: "{display_date}"\n'
        full_md += "---\n\n"
        full_md += f"# {normalized_title}\n\n"
        full_md += f"> 自动抓取于 {shanghai_now_iso()}\n"
        full_md += f"> 来源: 小红圈 (red-ring.cn) | 圈子: 红运Dang投 (ID: 27593)\n\n"
        full_md += "---\n\n"
        full_md += "## 原文\n\n"
        full_md += post_md + "\n\n"
        full_md += "---\n\n"
        full_md += f"## 💬 评论区 ({len(comments)} 条)\n\n"
        full_md += comments_md + "\n"
        
        DOCS_DIR.mkdir(parents=True, exist_ok=True)
        md_file.write_text(full_md, encoding="utf-8")
        
        # 保存状态 (供 guard / push 用)
        state = load_state()
        state[date_str] = {
            "title": title,
            "images": len(images),
            "comments": len(comments),
            "md_file": str(md_file),
            "fetched_at": shanghai_now_iso(),
        }
        save_state(state)
        
        log(f"  ✅ 生成 .md: {md_file}")
        log(f"     标题: {title}")
        log(f"     图片: {len(images)} 张")
        log(f"     评论: {len(comments)} 条")
        return 0
    except Exception as e:
        log(f"  ❌ 排版异常: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return 1


# ── Step 3: images (跳过) ────────────────────────────────────────

def step_images(date_str, dry_run=False):
    """Step 3: 按 MEMORY.md 约定, 图片直接引用红圈原 URL, 跳过本地化
    """
    log(f"[images] 跳过 (按 MEMORY.md 约定: 图片引用红圈原 URL)")
    return 0


# ── Step 4: guard ────────────────────────────────────────────────

def step_guard(date_str, dry_run=False):
    """Step 4: 用真实数据审计
    
    检查项:
      1. .md 文件存在
      2. 标题非空
      3. 图片数 >= 5 (经验值: 财经早餐一般 8-15 张图)
      4. 评论数 >= 3 (新流程不强制 19, 但应该抓到一些)
    """
    log(f"[guard] 审计 {date_str}")
    
    md_file = DOCS_DIR / f"JJC-{date_str}-001-原文.md"
    issues = []
    
    if not md_file.exists():
        issues.append(f"missing .md: {md_file}")
        log(f"  ❌ 审计失败: {md_file} 不存在")
        return 1
    
    content = md_file.read_text(encoding="utf-8")
    state = load_state().get(date_str, {})
    
    title = state.get("title", "")
    n_images = state.get("images", 0)
    n_comments = state.get("comments", 0)
    
    # 兜底: 从 .md 内容里数图片 (markdown 图片语法 + 红圈原 URL)
    if n_images == 0:
        n_images = len(re.findall(r'!\[[^\]]*\]\(https://private\.red-ring\.cn/', content))
    # 兜底: 从 .md 内容里数评论
    if n_comments == 0:
        n_comments = content.count("**") // 4  # 粗略: 每个评论至少有 1 个加粗用户名
        # 更精确: 数 "- **" 顶级评论标记
        n_comments = len(re.findall(r'^- \*\*[^*]+\*\*', content, re.MULTILINE))
    
    log(f"  标题: {title[:60]}")
    log(f"  图片: {n_images}")
    log(f"  评论: {n_comments}")
    
    if not title:
        issues.append("title 为空")
    if n_images < 5:
        issues.append(f"too few images: {n_images} (< 5)")
    if n_comments < 3:
        issues.append(f"too few comments: {n_comments} (< 3)")
    
    if issues:
        log(f"  ❌ 审计失败:")
        for i in issues:
            log(f"     - {i}")
        return 1
    
    log(f"  ✅ 审计通过")
    return 0


# ── Step 5: push ─────────────────────────────────────────────────

def generate_commit_message(date_str, state):
    """根据真实数据动态生成 commit message (严禁手填)
    """
    title = state.get("title", f"财经早餐 {date_str}")
    n_images = state.get("images", 0)
    n_comments = state.get("comments", 0)
    fetched_at = state.get("fetched_at", shanghai_now_iso())
    return f"feat: {title} ({n_images} images, {n_comments} comments)\n\n自动抓取于 {fetched_at}\nCo-Authored-By: OpenClaw <noreply@openclaw.ai>"


def step_push(date_str, dry_run=False):
    """Step 5: 调 system_git_pusher.py 穿墙推送
    """
    log(f"[push] 推送 {date_str} .md 到 GitHub")
    
    state = load_state().get(date_str, {})
    md_file = state.get("md_file", str(DOCS_DIR / f"JJC-{date_str}-001-原文.md"))
    
    if not Path(md_file).exists():
        log(f"  ❌ 缺少 .md: {md_file}")
        log(f"  请先跑 --step format")
        return 1
    
    if dry_run:
        log("  [dry-run] 跳过实际推送")
        return 0
    
    # 先 git add (只 add 这一个文件 + 凭证锁定 .gitignore 改动 + 工具更新)
    try:
        add_cmd = ["git", "add", str(md_file), ".gitignore", "tools/finance_breakfast.py", "tools/cdp_get_innerhtml.py", "tools/build_comments.py"]
        log(f"  → git add {md_file} + 工具更新")
        cp = subprocess.run(add_cmd, cwd=WORKSPACE_JOBS, capture_output=True, text=True, timeout=30)
        if cp.returncode != 0:
            log(f"  ❌ git add 失败: {cp.stderr}")
            return 1
        
        # 动态生成 commit message
        commit_msg = generate_commit_message(date_str, state)
        log(f"  → 动态 commit msg: {commit_msg.split(chr(10))[0]}")
        
        commit_cmd = ["git", "commit", "-m", commit_msg]
        log(f"  → git commit")
        cp = subprocess.run(commit_cmd, cwd=WORKSPACE_JOBS, capture_output=True, text=True, timeout=30)
        if cp.returncode != 0:
            if "nothing to commit" in cp.stdout:
                log(f"  ⚠️ nothing to commit (可能本轮已 commit)")
            else:
                log(f"  ❌ git commit 失败: {cp.stderr}")
                return 1
        else:
            log(f"  ✅ commit 成功")
    except Exception as e:
        log(f"  ❌ git 阶段异常: {type(e).__name__}: {e}")
        return 1
    
    # 调穿墙推送
    try:
        push_cmd = [sys.executable, str(PUSHER)]
        log(f"  → {PUSHER.name} 穿墙推送")
        cp = subprocess.run(push_cmd, cwd=WORKSPACE_JOBS, capture_output=True, text=True, timeout=120)
        if cp.stdout:
            for line in cp.stdout.split("\n")[-10:]:
                if line.strip():
                    log(f"  [pusher] {line}")
        if cp.returncode != 0:
            log(f"  ❌ pusher 失败 rc={cp.returncode}")
            if cp.stderr:
                log(f"  [pusher stderr] {cp.stderr[:500]}")
            return 1
        log(f"  ✅ 推送成功")
        return 0
    except Exception as e:
        log(f"  ❌ pusher 异常: {type(e).__name__}: {e}")
        return 1


# ── Main ─────────────────────────────────────────────────────────

def run_step(step_name, date_str, dry_run=False):
    """调度单个 step"""
    log(f"\n{'='*60}")
    log(f"  STEP: {step_name} - {STEP_DESC.get(step_name, '?')}")
    log(f"{'='*60}")
    
    fn = globals().get(f"step_{step_name}")
    if not fn:
        log(f"❌ 未知 step: {step_name}")
        return 1
    return fn(date_str, dry_run)


def main():
    ap = argparse.ArgumentParser(description="财经早餐发布主流程 v2 真实实现版")
    ap.add_argument("--date", default=shanghai_today_str(), help="日期 YYYYMMDD (默认今天)")
    ap.add_argument("--step", default="all", help=f"执行的 step, 逗号分隔 (可选: {','.join(STEP_NAMES)}, *_only 后缀, 或 'all')")
    ap.add_argument("--dry-run", action="store_true", help="不实际执行")
    args = ap.parse_args()
    
    date_str = args.date
    step_spec = args.step
    
    log(f"\n{'#'*60}")
    log(f"# finance_breakfast.py v2 - {date_str}")
    log(f"# step: {step_spec}")
    log(f"# dry-run: {args.dry_run}")
    log(f"{'#'*60}\n")
    
    if step_spec == "all":
        steps = STEP_NAMES
    else:
        # 兼容 "fetch_only" / "format_only" / "fetch,format,push" 等
        steps = [s.replace("_only", "") for s in step_spec.split(",")]
    
    # 验证 + 排序 (按 STEP_NAMES 顺序)
    valid = [s for s in steps if s in STEP_NAMES]
    invalid = [s for s in steps if s not in STEP_NAMES]
    if invalid:
        log(f"❌ 无效 step: {invalid}")
        log(f"   有效: {STEP_NAMES}")
        return 1
    steps_ordered = [s for s in STEP_NAMES if s in valid]
    
    rc_total = 0
    for s in steps_ordered:
        rc = run_step(s, date_str, args.dry_run)
        if rc == 2:
            log(f"  ⏭ step {s} 跳过")
            continue
        if rc != 0:
            log(f"  ❌ step {s} 失败 rc={rc}, 终止后续")
            rc_total = rc
            break
    
    log(f"\n{'#'*60}")
    log(f"# 完成. date={date_str}, steps={steps_ordered}, rc={rc_total}")
    log(f"{'#'*60}\n")
    return rc_total


if __name__ == "__main__":
    sys.exit(main())
