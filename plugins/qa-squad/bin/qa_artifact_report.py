#!/usr/bin/env python3
"""QA Squad evidence and failure report generator (self-contained HTML, Artifact-ready).

Reads the deterministic package under `docs/qa/` (the `manifest.json` of one finished
execution plus the evidence files it points at) and renders, for one scope:

  * an EVIDENCE report: verdict, summary, result per criterion / scenario / item, screenshots,
    trace and video paths, logs, coverage and environment;
  * a FAILURE report, only when the scope has a failure or a finding: error, steps to
    reproduce, the screenshot of the moment, evidence, severity and anchors.

Two output modes:

  --artifact    HTML *fragment* for the Claude Code Artifact tool: no doctype/html/head/body
                tags (the platform wraps the page), `<title>` of two to four words first,
                theme tokens with a dark variant, no external resources, images as data URIs.
                Written to --out-dir (default `.qa/artifacts/<execution>/`) together with
                `artifact-plan.json`, which lists what to publish (path, icon, description).
  --standalone  Complete HTML documents written next to the scope's data, in
                `docs/qa/executions/<execution>/scope-<id>/`. This is the default when
                neither flag is given.

Everything is filtered by scope: a story's reports list only items tagged with that story.
Total size is kept under the budget (default 12 MB) by degrading in levels; whatever was left
out is listed on the page. Secrets are masked before anything is embedded.

Standard library only. Pillow is optional and only shrinks images.

Examples:
  qa_artifact_report.py --execution latest --scope current --artifact --out-dir "$SCRATCH"
  qa_artifact_report.py --execution exec-20261011T120000Z --scope US-A01-03 --standalone
  qa_artifact_report.py --settings
  qa_artifact_report.py --selftest
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import html
import io
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import zlib
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qa_scope  # noqa: E402

try:  # optional: without Pillow images are embedded as they are, or left out when too large
    from PIL import Image
except Exception:  # pragma: no cover - depends on the environment
    Image = None

GENERATOR_VERSION = "1.0.0"
BUDGET_BYTES = 12 * 1024 * 1024

# (images per passing item, images per failing item, max width px, JPEG quality, log lines)
LEVELS = [
    (6, 12, 1280, 70, 200),
    (3, 12, 1280, 70, 150),
    (1, 12, 1100, 65, 100),
    (1, 6, 960, 60, 60),
    (0, 6, 960, 60, 40),
    (0, 3, 800, 50, 20),
    (0, 0, 800, 50, 0),
]

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
VIDEO_EXT = {".webm", ".mp4", ".mov"}
TRACE_EXT = {".zip"}
TEXT_EXT = {".log", ".txt", ".json", ".md", ".xml", ".yaml", ".yml", ".csv", ".har", ".out", ".err"}
MAX_TEXT_BYTES = 80_000
SEVERITY_ORDER = ["critical", "high", "medium", "low"]

# ------------------------------------------------------------------------------ strings

STRINGS_EN = {
    "title_evidence": "QA Evidence", "title_failures": "QA Failures",
    "verdict": "Verdict", "PASSED": "PASSED", "FAILED": "FAILED", "BLOCKED": "BLOCKED",
    "INCOMPLETE": "INCOMPLETE", "NO_DATA": "NO DATA", "PASSED_WITH_FINDINGS": "PASSED WITH FINDINGS",
    "PASS": "PASS", "FAIL": "FAIL", "NOT_EXECUTED": "NOT EXECUTED", "NOT_APPLICABLE": "N/A",
    "summary": "Summary", "scope": "Scope", "criteria": "Acceptance criteria",
    "coverage": "Coverage by category", "requirements": "Requirement acceptance",
    "results": "Results", "other_results": "Other results", "findings": "Findings",
    "environment": "Environment", "omitted": "Left out of this page", "files": "Files not embedded",
    "execution": "Execution", "generated": "Generated", "source": "Source", "type": "Type",
    "items": "Items", "executed": "Executed", "total": "Total", "category": "Category",
    "criterion": "Criterion", "status": "Status", "evidence": "Evidence", "title": "Title",
    "severity": "Severity", "result": "Result", "preconditions": "Preconditions", "steps": "Steps",
    "expected": "Expected result", "actual": "Actual result", "profile": "Profile", "route": "Route",
    "tester": "Tester", "tested_at": "Tested at", "bug": "Bug", "finding": "Finding",
    "no_evidence": "No evidence recorded.", "no_criteria": "No scenario executed for this criterion.",
    "story": "Story", "narrative": "Narrative", "branch": "Branch", "commit": "Commit",
    "base_url": "Base URL", "browser": "Browser", "executor": "Executor", "scopes": "Scope IDs",
    "requirement": "Requirement", "percent": "Executed", "error": "Error", "observed": "Observed",
    "hypothesis": "Hypothesis (not confirmed)", "reproduce": "Steps to reproduce",
    "moment": "Screenshot of the moment", "classification": "Classification", "anchors": "Anchors",
    "impact": "Impact", "recommendation": "Recommendation", "location": "Location",
    "no_failures": "No failures in this scope.", "failures_count": "failures", "failures_title": "Failures",
    "budget_note": "The size budget of {mb} MB was exceeded at the earlier levels, so the page was reduced "
                   "(images per item, resolution, log length). The complete material stays on disk.",
    "no_pillow": "Pillow is not installed: images are embedded as they are, and large ones are left out.",
    "categories_filter": "Categories", "back_to_top": "Back to top", "open_image": "enlarge",
    "log": "Log", "missing": "file not found", "size": "size", "desc_evidence":
        "Evidence report for {scope}: verdict {verdict}, {summary}.",
    "desc_failures": "Failure report for {scope}: {count} failure(s) with steps to reproduce and evidence.",
    "summary_counts": "{passed} passed, {failed} failed, {blocked} blocked, {ne} not executed",
    "orphan": "not in the inventory", "child_scopes": "Child scopes",
}


def load_strings(lang: str) -> dict:
    strings = dict(STRINGS_EN)
    if lang and lang.lower() not in ("en", "en-us", "en-gb"):
        data = qa_scope.load_i18n()
        match = next((v for k, v in data.items() if k.lower() == lang.lower()), None)
        if match:
            strings.update(match.get("ui") or {})
    return strings


# --------------------------------------------------------------------- text and secrets

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")
_KEY = r"[\w-]*(?:password|passwd|senha|secret|token|api[_-]?key|authorization|cookie|credential)[\w-]*"
REDACTIONS = [
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 ***"),
    (re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*"), "***jwt***"),
    (re.compile(r"(?i)(\b" + _KEY + r"[\"']?\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;&}\]\"']+)"), r"\1***"),
    (re.compile(r"(?i)(set-cookie\s*:\s*)(.+)"), r"\1***"),
    (re.compile(r"(\b[a-z][a-z0-9+.-]*://[^:/\s@]+:)[^@\s/]+@"), r"\1***@"),
    (re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"), "***"),
]


def redact(text: str) -> str:
    text = ANSI_RE.sub("", text or "")
    for rx, rep in REDACTIONS:
        text = rx.sub(rep, text)
    return text


def esc(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def clip_lines(text: str, max_lines: int, max_bytes: int = MAX_TEXT_BYTES) -> str:
    lines = text.splitlines()
    note = ""
    if max_lines and len(lines) > max_lines:
        note = f"[... {len(lines) - max_lines} earlier lines left out ...]\n"
        lines = lines[-max_lines:]
    out = "\n".join(lines)
    raw = out.encode("utf-8", "replace")
    if len(raw) > max_bytes:
        out = raw[-max_bytes:].decode("utf-8", "replace")
        note = "[... truncated by size ...]\n"
    return note + out


def human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


# ------------------------------------------------------------------------------ model

def find_manifest(root: Path, execution: str) -> tuple[str, dict]:
    base = root / "docs" / "qa" / "executions"
    if execution in ("latest", "", None):
        candidates = sorted((d for d in base.glob("exec-*") if (d / "manifest.json").exists()), reverse=True) \
            if base.exists() else []
        if not candidates:
            raise SystemExit(
                "No finished execution with a manifest was found under docs/qa/executions/. "
                "Run 'qa-cli execution-start' and 'qa-cli execution-finish' first."
            )
        execution = candidates[0].name
    manifest = read_json(base / execution / "manifest.json")
    if manifest is None:
        raise SystemExit(
            f"Execution '{execution}' has no manifest.json. It is written by 'qa-cli execution-finish'."
        )
    return execution, manifest


def build_view(manifest: dict, scope_id: str | None, categories: list[str] | None) -> dict:
    """Select the scope and keep only the items, findings and bugs that belong to it."""
    mscope = manifest.get("scope") or qa_scope.full_scope()
    if scope_id in (None, "", "current") or scope_id == mscope["id"]:
        scope = mscope
    else:
        scope = next((c for c in mscope.get("children", []) if c["id"] == scope_id), None)
        if scope is None:
            if any(scope_id in i.get("scope_ids", []) for i in manifest.get("items", [])):
                scope = {"type": "scope", "id": scope_id, "title": scope_id, "source": "",
                         "children": [], "acceptance_criteria": []}
            else:
                known = sorted({s for i in manifest.get("items", []) for s in i.get("scope_ids", [])})
                raise SystemExit(f"Scope '{scope_id}' is not part of this execution. Known scopes: {', '.join(known) or 'none'}.")
    is_full = scope["type"] == "full"
    items = [i for i in manifest.get("items", []) if is_full or scope["id"] in (i.get("scope_ids") or [])]
    if categories:
        items = [i for i in items if i.get("category") in categories]
    item_ids = {i["id"] for i in items}
    linked = {fid for i in items for fid in (i.get("finding_ids") or [])}
    findings = []
    for f in manifest.get("findings", []):
        mine = is_full or scope["id"] in (f.get("scope_ids") or []) or f["id"] in linked \
            or f.get("scenario_id") in item_ids
        if mine and categories and f.get("category") not in categories and f["id"] not in linked:
            mine = False
        if mine:
            findings.append(f)
    bug_ids = {i.get("bug_id") for i in items if i.get("bug_id")}
    bugs = [b for b in manifest.get("bugs", []) if b.get("bug_id") in bug_ids or b.get("scenario_id") in item_ids]
    criteria = []
    for c in scope.get("acceptance_criteria", []):
        owners = [i for i in items if i.get("criterion_id") == c["id"]]
        criteria.append({**c, "items": owners, "status": criterion_status(owners)})
    if not criteria and not is_full:
        # A scope with no parsed criteria still shows per-criterion rows when items name one.
        seen = {}
        for i in items:
            if i.get("criterion_id"):
                seen.setdefault(i["criterion_id"], []).append(i)
        for cid, owners in seen.items():
            criteria.append({"id": cid, "title": owners[0]["label"], "kind": "scenario", "steps": [],
                             "story_id": scope["id"], "items": owners, "status": criterion_status(owners)})
    view = {"scope": scope, "is_full": is_full, "items": items, "findings": findings, "bugs": bugs,
            "criteria": criteria, "categories": categories or []}
    view["counts"] = status_counts(items)
    view["verdict"] = compute_verdict(view)
    return view


def criterion_status(owners: list[dict]) -> str:
    if not owners:
        return "NOT_EXECUTED"
    statuses = {i["status"] for i in owners}
    if "FAIL" in statuses:
        return "FAIL"
    if "BLOCKED" in statuses:
        return "BLOCKED"
    if "NOT_EXECUTED" in statuses:
        return "NOT_EXECUTED"
    if statuses == {"NOT_APPLICABLE"}:
        return "NOT_APPLICABLE"
    return "PASS"


def status_counts(items: list[dict]) -> dict:
    counts = {"PASS": 0, "FAIL": 0, "BLOCKED": 0, "NOT_EXECUTED": 0, "NOT_APPLICABLE": 0}
    for i in items:
        counts[i["status"]] = counts.get(i["status"], 0) + 1
    return counts


def compute_verdict(view: dict) -> str:
    counts = view["counts"]
    serious = any(f.get("severity") in ("critical", "high") for f in view["findings"])
    if not view["items"] and not view["findings"]:
        return "NO_DATA"
    if counts["FAIL"] or serious or any(c["status"] == "FAIL" for c in view["criteria"]):
        return "FAILED"
    if counts["BLOCKED"] or any(c["status"] == "BLOCKED" for c in view["criteria"]):
        return "BLOCKED"
    if counts["NOT_EXECUTED"] or any(c["status"] == "NOT_EXECUTED" for c in view["criteria"]):
        return "INCOMPLETE"
    if view["findings"]:
        return "PASSED_WITH_FINDINGS"
    return "PASSED"


def coverage_rows(view: dict) -> list[dict]:
    rows: dict[str, dict] = {}
    for i in view["items"]:
        if i.get("orphan"):
            continue
        r = rows.setdefault(i["category"], {"category": i["category"], "total": 0, "executed": 0,
                                            "PASS": 0, "FAIL": 0, "BLOCKED": 0, "NOT_APPLICABLE": 0,
                                            "NOT_EXECUTED": 0})
        r["total"] += 1
        r[i["status"]] = r.get(i["status"], 0) + 1
        if i["status"] != "NOT_EXECUTED":
            r["executed"] += 1
    for r in rows.values():
        r["percent"] = round(100 * r["executed"] / r["total"], 1) if r["total"] else 0.0
    return sorted(rows.values(), key=lambda r: r["category"])


def requirement_rows(view: dict) -> list[dict]:
    """Per-requirement acceptance, using the same rule as `qa-cli requirement-report`."""
    bugs = {b["bug_id"]: b for b in view["bugs"]}
    groups: dict[str, list[dict]] = {}
    for i in view["items"]:
        rid = i.get("requirement_id")
        if rid and rid != "NOT_AVAILABLE":
            groups.setdefault(rid, []).append(i)
    rows = []
    for rid, items in sorted(groups.items()):
        counts = status_counts(items)
        product = inconclusive = unbugged = False
        for i in items:
            if i["status"] != "FAIL":
                continue
            bug = bugs.get(i.get("bug_id") or "")
            if not bug:
                unbugged = True
            elif bug.get("classification") == "PRODUCT_DEFECT":
                product = True
            else:
                inconclusive = True
        if product:
            result = "NOT_ACCEPTED"
        elif counts["BLOCKED"] or unbugged or inconclusive:
            result = "BLOCKED"
        elif counts["NOT_EXECUTED"]:
            result = "INCOMPLETE"
        elif counts["PASS"]:
            result = "ACCEPTED"
        else:
            result = "INCOMPLETE"
        rows.append({"requirement_id": rid, "scenarios": len(items), "pass": counts["PASS"],
                     "fail": counts["FAIL"], "blocked": counts["BLOCKED"], "result": result})
    return rows


def failure_units(view: dict) -> list[dict]:
    """One unit per failing item (its findings and bug merged in), plus findings with no failing item."""
    findings = {f["id"]: f for f in view["findings"]}
    bugs = {b["bug_id"]: b for b in view["bugs"]}
    used: set[str] = set()
    units = []
    for i in view["items"]:
        if i["status"] != "FAIL":
            continue
        fs = [findings[fid] for fid in (i.get("finding_ids") or []) if fid in findings]
        fs += [f for f in view["findings"] if f.get("scenario_id") == i["id"] and f not in fs]
        used.update(f["id"] for f in fs)
        units.append({"item": i, "findings": fs, "bug": bugs.get(i.get("bug_id") or "")})
    for f in view["findings"]:
        if f["id"] in used:
            continue
        item = next((i for i in view["items"] if f["id"] in (i.get("finding_ids") or [])
                     or i["id"] == f.get("scenario_id")), None)
        units.append({"item": item, "findings": [f], "bug": bugs.get((item or {}).get("bug_id") or "")})
    def rank(u):
        sev = next((f.get("severity") for f in u["findings"] if f.get("severity") in SEVERITY_ORDER), "low")
        if u["bug"] and u["bug"].get("severity") in SEVERITY_ORDER:
            sev = min(sev, u["bug"]["severity"], key=SEVERITY_ORDER.index)
        return SEVERITY_ORDER.index(sev)
    units.sort(key=rank)
    return units


def unit_severity(unit: dict) -> str:
    sevs = [f.get("severity") for f in unit["findings"] if f.get("severity") in SEVERITY_ORDER]
    if unit["bug"] and unit["bug"].get("severity") in SEVERITY_ORDER:
        sevs.append(unit["bug"]["severity"])
    return min(sevs, key=SEVERITY_ORDER.index) if sevs else "unrated"


# ------------------------------------------------------------------------------ images

class Imgs:
    """Encodes screenshots as data URIs, one cache entry per (file, width, quality)."""

    def __init__(self):
        self.cache: dict = {}
        self.omitted: list[tuple[str, str]] = []

    def encode(self, path: Path, width: int, quality: int, raw_cap: int) -> str | None:
        key = (str(path), width, quality, raw_cap)
        if key in self.cache:
            return self.cache[key]
        try:
            data = path.read_bytes()
        except OSError:
            self.cache[key] = None
            return None
        uri = None
        if Image is not None:
            try:
                im = Image.open(io.BytesIO(data))
                im.load()
                if im.mode != "RGB":
                    bg = Image.new("RGB", im.size, (255, 255, 255))
                    bg.paste(im, mask=im.split()[-1] if im.mode in ("RGBA", "LA") else None)
                    im = bg
                if im.width > width:
                    im = im.resize((width, max(1, round(im.height * width / im.width))), Image.LANCZOS)
                buf = io.BytesIO()
                im.save(buf, "JPEG", quality=quality, optimize=True)
                uri = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
            except Exception:
                uri = None
        if uri is None:
            if len(data) <= raw_cap:
                mime = ("image/png" if data[:4] == b"\x89PNG" else "image/webp" if data[:4] == b"RIFF"
                        else "image/gif" if data[:3] == b"GIF" else "image/jpeg")
                uri = f"data:{mime};base64," + base64.b64encode(data).decode()
        self.cache[key] = uri
        return uri


def pick_spread(items: list, n: int) -> list:
    """n entries spread evenly over a list, always keeping the first and the last."""
    if n <= 0 or not items:
        return []
    if len(items) <= n:
        return list(items)
    if n == 1:
        return [items[-1]]
    idx = sorted({round(k * (len(items) - 1) / (n - 1)) for k in range(n)})
    return [items[k] for k in idx]


# ------------------------------------------------------------------------------- HTML

TOKENS_LIGHT = (
    "--bg:#f3f5f6;--fg:#17212b;--muted:#566472;--card:#ffffff;--line:#d3dbe0;--code:#ebeff2;"
    "--pass:#16693a;--pass-bg:#dcf2e3;--fail:#b3261e;--fail-bg:#fde7e5;"
    "--warn:#7a5a06;--warn-bg:#fff1c9;--info:#1a5f8a;--info-bg:#e1eff8;"
    "--accent:#1f6f78;--link:#0b5cad;--overlay:rgba(0,0,0,.88)"
)
TOKENS_DARK = (
    "--bg:#0e1317;--fg:#e3e8ed;--muted:#97a4b1;--card:#161d23;--line:#2b353e;--code:#0b0f12;"
    "--pass:#6fd08c;--pass-bg:#14301d;--fail:#ff8b83;--fail-bg:#3a1a18;"
    "--warn:#e6c35c;--warn-bg:#33290c;--info:#7cc0ea;--info-bg:#10283a;"
    "--accent:#5cc2cc;--link:#7db8ff;--overlay:rgba(0,0,0,.92)"
)

CSS = """:root{TOKENS_LIGHT}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){TOKENS_DARK;color-scheme:dark}}
:root[data-theme="dark"]{TOKENS_DARK;color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;padding-block:20px 56px;padding-inline:16px;background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;overflow-wrap:anywhere}
.wrap{max-width:1160px;margin:0 auto}
h1{font-size:1.55rem;margin:0 0 4px;text-wrap:balance}
h2{font-size:1.2rem;margin:30px 0 10px;padding-bottom:4px;border-bottom:2px solid var(--line)}
h3{font-size:1.02rem;margin:0 0 6px} h4{font-size:.92rem;margin:12px 0 4px}
a{color:var(--link)} a:focus-visible,summary:focus-visible,label:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.muted{color:var(--muted)} .small{font-size:.85rem}
.badge{display:inline-block;padding:1px 9px;border-radius:999px;font-weight:600;font-size:.78rem;letter-spacing:.03em;border:1px solid transparent;white-space:nowrap}
.b-pass{background:var(--pass-bg);color:var(--pass);border-color:var(--pass)}
.b-fail{background:var(--fail-bg);color:var(--fail);border-color:var(--fail)}
.b-warn{background:var(--warn-bg);color:var(--warn);border-color:var(--warn)}
.b-info{background:var(--info-bg);color:var(--info);border-color:var(--info)}
.verdict{font-size:1.05rem;padding:3px 14px}
.nav{display:flex;flex-wrap:wrap;gap:6px 14px;margin:10px 0 0}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:14px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px;min-width:0}
.card .n{font-size:1.5rem;font-weight:700;font-variant-numeric:tabular-nums}
.card.pass .n{color:var(--pass)} .card.fail .n{color:var(--fail)} .card.warn .n{color:var(--warn)}
.kv{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:2px 14px;margin:0}
.kv dt{color:var(--muted)} .kv dd{margin:0;min-width:0}
.tw{overflow-x:auto;max-width:100%}
table{border-collapse:collapse;width:100%;min-width:520px;background:var(--card);border:1px solid var(--line)}
td,th{overflow-wrap:normal}
th,td{text-align:left;padding:5px 9px;border-bottom:1px solid var(--line);vertical-align:top}
th{background:var(--code);font-size:.82rem;color:var(--muted);white-space:nowrap}
td.num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
pre,code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.8rem}
pre{background:var(--code);border:1px solid var(--line);border-radius:6px;padding:8px 10px;margin:6px 0;white-space:pre-wrap;overflow:auto;max-height:380px}
code{background:var(--code);padding:1px 4px;border-radius:4px} pre code{background:none;padding:0}
details{margin:6px 0} summary{cursor:pointer;font-weight:600}
.item{background:var(--card);border:1px solid var(--line);border-left-width:4px;border-radius:8px;padding:11px 13px;margin:12px 0;min-width:0}
.item.s-pass{border-left-color:var(--pass)} .item.s-fail{border-left-color:var(--fail)}
.item.s-warn{border-left-color:var(--warn)} .item.s-info{border-left-color:var(--info)}
.item header{display:flex;flex-wrap:wrap;gap:6px 10px;align-items:center;margin-bottom:6px}
.item header h3{margin:0;flex:1 1 220px;min-width:0}
.frames{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px;margin:6px 0}
figure.shot{margin:0;position:relative;min-width:0}
figure.shot figcaption{font-size:.75rem;color:var(--muted);margin-top:2px}
figure.shot img{display:block;max-width:100%;height:auto;border:1px solid var(--line);border-radius:6px;background:#fff}
.moment{max-width:760px}
.zoom{position:absolute;opacity:0;width:1px;height:1px;pointer-events:none}
figure.shot label{display:block;cursor:zoom-in}
.zoom:checked+label{position:fixed;inset:0;z-index:100;background:var(--overlay);display:flex;align-items:center;justify-content:center;padding:16px;cursor:zoom-out}
.zoom:checked+label img{max-width:100%;max-height:100%;width:auto;border:0}
ol.steps{margin:4px 0;padding-left:22px;font-size:.9rem}
.note{background:var(--warn-bg);color:var(--warn);border:1px solid var(--warn);padding:8px 12px;border-radius:8px;margin:10px 0}
.group{margin-top:22px;padding-top:4px}
@media (max-width:600px){h1{font-size:1.3rem}.kv{grid-template-columns:minmax(0,1fr)}}
@media (prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}
""".replace("{TOKENS_LIGHT}", "{" + TOKENS_LIGHT + "}").replace("{TOKENS_DARK;", "{" + TOKENS_DARK + ";")


STATUS_CLASS = {"PASS": "b-pass", "FAIL": "b-fail", "BLOCKED": "b-warn", "NOT_EXECUTED": "b-info",
                "NOT_APPLICABLE": "b-info", "PASSED": "b-pass", "FAILED": "b-fail",
                "INCOMPLETE": "b-warn", "NO_DATA": "b-info", "PASSED_WITH_FINDINGS": "b-warn",
                "ACCEPTED": "b-pass", "NOT_ACCEPTED": "b-fail"}
SEVERITY_CLASS = {"critical": "b-fail", "high": "b-fail", "medium": "b-warn", "low": "b-info", "unrated": "b-info"}


class Page:
    def __init__(self, S: dict):
        self.S = S
        self.parts: list[str] = []
        self.zid = 0
        self.embedded = 0

    def add(self, html_text: str) -> None:
        self.parts.append(html_text)

    def badge(self, status: str) -> str:
        return f'<span class="badge {STATUS_CLASS.get(status, "b-info")}">{esc(self.S.get(status, status))}</span>'

    def sev(self, severity: str) -> str:
        return f'<span class="badge {SEVERITY_CLASS.get(severity, "b-info")}">{esc(severity)}</span>'

    def figure(self, uri: str, caption: str, alt: str, cls: str = "") -> str:
        self.zid += 1
        self.embedded += 1
        return (f'<figure class="shot {cls}"><input type="checkbox" class="zoom" id="z{self.zid}" '
                f'aria-label="{esc(self.S["open_image"])}"><label for="z{self.zid}">'
                f'<img src="{uri}" alt="{esc(alt)}" loading="lazy"></label>'
                f'<figcaption>{esc(caption)}</figcaption></figure>')


def table(headers: list[str], rows: list[list[str]], num_cols: tuple = ()) -> str:
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = ""
    for r in rows:
        body += "<tr>" + "".join(
            f'<td class="{"num" if k in num_cols else ""}">{c}</td>' for k, c in enumerate(r)) + "</tr>"
    return f'<div class="tw"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def kv(rows: list[tuple[str, str]]) -> str:
    return '<dl class="kv">' + "".join(f"<dt>{esc(k)}</dt><dd>{v}</dd>" for k, v in rows if v not in (None, "")) + "</dl>"


def pre(text: str, max_lines: int = 200) -> str:
    return f"<pre>{esc(clip_lines(redact(text), max_lines))}</pre>"


def classify(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in VIDEO_EXT:
        return "video"
    if ext in TRACE_EXT:
        return "trace"
    if ext in TEXT_EXT:
        return "text"
    return "other"


class Ctx:
    """Everything the renderers share for one build."""

    def __init__(self, root: Path, S: dict, imgs: Imgs, plan: tuple, level: int):
        self.root, self.S, self.imgs, self.plan, self.level = root, S, imgs, plan, level
        self.files_not_embedded: list[tuple[str, str, str]] = []  # (kind, path, size)
        self.page = Page(S)
        self.anchor_n = 0

    def next_id(self, prefix: str) -> str:
        self.anchor_n += 1
        return f"{prefix}-{self.anchor_n}"


def evidence_html(ctx: Ctx, item_label: str, evidence: list[str], image_budget: int,
                  moment: str | None = None) -> str:
    """Render one evidence list: images, then logs, and register videos/traces as paths."""
    S, root, page = ctx.S, ctx.root, ctx.page
    _, _, width, quality, log_lines = ctx.plan
    out: list[str] = []
    images = [e for e in evidence if classify(e) == "image" and e != moment]
    shots: list[str] = []
    if moment:
        shots.append(moment)
    shots += pick_spread(images, max(0, image_budget - (1 if moment else 0)))
    raw_cap = max(40_000, 450_000 >> min(ctx.level, 3))
    figs = []
    for rel in shots:
        uri = ctx.imgs.encode(root / rel, width, quality, raw_cap)
        if uri:
            figs.append(page.figure(uri, Path(rel).name, f"{item_label}: {Path(rel).name}",
                                    "moment" if rel == moment else ""))
        else:
            ctx.imgs.omitted.append((rel, "image too large or unreadable"))
    skipped = [e for e in images if e not in shots]
    for rel in skipped:
        ctx.imgs.omitted.append((rel, "not embedded at this size level"))
    if moment and figs and shots and shots[0] == moment:
        out.append(f'<h4>{esc(S["moment"])}</h4>' + figs[0])
        figs = figs[1:]
    if figs:
        out.append('<div class="frames">' + "".join(figs) + "</div>")
    for rel in evidence:
        kind = classify(rel)
        full = root / rel
        size = full.stat().st_size if full.exists() else 0
        if kind in ("video", "trace", "other"):
            ctx.files_not_embedded.append((kind, rel, human_bytes(size) if size else S["missing"]))
        elif kind == "text":
            if not full.exists():
                continue
            if log_lines <= 0:
                ctx.files_not_embedded.append(("log", rel, human_bytes(size)))
                continue
            text = full.read_text(encoding="utf-8", errors="replace")
            out.append(f'<details><summary>{esc(S["log"])}: {esc(Path(rel).name)}</summary>'
                       f'{pre(text, log_lines)}<div class="small muted"><code>{esc(rel)}</code></div></details>')
    media = [e for e in evidence if classify(e) in ("video", "trace")]
    if media:
        out.append('<div class="small">' + " &middot; ".join(
            f'{esc(classify(e))}: <code>{esc(e)}</code>' for e in media) + "</div>")
    return "".join(out)


def item_card(ctx: Ctx, item: dict, anchor: str, moment: str | None = None, skip_steps: bool = False) -> str:
    S = ctx.S
    status = item["status"]
    cls = {"PASS": "s-pass", "FAIL": "s-fail", "BLOCKED": "s-warn"}.get(status, "s-info")
    limit = ctx.plan[1] if status in ("FAIL", "BLOCKED") else ctx.plan[0]
    head = (f'<header><h3>{esc(item["label"])}</h3>{ctx.page.badge(status)} '
            f'<span class="small muted">{esc(item["category"])}</span></header>')
    meta = kv([
        (S["criterion"], esc(item.get("criterion_id") or "")),
        (S["requirement"], esc(item.get("requirement_id") if item.get("requirement_id") != "NOT_AVAILABLE" else "")),
        ("ID", f'<code>{esc(item["id"])}</code>'),
        (S["profile"], esc(item.get("profile_id") or "")), (S["route"], esc(item.get("route") or "")),
        (S["scopes"], esc(", ".join(item.get("scope_ids") or []))),
        (S["tester"], esc(item.get("tester") or "")), (S["tested_at"], esc(item.get("tested_at") or "")),
        (S["bug"], esc(item.get("bug_id") or "")), (S["finding"], esc(", ".join(item.get("finding_ids") or []))),
    ])
    body = [meta]
    if skip_steps:
        pass
    elif item.get("preconditions"):
        body.append(f'<h4>{esc(S["preconditions"])}</h4><p>{esc(redact(item["preconditions"]))}</p>')
    steps = item.get("steps_gherkin") or item.get("steps") or []
    if steps and not skip_steps:
        body.append(f'<h4>{esc(S["steps"])}</h4><ol class="steps">' +
                    "".join(f"<li>{esc(redact(str(s)))}</li>" for s in steps) + "</ol>")
    if item.get("expected") and not skip_steps:
        body.append(f'<h4>{esc(S["expected"])}</h4><p>{esc(redact(item["expected"]))}</p>')
    if item.get("actual"):
        body.append(f'<h4>{esc(S["actual"])}</h4>{pre(item["actual"], 40)}')
    ev = item.get("evidence") or []
    if ev:
        body.append(f'<h4>{esc(S["evidence"])}</h4>' + evidence_html(ctx, item["label"], ev, limit, moment))
    else:
        body.append(f'<p class="muted small">{esc(S["no_evidence"])}</p>')
    return f'<section class="item {cls}" id="{anchor}">{head}{"".join(body)}</section>'


def moment_shot(evidence: list[str]) -> str | None:
    images = [e for e in evidence if classify(e) == "image"]
    if not images:
        return None
    flagged = [e for e in images if re.search(r"(fail|error|erro|falha|exception)", Path(e).name, re.I)]
    return (flagged or images)[-1]


def scope_label(scope: dict) -> str:
    return "" if scope["type"] == "full" else qa_scope.slugify(scope["id"])


def page_title(S: dict, key: str, scope: dict) -> str:
    return " ".join(w for w in (S[key], scope_label(scope)) if w)


def header_html(ctx: Ctx, view: dict, manifest: dict, title: str, kind: str, extra: str = "") -> str:
    S, scope = ctx.S, view["scope"]
    ex = manifest.get("execution") or {}
    sub = esc(scope.get("title") or "") if not view["is_full"] else ""
    typ = f'<span class="badge b-info">{esc(scope["type"])}</span> ' if not view["is_full"] else ""
    return (f'<header><h1 id="top">{esc(title)}</h1>'
            f'<p class="muted">{typ}{sub} <span class="small">{esc(S["execution"])} <code>{esc(ex.get("execution_id", ""))}</code></span></p>'
            f'<p><span class="badge verdict {STATUS_CLASS.get(view["verdict"], "b-info")}">'
            f'{esc(S["verdict"])}: {esc(S.get(view["verdict"], view["verdict"]))}</span> {extra}</p></header>')


def nav_html(S: dict, entries: list[tuple[str, str]]) -> str:
    return '<nav class="nav" aria-label="sections">' + "".join(
        f'<a href="#{a}">{esc(t)}</a>' for a, t in entries) + "</nav>"


def summary_cards(S: dict, view: dict) -> str:
    c = view["counts"]
    sev = {s: sum(1 for f in view["findings"] if f.get("severity") == s) for s in SEVERITY_ORDER}
    cards = [("pass", c["PASS"], S["PASS"]), ("fail", c["FAIL"], S["FAIL"]), ("warn", c["BLOCKED"], S["BLOCKED"]),
             ("", c["NOT_EXECUTED"], S["NOT_EXECUTED"]), ("", c["NOT_APPLICABLE"], S["NOT_APPLICABLE"]),
             ("fail" if sum(sev.values()) else "", sum(sev.values()), S["findings"])]
    return '<div class="cards">' + "".join(
        f'<div class="card {cls}"><div class="n">{n}</div><div class="muted small">{esc(label)}</div></div>'
        for cls, n, label in cards) + "</div>"


def env_section(ctx: Ctx, manifest: dict, view: dict) -> str:
    S = ctx.S
    ex = manifest.get("execution") or {}
    env = ex.get("environment") or {}
    rows = [(S["execution"], f'<code>{esc(ex.get("execution_id", ""))}</code>'),
            ("Project", esc(ex.get("project", ""))), (S["branch"], esc(ex.get("branch", ""))),
            (S["commit"], esc(ex.get("commit", ""))), (S["base_url"], esc(ex.get("base_url", ""))),
            (S["browser"], esc(" ".join(x for x in (ex.get("browser"), ex.get("browser_version")) if x and x != "NOT_AVAILABLE"))),
            (S["executor"], esc(ex.get("executor", ""))), ("Framework", esc(ex.get("test_framework", ""))),
            ("Started", esc(ex.get("started_at", ""))), ("Finished", esc(ex.get("finished_at", ""))),
            (S["generated"], esc(dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))),
            ("Generator", f"qa_artifact_report {GENERATOR_VERSION}")]
    rows += [(k, esc(v)) for k, v in env.items()]
    if view["categories"]:
        rows.append((S["categories_filter"], esc(", ".join(view["categories"]))))
    return f'<h2 id="sec-env">{esc(S["environment"])}</h2>' + kv(rows)


def render_evidence(root: Path, manifest: dict, view: dict, S: dict, imgs: Imgs, plan: tuple, level: int,
                    budget: int, notes: list[str]) -> tuple[str, str, dict]:
    ctx = Ctx(root, S, imgs, plan, level)
    page = ctx.page
    scope = view["scope"]
    title = page_title(S, "title_evidence", scope)
    imgs.omitted.clear()
    counts = view["counts"]
    sections = [("sec-summary", S["summary"])]
    if not view["is_full"]:
        sections.append(("sec-scope", S["scope"]))
    if view["criteria"]:
        sections.append(("sec-criteria", S["criteria"]))
    sections += [("sec-coverage", S["coverage"])]
    reqs = requirement_rows(view)
    if reqs:
        sections.append(("sec-req", S["requirements"]))
    sections.append(("sec-results", S["results"]))
    if view["findings"]:
        sections.append(("sec-findings", S["findings"]))
    sections += [("sec-env", S["environment"])]

    page.add(header_html(ctx, view, manifest, title, "evidence",
                         extra=f'<span class="muted small">{esc(S["summary_counts"].format(passed=counts["PASS"], failed=counts["FAIL"], blocked=counts["BLOCKED"], ne=counts["NOT_EXECUTED"]))}</span>'))
    page.add(nav_html(S, sections))
    for n in notes:
        page.add(f'<p class="note">{n}</p>')
    page.add(f'<h2 id="sec-summary">{esc(S["summary"])}</h2>' + summary_cards(S, view))

    if not view["is_full"]:
        page.add(f'<h2 id="sec-scope">{esc(S["scope"])}</h2>' + kv([
            (S["type"], esc(scope["type"])), ("ID", f'<code>{esc(scope["id"])}</code>'),
            (S["title"], esc(scope.get("title", ""))), (S["source"], f'<code>{esc(scope.get("source") or "")}</code>'),
            (S["narrative"], esc(scope.get("narrative", ""))),
            (S["criteria"], str(len(scope.get("acceptance_criteria", [])))),
            (S["child_scopes"], esc(", ".join(c["id"] for c in scope.get("children", [])))),
        ]))

    shown_in_criteria: set[str] = set()
    if view["criteria"]:
        rows = []
        for n, c in enumerate(view["criteria"], 1):
            link = f'<a href="#ac-{n}">{esc(c["id"])}</a>'
            rows.append([link, esc(c.get("title", "")), page.badge(c["status"]),
                         str(sum(len(i.get("evidence") or []) for i in c["items"]))])
        page.add(f'<h2 id="sec-criteria">{esc(S["criteria"])}</h2>' +
                 table([S["criterion"], S["title"], S["status"], S["evidence"]], rows, num_cols=(3,)))

    cov = coverage_rows(view)
    page.add(f'<h2 id="sec-coverage">{esc(S["coverage"])}</h2>' + table(
        [S["category"], S["total"], S["executed"], S["PASS"], S["FAIL"], S["BLOCKED"], S["NOT_EXECUTED"], S["percent"]],
        [[esc(r["category"]), str(r["total"]), str(r["executed"]), str(r["PASS"]), str(r["FAIL"]),
          str(r["BLOCKED"]), str(r["NOT_EXECUTED"]), f'{r["percent"]}%'] for r in cov], num_cols=(1, 2, 3, 4, 5, 6, 7))
        if cov else f'<p class="muted">{esc(S["no_evidence"])}</p>')

    if reqs:
        page.add(f'<h2 id="sec-req">{esc(S["requirements"])}</h2>' + table(
            [S["requirement"], S["items"], S["PASS"], S["FAIL"], S["BLOCKED"], S["result"]],
            [[esc(r["requirement_id"]), str(r["scenarios"]), str(r["pass"]), str(r["fail"]), str(r["blocked"]),
              page.badge(r["result"])] for r in reqs], num_cols=(1, 2, 3, 4)))

    page.add(f'<h2 id="sec-results">{esc(S["results"])}</h2>')
    if view["criteria"]:
        for n, c in enumerate(view["criteria"], 1):
            head = (f'<section class="item {"s-pass" if c["status"] == "PASS" else "s-fail" if c["status"] == "FAIL" else "s-warn" if c["status"] == "BLOCKED" else "s-info"}" id="ac-{n}">'
                    f'<header><h3>{esc(c["id"])} &middot; {esc(c.get("title", ""))}</h3>{page.badge(c["status"])}</header>')
            steps = [f"{s['keyword']} {s['text']}" for s in c.get("steps", [])]
            if steps:
                head += '<ol class="steps">' + "".join(f"<li>{esc(redact(s))}</li>" for s in steps) + "</ol>"
            if not c["items"]:
                head += f'<p class="muted">{esc(S["no_criteria"])}</p>'
            page.add(head)
            for k, it in enumerate(c["items"], 1):
                shown_in_criteria.add(it["id"])
                page.add(item_card(ctx, it, ctx.next_id("item"), skip_steps=bool(c.get("steps")),
                                   moment=moment_shot(it.get("evidence") or []) if it["status"] == "FAIL" else None))
            page.add("</section>")

    rest = [i for i in view["items"] if i["id"] not in shown_in_criteria]
    cards = [i for i in rest if i["status"] in ("FAIL", "BLOCKED") or i.get("evidence") or i.get("steps")]
    compact = [i for i in rest if i not in cards]
    if view["criteria"] and rest:
        page.add(f'<h3>{esc(S["other_results"])}</h3>')
    for it in cards:
        page.add(item_card(ctx, it, ctx.next_id("item"), moment=moment_shot(it.get("evidence") or []) if it["status"] == "FAIL" else None))
    if compact:
        shown = compact[:1500]
        page.add(table([S["category"], "ID", S["title"], S["status"]], [
            [esc(i["category"]), f'<code>{esc(i["id"])}</code>', esc(i["label"]), page.badge(i["status"])] for i in shown]))
        if len(compact) > len(shown):
            page.add(f'<p class="muted small">+{len(compact) - len(shown)}</p>')
    if not view["items"]:
        page.add(f'<p class="muted">{esc(S["no_evidence"])}</p>')

    if view["findings"]:
        page.add(f'<h2 id="sec-findings">{esc(S["findings"])}</h2>' + table(
            ["ID", S["severity"], S["title"], S["category"], S["location"]],
            [[f'<code>{esc(f["id"])}</code>', page.sev(f.get("severity", "unrated")), esc(f.get("title", "")),
              esc(f.get("category", "")), esc(f.get("location") or "")] for f in view["findings"]]))

    page.add(env_section(ctx, manifest, view))
    tail = []
    if ctx.files_not_embedded:
        tail.append(f'<h2 id="sec-files">{esc(S["files"])}</h2>' + table(
            [S["type"], "Path", S["size"]], [[esc(k), f"<code>{esc(p)}</code>", esc(s)] for k, p, s in ctx.files_not_embedded]))
    if imgs.omitted:
        lis = "".join(f"<li><code>{esc(p)}</code> <span class=\"muted\">{esc(why)}</span></li>" for p, why in imgs.omitted[:200])
        more = f"<li>+{len(imgs.omitted) - 200}</li>" if len(imgs.omitted) > 200 else ""
        tail.append(f'<h2 id="sec-omitted">{esc(S["omitted"])}</h2><ul>{lis}{more}</ul>')
    for t in tail:
        page.add(t)
    info = {"images_embedded": page.embedded, "omitted": list(imgs.omitted),
            "files_not_embedded": ctx.files_not_embedded}
    return title, '<main class="wrap">' + "\n".join(page.parts) + "</main>", info


def render_failures(root: Path, manifest: dict, view: dict, S: dict, imgs: Imgs, plan: tuple, level: int,
                    budget: int, notes: list[str]) -> tuple[str, str, dict]:
    ctx = Ctx(root, S, imgs, plan, level)
    page = ctx.page
    scope = view["scope"]
    title = page_title(S, "title_failures", scope)
    imgs.omitted.clear()
    units = failure_units(view)
    sev_counts = {s: sum(1 for u in units if unit_severity(u) == s) for s in SEVERITY_ORDER + ["unrated"]}
    page.add(header_html(ctx, view, manifest, title, "failures",
                         extra=f'<span class="muted small">{len(units)} {esc(S["failures_count"])}</span>'))
    page.add(nav_html(S, [("sec-index", S["failures_title"]), ("sec-env", S["environment"])]))
    for n in notes:
        page.add(f'<p class="note">{n}</p>')
    cards = [("fail", len(units), S["failures_count"])] + [
        ("fail" if s in ("critical", "high") else "warn", sev_counts[s], s) for s in SEVERITY_ORDER if sev_counts[s]]
    page.add('<div class="cards">' + "".join(
        f'<div class="card {c}"><div class="n">{n}</div><div class="muted small">{esc(lab)}</div></div>' for c, n, lab in cards) + "</div>")
    rows = []
    for k, u in enumerate(units, 1):
        it = u["item"] or {}
        label = (u["findings"][0].get("title") if u["findings"] else None) or it.get("label") or "-"
        rows.append([f'<a href="#fail-{k}">F-{k}</a>', page.sev(unit_severity(u)), esc(label),
                     esc(it.get("criterion_id") or it.get("id") or ""), esc(it.get("category") or (u["findings"][0].get("category") if u["findings"] else ""))])
    page.add(f'<h2 id="sec-index">{esc(S["failures_title"])}</h2>' +
             table(["#", S["severity"], S["title"], S["criterion"], S["category"]], rows))
    for k, u in enumerate(units, 1):
        it = u["item"] or {}
        f0 = u["findings"][0] if u["findings"] else {}
        bug = u["bug"] or {}
        sev = unit_severity(u)
        title_text = f0.get("title") or it.get("label") or "-"
        evidence = list(it.get("evidence") or [])
        for f in u["findings"]:
            evidence += [e for e in (f.get("evidence") or []) if e not in evidence]
        body = [f'<header><h3>F-{k} &middot; {esc(title_text)}</h3>{page.sev(sev)}'
                f'{page.badge(it["status"]) if it.get("status") else ""}</header>']
        body.append(kv([
            (S["criterion"], esc(it.get("criterion_id") or "")),
            (S["requirement"], esc(it.get("requirement_id") if it.get("requirement_id") not in (None, "NOT_AVAILABLE") else "")),
            (S["classification"], esc(bug.get("classification") or "")),
            (S["category"], esc(it.get("category") or f0.get("category") or "")),
            (S["profile"], esc(it.get("profile_id") or f0.get("profile_id") or "")),
            (S["location"], esc(f0.get("location") or it.get("route") or "")),
        ]))
        observed = bug.get("observed_fact") or f0.get("actual") or it.get("actual") or ""
        body.append(f'<h4>{esc(S["error"])}</h4>' + (pre(observed, 40) if observed else '<p class="muted">-</p>'))
        expected = f0.get("expected") or it.get("expected") or ""
        if expected:
            body.append(f'<h4>{esc(S["expected"])}</h4><p>{esc(redact(expected))}</p>')
        if bug.get("technical_hypothesis"):
            body.append(f'<h4>{esc(S["hypothesis"])}</h4><p>{esc(redact(bug["technical_hypothesis"]))}</p>')
        repro = f0.get("reproduction") or ""
        steps = it.get("steps_gherkin") or it.get("steps") or []
        if repro or steps:
            body.append(f'<h4>{esc(S["reproduce"])}</h4>')
            if repro:
                body.append(pre(repro, 40))
            if steps:
                body.append('<ol class="steps">' + "".join(f"<li>{esc(redact(str(s)))}</li>" for s in steps) + "</ol>")
        for label, key in ((S["impact"], "impact"), (S["recommendation"], "recommendation")):
            if f0.get(key):
                body.append(f'<h4>{esc(label)}</h4><p>{esc(redact(f0[key]))}</p>')
        if evidence:
            body.append(f'<h4>{esc(S["evidence"])}</h4>' + evidence_html(
                ctx, title_text, evidence, ctx.plan[1], moment=moment_shot(evidence)))
        else:
            body.append(f'<p class="muted small">{esc(S["no_evidence"])}</p>')
        anchors = [("scope", scope["id"]), ("criterion", it.get("criterion_id")), ("scenario", it.get("id")),
                   ("finding", ", ".join(f["id"] for f in u["findings"])), ("bug", bug.get("bug_id") or it.get("bug_id"))]
        body.append(f'<h4>{esc(S["anchors"])}</h4>' + kv([(k2, f"<code>{esc(v)}</code>") for k2, v in anchors if v]))
        page.add(f'<section class="item s-fail" id="fail-{k}">{"".join(body)}</section>')
    page.add(env_section(ctx, manifest, view))
    if ctx.files_not_embedded:
        page.add(f'<h2 id="sec-files">{esc(S["files"])}</h2>' + table(
            [S["type"], "Path", S["size"]], [[esc(k), f"<code>{esc(p)}</code>", esc(s)] for k, p, s in ctx.files_not_embedded]))
    if imgs.omitted:
        lis = "".join(f"<li><code>{esc(p)}</code> <span class=\"muted\">{esc(why)}</span></li>" for p, why in imgs.omitted[:200])
        page.add(f'<h2 id="sec-omitted">{esc(S["omitted"])}</h2><ul>{lis}</ul>')
    info = {"images_embedded": page.embedded, "omitted": list(imgs.omitted), "failures": len(units),
            "files_not_embedded": ctx.files_not_embedded}
    return title, '<main class="wrap">' + "\n".join(page.parts) + "</main>", info


def wrap_document(title: str, body: str, lang: str, artifact: bool) -> str:
    """Artifact fragment (no document tags) or a complete standalone document."""
    if artifact:
        return f"<title>{esc(title)}</title>\n<style>\n{CSS}</style>\n{body}\n"
    return ("<!doctype html>\n<html lang=\"%s\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            "<title>%s</title>\n<style>\n%s</style>\n</head>\n<body>\n%s\n</body>\n</html>\n"
            % (esc(lang), esc(title), CSS, body))


def build_with_budget(renderer, root, manifest, view, S, imgs, budget, lang, artifact):
    chosen = None
    for level, plan in enumerate(LEVELS):
        notes = []
        if level:
            notes.append(esc(S["budget_note"].format(mb=f"{budget / 1048576:.0f}")))
        if Image is None:
            notes.append(esc(S["no_pillow"]))
        title, body, info = renderer(root, manifest, view, S, imgs, plan, level, budget, notes)
        doc = wrap_document(title, body, lang, artifact)
        size = len(doc.encode("utf-8"))
        info.update({"title": title, "bytes": size, "level": level, "over_budget": size > budget})
        chosen = (doc, info)
        if size <= budget:
            break
    return chosen


# ------------------------------------------------------------------- contract checker

class _Contract(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids: set[str] = set()
        self.hrefs: list[str] = []
        self.tags: list[str] = []
        self.external: list[str] = []
        self.table_outside_scroll = 0
        self._stack: list[tuple[str, str]] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.tags.append(tag)
        if a.get("id"):
            self.ids.add(a["id"])
        for k in ("src", "href", "action", "poster"):
            v = a.get(k)
            if not v:
                continue
            if v.startswith("#"):
                self.hrefs.append(v)
            elif v.startswith("data:image/"):
                continue
            else:
                self.external.append(f"{tag}[{k}]={v[:50]}")
        if tag == "table" and not any("tw" in c.split() for t, c in self._stack if t == "div"):
            self.table_outside_scroll += 1
        if tag not in ("img", "input", "meta", "br", "hr", "link"):
            self._stack.append((tag, a.get("class", "")))

    def handle_endtag(self, tag):
        for k in range(len(self._stack) - 1, -1, -1):
            if self._stack[k][0] == tag:
                del self._stack[k:]
                break


def check_artifact_html(text: str, budget: int = BUDGET_BYTES) -> list[str]:
    """Return the list of violations of the Artifact page contract (empty when it holds)."""
    problems: list[str] = []
    size = len(text.encode("utf-8"))
    if size > budget:
        problems.append(f"size {size} exceeds the budget {budget}")
    low = text.lower()
    for m in re.finditer(r"<(!doctype|html|head|body)\b", low):
        problems.append(f"contains the document tag <{m.group(1)}>")
    head = text[:8192]
    m = re.search(r"<title>(.*?)</title>", head, re.S)
    if not m:
        problems.append("no <title> within the first 8 KB")
    else:
        words = html.unescape(m.group(1)).split()
        if not 2 <= len(words) <= 4:
            problems.append(f"title has {len(words)} words (need 2 to 4): {m.group(1)!r}")
        if ":" in m.group(1) or " - " in m.group(1) or "—" in m.group(1):
            problems.append("title carries an explainer after a dash or colon")
    if "<script" in low:
        problems.append("contains a <script>")
    if re.search(r"@import|url\(\s*['\"]?https?:", low):
        problems.append("CSS pulls an external resource")
    if re.search(r"<link\b", low):
        problems.append("contains a <link>")
    if not re.search(r":root\s*\{[^}]*--bg:", text):
        problems.append("no color tokens on :root")
    if "@media (prefers-color-scheme: dark)" not in text or ':root:not([data-theme="light"])' not in text:
        problems.append("no prefers-color-scheme dark block guarded by :root:not([data-theme=\"light\"])")
    if ':root[data-theme="dark"]' not in text:
        problems.append('no :root[data-theme="dark"] block')
    if not re.search(r"body\s*\{[^}]*background:\s*var\(--bg\)", text):
        problems.append("body has no explicit background token")
    if not re.search(r"padding-inline:\s*16px", text):
        problems.append("no 16px side gutter")
    p = _Contract()
    p.feed(text)
    if p.external:
        problems.append("external resources: " + ", ".join(p.external[:5]))
    missing = [h for h in p.hrefs if h[1:] not in p.ids]
    if missing:
        problems.append("anchors without a target: " + ", ".join(missing[:5]))
    if p.table_outside_scroll:
        problems.append(f"{p.table_outside_scroll} table(s) outside an overflow-x container")
    return problems


def secrets_leaked(text: str) -> list[str]:
    """Patterns that must never survive into a page (used by tests and the selftest)."""
    bad = []
    for rx in (r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{12,}", r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.",
               r"(?i)password\s*=\s*(?!\*\*\*)[^\s<]{4,}", r"(?i)\"password\"\s*:\s*\"(?!\*\*\*)[^\"]{4,}"):
        for m in re.finditer(rx, text):
            bad.append(m.group(0)[:40])
    return bad


# --------------------------------------------------------------------------- outputs

def describe(S: dict, kind: str, view: dict, units: int = 0) -> str:
    scope = view["scope"]
    label = scope["id"] if not view["is_full"] else "the full scope"
    if kind == "failures":
        return S["desc_failures"].format(scope=label, count=units)
    c = view["counts"]
    return S["desc_evidence"].format(
        scope=label, verdict=S.get(view["verdict"], view["verdict"]),
        summary=S["summary_counts"].format(passed=c["PASS"], failed=c["FAIL"], blocked=c["BLOCKED"], ne=c["NOT_EXECUTED"]))


def _display_path(path: str, root: Path) -> str:
    """Project-relative path when possible, so versioned indexes never carry machine paths."""
    try:
        return Path(path).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path


def generate(root: Path, execution: str, scope_id: str | None, categories: list[str] | None, *,
             artifact: bool, standalone: bool, out_dir: Path | None, budget: int, lang: str) -> dict:
    root = Path(root).resolve()
    execution, manifest = find_manifest(root, execution)
    view = build_view(manifest, scope_id, categories)
    S = load_strings(lang)
    scope = view["scope"]
    imgs = Imgs()
    units = failure_units(view)
    has_failures = bool(units)
    exec_dir = root / "docs" / "qa" / "executions" / execution
    scope_dir = exec_dir / qa_scope.scope_dir_name(scope["id"])
    slug = qa_scope.slugify(scope["id"])
    result: dict = {"execution": execution, "scope": {k: scope.get(k) for k in ("type", "id", "title")},
                    "verdict": view["verdict"], "counts": view["counts"], "findings": len(view["findings"]),
                    "failures": len(units), "publish": [], "files": [], "failure_report": None,
                    "language": lang}
    scope_dir.mkdir(parents=True, exist_ok=True)
    (scope_dir / "scope.json").write_text(json.dumps(scope, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def emit(kind: str, renderer, as_artifact: bool) -> dict:
        doc, info = build_with_budget(renderer, root, manifest, view, S, imgs, budget, lang, as_artifact)
        if as_artifact:
            target_dir = out_dir or (root / ".qa" / "artifacts" / execution)
            target = target_dir / f"qa-{kind}-{slug}.html"
        else:
            target_dir = scope_dir
            target = scope_dir / ("evidence-report.html" if kind == "evidence" else "failure-report.html")
        target_dir.mkdir(parents=True, exist_ok=True)
        target.write_text(doc, encoding="utf-8")
        entry = {"kind": kind, "mode": "artifact" if as_artifact else "standalone",
                 "file_path": str(target), "title": info["title"], "bytes": info["bytes"],
                 "level": info["level"], "over_budget": info["over_budget"],
                 "images_embedded": info["images_embedded"], "omitted": [p for p, _ in info["omitted"]][:200]}
        if as_artifact:
            entry.update({"icon": "report" if kind == "evidence" else "bug",
                          "description": describe(S, kind, view, len(units))})
            result["publish"].append(entry)
        result["files"].append(entry)
        return entry

    modes = []
    if artifact:
        modes.append(True)
    if standalone or not artifact:
        modes.append(False)
    for as_artifact in modes:
        emit("evidence", render_evidence, as_artifact)
        stale_dir = (out_dir or (root / ".qa" / "artifacts" / execution)) if as_artifact else scope_dir
        stale = stale_dir / (f"qa-failures-{slug}.html" if as_artifact else "failure-report.html")
        if has_failures:
            emit("failures", render_failures, as_artifact)
        elif stale.exists():
            stale.unlink()
    if has_failures:
        result["failure_report"] = next(f["file_path"] for f in result["files"] if f["kind"] == "failures")
        result["message"] = f"{len(units)} failure(s) in scope {scope['id']}: failure report generated."
    else:
        result["message"] = f"No failures in scope {scope['id']}: no failure report generated."
    index = {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(), **{k: result[k] for k in (
        "execution", "scope", "verdict", "counts", "findings", "failures", "message", "language")},
        "files": [{**{k: v for k, v in f.items() if k != "omitted"}, "file_path": _display_path(f["file_path"], root)}
                  for f in result["files"]]}
    (scope_dir / "reports.json").write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    ledger = root / ".qa" / "artifacts"
    ledger.mkdir(parents=True, exist_ok=True)
    history = read_json(ledger / "index.json", []) or []
    history.append(index)
    (ledger / "index.json").write_text(json.dumps(history[-100:], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if artifact:
        plan_dir = out_dir or (root / ".qa" / "artifacts" / execution)
        plan_dir.mkdir(parents=True, exist_ok=True)
        plan = {k: result[k] for k in ("execution", "scope", "verdict", "failures", "message", "publish", "failure_report")}
        (plan_dir / "artifact-plan.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        result["plan"] = str(plan_dir / "artifact-plan.json")
    return result


# ----------------------------------------------------------------------- synthetic data

def _png(width: int, height: int, seed: int, label_bars: int = 3) -> bytes:
    """A small, valid PNG that looks like a screenshot: header bar, content blocks and a marker."""
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            if y < 28:
                px = (31, 111, 120)
            elif 60 < y < 100 and 24 < x < width - 24:
                px = (225, 232, 236)
            elif y > 130 and (x // 70 + y // 40 + seed) % 3 == 0 and x > 24:
                px = (200 + seed % 40, 215, 222)
            else:
                px = (245, 247, 248)
            row += bytes(px)
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


STORY_FIXTURE_EN = """---
epic: DEMO
title: Account access
---

# Account access

### US-DEMO-01 - Sign in with e-mail and password
**Persona:** member · **Priority:** Must

As a member, I want to sign in with my e-mail and password so that I can reach my area.

**Acceptance criteria**
```gherkin
Scenario: Valid sign in
  Given an active member with a correct password
  When the member submits the sign-in form
  Then the member lands on the home page
  And the session cookie is set

Scenario: Wrong password
  Given an active member
  When the member submits a wrong password
  Then the form shows "Invalid credentials"
```

### US-DEMO-02 - Reset a forgotten password
**Persona:** member · **Priority:** Should

As a member, I want to reset my password by e-mail so that I can recover access.

**Acceptance criteria**
```gherkin
Scenario: Request a reset link
  Given a registered e-mail address
  When the member asks for a reset link
  Then a confirmation is shown without revealing whether the address exists
```
"""


def make_fixture(root: Path, scenario: str = "failing") -> dict:
    """Build a docs/qa package on disk without any application, for tests and examples.

    The package holds two stories of one epic: US-DEMO-01 has a failing criterion (with a
    screenshot, a log, a finding and a bug), US-DEMO-02 passes cleanly. `scenario="full"`
    produces a full-scope execution instead (the same items, no scope filter).
    Returns {"execution_id", "root"}.
    """
    root = Path(root)
    exec_id = "exec-20261011T120000Z"
    ex_dir = root / "docs" / "qa" / "executions" / exec_id
    ev = root / "docs" / "qa" / "evidence" / exec_id
    (root / "docs" / "user-stories").mkdir(parents=True, exist_ok=True)
    story_path = root / "docs" / "user-stories" / "demo.md"
    story_path.write_text(STORY_FIXTURE_EN, encoding="utf-8")
    epic = qa_scope.resolve_scope(root, scope_type="epic", value="DEMO")
    scope = epic if scenario != "full" else qa_scope.full_scope()

    def put(rel: str, data: bytes) -> str:
        p = ev / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p.relative_to(root).as_posix()

    log_text = ("2026-10-11T12:00:01Z POST /api/login 401\nAuthorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl\n"
                "password=hunter2secret\nexpected redirect to /home but stayed on /login\n")
    shots_fail = [put("sign-in/step-1.png", _png(640, 360, 1)), put("sign-in/failure-moment.png", _png(640, 360, 7))]
    log_path = put("sign-in/console.log", log_text.encode())
    trace = put("sign-in/trace.zip", b"PK\x03\x04 fake trace")
    shot_ok = put("reset/final.png", _png(640, 360, 3))
    shot_ok2 = put("wrong/final.png", _png(640, 360, 5))
    crit = {c["id"]: c for c in epic["acceptance_criteria"]}
    ids = list(crit)

    def item(cid, status, evidence, actual, findings=(), bug=None, label=None):
        c = crit[cid]
        owner = c["story_id"]
        exe = qa_scope.executable_from_criterion(c)
        return {
            "id": f"scenario:criterion:{cid}", "category": "scenarios", "kind": "gherkin",
            "label": label or c["title"], "status": status, "profile_id": "member", "route": "/login",
            "scope_ids": [owner, "DEMO"] if scenario != "full" else [owner, "DEMO"],
            "requirement_id": owner, "criterion_id": cid, "origin": "acceptance-criterion",
            "source": "docs/user-stories/demo.md", "preconditions": exe["preconditions"],
            "steps": exe["steps"], "steps_gherkin": [f"{s['keyword']} {s['text']}" for s in c["steps"]],
            "expected": exe["expected"], "actual": actual, "evidence": list(evidence),
            "finding_ids": list(findings), "bug_id": bug, "tested_at": "2026-10-11T12:00:30+00:00",
            "tester": "claude", "orphan": False,
        }

    items = [
        item(ids[0], "FAIL", shots_fail + [log_path, trace],
             "After submitting valid credentials the page stayed on /login and showed a spinner; the API answered 401.",
             findings=["QA-F1"], bug="BUG-1"),
        item(ids[1], "PASS", [shot_ok2], "The form showed the message Invalid credentials."),
        item(ids[2], "PASS", [shot_ok], "A neutral confirmation was shown for known and unknown addresses."),
        {"id": "navigation:/login", "category": "navigation", "kind": "page", "label": "Login page",
         "status": "PASS", "profile_id": "member", "route": "/login", "scope_ids": ["US-DEMO-01", "DEMO"],
         "requirement_id": "NOT_AVAILABLE", "criterion_id": None, "steps": [], "steps_gherkin": [],
         "expected": "", "actual": "Page loads", "evidence": [], "finding_ids": [], "bug_id": None,
         "tested_at": "2026-10-11T12:00:10+00:00", "tester": "claude", "orphan": False, "preconditions": ""},
        {"id": "forms:/profile", "category": "forms", "kind": "form", "label": "Profile form (outside the stories)",
         "status": "FAIL", "profile_id": "member", "route": "/profile", "scope_ids": [],
         "requirement_id": "NOT_AVAILABLE", "criterion_id": None, "steps": [], "steps_gherkin": [],
         "expected": "", "actual": "Saving an empty name is accepted.", "evidence": [], "finding_ids": ["QA-F2"],
         "bug_id": None, "tested_at": "2026-10-11T12:00:40+00:00", "tester": "claude", "orphan": False, "preconditions": ""},
    ]
    findings = [
        {"id": "QA-F1", "title": "Valid sign in is rejected with 401", "severity": "high", "category": "scenarios",
         "scope_ids": ["US-DEMO-01", "DEMO"], "criterion_id": ids[0], "scenario_id": items[0]["id"],
         "location": "/login", "actual": "401 on POST /api/login with valid credentials",
         "expected": "Redirect to /home", "reproduction": "1. Open /login\n2. Fill valid e-mail and password\n3. Submit",
         "impact": "No member can sign in.", "recommendation": "Check the credential hash comparison.",
         "evidence": [shots_fail[1]]},
        {"id": "QA-F2", "title": "Empty profile name is accepted", "severity": "medium", "category": "forms",
         "scope_ids": [], "location": "/profile", "actual": "Saved", "expected": "Validation error",
         "reproduction": "Clear the name field and save", "impact": "Blank names in listings.",
         "recommendation": "Make the field required.", "evidence": []},
    ]
    bugs = [{"bug_id": "BUG-1", "scenario_id": items[0]["id"], "requirement_id": "US-DEMO-01",
             "classification": "PRODUCT_DEFECT", "severity": "high",
             "summary": "Valid credentials rejected", "observed_fact": "POST /api/login answered 401 for valid credentials.",
             "technical_hypothesis": "The password hash comparison may use the wrong salt.", "evidence": shots_fail,
             "retest_history": [], "scope_ids": ["US-DEMO-01", "DEMO"]}]
    execution = {"execution_id": exec_id, "project": "demo-app", "branch": "main", "commit": "0123abc",
                 "environment": {"stage": "local"}, "base_url": "http://localhost:3000",
                 "started_at": "2026-10-11T12:00:00+00:00", "finished_at": "2026-10-11T12:01:00+00:00",
                 "executor": "claude", "test_framework": "playwright", "browser": "chromium",
                 "browser_version": "128", "status": "COMPLETED",
                 "scope": {"type": scope["type"], "id": scope["id"], "title": scope.get("title", "")}}
    if scenario != "full":
        items = [i for i in items if "DEMO" in i["scope_ids"]]
        findings = [f for f in findings if "DEMO" in f["scope_ids"]]
    manifest = {"schema": "qa-squad/manifest/1", "generated_at": "2026-10-11T12:01:00+00:00", "execution": execution,
                "scope": scope, "items": items, "findings": findings, "bugs": bugs}
    ex_dir.mkdir(parents=True, exist_ok=True)
    (ex_dir / "execution.json").write_text(json.dumps(execution, indent=2) + "\n", encoding="utf-8")
    (ex_dir / "scope.json").write_text(json.dumps(scope, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (ex_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"execution_id": exec_id, "root": str(root)}


# -------------------------------------------------------------------------- selftest

def selftest() -> int:
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, bool(ok), detail))

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "failing"
        info = make_fixture(root, "failing")
        out = Path(tmp) / "out"
        r1 = generate(root, info["execution_id"], "US-DEMO-01", None, artifact=True, standalone=False,
                      out_dir=out, budget=BUDGET_BYTES, lang="en")
        ev = Path(r1["publish"][0]["file_path"]).read_text(encoding="utf-8")
        check("story with failure: failure report generated", r1["failure_report"] is not None)
        fr_text = Path(r1["failure_report"]).read_text(encoding="utf-8") if r1["failure_report"] else ""
        check("evidence page honours the Artifact contract", not check_artifact_html(ev), str(check_artifact_html(ev)))
        check("failure page honours the Artifact contract", not check_artifact_html(fr_text), str(check_artifact_html(fr_text)))
        check("secrets are masked", not secrets_leaked(ev + fr_text) and "hunter2secret" not in ev + fr_text)
        check("no foreign scope leaks in", "US-DEMO-02" not in fr_text and "Profile form" not in ev)
        r2 = generate(root, info["execution_id"], "US-DEMO-02", None, artifact=True, standalone=False,
                      out_dir=out, budget=BUDGET_BYTES, lang="en")
        check("clean story: no failure report", r2["failure_report"] is None and not (out / "qa-failures-US-DEMO-02.html").exists())
        check("clean story verdict", r2["verdict"] == "PASSED", r2["verdict"])
        r3 = generate(root, info["execution_id"], "current", None, artifact=False, standalone=True,
                      out_dir=None, budget=BUDGET_BYTES, lang="en")
        check("standalone mode writes complete documents",
              all(f["file_path"].endswith(".html") for f in r3["files"]) and
              Path(r3["files"][0]["file_path"]).read_text(encoding="utf-8").lower().startswith("<!doctype html>"))
        root2 = Path(tmp) / "full"
        info2 = make_fixture(root2, "full")
        r4 = generate(root2, info2["execution_id"], "current", None, artifact=True, standalone=False,
                      out_dir=Path(tmp) / "out2", budget=BUDGET_BYTES, lang="en")
        check("full scope lists items outside any story", "Profile form" in Path(r4["publish"][0]["file_path"]).read_text(encoding="utf-8"))
        r5 = generate(root, info["execution_id"], "US-DEMO-01", None, artifact=True, standalone=False,
                      out_dir=Path(tmp) / "out3", budget=12_000, lang="en")
        check("tiny budget degrades instead of failing", r5["publish"][0]["level"] > 0)
    failed = [c for c in checks if not c[1]]
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if not ok and detail else ""))
    print(f"qa_artifact_report selftest: {len(checks) - len(failed)}/{len(checks)} passed")
    return 1 if failed else 0


# -------------------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Generate the QA evidence and failure reports of one scope.")
    ap.add_argument("--execution", default="latest", help="execution ID, or 'latest' (default)")
    ap.add_argument("--scope", default="current",
                    help="scope ID to report on; 'current' (default) is the scope the execution ran with")
    ap.add_argument("--category", action="append", help="only these coverage categories (repeatable)")
    ap.add_argument("--artifact", action="store_true", help="emit Artifact fragments into --out-dir")
    ap.add_argument("--standalone", action="store_true",
                    help="emit complete HTML documents into the scope folder (default when --artifact is absent)")
    ap.add_argument("--no-artifact", action="store_true",
                    help="opt out of Artifact output: write standalone documents instead")
    ap.add_argument("--out-dir", help="where --artifact writes (default .qa/artifacts/<execution>/)")
    ap.add_argument("--root", default=os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    ap.add_argument("--lang", help="report language (default: settings; en or pt-BR)")
    ap.add_argument("--budget-mb", type=float, help="size budget per page in MB (max 12)")
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    ap.add_argument("--settings", action="store_true", help="print the resolved artifact settings and exit")
    ap.add_argument("--selftest", action="store_true", help="run the built-in checks and exit")
    ap.add_argument("--write-example", metavar="DIR",
                    help="write a synthetic package and its reports into DIR (used for examples/)")
    a = ap.parse_args(argv)

    root = Path(a.root).resolve()
    if a.selftest:
        return selftest()
    settings = qa_scope.artifact_settings(root, no_artifact=a.no_artifact)
    if a.settings:
        print(json.dumps(settings, indent=2))
        return 0
    lang = a.lang or settings["language"]
    budget = int(min(a.budget_mb or settings["budget_mb"], 12) * 1024 * 1024)

    if a.write_example:
        target = Path(a.write_example).resolve()
        if target.exists():
            shutil.rmtree(target)
        info = make_fixture(target / "project", "failing")
        res = {}
        for sid in ("US-DEMO-01", "US-DEMO-02"):
            res[sid] = generate(target / "project", info["execution_id"], sid, None, artifact=True,
                                standalone=True, out_dir=target / "artifacts", budget=budget, lang=lang)
        # Keep the example free of machine-local state: the run ledger and the absolute-path plan.
        shutil.rmtree(target / "project" / ".qa", ignore_errors=True)
        (target / "artifacts" / "artifact-plan.json").unlink(missing_ok=True)
        print(json.dumps({sid: r["message"] for sid, r in res.items()}, indent=2))
        return 0

    artifact = bool(a.artifact and settings["publish"])
    standalone = a.standalone or not artifact
    if a.artifact and not settings["publish"]:
        print(f"note: artifact output is disabled ({settings['reason']}); writing standalone documents.", file=sys.stderr)
    result = generate(root, a.execution, a.scope, a.category, artifact=artifact, standalone=standalone,
                      out_dir=Path(a.out_dir).resolve() if a.out_dir else None, budget=budget, lang=lang)
    over = [f for f in result["files"] if f["over_budget"]]
    if a.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"scope {result['scope']['id']}: verdict {result['verdict']}, {result['failures']} failure(s)")
        for f in result["files"]:
            print(f"  {f['kind']:<9} {f['mode']:<10} {f['bytes'] / 1048576:.2f} MB level {f['level']}  {f['file_path']}")
        print(result["message"])
        if result.get("plan"):
            print(f"plan: {result['plan']}")
    return 3 if over else 0


if __name__ == "__main__":
    sys.exit(main())
