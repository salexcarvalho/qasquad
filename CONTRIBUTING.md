# Contributing

Contributions are welcome.

## Principles

1. Keep agents domain-agnostic. Product-specific rules belong in `.qa/project-context.md`.
2. Put reusable procedures in skills rather than duplicating instructions across agents.
3. Preserve deterministic coverage accounting. Never make an unmeasured thing look measured,
   and never let an empty category read as success.
4. Never weaken secret-handling rules.
5. Add or update tests for CLI and hook behavior when changing coverage logic.
6. Write everything in English. The repository enforces this automatically.

## Local validation

```bash
python3 scripts/validate_package.py     # structure, frontmatter, cross-references
python3 scripts/check_english_only.py   # English-only gate
python3 tests/run_tests.py              # full test suite
```

With the Claude Code CLI available:

```bash
claude plugin validate ./plugins/qa-squad --strict
claude plugin validate . --strict
```

## Adding agents and skills

See [docs/extending.md](docs/extending.md). In short: agents get a single responsibility, the
verbatim shared **Operating principles** and **Running the CLI** sections, and explicit
Inputs, Procedure, Outputs and Escalation sections. Skills are thin scoped entry points that
pass `$ARGUMENTS` through.

`scripts/validate_package.py` will reject an agent referencing an unknown skill, a skill
referencing an unknown agent, a bare `qa-cli` invocation, or a documented count that no
longer matches the package.

## Pull requests

Describe the problem, the behavior change, and how it was validated. Keep domain-specific
test packs outside the generic core unless they are clearly optional extensions.
