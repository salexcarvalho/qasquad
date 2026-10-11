---
name: qa-final-report
description: "Generates the final report only once the configured coverage has been satisfied."
argument-hint: "[requirement ID] [--scope ID] [--no-artifact]"
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

Generate the EVIDENCE report and, only when the scope has a failure or a finding, the FAILURE
report, and publish both as Artifacts (default ON; `--no-artifact` in `$ARGUMENTS`, or
`QA_SQUAD_NO_ARTIFACT=1`, opts out). `qa-report-writer` runs
`python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa_artifact_report.py" --execution "$EXEC_ID" --scope current --artifact --json`
after `final-report`, then calls the Artifact tool for each entry of `publish`. A
`--scope <ID>` in `$ARGUMENTS` selects one story, feature, spec or epic of the execution.

If `$ARGUMENTS` names a `requirement_id`, treat this as scoped mode: publish or regenerate
only that requirement's acceptance report instead of every distinct requirement found.
Otherwise, treat $ARGUMENTS as additional free-form context for the report.
