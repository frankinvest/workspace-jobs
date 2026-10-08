#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_no_duplicate_articles.py - 验证 dedupe-articles 任务完成状态

依据: agent-bus/runs/20261009-0052-dedupe-articles/test-plan.md
- T1 本地 md 只剩 2 个 (20261002 + 20261005)
- T2 被删图片目录不存在 (JJC-20261003/04/06)
- T3 JJC-20261002 有 tldr 且 articleLink 自洽
- T4 站内无死图 (surviving slug)
- T5 线上列表去重 (卷十九×1, 国庆杂谈×1)
- T6 被删 slug 返回 404

退出码: 0 = 全部通过; 非 0 = 至少 1 项失败或 SKIP
纯标准库 (仅 urllib + 标准库).
"""
from __future__ import annotations

import random
import re
import string
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent  # workspace-jobs/
DOCS = REPO / "docs"
IMG = REPO / "public" / "images"
SITE = "https://frankofswing.com"

UA = "check-no-duplicate-articles/1.0"

failures: list[tuple[str, str]] = []


def _cb() -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=8))


def fail(name: str, msg: str) -> None:
    failures.append((name, msg))
    print(f"  ❌ FAIL [{name}] {msg}")


def skip(name: str, msg: str) -> None:
    failures.append((name, f"SKIP: {msg}"))
    print(f"  ⚠️  SKIP [{name}] {msg}")


def ok(name: str, msg: str = "") -> None:
    print(f"  ✅ PASS [{name}] {msg}")


def t1_local_md_dedup() -> None:
    print("[T1] 本地 md 文件去重 (期望仅 JJC-20261002 + JJC-20261005)")
    if not DOCS.is_dir():
        fail("T1", f"docs 目录不存在: {DOCS}")
        return
    found = sorted(
        p.name for p in DOCS.glob("JJC-*.md")
        if re.match(r"JJC-2026100[2-6]-\d{3}-", p.name)
    )
    expected = {"JJC-20261002-001-原文.md", "JJC-20261005-001-原文.md"}
    got = set(found)
    extra = got - expected
    missing = expected - got
    if extra or missing:
        fail("T1", f"extra={sorted(extra)} missing={sorted(missing)} got={found}")
    else:
        ok("T1", f"{len(found)} 个 (符合预期)")


def t2_image_dirs_gone() -> None:
    print("[T2] 被删图片目录不存在 (JJC-20261003/04/06)")
    bad = [d for d in ("JJC-20261003", "JJC-20261004", "JJC-20261006") if (IMG / d).exists()]
    if bad:
        fail("T2", f"仍存在: {bad}")
    else:
        ok("T2", "3 个目录全部不存在")


def t3_tldr_self_consistent() -> None:
    print("[T3] JJC-20261002 含 tldr 且 articleLink 自洽")
    p = DOCS / "JJC-20261002-001-原文.md"
    if not p.exists():
        fail("T3", f"文件不存在: {p.name}")
        return
    text = p.read_text(encoding="utf-8")
    m = re.search(r"^tldr:\s*\n(.*?)\n---\s*\n", text, re.S | re.M)
    if not m:
        fail("T3", "未找到 tldr 块 (frontmatter 应含 'tldr:' 块)")
        return
    tldr_block = m.group(1)
    links = re.findall(r"articleLink:\s*(\S+)", tldr_block)
    if not links:
        fail("T3", "tldr 块存在但无 articleLink 字段")
        return
    expected = "/docs/jjc-20261002-001-原文"
    bad = [l for l in links if l != expected]
    if bad:
        fail("T3", f"articleLink 异常: {bad} (期望全部 == {expected})")
    else:
        ok("T3", f"{len(links)} 个 articleLink 全部 == {expected}")


def _http_get(url: str, timeout: int = 25, follow_redirects: bool = True) -> tuple[int | None, str]:
    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **kw):  # noqa: ANN001, ANN002, ANN003
            return None

    opener = urllib.request.build_opener(_NoRedirect) if not follow_redirects \
        else urllib.request.build_opener()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
        return e.code, body
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


def _http_status(url: str, timeout: int = 15) -> tuple[int | None, str | None]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, None
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


def _enc(slug: str) -> str:
    """对 slug 做 percent-encode (避开 urllib 强制 ASCII 的 bug, system_api_pusher.py 注释同款)."""
    return urllib.parse.quote(slug, safe="-")


def t4_no_dead_images() -> None:
    print("[T4] 站内无死图 (surviving slug = jjc-20261002-001-原文)")
    slug = "jjc-20261002-001-原文"
    cb = _cb()
    page_url = f"{SITE}/docs/{_enc(slug)}/?cb={cb}"
    code, html = _http_get(page_url, timeout=25)
    if code is None:
        skip("T4", f"抓取页面失败 (网络): {html}")
        return
    if code != 200:
        fail("T4", f"页面 HTTP {code} ({page_url})")
        return
    img_paths = re.findall(r'(?:src|href)="(/images/[^"\'?#]+)"', html)
    img_paths = list(dict.fromkeys(img_paths))
    if not img_paths:
        ok("T4", "页面无 /images/* 引用")
        return
    bad: list[tuple[str, int | None, str | None]] = []
    for p in img_paths:
        url = f"{SITE}{p}?cb={cb}"
        s, err = _http_status(url, timeout=10)
        if s != 200:
            bad.append((p, s, err))
    if bad:
        fail("T4", f"死图 {len(bad)}/{len(img_paths)}: 样例 {bad[:3]}")
    else:
        ok("T4", f"{len(img_paths)} 张图全部 200")


def t5_site_list_dedup() -> None:
    print("[T5] 线上列表去重 (卷十九×1, 国庆杂谈×1)")
    cb = _cb()
    code, html = _http_get(f"{SITE}/?cb={cb}", timeout=25)
    if code is None:
        skip("T5", f"抓取首页失败 (网络): {html}")
        return
    if code != 200:
        fail("T5", f"首页 HTTP {code}")
        return
    # 抓所有 /docs/jjc-* slug
    article_links = re.findall(r'href="(/docs/(jjc-\d{8}-\d{3}-[^/"]*?)/?)"', html)
    slugs = {slug for _href, slug in article_links}
    # 卷十九组: dates 20261002/3/4 → 仅应剩 20261002
    j19 = sorted(s for s in slugs if re.match(r"jjc-2026100[234]-\d{3}-", s))
    # 国庆杂谈组: dates 20261005/6 → 仅应剩 20261005
    gq = sorted(s for s in slugs if re.match(r"jjc-2026100[56]-\d{3}-", s))
    ok_j19 = len(j19) == 1 and j19[0].startswith("jjc-20261002-")
    ok_gq = len(gq) == 1 and gq[0].startswith("jjc-20261005-")
    if ok_j19 and ok_gq:
        ok("T5", f"卷十九={j19}, 国庆杂谈={gq}")
    else:
        fail("T5", f"卷十九={j19} (期望仅 jjc-20261002-xxx), 国庆杂谈={gq} (期望仅 jjc-20261005-xxx)")


def t6_deleted_urls_404() -> None:
    print("[T6] 被删 slug 线上返回 404")
    slugs = ["jjc-20261003-001-原文", "jjc-20261004-001-原文", "jjc-20261006-001-原文"]
    results: list[tuple[str, int | None, str | None]] = []
    for s in slugs:
        url = f"{SITE}/docs/{_enc(s)}/"
        # 用带 redirect 跟随的 HTTP 抓取, 看最终状态码
        code, err = _http_status(url, timeout=15)
        results.append((s, code, err))
    bad = [(s, c, e) for s, c, e in results if c != 404]
    if any(c is None for _s, c, _e in results):
        # 至少一个网络失败
        none_results = [(s, c, e) for s, c, e in results if c is None]
        skip("T6", f"网络失败: {none_results}")
        return
    if bad:
        fail("T6", f"非 404: {bad}")
    else:
        ok("T6", f"{len(slugs)} 个 slug 全部 404")


def main() -> int:
    print("=" * 60)
    print("check_no_duplicate_articles.py")
    print(f"REPO: {REPO}")
    print(f"SITE: {SITE}")
    print(f"判定: T1-T3 本地 / T4-T6 线上")
    print("=" * 60)
    t1_local_md_dedup()
    t2_image_dirs_gone()
    t3_tldr_self_consistent()
    t4_no_dead_images()
    t5_site_list_dedup()
    t6_deleted_urls_404()
    print()
    print("=" * 60)
    if failures:
        print(f"❌ {len(failures)} 项未通过:")
        for n, m in failures:
            print(f"   - [{n}] {m}")
        return 1
    print("✅ 全部通过 (6/6)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
