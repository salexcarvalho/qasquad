#!/usr/bin/env python3
"""Behavioral tests for the bundled hooks."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
PLUGIN = PKG / "plugins" / "qa-squad"
STOP_HOOK = PLUGIN / "hooks" / "validate-qa-coverage.py"
SECRETS_HOOK = PLUGIN / "hooks" / "protect-secrets.py"
CLI = PLUGIN / "bin" / "qa-cli"


class Failure(Exception):
    pass


def check(condition, message):
    if not condition:
        raise Failure(message)


def cli(root, *args):
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(root)
    return subprocess.run([sys.executable, str(CLI), *args], env=env, text=True, capture_output=True)


def run_hook(hook, root, payload):
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(root)
    env["CLAUDE_PLUGIN_ROOT"] = str(PLUGIN)
    return subprocess.run(
        [sys.executable, str(hook)], input=json.dumps(payload),
        env=env, text=True, capture_output=True, timeout=90,
    )


def test_stop_hook_silent_without_qa_state():
    with tempfile.TemporaryDirectory() as d:
        p = run_hook(STOP_HOOK, Path(d), {"cwd": d})
        check(p.returncode == 0, "hook must exit 0 when no audit exists")
        check(p.stdout.strip() == "", f"hook must stay silent, got: {p.stdout}")


def test_stop_hook_blocks_incomplete_audit():
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        cli(r, "init", "--goal", "hook test")
        cli(r, "inventory-add", "--category", "navigation", "--id", "nav:1", "--label", "Home")
        p = run_hook(STOP_HOOK, r, {"cwd": d})
        check(p.stdout.strip() != "", "hook must emit a decision for an incomplete audit")
        data = json.loads(p.stdout)
        check(data.get("decision") == "block", f"expected block, got {data}")
        check("QA AUDIT INCOMPLETE" in data.get("reason", ""), "reason must state the audit is incomplete")
        check("nav:1" in data.get("reason", ""), "reason must name the missing item")


def test_stop_hook_allows_complete_audit():
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        cli(r, "init", "--goal", "hook test")
        for cat in ["profiles", "navigation", "features", "forms", "workflows", "permissions"]:
            cli(r, "declare-empty", "--category", cat, "--notes", "not applicable")
        cli(r, "mark-discovery-complete", "--notes", "done")
        p = run_hook(STOP_HOOK, r, {"cwd": d})
        check(p.stdout.strip() == "", f"hook must allow a complete audit, got: {p.stdout}")


def test_stop_hook_inactive_run_is_ignored():
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        cli(r, "init", "--goal", "hook test")
        state_path = r / ".qa" / "run-state.json"
        state = json.loads(state_path.read_text())
        state["status"] = "complete"
        state_path.write_text(json.dumps(state))
        p = run_hook(STOP_HOOK, r, {"cwd": d})
        check(p.stdout.strip() == "", "hook must ignore a run that is not active")


def test_stop_hook_fails_open_on_corrupt_state():
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        (r / ".qa").mkdir()
        (r / ".qa" / "run-state.json").write_text("{ this is not json")
        p = run_hook(STOP_HOOK, r, {"cwd": d})
        check(p.returncode == 0, "hook must fail open on corrupt state rather than trapping the session")
        check(p.stdout.strip() == "", "hook must not block on corrupt state")


def _secrets(root, file_path):
    return run_hook(SECRETS_HOOK, root, {"cwd": str(root), "tool_input": {"file_path": file_path}})


def test_secrets_hook_denies_env_write_during_audit():
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        cli(r, "init", "--goal", "secrets")
        for name in [".env", ".env.production", ".env.local"]:
            p = _secrets(r, str(r / name))
            check(p.stdout.strip() != "", f"{name} write must be denied")
            data = json.loads(p.stdout)
            decision = data["hookSpecificOutput"]["permissionDecision"]
            check(decision == "deny", f"{name} expected deny, got {decision}")


def test_secrets_hook_allows_example_files():
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        cli(r, "init", "--goal", "secrets")
        for name in [".env.example", ".env.sample", ".env.template", "config.py"]:
            p = _secrets(r, str(r / name))
            check(p.stdout.strip() == "", f"{name} must not be denied")


def test_secrets_hook_inactive_outside_audit():
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        p = _secrets(r, str(r / ".env"))
        check(p.stdout.strip() == "", "hook must not interfere when no audit is active")


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]


def main():
    failures = []
    for fn in TESTS:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except Failure as exc:
            failures.append(fn.__name__)
            print(f"  FAIL  {fn.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures.append(fn.__name__)
            print(f"  ERROR {fn.__name__}: {exc!r}")
    print(f"hook tests: {len(TESTS) - len(failures)}/{len(TESTS)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
