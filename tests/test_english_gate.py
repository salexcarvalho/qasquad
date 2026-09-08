#!/usr/bin/env python3
"""Tests for the English-only gate.

A language gate is only useful if it has both recall (it catches real Portuguese) and
precision (it does not cry wolf on legitimate English technical prose). Both are tested
here, because a noisy gate gets disabled and a blind gate protects nothing.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
GATE = PKG / "scripts" / "check_english_only.py"


class Failure(Exception):
    pass


def check(condition, message):
    if not condition:
        raise Failure(message)


def scan(files, allowlist=None):
    """Run the gate over a throwaway tree and return (returncode, stdout)."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "scripts").mkdir()
        for name, content in files.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        if allowlist is not None:
            (root / "scripts" / "i18n-allowlist.txt").write_text(allowlist, encoding="utf-8")
        p = subprocess.run(
            [sys.executable, str(GATE), "--root", str(root)],
            text=True, capture_output=True,
        )
        return p.returncode, p.stdout


PORTUGUESE_SAMPLES = {
    "a.md": "Você deve executar a auditoria quando a cobertura estiver incompleta.\n",
    "b.md": "Nunca confunda funciona com está correto.\n",
    "c.md": "Registre o achado com evidência e severidade.\n",
    "d.py": '"""Valide a navegação por perfil antes do relatório final."""\n',
    "e.md": "Não realize operações destrutivas em produção.\n",
    "f.md": "O inventário define o denominador da cobertura.\n",
}

ENGLISH_SAMPLES = {
    "ok1.md": (
        "# Coverage auditor\n\n"
        "The auditor validates that every inventoried item has a persisted result.\n"
        "Capture evidence, compare screens, and declare the environment requirements.\n"
        "Visit https://github.com/example/repo for the implementation details.\n"
    ),
    "ok2.md": (
        "Run the deterministic validation to observe whether the configuration is "
        "maintainable, reusable and accessible.\n"
        "Manage the deployment environment and document each measurement.\n"
    ),
    "ok3.py": (
        '"""Execute the audit and capture output."""\n'
        "import subprocess\n"
        "def main():\n"
        "    return subprocess.run(['ls'], capture_output=True)\n"
    ),
    "ok4.md": "| Severity | Meaning |\n|---|---|\n| critical | Data loss or an outage. |\n",
}


def test_detects_portuguese():
    rc, out = scan(PORTUGUESE_SAMPLES)
    check(rc == 1, "gate must fail when Portuguese is present")
    for name in PORTUGUESE_SAMPLES:
        check(name in out, f"gate missed Portuguese content in {name}")


def test_no_false_positives_on_english():
    rc, out = scan(ENGLISH_SAMPLES)
    check(rc == 0, f"gate must pass on legitimate English prose, but reported:\n{out}")


def test_reports_file_line_content_and_suggestion():
    rc, out = scan({"x.md": "A cobertura está incompleta.\n"})
    check(rc == 1, "gate must fail")
    check("x.md:1" in out, "output must carry file and line")
    check("detected" in out, "output must show the detected content")
    check("suggestion" in out, "output must show a suggested correction")
    check("coverage" in out, "suggestion should map cobertura to coverage")


def test_reports_zero_when_clean():
    rc, out = scan({"clean.md": "This document is written in English.\n"})
    check(rc == 0, "clean tree must pass")
    check("Portuguese occurrences remaining: 0" in out,
          "a clean tree must state that zero occurrences remain")


def test_allowlist_exempts_specific_line():
    files = {"keep.md": "Mantenha esta linha em portugues por decisao editorial.\n"}
    rc, _ = scan(files)
    check(rc == 1, "line must be flagged without an allowlist")
    rc, _ = scan(files, allowlist="keep.md :: decisao editorial\n")
    check(rc == 0, "allowlist must exempt the matching line")


def test_allowlist_exempts_whole_file():
    files = {"legacy.md": "Todo o conteudo deste arquivo permanece em portugues.\n"}
    rc, _ = scan(files, allowlist="legacy.md\n")
    check(rc == 0, "a bare path rule must exempt the whole file")


def test_ignores_excluded_directories():
    rc, _ = scan({"node_modules/pkg/readme.md": "Voce deve instalar a dependencia.\n"})
    check(rc == 0, "vendored directories must not be scanned")


def test_scans_extensionless_cli():
    rc, out = scan({"qa-cli": "# Valide a cobertura antes do relatorio\n"})
    check(rc == 1, "the extensionless qa-cli file must be scanned")
    check("qa-cli" in out, "finding must name the qa-cli file")


def test_real_repository_is_clean():
    """The gate must report zero occurrences across this repository."""
    p = subprocess.run([sys.executable, str(GATE)], text=True, capture_output=True)
    check(p.returncode == 0, f"repository still contains Portuguese content:\n{p.stdout}")
    check("Portuguese occurrences remaining: 0" in p.stdout,
          "gate did not confirm zero remaining occurrences")


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]


def main():
    failures = []
    for fn in TESTS:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except Failure as exc:
            failures.append(fn.__name__)
            print(f"  FAIL  {fn.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures.append(fn.__name__)
            print(f"  ERROR {fn.__name__}: {exc!r}")
    print(f"english gate tests: {len(TESTS) - len(failures)}/{len(TESTS)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
