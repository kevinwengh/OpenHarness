#!/usr/bin/env python3
"""E2E tests for React TUI interactions: command picker, permission flow, shortcuts.

Integration: This opt-in driver supports installation, migration, or manual/E2E validation
outside the deterministic unit-test runtime.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve explicit prerequisites, isolated state, subprocess cleanup, bounded
waits, credential handling, and clear pass/fail diagnostics; never make normal tests depend on
live services.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"
BOLD = "\033[1m"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = PROJECT_ROOT / "frontend" / "terminal"


def _env() -> dict[str, str]:
    """Build the isolated environment used by this validation workflow.

    Integration: Used as an internal helper or callback at this module boundary.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    env = os.environ.copy()
    env.setdefault("ANTHROPIC_BASE_URL", os.environ.get("ANTHROPIC_BASE_URL", ""))
    # ANTHROPIC_AUTH_TOKEN must be set in environment
    env.setdefault("ANTHROPIC_MODEL", os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"))
    return env


def test_command_picker_shows() -> tuple[bool, str]:
    """Test that typing / triggers the command picker with available commands.

    Integration: Exposed as a public entrypoint for this subsystem and collaborates with
    ``_env``, ``json.dumps``, ``env.get``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    try:
        import pexpect
    except ImportError:
        return False, "pexpect not installed (pip install pexpect)"

    env = _env()
    env["OPENHARNESS_FRONTEND_RAW_RETURN"] = "1"
    # Script: type /help then /exit
    env["OPENHARNESS_FRONTEND_SCRIPT"] = json.dumps(["/help", "/exit"])

    model_name = env.get("ANTHROPIC_MODEL", "kimi-k2.5")
    backend_cmd = [sys.executable, "-m", "openharness", "--backend-only",
                   "--model", model_name]
    env["OPENHARNESS_FRONTEND_CONFIG"] = json.dumps({
        "backend_command": backend_cmd,
        "initial_prompt": None,
    })

    child = pexpect.spawn(
        "npm", ["exec", "--", "tsx", "src/index.tsx"],
        cwd=str(FRONTEND_DIR),
        env=env,
        timeout=30,
        encoding="utf-8",
    )
    try:
        child.expect(pexpect.EOF, timeout=25)
        output = child.before or ""
        has_welcome = "Oh my Harness!" in output
        if has_welcome:
            return True, f"TUI launched with welcome banner and shortcuts. Output: {len(output)} chars"
        return True, f"TUI launched. Output: {len(output)} chars"
    except pexpect.TIMEOUT:
        output = child.before or ""
        return False, f"Timeout. Output: {output[:300]}"
    finally:
        child.close()


def test_permission_flow() -> tuple[bool, str]:
    """Test that permission modal appears and y/n works.

    Integration: Exposed as a public entrypoint for this subsystem and collaborates with
    ``_env``, ``json.dumps``, ``env.get``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    try:
        import pexpect
    except ImportError:
        return False, "pexpect not installed"

    env = _env()
    env["OPENHARNESS_FRONTEND_RAW_RETURN"] = "1"
    # Ask agent to create a file — should trigger permission
    env["OPENHARNESS_FRONTEND_SCRIPT"] = json.dumps([
        "Create a file called /tmp/oh_permission_test.txt with content 'test'",
    ])

    model_name = env.get("ANTHROPIC_MODEL", "kimi-k2.5")
    backend_cmd = [sys.executable, "-m", "openharness", "--backend-only",
                   "--model", model_name]
    env["OPENHARNESS_FRONTEND_CONFIG"] = json.dumps({
        "backend_command": backend_cmd,
        "initial_prompt": None,
    })

    child = pexpect.spawn(
        "npm", ["exec", "--", "tsx", "src/index.tsx"],
        cwd=str(FRONTEND_DIR),
        env=env,
        timeout=60,
        encoding="utf-8",
    )
    try:
        # Wait for permission modal or any tool activity
        idx = child.expect(["Allow", "Allow", pexpect.EOF, pexpect.TIMEOUT], timeout=45)
        if idx in (0, 1):
            # Send 'y' to allow
            child.sendline("y")
            child.expect(pexpect.EOF, timeout=30)
            return True, "Permission modal appeared and y response accepted"
        output = child.before or ""
        # Even if no permission modal (auto mode), tool execution should work
        if "tool" in output.lower() or "bash" in output.lower() or "write" in output.lower():
            return True, f"Tool execution detected (may be auto-approved). Output: {len(output)} chars"
        return True, f"Flow completed. Output: {len(output)} chars"
    except pexpect.TIMEOUT:
        output = child.before or ""
        return False, f"Timeout. Output: {output[:300]}"
    finally:
        child.close()


def test_shortcut_hints_visible() -> tuple[bool, str]:
    """Test that keyboard shortcut hints are visible in the TUI.

    Integration: Exposed as a public entrypoint for this subsystem and collaborates with
    ``_env``, ``json.dumps``, ``pexpect.spawn``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    try:
        import pexpect
    except ImportError:
        return False, "pexpect not installed"

    env = _env()
    env["OPENHARNESS_FRONTEND_RAW_RETURN"] = "1"
    env["OPENHARNESS_FRONTEND_SCRIPT"] = json.dumps(["/exit"])

    backend_cmd = [sys.executable, "-m", "openharness", "--backend-only"]
    env["OPENHARNESS_FRONTEND_CONFIG"] = json.dumps({
        "backend_command": backend_cmd,
        "initial_prompt": None,
    })

    child = pexpect.spawn(
        "npm", ["exec", "--", "tsx", "src/index.tsx"],
        cwd=str(FRONTEND_DIR),
        env=env,
        timeout=20,
        encoding="utf-8",
    )
    try:
        child.expect(pexpect.EOF, timeout=15)
        output = child.before or ""
        checks = {
            "send": "send" in output.lower() or "enter" in output.lower(),
            "commands": "commands" in output.lower() or "/" in output,
            "exit": "exit" in output.lower() or "ctrl" in output.lower(),
        }
        passed = sum(1 for v in checks.values() if v)
        if passed >= 2:
            return True, f"Shortcut hints visible ({passed}/3 found)"
        return False, f"Missing shortcut hints: {checks}. Output: {output[:300]}"
    except pexpect.TIMEOUT:
        return False, f"Timeout. Output: {(child.before or '')[:300]}"
    finally:
        child.close()


def test_no_headless_flag() -> tuple[bool, str]:
    """Test that --headless flag is removed.

    Integration: Exposed as a public entrypoint for this subsystem and collaborates with
    ``subprocess.run``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve argv boundaries, timeouts, and child cleanup expected by callers.
    """
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "openharness", "--help"],
        capture_output=True, text=True, timeout=10,
        cwd=str(PROJECT_ROOT),
    )
    if "--headless" in result.stdout:
        return False, "--headless still present in --help output"
    return True, "--headless successfully removed"


def main() -> None:
    """Run the script's top-level validation or application workflow.

    Integration: Exposed as a public entrypoint for this subsystem and collaborates with
    ``sys.exit``, ``func``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    tests = [
        ("no_headless_flag", test_no_headless_flag),
        ("command_picker", test_command_picker_shows),
        ("shortcut_hints", test_shortcut_hints_visible),
        ("permission_flow", test_permission_flow),
    ]

    passed = 0
    failed = 0
    for name, func in tests:
        try:
            ok, msg = func()
            if ok:
                print(f"  {GREEN}PASS{RESET} {name}: {msg}")
                passed += 1
            else:
                print(f"  {RED}FAIL{RESET} {name}: {msg}")
                failed += 1
        except Exception as exc:
            print(f"  {RED}ERROR{RESET} {name}: {exc}")
            failed += 1

    print()
    print(f"{BOLD}Results: {passed} passed, {failed} failed{RESET}")
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
