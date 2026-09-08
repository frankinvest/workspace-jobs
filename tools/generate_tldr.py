#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_tldr.py - 从财经早餐文章生成「今日速递」tldr (5 分类)，写回文章 frontmatter。

用法:
  python3 tools/generate_tldr.py --file docs/JJC-YYYYMMDD-001-原文.md
  python3 tools/generate_tldr.py --date 20260908

流程:
  1. 读文章正文（去 frontmatter + 图片行）
  2. codex exec 提炼 5 分类 (macro/military/industry/commodity/stock，每类 ≤3)
  3. 解析 JSON，补 articleLink，写回 frontmatter 的 tldr 字段

说明:
  - 内容只从当天文章正文提取，无外源（遵守 frankofswing-dev 内容规则）
  - codex exec 失败时返回非 0，由调用方（finance_breakfast.py step_tldr）决定是否阻断 push
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

WORKSPACE_JOBS = Path.home() / ".openclaw" / "workspace-jobs"
DOCS_DIR = WORKSPACE_JOBS / "docs"

CATEGORIES = ("macro", "military", "industry", "commodity", "stock")

PROMPT = """你是财经速递编辑。从下方财经早餐文章正文里提取「今日速递」要点，5 个分类：
- macro 宏观
- military 军事
- industry 产业
- commodity 大宗
- stock 个股

规则：
1. 每类最多 3 条；只提取文章正文确实出现的内容，某类没有内容就省略该类。
2. 每条 title 是中文，不超过 80 字，概括一条独立信息点。
3. keyNumbers 可选，最多 3 个关键数字/数据点。
4. 只输出一个 JSON 数组，不要任何解释、不要 markdown 代码块围栏。格式：
[{"category":"macro","title":"...","keyNumbers":["..."]}]

文章正文见 stdin。"""


def log(msg):
    print(f"[tldr] {msg}", file=sys.stderr)


def find_md_file(date_str=None, file_arg=None):
    if file_arg:
        p = Path(file_arg)
        if not p.is_absolute():
            p = WORKSPACE_JOBS / p
        if not p.exists():
            raise FileNotFoundError(f"文件不存在: {p}")
        return p
    # 按日期找
    candidates = sorted(DOCS_DIR.glob(f"JJC-{date_str}-001-原文.md"))
    if not candidates:
        raise FileNotFoundError(f"找不到 {date_str} 的文章")
    return candidates[0]


def read_body(md_path):
    text = md_path.read_text(encoding="utf-8")
    # 去掉 frontmatter
    text = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.S)
    # 去掉图片行（纯 URL 噪音）
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)\n?", "", text)
    return text.strip()


def run_codex(body_text):
    out_file = tempfile.mktemp(prefix="tldr_gen_", suffix=".json")
    cmd = [
        "codex", "exec", "--ephemeral", "--skip-git-repo-check",
        "-o", out_file, PROMPT,
    ]
    log("调用 codex exec 提炼 tldr …")
    r = subprocess.run(
        cmd, input=body_text,
        capture_output=True, text=True, timeout=900,
    )
    if r.returncode != 0:
        raise RuntimeError(f"codex exec rc={r.returncode}: {r.stderr[:300]}")
    out = Path(out_file).read_text(encoding="utf-8").strip()
    if not out:
        raise RuntimeError("codex exec 输出为空")
    return out


def parse_items(raw):
    # 去掉 markdown 代码块围栏
    m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", raw, re.S)
    if m:
        raw = m.group(1)
    else:
        m = re.search(r"\[.*\]", raw, re.S)
        if m:
            raw = m.group(0)
    items = json.loads(raw)
    if not isinstance(items, list):
        raise ValueError("输出不是 JSON 数组")
    # 校验 + 规整
    cleaned = []
    for it in items:
        cat = str(it.get("category", "")).strip().lower()
        if cat not in CATEGORIES:
            continue
        title = str(it.get("title", "")).strip()
        if not title:
            continue
        title = title[:80]
        kn = it.get("keyNumbers") or []
        if isinstance(kn, str):
            kn = [kn]
        kn = [str(x).strip() for x in kn if str(x).strip()][:3]
        entry = {"category": cat, "title": title}
        if kn:
            entry["keyNumbers"] = kn
        cleaned.append(entry)
    return cleaned


def inject_tldr(md_path, items, slug):
    text = md_path.read_text(encoding="utf-8")
    lines = []
    for it in items:
        lines.append(f"  - category: {it['category']}")
        lines.append(f'    title: "{it["title"]}"')
        if it.get("keyNumbers"):
            quoted = ", ".join(f'"{k}"' for k in it["keyNumbers"])
            lines.append(f"    keyNumbers: [{quoted}]")
        lines.append(f"    articleLink: /docs/{slug}")
    tldr_block = "tldr:\n" + "\n".join(lines) + "\n"

    if re.search(r"^tldr:", text, flags=re.M):
        # 替换已有 tldr 块
        text = re.sub(
            r"^tldr:\n(?:[ \t]+.*\n?)*",
            tldr_block,
            text, count=1, flags=re.M,
        )
    else:
        # 插到 date 行后
        text = re.sub(r"(date: .*\n)", r"\1" + tldr_block, text, count=1)
    md_path.write_text(text, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="文章 md 路径（相对或绝对）")
    ap.add_argument("--date", help="日期 YYYYMMDD（与 --file 二选一）")
    ap.add_argument("--dry-run", action="store_true", help="只生成不写回")
    args = ap.parse_args()

    if not args.file and not args.date:
        ap.error("必须给 --file 或 --date")

    md_path = find_md_file(args.date, args.file)
    slug = md_path.stem.lower()
    body = read_body(md_path)
    log(f"文章: {md_path.name} | 正文字符数: {len(body)}")

    raw = run_codex(body)
    items = parse_items(raw)
    log(f"提炼到 {len(items)} 条: " + ", ".join(
        f"{i['category']}×{sum(1 for x in items if x['category'] == i['category'])}"
        for i in items[:1]
    ) if items else "0 条")
    if not items:
        raise RuntimeError("提炼结果为空")

    if args.dry_run:
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return 0

    inject_tldr(md_path, items, slug)
    log(f"✅ 已写入 {md_path.name} frontmatter tldr")
    return 0


if __name__ == "__main__":
    sys.exit(main())
