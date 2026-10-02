# QA documentation (docs/qa)

This directory holds the deterministic, publishable output of the QA Squad audit. It is
generated from `.qa/` (the audit's working state) and is meant to be committed and read by
humans: developers, reviewers, and whoever signs off on a requirement.

Everything here is derived, not authored by hand. Re-running the commands below regenerates
these files from the current `.qa/` state.

## Structure

```text
docs/qa/
  executions/<execution_id>/
    execution.json          # branch, commit, environment, start/finish timestamps, status
    environment.json        # a focused copy of the environment facts
    scenarios/<scenario>/
      result.json           # PASS | FAIL | BLOCKED | NOT_EXECUTED | NOT_APPLICABLE
      report.md              # human-readable report for this one scenario
  evidence/<execution_id>/<scenario>/
    screenshots/ videos/ traces/ logs/ console/ network/
  reports/<requirement_id>/
    acceptance.json          # ACCEPTED | NOT_ACCEPTED | BLOCKED | INCOMPLETE
    ACCEPTANCE-REPORT.md
  bugs/<bug_id>/
    bug.json
    BUG-REPORT.md
  summary/<execution_id>/
    summary.json
    FINAL-REPORT.md
    evidence-manifest.json
```

## Running an execution

```bash
EXEC=$(python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" execution-start \
  --base-url https://staging.example.com --executor "Jane Doe")
# ... record scenario results in .qa/ as usual (qa-cli record) ...
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" execution-finish --execution "$EXEC"
```

`execution-start` detects `branch` and `commit` from git automatically. Outside a git repo,
or when git fails, these are recorded as the literal `NOT_AVAILABLE` rather than guessed.

An execution is immutable once finished: `execution-finish` on an already-finished execution
fails on purpose. To redo testing, start a new execution.

## Interpreting scenario status

Status is read straight from the result already recorded in `.qa/results/scenarios/`:

- `PASS`: recorded as `passed`.
- `FAIL`: recorded as `failed`.
- `BLOCKED`: recorded as `blocked`.
- `NOT_APPLICABLE`: recorded as `not_applicable`. Shown, but excluded from the denominator of
  acceptance: it never counts for or against a requirement.
- `NOT_EXECUTED`: inventoried in `.qa/inventory/scenarios.json` but with no result recorded yet.

## Finding evidence

Each scenario's `result.json` lists its evidence as paths relative to the project root, under
`docs/qa/evidence/<execution_id>/<scenario>/`. Files are sorted by kind:
`screenshots/`, `videos/`, `traces/`, `logs/`, `console/`, `network/`.

Text evidence (`.log`, `.txt`, `.json` that looks like a console or network capture) is
sanitized before being copied: values that look like bearer tokens, passwords, API keys,
cookies, or CPF numbers are replaced with `***REDACTED***`. If a file cannot be safely read as
text, its copy is replaced with the literal `EVIDENCE_REDACTED` and the scenario's notes say so.

## Acceptance per requirement

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" requirement-report <requirement_id> --execution "$EXEC"
```

This requires the execution to already be finished. It reads every exported scenario whose
`requirement_id` matches, and applies this rule, in order, stopping at the first match:

1. Any `FAIL` scenario with a bug classified `PRODUCT_DEFECT` -> `NOT_ACCEPTED`.
2. Otherwise, if there is any `BLOCKED` scenario, any `FAIL` without a linked bug, or any `FAIL`
   whose bug is classified `TEST_AUTOMATION_FAILURE`, `ENVIRONMENT_FAILURE`,
   `TEST_DATA_FAILURE`, `BLOCKED`, or `UNDETERMINED` -> `BLOCKED` (not confirmed clean, not
   confirmed a defect).
3. Otherwise, if any scenario is `NOT_EXECUTED` -> `INCOMPLETE`.
4. Otherwise, if at least one scenario `PASS`ed -> `ACCEPTED`.
5. Otherwise -> `INCOMPLETE`.

The result, counts, linked bugs and scenario list are written to
`docs/qa/reports/<requirement_id>/acceptance.json` and `ACCEPTANCE-REPORT.md`.

## Bug reports

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" bug-report \
  --scenario <scenario_id> --execution "$EXEC" \
  --classification PRODUCT_DEFECT \
  --summary "short summary" \
  --observed-fact "what was actually seen, without interpretation" \
  --hypothesis "optional technical hypothesis, never presented as a confirmed cause"
```

A `BUG-REPORT.md` keeps "Observed fact" (what was seen) and "Technical hypothesis" (never a
confirmed root cause) as two distinct sections, on purpose. `classification` drives the
acceptance rule above, so classify carefully: only `PRODUCT_DEFECT` blocks acceptance outright.

## Retesting a bug

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" retest --bug <bug_id> --execution <new_execution_id> --result PASS
```

Every retest is appended to the bug's `retest_history`; nothing is ever erased.
`qa-cli bugs-list` shows a bug as `retested` once its latest retest result is `PASS`, and
`open` otherwise.

## Final report and history

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" final-report --execution "$EXEC"
```

Aggregates every requirement touched by the execution into
`docs/qa/summary/<execution_id>/summary.json` and `FINAL-REPORT.md`, with `overall_result`
following the same precedence as a single requirement: any `NOT_ACCEPTED` requirement makes the
whole execution `NOT_ACCEPTED`; otherwise any `BLOCKED` makes it `BLOCKED`; otherwise any
`INCOMPLETE` makes it `INCOMPLETE`; otherwise it is `ACCEPTED`.

Because every execution directory is immutable once finished, `docs/qa/executions/` is a full,
auditable history across time: nothing here is ever overwritten, only added to.
