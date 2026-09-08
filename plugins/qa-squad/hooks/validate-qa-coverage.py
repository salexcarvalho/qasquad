#!/usr/bin/env python3
"""Stop hook: block premature completion while a QA run is active in this project.

The hook is deliberately fail-open. If the QA state cannot be read or the CLI cannot be
executed, the hook exits quietly and allows the stop. A Stop hook that failed closed on an
internal error could trap the session in a loop it cannot escape, which would be a worse
failure than allowing an early stop.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

try:
    hook_input = json.load(sys.stdin)
except (json.JSONDecodeError, ValueError):
    hook_input = {}

root = Path(os.environ.get("CLAUDE_PROJECT_DIR", hook_input.get("cwd") or os.getcwd())).resolve()
state_path = root / ".qa" / "run-state.json"
if not state_path.exists():
    sys.exit(0)

try:
    state = json.loads(state_path.read_text(encoding="utf-8"))
except (json.JSONDecodeError, OSError):
    sys.exit(0)

if state.get("status") != "active":
    sys.exit(0)

plugin_root = Path(os.environ.get("CLAUDE_PLUGIN_ROOT", Path(__file__).resolve().parents[1])).resolve()
cli = plugin_root / "bin" / "qa-cli"
if not cli.exists():
    print(f"qa-squad: CLI not found at {cli}; skipping coverage gate.", file=sys.stderr)
    sys.exit(0)

try:
    proc = subprocess.run(
        [sys.executable, str(cli), "status", "--json"],
        cwd=root, capture_output=True, text=True, timeout=60,
    )
    data = json.loads(proc.stdout)
except (subprocess.SubprocessError, json.JSONDecodeError, ValueError, OSError) as exc:
    print(f"qa-squad: could not read coverage state ({exc}); skipping gate.", file=sys.stderr)
    sys.exit(0)

if data.get("complete"):
    sys.exit(0)

parts = []
if not data.get("state", {}).get("discovery_complete"):
    parts.append("System discovery has not been marked complete.")

threshold = float(data.get("config", {}).get("required_coverage_percent", 100))
categories = data.get("categories", {})
for cat in data.get("required_categories", []):
    v = categories.get(cat)
    if v is None or float(v.get("coverage_percent", 0)) >= threshold:
        continue
    if v.get("empty"):
        parts.append(
            f"{cat}: no items discovered. Inventory this category, or declare it empty with "
            f"'qa-cli declare-empty --category {cat} --notes \"<justification>\"'."
        )
        continue
    missing = v.get("missing", [])
    sample = ", ".join(missing[:8])
    extra = f" (+{len(missing) - 8} more)" if len(missing) > 8 else ""
    parts.append(
        f"{cat}: {v.get('tested', 0)}/{v.get('total', 0)} "
        f"({v.get('coverage_percent', 0)}%). Missing: {sample}{extra}"
    )

reason = (
    "QA AUDIT INCOMPLETE. Continue execution and update the coverage ledger before stopping. "
    + " | ".join(parts)
)
print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
