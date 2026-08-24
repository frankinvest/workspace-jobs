#!/usr/bin/env python3
"""
openclaw_gateway_repair.py — Repair the OpenClaw gateway LaunchAgent handoff.

Why this exists:
  Frank's dashboard "Update now" returned
    "Update skipped: managed-service-handoff-unavailable"
  Root cause chain (verified):
    1. OpenClaw gateway has no LaunchAgent plist (never installed).
    2. gateway process PID 1374 is an orphan started manually on 7月 26,
       running OpenClaw 2026.6.11 with Node 22.22.0.
    3. New CLI 2026.7.1-2 + old gateway runtime → startup TypeError
       `params.skillCuratorCleanup is not a function`.
    4. dashboard.update.run needs to hand off to a launchd-supervised
       service boundary; none exists → "handoff unavailable".
    5. Side effect: feishu plugin can't load (needs plugin API >=2026.7.1).

  This loop installs the missing LaunchAgent, kills the orphan, lets
  launchd bootstrap a fresh gateway process, and verifies everything.

Design: 7 phases, exponential backoff, file logging, persistent state.

Usage:
  python3 tools/openclaw_gateway_repair.py                 # run all phases
  python3 tools/openclaw_gateway_repair.py --phase preflight
  python3 tools/openclaw_gateway_repair.py --phase install
  python3 tools/openclaw_gateway_repair.py --phase verify-plist
  python3 tools/openclaw_gateway_repair.py --phase stop-old
  python3 tools/openclaw_gateway_repair.py --phase bootstrap
  python3 tools/openclaw_gateway_repair.py --phase wait-verify
  python3 tools/openclaw_gateway_repair.py --phase notify
  python3 tools/openclaw_gateway_repair.py --keep-old     # skip stop-old
  python3 tools/openclaw_gateway_repair.py --no-bootstrap # don't actually launchctl load
  python3 tools/openclaw_gateway_repair.py --dry-run      # only preflight + verify-plist

Exit codes:
  0   success
  2   phase failure after exhausting retries
  3   fatal preflight (cannot proceed, e.g. no plist after install)
  4   user aborted (Ctrl-C)
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import random
import re
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

EXPECTED_CLI_VERSION = "2026.7.1-2"
EXPECTED_GATEWAY_VERSION = "2026.7.1-2"

GATEWAY_PORT = 18790
GATEWAY_BIND = "127.0.0.1"
LAUNCHD_DOMAIN = f"gui/{os.getuid()}"
PLIST_LABEL = "ai.openclaw.gateway"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{PLIST_LABEL}.plist"

LOG_DIR = Path("/tmp")
LOG_FILE = LOG_DIR / f"openclaw_gateway_repair_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
STATE_FILE = Path("/tmp/openclaw_gateway_repair_state.json")

FEISHU_OPEN_ID = "ou_8fab5d81798938a771ad4be7bb04593c"  # Frank on Feishu


# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------


class Logger:
    """Tee-style logger: stdout + file."""

    def __init__(self, path: Path):
        self.path = path
        self.fh = open(path, "a", buffering=1)
        import atexit

        atexit.register(self.fh.close)

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


# -----------------------------------------------------------------------------
# Command runner
# -----------------------------------------------------------------------------


def run(
    cmd: list[str] | str,
    *,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 300,
    check: bool = False,
    log: Logger | None = None,
    stdin_data: str | None = None,
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
            input=stdin_data,
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
    except subprocess.TimeoutExpired:
        if log:
            log.error(f"timeout after {timeout}s: {printable}")
        return 124, "", f"timeout after {timeout}s"


# -----------------------------------------------------------------------------
# State
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
    pre_state: dict[str, Any] = field(default_factory=dict)
    post_state: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls) -> "LoopState":
        defaults = {
            "preflight": PhaseState(name="preflight"),
            "install": PhaseState(name="install"),
            "verify_plist": PhaseState(name="verify_plist"),
            "stop_old": PhaseState(name="stop_old"),
            "bootstrap": PhaseState(name="bootstrap"),
            "wait_verify": PhaseState(name="wait_verify"),
            "notify": PhaseState(name="notify"),
        }
        if not STATE_FILE.exists():
            return cls(phases=defaults)
        try:
            raw = json.loads(STATE_FILE.read_text())
            state = cls()
            for name in defaults:
                state.phases[name] = PhaseState(**raw.get("phases", {}).get(name, {}))
                state.phases[name].name = name
            state.pre_state = raw.get("pre_state", {})
            state.post_state = raw.get("post_state", {})
            return state
        except Exception:
            return cls(phases=defaults)

    def save(self) -> None:
        STATE_FILE.write_text(
            json.dumps(
                {
                    "phases": {n: ps.__dict__ for n, ps in self.phases.items()},
                    "pre_state": self.pre_state,
                    "post_state": self.post_state,
                },
                indent=2,
            )
        )


# -----------------------------------------------------------------------------
# Retry helper
# -----------------------------------------------------------------------------


def retry(
    fn,
    *,
    max_attempts: int,
    base_delay: float = 2.0,
    max_delay: float = 32.0,
    log: Logger,
    state: PhaseState,
):
    """Run fn() with exponential backoff. Records state.attempts/rc."""
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
    return 2


# -----------------------------------------------------------------------------
# Probes
# -----------------------------------------------------------------------------


def probe_port(port: int) -> dict[str, Any]:
    """Find what is listening on port; return {pid, cmd, port}. Empty if free."""
    rc, out, _ = run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-F", "pcL"],
        timeout=10,
    )
    info: dict[str, Any] = {"pid": None, "cmd": None, "port": port, "free": True}
    if rc != 0 or not out.strip():
        return info
    pid = None
    cmd = None
    for line in out.splitlines():
        if line.startswith("p"):
            pid = int(line[1:])
        elif line.startswith("c"):
            cmd = line[1:]
    if pid is not None:
        info.update({"pid": pid, "cmd": cmd, "free": False})
    return info


def probe_launchd(label: str) -> dict[str, Any]:
    """Inspect launchd service state for `gui/$UID/$label`."""
    rc, out, _ = run(
        ["launchctl", "print", f"{LAUNCHD_DOMAIN}/{label}"],
        timeout=10,
    )
    info: dict[str, Any] = {
        "label": label,
        "exists": rc == 0,
        "state": None,
        "pid": None,
        "active_count": 0,
    }
    if rc != 0:
        return info
    state_m = re.search(r"state\s*=\s*(\S+)", out)
    pid_m = re.search(r"^\s*pid\s*=\s*(\d+)", out, re.MULTILINE)
    active_m = re.search(r"active count\s*=\s*(\d+)", out)
    if state_m:
        info["state"] = state_m.group(1)
    if pid_m:
        info["pid"] = int(pid_m.group(1))
    if active_m:
        info["active_count"] = int(active_m.group(1))
    return info


def probe_cli_version() -> str | None:
    """Get CLI version string."""
    rc, out, _ = run(["openclaw", "--version"], timeout=15)
    if rc != 0:
        return None
    m = re.search(r"OpenClaw\s+(\S+)", out)
    return m.group(1) if m else out.strip()


def probe_gateway_version() -> str | None:
    """Get the running gateway's reported version (via openclaw gateway status)."""
    rc, out, _ = run(["openclaw", "gateway", "status", "--json"], timeout=30)
    if rc != 0:
        return None
    m = re.search(r"Gateway version:\s*(\S+)", out)
    if m:
        return m.group(1)
    try:
        data = json.loads(out)
        if isinstance(data, dict):
            return data.get("version") or data.get("gateway", {}).get("version")
    except json.JSONDecodeError:
        pass
    return None


def parse_plist(path: Path) -> dict[str, Any] | None:
    """Read a launchd plist; return dict or None."""
    try:
        with open(path, "rb") as f:
            return plistlib.load(f)
    except Exception:
        return None


def plist_is_safe(plist_data: dict[str, Any]) -> tuple[bool, list[str]]:
    """Sanity-check the generated plist: Node path looks reasonable, version matches."""
    issues: list[str] = []
    if plist_data.get("Label") != PLIST_LABEL:
        issues.append(f"unexpected Label: {plist_data.get('Label')}")
    env = plist_data.get("EnvironmentVariables", {})
    version = env.get("OPENCLAW_SERVICE_VERSION", "")
    if EXPECTED_CLI_VERSION not in version:
        issues.append(f"OPENCLAW_SERVICE_VERSION={version!r}, expected to contain {EXPECTED_CLI_VERSION}")
    prog = plist_data.get("ProgramArguments", [])
    if not prog:
        issues.append("ProgramArguments missing")
    else:
        node_bin = prog[0]
        if not (node_bin.endswith("/bin/node") or node_bin.endswith("/node")):
            issues.append(f"unexpected ProgramArguments[0]: {node_bin}")
        # Make sure it is NOT node@22 if Node 24 is installed
        if "node@22" in node_bin or "node/22" in node_bin:
            issues.append(f"plist points to old Node 22: {node_bin}")
    return (len(issues) == 0, issues)


# -----------------------------------------------------------------------------
# Phases
# -----------------------------------------------------------------------------


def phase_preflight(log: Logger, state: LoopState) -> int:
    """Gather baseline info: port, PID, launchd, CLI/gateway versions, plist."""
    p = state.phases["preflight"]
    log.section("PHASE 0 · PREFLIGHT")
    p.completed = False

    # 1. Port 18790
    port = probe_port(GATEWAY_PORT)
    state.pre_state["port"] = port
    log.info(f"port {GATEWAY_PORT}: pid={port['pid']} cmd={port['cmd']!r} free={port['free']}")
    if not port["free"]:
        log.warn(f"port {GATEWAY_PORT} is occupied by PID {port['pid']} → needs STOP_OLD before BOOTSTRAP")

    # 2. launchd ai.openclaw.gateway
    gw_svc = probe_launchd(PLIST_LABEL)
    state.pre_state["launchd_gateway"] = gw_svc
    log.info(f"launchd {PLIST_LABEL}: exists={gw_svc['exists']} state={gw_svc['state']} active={gw_svc['active_count']}")

    # 3. existing plist file
    plist_exists = PLIST_PATH.exists()
    state.pre_state["plist_exists"] = plist_exists
    log.info(f"plist {PLIST_PATH}: exists={plist_exists}")

    if plist_exists:
        plist_data = parse_plist(PLIST_PATH)
        if plist_data:
            log.info(f"  Label: {plist_data.get('Label')}")
            prog = plist_data.get("ProgramArguments", [])
            if prog:
                log.info(f"  Program[0]: {prog[0]}")
            env = plist_data.get("EnvironmentVariables", {})
            log.info(f"  OPENCLAW_SERVICE_VERSION: {env.get('OPENCLAW_SERVICE_VERSION')}")
            log.info(f"  OPENCLAW_LAUNCHD_LABEL: {env.get('OPENCLAW_LAUNCHD_LABEL')}")

    # 4. CLI version
    cli_v = probe_cli_version()
    state.pre_state["cli_version"] = cli_v
    log.info(f"CLI version: {cli_v}")

    # 5. Gateway reported version (best-effort, may fail)
    gw_v = probe_gateway_version()
    state.pre_state["gateway_version"] = gw_v
    log.info(f"Gateway reported version: {gw_v}")

    if cli_v != EXPECTED_CLI_VERSION:
        log.warn(f"CLI version mismatch: expected {EXPECTED_CLI_VERSION}, got {cli_v}")

    # 6. Node version
    rc, out, _ = run(["node", "-v"], timeout=10)
    if rc == 0:
        log.info(f"node: {out.strip()}")
        state.pre_state["node_version"] = out.strip()

    p.completed = True
    p.finished_at = datetime.now().isoformat(timespec="seconds")
    return 0


def phase_install(log: Logger, state: LoopState) -> int:
    """Run `openclaw gateway install --force` to (re)generate the plist."""
    p = state.phases["install"]
    log.section("PHASE 1 · INSTALL")
    p.completed = False

    # Make sure parent dir exists
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)

    rc, out, err = run(
        ["openclaw", "gateway", "install", "--force"],
        timeout=120,
        log=log,
    )
    if rc != 0:
        log.error(f"openclaw gateway install --force failed rc={rc}")
        p.last_error = err.strip()[:500]
        return 2

    # Verify plist was generated
    if not PLIST_PATH.exists():
        log.error(f"plist not found at {PLIST_PATH} after install")
        p.last_error = "plist not generated"
        return 3

    p.completed = True
    p.finished_at = datetime.now().isoformat(timespec="seconds")
    return 0


def phase_verify_plist(log: Logger, state: LoopState) -> int:
    """Parse the plist and sanity-check Node path + version."""
    p = state.phases["verify_plist"]
    log.section("PHASE 2 · VERIFY PLIST")
    p.completed = False

    if not PLIST_PATH.exists():
        log.error(f"plist missing at {PLIST_PATH}")
        p.last_error = "plist missing"
        return 3

    plist_data = parse_plist(PLIST_PATH)
    if not plist_data:
        log.error("failed to parse plist")
        p.last_error = "plist unparseable"
        return 3

    log.info(f"Label: {plist_data.get('Label')}")
    prog = plist_data.get("ProgramArguments", [])
    if prog:
        log.info(f"Program[0] (node): {prog[0]}")
        log.info(f"Program[1]: {prog[1]}")
        log.info(f"Program args: {prog[2:]}")
    env = plist_data.get("EnvironmentVariables", {})
    for k in (
        "OPENCLAW_SERVICE_VERSION",
        "OPENCLAW_LAUNCHD_LABEL",
        "OPENCLAW_SERVICE_KIND",
        "OPENCLAW_LOG_PREFIX",
        "PATH",
    ):
        v = env.get(k)
        if v:
            short = v if len(v) < 200 else v[:200] + "…"
            log.info(f"  env {k} = {short}")

    ok, issues = plist_is_safe(plist_data)
    if not ok:
        for issue in issues:
            log.error(f"plist issue: {issue}")
        p.last_error = "; ".join(issues)
        return 2

    p.completed = True
    p.finished_at = datetime.now().isoformat(timespec="seconds")
    return 0


def phase_stop_old(log: Logger, state: LoopState) -> int:
    """Kill the process occupying 18790 (the orphan gateway)."""
    p = state.phases["stop_old"]
    log.section("PHASE 3 · STOP OLD GATEWAY")
    p.completed = False

    port = probe_port(GATEWAY_PORT)
    if port["free"]:
        log.info(f"port {GATEWAY_PORT} is already free, nothing to kill")
        p.completed = True
        p.finished_at = datetime.now().isoformat(timespec="seconds")
        return 0

    pid = port["pid"]
    cmd = port["cmd"]
    log.info(f"killing PID {pid} ({cmd!r})")

    rc, _, _ = run(["kill", str(pid)], timeout=10, log=log)
    if rc != 0:
        log.error(f"kill failed rc={rc}")
        p.last_error = "kill failed"
        return 2

    # Wait for port to be released
    for i in range(30):
        time.sleep(1)
        port = probe_port(GATEWAY_PORT)
        if port["free"]:
            log.info(f"port {GATEWAY_PORT} released after {i + 1}s")
            break
    else:
        log.error(f"port still occupied after 30s")
        p.last_error = "port not released"
        return 2

    p.completed = True
    p.finished_at = datetime.now().isoformat(timespec="seconds")
    return 0


def phase_bootstrap(log: Logger, state: LoopState) -> int:
    """`launchctl bootstrap gui/$UID <plist>` so launchd supervises it."""
    p = state.phases["bootstrap"]
    log.section("PHASE 4 · LAUNCHCTL BOOTSTRAP")
    p.completed = False

    if not PLIST_PATH.exists():
        log.error(f"plist missing: {PLIST_PATH}")
        p.last_error = "plist missing"
        return 3

    # Check if already bootstrapped
    existing = probe_launchd(PLIST_LABEL)
    if existing["exists"] and existing["state"] and existing["state"] != "not running":
        log.warn(f"service already bootstrapped (state={existing['state']}); skipping bootstrap")
        p.completed = True
        p.finished_at = datetime.now().isoformat(timespec="seconds")
        return 0

    rc, out, err = run(
        ["launchctl", "bootstrap", LAUNCHD_DOMAIN, str(PLIST_PATH)],
        timeout=60,
        log=log,
    )
    if rc != 0:
        # Common: "service already bootstrapped" → not fatal
        if "already" in err.lower():
            log.warn(f"already bootstrapped (rc={rc}); continuing")
        else:
            log.error(f"launchctl bootstrap failed rc={rc}: {err.strip()[:300]}")
            p.last_error = err.strip()[:300]
            return 2

    p.completed = True
    p.finished_at = datetime.now().isoformat(timespec="seconds")
    return 0


def phase_wait_verify(log: Logger, state: LoopState) -> int:
    """Wait for launchd to start the service, then verify everything."""
    p = state.phases["wait_verify"]
    log.section("PHASE 5 · WAIT + VERIFY")
    p.completed = False

    deadline = time.time() + 90  # 90s to come up
    attempts = 0
    while time.time() < deadline:
        attempts += 1
        port = probe_port(GATEWAY_PORT)
        svc = probe_launchd(PLIST_LABEL)
        gw_v = probe_gateway_version()
        log.info(
            f"check #{attempts}: port.pid={port['pid']} launchd.state={svc['state']} "
            f"active={svc['active_count']} gateway={gw_v}"
        )

        ready = (
            port["pid"] is not None
            and svc["active_count"] > 0
            and gw_v == EXPECTED_GATEWAY_VERSION
        )
        if ready:
            log.info("✓ gateway is up, version-aligned, and launchd-supervised")
            state.post_state["port_pid"] = port["pid"]
            state.post_state["launchd_state"] = svc["state"]
            state.post_state["gateway_version"] = gw_v
            p.completed = True
            p.finished_at = datetime.now().isoformat(timespec="seconds")
            return 0
        time.sleep(3)

    log.error(f"gateway not ready after {attempts} attempts (~{attempts * 3}s)")
    log.error("check log: /tmp/openclaw/openclaw-*.log")
    p.last_error = "gateway not ready in time"
    return 2


def phase_notify(log: Logger, state: LoopState) -> int:
    """Send Feishu summary to Frank."""
    p = state.phases["notify"]
    log.section("PHASE 6 · NOTIFY")
    p.completed = False

    failed = [n for n, ps in state.phases.items() if not ps.completed and n != "notify"]
    pre_port = state.pre_state.get("port", {})
    post_port = state.post_state

    lines = [
        "🔧 openclaw_gateway_repair 结果",
        "",
        f"  pre  port {GATEWAY_PORT}: pid={pre_port.get('pid')} cmd={(pre_port.get('cmd') or '')[:60]}",
        f"  pre  CLI version: {state.pre_state.get('cli_version')}",
        f"  pre  Gateway version: {state.pre_state.get('gateway_version')}",
        f"  pre  LaunchAgent: {state.pre_state.get('launchd_gateway', {}).get('state')}",
        f"  post port {GATEWAY_PORT}: pid={post_port.get('port_pid')}",
        f"  post Gateway version: {post_port.get('gateway_version')}",
        f"  post launchd state: {post_port.get('launchd_state')}",
        "",
    ]
    if failed:
        lines.append(f"⚠️ failed phases: {', '.join(failed)}")
    else:
        lines.append("✅ 全部 phase 完成")

    lines.append(f"\n日志: {LOG_FILE}")
    msg = "\n".join(lines)

    log.info("feishu message preview:")
    for line in msg.splitlines():
        log.info(f"  {line}")

    rc, _, err = run(
        [
            "openclaw", "message", "send",
            "--channel", "feishu",
            "--target", FEISHU_OPEN_ID,
            "--message", msg,
        ],
        timeout=30,
        log=log,
    )
    if rc != 0:
        log.warn(f"feishu send failed rc={rc}: {err.strip()[:300]}")

    p.completed = True
    p.finished_at = datetime.now().isoformat(timespec="seconds")
    return 0


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------


PHASES = {
    "preflight": phase_preflight,
    "install": phase_install,
    "verify-plist": phase_verify_plist,
    "stop-old": phase_stop_old,
    "bootstrap": phase_bootstrap,
    "wait-verify": phase_wait_verify,
    "notify": phase_notify,
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
        "--keep-old",
        action="store_true",
        help="skip STOP_OLD phase even if port is occupied",
    )
    parser.add_argument(
        "--no-bootstrap",
        action="store_true",
        help="don't actually launchctl bootstrap (just generate + verify plist)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="only run preflight + verify-plist (no changes)",
    )
    args = parser.parse_args()

    log = Logger(LOG_FILE)
    state = LoopState.load()

    log.section(f"openclaw_gateway_repair started at {datetime.now().isoformat()}")
    log.info(f"phase: {args.phase}, keep_old={args.keep_old}, no_bootstrap={args.no_bootstrap}, dry_run={args.dry_run}")
    log.info(f"log file: {LOG_FILE}")
    log.info(f"state file: {STATE_FILE}")

    def handler(sig, frame):
        log.warn("interrupted by user")
        state.save()
        sys.exit(4)

    signal.signal(signal.SIGINT, handler)

    if args.phase == "all":
        phases_to_run = list(PHASES.keys())
    else:
        phases_to_run = [args.phase]

    if args.dry_run:
        phases_to_run = [p for p in phases_to_run if p in ("preflight", "verify-plist")]

    overall_rc = 0
    for phase_name in phases_to_run:
        fn = PHASES[phase_name]
        if phase_name == "stop-old" and args.keep_old:
            log.warn("skipping stop-old (--keep-old)")
            continue
        if phase_name == "bootstrap" and args.no_bootstrap:
            log.warn("skipping bootstrap (--no-bootstrap)")
            continue
        rc = fn(log, state)
        state.save()
        if rc != 0:
            log.error(f"phase {phase_name} returned rc={rc}")
            overall_rc = rc
            if args.phase != "all":
                return rc
            log.warn("continuing to next phase (all-mode)")
    log.info(f"final rc={overall_rc}")
    return overall_rc


if __name__ == "__main__":
    sys.exit(main())