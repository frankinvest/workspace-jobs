#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""site_sync.py — 验证 GitHub 推送到 frankofswing.com (CF Pages) 是否同步

用法:
  python3 tools/site_sync.py --date 20260824
  python3 tools/site_sync.py --date 20260824 --timeout 300 --poll-interval 10

为什么需要:
  frankofswing.com 是 Cloudflare Pages, 监听 GitHub main push 应该自动 build + deploy.
  但实际上 CF Pages 经常罢工 (auto-deploy 失败, queue 阻塞, 集成断开等),
  不会自动 retry, 也不会主动告知 GitHub push 的人.
  这个工具在 push 之后, 主动去 frankofswing.com 验证文件是否生效, 失败就飞书通知.

前置依赖: stdlib only (urllib.request, 不依赖 requests/akshare)
"""
import argparse
import json
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
DEFAULT_TIMEOUT = 240        # 4 分钟
DEFAULT_POLL_INTERVAL = 10   # 每 10s 轮询
DEFAULT_RETRY_AFTER_FOUND = 6  # 连续 N 次 200 才算真正生效 (防 build 中途返回部分页面)

FEISHU_TARGET = "user:ou_8fab5d81798938a771ad4be7bb04593c"  # Frank


def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def check_url(url: str, timeout: int = 10) -> tuple[int, str]:
    """GET url, return (http_code, body_first_500_chars)"""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Jobs-SiteSync)",
            "Cache-Control": "no-cache",
        })
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", errors="ignore")
            return r.status, body[:500]
    except urllib.error.HTTPError as e:
        return e.code, ""
    except urllib.error.URLError as e:
        return 0, str(e.reason)
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


def file_relpath_to_url(relpath: str, site: str = DEFAULT_SITE) -> str:
    """Convert 'docs/JJC-20260824-001-原文.md' to site URL

    frankofswing.com Astro 用 lowercase jjc 前缀 + 去掉 .md
    注意: 中文字符必须 percent-encode, 否则 urllib.request.urlopen 报 UnicodeEncodeError
    """
    # docs/JJC-YYYYMMDD-NNN-...原文.md -> /docs/jjc-YYYYMMDD-NNN-...原文/
    no_ext = relpath[:-3] if relpath.endswith(".md") else relpath
    # 取最后一段 (basename) 作为 slug
    parts = no_ext.split("/")
    slug = parts[-1].lower()  # Astro 大概率会 lowercase
    parent = "/".join(parts[:-1]) if len(parts) > 1 else ""
    # Astro 把 docs/ 转成 /docs/
    url_path = f"/{parent}/{slug}" if parent else f"/{slug}"
    # percent-encode 路径部分 (含中文) 但保留 / 分隔符
    encoded_path = urllib.parse.quote(url_path, safe="/")
    url = f"{site.rstrip('/')}{encoded_path}/"
    return url


def homepage_contains(site: str, date_str: str, slug_hint: str = "") -> bool:
    """Check frankofswing.com homepage contains the new article slug."""
    try:
        req = urllib.request.Request(site, headers={
            "User-Agent": "Mozilla/5.0 (Jobs-SiteSync)",
            "Cache-Control": "no-cache",
        })
        with urllib.request.urlopen(req, timeout=10) as r:
            html = r.read().decode("utf-8", errors="ignore")
    except Exception as e:
        log(f"  homepage fetch err: {e}")
        return False
    # date pattern: jjc-{date_str[:4]}{date_str[4:6]}{date_str[6:8]}
    yy = date_str[:4]; mm = date_str[4:6]; dd = date_str[6:8]
    pat = f"jjc-{yy}{mm}{dd}"
    if pat in html:
        return True
    # fallback: slug hint
    if slug_hint and slug_hint.lower() in html.lower():
        return True
    return False


def feishu_notify(title: str, body: str):
    """Send Feishu DM to Frank via openclaw message send."""
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
            log(f"  feishu stderr: {r.stderr[:500]}")
    except FileNotFoundError:
        log(f"  ⚠ openclaw CLI not found, skipping feishu")
    except Exception as e:
        log(f"  ⚠ feishu notify failed: {e}")


def verify_deploy(date_str: str, file_relpath: str, site: str = DEFAULT_SITE,
                   timeout: int = DEFAULT_TIMEOUT, poll_interval: int = DEFAULT_POLL_INTERVAL,
                   notify: bool = True) -> bool:
    """Wait for frankofswing.com to show the new article.

    Returns True if deployed within timeout, False otherwise.
    """
    url = file_relpath_to_url(file_relpath, site)
    log(f"target URL: {url}")
    log(f"date: {date_str}, timeout: {timeout}s, poll: {poll_interval}s")

    deadline = time.time() + timeout
    found_count = 0
    attempts = 0
    last_status = None
    last_body = ""
    first_404_at = None

    while time.time() < deadline:
        attempts += 1
        status, body = check_url(url)
        on_homepage = False
        if status == 200:
            on_homepage = homepage_contains(site, date_str)
            log(f"  attempt #{attempts}: HTTP {status}, on_homepage={on_homepage}")
            if on_homepage:
                found_count += 1
                if found_count >= 2:  # 2 次确认
                    log(f"✅ DEPLOYED after {attempts} attempts ({attempts * poll_interval}s)")
                    return True
            else:
                # 200 但首页还没看到 → 可能 build 中
                found_count = 0
        else:
            log(f"  attempt #{attempts}: HTTP {status} {body[:100]}")
            found_count = 0
            if status == 404 and first_404_at is None:
                first_404_at = time.time()

        last_status = status
        last_body = body
        time.sleep(poll_interval)

    # timeout
    elapsed = timeout
    log(f"❌ TIMEOUT after {elapsed}s ({attempts} attempts, last status={last_status})")
    if notify:
        msg = (f"frankofswing.com 没在 {elapsed}s 内同步 {date_str} 早餐\n\n"
               f"URL: {url}\n"
               f"最后状态: HTTP {last_status}\n"
               f"响应: {last_body[:200]}\n\n"
               f"可能原因:\n"
               f"  - CF Pages auto-deploy 失败/排队\n"
               f"  - GitHub → CF Pages integration 断开\n"
               f"  - build 报错 (Astro 静态生成失败)\n\n"
               f"建议: 手动到 CF Pages Dashboard 检查 build 状态, 或重连 GitHub 集成")
        feishu_notify(f"⚠️ {date_str} 早餐未自动部署", msg)
    return False


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--date", required=True, help="日期 YYYYMMDD (例: 20260824)")
    p.add_argument("--file", help="相对于 repo 的 .md 文件路径 (默认 docs/JJC-{date}-001-原文.md)")
    p.add_argument("--site", default=DEFAULT_SITE, help="站点 URL (默认 frankofswing.com)")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help=f"超时秒数 (默认 {DEFAULT_TIMEOUT})")
    p.add_argument("--poll-interval", type=int, default=DEFAULT_POLL_INTERVAL, help=f"轮询间隔秒 (默认 {DEFAULT_POLL_INTERVAL})")
    p.add_argument("--no-notify", action="store_true", help="不发送飞书通知")
    args = p.parse_args()

    file_relpath = args.file or f"docs/JJC-{args.date}-001-原文.md"
    ok = verify_deploy(
        date_str=args.date,
        file_relpath=file_relpath,
        site=args.site,
        timeout=args.timeout,
        poll_interval=args.poll_interval,
        notify=not args.no_notify,
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()