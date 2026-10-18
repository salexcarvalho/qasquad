---
name: qa-start
description: "Initializes or resumes a persistent QA audit in this repository."
disable-model-invocation: true
---

Initialize the generic audit:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" init --goal "QA audit"
```

Then read `.qa/config.json` and `.qa/project-context.md` if it exists. Report the initial
state and recommend `/qa-squad:qa-full-audit` for a complete run.

Runs can be scoped to one user story, feature, spec or epic with `--story`, `--feature`,
`--spec`, `--epic` or `--scope` on `/qa-squad:qa-full-audit` and on the `qa-test-*` skills.
Every run ends with an evidence report (and a failure report when there are failures)
published as Artifacts; add `--no-artifact` to opt out.
