---
name: qa-coverage-matrix
description: "Generates the final traceability matrix of area, role, menu, submenu, feature, scenario, test, status and evidence."
---

Generate the matrix from the persisted ledger:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" matrix --format markdown --out .qa/reports/coverage-matrix.md
```

The matrix is derived from the inventory and the recorded results, so it cannot overstate
coverage. Every inventoried item with no persisted result appears as `NOT TESTED`, and every
category with no items appears as `NOT TESTED` or `DECLARED EMPTY`.

Use it to answer "what was actually tested" and to make missing coverage immediately visible.
Scope: `$ARGUMENTS`
