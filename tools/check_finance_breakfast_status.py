#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""财经早餐重试窗口 —— 只读验收检查（2026-09-18 上线时配套）

一次把「今天到底有没有发出去 / 是源端没发还是我们抓不到 / 调度有没有双跑」查清楚。
只读：不改任何文件、不碰 OpenClaw 配置、不触发抓取。

用法:
  python3 tools/check_finance_breakfast_status.py
  python3 tools/check_finance_breakfast_status.py --date 20260918
"""
import argparse
import json
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

WORKSPACE_JOBS = Path.home() / ".openclaw" / "workspace-jobs"
DOCS_DIR = WORKSPACE_JOBS / "docs"
CRON_DB = Path.home() / ".openclaw" / "state" / "openclaw.sqlite"
RETRY_STATUS = Path("/tmp/finance_breakfast_retry_status.json")
RETRY_LOG = Path("/tmp/finance_breakfast_retry.log")
LAUNCHD_LOG = WORKSPACE_JOBS / "logs" / "launchd-daily.out.log"

SHANGHAI = timezone(timedelta(hours=8))


def hr(title):
    print(f"\n{'-' * 60}\n{title}\n{'-' * 60}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now(SHANGHAI).strftime("%Y%m%d"))
    args = ap.parse_args()
    d = args.date

    hr(f"1. 当天文章是否落地（date={d}）")
    docs = sorted(DOCS_DIR.glob(f"JJC-{d}-*-原文.md"))
    if docs:
        for p in docs:
            print(f"  OK {p.name}  {p.stat().st_size} bytes  mtime={datetime.fromtimestamp(p.stat().st_mtime):%m-%d %H:%M}")
    else:
        print("  NO 当天没有 docs/JJC-*-原文.md")
    marker = Path(f"/tmp/finance_breakfast_published_{d}.json")
    print(f"  发布标记: {marker.read_text().strip() if marker.exists() else '（无，说明还没确认推送成功）'}")

    hr("2. 重试窗口最后一次运行结论")
    if RETRY_STATUS.exists():
        st = json.loads(RETRY_STATUS.read_text())
        print(f"  date={st.get('date')}  窗口到 {st.get('window_end')}  间隔 {st.get('interval_min')}min")
        print(f"  最终分类: {st.get('final')}")
        for a in st.get("attempts", []):
            print(f"    - #{a['n']} {a['at']} rc={a['rc']} bucket={a['bucket']} 可见帖子={a.get('visible_posts')}")
        if st.get("lock_contention"):
            print(f"  锁冲突（正常，说明有两个调度同时触发）: {st['lock_contention']}")
    else:
        print("  （还没有状态文件，说明窗口没跑过）")
    if RETRY_LOG.exists():
        print("  日志尾部:")
        for line in RETRY_LOG.read_text().splitlines()[-4:]:
            print(f"    {line}")

    hr("3. launchd 调度状态")
    try:
        out = subprocess.run(["launchctl", "list", "ai.finance-breakfast.daily"],
                             capture_output=True, text=True, timeout=15).stdout
        for line in out.splitlines():
            if any(k in line for k in ("LastExitStatus", "ProgramArguments", "/usr/bin/python3")):
                print(f"  {line.strip()}")
    except Exception as e:
        print(f"  launchctl 查询失败: {e}")
    if LAUNCHD_LOG.exists():
        rows = [l for l in LAUNCHD_LOG.read_text(errors="replace").splitlines() if l.strip()][-3:]
        print("  launchd-daily.out.log 尾部:")
        for line in rows:
            print(f"    {line[:160]}")

    hr("4. OpenClaw cron：有没有双跑")
    if not CRON_DB.exists():
        print("  （找不到 gateway state 库，跳过）")
        return 0
    db = sqlite3.connect(f"file:{CRON_DB}?mode=ro", uri=True)
    try:
        print("  daily_catch / ce064e9d 相关 job:")
        for jid, name, enabled, agent in db.execute(
                "select job_id, name, enabled, coalesce(agent_id,'(无 owner)') from cron_jobs "
                "where name like '%daily_catch%' or job_id='ce064e9d-91ea-496d-97c8-151a1cadc4df';"):
            flag = "启用" if enabled else "已停用"
            print(f"    - {jid[:12]}… name={name} {flag} agent={agent}")
        rows = list(db.execute(
            "select job_id, status, datetime(started_at_ms/1000,'unixepoch','+8 hours') "
            "from cron_run_receipts order by started_at_ms desc limit 5;"))
        print(f"  最近收据（共 {len(rows)} 条）:")
        for jid, status, ts in rows:
            print(f"    - {jid[:12]}… {status} {ts}")
        if not rows:
            print("    （0 条 -> OpenClaw 侧从未真正执行，实际只有 launchd 在跑）")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
