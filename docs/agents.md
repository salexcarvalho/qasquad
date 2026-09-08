# Agent catalog

Every agent shares the same operating principles block and the same escalation contract, and
each one owns a single clearly defined responsibility.

| Agent | Responsibility | Reads | Writes (category) |
|---|---|---|---|
| `qa-orchestrator` | Runs the audit, delegates, controls closure | audit goal, `.qa/` | none directly |
| `qa-system-discovery` | Builds the testable universe | code, UI, docs, APIs | all inventories |
| `qa-navigation-auditor` | Menus, submenus, pages, tabs, modals, deep links | `navigation` inventory | `navigation` |
| `qa-functional-tester` | Functional behavior and CRUD | `features` inventory | `features` |
| `qa-form-tester` | Form validation matrix | `forms` inventory | `forms` |
| `qa-workflow-tester` | Journeys and state machines | `workflows` inventory | `workflows` |
| `qa-profile-permission-tester` | RBAC/ABAC on UI and backend | `permissions`, `profiles` | `permissions`, `profiles` |
| `qa-data-integrity-tester` | Data consistency and impossible states | app data surface | `data-integrity` |
| `qa-ux-auditor` | Experience, information architecture, cognitive load | running app | `ux` |
| `qa-ui-visual-auditor` | Visual consistency and design system | running app | `ui` |
| `qa-responsive-auditor` | Layout and usability per viewport | running app | `responsive` |
| `qa-accessibility-auditor` | Keyboard, focus, semantics, contrast | running app | `accessibility` |
| `qa-security-authorization-tester` | Broken access control, IDOR, session, exposure | permissions, APIs | `security` |
| `qa-api-tester` | API contracts, authorization, validation | OpenAPI, routes, traffic | `api` |
| `qa-error-resilience-tester` | Degradation and recovery | critical flows | `resilience` |
| `qa-performance-auditor` | Perceptible and technical bottlenecks | running app, traces | `performance` |
| `qa-e2e-generator` | Regression tests for critical flows | workflows, findings | test files |
| `qa-coverage-auditor` | Independent review, prevents false 100% | whole `.qa/` ledger | gap list |
| `qa-report-writer` | Final traceable report | whole `.qa/` ledger | `.qa/reports/` |

## Shared contract

Every agent definition contains:

- **Operating principles** — identical across all agents, so they cannot drift apart.
- **Running the CLI** — the canonical invocation path.
- **Role**, **Inputs**, **Procedure**, **Outputs**.
- **Escalation** — when to stop and report instead of guessing.

## Escalation

Every agent stops and reports back to the orchestrator, rather than guessing, when
credentials are missing or rejected, the environment is unreachable, the task would require a
destructive action, the authorized scope is ambiguous, or a dependency such as an inventory
has not been produced yet. Affected items are recorded as `blocked` with a justification, so
the ledger reflects reality instead of hiding the gap.
