"""Fail if personal data is about to enter this repo.

Two layers:
1. Generic patterns that should never appear in a public CV tool: real-looking email addresses, UK mobile
   numbers and full UK postcodes. Fictional ones pass: addresses on documentation domains (example.com, .example,
   .test) and Ofcom's drama range (07700 900000 to 07700 900999). Documents (PDF, Word and the like) are refused
   outright, because they can hold a whole CV and cannot be scanned.
2. The maintainer's own terms, one per line in `.private-terms` at the repo root. That file is gitignored, so
   the list of what to hide is never published itself, and committing it (even with `git add -f`) fails here.

With --staged it also checks the commit author's email, since every commit publishes it.

Usage:
  python dev/check_private_data.py                  # every file git would commit (tracked or untracked, not ignored)
  python dev/check_private_data.py --staged         # what is staged now (the pre-commit hook runs this)
  python dev/check_private_data.py --message FILE   # a commit message (the commit-msg hook runs this)
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TERMS_NAME = ".private-terms"
TERMS_FILE = ROOT / TERMS_NAME
BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2"}
# Documents that can carry a whole CV but cannot be read here: refused outright rather than waved through
BLOCKED_EXT = {".pdf", ".doc", ".docx", ".odt", ".rtf", ".pages", ".xls", ".xlsx", ".zip"}

EMAIL = re.compile(r"[\w.+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{1,63})+")
# Domains reserved for documentation (RFC 2606) can never be anyone's real address
ALLOWED_EMAIL = re.compile(r"@(?:(?:[\w-]+\.)*example\.(?:com|org|net)|(?:[\w-]+\.)*(?:example|test|invalid)"
                           r"|users\.noreply\.github\.com)$", re.I)
# +44 7..., +44 (0)7..., 0044 7..., 07... with the remaining nine digits grouped any way
UK_MOBILE = re.compile(r"(?:(?:\+|\b00)44[\s-]?(?:\(0\)[\s-]?)?|\b0)7(?:[\s-]?\d){9}\b")
UK_POSTCODE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b")


def _is_drama_number(number: str) -> bool:
    """Ofcom reserves 07700 900000 to 900999 for fiction, so those numbers can never be anyone's."""
    digits = re.sub(r"\D", "", number)
    digits = digits[2:] if digits.startswith("00") else digits
    digits = "0" + digits[2:].removeprefix("0") if digits.startswith("44") else digits
    return digits.startswith("07700900")


def load_terms(path: Path = TERMS_FILE) -> list[str]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    return [t.strip() for t in lines if t.strip() and not t.lstrip().startswith("#")]


def _term_pattern(term: str) -> re.Pattern:
    """Whitespace, "_" or "-" (or nothing) between words, and "_" counts as a boundary, so "Jo Bloggs" is found in
    "Jo\\nBloggs", "jo_bloggs_cv.md" and "jo-bloggs"."""
    words = r"[\s_-]*".join(map(re.escape, term.split()))
    return re.compile(r"(?<![^\W_])" + words + r"(?![^\W_])", re.I)


def _split_camel_case(text: str) -> str:
    # "JoBloggsCV" -> "Jo Bloggs CV" (same length per line, so line numbers stay right)
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)


def find_problems(text: str, terms: list[str]) -> list[tuple[int, str]]:
    """(offset, message) for every problem in the text, scanning it whole."""
    problems = []
    for m in EMAIL.finditer(text):
        if not ALLOWED_EMAIL.search(m[0]):
            problems.append((m.start(), f"email address {m[0]!r}"))
    for m in UK_MOBILE.finditer(text):
        if not _is_drama_number(m[0]):
            problems.append((m.start(), f"UK mobile number {m[0]!r}"))
    for m in UK_POSTCODE.finditer(text):
        problems.append((m.start(), f"UK postcode {m[0]!r}"))
    camel = _split_camel_case(text)
    line_starts = [0] + [i + 1 for i, c in enumerate(text) if c == "\n"]
    for term in terms:
        pattern = _term_pattern(term)
        hits = [m.start() for m in pattern.finditer(text)]
        if not hits:
            # Found only once CamelCase is split: report it at the start of the same line in the original text
            hits = [line_starts[camel.count("\n", 0, m.start())] for m in pattern.finditer(camel)]
        problems += [(offset, f"private term {term!r}") for offset in hits]
    return sorted(problems)


def blocked_document(path: str) -> bool:
    return Path(path).suffix.lower() in BLOCKED_EXT


def scan_text(text: str, terms: list[str]) -> list[str]:
    """Return one message per problem found in the text."""
    return [message for _, message in find_problems(text, terms)]


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                          check=True).stdout


def _paths(output: str) -> list[str]:
    # -z output: NUL-separated and unquoted, so names with accents or spaces arrive intact
    return [p for p in output.split("\0") if p]


def candidate_files(staged: bool) -> list[str]:
    if staged:
        return _paths(_git("diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR"))
    return _paths(_git("ls-files", "-z", "--cached", "--others", "--exclude-standard"))


def terms_file_committed(staged: bool) -> bool:
    """The private-terms list must never be tracked or staged: that would publish the very list it protects."""
    if staged and TERMS_NAME in candidate_files(staged=True):
        return True
    return bool(_paths(_git("ls-files", "-z", "--cached", "--", TERMS_NAME)))


def read_candidate(path: str, staged: bool) -> str | None:
    if Path(path).suffix.lower() in BINARY_EXT:
        return None
    if staged:
        data = subprocess.run(["git", "show", f":{path}"], cwd=ROOT, capture_output=True, check=True).stdout
    else:
        full = ROOT / path
        if not full.is_file():
            return None
        data = full.read_bytes()
    return data.decode("utf-8", errors="replace")


def check_author_email() -> str | None:
    """Both identities git will write into the commit, including any GIT_AUTHOR_EMAIL/GIT_COMMITTER_EMAIL."""
    if os.environ.get("ALLOW_AUTHOR_EMAIL") == "1":
        return None
    for who in ("GIT_AUTHOR_IDENT", "GIT_COMMITTER_IDENT"):
        ident = _git("var", who)
        email = ident[ident.find("<") + 1:ident.find(">")] if "<" in ident else ""
        if email and not ALLOWED_EMAIL.search(email):
            return (f"commit {who.split('_')[1].lower()} email {email!r} would be published with every commit. Set a "
                    "private one for this repo: git config user.email <id>+<username>@users.noreply.github.com "
                    "(or set ALLOW_AUTHOR_EMAIL=1 to publish it on purpose)")
    return None


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Fail if personal data is about to enter this repo.")
    ap.add_argument("--staged", action="store_true", help="check staged changes and the author email")
    ap.add_argument("--message", type=Path, help="check a commit message file instead of files")
    args = ap.parse_args()

    terms = load_terms()
    findings = []
    if args.message:
        text = args.message.read_text(encoding="utf-8", errors="replace")
        findings += [f"commit message: {p}" for p in scan_text(text, terms)]
    else:
        if terms_file_committed(args.staged):
            findings.append(f"{TERMS_NAME} is tracked or staged: it must never be committed "
                            f"(git rm --cached {TERMS_NAME})")
        for path in candidate_files(args.staged):
            if path == TERMS_NAME:
                continue
            # The path itself can leak, e.g. a file named after a person or an employer
            findings += [f"{path}: (file name) {p}" for p in scan_text(path, terms)]
            if blocked_document(path):
                findings.append(f"{path}: documents ({', '.join(sorted(BLOCKED_EXT))}) are never committed here: "
                                "they can hold a whole CV and cannot be scanned")
                continue
            text = read_candidate(path, args.staged)
            if text is None:
                continue
            findings += [f"{path}:{text.count(chr(10), 0, offset) + 1}: {p}"
                         for offset, p in find_problems(text, terms)]
        if args.staged:
            problem = check_author_email()
            if problem:
                findings.append(problem)

    if not terms:
        print("note: no .private-terms file, so only the generic patterns were checked")
    if findings:
        print(f"Personal data check FAILED ({len(findings)}):")
        for f in findings:
            print(f"  {f}")
        return 1
    print("Personal data check passed.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # exit 2, never 1: the hooks read 1 as "personal data found"
        print(f"Personal data check could not run: {type(e).__name__}: {e}")
        sys.exit(2)
