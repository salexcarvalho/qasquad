# Configuration

Configuration lives in the audited project, at `.qa/config.json`. It is created by
`qa-cli init`.

```json
{
  "required_coverage_percent": 100,
  "required_categories": ["profiles", "navigation", "features", "forms", "workflows", "permissions"],
  "tracked_categories": ["api", "ux", "ui", "responsive", "accessibility", "security", "performance", "resilience", "data-integrity"],
  "strict_navigation_by_profile": true,
  "required_viewports": ["desktop", "mobile"],
  "allowed_result_statuses": ["blocked", "failed", "not_applicable", "passed"],
  "severity_scale": ["critical", "high", "medium", "low"]
}
```

| Key | Meaning |
|---|---|
| `required_coverage_percent` | Threshold each required category must reach before the audit can close. |
| `required_categories` | Categories that gate completion. |
| `tracked_categories` | Categories reported but not gating. Promote one into `required_categories` to gate on it. |
| `strict_navigation_by_profile` | When true, the same route seen by two roles is two distinct items. |
| `required_viewports` | Viewports the responsive audit must cover. |
| `allowed_result_statuses` | The statuses that count as executed coverage. |
| `severity_scale` | Canonical severity names. |

## Gating on a tracked category

To make an audit formally gate on, for example, security and accessibility, move them into
`required_categories`:

```json
"required_categories": ["profiles", "navigation", "features", "forms", "workflows", "permissions", "security", "accessibility"]
```

Those categories must then be inventoried and executed, or explicitly declared empty.

## Project context

`.qa/project-context.md` carries domain knowledge without contaminating the generic agents.
A template is materialized by `qa-cli init`, and a copy lives at
`examples/project-context.example.md`.

## Project-local state

```text
<target-project>/.qa/
|-- config.json
|-- run-state.json
|-- declared-empty.json
|-- inventory/
|-- results/
|-- findings/
|-- reports/
`-- evidence/
    |-- screenshots/
    |-- traces/
    `-- videos/
```

Agents and skills come from the plugin; test results stay in the application being audited.
This prevents data from different applications from being mixed.
