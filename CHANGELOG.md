# Changelog

All notable changes to this project will be documented here.

## [0.4.0] - 2026-10-02

### Added
- Deterministic, versionable evidence package under `docs/qa/`, generated from the `.qa/`
  ledger: `executions/`, `reports/<requirement_id>/`, `bugs/<bug_id>/`,
  `evidence/<execution_id>/<scenario_id>/`, and `summary/<execution_id>/`. `docs/qa/`
  coexists with `.qa/reports/`: the ledger is operational, the package is published.
- New `qa-cli` commands: `execution-start`, `execution-finish`, `requirement-report`,
  `bug-report`, `retest`, `bugs-list`, `final-report`.
- Automatic sanitization of secrets in text evidence copied into `docs/qa/evidence/`.
- A deterministic acceptance outcome per requirement: `ACCEPTED`, `NOT_ACCEPTED`, `BLOCKED`
  or `INCOMPLETE`. Only a bug classified as `PRODUCT_DEFECT` can move a requirement to
  `NOT_ACCEPTED`; every other failure cause leaves it `BLOCKED` until confirmed.
- Failure-cause classification before a failing scenario is promoted to a bug report:
  `PRODUCT_DEFECT`, `TEST_AUTOMATION_FAILURE`, `ENVIRONMENT_FAILURE`, `TEST_DATA_FAILURE`,
  `BLOCKED`, `UNDETERMINED`. `qa-scenario-tester` separates the observed fact from any
  technical hypothesis and never presents the hypothesis as a confirmed cause.
- Optional `metadata.requirement_id` on `scenarios` inventory items, evidence-based only;
  when absent, downstream reports show `NOT_AVAILABLE` rather than a guess.
- `qa-bugs` and `qa-retest` skills: list recorded bugs and re-execute the scenario behind a
  bug, appending to its retest history without erasing prior attempts. No new agent was
  added; `qa-retest` reuses `qa-scenario-tester`.

### Changed
- `qa-report-writer` now publishes `docs/qa/` as part of its own procedure (`execution-start`
  / `execution-finish`, `requirement-report` per distinct requirement, `final-report`).
- `qa-final-report` accepts an optional `requirement_id` scope to publish or regenerate a
  single requirement's acceptance report.

## [0.3.0] - 2026-09-24

### Added
- Test scenario detection. `qa-cli scenario-scan` finds the scenarios a project already has
  (Gherkin, browser E2E specs, automated suites, test-plan documents) and `--import` adds them
  to the new core category `scenarios`. `qa-cli scenario-list` publishes them with steps and
  status.
- `qa-scenario-tester` agent and `/qa-squad:qa-test-scenarios` skill: execute existing
  scenarios, or generate scenarios from the inventory and execute them when there are none.
- `scenarios` cannot be declared empty, and `validate` fails until the scan has run.
- `qa-cli record` warns when the ID is not in the inventory, since that result can never count.

### Fixed
- **Critical**: `/qa-squad:qa-full-audit` forked into `qa-orchestrator`. Subagents cannot
  start subagents, so the orchestrator could not delegate to any specialist. The skill now
  runs in the main conversation, and the package validator rejects forking into an agent
  that delegates.
- The secrets hook missed `NotebookEdit` and shell writes (`>`, `tee`, `sed -i`, `cp`, `mv`)
  to `.env` files.

## [0.2.0] - 2026-09-07

### Fixed
- **Critical**: an empty inventory reported 100% coverage, which let an audit that
  discovered and tested nothing close as COMPLETE. Empty categories now report 0% and block
  closure until they are inventoried or explicitly declared empty with a justification.
- Every agent and skill referenced a non-existent `qa_cli.py`, or invoked a bare `qa-cli`
  that is not on `PATH`. All references now use
  `python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli"`.
- `blocked` results silently accepted no justification, hiding why execution failed.
- The project-context template existed in two divergent copies; consolidated into one.

### Added
- `qa-cli declare-empty`: explicit, auditable declaration that a category has no applicable
  items, stored in `.qa/declared-empty.json` and retired automatically when an item is added.
- `qa-cli matrix`: traceability matrix generation, resolving menu and submenu ancestry, in
  Markdown or JSON.
- `qa-coverage-matrix` skill.
- Nine tracked coverage categories so every specialized agent has a measurable lane: `api`,
  `ux`, `ui`, `responsive`, `accessibility`, `security`, `performance`, `resilience`,
  `data-integrity`.
- Canonical `critical|high|medium|low` severity scale, with `P0`-`P3` kept as aliases.
- `scripts/check_english_only.py`: automated English-only gate with a maintainable
  lexicon-and-morphology strategy and an allowlist, wired into CI.
- Full documentation set under `docs/`.
- Expanded test suite: 28 tests covering the CLI, both hooks and the language gate.

### Changed
- All 19 agents and 24 skills rewritten in English with a consistent structure of Role,
  Inputs, Procedure, Outputs and Escalation.
- `scripts/validate_package.py` now derives counts from the filesystem and validates
  agent/skill cross-references, frontmatter, hook registration and documented counts.
- The Stop hook now reports in English, fails open on internal errors with a diagnostic on
  stderr, and has an execution timeout.

## [0.1.0] - 2026-09-07

### Added
- Generic multi-agent QA squad for Claude Code.
- 19 specialized QA agents.
- 23 reusable QA skills.
- Playwright MCP browser integration.
- Deterministic project-local coverage ledger.
- Stop hook that blocks premature completion of active audits.
- Secret-write protection during active QA runs.
- Marketplace-ready Claude Code plugin packaging.
