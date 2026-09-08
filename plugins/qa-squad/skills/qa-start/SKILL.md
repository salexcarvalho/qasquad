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
