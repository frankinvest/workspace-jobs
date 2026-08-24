#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dev_loop.py — frankofswing.com 网站功能开发的完整 loop (v2: 加 rollback + health check)

用法:
  python3 tools/dev_loop.py --feature "add reading time estimate"           # 全流程
  python3 tools/dev_loop.py --feature "add reading time" --phase plan     # 只生成 plan
  python3 tools/dev_loop.py --feature "add reading time" --phase test     # 只跑测试
  python3 tools/dev_loop.py --feature "add reading time" --phase code     # 只写代码
  python3 tools/dev_loop.py --feature "add reading time" --phase verify   # 只验证
  python3 tools/dev_loop.py --feature "add reading time" --phase deploy   # 只部署
  python3 tools/dev_loop.py --feature "add reading time" --phase live-verify  # curl 上线验证

  # Health check 模式 (verify feature 真的上线了):
  python3 tools/dev_loop.py --feature "add reading time" --phase live-verify \
      --paths "/,docs/jjc-20260824-001-原文/" --expect-text "分钟阅读" --wait 90

  # Auto rollback (live-verify 失败自动回滚):
  python3 tools/dev_loop.py --feature "..." --phase live-verify --auto-rollback

流程 (6 phase):
  Phase 0  PLAN         需求分析 → docs/dev/<feature>/plan.md + questions.md
  Phase 1  TEST         装 vitest + 写单测 (red) → npm test 跑应失败
  Phase 2  CODE         实现功能 (green) → 让测试通过
  Phase 3  VERIFY       astro check + npm run build + npm test 全部通过
  Phase 4  DEPLOY       git add + commit + push (Contents API 绕开 git push 撞墙) + 存 deploy-state.json
  Phase 5  LIVE-VERIFY  health check + feature 验证 (HTML grep) + auto-rollback on fail

rollback 机制:
  - deploy 前存 pre-deploy SHA + files 列表到 docs/dev/<feature>/deploy-state.json
  - live-verify 失败 + --auto-rollback: git reset --hard <pre_sha> + force-push 回滚
  - 不带 --auto-rollback: 写 docs/dev/<feature>/rollback.md 含具体命令, 飞书通知 Frank 手动处理
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
DEV_DIR = DOCS_DIR / "dev"
SITE = "https://frankofswing.com"
FEISHU_TARGET = "user:ou_8fab5d81798938a771ad4be7bb04593c"

PHASES = ["plan", "test", "code", "verify", "deploy", "live-verify"]


def log(msg: str, level: str = "INFO"):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", flush=True)


def log_phase(p: str):
    bar = "=" * 60
    log(f"{bar}\nPHASE {p.upper()}\n{bar}")


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def sh(cmd: list[str], cwd: Optional[str] = None, timeout: int = 600) -> subprocess.CompletedProcess:
    """Run shell command, return result"""
    return subprocess.run(cmd, capture_output=True, text=True,
                          cwd=cwd or str(WORKSPACE), timeout=timeout)


def feature_dirs(name: str) -> Path:
    """Generate feature directory path"""
    return DEV_DIR / slugify(name)


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
        return r.returncode == 0
    except Exception as e:
        log(f"feishu 失败: {e}", "WARN")
        return False


def get_remote_sha(ref: str = "origin/main") -> Optional[str]:
    """Get SHA of a git ref via local fetch first, then rev-parse"""
    try:
        r = subprocess.run(["git", "rev-parse", ref], cwd=str(WORKSPACE),
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return None


def curl_with_text(url: str, expect_text: str = "", timeout: int = 15) -> tuple[bool, int, str]:
    """GET URL, return (ok, status, body_preview). ok = status 200 + expect_text in body (if given)."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Jobs-DevLoop)",
            "Cache-Control": "no-cache",
        })
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", errors="ignore")
            status = r.status
    except urllib.error.HTTPError as e:
        return False, e.code, ""
    except Exception as e:
        return False, 0, f"{type(e).__name__}: {e}"
    if status != 200:
        return False, status, body[:300]
    if expect_text and expect_text not in body:
        return False, status, body[:300]
    return True, status, body[:300]


# ── Phase 0: PLAN ───────────────────────────────────────────────────

PHASE_0_QUESTIONS_TEMPLATE = """\
# {feature} — 需求对齐 (请 Frank review/edit 后批准)

## 关键问题 (默认回答已填, 不对就改)

### 1. 显示位置
- 默认: article-meta 区块 (跟 tag + date 排在一起)
- 备选: 文章 footer / sidebar / 标题下

### 2. 计算方式
- 默认: estimateReadingTime() 工具函数, 300 wpm (中英文混合按 1 word / 1 char)
- 备选: 固定 5 分钟 / 服务端计算 / 第三方 API

### 3. 文案
- 默认: "X 分钟阅读"
- 备选: "阅读约 X 分钟" / "X min read" / 加图标

### 4. 边界
- 空文章: 至少显示 "1 分钟阅读"
- 超长文章 (>10000 字): 上限? 默认无上限
- 隐藏条件: readingTime < 1 时不显示?

### 5. Astro SSG 考虑
- 因为 output: 'static', reading time 必须 build 时算 (不能客户端 JS)
- 新增工具函数必须能被 server-side 跑 (vitest 测得到)

### 6. 测试覆盖
- 单元测试: 至少 6 个 case (空/短/长/CJK/英文/混合)
- 集成验证: curl frankofswing.com 文章页, HTML 含 "X 分钟阅读" 文字

### 7. 回退策略
- 如果 Vercel build 失败 → 自动飞书通知 Frank
- 如果 live-verify 失败 → --auto-rollback 自动回滚 (否则写 rollback.md)
- Frank 手动回滚命令: `git reset --hard <pre_deploy_sha> && git push --force-with-lease origin main`

### 8. 部署影响
- 影响页面: 所有 /docs/* 文章 (174 个页面)
- 部署后等多久生效: Vercel 通常 30-90s
- 影响 SEO: 无 (前端静态文本)

## 审批

- [ ] Frank review 完成
- [ ] 所有问题答完 (或确认默认)
- [ ] 可以进 Phase 1 (test setup)
"""


def phase_0_plan(feature: str, feature_desc: str = "") -> bool:
    log_phase("0 PLAN — 需求分析 + 对齐")
    DEV_DIR.mkdir(parents=True, exist_ok=True)
    feat_dir = feature_dirs(feature)
    feat_dir.mkdir(parents=True, exist_ok=True)

    # 写 plan.md (TODO 模板)
    plan_path = feat_dir / "plan.md"
    desc = feature_desc or feature
    plan_content = f"""# {feature}

> 自动生成于 {time.strftime("%Y-%m-%d %H:%M:%S")} by dev_loop.py

## 需求描述
{desc}

## 实现方案 (人工 / 模型填)

### 修改/新增文件清单
- (TODO)

### 验收标准
- [ ] (TODO)

### 测试用例 (vitest)
- (TODO)

### 风险/注意事项
- (TODO)

## 部署记录
| 时间 | commit | 部署状态 |
|---|---|---|
"""
    plan_path.write_text(plan_content, encoding="utf-8")
    log(f"✅ 写 plan.md: {plan_path}")

    # 写 questions.md (需求对齐 checklist)
    questions_path = feat_dir / "questions.md"
    questions_path.write_text(PHASE_0_QUESTIONS_TEMPLATE.format(feature=feature), encoding="utf-8")
    log(f"✅ 写 questions.md: {questions_path} (Frank review 这份对齐需求)")
    log("  → Frank 看完 questions.md 后:")
    log("     - 全 OK → 进 --phase test 装 vitest")
    log("     - 有问题 → 直接改 questions.md, 然后再 --phase test")
    return True


# ── Phase 1: TEST ───────────────────────────────────────────────────

def phase_1_test(feature: str) -> bool:
    log_phase("1 TEST — 装 vitest + 写测试")
    plan_path = feature_dirs(feature) / "plan.md"
    if not plan_path.exists():
        log(f"❌ plan.md 不存在, 先跑 --phase plan", "ERR")
        return False

    pkg = json.loads((WORKSPACE / "package.json").read_text())
    dev_deps = pkg.get("devDependencies", {})
    if "vitest" not in dev_deps:
        log("  vitest 未装, npm install --save-dev vitest...")
        r = sh(["npm", "install", "--save-dev", "vitest", "@vitest/ui"], timeout=300)
        if r.returncode != 0:
            log(f"  ❌ npm install 失败: {r.stderr[:500]}", "ERR")
            return False
        log("  ✅ vitest 已装")
    else:
        log(f"  vitest 已装 (v{dev_deps.get('vitest', '?')})")

    vitest_cfg = WORKSPACE / "vitest.config.ts"
    if not vitest_cfg.exists():
        vitest_cfg.write_text("""import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['tests/unit/**/*.test.ts'],
    environment: 'node',
  },
});
""", encoding="utf-8")
        log("  ✅ 写 vitest.config.ts")

    tests_dir = WORKSPACE / "tests" / "unit"
    tests_dir.mkdir(parents=True, exist_ok=True)

    scripts = pkg.setdefault("scripts", {})
    for k, v in {"test": "vitest run", "test:watch": "vitest", "check": "astro check"}.items():
        if k not in scripts:
            scripts[k] = v
    pkg["scripts"] = scripts
    (WORKSPACE / "package.json").write_text(json.dumps(pkg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log("  ✅ npm scripts: test / test:watch / check 已加")

    log("✅ Phase 1 完成: vitest + tests/unit/ + scripts 全部就绪")
    log(f"  → 接下来在 tests/unit/*.test.ts 写测试 (参考 plan.md)")
    return True


# ── Phase 2: CODE ───────────────────────────────────────────────────

def phase_2_code(feature: str) -> bool:
    log_phase("2 CODE — 实现功能")
    log("  Phase 2 是手动/模型根据 plan.md 写代码")
    log(f"  写完跑 --phase verify (astro check + build + test)")
    return True


# ── Phase 3: VERIFY ─────────────────────────────────────────────────

def phase_3_verify(feature: str) -> bool:
    log_phase("3 VERIFY — astro check + build + test")
    results = {}

    log("  跑 astro check (TS strict)...")
    r = sh(["npm", "run", "check"], timeout=180)
    if r.returncode == 0:
        log("  ✅ astro check 通过")
        results["check"] = "PASS"
    else:
        log(f"  ❌ astro check 失败", "ERR")
        for line in (r.stdout + r.stderr).split("\n"):
            if "Error" in line or "error" in line.lower():
                log(f"     {line.strip()[:200]}")
        results["check"] = "FAIL"

    log("  跑 npm run build...")
    r = sh(["npm", "run", "build"], timeout=300)
    if r.returncode == 0:
        m = re.search(r"(\d+)\s+page\(s\)\s+built", r.stdout)
        pages = m.group(1) if m else "?"
        log(f"  ✅ build 通过 ({pages} 页)")
        results["build"] = f"PASS ({pages} 页)"
    else:
        log(f"  ❌ build 失败", "ERR")
        results["build"] = "FAIL"

    log("  跑 npm test (vitest)...")
    r = sh(["npm", "test"], timeout=180)
    if r.returncode == 0:
        m = re.search(r"Tests\s+(\d+)\s+passed", r.stdout)
        passed = m.group(1) if m else "?"
        log(f"  ✅ test 通过 ({passed} passed)")
        results["test"] = f"PASS ({passed} passed)"
    else:
        log(f"  ❌ test 失败", "ERR")
        results["test"] = "FAIL"

    all_pass = all(v.startswith("PASS") for v in results.values())
    if not all_pass:
        log(f"❌ verify 没全过: {results}", "ERR")
        return False
    log("✅ Phase 3 完成: 全部 verify 通过")
    return True


# ── Phase 4: DEPLOY ─────────────────────────────────────────────────

def phase_4_deploy(feature: str, files: list[str], commit_msg: str, auto_rollback: bool = False) -> bool:
    log_phase("4 DEPLOY — git push → Vercel (含 deploy-state.json)")
    if not files:
        log("❌ 必须传 --files", "ERR")
        return False

    r = sh(["git", "status", "-s"])
    log(f"  working tree:\n{r.stdout}")

    log("  fetch + rebase origin/main")
    sh(["git", "fetch", "origin", "main"], timeout=30)
    sh(["git", "pull", "--rebase", "origin", "main"], timeout=30)

    # ── 保存 deploy 前状态 (rollback 用) ──
    feat_dir = feature_dirs(feature)
    feat_dir.mkdir(parents=True, exist_ok=True)
    state_path = feat_dir / "deploy-state.json"

    pre_sha = get_remote_sha("HEAD") or get_remote_sha("origin/main") or "unknown"
    log(f"  pre-deploy HEAD: {pre_sha[:12]}")

    log("  push via Contents API...")
    file_commits = []
    for f in files:
        r = subprocess.run(
            ["python3", str(TOOLS_DIR / "system_api_pusher.py"),
             "--file", f, "--commit-msg", commit_msg],
            cwd=str(WORKSPACE), capture_output=True, text=True, timeout=120
        )
        if r.returncode != 0:
            log(f"  ❌ push {f} 失败: {r.stderr[:300]}", "ERR")
            return False
        m = re.search(r"commit ([a-f0-9]+)", r.stdout)
        sha = m.group(1) if m else "?"
        file_commits.append({"file": f, "sha": sha})
        log(f"  ✅ {f} → {sha[:8]}")

    post_sha = get_remote_sha("origin/main") or "unknown"
    log(f"  post-deploy origin/main: {post_sha[:12]}")

    state = {
        "feature": feature,
        "files": files,
        "files_commits": file_commits,
        "pre_deploy_sha": pre_sha,
        "post_deploy_sha": post_sha,
        "commit_msg": commit_msg,
        "auto_rollback": auto_rollback,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"  ✅ deploy state: {state_path}")
    log("✅ Phase 4 完成")
    log(f"   回滚命令: git reset --hard {pre_sha[:8]} && git push --force-with-lease origin main")
    return True


# ── Phase 5: LIVE-VERIFY (升级版: health check + feature 验证 + rollback) ───

def phase_5_live_verify(feature: str, paths_to_check: list[str], wait_seconds: int = 60,
                       expect_text: str = "", auto_rollback: bool = False) -> bool:
    log_phase("5 LIVE-VERIFY — health check + feature 验证 (Vercel)")
    log(f"  paths: {paths_to_check}")
    log(f"  expect_text: '{expect_text or '(空, 只看 HTTP 200)'}'")
    log(f"  auto_rollback: {auto_rollback}")
    log(f"  等 Vercel build {wait_seconds}s ...")

    # 读 deploy state (知道 pre-deploy SHA, 用于 rollback)
    state_path = feature_dirs(feature) / "deploy-state.json"
    pre_deploy_sha = "unknown"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
            pre_deploy_sha = state.get("pre_deploy_sha", "unknown")
            log(f"  pre_deploy SHA (从 deploy-state.json): {pre_deploy_sha[:12]}")
        except Exception:
            pass

    # Health check loop: 每 15s 轮询一次, 直到 wait_seconds 用完
    poll_interval = 15
    deadline = time.time() + wait_seconds
    attempt = 0
    all_paths_ok = False

    while time.time() < deadline:
        attempt += 1
        log(f"  [health check] attempt #{attempt} ({(deadline - time.time()):.0f}s 剩余)")
        path_results = []
        all_paths_ok_this_round = True

        for p in paths_to_check:
            path = p if p.startswith("/") else f"/{p}"
            encoded_path = urllib.parse.quote(path, safe="/")
            url = f"{SITE.rstrip('/')}{encoded_path}"
            ok, status, body = curl_with_text(url, expect_text=expect_text)
            path_results.append({"url": url, "ok": ok, "status": status, "preview": body[:150]})
            mark = "✅" if ok else "❌"
            log(f"    {mark} {url} → HTTP {status}"
                + (f", expect_text NOT FOUND" if (status == 200 and not ok and expect_text) else ""))
            if not ok:
                all_paths_ok_this_round = False

        if all_paths_ok_this_round:
            all_paths_ok = True
            log(f"  ✅ 所有路径通过 ({len(paths_to_check)} 个) in attempt #{attempt}")
            break
        time.sleep(poll_interval)

    if not all_paths_ok:
        log(f"❌ Phase 5 失败: health check 超时 ({wait_seconds}s) 或 feature 未渲染")
        # 写 rollback.md 给 Frank (无论 auto_rollback 是否启用)
        write_rollback_md(feature, pre_deploy_sha, paths_to_check, expect_text)
        if auto_rollback:
            log("  --auto-rollback 启用, 执行 git reset --hard + force-push")
            ok = do_rollback(pre_deploy_sha)
            if ok:
                log("  ✅ rollback 完成, 飞书通知 Frank")
                feishu_notify(f"🔴 {feature} 部署失败已 rollback",
                              f"feature '{feature}' 部署后 live-verify 失败\n"
                              f"已自动 rollback 到 pre-deploy SHA: {pre_deploy_sha[:8]}\n\n"
                              f"rollback.md: {feature_dirs(feature) / 'rollback.md'}\n"
                              f"Vercel 会自动 rebuild, 约 30-90s 生效")
            else:
                log("  ❌ rollback 失败, 飞书通知 Frank 手动处理", "ERR")
                feishu_notify(f"🔴 {feature} 部署失败 + rollback 也失败",
                              f"feature '{feature}' 部署后 live-verify 失败, rollback 也失败!\n\n"
                              f"请 Frank 手动处理:\n"
                              f"  cd {WORKSPACE}\n"
                              f"  git reset --hard {pre_deploy_sha}\n"
                              f"  git push --force-with-lease origin main")
        else:
            log("  未启用 --auto-rollback, 写 rollback.md 飞书通知 Frank")
            feishu_notify(f"🔴 {feature} 部署失败",
                          f"feature '{feature}' 部署后 live-verify 失败 ({wait_seconds}s 超时)\n\n"
                          f"回滚命令 (Frank 手动执行):\n"
                          f"  cd {WORKSPACE}\n"
                          f"  git reset --hard {pre_deploy_sha}\n"
                          f"  git push --force-with-lease origin main\n\n"
                          f"rollback.md: {feature_dirs(feature) / 'rollback.md'}\n\n"
                          f"或重跑: python3 tools/dev_loop.py --feature \"{feature}\" --phase live-verify --auto-rollback")
        return False

    log("✅ Phase 5 完成: health check + feature 验证全部通过")
    return True


def write_rollback_md(feature: str, pre_sha: str, paths: list[str], expect_text: str) -> Path:
    """写 rollback.md 给 Frank (手动或 auto-rollback 用)"""
    feat_dir = feature_dirs(feature)
    feat_dir.mkdir(parents=True, exist_ok=True)  # 确保 docs/dev/<feature>/ 存在
    md_path = feat_dir / "rollback.md"
    content = f"""# Rollback Plan — {feature}

> 自动生成于 {time.strftime("%Y-%m-%d %H:%M:%S")} by dev_loop.py (live-verify failed)

## 失败信息
- paths: {paths}
- expect_text: '{expect_text}'
- pre_deploy SHA: `{pre_sha}`

## 回滚步骤 (手动执行)

```bash
cd {WORKSPACE}

# 1. 确认本地没有未提交改动 (回滚会丢失它们)
git status

# 2. 回到 deploy 前的 commit
git reset --hard {pre_sha}

# 3. 强推到 origin (会覆盖 origin/main)
git push --force-with-lease origin main

# 4. 验证 Vercel 重新 build 后页面正常
sleep 60
curl -sS "https://frankofswing.com/docs/jjc-{pre_sha[:8]}-001-原文/" -L | head -50
```

## 或者用 Contents API (推荐, 更安全)

```bash
# 对每个改动文件, 从 pre_deploy_sha 取内容, 重新 push
for f in {"src/utils/..." "src/components/..."}; do
  python3 tools/system_api_pusher.py \\
    --file "$f" \\
    --commit-msg "revert: {feature} (live-verify failed)"
done
```

## 调试步骤

1. 跑 `python3 tools/dev_loop.py --feature "{feature}" --phase live-verify --wait 90` 看具体哪个 path 失败
2. 看 deploy-state.json 里每个 file 的 commit SHA
3. 本地跑 `npm run build` 看具体 build 错
4. 看 Vercel dashboard: https://vercel.com/muhuaxiawen-1094s-projects/workspace-jobs/deployments
"""
    md_path.write_text(content, encoding="utf-8")
    log(f"  ✅ rollback.md: {md_path}")
    return md_path


def do_rollback(pre_sha: str) -> bool:
    """git reset --hard + force-push 回滚"""
    try:
        if pre_sha == "unknown":
            log("  ⚠️ pre_sha 未知, 无法自动 rollback", "WARN")
            return False
        # 先 reset
        r = sh(["git", "reset", "--hard", pre_sha], timeout=30)
        if r.returncode != 0:
            log(f"  ❌ git reset 失败: {r.stderr[:300]}", "ERR")
            return False
        # 再 force-push
        r = sh(["git", "push", "--force-with-lease", "origin", "main"], timeout=60)
        if r.returncode != 0:
            log(f"  ❌ git push 失败: {r.stderr[:300]}", "ERR")
            return False
        log(f"  ✅ rollback 成功 (reset --hard {pre_sha[:8]} + force-push)")
        return True
    except Exception as e:
        log(f"  ❌ rollback 异常: {type(e).__name__}: {e}", "ERR")
        return False


# ── 主流程 ─────────────────────────────────────────────────────────

def run_phase(phase: str, args) -> bool:
    if phase == "plan":
        return phase_0_plan(args.feature, args.desc)
    elif phase == "test":
        return phase_1_test(args.feature)
    elif phase == "code":
        return phase_2_code(args.feature)
    elif phase == "verify":
        return phase_3_verify(args.feature)
    elif phase == "deploy":
        files = args.files.split(",") if args.files else []
        return phase_4_deploy(args.feature, files, args.commit_msg, args.auto_rollback)
    elif phase == "live-verify":
        paths = args.paths.split(",") if args.paths else ["/"]
        return phase_5_live_verify(args.feature, paths, args.wait, args.expect_text, args.auto_rollback)
    else:
        log(f"未知 phase: {phase}", "ERR")
        return False


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--feature", required=True, help="feature 名 (用作 slug 和目录)")
    p.add_argument("--desc", default="", help="feature 详细描述")
    p.add_argument("--phase", default="all",
                   help=f"all / plan / test / code / verify / deploy / live-verify")
    p.add_argument("--files", default="", help="deploy phase: 要 push 的文件列表 (逗号分隔)")
    p.add_argument("--commit-msg", default="feat: dev loop auto deploy", help="deploy phase: commit message")
    p.add_argument("--paths", default="", help="live-verify phase: 要 curl 的 URL 路径 (逗号分隔)")
    p.add_argument("--wait", type=int, default=60, help="live-verify phase: 等 Vercel build 秒数")
    p.add_argument("--expect-text", default="", help="live-verify phase: HTML 必须包含的文本 (例 '分钟阅读'). 空=只看 HTTP 200")
    p.add_argument("--auto-rollback", action="store_true", help="live-verify 失败时自动 git reset --hard + force-push 回滚")
    args = p.parse_args()

    log("=" * 60)
    log(f"dev_loop.py v2 — feature={args.feature}")
    log(f"phases={args.phase}")
    log("=" * 60)

    phases = PHASES if args.phase == "all" else [args.phase]
    all_ok = True
    summary = []
    for ph in phases:
        ok = run_phase(ph, args)
        summary.append(f"  Phase {ph}: {'✅' if ok else '❌'}")
        if not ok:
            all_ok = False
            break

    log("\n" + "=" * 60)
    log("SUMMARY:")
    for s in summary:
        log(s)
    log("=" * 60)

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()