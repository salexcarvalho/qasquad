# Usage

## Starting an audit

```text
/qa-squad:qa-full-audit
```

With explicit requirements:

```text
/qa-squad:qa-full-audit

Test the application from zero.
Discover every real role and test 100% of applicable menus, submenus,
pages, tabs and actions for every role.
Credentials are available in .env. Never expose secrets.
Audit functionality, workflows, permissions, UX, UI, responsive behavior,
accessibility and error handling.
```

## Available commands

```text
/qa-squad:qa-start
/qa-squad:qa-status
/qa-squad:qa-discover-system
/qa-squad:qa-test-navigation
/qa-squad:qa-test-functional
/qa-squad:qa-test-forms
/qa-squad:qa-test-workflows
/qa-squad:qa-test-permissions
/qa-squad:qa-test-data-integrity
/qa-squad:qa-test-ux
/qa-squad:qa-test-ui
/qa-squad:qa-test-responsive
/qa-squad:qa-test-accessibility
/qa-squad:qa-test-security
/qa-squad:qa-test-api
/qa-squad:qa-test-resilience
/qa-squad:qa-test-performance
/qa-squad:qa-test-scenarios
/qa-squad:qa-generate-e2e
/qa-squad:qa-gap-analysis
/qa-squad:qa-coverage-matrix
/qa-squad:qa-final-report
/qa-squad:qa-bugs
/qa-squad:qa-retest
```

## Test scenarios

Before anything is generated, QA Squad checks whether the project already has test
scenarios. The check is deterministic:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" scenario-scan --import
```

| Origin | Detected from | Imported as |
|---|---|---|
| Gherkin | `.feature` files | one item per `Scenario` / `Scenario Outline` |
| Browser E2E | Playwright, Cypress, WebdriverIO, Puppeteer, Selenium specs | one item per test title |
| Automated suites | test scripts in `package.json`, or runner configs | one item per way of running the suite |
| Documents | test plans, test cases and scenario files (`.md`, `.csv`, `.xlsx`) | listed; the agent imports them |

- **Scenarios found:** they are imported into the `scenarios` inventory and executed.
- **No scenarios:** `qa-scenario-tester` generates them from the inventory (happy,
  alternative, negative and boundary paths, each naming the inventory IDs it covers) and
  executes them.

`scenarios` is a core category and cannot be declared empty, so an audit cannot close until
the scan has run and every scenario, existing or generated, has a result. The list is
published with `qa-cli scenario-list --out .qa/reports/test-scenarios.md`.

## Publishing docs/qa/

`docs/qa/` is the deterministic, versionable evidence package generated from the `.qa/`
ledger (see [architecture](architecture.md#qa-versus-docsqa)). Use the skills, not the raw
`qa-cli` commands, for day-to-day work:

- `/qa-squad:qa-final-report` — generates the final report and, as part of the same pass,
  publishes `docs/qa/` (executions, per-requirement acceptance reports, bugs, evidence and
  summary). Pass a `requirement_id` as an argument to publish or regenerate only that
  requirement's acceptance report.
- `/qa-squad:qa-bugs` — lists the bugs recorded under `docs/qa/bugs/`, optionally filtered by
  `--status open|retested` or `--classification`.
- `/qa-squad:qa-retest <bug-id>` — re-executes the scenario behind a bug, opens a new
  execution, and appends the outcome to that bug's retest history without erasing prior
  attempts.

## Reading coverage

```text
category            tested/total  coverage  gate      breakdown
profiles                 8/8       100.00%  REQUIRED  {'passed': 8}
navigation             137/137     100.00%  REQUIRED  {'passed': 130, 'failed': 7}
features                64/64      100.00%  REQUIRED  {'passed': 60, 'failed': 4}
forms                   41/41      100.00%  REQUIRED  {'passed': 41}
workflows               22/22      100.00%  REQUIRED  {'passed': 22}
permissions            184/184     100.00%  REQUIRED  {'passed': 180, 'failed': 4}
security                 0/0         0.00%  tracked   {} (EMPTY - NOT DISCOVERED)
```

A category marked `EMPTY - NOT DISCOVERED` is undiscovered work, not a pass.

Navigation IDs should carry role context whenever behavior or visibility differs by role.
Testing a settings page as an administrator does not automatically cover the same surface for
a manager or a standard user.

## The completion gate

While `.qa/run-state.json` has `"status": "active"`, the bundled Stop hook checks the
coverage ledger. If required coverage is incomplete, it blocks premature completion and
returns the missing items to Claude.

## Generating the traceability matrix

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" matrix --format markdown --out .qa/reports/coverage-matrix.md
```

| Area | Role | Menu | Submenu | Feature | Scenario | Test | Status | Evidence |
|---|---|---|---|---|---|---|---|---|

Any item without a persisted result appears as `NOT TESTED`, which is what makes missing
coverage immediately visible.

## Closing an audit

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" finish
```

This refuses to close while coverage is incomplete. `--force` closes the run as
`closed_incomplete`, which is recorded honestly in the state file rather than being
presented as success.
