# Skill catalog

Skills are the invocable entry points. Plugin skills are namespaced, so they are invoked as
`/qa-squad:<skill>`.

## Utility skills

| Skill | Purpose | Backing agent |
|---|---|---|
| `qa-start` | Initialize or resume a persistent audit | none (direct) |
| `qa-status` | Show coverage and audit state | none (direct) |
| `qa-check-coverage` | Query and strictly validate coverage | none (direct) |
| `qa-record-finding` | Required pattern for a traceable finding | none (direct) |
| `qa-coverage-matrix` | Generate the traceability matrix | none (direct) |

## Orchestration skills

| Skill | Purpose | Backing agent |
|---|---|---|
| `qa-full-audit` | Run the complete audit | `qa-orchestrator` |
| `qa-discover-system` | Build the testable universe | `qa-system-discovery` |
| `qa-gap-analysis` | Find untested items and false 100% | `qa-coverage-auditor` |
| `qa-final-report` | Final report, gated on coverage | `qa-report-writer` |
| `qa-generate-e2e` | Regression test generation | `qa-e2e-generator` |

## Specialist testing skills

| Skill | Purpose | Backing agent |
|---|---|---|
| `qa-test-navigation` | Menus, submenus, pages, tabs, modals | `qa-navigation-auditor` |
| `qa-test-functional` | Features and CRUD | `qa-functional-tester` |
| `qa-test-forms` | Form validation matrix | `qa-form-tester` |
| `qa-test-workflows` | Journeys and state machines | `qa-workflow-tester` |
| `qa-test-permissions` | Roles and permissions | `qa-profile-permission-tester` |
| `qa-test-data-integrity` | Data consistency | `qa-data-integrity-tester` |
| `qa-test-ux` | UX and information architecture | `qa-ux-auditor` |
| `qa-test-ui` | Visual consistency | `qa-ui-visual-auditor` |
| `qa-test-responsive` | Responsiveness per viewport | `qa-responsive-auditor` |
| `qa-test-accessibility` | Practical accessibility | `qa-accessibility-auditor` |
| `qa-test-security` | Authorized security testing | `qa-security-authorization-tester` |
| `qa-test-api` | API contracts and behavior | `qa-api-tester` |
| `qa-test-resilience` | Error and recovery behavior | `qa-error-resilience-tester` |
| `qa-test-performance` | Performance bottlenecks | `qa-performance-auditor` |

## Agent and skill relationship

Each specialist skill is a thin, scoped entry point into exactly one agent, passing
`$ARGUMENTS` as the scope. This keeps a single responsibility per agent while letting a user
start any pass directly, without going through the orchestrator.

`scripts/validate_package.py` enforces that every `agent:` referenced by a skill exists, and
that every `skills:` entry referenced by an agent exists.
