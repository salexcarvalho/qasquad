# Extending the squad

## Adding a new agent

1. Create `plugins/qa-squad/agents/<name>.md`.
2. Use the standard frontmatter:

```yaml
---
name: qa-my-agent
description: "One sentence describing the single responsibility."
model: inherit
effort: high
skills:
  - qa-record-finding
  - qa-check-coverage
---
```

3. Copy the **Operating principles** and **Running the CLI** sections verbatim from any
   existing agent. They must stay identical across agents; drift between them is a defect.
4. Add **Role**, **Inputs**, **Procedure**, **Outputs** and **Escalation** sections.
5. Keep the agent domain-agnostic. A rule that mentions a specific product belongs in
   `.qa/project-context.md`, not in an agent.
6. Give the agent a coverage category so its work is measurable, and document it in
   `docs/agents.md`.

## Adding a new skill

1. Create `plugins/qa-squad/skills/<name>/SKILL.md`.
2. For a skill that delegates to an agent:

```yaml
---
name: qa-test-something
description: "One sentence."
context: fork
agent: qa-my-agent
background: false
---
```

3. Pass `$ARGUMENTS` through as the scope.
4. Document it in `docs/skills.md`.

## Adding a coverage category

1. Add the slug to `EXTENDED_CATEGORIES` in `plugins/qa-squad/bin/qa-cli`.
2. Document it in `plugins/qa-squad/bin/templates/SCHEMA.md` and `docs/configuration.md`.
3. Promote it into `required_categories` per project when the audit must gate on it.

## Validation before committing

```bash
python3 scripts/validate_package.py
python3 scripts/check_english_only.py
python3 tests/run_tests.py
```

`validate_package.py` checks structure, frontmatter, agent and skill cross-references, and
that the counts claimed in `README.md` and `MANIFEST.md` match reality.
`check_english_only.py` fails the build if Portuguese content is reintroduced.

## Design rules

1. Keep agents domain-agnostic.
2. Put reusable procedures in skills rather than duplicating instructions across agents.
3. Preserve deterministic coverage accounting. Never make an unmeasured thing look measured.
4. Never weaken secret-handling rules.
5. Add or update tests when changing coverage logic.
