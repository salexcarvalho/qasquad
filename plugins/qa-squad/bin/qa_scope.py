#!/usr/bin/env python3
"""Scope support for QA Squad: user stories, acceptance criteria, scope resolution and settings.

A QA run can be tied to one thing: a user story, a feature, a spec document, an epic, or the
whole product (`full`). This module turns such a reference into a deterministic `scope`
object that `qa-cli` stores in `.qa/scope.json`, propagates as `scope_ids` on every
scenario, result, finding and bug, and that `qa_artifact_report.py` uses to filter its output.

It also owns the report settings (artifact on/off, language, size budget), so the CLI, the
Stop hook and the report generator resolve them the same way.

Dependency-free on purpose (standard library only).

Story file format (tolerant parse, modelled on the user-story packs QA Squad users keep under
`docs/**/user-stories/*.md`):

  * optional front matter with `epic`, `title` and similar scalar or list keys;
  * a heading per story whose text starts with the story ID, e.g. `### US-A01-01 - Title`;
  * a narrative sentence ("As a ... I want ... so that ..." or a translation listed in templates/i18n.json);
  * acceptance criteria written as Gherkin (keywords in English or in any language of templates/i18n.json) inside fenced
    blocks, or as a bullet list under an "Acceptance criteria" label.
"""
from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
from pathlib import Path

SCOPE_SCHEMA = "qa-squad/scope/1"
SCOPE_TYPES = ["story", "feature", "spec", "epic", "full"]

# Folders searched, in order, for user-story and spec documents.
STORY_DIRS = [
    "docs/_handoff/user-stories", "docs/user-stories", "docs/stories", "user-stories",
    "docs/specs", "specs", "docs/requirements", "docs",
]
STORY_EXTENSIONS = {".md", ".markdown", ".feature", ".txt"}

STORY_ID_RE = re.compile(r"^[A-Z][A-Z0-9]{1,7}(?:-[A-Za-z0-9]+)+$")
STORY_HEADING_RE = re.compile(
    r"^(?P<hashes>#{2,5})\s*(?:\*\*)?\s*(?P<id>[A-Z][A-Z0-9]{1,7}(?:-[A-Za-z0-9]+)+)"
    r"\s*(?:[—–:.\-]+\s*)?(?P<title>.*?)\s*(?:\*\*)?\s*$"
)
EPIC_ID_RE = re.compile(r"^(?:EPIC-)?[A-Z]{1,3}\d{1,3}$|^EPIC-[A-Za-z0-9-]+$")

_TEMPLATES = Path(__file__).resolve().parent / "templates"

# English Gherkin vocabulary is built in. Other languages come from templates/i18n.json so that
# the vocabulary is data, not code.
_BASE_KEYWORDS = {
    "feature": ["feature"],
    "background": ["background"],
    "scenario": ["scenario outline", "scenario template", "scenario", "example"],
    "examples": ["examples", "scenarios"],
    "given": ["given"],
    "when": ["when"],
    "then": ["then"],
    "and": ["and"],
    "but": ["but"],
}


def _fold(text: str) -> str:
    """Lowercase and strip accents so keyword matching ignores diacritics."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c)
    )


def load_i18n() -> dict:
    path = _TEMPLATES / "i18n.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def gherkin_keywords() -> dict[str, list[str]]:
    """Merge the built-in English keywords with every language found in i18n.json."""
    merged = {k: list(v) for k, v in _BASE_KEYWORDS.items()}
    for lang in load_i18n().values():
        for key, words in (lang.get("gherkin") or {}).items():
            merged.setdefault(key, [])
            merged[key].extend(w for w in words if w not in merged[key])
    # Longest first, so "scenario outline" wins over "scenario".
    return {k: sorted({_fold(w) for w in v}, key=len, reverse=True) for k, v in merged.items()}


_VOCAB_DEFAULTS = {
    "title_keys": ["title"],
    "narrative_starters": ["as a", "as an"],
    "criteria_labels": ["acceptance criteria", "acceptance criterion"],
    "persona_keys": ["persona", "personas"],
    "priority_keys": ["priority"],
    "status_keys": ["status"],
}


def vocabulary(name: str) -> list[str]:
    """Words of one kind (title keys, narrative openers...) across English and every i18n language."""
    words = list(_VOCAB_DEFAULTS[name])
    for lang in load_i18n().values():
        words += [w for w in (lang.get("vocabulary") or {}).get(name, []) if w not in words]
    return words


def _starts_with_any(text: str, words: list[str]) -> bool:
    folded = _fold(text.strip().lstrip("*_ \t"))
    for w in words:
        fw = _fold(w)
        if folded.startswith(fw) and not folded[len(fw):len(fw) + 1].isalnum():
            return True
    return False


# ------------------------------------------------------------------------ small helpers

def slugify(text: str) -> str:
    out = re.sub(r"[^A-Za-z0-9._-]+", "-", str(text)).strip("-")
    return out or "scope"


def scope_dir_name(scope_id: str) -> str:
    return f"scope-{slugify(scope_id)}"


def parse_front_matter(text: str) -> tuple[dict, str]:
    """Parse a tolerant subset of YAML front matter. Returns (data, body_without_front_matter)."""
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, text
    data: dict = {}
    key = None
    for raw in lines[1:end]:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        m = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", raw)
        if m and not raw.startswith((" ", "\t")):
            key, value = m.group(1), m.group(2).strip()
            if value == "":
                data[key] = []
            elif value.startswith("[") and value.endswith("]"):
                data[key] = [v.strip().strip("\"'") for v in value[1:-1].split(",") if v.strip()]
            else:
                data[key] = value.strip("\"'")
        elif key and raw.lstrip().startswith("- ") and isinstance(data.get(key), list):
            data[key].append(raw.lstrip()[2:].strip().strip("\"'"))
    return data, "\n".join(lines[end + 1:])


# ---------------------------------------------------------------------------- gherkin

def _match_keyword(line: str, words: list[str]) -> tuple[str, str] | None:
    """If the line starts with one of the keywords, return (keyword as written, remainder)."""
    folded = _fold(line)
    for w in words:
        if folded.startswith(w):
            rest = line[len(w):]
            # keyword must be followed by a separator, not be a prefix of a longer word
            if rest[:1] in ("", " ", ":", "\t"):
                return line[:len(w)], rest.lstrip(" :\t")
    return None


def parse_gherkin(text: str) -> list[dict]:
    """Parse Gherkin text into criteria: [{title, kind, steps:[{keyword,type,text}], examples}]."""
    kw = gherkin_keywords()
    criteria: list[dict] = []
    background: list[dict] = []
    current: dict | None = None
    in_background = False
    in_examples = False
    last_type = "given"
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("@") or line.startswith('"""'):
            continue
        if line.startswith("|"):
            if in_examples and current is not None:
                current["examples"].append(line)
            continue
        # "Scenarios:" introduces an examples table, not a scenario, so test it first.
        m = _match_keyword(line, kw["examples"])
        if m and ":" in line[: len(m[0]) + 1]:
            in_examples = True
            continue
        m = _match_keyword(line, kw["background"])
        if m and ":" in line[: len(m[0]) + 1]:
            in_background, in_examples, current = True, False, None
            continue
        m = _match_keyword(line, kw["feature"])
        if m and ":" in line[: len(m[0]) + 1]:
            continue
        m = _match_keyword(line, kw["scenario"])
        if m and ":" in line[: len(m[0]) + 1]:
            in_background, in_examples = False, False
            current = {"title": m[1].strip() or "Untitled scenario", "kind": "gherkin",
                       "steps": [dict(s) for s in background], "examples": []}
            criteria.append(current)
            last_type = "given"
            continue
        step = None
        for stype in ("given", "when", "then"):
            m = _match_keyword(line, kw[stype])
            if m:
                step = {"keyword": m[0].strip(), "type": stype, "text": m[1].strip()}
                last_type = stype
                break
        if step is None:
            for stype in ("and", "but"):
                m = _match_keyword(line, kw[stype])
                if m:
                    step = {"keyword": m[0].strip(), "type": last_type, "text": m[1].strip()}
                    break
        if step is None and line.startswith("*"):
            step = {"keyword": "*", "type": last_type, "text": line[1:].strip()}
        if step is None:
            continue
        if in_background:
            background.append(step)
        elif current is not None:
            current["steps"].append(step)
    return criteria


def executable_from_criterion(criterion: dict) -> dict:
    """Turn a criterion into the scenario fields qa-scenario-tester executes."""
    steps = criterion.get("steps") or []
    if not steps:
        text = criterion.get("title") or ""
        return {"preconditions": "", "steps": [text] if text else [], "expected": text}
    given = [s["text"] for s in steps if s["type"] == "given"]
    when = [s["text"] for s in steps if s["type"] == "when"]
    then = [s["text"] for s in steps if s["type"] == "then"]
    return {
        "preconditions": "; ".join(given),
        "steps": when or [s["text"] for s in steps if s["type"] != "then"],
        "expected": "; ".join(then) if then else (steps[-1]["text"] if steps else ""),
    }


# ---------------------------------------------------------------------------- stories

_BOLD_LABEL_RE = re.compile(r"^\*\*[^*]+\*\*")
_FENCE_RE = re.compile(r"^\s*```+\s*([A-Za-z-]*)\s*$")
_FIELD_RE = re.compile(r"\*\*([^*:]+):\*\*\s*([^·|*]+)")


def _criteria_from_body(lines: list[str], story_id: str) -> list[dict]:
    """Extract acceptance criteria from a story body."""
    region_start = None
    for i, line in enumerate(lines):
        if _starts_with_any(line, vocabulary("criteria_labels")):
            region_start = i + 1
            break
    region = lines[region_start:] if region_start is not None else lines
    # The region ends at the next bold label or heading that is not the criteria label itself.
    cut = len(region)
    in_fence = False
    for i, line in enumerate(region):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        s = line.strip()
        if region_start is not None and (s.startswith("#") or (
                _BOLD_LABEL_RE.match(s) and not _starts_with_any(s, vocabulary("criteria_labels")))):
            cut = i
            break
    region = region[:cut]

    found: list[dict] = []
    fenced: list[list[str]] = []
    buf: list[str] | None = None
    for line in region:
        if _FENCE_RE.match(line):
            if buf is None:
                buf = []
            else:
                fenced.append(buf)
                buf = None
            continue
        if buf is not None:
            buf.append(line)
    for block in fenced:
        found.extend(parse_gherkin("\n".join(block)))
    if not found:
        found = parse_gherkin("\n".join(region))
    if not found and region_start is not None:
        for line in region:
            m = re.match(r"^\s*(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s*)?(.+?)\s*$", line)
            if m:
                found.append({"title": m.group(1)[:200], "kind": "bullet",
                              "steps": [], "examples": []})
    for n, c in enumerate(found, 1):
        c["id"] = f"{story_id}/AC-{n:02d}"
        c["story_id"] = story_id
    return found


def parse_story_text(text: str, source: str = "") -> dict:
    """Parse one document into {front_matter, stories:[...], doc_title, doc_criteria}."""
    front, body = parse_front_matter(text)
    lines = body.splitlines()
    heads: list[tuple[int, int, str, str]] = []
    in_fence = False
    doc_title = ""
    for i, line in enumerate(lines):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if not doc_title and re.match(r"^#\s+\S", line):
            doc_title = re.sub(r"^#\s+", "", line).strip()
        m = STORY_HEADING_RE.match(line)
        if m:
            heads.append((i, len(m.group("hashes")), m.group("id"), m.group("title").strip()))
    stories = []
    for idx, (start, level, sid, title) in enumerate(heads):
        end = len(lines)
        for j in range(start + 1, len(lines)):
            hm = re.match(r"^(#{1,6})\s+\S", lines[j])
            if hm and len(hm.group(1)) <= level and not _inside_fence(lines, start, j):
                end = j
                break
        if idx + 1 < len(heads):
            end = min(end, heads[idx + 1][0])
        block = lines[start + 1:end]
        narrative, fields = "", {}
        for k, bl in enumerate(block):
            s = bl.strip()
            if not fields and "**" in s:
                fields = {m.group(1).strip().lower(): m.group(2).strip()
                          for m in _FIELD_RE.finditer(s)}
            if not narrative and _starts_with_any(s, vocabulary("narrative_starters")):
                parts = [s]
                for nxt in block[k + 1:]:
                    if not nxt.strip() or nxt.strip().startswith(("**", "```", "#")):
                        break
                    parts.append(nxt.strip())
                narrative = " ".join(parts)
        persona = _first_field(fields, vocabulary("persona_keys"))
        priority = _first_field(fields, vocabulary("priority_keys"))
        status = _first_field(fields, vocabulary("status_keys"))
        epic = front.get("epic") or _epic_from_id(sid)
        stories.append({
            "type": "story", "id": sid, "title": title or sid, "source": source,
            "line": start + 1, "epic": epic, "narrative": narrative, "persona": persona,
            "priority": priority, "status": status,
            "acceptance_criteria": _criteria_from_body(block, sid),
        })
    return {"front_matter": front, "doc_title": doc_title, "stories": stories,
            "doc_lines": lines, "story_ranges": [(h[0], h[1]) for h in heads]}


def _first_field(fields: dict, keys: list[str]) -> str:
    folded = {_fold(k): v for k, v in fields.items()}
    for k in keys:
        if _fold(k) in folded:
            return folded[_fold(k)]
    return ""


def _inside_fence(lines: list[str], start: int, upto: int) -> bool:
    inside = False
    for line in lines[start:upto]:
        if _FENCE_RE.match(line):
            inside = not inside
    return inside


def _epic_from_id(story_id: str) -> str:
    parts = story_id.split("-")
    if len(parts) >= 3:
        return "-".join(parts[1:-1])
    return ""


def _candidate_files(root: Path, source: str | None = None) -> list[Path]:
    if source:
        p = Path(source)
        p = p if p.is_absolute() else root / p
        if p.is_file():
            return [p]
        if p.is_dir():
            return sorted(f for f in p.rglob("*") if f.suffix.lower() in STORY_EXTENSIONS)
        return []
    seen, out = set(), []
    for rel in STORY_DIRS:
        d = root / rel
        if not d.is_dir():
            continue
        depth_limit = 1 if rel == "docs" else 6
        for f in sorted(d.rglob("*")):
            if f.suffix.lower() not in STORY_EXTENSIONS or not f.is_file():
                continue
            if len(f.relative_to(d).parts) > depth_limit + 1:
                continue
            if f not in seen:
                seen.add(f)
                out.append(f)
    return out


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def load_stories(root: Path, source: str | None = None) -> list[dict]:
    """Every story found in the candidate files (each carries its source and epic)."""
    stories = []
    for f in _candidate_files(root, source):
        parsed = parse_story_text(_read(f), _rel(f, root))
        for s in parsed["stories"]:
            s["epic_title"] = _first_field(parsed["front_matter"], vocabulary("title_keys"))
            stories.append(s)
    return stories


# ----------------------------------------------------------------------------- scopes

def _finish(scope: dict) -> dict:
    """Fill the derived fields every scope carries."""
    scope["schema"] = SCOPE_SCHEMA
    scope.setdefault("children", [])
    scope.setdefault("acceptance_criteria", [])
    scope.setdefault("parent_id", "")
    scope.setdefault("narrative", "")
    scope.setdefault("source", "")
    scope["ids"] = [scope["id"]] + ([scope["parent_id"]] if scope.get("parent_id") else [])
    for child in scope["children"]:
        child["parent_id"] = scope["id"] if scope["type"] in ("epic", "spec") else child.get("parent_id", "")
        child["ids"] = [child["id"], scope["id"]] if scope["type"] in ("epic", "spec") else [child["id"]]
        child.setdefault("schema", SCOPE_SCHEMA)
        child.setdefault("children", [])
    return scope


def full_scope() -> dict:
    return _finish({"type": "full", "id": "full", "title": "Full audit"})


def story_scope(story: dict) -> dict:
    return _finish({
        "type": "story", "id": story["id"], "title": story["title"], "source": story.get("source", ""),
        "line": story.get("line"), "narrative": story.get("narrative", ""),
        "persona": story.get("persona", ""), "priority": story.get("priority", ""),
        "status": story.get("status", ""), "parent_id": story.get("epic", ""),
        "acceptance_criteria": story.get("acceptance_criteria", []),
    })


def _flatten_criteria(children: list[dict]) -> list[dict]:
    return [c for ch in children for c in ch.get("acceptance_criteria", [])]


def inline_criteria(story_id: str, texts: list[str]) -> list[dict]:
    """Criteria supplied directly on the command line ("Given a; When b; Then c" or plain text)."""
    out = []
    for n, text in enumerate(texts, 1):
        kw = gherkin_keywords()
        starts_like_steps = _starts_with_any(text, kw["given"] + kw["when"])
        title = re.sub(r"\s*;\s*", ", ", text)[:80]
        parsed = parse_gherkin(f"Scenario: {title}\n" + re.sub(r"\s*;\s*", "\n", text)) \
            if starts_like_steps else []
        if parsed and parsed[0]["steps"]:
            c = parsed[0]
        else:
            c = {"title": text[:200], "kind": "bullet", "steps": [], "examples": []}
        c["id"] = f"{story_id}/AC-{n:02d}"
        c["story_id"] = story_id
        out.append(c)
    return out


def detect_type(value: str, root: Path) -> str:
    p = Path(value)
    if (p if p.is_absolute() else root / p).is_file():
        return "spec"
    if value.lower() == "full":
        return "full"
    if STORY_ID_RE.match(value) and re.search(r"\d", value):
        return "story"
    if EPIC_ID_RE.match(value):
        return "epic"
    return "feature"


def resolve_scope(root: Path, *, scope_type: str, value: str = "", title: str = "",
                  source: str | None = None, criteria: list[str] | None = None) -> dict:
    """Resolve a scope reference into a scope object. Raises ValueError with a clear message."""
    root = Path(root)
    if scope_type == "auto":
        scope_type = detect_type(value, root)
    if scope_type not in SCOPE_TYPES:
        raise ValueError(f"Unknown scope type '{scope_type}'. Use one of: {', '.join(SCOPE_TYPES)}")
    if scope_type == "full":
        return full_scope()
    if not value:
        raise ValueError(f"Scope type '{scope_type}' needs an identifier or a path.")

    if scope_type == "story":
        stories = [s for s in load_stories(root, source) if s["id"].lower() == value.lower()]
        if stories:
            scope = story_scope(stories[0])
            if title:
                scope["title"] = title
            if criteria:
                scope["acceptance_criteria"] = inline_criteria(scope["id"], criteria)
            return scope
        if criteria or title:
            # The story is not in any document: take it as the user described it.
            return _finish({"type": "story", "id": value, "title": title or value,
                            "source": "inline", "acceptance_criteria": inline_criteria(value, criteria or [])})
        searched = ", ".join(STORY_DIRS) if not source else source
        raise ValueError(
            f"Story '{value}' was not found. Searched: {searched}. Pass --source <file or folder>, "
            "or describe it with --title and --criterion."
        )

    if scope_type == "epic":
        stories = [s for s in load_stories(root, source)
                   if s.get("epic", "").lower() == value.lower() or s["id"].lower() == value.lower()]
        stories = [s for s in stories if s["id"].lower() != value.lower()]
        if not stories:
            raise ValueError(f"Epic '{value}' has no stories. Pass --source <file or folder> with its stories.")
        children = [story_scope(s) for s in stories]
        return _finish({
            "type": "epic", "id": value, "title": title or (stories[0].get("epic_title") or value),
            "source": stories[0]["source"], "children": children,
            "acceptance_criteria": _flatten_criteria(children),
        })

    if scope_type == "spec":
        p = Path(value)
        p = p if p.is_absolute() else root / p
        if not p.is_file():
            raise ValueError(f"Spec file '{value}' does not exist.")
        parsed = parse_story_text(_read(p), _rel(p, root))
        children = [story_scope(s) for s in parsed["stories"]]
        spec_id = parsed["front_matter"].get("id") or slugify(p.stem)
        doc_criteria = _criteria_from_body(
            [ln for i, ln in enumerate(parsed["doc_lines"])
             if not any(a <= i for a, _ in parsed["story_ranges"])] if children else parsed["doc_lines"],
            spec_id,
        )
        criteria_all = doc_criteria + _flatten_criteria(children)
        if criteria:
            criteria_all += inline_criteria(spec_id, criteria)
        return _finish({
            "type": "spec", "id": spec_id,
            "title": title or _first_field(parsed["front_matter"], vocabulary("title_keys"))
            or parsed["doc_title"] or spec_id,
            "source": _rel(p, root), "children": children, "acceptance_criteria": criteria_all,
        })

    # feature: no document; the scenarios are tied to it through the inventory.
    return _finish({
        "type": "feature", "id": slugify(value), "title": title or value, "source": source or "",
        "acceptance_criteria": inline_criteria(slugify(value), criteria or []),
    })


def all_scope_ids(scope: dict) -> list[str]:
    """Every ID a result may carry to belong to this scope or one of its children."""
    ids = [scope["id"]]
    for ch in scope.get("children", []):
        ids.append(ch["id"])
    return ids


# --------------------------------------------------------------------------- settings

TRUTHY = {"1", "true", "yes", "on"}


def artifact_settings(root: Path, env: dict | None = None, no_artifact: bool = False) -> dict:
    """Resolve whether artifacts are on, plus language and size budget, and say why.

    Precedence: `--no-artifact` flag, then environment, then `.qa/config.json`, then defaults
    (artifacts ON, English, 12 MB).
    """
    env = os.environ if env is None else env
    cfg = {}
    try:
        cfg = (json.loads((Path(root) / ".qa" / "config.json").read_text(encoding="utf-8")) or {}).get("artifacts") or {}
    except (OSError, json.JSONDecodeError, AttributeError):
        cfg = {}
    publish, reason = True, "default"
    if "publish" in cfg:
        publish, reason = bool(cfg["publish"]), ".qa/config.json artifacts.publish"
    if str(env.get("QA_SQUAD_NO_ARTIFACT", "")).strip().lower() in TRUTHY:
        publish, reason = False, "QA_SQUAD_NO_ARTIFACT"
    if no_artifact:
        publish, reason = False, "--no-artifact"
    language = env.get("QA_SQUAD_REPORT_LANG") or cfg.get("language") or "en"
    try:
        budget = float(env.get("QA_SQUAD_ARTIFACT_BUDGET_MB") or cfg.get("budget_mb") or 12)
    except ValueError:
        budget = 12.0
    return {"publish": publish, "reason": reason, "language": language, "budget_mb": min(budget, 12.0)}


# -------------------------------------------------------------------------------- CLI

def _main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Inspect how QA Squad parses stories and scopes.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("parse", help="print the stories parsed from one file")
    p.add_argument("file")
    r = sub.add_parser("resolve", help="print the scope a reference resolves to")
    r.add_argument("--type", default="auto")
    r.add_argument("value", nargs="?", default="")
    r.add_argument("--root", default=".")
    r.add_argument("--source")
    a = ap.parse_args(argv)
    if a.cmd == "parse":
        out = parse_story_text(Path(a.file).read_text(encoding="utf-8"), a.file)
        print(json.dumps(out["stories"], indent=2, ensure_ascii=False))
        return 0
    try:
        print(json.dumps(resolve_scope(Path(a.root), scope_type=a.type, value=a.value, source=a.source),
                         indent=2, ensure_ascii=False))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
