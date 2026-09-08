# Changelog

All notable changes to this project will be documented here.

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
