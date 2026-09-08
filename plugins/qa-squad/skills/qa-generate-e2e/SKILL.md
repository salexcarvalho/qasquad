---
name: qa-generate-e2e
description: "Generates end-to-end regression tests for critical flows that are already understood."
context: fork
agent: qa-e2e-generator
background: false
disable-model-invocation: true
---

Generate or update E2E tests for `$ARGUMENTS`, prioritizing critical regressions and
essential flows. Never change the product to mask a failure.
