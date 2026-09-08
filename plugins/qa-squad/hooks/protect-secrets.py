#!/usr/bin/env python3
"""Global QA hook: protect .env writes only while a QA run is active in the current project."""
import json, os, sys
from pathlib import Path

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)

root = Path(os.environ.get("CLAUDE_PROJECT_DIR", data.get("cwd") or os.getcwd())).resolve()
state_path = root / ".qa" / "run-state.json"
if not state_path.exists():
    sys.exit(0)
try:
    state = json.loads(state_path.read_text(encoding="utf-8"))
except Exception:
    sys.exit(0)
if state.get("status") != "active":
    sys.exit(0)

fp = str((data.get("tool_input") or {}).get("file_path") or "").replace("\\", "/")
name = Path(fp).name
protected = name == ".env" or (name.startswith(".env.") and name not in {".env.example", ".env.sample", ".env.template"})
if protected:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "QA safety: credential files may be read when authorized, but must not be modified while a QA audit is active."
        }
    }))
