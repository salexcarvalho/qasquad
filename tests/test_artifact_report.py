#!/usr/bin/env python3
"""Behavioral tests for scope support and the evidence/failure report generator.

Everything runs on fixtures: no application, no browser, no network. Uses explicit failure
reporting rather than bare `assert`, so the suite keeps working under `python3 -O`.
"""
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
BIN = PKG / "plugins" / "qa-squad" / "bin"
CLI = BIN / "qa-cli"
GEN = BIN / "qa_artifact_report.py"
FIXTURES = PKG / "tests" / "fixtures"

sys.path.insert(0, str(BIN))
import qa_scope  # noqa: E402

_spec = importlib.util.spec_from_file_location("qa_artifact_report", GEN)
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)


class Failure(Exception):
    pass


def check(condition, message):
    if not condition:
        raise Failure(message)


def env_for(root, extra=None):
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(root)
    env.pop("QA_SQUAD_NO_ARTIFACT", None)
    env.pop("QA_SQUAD_REPORT_LANG", None)
    env.update(extra or {})
    return env


def cli(root, *args, ok=True):
    p = subprocess.run([sys.executable, str(CLI), *args], env=env_for(root), text=True, capture_output=True)
    if ok:
        check(p.returncode == 0, f"qa-cli {' '.join(args)} failed: {p.stdout}{p.stderr}")
    return p


def report(root, *args, extra_env=None, ok=True):
    p = subprocess.run([sys.executable, str(GEN), "--root", str(root), *args],
                       env=env_for(root, extra_env), text=True, capture_output=True)
    if ok:
        check(p.returncode == 0, f"generator {' '.join(args)} failed: {p.stdout}{p.stderr}")
    return p


def project(tmp, stories=True):
    """A throwaway project with the Portuguese story fixture and some real screenshots."""
    root = Path(tmp)
    if stories:
        (root / "docs" / "user-stories").mkdir(parents=True)
        (root / "docs" / "user-stories" / "A01-acesso.md").write_text(
            (FIXTURES / "user-stories" / "A01-acesso.md").read_text(encoding="utf-8"), encoding="utf-8")
    shots = root / "shots"
    shots.mkdir()
    for n, seed in (("ok.png", 2), ("fail.png", 9), ("step.png", 4)):
        (shots / n).write_bytes(gen._png(640, 360, seed))
    (shots / "console.log").write_text(
        "POST /login 401\nAuthorization: Bearer abcdefghijklmnop12345678\npassword=hunter2secret\nboom\n",
        encoding="utf-8")
    cli(root, "init", "--goal", "test")
    return root


def run_story_execution(root, results, finding_ids=()):
    """results: {criterion id: (status, evidence list, notes)}; returns the execution ID."""
    for cid, (status, evidence, notes) in results.items():
        args = ["record", "--category", "scenarios", "--id", f"scenario:criterion:{cid}",
                "--status", status, "--notes", notes]
        for e in evidence:
            args += ["--evidence", e]
        for f in finding_ids:
            args += ["--finding-id", f]
        cli(root, *args)
    exec_id = cli(root, "execution-start", "--executor", "claude").stdout.strip()
    cli(root, "execution-finish", "--execution", exec_id)
    return exec_id


def read(path):
    return Path(path).read_text(encoding="utf-8")


# ----------------------------------------------------------------------- scope parsing

def test_parses_portuguese_story_pack():
    scope = qa_scope.resolve_scope(FIXTURES, scope_type="epic", value="A01", source="user-stories")
    check(scope["type"] == "epic" and scope["title"] == "Autenticação e acesso", f"epic title: {scope['title']}")
    check([c["id"] for c in scope["children"]] == ["US-A01-01", "US-A01-02", "US-A01-03"], "story IDs")
    first = scope["children"][0]
    check(first["priority"] == "Must" and first["narrative"].startswith("Como usuário"), "story fields")
    crit = first["acceptance_criteria"]
    check(len(crit) == 2 and crit[0]["id"] == "US-A01-01/AC-01", "two criteria with stable IDs")
    check([s["type"] for s in crit[0]["steps"]] == ["given", "when", "then", "then"], "E continues the Then")
    check([s["type"] for s in crit[1]["steps"]] == ["given", "when", "then", "then"], "Mas continues the Then")
    outline = scope["children"][1]["acceptance_criteria"][1]
    check(outline["title"] == "Senha curta" and len(outline["examples"]) == 3, "scenario outline with examples")
    bullets = scope["children"][2]["acceptance_criteria"]
    check(len(bullets) == 2 and bullets[0]["kind"] == "bullet", "bullet criteria are tolerated")
    check(len(scope["acceptance_criteria"]) == 6, "epic flattens the criteria of its stories")


def test_parses_english_gherkin_and_spec_scope():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        gen.make_fixture(root, "failing")
        scope = qa_scope.resolve_scope(root, scope_type="spec", value="docs/user-stories/demo.md")
        check(scope["id"] == "demo" and scope["title"] == "Account access", f"spec id/title: {scope['id']} {scope['title']}")
        check(len(scope["children"]) == 2 and len(scope["acceptance_criteria"]) == 3, "spec carries its stories")
        story = qa_scope.resolve_scope(root, scope_type="auto", value="US-DEMO-02")
        check(story["type"] == "story" and story["parent_id"] == "DEMO", "auto-detects a story ID")
        check(qa_scope.detect_type("A01", root) == "epic" and qa_scope.detect_type("youth", root) == "feature",
              "auto-detects epic and feature")


def test_unknown_story_is_an_error_not_a_guess():
    try:
        qa_scope.resolve_scope(FIXTURES, scope_type="story", value="US-NOPE-99", source="user-stories")
    except ValueError as exc:
        check("not found" in str(exc), f"error should say not found: {exc}")
        return
    raise Failure("an unknown story must raise")


def test_inline_story_without_a_document():
    scope = qa_scope.resolve_scope(Path("/nonexistent"), scope_type="story", value="US-X-1", title="Pay by card",
                                   criteria=["Given a cart; When the user pays; Then the order is paid", "Receipt is e-mailed"])
    crit = scope["acceptance_criteria"]
    check(crit[0]["kind"] == "gherkin" and crit[0]["steps"][2]["type"] == "then", "inline Given/When/Then parsed")
    check(crit[1]["kind"] == "bullet", "plain text becomes a bullet criterion")


# --------------------------------------------------------------- cli: scope propagation

def test_scope_set_imports_criteria_and_tags_everything():
    with tempfile.TemporaryDirectory() as d:
        root = project(d)
        out = cli(root, "scope-set", "--story", "US-A01-01").stdout
        check("criteria=2 imported=2" in out, f"scope-set output: {out}")
        inv = json.loads(read(root / ".qa" / "inventory" / "scenarios.json"))["items"]
        check(len(inv) == 2 and all(i["metadata"]["requirement_id"] == "US-A01-01" for i in inv), "requirement_id = story")
        check(all(set(i["metadata"]["scope_ids"]) == {"US-A01-01", "A01"} for i in inv), "scenarios tagged with scope IDs")
        check(inv[0]["metadata"]["preconditions"] and inv[0]["metadata"]["expected"], "criterion became executable")
        cli(root, "inventory-add", "--category", "forms", "--id", "forms:login", "--label", "Login form")
        forms = json.loads(read(root / ".qa" / "inventory" / "forms.json"))["items"]
        check(forms[0]["metadata"]["scope_ids"] == ["US-A01-01", "A01"], "inventory-add inherits the active scope")
        cli(root, "record", "--category", "forms", "--id", "forms:login", "--status", "passed")
        cli(root, "finding", "--title", "T", "--severity", "low", "--category", "forms")
        res = [json.loads(read(p)) for p in (root / ".qa" / "results" / "forms").glob("*.json")]
        check(res[0]["scope_ids"] == ["US-A01-01", "A01"], "record inherits the active scope")
        fnd = [json.loads(read(p)) for p in (root / ".qa" / "findings").glob("*.json")]
        check(fnd[0]["scope_ids"] == ["US-A01-01", "A01"], "finding inherits the active scope")
        cli(root, "scope-clear")
        cli(root, "inventory-add", "--category", "forms", "--id", "forms:other", "--label", "Other")
        forms = json.loads(read(root / ".qa" / "inventory" / "forms.json"))["items"]
        other = next(i for i in forms if i["id"] == "forms:other")
        check("scope_ids" not in other["metadata"], "after scope-clear nothing is tagged (legacy behavior)")


def test_scope_tag_attaches_the_scope_to_earlier_inventory():
    with tempfile.TemporaryDirectory() as d:
        root = project(d)
        cli(root, "inventory-add", "--category", "forms", "--id", "forms:login", "--label", "Login form", "--route", "/login")
        cli(root, "inventory-add", "--category", "forms", "--id", "forms:billing", "--label", "Billing form", "--route", "/billing")
        cli(root, "scope-set", "--story", "US-A01-01")
        out = cli(root, "scope-tag", "--category", "forms", "--match", "login").stdout
        check("1 item(s) tagged" in out, f"scope-tag output: {out}")
        forms = {i["id"]: i for i in json.loads(read(root / ".qa" / "inventory" / "forms.json"))["items"]}
        check("US-A01-01" in forms["forms:login"]["metadata"].get("scope_ids", []), "matching item tagged")
        check("scope_ids" not in forms["forms:billing"]["metadata"], "other item left alone")
        check(cli(root, "scope-tag", ok=False).returncode != 0, "scope-tag needs --id or --match")


def test_manifest_command_and_missing_manifest_error():
    with tempfile.TemporaryDirectory() as d:
        root = project(d)
        exec_id = story_run_with_failure(root)
        p = cli(root, "manifest", "--execution", exec_id)
        check("manifest.json" in p.stdout, f"manifest output: {p.stdout}")
        p = cli(root, "manifest", "--execution", "exec-nope", ok=False)
        check(p.returncode != 0, "unknown execution must fail")


def test_scope_set_rejects_ambiguous_or_missing_input():
    with tempfile.TemporaryDirectory() as d:
        root = project(d)
        check(cli(root, "scope-set", ok=False).returncode != 0, "scope-set without a target must fail")
        check(cli(root, "scope-set", "--story", "A", "--epic", "B", ok=False).returncode != 0, "two targets must fail")
        check(cli(root, "scope-set", "--story", "US-ZZZ-9", ok=False).returncode != 0, "unknown story must fail")


# ----------------------------------------------------------- reports: story with failure

def story_run_with_failure(root):
    cli(root, "scope-set", "--story", "US-A01-01")
    ev_ok, ev_fail = ["shots/ok.png"], ["shots/fail.png", "shots/step.png", "shots/console.log"]
    # Findings are recorded while testing, before the execution is closed and exported.
    fid = cli(root, "finding", "--title", "Message missing", "--severity", "high", "--category", "scenarios",
              "--actual", "no message", "--expected", "Credenciais inválidas",
              "--reproduction", "1. open /login\n2. wrong password",
              "--evidence", "shots/fail.png", "--criterion-id", "US-A01-01/AC-02",
              "--scenario-id", "scenario:criterion:US-A01-01/AC-02").stdout.strip()
    cli(root, "record", "--category", "scenarios", "--id", "scenario:criterion:US-A01-01/AC-01",
        "--status", "passed", "--notes", "Landed on the home page.", "--evidence", ev_ok[0])
    exec_id = run_story_execution(root, {
        "US-A01-01/AC-02": ("failed", ev_fail, "The message did not appear."),
    }, finding_ids=[fid])
    cli(root, "bug-report", "--scenario", "scenario:criterion:US-A01-01/AC-02", "--execution", exec_id,
        "--classification", "PRODUCT_DEFECT", "--summary", "No message", "--observed-fact", "The page stayed silent.",
        "--hypothesis", "Validation may be skipped", "--severity", "high")
    return exec_id


def test_story_with_failure_produces_both_reports():
    with tempfile.TemporaryDirectory() as d:
        root = project(d)
        exec_id = story_run_with_failure(root)
        out = Path(d) / "out"
        report(root, "--execution", exec_id, "--scope", "current", "--artifact", "--out-dir", str(out))
        plan = json.loads(read(out / "artifact-plan.json"))
        kinds = [p["kind"] for p in plan["publish"]]
        check(kinds == ["evidence", "failures"], f"publish plan: {kinds}")
        check(all(p["icon"] and p["description"].endswith(".") and "\n" not in p["description"] for p in plan["publish"]),
              "each entry has an icon and a one-sentence description")
        ev, fr = read(out / "qa-evidence-US-A01-01.html"), read(out / "qa-failures-US-A01-01.html")
        check("<title>QA Evidence US-A01-01</title>" in ev, "evidence title carries the scope")
        check("<title>QA Failures US-A01-01</title>" in fr, "failure title carries the scope")
        check("Verdict: FAILED" in ev, "evidence verdict")
        check("US-A01-01/AC-01" in ev and "US-A01-01/AC-02" in ev, "pass/fail listed per criterion")
        check(re.search(r'US-A01-01/AC-01</a></td><td class="">[^<]*</td><td class=""><span class="badge b-pass">PASS', ev),
              "criterion AC-01 shows PASS in the matrix")
        check(re.search(r'US-A01-01/AC-02</a></td><td class="">[^<]*</td><td class=""><span class="badge b-fail">FAIL', ev),
              "criterion AC-02 shows FAIL in the matrix")
        check(ev.count("data:image/") >= 2, "screenshots are embedded in the evidence report")
        check("Screenshot of the moment" in fr and "data:image/" in fr, "failure report embeds the screenshot of the moment")
        check("Steps to reproduce" in fr and "open /login" in fr, "failure report has reproduction steps")
        check("PRODUCT_DEFECT" in fr and "Hypothesis (not confirmed)" in fr, "classification and hypothesis kept apart")
        check("Message missing" in fr and "BUG-" in fr, "finding and bug are anchored")


def test_story_without_failure_generates_no_failure_report():
    with tempfile.TemporaryDirectory() as d:
        root = project(d)
        cli(root, "scope-set", "--story", "US-A01-02")
        exec_id = run_story_execution(root, {
            "US-A01-02/AC-01": ("passed", ["shots/ok.png"], "Neutral confirmation shown."),
            "US-A01-02/AC-02": ("passed", ["shots/step.png"], "Policy error shown."),
        })
        out = Path(d) / "out"
        out.mkdir()
        (out / "qa-failures-US-A01-02.html").write_text("stale")
        p = report(root, "--execution", exec_id, "--artifact", "--out-dir", str(out))
        check("no failure report generated" in p.stdout, f"message missing: {p.stdout}")
        check(not (out / "qa-failures-US-A01-02.html").exists(), "a stale failure report must be removed")
        plan = json.loads(read(out / "artifact-plan.json"))
        check([x["kind"] for x in plan["publish"]] == ["evidence"] and plan["failure_report"] is None,
              "only the evidence report is published")
        check(plan["verdict"] == "PASSED", f"verdict: {plan['verdict']}")
        scope_dir = root / "docs" / "qa" / "executions" / exec_id / "scope-US-A01-02"
        check(not (scope_dir / "failure-report.html").exists(), "no failure document in the scope folder")


def test_scopes_are_isolated_from_each_other():
    with tempfile.TemporaryDirectory() as d:
        root = project(d)
        cli(root, "scope-set", "--epic", "A01")
        fid = cli(root, "finding", "--title", "Story one finding", "--severity", "high", "--category", "scenarios",
                  "--scope-id", "US-A01-01", "--scope-id", "A01",
                  "--scenario-id", "scenario:criterion:US-A01-01/AC-01").stdout.strip()
        cli(root, "record", "--category", "scenarios", "--id", "scenario:criterion:US-A01-01/AC-01", "--status", "failed",
            "--notes", "Story one broke.", "--evidence", "shots/fail.png", "--finding-id", fid)
        exec_id = run_story_execution(root, {
            "US-A01-01/AC-02": ("passed", ["shots/ok.png"], "ok"),
            "US-A01-02/AC-01": ("passed", ["shots/step.png"], "Story two works."),
            "US-A01-02/AC-02": ("passed", [], "ok"),
        })
        out = Path(d) / "out"
        for sid in ("US-A01-01", "US-A01-02", "A01"):
            report(root, "--execution", exec_id, "--scope", sid, "--artifact", "--out-dir", str(out))
        two_ev = read(out / "qa-evidence-US-A01-02.html")
        check(not (out / "qa-failures-US-A01-02.html").exists(), "story two must have no failure report")
        check("Story one" not in two_ev and "US-A01-01" not in two_ev, "story two evidence must not mention story one")
        check("Story two works" in two_ev, "story two keeps its own evidence")
        one_fr = read(out / "qa-failures-US-A01-01.html")
        check("Story one finding" in one_fr, "story one failure report has its failure")
        check("US-A01-02" not in one_fr, "story one failure report must not mention story two")
        epic_ev = read(out / "qa-evidence-A01.html")
        check("US-A01-01/AC-01" in epic_ev and "US-A01-02/AC-01" in epic_ev, "epic report covers both stories")
        check("fail.png" not in two_ev, "story one screenshots must not appear in story two")
        later = cli(root, "execution-start").stdout.strip()
        check(later != exec_id, "executions started in the same second get distinct IDs")


def test_scope_folder_layout_and_manifest():
    with tempfile.TemporaryDirectory() as d:
        root = project(d)
        exec_id = story_run_with_failure(root)
        ex_dir = root / "docs" / "qa" / "executions" / exec_id
        scope = json.loads(read(ex_dir / "scope.json"))
        check(scope["type"] == "story" and scope["id"] == "US-A01-01" and scope["source"].endswith("A01-acesso.md"),
              "scope.json records type, id and source")
        check(len(scope["acceptance_criteria"]) == 2 and scope["acceptance_criteria"][0]["steps"], "criteria and Gherkin steps stored")
        manifest = json.loads(read(ex_dir / "manifest.json"))
        check(manifest["schema"] == "qa-squad/manifest/1" and len(manifest["items"]) == 2, "manifest holds the in-scope items")
        check(all("US-A01-01" in i["scope_ids"] for i in manifest["items"]), "every item carries scope_ids")
        check(manifest["bugs"] and manifest["bugs"][0]["classification"] == "PRODUCT_DEFECT", "bug refreshed into the manifest")
        report(root, "--execution", exec_id, "--standalone")
        scope_dir = ex_dir / "scope-US-A01-01"
        check((scope_dir / "evidence-report.html").exists() and (scope_dir / "failure-report.html").exists()
              and (scope_dir / "reports.json").exists() and (scope_dir / "scope.json").exists(), "scope folder contents")
        doc = read(scope_dir / "evidence-report.html")
        check(doc.lower().startswith("<!doctype html>") and "<body>" in doc, "standalone output is a complete document")


def test_scenarios_outside_the_scope_are_not_exported():
    with tempfile.TemporaryDirectory() as d:
        root = project(d)
        cli(root, "inventory-add", "--category", "scenarios", "--id", "scenario:generated:other", "--kind", "generated",
            "--label", "Unrelated scenario")
        cli(root, "record", "--category", "scenarios", "--id", "scenario:generated:other", "--status", "failed",
            "--notes", "unrelated failure")
        cli(root, "scope-set", "--story", "US-A01-03")
        exec_id = run_story_execution(root, {"US-A01-03/AC-01": ("passed", [], "ok"), "US-A01-03/AC-02": ("passed", [], "ok")})
        manifest = json.loads(read(root / "docs" / "qa" / "executions" / exec_id / "manifest.json"))
        ids = [i["id"] for i in manifest["items"]]
        check("scenario:generated:other" not in ids, f"unrelated item leaked into the scoped execution: {ids}")
        scen_dirs = list((root / "docs" / "qa" / "executions" / exec_id / "scenarios").iterdir())
        check(len(scen_dirs) == 2, f"only the scope's scenarios are exported, got {len(scen_dirs)}")


# --------------------------------------------------------------------- full scope

def test_full_scope_keeps_current_behavior_and_reports_everything():
    with tempfile.TemporaryDirectory() as d:
        root = project(d, stories=False)
        cli(root, "inventory-add", "--category", "forms", "--id", "forms:a", "--label", "Form A")
        cli(root, "inventory-add", "--category", "navigation", "--id", "nav:a", "--label", "Nav A")
        cli(root, "inventory-add", "--category", "scenarios", "--id", "scenario:generated:a", "--kind", "generated", "--label", "Scenario A")
        cli(root, "record", "--category", "forms", "--id", "forms:a", "--status", "failed", "--notes", "form broke",
            "--evidence", "shots/fail.png")
        cli(root, "record", "--category", "navigation", "--id", "nav:a", "--status", "passed")
        cli(root, "record", "--category", "scenarios", "--id", "scenario:generated:a", "--status", "passed",
            "--evidence", "shots/ok.png")
        cli(root, "finding", "--title", "Form A rejects valid data", "--severity", "medium", "--category", "forms",
            "--actual", "rejected", "--expected", "accepted", "--evidence", "shots/fail.png")
        check(not (root / ".qa" / "scope.json").exists(), "no scope file is written for a full run")
        exec_id = cli(root, "execution-start").stdout.strip()
        cli(root, "execution-finish", "--execution", exec_id)
        out = Path(d) / "out"
        report(root, "--execution", "latest", "--artifact", "--out-dir", str(out))
        ev, fr = read(out / "qa-evidence-full.html"), read(out / "qa-failures-full.html")
        check("<title>QA Evidence full</title>" in ev or "<title>QA Evidence</title>" in ev,
              "full-scope title has no story ID")
        for needle in ("Form A", "Nav A", "Scenario A"):
            check(needle in ev, f"full report lists {needle}")
        check("Coverage by category" in ev and "forms" in ev and "navigation" in ev, "coverage by category")
        check("Form A rejects valid data" in fr, "failure report lists the finding")
        scope_dir = root / "docs" / "qa" / "executions" / exec_id / "scope-full"
        check((scope_dir / "reports.json").exists(), "full scope also gets a scope folder")


def test_category_filter_limits_a_report_to_one_lane():
    with tempfile.TemporaryDirectory() as d:
        root = project(d, stories=False)
        cli(root, "inventory-add", "--category", "forms", "--id", "forms:a", "--label", "Form A")
        cli(root, "inventory-add", "--category", "navigation", "--id", "nav:a", "--label", "Nav A")
        cli(root, "record", "--category", "forms", "--id", "forms:a", "--status", "passed")
        cli(root, "record", "--category", "navigation", "--id", "nav:a", "--status", "passed")
        exec_id = cli(root, "execution-start").stdout.strip()
        cli(root, "execution-finish", "--execution", exec_id)
        out = Path(d) / "out"
        report(root, "--execution", exec_id, "--category", "forms", "--artifact", "--out-dir", str(out))
        ev = read(out / "qa-evidence-full.html")
        check("Form A" in ev and "Nav A" not in ev, "only the forms lane is reported")


# ------------------------------------------------------------ the Artifact contract

def build_pages(tmp):
    info = gen.make_fixture(Path(tmp) / "p", "failing")
    out = Path(tmp) / "o"
    res = gen.generate(Path(tmp) / "p", info["execution_id"], "US-DEMO-01", None, artifact=True,
                       standalone=False, out_dir=out, budget=gen.BUDGET_BYTES, lang="en")
    return res, [read(f["file_path"]) for f in res["publish"]]


def test_artifact_html_honours_the_page_contract():
    with tempfile.TemporaryDirectory() as d:
        res, pages = build_pages(d)
        check(len(pages) == 2, "evidence and failure pages built")
        for text in pages:
            problems = gen.check_artifact_html(text)
            check(not problems, f"contract violations: {problems}")
            low = text.lower()
            check(not re.search(r"<(!doctype|html|head|body)\b", low), "no document tags")
            check("<script" not in low and "<link" not in low, "no scripts or stylesheet links")
            check(not re.search(r"""(?:src|href|action|poster)=["']https?:""", low) and "@import" not in low
                  and not re.search(r"url\(\s*[\"']?https?:", low), "no external resources")
            check(re.search(r":root\{--bg:", text) and ':root:not([data-theme="light"])' in text
                  and ':root[data-theme="dark"]' in text and "@media (prefers-color-scheme: dark)" in text,
                  "theme tokens and both dark blocks")
            check(re.search(r"body\{[^}]*background:var\(--bg\)", text), "explicit body background")
            check(len(text.encode("utf-8")) <= 12 * 1024 * 1024, "within 12 MB")
            title = re.search(r"<title>(.*?)</title>", text[:8192]).group(1)
            check(2 <= len(title.split()) <= 4, f"title word count: {title!r}")
            ids = set(re.findall(r'id="([^"]+)"', text))
            hrefs = re.findall(r'href="#([^"]+)"', text)
            check(hrefs and all(h in ids for h in hrefs), "every internal anchor has a target")


def test_contract_checker_catches_violations():
    good = build_pages_good()
    bad_cases = {
        "doctype": "<!doctype html>" + good,
        "script": good + "<script>1</script>",
        "external": good + '<img src="https://example.com/x.png">',
        "title": good.replace("<title>QA Evidence US-DEMO-01</title>", "<title>Evidence</title>"),
        "explainer": good.replace("QA Evidence US-DEMO-01", "QA Evidence: a long explainer"),
        "anchor": good + '<a href="#nowhere">x</a>',
        "dark": good.replace(':root[data-theme="dark"]', ":root.x"),
        "table": good + "<table><tr><td>x</td></tr></table>",
        "budget": good,
    }
    for name, text in bad_cases.items():
        budget = 100 if name == "budget" else gen.BUDGET_BYTES
        check(gen.check_artifact_html(text, budget), f"checker missed violation: {name}")


def build_pages_good():
    with tempfile.TemporaryDirectory() as d:
        return build_pages(d)[1][0]


def test_secrets_are_masked_in_every_page():
    with tempfile.TemporaryDirectory() as d:
        root = project(d)
        exec_id = story_run_with_failure(root)
        out = Path(d) / "out"
        report(root, "--execution", exec_id, "--artifact", "--out-dir", str(out))
        report(root, "--execution", exec_id, "--standalone")
        pages = [read(p) for p in out.glob("*.html")]
        pages += [read(p) for p in (root / "docs" / "qa" / "executions" / exec_id / "scope-US-A01-01").glob("*.html")]
        for text in pages:
            check("hunter2secret" not in text, "password value leaked")
            check("abcdefghijklmnop12345678" not in text, "bearer token leaked")
            check(not gen.secrets_leaked(text), f"secret patterns survive: {gen.secrets_leaked(text)}")
        check(any("password=***" in t or "***" in t for t in pages), "masking is visible, not silent")
        exported = list((root / "docs" / "qa" / "evidence" / exec_id).rglob("console.log"))
        check(exported and all("hunter2secret" not in read(p) for p in exported), "exported evidence is sanitized too")
    check(gen.redact("Authorization: Bearer abcdefghijkl123456") .count("abcdefghijkl123456") == 0, "redact() Bearer")
    check("eyJhbGciOiJIUzI1NiJ9" not in gen.redact("t=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2ln"), "redact() JWT")
    check("s3cr3t!" not in gen.redact('{"password": "s3cr3t!"}'), "redact() JSON password")
    check("hunter2" not in gen.redact("postgres://user:hunter2@db/app"), "redact() URL credentials")


def test_budget_degrades_in_levels_and_lists_what_was_left_out():
    with tempfile.TemporaryDirectory() as d:
        info = gen.make_fixture(Path(d) / "p", "failing")
        out = Path(d) / "o"
        res = gen.generate(Path(d) / "p", info["execution_id"], "US-DEMO-01", None, artifact=True, standalone=False,
                           out_dir=out, budget=12_000, lang="en")
        ev = next(f for f in res["publish"] if f["kind"] == "evidence")
        check(ev["level"] > 0, "a small budget forces a lower level")
        check(ev["bytes"] <= 12_000 or ev["level"] == len(gen.LEVELS) - 1, "size within budget or at the last level")
        text = read(ev["file_path"])
        check("Left out of this page" in text or "was exceeded" in text, "the page says what was reduced")
        check(not gen.check_artifact_html(text, 12_000) or ev["over_budget"], "contract still holds when degraded")
    # a real 12 MB ceiling: huge screenshots are never embedded past it
    with tempfile.TemporaryDirectory() as d:
        info = gen.make_fixture(Path(d) / "p", "failing")
        big = Path(d) / "p" / "docs" / "qa" / "evidence" / info["execution_id"] / "sign-in" / "failure-moment.png"
        big.write_bytes(big.read_bytes() + b"\0" * (13 * 1024 * 1024))
        res = gen.generate(Path(d) / "p", info["execution_id"], "US-DEMO-01", None, artifact=True, standalone=False,
                           out_dir=Path(d) / "o", budget=gen.BUDGET_BYTES, lang="en")
        check(all(f["bytes"] <= gen.BUDGET_BYTES for f in res["files"]), "no page exceeds 12 MB")


# ------------------------------------------------------------------ settings and i18n

def test_artifact_is_on_by_default_and_opt_out_is_explicit():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        check(qa_scope.artifact_settings(root, env={})["publish"] is True, "default is ON")
        s = qa_scope.artifact_settings(root, env={}, no_artifact=True)
        check(s["publish"] is False and s["reason"] == "--no-artifact", "flag opts out")
        s = qa_scope.artifact_settings(root, env={"QA_SQUAD_NO_ARTIFACT": "1"})
        check(s["publish"] is False and s["reason"] == "QA_SQUAD_NO_ARTIFACT", "environment opts out")
        (root / ".qa").mkdir()
        (root / ".qa" / "config.json").write_text(json.dumps({"artifacts": {"publish": False, "language": "pt-BR"}}))
        s = qa_scope.artifact_settings(root, env={})
        check(s["publish"] is False and s["language"] == "pt-BR", "config opts out and sets the language")
        p = report(root, "--settings", extra_env={})
        check(json.loads(p.stdout)["publish"] is False, "--settings reports the resolved value")


def test_no_artifact_writes_standalone_documents_instead():
    with tempfile.TemporaryDirectory() as d:
        info = gen.make_fixture(Path(d) / "p", "failing")
        out = Path(d) / "o"
        p = report(Path(d) / "p", "--execution", info["execution_id"], "--scope", "US-DEMO-01", "--artifact",
                   "--no-artifact", "--out-dir", str(out))
        check(not out.exists() or not list(out.glob("*.html")), "no artifact fragments with --no-artifact")
        check("disabled" in p.stderr, "the opt-out is announced")
        scope_dir = Path(d) / "p" / "docs" / "qa" / "executions" / info["execution_id"] / "scope-US-DEMO-01"
        check((scope_dir / "evidence-report.html").exists(), "standalone documents are still written")
        p = report(Path(d) / "p", "--execution", info["execution_id"], "--scope", "US-DEMO-01", "--artifact",
                   "--out-dir", str(out), extra_env={"QA_SQUAD_NO_ARTIFACT": "1"})
        check(not list(out.glob("*.html")) if out.exists() else True, "the environment variable also opts out")


def test_portuguese_report_titles_and_labels():
    with tempfile.TemporaryDirectory() as d:
        info = gen.make_fixture(Path(d) / "p", "failing")
        out = Path(d) / "o"
        report(Path(d) / "p", "--execution", info["execution_id"], "--scope", "US-DEMO-01", "--artifact",
               "--out-dir", str(out), "--lang", "pt-BR")
        ev, fr = read(out / "qa-evidence-US-DEMO-01.html"), read(out / "qa-failures-US-DEMO-01.html")
        check("<title>Evidências QA US-DEMO-01</title>" in ev, "pt-BR evidence title")
        check("<title>Falhas QA US-DEMO-01</title>" in fr, "pt-BR failure title")
        check("Veredito" in ev and "Passos para reproduzir" in fr, "pt-BR labels")
        for t in (ev, fr):
            check(not gen.check_artifact_html(t), f"pt-BR page honours the contract: {gen.check_artifact_html(t)}")


def test_feature_scope_reports_only_tagged_items():
    with tempfile.TemporaryDirectory() as d:
        root = project(d, stories=False)
        cli(root, "scope-set", "--feature", "youth")
        cli(root, "inventory-add", "--category", "features", "--id", "features:youth:list", "--label", "Youth list")
        cli(root, "record", "--category", "features", "--id", "features:youth:list", "--status", "failed",
            "--notes", "list is empty", "--evidence", "shots/fail.png")
        cli(root, "scope-clear")
        cli(root, "inventory-add", "--category", "features", "--id", "features:finance:list", "--label", "Finance list")
        cli(root, "record", "--category", "features", "--id", "features:finance:list", "--status", "failed", "--notes", "finance broke")
        cli(root, "scope-set", "--feature", "youth")
        exec_id = cli(root, "execution-start").stdout.strip()
        cli(root, "execution-finish", "--execution", exec_id)
        out = Path(d) / "o"
        report(root, "--execution", exec_id, "--artifact", "--out-dir", str(out))
        ev, fr = read(out / "qa-evidence-youth.html"), read(out / "qa-failures-youth.html")
        check("Youth list" in ev and "Finance" not in ev and "Finance" not in fr, "feature scope is isolated")


def test_latest_resolves_the_newest_finished_execution():
    with tempfile.TemporaryDirectory() as d:
        info = gen.make_fixture(Path(d) / "p", "failing")
        _, manifest = gen.find_manifest(Path(d) / "p", "latest")
        check(manifest["execution"]["execution_id"] == info["execution_id"], "latest finds the execution")
        p = subprocess.run([sys.executable, str(GEN), "--root", d, "--execution", "latest"], text=True, capture_output=True,
                           env=env_for(d))
        check(p.returncode != 0 and "No finished execution" in (p.stdout + p.stderr), "clear error when none exists")


def test_selftest_passes():
    p = subprocess.run([sys.executable, str(GEN), "--selftest"], text=True, capture_output=True)
    check(p.returncode == 0, f"--selftest failed:\n{p.stdout}{p.stderr}")
    check("10/10 passed" in p.stdout or re.search(r"(\d+)/\1 passed", p.stdout), f"selftest summary: {p.stdout}")


def test_example_writer_builds_a_failing_and_a_clean_scope():
    with tempfile.TemporaryDirectory() as d:
        p = subprocess.run([sys.executable, str(GEN), "--write-example", str(Path(d) / "ex")], text=True, capture_output=True)
        check(p.returncode == 0, f"--write-example failed: {p.stderr}")
        files = sorted(x.name for x in (Path(d) / "ex" / "artifacts").glob("*.html"))
        check(files == ["qa-evidence-US-DEMO-01.html", "qa-evidence-US-DEMO-02.html", "qa-failures-US-DEMO-01.html"],
              f"example files: {files}")


# ---------------------------------------------------------------- goal evidence report

FAKE_WEBM = b"\x1a\x45\xdf\xa3" + b"fake webm payload" * 40
CHROME_GAP = "no Chrome, Chromium or Edge found"


def goal_project(tmp, with_video=True, video_bytes=FAKE_WEBM):
    """A project with two finished goals (PASS with 3 steps, FAIL with 2) built through qa-cli."""
    root = Path(tmp)
    cli(root, "init", "--goal", "test")
    shots, goals = root / ".qa" / "evidence" / "screenshots", root / ".qa" / "goals"
    vids = root / ".qa" / "evidence" / "videos"
    for d in (shots, goals, vids):
        d.mkdir(parents=True, exist_ok=True)
    exec_id = cli(root, "execution-start", "--executor", "qa-squad qa-test-goal / claude-sonnet-5-5",
                  "--base-url", "https://hml.example.test/", "--environment", "environment=Staging",
                  "--environment", "version=v2.8.1").stdout.strip()
    specs = [("login-ok", "passed", 3, "A registered user can sign in and sees the dashboard"),
             ("export-csv", "failed", 2, "An agent can export the filtered list as CSV")]
    for slug, status, count, title in specs:
        trace, args = [], []
        for n in range(1, count + 1):
            png = shots / f"{slug}-{n}.png"
            png.write_bytes(gen._png(640, 360, n + len(slug)))
            args += ["--evidence", png.relative_to(root).as_posix()]
            trace.append({"n": n, "action": "click", "role": "button", "name": f"Action {n}", "value": None,
                          "expect": f"state {n}", "checked": f"Page state {n}", "time": f"2026-11-12T14:02:{10 + n:02d}Z",
                          "status": "failed" if status == "failed" and n == count else "ok",
                          "screenshot": png.relative_to(root).as_posix()})
        run = {"execution": exec_id, "started_at": "2026-11-12T14:02:11Z", "finished_at": "2026-11-12T14:02:53Z",
               "environment": {"viewport": "1280x720"}, "trace": trace}
        if with_video:
            vid = vids / f"{slug}.webm"
            vid.write_bytes(video_bytes)
            args += ["--evidence", vid.relative_to(root).as_posix()]
            run["video"] = {"path": vid.relative_to(root).as_posix(), "duration_s": 42.0}
        goal = {"goal": title, "role": "agent", "entry": "https://hml.example.test/", "preconditions": "Seeded user",
                "max_steps": 10, "oracle": {"pass": ["URL matches /dashboard"], "forbidden": ["still on /login"]},
                "trace": trace, "last_run": run}
        extra = []
        if status == "failed":
            goal["azure_work_item"] = 4321
            run.update({"observed": "Error page 500. Authorization: Bearer abcdefghijklmnop12345678",
                        "console": ["POST /api/export 500"],
                        "network": [{"method": "POST", "url": "/api/export?token=zzzzzzzzzz", "status": 500, "ms": 1842}],
                        "oracle_results": {"pass": [{"state": "no", "evidence": "step 2"}],
                                           "forbidden": [{"state": "no", "evidence": "step 2"}]}})
            fid = cli(root, "finding", "--title", "Export fails", "--severity", "high", "--category", "scenarios",
                      "--location", "/export", "--scenario-id", f"scenario:goal:{slug}", "--actual", "500",
                      "--expected", "download", "--reproduction", "1. click").stdout.strip()
            extra = ["--finding-id", fid]
        (goals / f"{slug}.json").write_text(json.dumps(goal), encoding="utf-8")
        cli(root, "inventory-add", "--category", "scenarios", "--id", f"scenario:goal:{slug}", "--kind", "goal",
            "--label", title, "--profile-id", "agent", "--metadata",
            json.dumps({"origin": "goal", "expected": "URL matches /dashboard", "steps": ["a", "b"]}))
        cli(root, "record", "--category", "scenarios", "--id", f"scenario:goal:{slug}", "--status", status,
            "--scenario", title, "--profile-id", "agent", "--notes", f"{status.upper()} | steps {count}/10 | detail",
            *args, *extra)
    cli(root, "execution-finish", "--execution", exec_id)
    cli(root, "bug-report", "--scenario", "scenario:goal:export-csv", "--execution", exec_id, "--severity", "high",
        "--classification", "PRODUCT_DEFECT", "--summary", "Export returns 500", "--observed-fact", "Observed: 500")
    return exec_id


def goal_html(root, exec_id):
    return read(Path(root) / "docs" / "qa" / "executions" / exec_id / "scope-full" / gen.GOAL_REPORT_HTML)


def test_goal_report_has_cover_summary_goals_steps_and_annexes():
    with tempfile.TemporaryDirectory() as d:
        exec_id = goal_project(d)
        report(d, "--execution", exec_id, "--goal-report")
        text = goal_html(d, exec_id)
        check(text.lower().startswith("<!doctype html>"), "standalone document")
        check("<script" not in text.lower() and "<link" not in text.lower(), "no scripts or links")
        for needle in ("Test Evidence Report", "https://hml.example.test/", "Staging", "v2.8.1",
                       "qa-squad qa-test-goal / claude-sonnet-5-5", exec_id, "1 of 2 goals passed"):
            check(needle in text, f"cover and summary carry {needle!r}")
        check(text.count('id="g-1"') == 1 and text.count('id="g-2"') == 1, "one sheet per goal")
        check("PASS" in text and "FAIL" in text and "INCONCLUSIVE" in text, "verdict codes, never colour only")
        check(text.count('<li class="step') == 5, "one timeline entry per step (3 + 2)")
        check(text.count('<figure class="shot') == 5, "one screenshot per step")
        check("st-bad" in text and "Expected" in text and "Observed" in text, "FAIL shows expected and observed")
        check("POST" in text and "/api/export" in text, "network summary")
        check("token=***" in text and "zzzzzzzzzz" not in text and not gen.secrets_leaked(text), "secrets masked")
        check("BUG-" in text and "BUG-REPORT.md" in text and "4321" in text, "bug link, local file and work item")
        check("QA responsible" in text and "Contract inspector" in text and text.count("Signature") == 2, "two signatories")
        check("size:A4" in text and "counter(pages)" in text and "@page :first" in text, "A4 page rules and page counter")
        check("Annex A" in text and "SHA-256" in text and "Annex B" in text and "1280x720" in text, "annexes")
        ids = set(re.findall(r'id="([^"]+)"', text))
        check(all(h in ids for h in re.findall(r'href="#([^"]+)"', text)), "every anchor has a target")


def test_goal_report_references_video_by_relative_path_and_hashes_files():
    with tempfile.TemporaryDirectory() as d:
        exec_id = goal_project(d)
        report(d, "--execution", exec_id, "--goal-report")
        text = goal_html(d, exec_id)
        srcs = re.findall(r'<video[^>]*\ssrc="([^"]+)"', text)
        check(len(srcs) == 2 and all(s.endswith(".webm") and not s.startswith(("http", "/", "data:")) for s in srcs),
              f"relative video sources: {srcs}")
        check(re.search(r'<video[^>]*poster="data:image/', text), "poster is the first screenshot")
        digest = hashlib.sha256(FAKE_WEBM).hexdigest()
        check(digest in text, "video SHA-256 on the page")
        sums = (Path(d) / "docs" / "qa" / "executions" / exec_id / "scope-full" / gen.SHA_SUMS_NAME).read_text()
        check(sums.count(".png") == 5 and sums.count(".webm") == 2 and gen.GOAL_REPORT_HTML in sums,
              "SHA256SUMS covers screenshots, videos and the report")
        p = subprocess.run(["sha256sum", "-c", gen.SHA_SUMS_NAME], cwd=Path(d) / "docs" / "qa" / "executions" / exec_id / "scope-full",
                           text=True, capture_output=True) if shutil.which("sha256sum") else None
        check(p is None or p.returncode == 0, f"sha256sum -c: {p and p.stdout}{p and p.stderr}")


def test_goal_report_pt_br_labels():
    with tempfile.TemporaryDirectory() as d:
        exec_id = goal_project(d)
        report(d, "--execution", exec_id, "--goal-report", "--lang", "pt-BR")
        text = goal_html(d, exec_id)
        for needle in ("Relatório de Evidências de Teste", "Resumo executivo", "1 de 2 objetivos aprovados",
                       "Esperado", "Obtido", "Responsável QA", "Fiscal / gestor do contrato", "Assinatura",
                       "Passo a passo com evidências", "Aprovado", "Reprovado"):
            check(needle in text, f"pt-BR label {needle!r}")
        check(text.count("Página") >= 1 and "counter(pages)" in text, "page counter label from i18n")


def test_goal_report_pt_br_has_no_english_scope_text():
    with tempfile.TemporaryDirectory() as d:
        exec_id = goal_project(d)
        out = Path(d) / "art"
        report(d, "--execution", exec_id, "--goal-report", "--lang", "pt-BR", "--artifact", "--out-dir", str(out))
        text = goal_html(d, exec_id)
        plan = " ".join(e.get("description", "") for e in json.loads(
            (out / "artifact-plan.json").read_text(encoding="utf-8"))["publish"])
        for blob, name in ((text, "report"), (plan, "plan description")):
            for leak in ("the full scope", "Full audit"):
                check(leak not in blob, f"no English {leak!r} in pt-BR goal {name}")
        check("Auditoria completa" in text, "scope title localized on the cover")
        check("todo o escopo" in plan, "plan description localized")
        report(d, "--execution", exec_id, "--goal-report", "--lang", "en", "--artifact", "--out-dir", str(out))
        check("Full audit" in goal_html(d, exec_id), "English scope title kept for en")


def test_goal_artifact_lists_videos_as_files_and_passes_the_contract():
    with tempfile.TemporaryDirectory() as d:
        exec_id = goal_project(d)
        out = Path(d) / "art"
        report(d, "--execution", exec_id, "--goal-report", "--artifact", "--out-dir", str(out))
        plan = json.loads((out / "artifact-plan.json").read_text())
        entry = next(e for e in plan["publish"] if e["kind"] == "goal-evidence")
        check(sorted(entry["files"]) == ["videos/export-csv.webm", "videos/login-ok.webm"], f"files map: {entry['files']}")
        check(all(Path(v).is_file() for v in entry["files"].values()), "sources exist")
        text = read(entry["file_path"])
        check(not entry["contract"], f"contract violations: {entry['contract']}")
        check(not gen.check_artifact_html(text, allowed_files=set(entry["files"])), "contract holds with the files map")
        check('src="videos/login-ok.webm"' in text, "published relative path in the page")
        check(re.search(r"<title>Goal Evidence</title>", text), "two-word title")
        problems = gen.check_artifact_html(text)
        check(any("video[src]" in x for x in problems), "unlisted video is rejected")
        # an artifact plan written by the scope reports keeps its entries
        report(d, "--execution", exec_id, "--artifact", "--out-dir", str(out), "--category", "scenarios")
        report(d, "--execution", exec_id, "--goal-report", "--artifact", "--out-dir", str(out))
        kinds = [e["kind"] for e in json.loads((out / "artifact-plan.json").read_text())["publish"]]
        check(kinds.count("goal-evidence") == 1 and "evidence" in kinds, f"plan merge: {kinds}")


def test_contract_checker_video_rules():
    base = build_pages_good()
    listed = base.replace("<main", '<video controls src="videos/a.webm"></video><main', 1)
    check(not gen.check_artifact_html(listed, allowed_files={"videos/a.webm"}), "listed relative video accepted")
    check(gen.check_artifact_html(listed), "unlisted video rejected")
    for bad in ("https://example.test/a.webm", "//example.test/a.webm", "videos/a.exe", "../a.webm"):
        text = base.replace("<main", f'<video controls src="{bad}"></video><main', 1)
        check(gen.check_artifact_html(text, allowed_files={"videos/a.webm"}), f"{bad} rejected")
    check(gen.check_artifact_html(base.replace("<main", '<img src="videos/a.webm"><main', 1), allowed_files={"videos/a.webm"}),
          "only <video src> may name a published file")


def test_large_video_is_listed_not_embedded():
    with tempfile.TemporaryDirectory() as d:
        exec_id = goal_project(d, video_bytes=b"\x1a\x45\xdf\xa3" + b"0" * 5000)
        old = gen.VIDEO_PUBLISH_MAX
        gen.VIDEO_PUBLISH_MAX = 1000
        try:
            res = gen.generate_goal_report(Path(d), exec_id, "current", None, artifact=True, out_dir=Path(d) / "art",
                                           budget=gen.BUDGET_BYTES, lang="en")
        finally:
            gen.VIDEO_PUBLISH_MAX = old
        entry = res["publish"][0]
        check(entry["files"] == {}, "no video is published over the limit")
        check(len(entry["videos_not_published"]) == 2 and all(v["sha256"] for v in entry["videos_not_published"]),
              "skipped videos are listed with their hash")
        text = read(entry["file_path"])
        check("<video" not in text and "not published" in text.lower(), "page says the video is not published")
        check("login-ok.webm" in text and not entry["contract"], f"filename stays on the page: {entry['contract']}")
        check(all(f["bytes"] <= gen.BUDGET_BYTES for f in res["files"]), "within the 12 MB budget")
        standalone = goal_html(d, exec_id)
        check("<video" in standalone, "the standalone report still references the video")


def test_goal_report_budget_degrades_images_not_the_page_structure():
    with tempfile.TemporaryDirectory() as d:
        exec_id = goal_project(d)
        res = gen.generate_goal_report(Path(d), exec_id, "current", None, artifact=True, out_dir=Path(d) / "art",
                                       budget=30_000, lang="en")
        entry = res["publish"][0]
        check(entry["level"] > 0 and entry["omitted"], "a small budget drops step images and lists them")
        text = read(entry["file_path"])
        check(text.count('<li class="step') == 5, "every step stays on the page")


def test_goal_report_without_a_video_or_goal_file_still_renders():
    with tempfile.TemporaryDirectory() as d:
        exec_id = goal_project(d, with_video=False)
        shutil.rmtree(Path(d) / ".qa" / "goals")
        report(d, "--execution", exec_id, "--goal-report")
        text = goal_html(d, exec_id)
        check("No video was recorded" in text and "<video" not in text, "missing video is said, not hidden")
        check(text.count('id="g-') >= 2, "goals come from the manifest alone")


def test_tracker_reference_is_validated():
    check(gen.tracker_ref(4321, "") == {"id": "4321", "url": ""}, "numeric id")
    check(gen.tracker_ref("javascript:alert(1)", "") is None, "script URL ignored")
    check(gen.tracker_ref("http://insecure.test/x", "") is None, "plain http ignored")
    check(gen.tracker_ref({"id": "7", "url": "https://dev.azure.test/o/p/_workitems/edit/7"}, "")["url"].startswith("https://"),
          "https URL kept")
    check(gen.tracker_ref("12", "https://dev.azure.test/o/p/_workitems/edit/{id}")["url"].endswith("/edit/12"),
          "config template builds the URL")
    check(gen.tracker_ref("https://dev.azure.test/o/p/_workitems/edit/99", "")["id"] == "99", "id read from the URL")


def test_pdf_is_skipped_with_one_line_when_no_chrome_exists():
    with tempfile.TemporaryDirectory() as d:
        exec_id = goal_project(d)
        empty = Path(d) / "emptybin"
        empty.mkdir()
        env = {"PATH": str(empty), "HOME": str(empty), "CHROME_BIN": "", "PLAYWRIGHT_BROWSERS_PATH": "", "LOCALAPPDATA": ""}
        check(gen.find_chrome(env) is None, "no browser found")
        res = gen.pdf_from_html(Path(d) / "x.html", Path(d) / "x.pdf", env=env)
        check(res["status"] == "skipped" and CHROME_GAP in res["reason"], f"skip reason: {res}")
        p = subprocess.run([sys.executable, str(GEN), "--root", d, "--execution", exec_id, "--goal-report", "--pdf"],
                           env=env_for(d, env), text=True, capture_output=True)
        check(p.returncode == 0, f"exit 0 without Chrome: {p.stdout}{p.stderr}")
        check(p.stderr.count("PDF skipped") == 1 and CHROME_GAP in p.stderr, f"one clear line: {p.stderr!r}")
        scope = Path(d) / "docs" / "qa" / "executions" / exec_id / "scope-full"
        check((scope / gen.GOAL_REPORT_HTML).exists() and not (scope / gen.GOAL_REPORT_PDF).exists(), "HTML written, no PDF")
        check(gen.GOAL_REPORT_PDF not in (scope / gen.SHA_SUMS_NAME).read_text(), "no PDF in SHA256SUMS")


def test_chrome_discovery_order():
    with tempfile.TemporaryDirectory() as d:
        fake = Path(d) / "fakechrome"
        fake.write_text("#!/bin/sh\n", encoding="utf-8")
        fake.chmod(0o755)
        check(gen.find_chrome({"CHROME_BIN": str(fake), "PATH": ""}) == str(fake), "$CHROME_BIN wins")
        check(gen.find_chrome({"CHROME_BIN": str(Path(d) / "missing"), "PATH": ""}) is None, "a bad $CHROME_BIN is not silently replaced")
        cache = Path(d) / "pw" / "chromium-1/chrome-linux64"
        cache.mkdir(parents=True)
        (cache / "chrome").write_text("x", encoding="utf-8")
        check(gen.find_chrome({"PATH": "", "HOME": d, "PLAYWRIGHT_BROWSERS_PATH": str(Path(d) / "pw")}) == str(cache / "chrome"),
              "Playwright cache is searched")


def test_pdf_flag_needs_goal_report():
    p = subprocess.run([sys.executable, str(GEN), "--pdf"], text=True, capture_output=True)
    check(p.returncode != 0 and "--goal-report" in p.stderr, "usage error")


def test_real_pdf_is_a4_with_the_report_text():
    if not gen.find_chrome():
        print("    (no Chrome found: real PDF check skipped)")
        return
    with tempfile.TemporaryDirectory() as d:
        exec_id = goal_project(d)
        p = report(d, "--execution", exec_id, "--goal-report", "--pdf", "--lang", "pt-BR")
        scope = Path(d) / "docs" / "qa" / "executions" / exec_id / "scope-full"
        pdf = scope / gen.GOAL_REPORT_PDF
        check(pdf.is_file() and pdf.read_bytes()[:5] == b"%PDF-", f"PDF written: {p.stdout}{p.stderr}")
        raw = pdf.read_bytes()
        box = re.search(rb"/MediaBox\s*\[\s*0\s+0\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s*\]", raw)
        check(box and abs(float(box.group(1)) - 595) < 2 and abs(float(box.group(2)) - 842) < 2, f"A4 MediaBox: {box and box.groups()}")
        check(gen.GOAL_REPORT_PDF in (scope / gen.SHA_SUMS_NAME).read_text(), "PDF in SHA256SUMS")
        if shutil.which("pdftotext"):
            txt = subprocess.run(["pdftotext", str(pdf), "-"], text=True, capture_output=True).stdout
            check("Página 2 de" in txt and "Relatório de Evidências de Teste" in txt, "page X of Y footer and cover text")


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
    print(f"artifact report tests: {len(TESTS) - len(failures)}/{len(TESTS)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
