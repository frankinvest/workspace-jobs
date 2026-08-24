#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""site_deploy_loop.py — Loop 推文章到 frankofswing.com (Vercel)

跟之前 finance_breakfast.py + system_api_pusher.py 配合, push 到 GitHub 之后,
这个 loop 主动验证 + 重试触发 Vercel deploy, 直到 frankofswing.com 上能看到文章.

策略阶梯 (按顺序循环):
  1. 验证 (already deployed) — 已经成功就退出
  2. Empty commit + git push — 触发 Vercel GitHub auto-deploy
  3. 等待 + 重验证 (Vercel build 30-120s)
  4. 飞书通知 Frank 手动 redeploy (最终 fallback)

为什么需要 loop:
  frankofswing.com 实际是 Vercel 部署 (server: Vercel + x-vercel-id: hnd1::...).
  MEMORY 之前记的是 Cloudflare Pages (错!), 实际上 Vercel GitHub integration
  偶尔会漏掉 commit 或 build 失败, 不主动通知, 不自动 retry.
  这个 loop 主动重试 empty commit + push (任何 push 都会触发 Vercel rebuild),
  把"deploy 漏单"恢复过来.

前置依赖:
  - git (push 已能通)
  - vercel CLI (备用, 没 token 时跳过)
  - openclaw CLI (飞书通知)
"""
import argparse
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path

WORKSPACE = Path(__file__).parent.parent
DEFAULT_SITE = "https://frankofswing.com"
FEISHU_TARGET = "user:ou_8fab5d81798938a771ad4be7bb04593c"  # Frank

# 默认 5 分钟上限, 隔 30s 重试一次
DEFAULT_MAX_SECONDS = 300
DEFAULT_POLL_INTERVAL = 30


def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def file_relpath_to_url(relpath: str, site: str) -> str:
    """docs/JJC-YYYYMMDD-NNN-...原文.md -> frankofswing.com URL"""
    no_ext = relpath[:-3] if relpath.endswith(".md") else relpath
    parts = no_ext.split("/")
    slug = parts[-1].lower()
    parent = "/".join(parts[:-1]) if len(parts) > 1 else ""
    url_path = f"/{parent}/{slug}" if parent else f"/{slug}"
    encoded = urllib.parse.quote(url_path, safe="/")
    return f"{site.rstrip('/')}{encoded}/"


def check_url(url: str, timeout: int = 10) -> int:
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Jobs-DeployLoop)",
            "Cache-Control": "no-cache",
        })
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def homepage_contains(site: str, date_str: str) -> bool:
    try:
        req = urllib.request.Request(site, headers={
            "User-Agent": "Mozilla/5.0 (Jobs-DeployLoop)",
            "Cache-Control": "no-cache",
        })
        with urllib.request.urlopen(req, timeout=10) as r:
            html = r.read().decode("utf-8", errors="ignore")
    except Exception:
        return False
    yy, mm, dd = date_str[:4], date_str[4:6], date_str[6:8]
    return f"jjc-{yy}{mm}{dd}" in html


def is_deployed(date_str: str, file_relpath: str, site: str = DEFAULT_SITE) -> bool:
    url = file_relpath_to_url(file_relpath, site)
    status = check_url(url)
    if status == 200:
        # 进一步确认首页有这篇文章 (防 build 中途返回部分页面)
        return homepage_contains(site, date_str)
    return False


def trigger_empty_commit_push(reason: str = "retrigger vercel deploy") -> bool:
    """Empty commit + push, 触发 Vercel GitHub webhook 重 build

    注意: push 前必须先 git fetch, 否则 origin 领先时会被 'fetch first' 拒绝.
    """
    try:
        # 0. fetch origin (避免 push 被 'fetch first' 拒绝)
        r = subprocess.run(
            ["git", "fetch", "origin", "main"],
            cwd=str(WORKSPACE), capture_output=True, text=True, timeout=30
        )
        if r.returncode != 0:
            log(f"  git fetch rc={r.returncode}: {r.stderr.strip()[:200]}")
            # 继续尝试 (fetch 失败也不一定死)
        # 1. empty commit
        r = subprocess.run(
            ["git", "commit", "--allow-empty", "-m", reason],
            cwd=str(WORKSPACE), capture_output=True, text=True, timeout=15
        )
        if r.returncode != 0 and "nothing to commit" not in r.stdout:
            log(f"  git commit rc={r.returncode}: {r.stderr.strip()[:200]}")
            return False
        # 2. push
        r = subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=str(WORKSPACE), capture_output=True, text=True, timeout=60
        )
        if r.returncode != 0:
            log(f"  git push rc={r.returncode}: {r.stderr.strip()[:300]}")
            return False
        log(f"  ✅ empty commit + push 成功")
        return True
    except subprocess.TimeoutExpired as e:
        log(f"  ⚠ git timeout: {e}")
        return False
    except Exception as e:
        log(f"  ⚠ git err: {type(e).__name__}: {e}")
        return False


def feishu_notify(title: str, body: str):
    try:
        r = subprocess.run(
            ["openclaw", "message", "send",
             "--channel", "feishu",
             "--target", FEISHU_TARGET,
             "--message", f"{title}\n\n{body}"],
            capture_output=True, text=True, timeout=30
        )
        log(f"  feishu rc={r.returncode}")
        if r.returncode != 0:
            log(f"  feishu stderr: {r.stderr[:300]}")
    except FileNotFoundError:
        log(f"  ⚠ openclaw CLI not found, skip feishu")
    except Exception as e:
        log(f"  ⚠ feishu notify failed: {e}")


def loop_until_deployed(date_str: str, file_relpath: str,
                         site: str = DEFAULT_SITE,
                         max_seconds: int = DEFAULT_MAX_SECONDS,
                         poll_interval: int = DEFAULT_POLL_INTERVAL,
                         notify: bool = True) -> bool:
    """主循环: 反复 empty commit + push + 验证, 直到 deployed 或超时"""
    log(f"date={date_str}, file={file_relpath}")
    log(f"site={site}, max={max_seconds}s, poll={poll_interval}s")
    deadline = time.time() + max_seconds
    attempt = 0
    empty_commit_count = 0

    while time.time() < deadline:
        attempt += 1
        log(f"--- attempt #{attempt} ---")

        # 1. 验证 (可能前一轮已经成功)
        if is_deployed(date_str, file_relpath, site):
            log(f"✅ DEPLOYED after {attempt} attempts, {empty_commit_count} empty commits")
            return True

        # 2. empty commit + push (触发 Vercel rebuild)
        empty_commit_count += 1
        log(f"[strategy] empty commit + push #{empty_commit_count}")
        if not trigger_empty_commit_push():
            log(f"  push 失败, 等 30s 重试")
            time.sleep(30)
            continue

        # 3. 等待 Vercel build (通常 30-120s)
        log(f"  等 {poll_interval}s 让 Vercel build + deploy")
        time.sleep(poll_interval)

    # 超时
    log(f"❌ TIMEOUT after {max_seconds}s, {empty_commit_count} empty commits")
    if notify:
        msg = (f"frankofswing.com 没在 {max_seconds}s 内同步 {date_str} 早餐\n\n"
               f"URL: {file_relpath_to_url(file_relpath, site)}\n"
               f"已 push {empty_commit_count} 次 empty commit, 仍 404\n\n"
               f"可能原因:\n"
               f"  - Vercel GitHub integration 断开 (Settings → Git)\n\n   "
               f"  - Vercel build 报错 (项目 dashboard 看 build log)\n"
               f"  - frankofswing.com DNS/域名配置失效\n\n"
               f"建议:\n"
               f"  1. 打开 https://vercel.com/muhuaxiawen-1094s-projects/workspace-jobs/deployments\n"
               f"  2. 看最近 deployments 状态 (Queued/Building/Failed)\n"
               f"  3. Failed 的话看 build log; Queued 不动就 Redeploy\n"
               f"  4. Settings → Git 确认 GitHub repo 还连着 (断的话 reconnect)")
        feishu_notify(f"⚠️ {date_str} 早餐 deploy 失败", msg)
    return False


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--date", required=True, help="日期 YYYYMMDD")
    p.add_argument("--file", help="相对 repo 的 .md 路径 (默认 docs/JJC-{date}-001-原文.md)")
    p.add_argument("--site", default=DEFAULT_SITE)
    p.add_argument("--max-seconds", type=int, default=DEFAULT_MAX_SECONDS, help=f"总超时秒 (默认 {DEFAULT_MAX_SECONDS})")
    p.add_argument("--poll-interval", type=int, default=DEFAULT_POLL_INTERVAL, help=f"每轮间隔 (默认 {DEFAULT_POLL_INTERVAL})")
    p.add_argument("--no-notify", action="store_true")
    args = p.parse_args()

    file_relpath = args.file or f"docs/JJC-{args.date}-001-原文.md"
    ok = loop_until_deployed(
        date_str=args.date,
        file_relpath=file_relpath,
        site=args.site,
        max_seconds=args.max_seconds,
        poll_interval=args.poll_interval,
        notify=not args.no_notify,
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()