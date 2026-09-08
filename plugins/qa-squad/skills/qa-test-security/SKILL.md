---
name: qa-test-security
description: "Runs authorized application security and broken-access-control tests."
context: fork
agent: qa-security-authorization-tester
background: false
---

Test application security within the authorized scope: `$ARGUMENTS`. Prioritize authorization
and isolation. Never run destructive actions, and never test outside the authorized
environment.
