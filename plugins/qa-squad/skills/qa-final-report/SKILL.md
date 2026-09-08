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

Additional context: $ARGUMENTS
