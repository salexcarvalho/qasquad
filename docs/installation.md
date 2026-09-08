# Installation

## Requirements

- Claude Code with plugin support
- Python 3.9 or newer
- Node.js with `npx`, for the bundled Playwright MCP server
- a browser environment supported by Playwright MCP

## Install from the GitHub marketplace

```text
/plugin marketplace add salexcarvalho/qasquad
/plugin install qa-squad@salexcarvalho-claude-plugins
```

Plugin installs default to user scope, so QA Squad becomes available across projects.

## Global installation (user scope)

From a clone of the repository:

```bash
./install-local-global.sh
```

The script verifies that the `claude` CLI is present, registers the local directory as a
marketplace and installs the plugin at user scope. Restart Claude Code, or run
`/reload-plugins`, afterwards.

## Local development

```bash
git clone https://github.com/salexcarvalho/qasquad.git
cd qasquad
claude --plugin-dir ./plugins/qa-squad
```

Claude Code also accepts the plugin as a ZIP through `--plugin-dir`.

## Verifying the installation

```bash
python3 scripts/validate_package.py
python3 scripts/check_english_only.py
python3 tests/run_tests.py
```

With the Claude Code CLI available:

```bash
claude plugin validate ./plugins/qa-squad --strict
claude plugin validate . --strict
```

## Calling the CLI

The CLI ships inside the plugin and is deliberately **not** added to `PATH`. Agents and
skills call it as:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" status
```

If you want it on your own shell `PATH`, add an alias rather than copying the file, so it
stays in sync with the installed plugin:

```bash
alias qa-cli='python3 "$HOME/.claude/plugins/qa-squad/bin/qa-cli"'
```

Adjust the path to match where your Claude Code installation stores plugins.
