# QA Squad architecture

## Pipeline

```text
QA Orchestrator
      |
      v
System Discovery ---> Inventories (.qa/inventory)
      |                         |
      v                         v
Specialized agents ------> Results keyed by ID
      |                         |
      +----------+--------------+
                 v
          Coverage Auditor
                 |
          +------+------+
          |             |
        gaps         threshold met
          |             |
          v             v
       re-test    E2E + final report
```

## Why the framework measures the denominator

"I tested everything" is unverifiable without an inventory. Discovery creates the
denominator; results form the numerator.

If the Coverage Auditor discovers a menu that was not in the inventory, it adds it. Coverage
drops automatically until that item is tested. This is the mechanism that makes a false 100%
structurally hard to produce.

An empty category is treated as undiscovered work, not as success. It reports 0% and blocks
closure until it is either inventoried or explicitly declared empty with a justification
recorded in `.qa/declared-empty.json`.

## Agents versus skills versus hooks

- **Agents** are specialists with an isolated context and a single clear responsibility.
- **Skills** are invocable, reusable procedures and operational entry points.
- **Hooks** enforce deterministic rules that do not depend on the model's willingness.
- **`.qa/`** is the operational memory that persists across agents and sessions.

The separation matters: an agent can be persuaded, a hook cannot. The Stop hook is what
turns "please finish the audit" into an enforced constraint.

## `.qa/` versus `docs/qa/`

`.qa/` is the operational ledger: inventories, raw results, findings and working reports,
local to the machine running the audit. `docs/qa/` is the published, versionable evidence
package generated from that ledger: executions, per-requirement acceptance reports, bug
reports, sanitized evidence, and a final summary. The two coexist and serve different
purposes; publishing to `docs/qa/` never replaces `.qa/reports/`.

Inside `docs/qa/`, JSON is the source of truth, Markdown is presentation generated from it,
and screenshots, traces and logs are evidence. Every exported scenario result lands in one
of four states:

`PASS | FAIL | BLOCKED | NOT_EXECUTED`

(`NOT_APPLICABLE` also exists but sits outside the acceptance denominator.) A requirement's
acceptance report resolves deterministically to one of four outcomes:

`ACCEPTED | NOT_ACCEPTED | BLOCKED | INCOMPLETE`

Only a bug classified as `PRODUCT_DEFECT` can move a requirement to `NOT_ACCEPTED`. Every
other failure cause leaves the requirement `BLOCKED`, because the failure has not been
confirmed as a product defect yet. A failure's cause is always one of six categories:

`PRODUCT_DEFECT | TEST_AUTOMATION_FAILURE | ENVIRONMENT_FAILURE | TEST_DATA_FAILURE | BLOCKED | UNDETERMINED`

`requirement_id` is an optional field on a scenario's `metadata`, exactly like the existing
`covers`/`preconditions`/`steps`/`expected` fields. When it is absent, anything that depends
on it reports the literal `NOT_AVAILABLE` rather than a guess.

## Coverage categories

Core categories gate completion by default:

`profiles`, `navigation`, `features`, `forms`, `workflows`, `permissions`, `scenarios`

`scenarios` cannot be declared empty. When the project has no test scenarios, they are
generated from the inventory and executed; see [usage](usage.md#test-scenarios).

Tracked categories give every specialized agent a measurable lane, and can be promoted into
`required_categories` when an audit must formally gate on them:

`api`, `ux`, `ui`, `responsive`, `accessibility`, `security`, `performance`, `resilience`,
`data-integrity`

## Concurrency

Results are written one file per item, which avoids a single `coverage.json` being contended
by several agents at once. Each write is atomic: the CLI writes to a temporary file and then
renames it. Coverage is computed on demand rather than stored.

## Generic by design

No agent knows about civil engineering, scouting, healthcare, an LMS or any other domain by
default. Domain knowledge enters through `.qa/project-context.md` or through the arguments
passed to `/qa-squad:qa-full-audit`.

This is a hard architectural rule. A domain-specific rule inside a core agent would make the
squad unusable on the next project.
