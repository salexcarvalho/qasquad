---
name: qa-record-finding
description: "Required pattern for recording a traceable QA finding."
---

When recording a problem, prefer:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" finding \
  --title "<short title>" \
  --severity <critical|high|medium|low> \
  --category "<category>" \
  --location "<route or module>" \
  --actual "<actual behavior>" \
  --expected "<expected behavior>" \
  --reproduction "<steps>" \
  --impact "<impact>" \
  --recommendation "<recommendation>" \
  --evidence "<evidence path>"
```

Severity scale:

| Severity | Meaning |
|---|---|
| critical | System unavailable, severe security issue, data loss, or an essential workflow completely blocked. |
| high | A major feature is broken, with significant business impact. |
| medium | A feature is partially broken or an important inconsistency exists, with a workaround available. |
| low | A minor functional, visual, usability or consistency problem. |

`P0` to `P3` remain accepted as aliases for backward compatibility.

If no screenshot exists, include other concrete evidence. Never include secrets.
