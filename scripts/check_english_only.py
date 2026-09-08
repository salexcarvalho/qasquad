#!/usr/bin/env python3
"""English-only repository gate.

Fails when Portuguese (or mixed Portuguese/English) content is introduced into
project text files.

Detection is deliberately NOT based on accented characters: legitimate English
technical files may contain Unicode (arrows, box drawing, em dashes, names).
Instead the gate combines two maintainable signals:

  1. A curated lexicon of high-precision Portuguese function words that are not
     also valid English words ("nao", "voce", "quando", "cobertura", ...).
  2. Portuguese morphology (suffixes such as -cao, -coes, -avel, -mente, -ncia)
     applied only to reasonably long tokens.

A line is reported when it contains at least one strong lexicon marker, or at
least two independent morphology hits. Intentional exceptions live in
scripts/i18n-allowlist.txt.

Usage:
    python3 scripts/check_english_only.py [--json] [--root PATH]

Exit codes:
    0  no Portuguese content detected
    1  Portuguese content detected
    2  invalid usage / configuration
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
import unicodedata
from pathlib import Path

SCAN_EXTENSIONS = {
    ".md", ".py", ".json", ".yml", ".yaml", ".toml", ".sh", ".bash",
    ".txt", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".cfg", ".ini",
}

# Extensionless files that are still project text we care about.
EXTRA_FILENAMES = {"qa-cli"}

EXCLUDED_DIRS = {
    ".git", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".venv", "venv", "dist", "build", ".qa", "evidence",
    ".idea", ".vscode", "coverage", ".tox",
}

# High-precision Portuguese markers. Every entry is compared in accent-stripped
# lowercase form and must NOT be a valid English word, so that English technical
# prose never trips the gate.
STRONG_MARKERS = {
    # function words / pronouns / determiners
    "nao", "voce", "voces", "quando", "porque", "porem", "tambem",
    "entao", "apos", "antes", "ainda", "cada", "todos", "todas", "toda",
    "muito", "muitos", "muitas", "pouco", "poucos", "mais", "menos",
    "apenas", "somente", "sempre", "nunca", "talvez", "assim", "aqui",
    "onde", "qual", "quais", "quem", "cujo", "cuja", "isso", "isto",
    "esse", "essa", "esses", "essas", "este", "esta", "estes", "estas",
    "aquele", "aquela", "aqueles", "aquelas", "pelo", "pela", "pelos",
    "pelas", "dele", "dela", "deles", "delas", "seu", "sua", "seus", "suas",
    "nosso", "nossa", "nossos", "nossas", "meu", "minha", "para", "pra",
    "sobre", "entre", "durante", "atraves", "conforme", "segundo",
    "enquanto", "embora", "caso", "salvo", "exceto", "alem", "atras",
    "abaixo", "acima", "dentro", "fora", "junto", "contra", "desde",
    "sem", "nas", "numa",
    "uma", "uns", "umas", "outro", "outra", "outros", "outras", "mesmo",
    "mesma", "proprio", "propria", "qualquer", "quaisquer", "nenhum",
    "nenhuma", "algum", "alguma", "alguns", "algumas",
    # verbs (common conjugations)
    "sao", "esta", "estao", "estava", "estavam", "sera", "serao", "seja",
    "sejam", "foi", "foram", "fosse", "sendo", "sido", "ser", "ter", "tem",
    "tinha", "tinham", "havia", "houver", "pode", "podem", "podera",
    "poderia", "deve", "devem", "devera", "deveria", "faz", "fazer", "feito",
    "usar", "usando", "utilizar", "executar",
    "registre", "registrar", "verifique", "verificar", "valide", "validar",
    "teste", "testar", "gere", "gerar", "leia", "ler", "escreva", "escrever",
    "descubra", "descobrir", "avalie", "avaliar", "inicialize", "inicializar",
    "prefira", "preferir", "evite", "evitar", "procure", "procurar",
    "comparar", "confirme", "confirmar", "capturar",
    "marque", "marcar", "inclua", "incluir", "exija", "exigir", "exige",
    "conduza", "conduzir", "siga", "seguir", "delegue", "delegar",
    "consulte", "consultar", "finalizar", "informe", "informar",
    "preencha", "preencher", "adapte", "adaptar", "acrescente", "assuma",
    "invente", "confunda", "considere", "altere",
    "corrija", "remova", "vincule", "limite", "processe",
    "apresente", "destacando", "priorizando", "incluindo", "orientar",
    "contaminar", "mascarar", "provoque", "simule", "meça", "audite", "auditar", "cubra", "cobrir", "trabalhe", "acesse",
    "autentique", "inspecione", "identifique", "diferencie", "proponha",
    "associe", "mantenha", "garanta", "encerramento",
    # QA / project domain nouns that are Portuguese-only
    "cobertura", "descoberta", "descobre", "inventario", "inventarios",
    "resultado", "resultados", "achado", "achados", "perfil", "perfis",
    "papel", "papeis", "usuario", "usuarios", "senha", "senhas", "segredo",
    "segredos", "evidencia", "evidencias", "relatorio", "relatorios",
    "auditoria", "auditorias", "formulario", "formularios",
    "rota", "rotas", "tela", "telas", "botao", "botoes", "campo", "campos",
    "pagina", "paginas", "ambiente", "ambientes",
    "arquivo", "arquivos", "pasta", "pastas", "codigo", "linha", "linhas",
    "erro", "erros", "falha", "falhas", "problema", "problemas", "risco",
    "riscos", "regra", "regras", "requisito", "requisitos", "objetivo",
    "objetivos", "escopo", "estado", "estados", "etapa", "etapas",
    "passo", "passos", "prova", "provas", "aprovacao", "reprovacao",
    "gargalo", "gargalos", "carga", "concorrencia", "consulta", "consultas",
    "conhecimento", "comportamento", "comportamentos", "coerencia",
    "divergencia", "divergencias", "duplicidade", "ordenacao", "paginacao",
    "atalho", "atalhos", "jornada", "jornadas", "fluxo", "fluxos",
    "seletor", "seletores", "teclado", "foco", "contraste", "tamanho",
    "alvo", "alvos", "largura", "altura", "tabela", "tabelas", "aba",
    "abas", "janela", "janelas", "vazio", "vazia", "cheio", "invalido",
    "invalida", "valido", "valida", "obrigatorio", "obrigatoria",
    "obrigatorios", "obrigatorias", "necessario", "necessaria",
    "disponivel", "disponiveis", "esperado", "esperada", "atual", "atuais",
    "anterior", "proximo", "primeiro", "primeira", "ultimo", "ultima",
    "seguinte", "seguintes", "abrangente", "generico", "generica",
    "genericos", "genericas", "especializado", "especializados",
    "persistido", "persistida", "persistente", "rastreavel", "rastreaveis",
    "reproduzivel", "reproduziveis", "descartavel", "destrutivo",
    "destrutiva", "destrutivos", "destrutivas", "incompleto", "incompleta",
    "completo", "completa", "faltam", "faltando", "ausente", "ausentes",
    "oculto", "oculta", "visivel", "visiveis", "correto", "correta",
    "incorreto", "incorreta", "seguro", "segura", "leitura", "escrita",
    "gravacao", "contexto", "conteudo", "detalhe", "detalhes",
    "nomenclatura", "carga", "ruido", "recuperacao", "prevencao",
    "quantidade", "numero", "denominador", "numerador", "amostragem",
    "hipotese", "hipoteses", "limitacao", "limitacoes", "justificativa",
    "impacto", "recomendacao", "recomendacoes", "severidade", "gravidade",
    "reteste", "retestar", "encerrar", "conclusao", "concluida",
    "concluido", "iniciada", "iniciado", "pendente", "pendentes",
    "sucesso", "aviso", "mensagem", "mensagens", "rotulo", "rotulos",
    "titulo", "titulos", "caminho", "caminhos", "modulo", "modulos",
    "estrita", "estrito", "manutencao",
}

# Tokens that are ambiguous (valid in both languages, or common in URLs and
# code) and must never on their own trigger a finding.
AMBIGUOUS_BLOCKLIST = {
    "a", "as", "e", "o", "os", "da", "de", "do", "no", "na", "em", "se",
    "so", "eu", "ele", "ela", "la", "me", "te", "ou", "mas", "que", "por",
    "um", "ao", "id", "ids", "meta", "menu", "menus", "final", "total",
    "normal", "local", "real", "base", "data", "media", "status",
    "sim", "num", "dos", "nos", "das", "aos", "ate", "com", "auditor",
}

# Portuguese morphology. Applied to accent-stripped tokens of length >= 6.
MORPHOLOGY_SUFFIXES = (
    "cao", "coes", "avel", "aveis", "ivel", "iveis", "mente", "dade",
    "dades", "encia", "encias", "ancia", "ancias", "agem", "agens",
    "izacao", "amento", "amentos", "imento", "imentos",
)

# English words that would otherwise be caught by the morphology rules.
MORPHOLOGY_EXCEPTIONS = {
    "management", "environment", "environments", "requirement", "requirements",
    "improvement", "improvements", "document", "documents", "argument",
    "arguments", "assignment", "statement", "statements", "increment",
    "implement", "implementation", "element", "elements", "component",
    "components", "instrument", "comment", "comments", "development",
    "deployment", "attachment", "enforcement", "measurement", "agreement",
    "achievement", "moment", "segment", "treatment", "experiment",
    "package", "packages", "message", "messages", "coverage", "storage",
    "usage", "language", "languages", "image", "images", "page", "pages",
    "stage", "stages", "manage", "damage", "average", "leverage", "homepage",
    "reusable", "available", "variable", "variables", "observable",
    "testable", "traceable", "readable", "disable", "enable", "table",
    "tables", "stable", "unstable", "portable", "editable", "runnable",
    "reachable", "unreachable", "actionable", "configurable", "maintainable",
    "scalable", "repeatable", "verifiable", "auditable", "accessible",
    "visible", "invisible", "possible", "impossible", "responsible",
    "flexible", "credible", "compatible", "reproducible", "deterministic",
}

# Suggested English replacements for the most frequent Portuguese terms, used to
# make findings actionable. Unknown terms fall back to a generic hint.
GLOSSARY = {
    "nao": "not / do not", "sao": "are", "esta": "is", "estao": "are",
    "voce": "you", "quando": "when", "porque": "because", "tambem": "also",
    "apos": "after", "entao": "then", "cada": "each", "todos": "all",
    "apenas": "only", "sempre": "always", "nunca": "never", "sem": "without",
    "para": "for / to", "sobre": "about", "entre": "between", "onde": "where",
    "cobertura": "coverage", "descoberta": "discovery",
    "inventario": "inventory", "inventarios": "inventories",
    "resultado": "result", "resultados": "results", "achado": "finding",
    "achados": "findings", "perfil": "profile", "perfis": "profiles",
    "usuario": "user", "usuarios": "users", "senha": "password",
    "segredo": "secret", "segredos": "secrets", "evidencia": "evidence",
    "evidencias": "evidence", "relatorio": "report", "relatorios": "reports",
    "auditoria": "audit", "formulario": "form", "formularios": "forms",
    "rota": "route", "rotas": "routes", "tela": "screen", "telas": "screens",
    "botao": "button", "botoes": "buttons", "campo": "field",
    "campos": "fields", "pagina": "page", "paginas": "pages",
    "ambiente": "environment", "arquivo": "file", "arquivos": "files",
    "codigo": "code", "erro": "error", "erros": "errors", "falha": "failure",
    "regra": "rule", "regras": "rules", "objetivo": "goal",
    "escopo": "scope", "estado": "state", "etapa": "step", "passo": "step",
    "fluxo": "flow", "fluxos": "flows", "jornada": "journey",
    "obrigatorio": "required", "necessario": "required",
    "esperado": "expected", "atual": "actual", "generico": "generic",
    "severidade": "severity", "impacto": "impact",
    "recomendacao": "recommendation", "justificativa": "justification",
    "limitacao": "limitation", "conteudo": "content", "contexto": "context",
    "caminho": "path", "titulo": "title", "mensagem": "message",
    "faltam": "missing", "incompleto": "incomplete", "conclusao": "conclusion",
    "leitura": "read", "escrita": "write", "seguro": "safe",
    "destrutivo": "destructive", "rastreavel": "traceable",
    "reproduzivel": "reproducible", "persistido": "persisted",
    "validacao": "validation", "execucao": "execution",
    "navegacao": "navigation", "permissao": "permission",
    "permissoes": "permissions", "aplicacao": "application",
    "acessibilidade": "accessibility", "responsividade": "responsiveness",
    "seguranca": "security", "autorizacao": "authorization",
    "autenticacao": "authentication", "integridade": "integrity",
    "resiliencia": "resilience", "desempenho": "performance",
    "consistencia": "consistency", "usabilidade": "usability",
}

TOKEN_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+")


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def load_allowlist(path: Path) -> list[tuple[str, re.Pattern[str] | None]]:
    """Parse the allowlist file into (path_glob, optional line regex) rules."""
    rules: list[tuple[str, re.Pattern[str] | None]] = []
    if not path.exists():
        return rules
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "::" in line:
            glob_part, regex_part = line.split("::", 1)
            rules.append((glob_part.strip(), re.compile(regex_part.strip())))
        else:
            rules.append((line, None))
    return rules


def is_allowed(rel_path: str, line: str, rules) -> bool:
    for glob_part, regex in rules:
        if fnmatch.fnmatch(rel_path, glob_part):
            if regex is None or regex.search(line):
                return True
    return False


def analyze_line(line: str) -> tuple[list[str], list[str]]:
    """Return (strong marker hits, morphology hits) for a single line."""
    strong: list[str] = []
    morph: list[str] = []
    for raw_token in TOKEN_RE.findall(line):
        token = strip_accents(raw_token).lower()
        if token in AMBIGUOUS_BLOCKLIST:
            continue
        if token in STRONG_MARKERS:
            strong.append(raw_token)
            continue
        if len(token) >= 6 and token not in MORPHOLOGY_EXCEPTIONS:
            if token.endswith(MORPHOLOGY_SUFFIXES):
                morph.append(raw_token)
    return strong, morph


def suggest(hits: list[str]) -> str:
    parts = []
    for hit in dict.fromkeys(hits):
        key = strip_accents(hit).lower()
        if key in GLOSSARY:
            parts.append(f"{hit} -> {GLOSSARY[key]}")
    if parts:
        return "; ".join(parts[:4])
    return "translate this line to professional technical English"


def iter_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in EXCLUDED_DIRS for part in path.relative_to(root).parts):
            continue
        if path.suffix.lower() in SCAN_EXTENSIONS or path.name in EXTRA_FILENAMES:
            yield path


def scan(root: Path, rules) -> list[dict]:
    findings: list[dict] = []
    for path in iter_files(root):
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            strong, morph = analyze_line(line)
            if not strong and len(morph) < 2:
                continue
            if is_allowed(rel, line, rules):
                continue
            hits = strong + morph
            findings.append({
                "file": rel,
                "line": lineno,
                "detected": line.strip()[:160],
                "markers": hits[:8],
                "suggestion": suggest(hits),
            })
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description="Fail the build on non-English content.")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    ap.add_argument("--json", action="store_true", help="emit machine-readable output")
    ap.add_argument("--allowlist", default=None)
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"Root is not a directory: {root}", file=sys.stderr)
        return 2

    allowlist_path = Path(args.allowlist) if args.allowlist else root / "scripts" / "i18n-allowlist.txt"
    rules = load_allowlist(allowlist_path)
    findings = scan(root, rules)

    if args.json:
        print(json.dumps({"count": len(findings), "findings": findings}, indent=2, ensure_ascii=False))
        return 1 if findings else 0

    if not findings:
        print("ENGLISH-ONLY GATE: PASS")
        print("Portuguese occurrences remaining: 0")
        return 0

    print("ENGLISH-ONLY GATE: FAIL")
    print(f"Portuguese occurrences remaining: {len(findings)}")
    print()
    print("File -> Line -> Detected content -> Suggested correction")
    print("-" * 78)
    for f in findings:
        print(f"{f['file']}:{f['line']}")
        print(f"  detected  : {f['detected']}")
        print(f"  markers   : {', '.join(f['markers'])}")
        print(f"  suggestion: {f['suggestion']}")
    print()
    print(f"Total: {len(findings)} line(s) with Portuguese content.")
    print("Add intentional exceptions to scripts/i18n-allowlist.txt.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
