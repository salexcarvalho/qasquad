---
name: qa-test-api
description: "Audits the contracts and behavior of the relevant APIs."
context: fork
agent: qa-api-tester
background: false
---

Audit the APIs in the scope `$ARGUMENTS`, sanitizing secrets. If formal API coverage is
required, maintain the `api` inventory and results and promote the category into
`required_categories`.
