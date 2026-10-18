# Evidence and failure artifacts, and scoped runs

## What every run produces

Every execution of QA Squad ends by generating two reports and publishing them with the
Claude Code Artifact tool. This is the default; nothing has to be asked for.

| Report | When | Contents |
|---|---|---|
| Evidence report | always | verdict, summary counts, result per acceptance criterion / scenario / item, screenshots and navigation frames, trace and video paths, logs and console output, coverage by category, requirement acceptance, environment |
| Failure report | only when the scope has a failure or a finding | error and observed fact, expected result, steps to reproduce, the screenshot of the moment, other evidence, severity, classification, hypothesis (kept apart, never stated as fact), anchors (scope, criterion, scenario, finding, bug) |

A scope without failures gets no failure report. The generator removes a stale one and the run
says "no failures in scope X". It never writes a failure report by hand.

Which runs: `qa-full-audit` (through `qa-report-writer`), every `qa-test-*` skill,
`qa-test-scenarios`, `qa-retest`, `qa-final-report`, and `qa-artifacts` on demand.

## Opting out

| Mechanism | Effect |
|---|---|
| `--no-artifact` on a skill | no Artifact is built or published for that run |
| `QA_SQUAD_NO_ARTIFACT=1` | same, for the shell or CI |
| `"artifacts": {"publish": false}` in `.qa/config.json` | same, for the project |

With an opt-out, `qa_artifact_report.py` writes standalone HTML (complete documents) into
`docs/qa/executions/<id>/scope-<id>/` and its `publish` list is empty. Precedence:
`--no-artifact`, then the environment variable, then `.qa/config.json`, then the default (on).
`qa_artifact_report.py --settings` prints the resolved settings and the reason. The Stop hook
respects the same opt-out: without it, a covered audit is not allowed to end before the
reports were generated.

`artifacts.language` (`en` or `pt-BR`, or `QA_SQUAD_REPORT_LANG`) sets the language of the
pages; `artifacts.budget_mb` lowers the size budget (never above 12).

## The generator

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa_artifact_report.py" --execution <id|latest> --scope current \
  --artifact --out-dir "<scratchpad>/qa-artifacts" --json
```

| Flag | Meaning |
|---|---|
| `--execution` | execution ID, or `latest` (newest finished one with a manifest) |
| `--scope` | `current` (the scope the execution ran with), or a story/feature/spec/epic ID that is part of it |
| `--category` | only these coverage categories (repeatable); used by the per-lane `qa-test-*` skills |
| `--artifact` | Artifact fragments into `--out-dir` (default `.qa/artifacts/<execution>/`) plus `artifact-plan.json` |
| `--standalone` | complete HTML documents in `docs/qa/executions/<id>/scope-<id>/` (default when `--artifact` is absent) |
| `--no-artifact` | opt out (see above) |
| `--lang`, `--budget-mb`, `--json` | language, size budget, machine-readable output |
| `--settings`, `--selftest`, `--write-example DIR` | resolved settings, built-in checks, synthetic example package |

`artifact-plan.json` and the `publish` array of the JSON output list, per page, the
`file_path`, the `icon` word and a one-sentence `description` to pass to the Artifact tool.
Republish the same `file_path` to update an artifact.

Artifact pages follow the platform contract: no `<!doctype>`, `<html>`, `<head>` or `<body>`
tags; a `<title>` of two to four words first (`QA Evidence US-A01-03`, `QA Failures US-A01-03`);
color tokens on `:root` with a dark variant under `prefers-color-scheme` and
`[data-theme="dark"]`; an explicit `body` background; a 16 px side gutter; tables and code in
`overflow-x:auto` containers; no scripts and no external resources; images as data URIs. The
generator's `check_artifact_html()` enforces this and the test suite runs it on every output.

### Size budget and secrets

Each page is kept at or under 12 MB. When it would exceed the budget, the generator steps
down through seven levels (fewer images per item, lower resolution and quality, shorter logs,
finally no images) and lists what it left out on the page, under "Left out of this page".
Screenshots are re-encoded as JPEG when Pillow is installed; without it they are embedded as
they are when small enough and listed as left out otherwise. Videos and traces are never
embedded, only their paths and sizes.

Authorization headers, bearer tokens, JWTs, passwords, API keys, cookies, URL credentials and
CPF numbers are masked in logs, notes and error text before they reach a page. Text evidence
is also sanitized when it is copied into `docs/qa/evidence/`.

## Scopes

A scope ties a run to one thing. Types: `story`, `feature`, `spec`, `epic`, `full`.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" scope-set --story US-A01-03
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" scope-set --epic A01
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" scope-set --spec specs/youth.md
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" scope-set --feature youth
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" scope-set --scope <value>    # type detected
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" scope-set --story US-X-1 --title "Pay by card" \
  --criterion "Given a cart; When the user pays; Then the order is paid"   # story typed in chat
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" scope-tag --category forms --match login
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" scope-show
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" scope-clear
```

The skills do this for you when their arguments carry `--story`, `--feature`, `--spec`,
`--epic` or `--scope`. `scope-clear` runs when no scope flag is given, so a stale scope never
tags a later run.

### Scope schema

Stored in `.qa/scope.json` and copied to `docs/qa/executions/<id>/scope.json` and
`scope-<id>/scope.json`:

```json
{
  "schema": "qa-squad/scope/1",
  "type": "story",
  "id": "US-A01-03",
  "title": "Require a second factor",
  "source": "docs/_handoff/user-stories/A01-access.md",
  "line": 87,
  "narrative": "As a platform owner, I want ... so that ...",
  "persona": "support",
  "priority": "Must",
  "parent_id": "A01",
  "ids": ["US-A01-03", "A01"],
  "acceptance_criteria": [
    {
      "id": "US-A01-03/AC-01",
      "story_id": "US-A01-03",
      "title": "Superadmin without 2FA",
      "kind": "gherkin",
      "steps": [
        {"keyword": "Given", "type": "given", "text": "a superadmin with no 2FA"},
        {"keyword": "When", "type": "when", "text": "they sign in"},
        {"keyword": "Then", "type": "then", "text": "no session is issued"}
      ]
    }
  ],
  "children": []
}
```

An `epic` or `spec` scope lists its stories in `children` (each with its own criteria) and
flattens their criteria in `acceptance_criteria`. `ids` is what new records are stamped with.

### How the scope propagates

- `scope-set` registers one executable scenario per criterion in the `scenarios` inventory
  (`scenario:criterion:<criterion id>`), with `preconditions` (Given), `steps` (When),
  `expected` (Then), the Gherkin lines, `requirement_id` set to the story ID, and
  `metadata.scope_ids`.
- `inventory-add`, `record` and `finding` stamp the active scope (`scope_ids`) unless
  `--scope-id` says otherwise; a result also carries the `criterion_id` of its scenario.
- `scope-tag` attaches the scope to inventory items discovered before the scope existed.
- `execution-start` snapshots the scope; `execution-finish` exports only in-scope scenarios and
  writes `manifest.json` with in-scope items, findings and bugs.
- The generator keeps items whose `scope_ids` contain the requested scope. A story's failure
  therefore never reaches another story's pages, and `full` keeps everything.

### Folder layout

```text
docs/qa/executions/<execution_id>/
  execution.json
  scope.json
  manifest.json
  scenarios/<scenario>/{result.json,report.md}
  scope-<id>/
    scope.json
    reports.json              what was generated, sizes, levels
    evidence-report.html      standalone mode only
    failure-report.html       standalone mode, only when there are failures
```

## User-story format

Stories are read from `docs/_handoff/user-stories`, `docs/user-stories`, `docs/stories`,
`user-stories`, `docs/specs`, `specs`, `docs/requirements` and `docs` (or `--source`). The
parser is tolerant:

- optional front matter (`epic`, `title`);
- a heading per story starting with its ID (`### US-A01-01 - Title`);
- a narrative sentence ("As a ..., I want ... so that ...");
- a labelled "Acceptance criteria" block with Gherkin inside a fenced block: `Scenario`,
  `Scenario Outline` with `Examples`, `Given`, `When`, `Then`, `And`, `But`, `Background`.
  Other languages come from `plugins/qa-squad/bin/templates/i18n.json`; Portuguese ships
  with it. A plain bullet list also works, one criterion per bullet.

A story that cannot be found is an error; criteria are never invented.

## Updating an installed copy

An installed copy is a snapshot. Run `claude plugin marketplace update
salexcarvalho-claude-plugins` and `claude plugin update qa-squad@salexcarvalho-claude-plugins`,
then restart Claude Code or run `/reload-plugins` (see [installation](installation.md)).
