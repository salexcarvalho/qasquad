---
name: qa-test-performance
description: "Audits perceptible and technical bottlenecks without aggressive load testing."
context: fork
agent: qa-performance-auditor
background: false
---

Audit the performance of `$ARGUMENTS` with measurements and traces where possible. Do not run
heavy load without authorization.
