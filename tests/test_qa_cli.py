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

CORE = ["profiles", "navigation", "features", "forms", "workflows", "permissions"]


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
        for cat in CORE:
            p = run(r, "declare-empty", "--category", cat, "--notes", "nothing applicable here")
            check(p.returncode == 0, f"declare-empty {cat} failed: {p.stderr}")
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


def test_invalid_category_rejected():
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        run(r, "init")
        p = run(r, "inventory-add", "--category", "../escape", "--id", "x")
        check(p.returncode != 0, "a path-traversal category must be rejected")


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
