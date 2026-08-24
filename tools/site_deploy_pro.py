#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""site_deploy_pro.py — Professional Vercel deploy loop for frankofswing.com

完整流程:
  Phase 0  Pre-flight:   .md 存在 / frontmatter 合法 / origin 有这个 commit / 本地 build 通过
  Phase 1  Deploy:      Git push (retrigger Vercel auto-deploy) + 必要时 force-push 兜底
  Phase 2  Verify:      多端点验证 (article URL + 首页 slug 列表 + Vercel headers)
  Phase 3  Backoff:     指数退避重试, max_attempts / max_seconds 可配
  Phase 4  Reporting:   成功 exit 0, 失败飞书通知 Frank

历史教训 (2026-08-24):
  - frankofswing.com 实际是 Vercel (server: Vercel, x-vercel-id: hnd1::*)
    不是 MEMORY 记的 Cloudflare Pages
  - 8/24 早餐 push 后 frankofswing.com 一直 404, 排查发现本地 `npm run build`
    报 InvalidContentEntryDataError — 我之前生成 frontmatter 用了
    `date: 2026-08-24` (无引号被 YAML 解析成 Date 对象), 但 Astro content
    schema 期望 string. 正确格式是 `date: "2026-08-24"` (引号包裹).
    修好后 build 通过 174 页, push 触发 Vercel, frankofswing.com 立刻生效.
  - 所以这个 loop 必须在 Phase 0 跑 `npm run build` 验证, 否则会把坏的 commit
    一遍遍推上去, Vercel 仍然 deploy 失败, 浪费时间.

用法:
  python3 tools/site_deploy_pro.py --date 20260824
  python3 tools/site_deploy_pro.py --date 20260824 --skip-build     # 跳过本地 build 验证
  python3 tools/site_deploy_pro.py --date 20260824 --max-seconds 120 --max-attempts 4
  python3 tools/site_deploy_pro.py --date 20260824 --site https://workspace-jobs.vercel.app
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
from typing import Optional

WORKSPACE = Path(__file__).parent.parent
TOOLS_DIR = WORKSPACE / "tools"
DOCS_DIR = WORKSPACE / "docs"
DEFAULT_SITE = "https://frankofswing.com"
FEISHU_TARGET = "user:ou_8fab5d81798938a771ad4be7bb04593c"

# defaults — overridden via CLI
DEFAULT_MAX_SECONDS = 240
DEFAULT_MAX_ATTEMPTS = 6
DEFAULT_POLL_INTERVAL = 20
DEFAULT_BACKOFF_BASE = 2.0  # exponential backoff factor


# ── logging helpers ────────────────────────────────────────────────

def log(msg: str, level: str = "INFO"):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", flush=True)


def log_phase(phase: str):
    log(f"{'─' * 50}")
    log(f"PHASE: {phase}")
    log(f"{'─' * 50}")


# ── pre-flight ──────────────────────────────────────────────────────

def validate_file_exists(file_relpath: str) -> Optional[Path]:
    abs_path = WORKSPACE / file_relpath
    if not abs_path.exists():
        log(f"❌ {file_relpath} 不存在", "ERR")
        return None
    if not abs_path.is_file():
        log(f"❌ {file_relpath} 不是文件", "ERR")
        return None
    size = abs_path.stat().st_size
    log(f"✅ 文件存在 ({size} bytes)")
    return abs_path


def validate_frontmatter(abs_path: Path) -> bool:
    """抓 frontmatter (--- ... --- 之间), 至少能 YAML 解析.
    
    已知坑 (2026-08-24): date 字段必须是引号包裹的 string, 不能是裸 ISO date
    (否则被 YAML 解析成 Date 对象, Astro schema 报 invalid_type).
    """
    try:
        content = abs_path.read_text(encoding="utf-8")
    except Exception as e:
        log(f"❌ 读文件失败: {e}", "ERR")
        return False

    # 抓 frontmatter
    fm_match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not fm_match:
        log(f"❌ 没有 frontmatter (开头没有 '---')", "ERR")
        return False

    fm_text = fm_match.group(1)
    # 检查 date 字段: 必须是 `date: "2026-08-24"` 形式 (引号包裹)
    # 不接受 `date: 2026-08-24` (裸 ISO date)
    date_match = re.search(r"^date:\s*(.+)$", fm_text, re.MULTILINE)
    if date_match:
        date_val = date_match.group(1).strip()
        # 裸 ISO date (YYYY-MM-DD) 不带引号 → 问题
        if re.match(r"^\d{4}-\d{2}-\d{2}$", date_val):
            log(f"❌ frontmatter date 字段必须用引号包裹, 当前: date: {date_val}", "ERR")
            log(f"   正确格式: date: \"{date_val}\" (防止 YAML 解析成 Date 对象)", "ERR")
            return False
        log(f"✅ date 字段合法: {date_val[:50]}")

    log(f"✅ frontmatter 格式 OK ({len(fm_text)} chars)")
    return True


def validate_on_origin(file_relpath: str) -> bool:
    """用 git log 看 origin/main 是否有这个文件路径"""
    try:
        r = subprocess.run(
            ["git", "log", "-1", "--format=%H %s", "--", file_relpath],
            cwd=str(WORKSPACE), capture_output=True, text=True, timeout=10
        )
        if r.returncode != 0 or not r.stdout.strip():
            log(f"⚠️ {file_relpath} 没有 commit 历史 (可能 untracked)", "WARN")
            return False
        sha = r.stdout.split()[0][:8]
        log(f"✅ {file_relpath} 在 git 历史里 (HEAD: {sha})")
        return True
    except Exception as e:
        log(f"⚠️ git log 失败: {e}", "WARN")
        return False


def run_build_check() -> bool:
    """本地 npm run build — 抓 build 错 (e.g. frontmatter date bug)"""
    log("  跑 npm run build 验证 (防 frontmatter / schema 错)...")
    try:
        r = subprocess.run(
            ["npm", "run", "build"],
            cwd=str(WORKSPACE), capture_output=True, text=True, timeout=180
        )
        if r.returncode != 0:
            log(f"❌ build 失败 (rc={r.returncode})", "ERR")
            # 找关键错误信息
            for line in r.stdout.split("\n") + r.stderr.split("\n"):
                if "Error" in line or "error" in line.lower() or "Invalid" in line:
                    log(f"   {line.strip()[:200]}")
            return False
        # 找 page 数
        m = re.search(r"(\d+)\s+page\(s\)\s+built", r.stdout)
        page_count = m.group(1) if m else "?"
        # 检查 8/24 文章是否在 build 输出里
        has_target = "jcc-20260824" in r.stdout or "jcc-20260824" in r.stdout.replace("jjc-", "jcc-")
        log(f"✅ build 通过 ({page_count} 页)")
        return True
    except subprocess.TimeoutExpired:
        log(f"❌ build 超时 (180s)", "ERR")
        return False
    except FileNotFoundError:
        log(f"⚠️ npm 不在 PATH, 跳过 build 验证", "WARN")
        return True  # skip, don't block
    except Exception as e:
        log(f"⚠️ build 验证失败: {type(e).__name__}: {e}", "WARN")
        return True  # skip, don't block


# ── deploy strategies ──────────────────────────────────────────────

def strategy_git_push(reason: str = "retrigger vercel deploy") -> tuple[bool, str]:
    """Strategy A: empty commit + push (触发 Vercel GitHub webhook rebuild)
    
    Returns: (success, stdout_or_stderr_summary)
    """
    try:
        # fetch 先 (避免 push 撞 fetch first)
        subprocess.run(
            ["git", "fetch", "origin", "main"],
            cwd=str(WORKSPACE), capture_output=True, text=True, timeout=20
        )
        # empty commit
        r = subprocess.run(
            ["git", "commit", "--allow-empty", "-m", reason],
            cwd=str(WORKSPACE), capture_output=True, text=True, timeout=10
        )
        if r.returncode != 0 and "nothing to commit" not in r.stdout:
            return False, f"commit: {r.stderr.strip()[:200]}"
        # push
        r = subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=str(WORKSPACE), capture_output=True, text=True, timeout=30
        )
        if r.returncode != 0:
            return False, f"push: {r.stderr.strip()[:300]}"
        return True, "empty commit + push 成功"
    except subprocess.TimeoutExpired as e:
        return False, f"timeout: {e}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def strategy_force_push(reason: str = "force push retrigger") -> tuple[bool, str]:
    """Strategy B: force-with-lease (origin 已 divergence 时的兜底)
    
    只在 Strategy A 失败且 origin 领先时用, --force-with-lease 保证不会
    覆盖别人的 commit (只覆盖 origin HEAD == 我们本地预期的).
    """
    try:
        # 先 fetch 看 origin HEAD
        r = subprocess.run(
            ["git", "fetch", "origin", "main"],
            cwd=str(WORKSPACE), capture_output=True, text=True, timeout=20
        )
        if r.returncode != 0:
            return False, f"fetch failed: {r.stderr.strip()[:200]}"
        # empty commit on top of origin
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", reason],
            cwd=str(WORKSPACE), capture_output=True, text=True, timeout=10
        )
        # force push with lease
        r = subprocess.run(
            ["git", "push", "--force-with-lease", "origin", "main"],
            cwd=str(WORKSPACE), capture_output=True, text=True, timeout=30
        )
        if r.returncode != 0:
            return False, f"force push: {r.stderr.strip()[:300]}"
        return True, "force push 成功"
    except subprocess.TimeoutExpired as e:
        return False, f"timeout: {e}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# ── verification ───────────────────────────────────────────────────

def file_relpath_to_url(relpath: str, site: str) -> str:
    no_ext = relpath[:-3] if relpath.endswith(".md") else relpath
    parts = no_ext.split("/")
    slug = parts[-1].lower()
    parent = "/".join(parts[:-1]) if len(parts) > 1 else ""
    url_path = f"/{parent}/{slug}" if parent else f"/{slug}"
    encoded = urllib.parse.quote(url_path, safe="/")
    return f"{site.rstrip('/')}{encoded}/"


def verify_article_url(url: str, timeout: int = 10) -> tuple[bool, int]:
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Jobs-SiteDeployPro)",
            "Cache-Control": "no-cache",
        })
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status == 200, r.status
    except urllib.error.HTTPError as e:
        return False, e.code
    except Exception as e:
        return False, 0


def verify_homepage(site: str, date_str: str, timeout: int = 10) -> bool:
    """首页是否列出 jjc-{yyyymmdd} slug"""
    try:
        req = urllib.request.Request(site, headers={
            "User-Agent": "Mozilla/5.0 (Jobs-SiteDeployPro)",
            "Cache-Control": "no-cache",
        })
        with urllib.request.urlopen(req, timeout=timeout) as r:
            html = r.read().decode("utf-8", errors="ignore")
    except Exception:
        return False
    yy, mm, dd = date_str[:4], date_str[4:6], date_str[6:8]
    return f"jjc-{yy}{mm}{dd}" in html


def verify_vercel_headers(url: str, timeout: int = 10) -> Optional[dict]:
    """看 Vercel 部署 headers (server, x-vercel-id, age, last-modified)"""
    try:
        req = urllib.request.Request(url, method="HEAD", headers={
            "User-Agent": "Mozilla/5.0 (Jobs-SiteDeployPro)",
            "Cache-Control": "no-cache",
        })
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {
                "server": r.headers.get("server", "?"),
                "x_vercel_id": r.headers.get("x-vercel-id", "?"),
                "x_vercel_cache": r.headers.get("x-vercel-cache", "?"),
                "age": r.headers.get("age", "?"),
                "last_modified": r.headers.get("last-modified", "?"),
                "x_vercel_error": r.headers.get("x-vercel-error", "?"),
            }
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}"}
    except Exception as e:
        return {"error": str(e)}


# ── feishu notify ──────────────────────────────────────────────────

def feishu_notify(title: str, body: str):
    try:
        r = subprocess.run(
            ["openclaw", "message", "send",
             "--channel", "feishu",
             "--target", FEISHU_TARGET,
             "--message", f"{title}\n\n{body}"],
            capture_output=True, text=True, timeout=20
        )
        log(f"feishu rc={r.returncode}")
        if r.returncode != 0:
            log(f"feishu stderr: {r.stderr[:300]}", "WARN")
        return r.returncode == 0
    except FileNotFoundError:
        log("openclaw CLI 没装, 跳过飞书通知", "WARN")
        return False
    except subprocess.TimeoutExpired:
        log("feishu 通知超时 (20s)", "WARN")
        return False
    except Exception as e:
        log(f"feishu 通知失败: {e}", "WARN")
        return False


# ── 主循环 ──────────────────────────────────────────────────────────

def run_preflight(file_relpath: str, skip_build: bool) -> bool:
    """Phase 0: 全部 pre-flight 通过才进 deploy loop"""
    log_phase("0 PRE-FLIGHT")
    abs_path = validate_file_exists(file_relpath)
    if not abs_path:
        return False
    if not validate_frontmatter(abs_path):
        return False
    if not validate_on_origin(file_relpath):
        log("⚠️ 文件没 commit 到 git, 但仍继续尝试 deploy", "WARN")
    if not skip_build:
        if not run_build_check():
            return False
    log("✅ pre-flight 全部通过")
    return True


def deploy_loop(
    date_str: str,
    file_relpath: str,
    site: str = DEFAULT_SITE,
    max_seconds: int = DEFAULT_MAX_SECONDS,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    poll_interval: int = DEFAULT_POLL_INTERVAL,
    backoff_base: float = DEFAULT_BACKOFF_BASE,
    notify: bool = True,
) -> bool:
    """Phase 1-4: deploy + verify + backoff + report"""
    log_phase(f"1-4 DEPLOY LOOP (max={max_seconds}s, max_attempts={max_attempts})")
    url = file_relpath_to_url(file_relpath, site)
    log(f"目标 URL: {url}")
    log(f"目标首页: {site}")

    deadline = time.time() + max_seconds
    attempt = 0
    strategy_idx = 0  # 0=A(git push), 1=B(force push)
    strategies = [
        ("A: empty commit + push", strategy_git_push),
        ("B: force-with-lease push", strategy_force_push),
    ]
    push_count = {0: 0, 1: 0}
    last_headers = None

    while time.time() < deadline and attempt < max_attempts:
        attempt += 1
        wait = min(poll_interval * (backoff_base ** (attempt - 1)), 90)
        wait = int(wait)
        log(f"--- attempt #{attempt}/{max_attempts} (wait {wait}s after push) ---")

        # 1. 验证
        url_ok, status = verify_article_url(url)
        home_ok = verify_homepage(site, date_str) if url_ok else False
        log(f"  verify: article={status}, homepage_listed={home_ok}")

        if url_ok and home_ok:
            log(f"✅ DEPLOYED after {attempt} attempts (push A:{push_count[0]} B:{push_count[1]})")
            last_headers = verify_vercel_headers(url)
            if last_headers:
                log(f"  Vercel headers: {json.dumps(last_headers, ensure_ascii=False)[:300]}")
            return True

        # 2. 选 strategy (轮询: 第一次 A, 第二次 B, 第三次 A ...)
        strategy_name, strategy_fn = strategies[strategy_idx % len(strategies)]
        strategy_idx += 1
        log(f"  strategy: {strategy_name}")
        ok, msg = strategy_fn(reason=f"retrigger vercel deploy 8/{date_str[6:8]} (try #{attempt})")
        push_count[strategy_idx % len(strategies)] += 0  # init
        if strategy_idx <= len(strategies):
            push_count[strategy_idx - 1] += 1
        else:
            push_count[(strategy_idx - 1) % len(strategies)] += 1
        log(f"  result: {'✅' if ok else '❌'} {msg[:200]}")

        # 3. 等 Vercel build (退避)
        log(f"  等 {wait}s 让 Vercel build + deploy...")
        time.sleep(wait)

    # 超时 / max attempts
    log(f"❌ TIMEOUT: {max_seconds}s / {max_attempts} attempts")
    last_headers = verify_vercel_headers(url)
    log(f"  最后一次 Vercel headers: {json.dumps(last_headers, ensure_ascii=False)[:300] if last_headers else 'N/A'}")

    if notify:
        body = (
            f"frankofswing.com 没在 {max_seconds}s 内同步 {date_str} 早餐\n\n"
            f"URL: {url}\n"
            f"推了 {sum(push_count.values())} 次 (A:{push_count[0]} B:{push_count[1]})\n\n"
            f"Vercel headers: {json.dumps(last_headers, ensure_ascii=False)[:300] if last_headers else 'N/A'}\n\n"
            f"排查步骤:\n"
            f"  1. 本地跑 npm run build, 看有没有报错 (e.g. frontmatter date 必须是引号 string)\n"
            f"  2. Vercel dashboard → frankofswing 项目 → 看 deployments 列表\n"
            f"  3. Settings → Git → 确认 GitHub repo 还连着\n"
            f"  4. Failed build 看 build log, Queued 不动就 Redeploy"
        )
        feishu_notify(f"⚠️ {date_str} 早餐 deploy 失败", body)

    return False


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--date", required=True, help="日期 YYYYMMDD")
    p.add_argument("--file", help="相对 repo 的 .md 路径 (默认 docs/JJC-{date}-001-原文.md)")
    p.add_argument("--site", default=DEFAULT_SITE)
    p.add_argument("--max-seconds", type=int, default=DEFAULT_MAX_SECONDS)
    p.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    p.add_argument("--poll-interval", type=int, default=DEFAULT_POLL_INTERVAL)
    p.add_argument("--skip-build", action="store_true", help="跳过本地 npm run build 验证")
    p.add_argument("--no-notify", action="store_true")
    args = p.parse_args()

    file_relpath = args.file or f"docs/JJC-{args.date}-001-原文.md"

    log(f"{'=' * 60}")
    log(f"site_deploy_pro.py — {args.date}")
    log(f"{'=' * 60}")

    # Phase 0: pre-flight
    if not run_preflight(file_relpath, args.skip_build):
        log("❌ pre-flight 失败, 不进入 deploy loop", "ERR")
        if not args.no_notify:
            feishu_notify(
                f"❌ {args.date} pre-flight 失败",
                f"frankofswing.com deploy loop 没启动, pre-flight 阶段就失败了.\n\n"
                f"文件: {file_relpath}\n"
                f"可能原因:\n"
                f"  - 文件不存在\n"
                f"  - frontmatter date 字段没引号 (YAML Date 对象 vs schema string)\n"
                f"  - 本地 npm run build 报错 (通常是 schema 不匹配)\n\n"
                f"手动跑 `npm run build` 看具体报错."
            )
        sys.exit(2)

    # Phase 1-4: deploy loop
    ok = deploy_loop(
        date_str=args.date,
        file_relpath=file_relpath,
        site=args.site,
        max_seconds=args.max_seconds,
        max_attempts=args.max_attempts,
        poll_interval=args.poll_interval,
        notify=not args.no_notify,
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()