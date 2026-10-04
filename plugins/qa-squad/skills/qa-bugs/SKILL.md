---
name: qa-bugs
description: "Lists the bugs recorded under docs/qa/bugs, with status and classification."
argument-hint: "[--status open|retested] [--classification PRODUCT_DEFECT|TEST_AUTOMATION_FAILURE|ENVIRONMENT_FAILURE|TEST_DATA_FAILURE|BLOCKED|UNDETERMINED]"
---

Run, passing through whatever filters were given:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa-cli" bugs-list $ARGUMENTS
```

Present the result as a compact table (id, scenario, classification, status, severity). A bug only ever moved a requirement to `NOT_ACCEPTED` when its
classification is `PRODUCT_DEFECT`; every other classification leaves the requirement
`BLOCKED` until it is confirmed one way or the other. Never reclassify a bug yourself; report
what is persisted under `docs/qa/bugs/`.
