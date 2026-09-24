#!/usr/bin/env python3
"""PreToolUse hook: block writes to credential files while a QA run is active.

Covers the file tools (Write, Edit, NotebookEdit) and the common shell forms of writing a
file (redirection, tee, sed -i, cp/mv onto the file). The shell check is a heuristic: it
catches accidental writes, it is not a sandbox.
"""
import json
import os
import re
import sys
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

ALLOWED = {".env.example", ".env.sample", ".env.template"}


def is_protected(path: str) -> bool:
    name = Path(path.replace("\\", "/")).name
    if name in ALLOWED:
        return False
    return name == ".env" or name.startswith(".env.")


# A path token that names a .env file, optionally quoted.
ENV_TOKEN = r"""['"]?(?P<path>[^\s'";|&<>]*\.env(?:\.[\w.-]+)?)['"]?"""
SHELL_WRITES = [
    re.compile(r">>?\s*" + ENV_TOKEN),                          # echo x > .env
    re.compile(r"\btee\b(?:\s+-\w+)*\s+" + ENV_TOKEN),          # ... | tee -a .env
    re.compile(r"\bsed\b[^|;&]*\s-i\S*[^|;&]*?\s" + ENV_TOKEN),  # sed -i 's/a/b/' .env
    re.compile(r"\b(?:cp|mv|install|truncate|dd)\b[^|;&]*\s" + ENV_TOKEN + r"\s*(?:$|[;|&])"),
]

tool = data.get("tool_name") or ""
tool_input = data.get("tool_input") or {}
targets = []
if tool == "Bash":
    command = str(tool_input.get("command") or "")
    for rx in SHELL_WRITES:
        targets += [m.group("path") for m in rx.finditer(command)]
else:
    targets.append(str(tool_input.get("file_path") or tool_input.get("notebook_path") or ""))

if any(t and is_protected(t) for t in targets):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "QA safety: credential files may be read when authorized, but must not be modified while a QA audit is active."
        }
    }))
