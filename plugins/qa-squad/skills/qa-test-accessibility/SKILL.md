---
name: qa-test-accessibility
description: "Runs a practical accessibility audit."
context: fork
agent: qa-accessibility-auditor
background: false
---

Audit keyboard access, focus, labels, semantics, contrast and messages within the scope
`$ARGUMENTS`. Record both the limitations and the findings.
