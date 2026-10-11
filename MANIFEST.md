# Package Manifest

- QA agents: 20
- QA skills: 28
- Plugin: `plugins/qa-squad`
- Marketplace: `.claude-plugin/marketplace.json`
- Browser integration: Playwright MCP
- Coverage CLI: `plugins/qa-squad/bin/qa-cli`
- Evidence and failure report generator: `plugins/qa-squad/bin/qa_artifact_report.py`
- Scope and user-story support: `plugins/qa-squad/bin/qa_scope.py`
- Coverage Stop hook: included
- `.env` write protection hook: included
- Traceability matrix generator: included
- English-only repository gate: `scripts/check_english_only.py`
