# Troubleshooting

## `qa-cli: command not found`

The CLI is not on `PATH` by design. Call it through the plugin root:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" status
```

If `CLAUDE_PLUGIN_ROOT` is empty, you are probably running outside plugin context. Locate the
installed plugin directory and call `bin/qa-cli` with `python3` directly.

## The session will not stop

This is the Stop hook doing its job. While `.qa/run-state.json` has `"status": "active"` and
required coverage is below the threshold, the hook blocks completion and lists what is
missing.

To see exactly what is blocking:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" validate
```

To close an intentionally incomplete audit honestly:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" finish --force
```

The run is then recorded as `closed_incomplete` rather than as a success.

## A category shows `EMPTY - NOT DISCOVERED`

Nothing was inventoried for it. This deliberately reports 0%, not 100%, because an empty
inventory used to be the easiest way to fake a complete audit.

Either inventory the category, or declare it empty with a justification:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" declare-empty --category forms --notes "No forms exist; verified by route and component scan"
```

The declaration is retired automatically if an item is later added to that category.

## Coverage dropped after the coverage audit

Expected. The Coverage Auditor adds newly discovered items to the inventory, which increases
the denominator. Coverage recovers as those items are tested.

## Cannot write to `.env`

The `protect-secrets.py` PreToolUse hook denies writes to `.env` and `.env.*` while an audit
is active. Credential files may be read when authorized, but not modified during an audit.
`.env.example`, `.env.sample` and `.env.template` are allowed.

## Playwright MCP is not available

The plugin declares the server in `plugins/qa-squad/.mcp.json` and runs it via
`npx -y @playwright/mcp@latest`. Confirm that Node.js and `npx` are installed and that the
browser environment is available. Without it, browser-driven passes must be recorded as
`blocked`, not silently skipped.

## The English-only gate reports a false positive

Tune the lexicon, or add a narrow exception to `scripts/i18n-allowlist.txt`:

```text
path/to/file.md :: ^the specific line pattern$
```

Prefer a line-scoped regex over exempting a whole file. The allowlist is for documented,
intentional exceptions, not a place to hide translation debt.

## Tests fail after changing coverage logic

Run the suite directly for detail:

```bash
python3 tests/run_tests.py
```

`tests/test_qa_cli.py` includes a regression test asserting that an empty inventory can never
report a complete audit. If that test fails, the false-100% defect has been reintroduced.
