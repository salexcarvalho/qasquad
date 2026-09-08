---
name: qa-status
description: "Shows the current coverage and state of the QA audit."
---

Run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" status
```

Present the result compactly, highlighting every category below the target, any category
marked EMPTY - NOT DISCOVERED, and the number of findings per severity.
