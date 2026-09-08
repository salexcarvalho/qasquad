---
name: qa-discover-system
description: "Discovers the testable universe and builds the inventories of roles, navigation, features, forms, workflows and permissions."
context: fork
agent: qa-system-discovery
background: false
---

Run a complete discovery pass over the project and update `.qa/inventory/`.

Additional context:
$ARGUMENTS

Mark discovery complete only after both a static and a dynamic validation pass have been
performed. If a category genuinely has no applicable items, declare it empty with a
justification instead of leaving it silently empty.
