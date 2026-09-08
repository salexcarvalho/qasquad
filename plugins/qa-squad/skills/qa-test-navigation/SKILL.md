---
name: qa-test-navigation
description: "Tests navigation IDs: menus, submenus, pages, tabs, modals and actions per role."
context: fork
agent: qa-navigation-auditor
background: false
---

Test the pending navigation items. If `$ARGUMENTS` names IDs, a role or a scope, restrict
yourself to that set; otherwise process every item in `.qa/inventory/navigation.json` that
has no result yet.

$ARGUMENTS

Record one result for every executed ID.
