#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dev_loop.py — frankofswing.com 网站功能开发的完整 loop (v3: 加 requirements alignment)

用法:
  python3 tools/dev_loop.py --feature "add reading time" --desc "..." --phase plan
    →  写 plan.md (TODO) + questions.md (10 个对齐问题带默认答案)
    →  STOP, 等 Frank review + 编辑 questions.md

  python3 tools/dev_loop.py --feature "add reading time" --phase finalize-plan
    →  读 questions.md (Frank review 完的), 写 plan.md (含 Frank 答案 + acceptance criteria)
    →  STOP, Frank 确认 plan.md OK 后再下一步

  python3 tools/dev_loop.py --feature "add reading time" --phase test
    →  装 vitest + npm scripts + vitest.config.ts
  python3 tools/dev_loop.py --feature "add reading time" --phase code
    →  (占位, 由 LLM 写代码)
  python3 tools/dev_loop.py --feature "add reading time" --phase verify
    →  astro check + npm run build + npm test
  python3 tools/dev_loop.py --feature "add reading time" --phase deploy
    →  push via Contents API + 存 deploy-state.json (rollback 用)
  python3 tools/dev_loop.py --feature "add reading time" --phase live-verify \\
      --paths "/,docs/..." --expect-text "..." --wait 90 [--auto-rollback]
    →  health check loop + feature 验证 + auto-rollback on fail

完整流程 (7 phase):
  Phase 0  PLAN         → 写 plan.md (TODO) + questions.md (Frank review)
  Phase 0b FINALIZE     → 读 questions.md, 写具体 plan.md
  Phase 1  TEST         → 装 vitest, 写 red 测试
  Phase 2  CODE         → 实现功能 (green)
  Phase 3  VERIFY       → astro check + build + test
  Phase 4  DEPLOY       → push (Contents API) + 存 deploy-state.json
  Phase 5  LIVE-VERIFY  → health check + feature 验证 + auto-rollback

rollback 机制:
  - deploy 前存 pre-deploy SHA 到 docs/dev/<feature>/deploy-state.json
  - live-verify 失败 + --auto-rollback: git reset --hard + force-push
  - 不带 --auto-rollback: 写 rollback.md + 飞书通知 Frank
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

PHASES = ["plan", "finalize-plan", "test", "code", "verify", "deploy", "live-verify"]


def log(msg: str, level: str = "INFO"):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", flush=True)


def log_phase(p: str):
    bar = "=" * 60
    log(f"{bar}\nPHASE {p.upper()}\n{bar}")


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def sh(cmd: list[str], cwd: Optional[str] = None, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True,
                          cwd=cwd or str(WORKSPACE), timeout=timeout)


def feature_dirs(name: str) -> Path:
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
    try:
        r = subprocess.run(["git", "rev-parse", ref], cwd=str(WORKSPACE),
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return None


def curl_with_text(url: str, expect_text: str = "", timeout: int = 15) -> tuple[bool, int, str]:
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
# {feature} — 需求对齐 (请 Frank review 后批准)

> 自动生成于 {timestamp} by dev_loop.py
> Frank review 后直接编辑默认答案 (改 "Frank 改:" 那行), 跑:
>   python3 tools/dev_loop.py --feature "{feature}" --phase finalize-plan

## 关键问题 (默认答案已填, 不对就改)

### 1. 触发场景 / User Story
- 默认: 用户访问 frankofswing.com 文章页时, 需要 X 功能
- Frank 改: ...

### 2. UI 显示位置 (UI feature 才需要)
- 默认: article-meta 区块 (跟 tag + date 排在一起)
- 备选: 文章 footer / sidebar / 标题上方
- Frank 改: ...

### 3. 数据来源 / 计算输入
- 默认: entry.body (markdown 原文) / entry.data.X (frontmatter 字段) / URL query
- 备选: ...
- Frank 改: ...

### 4. 业务规则 / 计算逻辑
- 默认: 300 wpm, CJK 1 word = 1 char, 至少 1 分钟, 向上取整
- 备选: 250 wpm, 中英文分开, ...
- Frank 改: ...

### 5. 文案 / 视觉规范
- 默认: "X 分钟阅读" (单行 + 时钟 icon, color = --color-text-muted)
- 备选: "阅读约 X 分钟" / "X min read" / 无 icon
- Frank 改: ...

### 6. 边界条件
- 空内容 → 至少显示 1 分钟
- readingTime < 1 → 隐藏 / 显示 1 兜底
- 超长内容 (>10000 字) → 上限 60 分钟 (防 "9999 分钟阅读")
- Frank 改: ...

### 7. Astro SSG / 构建时考虑 (关键!)
- output: 'static' → 必须 build 时算 (不能客户端 JS)
- 不能引入运行时依赖 (e.g., 第三方 API)
- 必须能被 vitest 纯函数测
- Frank 改: ...

### 8. 测试覆盖
- 单元测试 (vitest):
  - 至少 6 case: 空 / 短 / 长 / CJK / 英文 / 混合
  - 边界: readingTime = 1 / 超大
- 集成验证 (live-verify):
  - curl frankofswing.com 文章页
  - grep HTML 含 "X 分钟阅读"
- Frank 改: ...

### 9. 部署影响 / 回退策略
- 影响页面: 所有 /docs/* 文章 (174 页)
- Vercel build 多久生效: 30-90s
- 回退: 默认 --auto-rollback (live-verify 失败自动 git reset --hard + force-push)
- 备选: 手动 (飞书通知 + rollback.md)
- Frank 改: ...

### 10. SEO / 性能 / 可访问性
- SEO: 无影响 (静态文本)
- 性能: bundle size 影响? (新增组件 < 1KB OK)
- a11y: aria-label 含 "预估阅读时间 X 分钟" (屏幕阅读器友好)
- Frank 改: ...

## Frank review 状态

- [ ] 已 review 完所有问题 (默认答案接受或修改)
- [ ] 批准进 Phase 1 (test setup)
- [ ] 可以进 --phase finalize-plan 生成 plan.md

## Frank 备注 (可选)

(任何额外约束, 跨问题思考, 风险, 已知冲突, LLM 后续要问的问题等)
"""


def phase_0_plan(feature: str, feature_desc: str = "") -> bool:
    log_phase("0 PLAN — 需求对齐 questions.md 生成")
    DEV_DIR.mkdir(parents=True, exist_ok=True)
    feat_dir = feature_dirs(feature)
    feat_dir.mkdir(parents=True, exist_ok=True)

    # 写 plan.md (TODO 模板, finalize-plan 阶段会再写具体的)
    plan_path = feat_dir / "plan.md"
    desc = feature_desc or feature
    plan_content = f"""# {feature}

> 自动生成于 {time.strftime("%Y-%m-%d %H:%M:%S")} by dev_loop.py
> 等 --phase finalize-plan 才会写具体 plan (从 questions.md 答案生成)

## 需求描述
{desc}

## 实现方案 (TODO: 等 finalize-plan 填)

## 部署记录
| 时间 | commit | 部署状态 |
|---|---|---|
"""
    plan_path.write_text(plan_content, encoding="utf-8")
    log(f"✅ 写 plan.md (TODO 模板): {plan_path}")

    # 写 questions.md (核心: 10 个对齐问题)
    questions_path = feat_dir / "questions.md"
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    questions_path.write_text(
        PHASE_0_QUESTIONS_TEMPLATE.format(feature=feature, timestamp=timestamp),
        encoding="utf-8"
    )
    log(f"✅ 写 questions.md: {questions_path}")
    log("")
    log("📋 **请 Frank review questions.md:**")
    log("   1. 打开 questions.md, 直接编辑 'Frank 改:' 那些行 (把答案填进去)")
    log("   2. 也可以在底部 'Frank 备注' 加额外要求 / 风险 / LLM 后续要问的问题")
    log("   3. 改完跑: python3 tools/dev_loop.py --feature \"{feature}\" --phase finalize-plan")
    log("      → 这会读 questions.md 答案, 写具体的 plan.md")
    log("   4. plan.md 确认 OK 后跑 --phase test 装 vitest")
    log("")
    return True


# ── Phase 0b: FINALIZE-PLAN ─────────────────────────────────────────

def parse_questions_answers(questions_path: Path) -> dict[str, str]:
    """从 questions.md 提取每个问题的 Frank 改: 答案.

    简单解析: 每个 ### N. <question> 块下的 'Frank 改: ...' 行作为答案.
    """
    if not questions_path.exists():
        return {}

    text = questions_path.read_text(encoding="utf-8")
    answers = {}
    current_q = None

    for line in text.split("\n"):
        # 匹配问题标题: ### N. xxx
        m = re.match(r"^###\s+(\d+)\.\s+(.+)", line)
        if m:
            q_num = m.group(1)
            q_text = m.group(2).strip()
            current_q = (q_num, q_text)
            answers[f"q{q_num}"] = {"question": q_text, "answer": "(默认)"}
            continue

        # 匹配 Frank 改: ...
        if current_q and "Frank 改:" in line:
            answer = line.split("Frank 改:", 1)[1].strip()
            if answer and answer != "...":
                q_num = current_q[0]
                answers[f"q{q_num}"]["answer"] = answer

    return answers


def phase_0b_finalize_plan(feature: str) -> bool:
    log_phase("0b FINALIZE-PLAN — 从 questions.md 生成 plan.md")
    feat_dir = feature_dirs(feature)
    questions_path = feat_dir / "questions.md"
    plan_path = feat_dir / "plan.md"

    if not questions_path.exists():
        log(f"❌ questions.md 不存在, 先跑 --phase plan", "ERR")
        return False

    # 检查 Frank 是否 review 过 (有 [x] 已 review 标记)
    questions_text = questions_path.read_text(encoding="utf-8")
    reviewed = "- [x]" in questions_text or "- [X]" in questions_text
    if not reviewed:
        log("⚠️ questions.md 里没有 review checkbox 标记 (- [x])", "WARN")
        log("  Frank 应该 review 了才跑 finalize-plan")
        log("  如果确认 review 了, 在 questions.md 里把第一个 [ ] 改成 [x]")

    # 解析答案
    answers = parse_questions_answers(questions_path)
    log(f"  解析到 {len(answers)} 个问题答案:")
    for k, v in answers.items():
        preview = v["answer"][:60].replace("\n", " ")
        log(f"    {k}: {v['question'][:30]}... → {preview}{'...' if len(v['answer']) > 60 else ''}")

    # 生成具体的 plan.md
    plan_content = generate_plan_md(feature, answers)
    plan_path.write_text(plan_content, encoding="utf-8")
    log(f"✅ 写 plan.md: {plan_path}")
    log("")
    log("📋 **plan.md 已根据 Frank 答案生成, 请 review:**")
    log("   1. 打开 plan.md, 看 file 清单 / 验收标准 / 测试用例 / 风险 是否符合 Frank 预期")
    log("   2. 如果 OK → 跑 --phase test 装 vitest")
    log("   3. 如果要改 → 直接编辑 plan.md (不再走 finalize-plan)")
    log("")
    return True


def generate_plan_md(feature: str, answers: dict) -> str:
    """根据 questions.md 答案生成具体的 plan.md."""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    slug = slugify(feature)

    q1 = answers.get("q1", {}).get("answer", "(默认)")  # 触发场景
    q2 = answers.get("q2", {}).get("answer", "(默认)")  # UI 位置
    q3 = answers.get("q3", {}).get("answer", "(默认)")  # 数据来源
    q4 = answers.get("q4", {}).get("answer", "(默认)")  # 业务规则
    q5 = answers.get("q5", {}).get("answer", "(默认)")  # 文案视觉
    q6 = answers.get("q6", {}).get("answer", "(默认)")  # 边界
    q7 = answers.get("q7", {}).get("answer", "(默认)")  # SSG
    q8 = answers.get("q8", {}).get("answer", "(默认)")  # 测试
    q9 = answers.get("q9", {}).get("answer", "(默认)")  # 部署回退
    q10 = answers.get("q10", {}).get("answer", "(默认)")  # SEO/a11y

    return f"""# {feature}

> 自动生成于 {ts} by dev_loop.py (从 questions.md 答案生成)

## 需求描述 (从 Q1)
{q1}

## 实现方案

### UI 显示位置 (从 Q2)
{q2}

### 数据来源 / 输入 (从 Q3)
{q3}

### 业务规则 (从 Q4)
{q4}

### 文案 / 视觉 (从 Q5)
{q5}

### 边界条件 (从 Q6)
{q6}

### Astro SSG 约束 (从 Q7, 必须满足)
{q7}

## 文件清单 /

- `src/utils/<feature>.ts` — 工具函数 (可纯函数测, e.g., estimateReadingTime)
- `src/components/<Feature>.astro` — UI 组件 (如需要)
- `src/pages/<relevant>.astro` — 修改入口 (如需要)
- `tests/unit/<feature>.test.ts` — vitest 单测 (从 Q8 推)

## 验收标准 (从 Q1 + Q4 + Q5 + Q6 推)

- [ ] 功能按 Q1 场景正常工作
- [ ] UI 按 Q2 显示, Q5 文案 / 视觉一致
- [ ] 数据源按 Q3, 业务规则按 Q4, 边界按 Q6
- [ ] Astro SSG 约束满足 (Q7)
- [ ] SEO / a11y 满足 Q10

## 测试用例 (从 Q8 推)

- 单元测试 (vitest): tests/unit/<feature>.test.ts
- 集成验证 (live-verify): `python3 tools/dev_loop.py --feature "{feature}" --phase live-verify \\
    --paths "/,docs/<一个示例文章>" --expect-text "<Q5 文案关键字>"`

## 部署 / 回退 (从 Q9 推)

- 部署影响: 所有受影响页面 build 时重算, Vercel 30-90s 生效
- 回退: docs/dev/{slug}/rollback.md + deploy-state.json (含 pre_deploy_sha)
- 自动回滚: `python3 tools/dev_loop.py ... --auto-rollback` 失败时 git reset --hard + force-push

## 风险 / 注意事项 (跨问题思考)

- 边界条件 (Q6) 需要测试覆盖, 否则上线后被 edge case 搞挂
- Q5 文案如果有 emoji/icon 要确认跨字体兼容
- Astro SSG 约束 (Q7) 必须满足, 否则 build 失败 (参考 8/24 那个 frontmatter bug 教训)

## 部署记录

| 时间 | commit | 部署状态 |
|---|---|---|
"""


# ── Phase 1: TEST ───────────────────────────────────────────────────

def phase_1_test(feature: str) -> bool:
    log_phase("1 TEST — 装 vitest + 写测试")
    plan_path = feature_dirs(feature) / "plan.md"
    if not plan_path.exists():
        log(f"❌ plan.md 不存在, 先跑 --phase plan 和 --phase finalize-plan", "ERR")
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
    return True


# ── Phase 2: CODE ───────────────────────────────────────────────────

def phase_2_code(feature: str) -> bool:
    log_phase("2 CODE — 实现功能")
    log("  Phase 2 是手动/模型根据 plan.md 写代码")
    log("  写完跑 --phase verify (astro check + build + test)")
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


# ── Phase 5: LIVE-VERIFY ────────────────────────────────────────────

def phase_5_live_verify(feature: str, paths_to_check: list[str], wait_seconds: int = 60,
                       expect_text: str = "", auto_rollback: bool = False) -> bool:
    log_phase("5 LIVE-VERIFY — health check + feature 验证 (Vercel)")
    log(f"  paths: {paths_to_check}")
    log(f"  expect_text: '{ expect_text or '(空, 只看 HTTP 200)'}'")
    log(f"  auto_rollback: {auto_rollback}")
    log(f"  等 Vercel build {wait_seconds}s ...")

    state_path = feature_dirs(feature) / "deploy-state.json"
    pre_deploy_sha = "unknown"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
            pre_deploy_sha = state.get("pre_deploy_sha", "unknown")
            log(f"  pre_deploy SHA (从 deploy-state.json): {pre_deploy_sha[:12]}")
        except Exception:
            pass

    poll_interval = 15
    deadline = time.time() + wait_seconds
    attempt = 0
    all_paths_ok = False

    while time.time() < deadline:
        attempt += 1
        log(f"  [health check] attempt #{attempt} ({(deadline - time.time()):.0f}s 剩余)")
        all_paths_ok_this_round = True

        for p in paths_to_check:
            path = p if p.startswith("/") else f"/{p}"
            encoded_path = urllib.parse.quote(path, safe="/")
            url = f"{SITE.rstrip('/')}{encoded_path}"
            ok, status, body = curl_with_text(url, expect_text=expect_text)
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
    feat_dir = feature_dirs(feature)
    feat_dir.mkdir(parents=True, exist_ok=True)
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

# 1. 确认本地没有未提交改动
git status

# 2. 回到 deploy 前的 commit
git reset --hard {pre_sha}

# 3. 强推到 origin
git push --force-with-lease origin main

# 4. 验证 Vercel 重新 build
sleep 60
curl -sS "https://frankofswing.com/" -L | head -20
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
    try:
        if pre_sha == "unknown":
            log("  ⚠️ pre_sha 未知, 无法自动 rollback", "WARN")
            return False
        r = sh(["git", "reset", "--hard", pre_sha], timeout=30)
        if r.returncode != 0:
            log(f"  ❌ git reset 失败: {r.stderr[:300]}", "ERR")
            return False
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
    elif phase == "finalize-plan":
        return phase_0b_finalize_plan(args.feature)
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
                   help=f"all / plan / finalize-plan / test / code / verify / deploy / live-verify")
    p.add_argument("--files", default="", help="deploy phase: 要 push 的文件列表 (逗号分隔)")
    p.add_argument("--commit-msg", default="feat: dev loop auto deploy", help="deploy phase: commit message")
    p.add_argument("--paths", default="", help="live-verify phase: 要 curl 的 URL 路径 (逗号分隔)")
    p.add_argument("--wait", type=int, default=60, help="live-verify phase: 等 Vercel build 秒数")
    p.add_argument("--expect-text", default="", help="live-verify phase: HTML 必须包含的文本 (例 '分钟阅读')")
    p.add_argument("--auto-rollback", action="store_true", help="live-verify 失败时自动 git reset --hard + force-push")
    args = p.parse_args()

    log("=" * 60)
    log(f"dev_loop.py v3 — feature={args.feature}")
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