#!/usr/bin/env python3
"""Behavioral tests for the QA coverage CLI.

Uses explicit failure reporting rather than bare `assert`, so the suite keeps working
under `python3 -O`, where assert statements are stripped.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
CLI = PKG / "plugins" / "qa-squad" / "bin" / "qa-cli"

CORE = ["profiles", "navigation", "features", "forms", "workflows", "permissions", "scenarios"]
# Every core category except `scenarios`, which can never be declared empty.
DECLARABLE = [c for c in CORE if c != "scenarios"]


class Failure(Exception):
    pass


def check(condition, message):
    if not condition:
        raise Failure(message)


def run(root, *args):
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(root)
    return subprocess.run([sys.executable, str(CLI), *args], env=env, text=True, capture_output=True)


def status_json(root):
    p = run(root, "status", "--json")
    check(p.returncode == 0, f"status failed: {p.stderr}")
    return json.loads(p.stdout)


def complete_scenarios(root):
    """Scan for scenarios, then generate and execute one, as the scenario tester would."""
    p = run(root, "scenario-scan")
    check(p.returncode == 0, f"scenario-scan failed: {p.stderr}")
    run(root, "inventory-add", "--category", "scenarios", "--id", "scenario:generated:x",
        "--kind", "generated", "--label", "happy path")
    run(root, "record", "--category", "scenarios", "--id", "scenario:generated:x", "--status", "passed")


def test_happy_path():
    """A fully inventoried and fully executed audit reaches completion."""
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        p = run(r, "init", "--goal", "test")
        check(p.returncode == 0, f"init failed: {p.stderr}")
        for cat in CORE:
            p = run(r, "inventory-add", "--category", cat, "--id", f"{cat}:1", "--label", "one")
            check(p.returncode == 0, f"inventory-add {cat} failed: {p.stderr}")
        p = run(r, "mark-discovery-complete")
        check(p.returncode == 0, f"mark-discovery-complete failed: {p.stderr}")
        p = run(r, "scenario-scan")
        check(p.returncode == 0, f"scenario-scan failed: {p.stderr}")
        p = run(r, "validate")
        check(p.returncode != 0, "validate must fail before any result is recorded")
        for cat in CORE:
            p = run(r, "record", "--category", cat, "--id", f"{cat}:1", "--status", "passed")
            check(p.returncode == 0, f"record {cat} failed: {p.stderr}")
        p = run(r, "validate")
        check(p.returncode == 0, f"validate must pass once everything is executed: {p.stdout}{p.stderr}")
        p = run(r, "finish")
        check(p.returncode == 0, f"finish failed: {p.stderr}")


def test_empty_inventory_is_never_complete():
    """Regression: a zero-discovery audit must never report a false 100%.

    This is the defect the whole framework exists to prevent. An empty category used to
    report 100% coverage, which let an audit that discovered and tested nothing close as
    COMPLETE.
    """
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        run(r, "init", "--goal", "empty")
        run(r, "mark-discovery-complete", "--notes", "discovered nothing")
        data = status_json(r)
        check(data["complete"] is False, "empty inventory must not be complete")
        for cat in CORE:
            cov = data["categories"][cat]["coverage_percent"]
            check(cov == 0.0, f"empty category {cat} reported {cov}% instead of 0%")
        p = run(r, "validate")
        check(p.returncode != 0, "validate must fail on an empty inventory")
        p = run(r, "finish")
        check(p.returncode != 0, "finish must refuse to close a zero-discovery audit")


def test_declare_empty_is_the_only_escape():
    """An empty category counts only when explicitly and justifiably declared."""
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        run(r, "init", "--goal", "declare")
        for cat in DECLARABLE:
            p = run(r, "declare-empty", "--category", cat, "--notes", "nothing applicable here")
            check(p.returncode == 0, f"declare-empty {cat} failed: {p.stderr}")
        complete_scenarios(r)
        run(r, "mark-discovery-complete", "--notes", "all categories justified")
        p = run(r, "validate")
        check(p.returncode == 0, f"declared-empty audit should validate: {p.stdout}")
        # A declaration must be retired as soon as the category gains an item.
        run(r, "inventory-add", "--category", "forms", "--id", "forms:1", "--label", "login")
        p = run(r, "validate")
        check(p.returncode != 0, "adding an item must retire the declared-empty state")
        declared = json.loads((r / ".qa" / "declared-empty.json").read_text())
        check("forms" not in declared, "declared-empty entry was not retired")


def test_declare_empty_rejects_populated_category():
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        run(r, "init")
        run(r, "inventory-add", "--category", "forms", "--id", "forms:1", "--label", "x")
        p = run(r, "declare-empty", "--category", "forms", "--notes", "lying")
        check(p.returncode != 0, "must not allow declaring a populated category empty")


def test_status_justifications_required():
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        run(r, "init")
        run(r, "inventory-add", "--category", "features", "--id", "f:1", "--label", "x")
        p = run(r, "record", "--category", "features", "--id", "f:1", "--status", "not_applicable")
        check(p.returncode != 0, "not_applicable must require --notes")
        p = run(r, "record", "--category", "features", "--id", "f:1", "--status", "blocked")
        check(p.returncode != 0, "blocked must require --notes")
        p = run(r, "record", "--category", "features", "--id", "f:1", "--status", "blocked",
                "--notes", "environment unreachable")
        check(p.returncode == 0, f"blocked with notes must succeed: {p.stderr}")
        p = run(r, "record", "--category", "features", "--id", "f:1", "--status", "bogus")
        check(p.returncode != 0, "an unknown status must be rejected")


def test_severity_scale_and_aliases():
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        run(r, "init")
        for sev, expected in [("critical", "critical"), ("P0", "critical"), ("high", "high"),
                              ("P3", "low"), ("medium", "medium")]:
            p = run(r, "finding", "--title", f"t-{sev}", "--severity", sev, "--category", "features")
            check(p.returncode == 0, f"severity {sev} rejected: {p.stderr}")
            fid = p.stdout.strip()
            data = json.loads((r / ".qa" / "findings" / f"{fid}.json").read_text())
            check(data["severity"] == expected,
                  f"severity {sev} normalized to {data['severity']}, expected {expected}")
        p = run(r, "finding", "--title", "bad", "--severity", "urgent", "--category", "features")
        check(p.returncode != 0, "an unknown severity must be rejected")


def test_matrix_exposes_untested_items():
    """The matrix must show NOT TESTED rather than silently omitting a gap."""
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        run(r, "init")
        run(r, "inventory-add", "--category", "navigation", "--id", "nav:menu",
            "--kind", "menu", "--label", "Settings", "--profile-id", "admin", "--route", "/settings")
        run(r, "inventory-add", "--category", "navigation", "--id", "nav:sub",
            "--kind", "submenu", "--label", "Users", "--profile-id", "admin",
            "--route", "/settings/users", "--parent-id", "nav:menu")
        run(r, "record", "--category", "navigation", "--id", "nav:menu", "--status", "passed",
            "--profile-id", "admin", "--evidence", ".qa/evidence/screenshots/a.png")
        p = run(r, "matrix", "--format", "json")
        check(p.returncode == 0, f"matrix failed: {p.stderr}")
        rows = json.loads(p.stdout)["rows"]
        by_test = {row["test"]: row for row in rows}
        check(by_test["nav:menu"]["status"] == "PASSED", "tested item must show PASSED")
        check(by_test["nav:sub"]["status"] == "NOT TESTED", "untested item must show NOT TESTED")
        check(by_test["nav:sub"]["menu"] == "Settings", "submenu must resolve its parent menu")
        check(by_test["nav:sub"]["submenu"] == "Users", "submenu label must be populated")
        check(by_test["nav:menu"]["role"] == "admin", "role column must be populated")


def test_matrix_survives_cyclic_parent_chain():
    """A malformed inventory must not hang matrix generation."""
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        run(r, "init")
        run(r, "inventory-add", "--category", "navigation", "--id", "a", "--parent-id", "b")
        run(r, "inventory-add", "--category", "navigation", "--id", "b", "--parent-id", "a")
        p = run(r, "matrix", "--format", "json")
        check(p.returncode == 0, f"matrix must tolerate a cyclic parent chain: {p.stderr}")


def test_tracked_categories_are_visible():
    """Specialized agents must have a measurable, visible coverage lane."""
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        run(r, "init")
        data = status_json(r)
        for cat in ["api", "ux", "ui", "responsive", "accessibility", "security",
                    "performance", "resilience", "data-integrity"]:
            check(cat in data["categories"], f"tracked category {cat} is not reported")
        check("security" not in data["required_categories"],
              "tracked categories must not gate by default")


def test_promoted_category_gates():
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        run(r, "init")
        cfg_path = r / ".qa" / "config.json"
        cfg = json.loads(cfg_path.read_text())
        cfg["required_categories"] = CORE + ["security"]
        cfg_path.write_text(json.dumps(cfg, indent=2))
        for cat in CORE:
            run(r, "declare-empty", "--category", cat, "--notes", "n/a")
        run(r, "mark-discovery-complete")
        p = run(r, "validate")
        check(p.returncode != 0, "a promoted category must gate completion")


def _project(root):
    """A small project with one scenario of every detectable origin."""
    (root / "features").mkdir()
    (root / "features" / "login.feature").write_text(
        "Feature: Login\n  Scenario: valid credentials\n  Scenario Outline: invalid <field>\n")
    (root / "e2e").mkdir()
    (root / "e2e" / "cart.spec.ts").write_text(
        "import { test } from '@playwright/test';\n"
        "test('adds one item', async () => {});\n"
        "test.skip(\"applies coupon\", async () => {});\n"
        "test.describe('group', () => {});\n")
    (root / "src").mkdir()
    (root / "src" / "sum.test.ts").write_text("test('adds numbers', () => {});\n")
    (root / "docs").mkdir()
    (root / "docs" / "test-plan.md").write_text("# Test plan\n")
    (root / "node_modules" / "lib").mkdir(parents=True)
    (root / "node_modules" / "lib" / "a.spec.ts").write_text("test('ignored', () => {});\n")
    (root / "package.json").write_text(json.dumps({"scripts": {"test": "vitest", "test:e2e": "playwright test", "build": "vite build"}}))


def test_scenario_scan_finds_and_imports_existing_scenarios():
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        _project(r)
        run(r, "init", "--goal", "scan")
        p = run(r, "scenario-scan", "--import", "--json")
        check(p.returncode == 0, f"scenario-scan failed: {p.stderr}")
        scan = json.loads(p.stdout)
        check(scan["found"] is True, "existing scenarios must be detected")
        c = scan["counts"]
        check(c["gherkin_scenarios"] == 2, f"expected 2 gherkin scenarios, got {c['gherkin_scenarios']}")
        check(c["e2e_tests"] == 2, f"expected 2 e2e tests (describe excluded), got {c['e2e_tests']}")
        check(c["unit_files"] == 1, f"expected 1 unit file, got {c['unit_files']}")
        check(scan["sources"]["documented"] == ["docs/test-plan.md"], f"documented: {scan['sources']['documented']}")
        check(all("node_modules" not in f["file"] for f in scan["sources"]["e2e"]), "node_modules must be skipped")
        ids = {x["id"] for x in json.loads((r / ".qa" / "inventory" / "scenarios.json").read_text())["items"]}
        check("scenario:gherkin:features/login.feature::valid credentials" in ids, f"gherkin not imported: {ids}")
        check("scenario:e2e:e2e/cart.spec.ts::applies coupon" in ids, f"e2e not imported: {ids}")
        check("scenario:suite:package.json#test:e2e" in ids, f"suite not imported: {ids}")
        check("scenario:suite:package.json#build" not in ids, "a build script is not a test suite")
        check(scan["imported"] == len(ids) == 6, f"expected 6 imported items, got {scan['imported']}/{len(ids)}")
        # Importing again must not duplicate anything.
        again = json.loads(run(r, "scenario-scan", "--import", "--json").stdout)
        check(again["imported"] == 0, "a second import must be idempotent")
        state = status_json(r)
        check(state["scenario_scan"]["found"] is True, "run-state must remember the scan verdict")


def test_scenario_scan_reports_none_and_gates_until_generated():
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        (r / "src").mkdir()
        (r / "src" / "app.py").write_text("print('hi')\n")
        run(r, "init", "--goal", "none")
        for cat in DECLARABLE:
            run(r, "declare-empty", "--category", cat, "--notes", "n/a")
        run(r, "mark-discovery-complete", "--notes", "done")
        p = run(r, "validate")
        check("not been scanned" in p.stdout, f"validate must require the scan: {p.stdout}")
        p = run(r, "scenario-scan")
        check(p.returncode == 0 and "Scenario scan: NONE" in p.stdout, f"expected NONE: {p.stdout}")
        p = run(r, "validate")
        check(p.returncode != 0 and "no test scenarios" in p.stdout, f"empty scenarios must gate: {p.stdout}")
        p = run(r, "declare-empty", "--category", "scenarios", "--notes", "skip")
        check(p.returncode != 0, "scenarios must never be declarable as empty")
        complete_scenarios(r)
        p = run(r, "validate")
        check(p.returncode == 0, f"generated and executed scenarios must validate: {p.stdout}")


def test_scenario_list_exports_steps_and_status():
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        run(r, "init", "--goal", "list")
        meta = json.dumps({"origin": "generated", "covers": ["features:1"], "steps": ["open cart", "pay"], "expected": "order created"})
        run(r, "inventory-add", "--category", "scenarios", "--id", "scenario:generated:pay", "--kind", "generated",
            "--label", "pay order", "--metadata", meta)
        run(r, "record", "--category", "scenarios", "--id", "scenario:generated:pay", "--status", "failed")
        p = run(r, "scenario-list", "--out", ".qa/reports/test-scenarios.md")
        check(p.returncode == 0, f"scenario-list failed: {p.stderr}")
        text = (r / ".qa" / "reports" / "test-scenarios.md").read_text()
        for needle in ["pay order", "features:1", "1. open cart", "**Expected:** order created", "FAILED"]:
            check(needle in text, f"scenario list is missing '{needle}'")


def test_record_warns_on_unknown_id():
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        run(r, "init", "--goal", "typo")
        run(r, "inventory-add", "--category", "forms", "--id", "forms:1")
        p = run(r, "record", "--category", "forms", "--id", "forms:l", "--status", "passed")
        check(p.returncode == 0, "recording an unknown id keeps the result")
        check("not in the forms inventory" in p.stderr, f"an unknown id must warn: {p.stderr}")
        p = run(r, "record", "--category", "forms", "--id", "forms:1", "--status", "passed")
        check(p.stderr == "", f"a known id must not warn: {p.stderr}")


def test_invalid_category_rejected():
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        run(r, "init")
        p = run(r, "inventory-add", "--category", "../escape", "--id", "x")
        check(p.returncode != 0, "a path-traversal category must be rejected")


def _init_with_one_scenario(r, requirement_id="REQ-1", status="passed", notes=None):
    """Init a project and record exactly one scenario result for one requirement."""
    run(r, "init", "--goal", "docs-qa")
    meta = json.dumps({"requirement_id": requirement_id, "covers": ["features:1"],
                        "preconditions": "user is logged in", "steps": ["open page", "click save"],
                        "expected": "data is saved"})
    p = run(r, "inventory-add", "--category", "scenarios", "--id", "scenario:generated:x",
            "--kind", "generated", "--label", "happy path", "--metadata", meta)
    check(p.returncode == 0, f"inventory-add failed: {p.stderr}")
    record_args = ["record", "--category", "scenarios", "--id", "scenario:generated:x", "--status", status]
    if notes:
        record_args += ["--notes", notes]
    elif status in {"blocked", "not_applicable"}:
        record_args += ["--notes", "n/a"]
    p = run(r, *record_args)
    check(p.returncode == 0, f"record failed: {p.stderr}")


def test_execution_flow_accepted():
    """A PASSed scenario for a requirement must export, finish, and report ACCEPTED."""
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        _init_with_one_scenario(r, requirement_id="REQ-1", status="passed")
        p = run(r, "execution-start", "--base-url", "https://staging.example.com", "--executor", "tester")
        check(p.returncode == 0, f"execution-start failed: {p.stderr}")
        execution_id = p.stdout.strip()
        check(execution_id.startswith("exec-"), f"unexpected execution id: {execution_id}")

        readme = r / "docs" / "qa" / "README.md"
        check(readme.exists(), "docs/qa/README.md must be materialized on execution-start")

        p = run(r, "execution-finish", "--execution", execution_id)
        check(p.returncode == 0, f"execution-finish failed: {p.stderr}")

        from hashlib import sha1
        safe = "scenario_generated_x"
        digest = sha1("scenario:generated:x".encode()).hexdigest()[:8]
        scen_dir = r / "docs" / "qa" / "executions" / execution_id / "scenarios" / f"{safe}-{digest}"
        result_path = scen_dir / "result.json"
        report_path = scen_dir / "report.md"
        check(result_path.exists(), f"result.json missing at {result_path}")
        check(report_path.exists(), f"report.md missing at {report_path}")
        result = json.loads(result_path.read_text())
        check(result["status"] == "PASS", f"expected PASS, got {result['status']}")
        check(result["requirement_id"] == "REQ-1", f"requirement_id not propagated: {result}")
        report_text = report_path.read_text()
        for needle in ["ID: scenario:generated:x", "Requirement: REQ-1", "## Status", "PASS",
                       "open page", "click save", "data is saved"]:
            check(needle in report_text, f"report.md missing '{needle}'")

        p = run(r, "execution-finish", "--execution", execution_id)
        check(p.returncode != 0, "finishing an already-finished execution must fail")

        p = run(r, "requirement-report", "REQ-1", "--execution", execution_id)
        check(p.returncode == 0, f"requirement-report failed: {p.stderr}")
        check(p.stdout.strip() == "ACCEPTED", f"expected ACCEPTED, got {p.stdout.strip()}")

        acceptance_path = r / "docs" / "qa" / "reports" / "REQ-1" / "acceptance.json"
        check(acceptance_path.exists(), "acceptance.json was not written")
        acceptance = json.loads(acceptance_path.read_text())
        check(acceptance["result"] == "ACCEPTED", f"acceptance.json result mismatch: {acceptance}")
        md_path = r / "docs" / "qa" / "reports" / "REQ-1" / "ACCEPTANCE-REPORT.md"
        check(md_path.exists(), "ACCEPTANCE-REPORT.md was not written")
        check("RESULT: ACCEPTED" in md_path.read_text(), "ACCEPTANCE-REPORT.md missing final result")


def test_bug_report_blocks_acceptance():
    """A FAILed scenario with a PRODUCT_DEFECT bug must yield NOT_ACCEPTED."""
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        _init_with_one_scenario(r, requirement_id="REQ-2", status="failed", notes="save button did nothing")
        p = run(r, "execution-start")
        execution_id = p.stdout.strip()
        p = run(r, "execution-finish", "--execution", execution_id)
        check(p.returncode == 0, f"execution-finish failed: {p.stderr}")

        p = run(r, "bug-report", "--scenario", "scenario:generated:x", "--execution", execution_id,
                "--classification", "PRODUCT_DEFECT", "--summary", "save silently fails",
                "--observed-fact", "clicking save shows no error and no data is persisted",
                "--hypothesis", "likely a swallowed exception in the save handler")
        check(p.returncode == 0, f"bug-report failed: {p.stderr}")
        bug_id = p.stdout.strip()
        check(bug_id.startswith("BUG-"), f"unexpected bug id: {bug_id}")

        bug_path = r / "docs" / "qa" / "bugs" / bug_id / "bug.json"
        check(bug_path.exists(), "bug.json was not written")
        bug = json.loads(bug_path.read_text())
        check(bug["classification"] == "PRODUCT_DEFECT", f"classification mismatch: {bug}")

        md = (r / "docs" / "qa" / "bugs" / bug_id / "BUG-REPORT.md").read_text()
        check("## Observed fact" in md, "BUG-REPORT.md missing 'Observed fact' section")
        check("## Technical hypothesis" in md, "BUG-REPORT.md missing 'Technical hypothesis' section")
        fact_idx = md.index("## Observed fact")
        hyp_idx = md.index("## Technical hypothesis")
        check(fact_idx != hyp_idx, "Observed fact and Technical hypothesis must be distinct sections")
        check("clicking save shows no error" in md, "observed fact content missing from BUG-REPORT.md")
        check("likely a swallowed exception" in md, "technical hypothesis content missing from BUG-REPORT.md")

        from hashlib import sha1
        digest = sha1("scenario:generated:x".encode()).hexdigest()[:8]
        result_path = (r / "docs" / "qa" / "executions" / execution_id / "scenarios" /
                       f"scenario_generated_x-{digest}" / "result.json")
        result = json.loads(result_path.read_text())
        check(result["bug_id"] == bug_id, "result.json was not updated with the bug_id")

        p = run(r, "requirement-report", "REQ-2", "--execution", execution_id)
        check(p.returncode == 0, f"requirement-report failed: {p.stderr}")
        check(p.stdout.strip() == "NOT_ACCEPTED", f"expected NOT_ACCEPTED, got {p.stdout.strip()}")


def test_not_executed_yields_incomplete():
    """A scenario with no recorded result must export as NOT_EXECUTED and gate as INCOMPLETE."""
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        run(r, "init", "--goal", "incomplete")
        meta = json.dumps({"requirement_id": "REQ-3"})
        run(r, "inventory-add", "--category", "scenarios", "--id", "scenario:generated:untested",
            "--kind", "generated", "--label", "never run", "--metadata", meta)
        p = run(r, "execution-start")
        execution_id = p.stdout.strip()
        p = run(r, "execution-finish", "--execution", execution_id)
        check(p.returncode == 0, f"execution-finish failed: {p.stderr}")

        from hashlib import sha1
        digest = sha1("scenario:generated:untested".encode()).hexdigest()[:8]
        result_path = (r / "docs" / "qa" / "executions" / execution_id / "scenarios" /
                       f"scenario_generated_untested-{digest}" / "result.json")
        result = json.loads(result_path.read_text())
        check(result["status"] == "NOT_EXECUTED", f"expected NOT_EXECUTED, got {result['status']}")

        p = run(r, "requirement-report", "REQ-3", "--execution", execution_id)
        check(p.returncode == 0, f"requirement-report failed: {p.stderr}")
        check(p.stdout.strip() == "INCOMPLETE", f"expected INCOMPLETE, got {p.stdout.strip()}")


def test_retest_appends_without_erasing_history():
    """Retesting a bug must append to its history and keep the original bug intact."""
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        _init_with_one_scenario(r, requirement_id="REQ-4", status="failed", notes="broken")
        p = run(r, "execution-start")
        exec1 = p.stdout.strip()
        run(r, "execution-finish", "--execution", exec1)
        p = run(r, "bug-report", "--scenario", "scenario:generated:x", "--execution", exec1,
                "--classification", "PRODUCT_DEFECT", "--summary", "s", "--observed-fact", "f")
        bug_id = p.stdout.strip()

        # Fix it, run a second execution, and retest the bug against it.
        run(r, "record", "--category", "scenarios", "--id", "scenario:generated:x", "--status", "passed")
        p = run(r, "execution-start")
        exec2 = p.stdout.strip()
        run(r, "execution-finish", "--execution", exec2)
        p = run(r, "retest", "--bug", bug_id, "--execution", exec2, "--result", "PASS")
        check(p.returncode == 0, f"retest failed: {p.stderr}")

        bug = json.loads((r / "docs" / "qa" / "bugs" / bug_id / "bug.json").read_text())
        check(len(bug["retest_history"]) == 1, f"retest_history not appended: {bug}")
        check(bug["retest_history"][0]["execution_id"] == exec2, "retest execution_id mismatch")
        check(bug["classification"] == "PRODUCT_DEFECT", "original bug classification must survive a retest")
        check(bug["summary"] == "s", "original bug summary must survive a retest")

        md = (r / "docs" / "qa" / "bugs" / bug_id / "BUG-REPORT.md").read_text()
        check(exec2 in md, "retest history table must list the retest execution")

        p = run(r, "bugs-list", "--format", "json")
        check(p.returncode == 0, f"bugs-list failed: {p.stderr}")
        data = json.loads(p.stdout)
        by_id = {row["bug_id"]: row for row in data["rows"]}
        check(bug_id in by_id, "bugs-list must include the created bug")
        check(by_id[bug_id]["status"] == "retested", f"bug must show as retested: {by_id[bug_id]}")


def test_evidence_sanitization_strips_secrets():
    """A secret in a text evidence file must never survive the export into docs/qa."""
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        evidence_dir = r / "evidence"
        evidence_dir.mkdir()
        evidence_file = evidence_dir / "console.log"
        secret = "abc123xyzSECRET"
        evidence_file.write_text(f"request failed\nAuthorization: Bearer {secret}\nstatus=500\n")

        run(r, "init", "--goal", "sanitize")
        meta = json.dumps({"requirement_id": "REQ-5"})
        run(r, "inventory-add", "--category", "scenarios", "--id", "scenario:generated:evid",
            "--kind", "generated", "--label", "with evidence", "--metadata", meta)
        run(r, "record", "--category", "scenarios", "--id", "scenario:generated:evid",
            "--status", "failed", "--notes", "n/a", "--evidence", "evidence/console.log")
        p = run(r, "execution-start")
        execution_id = p.stdout.strip()
        p = run(r, "execution-finish", "--execution", execution_id)
        check(p.returncode == 0, f"execution-finish failed: {p.stderr}")

        from hashlib import sha1
        digest = sha1("scenario:generated:evid".encode()).hexdigest()[:8]
        scen_dir = (r / "docs" / "qa" / "executions" / execution_id / "scenarios" /
                    f"scenario_generated_evid-{digest}")
        result = json.loads((scen_dir / "result.json").read_text())
        check(result["evidence"], "evidence was not exported")
        exported_path = r / result["evidence"][0]
        check(exported_path.exists(), f"exported evidence file missing: {exported_path}")
        exported_text = exported_path.read_text()
        check(secret not in exported_text, "secret leaked into exported evidence")
        check("***REDACTED***" in exported_text, "redaction marker missing from exported evidence")
        check("status=500" in exported_text, "non-secret content must survive sanitization")


def test_final_report_aggregates_execution():
    """final-report must aggregate requirements into one coherent execution summary."""
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        run(r, "init", "--goal", "final")
        meta_pass = json.dumps({"requirement_id": "REQ-OK"})
        meta_fail = json.dumps({"requirement_id": "REQ-BAD"})
        run(r, "inventory-add", "--category", "scenarios", "--id", "scenario:generated:ok",
            "--kind", "generated", "--label", "ok", "--metadata", meta_pass)
        run(r, "inventory-add", "--category", "scenarios", "--id", "scenario:generated:bad",
            "--kind", "generated", "--label", "bad", "--metadata", meta_fail)
        run(r, "record", "--category", "scenarios", "--id", "scenario:generated:ok", "--status", "passed")
        run(r, "record", "--category", "scenarios", "--id", "scenario:generated:bad", "--status", "failed",
            "--notes", "broken")
        p = run(r, "execution-start")
        execution_id = p.stdout.strip()
        run(r, "execution-finish", "--execution", execution_id)
        p = run(r, "bug-report", "--scenario", "scenario:generated:bad", "--execution", execution_id,
                "--classification", "PRODUCT_DEFECT", "--summary", "s", "--observed-fact", "f")
        check(p.returncode == 0, f"bug-report failed: {p.stderr}")

        p = run(r, "final-report", "--execution", execution_id)
        check(p.returncode == 0, f"final-report failed: {p.stderr}")

        summary_path = r / "docs" / "qa" / "summary" / execution_id / "summary.json"
        check(summary_path.exists(), "summary.json was not written")
        summary = json.loads(summary_path.read_text())
        check(summary["requirements_evaluated"] == 2, f"expected 2 requirements, got {summary}")
        check(summary["overall_result"] == "NOT_ACCEPTED", f"expected NOT_ACCEPTED, got {summary}")
        check(summary["bugs_by_classification"].get("PRODUCT_DEFECT") == 1,
              f"expected one PRODUCT_DEFECT bug, got {summary}")

        md = (r / "docs" / "qa" / "summary" / execution_id / "FINAL-REPORT.md").read_text()
        check("QA EXECUTION REPORT" in md, "FINAL-REPORT.md missing title")
        check("REQ-OK" in md and "REQ-BAD" in md, "FINAL-REPORT.md missing requirement rows")
        check("Overall result: NOT_ACCEPTED" in md, "FINAL-REPORT.md missing overall result")

        manifest_path = r / "docs" / "qa" / "summary" / execution_id / "evidence-manifest.json"
        check(manifest_path.exists(), "evidence-manifest.json was not written")
        manifest = json.loads(manifest_path.read_text())
        check(len(manifest) == 2, f"expected 2 manifest entries, got {manifest}")


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]


def main():
    failures = []
    for fn in TESTS:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except Failure as exc:
            failures.append((fn.__name__, str(exc)))
            print(f"  FAIL  {fn.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001 - surface unexpected errors as failures
            failures.append((fn.__name__, repr(exc)))
            print(f"  ERROR {fn.__name__}: {exc!r}")
    print(f"qa_cli tests: {len(TESTS) - len(failures)}/{len(TESTS)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
