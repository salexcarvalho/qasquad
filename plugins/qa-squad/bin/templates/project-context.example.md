# QA project context

Fill this in only when you want to guide the audit with domain knowledge without
hard-coding that knowledge into the generic agents. Copy it to `.qa/project-context.md`
inside the application being tested.

## Goal

For example: audit the whole system from scratch, including 100% of menus and submenus for
every role.

## Environment

- QA/staging URL:
- Is the environment disposable? yes/no
- Credentials: state only where they are stored. Never copy secrets into this file.

## Expected roles

Optional. Discovery must confirm the real roles against the system and the code.

## Relevant domain rules

- ...

## Constraints

- do not send real emails;
- do not run real payments;
- do not delete production data;
- ...

## Additional success criteria

- ...
