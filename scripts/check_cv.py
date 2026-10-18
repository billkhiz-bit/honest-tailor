"""Trace every checkable claim in a tailored CV back to the user's own sources.

A tailored CV may reword and reorder, but its facts must come from the sources. This script finds the facts
that can be checked mechanically and reports any that the sources do not contain:

- numbers: counts, money, percentages and years ("£30,000", "~250", "10+", "8.5%", "2021")
- names: capitalised terms such as employers, tools and qualifications ("Kubernetes", "PhD", "Contoso", "A*")
- headers: each "**Employer** - *dates*" line and the *role* line under it must appear in the sources (any dash
  style), and every line that opens with a bold name (a project, an employer in another layout) must use a name
  from the sources
- contact details: email addresses, phone numbers (+44 and 0 treated alike) and link targets must exist in the
  sources, so a CV cannot quietly point somewhere else

It cannot judge meaning. "Assisted with" reworded as "led" passes, and so does a real number moved onto the
wrong claim. The skill re-reads every bullet against its source line for those, and `benchmark/` measures
what this script catches and what it misses.

A source section whose `## ` heading contains "unconfirmed" is not a source: career-facts.md parks facts
there until the user confirms them. The CV's `# Name` line is compared with the first source's.

Usage:
  python check_cv.py <cv.md> --sources <master-cv.md> [<career-facts.md> ...] [--allow TERM ...]
Exit code: 0 when every claim traces to a source, 1 when something does not, 2 when the check could not run.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

# ---------------------------------------------------------------- numbers

_AT_LEAST = r"over|more than|above|at least"
_APPROX = r"around|about|approximately|roughly|circa|c\."
_AT_MOST = r"up to|under|fewer than|less than|below"
NUMBER = re.compile(
    rf"(?:\b(?P<word>{_AT_LEAST}|{_APPROX}|{_AT_MOST})\s+|(?P<tilde>~)\s?)?"
    r"(?P<cur>[£$€])?"
    r"(?<![\w.,])(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?P<scale>\s?(?:k|m|bn|million|billion)\b)?"
    r"(?P<pct>\s?%)?"
    r"(?P<plus>\+)?",
    re.IGNORECASE,
)
SCALE = {"k": 1e3, "m": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9}
CURRENCIES = {"£", "$", "€"}
APPROX_TOLERANCE = 0.10   # "about X" must be within 10% of a source number
HEDGE_RANGE = 1.5         # "over X" needs a source between X and 1.5X ("up to X": between X/1.5 and X)


@dataclass(frozen=True)
class Num:
    value: float
    unit: str        # "£", "$", "€", "%", "year", or "" for a plain count
    qualifier: str   # "" (exact), "at_least" (over, 10+), "approx" (~, around) or "at_most" (up to, under)
    text: str        # as written, for reports


def _qualifier(m: re.Match) -> str:
    word = (m["word"] or "").lower()
    if m["tilde"] or re.fullmatch(_APPROX, word):
        return "approx"
    if m["plus"] or re.fullmatch(_AT_LEAST, word):
        return "at_least"
    if re.fullmatch(_AT_MOST, word):
        return "at_most"
    return ""


def parse_numbers(text: str) -> list[Num]:
    """Every number in the text, normalised: "£30k" and "£30,000" both become 30000.0 with unit "£"."""
    nums = []
    for m in NUMBER.finditer(text):
        value = float(m["num"].replace(",", ""))
        scale = (m["scale"] or "").strip().lower()
        value *= SCALE.get(scale, 1)
        qualifier = _qualifier(m)
        if m["pct"]:
            unit = "%"
        elif m["cur"]:
            unit = m["cur"]
        elif (not scale and not qualifier and "," not in m["num"] and "." not in m["num"]
              and 1950 <= value <= 2099):
            unit = "year"
        else:
            unit = ""
        nums.append(Num(value, unit, qualifier, m[0].strip()))
    return nums


def compatible(claim: Num, source: Num) -> bool:
    """Can this source number back this claim at all? Units must agree. A plain count may drop a currency, and a
    year-shaped claim ("2000 customers") may be a plain count; a plain count may never borrow a year."""
    if claim.unit == source.unit:
        return True
    if claim.unit == "year":
        return source.unit == ""
    return claim.unit == "" and source.unit in CURRENCIES


def value_supported(claim: Num, candidates: list[Num]) -> bool:
    """Decide whether a number on the CV is backed by a number in the sources.

    `claim` is one number from the tailored CV, already normalised: "£30k" and "£30,000" both arrive as
    value 30000.0 with unit "£". `claim.qualifier` says how it was hedged: "" (exact), "at_least"
    ("over 1,000", "1,000+"), "approx" ("~1,000", "around 1,000") or "at_most" ("up to 1,000").
    `candidates` are the source numbers whose unit is compatible with the claim, each with its own qualifier.

    Return True when the claim is honest given at least one candidate. This is the policy that decides how
    strict the whole checker is: benchmark/README.md lists the cases it moves.

    A hedge must point the honest way, by a bounded amount: an exact claim needs an exact (or "at least") source
    of the same value, so a hedge in the source is never dropped; "over X" may understate a source by up to a
    third; "about X" must be within 10%; "up to X" may overstate a ceiling by the same bounded margin.
    """
    def same(a: float, b: float) -> bool:
        return abs(a - b) <= 1e-9 * max(1.0, abs(b))

    c = claim.value
    for source in candidates:
        s = source.value
        if claim.qualifier == "" and source.qualifier in ("", "at_least") and same(c, s):
            return True
        if claim.qualifier == "approx" and abs(c - s) <= APPROX_TOLERANCE * abs(s):
            return True
        if claim.qualifier == "at_least" and source.qualifier != "at_most" and c <= s <= c * HEDGE_RANGE:
            return True
        if claim.qualifier == "at_most" and source.qualifier != "at_least" and c / HEDGE_RANGE <= s <= c:
            return True
    return False


# ---------------------------------------------------------------- names

TOKEN = re.compile(r"[^\W\d_][\w&+#.'*]*[\w+#*]|[^\W\d_]")
SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")
# A full stop after one of these does not end a sentence, so the next word is still checked
ABBREVIATIONS = {"e.g", "eg", "i.e", "ie", "incl", "inc", "etc", "vs", "c", "ca", "approx", "no", "esp", "dept",
                 "est", "ltd", "co", "corp", "st", "dr", "mr", "mrs", "ms"}


def _norm(token: str) -> str:
    token = token.lower().replace("’", "'")
    return token[:-2] if token.endswith("'s") else token.rstrip("'")


def _in_vocabulary(token: str, vocabulary: set[str]) -> bool:
    n = _norm(token)
    return n in vocabulary or (n.endswith("s") and n[:-1] in vocabulary) or n + "s" in vocabulary


def _sentences(text: str) -> list[str]:
    parts, start = [], 0
    for m in SENTENCE_BREAK.finditer(text):
        words = text[start:m.start()].split()
        if words and words[-1].rstrip(".").lower() in ABBREVIATIONS:
            continue
        parts.append(text[start:m.start()])
        start = m.end()
    parts.append(text[start:])
    return parts


# Verbs that open CV bullets, as base forms: every inflection is generated from them (plan: plans, planned,
# planning), so a name that merely ends in -ed or -ing ("Spring", "Boeing") is never mistaken for a verb.
BASE_VERBS = """
accelerate achieve act adapt add administer advise align analyse analyze apply architect arrange assess assist audit
author automate boost build calculate champion chair coach collaborate collect communicate compile complete conduct
configure consolidate contribute convert coordinate create cut debug define deliver deploy design detect develop
devise direct document double draft drive earn edit eliminate enable engineer enhance ensure establish evaluate
examine execute expand extend extract facilitate feed find forecast gather generate grow guide halve handle help hold
identify implement improve include increase initiate install integrate interview introduce investigate keep launch
lead liaise maintain make manage map measure mentor merge migrate model modernise modernize monitor negotiate optimise
optimize organise organize overhaul oversee own partner perform pilot plan prepare present process produce program
programme prototype provide publish query raise rebuild record recruit redesign reduce refactor register release
replace replan report research resolve restructure review revise run save scale schedule secure select sell serve
set ship simplify solve speak spearhead specify spend standardise standardize steer streamline strengthen structure
supervise support take teach test track train transform translate trim tune undertake unify update upgrade use
validate verify win work write begin bring give meet seek
acquire advocate allocate answer approve assemble attend budget consult enter file fund invest join learn lower
market obtain operate participate pass pitch price promote qualify reconcile represent shape source study submit
triple visit volunteer
""".split()
# Past tenses that the rules below cannot generate
IRREGULAR = set("""
built drove fed found grew held kept led made oversaw ran rebuilt sold spoke spent took taught undertook won wrote
began brought gave met sought set cut
""".split())
# Openers that are not verbs but never name anything
OPENERS = {"successfully", "independently", "jointly", "personally", "consistently", "regularly", "proactively",
           "directly", "also", "currently", "previously", "together", "responsible", "accountable"}
# Bare forms that also serve as job titles: "Lead data engineer" or "Partner at..." is a claim, so it is checked;
# "Leads", "Led" and "Partnered" are still verbs
TITLE_LIKE = {"lead", "partner", "chair", "champion", "pilot", "head", "director", "manager", "principal"}
PREFIXES = {"co", "re", "pre", "self", "cross", "multi"}  # skipped only when a hyphen follows: "Co-developed"


def _verb_forms(base: str) -> set[str]:
    forms = {base, base + "s", base + "ed", base + "ing"}
    if base.endswith("e"):
        forms |= {base + "d", base[:-1] + "ing"}
    if base.endswith(("s", "sh", "ch", "x", "z", "o")):
        forms.add(base + "es")
    if base.endswith("y") and base[-2] not in "aeiou":
        forms |= {base[:-1] + "ies", base[:-1] + "ied"}
    if re.fullmatch(r"[a-z]*[^aeiou][aeiou][bdgklmnprt]", base) and len(base) <= 6:
        forms |= {base + base[-1] + "ed", base + base[-1] + "ing"}       # plan: planned, planning
    return forms


VERB_FORMS = (set().union(*map(_verb_forms, BASE_VERBS)) | IRREGULAR | OPENERS) - TITLE_LIKE


def _looks_like_verb(token: str) -> bool:
    return token.lower() in VERB_FORMS


def name_tokens(text: str, skip_sentence_start: bool) -> list[str]:
    """Capitalised terms worth checking. A sentence's first word is skipped only when it is a known verb form or
    opening adverb ("Built", "Leads", "Successfully"), since bullets open with verbs; any other opener
    ("Kubernetes clusters...", "First Class Honours", "Lead engineer") is checked like the rest."""
    found = []
    for sentence in _sentences(text):
        opener = True
        for m in TOKEN.finditer(sentence):
            token, first, opener = m[0], opener, False
            if first and token.lower() in PREFIXES and sentence[m.end():m.end() + 1] == "-":
                opener = True  # "Co-developed": the word after the hyphen is the real opener
                continue
            if not any(c.isupper() for c in token):
                continue
            if (skip_sentence_start and first and token[0].isupper() and token[1:] == token[1:].lower()
                    and _looks_like_verb(token)):
                continue
            found.append(token)
    return found


# ---------------------------------------------------------------- Markdown

LINK = re.compile(r"\[([^\]]{1,300})\]\(([^)\s]{1,2000})\)")
DATED_HEADER = re.compile(r"^\*\*(.+?)\*\*\s+[-–—]\s+\*(.+?)\*\s*$")
LABEL_LINE = re.compile(r"^\*\*([^*]+?:)\*\*\s*(.*)$")
BOLD_LEAD = re.compile(r"^\*\*([^*]+?)\*\*(.*)$")          # **Name** followed by anything: a project or employer
ROLE_LEAD = re.compile(r"^\*(?!\*)([^*]+)\*(.*)$")          # *Role* followed by anything (e.g. "– London")
EMPHASIS = re.compile(r"(?<![\w*])(\*\*|\*)(?=\S)(.+?)(?<=\S)\1(?![\w*])")
YEAR = re.compile(r"\b(?:19[5-9]\d|20\d\d)\b")
UNCONFIRMED = re.compile(r"unconfirmed", re.I)


def plain_text(md: str) -> str:
    """Markdown to the words a reader sees: link text kept, URLs and emphasis markers dropped. An asterisk that is
    not emphasis (a grade such as "A*") stays."""
    text, previous = LINK.sub(r"\1", md).replace("`", ""), None
    while previous != text:
        previous, text = text, EMPHASIS.sub(r"\2", text)
    return text


def _squash(text: str) -> str:
    return " ".join(text.split())


def _canon(text: str) -> str:
    """Whitespace and dash style do not count as a change: "-", "–" and "—" compare equal."""
    return _squash(text).replace("–", "-").replace("—", "-")


def _whole_italic(line: str) -> bool:
    return len(line) > 2 and line.startswith("*") and line.endswith("*") and not line.startswith("**")


def _role_texts(role_content: str) -> set[str]:
    """A role as written ("Operations Analyst – London") and its title alone ("Operations Analyst")."""
    canon = _canon(role_content)
    return {canon, re.split(r"\s+-\s+|,\s*", canon)[0]}


# ---------------------------------------------------------------- contact details

CONTACT_EMAIL = re.compile(r"[\w.+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{1,63})+")
PHONE = re.compile(r"(?<![\w+])(?:\+\d{1,3}[\s-]?(?:\(0\)[\s-]?)?|0)\d(?:[\s-]?\d){6,13}(?!\w)")
BARE_HOST = re.compile(r"(?<![\w@./-])((?:[a-z0-9-]{1,63}\.)+[a-z]{2,24})(?:/\S*)?", re.I)


def _phone_key(text: str) -> str:
    digits = re.sub(r"\D", "", text)
    if digits.startswith("440"):    # +44 (0)7700 ...
        return digits[2:]
    if digits.startswith("44"):     # +44 7700 ...
        return "0" + digits[2:]
    return digits


# A website as people write one on a contact line: lower case, with a common top-level domain. "Node.js" and
# "ASP.NET" are not websites, so a summary that mentions them is still checked as a summary.
CONTACT_HOST = re.compile(r"(?<![\w@./-])(?:[a-z0-9-]+\.)+(?:com|org|net|io|dev|ai|app|co|uk|me|info|biz|edu|gov|xyz"
                          r"|tech|site|page|eu|de|fr|nl|ie|ae|qa|sa|in|ca|au|us)(?:/\S*)?(?![\w.])")


def _target_atom(target: str) -> str:
    """A link target, normalised but keeping its path, so github.com/sam and github.com/someone-else differ."""
    if target.lower().startswith("mailto:"):
        return "email:" + target[7:].lower()
    try:
        parts = urlsplit(target if "://" in target else "https://" + target)
        host = (parts.hostname or "").lower()
    except ValueError:
        return "url:" + target.lower()
    host = host[4:] if host.startswith("www.") else host
    query = "?" + parts.query.lower() if parts.query else ""
    return "url:" + host + parts.path.rstrip("/").lower() + query


def contact_atoms(text: str, bare_hosts: bool) -> set[str]:
    """Emails, phone numbers and link targets in a line, normalised ("phone:07700900123", "url:example.com/sam").
    Bare web addresses ("example.com/sam") count only where asked, i.e. on contact lines: in body text "Node.js" is
    a library, not a website."""
    atoms = {_target_atom(m[2]) for m in LINK.finditer(text)}
    visible = LINK.sub(r"\1", text)
    atoms |= {"email:" + m[0].lower() for m in CONTACT_EMAIL.finditer(visible)}
    without_emails = CONTACT_EMAIL.sub(" ", visible)
    atoms |= {"phone:" + _phone_key(m[0]) for m in PHONE.finditer(without_emails)}
    if bare_hosts:
        atoms |= {_target_atom(m[0]) for m in BARE_HOST.finditer(without_emails)}
    return atoms


def _is_contact_line(line: str) -> bool:
    """In the header zone: a line of contact details (a "•" list, an email, a phone number or a website), as
    opposed to the summary, which is checked like a bullet."""
    visible = LINK.sub(r"\1", line)
    without_emails = CONTACT_EMAIL.sub(" ", visible)
    return ("•" in line or bool(CONTACT_EMAIL.search(visible)) or bool(PHONE.search(without_emails))
            or bool(CONTACT_HOST.search(without_emails)))


def confirmed_lines(md_text: str) -> list[str]:
    """The lines of a source, minus any section whose heading marks it unconfirmed."""
    keep, skipping = [], False
    for raw in md_text.splitlines():
        if raw.startswith("## "):
            skipping = bool(UNCONFIRMED.search(raw))
        if not skipping:
            keep.append(raw)
    return keep


# ---------------------------------------------------------------- sources

@dataclass
class Sources:
    numbers: list[Num] = field(default_factory=list)
    vocabulary: set[str] = field(default_factory=set)
    headers: set[str] = field(default_factory=set)      # canonical "**Employer** - *dates*" lines
    roles: set[str] = field(default_factory=set)        # canonical role texts, with and without the location
    bold_names: set[str] = field(default_factory=set)   # lower-case names that open a line in bold
    contacts: set[str] = field(default_factory=set)
    name_line: str | None = None


def sources_from_texts(texts: list[str]) -> Sources:
    src = Sources()
    for index, text in enumerate(texts):
        previous_was_header = False
        lines = confirmed_lines(text)
        first = next((l.strip() for l in lines if l.strip()), "")
        in_header_zone = first.startswith("# ")
        for raw in lines:
            line = raw.strip()
            if not line:
                continue
            src.contacts |= contact_atoms(line, bare_hosts=True)
            if line.startswith("# ") and index == 0 and src.name_line is None:
                src.name_line = _squash(line)
            if line.startswith("## "):
                in_header_zone = False
            if in_header_zone and not line.startswith("# ") and _is_contact_line(line):
                # A contact line: its words help (a city), but phone digits must not back any claim
                src.vocabulary |= {_norm(t) for t in TOKEN.findall(plain_text(line))}
                continue
            lead = BOLD_LEAD.match(line)
            header_like = bool(DATED_HEADER.match(line)) or bool(
                lead and not LABEL_LINE.match(line) and YEAR.search(lead[2]))
            if DATED_HEADER.match(line):
                src.headers.add(_canon(line))
            elif previous_was_header and ROLE_LEAD.match(line):
                src.roles |= _role_texts(plain_text(line))
            previous_was_header = header_like  # the same rule check_cv uses, so roles under any layout are kept
            bold = re.match(r"^(?:- )?\*\*([^*]+?)\*\*", line)
            if bold:
                src.bold_names.add(_canon(bold[1]).rstrip(":").lower())
            visible = plain_text(line)
            src.numbers += parse_numbers(visible)
            src.vocabulary |= {_norm(t) for t in TOKEN.findall(visible)}
    return src


def load_sources(paths: list[Path]) -> Sources:
    return sources_from_texts([p.read_text(encoding="utf-8-sig") for p in paths])


# ---------------------------------------------------------------- checking

@dataclass(frozen=True)
class Finding:
    line_no: int
    kind: str    # "number", "name", "header", "role", "project", "contact" or "name-line"
    term: str
    detail: str


def _nearest(claim: Num, sources: Sources, limit: int = 3) -> str:
    same = sorted({s.text for s in sources.numbers if compatible(claim, s)},
                  key=lambda t: abs(parse_numbers(t)[0].value - claim.value) if parse_numbers(t) else 0)
    return ", ".join(same[:limit]) if same else "none with this unit"


def _check_names(text: str, n: int, sources: Sources, allow: set[str], skip_sentence_start: bool):
    for token in name_tokens(plain_text(text), skip_sentence_start):
        if _norm(token) in allow or _in_vocabulary(token, sources.vocabulary):
            continue
        yield Finding(n, "name", token, "not in the sources")


def _check_text(text: str, n: int, sources: Sources, allow: set[str], skip_sentence_start: bool):
    visible = plain_text(text)
    for claim in parse_numbers(visible):
        if claim.text.lower() in allow:
            continue
        # A plain count may match a year-shaped source number ("2000 customers") only when the value is identical
        candidates = [s for s in sources.numbers if compatible(claim, s)
                      or (claim.unit == "" and s.unit == "year" and s.value == claim.value)]
        if not value_supported(claim, candidates):
            yield Finding(n, "number", claim.text, f"no source number backs it (nearest: {_nearest(claim, sources)})")
    yield from _check_names(text, n, sources, allow, skip_sentence_start)


def check_cv(md_text: str, sources: Sources, allow: set[str] | frozenset = frozenset()) -> list[Finding]:
    """Every claim in the CV that cannot be traced to the sources. A CV starting with "# Name" has a header
    zone (name, contact lines, summary) before its first section; a fragment without one is all body."""
    allow = {a.lower() for a in allow}
    findings: list[Finding] = []
    lines = md_text.splitlines()
    first = next((l.strip() for l in lines if l.strip()), "")
    in_header_zone = first.startswith("# ")
    previous_was_header = False
    for n, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line:
            continue
        was_header, previous_was_header = previous_was_header, False
        if line.startswith("# "):
            if sources.name_line and _squash(line) != sources.name_line and _squash(line).lower() not in allow:
                findings.append(Finding(n, "name-line", line, f"the sources say {sources.name_line!r}"))
            continue
        if line.startswith("## "):
            in_header_zone = False
            continue
        is_contact_line = in_header_zone and _is_contact_line(line)
        for atom in sorted(contact_atoms(line, bare_hosts=is_contact_line) - sources.contacts):
            if atom.split(":", 1)[1] not in allow:
                findings.append(Finding(n, "contact", atom.split(":", 1)[1],
                                        f"this {atom.split(':', 1)[0]} is not in the sources"))
        if is_contact_line:
            continue  # only its emails, phones and links are checked: contact formatting may change freely
        if in_header_zone:  # the summary, in whatever formatting: checked like a bullet
            findings += _check_text(line, n, sources, allow, skip_sentence_start=True)
            continue
        if DATED_HEADER.match(line):
            previous_was_header = True
            if _canon(line) not in sources.headers and _canon(line).lower() not in allow:
                findings.append(Finding(n, "header", line, "no header in the sources matches it"))
            continue
        role = ROLE_LEAD.match(line) if was_header else None
        if role:
            if not ({_canon(role[1]), _canon(plain_text(line))} & sources.roles) and _canon(line).lower() not in allow:
                findings.append(Finding(n, "role", line, "no role line in the sources matches it"))
            findings += _check_text(role[2], n, sources, allow, skip_sentence_start=False)
            continue
        m = LABEL_LINE.match(line)
        if m:  # a skills line: the label is free wording, but tools listed inside it are checked, as is every item
            for listed in re.findall(r"\(([^)]*)\)", m[1]):
                findings += _check_text(listed, n, sources, allow, skip_sentence_start=False)
            findings += _check_text(m[2], n, sources, allow, skip_sentence_start=False)
            continue
        m = BOLD_LEAD.match(line)
        if m:  # a project, or an employer in a layout other than "**Employer** - *dates*"
            name, rest = _canon(m[1]).lower(), m[2]
            dated = bool(YEAR.search(rest))
            previous_was_header = dated
            if name not in sources.bold_names and name not in allow:
                findings.append(Finding(n, "header" if dated else "project", m[1],
                                        "no entry in the sources has this name"))
            findings += _check_text(rest, n, sources, allow, skip_sentence_start=False)
            continue
        text = line[2:] if line.startswith("- ") else line
        bold_lead = re.match(r"^\*\*([^*]+?)\*\*", text)
        if bold_lead:  # "- **Initech**: led ..." names something, so its first word is not a skippable verb
            findings += _check_names(bold_lead[1], n, sources, allow, skip_sentence_start=False)
        findings += _check_text(text, n, sources, allow, skip_sentence_start=True)
    unique, seen = [], set()
    for f in findings:
        if (f.line_no, f.kind, f.term) not in seen:
            seen.add((f.line_no, f.kind, f.term))
            unique.append(f)
    return unique


# ---------------------------------------------------------------- main

def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Trace every checkable claim in a tailored CV to its sources.")
    ap.add_argument("cv", type=Path, help="the tailored CV (.md)")
    ap.add_argument("--sources", type=Path, nargs="+", required=True,
                    help="the master CV first, then any facts files (sections marked unconfirmed are ignored)")
    ap.add_argument("--allow", action="append", default=[],
                    help="a term to accept as a fair rewording (repeatable); record why in notes.md")
    args = ap.parse_args()

    try:
        sources = load_sources(args.sources)
        cv_text = args.cv.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as e:
        # Exit 2, never 1: a file that cannot be read must not look like a list of findings
        print(f"check_cv could not run: {e}. Check the paths, and that every file is saved as UTF-8.")
        return 2
    findings = check_cv(cv_text, sources, set(args.allow))
    if not findings:
        print(f"check_cv: every checkable claim in {args.cv.name} traces to the sources.")
        return 0
    print(f"check_cv: {len(findings)} claim(s) in {args.cv.name} could not be traced to the sources\n")
    for f in findings:
        print(f"  line {f.line_no:<4} {f.kind:<9} {f.term!r}  {f.detail}")
    print("\nFix each one (restore the source's wording, or cut the claim). If one is a fair rewording, re-run "
          'with --allow "<term>" and record in notes.md the source line that supports it.')
    return 1


if __name__ == "__main__":
    sys.exit(main())
