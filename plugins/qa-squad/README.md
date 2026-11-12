# QA Squad plugin

This is the installable Claude Code plugin directory.

Visible components:

- `agents/` — 20 generic QA agents
- `skills/` — 29 QA skills
- `hooks/` — deterministic coverage and secret-safety hooks
- `bin/qa-cli` — project-local QA coverage ledger CLI
- `bin/qa_artifact_report.py` — evidence, failure and goal evidence report generator (Artifact-ready HTML, A4 PDF)
- `bin/qa_scope.py` — user stories, scope resolution and report settings
- `.mcp.json` — Playwright MCP browser integration (`@playwright/mcp@0.0.85` with `--caps=devtools` for the video tools)
- `.claude-plugin/plugin.json` — plugin metadata

Test locally from the repository root:

```bash
claude --plugin-dir ./plugins/qa-squad
```

The CLI is intentionally not on `PATH`. Invoke it as:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" status
```
