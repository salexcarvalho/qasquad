---
name: qa-retest
description: "Re-executes the scenario behind a recorded bug and appends the outcome to its retest history."
argument-hint: "<bug-id>"
context: fork
agent: qa-scenario-tester
background: false
---

Retest bug `$ARGUMENTS`.

Read `docs/qa/bugs/$ARGUMENTS/bug.json` to find the original `scenario_id` and the
requirement it is tied to. Re-run that specific scenario with the same execution logic you
already use for `/qa-squad:qa-test-scenarios` (Playwright MCP, or the project's own runner for
`suite`/`e2e` kinds) — never a different scenario, never a loosened version of it.

Open a fresh execution, record the new result against the same scenario ID, and close it:

```bash
NEW_EXEC_ID=$(python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" execution-start --executor claude --test-framework playwright)
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" record --category scenarios --id "<scenario id>" \
  --status passed|failed|blocked --scenario "<title>" \
  --evidence "<evidence path>" --notes "retest of $ARGUMENTS"
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" execution-finish --execution "$NEW_EXEC_ID"
```

Then append this attempt to the bug's retest history, without erasing any prior attempt:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" retest --bug "$ARGUMENTS" --execution "$NEW_EXEC_ID" --result PASS|FAIL|BLOCKED
```

Map the recorded status to the retest result: `passed` -> `PASS`, `failed` -> `FAIL`,
`blocked` -> `BLOCKED`. A `PASS` here does not by itself flip the requirement back to
`ACCEPTED`; that is decided deterministically the next time `requirement-report` runs.
