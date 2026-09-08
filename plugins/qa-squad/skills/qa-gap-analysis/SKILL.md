---
name: qa-gap-analysis
description: "Identifies discovered items that have not been executed yet, and false 100% coverage."
context: fork
agent: qa-coverage-auditor
background: false
---

Run an independent audit of the current coverage and return the IDs and areas that have not
been tested yet. Also verify whether the denominator itself looks incomplete.

$ARGUMENTS
