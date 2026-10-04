---
name: qa-final-report
description: "Generates the final report only once the configured coverage has been satisfied."
context: fork
agent: qa-report-writer
background: false
disable-model-invocation: true
---

First run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" validate
```

If it fails, do not produce a report labelled final. List the gaps and direct the
continuation of the audit instead.

If it passes, generate the traceability matrix, consolidate `.qa/` into the final reports,
sanitize every secret, and then close the run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" matrix --format markdown --out .qa/reports/coverage-matrix.md
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" finish
```

Also publish the deterministic package under `docs/qa/` (executions, requirement acceptance
reports, bugs, evidence and final summary), as `qa-report-writer` now does as part of its own
procedure.

If `$ARGUMENTS` names a `requirement_id`, treat this as scoped mode: publish or regenerate
only that requirement's acceptance report instead of every distinct requirement found.
Otherwise, treat $ARGUMENTS as additional free-form context for the report.
