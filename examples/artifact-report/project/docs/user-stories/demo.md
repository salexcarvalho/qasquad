---
epic: DEMO
title: Account access
---

# Account access

### US-DEMO-01 - Sign in with e-mail and password
**Persona:** member · **Priority:** Must

As a member, I want to sign in with my e-mail and password so that I can reach my area.

**Acceptance criteria**
```gherkin
Scenario: Valid sign in
  Given an active member with a correct password
  When the member submits the sign-in form
  Then the member lands on the home page
  And the session cookie is set

Scenario: Wrong password
  Given an active member
  When the member submits a wrong password
  Then the form shows "Invalid credentials"
```

### US-DEMO-02 - Reset a forgotten password
**Persona:** member · **Priority:** Should

As a member, I want to reset my password by e-mail so that I can recover access.

**Acceptance criteria**
```gherkin
Scenario: Request a reset link
  Given a registered e-mail address
  When the member asks for a reset link
  Then a confirmation is shown without revealing whether the address exists
```
