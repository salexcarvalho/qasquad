---
name: qa-test-resilience
description: "Tests recovery from network, API, session and concurrency errors."
context: fork
agent: qa-error-resilience-tester
background: false
---

Run safe resilience scenarios for `$ARGUMENTS` without causing an outage in a shared
environment.
