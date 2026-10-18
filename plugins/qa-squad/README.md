# QA Squad plugin

This is the installable Claude Code plugin directory.

Visible components:

- `agents/` — 20 generic QA agents
- `skills/` — 28 QA skills
- `hooks/` — deterministic coverage and secret-safety hooks
- `bin/qa-cli` — project-local QA coverage ledger CLI
- `bin/qa_artifact_report.py` — evidence and failure report generator (Artifact-ready HTML)
- `bin/qa_scope.py` — user stories, scope resolution and report settings
- `.mcp.json` — Playwright MCP browser integration
- `.claude-plugin/plugin.json` — plugin metadata

Test locally from the repository root:

```bash
claude --plugin-dir ./plugins/qa-squad
```

The CLI is intentionally not on `PATH`. Invoke it as:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" status
```
