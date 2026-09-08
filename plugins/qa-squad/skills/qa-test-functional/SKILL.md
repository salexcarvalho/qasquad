---
name: qa-test-functional
description: "Tests inventoried functional features and CRUD surfaces."
context: fork
agent: qa-functional-tester
background: false
---

Test the pending features, or the scope given in `$ARGUMENTS`. Record a result per ID and a
finding whenever behavior diverges from the expectation. Cover happy path, alternative path,
negative path and boundary conditions rather than only confirming the page loads.
