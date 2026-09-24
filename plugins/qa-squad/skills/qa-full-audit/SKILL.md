---
name: qa-full-audit
description: "Runs a complete, generic, traceable QA audit driven towards the configured coverage target."
argument-hint: "[audit goal and requirements]"
disable-model-invocation: true
---

Run the complete QA audit of the current project. You are the orchestrator for this run.

Additional requirements supplied by the user:

$ARGUMENTS

This skill runs in the main conversation on purpose. Subagents cannot start other subagents,
so the delegation below only works from here. Do not hand the whole audit to one subagent.

## Ground rules

- Never assume the product domain; learn it from the code, the UI and `.qa/project-context.md`.
- Use `.env` credentials only when authorized, and never write a secret anywhere.
- Never run destructive operations against production.
- An item counts as covered only when a result is persisted with `qa-cli record`.
- Never declare completion from subagent summaries. Trust only `qa-cli validate`.

The CLI is not on `PATH`:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" <command>
```

## Sequence

1. Initialize or resume the run if `.qa/run-state.json` does not exist:
   `qa-cli init --goal "Full generic QA audit"`.
2. Read the goal above and `.qa/project-context.md` when present.
3. Delegate discovery to `qa-squad:qa-system-discovery`. Do not start mass testing before the
   inventory is sufficient to measure coverage.
4. Delegate the scenario check to `qa-squad:qa-scenario-tester`. It runs
   `qa-cli scenario-scan --import`, reports whether the project already has test scenarios,
   and then either executes the existing ones or generates scenarios from the inventory and
   executes them. Report its verdict (`FOUND` or `NONE`) to the user.
5. Distribute the remaining work by specialty with the Agent tool. Run independent
   workstreams in parallel; pass each agent the exact IDs or scope it owns.
6. Run `qa-cli status` between waves. When gaps exist, delegate the specific missing IDs. Do
   not re-run covered areas without a reason.
7. Ask `qa-squad:qa-coverage-auditor` for an independent review before the final report.
8. Delegate regression tests to `qa-squad:qa-e2e-generator` once the critical flows are
   understood.
9. Close with `qa-squad:qa-report-writer` only when `qa-cli validate` passes.

If the goal requires 100% of menus and submenus per role, discovery must inventory navigation
per role: the same route seen by two roles is two items.

## Delegation map

| Concern | Agent | Coverage category |
|---|---|---|
| discovery | `qa-squad:qa-system-discovery` | all |
| test scenarios | `qa-squad:qa-scenario-tester` | `scenarios` |
| menus and submenus | `qa-squad:qa-navigation-auditor` | `navigation` |
| functional behavior | `qa-squad:qa-functional-tester` | `features` |
| forms | `qa-squad:qa-form-tester` | `forms` |
| workflows | `qa-squad:qa-workflow-tester` | `workflows` |
| roles and permissions | `qa-squad:qa-profile-permission-tester` | `permissions`, `profiles` |
| data integrity | `qa-squad:qa-data-integrity-tester` | `data-integrity` |
| UX | `qa-squad:qa-ux-auditor` | `ux` |
| UI | `qa-squad:qa-ui-visual-auditor` | `ui` |
| responsiveness | `qa-squad:qa-responsive-auditor` | `responsive` |
| accessibility | `qa-squad:qa-accessibility-auditor` | `accessibility` |
| authorization | `qa-squad:qa-security-authorization-tester` | `security` |
| APIs | `qa-squad:qa-api-tester` | `api` |
| resilience | `qa-squad:qa-error-resilience-tester` | `resilience` |
| performance | `qa-squad:qa-performance-auditor` | `performance` |
| regression | `qa-squad:qa-e2e-generator` | n/a |
| independent coverage review | `qa-squad:qa-coverage-auditor` | n/a |
| reporting | `qa-squad:qa-report-writer` | n/a |

While `.qa/run-state.json` is active, the Stop hook blocks the end of the turn until
`qa-cli validate` passes, and returns the missing items. Treat that list as the next wave.
