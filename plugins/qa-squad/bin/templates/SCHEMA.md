# Inventory and result schema

## Inventory

Each `.qa/inventory/<category>.json` may be a plain list, or an object:

```json
{
  "category": "navigation",
  "items": [
    {
      "id": "profile:admin|nav:/users|kind:menu",
      "kind": "menu",
      "label": "Users",
      "profile_id": "admin",
      "route": "/users",
      "parent_id": null,
      "metadata": {}
    }
  ]
}
```

IDs must be stable and unique. `parent_id` links a submenu to its menu and is what allows
the traceability matrix to resolve the menu and submenu columns.

### Core categories

These gate audit completion by default:

- `profiles`
- `navigation`
- `features`
- `forms`
- `workflows`
- `permissions`
- `scenarios` (cannot be declared empty)

### Tracked categories

These give every specialized agent a measurable lane. They are reported by default and can
be promoted into `required_categories` in `.qa/config.json` when the audit must formally
gate on them:

- `api`
- `ux`
- `ui`
- `responsive`
- `accessibility`
- `security`
- `performance`
- `resilience`
- `data-integrity`

### Navigation

When the audit requires coverage per role, **do not deduplicate by route**. The same route
seen by two roles produces two items.

Suggested kinds: `menu`, `submenu`, `page`, `tab`, `subtab`, `modal`, `action`, `shortcut`,
`deep-link`.

### Scenarios

`scenarios` holds test scenarios. `qa-cli scenario-scan --import` fills it with the ones the
project already has; `qa-scenario-tester` adds generated ones when there are none.

```json
{
  "id": "scenario:generated:features:checkout:happy-path",
  "kind": "generated",
  "label": "Customer pays an order with a saved card",
  "profile_id": "customer",
  "metadata": {
    "origin": "generated",
    "covers": ["features:checkout", "workflows:order"],
    "preconditions": "customer with one saved card and one item in the cart",
    "steps": ["Open the cart", "Choose the saved card", "Confirm the payment"],
    "expected": "The order appears as paid in My orders"
  }
}
```

`kind` is `gherkin`, `e2e`, `suite`, `documented` or `generated`. Imported items carry
`metadata.origin = "existing"` and `metadata.source` with the file they came from. The last
scan is kept in `.qa/scenario-scan.json`.

## Results

Results live in `.qa/results/<category>/*.json` and carry the original ID.

Statuses:

- `passed`: executed with no relevant divergence;
- `failed`: executed and the behavior was wrong;
- `blocked`: execution could not be completed; a justification is required;
- `not_applicable`: the item does not apply in this context; a justification is required.

All four count as executed coverage. This keeps coverage separate from quality: a failing
item is still a tested item.

## Empty categories

An empty category is **not** treated as complete. It reports 0% and blocks closure until
either items are inventoried, or the emptiness is explicitly declared:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" declare-empty --category forms --notes "<justification>"
```

Declarations are stored in `.qa/declared-empty.json` and are retired automatically if an
item is later added to that category. This is what prevents a zero-discovery audit from
reporting a false 100%.

## Findings

`.qa/findings/<ID>.json` records severity, reproduction, actual result, expected result,
impact, recommendation and evidence.

Severity is `critical`, `high`, `medium` or `low`. The `P0` to `P3` scale is accepted as an
alias and stored alongside as `severity_code`.

## Evidence

Use paths under:

```text
.qa/evidence/screenshots/
.qa/evidence/traces/
.qa/evidence/videos/
```

Never store secrets in evidence.
