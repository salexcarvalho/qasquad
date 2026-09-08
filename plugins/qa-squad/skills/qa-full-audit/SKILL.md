---
name: qa-full-audit
description: "Runs a complete, generic, traceable QA audit driven towards the configured coverage target."
context: fork
agent: qa-orchestrator
background: false
disable-model-invocation: true
---

Run the complete QA audit of the current project.

Additional requirements supplied by the user:

$ARGUMENTS

If `.qa/run-state.json` does not exist, initialize it:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" init --goal "Full generic QA audit"
```

Follow the QA Orchestrator workflow end to end: discovery, inventory, specialized testing,
coverage, gap analysis, E2E generation and reporting. Do not declare completion while
`python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" validate` fails.

If the user requires 100% of menus and submenus per role, make sure the navigation inventory
represents the role x navigable-item combination and execute every applicable combination.
