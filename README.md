# QA Squad for Claude Code

**Generic autonomous multi-agent QA for Claude Code with deterministic coverage enforcement.**

QA Squad discovers the real test surface of an application, maps roles and navigation, executes specialized QA passes, stores evidence and findings, tracks persistent coverage, and prevents an active audit from being declared complete while required coverage is below the configured threshold.

> Discover first. Test by profile. Record evidence. Measure the denominator. Do not fake 100%.

## Why QA Squad

AI testing often fails in a predictable way: the agent visits a few screens, finds some bugs, and says the audit is complete. QA Squad separates **discovery**, **execution**, and **coverage** so completeness is measurable.

Core capabilities:

- 20 specialized QA agents
- 25 reusable QA skills
- browser-driven testing through Playwright MCP
- menu/submenu/page/tab/action coverage by profile
- detection of existing test scenarios, and generation plus execution when there are none
- functional, forms, workflow, API and data-integrity testing
- UX, UI, responsive and accessibility audits
- authorization and broken-access-control checks in authorized environments
- error and resilience testing
- persistent project-local `.qa/` state
- deterministic Stop hook for incomplete active audits
- secret-write protection for `.env*` during QA runs
- E2E regression generation
- traceability matrix generation from the persisted ledger
- automated English-only repository gate
- final report generation only after coverage validation

## Architecture

```text
QA Orchestrator
      │
      ▼
System Discovery
      │
      ▼
Test Inventory ───────────────────────────────┐
      │                                      │
      ├── Profiles                           │
      ├── Navigation                         │
      ├── Features                           │
      ├── Forms                              │
      ├── Workflows                          │
      └── Permissions                        │
      │                                      │
      ▼                                      │
Specialized QA agents                        │
      │                                      │
      ▼                                      │
Persistent results + findings + evidence     │
      │                                      │
      ▼                                      │
Coverage Auditor                             │
      │                                      │
   100% required?                            │
   │          │                              │
   no        yes                             │
   │          │                              │
   └──────────┘                              │
      │                                      │
      ▼                                      │
Final report                                 │
```

## Repository layout

The public repository intentionally keeps agents and skills **visible**:

```text
qasquad/
├── .claude-plugin/
│   └── marketplace.json
├── plugins/
│   └── qa-squad/
│       ├── .claude-plugin/
│       │   └── plugin.json
│       ├── agents/          # 20 QA agents
│       ├── skills/          # 25 QA skills
│       ├── hooks/
│       ├── bin/
│       │   └── qa-cli
│       └── .mcp.json        # Playwright MCP
├── docs/
├── examples/
├── tests/
└── .github/workflows/
```

Claude Code requires plugin `agents/` and `skills/` to live at the plugin root, not inside `.claude-plugin/`.

## Install from GitHub marketplace

Install directly from GitHub:

```text
/plugin marketplace add salexcarvalho/qasquad
/plugin install qa-squad@salexcarvalho-claude-plugins
```

Plugin installs default to user scope, so QA Squad can be available across projects.

## Local development

Clone the repository and load the plugin directly:

```bash
git clone https://github.com/salexcarvalho/qasquad.git
cd qasquad
claude --plugin-dir ./plugins/qa-squad
```

Claude Code also accepts the plugin itself as a ZIP through `--plugin-dir`.

## Start a full audit

Because plugin skills are namespaced, invoke:

```text
/qa-squad:qa-full-audit
```

Example:

```text
/qa-squad:qa-full-audit

Test the application from zero.
Discover every real role and test 100% of applicable menus, submenus,
pages, tabs and actions for every role.
Credentials are available in .env. Never expose secrets.
Audit functionality, workflows, permissions, UX, UI, responsive behavior,
accessibility and error handling.
```

Useful commands:

```text
/qa-squad:qa-start
/qa-squad:qa-status
/qa-squad:qa-discover-system
/qa-squad:qa-test-navigation
/qa-squad:qa-test-functional
/qa-squad:qa-test-forms
/qa-squad:qa-test-workflows
/qa-squad:qa-test-permissions
/qa-squad:qa-test-ux
/qa-squad:qa-test-ui
/qa-squad:qa-test-responsive
/qa-squad:qa-test-accessibility
/qa-squad:qa-test-security
/qa-squad:qa-test-api
/qa-squad:qa-test-resilience
/qa-squad:qa-test-performance
/qa-squad:qa-test-scenarios
/qa-squad:qa-test-data-integrity
/qa-squad:qa-generate-e2e
/qa-squad:qa-gap-analysis
/qa-squad:qa-coverage-matrix
/qa-squad:qa-final-report
```

## Deterministic coverage

QA Squad does not let the model decide subjectively whether “everything” was tested.

A typical coverage state may look like:

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

An empty category reports **0%**, never 100%. An undiscovered category is undiscovered
work, not success. The only way an empty category counts as complete is an explicit,
justified declaration recorded in `.qa/declared-empty.json`:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" declare-empty --category forms --notes "<justification>"
```

Core categories gate completion: `profiles`, `navigation`, `features`, `forms`,
`workflows`, `permissions`, `scenarios`. Tracked categories give every specialist agent a measurable
lane and can be promoted into `required_categories`: `api`, `ux`, `ui`, `responsive`,
`accessibility`, `security`, `performance`, `resilience`, `data-integrity`.

Navigation IDs should include profile context when behavior or visibility differs by role. Testing a settings page as an administrator does not automatically cover the same surface for a manager or standard user.

While `.qa/run-state.json` has `"status": "active"`, the bundled Stop hook checks the coverage ledger. If required coverage is incomplete, it blocks premature completion and returns the missing items to Claude.

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

## Project-local QA state

Agents and skills come from the plugin, while test results stay in the application being audited:

```text
<target-project>/.qa/
├── config.json
├── run-state.json
├── declared-empty.json
├── inventory/
├── results/
├── findings/
├── reports/
└── evidence/
    ├── screenshots/
    ├── traces/
    └── videos/
```

This prevents data from different applications from being mixed.

## QA agents

The plugin includes:

- `qa-orchestrator`
- `qa-system-discovery`
- `qa-scenario-tester`
- `qa-navigation-auditor`
- `qa-functional-tester`
- `qa-form-tester`
- `qa-workflow-tester`
- `qa-profile-permission-tester`
- `qa-data-integrity-tester`
- `qa-ux-auditor`
- `qa-ui-visual-auditor`
- `qa-responsive-auditor`
- `qa-accessibility-auditor`
- `qa-security-authorization-tester`
- `qa-api-tester`
- `qa-error-resilience-tester`
- `qa-performance-auditor`
- `qa-e2e-generator`
- `qa-coverage-auditor`
- `qa-report-writer`

All agents are domain-agnostic. Product-specific business rules belong in the audit context, not in the core agent definitions.

## Security and secrets

QA Squad is intended only for systems you own or are authorized to test.

- `.env` may be read when the user explicitly authorizes using its credentials.
- secrets must never be copied into findings, screenshots or reports.
- QA Squad blocks writes to sensitive `.env*` files during active audits.
- destructive production testing is not assumed to be allowed.
- screenshots, traces and request/response evidence must be sanitized.

See [SECURITY.md](SECURITY.md).

## Validation

Repository checks:

```bash
python3 scripts/validate_package.py     # structure, frontmatter, cross-references
python3 scripts/check_english_only.py   # English-only gate
python3 tests/run_tests.py              # full test suite
```

With Claude Code installed:

```bash
claude plugin validate ./plugins/qa-squad --strict
claude plugin validate . --strict
```

## Traceability matrix

Coverage is only credible if it can be inspected. The matrix is generated from the
persisted ledger, so it cannot overstate what happened:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" matrix --format markdown --out .qa/reports/coverage-matrix.md
```

| Area | Role | Menu | Submenu | Feature | Scenario | Test | Status | Evidence |
|---|---|---|---|---|---|---|---|---|
| navigation | admin | Settings | Users | Users | submenu | `profile:admin\|nav:/settings/users` | NOT TESTED | |

Every inventoried item without a persisted result appears as `NOT TESTED`. Any area that
could not be verified is reported as NOT TESTED or BLOCKED, never silently treated as
covered.

## Documentation

| Document | Contents |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Pipeline, coverage model, design rules |
| [docs/agents.md](docs/agents.md) | Agent catalog and shared contract |
| [docs/skills.md](docs/skills.md) | Skill catalog and agent relationships |
| [docs/installation.md](docs/installation.md) | Install, global install, verification |
| [docs/configuration.md](docs/configuration.md) | `.qa/config.json` reference |
| [docs/usage.md](docs/usage.md) | Commands and reading coverage |
| [docs/qa-workflow.md](docs/qa-workflow.md) | Phases, evidence, severity |
| [docs/extending.md](docs/extending.md) | Adding agents, skills and categories |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Common problems |

## Requirements

- Claude Code with plugin support
- Python 3.9 or newer
- Node.js / `npx` for the bundled Playwright MCP server
- a browser environment supported by Playwright MCP

## Roadmap

Potential next steps:

- richer HTML/JSON reports
- coverage visualization
- reusable optional domain packs
- PR regression mode
- differential audits between releases
- test-case import/export
- CI/headless execution patterns
- additional browser evidence helpers
- automated evidence sanitization checks

## License

MIT. See [LICENSE](LICENSE).
