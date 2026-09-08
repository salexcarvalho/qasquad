#!/usr/bin/env bash
# Install QA Squad at user scope from a local clone of this repository.
set -euo pipefail

if ! command -v claude >/dev/null 2>&1; then
  echo "Claude Code CLI ('claude') was not found in PATH." >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 was not found in PATH; the QA coverage CLI requires it." >&2
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -f "$ROOT/.claude-plugin/marketplace.json" ]; then
  echo "marketplace.json not found; run this script from inside the repository." >&2
  exit 1
fi

echo "Validating the package before installing..."
python3 "$ROOT/scripts/validate_package.py"

claude plugin marketplace add "$ROOT"
claude plugin install qa-squad@salexcarvalho-claude-plugins --scope user

echo
echo "QA Squad installed at user scope. Restart Claude Code or run /reload-plugins."
echo "Start an audit with: /qa-squad:qa-full-audit"
