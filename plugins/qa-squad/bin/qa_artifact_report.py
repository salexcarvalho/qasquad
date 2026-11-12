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

A third kind, `--goal-report`, renders the GOAL EVIDENCE report of `/qa-test-goal`: cover, executive
summary, per goal the verdict, oracle checks, video, a screenshot after every step and the failure
analysis, then the evidence files with SHA-256 and the acceptance block. It always writes a
standalone document (print-ready A4) next to the scope's data; `--pdf` prints it with headless
Chrome and `SHA256SUMS.txt` covers the report, the PDF, the videos and the screenshots. With
`--artifact` it also writes a fragment: videos are not embedded, they are listed as supporting
files in `artifact-plan.json` and referenced by relative path.

Everything is filtered by scope: a story's reports list only items tagged with that story.
Total size is kept under the budget (default 12 MB) by degrading in levels; whatever was left
out is listed on the page. Secrets are masked before anything is embedded.

Standard library only. Pillow is optional and only shrinks images.

Examples:
  qa_artifact_report.py --execution latest --scope current --artifact --out-dir "$SCRATCH"
  qa_artifact_report.py --execution exec-20261011T120000Z --scope US-A01-03 --standalone
  qa_artifact_report.py --execution latest --goal-report --pdf --artifact --out-dir "$SCRATCH"
  qa_artifact_report.py --settings
  qa_artifact_report.py --selftest
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import functools
import hashlib
import html
import io
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote

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
    "scope_full_label": "the full scope", "scope_full_title": "Full audit",
}


GOAL_STRINGS_EN = {
    "title_goal_evidence": "Goal Evidence",
    "INCONCLUSIVE": "INCONCLUSIVE",
    "report_title": "Test Evidence Report",
    "doc_class": "Goal-driven test evidence",
    "doc_eyebrow": "Goal-driven tests",
    "project": "Project",
    "system_url": "System / URL",
    "env_label": "Environment",
    "version_build": "Version / build",
    "start": "Start",
    "end": "End",
    "executor_agent": "Executor (agent and model)",
    "execution_id": "Execution ID",
    "total_duration": "Total duration",
    "scope_label": "Scope",
    "scope_goals": "{n} goal(s)",
    "overall": "Overall result of this execution",
    "pdf_note": "This PDF is generated from the same HTML as the report. Videos do not play in a PDF: each goal shows the opening frame, the file name, the duration and the SHA-256 hash. The files come with the evidence package.",
    "exec_summary": "Executive summary",
    "goals_passed_of": "{passed} of {total} goals passed",
    "summary_text": "{fail} failed and {inc} inconclusive. Inconclusive is never counted as passed.",
    "pass_rate": "pass rate",
    "total_duration_short": "total duration",
    "steps_stat": "steps, with {shots} screenshots and {videos} video(s)",
    "goals_run": "Goals executed",
    "col_id": "ID",
    "col_goal": "Goal",
    "col_verdict": "Verdict",
    "col_steps": "Steps",
    "col_duration": "Duration",
    "col_detail": "Detail",
    "see_evidence": "See evidence",
    "back_to_summary": "Back to summary",
    "how_verdict": "How the verdict is decided",
    "legend_pass": "Every success line of the oracle held and no forbidden state occurred.",
    "legend_fail": "A success line did not hold or a forbidden state occurred. The bug is recorded and linked.",
    "legend_inc": "The step budget ran out, or an impediment left the oracle without enough evidence. A human decision is needed.",
    "g_pass": "Passed",
    "g_fail": "Failed",
    "g_inc": "Inconclusive",
    "g_ne": "Not executed",
    "goal_n_of": "Goal {n} of {total}",
    "steps_used": "Steps used",
    "steps_of": "{used} of {budget} (budget)",
    "steps_only": "{used}",
    "window": "Window",
    "screenshots": "Screenshots",
    "one_per_step": "{n} (one per step)",
    "linked_bug": "Linked bug",
    "tracker_item": "Azure DevOps work item",
    "role_label": "Role",
    "entry_label": "Entry",
    "objective": "Goal",
    "oracle_title": "Success criteria and forbidden states",
    "oracle_pass": "Success criteria",
    "oracle_forbidden": "Forbidden states",
    "o_met": "Met",
    "o_not_met": "Not met",
    "o_not_occurred": "Did not occur",
    "o_violated": "Occurred (violated)",
    "o_unverified": "Not verified",
    "video_title": "Goal video",
    "video_unsupported": "This browser cannot play the video.",
    "video_print_note": "The video does not play in a PDF. See the file in the evidence package.",
    "video_not_embedded": "Video not published with this page ({reason}). The opening frame, file name and hash are listed instead.",
    "video_reason_size": "over the Artifact size limit",
    "video_reason_total": "publish size limit reached",
    "video_missing": "No video was recorded for this goal.",
    "video_poster_alt": "Opening frame of the video {name}",
    "timeline": "Step by step with evidence",
    "timeline_note": "One screenshot after every step. Select a thumbnail to enlarge it.",
    "step": "Step",
    "checked": "Checked",
    "target": "Target",
    "st_ok": "Completed",
    "st_bad": "Failed",
    "st_warn": "No progress",
    "no_steps": "No step was recorded for this goal.",
    "shot_missing": "screenshot not found",
    "shot_omitted": "image left out at this size level",
    "failure_analysis": "Failure analysis",
    "inc_reason": "Reason for the inconclusive result",
    "inc_note": "It cannot be said that the system failed. Confirm with the product owner and run again with the path described or a larger budget.",
    "expected_vs_observed": "Expected x Observed",
    "console_summary": "Browser console (summary)",
    "network_summary": "Network (summary)",
    "col_method": "Method",
    "col_url": "URL",
    "col_http": "Status",
    "col_ms": "Time (ms)",
    "bug_report_file": "Bug report file",
    "bug_severity": "Severity",
    "finding_only": "Finding recorded, no bug report yet",
    "annex_a": "Annex A - traceability",
    "annex_a_title": "Evidence files and integrity",
    "annex_a_note": "Each file has a SHA-256 hash computed when this report was generated. Recompute the hash and compare. The hashes of this document and of the PDF are in SHA256SUMS.txt, outside the document.",
    "col_file": "File",
    "col_kind": "Type",
    "col_size": "Size",
    "col_sha": "SHA-256",
    "kind_screenshot": "Screenshot",
    "kind_video": "Video",
    "kind_log": "Log",
    "kind_other": "Other",
    "annex_b": "Annex B - environment and acceptance",
    "annex_b_title": "Execution environment and acceptance",
    "viewport": "Viewport",
    "os_label": "Operating system",
    "tool_label": "Tool",
    "linked_bugs": "Linked bugs",
    "acceptance": "Acceptance",
    "acceptance_text": "I declare that I have reviewed the evidence in this report and record my acceptance, with the reservations noted for failed and inconclusive goals.",
    "qa_responsible": "QA responsible",
    "contract_inspector": "Contract inspector / manager",
    "sign_name": "Name",
    "sign_date": "Date",
    "sign_signature": "Signature",
    "page_word": "Page",
    "of_word": "of",
    "no_goals": "No goal was executed in this scope.",
    "desc_goal_evidence": "Goal evidence report for {scope}: {passed} of {total} goals passed, with a screenshot per step and one video per goal.",
}
STRINGS_EN.update(GOAL_STRINGS_EN)


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


def scope_display_title(S: dict, scope: dict) -> str:
    """Scope title for visible text; the built-in full scope is localized, user-given titles stay as written."""
    if scope.get("type") == "full":
        return S["scope_full_title"]
    return scope.get("title") or ""


def scope_display_label(S: dict, view: dict) -> str:
    return S["scope_full_label"] if view["is_full"] else view["scope"]["id"]


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


def wrap_document(title: str, body: str, lang: str, artifact: bool, css: str = CSS) -> str:
    """Artifact fragment (no document tags) or a complete standalone document."""
    if artifact:
        return f"<title>{esc(title)}</title>\n<style>\n{css}</style>\n{body}\n"
    return ("<!doctype html>\n<html lang=\"%s\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            "<title>%s</title>\n<style>\n%s</style>\n</head>\n<body>\n%s\n</body>\n</html>\n"
            % (esc(lang), esc(title), css, body))


def build_with_budget(renderer, root, manifest, view, S, imgs, budget, lang, artifact, *, levels=None, css=CSS):
    chosen = None
    for level, plan in enumerate(levels or LEVELS):
        notes = []
        if level:
            notes.append(esc(S["budget_note"].format(mb=f"{budget / 1048576:.0f}")))
        if Image is None:
            notes.append(esc(S["no_pillow"]))
        title, body, info = renderer(root, manifest, view, S, imgs, plan, level, budget, notes)
        doc = wrap_document(title, body, lang, artifact, css)
        size = len(doc.encode("utf-8"))
        info.update({"title": title, "bytes": size, "level": level, "over_budget": size > budget})
        chosen = (doc, info)
        if size <= budget:
            break
    return chosen


# ------------------------------------------------------------------- contract checker

class _Contract(HTMLParser):
    def __init__(self, allowed_files: set | None = None):
        super().__init__()
        self.allowed_files = allowed_files or set()
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
            elif v.startswith("data:image/") or self._listed_video(tag, k, v):
                continue
            else:
                self.external.append(f"{tag}[{k}]={v[:50]}")
        if tag == "table" and not any("tw" in c.split() for t, c in self._stack if t == "div"):
            self.table_outside_scroll += 1
        if tag not in ("img", "input", "meta", "br", "hr", "link"):
            self._stack.append((tag, a.get("class", "")))

    def _listed_video(self, tag: str, attr: str, value: str) -> bool:
        """A <video src> is allowed only when it names a video file published next to the page."""
        return (tag == "video" and attr == "src" and value in self.allowed_files
                and Path(value).suffix.lower() in PUBLISHABLE_VIDEO_EXT)

    def handle_endtag(self, tag):
        for k in range(len(self._stack) - 1, -1, -1):
            if self._stack[k][0] == tag:
                del self._stack[k:]
                break


def check_artifact_html(text: str, budget: int = BUDGET_BYTES, allowed_files: set | None = None) -> list[str]:
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
    p = _Contract(allowed_files)
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
    label = scope_display_label(S, view)
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


# ------------------------------------------------------- goal evidence report: model

K_STARTED, K_FINISHED, K_ENV, K_SHOT = "started_at", "finished_at", "environment", "screenshot"
K_STANDALONE, K_SUMS, K_OPASS, K_OFORB = "standalone", "sha256sums", "oracle_pass", "oracle_forbidden"
PLAN_FILE = "artifact-plan.json"
PW_DIR, PW_ENV = "ms-playwright", "PLAYWRIGHT_BROWSERS_PATH"
GOAL_PREFIX = "scenario:goal:"
SLUG_RE = re.compile(r"[A-Za-z0-9._-]{1,120}")
AZURE_ID_RE = re.compile(r"[0-9]{1,12}")
AZURE_EDIT_RE = re.compile(r"/edit/([0-9]{1,12})(?:[/?#]|$)")
STEP_NUM_RE = re.compile(r"-(\d{1,4})\.\w+$")
V_PASS, V_FAIL, V_INC, V_NE = "pass", "fail", "inc", "ne"
ST_OK, ST_BAD, ST_WARN = "ok", "bad", "warn"
ORACLE_NO, ORACLE_UNK = "no", "unk"
VERDICT_META = {V_PASS: ("PASS", "g_pass"), V_FAIL: ("FAIL", "g_fail"),
                V_INC: ("INCONCLUSIVE", "g_inc"), V_NE: ("NOT EXECUTED", "g_ne")}
STATUS_TO_VERDICT = {"PASS": V_PASS, "FAIL": V_FAIL, "BLOCKED": V_INC}
ICON_KEY = {V_PASS: V_PASS, V_FAIL: V_FAIL, V_INC: V_INC, V_NE: V_INC,
            ST_OK: V_PASS, ST_BAD: V_FAIL, ST_WARN: V_INC, ORACLE_NO: V_FAIL, ORACLE_UNK: V_INC}
STEP_OK_WORDS = {"ok", "pass", "passed", "done", "completed"}
STEP_BAD_WORDS = {"bad", "fail", "failed", "error"}
ORACLE_STATES = {ST_OK, ORACLE_NO, ORACLE_UNK}
ICONS = {
    V_PASS: '<svg class="ico" viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="8.25" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M6 10.4l2.8 2.8L14.2 7.4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    V_FAIL: '<svg class="ico" viewBox="0 0 20 20" aria-hidden="true"><path d="M6.6 2.5h6.8l4.1 4.1v6.8l-4.1 4.1H6.6l-4.1-4.1V6.6z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M7.2 7.2l5.6 5.6M12.8 7.2l-5.6 5.6" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
    V_INC: '<svg class="ico" viewBox="0 0 20 20" aria-hidden="true"><path d="M10 2.6l8 14H2z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M10 8v4M10 14.2v.1" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
}
GOAL_LEVELS = [(1100, 72, 60), (900, 65, 40), (720, 55, 30), (560, 45, 20), (420, 38, 10), (0, 0, 0)]
POSTER_WIDTH = 480
SHA_CHUNK = 1 << 20
VIDEO_PUBLISH_MAX = 15 * 1024 * 1024 - 1
VIDEO_PUBLISH_TOTAL = 50 * 1024 * 1024
PUBLISHABLE_VIDEO_EXT = {".webm", ".mp4"}
PUBLISH_VIDEO_DIR = "videos"
PDF_TIMEOUT_S = 180
SHA_SUMS_NAME = "SHA256SUMS.txt"
GOAL_REPORT_HTML = "goal-evidence-report.html"
GOAL_REPORT_PDF = "goal-evidence-report.pdf"
KIND_GOAL = "goal-evidence"
NO_VALUE = "\u2014"
SEP = " \u00b7 "


def sha256_file(path: Path, cache: dict) -> str:
    key = str(path)
    if key not in cache:
        digest = hashlib.sha256()
        try:
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(SHA_CHUNK), b""):
                    digest.update(chunk)
            cache[key] = digest.hexdigest()
        except OSError:
            cache[key] = ""
    return cache[key]


def short_hash(value: str) -> str:
    return f"{value[:12]}\u2026{value[-8:]}" if len(value) > 24 else value


def parse_ts(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def fmt_ts(value) -> str:
    ts = parse_ts(value)
    if ts is None:
        return str(value or "")
    off = ts.utcoffset()
    total = int(off.total_seconds()) if off else 0
    sign = "-" if total < 0 else "+"
    total = abs(total)
    zone = "UTC" if total == 0 else f"UTC{sign}{total // 3600:02d}:{total % 3600 // 60:02d}"
    return f"{ts.strftime('%Y-%m-%d %H:%M:%S')} {zone}"


def fmt_clock(value) -> str:
    ts = parse_ts(value)
    return ts.strftime("%H:%M:%S") if ts else str(value or "")


def fmt_dur(seconds) -> str:
    if seconds is None:
        return ""
    whole = int(round(seconds))
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def span_seconds(start, end):
    a, b = parse_ts(start), parse_ts(end)
    if a is None or b is None:
        return None
    try:
        delta = (b - a).total_seconds()
    except TypeError:
        return None
    return delta if delta >= 0 else None


def as_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v or "").strip()]
    if isinstance(value, str):
        return [ln.strip() for ln in value.splitlines() if ln.strip()]
    return []


def local_file(root: Path, rel) -> Path | None:
    """A file under the project root, or None (never follows a path out of the project)."""
    if not rel or not isinstance(rel, str):
        return None
    path = Path(rel)
    path = path if path.is_absolute() else root / path
    try:
        path = path.resolve()
        path.relative_to(root)
    except (OSError, ValueError):
        return None
    return path if path.is_file() else None


def tracker_template(root: Path) -> str:
    cfg = read_json(root / ".qa" / "config.json", {}) or {}
    tracker = cfg.get("tracker") if isinstance(cfg, dict) else None
    value = tracker.get("azure_work_item_url") if isinstance(tracker, dict) else ""
    return value if isinstance(value, str) else ""


def split_tracker(raw) -> tuple[str, str]:
    if isinstance(raw, dict):
        return str(raw.get("id") or ""), str(raw.get("url") or "")
    text = str(raw or "").strip()
    return ("", text) if text.lower().startswith("https://") else (text, "")


def tracker_ref(raw, template: str) -> dict | None:
    """Azure DevOps work item of a goal: an id, an https URL, or {id, url}. Anything else is ignored."""
    wid, url = split_tracker(raw)
    url = url if url.lower().startswith("https://") else ""
    found = AZURE_EDIT_RE.search(url)
    wid = wid if AZURE_ID_RE.fullmatch(wid) else (found.group(1) if found else "")
    if not url and wid and template.startswith("https://") and "{id}" in template:
        url = template.replace("{id}", wid)
    return {"id": wid, "url": url} if (wid or url) else None


def step_status(raw) -> str:
    word = str(raw or ST_OK).lower()
    if word in STEP_OK_WORDS:
        return ST_OK
    return ST_BAD if word in STEP_BAD_WORDS else ST_WARN


def target_text(st: dict) -> str:
    name = f'"{st["name"]}"' if st.get("name") else ""
    return " ".join(str(p) for p in (st.get("role"), name) if p)


def action_text(st: dict) -> str:
    if st.get("label"):
        return str(st["label"])
    return " ".join(str(p) for p in (st.get("action"), target_text(st), st.get("value")) if p)


def resolve_media(root: Path, recorded, index: dict) -> Path | None:
    """The copy of a recorded file kept in the execution evidence, else the recorded path itself."""
    if not recorded or not isinstance(recorded, str):
        return None
    kept = index.get(Path(recorded).name)
    return local_file(root, kept) if kept else local_file(root, recorded)


def build_step(root: Path, st: dict, n: int, index: dict, cache: dict) -> dict:
    shot = resolve_media(root, st.get(K_SHOT), index)
    return {"n": n, "action": action_text(st) or f"#{n}", "target": target_text(st),
            "checked": str(st.get("checked") or st.get("expect") or ""), "time": fmt_clock(st.get("time")),
            "status": step_status(st.get("status")), "shot": shot,
            "shot_name": Path(str(st[K_SHOT])).name if st.get(K_SHOT) else "",
            "size": shot.stat().st_size if shot else 0, "sha": sha256_file(shot, cache) if shot else ""}


def fallback_steps(root: Path, item: dict, index: dict, cache: dict) -> list[dict]:
    """Steps from the scenario's own step list when the goal file carries no trace."""
    by_n = {}
    for rel in item.get("evidence") or []:
        found = STEP_NUM_RE.search(rel)
        if found and classify(rel) == "image":
            by_n.setdefault(int(found.group(1)), rel)
    out = []
    for k, text in enumerate(item.get("steps") or [], 1):
        out.append(build_step(root, {"label": str(text), K_SHOT: by_n.get(k)}, k, index, cache))
    return out


def build_videos(root: Path, item: dict, run: dict, cache: dict) -> list[dict]:
    meta = run.get("video") if isinstance(run.get("video"), dict) else {}
    extra = {Path(str(e.get("path", ""))).name: e for e in (meta.get("extra") or []) if isinstance(e, dict)}
    primary = Path(str(meta.get("path", ""))).name
    paths = [local_file(root, e) for e in item.get("evidence") or [] if classify(e) == "video"]
    paths = [p for p in paths if p]
    if not paths and meta.get("path") and local_file(root, meta.get("path")):
        paths = [local_file(root, meta["path"])]
    paths.sort(key=lambda p: (p.name != primary, p.name))
    out = []
    for p in paths:
        info = meta if p.name == primary else extra.get(p.name, {})
        out.append({"name": p.name, "path": p, "size": p.stat().st_size, "sha": sha256_file(p, cache),
                    "duration": info.get("duration_s"), "published": None, "src": None, "skip": ""})
    return out


def oracle_lines(texts: list[str], results, default: str) -> list[dict]:
    results = results if isinstance(results, list) else []
    out = []
    for k, text in enumerate(texts):
        res = results[k] if k < len(results) and isinstance(results[k], dict) else {}
        state = res.get("state") if res.get("state") in ORACLE_STATES else default
        out.append({"text": text, "state": state, "ev": str(res.get("evidence") or "")})
    return out


def goal_bug(root: Path, item: dict, view: dict) -> dict:
    bug = next((b for b in view["bugs"] if b.get("bug_id") == item.get("bug_id")
                or b.get("scenario_id") == item["id"]), None)
    finding = next((f for f in view["findings"] if f["id"] in (item.get("finding_ids") or [])
                    or f.get("scenario_id") == item["id"]), None)
    bug_id = str((bug or {}).get("bug_id") or "")
    bug_file = local_file(root, f"docs/qa/bugs/{bug_id}/BUG-REPORT.md") if SLUG_RE.fullmatch(bug_id) else None
    severity = (bug or {}).get("severity") or (finding or {}).get("severity") or ""
    return {"bug": bug, "finding": finding, "bug_file": bug_file, "severity": severity}


def goal_run(goal: dict, execution_id: str) -> dict:
    run = goal.get("last_run")
    return run if isinstance(run, dict) and run.get("execution") == execution_id else {}


def as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def first_text(*values) -> str:
    return next((str(v) for v in values if v), "")


def load_goal_file(root: Path, slug: str) -> dict:
    return as_dict(read_json(root / ".qa" / "goals" / f"{slug}.json", {})) if SLUG_RE.fullmatch(slug) else {}


def goal_steps(root: Path, item: dict, goal: dict, run: dict, cache: dict) -> list[dict]:
    index = {Path(e).name: e for e in reversed(item.get("evidence") or [])}
    trace = run.get("trace") or goal.get("trace") or []
    steps = [build_step(root, st, k, index, cache) for k, st in enumerate(trace, 1) if isinstance(st, dict)]
    return steps or fallback_steps(root, item, index, cache)


def goal_oracle(goal: dict, run: dict, item: dict, verdict: str) -> tuple[list[dict], list[dict], list[str]]:
    oracle, ores = as_dict(goal.get("oracle")), as_dict(run.get("oracle_results"))
    default = ST_OK if verdict == V_PASS else ORACLE_UNK
    pass_lines = as_list(oracle.get("pass")) or as_list(item.get("expected"))
    return (oracle_lines(pass_lines, ores.get("pass"), default),
            oracle_lines(as_list(oracle.get("forbidden")), ores.get("forbidden"), default), pass_lines)


def build_goal(root: Path, item: dict, n: int, ctx_info: dict) -> dict:
    """Everything the report shows about one goal, read from the manifest item and the goal file."""
    ex, view = ctx_info["execution"], ctx_info["view"]
    slug = item["id"][len(GOAL_PREFIX):]
    goal = load_goal_file(root, slug)
    run = goal_run(goal, ex.get("execution_id", ""))
    verdict = STATUS_TO_VERDICT.get(item["status"], V_NE)
    oracle_pass, oracle_forbidden, pass_lines = goal_oracle(goal, run, item, verdict)
    videos = build_videos(root, item, run, ctx_info["cache"])
    duration = span_seconds(run.get(K_STARTED), run.get(K_FINISHED))
    if duration is None and videos:
        duration = videos[0]["duration"]
    ref = goal.get("azure_work_item", as_dict(ex.get(K_ENV)).get("azure_work_item"))
    return {
        "n": n, "code": f"G-{n:02d}", "slug": slug, "item": item, "verdict": verdict,
        "title": first_text(goal.get("goal"), item.get("label"), slug),
        "role": first_text(goal.get("role"), item.get("profile_id")),
        "entry": first_text(goal.get("entry"), item.get("route")),
        "pre": as_list(goal.get("preconditions") or item.get("preconditions")),
        K_OPASS: oracle_pass, K_OFORB: oracle_forbidden,
        "budget": goal.get("max_steps"), "steps": goal_steps(root, item, goal, run, ctx_info["cache"]),
        "videos": videos, "start": run.get(K_STARTED), "end": run.get(K_FINISHED), "duration": duration,
        "expected": first_text(run.get("expected"), "; ".join(pass_lines)),
        "observed": first_text(run.get("observed"), item.get("actual")),
        "console": as_list(run.get("console")), "network": [r for r in (run.get("network") or []) if isinstance(r, dict)],
        "env": as_dict(run.get(K_ENV)), "azure": tracker_ref(ref, ctx_info["template"]),
        **goal_bug(root, item, view),
    }


def goal_files(g: dict, root: Path, cache: dict) -> list[Path]:
    """Every evidence file of a goal that exists on disk (screenshots, videos, logs, traces), once each."""
    seen: dict[str, Path] = {}
    for st in g["steps"]:
        if st["shot"]:
            seen.setdefault(str(st["shot"]), st["shot"])
    for v in g["videos"]:
        seen.setdefault(str(v["path"]), v["path"])
    for rel in g["item"].get("evidence") or []:
        p = local_file(root, rel)
        if p:
            seen.setdefault(str(p), p)
    return sorted(seen.values(), key=lambda p: p.as_posix())


def video_skip_reason(v: dict, total: int) -> str:
    if v["path"].suffix.lower() not in PUBLISHABLE_VIDEO_EXT or v["size"] > VIDEO_PUBLISH_MAX:
        return "video_reason_size"
    return "video_reason_total" if total + v["size"] > VIDEO_PUBLISH_TOTAL else ""


def plan_video_publication(goals: list[dict]) -> dict:
    """Decide which videos travel with an Artifact (relative paths) and which are only listed."""
    files: dict[str, str] = {}
    total = 0
    for g in goals:
        for v in g["videos"]:
            v["skip"] = video_skip_reason(v, total)
            if v["skip"]:
                continue
            safe = re.sub(r"[^A-Za-z0-9._-]", "_", v["name"])
            name = f"{PUBLISH_VIDEO_DIR}/{safe}"
            if name in files:
                name = f"{PUBLISH_VIDEO_DIR}/{g['slug']}-{safe}"
            files[name] = str(v["path"])
            v["published"] = name
            total += v["size"]
    return files


GOAL_TOKENS_LIGHT = (
    "--bg:#eef1f5;--surface:#ffffff;--fg:#14202b;--muted:#4a5a6a;--line:#d3dae2;--soft:#f3f5f8;"
    "--accent:#1d4f7c;--accent-fg:#ffffff;--focus:#0b5fd1;--overlay:rgba(5,10,15,.88);"
    "--pass:#12633a;--pass-bg:#e4f4ea;--pass-line:#8fcba6;"
    "--fail:#a31622;--fail-bg:#fbe8e9;--fail-line:#e3a0a5;"
    "--warn:#7d4a00;--warn-bg:#fdf1d6;--warn-line:#e2bd6a"
)
GOAL_TOKENS_DARK = (
    "--bg:#0e141a;--surface:#161f28;--fg:#e7edf3;--muted:#a6b4c2;--line:#2b3946;--soft:#1b2630;"
    "--accent:#8cbdea;--accent-fg:#0e141a;--focus:#8cbdea;--overlay:rgba(0,0,0,.92);"
    "--pass:#7bdba2;--pass-bg:#11301f;--pass-line:#2d6b48;"
    "--fail:#ff9ea6;--fail-bg:#3b1519;--fail-line:#7a3038;"
    "--warn:#f2c46b;--warn-bg:#36290c;--warn-line:#7d6322"
)

GOAL_CSS_BASE = """
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;padding-block:20px 48px;padding-inline:16px;background:var(--bg);color:var(--fg);font:400 15px/1.55 "IBM Plex Sans",system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;overflow-wrap:anywhere}
h1,h2,h3,h4,h5,p,dl,dd,ul,ol,figure,blockquote{margin:0;padding:0}
h1,h2,h3,h4{text-wrap:balance;line-height:1.25}
ul,ol{list-style:none}
a{color:var(--accent);text-underline-offset:2px}
a:focus-visible,summary:focus-visible,label:focus-visible,input:focus-visible+label{outline:3px solid var(--focus);outline-offset:2px}
code,.mono{font-family:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.875em}
.tnum{font-variant-numeric:tabular-nums}
.small,.muted{font-size:.8125rem;color:var(--muted)}
.print-only{display:none}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.stage{max-width:1040px;margin:0 auto;display:grid;gap:1.25rem}
.note{font-size:.8125rem;color:var(--warn);background:var(--warn-bg);border:1px solid var(--warn-line);padding:.55rem .8rem}
.sheet{background:var(--surface);border:1px solid var(--line);padding:clamp(1rem,3vw,2rem);display:flex;flex-direction:column;gap:1.1rem;min-width:0}
.sheet h2{font-size:1.5rem;font-weight:700}
.sheet h3{font-size:.8125rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);padding-bottom:.35rem;border-bottom:1px solid var(--line)}
.eyebrow{font-size:.75rem;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.sec{display:grid;gap:.6rem;min-width:0}
.backlink{font-size:.8125rem}
.v{display:inline-flex;align-items:center;gap:.45rem;padding:.3rem .7rem;border:1.5px solid currentColor;font-weight:700;letter-spacing:.05em;font-size:.875rem;line-height:1.2;white-space:nowrap}
.v span{font-weight:500;letter-spacing:0}
.v .ico{width:1.15em;height:1.15em;flex:none}
.v-pass{color:var(--pass);background:var(--pass-bg)}
.v-fail{color:var(--fail);background:var(--fail-bg)}
.v-inc{color:var(--warn);background:var(--warn-bg)}
.v.big{font-size:1.25rem;padding:.55rem 1rem}
.ico{width:1.1em;height:1.1em;flex:none}
.cover{gap:1.6rem}
.cover-top{display:flex;justify-content:space-between;gap:1rem;flex-wrap:wrap;align-items:flex-start}
.doc-class{font-size:.75rem;text-align:right;color:var(--muted);line-height:1.5;margin-left:auto}
.cover h1{font-size:clamp(1.7rem,4.5vw,2.5rem);font-weight:700;letter-spacing:-.01em}
.cover .sub{color:var(--muted);font-size:1.0625rem;margin-top:.35rem}
.meta{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));border-top:2px solid var(--fg)}
.meta>div{padding:.65rem .8rem .65rem 0;border-bottom:1px solid var(--line);min-width:0}
.meta>div.wide{grid-column:1/-1}
.meta dt,.facts dt{font-size:.6875rem;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.meta dd{font-size:.9375rem;overflow-wrap:anywhere}
.result-strip{display:flex;flex-wrap:wrap;gap:.6rem;align-items:center}
.result-strip p{font-size:.8125rem;color:var(--muted);flex-basis:100%}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(10.5rem,1fr));gap:.75rem}
.stat{border:1px solid var(--line);padding:.7rem .85rem;display:grid;gap:.15rem;min-width:0}
.stat b{font-size:1.75rem;line-height:1.1;font-weight:700;font-variant-numeric:tabular-nums}
.stat span{font-size:.8125rem;color:var(--muted)}
.stat.v-pass,.stat.v-fail,.stat.v-inc{border:1.5px solid currentColor;white-space:normal}
.stat.v-pass span,.stat.v-fail span,.stat.v-inc span{color:inherit;font-weight:600}
.stat .lbl{display:flex;align-items:center;gap:.4rem;font-weight:700;letter-spacing:.05em;font-size:.8125rem}
.bar{display:flex;height:2rem;border:1px solid var(--line);overflow:hidden}
.bar>div{display:flex;align-items:center;gap:.4rem;padding:0 .6rem;font-size:.8125rem;font-weight:700;white-space:nowrap;overflow:hidden}
.tw{overflow-x:auto;max-width:100%}
table{border-collapse:collapse;width:100%;font-size:.875rem}
th,td{text-align:left;padding:.55rem .6rem;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:.6875rem;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);background:var(--soft);border-bottom:1.5px solid var(--fg)}
td:first-child{white-space:nowrap}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.files .h{font-family:"IBM Plex Mono",ui-monospace,Menlo,Consolas,monospace;font-size:.6875rem;word-break:break-all;min-width:14rem}
.legend{display:grid;gap:.4rem;font-size:.8125rem;color:var(--muted)}
.legend li{display:flex;gap:.5rem;align-items:flex-start}
.legend .v{font-size:.6875rem;padding:.1rem .45rem;flex:none}
.goal-head{display:flex;justify-content:space-between;gap:1rem;flex-wrap:wrap;align-items:center;padding:1rem 1.1rem;border:1.5px solid currentColor}
.goal-head.v-pass{border-color:var(--pass-line)}.goal-head.v-fail{border-color:var(--fail-line)}.goal-head.v-inc{border-color:var(--warn-line)}
.goal-head>div{min-width:0;flex:1 1 16rem}
.goal-head h2{color:var(--fg)}
.goal-head .eyebrow{color:inherit}
.goal-head .v{background:var(--surface)}
.facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(9rem,1fr));gap:.5rem 1rem}
.facts dd{font-size:.9375rem;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
.objective{border-left:3px solid var(--accent);padding:.15rem 0 .15rem .9rem;font-size:1.0625rem;max-width:68ch}
.bullets{display:grid;gap:.3rem;font-size:.9375rem}
.bullets li{padding-left:1rem;position:relative}
.bullets li::before{content:"";position:absolute;left:.15rem;top:.62em;width:.35rem;height:.35rem;background:var(--muted)}
.oracle{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem}
.oracle h4{font-size:.9375rem;margin-bottom:.4rem}
.crit{display:grid;grid-template-columns:auto minmax(0,1fr);gap:.2rem .55rem;padding:.55rem .6rem;border:1px solid var(--line);align-items:start}
.crit+.crit{margin-top:.4rem}
.crit .ico{margin-top:.15rem}
.crit-text{font-size:.9375rem}
.crit-meta{grid-column:2;display:flex;flex-wrap:wrap;gap:.2rem .8rem;font-size:.75rem;color:var(--muted)}
.crit-state{font-weight:700;letter-spacing:.03em;text-transform:uppercase;font-size:.6875rem}
.st-ok .ico,.st-ok .crit-state{color:var(--pass)}
.st-no{background:var(--fail-bg);border:2px solid var(--fail)}
.st-no .ico,.st-no .crit-state{color:var(--fail)}
.st-no .crit-text{font-weight:600}
.st-unk{background:var(--warn-bg);border-color:var(--warn-line)}
.st-unk .ico,.st-unk .crit-state{color:var(--warn)}
.videos{display:grid;gap:1rem}
.video{display:grid;gap:.5rem}
.video-live{position:relative;background:#0b1117}
.video-live video{display:block;width:100%;max-width:100%;aspect-ratio:16/9;background:#0b1117;object-fit:contain}
.video-live.empty{padding:1rem;color:#e7edf3;font-size:.875rem}
.video-print{display:none;line-height:0;border:1px solid var(--line);background:#fff}
.video-print img{width:100%;height:auto;display:block}
.video figcaption{font-size:.8125rem;color:var(--muted);display:grid;gap:.15rem;min-width:0}
.video figcaption .mono{color:var(--fg);font-weight:500}
.hash{font-family:"IBM Plex Mono",ui-monospace,Menlo,Consolas,monospace;font-size:.6875rem;color:var(--muted);overflow-wrap:anywhere;word-break:break-all}
.callout{border:1px solid var(--line);padding:.9rem 1rem;display:grid;gap:.7rem;min-width:0}
.callout.fail{border-color:var(--fail-line);background:var(--fail-bg)}
.callout.inc{border-color:var(--warn-line);background:var(--warn-bg)}
.callout h4{font-size:1rem;display:flex;gap:.45rem;align-items:center}
.callout.fail h4{color:var(--fail)}.callout.inc h4{color:var(--warn)}
.cmp{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.75rem}
.cmp>div{background:var(--surface);border:1px solid var(--line);padding:.6rem .75rem;min-width:0}
.cmp h5{font-size:.6875rem;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin:0 0 .3rem}
.cmp .obt{border:2px solid var(--fail)}
pre{margin:0;padding:.6rem .75rem;background:var(--surface);border:1px solid var(--line);font:400 .75rem/1.55 "IBM Plex Mono",ui-monospace,Menlo,Consolas,monospace;white-space:pre-wrap;overflow-wrap:anywhere;color:var(--fg)}
.pill{font-family:"IBM Plex Mono",ui-monospace,Menlo,Consolas,monospace;font-size:.75rem;padding:.05rem .4rem;border:1px solid currentColor}
.bug-link{display:inline-flex;gap:.4rem;align-items:center;font-weight:700;flex-wrap:wrap}
.timeline{display:grid;gap:.9rem}
.step{display:grid;grid-template-columns:2.25rem minmax(0,1fr) minmax(0,17rem);gap:.4rem 1rem;padding:.8rem;border:1px solid var(--line);align-items:start}
.step.st-bad{border:2px solid var(--fail);background:var(--fail-bg)}
.step-n{width:2rem;height:2rem;border:1.5px solid var(--fg);display:grid;place-items:center;font-weight:700;font-variant-numeric:tabular-nums}
.step-body{display:grid;gap:.35rem;min-width:0}
.step-top{display:flex;gap:.6rem;justify-content:space-between;align-items:flex-start;flex-wrap:wrap}
.step-top h4{font-size:1rem;flex:1 1 14rem;min-width:0}
.chip{display:inline-flex;align-items:center;gap:.35rem;font-size:.75rem;font-weight:700;padding:.15rem .5rem;border:1.5px solid currentColor;white-space:nowrap}
.chip.ok{color:var(--pass);background:var(--pass-bg)}.chip.bad{color:var(--fail);background:var(--surface)}.chip.warn{color:var(--warn);background:var(--warn-bg)}
.step-check{font-size:.9375rem}
.step-meta{display:flex;flex-wrap:wrap;gap:.2rem 1rem;font-size:.8125rem;color:var(--muted)}
.step-shot{display:grid;gap:.3rem;min-width:0}
.shot-missing{border:1px dashed var(--muted);padding:.8rem;font-size:.75rem;color:var(--muted);text-align:center}
figure.shot{margin:0;position:relative;min-width:0}
figure.shot figcaption{font-size:.6875rem;color:var(--muted);margin-top:2px;overflow-wrap:anywhere}
figure.shot img{display:block;max-width:100%;width:100%;height:auto;border:1px solid var(--line);background:#fff}
.zoom{position:absolute;opacity:0;width:1px;height:1px;pointer-events:none}
figure.shot label{display:block;cursor:zoom-in;line-height:0}
.zoom:checked+label{position:fixed;inset:0;z-index:100;background:var(--overlay);display:flex;align-items:center;justify-content:center;padding:16px;cursor:zoom-out}
.zoom:checked+label img{max-width:100%;max-height:100%;width:auto;border:0}
.sign-group{display:grid;gap:.5rem}
.sign-group h4{font-size:.9375rem}
.sign{display:grid;grid-template-columns:2fr 1fr 2fr;gap:1.2rem}
.sign div{border-top:1.5px solid var(--fg);padding-top:.35rem;min-height:3.4rem;font-size:.75rem;font-weight:600;letter-spacing:.05em;text-transform:uppercase;color:var(--muted)}
@media (max-width:760px){
.step{grid-template-columns:2rem minmax(0,1fr)}
.step-shot{grid-column:1/-1}
.oracle,.cmp,.meta,.sign{grid-template-columns:1fr}
}
@media (prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}
"""

GOAL_CSS_PRINT = """
@media print{
:root:root:root{--bg:#fff;--surface:#ffffff;--fg:#14202b;--muted:#4a5a6a;--line:#d3dae2;--soft:#f3f5f8;--accent:#1d4f7c;--accent-fg:#fff;--focus:#0b5fd1;--pass:#12633a;--pass-bg:#e4f4ea;--pass-line:#8fcba6;--fail:#a31622;--fail-bg:#fbe8e9;--fail-line:#e3a0a5;--warn:#7d4a00;--warn-bg:#fdf1d6;--warn-line:#e2bd6a;color-scheme:light}
html{font-size:12px}
body{padding:0;font-size:12px;background:#fff}
*{-webkit-print-color-adjust:exact;print-color-adjust:exact}
.stage{display:block;max-width:none;margin:0}
.sheet{break-before:page;border:0;padding:0;gap:4mm;background:#fff}
.sheet:first-child{break-before:auto}
.sheet h2{font-size:1.5rem}
a{color:inherit;text-decoration:none}
.step,.crit,.callout,.stat,tr,.video,.sign-group{break-inside:avoid}
h2,h3,h4{break-after:avoid}
.timeline{grid-template-columns:repeat(2,minmax(0,1fr));gap:4mm}
.step{display:block;padding:3mm}
.step-n{display:inline-grid;width:1.7rem;height:1.7rem;margin-bottom:1.5mm}
.step-shot{margin-top:2mm}
figure.shot label{cursor:default}
.oracle,.cmp{grid-template-columns:1fr 1fr;gap:4mm}
.video{grid-template-columns:72mm minmax(0,1fr);gap:4mm;align-items:start}
.video-live{display:none!important}
.video-print{display:block}
.print-only{display:block}
.backlink{display:none}
.tw{overflow:visible}
.files .h{min-width:0}
.stats{grid-template-columns:repeat(3,minmax(0,1fr))}
.sign{grid-template-columns:2fr 1fr 2fr}
}
"""


# ------------------------------------------------------- goal evidence report: HTML

class GoalCtx(Ctx):
    """Build context of the goal report: standalone (relative video paths) or Artifact fragment."""

    def __init__(self, root: Path, S: dict, imgs: Imgs, plan: tuple, level: int, standalone: bool, html_dir: Path):
        super().__init__(root, S, imgs, plan, level)
        self.standalone = standalone
        self.html_dir = html_dir

    def rel_url(self, path: Path) -> str:
        return quote(Path(os.path.relpath(path, self.html_dir)).as_posix())


def css_string(text: str) -> str:
    """A CSS string literal that cannot break out of a <style> block."""
    clean = re.sub(r"[\r\n]+", " ", str(text)).replace("\\", "\\\\").replace('"', '\\"').replace("<", "\\3c ")
    return f'"{clean}"'


def goal_css(S: dict, footer: str) -> str:
    page_rule = (
        "@page{size:A4;margin:16mm 14mm 18mm 14mm;"
        f"@bottom-left{{content:{css_string(footer)};font:400 7.5pt Arial,sans-serif;color:#4a5a6a}}"
        f"@bottom-right{{content:{css_string(S['page_word'] + ' ')} counter(page) {css_string(' ' + S['of_word'] + ' ')} counter(pages);"
        "font:500 7.5pt Arial,sans-serif;color:#4a5a6a}}\n"
        "@page :first{@bottom-left{content:none}@bottom-right{content:none}}\n"
    )
    return (":root{" + GOAL_TOKENS_LIGHT + "}\n"
            "@media (prefers-color-scheme: dark){:root:not([data-theme=\"light\"]){" + GOAL_TOKENS_DARK + ";color-scheme:dark}}\n"
            ":root[data-theme=\"dark\"]{" + GOAL_TOKENS_DARK + ";color-scheme:dark}\n"
            + GOAL_CSS_BASE + GOAL_CSS_PRINT + page_rule)


def verdict_badge(S: dict, verdict: str, big: bool = False, suffix: str = "") -> str:
    code, word = VERDICT_META[verdict]
    cls = "inc" if verdict == V_NE else verdict
    size = " big" if big else ""
    return (f'<span class="v v-{cls}{size}">{ICONS[ICON_KEY[verdict]]}'
            f'<b>{esc(code)}</b><span>{esc(S[word] + suffix)}</span></span>')


def meta_dl(rows: list[tuple]) -> str:
    cells = []
    for r in rows:
        wide = ' class="wide"' if len(r) > 2 else ""
        cells.append(f"<div{wide}><dt>{esc(r[0])}</dt><dd>{esc(redact(str(r[1] or NO_VALUE)))}</dd></div>")
    return '<dl class="meta">' + "".join(cells) + "</dl>"


def pick_env(env: dict) -> str:
    for key in (K_ENV, "env", "stage", "name"):
        if env.get(key):
            return str(env[key])
    return ""


def version_text(ex: dict, env: dict) -> str:
    named = " ".join(str(env[k]) for k in ("version", "build") if env.get(k))
    known = [str(ex[k]) for k in ("branch", "commit") if ex.get(k) and ex[k] != "NOT_AVAILABLE"]
    commit = f"{known[0]}@{known[1][:8]}" if len(known) == 2 else ""
    return SEP.join(x for x in (named, commit) if x)


def goal_counts(goals: list[dict]) -> dict:
    counts = {V_PASS: 0, V_FAIL: 0, V_INC: 0, V_NE: 0}
    for g in goals:
        counts[g["verdict"]] += 1
    return counts


def total_seconds(ex: dict, goals: list[dict]):
    whole = span_seconds(ex.get(K_STARTED), ex.get(K_FINISHED))
    parts = [g["duration"] for g in goals if g["duration"] is not None]
    return whole if whole is not None else (sum(parts) if parts else None)


def cover_html(ctx: GoalCtx, ex: dict, view: dict, goals: list[dict]) -> str:
    S = ctx.S
    env = ex.get(K_ENV) or {}
    scope = view["scope"]
    roles = ", ".join(sorted({g["role"] for g in goals if g["role"]}))
    scope_text = SEP.join(x for x in (
        scope_display_title(S, scope) or ("" if view["is_full"] else scope["id"]),
        S["scope_goals"].format(n=len(goals)), roles) if x)
    rows = [(S["project"], ex.get("project")), (S["system_url"], ex.get("base_url")),
            (S["env_label"], pick_env(env)), (S["version_build"], version_text(ex, env)),
            (S["start"], fmt_ts(ex.get(K_STARTED))), (S["end"], fmt_ts(ex.get(K_FINISHED))),
            (S["execution_id"], ex.get("execution_id")), (S["total_duration"], fmt_dur(total_seconds(ex, goals))),
            (S["executor_agent"], ex.get("executor"), True), (S["scope_label"], scope_text, True)]
    counts = goal_counts(goals)
    strip = "".join(verdict_badge(S, v, suffix=f"{SEP}{counts[v]}")
                    for v in (V_PASS, V_FAIL, V_INC, V_NE) if counts[v] or v != V_NE)
    sub = SEP.join(x for x in (ex.get("project"), pick_env(env), version_text(ex, env)) if x)
    return (f'<section class="sheet cover" id="capa" aria-labelledby="t-capa"><div class="cover-top">'
            f'<p class="doc-class">{esc(S["doc_class"])}</p></div>'
            f'<div><p class="eyebrow">{esc(S["doc_eyebrow"])}{SEP}/qa-test-goal</p>'
            f'<h1 id="t-capa">{esc(S["report_title"])}</h1><p class="sub">{esc(redact(sub))}</p></div>'
            f'{meta_dl(rows)}<div class="result-strip"><p>{esc(S["overall"])}</p>{strip}</div>'
            f'<p class="small">{esc(S["pdf_note"])}</p></section>')


def sec_open(title: str) -> str:
    """Opening of a titled block; the caller closes the <div>."""
    return f'<div class="sec"><h3>{esc(title)}</h3>'


def stat_box(S: dict, verdict: str, n: int) -> str:
    code, word = VERDICT_META[verdict]
    cls = "inc" if verdict == V_NE else verdict
    return (f'<div class="stat v-{cls}"><span class="lbl">{ICONS[ICON_KEY[verdict]]}{esc(code)}</span>'
            f'<b>{n}</b><span>{esc(S[word])}</span></div>')


def summary_stats(ctx: GoalCtx, ex: dict, goals: list[dict], shown: list[str]) -> str:
    S = ctx.S
    counts = goal_counts(goals)
    total = len(goals)
    rate = f"{100 * counts[V_PASS] / total:.1f}%" if total else NO_VALUE
    steps = sum(len(g["steps"]) for g in goals)
    shots = sum(1 for g in goals for st in g["steps"] if st["shot"])
    videos = sum(len(g["videos"]) for g in goals)
    stats = "".join(stat_box(S, v, counts[v]) for v in shown)
    return stats + (
        f'<div class="stat"><b>{esc(rate)}</b><span>{esc(S["pass_rate"])} ({counts[V_PASS]}/{total})</span></div>'
        f'<div class="stat"><b>{esc(fmt_dur(total_seconds(ex, goals)) or NO_VALUE)}</b><span>{esc(S["total_duration_short"])}</span></div>'
        f'<div class="stat"><b>{steps}</b><span>{esc(S["steps_stat"].format(shots=shots, videos=videos))}</span></div>')


def summary_html(ctx: GoalCtx, ex: dict, goals: list[dict]) -> str:
    S = ctx.S
    counts = goal_counts(goals)
    shown = [v for v in (V_PASS, V_FAIL, V_INC, V_NE) if counts[v] or v != V_NE]
    bar = "".join(f'<div class="v-{"inc" if v == V_NE else v}" style="flex:{counts[v]}">{ICONS[ICON_KEY[v]]}'
                  f'{esc(VERDICT_META[v][0])}{SEP}{counts[v]}</div>' for v in shown if counts[v])
    rows = [[f'<b>{esc(g["code"])}</b>', esc(redact(g["title"])), verdict_badge(S, g["verdict"]),
             esc(steps_text(S, g)), esc(fmt_dur(g["duration"])),
             f'<a href="#g-{g["n"]}">{esc(S["see_evidence"])}</a>'] for g in goals]
    legend = "".join(f"<li>{verdict_badge(S, v)}<span>{esc(S[key])}</span></li>"
                     for v, key in ((V_PASS, "legend_pass"), (V_FAIL, "legend_fail"), (V_INC, "legend_inc")))
    headline = S["goals_passed_of"].format(passed=counts[V_PASS], total=len(goals))
    sentence = S["summary_text"].format(fail=counts[V_FAIL], inc=counts[V_INC] + counts[V_NE])
    table_html = (table([S["col_id"], S["col_goal"], S["col_verdict"], S["col_steps"], S["col_duration"], S["col_detail"]],
                        rows, num_cols=(3, 4)) if rows else f'<p class="muted">{esc(S["no_goals"])}</p>')
    return (f'<section class="sheet" id="resumo" aria-labelledby="t-resumo"><div><p class="eyebrow">{esc(S["exec_summary"])}</p>'
            f'<h2 id="t-resumo">{esc(headline)}</h2></div><p style="max-width:68ch">{esc(sentence)}</p>'
            f'<div class="stats">{summary_stats(ctx, ex, goals, shown)}</div>'
            f'<div class="bar" role="img" aria-label="{esc(headline)}">{bar}</div>'
            f'{sec_open(S["goals_run"])}{table_html}</div>'
            f'{sec_open(S["how_verdict"])}<ul class="legend">{legend}</ul></div></section>')


def steps_text(S: dict, g: dict) -> str:
    used = len(g["steps"])
    return S["steps_of"].format(used=used, budget=g["budget"]) if g["budget"] else S["steps_only"].format(used=used)


def crit_html(S: dict, line: dict, forbidden: bool) -> str:
    labels = {ST_OK: S["o_not_occurred"] if forbidden else S["o_met"],
              ORACLE_NO: S["o_violated"] if forbidden else S["o_not_met"], ORACLE_UNK: S["o_unverified"]}
    state = line["state"]
    meta = f"<span>{esc(redact(line['ev']))}</span>" if line["ev"] else ""
    return (f'<li class="crit st-{state}">{ICONS[ICON_KEY[state]]}<span class="crit-text">{esc(redact(line["text"]))}</span>'
            f'<span class="crit-meta"><span class="crit-state">{esc(labels[state])}</span>{meta}</span></li>')


def oracle_html(S: dict, g: dict) -> str:
    cols = ((S["oracle_pass"], g[K_OPASS], False), (S["oracle_forbidden"], g[K_OFORB], True))
    html_cols = "".join(f'<div><h4>{esc(title)}</h4><ul>{"".join(crit_html(S, ln, forb) for ln in lines)}</ul></div>'
                        for title, lines, forb in cols)
    return f'<div class="oracle">{html_cols}</div>'


def poster_uri(ctx: GoalCtx, g: dict) -> str | None:
    first = next((st["shot"] for st in g["steps"] if st["shot"]), None)
    if first is None or ctx.plan[0] <= 0:
        return None
    width, quality = min(ctx.plan[0], POSTER_WIDTH), max(30, ctx.plan[1] - 15)
    return ctx.imgs.encode(first, width, quality, 60_000)


def video_source(ctx: GoalCtx, v: dict) -> str | None:
    """The `src` of the player: a relative path next to the HTML, or the published Artifact path."""
    if ctx.standalone:
        return ctx.rel_url(v["path"])
    return v["published"]


def video_fig(ctx: GoalCtx, g: dict, v: dict, poster: str | None) -> str:
    S = ctx.S
    src = video_source(ctx, v)
    poster_attr = f' poster="{poster}"' if poster else ""
    if src:
        live = (f'<div class="video-live"><video controls preload="none" playsinline src="{esc(src)}"{poster_attr} '
                f'aria-label="{esc(v["name"])}">{esc(S["video_unsupported"])}</video></div>')
    else:
        reason = S.get(v["skip"], v["skip"])
        live = f'<div class="video-live empty">{esc(S["video_not_embedded"].format(reason=reason))}</div>'
        ctx.files_not_embedded.append((S["kind_video"], v["name"], human_bytes(v["size"])))
    frame = (f'<img src="{poster}" alt="{esc(S["video_poster_alt"].format(name=v["name"]))}">' if poster else "")
    dur = fmt_dur(v["duration"])
    head = SEP.join(x for x in (v["name"], dur, "sha256 " + short_hash(v["sha"])) if x)
    return (f'<figure class="video">{live}<div class="video-print">{frame}</div><figcaption>'
            f'<span class="mono">{esc(head)}</span><span>{esc(human_bytes(v["size"]))}</span>'
            f'<span class="hash">sha256 {esc(v["sha"])}</span>'
            f'<span class="print-only small">{esc(S["video_print_note"])}</span></figcaption></figure>')


def videos_html(ctx: GoalCtx, g: dict) -> str:
    if not g["videos"]:
        return f'<p class="muted small">{esc(ctx.S["video_missing"])}</p>'
    poster = poster_uri(ctx, g)
    return '<div class="videos">' + "".join(video_fig(ctx, g, v, poster) for v in g["videos"]) + "</div>"


def facts_html(ctx: GoalCtx, g: dict) -> str:
    S = ctx.S
    shots = sum(1 for st in g["steps"] if st["shot"])
    window = SEP.join(x for x in (fmt_clock(g["start"]), fmt_clock(g["end"])) if x)
    cells = [(S["steps_used"], steps_text(S, g)), (S["col_duration"], fmt_dur(g["duration"])),
             (S["window"], window.replace(SEP, " \u2192 ")), (S["screenshots"], S["one_per_step"].format(n=shots))]
    if g["role"]:
        cells.append((S["role_label"], g["role"]))
    html_cells = "".join(f"<div><dt>{esc(k)}</dt><dd>{esc(redact(v))}</dd></div>" for k, v in cells if v)
    html_cells += bug_fact(ctx, g) + tracker_fact(ctx, g)
    return f'<dl class="facts">{html_cells}</dl>'


def bug_fact(ctx: GoalCtx, g: dict) -> str:
    bug = g["bug"]
    if not bug:
        return ""
    ident = esc(bug["bug_id"])
    return f'<div><dt>{esc(ctx.S["linked_bug"])}</dt><dd><a href="#bug-{ident}">{ident}</a></dd></div>'


def tracker_fact(ctx: GoalCtx, g: dict) -> str:
    return f'<div><dt>{esc(ctx.S["tracker_item"])}</dt><dd>{tracker_link(ctx, g["azure"])}</dd></div>' if g["azure"] else ""


def tracker_link(ctx: GoalCtx, ref: dict) -> str:
    label = esc("#" + ref["id"] if ref["id"] else ref["url"])
    if ref["url"] and ctx.standalone:
        return f'<a href="{esc(ref["url"])}" rel="noopener">{label}</a>'
    return f"{label} <code>{esc(ref['url'])}</code>" if ref["url"] else label


def inconclusive_html(ctx: GoalCtx, g: dict) -> str:
    S = ctx.S
    return (f'<div class="callout inc"><h4>{ICONS[V_INC]}{esc(S["inc_reason"])}</h4>'
            f'<p>{esc(redact(g["observed"]))}</p><p class="small">{esc(S["inc_note"])}</p></div>')


def goal_overview(ctx: GoalCtx, g: dict, total: int) -> str:
    S = ctx.S
    cls = "inc" if g["verdict"] == V_NE else g["verdict"]
    head = (f'<header class="goal-head v-{cls}"><div><p class="eyebrow">{esc(g["code"])}{SEP}'
            f'{esc(S["goal_n_of"].format(n=g["n"], total=total))}</p>'
            f'<h2 id="g-{g["n"]}-h">{esc(redact(g["title"]))}</h2></div>{verdict_badge(S, g["verdict"], True)}</header>')
    pre = "".join(f"<li>{esc(redact(p))}</li>" for p in g["pre"])
    pre_html = f'{sec_open(S["preconditions"])}<ul class="bullets">{pre}</ul></div>' if pre else ""
    extra = inconclusive_html(ctx, g) if g["verdict"] == V_INC else ""
    return (f'<section class="sheet" id="g-{g["n"]}" aria-labelledby="g-{g["n"]}-h">'
            f'<a class="backlink" href="#resumo">{esc(S["back_to_summary"])}</a>{head}{facts_html(ctx, g)}'
            f'{sec_open(S["objective"])}<blockquote class="objective">{esc(redact(g["title"]))}</blockquote></div>'
            f'{pre_html}{sec_open(S["oracle_title"])}{oracle_html(S, g)}</div>'
            f'{sec_open(S["video_title"])}{videos_html(ctx, g)}</div>{extra}</section>')


def step_shot_html(ctx: GoalCtx, g: dict, st: dict) -> str:
    S = ctx.S
    width, quality, _ = ctx.plan
    if st["shot"] is None:
        return f'<div class="shot-missing">{esc(st["shot_name"] or S["shot_missing"])}<br>{esc(S["shot_missing"])}</div>'
    uri = ctx.imgs.encode(st["shot"], width, quality, max(40_000, 450_000 >> min(ctx.level, 3))) if width else None
    rel = st["shot"].relative_to(ctx.root).as_posix()
    cap = SEP.join((st["shot_name"], human_bytes(st["size"]), "sha256 " + short_hash(st["sha"])))
    if uri is None:
        ctx.imgs.omitted.append((rel, S["shot_omitted"]))
        return f'<div class="shot-missing">{esc(cap)}<br>{esc(S["shot_omitted"])}</div>'
    return ctx.page.figure(uri, cap, f'{g["code"]} {S["step"]} {st["n"]}: {redact(st["action"])}')


def step_html(ctx: GoalCtx, g: dict, st: dict) -> str:
    S = ctx.S
    chip_text = {ST_OK: S["st_ok"], ST_BAD: S["st_bad"], ST_WARN: S["st_warn"]}[st["status"]]
    chip = f'<span class="chip {st["status"]}">{ICONS[ICON_KEY[st["status"]]]}{esc(chip_text)}</span>'
    checked = f'<p class="step-check"><b>{esc(S["checked"])}:</b> {esc(redact(st["checked"]))}</p>' if st["checked"] else ""
    target = f'<span>{esc(S["target"])}: <code>{esc(redact(st["target"]))}</code></span>' if st["target"] else ""
    clock = f'<span class="mono tnum">{esc(st["time"])}</span>' if st["time"] else ""
    bad = " st-bad" if st["status"] == ST_BAD else ""
    return (f'<li class="step{bad}"><div class="step-n" aria-hidden="true">{st["n"]}</div><div class="step-body">'
            f'<div class="step-top"><h4><span class="sr">{esc(S["step"])} </span>{esc(redact(st["action"]))}</h4>{chip}</div>'
            f'{checked}<p class="step-meta">{clock}{target}</p></div>'
            f'<div class="step-shot">{step_shot_html(ctx, g, st)}</div></li>')


def steps_sheet(ctx: GoalCtx, g: dict) -> str:
    S = ctx.S
    body = "".join(step_html(ctx, g, st) for st in g["steps"])
    inner = f'<ol class="timeline">{body}</ol>' if body else f'<p class="muted">{esc(S["no_steps"])}</p>'
    return (f'<section class="sheet" id="g-{g["n"]}-steps" aria-label="{esc(g["code"])} {esc(S["timeline"])}">'
            f'<div><p class="eyebrow">{esc(g["code"])}{SEP}{esc(VERDICT_META[g["verdict"]][0])}</p><h2>{esc(S["timeline"])}</h2></div>'
            f'<p class="small">{esc(S["timeline_note"])}</p>{inner}</section>')


def network_table(S: dict, rows: list[dict]) -> str:
    cells = [[esc(r.get("method", "")), f'<span class="mono">{esc(redact(str(r.get("url", ""))))}</span>',
              f'<span class="pill">{esc(r.get("status", ""))}</span>', esc(r.get("ms", ""))] for r in rows[:50]]
    return table([S["col_method"], S["col_url"], S["col_http"], S["col_ms"]], cells, num_cols=(2, 3))


def bug_block(ctx: GoalCtx, g: dict) -> str:
    S = ctx.S
    lines = []
    bug, finding = g["bug"], g["finding"]
    sev = f"{SEP}{S['bug_severity']}: {g['severity']}" if g["severity"] else ""
    if bug:
        ident = esc(bug["bug_id"])
        lines.append(f'<p><span class="bug-link">{esc(S["linked_bug"])}: <a href="#bug-{ident}">{ident}</a></span> '
                     f'<span class="small">{esc(redact(str(bug.get("summary") or "")))}{esc(sev)}</span></p>')
        if g["bug_file"]:
            lines.append(f'<p class="small">{esc(S["bug_report_file"])}: {bug_file_ref(ctx, g["bug_file"])}</p>')
    elif finding:
        lines.append(f'<p class="small">{esc(S["finding_only"])}: <code>{esc(finding["id"])}</code>{esc(sev)}</p>')
    if g["azure"]:
        lines.append(f'<p class="small">{esc(S["tracker_item"])}: {tracker_link(ctx, g["azure"])}</p>')
    return "".join(lines)


def bug_file_ref(ctx: GoalCtx, path: Path) -> str:
    rel = path.relative_to(ctx.root).as_posix()
    if ctx.standalone:
        return f'<a href="{ctx.rel_url(path)}"><code>{esc(rel)}</code></a>'
    return f"<code>{esc(rel)}</code>"


def failure_sheet(ctx: GoalCtx, g: dict) -> str:
    S = ctx.S
    console = (f'<div><h5 class="small" style="margin:0 0 .3rem">{esc(S["console_summary"])}</h5>'
               f'{pre(chr(10).join(g["console"]), ctx.plan[2] or 10)}</div>') if g["console"] else ""
    net = (f'<div><h5 class="small" style="margin:0 0 .3rem">{esc(S["network_summary"])}</h5>'
           f'{network_table(S, g["network"])}</div>') if g["network"] else ""
    return (f'<section class="sheet" id="g-{g["n"]}-failure" aria-label="{esc(g["code"])} {esc(S["failure_analysis"])}">'
            f'<div><p class="eyebrow">{esc(g["code"])}{SEP}FAIL</p><h2>{esc(S["failure_analysis"])}</h2></div>'
            f'<div class="callout fail"><h4>{ICONS[V_FAIL]}{esc(S["expected_vs_observed"])}</h4><div class="cmp">'
            f'<div><h5>{esc(S["expected"])}</h5><p>{esc(redact(g["expected"]))}</p></div>'
            f'<div class="obt"><h5>{esc(S["observed"])}</h5><p>{esc(redact(g["observed"]))}</p></div></div>'
            f'{console}{net}{bug_block(ctx, g)}</div></section>')


def goal_sheets(ctx: GoalCtx, g: dict, total: int) -> str:
    out = goal_overview(ctx, g, total) + steps_sheet(ctx, g)
    return out + (failure_sheet(ctx, g) if g["verdict"] == V_FAIL else "")


def file_kind(S: dict, path: Path) -> str:
    kind = classify(path.name)
    return {"image": S["kind_screenshot"], "video": S["kind_video"], "text": S["kind_log"]}.get(kind, S["kind_other"])


def annex_a(ctx: GoalCtx, goals: list[dict], notes: list[str], files: list[Path], cache: dict) -> str:
    S = ctx.S
    rows = []
    for k, p in enumerate(files, 1):
        rel = p.relative_to(ctx.root).as_posix()
        rows.append([str(k), f'<span class="mono">{esc(rel)}</span>', f'<span style="white-space:nowrap">{esc(file_kind(S, p))}</span>',
                     esc(human_bytes(p.stat().st_size)), f'<span class="h">{esc(sha256_file(p, cache))}</span>'])
    note_html = "".join(f'<p class="note">{n}</p>' for n in notes)
    body = table(["#", S["col_file"], S["col_kind"], S["col_size"], S["col_sha"]], rows, num_cols=(0, 3))
    return (f'<section class="sheet" id="anexo-a" aria-labelledby="t-anexo-a"><div><p class="eyebrow">{esc(S["annex_a"])}</p>'
            f'<h2 id="t-anexo-a">{esc(S["annex_a_title"])}</h2></div>{note_html}'
            f'<p class="small" style="max-width:70ch">{esc(S["annex_a_note"])}</p><div class="files">{body}</div></section>')


def environment_rows(ctx: GoalCtx, ex: dict, goals: list[dict]) -> list[tuple]:
    S = ctx.S
    env = next((g["env"] for g in goals if g["env"]), {})
    browser = " ".join(x for x in (ex.get("browser"), ex.get("browser_version")) if x and x != "NOT_AVAILABLE")
    return [(S["browser"], env.get("browser") or browser), (S["viewport"], env.get("viewport")),
            (S["os_label"], env.get("os") or f"{platform.system()} {platform.release()}"),
            (S["tool_label"], f"qa-squad{SEP}qa_artifact_report {GENERATOR_VERSION}"),
            (S["base_url"], ex.get("base_url"))]


def bug_cards(ctx: GoalCtx, goals: list[dict]) -> str:
    S = ctx.S
    cards = []
    for g in goals:
        bug = g["bug"]
        if not bug:
            continue
        ident = esc(bug["bug_id"])
        detail = SEP.join(x for x in (S["bug_severity"] + ": " + g["severity"] if g["severity"] else "",
                                        str(bug.get("classification") or "")) if x)
        path = f'<p class="small">{esc(S["bug_report_file"])}: {bug_file_ref(ctx, g["bug_file"])}</p>' if g["bug_file"] else ""
        cards.append(f'<div class="callout" id="bug-{ident}" tabindex="-1"><h4>{ident}{SEP}{esc(redact(str(bug.get("summary") or "")))}</h4>'
                     f'<p class="small">{esc(detail)}</p>{path}</div>')
    return "".join(cards)


def signatory(S: dict, role: str) -> str:
    boxes = "".join(f"<div>{esc(S[k])}</div>" for k in ("sign_name", "sign_date", "sign_signature"))
    return f'<div class="sign-group"><h4>{esc(role)}</h4><div class="sign">{boxes}</div></div>'


def annex_b(ctx: GoalCtx, ex: dict, goals: list[dict]) -> str:
    S = ctx.S
    env = meta_dl(environment_rows(ctx, ex, goals))
    cards = bug_cards(ctx, goals)
    bugs = f'{sec_open(S["linked_bugs"])}{cards}</div>' if cards else ""
    sign = signatory(S, S["qa_responsible"]) + signatory(S, S["contract_inspector"])
    return (f'<section class="sheet" id="anexo-b" aria-labelledby="t-anexo-b"><div><p class="eyebrow">{esc(S["annex_b"])}</p>'
            f'<h2 id="t-anexo-b">{esc(S["annex_b_title"])}</h2></div>'
            f'<div class="sec"><h3>{esc(S["environment"])}</h3>{env}</div>{bugs}'
            f'{sec_open(S["acceptance"])}<p class="small" style="max-width:70ch">{esc(S["acceptance_text"])}</p>'
            f'{sign}</div></section>')


def render_goal_evidence(root: Path, manifest: dict, view: dict, S: dict, imgs: Imgs, plan: tuple, level: int,
                         budget: int, notes: list[str], *, goals: list[dict], opts: dict) -> tuple[str, str, dict]:
    ctx = GoalCtx(root, S, imgs, plan, level, opts[K_STANDALONE], opts["html_dir"])
    imgs.omitted.clear()
    ex = manifest.get("execution") or {}
    title = page_title(S, "title_goal_evidence", view["scope"])
    parts = [cover_html(ctx, ex, view, goals), summary_html(ctx, ex, goals)]
    parts += [goal_sheets(ctx, g, len(goals)) for g in goals]
    parts.append(annex_a(ctx, goals, notes, opts["files"], opts["cache"]))
    parts.append(annex_b(ctx, ex, goals))
    body = '<main class="stage">' + "\n".join(parts) + "</main>"
    info = {"images_embedded": ctx.page.embedded, "omitted": list(imgs.omitted),
            "files_not_embedded": ctx.files_not_embedded}
    return title, body, info


# ---------------------------------------------------------------------- PDF (headless Chrome)

CHROME_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                "microsoft-edge", "msedge", "chrome")
PLAYWRIGHT_BROWSER_GLOBS = (
    "chromium-*/chrome-linux*/chrome",
    "chromium_headless_shell-*/chrome-headless-shell-linux*/chrome-headless-shell",
    "chromium_headless_shell-*/chrome-linux*/headless_shell",
    "chromium-*/chrome-win*/chrome.exe",
    "chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium",
)
HEADLESS_SHELL_NAMES = ("chrome-headless-shell", "headless_shell")


def playwright_cache_dirs(env: dict) -> list[Path]:
    dirs = []
    if env.get(PW_ENV) and env[PW_ENV] != "0":
        dirs.append(Path(env[PW_ENV]))
    home = Path(env["HOME"]) if env.get("HOME") else Path.home()
    dirs += [home / ".cache" / PW_DIR, home / "Library" / "Caches" / PW_DIR]
    if env.get("LOCALAPPDATA"):
        dirs.append(Path(env["LOCALAPPDATA"]) / PW_DIR)
    return dirs


def find_chrome(env: dict | None = None) -> str | None:
    """A Chrome, Chromium or Edge binary: $CHROME_BIN, the PATH, then the Playwright browser cache."""
    env = os.environ if env is None else env
    explicit = env.get("CHROME_BIN")
    if explicit:
        found = shutil.which(explicit)
        return found or (explicit if Path(explicit).is_file() else None)
    for name in CHROME_NAMES:
        found = shutil.which(name, path=env.get("PATH"))
        if found:
            return found
    for cache in playwright_cache_dirs(env):
        for pattern in PLAYWRIGHT_BROWSER_GLOBS:
            hits = sorted(cache.glob(pattern), reverse=True)
            if hits:
                return str(hits[0])
    return None


def chrome_command(chrome: str, html_path: Path, pdf_path: Path, profile: str) -> list[str]:
    cmd = [chrome]
    if Path(chrome).name not in HEADLESS_SHELL_NAMES:
        cmd.append("--headless=new")
    cmd += ["--no-sandbox", "--disable-gpu", "--no-pdf-header-footer", f"--user-data-dir={profile}",
            f"--print-to-pdf={pdf_path}", html_path.resolve().as_uri()]
    return cmd


def pdf_from_html(html_path: Path, pdf_path: Path, chrome: str | None = None, env: dict | None = None,
                  timeout: int = PDF_TIMEOUT_S) -> dict:
    """Print an HTML file to an A4 PDF with headless Chrome. Never raises: the result says what happened."""
    chrome = chrome or find_chrome(env)
    if not chrome:
        return {"status": "skipped", "path": None,
                "reason": "no Chrome, Chromium or Edge found (set CHROME_BIN to a browser binary)"}
    pdf_path = Path(pdf_path)
    pdf_path.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory() as profile:
        try:
            proc = subprocess.run(chrome_command(chrome, Path(html_path), pdf_path, profile),
                                  capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"status": "failed", "path": None, "browser": chrome, "reason": f"{type(exc).__name__}: {exc}"}
    if not pdf_path.is_file() or pdf_path.stat().st_size == 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or [f"exit code {proc.returncode}"]
        return {"status": "failed", "path": None, "browser": chrome, "reason": tail[0][:200]}
    return {"status": "ok", "path": str(pdf_path), "browser": chrome, "reason": ""}


def write_sha256sums(target_dir: Path, paths: list[Path], cache: dict) -> Path:
    """`sha256sum -c` compatible list (paths relative to the folder that holds the file)."""
    lines = []
    for p in sorted({Path(x).resolve() for x in paths}, key=lambda x: x.as_posix()):
        digest = sha256_file(p, cache)
        if digest:
            lines.append(f"{digest}  {Path(os.path.relpath(p, target_dir)).as_posix()}")
    out = target_dir / SHA_SUMS_NAME
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


# ------------------------------------------------------------- goal evidence report: outputs

def goal_footer(ex: dict) -> str:
    env = pick_env(ex.get(K_ENV) or {})
    return SEP.join(x for x in (ex.get("project"), ex.get("execution_id"), env) if x)


def collect_goals(root: Path, manifest: dict, view: dict, cache: dict) -> list[dict]:
    info = {"cache": cache, "execution": manifest.get("execution") or {}, "view": view, "template": tracker_template(root)}
    items = [i for i in view["items"] if i["id"].startswith(GOAL_PREFIX)]
    return [build_goal(root, item, n, info) for n, item in enumerate(items, 1)]


def merge_artifact_plan(plan_path: Path, base: dict, entry: dict) -> dict:
    """Add the goal report to artifact-plan.json, keeping the entries the scope reports wrote."""
    plan = read_json(plan_path, None)
    plan = plan if isinstance(plan, dict) else dict(base, publish=[])
    plan["publish"] = [p for p in plan.get("publish", []) if p.get("kind") != KIND_GOAL] + [entry]
    plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return plan


def emit_goal_html(job: dict, as_artifact: bool, target: Path, video_files: dict) -> dict:
    """Render the goal report once (standalone document or Artifact fragment) and describe the file."""
    goals, view, S = job["goals"], job["view"], job["S"]
    opts = {K_STANDALONE: not as_artifact, "html_dir": target.parent, "files": job["files"], "cache": job["cache"]}
    renderer = functools.partial(render_goal_evidence, goals=goals, opts=opts)
    doc, info = build_with_budget(renderer, job["root"], job["manifest"], view, S, job["imgs"], job["budget"],
                                  job["lang"], as_artifact, levels=GOAL_LEVELS, css=job["css"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(doc, encoding="utf-8")
    entry = {"kind": KIND_GOAL, "mode": "artifact" if as_artifact else K_STANDALONE, "file_path": str(target),
             "title": info["title"], "bytes": info["bytes"], "level": info["level"],
             "over_budget": info["over_budget"], "images_embedded": info["images_embedded"],
             "omitted": [p for p, _ in info["omitted"]][:200]}
    if as_artifact:
        counts = job["counts"]
        label = scope_display_label(S, view)
        entry.update({
            "icon": "report", "files": video_files,
            "description": S["desc_goal_evidence"].format(scope=label, passed=counts[V_PASS], total=len(goals)),
            "videos_not_published": [{"name": v["name"], "sha256": v["sha"], "reason": v["skip"]}
                                     for g in goals for v in g["videos"] if not v["published"]],
            "contract": check_artifact_html(doc, job["budget"], allowed_files=set(video_files))})
    return entry


def goal_job(root: Path, execution: str, scope_id: str | None, categories: list[str] | None,
             budget: int, lang: str) -> dict:
    execution, manifest = find_manifest(root, execution)
    view = build_view(manifest, scope_id, categories)
    S = load_strings(lang)
    cache: dict = {}
    goals = collect_goals(root, manifest, view, cache)
    files = sorted({p for g in goals for p in goal_files(g, root, cache)}, key=lambda p: p.as_posix())
    return {"root": root, "execution": execution, "manifest": manifest, "view": view, "S": S, "cache": cache,
            "goals": goals, "files": files, "counts": goal_counts(goals), "budget": budget, "lang": lang,
            "imgs": Imgs(), "css": goal_css(S, goal_footer(manifest.get("execution") or {}))}


def generate_goal_report(root: Path, execution: str, scope_id: str | None, categories: list[str] | None, *,
                         artifact: bool, out_dir: Path | None, budget: int, lang: str, pdf: bool = False,
                         chrome: str | None = None) -> dict:
    """Goal evidence report: standalone HTML (+ PDF, SHA256SUMS.txt) and, optionally, the Artifact fragment."""
    root = Path(root).resolve()
    job = goal_job(root, execution, scope_id, categories, budget, lang)
    view, counts, execution = job["view"], job["counts"], job["execution"]
    scope_dir = root / "docs" / "qa" / "executions" / execution / qa_scope.scope_dir_name(view["scope"]["id"])
    scope_dir.mkdir(parents=True, exist_ok=True)
    result: dict = {"execution": execution, "kind": KIND_GOAL, "language": lang, "goals": len(job["goals"]),
                    "scope": {k: view["scope"].get(k) for k in ("type", "id", "title")}, "counts": counts,
                    "publish": [], "files": [], "pdf": None, K_SUMS: None}
    standalone = emit_goal_html(job, False, scope_dir / GOAL_REPORT_HTML, {})
    result["files"].append(standalone)
    sums = [Path(standalone["file_path"]), *job["files"]]
    if pdf:
        result["pdf"] = pdf_from_html(Path(standalone["file_path"]), scope_dir / GOAL_REPORT_PDF, chrome)
        sums += [Path(result["pdf"]["path"])] if result["pdf"]["status"] == "ok" else []
    result[K_SUMS] = str(write_sha256sums(scope_dir, sums, job["cache"]))
    if artifact:
        plan_dir = out_dir or root / ".qa" / "artifacts" / execution
        name = f"qa-goal-evidence-{qa_scope.slugify(view['scope']['id'])}.html"
        entry = emit_goal_html(job, True, plan_dir / name, plan_video_publication(job["goals"]))
        result["publish"].append(entry)
        result["files"].append(entry)
        base = {"execution": execution, "scope": result["scope"], "verdict": view["verdict"], "failures": 0,
                "message": "", "failure_report": None}
        merge_artifact_plan(plan_dir / PLAN_FILE, base, entry)
        result["plan"] = str(plan_dir / PLAN_FILE)
    result["message"] = (f"goal evidence: {len(job['goals'])} goal(s): {counts[V_PASS]} pass, "
                         f"{counts[V_FAIL]} fail, {counts[V_INC]} inconclusive.")
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

def run_goal_report(a, root: Path, artifact: bool, budget: int, lang: str) -> int:
    result = generate_goal_report(root, a.execution, a.scope, a.category, artifact=artifact,
                                  out_dir=Path(a.out_dir).resolve() if a.out_dir else None,
                                  budget=budget, lang=lang, pdf=a.pdf)
    if a.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"scope {result['scope']['id']}: {result['message']}")
        for f in result["files"]:
            print(f"  {f['mode']:<10} {f['bytes'] / 1048576:.2f} MB level {f['level']}  {f['file_path']}")
        print_pdf_line(result["pdf"])
        print(f"  sha256     {result['sha256sums']}")
        if result.get("plan"):
            print(f"plan: {result['plan']}")
    if result["pdf"] and result["pdf"]["status"] == "skipped":
        print(f"PDF skipped: {result['pdf']['reason']}", file=sys.stderr)
    return 3 if any(f["over_budget"] for f in result["files"]) else 0


def print_pdf_line(pdf: dict | None) -> None:
    if pdf and pdf["status"] == "ok":
        print(f"  pdf        {pdf['path']}")
    elif pdf:
        print(f"  pdf        {pdf['status']}: {pdf['reason']}")


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
    ap.add_argument("--goal-report", action="store_true",
                    help="render the goal evidence report of /qa-test-goal (screenshot per step, video per goal) "
                         "instead of the scope evidence and failure reports")
    ap.add_argument("--pdf", action="store_true",
                    help="with --goal-report: also print the report to an A4 PDF with headless Chrome "
                         "(skipped with one line when no Chrome, Chromium or Edge is found)")
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
    if a.pdf and not a.goal_report:
        ap.error("--pdf needs --goal-report")
    if a.goal_report:
        return run_goal_report(a, root, artifact, budget, lang)
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
