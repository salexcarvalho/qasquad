#!/usr/bin/env python3
"""Structural validation of the QA Squad plugin package.

Checks that the package is internally consistent: valid JSON, well-formed frontmatter,
unique names, valid cross-references between agents and skills, and documentation counts
that match reality. Counts are derived from the filesystem rather than hard-coded, so the
validator cannot drift out of date on its own.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "qa-squad"

errors: list[str] = []
warnings: list[str] = []


def parse_frontmatter(text: str) -> dict | None:
    """Parse the small subset of YAML frontmatter this package uses."""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    block = text[4:end]
    data: dict = {}
    current_list_key: str | None = None
    for raw in block.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw.startswith(("  - ", "- ")) and current_list_key:
            data[current_list_key].append(raw.split("- ", 1)[1].strip())
            continue
        if ":" not in raw:
            continue
        key, _, value = raw.partition(":")
        key = key.strip()
        value = value.strip()
        if value == "":
            data[key] = []
            current_list_key = key
        else:
            data[key] = value.strip('"').strip("'")
            current_list_key = None
    return data


# ---------------------------------------------------------------- JSON validity
for p in [
    ROOT / ".claude-plugin" / "marketplace.json",
    PLUGIN / ".claude-plugin" / "plugin.json",
    PLUGIN / ".mcp.json",
    PLUGIN / "hooks" / "hooks.json",
]:
    try:
        json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        errors.append(f"Invalid JSON {p.relative_to(ROOT)}: {e}")

# -------------------------------------------------------------------- inventory
agent_paths = sorted((PLUGIN / "agents").glob("*.md"))
skill_paths = sorted((PLUGIN / "skills").glob("*/SKILL.md"))

if not agent_paths:
    errors.append("No agents found")
if not skill_paths:
    errors.append("No skills found")

agents: dict[str, dict] = {}
for p in agent_paths:
    text = p.read_text(encoding="utf-8")
    fm = parse_frontmatter(text)
    if fm is None:
        errors.append(f"Missing or malformed YAML frontmatter in agents/{p.name}")
        continue
    if "mcpServers:" in text:
        errors.append(f"Unsupported plugin-agent field mcpServers in agents/{p.name}")
    name = fm.get("name")
    if not name:
        errors.append(f"Missing 'name' in agents/{p.name}")
        continue
    if name != p.stem:
        errors.append(f"Agent name '{name}' does not match filename agents/{p.name}")
    if name in agents:
        errors.append(f"Duplicate agent name '{name}'")
    if not fm.get("description"):
        errors.append(f"Missing 'description' in agents/{p.name}")
    agents[name] = fm

    body = text[text.find("\n---", 4) + 4:]
    for section in ["## Operating principles", "## Escalation"]:
        if section not in body:
            errors.append(f"agents/{p.name} is missing the required section '{section}'")
    # The CLI lives inside the plugin and is not on PATH. A bare `qa-cli ...`
    # instruction would fail at runtime, and `qa_cli.py` does not exist at all.
    if re.search(r"\bqa_cli\.py\b", body):
        errors.append(f"agents/{p.name} references the non-existent 'qa_cli.py'")
    for m in re.finditer(r"^\s*(?:\$ )?qa-cli\s", body, re.MULTILINE):
        errors.append(
            f"agents/{p.name} invokes bare 'qa-cli'; use "
            f'python3 "${{CLAUDE_PLUGIN_ROOT}}/bin/qa-cli\''
        )
        break

skills: dict[str, dict] = {}
for p in skill_paths:
    rel = p.relative_to(PLUGIN)
    text = p.read_text(encoding="utf-8")
    fm = parse_frontmatter(text)
    if fm is None:
        errors.append(f"Missing or malformed YAML frontmatter in {rel}")
        continue
    name = fm.get("name")
    if not name:
        errors.append(f"Missing 'name' in {rel}")
        continue
    if name != p.parent.name:
        errors.append(f"Skill name '{name}' does not match directory '{p.parent.name}'")
    if name in skills:
        errors.append(f"Duplicate skill name '{name}'")
    if not fm.get("description"):
        errors.append(f"Missing 'description' in {rel}")
    skills[name] = fm

    body = text[text.find("\n---", 4) + 4:]
    if re.search(r"\bqa_cli\.py\b", body):
        errors.append(f"{rel} references the non-existent 'qa_cli.py'")
    for m in re.finditer(r"^\s*(?:\$ )?qa-cli\s", body, re.MULTILINE):
        errors.append(
            f"{rel} invokes bare 'qa-cli'; use "
            f'python3 "${{CLAUDE_PLUGIN_ROOT}}/bin/qa-cli\''
        )
        break

# ------------------------------------------------------------ cross-references
# Agents that delegate to other agents. Subagents cannot start subagents, so these
# must run on the main thread and must never be the target of a forked skill.
MAIN_THREAD_AGENTS = {"qa-orchestrator"}

for skill_name, fm in skills.items():
    ref = fm.get("agent")
    if ref and ref not in agents:
        errors.append(f"Skill '{skill_name}' references unknown agent '{ref}'")
    if ref in MAIN_THREAD_AGENTS:
        errors.append(
            f"Skill '{skill_name}' forks into '{ref}', which delegates to other agents; "
            "subagents cannot start subagents, so it must run on the main thread"
        )
    if ref and fm.get("context") != "fork":
        warnings.append(f"Skill '{skill_name}' delegates to an agent without 'context: fork'")

for agent_name, fm in agents.items():
    for ref in fm.get("skills", []) or []:
        if ref not in skills:
            errors.append(f"Agent '{agent_name}' references unknown skill '{ref}'")

referenced_agents = {fm.get("agent") for fm in skills.values() if fm.get("agent")}
for agent_name in agents:
    if agent_name not in referenced_agents and agent_name not in MAIN_THREAD_AGENTS:
        warnings.append(f"Agent '{agent_name}' is not reachable from any skill")

# --------------------------------------------------------------- CLI and hooks
cli = PLUGIN / "bin" / "qa-cli"
if not cli.exists():
    errors.append("Missing plugins/qa-squad/bin/qa-cli")
elif not cli.stat().st_mode & 0o111:
    errors.append("plugins/qa-squad/bin/qa-cli is not executable")

for hook in ["validate-qa-coverage.py", "protect-secrets.py"]:
    hp = PLUGIN / "hooks" / hook
    if not hp.exists():
        errors.append(f"Missing hook {hook}")

try:
    hooks_cfg = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    declared = json.dumps(hooks_cfg)
    for hook in ["validate-qa-coverage.py", "protect-secrets.py"]:
        if hook not in declared:
            errors.append(f"Hook {hook} exists but is not registered in hooks.json")
except (json.JSONDecodeError, OSError):
    pass  # already reported above

# --------------------------------------------------- documented counts are true
n_agents, n_skills = len(agents), len(skills)
for doc in [ROOT / "README.md", ROOT / "MANIFEST.md", PLUGIN / "README.md"]:
    if not doc.exists():
        continue
    text = doc.read_text(encoding="utf-8")
    for count, noun in [(n_agents, "agent"), (n_skills, "skill")]:
        claimed = re.findall(rf"(\d+)\s+(?:specialized\s+|generic\s+|reusable\s+)?QA\s+{noun}s", text)
        claimed += re.findall(rf"{noun.capitalize()}s:\s*(\d+)", text)
        claimed += re.findall(rf"`{noun}s/`\s*[^\n]*?(\d+)", text)
        for c in claimed:
            if int(c) != count:
                errors.append(
                    f"{doc.relative_to(ROOT)} claims {c} {noun}s but the package contains {count}"
                )

# ------------------------------------------------------------------------ output
if warnings:
    print("PACKAGE VALIDATION WARNINGS")
    for w in warnings:
        print("-", w)
    print()

if errors:
    print("PACKAGE VALIDATION FAILED")
    for e in errors:
        print("-", e)
    sys.exit(1)

print(f"PACKAGE VALIDATION PASS: {n_agents} agents, {n_skills} skills, "
      f"{len(referenced_agents)} agent-backed skills")
