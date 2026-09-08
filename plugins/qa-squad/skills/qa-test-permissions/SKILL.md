---
name: qa-test-permissions
description: "Validates roles and permissions on the UI and the backend, including direct access and multi-role users."
context: fork
agent: qa-profile-permission-tester
background: false
---

Test the pending permissions and roles, or `$ARGUMENTS`. Never accept a hidden button as
authorization. Record every `permissions` ID and every applicable `profiles` ID.
