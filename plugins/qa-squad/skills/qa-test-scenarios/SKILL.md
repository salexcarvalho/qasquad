---
name: qa-test-scenarios
description: "Checks whether the project already has test scenarios; imports and executes them, or generates scenarios from the inventory and executes them when there are none."
argument-hint: "[scope: feature, workflow, role or file]"
context: fork
agent: qa-scenario-tester
background: false
---

Detect, import, generate when missing, and execute the test scenarios of this project.

Scope, if any: $ARGUMENTS

Start with the deterministic scan and state its verdict (`FOUND` or `NONE`) before doing
anything else:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" scenario-scan --import
```

If scenarios exist, import any documented ones the scan listed and execute every scenario
without a result. If none exist, generate scenarios from the inventory and execute them. If
the inventory is still empty, run discovery first (`/qa-squad:qa-discover-system`) instead of
inventing scenarios.

Record one result per scenario ID and finish with:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" scenario-list --out .qa/reports/test-scenarios.md
```
