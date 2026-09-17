#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
finance_breakfast_retry.py — 08:00 起按间隔重试的包装器 (v1)

背景（2026-09-18 修复）:
  launchd 原来只在 08:00 跑一次 finance_breakfast.py。Mr Dang 常在 8:00 之后才发帖，
  08:00 抓 0 条就触发日期熔断，当天再也不会自动补上，只能等 Frank 早上来问。

本脚本只做调度 + 分类，不改 finance_breakfast.py 的 6 个 step:
  - 在窗口内（默认 08:00-11:00，每 30 分钟）反复调用 finance_breakfast.py
  - 每次失败按证据分类:
      source_not_posted  圈子页面正常渲染（cdp 输出「发现 N 条帖子」且 N>0）只是今天还没发
      fetch_failure      页面渲染不出来 / CDP 连不上（N=0 或没有该行）→ 我们的抓取通路问题
      push_failure       抓取+排版成功，但推送失败
  - 状态写到 /tmp/finance_breakfast_retry_<date>.json，日志 /tmp/finance_breakfast_retry.log

用法:
  python3 tools/finance_breakfast_retry.py                      # 跑完整窗口
  python3 tools/finance_breakfast_retry.py --once               # 只试一次（手动补抓 / 调试）
  python3 tools/finance_breakfast_retry.py --date 20260918 --interval-min 15 --end-hour 11

退出码:
  0  已发布（本次发布，或之前已确认发布）
  0  另一个实例正在跑（正常跳过，说明有两个调度同时触发；详情见状态文件的 lock_contention）
  3  窗口结束：源端今天没发
  4  窗口结束：抓取通路有问题（需要我们处理）
  5  窗口结束：推送失败
  1  参数/环境错误
"""
import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

WORKSPACE_JOBS = Path.home() / ".openclaw" / "workspace-jobs"
PIPELINE = WORKSPACE_JOBS / "tools" / "finance_breakfast.py"
DOCS_DIR = WORKSPACE_JOBS / "docs"
RAW_DIR = Path("/tmp")
STATUS_FILE = Path("/tmp/finance_breakfast_retry_status.json")
LOG_FILE = Path("/tmp/finance_breakfast_retry.log")
LOCK_FILE = Path("/tmp/finance_breakfast_retry.lock")
ATTEMPT_TIMEOUT = 900

SHANGHAI = timezone(timedelta(hours=8))
BUCKET_EXIT = {"source_not_posted": 3, "fetch_failure": 4, "push_failure": 5, "unknown_failure": 4}


def now():
    return datetime.now(SHANGHAI)


def log(msg):
    line = f"[{now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def write_status(payload):
    STATUS_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False))


def marker_file(date_str):
    return Path(f"/tmp/finance_breakfast_published_{date_str}.json")


def docs_file_exists(date_str):
    return bool(list(DOCS_DIR.glob(f"JJC-{date_str}-*-原文.md")))


def classify(output, rc):
    """从 finance_breakfast.py 的输出里判断失败类别

    实测（2026-09-18 00:26）三种真实表现:
      A. 今天没发时 cdp 不熔断——它把「昨天」的帖子当候选抓回来，format 的 date 校验
         拒绝写入 → guard 报「文件不存在」。判为 source_not_posted。
      B. 圈子页一条帖子都渲染不出来（N=0）→ 熔断，判为 fetch_failure。
      C. 页面正常但今天确实没帖（N>0）→ 熔断，判为 source_not_posted。
    """
    m = re.search(r"发现\s*(\d+)\s*条帖子", output)
    n_posts = int(m.group(1)) if m else None

    if "pusher 失败" in output or "pusher 异常" in output or "git commit 失败" in output:
        return "push_failure", n_posts
    # A: 抓到的是别天的帖子 → 今天还没发（或抓错帖，重试同样有意义）
    if "date 校验失败" in output or "拒绝写入文件" in output:
        return "source_not_posted", n_posts
    if "日期熔断" in output:
        return ("source_not_posted" if (n_posts or 0) > 0 else "fetch_failure"), n_posts
    # B: 抓取通路本身的问题
    for marker in ("抓取异常", "抓取超时", "cdp_get_innerhtml.py 失败", "输出文件异常", "缺少抓取脚本"):
        if marker in output:
            return "fetch_failure", n_posts
    return ("unknown_failure", n_posts) if rc != 0 else ("published", n_posts)


def run_attempt(date_str, dry_run=False):
    """跑一次 finance_breakfast.py；返回 (rc, bucket, n_posts, output)"""
    # 当天已经有 .md 但还没确认推送 → 只补 push；否则跑全流程
    if docs_file_exists(date_str):
        step = "push"
    else:
        step = "all"

    # 清掉当天残留的抓取缓存，避免失败重试时被旧缓存短路
    raw = RAW_DIR / f"finance_breakfast_raw_{date_str}.html"
    if raw.exists():
        stale = raw.with_suffix(f".html.stale-{now().strftime('%H%M%S')}")
        try:
            raw.rename(stale)
            log(f"  清掉残留抓取缓存 → {stale.name}")
        except OSError as e:
            log(f"  ⚠️ 清理缓存失败（继续）: {e}")

    cmd = [sys.executable, str(PIPELINE), "--date", date_str, "--step", step]
    if dry_run:
        cmd.append("--dry-run")
    log(f"  → {' '.join(cmd)}")
    try:
        cp = subprocess.run(cmd, cwd=WORKSPACE_JOBS, capture_output=True, text=True,
                            timeout=ATTEMPT_TIMEOUT)
    except subprocess.TimeoutExpired:
        return 1, "fetch_failure", None, f"attempt timeout >{ATTEMPT_TIMEOUT}s"

    output = (cp.stdout or "") + (cp.stderr or "")
    if cp.returncode == 0:
        return 0, "published", None, output
    bucket, n_posts = classify(output, cp.returncode)
    return cp.returncode, bucket, n_posts, output


def main():
    ap = argparse.ArgumentParser(description="财经早餐抓取重试窗口包装器")
    ap.add_argument("--date", default=now().strftime("%Y%m%d"), help="日期 YYYYMMDD（默认今天）")
    ap.add_argument("--interval-min", type=int, default=30, help="重试间隔分钟（默认 30）")
    ap.add_argument("--end-hour", type=int, default=11, help="窗口结束小时（默认 11）")
    ap.add_argument("--end-minute", type=int, default=0, help="窗口结束分钟（默认 0）")
    ap.add_argument("--once", action="store_true", help="只尝试一次，不进入重试循环")
    ap.add_argument("--dry-run", action="store_true", help="透传给 finance_breakfast.py")
    args = ap.parse_args()

    date_str = args.date
    lock_fd = os.open(LOCK_FILE, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        # 正常跳过：launchd 和 OpenClaw cron 可能同时触发同一个窗口。
        # 退出码给 0，避免被误判成故障；但写进状态文件，双调度仍然可见。
        log(f"另一个重试实例正在跑，本次正常跳过（date={date_str}）")
        prev = {}
        if STATUS_FILE.exists():
            try:
                prev = json.loads(STATUS_FILE.read_text())
            except Exception:
                prev = {}
        prev.setdefault("date", date_str)
        prev.setdefault("lock_contention", []).append(now().strftime("%Y-%m-%d %H:%M:%S GMT+8"))
        write_status(prev)
        return 0

    if not PIPELINE.exists():
        log(f"❌ 找不到 {PIPELINE}")
        return 1

    status = {
        "date": date_str,
        "started_at": now().strftime("%Y-%m-%d %H:%M:%S GMT+8"),
        "window_end": f"{args.end_hour:02d}:{args.end_minute:02d}",
        "interval_min": args.interval_min,
        "attempts": [],
        "final": "running",
    }

    if marker_file(date_str).exists():
        log(f"✅ {date_str} 已确认发布过，跳过")
        status["final"] = "already_published"
        write_status(status)
        return 0

    deadline = now().replace(hour=args.end_hour, minute=args.end_minute, second=0, microsecond=0)
    attempt = 0
    while True:
        attempt += 1
        started = now()
        log(f"[attempt {attempt}] {date_str} 开始（{started.strftime('%H:%M:%S')}）")
        rc, bucket, n_posts, output = run_attempt(date_str, args.dry_run)

        # 把 pipeline 的最后几行搬进我们的日志，便于事后定位
        for line in [l for l in output.strip().split("\n") if l.strip()][-8:]:
            log(f"    | {line[:200]}")

        status["attempts"].append({
            "n": attempt,
            "at": started.strftime("%Y-%m-%d %H:%M:%S GMT+8"),
            "rc": rc,
            "bucket": bucket,
            "visible_posts": n_posts,
        })
        write_status(status)

        if rc == 0:
            marker_file(date_str).write_text(json.dumps(
                {"date": date_str, "published_at": now().strftime("%Y-%m-%d %H:%M:%S GMT+8")},
                ensure_ascii=False))
            status["final"] = "published"
            write_status(status)
            log(f"✅ {date_str} 发布成功（第 {attempt} 次尝试）")
            return 0

        label = {
            "source_not_posted": "源端还没发（圈子能正常看到内容）",
            "fetch_failure": "抓取通路有问题（页面渲染不出来 / CDP 连不上）",
            "push_failure": "抓取成功但推送失败",
        }.get(bucket, "未知失败")
        log(f"  ❌ 第 {attempt} 次失败：{label}（rc={rc}）")

        if args.once:
            status["final"] = bucket
            write_status(status)
            return BUCKET_EXIT.get(bucket, 4)

        next_at = started + timedelta(minutes=args.interval_min)
        if next_at >= deadline:
            status["final"] = bucket
            write_status(status)
            log(f"⏹ {date_str} 窗口结束（{args.end_hour:02d}:{args.end_minute:02d}）：{label}")
            return BUCKET_EXIT.get(bucket, 4)
        wait_s = int((next_at - now()).total_seconds())
        log(f"  ⏳ {max(wait_s, 0)}s 后重试（窗口到 {args.end_hour:02d}:{args.end_minute:02d}）")
        time.sleep(max(wait_s, 0))


if __name__ == "__main__":
    sys.exit(main())
