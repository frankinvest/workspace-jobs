#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_local_images.py — 审计「文章引用的站内图片」是否真的在远端/线上，并补推缺失的

背景（2026-09-22）：批量推送时撞 GitHub secondary rate limit，个别图片静默没上去，
导致文章页引用了不存在的本地路径（线上 404）。本脚本做两件事：

  1. 从 docs/JJC-*.md（默认只查 date >= --since）里抽出所有 /images/... 引用
  2. 逐个查 GitHub 远端是否存在；缺失的用 system_api_pusher.py 补推（带节流 + 重试）

用法:
  python3 tools/audit_local_images.py --since 20260624            # 只审计，报告缺失
  python3 tools/audit_local_images.py --since 20260624 --fix      # 审计 + 补推
  python3 tools/audit_local_images.py --since 20260624 --verify-online   # 再抽查线上 200
"""
import argparse
import json
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
IMG_RE = re.compile(r"/images/JJC-[^\"')\s]+")


def repo_token():
    url = subprocess.run(["git", "remote", "get-url", "origin"], cwd=ROOT,
                         capture_output=True, text=True).stdout.strip()
    m = re.search(r"https://([^@]+)@github\.com/(.+?)(?:\.git)?$", url)
    if not m:
        raise SystemExit("无法从 git remote 解析 token")
    return m.group(1).split(":")[-1], m.group(2)


TOK, REPO = repo_token()


def remote_exists(path):
    q = urllib.parse.quote(path.lstrip("/"))
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/contents/{q}",
                                 headers={"Authorization": "Bearer " + TOK, "User-Agent": "codex"})
    for attempt in range(4):
        try:
            urllib.request.urlopen(req, timeout=25).read()
            return True
        except urllib.error.HTTPError as e:            # noqa: F821
            if e.code == 404:
                return False
            time.sleep(2 + attempt * 2)                # 403/429 等：退避重试
        except Exception:
            time.sleep(2)
    return None                                        # 未知：当作缺失但标记


def push(path):
    cp = subprocess.run(["python3", "tools/system_api_pusher.py", "--file", path,
                         "--commit-msg", f"chore(images): audit-repair {path}"],
                        cwd=ROOT, capture_output=True, text=True, timeout=240)
    return cp.returncode == 0 and "✅" in cp.stdout, cp.stdout[-160:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="20200101")
    ap.add_argument("--fix", action="store_true")
    ap.add_argument("--verify-online", action="store_true")
    ap.add_argument("--throttle", type=float, default=0.6)
    args = ap.parse_args()

    refs, docs_n = [], 0
    for md in sorted(DOCS.glob("JJC-2026*.md")):
        m = re.search(r"JJC-(\d{8})", md.name)
        if not m or m.group(1) < args.since:
            continue
        text = md.read_text(encoding="utf-8")
        if text.count("private.red-ring.cn"):
            print(f"! {md.name} 仍有红圈外链残留")
        found = list(dict.fromkeys(IMG_RE.findall(text)))
        if found:
            docs_n += 1
            refs.append((md.name, found))

    all_refs = [r for _, fs in refs for r in fs]
    print(f"文档 {docs_n} 篇 | 站内图片引用 {len(all_refs)} 个（去重前）")

    missing, unknown = [], []
    for i, p in enumerate(all_refs, 1):
        local = ROOT / "public" / p.lstrip("/")
        if not local.exists():
            unknown.append(("本地缺文件", p))
            continue
        ok = remote_exists(p)
        if ok is False:
            missing.append(p)
        elif ok is None:
            unknown.append(("远端查询失败", p))
        if i % 100 == 0:
            print(f"  已查 {i}/{len(all_refs)} | 缺 {len(missing)} | 异常 {len(unknown)}")
        time.sleep(args.throttle)

    print(f"\n审计结果：远端缺失 {len(missing)} | 本地/查询异常 {len(unknown)}")
    if missing[:10]:
        print("  缺失示例:", missing[:10])

    pushed = fail = 0
    if args.fix and missing:
        print("\n开始补推缺失文件…")
        for i, p in enumerate(missing, 1):
            ok, tail = push(p)
            if not ok:
                time.sleep(3)
                ok, tail = push(p)
            pushed += 1 if ok else 0
            fail += 0 if ok else 1
            if i % 20 == 0 or not ok:
                print(f"  {i}/{len(missing)} 已补 {pushed} 失败 {fail} {'' if ok else tail}")
            time.sleep(max(args.throttle, 1.0))
        print(f"补推完成：成功 {pushed} | 失败 {fail}")

    if args.verify_online:
        print("\n线上抽查…")
        bad = 0
        for p in all_refs:
            try:
                r = urllib.request.urlopen(urllib.request.Request("https://frankofswing.com" + p,
                                                                  headers={"User-Agent": "Mozilla/5.0"}), timeout=25)
                if r.status != 200:
                    bad += 1
            except Exception:
                bad += 1
        print(f"线上非 200: {bad}/{len(all_refs)}")
    return 0 if not unknown else 1


if __name__ == "__main__":
    import urllib.error                                  # noqa: E402
    sys.exit(main())
