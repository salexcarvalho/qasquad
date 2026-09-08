# Security Policy

QA Squad is designed to inspect applications in environments the user is authorized to test.

## Secrets

- Never commit `.env` files, passwords, API keys, tokens, session cookies, or private certificates.
- Findings and screenshots must be sanitized before publication.
- The bundled QA safety hook blocks writes to secret `.env*` files while an audit is active.

## Responsible testing

Only run security and authorization checks against systems you own or are explicitly authorized to assess. Avoid destructive tests in production unless the environment and scope explicitly permit them.

## Reporting vulnerabilities

Please report vulnerabilities privately to the repository maintainer before opening a public issue when disclosure could expose users or credentials.
