#!/usr/bin/env python3
"""
finance_breakfast.py - 财经早餐发布主流程 (支持单步可重入)

🎯 设计哲学 (Frank 终极架构指令):
  - 【环节工具化】每个步骤都是独立函数, 可被单独调用
  - 【单步可重入】任何步骤失败, 可重新跑那个 step 断点续传
  - 【不重复拉取】失败重试时不重新做已完成的步骤

五个独立 step:
  1. fetch    - 抓取小红圈今日帖子 (用 browser/web_fetch 工具)
  2. format   - 本地排版, 生成 .md 原文文件
  3. images   - 图片本化 (下载到 public/images/YYYYMMDD/)
  4. guard    - 合规审计 (检查图片数/评论数/格式)
  5. push     - 云端推送 (调用 system_git_pusher.py 穿墙推送)

用法:
  python3 tools/finance_breakfast.py                            # 跑全流程
  python3 tools/finance_breakfast.py --step fetch_only          # 只跑抓取
  python3 tools/finance_breakfast.py --step format_only         # 只跑排版
  python3 tools/finance_breakfast.py --step images_only         # 只跑图片
  python3 tools/finance_breakfast.py --step guard_only          # 只跑审计
  python3 tools/finance_breakfast.py --step push_only           # 只跑推送 (断点续传用)
  python3 tools/finance_breakfast.py --step fetch               # 跑 fetch + 后续所有
  python3 tools/finance_breakfast.py --step fetch,format,push   # 跑指定多个 step
  python3 tools/finance_breakfast.py --date 2026-06-04          # 指定日期 (默认今天)
  python3 tools/finance_breakfast.py --dry-run                  # 不实际执行

每个 step 退出码:
  0 - 成功
  1 - 失败
  2 - 跳过 (前置条件不满足)

整体退出码:
  0 - 全部 step 成功
  非0 - 第一个失败 step 的退出码
"""
import argparse
import subprocess
import sys
import os
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

WORKSPACE_JOBS = Path.home() / ".openclaw" / "workspace-jobs"
DOCS_DIR = WORKSPACE_JOBS / "docs"
IMAGES_DIR = WORKSPACE_JOBS / "public" / "images"
STATE_FILE = Path("/tmp/finance_breakfast_state.json")
LOG_FILE = "/tmp/finance_breakfast.log"
PUSHER = WORKSPACE_JOBS / "tools" / "system_git_pusher.py"

# 步骤定义
STEP_NAMES = ["fetch", "format", "images", "guard", "push"]
STEP_DESC = {
    "fetch":  "抓取小红圈今日帖子",
    "format": "本地排版, 生成 .md 原文",
    "images": "图片本化到 public/images/",
    "guard":  "合规审计 (图片数/评论数/格式)",
    "push":   "云端推送 (调用 system_git_pusher.py)",
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


def shanghai_today_hyphen():
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def step_fetch(date_str, dry_run=False):
    """Step 1: 抓取小红圈今日帖子
    
    用内置 browser 工具 (或调用 agent 抓取脚本)
    输出: /tmp/finance_breakfast_raw_<date>.json
    """
    log(f"[fetch] 抓取 {date_str} 帖子")
    
    if dry_run:
        log("  [dry-run] 跳过")
        return 0
    
    output_file = Path(f"/tmp/finance_breakfast_raw_{date_str}.json")
    if output_file.exists():
        log(f"  ✅ 已有缓存: {output_file}")
        return 0
    
    # 实际抓取 - 调用 agent 抓取脚本或用 browser 工具
    # 这里调用一个假设的抓取脚本; 实际环境会注入 browser tools
    log(f"  ⚠️ 此 step 需要 agent 用 browser 工具手动执行")
    log(f"  抓取结果应保存到: {output_file}")
    log(f"  格式: {{title, body, images: [...], comments: [...]}}")
    return 2  # 跳过


def step_format(date_str, dry_run=False):
    """Step 2: 本地排版, 生成 .md 原文"""
    log(f"[format] 排版 {date_str} .md")
    
    md_file = DOCS_DIR / f"JJC-{date_str}-001-原文.md"
    if md_file.exists():
        log(f"  ✅ 已有文件: {md_file}")
        return 0
    
    raw_file = Path(f"/tmp/finance_breakfast_raw_{date_str}.json")
    if not raw_file.exists():
        log(f"  ❌ 缺少原始数据: {raw_file}")
        log(f"  请先跑 --step fetch_only")
        return 1
    
    if dry_run:
        log("  [dry-run] 跳过")
        return 0
    
    # 实际生成 .md (从 raw JSON 渲染)
    # 这里需要调用一个 .md 生成函数 (agent 任务时实现)
    log(f"  ⚠️ 此 step 需要 agent 渲染 .md")
    log(f"  输出: {md_file}")
    return 2


def step_images(date_str, dry_run=False):
    """Step 3: 图片本化"""
    log(f"[images] 下载 {date_str} 图片到本地")
    
    images_dir = IMAGES_DIR / date_str
    if images_dir.exists() and any(images_dir.iterdir()):
        n = len(list(images_dir.iterdir()))
        log(f"  ✅ 已有 {n} 张图片: {images_dir}")
        return 0
    
    md_file = DOCS_DIR / f"JJC-{date_str}-001-原文.md"
    if not md_file.exists():
        log(f"  ❌ 缺少 .md: {md_file}")
        log(f"  请先跑 --step format_only")
        return 1
    
    if dry_run:
        log("  [dry-run] 跳过")
        return 0
    
    # 从 .md 里提取图片 URL, 下载到 images_dir
    images_dir.mkdir(parents=True, exist_ok=True)
    log(f"  ⚠️ 此 step 需要从 .md 提取图片 URL 并下载")
    log(f"  下载到: {images_dir}")
    return 2


def step_guard(date_str, dry_run=False):
    """Step 4: 合规审计"""
    log(f"[guard] 审计 {date_str}")
    
    md_file = DOCS_DIR / f"JJC-{date_str}-001-原文.md"
    images_dir = IMAGES_DIR / date_str
    
    issues = []
    if not md_file.exists():
        issues.append(f"missing .md: {md_file}")
    if not images_dir.exists():
        issues.append(f"missing images dir: {images_dir}")
    elif not any(images_dir.iterdir()):
        issues.append(f"empty images dir: {images_dir}")
    
    if md_file.exists():
        content = md_file.read_text()
        n_images = content.count("/images/" + date_str + "/")
        n_comments = content.count('class="cmt-item"')
        log(f"  图片引用: {n_images}")
        log(f"  评论数: {n_comments}")
        if n_images < 10:
            issues.append(f"too few images: {n_images}")
        if n_comments < 5:
            issues.append(f"too few comments: {n_comments}")
    
    if issues:
        log(f"  ❌ 审计失败:")
        for i in issues:
            log(f"     - {i}")
        return 1
    
    log(f"  ✅ 审计通过")
    return 0


def step_push(date_str, dry_run=False):
    """Step 5: 云端推送 (调用 system_git_pusher.py)"""
    log(f"[push] 推送 {date_str} 到 workspace-jobs main")
    
    if not PUSHER.exists():
        log(f"  ❌ 找不到穿墙推送工具: {PUSHER}")
        return 1
    
    if dry_run:
        log(f"  [dry-run] 会运行: python3 {PUSHER}")
        return 0
    
    log(f"  调用: python3 {PUSHER}")
    result = subprocess.run(
        ["python3", str(PUSHER)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    log(f"  pusher stdout: {result.stdout[-500:]}")
    if result.returncode != 0:
        log(f"  pusher stderr: {result.stderr[-500:]}")
    return result.returncode


# 步骤别名映射 (支持 --step fetch_only 等)
STEP_ALIAS = {
    "fetch_only":  ["fetch"],
    "format_only": ["format"],
    "images_only": ["images"],
    "guard_only":  ["guard"],
    "push_only":   ["push"],
    "all":         STEP_NAMES,
}


def parse_steps(step_arg):
    """解析 --step 参数, 返回要跑的 step 列表"""
    if not step_arg:
        return list(STEP_NAMES)
    
    parts = [s.strip() for s in step_arg.split(",")]
    result = []
    for p in parts:
        if p in STEP_ALIAS:
            result.extend(STEP_ALIAS[p])
        elif p in STEP_NAMES:
            result.append(p)
        else:
            log(f"❌ 未知 step: {p}")
            log(f"可用: {', '.join(STEP_NAMES)} 或 {', '.join(STEP_ALIAS.keys())}")
            sys.exit(1)
    
    # 去重保持顺序
    seen = set()
    unique = []
    for s in result:
        if s not in seen:
            seen.add(s)
            unique.append(s)
    return unique


def main():
    parser = argparse.ArgumentParser(
        description="财经早餐发布主流程 (支持单步可重入)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--step", 
        help=f"指定 step (可逗号分隔)。可用: {', '.join(STEP_NAMES + list(STEP_ALIAS.keys()))}",
    )
    parser.add_argument(
        "--date",
        help="指定日期 (YYYYMMDD 或 YYYY-MM-DD)，默认今天",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印不执行",
    )
    args = parser.parse_args()
    
    # 解析日期
    if args.date:
        d = args.date.replace("-", "")
        if len(d) != 8:
            log(f"❌ 日期格式错误: {args.date}")
            sys.exit(1)
        date_str = d
    else:
        date_str = shanghai_today_str()
    
    # 解析 steps
    steps = parse_steps(args.step)
    
    # 启动
    log("=" * 60)
    log(f"🚀 财经早餐发布主流程")
    log(f"  日期: {date_str} ({shanghai_today_hyphen()})")
    log(f"  步骤: {' -> '.join(steps)}")
    log(f"  dry-run: {args.dry_run}")
    log("=" * 60)
    
    # 执行
    step_funcs = {
        "fetch":  step_fetch,
        "format": step_format,
        "images": step_images,
        "guard":  step_guard,
        "push":   step_push,
    }
    
    for s in steps:
        log(f"--- 步骤: {s} ({STEP_DESC[s]}) ---")
        rc = step_funcs[s](date_str, dry_run=args.dry_run)
        if rc == 0:
            log(f"✅ {s} 成功")
        elif rc == 2:
            log(f"⏭️ {s} 跳过 (前置条件不满足或 dry-run)")
        else:
            log(f"❌ {s} 失败 (exit={rc})")
            log(f"   提示: 修复后可单独重跑: python3 tools/finance_breakfast.py --step {s}_only --date {date_str}")
            sys.exit(rc)
    
    log("=" * 60)
    log(f"🎉 全部步骤完成! 日期: {date_str}")
    log("=" * 60)


if __name__ == "__main__":
    main()
