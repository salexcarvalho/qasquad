---
name: qa-test-data-integrity
description: "Looks for data inconsistencies and divergences between views and relationships."
context: fork
agent: qa-data-integrity-tester
background: false
---

Audit data integrity within the scope `$ARGUMENTS`. Link every finding to its evidence and to
the affected features and workflows.
