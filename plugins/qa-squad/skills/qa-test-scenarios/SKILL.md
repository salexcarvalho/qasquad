---
name: qa-test-scenarios
description: "Checks whether the project already has test scenarios; imports and executes them, or generates scenarios from the inventory and executes them when there are none."
argument-hint: "[--story ID | --feature NAME | --spec PATH | --epic ID | --scope VALUE] [--no-artifact] [extra scope text]"
context: fork
agent: qa-scenario-tester
background: false
---

## Scope (do this first)

If `$ARGUMENTS` carries `--story <ID>`, `--feature <name>`, `--spec <path>`, `--epic <ID>` or
`--scope <value>` (or names a user story or a story file in plain words), restrict the whole
run to it before testing anything. Add `--source <file or folder>` when the story lives
somewhere unusual:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" scope-set --story <ID>   # or --feature / --spec / --epic / --scope
```

`scope-set` turns the acceptance criteria into scenarios tagged with the scope. Everything you
record afterwards inherits the scope. Inventory items discovered before the scope existed are
untagged: tag the ones that belong to it (judge by the criteria, routes and `covers`) with
`python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" scope-tag --category <category> --id <item id>`
(or `--match <text>`), and run discovery for the scope when nothing in the inventory matches.
Test only items tagged with the scope, and never touch or report items of another scope. Without scope flags, run
`python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" scope-clear` first so that a stale scope cannot tag
this run.

## Task

Detect, import, generate when missing, and execute the test scenarios of this project.

Scope, if any: $ARGUMENTS

Typical calls: `/qa-squad:qa-test-scenarios --story US-A01-03`, `--feature youth`,
`--spec specs/youth.md`, `--epic A01`, or a user story / story file named in plain words.

Start with the deterministic scan and state its verdict (`FOUND` or `NONE`) before doing
anything else:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" scenario-scan --import
```

If scenarios exist, import any documented ones the scan listed and execute every scenario
without a result. If none exist, generate scenarios from the inventory and execute them. If
the inventory is still empty, run discovery first (`/qa-squad:qa-discover-system`) instead of
inventing scenarios.

When the scope is a user story, an epic or a spec, `scope-set` has already turned each
acceptance criterion (Gherkin `Given/When/Then`, in English or in the languages of
`templates/i18n.json`, or a bullet) into one executable scenario with preconditions, steps
and an expected result, tagged with the scope and with `requirement_id` set to the story ID.
Execute exactly those first. Execute other scenarios (existing or generated) only when they
are tagged with the scope: existing ones are tagged when their title, source or feature names
the scope ID; register any scenario you generate with `inventory-add ... --scope-id <ID>`
(the active scope is applied automatically). One result per criterion scenario, with its
screenshots as evidence. The report then shows PASS or FAIL per criterion with that evidence.

Scenarios that carry a `requirement_id` become traceable all the way to the per-requirement
acceptance report published under `docs/qa/reports/`.

Record one result per scenario ID and finish with:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" scenario-list --out .qa/reports/test-scenarios.md
```

## Closing: evidence and failure artifacts

Every run ends by generating an evidence report and, only when there is a failure or a
finding, a failure report, and publishing both as Artifacts. This is ON by default. Skip the
publishing only when `$ARGUMENTS` contains `--no-artifact` (or the project sets
`QA_SQUAD_NO_ARTIFACT=1` / `artifacts.publish=false`); the generator then writes standalone
HTML into `docs/qa/` instead.

1. Close the work as an execution, and promote each failed scenario to a bug with
   `qa-cli bug-report` when you know its classification:

   ```bash
   EXEC_ID=$(python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" execution-start --executor claude --test-framework playwright)
   python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" execution-finish --execution "$EXEC_ID"
   ```

2. Generate the reports for this scope and lane. Use the session scratchpad directory from
   your system prompt as `--out-dir` (omit it when there is none). Add `--no-artifact` when
   `$ARGUMENTS` has it:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa_artifact_report.py" --execution "$EXEC_ID" --scope current \
     --category scenarios --artifact --out-dir "<scratchpad>/qa-artifacts" --json
   ```

3. Call the Artifact tool once per entry of `publish` in the printed JSON, with its
   `file_path`, `icon` and `description` exactly as listed. Republish the same `file_path` to
   update an artifact. When `publish` has no failure entry, do not invent one: tell the user
   the scope has no failures. Give the user every Artifact link.
4. Run `python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" scope-clear` if you set a scope in this run.
