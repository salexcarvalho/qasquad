# QA workflow

## Phases

### 1. Initialize

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" init --goal "Full generic QA audit"
```

Creates `.qa/` in the audited project and marks the run active, which arms the Stop hook.

### 2. Discover

`qa-system-discovery` builds the denominator from multiple independent sources: frontend and
backend routes, menu configuration, role definitions, feature flags, components,
documentation, database schema when authorized, API specs, and the real rendered navigation.

Discovery runs a static pass and a dynamic pass, then compares them. What the code claims
exists and what the UI actually exposes are different questions, and the difference is where
orphan pages and unreachable routes are found.

Discovery is complete only when marked:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" mark-discovery-complete --notes "<what was covered>"
```

### 3. Test by specialty

The orchestrator distributes work across the specialized agents, parallelizing only
independent workstreams. Each agent records one result per inventory ID.

For every discovered feature, the functional pass validates at least: happy path, alternative
path, negative path, boundary conditions, invalid input, missing input, unexpected state,
permission failure, backend failure and network failure where applicable.

### 4. Audit coverage

`qa-coverage-auditor` reviews the ledger independently, looking specifically for a false
100%: incomplete discovery, dynamic menus never inventoried, items not qualified by role,
pages reachable only through an action, feature flags, rare roles, ignored tabs and modals,
`not_applicable` without justification, and coverage recorded without evidence.

New items discovered at this stage are added to the inventory, which lowers coverage until
they are tested. That is the intended behavior.

### 5. Generate regression tests

Only once the critical flows are understood.

### 6. Report

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" matrix --format markdown --out .qa/reports/coverage-matrix.md
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" validate
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" finish
```

The final report is produced only after validation passes.

## Evidence requirements

A test is not passed without evidence that the expected behavior occurred. For failures,
capture: test name, environment, user role, URL or route, reproduction steps, expected
result, actual result, severity, stack trace, relevant logs, sanitized API request and
response, and a screenshot where applicable.

## Severity classification

| Severity | Definition |
|---|---|
| critical | System unavailable, severe security issue, data loss, or an essential workflow completely blocked. |
| high | A major feature is broken, with significant business impact. |
| medium | A feature is partially broken or an important inconsistency exists, with a workaround available. |
| low | A minor functional, visual, usability or consistency problem. |

`P0` to `P3` are accepted as aliases and stored as `severity_code`.

## Honesty rules

- Coverage measures execution, not quality.
- An empty category is undiscovered work, not a pass.
- Never claim 100% while `qa-cli validate` fails.
- Any area that could not be verified is reported as NOT TESTED or BLOCKED, never silently
  treated as covered.
