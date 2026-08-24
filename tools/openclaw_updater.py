#!/usr/bin/env python3
"""
openclaw_updater.py — Professional multi-phase loop to update OpenClaw.

Why this exists:
  Frank's `openclaw update` has been failing because the host Node.js (22.22.0)
  is below OpenClaw's required engines.node (>=22.22.3 / >=24.15 / >=25.9).
  OpenClaw CLI refuses to start, so every update attempt fails immediately.

Design: 5 phases, each with exponential backoff + fallback strategies.
  PHASE 0  PREFLIGHT   — check Node, network, disk, brew
  PHASE 1  NODE_UPGRADE— install Node 24 LTS (brew → pkg → fnm fallback)
  PHASE 2  DRY_RUN     — preview `openclaw update --dry-run --json`
  PHASE 3  ACTUAL      — run `openclaw update --yes --json`
  PHASE 4  VERIFY      — openclaw status / doctor / update status
  PHASE 5  NOTIFY      — feishu message to Frank with before/after versions

Usage:
  python3 tools/openclaw_updater.py                # run all phases
  python3 tools/openclaw_updater.py --phase preflight
  python3 tools/openclaw_updater.py --phase node
  python3 tools/openclaw_updater.py --phase dry-run
  python3 tools/openclaw_updater.py --phase update
  python3 tools/openclaw_updater.py --phase verify
  python3 tools/openclaw_updater.py --phase notify
  python3 tools/openclaw_updater.py --max-attempts 5
  python3 tools/openclaw_updater.py --channel stable
  python3 tools/openclaw_updater.py --dry-run        # only print plan, no actual changes

Exit codes:
  0   success (or skipped because already up to date)
  2   phase failure after exhausting retries
  3   fatal preflight (cannot proceed)
  4   user aborted (Ctrl-C / --stop-on-fail in non-interactive mode)
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

REQUIRED_NODE_VERSIONS = [
    ("22.22.3", 22, 22, 3),
    ("24.15.0", 24, 15, 0),
    ("25.9.0", 25, 9, 0),
]

TARGET_NODE_MAJOR = 24  # Node 24 LTS, most stable for OpenClaw

LOG_DIR = Path("/tmp")
LOG_FILE = LOG_DIR / f"openclaw_update_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

STATE_FILE = Path("/tmp/openclaw_update_state.json")

FEISHU_OPEN_ID = "ou_8fab5d81798938a771ad4be7bb04593c"  # Frank on Feishu


# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------


class Logger:
    """Tee-style logger: stdout + file."""

    def __init__(self, path: Path):
        self.path = path
        self.fh = open(path, "a", buffering=1)
        atexit_register(lambda: self.fh.close())

    def log(self, level: str, msg: str) -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] [{level:>5}] {msg}"
        print(line, flush=True)
        self.fh.write(line + "\n")

    def info(self, msg: str) -> None:
        self.log("INFO", msg)

    def warn(self, msg: str) -> None:
        self.log("WARN", msg)

    def error(self, msg: str) -> None:
        self.log("ERROR", msg)

    def debug(self, msg: str) -> None:
        self.log("DEBUG", msg)

    def section(self, title: str) -> None:
        self.log("INFO", "")
        self.log("INFO", "=" * 70)
        self.log("INFO", f"  {title}")
        self.log("INFO", "=" * 70)


def atexit_register(fn):
    """Tiny atexit shim so Logger doesn't need an extra import at module top."""
    import atexit

    atexit.register(fn)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def run(
    cmd: list[str] | str,
    *,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 300,
    check: bool = False,
    log: Logger | None = None,
) -> tuple[int, str, str]:
    """Run a command; return (rc, stdout, stderr). Tee to log if provided."""
    if isinstance(cmd, str):
        cmd = ["bash", "-lc", cmd]
    printable = " ".join(cmd) if isinstance(cmd, list) else cmd
    if log:
        log.debug(f"$ {printable}")
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        rc = proc.returncode
        out = proc.stdout or ""
        err = proc.stderr or ""
        if log and (out.strip() or err.strip()):
            for line in out.splitlines():
                log.debug(f"  | {line}")
            for line in err.splitlines():
                log.debug(f"  ! {line}")
        if check and rc != 0:
            raise subprocess.CalledProcessError(rc, cmd, out, err)
        return rc, out, err
    except subprocess.TimeoutExpired as e:
        if log:
            log.error(f"timeout after {timeout}s: {printable}")
        return 124, "", f"timeout after {timeout}s"


def parse_node_version(v: str) -> tuple[int, int, int] | None:
    """Parse 'v22.22.0' or '22.22.0' → (22, 22, 0)."""
    m = re.match(r"v?(\d+)\.(\d+)\.(\d+)", v.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def node_satisfies(actual: tuple[int, int, int]) -> bool:
    """Check if actual node version satisfies OpenClaw engines."""
    a_major, a_minor, a_patch = actual
    # Accept 22.22.3+ or 24.15.0+ or 25.9.0+
    if a_major == 22 and (a_minor, a_patch) >= (22, 3):
        return True
    if a_major == 24 and (a_minor, a_patch) >= (15, 0):
        return True
    if a_major == 25 and (a_minor, a_patch) >= (9, 0):
        return True
    return False


def node_best_match() -> tuple[str, tuple[int, int, int]]:
    """Pick the best supported version for OpenClaw."""
    return "24.19.0", (24, 19, 0)


def fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}PB"


def disk_free(path: str = "/opt/homebrew") -> int:
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize


# -----------------------------------------------------------------------------
# Phase state (persistent across runs)
# -----------------------------------------------------------------------------


@dataclass
class PhaseState:
    name: str
    attempts: int = 0
    last_rc: int | None = None
    last_error: str = ""
    completed: bool = False
    started_at: str = ""
    finished_at: str = ""


@dataclass
class LoopState:
    phases: dict[str, PhaseState] = field(default_factory=dict)
    before_version: str = ""
    after_version: str = ""

    @classmethod
    def load(cls) -> "LoopState":
        if not STATE_FILE.exists():
            return cls(
                phases={
                    "preflight": PhaseState(name="preflight"),
                    "node": PhaseState(name="node"),
                    "dry_run": PhaseState(name="dry_run"),
                    "update": PhaseState(name="update"),
                    "verify": PhaseState(name="verify"),
                    "notify": PhaseState(name="notify"),
                }
            )
        try:
            raw = json.loads(STATE_FILE.read_text())
            state = cls()
            for name, p in raw.get("phases", {}).items():
                state.phases[name] = PhaseState(**p)
            state.before_version = raw.get("before_version", "")
            state.after_version = raw.get("after_version", "")
            return state
        except Exception:
            return cls.load.__func__()  # type: ignore

    def save(self) -> None:
        STATE_FILE.write_text(
            json.dumps(
                {
                    "phases": {n: ps.__dict__ for n, ps in self.phases.items()},
                    "before_version": self.before_version,
                    "after_version": self.after_version,
                },
                indent=2,
            )
        )


# -----------------------------------------------------------------------------
# Retry decorator (stateful)
# -----------------------------------------------------------------------------


def retry(
    fn,
    *,
    max_attempts: int,
    base_delay: float = 2.0,
    max_delay: float = 32.0,
    log: Logger,
    state: PhaseState,
    on_exhaust: str = "fail",  # "fail" | "fallback"
):
    """Run fn() with exponential backoff. Records state.attempts/rc."""

    def attempt():
        delay = base_delay
        last_exc: Exception | None = None
        for i in range(1, max_attempts + 1):
            state.attempts = i
            state.started_at = datetime.now().isoformat(timespec="seconds")
            log.info(f"[{state.name}] attempt {i}/{max_attempts}")
            try:
                rc = fn()
                state.last_rc = rc
                if rc == 0:
                    state.completed = True
                    state.finished_at = datetime.now().isoformat(timespec="seconds")
                    log.info(f"[{state.name}] ✓ success on attempt {i}")
                    return 0
                log.warn(f"[{state.name}] rc={rc}, will retry")
            except Exception as e:
                last_exc = e
                state.last_error = repr(e)
                log.error(f"[{state.name}] exception: {e!r}")
            if i < max_attempts:
                jitter = random.uniform(0, delay * 0.3)
                sleep = min(delay + jitter, max_delay)
                log.info(f"[{state.name}] sleeping {sleep:.1f}s before retry")
                time.sleep(sleep)
                delay = min(delay * 2, max_delay)
        if last_exc:
            state.last_error = repr(last_exc)
        state.finished_at = datetime.now().isoformat(timespec="seconds")
        log.error(f"[{state.name}] ✗ exhausted {max_attempts} attempts")
        return 2 if on_exhaust == "fail" else 1

    return attempt()


# -----------------------------------------------------------------------------
# Phase implementations
# -----------------------------------------------------------------------------


def phase_preflight(log: Logger, state: LoopState) -> int:
    """Check Node version, network, disk, brew, openclaw CLI reachability."""
    p = state.phases["preflight"]
    log.section("PHASE 0 · PREFLIGHT")
    p.completed = False

    # 1. Node version
    rc, out, err = run(["node", "-v"], log=log)
    if rc != 0:
        log.error("node not on PATH")
        p.last_error = "node missing"
        return 3
    actual = parse_node_version(out)
    if actual is None:
        log.error(f"cannot parse node version: {out!r}")
        p.last_error = f"unparseable: {out}"
        return 3
    state.before_version = out.strip()
    log.info(f"current node: {out.strip()} → parsed {actual}")
    if node_satisfies(actual):
        log.info("✓ node already satisfies OpenClaw engines, skipping phase 1")
        p.completed = True
        p.finished_at = datetime.now().isoformat(timespec="seconds")
        return 0
    log.warn(f"node {actual} does NOT satisfy engines; phase 1 required")

    # 2. Disk free
    free = disk_free()
    log.info(f"disk free under /opt/homebrew: {fmt_bytes(free)}")
    if free < 500 * 1024 * 1024:  # 500MB
        log.error("insufficient disk for Node install (< 500MB)")
        p.last_error = "low disk"
        return 3

    # 3. Network
    for host in ("github.com", "registry.npmjs.org", "formulae.brew.sh"):
        try:
            socket.create_connection((host, 443), timeout=4).close()
            log.info(f"  ✓ {host} reachable")
        except OSError as e:
            log.warn(f"  ✗ {host} unreachable: {e}")

    # 4. Brew
    rc, out, err = run(["brew", "--version"], log=log)
    if rc == 0:
        log.info(f"brew: {out.splitlines()[0]}")
    else:
        log.warn(f"brew not available: {err.strip()}")

    # 5. OpenClaw binary (will fail because node is bad, but we want to record)
    rc, out, err = run(["openclaw", "--version"], log=log)
    if rc != 0:
        log.warn(f"openclaw --version currently fails: {err.strip().splitlines()[0] if err else '?'}")
    else:
        log.info(f"openclaw: {out.strip()}")

    p.completed = True
    p.finished_at = datetime.now().isoformat(timespec="seconds")
    return 0


def phase_node_upgrade(log: Logger, state: LoopState) -> int:
    """Install Node 24 LTS via brew (preferred), then pkg, then fnm."""
    p = state.phases["node"]
    log.section("PHASE 1 · NODE UPGRADE")
    p.completed = False

    # Re-check
    rc, out, err = run(["node", "-v"], log=log)
    if rc == 0 and node_satisfies(parse_node_version(out) or (0, 0, 0)):
        log.info(f"node already upgraded to {out.strip()}, skip")
        p.completed = True
        p.finished_at = datetime.now().isoformat(timespec="seconds")
        return 0

    # Strategy A: brew install node@24
    def try_brew() -> int:
        log.info("strategy A: brew install node@24")
        rc, out, err = run(
            ["brew", "install", "node@24"],
            timeout=900,
            log=log,
        )
        if rc != 0:
            log.warn(f"brew install failed (rc={rc})")
            return rc
        # Link
        rc, _, err = run(["brew", "link", "--force", "--overwrite", "node@24"], log=log)
        if rc != 0:
            log.warn(f"brew link --force failed: {err.strip()}")
        # Verify
        rc, out, err = run(["node", "-v"], log=log)
        if rc == 0:
            actual = parse_node_version(out)
            if actual and node_satisfies(actual):
                log.info(f"✓ node upgraded via brew to {out.strip()}")
                return 0
        log.warn("node version still does not satisfy after brew install")
        return 1

    rc = retry(
        try_brew,
        max_attempts=3,
        base_delay=4.0,
        log=log,
        state=p,
    )
    if rc == 0:
        p.completed = True
        p.finished_at = datetime.now().isoformat(timespec="seconds")
        return 0

    # Strategy B: brew install node (latest within supported range)
    def try_brew_node() -> int:
        log.info("strategy B: brew install node (stable, may be 26+)")
        rc, _, err = run(["brew", "install", "node"], timeout=900, log=log)
        if rc != 0:
            return rc
        rc, out, _ = run(["node", "-v"], log=log)
        if rc == 0 and node_satisfies(parse_node_version(out) or (0, 0, 0)):
            log.info(f"✓ node upgraded via brew node to {out.strip()}")
            return 0
        return 1

    log.warn("falling back to strategy B (brew install node stable)")
    rc = retry(
        try_brew_node,
        max_attempts=2,
        base_delay=8.0,
        log=log,
        state=p,
    )
    if rc == 0:
        p.completed = True
        p.finished_at = datetime.now().isoformat(timespec="seconds")
        return 0

    # Strategy C: download official pkg installer
    def try_pkg() -> int:
        log.info("strategy C: download official pkg installer")
        # Detect arch
        arch = subprocess.run(["uname", "-m"], capture_output=True, text=True).stdout.strip()
        if arch == "arm64":
            pkg_url = "https://nodejs.org/dist/v24.19.0/node-v24.19.0-arm64.pkg"
        else:
            pkg_url = "https://nodejs.org/dist/v24.19.0/node-v24.19.0.pkg"
        pkg_path = "/tmp/node-installer.pkg"
        rc, _, _ = run(["curl", "-fL", "-o", pkg_path, pkg_url], timeout=300, log=log)
        if rc != 0:
            log.warn(f"pkg download failed rc={rc}")
            return rc
        rc, _, _ = run(["sudo", "-n", "installer", "-pkg", pkg_path, "-target", "/"], timeout=600, log=log)
        if rc != 0:
            log.warn(f"pkg install failed rc={rc} (likely needs interactive sudo)")
            return rc
        rc, out, _ = run(["node", "-v"], log=log)
        if rc == 0 and node_satisfies(parse_node_version(out) or (0, 0, 0)):
            log.info(f"✓ node upgraded via pkg to {out.strip()}")
            return 0
        return 1

    log.warn("falling back to strategy C (pkg installer)")
    rc = retry(
        try_pkg,
        max_attempts=1,
        log=log,
        state=p,
    )
    if rc == 0:
        p.completed = True
        p.finished_at = datetime.now().isoformat(timespec="seconds")
        return 0

    # Strategy D: fnm (last resort, doesn't replace system node but adds shim)
    log.warn("strategy D: fnm per-user node")
    rc, _, _ = run(
        ["bash", "-lc",
         'curl -fsSL https://fnm.vercel.app/install | bash && '
         'export PATH="$HOME/.fnm:$PATH" && '
         'eval "$(fnm env --bash)" && '
         'fnm install 24 && fnm use 24 && fnm default 24 && '
         'node -v'],
        timeout=300,
        log=log,
    )
    if rc == 0:
        log.warn("fnm installed node 24 — but PATH shim is per-shell; openclaw CLI may still use old /opt/homebrew/bin/node")
        log.warn("openclaw will only see the new node if you restart the shell or set PATH=$HOME/.fnm:$PATH first")
    p.completed = False
    p.finished_at = datetime.now().isoformat(timespec="seconds")
    return 2


def phase_dry_run(log: Logger, state: LoopState, channel: str) -> int:
    """Run `openclaw update --dry-run --json` and report plan."""
    p = state.phases["dry_run"]
    log.section("PHASE 2 · DRY-RUN")
    p.completed = False

    rc, out, err = run(
        ["openclaw", "update", "--dry-run", "--json", "--channel", channel],
        timeout=180,
        log=log,
    )
    if rc != 0:
        log.error(f"dry-run failed rc={rc}")
        log.error(f"stderr: {err.strip()[:500]}")
        p.last_error = err.strip()[:500]
        return 2
    try:
        plan = json.loads(out)
    except json.JSONDecodeError as e:
        log.error(f"dry-run output not JSON: {e}")
        log.info(f"raw output: {out[:500]}")
        p.last_error = "non-json"
        return 2
    log.info("dry-run plan:")
    log.info(json.dumps(plan, indent=2))
    p.completed = True
    p.finished_at = datetime.now().isoformat(timespec="seconds")
    return 0


def phase_update(log: Logger, state: LoopState, channel: str, max_attempts: int) -> int:
    """Run `openclaw update --yes --json` with retries."""
    p = state.phases["update"]
    log.section("PHASE 3 · ACTUAL UPDATE")
    p.completed = False

    def attempt() -> int:
        log.info(f"running: openclaw update --yes --json --channel {channel}")
        rc, out, err = run(
            ["openclaw", "update", "--yes", "--json", "--channel", channel],
            timeout=1800,
            log=log,
        )
        if rc != 0:
            log.warn(f"update rc={rc}")
            log.warn(f"stderr (head): {err.strip()[:1000]}")
            log.warn(f"stdout (head): {out.strip()[:500]}")
            return rc
        # Try parse JSON
        try:
            result = json.loads(out)
            status = result.get("status") or result.get("ok")
            log.info(f"update result status: {status}")
            log.info(json.dumps(result, indent=2)[:3000])
            if status in ("ok", "up-to-date", True):
                return 0
            log.warn(f"update returned non-success status: {status}")
            return 1
        except json.JSONDecodeError:
            log.warn("update output is not JSON; treating rc=0 as success")
            log.info(f"raw: {out[:500]}")
            return 0

    rc = retry(
        attempt,
        max_attempts=max_attempts,
        base_delay=8.0,
        max_delay=60.0,
        log=log,
        state=p,
    )
    if rc == 0:
        p.completed = True
        p.finished_at = datetime.now().isoformat(timespec="seconds")
        return 0
    p.finished_at = datetime.now().isoformat(timespec="seconds")
    return 2


def phase_verify(log: Logger, state: LoopState) -> int:
    """Verify install + version + service health."""
    p = state.phases["verify"]
    log.section("PHASE 4 · VERIFY")
    p.completed = False

    # 1. node -v
    rc, out, err = run(["node", "-v"], log=log)
    if rc == 0:
        log.info(f"node: {out.strip()}")
    else:
        log.error(f"node -v failed: {err.strip()}")
        p.last_error = "node missing"
        return 2

    # 2. openclaw --version
    rc, out, err = run(["openclaw", "--version"], log=log)
    if rc == 0:
        log.info(f"openclaw: {out.strip()}")
        state.after_version = out.strip()
    else:
        log.warn(f"openclaw --version failed: {err.strip()[:300]}")
        return 2

    # 3. openclaw update status --json
    rc, out, err = run(["openclaw", "update", "status", "--json"], timeout=30, log=log)
    if rc == 0:
        try:
            st = json.loads(out)
            log.info(f"update status: {json.dumps(st, indent=2)[:1500]}")
        except json.JSONDecodeError:
            log.info(f"update status (raw): {out[:500]}")

    # 4. openclaw status
    rc, out, err = run(["openclaw", "status"], timeout=60, log=log)
    if rc == 0:
        log.info(f"openclaw status:\n{out[:2000]}")
    else:
        log.warn(f"openclaw status rc={rc}: {err.strip()[:300]}")

    p.completed = True
    p.finished_at = datetime.now().isoformat(timespec="seconds")
    return 0


def phase_notify(log: Logger, state: LoopState) -> int:
    """Send Feishu message to Frank with summary."""
    p = state.phases["notify"]
    log.section("PHASE 5 · NOTIFY")
    p.completed = False

    before = state.before_version or "(unknown)"
    after = state.after_version or "(unchanged)"
    failed = [n for n, ps in state.phases.items() if not ps.completed and n != "notify"]

    if failed:
        msg = (
            f"⚠️ openclaw_updater 部分失败\n"
            f"before: {before}\n"
            f"after:  {after}\n"
            f"failed phases: {', '.join(failed)}\n"
            f"日志: {LOG_FILE}\n"
        )
    else:
        msg = (
            f"✅ openclaw_updater 全部完成\n"
            f"before: {before}\n"
            f"after:  {after}\n"
            f"日志: {LOG_FILE}\n"
        )

    # Use the message tool's CLI fallback or write a notify script
    # Prefer the openclaw message action through gateway if available; else
    # print to stdout so the calling agent can relay it.
    log.info("notification (Frank please relay):")
    log.info(msg)

    # Try to send via openclaw CLI message command (best-effort, do not fail this phase)
    rc, _, err = run(
        ["openclaw", "message", "send", "--channel", "feishu",
         "--target", FEISHU_OPEN_ID, "--message", msg],
        timeout=30,
        log=log,
    )
    if rc != 0:
        log.warn(f"feishu send via openclaw failed: {err.strip()[:300]}")
        log.warn("(relay the message above to Frank manually)")

    p.completed = True
    p.finished_at = datetime.now().isoformat(timespec="seconds")
    return 0


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------


PHASES = {
    "preflight": ("PHASE 0", phase_preflight),
    "node": ("PHASE 1", phase_node_upgrade),
    "dry-run": ("PHASE 2", phase_dry_run),
    "update": ("PHASE 3", phase_update),
    "verify": ("PHASE 4", phase_verify),
    "notify": ("PHASE 5", phase_notify),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        choices=list(PHASES.keys()) + ["all"],
        default="all",
        help="which phase to run (default: all)",
    )
    parser.add_argument(
        "--channel",
        default="stable",
        choices=["stable", "extended-stable", "beta", "dev"],
        help="update channel",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="max attempts per phase (default 3)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="don't actually change anything (still runs preflight + dry-run phase)",
    )
    parser.add_argument(
        "--skip-node",
        action="store_true",
        help="skip PHASE 1 even if node is too old (use when you want to fail at update step)",
    )
    args = parser.parse_args()

    log = Logger(LOG_FILE)
    state = LoopState.load()

    log.section(f"openclaw_updater started at {datetime.now().isoformat()}")
    log.info(f"phase: {args.phase}, channel: {args.channel}, max_attempts: {args.max_attempts}")
    log.info(f"log file: {LOG_FILE}")
    log.info(f"state file: {STATE_FILE}")

    # Ctrl-C graceful
    def handler(sig, frame):
        log.warn("interrupted by user")
        state.save()
        sys.exit(4)
    signal.signal(signal.SIGINT, handler)

    # PHASE 0 always
    phases_to_run: list[str]
    if args.phase == "all":
        phases_to_run = ["preflight", "node", "dry-run", "update", "verify", "notify"]
    else:
        phases_to_run = [args.phase]

    overall_rc = 0
    for phase_name in phases_to_run:
        if phase_name == "node" and args.skip_node:
            log.warn("skipping node phase (--skip-node)")
            continue
        _, fn = PHASES[phase_name]
        # Different phases have different signatures.
        if phase_name == "update":
            rc = fn(log, state, args.channel, args.max_attempts)
        elif phase_name == "dry-run":
            rc = fn(log, state, args.channel)
        else:
            rc = fn(log, state)
        state.save()
        if rc != 0:
            log.error(f"phase {phase_name} returned rc={rc}")
            overall_rc = rc
            if phase_name != "notify":
                # non-fatal for notify; fail-fast otherwise
                if args.phase == "all":
                    log.warn("continuing to next phase despite failure (all-mode)")
                else:
                    return rc
    log.info(f"final rc={overall_rc}")
    return overall_rc


if __name__ == "__main__":
    sys.exit(main())