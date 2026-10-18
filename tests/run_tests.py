#!/usr/bin/env python3
"""Run the full QA Squad test suite and report a single aggregated result."""
import shutil
import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
ROOT = TESTS_DIR.parent

SUITES = [
    ("package structure", ROOT / "scripts" / "validate_package.py"),
    ("english-only gate", ROOT / "scripts" / "check_english_only.py"),
    ("qa-cli behavior", TESTS_DIR / "test_qa_cli.py"),
    ("hooks behavior", TESTS_DIR / "test_hooks.py"),
    ("english gate behavior", TESTS_DIR / "test_english_gate.py"),
]


def main() -> int:
    failed = []
    for label, script in SUITES:
        print(f"\n=== {label} ===")
        proc = subprocess.run([sys.executable, str(script)], text=True)
        if proc.returncode != 0:
            failed.append(label)

    node = shutil.which("node")
    print("\n=== npm package (node:test) ===")
    if node is None:
        print("node not found; skipping npm package tests")
    elif subprocess.run(
        [node, "--test", str(TESTS_DIR / "npm-package.test.js")], text=True
    ).returncode != 0:
        failed.append("npm package")

    print("\n" + "=" * 46)
    if failed:
        print(f"SUITE FAILED: {len(failed)} groups failed")
        for label in failed:
            print(f"  - {label}")
        return 1
    print("SUITE PASSED: all groups")
    return 0


if __name__ == "__main__":
    sys.exit(main())
