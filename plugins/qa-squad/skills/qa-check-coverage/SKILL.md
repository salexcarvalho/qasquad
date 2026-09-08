---
name: qa-check-coverage
description: "Queries and validates the persisted coverage of the QA audit."
---

Run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" status
```

For strict validation:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" validate
```

Never round incomplete coverage up to 100%. A category showing `EMPTY - NOT DISCOVERED` is
undiscovered work, not a passing category.
