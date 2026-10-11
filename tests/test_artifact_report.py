#!/usr/bin/env python3
"""Behavioral tests for scope support and the evidence/failure report generator.

Everything runs on fixtures: no application, no browser, no network. Uses explicit failure
reporting rather than bare `assert`, so the suite keeps working under `python3 -O`.
"""
import importlib.util
import json
import os
import re
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
