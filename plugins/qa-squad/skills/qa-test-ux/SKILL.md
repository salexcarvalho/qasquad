---
name: qa-test-ux
description: "Audits UX, discoverability, information architecture and cognitive load."
argument-hint: "[--story ID | --feature NAME | --spec PATH | --epic ID | --scope VALUE] [--no-artifact] [extra scope text]"
context: fork
agent: qa-ux-auditor
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

Run a UX audit over the scope `$ARGUMENTS`. Use the real personas and roles found in the
system, and do not use code knowledge as a shortcut during discovery-style tasks.

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
     --category ux --artifact --out-dir "<scratchpad>/qa-artifacts" --json
   ```

3. Call the Artifact tool once per entry of `publish` in the printed JSON, with its
   `file_path`, `icon` and `description` exactly as listed. Republish the same `file_path` to
   update an artifact. When `publish` has no failure entry, do not invent one: tell the user
   the scope has no failures. Give the user every Artifact link.
4. Run `python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" scope-clear` if you set a scope in this run.
