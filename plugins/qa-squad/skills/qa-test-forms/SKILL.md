---
name: qa-test-forms
description: "Runs the generic validation matrix against the inventoried forms."
context: fork
agent: qa-form-tester
background: false
---

Test the pending forms, or the scope given in `$ARGUMENTS`, including happy path, boundary
values, invalid input, duplicates and error recovery. Record every ID.
