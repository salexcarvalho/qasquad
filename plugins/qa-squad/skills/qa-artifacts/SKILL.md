---
name: qa-artifacts
description: "Generates and publishes the evidence and failure Artifacts of a finished QA execution, for one scope."
argument-hint: "[--execution ID] [--scope ID] [--category NAME] [--no-artifact]"
---

Generate the evidence report and, only when there is a failure or a finding, the failure
report of a finished execution, and publish them as Artifacts. Use it to re-publish after a
bug report or a retest, to report on one story of an epic, or when a run ended without them.

Arguments: $ARGUMENTS

1. Pick the execution: `--execution <id>`, or the latest finished one. A run that was not
   closed yet needs `qa-cli execution-start` and `qa-cli execution-finish --execution <id>`
   first; the generator reads the `manifest.json` that `execution-finish` writes.
2. Generate. `--scope current` is the scope the execution ran with; `--scope <ID>` selects a
   story, feature, spec or epic that is part of it (a story's report never lists another
   story's items); `--category <name>` limits the report to one coverage lane:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa_artifact_report.py" --execution <id|latest> --scope current \
     --artifact --out-dir "<scratchpad>/qa-artifacts" --json
   ```

   Use the session scratchpad directory from your system prompt as `--out-dir`; omit the flag
   when there is none (the default is `.qa/artifacts/<execution>/`). Pass `--no-artifact` when
   `$ARGUMENTS` has it: standalone HTML is written into `docs/qa/executions/<id>/scope-<id>/`
   and nothing is published. `--lang pt-BR` renders the pages in Portuguese; the default comes
   from `artifacts.language` in `.qa/config.json` or `QA_SQUAD_REPORT_LANG`.
3. Call the Artifact tool once per entry of `publish` in the printed JSON, with its
   `file_path`, `icon` and `description` exactly as listed. Republish the same `file_path` to
   update an existing artifact. When the plan has no failure entry, say the scope has no
   failures; never write a failure report by hand.
4. Give the user every Artifact link, the verdict, and the counts from the JSON.

`python3 "${CLAUDE_PLUGIN_ROOT}/bin/qa_artifact_report.py" --settings` prints whether
publishing is on and why. Every page stays under 12 MB: when the evidence is larger the
generator reduces images and logs in levels and lists what it left out.
