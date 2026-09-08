---
name: qa-test-workflows
description: "Runs end-to-end journeys and state machines."
context: fork
agent: qa-workflow-tester
background: false
---

Test the pending workflows, or `$ARGUMENTS`. Include the normal path, invalid transitions and
handoffs between roles where applicable. Record a result per ID.
